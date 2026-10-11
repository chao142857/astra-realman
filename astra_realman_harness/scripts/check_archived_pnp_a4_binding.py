"""Read-only archived A4 diagnostic. No execution, model dispatch or GT input."""
import json,hashlib,time,math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from platform_v1.research.public_store import PublicStore
from platform_v1.research.semantic_binding import verify_world_hash,import_grounding_archive,restore_persistent_world,register_geometry_update
from platform_v1.research.broker import Broker
from platform_v1.research import pnp_proposal,chunk_plan
from platform_v1.research.contracts import digest
P=Path('/home/alex/astra-realman_ws/postcontact-recovery-20261010/NEXT_PERSISTENT_RUN')
OUT=Path('/home/alex/astra-realman_ws/pnp-host-binding-20261010')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
class OfflineJob:
 def __init__(self,*a,**kw):self.proc=SimpleNamespace(pid=-1);self.result=None
 def poll(self):return self.result

def main():
 start=time.monotonic();manifest=read(P/'FINAL_SEAL.json');assert all(sha(P/f)==h for f,h in manifest.items())
 worlds=sorted([read(f) for f in (P/'worlds').glob('*.json')],key=lambda w:w['world_revision'])
 obs=[read(f) for f in (P/'observations').glob('*.json')];store=PublicStore(P/'episode/public',obs[0]['episode_id'])
 for o in obs:store.observe(o,o['execution_epoch'])
 base=worlds[0];verify_world_hash(base);store.worlds[base['world_id']]=base;store.current_world_id=base['world_id'];store.revision=base['world_revision'];store.read_versions=base['read_versions']
 sealed=P/'semantic_sealed';eid=read(sealed/'MODEL_RESULT.json')['evidence_id'];import_grounding_archive(store,sealed,manifest['semantic_sealed/DELIVERY_MANIFEST.json'],base['world_id'],eid)
 semantic=worlds[1];restore_persistent_world(store,semantic,semantic['world_id'],semantic['state']['task_selection']['task'])
 for w in worlds[2:]:
  verify_world_hash(w);parent=store.get_world(w['binding']['reference_world_id']);o=store.get(w['state']['observation_id']);store.worlds[w['world_id']]=w;store.current_world_id=w['world_id'];store.revision=w['world_revision'];store.read_versions=w['read_versions'];register_geometry_update(store,w,parent,o)
 w=worlds[-1];o=store.get(w['state']['observation_id']);archived=P/'episode/private/research_broker/broker-005';wire=read(archived/'input_only/wire.json');assert wire['binding']['world_id']==w['world_id']
 resultfile=next(archived.glob('infer_output/bridge/*/result.json'));raw=read(resultfile)['raw'];answer=json.loads(raw);rawhash=hashlib.sha256(raw.encode()).hexdigest()
 b=Broker(OUT/'A4_OFFLINE_BROKER',store,SimpleNamespace(fixture=True),deadline=time.monotonic()+120,epoch=lambda:o['execution_epoch'],allowance=lambda:1,baseline_busy=lambda:False,emit=lambda *x:None);b.pnp_episode_authorization=store.episode_id
 with patch('platform_v1.research.broker.ProcessJob',OfflineJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
  rid=b.submit(pnp_proposal.request(w,o))['request_id']
 row=b.rows[rid];record={'raw':raw,'usage':None,'usage_events':[],'return_code':0,'error':None,'source':'OFFLINE_ARCHIVED_RAW_NOT_NEW_MODEL'}
 b.job[1].result={'bytes':json.dumps(record).encode(),'return_code':0,'cancel_reason':None};b.tick()
 report={'scope':'READ_ONLY_DEVELOPMENT_DIAGNOSTIC_NOT_NEW_MODEL_OR_PHYSICAL_SUCCESS','frozen_result':'FAIL_STOP / PNP_MISSING_SEMANTIC_SOURCE; K=10','raw_sha256':rawhash,'raw_file':str(resultfile),'missing_model_echo':sorted(set(w['binding']['evidence_ids'])-set(answer['evidence_refs'])),'new_offline_parser_status':row['status'],'error':row['error'],'K':0,'model_calls':0,'episodes':0,'Owner_calls':0,'IK':'NOT_TESTED','collision':'NOT_TESTED','clearance':'NOT_TESTED'}
 poses=[wire['action_proposal_host']['plan_fields']['origin_pose_world']]+[x['pose'] for x in answer['result']['proposal']['waypoints']]
 report['waypoints']=[{'original':wp,'distance_m':chunk_plan.pose_error(poses[i],poses[i+1])[0],'rotation_rad':chunk_plan.pose_error(poses[i],poses[i+1])[1]} for i,wp in enumerate(answer['result']['proposal']['waypoints'])]
 if row['status']=='READY':
  d=row['pnp_candidate'];assert row['raw']==raw and row['parsed']==answer;assert d['actions']==[{'type':'move_pose','pose':x['pose']} for x in answer['result']['proposal']['waypoints']];assert b.action_ready is None and d['grants_execution'] is False
  report.update(raw_unmodified=True,waypoints_exact=True,derived_source=d['source']['producer'],trusted_binding=d['trusted_semantic_binding'],internal_plan_sha256=digest(d['plan']),actions_sha256=digest(d['actions']))
 report['wall_s']=time.monotonic()-start;report['old_seal_files_unchanged']=len(manifest) if all(sha(P/f)==h for f,h in manifest.items()) else False
 (OUT/'A4_READ_ONLY_DIAGNOSTIC.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('trusted_binding','waypoints')},indent=2))
 assert row['status']=='READY',row['error']
if __name__=='__main__':main()
