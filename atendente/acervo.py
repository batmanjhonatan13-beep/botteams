"""
De onde vem a documentacao interna: a pasta local e o Confluence.

O acervo e montado UMA vez e fica guardado. Reindexar a cada pergunta custaria segundos
em cima de um modelo que ja e lento; e documentacao interna nao muda de minuto em minuto.
`/acervo/recarregar` refaz quando voce quiser.
"""
import os
import threading
import time
from pathlib import Path

from . import busca, config, confluence

_trava = threading.Lock()
_indice = None
_quando = 0.0
_de_onde: dict = {}


def _titulo_do_texto(texto: str, caminho: Path) -> str:
    for linha in str(texto or "").split("\n")[:10]:
        limpo = linha.strip()
        if limpo.startswith("#"):
            return limpo.lstrip("#").strip()
        if limpo.startswith("<h1"):
            import re
            m = re.search(r">([^<]{2,120})<", limpo)
            if m:
                return m.group(1).strip()
    return caminho.stem.replace("_", " ").replace("-", " ")


def da_pasta(cfg: config.Config | None = None) -> list[dict]:
    """Os arquivos da pasta do acervo. E aqui que entra o site de docs interno: exporte
    ou monte a pasta em ACERVO_PASTA e ele vira base de busca sem mais nada."""
    c = cfg or config.atual()
    raiz = Path(c.pasta_do_acervo)
    if not raiz.is_dir():
        return []
    saida = []
    extensoes = {e.lower() for e in c.acervo_extensoes}
    for caminho in sorted(raiz.rglob("*")):
        if not caminho.is_file() or caminho.suffix.lower() not in extensoes:
            continue
        try:
            bruto = caminho.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texto = confluence.texto_de_html(bruto) if caminho.suffix.lower() in {".html", ".htm"} else bruto
        if not texto.strip():
            continue
        relativo = str(caminho.relative_to(raiz))
        # A primeira pasta vale como "espaco": acervo/SRE/x.md e do time SRE. Quem joga
        # tudo na raiz fica sem espaco, e funciona do mesmo jeito.
        partes = Path(relativo).parts
        saida.append({
            "id": f"pasta:{relativo}",
            "titulo": _titulo_do_texto(texto, caminho),
            "fonte": relativo,
            "espaco": partes[0] if len(partes) > 1 else "",
            "texto": texto,
        })
    return saida


def documentos(cfg: config.Config | None = None) -> tuple[list[dict], dict]:
    c = cfg or config.atual()
    locais = da_pasta(c)
    remotos = confluence.paginas(c)
    return locais + remotos, {"pasta": len(locais), "confluence": len(remotos)}


def recarregar(cfg: config.Config | None = None) -> dict:
    """Refaz o indice inteiro. Devolve o retrato dele."""
    global _indice, _quando, _de_onde
    docs, de_onde = documentos(cfg)
    por_espaco: dict[str, int] = {}
    for d in docs:
        por_espaco[d.get("espaco") or "(sem espaco)"] = por_espaco.get(d.get("espaco") or "(sem espaco)", 0) + 1
    de_onde = {**de_onde, "por_espaco": dict(sorted(por_espaco.items()))}
    novo = busca.montar(docs)
    with _trava:
        _indice, _quando, _de_onde = novo, time.time(), de_onde
    return retrato()


def indice(cfg: config.Config | None = None):
    """O indice de agora. Monta na primeira vez que alguem precisar."""
    global _indice
    if _indice is None:
        recarregar(cfg)
    return _indice


def retrato() -> dict:
    i = _indice or {"quantos": 0, "documentos": 0}
    return {"documentos": i.get("documentos", 0), "pedacos": i.get("quantos", 0),
            "de_onde": dict(_de_onde), "quando": _quando}


def usar_este_indice(novo) -> None:
    """Para o teste: plugar um indice de mentira sem tocar no disco nem na rede."""
    global _indice, _quando, _de_onde
    _indice, _quando, _de_onde = novo, time.time(), {"teste": novo.get("documentos", 0)}
