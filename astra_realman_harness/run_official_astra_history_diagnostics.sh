#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PY="${ASTRA_PYTHON:-/home/tongji/miniconda3/envs/dp/bin/python}"
mode=shadow
print_only=0
args=()
if [[ "${1:-}" == shadow || "${1:-}" == execute ]]; then mode="$1"; shift; fi
if [[ "${1:-}" == --print-command ]]; then print_only=1; shift; fi
args=("$@")
cmd=("$PY" -I -B "$ROOT/scripts/run_left_history_diagnostics.py" --live)
if [[ "$mode" == execute ]]; then cmd+=(--execute); fi
cmd+=("${args[@]}")
if ((print_only)); then printf '%q ' "${cmd[@]}"; printf '\n'; exit 0; fi
exec "${cmd[@]}"
