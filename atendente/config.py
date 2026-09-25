"""
Tudo que muda de time para time mora aqui, e vem do ambiente.

Este arquivo existe por causa de um pedido explicito: "crie num formato que outros times
tambem poderao utilizar se precisarem". Entao nenhuma URL, nenhum espaco de Confluence e
nenhum nome de time esta escrito no codigo. Outro time copia o .env.exemplo, troca cinco
linhas e sobe o mesmo container.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _txt(nome: str, padrao: str = "") -> str:
    return str(os.environ.get(nome, padrao)).strip()


def _num(nome: str, padrao: int) -> int:
    try:
        return int(str(os.environ.get(nome, padrao)).strip())
    except (TypeError, ValueError):
        return padrao


def _lista(nome: str, padrao: str = "") -> list[str]:
    bruto = _txt(nome, padrao)
    return [p.strip() for p in bruto.split(",") if p.strip()]


@dataclass
class Config:
    # ---- o modelo. Ele e CONSULTOR: responde uma pergunta curta e esquece.
    modelo_url: str = field(default_factory=lambda: _txt("MODELO_URL", "http://127.0.0.1:11434"))
    modelo_nome: str = field(default_factory=lambda: _txt("MODELO_NOME", "qwen2.5:14b"))
    # 14b em CPU e lento: o teto de espera tem que ser generoso ou o primeiro turno morre
    # de timeout e parece que o modelo esta fora do ar.
    segundos_de_espera: int = field(default_factory=lambda: _num("MODELO_SEGUNDOS", 300))
    # A janela e dimensionada POR CHAMADA ao tamanho do prompt. Este e so o teto.
    janela_maxima: int = field(default_factory=lambda: _num("MODELO_JANELA_MAXIMA", 8192))

    # ---- o acervo de documentacao interna (o RAG)
    pasta_do_acervo: str = field(default_factory=lambda: _txt("ACERVO_PASTA", str(RAIZ / "acervo")))
    acervo_extensoes: list[str] = field(
        default_factory=lambda: _lista("ACERVO_EXTENSOES", ".md,.txt,.html,.htm,.rst,.adoc"))

    # ---- Confluence / Atlassian. SOMENTE LEITURA nesta fase, e o codigo nao tem
    # nenhuma funcao que escreva: a garantia e estrutural, nao um aviso no README.
    confluence_url: str = field(default_factory=lambda: _txt("CONFLUENCE_URL"))
    confluence_usuario: str = field(default_factory=lambda: _txt("CONFLUENCE_USUARIO"))
    confluence_token: str = field(default_factory=lambda: _txt("CONFLUENCE_TOKEN"))
    confluence_espacos: list[str] = field(default_factory=lambda: _lista("CONFLUENCE_ESPACOS"))
    # O espaco do SEU time. Ele nao filtra nada: so desempata. A IA ajuda os outros times
    # tambem, entao a doc deles precisa poder ganhar quando for ela que responde.
    confluence_espaco_de_casa: str = field(
        default_factory=lambda: _txt("CONFLUENCE_ESPACO_DE_CASA"))
    confluence_paginas: int = field(default_factory=lambda: _num("CONFLUENCE_PAGINAS", 200))

    # ---- quem e o time. Outro time troca este arquivo e o bot muda de dono.
    perfil: str = field(default_factory=lambda: _txt("PERFIL_ARQUIVO", str(RAIZ / "perfil.md")))

    def tem_confluence(self) -> bool:
        return bool(self.confluence_url and self.confluence_usuario and self.confluence_token)

    def texto_do_perfil(self) -> str:
        try:
            return Path(self.perfil).read_text(encoding="utf-8").strip()
        except OSError:
            return ""


_atual: Config | None = None


def atual() -> Config:
    """Uma so instancia, lida do ambiente na primeira vez."""
    global _atual
    if _atual is None:
        _atual = Config()
    return _atual


def recarregar() -> Config:
    """Para o teste: reler o ambiente sem reiniciar o processo."""
    global _atual
    _atual = Config()
    return _atual
