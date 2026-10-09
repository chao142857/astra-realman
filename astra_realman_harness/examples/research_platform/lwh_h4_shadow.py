"""Requires separately authorized real budget. SHADOW ONLY: never calls execute/step."""
import sys
import time
from platform_client import Client

p=Client()
def wait(method,request_id):
    while True:
        row=method(request_id)
        if row['status'] in ('READY','FAILED','CANCELLED'):
            if row['status']!='READY':raise RuntimeError('JOB_FAILED_NO_RETRY: '+request_id)
            return row
        time.sleep(.02)

try:
    obs=p.reset()
    pair=p.call('lwh_prepare',observation_id=obs['observation_id'])
    semantic=wait(p.broker_poll,pair['semantic'])
    geometry=wait(p.world_poll,pair['geometry'])
    world=p.call('lwh_fuse',geometry_request_id=pair['geometry'],semantic_evidence_id=semantic['evidence_id'])
    target=world['state']['task_target_id']
    if target is None or world['state']['entities'][target]['status']!='coarse':
        raise RuntimeError('TASK_TARGET_OR_GEOMETRY_UNKNOWN_NO_ACTION_QUERY')
    action=p.call('lwh_action',world_id=world['world_id'],
        task={'id':'approach_red_block_without_contact','revision':'T1_demo_v1','stage':'T1_PREGRASP_APPROACH'},
        task_binding={'profile':'generic_semantic_v1','object_id':target,'goal_id':''},H=4)
    answer=wait(p.broker_poll,action['request_id'])
    plan=p.supervisor_from_broker(action['request_id'])
    print(repr({'status':'SHADOW_LOADED_ONLY','plan':plan,'semantic_usage':semantic['usage_raw'],
        'action_usage':answer['usage_raw'],'generic_owner_admission':'UNKNOWN_BLOCKED',
        'native_EA_concurrency':'NOT_VERIFIED'}),file=sys.stderr)
    p.supervisor_cancel(plan['plan_id'])
finally:
    p.finish('unknown')
