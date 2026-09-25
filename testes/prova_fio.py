"""
Prova da memoria: a API lembra o assunto, o modelo nao recebe historico.

Os casos sao os que derrubaram o dragon_ia de verdade, traduzidos para o mundo de um time
de plantao: a terceira pergunta sem sujeito, o pronome pendurado, o item da lista.
"""
from comum import Prova
from atendente import fio as F

p = Prova("fio")

p.secao("1. o assunto sai da frase, sem modelo")
p.confere("pega o substantivo", F.assunto_do_texto("o que e o cluster de pagamentos?") ==
          "cluster pagamentos", F.assunto_do_texto("o que e o cluster de pagamentos?"))
p.confere("tira saudacao", F.assunto_do_texto("oi, bom dia, o que e o produto falcao?") ==
          "produto falcao", F.assunto_do_texto("oi, bom dia, o que e o produto falcao?"))
p.confere("frase sem conteudo nao vira assunto", F.assunto_do_texto("oi, tudo bem?") == "",
          repr(F.assunto_do_texto("oi, tudo bem?")))

p.secao("\n2. a primeira pergunta nunca esta pendurada")
vazio = F.fio_vazio("t")
p.confere("sem turno anterior, nada pendura", F.esta_pendurada("quais sao os limites?", vazio) == "")

p.secao("\n3. a pergunta sem sujeito pendura no assunto de antes")
f = F.fio_vazio("t")
F.anotar_turno(f, "o que e o cluster de pagamentos?", "E o cluster que roda o checkout.")
p.confere("atributo sem dono pendura", bool(F.esta_pendurada("quais sao os limites?", f)))
p.confere("pronome pendura", bool(F.esta_pendurada("como ele escala?", f)))
p.confere("pedir de novo pendura", bool(F.esta_pendurada("me explica mais curto", f)))
p.confere("apontar item da lista pendura", bool(F.esta_pendurada("qual o dono do 1 da lista", f)))
p.confere("pergunta que se explica NAO pendura",
          F.esta_pendurada("o que e o produto gaviao?", f) == "",
          F.esta_pendurada("o que e o produto gaviao?", f))
p.confere("pergunta que repete o assunto NAO pendura",
          F.esta_pendurada("quais os limites do cluster de pagamentos?", f) == "")
p.confere("pergunta com host concreto NAO pendura",
          F.esta_pendurada("qual o dono de falcao.interno.local?", f) == "",
          F.esta_pendurada("qual o dono de falcao.interno.local?", f))

p.secao("\n4. o digesto e curto, e diz o assunto")
d = F.digesto_do_fio(f, "quais sao os limites?")
p.confere("diz o assunto", "cluster pagamentos" in d["texto"], d["texto"])
p.confere("cabe no teto", len(d["texto"]) <= F.TETO_DE_LETRAS + F.TETO_DO_RESUMO,
          str(len(d["texto"])))
p.confere("conta que colou", F.como_contar(d).startswith("entendi que e sobre"))
p.confere("pergunta que se explica nao leva digesto",
          F.digesto_do_fio(f, "o que e o produto gaviao?")["texto"] == "")

p.secao("\n5. a busca herda o assunto — e e isso que faz o RAG achar")
p.confere("pendurada leva o assunto junto",
          F.o_que_procurar(f, "qual o ip?") == "cluster pagamentos qual o ip?",
          F.o_que_procurar(f, "qual o ip?"))
p.confere("pergunta inteira vai sozinha",
          F.o_que_procurar(f, "o que e o produto gaviao?") == "o que e o produto gaviao?")

p.secao("\n6. a lista sobrevive ao resumo do turno")
lista = "Rodam neste cluster:\n1. pagamentos\n2. carrinho\n3. catalogo\nQualquer duvida, chame."
p.confere("guarda os itens, nao a primeira frase",
          F.resumir_resposta(lista) == "1. pagamentos; 2. carrinho; 3. catalogo",
          F.resumir_resposta(lista))
p.confere("resposta comum vira uma frase",
          F.resumir_resposta("O IP e 10.20.30.40. Ele fica no balanceador.") ==
          "O IP e 10.20.30.40.", F.resumir_resposta("O IP e 10.20.30.40. Ele fica no balanceador."))
p.confere("bloco de codigo nao entra no resumo",
          "def" not in F.resumir_resposta("Use isto:\n```py\ndef x():\n  pass\n```\npronto."))

p.secao("\n7. o fio nao cresce sem fim")
longo = F.fio_vazio("t")
for i in range(20):
    F.anotar_turno(longo, f"pergunta numero {i} sobre kubernetes", f"resposta {i}")
p.confere("guarda so os ultimos seis turnos", len(longo.turnos) == F.TETO_DE_TURNOS,
          str(len(longo.turnos)))
