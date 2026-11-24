# Imagem única do Léo (Maratona Docker, DK1). Todas as peças Python usam esta imagem;
# muda só o comando de cada serviço no docker-compose.yml.
# Versões fixadas: a imagem base pelo número exato e os pacotes pelo requirements.txt.

# --- Etapa 1: instala os pacotes num ambiente separado (fica fora da imagem final) ---
FROM python:3.13.9-slim-trixie AS pacotes

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/leo
COPY requirements.txt /tmp/requirements.txt
RUN /opt/leo/bin/pip install -r /tmp/requirements.txt

# --- Etapa 2: imagem final, só com o Python, os pacotes e o código ---
FROM python:3.13.9-slim-trixie

ENV PATH=/opt/leo/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=UTC \
    FOTOS_PASTA=/app/fotos_deposito

# Usuário comum (sem poder de administrador). Número fixo (1000) para os volumes.
RUN groupadd --gid 1000 leo \
 && useradd --uid 1000 --gid leo --home-dir /app --no-create-home --shell /usr/sbin/nologin leo

COPY --from=pacotes /opt/leo /opt/leo

WORKDIR /app
COPY --chown=leo:leo . /app

# Pastas que viram volumes (banco de vetores, depósito de fotos, logs): do usuário leo.
RUN mkdir -p /app/chroma_db /app/fotos_deposito /app/logs /app/.streamlit \
 && chown -R leo:leo /app/chroma_db /app/fotos_deposito /app/logs /app/.streamlit

USER leo

# O comando de cada peça vem do docker-compose.yml.
CMD ["python", "-c", "print('Escolha a peça no docker-compose.yml.')"]
