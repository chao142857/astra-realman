"""Offline migration of chunk semantics. No SDK, camera or model imports.

Hardware dispatch is deliberately unavailable until calibrated frames, swept
collision checks, trajectory tracking and in-flight stop have been accepted.
No task routes or contact targets are selected here.
"""
import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from io_utils import strict_json, number, vector
from chunk_protocol_v2_1 import SCHEMA, validate_control_semantics

VERSION = 'real_chunk_offline_v1'
BLOCKERS = ['world_base_tcp_calibration', 'four_camera_calibration',
            'shared_swept_collision', 'trajectory_tracking', 'inflight_stop',
            'gripper_position_calibration', 'bilateral_hold_feedback',
            'new_model_and_motion_authorization']


def fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('FIELDS:' + ','.join(expected))


def parse_chunk(raw):
    value = strict_json(raw)
    fields(value, ['done', 'stages'])
    if type(value['done']) is not bool or not isinstance(value['stages'], list) or len(value['stages']) > 8:
        raise ValueError('CHUNK_SHAPE')
    for stage in value['stages']:
        fields(stage, ['mode', 'actions', 'observe_s'])
        if stage['mode'] not in ('sequential', 'parallel') or not number(stage['observe_s']) or not 0 <= stage['observe_s'] <= 5:
            raise ValueError('STAGE_VALUES')
        if not isinstance(stage['actions'], list) or len(stage['actions']) > 2:
            raise ValueError('ACTION_COUNT')
        for action in stage['actions']:
            if not isinstance(action, dict):raise ValueError('ACTION_OBJECT')
            kind = action.get('kind')
            fields(action, ['arm', 'kind', 'waypoints_world_wxyz'] if kind == 'tcp' else ['arm', 'kind', 'opening_fraction', 'contact_mode'])
            if action['arm'] not in ('left', 'right'):raise ValueError('ARM')
            if kind == 'tcp':
                poses = action['waypoints_world_wxyz']
                if not isinstance(poses, list) or not 1 <= len(poses) <= 16:raise ValueError('WAYPOINT_COUNT')
                for p in poses:
                    if not vector(p, 7) or abs(sum(x*x for x in p[3:]) - 1) > 1e-6:raise ValueError('POSE_OR_UNIT_QUATERNION')
            elif kind == 'gripper':
                if not number(action['opening_fraction']) or not 0 <= action['opening_fraction'] <= 1:raise ValueError('OPENING')
                if action['contact_mode'] not in ('position', 'bilateral_hold'):raise ValueError('CONTACT_MODE')
            else:raise ValueError('KIND')
    validate_control_semantics(value)
    return value


def qmul(a, b):
    w,x,y,z=a;v,i,j,k=b
    return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v]


def compose(a, b):
    """T_A_C = T_A_B * T_B_C; xyz metres, quaternion wxyz."""
    q=a[3:];rot=qmul(qmul(q,[0]+b[:3]),[q[0],-q[1],-q[2],-q[3]])[1:]
    return [a[i]+rot[i] for i in range(3)]+qmul(q,b[3:])


def inverse(a):
    q=[a[3],-a[4],-a[5],-a[6]]
    return compose([0,0,0]+q,[-x for x in a[:3]]+[1,0,0,0])


def sdk_target(world_tcp, world_work, tool_tcp):
    """Pure preview conversion only. All three transforms must be explicit.

    T_work_tool = inv(T_world_work) * T_world_tcp * inv(T_tool_tcp).
    No default identity, inferred pad offset or simulated base spacing.
    Returns SDK xyz/RPY (Rz(yaw) Ry(pitch) Rx(roll)); not a motion permit.
    """
    for p in (world_tcp, world_work, tool_tcp):
        if not vector(p,7) or abs(sum(x*x for x in p[3:])-1)>1e-6:raise ValueError('EXPLICIT_RIGID_TRANSFORM_REQUIRED')
    p=compose(compose(inverse(world_work),world_tcp),inverse(tool_tcp))
    w,x,y,z=p[3:]
    pitch=2*(w*y-z*x)
    if abs(pitch)>1-1e-8:raise ValueError('RPY_SINGULARITY_UNVALIDATED')
    return p[:3]+[math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),math.asin(pitch),math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))]


def subdivide(start, waypoints):
    """Preview of only model segments: <=5 mm / 1 degree; endpoints unchanged.

    This is not proof that rm_movej_p will track these Cartesian segments.
    """
    current=list(start);result=[]
    for segment, end in enumerate(waypoints):
        dot=sum(a*b for a,b in zip(current[3:],end[3:]));qb=end[3:]
        if dot<0:qb=[-x for x in qb];dot=-dot
        angle=math.acos(min(1,max(-1,dot)))
        n=max(1,math.ceil(math.dist(current[:3],end[:3])/.005),math.ceil(2*angle/math.radians(1)))
        if len(result)+n>128:raise ValueError('SUBDIVISION_LIMIT')
        for index in range(1,n+1):
            t=index/n
            if index==n:p=list(end)
            else:
                q=[(1-t)*a+t*b for a,b in zip(current[3:],qb)] if angle<1e-8 else [(math.sin((1-t)*angle)*a+math.sin(t*angle)*b)/math.sin(angle) for a,b in zip(current[3:],qb)]
                norm=math.sqrt(sum(x*x for x in q));p=[(1-t)*a+t*b for a,b in zip(current[:3],end[:3])]+[x/norm for x in q]
            result.append({'segment_index':segment,'target_world_wxyz':p,'original_waypoint':index==n})
        current=list(end)
    return result


