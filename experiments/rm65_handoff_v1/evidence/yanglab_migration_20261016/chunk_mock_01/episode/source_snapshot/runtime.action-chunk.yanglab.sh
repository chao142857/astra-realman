#!/usr/bin/env bash
# Source in the current simulation subprocess only. No machine/global changes.
_rm65_chunk_runtime_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$_rm65_chunk_runtime_dir/runtime.sh"
export RM65_LAYOUT="$_rm65_chunk_runtime_dir/scene_v4_ready_transfer_1100.json"
export RM65_CONTROLLER=urdf_effort_hold_v2
export RM65_SOLVER=original
unset _rm65_chunk_runtime_dir
