"""Explicit SYNTHETIC fixtures. No physical observations or hardware calls."""
import base64
import copy
import hashlib
import time
from io_utils import ROOT, read_json, write_json, new_run
from realman_api2_readonly import canonical_state
from left_terminal import command_plan
from history_diagnostics import build_transition

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jp1kAAAAASUVORK5CYII=')


def action():
    return {'action_type':'cartesian_delta','arm':'left','frame':'realman:left:work:World',
            'tool_frame':'realman:left:tool:Arm_Tip','translation_m':[.04,0,0],
            'rotation_rpy_rad':[0,0,0],'gripper_opening':1,'done':False}


def state(now=None):
    now = time.time() if now is None else now
    raw = {'joint':[0.,20.,30.,0.,90.,0.],'pose':[-.35,.07,.35,-3.04,.21,.07],
           'err':{'err_len':1,'err':['0']}}
    work = {'name':'World','pose':[0.]*6,'payload':0.,'x':0.,'y':0.,'z':0.}
    tool = dict(work,name='Arm_Tip')
    values = {'state':raw,'work_before':work,'work_after':work,'tool_before':tool,'tool_after':tool}
    sample = {'calls':{k:{'return_code':0,'raw_return':[0,copy.deepcopy(v)],'finished_at':now} for k,v in values.items()}}
    s = canonical_state('left',sample,connection={'arm':'left','ip':'192.168.1.19','port':8080})
    s['source']['kind'] = 'SYNTHETIC'
    s['gripper_state'] = {'position':1000,'position_range':[0,1000],
                          'raw':{'pos':[1000],'speed':[0],'sys_state':0,'dof_err':[0]}}
    return s


def observation(folder, index=0, now=None):
    now = time.time() if now is None else now
    cameras = []
    for camera in read_json(ROOT/'config/left_terminal.json')['cameras']:
        path = folder/(camera['role']+'-'+str(index)+'.png')
        if not path.exists():
            path.write_bytes(PNG)
        cameras.append(dict(camera,image_path=str(path),sha256=hashlib.sha256(PNG).hexdigest(),captured_at=now))
    return {'observation_id':'synthetic-'+str(index),'task':'  SYNTHETIC: put ball in basket  ',
            'canonical_states':{'left':state(now)},'cameras':cameras,'captured_at':now,
            'decision_ready_at':now,'capture_failures':[],'capture_span_ms':0,
            'previous':None,'source':'SYNTHETIC_NOT_REAL'}


def make_run(output):
    new_run(output)
    write_json(output/'SYNTHETIC.json',{'synthetic':True,'meaning':'Data-flow fixture only; images are 1 pixel, no scene or success evidence.'})
    episode = output.name
    base = time.time()-100
    current = observation(output,0,base)
    for i in range(1,8):
        step = new_run(output/('step-%02d'%i))
        current.update(episode_id=episode,decision_ready_at=base+i*10)
        write_json(step/'input_observation.json',current)
        if i==7:
            break
        before = copy.deepcopy(current)
        before['canonical_states']['left']['ee_pose']['xyz_m'][0] += .001
        after = observation(output,i,base+i*10+1)
        a = action()
        plan = command_plan(a,before['canonical_states']['left'])
        rejected = i==2
        execution = {'status':'REJECTED_IK' if rejected else 'EXECUTED',
                     'executed_action':{'arm':None if rejected else plan['arm'],'gripper':None},
                     'hardware_commands_sent':0 if rejected else 1,
                     'sdk_result':{'called':not rejected,'arm':None if rejected else 0,'gripper':None}}
        check = {'status':'REJECTED_IK' if rejected else 'PASS_IK','original_target':plan['arm']['pose'],
                 'return_code':1 if rejected else 0,'reason':'SYNTHETIC endpoint check'}
        # Deliberately substantial measured tracking residual; not a success/failure label.
        after['canonical_states']['left']['ee_pose']['xyz_m'][0] = before['canonical_states']['left']['ee_pose']['xyz_m'][0] + (0 if rejected else .01)
        after['canonical_states']['left']['raw_sdk_state']['pose'] = after['canonical_states']['left']['ee_pose']['xyz_m'] + after['canonical_states']['left']['ee_pose']['rpy_rad']
        t = build_transition(episode,i,current,before,after,a,execution,check,completed_at=base+i*10+2)
        write_json(step/'transition.json',t)
        write_json(step/'next_observation.json',after)
        current = after
    return output
