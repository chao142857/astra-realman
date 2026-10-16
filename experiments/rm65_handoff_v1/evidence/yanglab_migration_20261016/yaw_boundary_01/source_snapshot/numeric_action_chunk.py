"""Public numerical action chunks. No task stages, scene objects or reference routes.

Fixed stop-and-settle tracking, not obstacle planning or a Cartesian servo.
Each generated node uses the original closest IK, joint cubic and FCL preflight.
"""
import copy
import json
import math
from pathlib import Path
import numpy as np
import jsonschema
from scipy.spatial.transform import Rotation, Slerp
from action_interface import obj, vector, strict_json

VERSION='numeric_chunk_v2'
PRIVATE_FEEDBACK_FIELDS={'bilateral_contact_at_end','latched'}
MAX_TRANSLATION_M=.005
MAX_ROTATION_RAD=math.radians(1)
MAX_GROUPS=128
POSITION_TOLERANCE_M=.002
ROTATION_TOLERANCE_RAD=math.radians(1)
# Same anyOf/typed-enum vocabulary as the already used V1 output schema.
TCP=obj({'arm':{'type':'string','enum':['left','right']},'kind':{'type':'string','enum':['tcp']},
    'waypoints_world_wxyz':{'type':'array','items':vector(7),'minItems':1,'maxItems':16}})
GRIP=obj({'arm':{'type':'string','enum':['left','right']},'kind':{'type':'string','enum':['gripper']},
    'opening_fraction':{'type':'number','minimum':0,'maximum':1},
    'contact_mode':{'type':'string','enum':['position','bilateral_hold']}})
STAGE=obj({'mode':{'type':'string','enum':['sequential','parallel']},
    'actions':{'type':'array','items':{'anyOf':[TCP,GRIP]},'maxItems':2},
    'observe_s':{'type':'number','minimum':0,'maximum':5}})
SCHEMA=obj({'done':{'type':'boolean'},'stages':{'type':'array','items':STAGE,'maxItems':8}})
CONVENTIONS={
    'interface_version':VERSION,
    'position':'metres in shared SAPIEN world; quaternion [w,x,y,z] is Link6 world orientation',
    'tcp':'mean of actual inner pad representative centres, not flange; changes with gripper geometry',
    'authority':'You choose every target, intermediate waypoint, gripper command, order and release. No task skill or expert waypoint is inserted.',
    'tcp_tracking':{'translation_step_max_m':MAX_TRANSLATION_M,'rotation_step_max_rad':MAX_ROTATION_RAD,
        'interpolation':'Straight position and shortest quaternion SLERP between your consecutive waypoints, including measured initial TCP. No detours, snapping or target edits.',
        'low_level':'Every node uses closest IK and cubic JOINT interpolation, followed by 0.4 s settle. Minimum node movement duration 0.5 s; this is stop-and-settle tracking, not exact Cartesian interpolation or specified-speed motion.',
        'acceptance':'Every physics sample is checked against its current specified TCP segment; >2 mm position or >1 degree orientation tracking discrepancy stops the chunk after the current numeric group. Endpoint uses the same bounds. Physical safety always stops immediately.',
        'rejection':'Per-node full shared-scene collision preflight before movement. A later rejection can follow earlier executed nodes; receipts state partial execution. No alternate IK path search or automatic repair.'},
    'gripper':{'opening_fraction':'Empty-space command: master_target_rad = -0.91*(1-opening_fraction); 0 closed, 1 open. This is not measured millimetres. Reported pad-centre gap is not exact minimum contact gap.',
        'position':'Follow the requested joint target without bilateral-contact latching; ordinary servo, no implicit grasp selection.',
        'bilateral_hold':'While closing, after two successive bilateral contact samples, stop the ramp and hold the measured master angle minus the existing 0.005 rad preload. The held SERVO TARGET never requests further closure beyond your requested joint target; actual overshoot is possible and monitored. No bilateral contact at the end means explicit execution failure. Omitted gripper retains its last servo target.',
        'controller':'Versioned right master damping=0 after contact latch, K and URDF effort limit unchanged. Left controller unchanged. A new opening command restores ordinary servo settings. No object binding or qpos overwrites.'},
    'ordering':'Stages follow list order. sequential finishes each listed arm operation before the next. parallel advances one resampled node per TCP arm together in shared physics; a gripper operation runs with the first node. An arm finishing early holds. Arms omitted from a group hold drive targets.',
    'time':'Physics paused during inference. Each stage ends with your observe_s passive physical hold. An empty actions list with observe_s>0 only observes while holding drive targets. No expert motion during a hold. done=true requires stages=[] and requests a terminal 2 s hold, not automatic task success.',
    'bounds':{'stages_max':8,'waypoints_per_arm_operation_max':16,'numeric_groups_per_chunk_max':MAX_GROUPS,
        'position_residual_m':POSITION_TOLERANCE_M,'rotation_residual_rad':ROTATION_TOLERANCE_RAD}}


