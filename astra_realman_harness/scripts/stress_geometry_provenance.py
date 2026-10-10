"""Synthetic software-only source-chain pressure. No state-estimator accuracy claim."""
import argparse,copy,hashlib,json,resource,sys,time,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from platform_v1.research.public_store import PublicStore
from platform_v1.research.semantic_binding import register_geometry_update,validate_geometry_update
from platform_v1.research.contracts import clone
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--unique-files',action='store_true');a=ap.parse_args();a.output.mkdir(exist_ok=False)
ws=Path('/home/alex/astra-realman_ws');base=json.loads((ws/'shadow-candidate-cheap-update-20261010/G1_PUBLIC_INPUTS.json').read_text())['frames'][0]['observation']
public=a.output/'public';public.mkdir();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for c in ('assembly','fixed','wrist'):
 Image.fromarray(np.zeros((8,8,3),np.uint8)).save(public/(c+'.png'))
 Image.fromarray(np.full((8,8),255,np.uint8)).save(public/(c+'.valid.png'))
 np.save(public/(c+'.depth.npy'),np.full((8,8),.5,dtype=np.float32),allow_pickle=False)
s=PublicStore(public,'SYNTHETIC_SOFTWARE_CHAIN');rows=[];previous=None
for i in range(65):
 frame_public=public
 if a.unique_files:
  frame_public=public/('frame_%03d'%i);frame_public.mkdir()
  for c in ('assembly','fixed','wrist'):
   for suffix in ('.png','.valid.png','.depth.npy'):shutil.copyfile(public/(c+suffix),frame_public/(c+suffix))
 o=clone(base);o.update(episode_id=s.episode_id,observation_id='SYNTHETIC_CHAIN:%03d'%i,captured_monotonic=100.+i,execution_epoch=i,research_input_provenance='SYNTHETIC_FAULT_INJECTION')
 o['state']['sim_step']=i
 for rgb in o['rgb']:
  c=rgb['camera'];rgb.update(file=str((frame_public/(c+'.png')).relative_to(public)),sha256=sha(frame_public/(c+'.png')))
  cal=o['calibration'][c];cal['resolution']=[8,8];cal['intrinsic']=[[8.,0.,4.],[0.,8.,4.],[0.,0.,1.]]
  rec=next(r for r in o['depth'] if r['camera']==c)
  rec.update(resolution=[8,8],frame_id=o['observation_id']+'/'+c,captured_monotonic=o['captured_monotonic'],capture_interval_monotonic=[o['captured_monotonic']-.01,o['captured_monotonic']],readback_completed_monotonic=o['captured_monotonic']+.01,sensor_timestamp=float(i),simulation_step=i,aligned_rgb_sha256=rgb['sha256'])
  rec['alignment']['intrinsics']=cal['intrinsic']
  for k,suffix in [('depth','.depth.npy'),('validity','.valid.png')]:rec[k].update(file=c+suffix,sha256=sha(public/(c+suffix)))
 s.observe(o,i)
 state={'observation_id':o['observation_id'],'robot_state':o['state'],'entities':{},'scope':'SYNTHETIC_VALIDATION_CHAIN_NO_ESTIMATION'}
 binding={'execution_epoch':i,'observation_ids':[o['observation_id']],'evidence_ids':[]}
 if i:state['geometry_update_version']='astra.geometry_first_cheap_update.v1';binding['reference_world_id']=previous['world_id']
 w=s.publish_world(state,binding,'SYNTHETIC_SOFTWARE_CHAIN',read_versions={'synthetic/measurement':i})
 if i:
  register_geometry_update(s,w,previous,o);validate_geometry_update(s,w)
  if i in (1,4,8,16,32,64):
   for mode in ('cached','full_audit'):
    samples=[]
    for repeat in range(3):
     s.verification_cache.reset_metrics();t=time.monotonic();validate_geometry_update(s,w,full_audit=mode=='full_audit')
     samples.append({'wall_s':time.monotonic()-t,'metrics':clone(s.verification_cache.metrics)})
    rows.append({'length':i,'mode':mode,'samples':samples})
 previous=w
with (a.output/'SUMMARY.json').open('x') as f:json.dump({'scope':'SYNTHETIC_SOFTWARE_STRESS_NOT_PHYSICAL_EVIDENCE','unique_sensor_paths_per_frame':a.unique_files,'rows':rows,'worlds':65,'real_models':0,'new_episodes':0,'hardware':0,'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024},f,indent=2)
print(json.dumps({'rows':len(rows),'worlds':65,'status':'COMPLETE_SOFTWARE_ONLY'}))
