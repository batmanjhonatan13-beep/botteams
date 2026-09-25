"""
A API. Um turno de conversa passa por aqui, e o desenho inteiro cabe em seis passos:

    1. abre o fio desta conversa          (a memoria e da API)
    2. o fio diz se a pergunta esta pendurada, e em que assunto
    3. a busca BM25 procura nas docs      (com o assunto junto, quando pendurada)
    4. UMA chamada ao modelo: pergunta + fatos + assunto. Sem historico.
    5. guarda o turno resumido no fio
    6. se ja deu tempo, comprime o passado em tres linhas — DEPOIS de responder

O passo 4 e o unico que fala com o modelo. Tudo que e memoria, escolha e recorte acontece
antes dele, aqui na API. E por isso que a janela do 14b nao enche.
"""
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import acervo, busca, canal, config, confluence, fio as F, memoria, modelo


@asynccontextmanager
async def ao_subir(_app):
    """Monta o acervo no arranque, em segundo plano.

    Montar na primeira pergunta faria a primeira pessoa do dia esperar a indexacao do
    Confluence inteiro em cima de um modelo que ja e lento. Em segundo plano, porque a
    API tem que responder /saude antes de o Confluence terminar de baixar."""
    threading.Thread(target=acervo.recarregar, daemon=True).start()
    memoria.limpar_velhos()
    yield


app = FastAPI(
    lifespan=ao_subir,
    title="Atendente",
    description="Bot de atendimento com memoria na API. O modelo e consultor: "
                "responde pergunta curta e esquece.",
    version="0.1.0",
)


