#!/usr/bin/env bash
# Isolated replay runtime; no changes to existing environments or old runs.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/runtime.decision4.ubuntu-robot.sh"
export RM65_CONTROLLER=urdf_effort_hold_v2
export RM65_SOLVER=original
export RM65_LAYOUT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scene_v4_ready_transfer_1100.json"
