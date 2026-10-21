#!/usr/bin/env bash
# Prepared Phase 2A environment only. No downloads, SDK, cameras or hardware.
set -euo pipefail
task_root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$task_root"
output_rel=${1:?usage: bash aspire_realman_phase2a/tools/reproduce_phase2b.sh evidence/phase2b/unique-new-name}
output_path="$task_root/$output_rel"
.venv/bin/python -B -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]).resolve(); p.relative_to(pathlib.Path.cwd()); p.mkdir(parents=True,exist_ok=False)' "$output_path"
export CUDA_HOME=/usr/local/cuda-12.1
export CUDA_CACHE_PATH="$task_root/.cache/cuda"
PHASE2A_STUB_EVIDENCE="$output_path/stub-raw" PYTHON=.venv/bin/python bash aspire_realman_phase2a/tools/run_cpu_tests.sh > "$output_path/stub.log" 2>&1
.venv/bin/python -u -B aspire_realman_phase2a/tools/phase2b_geometry.py \
  --manifest evidence/model-preserved/model.json \
  --vendor /home/tongji/alex/rm65-handoff-runtime-20261014/assets/vendor/target_models_20260921 \
  --output "$output_path/geometry" > "$output_path/geometry.log" 2>&1
.venv/bin/python -u -B aspire_realman_phase2a/tools/phase2b_geometry_verify.py \
  --manifest evidence/model-preserved/model.json --report "$output_path/geometry/result.json" \
  --output "$output_path/geometry-review" > "$output_path/geometry-review.log" 2>&1
.venv/bin/python -u -B aspire_realman_phase2a/tools/native_gpu_acceptance.py \
  --manifest evidence/phase2b/model-arm-only/model.json --output "$output_path/native" \
  --warp-cubin --phase2b-controls > "$output_path/native.log" 2>&1
.venv/bin/python -u -B aspire_realman_phase2a/tools/gpu_probe.py \
  --manifest evidence/phase2b/model-arm-only-coincident/model.json --output "$output_path/cross-negative" \
  --planner --warp-cubin --expect-start-infeasible --http-gate > "$output_path/cross-negative.log" 2>&1
printf '%s\n' 'PASS ARM_ONLY_DIAGNOSTIC software chain; full assembly remains BLOCKED_PHYSICAL_GEOMETRY_EVIDENCE.'
