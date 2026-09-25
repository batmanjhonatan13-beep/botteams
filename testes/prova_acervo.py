"""
Prova de onde vem a documentacao: a pasta local e o Confluence.

Nada aqui abre rede: `pegar` entra por fora. O que esta sob prova e a leitura — e a
garantia que o dono pediu com todas as letras: nada de escrita no Atlassian.
"""
import inspect
import shutil
from pathlib import Path

from comum import Prova
from atendente import acervo, config, confluence

p = Prova("acervo")

p.secao("1. Confluence e SOMENTE LEITURA — por estrutura, nao por aviso")
fonte = inspect.getsource(confluence)
p.confere("nenhum POST no arquivo", 'method="POST"' not in fonte and "'POST'" not in fonte)
p.confere("nenhum PUT", 'method="PUT"' not in fonte)
p.confere("nenhum DELETE", 'method="DELETE"' not in fonte)
p.confere("a unica porta para a rede e GET", fonte.count('method="GET"') == 1,
          str(fonte.count('method="GET"')))
p.confere("sem credencial nao tenta nada", confluence.paginas(config.Config()) == [])

p.secao("\n2. o storage format do Confluence vira texto com secoes")
html = ("<h2>Enderecos</h2><p>O IP e <strong>10.1.2.3</strong></p>"
        "<ul><li>producao</li><li>homologacao</li></ul>"
        "<ac:structured-macro ac:name='info'><p>aviso</p></ac:structured-macro>"
        "<script>alert(1)</script>")
t = confluence.texto_de_html(html)
p.confere("o cabecalho virou secao", t.startswith("## Enderecos"), t[:40])
p.confere("o IP sobreviveu", "10.1.2.3" in t)
p.confere("a lista virou linhas", "- producao" in t and "- homologacao" in t, t)
p.confere("o script foi fora", "alert" not in t)
p.confere("a macro nao deixou lixo", "ac:" not in t)

p.secao("\n3. as paginas viram documentos com fonte clicavel")
c = config.Config(confluence_url="https://empresa.atlassian.net/wiki",
                  confluence_usuario="eu@empresa.com", confluence_token="x",
                  confluence_espacos=["SRE", "ENG"], confluence_paginas=2)
pedidos = []
def pegar_falso(caminho, parametros):
    pedidos.append((caminho, parametros))
    if parametros.get("start", 0) > 0:
        return {"results": []}
    return {"results": [
        {"id": "555", "title": "Produto Falcao", "space": {"key": "SRE"},
         "body": {"storage": {"value": "<h2>Enderecos</h2><p>IP 10.20.30.40</p>"}}},
        {"id": "556", "title": "Pagina vazia", "space": {"key": "SRE"},
         "body": {"storage": {"value": ""}}},
    ]}
docs = confluence.paginas(c, pegar=pegar_falso)
p.confere("trouxe a pagina com conteudo", len(docs) == 1, str(len(docs)))
p.confere("a pagina vazia nao entra no indice", all(d["texto"] for d in docs))
p.confere("o titulo e o da pagina", docs[0]["titulo"] == "Produto Falcao")
p.confere("a fonte e um link", docs[0]["fonte"].startswith("https://empresa.atlassian.net/wiki"),
          docs[0]["fonte"])
p.confere("filtrou pelos espacos configurados", "SRE" in pedidos[0][1]["cql"], pedidos[0][1]["cql"])
p.confere("pediu o corpo junto", "body.storage" in pedidos[0][1]["expand"])
p.confere("respeitou o teto de paginas", pedidos[0][1]["limit"] <= 2, str(pedidos[0][1]["limit"]))

p.secao("\n4. a pasta local: o site de docs interno entra por aqui")
raiz = Path("/tmp/prova-acervo-pasta")
shutil.rmtree(raiz, ignore_errors=True)
(raiz / "k8s").mkdir(parents=True)
(raiz / "k8s" / "runbook-pods.md").write_text(
    "# Pods em CrashLoop\nOlhe os eventos.\n", encoding="utf-8")
(raiz / "produtos.html").write_text(
    "<h1>Produtos</h1><p>O Falcao responde em 10.20.30.40</p>", encoding="utf-8")
(raiz / "foto.png").write_bytes(b"\x89PNG\r\n")
locais = acervo.da_pasta(config.Config(pasta_do_acervo=str(raiz)))
nomes = sorted(d["titulo"] for d in locais)
p.confere("leu os dois arquivos de texto", len(locais) == 2, str(len(locais)))
p.confere("nao leu o binario", "foto" not in " ".join(nomes), str(nomes))
p.confere("o titulo sai do cabecalho", "Pods em CrashLoop" in nomes, str(nomes))
p.confere("html vira texto", any("10.20.30.40" in d["texto"] for d in locais))
p.confere("a fonte e o caminho relativo",
          any(d["fonte"] == "k8s/runbook-pods.md" for d in locais),
          str([d["fonte"] for d in locais]))
p.confere("pasta que nao existe nao quebra",
          acervo.da_pasta(config.Config(pasta_do_acervo="/tmp/nao-existe-mesmo")) == [])
shutil.rmtree(raiz, ignore_errors=True)

raise SystemExit(p.fim())