def parse_chunk(raw):
    value=strict_json(raw);jsonschema.validate(value,SCHEMA)
    if value['done'] != (len(value['stages'])==0):raise ValueError('DONE_OR_EMPTY_CHUNK')
    for stage in value['stages']:
        if not stage['actions'] and stage['observe_s']<=0:raise ValueError('EMPTY_STAGE_WITHOUT_OBSERVATION')
        if len({a['arm'] for a in stage['actions']})!=len(stage['actions']):raise ValueError('DUPLICATE_ARM_IN_STAGE')
        for action in stage['actions']:
            for pose in action.get('waypoints_world_wxyz',[]):
                p=np.asarray(pose,float)
                if not np.isfinite(p).all() or abs(np.linalg.norm(p[3:])-1)>.001:raise ValueError('INVALID_POSE')
                if not(-.15<=p[0]<=.9 and -.4<=p[1]<=.4 and .025<=p[2]<=.5):raise ValueError('TCP_WORKSPACE')
    return value


def public_receipt(value):
    """Raw receipts stay archived; private contact truth is not model context."""
    if isinstance(value,dict):return {k:public_receipt(v) for k,v in value.items() if k not in PRIVATE_FEEDBACK_FIELDS}
    if isinstance(value,list):return [public_receipt(v) for v in value]
    return copy.deepcopy(value)


def actual_pose(arm):
    s=arm.state();return list(s['actual_grasp_center_world'])+list(s['flange_pose_world'][3:])


def rotations(pose):return Rotation.from_quat(np.roll(pose[3:],-1))


def segment_nodes(start,goal):
    start=np.asarray(start,float);goal=np.asarray(goal,float)
    angle=float((rotations(start).inv()*rotations(goal)).magnitude())
    count=max(1,int(math.ceil(np.linalg.norm(goal[:3]-start[:3])/MAX_TRANSLATION_M)),
        int(math.ceil(angle/MAX_ROTATION_RAD)))
    t=np.arange(1,count+1)/count
    quat=Slerp([0,1],Rotation.concatenate([rotations(start),rotations(goal)]))(t).as_quat()
    values=np.c_[start[:3]+t[:,None]*(goal[:3]-start[:3]),np.roll(quat,1,axis=1)]
    values[-1]=goal  # Archive/execution receives the exact supplied endpoint.
    return values.tolist()


def operation_nodes(action,start):
    if action['kind']=='gripper':return [{'opening':action['opening_fraction'],'contact_mode':action['contact_mode']}]
    nodes=[]
    for index,goal in enumerate(action['waypoints_world_wxyz']):
        previous=start
        for pose in segment_nodes(start,goal):
            nodes.append({'pose':pose,'segment_start':previous,'waypoint_index':index})
            previous=pose
        start=goal
    return nodes


def tracking_errors(pose,start,end):
    """Position and orientation distance to current user-derived short segment.

    Projection parameters are independent: this bounds cross-track discrepancy,
    not along-track timing or exact Cartesian path adherence.
    """
    p=np.asarray(pose,float);a=np.asarray(start,float);b=np.asarray(end,float)
    d=b[:3]-a[:3];u=float(np.clip(np.dot(p[:3]-a[:3],d)/np.dot(d,d),0,1)) if np.dot(d,d)>1e-20 else 0.
    position=float(np.linalg.norm(p[:3]-(a[:3]+u*d)))
    # Each orientation subsegment <=1 degree: nearest endpoint bound remains
    # conservative without silently choosing an intermediate orientation.
    rotation=min(float((rotations(a).inv()*rotations(p)).magnitude()),float((rotations(b).inv()*rotations(p)).magnitude()))
    return position,rotation


