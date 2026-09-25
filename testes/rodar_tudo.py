"""Todas as provas, uma depois da outra. Nenhuma delas precisa de modelo nem de rede."""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
provas = sorted(AQUI.glob("prova_*.py"))
falharam = []
for prova in provas:
    r = subprocess.run([sys.executable, str(prova)], capture_output=True, text=True, cwd=AQUI)
    ok = r.returncode == 0
    print(f"{prova.name:22} {'ok' if ok else 'FALHOU'}")
    if not ok:
        falharam.append(prova.name)
        for linha in (r.stdout + r.stderr).splitlines():
            if "ERRO" in linha or "Error" in linha or "Traceback" in linha:
                print("     " + linha)
print(f"\n{len(provas)} provas · {len(falharam)} falharam")
sys.exit(1 if falharam else 0)
