"""RGB-D-only diagnostic entry. Run inside public-only, networkless bwrap.
No semantic evidence/reference/private actor data or model runtime is accepted.
"""
import argparse,json,sys,time,resource,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def audit(event,args):
    if event=='import' and str(args[0]).split('.')[0] in ('torch','sapien','sam2','depth_anything_3'):
        raise RuntimeError('MODEL_OR_PHYSICS_IMPORT_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes)) and any(k in str(args[0]) for k in ('/private/','SCORING_TRUTH','RGB_REFERENCE','EVIDENCE.json','MODEL_RAW','assembly_config')):
        raise RuntimeError('NON_GEOMETRY_INPUT_FORBIDDEN')
    if event in ('socket.connect','subprocess.Popen','os.system'): raise RuntimeError('DISPATCH_FORBIDDEN')
sys.addaudithook(audit)
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
import cv2
cv2.setNumThreads(1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--public',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    start=time.monotonic();cpu=time.process_time()
    o=json.loads((args.input/'OBSERVATION.json').read_text());cfg=json.loads((args.input/'CONFIG.json').read_text());plane=json.loads((args.input/'PLANE.json').read_text())
    store=PublicStore(args.public,o['episode_id']);store.observe(o,o['execution_epoch'])
    head=WorldHead(args.output,store,epoch=lambda:o['execution_epoch'],deadline=time.monotonic()+110,emit=lambda *x:None);head.public_plane=plane
    w=head.build_geometry_first(o['observation_id'],cfg);built=time.monotonic();q=store.query_world(w['world_id']);queried=time.monotonic()
    for name,value in [('WORLD.json',w),('WORLD_QUERY.json',q),('WORLDSTORE.json',{'worlds':store.worlds,'evidence':store.evidence,'revision':store.revision,'read_versions':store.read_versions,'current_world_id':store.current_world_id})]:
        with (args.output/name).open('x') as f:json.dump(value,f,indent=2,allow_nan=False)
    summary={'status':'GEOMETRY_FIRST_DEVELOPMENT_PREDICTION','candidates':len(w['state']['entities']),
        'entities':{i:{k:e.get(k) for k in ('geometry_instance_id','status','candidate_type','robot_exclusion','point_world_m','coarse_observed_bounds_world_m','contributing_views','association_uncertainty','uncertainty_components','reason')} for i,e in w['state']['entities'].items()},
        'profiling':{**w['state']['resource_metrics'],'head_build_wall_s':built-start,'query_s':queried-built,'serialization_s':time.monotonic()-queried,'pipeline_wall_s':time.monotonic()-start,'CPU_s':time.process_time()-cpu,'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'GPU_allocations':0},
        'calls':{'Astra_E':0,'Astra_A':0,'new_SAPIEN_episodes':0,'hardware':0,'training':0,'DA3':0,'SAM':0},
        'semantics_or_GT_read':False,'grants_execution':False}
    with (args.output/'SUMMARY.json').open('x') as f:json.dump(summary,f,indent=2,allow_nan=False)
    print(json.dumps({'candidates':summary['candidates'],'profiling':summary['profiling']}))
if __name__=='__main__':main()
