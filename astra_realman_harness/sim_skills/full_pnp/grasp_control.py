"""Shared simulation contact controller; no inference, scene creation or hardware.

The frozen scene owns all stepping, collision/limit checks and contact latch.
Only contact qualification and contact-loss monitoring change here.
Contact evidence stays private; controller success does not prove stable carry.
"""
import json
import math
import time

REVISION = 'shared_grasp_contact_v1'
CONTACT_CONFIRM_STEPS = 50       # final 0.2s of the existing 200-step settling
CONTACT_LOSS_STEPS = 20          # existing scoring loss window, 0.08s at dt=.004


class ContactState:
    """Measured contact persistence, NOT an object pose or a holding oracle."""
    def __init__(self):
        self.last_step=None;self.begin('IDLE')
    def begin(self, phase):
        self.phase=phase;self.run=0;self.missing=0;self.seen=False;self.armed=False
        self.status='UNKNOWN' if phase=='IDLE' else phase
    def sample(self, step, bilateral):
        if step==self.last_step:return
        if self.last_step is not None and step!=self.last_step+1:
            self.run=0;self.missing=0  # gaps never count as continuous evidence
        self.last_step=step
        self.run=self.run+1 if bilateral else 0
        self.missing=0 if bilateral else self.missing+1
        self.seen|=bilateral
        if self.phase in ('CLOSING','CONTACT_MONITORING'):
            self.status=('CONTACT_CONFIRMED' if self.run>=CONTACT_CONFIRM_STEPS else
                         'CONTACT_CANDIDATE' if bilateral else 'CONTACT_LOST' if self.seen else 'NO_CONTACT')
    def closure_result(self, latched):
        if self.run>=CONTACT_CONFIRM_STEPS and latched:
            self.phase='CONTACT_MONITORING';self.armed=True
            return True,None
        return False,'GRASP_CONTACT_LOST_AFTER_LATCH' if latched else 'GRASP_CONTACT_NOT_ESTABLISHED'
    def loss_abort(self):return self.armed and self.missing>=CONTACT_LOSS_STEPS


class SharedGraspController:
    def __init__(self, scene):
        self.s=scene;self.original_gripper=scene.gripper;self.original_monitor=scene.monitor;self.contact=ContactState()
        self.stream=(scene.output/'grasp_execution_private.jsonl').open('x',buffering=1)
        self.last_status=None
        scene.monitor=self.monitor
        self.last_close=None
        self.emit('INSTALLED',{'revision':REVISION,'trajectory':'unchanged original scene.gripper',
            'confirm_steps':CONTACT_CONFIRM_STEPS,'loss_steps':CONTACT_LOSS_STEPS,
            'scope':'SIMULATOR_CONTACT_ASSISTANCE_PRIVATE; not stable holding or policy target evidence',
            'unchanged':'scene monitor including -2mm; physical parameters; opening endpoint; 150-step ramp; latch preload/torque; 200-step settling'})
    def emit(self,event,data):
        if event in ('CLOSING_END','CLOSING_ABORT'):self.last_close=dict(data)
        self.stream.write(json.dumps({'event':event,'step':self.s.step,'monotonic':time.monotonic(),'data':data})+'\n')
    def sample(self):
        self.contact.sample(self.s.step,self.s.bilateral_pad_contact())
        if self.contact.status!=self.last_status:
            self.emit('CONTACT_STATE',{'status':self.contact.status,'consecutive_contact_steps':self.contact.run,
                                     'consecutive_missing_steps':self.contact.missing})
            self.last_status=self.contact.status
    def monitor(self):
        self.original_monitor()  # frozen checks always run first; original tick archives exceptions
        self.sample()
        if self.contact.loss_abort():
            self.contact.armed=False
            self.emit('CONTACT_LOSS_ABORT',{'status':'GRASP_FAILED','reason':'GRASP_CONTACT_LOST_DURING_EXECUTION'})
            raise RuntimeError('GRASP_CONTACT_LOST_DURING_EXECUTION')
    def gripper(self,opening):
        if isinstance(opening,bool) or not isinstance(opening,(int,float)) or not math.isfinite(opening) or not 0<=opening<=1:
            raise ValueError('opening must be 0..1')
        s=self.s
        if s.stopped.is_set():raise RuntimeError('STOPPED')
        start=float(s.robot.get_qpos()[s.master]);target=-.91*(1-opening)
        if abs(target-start)<=.005:
            # FullTaskBackend's common owner normally handles this no-op first.
            self.emit('GRIPPER_NOOP',{'opening':opening,'target_rad':target,'actual_rad':start})
            return {'ok':True,'noop':True,'after':s.state()}
        if target>start:
            self.contact.begin('RELEASING');self.emit('OPENING_BEGIN',{'opening':opening})
            try:
                out=self.original_gripper(opening)
                self.emit('OPENING_END',{'command_completed':bool(out['ok']),'holding':'UNKNOWN'})
                return out
            except Exception as exc:
                self.emit('OPENING_ABORT',{'command_completed':False,'error':repr(exc)});raise
            finally:self.contact.begin('IDLE')
        self.contact.begin('CLOSING')
        self.emit('CLOSING_BEGIN',{'opening':opening,'start_rad':start,'requested_target_rad':target,'ramp_steps':150})
        try:
            result=self.original_gripper(opening)
            if not result.get('ok'):raise RuntimeError('GRIPPER_COMMAND_FAILED')
            ok,error=self.contact.closure_result(result.get('contact_latch') is not None)
            self.emit('CLOSING_END',{'command_completed':True,'contact_qualified':ok,
                'contact_status':self.contact.status,'holding_status':'NOT_ESTABLISHED_BY_CLOSING',
                'grasp_failed':not ok,'error':error,'consecutive_contact_steps':self.contact.run,
                'consecutive_missing_steps':self.contact.missing})
            result['ok']=ok
            if error:
                result['error']=error;s.stopped.set();s.hold()
                result['after']=s.state()
            return result
        except Exception as exc:
            self.contact.armed=False
            self.emit('CLOSING_ABORT',{'command_completed':False,'contact_qualified':False,
                                      'grasp_failed':True,'error':repr(exc)})
            s.stopped.set();s.hold();raise
    def close(self):self.stream.close()
