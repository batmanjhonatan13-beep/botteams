"""
Prova da API inteira, de ponta a ponta, com modelo de mentira.

O que esta sob prova e a promessa do projeto: a MEMORIA E DA API. Entao o teste olha o
prompt que saiu — e cobra que o historico nao esteja la, que o assunto esteja, e que a
busca tenha usado o assunto para achar o pedaco certo.
"""
import os
from comum import Prova

os.environ["MEMORIA_PASTA"] = "/tmp/prova-atendente-memoria"
import shutil
shutil.rmtree("/tmp/prova-atendente-memoria", ignore_errors=True)

from fastapi.testclient import TestClient
from atendente import acervo, busca, memoria, modelo
from atendente.app import app

p = Prova("api")

# ---- acervo de mentira, sem disco e sem Confluence
acervo.usar_este_indice(busca.montar([
    {"id": "falcao", "titulo": "Produto Falcao", "fonte": "confluence:101", "texto": """# Visao geral
O Falcao e o produto de pagamentos.

# Enderecos
O IP do balanceador de producao e 10.20.30.40.
"""},
    {"id": "gaviao", "titulo": "Produto Gaviao", "fonte": "confluence:102",
     "texto": "# Enderecos\nO IP de producao do Gaviao e 10.90.1.2.\n"},
]))

# ---- modelo de mentira: guarda o prompt e devolve uma resposta plausivel
prompts = []
def modelo_falso(tipo, fatos, cfg=None, bater=None):
    prompts.append({"tipo": tipo, "usuario": __import__("atendente.perguntas", fromlist=["PERGUNTAS"])
                    .PERGUNTAS[tipo]["monta"](fatos)})
    if tipo == "resumo":
        return modelo.RespostaDoModelo(True, dados="A conversa trata do produto Falcao e do IP.")
    texto = "O IP de producao e 10.20.30.40." if "10.20.30.40" in (fatos.get("fatos") or "") \
            else "Nao encontrei esse dado na documentacao interna."
    return modelo.RespostaDoModelo(True, dados=texto, fichas_de_entrada=120, janela=2048,
                                   tentativas=1)

import atendente.app as A
A.modelo.perguntar = modelo_falso
cliente = TestClient(app)

p.secao("1. o primeiro turno: pergunta inteira, sem cola")
r = cliente.post("/conversa", json={"conversa_id": "c1", "texto": "o que e o produto falcao?"}).json()
p.confere("respondeu", bool(r["resposta"]), r["resposta"][:60])
p.confere("guardou o assunto", r["assunto"] == "produto falcao", r["assunto"])
p.confere("nao colou nada (a pergunta se explica)", r["colou"] == "", r["colou"])
p.confere("disse o que olhou nas docs", "Produto Falcao" in r["olhei"], r["olhei"])

p.secao("\n2. o segundo turno: pergunta pendurada")
r2 = cliente.post("/conversa", json={"conversa_id": "c1", "texto": "qual o ip de producao?"}).json()
p.confere("respondeu com o IP certo", "10.20.30.40" in r2["resposta"], r2["resposta"])
p.confere("nao entregou o IP do vizinho", "10.90.1.2" not in r2["resposta"])
p.confere("avisou que colou o assunto", r2["colou"] == "produto falcao", r2["colou"])
p.confere("e diz por que colou", "nao diz de que" in r2["porque_colou"], r2["porque_colou"])
p.confere("devolveu a fonte", r2["fontes"] and r2["fontes"][0]["fonte"] == "confluence:101",
          str(r2["fontes"]))

p.secao("\n3. o prompt: com assunto, SEM historico")
ultimo = prompts[-1]["usuario"]
p.confere("o assunto esta no prompt", "produto falcao" in ultimo, ultimo[:80])
p.confere("os FATOS estao no prompt", "10.20.30.40" in ultimo)
p.confere("a resposta anterior NAO esta inteira no prompt",
          "O Falcao e o produto de pagamentos." not in ultimo or len(ultimo) < 900)
p.confere("o prompt e pequeno", len(ultimo) < 1200, f"{len(ultimo)} letras")

p.secao("\n4. a memoria e visivel")
v = cliente.get("/conversa/c1").json()
p.confere("dois turnos", v["total_de_turnos"] == 2, str(v["total_de_turnos"]))
p.confere("guardou resumo do turno, nao a resposta inteira",
          all(len(t["resumo"]) <= 200 for t in v["turnos"]))
p.confere("o assunto esta la", v["assunto_atual"] == "produto falcao")

p.secao("\n5. conversas nao se misturam")
r3 = cliente.post("/conversa", json={"conversa_id": "c2", "texto": "qual o ip de producao?"}).json()
p.confere("outra conversa nao herda o assunto", r3["colou"] == "", r3["colou"])
p.confere("e sem assunto nao acha o pedaco certo",
          "10.20.30.40" not in r3["resposta"], r3["resposta"])

p.secao("\n6. o resumo rolante roda depois de responder")
for i in range(4):
    cliente.post("/conversa", json={"conversa_id": "c1", "texto": f"e sobre o item {i}, como faz?"})
v2 = cliente.get("/conversa/c1").json()
p.confere("comprimiu o passado", bool(v2["resumo_do_passado"]), v2["resumo_do_passado"])
p.confere("marcou ate onde", v2["resumidos_ate"] >= 5, str(v2["resumidos_ate"]))
p.confere("houve chamada de resumo", any(x["tipo"] == "resumo" for x in prompts))

p.secao("\n7. o depurador: ver a busca sem gastar o modelo")
b = cliente.get("/busca", params={"q": "ip de producao do falcao"}).json()
p.confere("achou", b["achados"] and b["achados"][0]["titulo"] == "Produto Falcao",
          str(b["achados"][:1]))
p.confere("diz a nota e as palavras", "nota" in b["achados"][0] and b["achados"][0]["casou"])

m = cliente.post("/conversa", json={"conversa_id": "c3", "texto": "qual o ip do gaviao?",
                                    "so_montar": True}).json()
p.confere("so_montar devolve o prompt sem chamar o modelo",
          m["prompt"] and "10.90.1.2" in m["prompt"], (m["prompt"] or "")[:80])

p.secao("\n8. esquecer")
p.confere("esqueceu", cliente.delete("/conversa/c1").json()["esqueci"])
p.confere("e volta do zero", cliente.get("/conversa/c1").json()["total_de_turnos"] == 0)

p.secao("\n9. a memoria sobrevive a um reinicio")
cliente.post("/conversa", json={"conversa_id": "c9", "texto": "o que e o produto falcao?"})
memoria._vivos.clear()      # como se o container tivesse reiniciado
v9 = cliente.get("/conversa/c9").json()
p.confere("leu do disco", v9["assunto_atual"] == "produto falcao", v9["assunto_atual"])

p.secao("\n10. id de conversa nao vira caminho")
p.confere("id com ../ e neutralizado", "/" not in memoria._seguro("../../etc/passwd"),
          memoria._seguro("../../etc/passwd"))

shutil.rmtree("/tmp/prova-atendente-memoria", ignore_errors=True)
raise SystemExit(p.fim())
