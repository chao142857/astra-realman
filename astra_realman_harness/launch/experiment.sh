#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${ASTRA_PYTHON:-}" ]]; then PY="$ASTRA_PYTHON"
elif [[ -x /home/tongji/miniconda3/envs/dp/bin/python ]]; then PY=/home/tongji/miniconda3/envs/dp/bin/python
else PY=python3; fi
cmd=("$PY" -I -B "$ROOT/scripts/run_experiment.py")
[[ -z "${ASTRA_SETTINGS:-}" ]] || cmd+=(--settings "$ASTRA_SETTINGS")
[[ -z "${ASTRA_PROFILE:-}" ]] || cmd+=(--profile "$ASTRA_PROFILE")
[[ -z "${ASTRA_MODE:-}" ]] || cmd+=(--mode "$ASTRA_MODE")
[[ -z "${ASTRA_TASK:-}" ]] || cmd+=(--task "$ASTRA_TASK")
[[ -z "${ASTRA_MAX_STEPS:-}" ]] || cmd+=(--max-steps "$ASTRA_MAX_STEPS")
[[ -z "${ASTRA_WALL_BUDGET_S:-}" ]] || cmd+=(--wall-budget-s "$ASTRA_WALL_BUDGET_S")
exec "${cmd[@]}" "$@"
