"""
Prova da busca nas docs internas.

O caso que manda no arquivo e o do dono: "qual o IP do produto tal" tem que achar a secao
de enderecos DAQUELE produto — nao a do vizinho, que fala das mesmas palavras.
"""
from comum import Prova
from atendente import busca as B

p = Prova("busca")

ACERVO = [
    {"id": "falcao", "titulo": "Produto Falcao", "fonte": "confluence:101", "texto": """# Visao geral
O Falcao e o produto de pagamentos do time. Ele roda no cluster prd-pagamentos.

# Enderecos
O IP do balanceador de producao e 10.20.30.40. Homologacao responde em 10.20.31.7.
O dominio publico e falcao.interno.local.

# Plantao
Em crise, acione o time de confiabilidade pelo canal #sre-plantao.
"""},
    {"id": "gaviao", "titulo": "Produto Gaviao", "fonte": "confluence:102", "texto": """# Visao geral
O Gaviao e o produto de catalogo.

# Enderecos
O IP de producao do Gaviao e 10.90.1.2.
"""},
    {"id": "runbook", "titulo": "Runbook de Kubernetes", "fonte": "docs/runbook-k8s.md",
     "texto": """# Pods em CrashLoopBackOff
Olhe os eventos com kubectl describe pod. A causa mais comum e falta de memoria.

# Como escalar um deployment
Use kubectl scale deployment NOME --replicas=N. Em producao, abra mudanca antes.
"""},
]
indice = B.montar(ACERVO)

p.secao("1. o indice se monta sem modelo e sem rede")
p.confere("partiu em pedacos por secao", indice["quantos"] >= 6, str(indice["quantos"]))
p.confere("contou os documentos", indice["documentos"] == 3)
p.confere("todo pedaco tem fonte", all(x["fonte"] for x in indice["pedacos"]))

p.secao("\n2. palavra e palavra: acento, plural, camelCase e IP")
p.confere("acento nao separa", B.pedacos_de_texto("produção") == ["producao"],
          str(B.pedacos_de_texto("produção")))
p.confere("plural encosta no singular", B.raiz("servidores") == "servidor")
p.confere("camelCase parte", B.pedacos_de_texto("pagamentoApi") == ["pagamento", "api"],
          str(B.pedacos_de_texto("pagamentoApi")))
p.confere("snake_case parte igual", B.pedacos_de_texto("pagamento_api") == ["pagamento", "api"])
p.confere("IP fica inteiro", "10.20.30.40" in B.pedacos_de_texto("o ip e 10.20.30.40"),
          str(B.pedacos_de_texto("o ip e 10.20.30.40")))
p.confere("palavra de toda pergunta nao entra",
          B.pedacos_de_texto("qual o ip da pagina") == ["ip"],
          str(B.pedacos_de_texto("qual o ip da pagina")))

p.secao("\n3. a pergunta escolhe o pedaco certo")
def topo(q):
    a = B.procurar(indice, q, 1)
    return (a[0]["pedaco"]["titulo"], a[0]["pedaco"]["secao"]) if a else ("", "")

p.confere("ip do falcao acha a secao de enderecos do FALCAO",
          topo("qual o ip de producao do falcao") == ("Produto Falcao", "Enderecos"),
          str(topo("qual o ip de producao do falcao")))
p.confere("ip do gaviao acha o GAVIAO",
          topo("qual o ip do gaviao") == ("Produto Gaviao", "Enderecos"),
          str(topo("qual o ip do gaviao")))
p.confere("crashloop acha o runbook",
          topo("meu pod esta em CrashLoopBackOff") == ("Runbook de Kubernetes",
                                                       "Pods em CrashLoopBackOff"),
          str(topo("meu pod esta em CrashLoopBackOff")))
p.confere("escalar acha a secao de escalar",
          topo("como eu escalo um deployment") == ("Runbook de Kubernetes",
                                                    "Como escalar um deployment"),
          str(topo("como eu escalo um deployment")))
p.confere("pergunta sem nada a ver nao acha nada",
          B.procurar(indice, "qual a capital da franca") == [],
          str([a["pedaco"]["titulo"] for a in B.procurar(indice, "qual a capital da franca")]))

p.secao("\n4. o bloco de FATOS cabe no prompt e traz a fonte")
r = B.fatos_para_o_modelo(indice, "qual o ip de producao do falcao")
p.confere("o IP certo esta dentro", "10.20.30.40" in r["texto"], r["texto"][:120])
p.confere("o do vizinho nao veio junto", "10.90.1.2" not in r["texto"])
p.confere("cabe no teto", len(r["texto"]) <= B.TETO_DOS_FATOS, str(len(r["texto"])))
p.confere("diz de onde tirou", r["fontes"] and r["fontes"][0]["fonte"] == "confluence:101",
          str(r["fontes"]))
