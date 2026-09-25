"""
Prova da pergunta curta: forma, janela dimensionada por chamada, e uma cobranca so.

Nada aqui sobe modelo: `bater` entra por fora. E por isso que esta prova roda em
milissegundos num servidor sem GPU.
"""
from comum import Prova
from atendente import config, modelo as M
from atendente.perguntas import PERGUNTAS

p = Prova("modelo")
cfg = config.Config(modelo_url="http://x", modelo_nome="qwen-teste", janela_maxima=8192)

p.secao("1. a janela fica parada na base, e so sobe quando precisa")
# Medido contra o Ollama: mesma janela -> ~8s por chamada; janela trocada -> 20 a 28s,
# porque ele reconstroi o runner. Num servidor sem GPU isso e ainda pior.
p.confere("prompt pequeno usa a base", M.janela_para(300, 700, 8192) == 4096,
          str(M.janela_para(300, 700, 8192)))
p.confere("prompt medio continua na base", M.janela_para(3000, 700, 8192) == 4096,
          str(M.janela_para(3000, 700, 8192)))
p.confere("todo turno de uma conversa normal cai na MESMA janela",
          len({M.janela_para(f, 700, 8192) for f in (200, 400, 700, 1200, 2000, 3000)}) == 1,
          str(sorted({M.janela_para(f, 700, 8192) for f in (200, 400, 700, 1200, 2000, 3000)})))
p.confere("so sobe quando o prompt nao cabe mesmo", M.janela_para(6000, 700, 8192) == 8192)
p.confere("e nunca passa do teto do time", M.janela_para(90000, 700, 4096) == 4096,
          str(M.janela_para(90000, 700, 4096)))
p.confere("a conta de ficha erra para cima", M.estimar_fichas("a" * 300) >= 100)

p.secao("\n2. uma chamada leva tudo que precisa, e nada de historico")
visto = {}
def bater_ok(url, corpo, segundos):
    visto.update({"url": url, "corpo": corpo, "segundos": segundos})
    return {"message": {"content": "O IP de producao e 10.20.30.40."}}

r = M.perguntar("resposta", {
    "pergunta": "qual o ip?",
    "fatos": "[Produto Falcao > Enderecos]\nO IP e 10.20.30.40.",
    "digesto": "Assunto desta conversa: produto falcao.",
    "perfil": "Time de confiabilidade.",
}, cfg, bater=bater_ok)
p.confere("respondeu", r.ok and "10.20.30.40" in r.dados, r.porque)
p.confere("bateu no /api/chat", visto["url"].endswith("/api/chat"), visto["url"])
p.confere("mandou duas mensagens so: sistema e pergunta",
          len(visto["corpo"]["messages"]) == 2, str(len(visto["corpo"]["messages"])))
usuario = visto["corpo"]["messages"][1]["content"]
p.confere("os FATOS foram junto", "10.20.30.40" in usuario)
p.confere("o assunto foi junto", "produto falcao" in usuario)
p.confere("o perfil do time foi junto", "confiabilidade" in usuario)
p.confere("a janela foi pedida", visto["corpo"]["options"]["num_ctx"] >= 2048,
          str(visto["corpo"]["options"]["num_ctx"]))
p.confere("nao usou o padrao de 2048 as cegas",
          visto["corpo"]["options"]["num_ctx"] == M.janela_para(
              r.fichas_de_entrada, PERGUNTAS["resposta"]["fichas_de_saida"], 8192))
p.confere("a espera e a configurada", visto["segundos"] == cfg.segundos_de_espera)
p.confere("mediu o que gastou", r.fichas_de_entrada > 0 and r.tentativas == 1)

p.secao("\n3. resposta fora da forma e cobrada UMA vez")
contagem = {"n": 0}
def bater_vazio(url, corpo, segundos):
    contagem["n"] += 1
    return {"message": {"content": "   "}}
r2 = M.perguntar("resposta", {"pergunta": "oi"}, cfg, bater=bater_vazio)
p.confere("nao passou", not r2.ok)
p.confere("cobrou duas vezes e parou", contagem["n"] == 2, str(contagem["n"]))
p.confere("diz o que veio errado", "fora da forma" in r2.porque, r2.porque)

contagem2 = {"n": 0}
def bater_segunda_vez(url, corpo, segundos):
    contagem2["n"] += 1
    return {"message": {"content": "  " if contagem2["n"] == 1 else "agora vai"}}
r3 = M.perguntar("resposta", {"pergunta": "oi"}, cfg, bater=bater_segunda_vez)
p.confere("a segunda tentativa vale", r3.ok and r3.dados == "agora vai", r3.porque)
p.confere("e ela avisa que a primeira falhou",
          r3.tentativas == 2, str(r3.tentativas))

p.secao("\n4. modelo fora do ar e modelo fora do ar, nao 'o modelo falhou'")
def bater_caido(url, corpo, segundos):
    raise OSError("connection refused")
r4 = M.perguntar("resposta", {"pergunta": "oi"}, cfg, bater=bater_caido)
p.confere("nao passou", not r4.ok)
p.confere("o recado aponta para a rede", "nao respondeu" in r4.porque, r4.porque)

p.secao("\n5. o resumo tem forma propria e teto pequeno")
p.confere("gasta pouca saida", PERGUNTAS["resumo"]["fichas_de_saida"] <= 200)
p.confere("recusa resumo com codigo", not PERGUNTAS["resumo"]["valida"]("```py\nx=1\n```"))
p.confere("aceita tres linhas", PERGUNTAS["resumo"]["valida"](
    "A conversa trata do cluster de pagamentos e do IP de producao."))

p.secao("\n6. nenhum sistema manda o modelo dizer que nao sabe")
# O defeito medido no dragon_ia: 31 respostas "Nao sei." numa bateria de 400 cadeias, e a
# causa era uma linha do proprio prompt mandando isso.
for nome, forma in PERGUNTAS.items():
    sistema = forma["sistema"].lower()
    p.confere(f"{nome}: nao manda se recusar",
              "diga que nao sabe" not in sistema and "nao souber, diga" not in sistema)

raise SystemExit(p.fim())
