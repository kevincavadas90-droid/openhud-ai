#!/usr/bin/env bash
# Start the OpenHUD AI server for the public work-host demo.
#
# Reads the demo password from data/.demo_login (never printed) so no secret
# appears in process listings or logs. Serves the source ZIP on the download
# page (OPENHUD_SERVE_SOURCE) but NOT the Windows installer, because no .exe
# exists yet — the download page stays honest.
set -u
cd "$(dirname "$0")"

CRED="data/.demo_login"
if [ ! -f "$CRED" ]; then
  python -c "import secrets,pathlib; p=pathlib.Path('$CRED'); p.write_text(secrets.token_urlsafe(12)+'\n'+secrets.token_urlsafe(48)+'\n'); import os; os.chmod(p,0o600)"
fi
OPENHUD_PASSWORD="$(sed -n 1p "$CRED")"
OPENHUD_SESSION_SECRET="$(sed -n 2p "$CRED")"
export OPENHUD_PASSWORD OPENHUD_SESSION_SECRET
export OPENHUD_PORT="${OPENHUD_PORT:-12000}"
export OPENHUD_AUTH=on
export OPENHUD_SERVE_SOURCE=1
export OPENHUD_DATA_DIR="${OPENHUD_DATA_DIR:-./data}"
export OPENHUD_WORKSPACE="${OPENHUD_WORKSPACE:-./workspace}"

exec .venv/bin/python -m openhud