p.confere("mas sabe quantos ja houve", longo.total_de_turnos == 20, str(longo.total_de_turnos))

p.secao("\n8. o resumo rolante")
p.confere("com poucos turnos nao gasta chamada", not F.precisa_resumir(f))
p.confere("com muitos, resume", F.precisa_resumir(longo))
texto = F.o_que_resumir(longo)
p.confere("o que vai resumir cabe no teto", len(texto) <= 1600, str(len(texto)))
F.com_o_resumo(longo, "  A conversa trata de kubernetes   e do cluster de pagamentos. ")
p.confere("guardou comprimido", longo.resumo_do_passado.startswith("A conversa trata"))
p.confere("marcou ate onde comprimiu", longo.resumidos_ate == 20, str(longo.resumidos_ate))
p.confere("e nao resume de novo a toa", not F.precisa_resumir(longo))
F.anotar_turno(longo, "e o carrinho?", "o carrinho roda no mesmo cluster")
p.confere("turno novo pede resumo novo", F.precisa_resumir(longo))
d2 = F.digesto_do_fio(longo, "quais sao os limites?")
p.confere("o resumo entra no digesto", "Ate aqui:" in d2["texto"], d2["texto"][:120])

p.secao("\n9. fio esfria")
frio = F.fio_vazio("t")
F.anotar_turno(frio, "o que e o falcao?", "um produto")
frio.quando = 0.0
p.confere("sem hora nao esfria", not F.esfriou(F.fio_vazio("t")))
import time as _t
frio.quando = _t.time() - (F.MINUTOS_ATE_ESFRIAR + 1) * 60
p.confere("meia hora parado esfria", F.esfriou(frio))

p.secao("\n10. a conversa inteira, como ela chega no canal")
# Estes tres casos vieram de uma conversa de verdade contra o 14b, nao da minha cabeca.
# O assunto degradava: virava "dono", depois "producao precisa alguma".
p.confere("'quem e o dono?' nao abre assunto novo — dono DE QUE",
          bool(F.esta_pendurada("quem e o dono?", f)),
          F.esta_pendurada("quem e o dono?", f))
p.confere("'o que eu olho primeiro?' nao e item de lista",
          F.esta_pendurada("meu pod ta em CrashLoopBackOff, o que eu olho primeiro?", f) == "",
          F.esta_pendurada("meu pod ta em CrashLoopBackOff, o que eu olho primeiro?", f))
p.confere("'em producao precisa de alguma coisa antes?' pendura",
          bool(F.esta_pendurada("em producao precisa de alguma coisa antes?", f)))
p.confere("mas 'quem e o dono do gaviao?' se sustenta",
          F.esta_pendurada("quem e o dono do gaviao?", f) == "",
          F.esta_pendurada("quem e o dono do gaviao?", f))
# Pendurar no modelo e barato; pendurar na BUSCA nao e. As duas decisoes sao separadas.
p.confere("'qual o ip de producao do falcao?' nomeia o produto",
          F.nomeia_algo("qual o ip de producao do falcao?"))
p.confere("e por isso a busca NAO herda o assunto",
          F.o_que_procurar(f, "qual o ip do gaviao?") == "qual o ip do gaviao?",
          F.o_que_procurar(f, "qual o ip do gaviao?"))
p.confere("pronome nao nomeia nada: 'o ip de producao DELE' herda o assunto",
          F.o_que_procurar(f, "qual o ip de producao dele?").startswith(f.assunto_atual),
          F.o_que_procurar(f, "qual o ip de producao dele?"))
p.confere("mas 'qual o ip de producao?' nomeia nada, e herda",
          F.o_que_procurar(f, "qual o ip de producao?").startswith(f.assunto_atual),
          F.o_que_procurar(f, "qual o ip de producao?"))

conversa = F.fio_vazio("canal")
falas = ["o que e o produto falcao?", "qual o ip de producao dele?", "e o de homologacao?",
         "quem e o dono?", "meu pod ta em CrashLoopBackOff, o que eu olho primeiro?",
         "e se for falta de memoria?", "como eu escalo o deployment?",
         "em producao precisa de alguma coisa antes?"]
assuntos = []
for t in falas:
    F.anotar_turno(conversa, t, "resposta qualquer")
    assuntos.append(conversa.assunto_atual)
p.confere("os quatro primeiros turnos ficam no Falcao",
          all(a == "produto falcao" for a in assuntos[:4]), str(assuntos[:4]))
p.confere("o quinto troca de assunto de verdade",
          "pod" in assuntos[4], assuntos[4])
p.confere("e os tres ultimos ficam nele",
          assuntos[5] == assuntos[6] == assuntos[7] == assuntos[4], str(assuntos[5:]))

raise SystemExit(p.fim())
