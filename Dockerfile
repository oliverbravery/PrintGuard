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

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser

VOLUME /data

COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/printguard /usr/local/bin/printguard

COPY --chown=appuser:appuser printguard/model/ /app/printguard/model/

EXPOSE 8000

CMD ["printguard"]
