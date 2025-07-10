# Dockerfile for PrintGuard

# ---- Builder Stage ----
FROM python:3.13-slim AS builder

WORKDIR /app

RUN pip install --upgrade pip setuptools wheel

COPY pyproject.toml .
COPY printguard/ printguard/

RUN pip install --no-cache-dir .

# ---- Final Stage ----
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    dbus-x11 \
    gnome-keyring \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docker/ /app/docker/
RUN chmod +x /app/docker/entrypoint.sh

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/printguard /usr/local/bin/printguard

COPY --chown=appuser:appuser printguard/model/ /app/printguard/model/

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["printguard"]
