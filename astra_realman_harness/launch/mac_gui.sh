#!/usr/bin/env bash
# Start the lab GUI, tunnel it locally, and open the browser. Model bridge remains separate.
set -euo pipefail
LAB_HOST="${ASTRA_LAB_HOST:-yanglab}"
LAB_ROOT="${ASTRA_LAB_ROOT:-/home/tongji/alex/astra_history_prep_20261007/astra_realman_harness}"
PORT="${ASTRA_GUI_PORT:-8877}"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo 'ASTRA_GUI_PORT must be numeric' >&2; exit 2; }
[[ "$LAB_ROOT" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo 'ASTRA_LAB_ROOT contains unsupported shell characters' >&2; exit 2; }
if command -v open >/dev/null; then (sleep 2; open "http://127.0.0.1:$PORT") & fi
exec ssh -T -L "$PORT:127.0.0.1:$PORT" -o ExitOnForwardFailure=yes "$LAB_HOST" \
  "cd '$LAB_ROOT' && exec bash launch/gui.sh --port '$PORT'"