def save(path, value):
    """Immutable journal entries; no resuming or overwriting a dispatch."""
    with Path(path).open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())


class FakeBackend:
    """Explicit software fixture, never evidence of physical success."""
    def __init__(self):
        self.states={a:{'tcp_world_wxyz':[0,0,.3,1,0,0,0], 'opening_fraction':1., 'sequence':0} for a in ('left','right')}
        self.calls=[]
    def read(self, arm):return copy.deepcopy(self.states[arm])
    def check(self, batch):
        if any(a.get('contact_mode')=='bilateral_hold' for _,a in batch):return 'UNSUPPORTED_BILATERAL_HOLD'
        return None
    def execute_batch(self, batch):
        # Parallel is a logical simultaneous fake group; not two real SDK calls.
        self.calls.append(copy.deepcopy(batch))
        for arm,node in batch:
            s=self.states[arm];s['sequence']+=1
            if node['kind']=='tcp':s['tcp_world_wxyz']=copy.deepcopy(node['target_world_wxyz'])
            else:s['opening_fraction']=node['opening_fraction']
        return {'status':'FAKE_EXECUTED','command_execution':'FAKE_EXECUTED',
                'contact_hold_state':'UNKNOWN','stable_grasp':'NOT_ASSESSED', 'hardware_commands_sent':0}
    def observe(self, seconds):return {'requested_s':seconds,'source':'FAKE_NO_PHYSICS_OR_WALL_WAIT'}


class _Rejected(Exception):
    pass


class OfflineChunkAdapter:
    def __init__(self, backend, mode='offline'):
        if mode!='offline' or not isinstance(backend,FakeBackend):
            raise ValueError('REAL_EXECUTION_BLOCKED:' + ','.join(BLOCKERS))
        self.backend=backend
    def run(self, raw, step):
        step=Path(step);step.mkdir(parents=True,exist_ok=False)
        (step/'raw_proposal.txt').write_text(raw)
        save(step/'migration.json',{'version':VERSION,'source_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'synthetic':True,'model_requests':0,'hardware_commands_sent':0,'real_blockers':BLOCKERS})
        start=time.monotonic();operations=[];status='FAKE_COMPLETED';reason=None
        try:
            chunk=parse_chunk(raw);save(step/'parsed_chunk.json',chunk);save(step/'action_schema.json',SCHEMA)
            if chunk['done']:status='MODEL_DONE_NOT_TASK_SUCCESS'
            for si,stage in enumerate(chunk['stages']):
                # Sequential runs a complete operation before taking the next read.
                groups=[[i] for i in range(len(stage['actions']))] if stage['mode']=='sequential' else [list(range(len(stage['actions'])))]
                for indices in groups:
                    streams=[];rows=[]
                    for oi in indices:
                        a=stage['actions'][oi];before=self.backend.read(a['arm'])
                        row={'operation_id':f's{si:02d}-o{oi:02d}-{a["arm"]}', 'stage_index':si,'operation_index':oi,
                             'mode':stage['mode'],'arm':a['arm'],'proposal':copy.deepcopy(a),'before':before,'nodes':[],'status':'PREPARED'}
                        operations.append(row);rows.append(row)
                        nodes=[dict(n,kind='tcp') for n in subdivide(before['tcp_world_wxyz'],a['waypoints_world_wxyz'])] if a['kind']=='tcp' else [copy.deepcopy(a)]
                        streams.append(nodes)
                    for ni in range(max((len(s) for s in streams),default=0)):
                        active=[(row,stream[ni]) for row,stream in zip(rows,streams) if ni<len(stream)]
                        batch=[(r['arm'],n) for r,n in active]
                        refusal=self.backend.check(batch)
                        if refusal:
                            for row,node in active:
                                row.update(status='REJECTED',reason=refusal)
                                row['nodes'].append({'node_index':ni,'requested':node,'status':'REJECTED','reason':refusal})
                            status='REJECTED';reason=refusal;raise _Rejected
                        claim=f's{si:02d}-g{indices[0] if indices else 0:02d}-n{ni:03d}'
                        save(step/(claim+'-fake-dispatch.claim.json'),{'batch':batch,'synthetic':True,'status':'RESERVED_OUTCOME_UNKNOWN'})
                        for row,node in active:row['status']='DISPATCH_RESERVED_OUTCOME_UNKNOWN'
                        receipt=self.backend.execute_batch(batch)
                        if receipt.get('status')!='FAKE_EXECUTED':raise RuntimeError('UNKNOWN_OR_FAILED_COMPLETION')
                        for row,node in active:
                            row['nodes'].append({'node_index':ni,'requested':node,'receipt':copy.deepcopy(receipt),'after':self.backend.read(row['arm'])})
                    for row in rows:
                        row.update(status='FAKE_EXECUTED',after=self.backend.read(row['arm']))
                        save(step/(row['operation_id']+'.json'),row)
                save(step/f's{si:02d}-observe.json',self.backend.observe(stage['observe_s']))
        except _Rejected:pass
        except Exception as exc:
            status='STOPPED';reason=type(exc).__name__+':'+str(exc)
        result={'status':status,'reason':reason,'synthetic':True,'operations':operations,
                'hardware_commands_sent':0,'model_requests':0,'task_success':'NOT_ASSESSED', 'elapsed_s':time.monotonic()-start}
        save(step/'chunk_result.json',result)
        return result
