#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$HERE/experiment.sh" --phase full-pick-place --max-steps 50 --wall-budget-s 1200 "$@"
