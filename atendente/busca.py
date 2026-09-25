"""
A busca nas docs internas: BM25 sobre os pedacos, sem modelo de embed.

Por que BM25 e nao vetor: o servidor onde isto roda nao tem GPU. Gerar embedding de
milhares de paginas de Confluence num CPU e caro na indexacao e caro em toda pergunta, e
o 14b ja esta lento. BM25 e busca por palavra: custa uma passada de regex, roda em
milissegundos e nao gasta chamada nenhuma ao modelo.

E, para documentacao interna, palavra e o que a pessoa usa mesmo: ela pergunta "qual o IP
do produto Falcao", e a doc diz "Falcao" e diz "IP". Quem procura documentacao procura
pelo NOME da coisa.

Este arquivo e a porta do simbolos.js do dragon_ia, onde a mesma nota BM25 foi medida:
num projeto de 37 arquivos, escolher o arquivo certo pelo pedido tirou 25% das chamadas
ao modelo. Aqui o trabalho e o mesmo — escolher o pouco que cabe no prompt.

Modulo puro: entra [{id, titulo, fonte, texto}], sai ordem. Nao le disco, nao abre rede.
"""
import math
import re
import unicodedata

# k1 e b do BM25, os valores de sempre. k1 segura a repeticao; b desconta pedaco grande.
K1 = 1.2
B = 0.75

# Quanto do acervo pode ir no prompt. O teto existe pelo mesmo motivo de sempre: o modelo
# esta em CPU, e cada ficha a mais e segundo a mais de espera.
TETO_DOS_FATOS = 1800
PEDACOS_POR_RESPOSTA = 3
# Abaixo disto nao e achado, e barulho: mandar um pedaco que nao fala do assunto e pior
# do que nao mandar nada, porque o modelo tenta usar.
NOTA_MINIMA = 1.5

# Letras por pedaco. Pedaco grande dilui a nota e estoura o prompt; pedaco pequeno demais
# perde a frase que responde.
LETRAS_POR_PEDACO = 900
LETRAS_DE_COSTURA = 120

PALAVRAS_VAZIAS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "sobre", "ao",
    "e", "ou", "que", "se", "mais", "menos", "muito", "ser", "sao", "esta", "estao",
    "tem", "ter", "foi", "era", "seu", "sua", "isso", "isto", "ele", "ela", "eles",
    "elas", "esse", "essa", "este", "aquele", "eu", "voce", "vc", "nao", "sim", "ja",
    "qual", "quais", "quando", "onde", "quem", "como", "porque", "pq", "quanto",
    "quero", "queria", "preciso", "pode", "poderia", "saber", "favor", "obrigado",
    "the", "of", "to", "in", "on", "and", "for", "is", "are", "this", "that", "with",
    "pagina", "paginas", "doc", "docs", "documentacao", "confluence", "wiki",
}


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or ""))
                   if unicodedata.category(c) != "Mn")


def raiz(palavra: str) -> str:
    """Corte de plural, o minimo que faz "servidores" achar "servidor". Nada de stemmer de
    verdade: em nome de produto, cortar demais junta coisas que nao sao a mesma."""
    p = str(palavra or "")
    if len(p) > 4 and p.endswith(("oes", "aes", "ais", "eis")):
        return p[:-3] + "ao"
    if len(p) > 4 and p.endswith("es"):
        return p[:-2]
    if len(p) > 3 and p.endswith("s"):
        return p[:-1]
    return p


def pedacos_de_texto(texto: str) -> list[str]:
    """As palavras que contam. camelCase e snake_case quebram, porque nome de servico vem
    dos dois jeitos: `pagamentoApi`, `pagamento_api` e "pagamento api" sao a mesma coisa."""
    bruto = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", sem_acento(texto)).lower()
    achados = re.split(r"[^a-z0-9.]+", bruto)
    saida = []
    for p in achados:
        # IP e versao nao podem perder o ponto: 10.20.30.40 e uma palavra so
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){2,3}", p) or re.fullmatch(r"\d+\.\d+(?:\.\d+)?", p):
            saida.append(p)
            continue
        for parte in p.split("."):
            if len(parte) > 1 and parte not in PALAVRAS_VAZIAS:
                saida.append(raiz(parte))
    return saida


