"""Frozen sensor replay benchmark; no models, episodes, execution or GT scoring."""
import argparse,hashlib,json,resource,sys,time
from pathlib import Path
ap=argparse.ArgumentParser()
ap.add_argument('--source-root',type=Path,required=True);ap.add_argument('--mode',choices=['original','full','cached'],required=True)
ap.add_argument('--workspace',type=Path,default=Path('/home/alex/astra-realman_ws'));ap.add_argument('--output',type=Path,required=True)
a=ap.parse_args();sys.path.insert(0,str(a.source_root));a.output.mkdir(exist_ok=False)
def audit(event,args):
    if event=='import' and (str(args[0]).split('.')[0] in ('sapien','torch','sam2','depth_anything_3') or str(args[0]) in ('platform_v1.owner','platform_v1.research.supervisor')):raise RuntimeError('FORBIDDEN_IMPORT')
    if event in ('socket.connect','subprocess.Popen','os.system'):raise RuntimeError('FORBIDDEN_DISPATCH')
    if event=='open' and isinstance(args[0],(str,bytes)) and any(x in str(args[0]) for x in ('/private/','RGB_REFERENCE','SCORING_TRUTH')):raise RuntimeError('FORBIDDEN_PRIVATE_INPUT')
sys.addaudithook(audit)
import cv2
cv2.setNumThreads(1)
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.semantic_binding import validate_geometry_update
from platform_v1.research.contracts import clone

def read(p):return json.loads(p.read_text())
def save(p,v):
    with p.open('x') as f:json.dump(v,f,indent=2,allow_nan=False)
start=time.monotonic();cpu=time.process_time();ws=a.workspace
records=ws/'shadow-candidate-cheap-update-20261010/G1_PUBLIC_INPUTS.json';data=read(records);frames=data['frames'];o=frames[0]['observation'];epoch=o['execution_epoch']
s=PublicStore(ws/'rgbd-g1-execution-20261009/run/public',o['episode_id'])
if a.mode!='original':s.validation_cache_enabled=a.mode=='cached'
s.observe(o,epoch);h=WorldHead(a.output/'head',s,epoch=lambda:epoch,deadline=time.monotonic()+600,emit=lambda *x:None)
h.public_plane=read(ws/'geometry-first-v2-20261010/inputs/PLANE.json');h.geometry_update_config=read(a.source_root/'config/research/geometry_first_update_v1.json')
rows=[];previous=None;worlds=[]
for i,f in enumerate(frames):
    o=f['observation'];epoch=o['execution_epoch'];s.observe(o,epoch);t=time.monotonic();c=time.process_time()
    if not i:w=h.build_geometry_first(o['observation_id'],read(a.source_root/'config/research/geometry_first_v2.json'))
    else:w=h.update(previous['world_id'],o['observation_id'],f['feedback']['completed_monotonic'],execution_feedback=f['feedback'])
    api=time.monotonic()-t;api_cpu=time.process_time()-c;profile=clone(getattr(s,'last_update_profile',{})) if i else {}
    t=time.monotonic()
    if i:validate_geometry_update(s,w)
    verify=time.monotonic()-t;t=time.monotonic();q=s.query_world(w['world_id']);query=time.monotonic()-t
    t=time.monotonic();save(a.output/('world-%02d.json'%i),w);save(a.output/('query-%02d.json'%i),q);serialization=time.monotonic()-t
    rows.append({'index':i,'stage':f['stage'],'API_s':api,'API_CPU_s':api_cpu,'extra_validation_s':verify,'query_s':query,'file_serialization_s':serialization,
        'world_metrics':w['state']['resource_metrics'],'update_profile':profile,'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024})
    worlds.append(w);previous=w
save(a.output/'SUMMARY.json',{'mode':a.mode,'source_root':str(a.source_root),'records_sha256':hashlib.sha256(records.read_bytes()).hexdigest(),
 'scope':'ARCHIVED_DEVELOPMENT_SENSOR_REPLAY_NOT_NEW_EPISODE','threads':1,'rows':rows,'pipeline_wall_s':time.monotonic()-start,'CPU_s':time.process_time()-cpu,
 'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'real_models':0,'new_episodes':0,'hardware':0,'training':0,'GPU':False,
 'timer_scope':'after imports; includes records/initialization, Build/Update/validation/query/world-query writes; excludes summary write'})
print(json.dumps({'mode':a.mode,'API_s':[r['API_s'] for r in rows],'pipeline_wall_s':time.monotonic()-start}))
