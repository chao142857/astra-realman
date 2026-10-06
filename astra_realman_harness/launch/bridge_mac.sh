#!/usr/bin/env bash
# Run on the Mac logged into Codex; retains the original yanglab loopback bridge.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ASTRA_PYTHON:-python3}" -I -B "$ROOT/scripts/codex_astra_mac_bridge.py" "$@"
