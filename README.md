# Atendente

Bot de atendimento para time de plantao. **A memória é da API, não do modelo.**

O modelo é consultor: recebe uma pergunta curta e fechada, responde, e esquece. Quem
lembra do assunto, do que já foi dito e do que a documentação diz é a FastAPI.

Isso não é estilo — é o que torna o projeto possível num 14b em CPU. Mandar a conversa
inteira a cada turno faz o prompt crescer de 400 para 6.000 fichas em dez turnos, e cada
ficha é tempo de CPU. Aqui o prompt do décimo turno tem o mesmo tamanho do primeiro.

## O que existe hoje (fase 1)

- **Conversa natural** com contexto que não se perde entre turnos.
- **RAG nas docs internas** por BM25: pasta local (o site de docs interno) e Confluence.
- **Confluence somente leitura.** Não existe no código nenhum caminho que escreva.
- **Memória visível e persistente**: dá para olhar o que o bot entendeu, e ela sobrevive
  ao reinício do container.

- **Porta do Bot Framework** (`/api/messages`) para conversar pelo Bot Framework Emulator.

Ainda **não** existe, de propósito: Teams, formulários, abertura de card, escrita no
Jira, Grafana, Kubernetes, Splunk. A fase 1 é a base sobre a qual isso tudo entra.

## Subir

```bash
cp .env.exemplo .env      # aponte MODELO_URL para o seu Ollama
docker compose up --build -d
curl -s localhost:8080/saude | python3 -m json.tool
```

Sem Docker, para desenvolver:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
MODELO_URL=http://127.0.0.1:11434 MODELO_NOME=qwen2.5:14b \
  .venv/bin/uvicorn atendente.app:app --reload --port 8080
```

## Conversar

```bash
curl -s localhost:8080/conversa -H 'content-type: application/json' \
  -d '{"conversa_id":"eu","texto":"o que e o produto falcao?"}' | python3 -m json.tool

curl -s localhost:8080/conversa -H 'content-type: application/json' \
  -d '{"conversa_id":"eu","texto":"qual o ip de producao dele?"}' | python3 -m json.tool
```

A segunda pergunta não diz "falcão". A resposta vem certa mesmo assim, e o campo `colou`
diz que a API entendeu que o assunto continua sendo o Falcão.

## As rotas

| rota | o que faz |
|---|---|
| `POST /conversa` | um turno de conversa. `{conversa_id, texto}` |
| `GET /conversa/{id}` | **a memória, visível**: assunto, turnos guardados, resumo |
| `DELETE /conversa/{id}` | esquece a conversa |
| `GET /busca?q=` | o que o RAG acharia, **sem gastar o modelo** |
| `GET /acervo` · `POST /acervo/recarregar` | o retrato do acervo e o reindex |
| `GET /saude` | modelo no ar? Confluence responde? quantos docs? |
| `POST /api/messages` | a porta do Bot Framework Emulator (ver abaixo) |
| `GET /docs` | o Swagger, de graça pelo FastAPI |

`POST /conversa` com `"so_montar": true` devolve **o prompt que iria para o modelo**, sem
chamá-lo. É com isso que se descobre se a resposta ruim veio de busca ruim ou de modelo
ruim.

## Conversar pelo Bot Framework Emulator (Windows)

O Emulator fala o protocolo do Bot Framework: ele manda a mensagem em `/api/messages`, a
API responde `200` na hora e a resposta volta depois, num POST da API para o Emulator.
Por isso o "digitando" aparece antes, e a resposta chega quando o modelo terminar.

**1. Suba a API** direto no Windows, sem Docker — é o caminho mais simples, porque API e
Emulator ficam no mesmo `localhost`. No PowerShell, na pasta do projeto:

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:MODELO_URL  = "http://127.0.0.1:11434"   # o Ollama
$env:MODELO_NOME = "qwen2.5:14b"              # como o `ollama list` mostra
.venv\Scripts\uvicorn atendente.app:app --reload --port 8080
```

Confira em `http://localhost:8080/saude` que `modelo.ok` é `true`.

**2. Instale o Emulator:** baixe o `BotFramework-Emulator-*-windows-setup.exe` em
<https://github.com/microsoft/BotFramework-Emulator/releases>.

**3. Conecte:** *Open Bot* e preencha

| campo | valor |
|---|---|
| Bot URL | `http://localhost:8080/api/messages` |
| Microsoft App ID | *(vazio)* |
| Microsoft App password | *(vazio)* |

Ao conectar chega a mensagem de boas-vindas — é o sinal de que a porta e a volta
funcionam, sem gastar o modelo. Cada conversa do Emulator tem a sua memória (o
`conversation.id` dele); *Restart conversation* começa do zero, e `GET /conversa/{id}`
mostra o que o bot entendeu.

**Com a API no Docker Desktop**, acrescente ao `.env`:

```
EMULADOR_HOST=host.docker.internal
```

O Emulator diz "responda em `http://localhost:PORTA`", e o `localhost` de dentro do
container não é o do Windows; isto troca só o nome, mantendo a porta. Se a resposta não
chegar, o log do container diz `canal: nao consegui responder em ...` — aí o caminho sem
Docker, acima, é o que resolve.

**O que esta porta não faz:** ela não confere assinatura (JWT) nem pede token para
responder — é o modo do Emulator sem App ID. Por isso ela só responde para um endereço
desta máquina (`localhost`, `127.0.0.1`, `::1`) e recusa o resto com `403`. O Teams de
verdade precisa das duas coisas, e entra noutra fase.

