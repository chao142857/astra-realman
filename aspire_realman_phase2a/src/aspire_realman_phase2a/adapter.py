"""Native EnvironmentAdapter over a strictly typed Stub and actual planner client."""
from dataclasses import replace
import json
from pathlib import Path
import time
import uuid
import xml.etree.ElementTree as ET
import numpy as np
import requests
from cap_harness.contracts import (RobotState,Pose,Observation,CameraObservation,TaskContext,PointCloud,
    PlanningScene,RobotPlanningContext,StepResult,ExecutionResult,SynchronizedTrajectory)
from cap_harness.errors import ApiError,ErrorCode
from cap_harness.geometry import matrix_to_quaternion_wxyz
from aspire_realman.codec import rpy_matrix
from aspire_realman.adapter import RealManAdapter
from .model import ARMS,NAMES,FRAME,MODEL
from .execution import StubTransport,ExecutionEngine


class ModelFK:
    """Nominal URDF FK for synthetic Stub feedback; no real state/TCP claims."""
    def __init__(self,manifest):
        root=ET.parse(manifest['urdf']['path']).getroot()
        self.rows=[];self.locked={}
        import yaml
        kin=yaml.safe_load(Path(manifest['config']['path']).read_text())['robot_cfg']['kinematics']
        self.locked=kin['lock_joints']
        for joint in root.findall('joint'):
            origin=joint.find('origin');axis=joint.find('axis')
            xyz=[float(v) for v in origin.get('xyz','0 0 0').split()] if origin is not None else [0,0,0]
            rpy=[float(v) for v in origin.get('rpy','0 0 0').split()] if origin is not None else [0,0,0]
            t=np.eye(4);t[:3,:3]=rpy_matrix(rpy);t[:3,3]=xyz
            self.rows.append((joint.get('name'),joint.get('type'),joint.find('parent').get('link'),joint.find('child').get('link'),t,
                np.array([float(v) for v in axis.get('xyz').split()]) if axis is not None else np.array([0,0,1.])))
    def poses(self,positions):
        q={n:float(v) for arm in ARMS for n,v in zip(NAMES[arm],positions[arm])};q.update(self.locked)
        known={'SYNTHETIC_rm65_world':np.eye(4)};pending=list(self.rows)
        while pending:
            previous=len(pending)
            deferred=[]
            for row in pending:
                name,kind,parent,child,t,axis=row
                if parent not in known:deferred.append(row);continue
                rotation=np.eye(4)
                if kind in ('revolute','continuous'):
                    unit=axis/np.linalg.norm(axis);x,y,z=unit;k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
                    a=q[name];rotation[:3,:3]=np.eye(3)+np.sin(a)*k+(1-np.cos(a))*(k@k)
                known[child]=known[parent]@t@rotation
            pending=deferred
            if len(pending)==previous:raise ValueError('URDF_DISCONNECTED_OR_CYCLIC')
        return {arm:Pose(known[arm+'_Link6'][:3,3],matrix_to_quaternion_wxyz(known[arm+'_Link6'][:3,:3]),FRAME) for arm in ARMS}


class GpuTrajectoryValidator:
    def __init__(self,provider):self.provider=provider;self.records=[]
    def __call__(self,trajectory,state,context,scene):
        data=self.provider._base_payload(state,context,scene)
        values=trajectory.joint_positions if isinstance(trajectory,SynchronizedTrajectory) else {trajectory.arm:trajectory.joint_positions}
        data.update(waypoints={a:q.tolist() for a,q in values.items()},dt_s=trajectory.dt_s)
        with requests.Session() as session:
            session.trust_env=False
            try:response=session.post(self.provider.base_url+'/v1/realman/validate_trajectory',json=data,timeout=180)
            except requests.RequestException as exc:raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE,'GPU_POST_RESAMPLE_CHECK_UNAVAILABLE',details={'error':str(exc)}) from exc
        if response.status_code!=200:raise ApiError(ErrorCode.PLANNING_FAILED,'GPU_POST_RESAMPLE_CHECK_REJECTED',details={'http_status':response.status_code,'body':response.text})
        value=response.json();self.records.append(value)
        if not value['ok']:raise ApiError(ErrorCode.PLANNING_FAILED,'GPU_POST_RESAMPLE_COLLISION_OR_BOUNDS',details=value)
        return value


