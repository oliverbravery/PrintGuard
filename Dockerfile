FROM bluenviron/mediamtx:1.18.2 AS mediamtx

FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY docs/assets/ ../docs/assets/
RUN npm run build

FROM python:3.13-slim-trixie AS deps
ARG INFERENCE_EXTRA
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode $INFERENCE_EXTRA
COPY printguard/ printguard/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --compile-bytecode $INFERENCE_EXTRA
RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && find .venv \( -name '*.cpython-*.so' -o -name '*.abi3.so' \) -exec strip --strip-debug {} +

FROM python:3.13-slim-trixie
ARG GPU_RUNTIME_DEBS
ARG NVIDIA_VISIBLE_DEVICES
WORKDIR /app
RUN if [ -n "$GPU_RUNTIME_DEBS" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends curl \
        && curl -fsSL --remote-name-all --output-dir /tmp $GPU_RUNTIME_DEBS \
        && apt-get install -y --no-install-recommends /tmp/*.deb \
        && apt-get purge -y curl && apt-get autoremove -y && rm /tmp/*.deb; \
    fi \
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
    MEDIAMTX_CONFIG=/app/mediamtx.yml \
    NVIDIA_VISIBLE_DEVICES=$NVIDIA_VISIBLE_DEVICES \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility
VOLUME /data
EXPOSE 8000 8554
CMD ["printguard"]
