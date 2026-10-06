#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ASTRA_PYTHON:-python3}"
exec "$PY" -I -B "$ROOT/scripts/prepare_diagnostic_controls.py" "$@"
