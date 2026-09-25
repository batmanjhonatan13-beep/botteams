"""
Uma conversa de verdade contra o modelo que estiver no ar.

Isto NAO e prova (nao entra no rodar_tudo): ela conversa com um modelo e demora. E uma
BANCADA — serve para medir a coisa que o projeto promete, que e esta: o prompt tem que
ficar do mesmo tamanho no decimo turno e no primeiro, e o assunto tem que sobreviver.

    .venv/bin/python testes/conversa_real.py
    .venv/bin/python testes/conversa_real.py --modelo qwen2.5-coder:14b-instruct-q4_K_M
"""
import os
import shutil
import sys

os.environ["MEMORIA_PASTA"] = "/tmp/bancada-atendente"
shutil.rmtree("/tmp/bancada-atendente", ignore_errors=True)

from comum import Prova  # noqa: E402  (precisa do sys.path)
from fastapi.testclient import TestClient  # noqa: E402
from atendente import acervo, busca, config  # noqa: E402

def arg(nome, padrao):
    i = sys.argv.index("--" + nome) if ("--" + nome) in sys.argv else -1
    return sys.argv[i + 1] if i >= 0 and i + 1 < len(sys.argv) else padrao

os.environ["MODELO_NOME"] = arg("modelo", "qwen2.5:14b")
os.environ["MODELO_URL"] = arg("url", "http://127.0.0.1:11434")
config.recarregar()

from atendente.app import app  # noqa: E402
from atendente import modelo  # noqa: E402

no_ar = modelo.esta_no_ar()
if not no_ar["ok"]:
    print("o modelo nao esta no ar:", no_ar.get("porque"))
    raise SystemExit(0)
print(f"modelo: {config.atual().modelo_nome} em {config.atual().modelo_url}\n")

acervo.recarregar()          # a pasta acervo/ de verdade
print("acervo:", acervo.retrato(), "\n")

cliente = TestClient(app)
p = Prova("conversa real")

# Uma conversa como a do canal: a pessoa nunca repete o sujeito depois do primeiro turno.
TURNOS = [
    ("o que e o produto falcao?",           ["pagamento"]),
    ("qual o ip de producao dele?",         ["10.20.30.40"]),
    ("e o de homologacao?",                 ["10.20.31.7"]),
    ("quem e o dono?",                      ["pagamentos"]),
    ("meu pod ta em CrashLoopBackOff, o que eu olho primeiro?", ["describe", "evento", "log"]),
    ("e se for falta de memoria?",          ["oom", "memoria", "limit"]),
    ("como eu escalo o deployment?",        ["scale", "replicas"]),
    ("em producao precisa de alguma coisa antes?", ["mudanca", "aprovac", "janela"]),
]

maior_prompt = 0
for i, (texto, esperadas) in enumerate(TURNOS, 1):
    r = cliente.post("/conversa", json={"conversa_id": "bancada", "texto": texto}).json()
    if "resposta" not in r:
        p.confere(f"[{i}] {texto}", False, str(r)[:120])
        continue
    resposta = r["resposta"].replace("\n", " ")
    medida = r.get("medida", {})
    maior_prompt = max(maior_prompt, medida.get("fichas_de_entrada", 0))
    bateu = any(e.lower() in resposta.lower() for e in esperadas)
    p.confere(f"[{i}] {texto}", bateu,
              f"{medida.get('fichas_de_entrada')}f {medida.get('segundos')}s "
              f"| colou: {r['colou'] or '-'} | {resposta[:90]}")

v = cliente.get("/conversa/bancada").json()
print()
p.secao("o que a API guardou")
p.confere("o assunto sobreviveu a conversa inteira", bool(v["assunto_atual"]), v["assunto_atual"])
p.confere("comprimiu o passado", bool(v["resumo_do_passado"]), v["resumo_do_passado"][:120])
p.confere("o prompt nunca estourou a janela pequena", maior_prompt < 2048,
          f"maior prompt: {maior_prompt} fichas")
p.confere("guardou so seis turnos", len(v["turnos"]) <= 6, str(len(v["turnos"])))

shutil.rmtree("/tmp/bancada-atendente", ignore_errors=True)
raise SystemExit(p.fim())
