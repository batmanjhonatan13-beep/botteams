"""
Onde os fios ficam guardados.

A memoria e da API, nao do modelo — esse e o ponto do projeto inteiro. Aqui ela ganha um
lugar: um arquivo por conversa, numa pasta que e volume no Docker. Sem isso, reiniciar o
container apagaria o assunto de todo mundo no meio do atendimento.
"""
import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from . import fio as F

PASTA = Path(os.environ.get("MEMORIA_PASTA", "memoria"))
# Conversa parada ha mais de um dia nao volta: o fio ja teria esfriado de qualquer jeito.
DIAS_ATE_APAGAR = 7

_trava = threading.Lock()
_vivos: dict[str, F.Fio] = {}


def _seguro(id_da_conversa: str) -> str:
    """Id de conversa vem do Teams e de gente digitando. Ele NAO vira caminho sem passar
    por aqui — senao um id com ../ escreve fora da pasta."""
    limpo = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(id_da_conversa or ""))
    return (limpo[:120] or "sem-id")


def _arquivo(id_da_conversa: str) -> Path:
    return PASTA / (_seguro(id_da_conversa) + ".json")


def _do_disco(id_da_conversa: str) -> F.Fio | None:
    try:
        bruto = json.loads(_arquivo(id_da_conversa).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    turnos = [F.Turno(**t) for t in bruto.get("turnos", [])]
    return F.Fio(
        id=bruto.get("id", id_da_conversa), turnos=turnos,
        assunto_atual=bruto.get("assunto_atual", ""), quando=bruto.get("quando", 0.0),
        resumo_do_passado=bruto.get("resumo_do_passado", ""),
        resumidos_ate=bruto.get("resumidos_ate", 0),
        total_de_turnos=bruto.get("total_de_turnos", 0))


def abrir(id_da_conversa: str) -> F.Fio:
    """O fio desta conversa. Esfriado, volta vazio: a pessoa voltou amanha, o assunto nao
    e o de ontem."""
    with _trava:
        f = _vivos.get(id_da_conversa) or _do_disco(id_da_conversa) or F.fio_vazio(id_da_conversa)
        if F.esfriou(f):
            f = F.fio_vazio(id_da_conversa)
        _vivos[id_da_conversa] = f
        return f


def gravar(f: F.Fio) -> None:
    with _trava:
        _vivos[f.id] = f
        try:
            PASTA.mkdir(parents=True, exist_ok=True)
            _arquivo(f.id).write_text(
                json.dumps({**asdict(f)}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass          # perder o disco nao pode derrubar o atendimento


def esquecer(id_da_conversa: str) -> bool:
    with _trava:
        _vivos.pop(id_da_conversa, None)
        try:
            _arquivo(id_da_conversa).unlink()
            return True
        except OSError:
            return False


def limpar_velhos(agora: float | None = None) -> int:
    agora = agora if agora is not None else time.time()
    quantos = 0
    try:
        for caminho in PASTA.glob("*.json"):
            if (agora - caminho.stat().st_mtime) > DIAS_ATE_APAGAR * 86400:
                caminho.unlink()
                quantos += 1
    except OSError:
        pass
    return quantos


def quantos() -> int:
    return len(_vivos)
