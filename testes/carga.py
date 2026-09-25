"""
Quantas conversas ao mesmo tempo isto aguenta?

A resposta tem duas partes, e elas tem tetos MUITO diferentes:

  1. o trabalho da API (memoria + busca BM25) — cabe em milissegundos, e nao depende de
     GPU nenhuma. O numero medido aqui vale para o seu servidor tambem.
  2. o modelo — e o gargalo, sempre. E o numero dele depende da SUA maquina: um 14b em
     CPU nao se parece em nada com o mesmo 14b numa GPU.

Por isso esta bancada mede as duas separadas.

    .venv/bin/python testes/carga.py                 # so a API (rapido)
    .venv/bin/python testes/carga.py --com-modelo    # inclui o modelo de verdade
"""
import os
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

os.environ["MEMORIA_PASTA"] = "/tmp/carga-atendente"
shutil.rmtree("/tmp/carga-atendente", ignore_errors=True)

from comum import Prova  # noqa: E402
from atendente import acervo, busca, config, modelo  # noqa: E402


def arg(nome, padrao):
    return sys.argv[sys.argv.index("--" + nome) + 1] if ("--" + nome) in sys.argv else padrao


COM_MODELO = "--com-modelo" in sys.argv
if COM_MODELO:
    os.environ["MODELO_NOME"] = arg("modelo", os.environ.get(
        "MODELO_NOME", "qwen2.5:14b"))
    os.environ["MODELO_URL"] = arg("url", os.environ.get("MODELO_URL", "http://127.0.0.1:11434"))
    config.recarregar()
PAGINAS = int(sys.argv[sys.argv.index("--paginas") + 1]) if "--paginas" in sys.argv else 600

# ---------------------------------------------------------------- um acervo de verdade
# Tres espacos, 200 paginas cada, cada pagina com quatro secoes. E mais ou menos o que
# tres times de porte medio tem no Confluence.
def acervo_grande(quantas: int) -> list[dict]:
    espacos = ["SRE", "PAGAMENTOS", "CATALOGO"]
    docs = []
    for i in range(quantas):
        espaco = espacos[i % len(espacos)]
        docs.append({
            "id": f"c:{i}", "titulo": f"Servico {espaco.lower()}-{i:03d}",
            "fonte": f"https://wiki/x/{i}", "espaco": espaco,
            "texto": f"""# Visao geral
O servico {espaco.lower()}-{i:03d} atende o dominio de numero {i} e roda no cluster prd-{espaco.lower()}.

# Enderecos
IP de producao 10.{i % 250}.{(i * 3) % 250}.{(i * 7) % 250}. Homologacao 10.90.{i % 250}.{i % 99}.
Dominio servico{i}.interno.local.

# Plantao e dono
Squad numero {i % 20}. Em crise acione o canal do time.

# Dependencias
Banco pg-{i:03d}, fila rabbit-{i:03d}, cache redis-{i:03d}.
"""})
    return docs


print(f"montando acervo de {PAGINAS} paginas...")
comecou = time.time()
indice = busca.montar(acervo_grande(PAGINAS))
segundos_indexando = time.time() - comecou
print(f"  {indice['documentos']} documentos · {indice['quantos']} pedacos · "
      f"{segundos_indexando:.1f}s para indexar\n")
acervo.usar_este_indice(indice)

PERGUNTAS = [
    "qual o ip de producao do servico sre-042?",
    "quem e o dono do servico pagamentos-101?",
    "qual a fila do servico catalogo-200?",
    "meu pod ta em CrashLoopBackOff, o que eu olho?",
    "qual o dominio do servico sre-300?",
]

p = Prova("carga")

# ---------------------------------------------------------------- 1. a busca sozinha
p.secao("1. uma busca no acervo inteiro")
tempos = []
for q in PERGUNTAS * 20:
    t = time.time()
    busca.fatos_para_o_modelo(indice, q, espaco_de_casa="SRE")
    tempos.append((time.time() - t) * 1000)
mediana = statistics.median(tempos)
p95 = sorted(tempos)[int(len(tempos) * 0.95)]
print(f"   mediana {mediana:.1f}ms · p95 {p95:.1f}ms · pior {max(tempos):.1f}ms")
p.confere("a busca cabe em milissegundos", mediana < 100, f"{mediana:.1f}ms")

# ---------------------------------------------------------------- 2. a API sem o modelo
p.secao("\n2. a API inteira, com o modelo trocado por um duble instantaneo")
from fastapi.testclient import TestClient  # noqa: E402
import atendente.app as A  # noqa: E402

def modelo_instantaneo(tipo, fatos, cfg=None, bater=None):
    return modelo.RespostaDoModelo(True, dados="resposta de mentira", fichas_de_entrada=300)

de_verdade = A.modelo.perguntar
A.modelo.perguntar = modelo_instantaneo
cliente = TestClient(A.app)

def um_turno(n):
    t = time.time()
    r = cliente.post("/conversa", json={"conversa_id": f"carga-{n % 50}",
                                        "texto": PERGUNTAS[n % len(PERGUNTAS)]})
    return (time.time() - t) * 1000, r.status_code

for quantos in (1, 2, 4, 8, 16, 32):
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=quantos) as pool:
        saidas = list(pool.map(um_turno, range(quantos * 4)))
    total = time.time() - inicio
    temposr = [s[0] for s in saidas]
    ruins = [s for s in saidas if s[1] != 200]
    print(f"   {quantos:2d} ao mesmo tempo · {len(saidas):3d} turnos em {total:5.2f}s"
          f" · mediana {statistics.median(temposr):6.1f}ms"
          f" · p95 {sorted(temposr)[int(len(temposr) * .95)]:6.1f}ms"
          f" · {len(saidas) / total:5.1f} turnos/s"
          + (f"  · {len(ruins)} ERRO" if ruins else ""))
    p.confere(f"{quantos} ao mesmo tempo sem erro", not ruins, str(ruins[:2]))

A.modelo.perguntar = de_verdade

# ---------------------------------------------------------------- 3. com o modelo
if COM_MODELO:
    no_ar = modelo.esta_no_ar()
    if not no_ar["ok"]:
        print("\n   (o modelo nao esta no ar; pulando a parte 3)")
    else:
        p.secao(f"\n3. com o modelo de verdade ({config.atual().modelo_nome})")
        print("   ATENCAO: este numero e da MAQUINA ONDE ISTO RODA. Num servidor sem GPU")
        print("   ele vai ser varias vezes maior. Rode esta bancada LA para saber o seu.\n")
        for quantos in (1, 2, 4):
            inicio = time.time()
            with ThreadPoolExecutor(max_workers=quantos) as pool:
                saidas = list(pool.map(um_turno, range(quantos)))
            total = time.time() - inicio
            temposr = [s[0] for s in saidas]
            ruins = [s for s in saidas if s[1] != 200]
            print(f"   {quantos} ao mesmo tempo · pior resposta {max(temposr) / 1000:5.1f}s"
                  f" · mediana {statistics.median(temposr) / 1000:5.1f}s"
                  f" · total {total:5.1f}s"
                  + (f"  · {len(ruins)} ERRO" if ruins else ""))
            # erro aqui NAO pode passar calado: uma bancada que diz PASSOU com tres
            # chamadas falhadas e pior do que nao medir nada
            p.confere(f"{quantos} chamada(s) ao modelo sem erro", not ruins,
                      str(ruins[:2]))

shutil.rmtree("/tmp/carga-atendente", ignore_errors=True)
raise SystemExit(p.fim())
