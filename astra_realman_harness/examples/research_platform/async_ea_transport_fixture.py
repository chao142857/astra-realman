"""OFFLINE ROUTING FIXTURE: E then A during a pre-approved hold, never native agents.
The A plan is deliberately not rebound after the execution epoch changes.
"""
import sys,time
from platform_client import Client,PlatformError
p=Client();o=p.reset();cap=p.research_capabilities()
w=p.world_submit([o['observation_id']])
while True:
    r=p.world_poll(w['request_id'])
    if r['status'] in ('READY','FAILED','CANCELLED'):break
    time.sleep(.01)
assert r['status']=='READY';world=r['result']
execution=p.begin('execute',chunk=[{'type':'hold','seconds':2.0}],source_observation_id=o['observation_id'],proposal_id=None)

def model(role,camera,schema,evidence=None):
    request=p.broker_submit({'backend':'existing_codex_infer','role':role,'instruction':'OFFLINE TRANSPORT FIXTURE ONLY',
        'images':[{'observation_id':o['observation_id'],'camera':camera,'roi':None}],
        'evidence_ids':evidence or [],'world_id':world['world_id'],'output_schema':schema,'timeout_s':10})
    while True:
        row=p.broker_poll(request['request_id'])
        if row['status'] in ('READY','FAILED','CANCELLED'):break
        time.sleep(.01)
    assert row['status']=='READY',row
    return row

e=model('semantic_e0','fixed',cap['semantic_schema'])
a=model('action','wrist',cap['plan_schema'],[e['evidence_id']])
feedback=p.wait(execution);assert feedback['ok']
try:p.supervisor_from_broker(a['request_id'])
except PlatformError as error:assert str(error)=='STALE_PLAN_EPOCH',error
else:raise AssertionError('STALE_PREDICTION_WAS_REBOUND')
print('ASYNC_E_THEN_A_DURING_HOLD; STALE_PLAN_REJECTED; FAKE_EXECUTION_NOT_NATIVE_SUBAGENTS',file=sys.stderr)
p.finish('unknown')
