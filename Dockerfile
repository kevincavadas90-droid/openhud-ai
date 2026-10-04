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

# Persistent state (SQLite DB, encrypted keys, workspace) lives in /data.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
CMD ["python", "-m", "openhud"]
