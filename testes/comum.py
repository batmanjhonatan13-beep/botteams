"""O minimo para uma prova: contar acerto e erro, e dizer o que falhou."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Prova:
    def __init__(self, nome: str):
        self.nome = nome
        self.erros = 0

    def secao(self, titulo: str) -> None:
        print(titulo)

    def confere(self, o_que: str, certo: bool, detalhe: str = "") -> None:
        print(f"   {'ok  ' if certo else 'ERRO'} {o_que}" + (f"  · {detalhe}" if detalhe else ""))
        if not certo:
            self.erros += 1

    def fim(self) -> int:
        print("\n" + (f"{self.erros} erro(s)" if self.erros else "PASSOU"))
        return 1 if self.erros else 0
