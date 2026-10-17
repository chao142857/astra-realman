#!/usr/bin/env python3
"""Read archived evidence only. No SDK/model imports or action execution."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parallel_history import compact
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
rows=[];hashes={}
for n in range(10,17):
 step=a.run/f'step-{n:03d}';row={'step':n,'readbacks':{}}
 for rel in ['input/observation.json','pre-execution/observation.json','left/preflight-1/state/observation.json','left/between-channels/observation.json','left/after/observation.json']:
  f=step/rel
  if not f.exists():continue
  b=f.read_bytes();hashes[str(f.relative_to(a.run))]=hashlib.sha256(b).hexdigest();o=json.loads(b)
  row['readbacks'][rel]=compact(o['canonical_states']['left'])
 for name in ['proposed_group.json','diagnostics.json','left/execution_result.json']:
  f=step/name;b=f.read_bytes();hashes[str(f.relative_to(a.run))]=hashlib.sha256(b).hexdigest();row[name]=json.loads(b)
 for f in sorted((step/'input').glob('camera-*.png')):hashes[str(f.relative_to(a.run))]=hashlib.sha256(f.read_bytes()).hexdigest()
 rows.append(row)
r13=rows[3]
assert r13['left/execution_result.json']['executed_action']['gripper'] is None
assert r13['readbacks']['input/observation.json']['opening_raw']==436
assert r13['readbacks']['left/between-channels/observation.json']['opening_raw']==300
assert r13['readbacks']['input/observation.json']['gripper_telemetry']['dof_state']==3
with a.output.open('x') as f:json.dump({'source':str(a.run),'source_hashes':hashes,'rows':rows,'motion_or_model_calls':0},f,ensure_ascii=False,indent=2)
print('PASS: steps10–16 preserved; D13 no new grip command, 436→300 during arm channel. No grasp inference.')
