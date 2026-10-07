"""One arm interface each. Only mock transport is implemented in this foundation."""
import copy,time
from abc import ABC,abstractmethod
from bimanual_demo.protocol import require,HardwareDisabled,SkillFailure,finite_vector

class ArmExecutor(ABC):
    def __init__(self,arm_id):require(arm_id in ('left','right'),'ARM_ID');self.arm_id=arm_id
    @abstractmethod
    def read_state(self):pass
    @abstractmethod
    def move_to_pose(self,pose,frame,tool_frame,operation_id):pass
    @abstractmethod
    def move_delta(self,translation,rotation,frame,operation_id):pass
    @abstractmethod
    def set_gripper(self,opening,operation_id):pass
    def hold(self):return {'arm_id':self.arm_id,'status':'HOLD','commands_sent':0}
    def retract(self,pose,frame,tool_frame,operation_id):return self.move_to_pose(pose,frame,tool_frame,operation_id)

class RealArmExecutor(ArmExecutor):
    """Bridge to the mirrored single-arm stack; no SDK lifecycle or new motion logic."""
    def __init__(self,arm_id,session=None,capture=None,stop=None,root=None,*,execute_enabled=False,gripper_factory=None):
        super().__init__(arm_id)
        if session is None or capture is None or stop is None or root is None:
            raise HardwareDisabled('Explicit existing SDK session/capture/stop/log root required')
        from arm_stack import ArmStack
        self.stack=ArmStack(arm_id,session,capture,stop,root,execute_enabled=execute_enabled,gripper_factory=gripper_factory)
    def read_state(self):return self.stack.read_state()
    def move_to_pose(self,pose,frame,tool_frame,operation_id):return self.stack.move_to_pose(pose,frame,tool_frame,operation_id)
    def move_delta(self,translation,rotation,frame,operation_id):return self.stack.move_delta(translation,rotation,frame,operation_id)
    def set_gripper(self,opening,operation_id):return self.stack.set_gripper(opening,operation_id)
    def hold(self):return self.stack.hold()

class MockArmExecutor(ArmExecutor):
    def __init__(self,arm_id,site):
        super().__init__(arm_id);self.site=site;self.pose=[0.,0.,.3,0.,0.,0.];self.opening=1.;self.calls=[];self.seen=set();self.fail_next=None
        self.frame='synthetic:'+arm_id+':work';self.tool_frame='synthetic:'+arm_id+':tool'
    def read_state(self):return {'arm_id':self.arm_id,'pose':copy.deepcopy(self.pose),'joint_deg':[0.]*6,'opening':self.opening,'timestamp':time.time(),'frame':self.frame,'tool_frame':self.tool_frame,'errors':[0],'source':'MOCK'}
    def _send(self,kind,values,operation_id):
        require(operation_id not in self.seen,'AT_MOST_ONCE');self.seen.add(operation_id)
        record={'arm_id':self.arm_id,'kind':kind,'values':copy.deepcopy(values),'operation_id':operation_id,
                'source':'MOCK_TRANSPORT','hardware_calls':0,'speed_percent':self.site['speed_percent'],'return_code':0}
        self.calls.append(record)
        if self.fail_next:
            record.update(return_code=None,uncertain_dispatch=True,error=self.fail_next);self.fail_next=None
            raise SkillFailure('MOCK_UNKNOWN_ACK_NO_RETRY')
        return record
    def move_to_pose(self,pose,frame,tool_frame,operation_id):
        require(frame==self.frame and tool_frame==self.tool_frame,'ARM_FRAME_TOOL_MISMATCH');require(finite_vector(pose,6),'POSE_FINITE')
        r=self._send('move_to_pose',pose,operation_id);self.pose=copy.deepcopy(pose);return r
    def move_delta(self,translation,rotation,frame,operation_id):
        require(finite_vector(translation,3) and finite_vector(rotation,3),'DELTA_FINITE')
        return self.move_to_pose([p+d for p,d in zip(self.pose,translation+rotation)],frame,self.tool_frame,operation_id)
    def set_gripper(self,opening,operation_id):
        require(type(opening)in(int,float) and 0<=opening<=1,'OPENING_RANGE')
        r=self._send('set_gripper',opening,operation_id);self.opening=opening;return r

def make_arms(site,mode,*,session=None,capture=None,stop=None,root=None):
    require(set(site['arms'])=={'left','right'},'TWO_ARMS')
    require(site['arms']['left']['endpoint']!=site['arms']['right']['endpoint'],'DUPLICATE_ENDPOINT')
    if mode=='real':
        require(site['hardware_enabled'] is True and root is not None,'EXPLICIT_REAL_ENABLE_REQUIRED')
        from pathlib import Path
        return {arm:RealArmExecutor(arm,session,capture,stop,Path(root)/arm,execute_enabled=True) for arm in ('left','right')}
    require(mode=='synthetic' and site['hardware_enabled'] is False,'REAL_EXECUTION_OFF')
    return {arm:MockArmExecutor(arm,site) for arm in ('left','right')}
