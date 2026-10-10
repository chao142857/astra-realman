"""Offline verified semantic publication + production Broker.prepare, no dispatch."""
import argparse,hashlib,json,resource,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def audit(event,args):
    if event=='import' and str(args[0]).split('.')[0] in ('torch','sapien','sam2','depth_anything_3'):
        raise RuntimeError('MODEL_PHYSICS_IMPORT_FORBIDDEN')
    if event in ('socket.connect','subprocess.Popen','os.system'): raise RuntimeError('DISPATCH_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes)) and any(x in str(args[0]) for x in ('SCORING_TRUTH','RGB_REFERENCE','/private/')):
        raise RuntimeError('PRIVATE_INPUT_FORBIDDEN')
sys.addaudithook(audit)
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.broker import Broker
from platform_v1.research.semantic_binding import import_grounding_archive,validate_persistent_world,SEMANTIC_FIELDS
from platform_v1.research.review_contracts import shadow_request
from platform_v1.research.contracts import digest

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser()
    for n in ('world','observation','public','semantic-archive','config','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(exist_ok=False)
    start=time.monotonic();cpu=time.process_time();cfg=read(a.config);base=read(a.world);obs=read(a.observation)
    assert sha(a.world)==cfg['world_file_sha256'] and base['world_id']==cfg['world_id']
    store=PublicStore(a.public,obs['episode_id']);store.observe(obs,obs['execution_epoch'])
    store.worlds[base['world_id']]=base;store.current_world_id=base['world_id'];store.revision=base['world_revision'];store.read_versions=base['read_versions']
    t=time.monotonic();source=import_grounding_archive(store,a.semantic_archive,cfg['archive_manifest_sha256'],base['world_id'],cfg['evidence_id']);import_s=time.monotonic()-t
    head=WorldHead(a.output/'head',store,epoch=lambda:obs['execution_epoch'],deadline=time.monotonic()+90,emit=lambda *x:None)
    t=time.monotonic();world=head.bind_semantic_grounding(base['world_id'],cfg['evidence_id'],cfg['task']);bind_s=time.monotonic()-t
    validate_persistent_world(store,world)
    unchanged={}
    for i,e in base['state']['entities'].items():
        fields={k:v for k,v in e.items() if k not in SEMANTIC_FIELDS}
        after={k:v for k,v in world['state']['entities'][i].items() if k not in SEMANTIC_FIELDS}
        assert fields==after
        unchanged[i]={'before_sha256':digest(fields),'after_sha256':digest(after),'all_nonsemantic_fields_identical':True}
    assert world['state']['geometry_quality']==base['state']['geometry_quality']
    assert world['state']['scene_layers']==base['state']['scene_layers']
    t=time.monotonic();query=store.query_world(world['world_id']);query_s=time.monotonic()-t
    request=shadow_request(world,obs,cfg['task'],{'profile':'generic_semantic_v1','object_id':world['state']['task_target_geometry_id'],'goal_id':''})
    b=Broker(a.output/'broker',store,SimpleNamespace(fixture=False),deadline=time.monotonic()+90,epoch=lambda:obs['execution_epoch'],allowance=lambda:0,baseline_busy=lambda:False,emit=lambda *x:None)
    t=time.monotonic();prepared=b.prepare(request);prepare_s=time.monotonic()-t
    assert b.calls==b.infer_calls==0 and b.job is None and b.action_ready is None
    for name,value in [('WORLD.json',world),('WORLD_QUERY.json',query),('SEMANTIC_SOURCE.json',source),('REQUEST.json',request),('GEOMETRY_IMMUTABILITY.json',unchanged),
        ('WORLDSTORE.json',{'worlds':store.worlds,'evidence':store.evidence,'grounding_sources':store.grounding_sources,'semantic_world_pins':store.semantic_world_pins,'current_world_id':store.current_world_id,'revision':store.revision,'read_versions':store.read_versions})]:
        with (a.output/name).open('x') as f:json.dump(value,f,indent=2,allow_nan=False)
    summary={'status':'PREPARED_NOT_DISPATCHED','world_id':world['world_id'],'world_revision':world['world_revision'],'source_world_id':base['world_id'],'evidence_id':cfg['evidence_id'],
        'target':world['state']['task_target_geometry_id'],'target_status':world['state']['task_selection']['status'],'task_usable':world['state']['geometry_quality']['task_usable'],
        'entities':len(world['state']['entities']),'robot_semantic_ids':[i for i,e in world['state']['entities'].items() if e['semantic_disposition']=='robot'],'semantic_requests':world['state']['semantic_requests'],
        'unchanged_geometry':True,'model_calls':0,'new_physics_episodes':0,'hardware_actions':0,'training':0,'grants_execution':False,'H':4,'m':1,'K':0,
        'profile':{'archive_verify_import_s':import_s,'bind_publish_s':bind_s,'query_s':query_s,'broker_prepare_s':prepare_s,'pipeline_wall_s':time.monotonic()-start,'CPU_s':time.process_time()-cpu,'peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'GPU_used':False},
        'query_json_bytes':len(json.dumps(query,sort_keys=True,allow_nan=False).encode()),'actual_wire_bytes':(a.output/'broker/prepare-001/input_only/wire.json').stat().st_size,
        'world_file_sha256':sha(a.output/'WORLD.json'),'query_file_sha256':sha(a.output/'WORLD_QUERY.json'),'provider_schema_sha256':sha(a.output/'broker/prepare-001/schema.json'),
        'authoritative_schema_sha256':sha(a.output/'broker/prepare-001/authoritative_schema.json'),'request_sha256':sha(a.output/'REQUEST.json')}
    with (a.output/'SUMMARY.json').open('x') as f:json.dump(summary,f,indent=2)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
