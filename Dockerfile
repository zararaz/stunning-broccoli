# The production image: code + serving bundle + embedding model, nothing else.
#
#   python src/export_bundle.py --city Philadelphia     # creates bundle/ (34 MB)
#   docker build -t city-guide .
#   docker run -p 7860:7860 -v city-guide-state:/app/state city-guide
#
# Everything the app needs at runtime is inside the image, so a given image
# always serves the same code, data and model, and makes no downloads at startup.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    GRADIO_ANALYTICS_ENABLED=False

WORKDIR /app

# 1. Dependencies first: this layer is cached until requirements-serve.txt changes.
#    The CPU index gives a torch build without GPU libraries (much smaller).
COPY requirements-serve.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-serve.txt

# 2. Bake in the embedding model, so containers never download it.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# 3. Data, then code (code changes most often, so it goes last).
COPY bundle/ bundle/
COPY src/ src/
COPY app.py server.py ./

# Run as an unprivileged user; /app/state is the only writable place (users' pick history).
RUN useradd --create-home appuser && mkdir -p /app/state && chown -R appuser /app/state /app/.cache
USER appuser

ENV CITY_GUIDE_DB=/app/bundle/serve.db \
    CITY_GUIDE_VECTORS=/app/bundle/vectors \
    CITY_GUIDE_APP_DB=/app/state/app.db \
    CITY_GUIDE_LLM=rules \
    HF_HUB_OFFLINE=1 \
    PORT=7860

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
