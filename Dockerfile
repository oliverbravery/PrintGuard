FROM bluenviron/mediamtx:1.18.2 AS mediamtx

FROM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY docs/assets/ ../docs/assets/
RUN npm run build

FROM python:3.13-slim AS deps
ARG INFERENCE_EXTRA
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --compile-bytecode $INFERENCE_EXTRA
COPY printguard/ printguard/
RUN uv sync --frozen --no-dev --compile-bytecode $INFERENCE_EXTRA

FROM python:3.13-slim
WORKDIR /app
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then apt-get update && apt-get install -y --no-install-recommends intel-opencl-icd ocl-icd-libopencl1; fi \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deps /app/.venv .venv
COPY --from=mediamtx /mediamtx /usr/local/bin/mediamtx
COPY printguard/ printguard/
COPY models/ models/
COPY mediamtx.yml mediamtx.yml
COPY THIRD_PARTY_NOTICES.md THIRD_PARTY_NOTICES.md
COPY --from=web /build/web/dist static/
ENV PATH="/app/.venv/bin:$PATH" \
    MODEL_DIR=/app/models \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    MEDIAMTX_BINARY=/usr/local/bin/mediamtx \
    MEDIAMTX_CONFIG=/app/mediamtx.yml
VOLUME /data
EXPOSE 8000 8554 1935
CMD ["printguard"]
