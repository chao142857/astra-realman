"""Explicitly enabled left executor. Same verified calls; no retries or planning."""
import json, os, time
from contextlib import nullcontext
from io_utils import write_json
from left_terminal import parse, command_plan, validate_state

class RealArmExecutor:
    def __init__(self, session, capture, stop, step, gripper_factory=None, timings=None, *, arm_id="left", allow_shared_session=True):
        if arm_id not in ("left","right"):raise ValueError("ARM_ID")
        self.arm_id=arm_id;self.allow_shared_session=allow_shared_session;self.frames=None
        self.session,self.capture,self.stop,self.step=session,capture,stop,step
        self.gripper_factory=gripper_factory
        self.timings=timings
        self.used=False
        self.result={'status':'NOT_SENT','executed_action':{'arm':None,'gripper':None},
                     'sdk_result':{'called':False,'arm':None,'gripper':None},'hardware_commands_sent':0}
    def measure(self, stage):
        return self.timings.measure(stage, "executor") if self.timings else nullcontext()
    def guard(self,obs):
        if self.stop.is_set():raise RuntimeError('HUMAN_STOP')
        if self.arm_id not in self.session.connected or (not self.allow_shared_session and set(self.session.connected)!={self.arm_id}):raise RuntimeError('ARM_SESSION_MISMATCH')
        state=obs["canonical_states"][self.arm_id]
        if self.frames is None:
            self.frames={k:dict(state[k]) for k in ("work_frame","tool_frame")}
        errors=validate_state(obs,live=True,max_age_s=3,arm_id=self.arm_id,
            frame_fingerprints={k:f["definition_fingerprint"] for k,f in self.frames.items()} if self.arm_id=="right" or self.allow_shared_session else None,
            work=self.frames["work_frame"]["id"],tool=self.frames["tool_frame"]["id"])
        if errors:raise RuntimeError('PREFLIGHT:'+','.join(errors))
    def execute(self,action,obs,*,feasibility=None):
        if self.used:raise RuntimeError('NO_RETRY_EXECUTOR_CONSUMED')
        self.used=True
        state=obs["canonical_states"][self.arm_id]
        action=parse(json.dumps(action,allow_nan=False),self.arm_id,state["work_frame"]["id"],state["tool_frame"]["id"])
        self.guard(obs)
        from exact_target_feasibility import require_exact_check
        require_exact_check(feasibility,action,obs)
        plan=command_plan(action,obs['canonical_states'][self.arm_id])
        started=time.monotonic()
        def claim(channel,command):
            if self.stop.is_set():raise RuntimeError('HUMAN_STOP')
            with (self.step/(channel+'-dispatch.claim.json')).open('x') as f:
                json.dump({'command':command,'timestamp':time.time(),'retry_allowed':False},f)
                f.flush();os.fsync(f.fileno())
        try:
            if plan['terminal']:
                self.result['status']='MODEL_DONE';return self.result
            if plan['arm']:
                command=plan['arm'];self.guard(obs);claim('arm',command)
                self.result['executed_action']['arm']=command
                self.result['sdk_result']['called']=True
                self.result['hardware_commands_sent']+=1
                with self.measure('arm_command'):
                    ret=self.session.connected[self.arm_id].rm_movej_p(command['pose'],1,0,0,1)
                self.result['sdk_result']['arm']=ret
                write_json(self.step/'arm-command-result.json',{'request':command,'return':ret})
                if type(ret) is not int or ret!=0:raise RuntimeError('ARM_COMMAND_RETURN:'+str(ret))
                # Actual feedback and healthy controller mandatory before a second channel.
                obs=self.capture(self.step/'between-channels')
                self.guard(obs)
            if plan['gripper']:
                target=plan['gripper']['wire_target'];g=obs['canonical_states'][self.arm_id]['gripper_state']
                if not (g['position']==target and g['raw'].get('speed',[None])[0]==0):
                    factory=self.gripper_factory
                    if factory is None:
                        from lab_gripper_adapter import LabGripperAdapter
                        factory=LabGripperAdapter if not self.allow_shared_session else lambda: LabGripperAdapter(self.arm_id)
                    adapter=factory()
                    try:
                        self.guard(obs);claim('gripper',plan['gripper'])
                        self.result['executed_action']['gripper']=plan['gripper']
                        self.result['sdk_result']['called']=True
                        self.result['hardware_commands_sent']+=1
                        with self.measure('gripper_communication'):
                            response=adapter.set_gripper(self.arm_id,action['gripper_opening'])
                        self.result['sdk_result']['gripper']=response
                        if response.get('command_return')!={'command':'hand_follow_pos','set_state':True}:
                            raise RuntimeError('GRIPPER_COMMAND_RETURN')
                    finally:
                        if adapter.last_result is not None:self.result['sdk_result']['gripper']=adapter.last_result
                        adapter.close()
                    # Existing settling interval, interruptible; no position/force servo or retry.
                    with self.measure('gripper_settle'):
                        if self.stop.wait(2):raise RuntimeError('HUMAN_STOP')
            self.result['status']='EXECUTED' if self.result['hardware_commands_sent'] else 'NOOP'
            return self.result
        except Exception as exc:
            self.result.update(status='STOPPED',error=str(exc))
            try:
                after=self.capture(self.step/'failure-readback')
                write_json(self.step/'failure-state.json',after['canonical_states'])
            except Exception as read_exc:
                write_json(self.step/'failure-readback-error.json',{'error':str(read_exc)})
            raise
        finally:
            self.result['execution_latency_s']=time.monotonic()-started
            write_json(self.step/'executed_action.json',self.result['executed_action'])
            write_json(self.step/'sdk_result.json',self.result['sdk_result'])
            write_json(self.step/'execution_result.json',self.result)


class RealLeftExecutor(RealArmExecutor):
    """Legacy entry keeps its original left-only session and frame checks."""
    def __init__(self, session, capture, stop, step, gripper_factory=None, timings=None):
        super().__init__(session,capture,stop,step,gripper_factory,timings,arm_id="left",allow_shared_session=False)


class RealRightExecutor(RealArmExecutor):
    def __init__(self, session, capture, stop, step, gripper_factory=None, timings=None):
        super().__init__(session,capture,stop,step,gripper_factory,timings,arm_id="right")
