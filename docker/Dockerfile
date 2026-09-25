# A API. Nada de modelo aqui dentro: o modelo mora no servidor e e consultor.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY atendente/ ./atendente/
COPY perfil.md ./perfil.md

# a memoria das conversas e o acervo sao VOLUMES: reiniciar o container nao pode apagar o
# assunto de quem esta sendo atendido
RUN mkdir -p /app/memoria /app/acervo && \
    useradd --create-home --uid 10001 atendente && \
    chown -R atendente:atendente /app
USER atendente

ENV MEMORIA_PASTA=/app/memoria ACERVO_PASTA=/app/acervo

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/vivo',timeout=5)"

CMD ["uvicorn", "atendente.app:app", "--host", "0.0.0.0", "--port", "8080"]
