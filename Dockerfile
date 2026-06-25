FROM bluenviron/mediamtx:1.18.2 AS mediamtx

FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --compile-bytecode
COPY printguard/ printguard/
RUN uv sync --frozen --no-dev --compile-bytecode

FROM python:3.13-slim
WORKDIR /app
COPY --from=deps /app/.venv .venv
COPY --from=mediamtx /mediamtx /usr/local/bin/mediamtx
COPY printguard/ printguard/
COPY models/ models/
COPY mediamtx.yml mediamtx.yml
COPY THIRD_PARTY_NOTICES.md THIRD_PARTY_NOTICES.md
COPY --from=web /build/dist static/
ENV PATH="/app/.venv/bin:$PATH" \
    MODEL_DIR=/app/models \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    MEDIAMTX_BINARY=/usr/local/bin/mediamtx \
    MEDIAMTX_CONFIG=/app/mediamtx.yml
VOLUME /data
EXPOSE 8000 8554 1935
CMD ["printguard"]
