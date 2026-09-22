# Backend del asistente (Fase 11): un contenedor SIEMPRE ENCENDIDO que reemplaza a la laptop de desarrollo.
# Solo expone /health y /telegram/webhook (interfaces/api_server.py); nunca abre PDFs ni hace OCR.
#
# El modelo de embeddings y el ÍNDICE se preparan DURANTE EL BUILD, nunca al arrancar (evita sumarle a un arranque en
# frío ya lento -en el plan gratuito elegido, Render- una descarga de ~500 MB o una indexación de varios minutos):
#   * el modelo se descarga y queda en la caché de Hugging Face dentro de la imagen (capa RUN de abajo).
#   * el índice se CONSTRUYE en la imagen a partir de data/processed/ (versionado en git); data/index/ NO está en git
#     (se regenera siempre, aquí y en el CI de la Fase 9), así que este paso es indispensable, no un atajo.
#
# Host elegido (ver README, "Fase 11"): Render, plan gratuito. Requiere escuchar en 0.0.0.0:$PORT (variable que Render
# fija en tiempo de ejecución) y duerme el servicio tras 15 min sin tráfico (el Worker de Cloudflare ya avisa si tarda
# en despertar). Riesgo documentado: el plan gratuito no publica su RAM exacta; si el contenedor no cabe, la alternativa
# es una imagen más liviana o un host con más memoria garantizada (ver PROGRESO.md, Fase 11).
FROM python:3.12-slim

RUN useradd -m -u 1000 app
WORKDIR /home/app/tarea1
ENV HF_HOME=/home/app/.cache/huggingface \
    TOKENIZERS_PARALLELISM=false \
    PYTHONPATH=/home/app/tarea1/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements-backend.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements-backend.txt

# Código, configuración y lo mínimo necesario para construir el índice (sin PDFs originales: no hacen falta para responder)
COPY config.yaml pricing.yaml ./
COPY src/rag_engine ./src/rag_engine
COPY src/indexing ./src/indexing
COPY interfaces ./interfaces
COPY scripts/build_index.py ./scripts/build_index.py
COPY data/processed ./data/processed

# 1. Descarga el modelo de embeddings AHORA (build), no la primera vez que alguien pregunte
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"
# 2. Construye el índice AHORA (build); es idempotente, así que reconstruir la imagen nunca deja un índice a medias
RUN python scripts/build_index.py

RUN chown -R app:app /home/app
USER app

EXPOSE 8000
# Forma shell (no exec/JSON): así se expande ${PORT}, que Render fija en tiempo de ejecución. Sin Render, usa 8000.
CMD uvicorn interfaces.api_server:app --host 0.0.0.0 --port ${PORT:-8000}
