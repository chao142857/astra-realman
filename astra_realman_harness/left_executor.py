"""Explicitly enabled left executor. Same verified calls; no retries or planning."""
import json, os, time
from io_utils import write_json
from left_terminal import parse, command_plan, validate_state

class RealLeftExecutor:
    def __init__(self, session, capture, stop, step, gripper_factory=None):
        self.session,self.capture,self.stop,self.step=session,capture,stop,step
        self.gripper_factory=gripper_factory
        self.used=False
        self.result={'status':'NOT_SENT','executed_action':{'arm':None,'gripper':None},
                     'sdk_result':{'called':False,'arm':None,'gripper':None},'hardware_commands_sent':0}
    def guard(self,obs):
        if self.stop.is_set():raise RuntimeError('HUMAN_STOP')
        if set(self.session.connected)!={'left'}:raise RuntimeError('LEFT_SESSION_ONLY')
        errors=validate_state(obs,live=True,max_age_s=3)
        if errors:raise RuntimeError('PREFLIGHT:'+','.join(errors))
    def execute(self,action,obs,*,feasibility=None):
        if self.used:raise RuntimeError('NO_RETRY_EXECUTOR_CONSUMED')
        self.used=True
        action=parse(json.dumps(action,allow_nan=False))
        self.guard(obs)
        from exact_target_feasibility import require_exact_check
        require_exact_check(feasibility,action,obs)
        plan=command_plan(action,obs['canonical_states']['left'])
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
                ret=self.session.connected['left'].rm_movej_p(command['pose'],1,0,0,1)
                self.result['sdk_result']['arm']=ret
                write_json(self.step/'arm-command-result.json',{'request':command,'return':ret})
                if type(ret) is not int or ret!=0:raise RuntimeError('ARM_COMMAND_RETURN:'+str(ret))
                # Actual feedback and healthy controller mandatory before a second channel.
                obs=self.capture(self.step/'between-channels')
                self.guard(obs)
            if plan['gripper']:
                target=plan['gripper']['wire_target'];g=obs['canonical_states']['left']['gripper_state']
                if not (g['position']==target and g['raw'].get('speed',[None])[0]==0):
                    factory=self.gripper_factory
                    if factory is None:
                        from lab_gripper_adapter import LabGripperAdapter
                        factory=LabGripperAdapter
                    adapter=factory()
                    try:
                        self.guard(obs);claim('gripper',plan['gripper'])
                        self.result['executed_action']['gripper']=plan['gripper']
                        self.result['sdk_result']['called']=True
                        self.result['hardware_commands_sent']+=1
                        response=adapter.set_gripper('left',action['gripper_opening'])
                        self.result['sdk_result']['gripper']=response
                        if response.get('command_return')!={'command':'hand_follow_pos','set_state':True}:
                            raise RuntimeError('GRIPPER_COMMAND_RETURN')
                    finally:
                        if adapter.last_result is not None:self.result['sdk_result']['gripper']=adapter.last_result
                        adapter.close()
                    # Existing settling interval, interruptible; no position/force servo or retry.
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
