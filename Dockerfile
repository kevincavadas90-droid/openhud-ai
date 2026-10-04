# OpenHUD — container image for free/cheap hosting (Render, Railway, Fly, VPS).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENHUD_HOST=0.0.0.0 \
    OPENHUD_DATA_DIR=/data

WORKDIR /app

# Install dependencies first so Docker caches this layer.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY openhud ./openhud
COPY README.md ./

# Persistent state (SQLite DB, encrypted keys, workspace, backups) lives in /data.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
# Liveness probe used by Docker/compose; /health needs no auth.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

# Single process: uvicorn serves the API, SSE, WebSocket and the SPA. The
# in-process job queue handles background work (video render, etc.).
CMD ["python", "-m", "openhud"]
