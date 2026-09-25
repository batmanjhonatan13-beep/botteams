"""
A porta do Bot Framework: e por aqui que o Bot Framework Emulator conversa com o atendente.

O protocolo tem duas maos, e isso importa num 14b em CPU:

  1. o Emulator faz POST de uma "atividade" em /api/messages
  2. a API devolve 200 NA HORA e atende em segundo plano
  3. a resposta volta por OUTRO pedido: a API faz POST no `serviceUrl` que a atividade
     trouxe, em /v3/conversations/{conversa}/activities/{atividade}

Responder dentro do passo 1 faria o Emulator segurar a conexao aberta pelo tempo do
modelo, que aqui passa de minuto.

Esta porta NAO confere assinatura (JWT) e NAO pede token para responder: e o modo do
Emulator sem App ID e senha. Por isso ela so responde para um serviceUrl LOCAL — sem essa
trava, qualquer um mandaria a API fazer POST para onde quisesse. O Teams de verdade
precisa das duas coisas, e entra noutra fase.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import config

LOCAIS = {"localhost", "127.0.0.1", "::1"}

BOAS_VINDAS = ("Ola! Sou o atendente. Pergunte sobre a documentacao do time. "
               "A primeira resposta pode demorar: o modelo roda em CPU.")


def para_onde(atividade: dict, cfg: config.Config | None = None) -> str:
    """O serviceUrl para onde a resposta vai, ou "" quando ele nao e desta maquina."""
    c = cfg or config.atual()
    try:
        partes = urllib.parse.urlsplit(str(atividade.get("serviceUrl") or ""))
        porta = partes.port
    except ValueError:
        return ""
    if partes.scheme not in ("http", "https") or partes.hostname not in LOCAIS:
        return ""
    if c.emulador_host:
        # A API no Docker: o localhost que o Emulator manda e o do Windows, nao o do
        # container. A trava acima ja olhou o endereco original.
        partes = partes._replace(netloc=c.emulador_host + (f":{porta}" if porta else ""))
    return urllib.parse.urlunsplit(partes).rstrip("/")


def e_pergunta(atividade: dict) -> bool:
    return atividade.get("type") == "message" and bool(texto_de(atividade))


def chegou_gente(atividade: dict) -> bool:
    """O Emulator abre a conversa com um conversationUpdate que traz o bot E a pessoa.
    So a pessoa merece boas-vindas."""
    if atividade.get("type") != "conversationUpdate":
        return False
    eu = (atividade.get("recipient") or {}).get("id")
    return any(m.get("id") != eu for m in atividade.get("membersAdded") or [])


def texto_de(atividade: dict) -> str:
    return str(atividade.get("text") or "").strip()[:4000]


def conversa_de(atividade: dict) -> str:
    """A memoria e por conversa do canal: reiniciar a conversa no Emulator comeca do zero."""
    return str((atividade.get("conversation") or {}).get("id") or "canal")[:200]


def quem_perguntou(atividade: dict) -> str:
    return str((atividade.get("from") or {}).get("name") or "")[:200]


def texto_da_resposta(resposta) -> str:
    """A resposta e, embaixo, de onde ela veio. No curl as fontes vem num campo proprio;
    no chat, ou vao no texto, ou ninguem ve."""
    titulos = list(dict.fromkeys(f["titulo"] for f in resposta.fontes if f.get("titulo")))
    if not titulos:
        return resposta.resposta
    return f"{resposta.resposta}\n\n_fontes: {' · '.join(titulos)}_"


def resposta_para(atividade: dict, tipo: str, texto: str = "") -> dict:
    """A atividade de volta: quem falou vira quem recebe."""
    volta = {"type": tipo,
             "from": atividade.get("recipient") or {},
             "recipient": atividade.get("from") or {},
             "conversation": atividade.get("conversation") or {},
             "replyToId": atividade.get("id") or ""}
    if texto:
        volta.update(text=texto, textFormat="markdown",
                     locale=atividade.get("locale") or "pt-BR")
    return volta


def _postar(url: str, corpo: dict) -> None:
    pedido = urllib.request.Request(
        url, data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(pedido, timeout=30):
        pass


def enviar(atividade: dict, volta: dict, base: str) -> bool:
    conversa = urllib.parse.quote(
        str((atividade.get("conversation") or {}).get("id") or ""), safe="")
    url = f"{base}/v3/conversations/{conversa}/activities"
    if atividade.get("id"):
        url += "/" + urllib.parse.quote(str(atividade["id"]), safe="")
    try:
        _postar(url, volta)
        return True
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Sem isto, "o bot nao respondeu" nao deixa rastro nenhum — e quase sempre e o
        # container que nao enxerga o Emulator (ver EMULADOR_HOST).
        print(f"canal: nao consegui responder em {url}: {str(e)[:160]}", flush=True)
        return False
