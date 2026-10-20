#!/usr/bin/env bash
# Uses the prepared isolated environment/cache. Performs NO downloads or SDK I/O.
set -u
task_root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$task_root" || exit 1
output_rel=${1:?usage: bash aspire_realman_phase2a/tools/reproduce.sh evidence/unique-new-name}
output_path="$task_root/$output_rel"
.venv/bin/python -B -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]).resolve(); p.relative_to(pathlib.Path.cwd()); p.mkdir(parents=True,exist_ok=False)' "$output_path" || exit 1
PHASE2A_STUB_EVIDENCE="$output_path/stub-raw" PYTHON=.venv/bin/python bash aspire_realman_phase2a/tools/run_cpu_tests.sh > "$output_path/stub-tests.log" 2>&1
cpu_rc=$?
export CUDA_HOME=/usr/local/cuda-12.1
export CUDA_CACHE_PATH="$task_root/.cache/cuda"
.venv/bin/python -u -B aspire_realman_phase2a/tools/native_gpu_acceptance.py \
  --manifest evidence/model-preserved/model.json --output "$output_path/native" --warp-cubin \
  > "$output_path/native.log" 2>&1
native_rc=$?
.venv/bin/python -B -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); j={"cpu_exit":int(sys.argv[2]),"native_exit":int(sys.argv[3]),"scope":"SYNTHETIC_OFFLINE_ONLY","note":"Native exit 1 currently records actual self-collision planning rejection; not a planning PASS."}; (p/"exit-status.json").write_text(json.dumps(j,indent=2)); print(json.dumps(j))' "$output_path" "$cpu_rc" "$native_rc"
if [ "$cpu_rc" -ne 0 ]; then exit "$cpu_rc"; fi
exit "$native_rc"
