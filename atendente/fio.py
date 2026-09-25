"""
O fio da conversa: a API lembra o assunto, o modelo NAO recebe historico.

Este arquivo e a porta, para Python, do fio.js do dragon_ia — o editor onde esta ideia foi
medida contra 4.000 cadeias de conversa. O defeito que ele conserta e sempre o mesmo:

    voce:  "o que e o cluster de pagamentos?"      bot: (responde)
    voce:  "como ele escala?"                      bot: (responde)
    voce:  "quais sao os limites?"                 <- limites de QUE?

A terceira pergunta nao tem sujeito. Sem assunto, o modelo INVENTA um para poder
responder, e a resposta sai confiante e sobre outra coisa.

A saida nao e devolver o historico. E a API guardar, a cada turno, tres coisas curtas —
assunto, um resumo de uma linha, e o que foi citado. Da umas 60 fichas. O historico bruto
daria quatro mil, e num 14b em CPU cada ficha a mais e segundo a mais de espera.

Tres regras que valem o arquivo:

  1. So cola o assunto quando a pergunta NAO tem sujeito proprio. Colar sempre faria a
     pergunta nova herdar o assunto velho, que e o mesmo defeito ao contrario.
  2. Fio apodrece. Seis turnos, meia hora parado comeca de novo.
  3. Quando cola, DIZ que colou. Errar o assunto e barato se a pessoa ve; caro se nao ve.

Modulo puro: nao chama modelo, nao abre rede. So texto entrando e texto saindo.
"""
import re
import time
import unicodedata
from dataclasses import dataclass, field, asdict

TETO_DE_TURNOS = 6
TETO_DE_LETRAS = 400
# O resumo do que ficou para tras tem teto proprio, e pequeno. Ele existe para o modelo
# nao perder o rumo numa conversa longa — nao para devolver a conversa a ele.
TETO_DO_RESUMO = 300
# A partir de quantos turnos vale a pena gastar UMA chamada para comprimir o passado.
TURNOS_ATE_RESUMIR = 5
MINUTOS_ATE_ESFRIAR = 30

# --------------------------------------------------------------- o que nao e assunto
INTERROGATIVO_NA_FRENTE = re.compile(
    r"^\s*(?:e\s+)?(?:o\s+que|oque|que\s+que|qual|quais|quando|onde|aonde|quem|quanto s?|"
    r"quantos?|quantas?|por\s*que|porque|pq|como|sera\s+que|"
    r"me\s+(?:explica|explique|diga|fala|fale|conta|ajuda)|"
    r"explica|explique|diga|fala|conta|tem\s+como|da\s+pra|da\s+para|"
    r"vale\s+a\s+pena|voce\s+sabe|vc\s+sabe)\b", re.I)

VAZIAS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "pro", "com", "sem", "sobre",
    "e", "eh", "ou", "que", "se", "ao", "aos", "mais", "menos", "muito", "pouco",
    "ser", "sao", "esta", "estao", "tem", "ter", "foi", "era", "seu", "sua", "seus",
    "suas", "meu", "minha", "isso", "isto", "aquilo", "ele", "ela", "eles", "elas",
    "esse", "essa", "este", "aquele", "aquela", "me", "te", "lhe", "vos",
    # pronome NAO nomeia coisa nenhuma. Sem isto, "qual o ip de producao DELE?" era lido
    # como pergunta que nomeia algo ("dele"), a busca nao herdava o assunto e a consulta
    # virava "ip producao dele" — que nao acha a doc do produto. Medido contra o 14b.
    "dele", "dela", "deles", "delas", "disso", "nisso", "nele", "nela", "dessa",
    "desse", "daquele", "daquela", "ai", "la", "nesse", "nessa", "neste", "nesta",
    "eu", "voce", "vc", "tu", "nao", "sim", "ja", "ainda", "agora", "aqui", "ali", "la",
    "quero", "queria", "gostaria", "preciso", "pode", "poderia", "saber", "detalhes",
    "detalhe", "exemplo", "exemplos", "coisa", "coisas", "favor", "por favor",
    "bom", "boa", "dia", "tarde", "noite", "oi", "ola", "obrigado", "obrigada",
    # saudacao nao e assunto. Sem isto, "oi, tudo bem?" abria a conversa com o assunto
    # "tudo bem", e a pergunta seguinte — que pendura no assunto — herdava aquilo.
    "tudo", "bem", "blz", "beleza", "entao", "cara", "gente", "pessoal", "galera",
    "ajuda", "ajudar", "duvida", "pergunta", "seguinte", "rapido", "rapidinho",
    # "em producao precisa de alguma coisa antes?" virava o assunto "producao precisa
    # alguma". Verbo de necessidade e quantificador nao sao assunto de nada.
    "precisa", "precisar", "alguma", "algum", "alguns", "algumas", "alguem", "antes",
    "depois", "caso", "tambem", "outra", "outro", "outros", "outras", "mesmo", "mesma",
}

