"""Offline input packaging only: no dispatcher, network, ledger or inference."""
import argparse,base64,copy,hashlib,json,sys
from pathlib import Path
from spatial_eval.schema import read,write,parse_prediction
from pilot02_runtime import validate_public,bridge_module
from pilot02_contract import score
M=Path(__file__).resolve().parents[2]
SUITE=M/'evidence/b_v2_20261014/validation_suite'
CONDITIONS=('RGB_MULTI_VIEW','RGB_ORACLE_3D')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def reject_private(value):
 if isinstance(value,dict):
  for k,v in value.items():
   if any(t in k.lower() for t in ('witness','ground_truth','negative_control','reference_path','reference_action','score','private')):raise ValueError('PRIVATE_INPUT_FIELD:'+k)
   reject_private(v)
 elif isinstance(value,list):
  for v in value:reject_private(v)
def prepare(out):
 out.mkdir(parents=True,exist_ok=False)
 for f in read(SUITE/'freeze.json')['files']:assert sha(SUITE/f['file'])==f['sha256']
 bridge=bridge_module();catalog=[];checks=[];pairs=[]
 scenes=sorted(p.name for p in SUITE.iterdir() if p.is_dir() and (p/'snapshot.json').exists());assert len(scenes)==6
 for scene in scenes:
  contexts={};bindings={}
  snapshot=read(SUITE/scene/'snapshot.json');policy=read(SUITE/scene/'task_policy.json');task=snapshot['task'][0]
  for condition in CONDITIONS:
   src=SUITE/scene/'model_inputs'/condition;dest=out/'inputs'/scene/condition;dest.mkdir(parents=True)
   for name in ('context.json','image-0.png','image-1.png','image-2.png'):(dest/name).write_bytes((src/name).read_bytes())
   ctx=read(dest/'context.json');images=[dest/f'image-{i}.png' for i in range(3)];validate_public(ctx,images);reject_private(ctx)
   assert ctx['task']==task and ctx['task_policy']==policy
   provider_schema,audit=bridge.compile_schema(ctx['output_schema'])
   payload={'context':ctx,'authoritative_schema':ctx['output_schema'],'schema':provider_schema,'images':[base64.b64encode(p.read_bytes()).decode() for p in images]}
   bridge.validate_payload(payload)  # Pure in-process check, never starts service.
   contexts[condition]=ctx
   binding={'input_directory':str(dest.relative_to(out)),'context_sha256':sha(dest/'context.json'),'rgb_sha256':[sha(p) for p in images],'task_sha256':digest(task),'policy_sha256':digest(policy),'schema_sha256':digest(ctx['output_schema']),'provider_schema_sha256':digest(provider_schema)};bindings[condition]=binding
   checks.append({'scene':scene,'condition':condition,'public_validator':'PASS','production_payload_validator':'PASS','source_bytes_identical':True,'schema_compiler_audit':audit})
  a,c=(contexts[k] for k in CONDITIONS);assert a['geometry'] is None;assert c['geometry']==snapshot['ground_truth'];c_base=copy.deepcopy(c);c_base['geometry']=None;assert a==c_base
  assert not c['geometry']['renderings'];assert set(c['geometry'])=={'source','frame','units','objects','regions','obstacles','renderings'}
  for collection in ('objects','regions','obstacles'):
   for box in c['geometry'][collection]:assert set(box)=={'id','center_m','size_m','quaternion_wxyz'}
  design=read(SUITE/scene/'private/design_and_controls.json');controls=[('witness',design['witness'])]+[(f'alternate_{i}',p) for i,p in enumerate(design['alternate_witnesses'])]+[('negative_'+k,p) for k,p in design['negative_controls'].items()]
  outcomes=[]
  for name,pred in controls:
   parsed=parse_prediction(json.dumps(pred),task);evaluated=score(snapshot,task,parsed,policy);assert evaluated['success']==(not name.startswith('negative_'));outcomes.append({'candidate_type':name,'status':evaluated['status'],'success':evaluated['success'],'error_types':evaluated['error_types']})
  catalog.append({'scene':scene,'task_kind':task['kind'],'task':task,'task_policy':policy,'public_RGB_count':3,'private_snapshot':str((SUITE/scene/'snapshot.json').relative_to(M)),'snapshot_sha256':sha(SUITE/scene/'snapshot.json'),'scorer':'pilot02_contract.score','clearance_m':.002,'validity_controls':outcomes,'inputs':bindings,'eligible':True})
  pairs.append({'scene':scene,'same_context_except_geometry':True,'C_exact_scene_geometry':True,'C_contains_reference_action_or_path':False,'depth_sent':False})
 jobs=[]
 # Two blocks; every scene receives AC then CA or CA then AC. Three of each per block.
 for repeat in (1,2):
  for si,scene in enumerate(scenes):
   order=CONDITIONS if (si+repeat)%2 else CONDITIONS[::-1]
   for condition in order:
    binding=next(x for x in catalog if x['scene']==scene)['inputs'][condition]
    jobs.append({'index':len(jobs)+1,'repeat':repeat,'pair_id':f'{scene}-r{repeat}','scene':scene,'task_id':'plan','condition':condition,**binding})
 protocol={'model':'gpt-6-astra','reasoning':'medium','backend':'existing Mac ChatGPT SSH bridge','ephemeral':True,'workers':1,'client_deadline_s':180,'server_timeout_required_s':190,'automatic_retries':0,'code_mode':'existing production configuration unchanged','generation_authorized':False,'current_budget':0,'requested_future_max_client_dispatches':24,'repetitions':2,'stop_on':['timeout','transport error','403/409','native CLI error/reconnect','unknown completion','invalid JSON','parameter drift','input integrity failure'],'valid_geometric_failure':'score zero and continue','budget_unit':'client dispatch; CLI upstream reconnects are distinct and not precisely controllable by client','old_batch_next_or_wave_allowed':False}
 write(out/'task_catalog.json',catalog);write(out/'future_ac_order.json',{'version':'astra.six_scene_ac.plan.v1','protocol':protocol,'ordered_samples':jobs});write(out/'acceptance.json',{'status':'PASS','eligible_scenes':6,'input_sets':12,'scheduled_requests':24,'real_generation_requests':0,'bridge_connections':0,'new_ledgers':0,'pair_checks':pairs,'protocol_checks':checks,'scoring_fixture_checks':sum(len(x['validity_controls']) for x in catalog),'scope':'static payload validation + original scorer fixtures, not production readiness or live bridge test'})
 write(out/'freeze.json',{'version':'astra.six_scene_ac.freeze.v1','baseline':'94b6c67','source_suite_freeze_sha256':sha(SUITE/'freeze.json'),'preparer_sha256':sha(__file__),'order_sha256':sha(out/'future_ac_order.json'),'generation_authorized':False,'files':[{'file':str(p.relative_to(out)),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file()]})
 print('PASS: 6 scenes, 12 byte-identical A/C inputs, 24 planned requests; zero generation')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();prepare(args.output)
