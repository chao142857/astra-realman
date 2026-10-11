"""Pinned archive replay into existing Store/WorldHead, zero model/physics."""
import time,hashlib
from pathlib import Path
from scripts.diagnose_postcontact_offline import ROOT,OUT,read,save,load
from platform_v1.research.public_store import PublicStore
from platform_v1.research.semantic_binding import (verify_world_hash,import_grounding_archive,restore_persistent_world,register_geometry_update,validate_geometry_update)
from platform_v1.research.world_head import WorldHead
from platform_v1.research.model_context import role_world_view
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def restore(name,through_close=False):
 p=ROOT/name;manifest=read(p/'FINAL_SEAL.json')
 def pinned(f):
  assert manifest[str(f.relative_to(p))]==sha(f)
  return read(f)
 worlds=sorted([pinned(f) for f in (p/'worlds').glob('*.json')],key=lambda w:w['world_revision'])
 observations=[pinned(f) for f in (p/'observations').glob('*.json')];store=PublicStore(p/'episode/public',observations[0]['episode_id'])
 for o in observations:store.observe(o,o['execution_epoch'])
 base=worlds[0];verify_world_hash(base);store.worlds[base['world_id']]=base;store.current_world_id=base['world_id'];store.revision=base['world_revision'];store.read_versions=base['read_versions']
 sealed=p/'semantic_sealed';eid=pinned(sealed/'MODEL_RESULT.json')['evidence_id']
 import_grounding_archive(store,sealed,manifest['semantic_sealed/DELIVERY_MANIFEST.json'],base['world_id'],eid)
 semantic=worlds[1];restore_persistent_world(store,semantic,semantic['world_id'],semantic['state']['task_selection']['task'])
 for w in worlds[2:] if through_close else worlds[2:-1]:
  verify_world_hash(w);parent=store.get_world(w['binding']['reference_world_id']);o=store.get(w['state']['observation_id'])
  store.worlds[w['world_id']]=w;store.current_world_id=w['world_id'];store.revision=w['world_revision'];store.read_versions=w['read_versions']
  register_geometry_update(store,w,parent,o);validate_geometry_update(store,w)
 return store,worlds[-1] if through_close else worlds[-2]
def replay(name):
 begin=time.monotonic();store,parent=restore(name);restored=time.monotonic();w,previous,current,images,depths,fb=load(name)
 assert w==parent
 head=WorldHead(OUT/name/'offline_worker',store,epoch=lambda:current['execution_epoch'],deadline=time.monotonic()+120,emit=lambda *x:None)
 new=head.update(parent['world_id'],current['observation_id'],fb['completed_monotonic'],execution_feedback=fb)
 validate_geometry_update(store,new);query=role_world_view(store,new['world_id'],'pnp_action_proposal')
 save(OUT/name/'replay_v2/WORLD_RECOVERED.json',new);save(OUT/name/'replay_v2/WORLD_QUERY.json',query)
 save(OUT/name/'replay_v2/REPLAY_RESULT.json',{'scope':'DEVELOPMENT_ARCHIVED_SENSOR_REPLAY_NOT_NEW_PHYSICS','WorldHead_API':'update','original_world_unchanged':store.get_world(parent['world_id'])==parent,'world_id':new['world_id'],'world_revision':new['world_revision'],'read_versions':new['read_versions'],'status':new['state']['pnp_interaction']['status'],'current_support':new['state']['pnp_interaction']['current_support'],'task_usable':new['state']['geometry_quality']['task_usable'],'held':False,'trial_lift':'NOT_RUN_AUTHORIZATION_REQUIRED','archive_restore_s':restored-begin,'update_and_validation_s':time.monotonic()-restored,'profiling':new['state']['resource_metrics'],'local_s':new['state']['pnp_interaction']['tracking_measurement']['wall_s'],'world_query_bytes':len(__import__('json').dumps(query).encode()),'models':0,'episode':0})
 print(name,new['state']['pnp_interaction']['status'],new['state']['pnp_interaction']['current_support'],new['state']['geometry_quality']['task_usable'])
if __name__=='__main__':
 for name in ('current_rgbd_h4','persistent_wh_h4'):replay(name)
