"""SYNTHETIC LWH OUTPUT SCHEMA ONLY. Zero DA3 forward passes or physics episodes."""
import copy
import time
from platform_v1.research import integration, fusion
from research_fixtures import wait_job

def geometry_state(observation):
    # Fabricated surface support for testing fusion contracts, NOT pretrained results.
    samples=[]
    for camera,c in observation['calibration'].items():
        width,height=c['resolution']
        for x,y in ((.4,.4),(.4,.6),(.6,.4),(.6,.6)):
            samples.append({'camera':camera,'pixel':[width*x,height*y],
                'point_world_m':[.2+(x-.5)*.05,.1+(y-.5)*.05,.8],
                'confidence_raw':1.,'observation_id':observation['observation_id']})
    return {'backend':'da3_small_v1','observation_id':observation['observation_id'],
        'captured_monotonic':observation['captured_monotonic'],'scene_healthy':True,
        'entities':{},'robot_state':copy.deepcopy(observation['state']),
        'history_semantics':'SYNTHETIC_LWH_OUTPUT_NOT_DA3','geometry_only':True,
        'task_identity_verified':False,'surface_samples':samples,
        'resource_metrics':{'source':'SYNTHETIC_SCHEMA_FIXTURE_NO_INFERENCE'}}

def fused_fixture(owner,obs):
    a=owner.research
    req=a.broker.submit(integration.semantic_request(obs['observation_id']))
    row=wait_job(a.broker,req['request_id']);assert row['status']=='READY',row
    binding={'observation_ids':[obs['observation_id']],'execution_epoch':owner.epoch,'evidence_ids':[]}
    geom=a.store.publish_world(geometry_state(obs),binding,'FAKE_MODEL_RAW')
    wr={'status':'READY','result':geom}
    return fusion.fuse(a.store,wr,row['evidence_id']),wr,row

def action_fixture(owner,world,obs,H=4):
    req=integration.action_request(world,obs,{'id':'fixture_t1','revision':'fixture_v1','stage':'T1_PREGRASP_APPROACH'},
        {'profile':'generic_semantic_v1','object_id':'fixture-object','goal_id':''},H)
    row=owner.research.broker.submit(req);return wait_job(owner.research.broker,row['request_id'])

def fake_world_check(a):
    """Install ONLY under unittest.patch.object; never a runtime fallback."""
    def submit(observation_ids,evidence_ids,backend,reference_world_id=None):
        obs=a.store.get(observation_ids[-1]);a.world.rows['fixture-check']={'request_id':'fixture-check','status':'READY',
            'result':{'binding':{'execution_epoch':obs['execution_epoch'],'observation_ids':observation_ids},
                'state':geometry_state(obs)}}
        return {'request_id':'fixture-check'}
    return submit
