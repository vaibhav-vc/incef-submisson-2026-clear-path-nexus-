# Nexus RailGuard / India Rail AI - production image.
#   docker build -t railguard india_rail_ai
#   docker compose -f india_rail_ai/docker-compose.railguard.yml up -d
# Data is never baked in: third-party datasets are fetched and built at the deployment site into the
# /app/data volume (see DEPLOYMENT.md), so the image itself redistributes nothing.
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RAILGUARD_LOG_JSON=1

WORKDIR /app
COPY requirements.txt .
# Runtime only: no test tools, and no paid-assistant SDK (that assistant is opt-in and off in this image).
# Behind a TLS-inspecting proxy, pass its CA as a build secret (never disable verification):
#   docker build --secret id=proxy_ca,src=/path/to/ca.pem ...
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi \
    && grep -vE '^(pytest|httpx|ruff|anthropic)==' requirements.txt > /tmp/runtime.txt \
    && pip install --no-cache-dir -r /tmp/runtime.txt \
    && rm /tmp/runtime.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin railguard \
    && mkdir -p /app/data /app/models /state /audit \
    && chown railguard /app/data /app/models /state /audit

COPY india_rail ./india_rail
COPY pyproject.toml README.md ./

USER 10001
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health/live', timeout=4).status == 200 else 1)"]
# No uvicorn access log (it would print query strings, where a cab's token can travel); the service writes its
# own JSON access log with route templates only. One worker: the twin is in-process state with a single writer. Availability comes from a hot standby that
# restores the shared checkpoint, not from several writers.
CMD ["uvicorn", "india_rail.api:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1", "--no-server-header", "--no-access-log", \
     "--timeout-graceful-shutdown", "20"]
