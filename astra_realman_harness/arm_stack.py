"""Symmetric facade over the existing state, exact IK, executor and lab gripper paths."""
import copy
import hashlib
import json
import time
import uuid
from pathlib import Path
from io_utils import ROOT, number, vector, write_json
from left_terminal import parse, command_plan, validate_state
from left_executor import RealArmExecutor
from exact_target_feasibility import check_exact_target, dispatch_checked

ENDPOINTS={'left':('192.168.1.19',8080),'right':('192.168.1.18',8080)}
CONFIGS={arm:'/home/tongji/aloha/RealMan_Control/config/rm_'+arm+'_arm.yaml' for arm in ENDPOINTS}


def capture_states(session, path, *, task='', previous=None, streams=None):
    """Same SDKReadOnly snapshot and existing RM-plus read; preserve raw telemetry."""
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    states={}
    for arm in session.connected:
        sample=session.snapshot(arm);write_json(path/(arm+'-sdk-sample.json'),sample)
        state=sample['canonical']
        if state is None:raise RuntimeError(arm+':CANONICAL_STATE_FAILED')
        raw=session.connected[arm].rm_get_rm_plus_state_info()
        write_json(path/(arm+'-gripper-raw.json'),{'timestamp':time.time(),'raw_return':raw,'units':'raw SDK fields; no force interpretation'})
        if not isinstance(raw,(tuple,list)) or len(raw)!=2 or type(raw[0]) is not int or raw[0]!=0:
            raise RuntimeError(arm+':GRIPPER_READ_FAILED:'+str(raw))
        g=raw[1]
        state['gripper_state']={'position':g['pos'][0],'position_range':[0,1000],'raw':g}
        states[arm]=state
    if not states:raise RuntimeError('NO_CONNECTED_ARMS')
    images,failures,metrics=streams.snapshot(path) if streams else ([],[],{'capture_span_ms':0})
    obs={'observation_id':'arms-'+uuid.uuid4().hex,'canonical_states':states,'task':task,'previous':previous,
         'cameras':images,'capture_failures':failures,'capture_span_ms':metrics['capture_span_ms'],
         'camera_capture':metrics,'captured_at':min([s['timestamp'] for s in states.values()]+[i['captured_at'] for i in images]),
         'source':'LIVE_READ_ONLY','camera_source':'LIVE' if streams else 'NO_CAMERAS_STATE_ONLY'}
    write_json(path/'observation.json',obs)
    return obs


def schema_for(states):
    """Unchanged eight fields; enum alternatives derived from actual controller frame IDs."""
    schema=json.loads((ROOT/'schema/left_opening.schema.json').read_text())
    for field in ('arm','frame','tool_frame'):
        schema['properties'][field]['enum']=[arm if field=='arm' else s['work_frame' if field=='frame' else 'tool_frame']['id'] for arm,s in states.items()]
    return schema


def model_input(obs):
    """Identical left/right projections; no hidden task instructions or frame transforms."""
    states=obs['canonical_states']
    if not states or set(states)-set(ENDPOINTS) or obs.get('capture_failures'):raise ValueError('ARM_OBSERVATION')
    images=[]
    for i,c in enumerate(obs['cameras'],1):
        path=Path(c['image_path']).resolve()
        if ROOT/'logs' not in path.parents or not path.is_file() or not 0<path.stat().st_size<=8*1024*1024:raise ValueError('IMAGE_PATH_OR_SIZE')
        data=path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=c['sha256']:raise ValueError('IMAGE_INTEGRITY')
        images.append({**{k:c.get(k) for k in ('serial','role','role_confirmed','image_path','captured_at')},'input_index':i})
    robots={};works={};tools={}
    for arm,s in states.items():
        if s['arm']!=arm:raise ValueError('ARM_IDENTITY')
        robots[arm]={k:copy.deepcopy(s[k]) for k in ('arm','joint_deg','system_error','timestamp')}
        robots[arm]['ee_pose']={k:copy.deepcopy(s['ee_pose'][k]) for k in ('xyz_m','rpy_rad','units')}
        g=s.get('gripper_state',{})
        robots[arm]['gripper']={'opening_feedback':g.get('position')/1000 if number(g.get('position')) else None,
                               'range':[0,1],'zero':'fully closed','one':'fully open','quantity':'opening, not force'}
        works[arm]={k:copy.deepcopy(s['work_frame'][k]) for k in ('id','name','pose')}
        tools[arm]={k:copy.deepcopy(s['tool_frame'][k]) for k in ('id','name','pose')}
    return {'task':obs['task'],'observation_id':obs['observation_id'],'images_in_attachment_order':images,
            'robot_states':robots,'work_frames':works,'tool_frames':tools,'previous':obs.get('previous'),'action_schema':schema_for(states)}


