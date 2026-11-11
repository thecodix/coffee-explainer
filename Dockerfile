# API image for Google Cloud Run (built by GitHub Actions, published to ghcr.io). The embedding model is downloaded at build time so a cold start does not fetch 220 MB.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is reused while only the code changes.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY explainer_data ./explainer_data
COPY coffee_api ./coffee_api
COPY db ./db

# Bake the embedding model into the image (same model the loader used; override with --build-arg).
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
RUN python -c "import os; from explainer_data.embed import FastEmbedder; FastEmbedder(os.environ['EMBEDDING_MODEL']).embed(['warm-up'])"

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

# Cloud Run passes the port in $PORT (8080 by default).
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn coffee_api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