## Como um turno funciona

```
  1. abre o fio desta conversa          (a memória é da API)
  2. o fio diz se a pergunta está pendurada, e em que assunto
  3. a busca BM25 procura nas docs      (com o assunto junto, quando pendurada)
  4. UMA chamada ao modelo: pergunta + fatos + assunto. Sem histórico.
  5. guarda o turno resumido no fio
  6. se já deu tempo, comprime o passado em três linhas — DEPOIS de responder
```

O passo 3 merece atenção: *"qual o IP?"* não acha nada em documentação nenhuma. A API
manda *"produto falcao qual o IP?"* para a busca, porque ela sabe o assunto. A memória
não serve só para o modelo — ela é o que faz o RAG achar.

Os tetos que impedem a janela de encher:

| o quê | teto |
|---|---|
| assunto + o que já foi dito | 400 letras |
| resumo do passado | 300 letras |
| fatos da documentação | 1.800 letras |
| turnos guardados | 6 (o resto vira resumo) |
| janela (`num_ctx`) | a **menor** que couber o prompt, até `MODELO_JANELA_MAXIMA` |

O `num_ctx` importa mais do que parece: o padrão do Ollama é 2048, e prompt maior que
isso é **cortado em silêncio pelo servidor** — e o que se perde é sempre o começo, que é
justamente onde estão os FATOS.

## Outro time usando isto

Nada de time nenhum está escrito no código:

1. `perfil.md` — quem é o time e como ele responde.
2. `acervo/` — a documentação interna dele (exporte o site interno para cá).
3. `.env` — o Confluence dele, o modelo dele.

São três arquivos. O código é o mesmo.

## Quantas conversas ao mesmo tempo

Duas partes, com tetos muito diferentes. `testes/carga.py` mede as duas.

**A API não é o gargalo.** Com um acervo de 600 páginas (2.400 pedaços, o tamanho de três
Confluences de time), medido nesta máquina:

| ao mesmo tempo | turnos/s | mediana por turno |
|---|---|---|
| 1 | 81 | 12 ms |
| 4 | 83 | 45 ms |
| 32 | 79 | 380 ms |

Uma busca no acervo inteiro leva **4,3 ms** (p95 7 ms). Indexar as 600 páginas leva 0,1 s.
Nada disso depende de GPU, então esses números valem no seu servidor também.

**O gargalo é o modelo, e o número dele é da sua máquina.** Rode a bancada lá:

```bash
.venv/bin/python testes/carga.py --com-modelo --url http://SEU-SERVIDOR:11434
```

E ajuste o Ollama do servidor para atender em paralelo:

```bash
OLLAMA_NUM_PARALLEL=2       # duas pessoas ao mesmo tempo
OLLAMA_MAX_LOADED_MODELS=1  # um modelo só; em 32 GB sem GPU, dois não cabem bem
OLLAMA_KEEP_ALIVE=-1        # não descarregue: recarregar 9 GB em CPU custa caro
```

### Por que a janela é fixa em 4096

Medido contra o Ollama: chamadas seguidas com o **mesmo** `num_ctx` levam ~8 s; quando o
`num_ctx` muda entre chamadas, a mesma chamada leva **20 a 28 s**, porque o Ollama
reconstrói o runner do modelo. Num servidor sem GPU isso é pior ainda.

Por isso a janela não acompanha o prompt de perto: ela fica parada em 4096 e só sobe
quando o prompt não cabe mesmo. Janela maior custa memória de KV, não custa conta — o
tempo de geração depende das fichas que existem, não do tamanho da janela reservada.
Trocar de janela a cada turno era otimizar a coisa barata pagando com a cara.

Os oito turnos da conversa de exemplo pedem `4096` nos oito.

## Provas

```bash
.venv/bin/python testes/rodar_tudo.py
```

Seis provas, nenhuma precisa de modelo nem de rede — o modelo, o Confluence e o Emulator
entram por injeção. Elas rodam em milissegundos e cobrem: a memória (assunto, pergunta
pendurada, lista que sobrevive, resumo rolante), a busca (acento, plural, camelCase, IP, o
vizinho que não pode vir junto), a forma das perguntas, a API de ponta a ponta, a porta do
Emulator (a resposta pela volta, a trava do endereço local) e a leitura do Confluence —
incluindo a conferência de que **não existe POST, PUT ou DELETE** naquele arquivo.

E a bancada, que conversa com o modelo de verdade e mede o tamanho do prompt ao longo de
oito turnos:

```bash
.venv/bin/python testes/conversa_real.py
```

## De onde vem este desenho

Do `dragon_ia`, um editor que roda contra modelos locais pequenos. Lá a memória-na-API
(lá, memória-no-editor) foi medida contra 4.000 cadeias de conversa. Três coisas foram
portadas inteiras para cá:

- **A pergunta pendurada.** Só colar o assunto quando a pergunta não tem sujeito próprio.
  Colar sempre faz a pergunta nova herdar o assunto velho — o mesmo defeito ao contrário.
- **A lista sobrevive.** Quando a resposta é uma lista, a lista *é* o conteúdo. Guardar só
  a primeira frase fazia o turno seguinte — que fala de um item dela — responder "não sei".
- **Nenhum prompt manda o modelo se recusar.** Numa bateria de 400 cadeias, 31 respostas
  vieram como "Não sei." — e a causa era uma linha do próprio prompt dizendo "se não
  souber, diga que não sabe". Modelo pequeno obedece ao pé da letra.