class Pergunta(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    conversa_id: str = Field(default="avulsa", max_length=200)
    quem: str = Field(default="", max_length=200)
    # Vazio = procura em TODOS os espacos indexados. Preencher limita a estes — util
    # quando alguem pergunta "no MEU produto, como faz" e o nome bate em varios times.
    espacos: list[str] = Field(default_factory=list)
    # para depurar: devolve o prompt que foi montado, sem mandar ao modelo
    so_montar: bool = False


class Resposta(BaseModel):
    resposta: str
    assunto: str = ""
    colou: str = ""
    porque_colou: str = ""
    fontes: list[dict] = []
    olhei: str = ""
    turno: int = 0
    medida: dict = {}
    prompt: str | None = None


@app.get("/saude")
def saude():
    """Quem esta no ar e o que ele tem. Um problema de porta nao pode aparecer como
    'o modelo falhou' — a pessoa troca de modelo e nao era isso."""
    c = config.atual()
    return {
        "modelo": modelo.esta_no_ar(c),
        "modelo_configurado": c.modelo_nome,
        "acervo": acervo.retrato(),
        "confluence": confluence.conferir(c) if c.tem_confluence()
                      else {"ok": False, "porque": "nao configurado"},
        "conversas_na_memoria": memoria.quantos(),
    }


@app.get("/acervo")
def ver_acervo():
    acervo.indice()
    return acervo.retrato()


@app.get("/vivo")
def vivo():
    """Para o HEALTHCHECK do container: responde sem tocar no acervo nem no modelo."""
    return {"vivo": True}


@app.post("/acervo/recarregar")
def recarregar_acervo():
    return acervo.recarregar()


@app.get("/busca")
def ver_busca(q: str, quantos: int = 5, espaco: str = ""):
    """O que o RAG acharia para esta consulta, sem gastar o modelo. E com isto que se
    descobre se a resposta ruim veio de busca ruim ou de modelo ruim."""
    i = acervo.indice()
    achados = busca.procurar(i, q, quantos, espacos=[espaco] if espaco else None,
                             espaco_de_casa=config.atual().confluence_espaco_de_casa)
    return {"consulta": q, "achados": [
        {"nota": a["nota"], "titulo": a["pedaco"]["titulo"], "secao": a["pedaco"]["secao"],
         "fonte": a["pedaco"]["fonte"], "espaco": a["pedaco"].get("espaco", ""),
         "casou": a["casou"],
         "trecho": a["pedaco"]["texto"][:300]} for a in achados]}


@app.get("/conversa/{conversa_id}")
def ver_conversa(conversa_id: str):
    """A memoria e visivel. Se o bot entendeu o assunto errado, da para ver POR QUE."""
    f = memoria.abrir(conversa_id)
    return {
        "id": f.id, "assunto_atual": f.assunto_atual, "total_de_turnos": f.total_de_turnos,
        "resumo_do_passado": f.resumo_do_passado, "resumidos_ate": f.resumidos_ate,
        "turnos": [{"voce": t.voce, "resumo": t.resumo, "assunto": t.assunto} for t in f.turnos],
    }


@app.delete("/conversa/{conversa_id}")
def esquecer_conversa(conversa_id: str):
    return {"esqueci": memoria.esquecer(conversa_id)}


def _resumir_depois(conversa_id: str) -> None:
    """O resumo rolante roda DEPOIS de a pessoa receber a resposta. Ela nunca espera por
    ele — num 14b em CPU isso seria meio minuto de silencio a cada cinco turnos."""
    f = memoria.abrir(conversa_id)
    if not F.precisa_resumir(f):
        return
    r = modelo.perguntar("resumo", {"conversa": F.o_que_resumir(f)})
    if r.ok and r.dados:
        memoria.gravar(F.com_o_resumo(memoria.abrir(conversa_id), r.dados))


@app.post("/conversa", response_model=Resposta)
def conversar(p: Pergunta, tarefas: BackgroundTasks):
    comecou = time.time()
    c = config.atual()
    f = memoria.abrir(p.conversa_id)

    # 2. o fio: esta pergunta se sustenta sozinha, ou fala do assunto de antes?
    digesto = F.digesto_do_fio(f, p.texto)

    # 3. a busca. A consulta leva o assunto junto quando a pergunta esta pendurada:
    # "qual o IP?" nao acha nada; "produto falcao qual o IP?" acha.
    consulta = F.o_que_procurar(f, p.texto)
    indice = acervo.indice(c)
    achado = busca.fatos_para_o_modelo(indice, consulta, espacos=p.espacos,
                                       espaco_de_casa=c.confluence_espaco_de_casa)

    dados = {
        "pergunta": p.texto,
        "fatos": achado["texto"],
        "digesto": digesto["texto"],
        "perfil": c.texto_do_perfil()[:600],
    }
    if p.so_montar:
        from .perguntas import PERGUNTAS
        return Resposta(resposta="", assunto=f.assunto_atual, colou=digesto["colou"],
                        porque_colou=digesto["porque"], fontes=achado["fontes"],
                        olhei=busca.como_contar(indice, consulta), turno=f.total_de_turnos,
                        prompt=PERGUNTAS["resposta"]["monta"](dados),
                        medida={"so_montar": True})

    # 4. UMA chamada. Sem historico.
    r = modelo.perguntar("resposta", dados, c)
    if not r.ok:
        raise HTTPException(status_code=503, detail=r.porque)

    # 5. o turno vira uma linha no fio
    citou = [x["titulo"] for x in achado["fontes"]]
    memoria.gravar(F.anotar_turno(f, p.texto, r.dados, citou))

    # 6. e o passado vira tres linhas, depois de responder
    tarefas.add_task(_resumir_depois, p.conversa_id)

    return Resposta(
        resposta=r.dados,
        assunto=f.assunto_atual,
        colou=digesto["colou"],
        porque_colou=digesto["porque"],
        fontes=achado["fontes"],
        olhei=busca.como_contar(indice, consulta),
        turno=f.total_de_turnos,
        medida={**r.como_dicionario(), "segundos_no_total": round(time.time() - comecou, 2),
                "letras_de_fatos": len(achado["texto"]),
                "letras_de_digesto": len(digesto["texto"])},
    )


@app.post("/api/messages")
def mensagem_do_canal(atividade: dict, tarefas: BackgroundTasks):
    """A porta do Bot Framework Emulator. Responde 200 na hora; a resposta de verdade vai
    por outro pedido, depois do modelo — ver canal.py."""
    base = canal.para_onde(atividade)
    if not base:
        raise HTTPException(status_code=403, detail="serviceUrl fora desta maquina: esta "
                            "porta so atende o Emulator local, sem App ID")
    if canal.e_pergunta(atividade):
        tarefas.add_task(_atender_no_canal, atividade, base)
    elif canal.chegou_gente(atividade):
        tarefas.add_task(canal.enviar, atividade,
                         canal.resposta_para(atividade, "message", canal.BOAS_VINDAS), base)
    return {}


def _atender_no_canal(atividade: dict, base: str) -> None:
    """Um turno vindo do Emulator: o mesmo /conversa, com a resposta indo pelo canal."""
    canal.enviar(atividade, canal.resposta_para(atividade, "typing"), base)
    p = Pergunta(texto=canal.texto_de(atividade), conversa_id=canal.conversa_de(atividade),
                 quem=canal.quem_perguntou(atividade))
    try:
        # o resumo que o conversar agenda fica num BackgroundTasks que ninguem roda: aqui
        # ja estamos depois do 200, entao ele roda direto, embaixo
        texto = canal.texto_da_resposta(conversar(p, BackgroundTasks()))
    except HTTPException as e:
        texto = f"Nao consegui falar com o modelo agora: {e.detail}"
    canal.enviar(atividade, canal.resposta_para(atividade, "message", texto), base)
    _resumir_depois(p.conversa_id)