# --------------------------------------------------------------- partir em pedacos
CABECALHO = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


def partir_em_pedacos(texto: str, titulo: str = "") -> list[dict]:
    """Um pedaco por secao. O titulo da secao vai junto do corpo porque e ele que diz do
    que a secao fala — e e por ele que a busca acha.

    Sem cabecalho nenhum, parte por tamanho, com costura entre os pedacos: a frase que
    responde a pergunta nao pode morrer no corte."""
    linhas = str(texto or "").replace("\r\n", "\n").split("\n")
    secoes: list[dict] = []
    atual = {"secao": titulo, "linhas": []}
    for linha in linhas:
        m = CABECALHO.match(linha)
        if m:
            if atual["linhas"]:
                secoes.append(atual)
            atual = {"secao": m.group(2).strip(), "linhas": []}
        else:
            atual["linhas"].append(linha)
    if atual["linhas"]:
        secoes.append(atual)

    saida: list[dict] = []
    for s in secoes:
        corpo = "\n".join(s["linhas"]).strip()
        if not corpo:
            continue
        if len(corpo) <= LETRAS_POR_PEDACO:
            saida.append({"secao": s["secao"], "texto": corpo})
            continue
        passo = LETRAS_POR_PEDACO - LETRAS_DE_COSTURA
        for i in range(0, len(corpo), passo):
            parte = corpo[i:i + LETRAS_POR_PEDACO].strip()
            if parte:
                saida.append({"secao": s["secao"], "texto": parte})
    return saida


# --------------------------------------------------------------- montar o indice
def montar(documentos: list[dict]) -> dict:
    """documentos: [{id, titulo, fonte, texto}] -> o indice inteiro.

    Custa uma passada por documento e zero chamadas ao modelo."""
    pedacos: list[dict] = []
    df: dict[str, int] = {}
    for d in documentos or []:
        titulo = str(d.get("titulo") or "")
        for p in partir_em_pedacos(d.get("texto") or "", titulo):
            # o titulo do documento e a secao contam duas vezes: quem pergunta usa o nome
            # da coisa, e o nome da coisa mora no titulo
            palavras = (pedacos_de_texto(titulo) * 2 + pedacos_de_texto(p["secao"]) * 2 +
                        pedacos_de_texto(p["texto"]))
            if not palavras:
                continue
            tf: dict[str, int] = {}
            for w in palavras:
                tf[w] = tf.get(w, 0) + 1
            pedacos.append({
                "documento": d.get("id") or titulo,
                "titulo": titulo,
                "fonte": d.get("fonte") or "",
                # de que time e esta doc. Cada time tem o espaco dele no Confluence, e a
                # mesma palavra ("deploy", "banco", "fila") quer dizer coisas diferentes em
                # cada um. Sem dizer de onde veio, a resposta vira boato.
                "espaco": d.get("espaco") or "",
                "secao": p["secao"],
                "texto": p["texto"],
                "tf": tf,
                "tamanho": len(palavras),
            })
            for termo in tf:
                df[termo] = df.get(termo, 0) + 1
    media = (sum(p["tamanho"] for p in pedacos) / len(pedacos)) if pedacos else 1.0
    return {"pedacos": pedacos, "df": df, "quantos": len(pedacos), "tamanho_medio": media,
            "documentos": len(documentos or [])}


def _idf(indice: dict, termo: str) -> float:
    n = indice["quantos"]
    d = indice["df"].get(termo, 0)
    # o +1 de dentro do log nunca deixa a nota ficar negativa quando o termo esta em todos
    # os pedacos — sem ele, um termo comum EMPURRA o pedaco certo para baixo
    return math.log(1 + (n - d + 0.5) / (d + 0.5))


# Quanto a doc do PROPRIO time vale a mais. Pequeno de proposito: e desempate, nao
# censura. Se a resposta certa esta no espaco de outro time, ela tem que vir assim mesmo —
# foi para isso que o acervo passou a ler os espacos de todos.
EMPURRAO_DE_CASA = 1.15


