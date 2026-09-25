"""
Prova da porta do Bot Framework Emulator, com modelo de mentira e Emulator de mentira.

O que esta sob prova: a atividade entra em /api/messages, a resposta sai por OUTRO pedido
no serviceUrl, e a porta se recusa a responder para fora da maquina.
"""
import os
from comum import Prova

os.environ["MEMORIA_PASTA"] = "/tmp/prova-atendente-canal"
import shutil
shutil.rmtree("/tmp/prova-atendente-canal", ignore_errors=True)

from fastapi.testclient import TestClient
from atendente import acervo, busca, canal, config, modelo
from atendente.app import app

p = Prova("canal")

acervo.usar_este_indice(busca.montar([
    {"id": "falcao", "titulo": "Produto Falcao", "fonte": "confluence:101", "texto": """# Visao geral
O Falcao e o produto de pagamentos.

# Enderecos
O IP do balanceador de producao e 10.20.30.40.
"""},
    {"id": "gaviao", "titulo": "Produto Gaviao", "fonte": "confluence:102",
     "texto": "# Enderecos\nO IP de producao do Gaviao e 10.90.1.2.\n"},
]))

falhar = []
def modelo_falso(tipo, fatos, cfg=None, bater=None):
    if falhar:
        return modelo.RespostaDoModelo(False, porque="o modelo nao respondeu: recusada")
    if tipo == "resumo":
        return modelo.RespostaDoModelo(True, dados="A conversa trata do produto Falcao.")
    texto = "O IP de producao e 10.20.30.40." if "10.20.30.40" in (fatos.get("fatos") or "") \
            else "Nao encontrei esse dado na documentacao interna."
    return modelo.RespostaDoModelo(True, dados=texto)

import atendente.app as A
A.modelo.perguntar = modelo_falso

# o Emulator de mentira: guarda tudo que a API mandou de volta
enviados = []
canal._postar = lambda url, corpo: enviados.append({"url": url, "corpo": corpo})

cliente = TestClient(app)
EMULADOR = "http://localhost:53000"
CONVERSA = {"id": "abc-123|livechat"}
BOT = {"id": "bot-1", "name": "Bot"}
PESSOA = {"id": "pessoa-1", "name": "Maria"}


def atividade(**campos):
    base = {"type": "message", "id": "at-1", "serviceUrl": EMULADOR, "channelId": "emulator",
            "conversation": CONVERSA, "from": PESSOA, "recipient": BOT}
    base.update(campos)
    return base


p.secao("1. o Emulator abre a conversa")
enviados.clear()
r = cliente.post("/api/messages", json=atividade(type="conversationUpdate", id="at-0",
                                                  membersAdded=[BOT, PESSOA]))
p.confere("respondeu 200", r.status_code == 200, str(r.status_code))
p.confere("mandou boas-vindas uma vez", len(enviados) == 1, str(len(enviados)))
p.confere("no endereco do Emulator",
          enviados and enviados[0]["url"] ==
          EMULADOR + "/v3/conversations/abc-123%7Clivechat/activities/at-0",
          enviados[0]["url"] if enviados else "")

enviados.clear()
cliente.post("/api/messages", json=atividade(type="conversationUpdate", membersAdded=[BOT]))
p.confere("o bot chegando sozinho nao ganha boas-vindas", not enviados, str(enviados))

p.secao("\n2. uma pergunta")
enviados.clear()
r = cliente.post("/api/messages", json=atividade(text="o que e o produto falcao?"))
p.confere("respondeu 200", r.status_code == 200, str(r.status_code))
tipos = [e["corpo"]["type"] for e in enviados]
p.confere("primeiro o digitando, depois a resposta", tipos == ["typing", "message"], str(tipos))
volta = enviados[-1]["corpo"] if enviados else {}
p.confere("responde a atividade certa", volta.get("replyToId") == "at-1")
p.confere("quem falou vira quem recebe",
          volta.get("from") == BOT and volta.get("recipient") == PESSOA)
p.confere("na mesma conversa", volta.get("conversation") == CONVERSA)
p.confere("sem fonte achada, sem linha de fontes", volta.get("text")
          and "_fontes" not in volta["text"], volta.get("text", ""))

p.secao("\n3. a pergunta pendurada usa a memoria da conversa do canal")
enviados.clear()
cliente.post("/api/messages", json=atividade(id="at-2", text="qual o ip de producao?"))
volta = enviados[-1]["corpo"] if enviados else {}
p.confere("respondeu com o IP certo", "10.20.30.40" in volta.get("text", ""),
          volta.get("text", ""))
p.confere("e diz de onde veio", volta.get("text", "").endswith("_fontes: Produto Falcao_"),
          volta.get("text", ""))
v = cliente.get("/conversa/" + CONVERSA["id"]).json()
p.confere("a memoria e a da conversa do Emulator", v["total_de_turnos"] == 2,
          str(v["total_de_turnos"]))

p.secao("\n4. o modelo fora do ar vira recado, nao silencio")
enviados.clear()
falhar.append(True)
cliente.post("/api/messages", json=atividade(id="at-3", text="e o dono dele?"))
falhar.clear()
volta = enviados[-1]["corpo"] if enviados else {}
p.confere("avisou no chat", "Nao consegui falar com o modelo" in volta.get("text", ""),
          volta.get("text", ""))

p.secao("\n5. o que nao e pergunta nao gasta o modelo")
enviados.clear()
r = cliente.post("/api/messages", json=atividade(type="typing"))
p.confere("typing: 200 e nada de volta", r.status_code == 200 and not enviados)
r = cliente.post("/api/messages", json=atividade(text="   "))
p.confere("mensagem vazia: 200 e nada de volta", r.status_code == 200 and not enviados)

p.secao("\n6. a trava: so responde para esta maquina")
for fora in ("http://10.0.0.5:8080", "https://evil.example.com", "", "file:///etc/passwd",
             "http://localhost.evil.com"):
    enviados.clear()
    r = cliente.post("/api/messages", json=atividade(serviceUrl=fora, text="oi"))
    p.confere(f"recusou {fora or '(vazio)'}", r.status_code == 403 and not enviados,
              str(r.status_code))

p.secao("\n7. a API no Docker: o localhost do Emulator vira o host dele")
os.environ["EMULADOR_HOST"] = "host.docker.internal"
config.recarregar()
enviados.clear()
cliente.post("/api/messages", json=atividade(serviceUrl="http://127.0.0.1:53000/", text="oi"))
p.confere("mandou para host.docker.internal, na mesma porta",
          enviados and enviados[0]["url"].startswith("http://host.docker.internal:53000/v3/"),
          enviados[0]["url"] if enviados else "")
r = cliente.post("/api/messages", json=atividade(serviceUrl="http://10.0.0.5:53000", text="oi"))
p.confere("e a trava continua olhando o endereco original", r.status_code == 403)
del os.environ["EMULADOR_HOST"]
config.recarregar()

shutil.rmtree("/tmp/prova-atendente-canal", ignore_errors=True)
raise SystemExit(p.fim())
