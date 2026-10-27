FROM bluenviron/mediamtx:1.21.2@sha256:c7540465f868a02652118bea5a0daab12a29ac0f6cb8485abd535939ecddf886 AS mediamtx

FROM python:3.14-slim-trixie@sha256:0514bc76712d64f8bb48adcb95b1ab0d88c69fee95d62fe4c18ee948bee9b1e1 AS base

FROM --platform=$BUILDPLATFORM node:26-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM base AS deps
ARG INFERENCE_EXTRA
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --compile-bytecode $INFERENCE_EXTRA
COPY printguard/ printguard/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode $INFERENCE_EXTRA
RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && find .venv \( -name '*.cpython-*.so' -o -name '*.abi3.so' \) -exec strip --strip-debug {} +

FROM base
ARG VARIANT
ARG GPU_RUNTIME_DEBS
ARG GPU_RUNTIME_DEBS_SHA256
ARG NVIDIA_VISIBLE_DEVICES
WORKDIR /app
RUN if [ -n "$GPU_RUNTIME_DEBS" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends curl \
        && curl -fsSL --remote-name-all --output-dir /tmp $GPU_RUNTIME_DEBS \
        && for deb in /tmp/*.deb; do \
            echo "$GPU_RUNTIME_DEBS_SHA256" | grep -qw "$(sha256sum "$deb" | cut -d' ' -f1)" \
            || { echo "$deb matches no checksum in GPU_RUNTIME_DEBS_SHA256" >&2; exit 1; }; \
        done \
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
COPY LICENSE.md LICENSE.md
COPY --from=web /build/web/dist static/
ENV PATH="/app/.venv/bin:$PATH" \
    PRINTGUARD_VARIANT=$VARIANT \
    PRINTGUARD_CAMERAS=auto \
    MODEL_DIR=/app/models \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    MEDIAMTX_BINARY=/usr/local/bin/mediamtx \
    MEDIAMTX_CONFIG=/app/mediamtx.yml \
    NVIDIA_VISIBLE_DEVICES=$NVIDIA_VISIBLE_DEVICES \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility
VOLUME /data
EXPOSE 8000 8554 1935
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"]
CMD ["printguard"]