p.confere("sem achado, nao inventa contexto",
          B.fatos_para_o_modelo(indice, "qual a capital da franca")["texto"] == "")
p.confere("nota fraca nao vira fato",
          B.fatos_para_o_modelo(indice, "producao", nota_minima=99)["texto"] == "")

p.secao("\n5. texto grande vira pedacos com costura")
grande = "\n".join(f"linha numero {i} sobre o assunto" for i in range(300))
pedacos = B.partir_em_pedacos(grande, "Documento grande")
p.confere("partiu", len(pedacos) > 1, str(len(pedacos)))
p.confere("nenhum pedaco passa do teto",
          all(len(x["texto"]) <= B.LETRAS_POR_PEDACO for x in pedacos))
p.confere("a costura repete o fim do anterior",
          pedacos[0]["texto"][-40:] in pedacos[1]["texto"] or len(pedacos) < 2)

p.secao("\n6. acervo vazio nao quebra")
vazio = B.montar([])
p.confere("indice vazio", vazio["quantos"] == 0)
p.confere("busca em acervo vazio devolve nada", B.procurar(vazio, "qualquer coisa") == [])
p.confere("fatos de acervo vazio sao vazios",
          B.fatos_para_o_modelo(vazio, "qualquer coisa")["texto"] == "")

p.secao("\n7. varios times, cada um no seu espaco")
# Cada time tem o espaco dele no Confluence, e o bot ajuda os outros times tambem. Entao
# a mesma palavra aparece em dois espacos querendo dizer coisas diferentes.
MUITOS = [
    {"id": "sre-deploy", "titulo": "Deploy", "fonte": "c:1", "espaco": "SRE",
     "texto": "# Deploy\nNo SRE, deploy passa por mudanca aprovada e janela."},
    {"id": "pag-deploy", "titulo": "Deploy", "fonte": "c:2", "espaco": "PAGAMENTOS",
     "texto": "# Deploy\nEm Pagamentos, o deploy e pelo pipeline do time, sem janela."},
    {"id": "cat-fila", "titulo": "Filas do catalogo", "fonte": "c:3", "espaco": "CATALOGO",
     "texto": "# Filas\nA fila do catalogo e a rabbit-catalogo, no cluster prd-catalogo."},
]
m = B.montar(MUITOS)
p.confere("o espaco vai junto de cada pedaco",
          all(x["espaco"] for x in m["pedacos"]), str([x["espaco"] for x in m["pedacos"]]))

todos = B.procurar(m, "como funciona o deploy", 5)
p.confere("sem filtro, os dois times aparecem",
          {a["pedaco"]["espaco"] for a in todos} == {"SRE", "PAGAMENTOS"},
          str([a["pedaco"]["espaco"] for a in todos]))

so_pag = B.procurar(m, "como funciona o deploy", 5, espacos=["PAGAMENTOS"])
p.confere("com filtro, so o time pedido",
          [a["pedaco"]["espaco"] for a in so_pag] == ["PAGAMENTOS"],
          str([a["pedaco"]["espaco"] for a in so_pag]))

de_casa = B.procurar(m, "como funciona o deploy", 5, espaco_de_casa="SRE")
p.confere("o espaco de casa desempata", de_casa[0]["pedaco"]["espaco"] == "SRE",
          str([(a["pedaco"]["espaco"], a["nota"]) for a in de_casa]))
p.confere("mas nao esconde o do outro time",
          "PAGAMENTOS" in [a["pedaco"]["espaco"] for a in de_casa])

outro = B.procurar(m, "qual a fila do catalogo", 5, espaco_de_casa="SRE")
p.confere("pergunta de outro time ainda ganha do espaco de casa",
          outro[0]["pedaco"]["espaco"] == "CATALOGO", str(outro[0]["pedaco"]["espaco"]))

fatos = B.fatos_para_o_modelo(m, "qual a fila do catalogo", espaco_de_casa="SRE")
p.confere("os FATOS dizem de que espaco vieram",
          fatos["texto"].startswith("[CATALOGO:"), fatos["texto"][:40])
p.confere("a fonte devolvida tambem", fatos["fontes"][0]["espaco"] == "CATALOGO")

raise SystemExit(p.fim())
