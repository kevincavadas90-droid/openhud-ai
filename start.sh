#!/usr/bin/env bash
# OpenHUD launcher — idempotent. Brings up everything the app needs:
#   1. the Python environment (venv + deps)
#   2. a local Ollama server + a small model (keyless, unlimited fallback)
#   3. the OpenHUD web server
# Safe to run repeatedly; already-running pieces are left alone.
#
# Usage:  ./start.sh            (background, logs to ./openhud.log)
#         OPENHUD_FG=1 ./start.sh   (foreground)
set -u
cd "$(dirname "$0")"

export OPENHUD_PASSWORD="${OPENHUD_PASSWORD:-hud-demo-2026}"
export OPENHUD_PORT="${OPENHUD_PORT:-12000}"
export OPENHUD_HOST="${OPENHUD_HOST:-0.0.0.0}"
export OPENHUD_DATA_DIR="${OPENHUD_DATA_DIR:-$PWD/data}"
export OPENHUD_WORKSPACE="${OPENHUD_WORKSPACE:-$PWD/workspace}"

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
OLLAMA_URL="http://127.0.0.1:11434"

log() { echo "[start] $*"; }

# --- 1. Python environment -------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  log "criando venv e instalando dependências…"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt >/dev/null
fi

# --- 2. Ollama (keyless local model) --------------------------------------
install_ollama() {
  command -v ollama >/dev/null 2>&1 && return 0
  log "Ollama não encontrado; baixando binário (sem curl|bash)…"
  python3 -m pip install -q zstandard 2>/dev/null || true
  local tgz=/tmp/ollama.tar.zst
  curl -sL -m 900 -o "$tgz" \
    "https://github.com/ollama/ollama/releases/download/v0.35.1/ollama-linux-amd64.tar.zst" || return 1
  python3 - "$tgz" <<'PY'
import sys, zstandard, tarfile, tempfile
with open(sys.argv[1], "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as r, tempfile.TemporaryFile() as t:
    while (c := r.read(1 << 22)):
        t.write(c)
    t.seek(0)
    tarfile.open(fileobj=t, mode="r:").extractall("/tmp/ollama_extract")
PY
  sudo cp -r /tmp/ollama_extract/bin/* /usr/local/bin/ 2>/dev/null || cp -r /tmp/ollama_extract/bin/* "$HOME/.local/bin/" 2>/dev/null
  sudo cp -r /tmp/ollama_extract/lib/* /usr/local/lib/ 2>/dev/null || true
}

if install_ollama && command -v ollama >/dev/null 2>&1; then
  if ! curl -s -m 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    log "iniciando ollama serve…"
    nohup ollama serve >/tmp/ollama_serve.log 2>&1 &
    for _ in $(seq 1 20); do curl -s -m 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1 && break; sleep 1; done
  fi
  if curl -s -m 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    if ! ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
      log "baixando modelo $OLLAMA_MODEL…"
      ollama pull "$OLLAMA_MODEL" >/tmp/ollama_pull.log 2>&1 || log "falha ao baixar o modelo (seguindo sem Ollama)"
    fi
  fi
fi

# --- 3. OpenHUD web server -------------------------------------------------
if curl -s -m 3 "http://127.0.0.1:$OPENHUD_PORT/api/health" >/dev/null 2>&1; then
  log "OpenHUD já está rodando na porta $OPENHUD_PORT"
  exit 0
fi

log "iniciando OpenHUD na porta $OPENHUD_PORT (senha: $OPENHUD_PASSWORD)"
if [ "${OPENHUD_FG:-0}" = "1" ]; then
  exec .venv/bin/python -m openhud
else
  nohup .venv/bin/python -m openhud > ./openhud.log 2>&1 &
  sleep 4
  curl -s -m 5 "http://127.0.0.1:$OPENHUD_PORT/api/health" && echo
  log "pronto. URL local: http://127.0.0.1:$OPENHUD_PORT  |  log: ./openhud.log"
fi