def execute_chunk(world,value):
    value=parse_chunk(json.dumps(value,allow_nan=False))
    if value['done']:return {'ok':True,'executed':False,'reason':'MODEL_STOP_REQUEST','interface':VERSION}
    number=getattr(world,'chunk_count',0)+1;world.chunk_count=number
    folder=Path(world.output)/f'chunk_{number:03d}';folder.mkdir()
    def save(name,value):(folder/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    save('proposal.json',value)
    receipt={'ok':True,'executed':False,'interface':VERSION,'start_step':world.steps,'groups':[],
        'input_unchanged':True,'automatic_waypoint_selection':False,'scope':'per-node preflight; partial execution possible'}
    group_count=0;in_flight=None
    try:
        for si,stage in enumerate(value['stages']):
            streams={a['arm']:operation_nodes(a,actual_pose(world.arms[a['arm']])) for a in stage['actions']}
            if not streams:batches=[]
            elif stage['mode']=='parallel':
                batches=[{s:n[i] for s,n in streams.items() if i<len(n)} for i in range(max(map(len,streams.values())))]
            else:batches=[{a['arm']:n} for a in stage['actions'] for n in streams[a['arm']]]
            if group_count+len(batches)>MAX_GROUPS:
                receipt.update(ok=False,reason='CHUNK_GROUP_LIMIT',rejected_stage=si);break
            for bi,batch in enumerate(batches):
                group_count+=1
                commands={s:({k:v for k,v in node.items() if k in ('pose','opening','contact_mode')}) for s,node in batch.items()}
                before=world.steps;log={'stage_index':si,'subgroup_index':bi,'commands':copy.deepcopy(commands)}
                in_flight=log
                save('progress.json',dict(receipt,in_flight=log))
                r=world.execute_group(commands);log['receipt']=r
                trace={}
                for side,node in batch.items():
                    if 'pose' not in node:continue
                    samples=[x for x in world.records if before<x['step']<=world.steps]
                    errors=[tracking_errors([*x['arms'][side]['actual_grasp_center_world'],*x['arms'][side]['flange_pose_world'][3:]],node['segment_start'],node['pose']) for x in samples]
                    goal=r.get('goal_residuals',{}).get(side,{})
                    trace[side]={'user_waypoint_index':node['waypoint_index'],'samples':len(errors),
                        'max_position_cross_track_m':max((x[0] for x in errors),default=0.),
                        'max_orientation_endpoint_distance_rad':max((x[1] for x in errors),default=0.),'endpoint':goal}
                log['tracking']=trace;receipt['groups'].append(log);in_flight=None;receipt['executed']=world.steps>receipt['start_step']
                if not r['ok']:
                    receipt.update(ok=False,reason=r.get('reason','NUMERIC_EXECUTION_FAILED'));break
                if any(t['max_position_cross_track_m']>POSITION_TOLERANCE_M or t['max_orientation_endpoint_distance_rad']>ROTATION_TOLERANCE_RAD or t['endpoint'].get('position_error_m',0)>POSITION_TOLERANCE_M or t['endpoint'].get('rotation_error_rad',0)>ROTATION_TOLERANCE_RAD for t in trace.values()):
                    receipt.update(ok=False,reason='TRACKING_TOLERANCE_EXCEEDED');break
            if not receipt['ok']:break
            world.phase_name='chunk_passive_observation';world.tick(int(math.ceil(stage['observe_s']/world.dt)))
    except Exception as exc:
        stopped=any(getattr(a,'stopped',None) is not None and a.stopped.is_set() for a in world.arms.values())
        receipt.update(ok=False,reason='PHYSICAL_PROTECTION_STOP' if stopped else 'EXECUTOR_EXCEPTION',
            error=repr(exc),safety_stop=stopped)
        if in_flight is not None:
            in_flight['receipt']={'ok':False,'executed':'PARTIAL' if world.steps>before else False,
                'start_step':before,'end_step':world.steps,'error':repr(exc)}
            receipt['groups'].append(in_flight)
        raise
    finally:
        receipt.update(end_step=world.steps,executed=world.steps>receipt['start_step'],numeric_groups_attempted=group_count)
        if not receipt['ok'] and receipt['executed']:receipt['execution_status']='PARTIAL_FAILED'
        else:receipt['execution_status']='COMPLETE' if receipt['ok'] else 'REJECTED_WITHOUT_MOTION'
        save('receipt.json',receipt)
    return receipt