# pronome que so faz sentido apontando para algo dito antes
PRONOME_PENDURADO = re.compile(
    r"\b(ela|ele|elas|eles|isso|isto|aquilo|dela|dele|delas|deles|disso|nisso|nele|nela|"
    r"o\s+mesmo|a\s+mesma|o\s+outro|a\s+outra)\b", re.I)

# Duas familias de pergunta, e a diferenca decide tudo:
#
#   APRESENTA  "o que e X", "quem e X"      -> X e o sujeito. Isto ABRE um assunto.
#   ATRIBUTO   "quais sao os Y", "qual o Y" -> Y e uma propriedade DE alguma coisa.
#
# "qual o IP?" e atributo: IP de QUE. Sem esta divisao, a API leria "IP" como sujeito
# proprio, nao colaria assunto nenhum, e a busca nas docs procuraria por "ip" sozinho.
PERGUNTA_QUE_APRESENTA = re.compile(
    r"^\s*(?:o\s+que|oque|que\s+que)\s+(?:e|eh|sao|significa|seria)\b|"
    r"^\s*quem\s+(?:e|eh|foi)\b|"
    r"^\s*(?:me\s+)?(?:explica|explique|fala\s+sobre|conta\s+sobre)\b", re.I)

# Nome proprio de coisa concreta: um arquivo, um host, uma URL. Se sustenta sozinho.
CITA_COISA_CONCRETA = re.compile(
    r"\b[\w.-]+\.(?:py|js|ts|java|go|rb|php|ya?ml|json|md|sh|sql|log|conf|tf)\b|"
    r"\bhttps?://|\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[a-z0-9-]+\.(?:com|net|org|br|io|local|svc)\b", re.I)

PERGUNTA_DE_ATRIBUTO = re.compile(
    r"^\s*(?:e\s+)?(?:quais|qual|quantos?|quantas?|como|quando|onde|aonde|por\s*que|porque|pq)\b|"
    r"^\s*(?:e\s+)?o\s+que\s+(?:eu\s+)?(?:devo|faco|preciso|posso|teria|tenho|uso|usar|fazer)\b", re.I)

PEDE_MAIS = re.compile(
    r"^\s*(?:e\s|mais\b|continua|continue|segue|prossiga|detalha|detalhe|melhor\b|"
    r"explica\s+melhor|de\s+novo|outro\s+exemplo)", re.I)

# "o 1 da lista", "o terceiro", "o primeiro deles": a frase aponta para um item do que ja
# foi respondido. Sem o que veio antes ela nao existe.
# O ordinal so aponta para um item quando ele E um item: "o primeiro", "o 1 da lista".
# Sem o determinante na frente, "o que eu olho primeiro?" era lido como "o primeiro da
# lista" — medido numa conversa de verdade, onde a pergunta sobre CrashLoopBackOff herdou
# o assunto do turno anterior por causa da palavra "primeiro".
APONTA_PARA_ITEM = re.compile(
    r"\b(?:da|na|de|a|essa|dessa|aquela)\s+lista\b|\bo\s+\d{1,2}\b|"
    r"\b(?:o|a|os|as)\s+(?:primeir|segund|terceir|quart|quint|sext|setim|oitav|non|decim|ultim)[oa]s?\b|"
    r"\bdeles\b|\bdelas\b|\bdesses\b|\bdessas\b", re.I)