def procurar(indice: dict, consulta: str, quantos: int = PEDACOS_POR_RESPOSTA,
             espacos: list[str] | None = None, espaco_de_casa: str = "") -> list[dict]:
    termos = list(dict.fromkeys(pedacos_de_texto(consulta)))
    if not indice or not indice.get("quantos") or not termos:
        return []
    so_estes = {e.strip().upper() for e in (espacos or []) if e.strip()}
    de_casa = str(espaco_de_casa or "").strip().upper()
    notas = []
    for p in indice["pedacos"]:
        if so_estes and str(p.get("espaco", "")).upper() not in so_estes:
            continue
        nota = 0.0
        casou = []
        for termo in termos:
            tf = p["tf"].get(termo, 0)
            if not tf:
                continue
            baixo = tf + K1 * (1 - B + B * (p["tamanho"] / indice["tamanho_medio"]))
            nota += _idf(indice, termo) * (tf * (K1 + 1)) / baixo
            casou.append(termo)
        if nota > 0:
            if de_casa and str(p.get("espaco", "")).upper() == de_casa:
                nota *= EMPURRAO_DE_CASA
            notas.append({"nota": round(nota, 3), "casou": casou, "pedaco": p})
    notas.sort(key=lambda x: (-x["nota"], x["pedaco"]["titulo"]))
    return notas[:quantos]


def sem_os_piores(achados: list[dict]) -> list[dict]:
    """Tira o pedaco que casou MENOS palavras que o melhor, e nenhuma a mais.

    O caso que obrigou esta regra: "qual o ip de producao do falcao" trazia junto a secao
    de enderecos do GAVIAO — ela casa `ip` e `producao`, so nao casa `falcao`. As duas
    secoes falam de IP de producao; a diferenca inteira e a palavra que diz DE QUEM. Com
    as duas no prompt, o modelo tem dois IPs para escolher e nenhuma razao para preferir o
    certo. Um IP errado numa crise e pior do que "nao achei na documentacao".

    Quem casou tudo que o melhor casou continua: duas secoes do mesmo produto sao duas
    partes da mesma resposta."""
    if len(achados) < 2:
        return achados
    do_topo = set(achados[0]["casou"])
    return [achados[0]] + [a for a in achados[1:] if not set(a["casou"]) < do_topo]


def fatos_para_o_modelo(indice: dict, consulta: str, teto: int = TETO_DOS_FATOS,
                        quantos: int = PEDACOS_POR_RESPOSTA,
                        nota_minima: float = NOTA_MINIMA,
                        espacos: list[str] | None = None,
                        espaco_de_casa: str = "") -> dict:
    """O bloco de FATOS que vai no prompt, e as fontes para devolver junto da resposta.

    Devolve {texto, fontes}. Quando nada passa da nota minima, devolve texto vazio: o
    modelo entao responde do que ele sabe, e a API diz que nao achou na documentacao.
    Inventar contexto e pior do que nao ter contexto."""
    achados = [a for a in procurar(indice, consulta, quantos, espacos, espaco_de_casa)
               if a["nota"] >= nota_minima]
    achados = sem_os_piores(achados)
    if not achados:
        return {"texto": "", "fontes": []}
    partes, fontes, letras = [], [], 0
    for a in achados:
        p = a["pedaco"]
        cabeca = p["titulo"] + (f" › {p['secao']}" if p["secao"] and p["secao"] != p["titulo"] else "")
        if p.get("espaco"):
            cabeca = f"{p['espaco']}: {cabeca}"
        bloco = f"[{cabeca}]\n{p['texto'].strip()}"
        if letras + len(bloco) > teto and partes:
            break
        partes.append(bloco)
        letras += len(bloco)
        fontes.append({"titulo": p["titulo"], "secao": p["secao"], "fonte": p["fonte"],
                       "espaco": p.get("espaco", ""), "nota": a["nota"]})
    return {"texto": "\n\n".join(partes), "fontes": fontes}


def como_contar(indice: dict, consulta: str) -> str:
    """Para o log e para a resposta: o que eu procurei, e o que achei."""
    achados = procurar(indice, consulta, 3)
    if not achados:
        return ""
    quais = ", ".join(a["pedaco"]["titulo"] for a in achados)
    palavras = ", ".join(dict.fromkeys(w for a in achados for w in a["casou"]))[:60]
    return f"olhei {quais} (pelas palavras: {palavras})"
