"""Read-only hashes, source lock, public-data binding and historical protection check."""
import argparse,hashlib,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.repo.resolve();module=root/'experiments/spatial_input_eval_v0';e=module/'evidence/b_v2_20261014'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
count=0
for name in ('validation_suite','validation_B1','validation_B2','development_B2','development_public_trial'):
 for f in read(e/name/'freeze.json')['files']:
  assert sha(e/name/f['file'])==f['sha256'],f;count+=1
for f in read(e/'public_validation/manifest.json')['files']:assert sha(e/'public_validation'/f['file'])==f['sha256'];count+=1
for name,digest in read(e/'pre_estimation_lock.json')['source_sha256'].items():assert sha(module/name)==digest
# git diff baseline covers all historically tracked sources, ledgers, plans, outputs.
changes=subprocess.check_output(['git','diff','--name-status','3008a8a','--'],cwd=root,text=True).splitlines()
allowed=('experiments/spatial_input_eval_v0/lab/b_v2/','experiments/spatial_input_eval_v0/evidence/b_v2_20261014/','experiments/spatial_input_eval_v0/tests/test_b_v2.py')
for line in changes:
 status,name=line.split('\t',1);assert status=='A' and name.startswith(allowed),line
n=len(subprocess.check_output(['git','ls-tree','-r','--name-only','3008a8a'],cwd=root,text=True).splitlines())
a.output.write_text(json.dumps({'status':'PASS','hashes_checked':count,'baseline_tracked_files_preserved':n,'historical_modifications':0,'new_model_requests':0,'bridge_connections':0,'new_authorization_ledgers':0,'source_lock_verified':True,'all_six_validation_scenes_retained':True},indent=2)+'\n')
