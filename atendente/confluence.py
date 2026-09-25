"""
Confluence, SOMENTE LEITURA.

O pedido foi explicito: "api com o atlassian so de consulta, nada de criacao e alteracao
por enquanto". A garantia aqui e estrutural, nao um aviso no README: este modulo tem UMA
funcao que fala com a rede, `_pegar`, e ela so sabe fazer GET. Nao existe neste arquivo
nenhum caminho que faca POST, PUT ou DELETE. Para escrever no Confluence sera preciso
escrever codigo novo, e ai a mudanca aparece no diff.

Serve Cloud e Server/DC: o que muda e a URL base que voce configura.
  Cloud:      CONFLUENCE_URL=https://suaempresa.atlassian.net/wiki
  Server/DC:  CONFLUENCE_URL=https://confluence.suaempresa.com
"""
import base64
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config

TAG = re.compile(r"<[^>]+>")
MACRO = re.compile(r"<ac:[^>]*>|</ac:[^>]*>")
ESPACO = re.compile(r"[ \t]+")
LINHAS_VAZIAS = re.compile(r"\n{3,}")


def texto_de_html(bruto: str) -> str:
    """O corpo do Confluence vem em 'storage format', que e XHTML com macros. O que
    interessa e o texto — e as quebras de linha, porque e nelas que a secao comeca."""
    t = str(bruto or "")
    t = re.sub(r"<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>", " ", t, flags=re.I)
    t = re.sub(r"<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", t, flags=re.I)
    t = re.sub(r"</h[1-6]>", "\n", t, flags=re.I)
    t = re.sub(r"<(?:br|/p|/div|/li|/tr)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "- ", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = MACRO.sub(" ", t)
    t = TAG.sub(" ", t)
    t = html.unescape(t)
    t = ESPACO.sub(" ", t)
    return LINHAS_VAZIAS.sub("\n\n", t).strip()


def _cabecalhos(c: config.Config) -> dict:
    cru = f"{c.confluence_usuario}:{c.confluence_token}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(cru).decode("ascii"),
            "Accept": "application/json"}


def _pegar(caminho: str, parametros: dict, c: config.Config, segundos: int = 60) -> dict:
    """A UNICA porta para a rede neste arquivo, e ela so faz GET."""
    base = c.confluence_url.rstrip("/")
    url = f"{base}{caminho}?{urllib.parse.urlencode(parametros)}"
    pedido = urllib.request.Request(url, headers=_cabecalhos(c), method="GET")
    with urllib.request.urlopen(pedido, timeout=segundos) as r:
        return json.loads(r.read().decode("utf-8"))


def conferir(cfg: config.Config | None = None) -> dict:
    """Bate uma vez para dizer se a credencial vale — antes de alguem esperar o acervo."""
    c = cfg or config.atual()
    if not c.tem_confluence():
        return {"ok": False, "porque": "sem CONFLUENCE_URL/USUARIO/TOKEN configurados"}
    try:
        d = _pegar("/rest/api/content/search", {"cql": "type=page", "limit": 1}, c, 30)
        return {"ok": True, "url": c.confluence_url, "achou": len(d.get("results", []))}
    except urllib.error.HTTPError as e:
        return {"ok": False, "porque": f"HTTP {e.code} ao consultar o Confluence"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "porque": str(e)[:200]}


def _cql(c: config.Config) -> str:
    if c.confluence_espacos:
        espacos = ",".join(f'"{e}"' for e in c.confluence_espacos)
        return f"type=page and space in ({espacos})"
    return "type=page"


def paginas(cfg: config.Config | None = None, pegar=None) -> list[dict]:
    """As paginas dos espacos configurados, como documentos prontos para o indice.

    `pegar` entra por fora para o teste rodar sem Confluence nenhum."""
    c = cfg or config.atual()
    if not c.tem_confluence():
        return []
    chamar = pegar or (lambda caminho, params: _pegar(caminho, params, c))
    saida: list[dict] = []
    inicio, por_vez = 0, 50
    while len(saida) < c.confluence_paginas:
        try:
            d = chamar("/rest/api/content/search", {
                "cql": _cql(c), "limit": min(por_vez, c.confluence_paginas - len(saida)),
                "start": inicio, "expand": "body.storage,space,version",
            })
        except (urllib.error.URLError, OSError, ValueError):
            break
        achados = d.get("results", []) or []
        if not achados:
            break
        for p in achados:
            corpo = ((p.get("body") or {}).get("storage") or {}).get("value", "")
            texto = texto_de_html(corpo)
            if not texto:
                continue
            espaco = (p.get("space") or {}).get("key", "")
            ident = p.get("id", "")
            saida.append({
                "id": f"confluence:{ident}",
                "titulo": p.get("title", "") or f"pagina {ident}",
                "fonte": f"{c.confluence_url.rstrip('/')}/pages/viewpage.action?pageId={ident}",
                "espaco": espaco,
                "texto": texto,
            })
        inicio += len(achados)
        if len(achados) < por_vez:
            break
    return saida
