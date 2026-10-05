#!/usr/bin/env bash
# Thin interactive launcher: delegates to the existing three-view loop.
set -euo pipefail
ROOT=/home/tongji/alex/astra_realman_harness
PY=/home/tongji/miniconda3/envs/dp/bin/python
mode=shadow
print_only=0
while (($#)); do
  case "$1" in
    shadow|execute) mode="$1" ;;
    --print-command) print_only=1 ;;
    -h|--help)
      echo "Usage: ./run_official_astra_threeview.sh [shadow|execute] [--print-command]"
      echo "shadow: real observation, no actuation (default)"
      echo "execute: existing real execution mode, up to 50 steps"
      echo "Task is read interactively by the existing runner; STOP or Ctrl-C cancels."
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
"$PY" -I -B -c 'import json; c=json.load(open("/home/tongji/alex/astra_realman_harness/config/decision_backend.json")); assert c.get("backend")=="CodexAstraBackend" and c.get("model")=="gpt-6-astra", "Official backend not selected"'
cmd=("$PY" -I -B "$ROOT/scripts/run_left_terminal.py" --live --model gpt-6-astra --max-steps 50)
if [[ "$mode" == execute ]]; then cmd+=(--execute); fi
printf 'MODE: %s | cameras: left_wrist, tabletop, overhead | backend: CodexAstraBackend | model: gpt-6-astra
' "$mode"
if ((print_only)); then printf '%q ' "${cmd[@]}"; printf '
'; exit 0; fi
# No --task: preserve the runner's existing verbatim terminal task prompt.
exec "${cmd[@]}"
