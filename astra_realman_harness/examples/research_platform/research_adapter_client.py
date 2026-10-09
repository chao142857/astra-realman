"""Route/lifecycle example, not a research algorithm. Use the fake CLI for acceptance.
Semantic planning, view choice, memory and scheduling policy belong in the new project.
"""
import sys,time
from platform_client import Client
p=Client();o=p.reset();cap=p.research_capabilities()

def wait_model(request):
    while True:
        r=p.broker_poll(request['request_id'])
        if r['status'] in ('READY','FAILED','CANCELLED'):return r
        time.sleep(.02)

def request(role,images,schema,world=None,evidence=None):
    return p.broker_submit({'backend':'existing_codex_infer','role':role,
        'instruction':'Public-input interface fixture. bbox coordinates refer to the selected attachment. Return only the requested schema; no tools.',
        'images':images,'evidence_ids':evidence or [],'world_id':world['world_id'] if world else None,
        'output_schema':schema,'timeout_s':10})

def images(*cameras,roi=None):
    return [{'observation_id':o['observation_id'],'camera':c,'roi':roi} for c in cameras]

e=wait_model(request('semantic_e0',images('assembly','fixed'),cap['legacy_semantic_schema']))
assert e['status']=='READY',e
w=p.world_submit([o['observation_id']]) # existing public RGB geometry, independent of a semantic identity claim
while True:
    wr=p.world_poll(w['request_id'])
    if wr['status'] in ('READY','FAILED','CANCELLED'):break
    time.sleep(.02)
assert wr['status']=='READY',wr
world=wr['result']
a=wait_model(request('action',images('wrist'),cap['legacy_plan_schema'],world,[e['evidence_id']]))
assert a['status']=='READY',a
plan=p.supervisor_from_broker(a['request_id']) # loading alone cannot execute
local=request('local_reground',images('fixed',roi=[.1,.2,.8,.9]),cap['legacy_semantic_schema'],world,[e['evidence_id']])
# External caller explicitly advances the plan. Broker process can run during approved motion.
while plan['status'] not in ('COMPLETED','DISCARDED'):
    plan=p.supervisor_step(plan['plan_id']);time.sleep(.01)
local_result=wait_model(local)
print(repr({'plan':plan,'local_status':local_result['status'],'geometry':world['state']['geometry_only']}),file=sys.stderr)
p.finish('unknown') # No policy access to private score; no automatic retry of a failure.
