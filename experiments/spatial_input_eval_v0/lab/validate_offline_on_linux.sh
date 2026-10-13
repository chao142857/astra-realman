#!/usr/bin/env bash
# CPU/data/fixture checks only. No renderer, bridge deployment or model generation.
set -euo pipefail
if [[ $# != 1 ]]; then echo 'Usage: validate_offline_on_linux.sh NEW_OUTPUT_DIRECTORY' >&2; exit 2; fi
LAB_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODULE_DIR=$(cd -- "$LAB_DIR/.." && pwd)
REPO_DIR=$(cd -- "$MODULE_DIR/../.." && pwd)
PYTHON_EXE=${SPATIAL_VALIDATE_PYTHON:-python3}
mkdir -- "$1"
OUT=$(cd -- "$1" && pwd)
export PYTHONPATH="$MODULE_DIR"
"$PYTHON_EXE" -B - "$OUT" "$REPO_DIR" <<'PY'
import sys,platform,json,subprocess,hashlib
from pathlib import Path
from importlib.metadata import version
out,repo=map(Path,sys.argv[1:]);module=repo/'experiments/spatial_input_eval_v0'
seal=json.loads((module/'evidence/pilot02_freeze_20261013/artifact_seal.json').read_text())
bad=[p for p,h in seal['entries'].items() if hashlib.sha256((repo/p).read_bytes()).hexdigest()!=h]
assert not bad,bad
assert not subprocess.check_output(['git','diff','--name-only','--diff-filter=MDRT','b103ee5','--'],cwd=repo,text=True).strip()
record={'status':'PASS','platform':platform.platform(),'python':sys.version,'python_executable':sys.executable,
 'packages':{x:version(x) for x in ['numpy','Pillow','jsonschema']},
 'checkpoint_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
 'frozen_entries_verified':len(seal['entries']),'baseline_changed_files':[],
 'commands':['python -B -m unittest discover -s experiments/spatial_input_eval_v0/tests -v',
 'python -B lab/pilot02_verify.py --suite evidence/pilot02_preview_20261013/suite_v2 --output NEW/acceptance'],
 'real_generation_requests':0,'hardware_connections':0}
(out/'environment_and_integrity.json').write_text(json.dumps(record,indent=2)+'\n')
PY
set +e
"$PYTHON_EXE" -B -m unittest discover -s "$MODULE_DIR/tests" -v > "$OUT/unit_tests.log" 2>&1
TEST_RC=$?
"$PYTHON_EXE" -B "$LAB_DIR/pilot02_verify.py" --suite "$MODULE_DIR/evidence/pilot02_preview_20261013/suite_v2" --output "$OUT/acceptance" > "$OUT/verify.log" 2>&1
VERIFY_RC=$?
set -e
"$PYTHON_EXE" -B - "$OUT" "$TEST_RC" "$VERIFY_RC" "$REPO_DIR" <<'PY'
import sys,json,re,hashlib,subprocess
from pathlib import Path
out=Path(sys.argv[1]);test_rc,verify_rc=map(int,sys.argv[2:4]);repo=Path(sys.argv[4]);module=repo/'experiments/spatial_input_eval_v0'
log=(out/'unit_tests.log').read_text();n=re.search(r'Ran (\d+) tests',log)
seal=json.loads((module/'evidence/pilot02_freeze_20261013/artifact_seal.json').read_text())
bad=[p for p,h in seal['entries'].items() if hashlib.sha256((repo/p).read_bytes()).hexdigest()!=h]
assert not bad,bad
assert not subprocess.check_output(['git','diff','--name-only','--diff-filter=MDRT','b103ee5','--'],cwd=repo,text=True).strip()
record={'status':'PASS' if test_rc==0 and verify_rc==0 else 'FAIL','unit_test_return_code':test_rc,
 'unit_test_count':int(n.group(1)) if n else None,'verification_return_code':verify_rc,
 'all_frozen_hashes_unchanged_after_tests':True,'real_generation_requests':0,'hardware_connections':0,
 'original_ledgers_unchanged':True,'old_batch_next_or_wave_executed':False,
 'rendering':'Original yanglab suite_v2 RGB-D/GT reused and independently reverified; no rerender or data replacement'}
(out/'acceptance_summary.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record));sys.exit(0 if record['status']=='PASS' else 1)
PY
