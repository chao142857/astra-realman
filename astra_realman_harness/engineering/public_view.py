"""Read-only frozen observation/result projection. No owner, policy or scheduler."""
import copy,hashlib,json,math
from pathlib import Path
from sim_skills.model import state_projection
from sim_skills.full_pnp.wire import parse_actual_raw
CAMERAS=('assembly','fixed','wrist')
ERRORS=('GRASP_CONTACT_LOST_DURING_EXECUTION','GRASP_CONTACT_LOST_AFTER_LATCH','GRASP_CONTACT_NOT_ESTABLISHED',
 'PAD_CONTACT_PENETRATION','SCENE_COLLISION','SELF_COLLISION','TRACKING_ERROR','ACTUAL_JOINT_LIMIT',
 'PRE_GRIPPER_UNKNOWN','PRE_GRIPPER_INVALID','STOPPED','HUMAN_STOP','EXECUTION_TIMEOUT','IK Failed')
def error_code(raw):
    if not raw:return None
    return next((x for x in ERRORS if x in str(raw)),'UNCLASSIFIED_EXECUTION_ERROR')
def finite(value):
    if isinstance(value,list):return all(finite(x) for x in value)
    return type(value) in (int,float) and math.isfinite(value)
def robot_state(raw):
    s=state_projection(raw)
    for k,v in s.items():
        if k=='joint_names':
            if not isinstance(v,list) or not all(isinstance(n,str) for n in v):raise ValueError('STATE_JOINT_NAMES')
        elif k=='stopped':
            if type(v) is not bool:raise ValueError('STATE_STOPPED')
        elif not finite(v):raise ValueError('STATE_NONNUMERIC:'+k)
    return s

def observation(raw,destination):
    """Inputs are already captured immutable data; never access scene or score."""
    dest=Path(destination);dest.mkdir(parents=True,exist_ok=False)
    cal={}
    for name in CAMERAS:
        c=raw['calibration'][name]
        for k in ('pose_world_xyz_wxyz','intrinsic','resolution'):
            if not finite(c[k]):raise ValueError('CALIBRATION_NONNUMERIC')
        cal[name]={k:copy.deepcopy(c[k]) for k in ('pose_world_xyz_wxyz','intrinsic','resolution')}
        cal[name]['axes']='SAPIEN +x forward,+y left,+z up'
    out={'schema':'astra.shared.observation.v1','observation_id':raw['observation_id'],
       'captured_monotonic':raw['captured_monotonic'],'capture_span_s':raw['capture_span_s'],
       'timestamp_semantics':'owner monotonic capture-completed time; three sequential images, not hardware exposure synchronization',
       'frame':'sapien:world','state':robot_state(raw['state']),'calibration':cal,'rgb':[]}
    for key in ('captured_monotonic','capture_span_s'):
        if not finite(out[key]):raise ValueError('CAPTURE_TIME')
    for name in CAMERAS:
        data=Path(raw['images'][name]).read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>8*1024*1024:raise ValueError('PNG')
        file=name+'.png';(dest/file).write_bytes(data)
        out['rgb'].append({'camera':name,'file':file,'sha256':hashlib.sha256(data).hexdigest(),'sensor_exposure_timestamp':None})
    if 'depth' in raw:
        from platform_v1.research.rgbd_sensor import export_depth, VERSION
        out['depth']=export_depth(raw,dest,out['rgb']);out['schema']=VERSION
        out['timestamp_semantics']='RGB and depth share cached render; exact frozen simulation step; no hardware exposure-time claim'
    (dest/'observation.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');return out

def execution(raw):
    """Expose actual feedback, not engineering action targets or arbitrary error text."""
    results=[]
    for item in raw.get('results',[]):
        r=item['result'];o={k:copy.deepcopy(r[k]) for k in ('ok','planning_s','trajectory_steps','position_error_m','rotation_error_rad','noop') if k in r}
        for k,v in o.items():
            if k in ('ok','noop'):
                if type(v) is not bool:raise ValueError('EXECUTION_BOOL')
            elif not finite(v):raise ValueError('EXECUTION_NONNUMERIC')
        if 'after' in r:o['after']=robot_state(r['after'])
        o['error_code']=error_code(r.get('error') or (r.get('planner_status') if not r.get('ok') else None));results.append(o)
    if type(raw['ok']) is not bool or type(raw.get('unexecuted_count',0)) is not int:raise ValueError('EXECUTION_ENVELOPE')
    return {'schema':'astra.shared.execution.v1','ok':raw['ok'],'results':results,'unexecuted_count':raw.get('unexecuted_count',0),
       'error_code':error_code(raw.get('error')),'holding_status':'UNKNOWN_FROM_COMMAND_COMPLETION',
       'commanded_actions':'withheld from engineering observation export; model proposals have separate raw provenance'}

def model_proposal(raw,wire,*,source):
    if source!='MODEL_RAW':raise ValueError('ENGINEERING_ANSWERS_NOT_MODEL_INPUT')
    if wire['role'] not in ('B','A'):raise ValueError('NOT_ACTION_RAW')
    return {'source':source,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'candidate':parse_actual_raw(raw,wire),'authority':'PROPOSAL_ONLY_NO_EXECUTION'}