# Palavras que so existem EM RELACAO a outra coisa: dono DE, IP DE, limite DE. Elas nunca
# sao o assunto sozinhas, mesmo numa pergunta que tem forma de apresentacao.
#
# "quem e o dono?" tem a forma de "quem e X", que normalmente ABRE um assunto novo. Mas
# "dono" nao e coisa nenhuma: e dono de alguma coisa. Sem esta lista, uma conversa sobre
# o produto Falcao passava a ter o assunto "dono", e os tres turnos seguintes — que eram
# sobre Kubernetes — colavam "dono" em cima. Medido contra o modelo de verdade.
RELACIONAL = {
    "dono", "donos", "responsavel", "responsaveis", "time", "times", "squad", "equipe",
    "ip", "ips", "endereco", "enderecos", "url", "porta", "portas", "host", "dominio",
    "versao", "versoes", "status", "estado", "limite", "limites", "prazo", "prazos",
    "custo", "custos", "valor", "valores", "tamanho", "quantidade",
    "causa", "causas", "motivo", "motivos", "impacto", "risco", "riscos",
    "passo", "passos", "regra", "regras", "requisito", "requisitos", "criterio",
    "problema", "problemas", "solucao", "solucoes", "alternativa", "alternativas",
    "diferenca", "diferencas", "vantagem", "vantagens", "desvantagem", "desvantagens",
    "tipo", "tipos", "forma", "formas", "funcao", "funcoes", "objetivo", "objetivos",
    "dependencia", "dependencias", "config", "configuracao", "parametro", "parametros",
    "log", "logs", "metrica", "metricas", "alerta", "alertas", "painel", "dashboard",
    "chamado", "chamados", "card", "cards", "fila", "filas", "banco", "bancos",
    # ambiente e ambiente DE alguma coisa: "qual o ip de producao?" nao diz de que produto
    "producao", "prod", "homologacao", "homolog", "desenvolvimento", "dev", "staging",
}

PEDE_DE_NOVO = re.compile(
    r"\b(?:de\s+novo|novamente|repet\w+|resum\w+|mais\s+(?:curto|simples|resumido|claro|detalhad\w+)|"
    r"em\s+(?:uma|duas|tres|\d+)\s+linhas|de\s+outro\s+jeito|reformul\w+|simplific\w+)\b", re.I)

ITEM_DE_LISTA = re.compile(r"^\s*(?:\d{1,2}[.)\-]|[-*•])\s+(.{2,80}?)\s*$")
BLOCO_DE_CODIGO = re.compile(r"```[\s\S]*?```")


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or ""))
                   if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", sem_acento(texto)).lower().strip()


def palavras_cheias(texto: str) -> list[str]:
    """O que sobra quando saem o interrogativo e as palavras vazias. E isso que decide se
    a pergunta tem sujeito proprio."""
    limpo = INTERROGATIVO_NA_FRENTE.sub(" ", normalizar(texto))
    limpo = re.sub(r"[^a-z0-9\s-]", " ", limpo)
    return [p for p in limpo.split() if len(p) >= 3 and p not in VAZIAS]


def assunto_do_texto(texto: str) -> str:
    """O substantivo principal da frase, por forma — sem modelo. Nao e analise gramatical:
    e o que sobra depois de tirar interrogativo e palavra vazia, limitado a tres."""
    cheias = palavras_cheias(texto)
    return " ".join(cheias[:3]) if cheias else ""


def tem_sujeito_proprio(pergunta: str) -> bool:
    return len(palavras_cheias(pergunta)) > 0


# --------------------------------------------------------------- o fio
@dataclass
class Turno:
    quando: float
    assunto: str
    voce: str
    resumo: str
    citou: list[str] = field(default_factory=list)


@dataclass
class Fio:
    id: str = ""
    turnos: list[Turno] = field(default_factory=list)
    assunto_atual: str = ""
    quando: float = 0.0
    # total de turnos JA HAVIDOS. `turnos` para de crescer no teto de seis, entao contar o
    # tamanho da lista nunca passaria de seis — e o resumo nunca se renovaria.
    resumo_do_passado: str = ""
    resumidos_ate: int = 0
    total_de_turnos: int = 0

    def como_dicionario(self) -> dict:
        d = asdict(self)
        return d


def fio_vazio(id_da_conversa: str = "") -> Fio:
    return Fio(id=id_da_conversa)


def esfriou(fio: Fio, agora: float | None = None) -> bool:
    """A pessoa voltou amanha: o assunto nao e o de ontem."""
    if not fio.quando:
        return False
    minutos = ((agora if agora is not None else time.time()) - fio.quando) / 60.0
    return minutos > MINUTOS_ATE_ESFRIAR