class OfflineRealManAdapter(RealManAdapter):
    embodiment='realman'
    control_period_s=.05
    control_frequency=20.
    def __init__(self,manifest,ledger,*,provider=None,transport=None):
        self.manifest=manifest;self.provider=provider
        self.transport=transport or StubTransport(manifest['default_positions'])
        if type(self.transport) is not StubTransport:raise ApiError(ErrorCode.SAFETY_INTERLOCK,'ONLY_OFFLINE_STUB_TRANSPORT')
        self.engine=ExecutionEngine(self.transport,manifest,ledger);self.fk=ModelFK(manifest)
        self.validator=None if provider is None else GpuTrajectoryValidator(provider)
        self._closed=False;self._refusals=[];self.plans=[]
    @property
    def arms(self):return ARMS
    def get_robot_state(self):
        if self._closed:raise RuntimeError('OFFLINE_ADAPTER_CLOSED')
        return RobotState(joint_positions=self.transport.positions,joint_velocities={a:np.zeros(6) for a in ARMS},
            end_effector_poses=self.fk.poses(self.transport.positions),gripper_positions=self.transport.openings,
            base_frame=FRAME,joint_names=NAMES,timestamp_s=time.time(),embodiment='realman',
            metadata={'source_kind':'SYNTHETIC_OFFLINE','controller_feedback':'STUB_ONLY','actual_grasp_tcp':None,
                'physical_motion_permitted':False,'model':MODEL,'pose_endpoint':'nominal Link6 flange; NOT actual grasp TCP'})
    def get_task_context(self):
        return TaskContext('offline',0,'rm65_software_validation','Synthetic offline API integration only.','realman',
            metadata={'source_kind':'SYNTHETIC_OFFLINE','physical_motion_permitted':False})
    def get_observation(self):
        state=self.get_robot_state()
        camera=CameraObservation(rgb=np.zeros((24,32,3),np.uint8),depth_m=np.full((24,32),2.5),
            intrinsics=np.array([[32,0,16],[0,32,12],[0,0,1.]]),frame='synthetic:camera_optical',
            camera_pose=Pose(np.array([0,0,-.5]),np.array([1,0,0,0.]),FRAME),timestamp_s=state.timestamp_s)
        return Observation({'synthetic_overhead':camera},state,self.get_task_context(),state.timestamp_s)
    def get_planning_context(self):
        return RobotPlanningContext(embodiment='realman',model=MODEL,joint_names=NAMES,
            base_transforms={a:np.array(self.manifest['layout']['base_transforms'][a]) for a in ARMS},
            end_effector_links=self.manifest['end_effector_links'])
    def scene(self):
        # Same public synthetic depth projection as native CapApi uses.
        obs=self.get_observation();c=obs.cameras['synthetic_overhead'];v,u=np.indices(c.depth_m.shape)
        points=np.column_stack((((u-16)*c.depth_m/32).ravel(),((v-12)*c.depth_m/32).ravel(),(c.depth_m-.5).ravel()))
        return PlanningScene(PointCloud(points=points,frame=FRAME),.01,obs.timestamp_s)
    def execute_trajectory(self,trajectory):
        if self.provider is None or self.validator is None:
            return self.engine.error(ErrorCode.PROVIDER_UNAVAILABLE,'REAL_GPU_VALIDATION_REQUIRED_FOR_CAP_EXECUTION')
        try:self.validator(trajectory,self.get_robot_state(),self.get_planning_context(),self.scene())
        except ApiError as exc:return self.engine.error(exc.code,exc.message,**dict(exc.details))
        result=self.engine.execute(trajectory)
        return replace(result,final_observation=self.get_observation())
    def step(self,action):
        if len(action.arms)!=1:return StepResult(ok=False,error=ApiError(ErrorCode.UNSUPPORTED,'DUAL_STEP_IS_NOT_SYNCHRONIZED_TRAJECTORY'))
        arm,command=next(iter(action.arms.items()))
        if command.mode!='joint_position' or arm not in ARMS:return StepResult(ok=False,error=ApiError(ErrorCode.UNSUPPORTED,'SINGLE_ARM_JOINT_POSITION_REQUIRED'))
        if self.provider is None:return StepResult(ok=False,error=ApiError(ErrorCode.PROVIDER_UNAVAILABLE,'ACTUAL_CUROBO_NOT_CONFIGURED'))
        state=self.get_robot_state()
        if command.gripper_position is not None and abs(command.gripper_position-state.gripper_positions[arm])>1e-9:
            return StepResult(ok=False,error=ApiError(ErrorCode.UNSUPPORTED,'CHANGING_GRIPPER_REQUIRES_SEPARATE_EXPLICIT_TOOL'))
        plan=self.provider.plan_to_joints(state,np.array(command.target),arm=arm,gripper_position=state.gripper_positions[arm],
            context=self.get_planning_context(),scene=self.scene(),time_dilation_factor=.4)
        self.plans.append(plan)
        if not plan.ok:return StepResult(ok=False,error=plan.error)
        result=self.execute_trajectory(plan.trajectory)
        return StepResult(ok=result.ok,observation=self.get_observation() if result.ok else None,error=result.error,
            diagnostics={'execution_source':'STUB_ONLY','actual_planning_provider':'curobo','hardware_commands_sent':0})
    def set_gripper(self,position,*,arm='primary'):
        arm=self.resolve_arm(arm)
        result=self.engine.set_gripper(position,arm,request_id='native-stub-gripper:'+uuid.uuid4().hex)
        return replace(result,final_observation=self.get_observation())
    def set_grippers(self,positions):
        return self.engine.error(ErrorCode.UNSUPPORTED,'ATOMIC_DUAL_GRIPPER_NOT_IMPLEMENTED_USE_EXPLICIT_SINGLE_ARM_STUB')
    def reset(self,*args,**kwargs):raise self._error('reset')
    def go_home(self,*args,**kwargs):return self._deny('go_home')
    def monitor_snapshot(self):
        obs=self.get_observation();state=obs.robot_state
        return {'ok':True,'timestamp_s':state.timestamp_s,'observation_seq':len(self.transport.events),
            'refresh_timestamp_s':time.time(),'cameras':{n:c.rgb for n,c in obs.cameras.items()},
            'camera_metadata':{n:{'source_kind':'SYNTHETIC_OFFLINE','timestamp_s':c.timestamp_s,'stale':False,'missing':False,
                'serial':None,'geometry_eligible':True,'calibration_status':'SYNTHETIC_NOT_PHYSICAL','frame':c.frame} for n,c in obs.cameras.items()},
            'state':{a+'_joint_pos':q for a,q in state.joint_positions.items()}}