class ArmStack:
    """Persistent arm facade; a fresh one-shot existing executor per explicit operation."""
    def __init__(self,arm_id,session,capture,stop,root,*,execute_enabled=False,gripper_factory=None):
        if arm_id not in ENDPOINTS:raise ValueError('ARM_ID')
        self.arm_id=arm_id;self.session=session;self.capture=capture;self.stop=stop;self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True);self.execute_enabled=execute_enabled
        self.gripper_factory=gripper_factory;self.seen=set()
    def read_state(self):return self.capture(self.root/('read-'+uuid.uuid4().hex))['canonical_states'][self.arm_id]
    def hold(self):return {'arm_id':self.arm_id,'status':'HOLD','commands_sent':0}
    def _action(self,state,translation,rotation,opening):
        return {'action_type':'cartesian_delta','arm':self.arm_id,'frame':state['work_frame']['id'],
                'tool_frame':state['tool_frame']['id'],'translation_m':translation,'rotation_rpy_rad':rotation,
                'gripper_opening':opening,'done':False}
    def run(self, action, operation_id, *, observation=None):
        if not isinstance(operation_id,str) or not operation_id or len(operation_id)>128:raise ValueError('OPERATION_ID')
        if operation_id in self.seen:raise RuntimeError('NO_RETRY_OPERATION_CONSUMED')
        self.seen.add(operation_id)
        # Hash the identifier so external IDs cannot escape the journal root.
        step=self.root/hashlib.sha256(operation_id.encode()).hexdigest();step.mkdir(exist_ok=False)
        write_json(step/'raw_proposal.json',action)
        obs=observation if observation is not None else self.capture(step/'before')
        state=obs['canonical_states'][self.arm_id]
        parsed=parse(json.dumps(action,allow_nan=False),self.arm_id,state['work_frame']['id'],state['tool_frame']['id'])
        write_json(step/'parsed_action.json',parsed)
        for arm,s in obs['canonical_states'].items():
            errors=validate_state(obs,live=True,max_age_s=3,arm_id=arm,work=s['work_frame']['id'],tool=s['tool_frame']['id'],
                                  frame_fingerprints={k:s[k]['definition_fingerprint'] for k in ('work_frame','tool_frame')})
            if errors:raise RuntimeError(arm+':PREFLIGHT:'+','.join(errors))
        check=check_exact_target(self.session,parsed,obs,allow_shared_session=True)
        write_json(step/'feasibility.json',check);write_json(step/'planned_action.json',command_plan(parsed,state))
        if self.execute_enabled:
            result=dispatch_checked(parsed,obs,check,lambda:RealArmExecutor(self.session,self.capture,self.stop,step,
                                             self.gripper_factory,arm_id=self.arm_id))
        else:
            result={'status':check['status'] if check['status'] not in ('PASS_IK','NOT_REQUIRED') else 'DRY_RUN_NOT_SENT',
                    'hardware_commands_sent':0,'executed_action':{'arm':None,'gripper':None}}
            write_json(step/'execution_result.json',result)
        after=self.capture(step/'after');write_json(step/'after_state.json',after['canonical_states'])
        after_errors=[]
        for arm,s in after['canonical_states'].items():
            before=obs['canonical_states'][arm]
            after_errors.extend(arm+':'+e for e in validate_state(after,live=True,max_age_s=3,arm_id=arm,
                work=before['work_frame']['id'],tool=before['tool_frame']['id'],
                frame_fingerprints={k:before[k]['definition_fingerprint'] for k in ('work_frame','tool_frame')}))
        result=dict(result,after_state=after['canonical_states'],log=str(step),feasibility=check,after_errors=after_errors)
        if after_errors:result.update(status='STOPPED',error='AFTER_STATE:'+','.join(after_errors))
        write_json(step/'result.json',result)
        if after_errors:raise RuntimeError(result['error'])
        return result
    def move_delta(self,translation,rotation,frame,operation_id):
        if not vector(translation,3) or not vector(rotation,3):raise ValueError('DELTA_FINITE')
        obs=self.capture(self.root/('input-'+uuid.uuid4().hex));s=obs['canonical_states'][self.arm_id]
        if frame!=s['work_frame']['id']:raise ValueError('FRAME_MISMATCH')
        return self.run(self._action(s,translation,rotation,s['gripper_state']['position']/1000),operation_id,observation=obs)
    def move_to_pose(self,pose,frame,tool_frame,operation_id):
        if not vector(pose,6):raise ValueError('POSE_FINITE')
        obs=self.capture(self.root/('input-'+uuid.uuid4().hex));s=obs['canonical_states'][self.arm_id]
        if frame!=s['work_frame']['id'] or tool_frame!=s['tool_frame']['id']:raise ValueError('FRAME_TOOL_MISMATCH')
        current=s['ee_pose']['xyz_m']+s['ee_pose']['rpy_rad'];delta=[x-y for x,y in zip(pose,current)]
        return self.run(self._action(s,delta[:3],delta[3:],s['gripper_state']['position']/1000),operation_id,observation=obs)
    def set_gripper(self,opening,operation_id):
        obs=self.capture(self.root/('input-'+uuid.uuid4().hex));s=obs['canonical_states'][self.arm_id]
        return self.run(self._action(s,[0,0,0],[0,0,0],opening),operation_id,observation=obs)
    def retract(self,pose,frame,tool_frame,operation_id):return self.move_to_pose(pose,frame,tool_frame,operation_id)
