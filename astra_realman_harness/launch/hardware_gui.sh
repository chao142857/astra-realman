#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/launch/gui.sh" --hardware-console \
 --three-calibration /home/tongji/alex/astra_onsite_1011/astra_realman_harness/config/engineering/three_camera_calibration_20261011.json \
 --lock-path /tmp/astra-realman-gui-episode.lock --port 8888 "$@"
