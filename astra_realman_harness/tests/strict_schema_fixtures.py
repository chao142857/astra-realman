"""Explicit SYNTHETIC response/world builders. Never used by production code."""
import copy
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from platform_v1.research import fusion, integration

class PendingJob:
    def __init__(self, folder, command, env, deadline, **kw):
        self.folder=folder; self.command=command; self.env=env; self.deadline=deadline
        self.proc=SimpleNamespace(pid=os.getpid()); self.result=None
    def poll(self): return self.result
    def close(self): pass

def prepare(broker, request):
    with patch('platform_v1.research.broker.ProcessJob', PendingJob):
        identity=broker.submit(request)['request_id']
    return broker.rows[identity], broker.job[1]

def complete(broker, job, answer=None, raw=None, record=None):
    if record is None:
        record={'raw':json.dumps(answer) if raw is None else raw, 'usage':None, 'usage_events':[],
                'return_code':0, 'error':None, 'source':'SYNTHETIC_OFFLINE_NOT_ASTRA'}
    job.result={'return_code':0, 'bytes':json.dumps(record).encode(), 'cancel_reason':None}
    broker.tick()

def semantic_answer(row):
    ids=[a['id'] for a in row['attachments']]
    return {'binding':copy.deepcopy(row['binding']), 'evidence_refs':ids,
        'result':{'version':'astra.semantic_scene.v2','task_target_id':'SYNTHETIC-object',
        'entities':[{'entity_id':'SYNTHETIC-object','label':'SYNTHETIC NOT PERCEPTION','kind':'object',
            'identity_status':'hypothesis','views':[{'attachment_id':i,'bbox':[.2,.2,.4,.4],
            'visibility':'partial'} for i in ids],'description':'OFFLINE CONTRACT ONLY'},
            {'entity_id':'SYNTHETIC-unknown','label':'unknown','kind':'unknown','identity_status':'unknown',
             'views':[],'description':'OFFLINE CONTRACT ONLY'}],
        'relations':[], 'unknowns':['SYNTHETIC ANSWER; NO SEMANTIC PERFORMANCE CLAIM']}}

def synthetic_world(store, obs, evidence_id):
    state={'backend':'semantic_lwh_v1','observation_id':obs['observation_id'],
        'scene_healthy':True,'robot_state':copy.deepcopy(obs['state']),
        'geometry_quality':{'numeric_valid':'pass','self_consistent':'pass','task_usable':'pass',
            'observation_id':obs['observation_id'],'source':'SYNTHETIC_CONTRACT_ONLY','grants_execution':False},
        'semantic_evidence_id':evidence_id,'entities':{'SYNTHETIC-object':{'status':'coarse',
            'measurement_kind':'current_depth_region','source':'SYNTHETIC_NOT_MEASURED'}},
        'history_semantics':'SYNTHETIC_CONTRACT_ONLY_NOT_WORLD_ACCEPTANCE'}
    return store.publish_world(state,{'observation_ids':[obs['observation_id']],
        'execution_epoch':obs['execution_epoch']},'FAKE_MODEL_RAW',read_versions={
        'task/SYNTHETIC':1,'world/SYNTHETIC-object':1,'visibility/SYNTHETIC-object':1})

def action_request(world, obs, H=4):
    return integration.action_request(world,obs,
        {'id':'SYNTHETIC-T1','revision':'SYNTHETIC-1','stage':'T1_PREGRASP_APPROACH'},
        {'profile':'generic_semantic_v1','object_id':'SYNTHETIC-object','goal_id':''},H)

def action_answer(row):
    shape=row['authoritative_schema']['properties']['result']['properties']
    result={k:copy.deepcopy(v['const']) for k,v in shape.items() if 'const' in v}
    start=result['origin_pose_world']
    result['waypoints']=[{'index':i,'type':'move_pose',
        'pose':[start[0]+.03*i,*start[1:]],'nominal_end_offset_s':2.*i,
        'preconditions':copy.deepcopy(shape['waypoints']['items']['properties']['preconditions']['const']),
        'prediction_dependencies':list(range(1,i)), 'boundary_after':'none'} for i in range(1,result['H']+1)]
    result['termination']={'kind':'horizon_filled','reason':'SYNTHETIC CONTRACT RESPONSE'}
    return {'binding':copy.deepcopy(row['binding']), 'evidence_refs':[a['id'] for a in row['attachments']]+row['binding']['evidence_ids'], 'result':result}
