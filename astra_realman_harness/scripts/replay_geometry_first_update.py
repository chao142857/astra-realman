"""Archived public sensor replay only. No model, physics, scoring or GT imports."""
import argparse,json,hashlib,resource,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def audit(event,args):
    if event=='import' and (str(args[0]).split('.')[0] in ('sapien','torch','sam2','depth_anything_3')
       or str(args[0]) in ('platform_v1.owner','platform_v1.research.supervisor')):raise RuntimeError('EXECUTION_IMPORT_FORBIDDEN')
    if event in ('socket.connect','subprocess.Popen','os.system'):raise RuntimeError('DISPATCH_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes)) and any(k in str(args[0]) for k in ('/private/','scoring_truth','SCORING_TRUTH','RGB_REFERENCE')):
        raise RuntimeError('PRIVATE_SCORING_INPUT_FORBIDDEN')
sys.addaudithook(audit)
import cv2
cv2.setNumThreads(1)
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.semantic_binding import validate_geometry_update
from platform_v1.research.contracts import digest
def read(p):return json.loads(p.read_text())
def save(p,v):
    with p.open('x') as f:json.dump(v,f,indent=2,allow_nan=False)
def main():
    ap=argparse.ArgumentParser()
    for n in ('records','public','config','update-config','plane','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(exist_ok=False)
    total=time.monotonic();cpu=time.process_time();records=read(a.records);cfg=read(a.config);rows=[]
    assert records['scope']=='ARCHIVED_PHYSICAL_SENSOR_REPLAY_NOT_NEW_EPISODE'
    frames=records['frames'];first=frames[0]['observation'];epoch=first['execution_epoch']
    store=PublicStore(a.public,first['episode_id']);store.observe(first,epoch)
    head=WorldHead(a.output/'head',store,epoch=lambda:epoch,deadline=time.monotonic()+600,emit=lambda *x:None)
    head.public_plane=read(a.plane);head.geometry_update_config=read(a.update_config)
    previous=None
    for index,frame in enumerate(frames):
        o=frame['observation'];epoch=o['execution_epoch'];store.observe(o,epoch)
        start=time.monotonic();c=time.process_time()
        if index==0:w=head.build_geometry_first(o['observation_id'],cfg)
        else:
            feedback=frame['feedback'];w=head.update(previous['world_id'],o['observation_id'],feedback['completed_monotonic'],execution_feedback=feedback)
        api=time.monotonic()-start;api_cpu=time.process_time()-c
        verify_start=time.monotonic()
        if index:validate_geometry_update(store,w)
        validation=time.monotonic()-verify_start
        query_start=time.monotonic();q=store.query_world(w['world_id']);query_s=time.monotonic()-query_start
        serialization=time.monotonic();save(a.output/('world-%02d.json'%index),w);save(a.output/('query-%02d.json'%index),q)
        serialize_s=time.monotonic()-serialization
        rows.append({'stage':frame['stage'],'observation_id':o['observation_id'],'execution_epoch':epoch,
            'world_id':w['world_id'],'world_revision':w['world_revision'],'read_versions':w['read_versions'],
            'entities':{i:{k:e.get(k) for k in ('status','semantic_status','observation_id','point_world_m','motion','reason','visibility',
                'geometry_residual','temporal_association','association_uncertainty')} for i,e in w['state']['entities'].items()},
            'FK_camera_check':w['state'].get('fk_camera_check'),'actual_wrist_pose':o['calibration']['wrist']['pose_world_xyz_wxyz'],
            'profile':{**w['state']['resource_metrics'],'WorldHead_API_wall_s':api,'WorldHead_API_CPU_s':api_cpu,
                'lineage_verification_s':validation,'query_s':query_s,'serialization_s':serialize_s,
                'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024},
            'current_geometry_count':sum(e['status']=='coarse' for e in w['state']['entities'].values()),
            'current_candidate_count':len(w['state'].get('current_candidate_ids',w['state']['entities'])),
            'historical_only_count':sum(not e.get('candidate_surface_cloud') for e in w['state']['entities'].values()),
            'unique_associations':sum(e.get('temporal_association',{}).get('status')=='unique_current_match' for e in w['state']['entities'].values()),
            'task_usable':w['state']['geometry_quality']['task_usable'],'current_static_points':w['state']['scene_layers']['static']['current_support_count'],
            'query_canonical_bytes':len(json.dumps(q,sort_keys=True).encode()),'grants_execution':False})
        previous=w
    save(a.output/'WORLDSTORE.json',{'worlds':store.worlds,'evidence':store.evidence,'read_versions':store.read_versions,
        'current_world_id':store.current_world_id,'revision':store.revision,'geometry_update_receipts':store.geometry_update_receipts})
    summary={'status':'ARCHIVED_ENGINEERING_REPLAY_ONLY','source_records_sha256':hashlib.sha256(a.records.read_bytes()).hexdigest(),
        'input_scope':records['scope'],'frames':len(rows),'update_calls':len(rows)-1,'Build_calls':1,'rows':rows,
        'real_semantic_persistence_under_motion':'NOT_TESTED_G1_HAS_NO_REAL_SEMANTIC_GROUNDING',
        'G1_original_result':'PARTIAL_PASS_STATE_CONSISTENCY_ONLY; original 61mm reprojection failure unchanged',
        'GT_read':False,'new_independent_episode':False,'real_Astra_E':0,'real_Astra_A':0,'new_SAPIEN_episodes':0,
        'hardware':0,'training':0,'GPU_used':False,'grants_execution':False,
        'profile':{'pipeline_wall_s':time.monotonic()-total,'CPU_s':time.process_time()-cpu,
                   'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}}
    save(a.output/'SUMMARY.json',summary)
    save(a.output/'PREDICTION_SEAL.json',{'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.iterdir() if p.is_file()},
        'no_independent_physics_or_GT_score':True})
    print(json.dumps({'status':summary['status'],'counts':[(r['stage'],len(r['entities']),r['unique_associations'],r['current_geometry_count']) for r in rows],
                      'profile':summary['profile']},indent=2))
if __name__=='__main__':main()
