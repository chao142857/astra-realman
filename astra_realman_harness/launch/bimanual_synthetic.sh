#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x /home/tongji/miniconda3/envs/dp/bin/python ]]; then PY=/home/tongji/miniconda3/envs/dp/bin/python; else PY=python3; fi
exec "$PY" -I -B "$ROOT/scripts/run_bimanual_synthetic.py" "$@"