def esta_pendurada(pergunta: str, fio: Fio) -> str:
    """A pergunta depende do que veio antes?

    Devolve "" quando ela se sustenta sozinha, ou o motivo quando nao. Sem turno anterior
    nao ha do que depender: a primeira pergunta nunca esta pendurada."""
    if not fio or not fio.turnos:
        return ""
    cru = str(pergunta or "").strip()
    if not cru:
        return ""

    if not tem_sujeito_proprio(cru):
        return "a pergunta nao diz do que e"
    if PEDE_MAIS.search(cru):
        return "esta pedindo mais do mesmo"
    if PEDE_DE_NOVO.search(cru):
        return "esta pedindo a mesma coisa de outro jeito"
    if APONTA_PARA_ITEM.search(sem_acento(cru)):
        return "aponta para um item do que ja foi dito"

    sobrou = palavras_cheias(cru)
    # Tudo que sobrou e palavra relacional: a pergunta nao diz DE QUE, qualquer que seja a
    # forma dela. Isto vem antes da regra de apresentacao de proposito — "quem e o dono?"
    # tem forma de apresentacao e mesmo assim nao apresenta coisa nenhuma.
    if sobrou and all(x in RELACIONAL for x in sobrou):
        return "pergunta " + " ".join(sobrou) + " de alguma coisa, e nao diz de que"

    # "o que e X" abre assunto novo e nunca esta pendurada
    if PERGUNTA_QUE_APRESENTA.search(cru):
        return ""

    # A pergunta que JA DIZ o assunto nao precisa que ninguem cole nada.
    assunto_agora = normalizar(fio.assunto_atual)
    aqui = normalizar(cru)
    if assunto_agora and any(len(p) >= 4 and p in aqui for p in assunto_agora.split()):
        return ""

    if PERGUNTA_DE_ATRIBUTO.search(cru):
        # "qual e o X?" nao diz de QUE coisa, seja X o que for — a menos que a frase cite
        # uma coisa concreta (um arquivo, um host, uma URL), que se sustenta sozinha.
        #
        # Errar para o lado de colar custa uma linha de contexto que o modelo ignora
        # quando a pergunta ja se explica. Errar para o outro custa a resposta inteira.
        if sobrou and not CITA_COISA_CONCRETA.search(cru):
            return "pergunta " + " ".join(sobrou) + " sem dizer de que"

    if PRONOME_PENDURADO.search(normalizar(cru)):
        assunto = normalizar(fio.assunto_atual)
        if not (assunto and any(len(p) >= 4 and p in aqui for p in assunto.split())):
            return "usa um pronome que aponta para o que ja foi dito"
    return ""


def resumir_resposta(resposta: str) -> str:
    """Uma linha do que foi respondido. Escrita pela API a partir do texto, com teto —
    guardar a resposta inteira seria guardar a conversa, que e o que nao se quer.

    MAS: quando a resposta e uma LISTA, a lista E o conteudo. Medido no dragon_ia:

        voce: quais servicos rodam nesse cluster?
        bot:  1. pagamentos  2. carrinho  3. catalogo
        voce: qual o dono do 1 da lista
        bot:  Nao sei qual e o servico. A lista nao foi especificada.   <- antes

    O resumo guardado tinha sido "1." — a primeira frase. Os itens, que eram a resposta
    inteira, iam para o lixo, e o turno seguinte falava justamente de um deles."""
    bruto = BLOCO_DE_CODIGO.sub(" ", str(resposta or ""))
    itens = [m.group(1) for m in (ITEM_DE_LISTA.match(l) for l in bruto.split("\n")) if m]
    if len(itens) >= 2:
        return "; ".join(f"{i + 1}. {x}" for i, x in enumerate(itens))[:200]
    limpo = re.sub(r"\s+", " ", bruto).strip()
    if not limpo:
        return ""
    primeira = re.split(r"(?<=[.!?])\s", limpo)[0] or limpo
    return primeira[:200]


def anotar_turno(fio: Fio, voce: str, resposta: str, citou: list[str] | None = None) -> Fio:
    pendurada = esta_pendurada(voce, fio)
    # pergunta pendurada NAO troca o assunto: ela e sobre o mesmo
    if pendurada:
        assunto = fio.assunto_atual or assunto_do_texto(voce)
    else:
        assunto = assunto_do_texto(voce) or fio.assunto_atual
    fio.turnos.append(Turno(
        quando=time.time(), assunto=assunto,
        voce=str(voce or "")[:200],
        resumo=resumir_resposta(resposta),
        citou=list(citou or [])[:5],
    ))
    fio.total_de_turnos += 1
    if len(fio.turnos) > TETO_DE_TURNOS:
        fio.turnos = fio.turnos[-TETO_DE_TURNOS:]
    fio.assunto_atual = assunto
    fio.quando = time.time()
    return fio


