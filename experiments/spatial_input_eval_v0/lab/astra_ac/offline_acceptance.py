"""Loopback fixture only. Original HTTP handler's infer is replaced before listen."""
import argparse,copy,json,socket,subprocess,tempfile
from pathlib import Path
from unittest.mock import patch
from astra_ac import runtime as r,dispatch as d
from pilot02_mock import mock_bridge

def controls(job):
 row=next(x for x in r.read(r.PLAN/'task_catalog.json') if x['scene']==job['scene'])
 return r.read((r.M/row['private_snapshot']).parent/'private/design_and_controls.json')
def fixed_strategies():
 rows=[]
 for scene in r.read(r.PLAN/'task_catalog.json'):
  snapshot=r.read(r.M/scene['private_snapshot']);target=snapshot['ground_truth']['objects'][0];task=scene['task'];region=next(b for b in snapshot['ground_truth']['regions'] if b['id']=='task_volume');goal=region['center_m']
  # No search, private witness, estimated geometry, or geometry-dependent repair.
  preds={'public_center_initial_orientation':{'object_id':'target','position_m':goal,'quaternion_wxyz':target['quaternion_wxyz'],'waypoints_m':[goal] if task['kind']=='path' else []}}
  if task['kind']=='path':
   start=task['constraints']['start_position_m']
   for sign in (-1,1):preds[f'fixed_side_{sign}']={'object_id':'target','position_m':goal,'quaternion_wxyz':target['quaternion_wxyz'],'waypoints_m':[[start[0],sign*.215,.11],[goal[0],sign*.215,.11],goal]}
  else:preds['public_center_world_yaw_zero']={'object_id':'target','position_m':goal,'quaternion_wxyz':[1.,0.,0.,0.],'waypoints_m':[]}
  rows.append({'scene':scene['scene'],'strategies':{n:{'prediction':p,'score':r.r.score(snapshot,task,p,scene['task_policy'])} for n,p in preds.items()},'initial_orientation_source':'GT initial pose as a perception-free baseline; not an RGB agent, not a target solution','no_generation':True})
 return rows

def main(output):
 output.mkdir(parents=True,exist_ok=False);r.frozen();d.prepare(output/'mock_batch')
 # Absolute path fixture outputs live under /tmp/astra-ac-*; no real-mode grant is made.
 state=d.load(output/'mock_batch');state.update(mode='OFFLINE_FIXTURE',status='READY');r.save(output/'mock_batch/ledger.json',state)
 real_connect=socket.socket.connect
 def local_only(sock,address):
  if not isinstance(address,tuple) or address[0]!='127.0.0.1' or address[1] in (18766,18767):raise AssertionError('PRODUCTION_NETWORK_FORBIDDEN')
  return real_connect(sock,address)
 with patch('subprocess.Popen',side_effect=AssertionError('MODEL_PROCESS_FORBIDDEN')),patch('socket.socket.connect',local_only),mock_bridge(output) as server:
  def runner(job,folder):
   # Deliberately include valid zero scores in each repeat, no answer correction.
   spec=controls(job);pred=next(iter(spec['negative_controls'].values())) if job['index'] in (3,15) else spec['witness'];server['raw']=json.dumps(pred)
   on_disk=r.read(output/'mock_batch/ledger.json');assert on_disk['runs'][-1]['status']=='RESERVED' and on_disk['reserved_budget']==job['index']
   return r.perform(job,folder,server['config'],offline=True)
  with r.lock():final=d.advance(output/'mock_batch',state,runner,24)
  assert final['status']=='COMPLETE' and final['reserved_budget']==24 and server['decide_calls']==server['stub_calls']==24 and server['cancel_calls']==0
  assessments=[x['assessment'] for x in final['runs']]
  assert len({x['thread_id'] for x in assessments})==len({x['request_id'] for x in assessments})==24
  assert [x['assessment']['score'] for x in final['runs'] if x['index'] in (3,15)]==[0.,0.]
  for row in final['runs']:
   folder=output/'mock_batch'/row['artifact'];assert r.read(folder/'assessment.json')==r.read(folder/'independent_rescore.json');assert r.read(folder/'response.json')['model_calls']==0
  assert len(r.read(output/'mock_batch/paired_results.json'))==12
  r.save(output/'summary.json',{'status':'PASS','mock_HTTP_dispatches':24,'fake_infer_calls':24,'unique_request_ids':24,'unique_ephemeral_thread_ids':24,'pairs':12,'valid_geometric_zero_indices':[3,15],'independent_rescores':24,'retries':0,'real_generation_requests':0,'production_bridge_connections':0,'new_real_authorizations':0,'cache_semantics':'fixture cache field absent -> null, never filled with zero; raw usage retained','scope':'independent client calls verified under mock; future real calls must pass same ID and ephemeral command checks; upstream generation count not measurable'})
 r.save(output/'fixed_strategy_controls.json',fixed_strategies())
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
