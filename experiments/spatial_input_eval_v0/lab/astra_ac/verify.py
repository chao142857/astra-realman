"""Read-only A/C release validation; cannot dispatch or authorize."""
import argparse,copy,hashlib,json
from pathlib import Path
from pilot02_runtime import validate_public
from pilot02_contract import score
from spatial_eval.schema import parse_prediction
M=Path(__file__).resolve().parents[2]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(root):
 freeze=read(root/'freeze.json')
 if (root/'release_manifest.json').exists():
  release=read(root/'release_manifest.json')
  for f in release['files']:assert sha(root/f['file'])==f['sha256'],f['file']
  for name,digest in release['sources_sha256'].items():assert sha(M/name)==digest,name
 for f in freeze['files']:assert sha(root/f['file'])==f['sha256'],f['file']
 assert sha(Path(__file__).with_name('prepare.py'))==freeze['preparer_sha256']
 order=read(root/'future_ac_order.json');assert len(order['ordered_samples'])==24
 assert order['protocol']['current_budget']==0 and not order['protocol']['generation_authorized']
 counts={};scoring=0
 for row in read(root/'task_catalog.json'):
  snapshot=read(M/row['private_snapshot']);assert sha(M/row['private_snapshot'])==row['snapshot_sha256'];a,c=[read(root/row['inputs'][k]['input_directory']/'context.json') for k in ('RGB_MULTI_VIEW','RGB_ORACLE_3D')];cc=copy.deepcopy(c);cc['geometry']=None;assert a==cc
  for k in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
   folder=root/row['inputs'][k]['input_directory'];validate_public(read(folder/'context.json'),[folder/f'image-{i}.png' for i in range(3)])
  scene=(M/row['private_snapshot']).parent;controls=read(scene/'private/design_and_controls.json')
  for pred in [controls['witness'],*controls['alternate_witnesses']]:
   p=parse_prediction(json.dumps(pred),row['task']);assert score(snapshot,row['task'],p,row['task_policy'])['success'];scoring+=1
  for pred in controls['negative_controls'].values():
   p=parse_prediction(json.dumps(pred),row['task']);assert not score(snapshot,row['task'],p,row['task_policy'])['success'];scoring+=1
 for i,j in enumerate(order['ordered_samples'],1):
  assert j['index']==i;folder=root/j['input_directory'];assert sha(folder/'context.json')==j['context_sha256'];assert [sha(folder/f'image-{n}.png') for n in range(3)]==j['rgb_sha256'];key=(j['scene'],j['condition']);counts[key]=counts.get(key,0)+1
 assert len(counts)==12 and set(counts.values())=={2}
 for pair in {j['pair_id'] for j in order['ordered_samples']}:
  jobs=[j for j in order['ordered_samples'] if j['pair_id']==pair];assert len(jobs)==2 and len({j['condition'] for j in jobs})==2;assert len({j['task_sha256'] for j in jobs})==1 and len({j['schema_sha256'] for j in jobs})==1 and len({j['policy_sha256'] for j in jobs})==1
 return {'status':'PASS','frozen_files_verified':len(freeze['files']),'jobs':24,'unique_inputs':12,'scene_count':6,'scorer_positive_negative_checks':scoring,'generation_requests':0,'bridge_connections':0,'ledgers_created':0}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(verify(a.root),indent=2))
