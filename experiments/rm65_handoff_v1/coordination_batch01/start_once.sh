#!/usr/bin/env bash
# Requires a NEW human grant. Never creates authorization, resets or retries.
set -euo pipefail
if [[ $# != 4 ]]; then
  echo 'usage: start_once.sh CAMPAIGN_ROOT GRANTED_AUTH FRESH_MAC_PROOF BRIDGE_CONFIG' >&2
  exit 2
fi
cd "$(cd -- "$(dirname -- "$0")/.." && pwd)"
source runtime.decision4.ubuntu-robot.sh
"$RM65_PYTHON" -m coordination_batch01.preflight --budget-root "$1" \
  --bridge-config "$4" --mac-proof "$3" --output "$1/production_preflight_RUN.json"
exec "$RM65_PYTHON" -m coordination_batch01.run --real --budget-root "$1" \
  --authorization "$2" --preflight "$1/production_preflight_RUN.json" --bridge-config "$4"