def digesto_do_fio(fio: Fio, pergunta: str) -> dict:
    """O que vai junto da pergunta — e SO quando ela precisa.

    Devolve {texto, colou, porque}. `colou` e o que a API devolve na resposta: se ela
    entendeu o assunto errado, a pessoa corrige numa palavra em vez de receber uma
    resposta certa sobre a coisa errada."""
    porque = esta_pendurada(pergunta, fio)
    if not porque or not fio.assunto_atual:
        return {"texto": "", "colou": "", "porque": ""}

    ditos = [t.resumo for t in fio.turnos[-3:] if t.resumo]
    texto = f"Assunto desta conversa: {fio.assunto_atual}."
    if fio.resumo_do_passado:
        texto += "\nAte aqui: " + fio.resumo_do_passado[:TETO_DO_RESUMO]
    if ditos:
        ja = "\nJa foi dito: " + "; ".join(ditos)
        if len(texto) + len(ja) > TETO_DE_LETRAS:
            ja = ja[: max(0, TETO_DE_LETRAS - len(texto) - 2)] + "…"
        texto += ja
    teto = TETO_DE_LETRAS + (TETO_DO_RESUMO if fio.resumo_do_passado else 0)
    return {"texto": texto[:teto], "colou": fio.assunto_atual, "porque": porque}


def nomeia_algo(pergunta: str) -> bool:
    """A pergunta traz o nome de alguma coisa, ou so palavras que existem em relacao a
    outra? "qual o ip de producao?" nao nomeia nada; "qual o ip de producao do falcao?"
    nomeia."""
    sobrou = palavras_cheias(pergunta)
    return bool(sobrou) and any(x not in RELACIONAL for x in sobrou)


def o_que_procurar(fio: Fio, pergunta: str) -> str:
    """A consulta que vai para a busca nas docs.

    Aqui esta a diferenca que a memoria faz no RAG, e ela e grande: "qual o IP?" nao acha
    nada em documentacao nenhuma. "produto falcao qual o IP?" acha.

    MAS a regra aqui e mais apertada do que a que decide o que vai para o modelo, e de
    proposito. Colar o assunto no PROMPT e barato: se a pergunta ja se explica, o modelo
    ignora a linha a mais. Colar o assunto na BUSCA nao e: "qual o ip do gaviao?" numa
    conversa sobre o Falcao viraria a consulta "produto falcao qual o ip do gaviao" — e
    a busca traria a secao errada, com o IP errado, numa crise.

    Entao aqui o assunto so entra quando a pergunta NAO nomeia coisa nenhuma."""
    if fio.assunto_atual and esta_pendurada(pergunta, fio) and not nomeia_algo(pergunta):
        return f"{fio.assunto_atual} {pergunta}".strip()
    return str(pergunta or "").strip()


# --------------------------------------------------------------- o resumo rolante
def precisa_resumir(fio: Fio) -> bool:
    """Vale a pena gastar UMA chamada para comprimir o passado desta conversa?

    O fio ja guarda pouco (seis turnos, uma linha cada). O que falta e o que veio ANTES
    desses seis: sem isto, o setimo turno apaga o primeiro e a conversa perde o comeco."""
    return fio.total_de_turnos >= TURNOS_ATE_RESUMIR and fio.total_de_turnos > fio.resumidos_ate


def o_que_resumir(fio: Fio) -> str:
    """O texto que vai para a pergunta de resumo: os turnos, curtos, mais o resumo que ja
    existia. Comprimir o comprimido e o que deixa uma conversa de cinquenta turnos caber
    em tres linhas."""
    partes = []
    if fio.resumo_do_passado:
        partes.append("Ate agora: " + fio.resumo_do_passado)
    for t in fio.turnos:
        partes.append(f"pessoa: {t.voce[:120]}")
        if t.resumo:
            partes.append(f"bot: {t.resumo[:120]}")
    return "\n".join(partes)[:1600]


def com_o_resumo(fio: Fio, texto: str) -> Fio:
    """Guarda o resumo e marca ate onde ja foi comprimido. Nao apaga turno nenhum: o teto
    de seis ja cuida disso, e o resumo e o que sobrevive quando eles caem."""
    limpo = re.sub(r"\s+", " ", str(texto or "")).strip()[:TETO_DO_RESUMO]
    if not limpo:
        return fio
    fio.resumo_do_passado = limpo
    fio.resumidos_ate = fio.total_de_turnos
    return fio


def como_contar(digesto: dict) -> str:
    return f"entendi que e sobre {digesto['colou']}" if digesto.get("colou") else ""
