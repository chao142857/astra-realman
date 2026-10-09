"""NO-DISPATCH preparation over the production Broker. No credentials/environment.
Creates requests, exact role wire, attachments and two-layer schemas, no answers.
"""
import argparse,json,time,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_v1.research.public_store import PublicStore
from platform_v1.research.broker import Broker
from platform_v1.research.contracts import digest
from platform_v1.research.review_contracts import grounding_request,shadow_request,planning_review_eligibility

def read(p):return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--role',choices=['semantic_grounding','action_shadow'],required=True)
    for name in ('world','observation','public','output'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--evidence',type=Path);args=ap.parse_args();args.output.mkdir(exist_ok=False)
    w=read(args.world);o=read(args.observation)
    if 'w-'+digest({k:v for k,v in w.items() if k!='world_id'})!=w['world_id']:raise ValueError('FROZEN_WORLD_HASH')
    store=PublicStore(args.public,o['episode_id']);store.observe(o,o['execution_epoch']);store.worlds[w['world_id']]=w;store.current_world_id=w['world_id'];store.revision=w['world_revision'];store.read_versions=w['read_versions']
    if args.evidence:
        e=read(args.evidence)
        if e['provenance']!='MODEL_RAW' or 'e-'+digest({k:v for k,v in e.items() if k!='evidence_id'})!=e['evidence_id']:raise ValueError('REAL_EVIDENCE_BINDING')
        store.evidence[e['evidence_id']]=e
    task_text='Approach the red cuboid appearing on the left of the two red cuboids in the fixed-camera image to a precontact ready pose, without grasp/contact. Red cuboid alone is ambiguous.'
    if args.role=='semantic_grounding':request=grounding_request(w,o,task_text)
    else:
        request=shadow_request(w,o,{'id':'S1_FIXED_LEFT_PRECONTACT','revision':'1','stage':'T1_PREGRASP_APPROACH'},
            {'profile':'generic_semantic_v1','object_id':w['state']['task_target_id'],'goal_id':''})
    # fixture=False verifies real-input provenance. prepare never constructs a ProcessJob,
    # calls sandbox_command or reads auth; no real model answer/evidence can be generated.
    b=Broker(args.output/'broker',store,SimpleNamespace(fixture=False),deadline=time.monotonic()+90,epoch=lambda:o['execution_epoch'],allowance=lambda:0,baseline_busy=lambda:False,emit=lambda *x:None)
    result=b.prepare(request)
    (args.output/'REQUEST.json').write_text(json.dumps(request,indent=2));(args.output/'PREPARATION.json').write_text(json.dumps({**result,'role':args.role,'Astra_calls':0,'broker_model_attempts':b.calls,'worker_processes':0,'native_concurrency':False,'source_world':w['world_id'],'status':'PREPARED_NOT_DISPATCHED_NOT_SERVER_ACCEPTED'},indent=2))
    if args.role=='action_shadow':(args.output/'PLANNING_REVIEW.json').write_text(json.dumps(planning_review_eligibility(w,o),indent=2))
    assert b.calls==0 and b.infer_calls==0 and b.job is None and b.action_ready is None
    print(json.dumps(result))
if __name__=='__main__':main()
