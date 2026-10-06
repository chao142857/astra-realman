#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$HERE/experiment.sh" --phase placement --max-steps 10 --wall-budget-s 480 "$@"
