"""Read archived PUBLIC sensor inputs only; no model, simulator or private score."""
import json,hashlib,time
from pathlib import Path
import numpy as np,cv2
from platform_v1.research import rgbd_world as rw
ROOT=Path('/home/alex/astra-realman_ws/persistent-chunk-pair-20261010')
OUT=Path('/home/alex/astra-realman_ws/postcontact-recovery-20261010')
def read(p):return json.loads(p.read_text())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def load(name):
 p=ROOT/name;checks=read(p/'CURRENT_RECHECKS.json');last=checks[-1]
 worlds={w['world_id']:w for f in (p/'worlds').glob('*.json') for w in [read(f)]}
 w=worlds[last['previous_world_id']];current=read(p/'observations'/('rm65_0020.json'));previous=read(p/'observations'/(w['state']['observation_id'].replace(':','_')+'.json'))
 def images(oid):
  o=read(p/'observations'/(oid.replace(':','_')+'.json'));out={}
  for r in o['rgb']:
   f=p/'episode/public'/r['file'];assert hashlib.sha256(f.read_bytes()).hexdigest()==r['sha256'];out[r['camera']]=cv2.cvtColor(cv2.imread(str(f)),cv2.COLOR_BGR2RGB)
  return out
 depths={}
 for r in current['depth']:
  folder=(p/'episode/public'/next(x['file'] for x in current['rgb'] if x['camera']==r['camera'])).parent
  for key in ('depth','validity'):assert hashlib.sha256((folder/r[key]['file']).read_bytes()).hexdigest()==r[key]['sha256']
  depths[r['camera']]=(np.load(folder/r['depth']['file']),cv2.imread(str(folder/r['validity']['file']),0)>0,r)
 feedback=read(p/'TRAJECTORY.json')[-1]['feedback'];feedback['run_full_pnp']=True
 return w,previous,current,images,depths,feedback

def diagnose(name):
 w,prev,cur,images,depths,fb=load(name);ref=w['state'];cfg=ref['object_config'];old=ref['entities'][ref['task_target_geometry_id']];new_images=images(cur['observation_id'])
 cand,metric=rw.measure_geometry_first(cur,depths,cfg,ref['public_plane']);views=[];rows=[];pictures=[]
 for seed in old['tracking_seeds']:
  c=seed['camera'];oldim=images(seed['observation_id'])[c];track=rw.track_view(oldim,new_images[c],rw.decode_mask(seed['mask']),c,cfg['tracker'])
  r={'camera':c,'tracker':track,'current_component_overlap':[]}
  if track['mask'] is not None:
   m=rw.decode_mask(track['mask']);views.append({'camera':c,'mask':track['mask'],'producer':'CURRENT_ARCHIVED_TRACK','observation_id':cur['observation_id']})
   for cid,e in cand.items():
    v=next((v for v in e['views'] if v['camera']==c),None)
    if v:
     n=int((m&rw.decode_mask(v['mask'])).sum());r['current_component_overlap'].append({'id':cid,'pixels':n,'fraction_of_current_tracked_mask':n/max(1,int(m.sum())),'status':e['status'],'reason':e['reason'],'candidate_type':e['candidate_type'],'FK_seed_min_distance_m':e['FK_seed_min_distance_m']})
  a=oldim.copy();cv2.drawContours(a,cv2.findContours(rw.decode_mask(seed['mask']),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(0,255,255),1)
  b=new_images[c].copy()
  for i,e in enumerate(cand.values()):
   v=next((v for v in e['views'] if v['camera']==c),None)
   if v:cv2.drawContours(b,cv2.findContours(rw.decode_mask(v['mask']),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(255,200,0),1)
  if track['mask'] is not None:cv2.drawContours(b,cv2.findContours(rw.decode_mask(track['mask']),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(0,255,255),2)
  cv2.putText(a,c+' before: historical target mask',(8,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
  cv2.putText(b,c+' after: current track(cyan), 3D components(orange)',(8,22),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
  pictures.append(np.concatenate([a,b],axis=1));rows.append(r)
 ext,k=rw.calibrated_cameras(cur);measurement=rw.measure_entity({'entity_id':old['entity_id'],'identity_status':'hypothesis'},views,cur,depths,cfg['geometry'],ext,k)
 out={'scope':'DEVELOPMENT_OFFLINE_REPLAY','world_id':w['world_id'],'before':prev['observation_id'],'after':cur['observation_id'],'tracking':rows,'measurement':measurement,'current_candidates':{i:{k:e.get(k) for k in ('status','reason','candidate_type','FK_seed_min_distance_m','coarse_observed_bounds_world_m')} for i,e in cand.items()},'original_fallback_trigger':'old.gripper_event==close; false on actual close boundary','model_calls':0,'physics':0}
 save(OUT/name/'DIAGNOSIS.json',out);cv2.imwrite(str(OUT/name/'BEFORE_AFTER.png'),cv2.cvtColor(np.concatenate(pictures,axis=0),cv2.COLOR_RGB2BGR))
 print(name,[(r['camera'],r['tracker']['reason'],r['tracker'].get('current_pixels'),r['current_component_overlap']) for r in rows]);print('measure',measurement['status'],measurement['reason'],measurement['point_world_m'])
if __name__=='__main__':
 for name in ('current_rgbd_h4','persistent_wh_h4'):diagnose(name)
