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
COPY printguard/ printguard/
COPY models/ models/
COPY --from=web /build/dist static/
ENV PATH="/app/.venv/bin:$PATH" \
    MODEL_DIR=/app/models \
    DATA_DIR=/data \
    STATIC_DIR=/app/static
VOLUME /data
EXPOSE 8000
CMD ["printguard"]
