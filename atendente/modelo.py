"""
A pergunta curta: o modelo sem memoria.

O modelo aqui e CONSULTOR. Ele responde uma pergunta fechada e esquece. Quem lembra e a
API, no fio.

Isto nao e preferencia de estilo, e o que torna o projeto possivel: o 14b esta na memoria
de um servidor SUSE sem GPU. Cada ficha de prompt e tempo de CPU. Mandar a conversa
inteira a cada turno faria o prompt crescer de 400 para 6.000 fichas em dez turnos —
medido no dragon_ia, onde um pedido simples gastou 22 chamadas e 94.407 fichas de entrada
antes desta mudanca.

Duas coisas concretas saem disso:

  1. A janela (num_ctx) e dimensionada POR CHAMADA ao tamanho do prompt mais folga. O
     padrao do Ollama e 2048: prompt maior que isso e cortado em silencio pelo servidor, e
     o que se perde e sempre o comeco — justamente os FATOS.
  2. Resposta fora da forma e cobrada UMA vez. Cobrar duas viraria conversa fiada.
"""
import json
import time
import urllib.error
import urllib.request

from . import config
from .perguntas import PERGUNTAS

# Janelas que valem a pena pedir. A PRIMEIRA e a base, e ela e onde quase toda chamada
# cai — de proposito.
#
# Medido contra o Ollama: chamadas seguidas com o MESMO num_ctx levam ~8s; quando o
# num_ctx muda, a mesma chamada leva 20 a 28s, porque o Ollama reconstroi o runner do
# modelo. Num servidor sem GPU isso e pior ainda: recarregar 9 GB de pesos nao e barato.
#
# Entao a janela nao acompanha o prompt de perto. Ela fica FIXA na base, e so sobe quando
# o prompt de verdade nao cabe. Janela maior custa memoria de KV, nao custa conta: o
# tempo de geracao depende das fichas que existem, nao do tamanho da janela reservada.
# Trocar de janela a cada turno era otimizar a coisa barata pagando com a cara.
JANELAS = [4096, 8192, 16384, 32768]
# Portugues em modelo qwen da por volta de 3 letras por ficha. A conta nao precisa ser
# exata — ela so precisa errar para CIMA.
LETRAS_POR_FICHA = 3.0


def estimar_fichas(texto: str) -> int:
    return int(len(str(texto or "")) / LETRAS_POR_FICHA) + 1


def janela_para(fichas_de_entrada: int, fichas_de_saida: int, teto: int) -> int:
    """A janela desta chamada: a base, ou o primeiro degrau em que o prompt caiba.

    Quase toda chamada devolve o mesmo numero, e e isso que se quer — janela que muda faz
    o Ollama reconstruir o runner."""
    preciso = fichas_de_entrada + fichas_de_saida + 256
    for j in JANELAS:
        if j > teto:
            break
        if j >= preciso:
            return j
    return min(teto, JANELAS[-1])


class RespostaDoModelo:
    def __init__(self, ok: bool, dados: str = "", porque: str = "", segundos: float = 0.0,
                 fichas_de_entrada: int = 0, janela: int = 0, tentativas: int = 0):
        self.ok = ok
        self.dados = dados
        self.porque = porque
        self.segundos = round(segundos, 2)
        self.fichas_de_entrada = fichas_de_entrada
        self.janela = janela
        self.tentativas = tentativas

    def como_dicionario(self) -> dict:
        return {"ok": self.ok, "porque": self.porque, "segundos": self.segundos,
                "fichas_de_entrada": self.fichas_de_entrada, "janela": self.janela,
                "tentativas": self.tentativas}


def _bater(url: str, corpo: dict, segundos: int) -> dict:
    pedido = urllib.request.Request(
        url, data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(pedido, timeout=segundos) as r:
        return json.loads(r.read().decode("utf-8"))


def esta_no_ar(cfg: config.Config | None = None) -> dict:
    """Quem esta atendendo e que modelos ele tem. Culpar o modelo por uma porta fechada e
    o pior recado possivel — a pessoa troca de modelo, e nao era isso."""
    c = cfg or config.atual()
    try:
        with urllib.request.urlopen(c.modelo_url.rstrip("/") + "/api/tags", timeout=10) as r:
            dados = json.loads(r.read().decode("utf-8"))
        nomes = [m.get("name", "") for m in dados.get("models", [])]
        return {"ok": True, "url": c.modelo_url, "modelos": nomes,
                "o_meu_esta_la": any(c.modelo_nome in n or n in c.modelo_nome for n in nomes)}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "url": c.modelo_url, "porque": str(e)[:200], "modelos": []}


def perguntar(tipo: str, fatos: dict, cfg: config.Config | None = None,
              bater=None) -> RespostaDoModelo:
    """Uma pergunta fechada, sem historico. `bater` entra por fora para o teste rodar sem
    subir modelo nenhum."""
    c = cfg or config.atual()
    forma = PERGUNTAS.get(tipo)
    if not forma:
        return RespostaDoModelo(False, porque=f"nao existe pergunta do tipo {tipo}")

    usuario = forma["monta"](fatos)
    sistema = forma["sistema"]
    fichas = estimar_fichas(sistema) + estimar_fichas(usuario)
    janela = janela_para(fichas, forma["fichas_de_saida"], c.janela_maxima)
    chamar = bater or _bater

    ultimo = ""
    for tentativa in (1, 2):
        pedido_usuario = usuario if tentativa == 1 else (
            usuario + "\n\nA resposta anterior veio fora de forma. Responda de novo, "
            "direto, sem repetir a pergunta.")
        corpo = {
            "model": c.modelo_nome,
            "stream": False,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": pedido_usuario}],
            "options": {
                "num_ctx": janela,
                "num_predict": forma["fichas_de_saida"],
                "temperature": forma["temperatura"],
            },
        }
        comecou = time.time()
        try:
            bruto = chamar(c.modelo_url.rstrip("/") + "/api/chat", corpo, c.segundos_de_espera)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return RespostaDoModelo(False, porque=f"o modelo nao respondeu: {str(e)[:160]}",
                                    segundos=time.time() - comecou,
                                    fichas_de_entrada=fichas, janela=janela,
                                    tentativas=tentativa)
        texto = ((bruto or {}).get("message") or {}).get("content", "")
        lido = forma["le"](texto)
        if forma["valida"](lido):
            return RespostaDoModelo(True, dados=lido, segundos=time.time() - comecou,
                                    fichas_de_entrada=fichas, janela=janela,
                                    tentativas=tentativa)
        ultimo = str(texto)[:160]
    return RespostaDoModelo(False, porque=f"o modelo respondeu fora da forma: {ultimo}",
                            fichas_de_entrada=fichas, janela=janela, tentativas=2)
