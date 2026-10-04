#!/usr/bin/env bash
# Start OpenHUD. Creates the venv and installs dependencies on first run.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Criando ambiente virtual..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python -m openhud
