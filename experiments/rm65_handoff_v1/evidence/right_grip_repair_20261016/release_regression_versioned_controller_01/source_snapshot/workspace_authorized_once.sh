#!/usr/bin/env bash
# Future authorization only. This script never grants permission or retries.
set -euo pipefail
if [[ $# != 4 ]]; then
  echo 'usage: workspace_authorized_once.sh BATCH_ROOT GRANTED_AUTH FRESH_PREFLIGHT BRIDGE_CONFIG' >&2
  exit 2
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$script_dir"
source runtime.decision4.ubuntu-robot.sh
batch="$1"
"$RM65_PYTHON" run_episode.py --task shared_workspace_yield_v1 \
  --budget-root "$batch" --authorization "$2" --preflight "$3" --bridge-config "$4" \
  --output "$batch/shadow_01" --mode shadow --real
"$RM65_PYTHON" -c 'import json,sys; from pathlib import Path; b=Path(sys.argv[1]); s=json.loads((b/"ledger.json").read_text()); e=json.loads((b/"shadow_01/episode.json").read_text()); assert s["status"]=="READY" and s["shadow_validated"] and s["reserved_budget"]==1 and e["status"]=="SHADOW_VALID_NO_EXECUTION"' "$batch"
# New simulator/reset, empty history. The gate independently rechecks the same
# batch's unique valid shadow, fresh preflight and remaining 7-request budget.
"$RM65_PYTHON" run_episode.py --task shared_workspace_yield_v1 \
  --budget-root "$batch" --authorization "$2" --preflight "$3" --bridge-config "$4" \
  --output "$batch/execute_01" --mode execute --max-decisions 7 --real
