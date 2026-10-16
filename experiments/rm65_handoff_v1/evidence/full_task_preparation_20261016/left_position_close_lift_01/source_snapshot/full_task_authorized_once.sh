#!/usr/bin/env bash
# Does not grant permission, restart an episode or retry a model request.
set -euo pipefail
if [[ $# != 4 ]]; then
  echo 'usage: full_task_authorized_once.sh BATCH_ROOT GRANTED_AUTH FRESH_MAC_PROOF PRIVATE_BRIDGE_CONFIG' >&2
  exit 2
fi
cd "$(dirname -- "$0")"
source runtime.action-chunk.yanglab.sh
batch="$1"
# Never use /decide as a health check. Fresh proof bound to the same batch.
"$RM65_PYTHON" full_task_preflight.py host --budget-root "$batch" \
  --bridge-config "$4" --mac-proof "$3" --output "$batch/host_preflight_FRESH.json"
exec "$RM65_PYTHON" run_episode.py --task handoff_place_full --real \
  --budget-root "$batch" --authorization "$2" --preflight "$batch/host_preflight_FRESH.json" \
  --bridge-config "$4" --output "$batch/episode" --max-decisions 16 \
  --action-interface chunk_v2 --right-hold-control master_damping0_v3
