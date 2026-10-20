#!/usr/bin/env bash
# Official sealed-photo inference only: no camera owner, robot SDK, or Agent task.
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PHASE1A=/home/tongji/alex/aspire_realman_phase1a_20261020
cd "$TASK_ROOT"
export HF_HUB_OFFLINE=1
export XDG_CACHE_HOME="$TASK_ROOT/.cache/sam3-runtime/xdg"
export TORCH_HOME="$TASK_ROOT/.cache/sam3-runtime/torch"
export TORCH_EXTENSIONS_DIR="$TASK_ROOT/.cache/sam3-runtime/torch-extensions"
export TRITON_CACHE_DIR="$TASK_ROOT/.cache/sam3-runtime/triton"
export TORCHINDUCTOR_CACHE_DIR="$TASK_ROOT/.cache/sam3-runtime/inductor"
export CUDA_CACHE_PATH="$TASK_ROOT/.cache/sam3-runtime/cuda"
mkdir -p "$XDG_CACHE_HOME" "$TORCH_HOME" "$TORCH_EXTENSIONS_DIR" \
  "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$CUDA_CACHE_PATH"
"$PHASE1A/.sam3-venv/bin/python" -B \
  "$TASK_ROOT/aspire_realman_phase1a/tools/sam3_real_photo.py" \
  --image "$PHASE1A/evidence/live-final/last/rgb.png" \
  --image-sha256 cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06 \
  --snapshot "$PHASE1A/evidence/live-final/last/snapshot.json" \
  --checkpoint "${1:?Usage: bash run_sealed_sam3.sh CHECKPOINT [NEW_REPORT]}" \
  --output "${2:-evidence/sam3-real-$(date -u +%Y%m%dT%H%M%SZ).json}" \
  --prompt banana \
  --prompt-evidence 'Visible yellow banana on left desk in manually inspected sealed RGB; no task execution' \
  --native-http --aspire-source "$PHASE1A/.cache/ASPIRE"
