"""One decision source, shared state, sequential skills, exact per-arm routing."""
import copy,fcntl,json,threading,time
from pathlib import Path
from bimanual_demo.protocol import parse,require,SkillFailure
from bimanual_demo.state import TaskState
from bimanual_demo.executors import make_arms
from bimanual_demo.evidence import Keyframes,SyntheticObserver
from bimanual_demo.logging import Recorder
from bimanual_demo.skills import Skills

class TaskLock:
    def __init__(self,path):self.path=Path(path)
    def __enter__(self):
        self.file=self.path.open('a+')
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except Exception:self.file.close();raise
        return self
    def __exit__(self,*args):self.file.close()

class Runtime:
    def __init__(self,site,root,objects,classes,*,arms=None,observer=None,mode='synthetic'):
        require(site['requested_effort']=='medium','MEDIUM_ONLY')
        require(mode in ('synthetic','simulate'),'EXPLICIT_SIMULATION_MODE_REQUIRED')
        require((arms is None)==(observer is None),'INJECT_ARMS_AND_OBSERVER_TOGETHER')
        require(mode=='synthetic' or arms is not None,'SIMULATION_DEPENDENCIES_REQUIRED')
        require(site['hardware_enabled'] is False,'REAL_EXECUTION_OFF')
        self.site=copy.deepcopy(site);self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.mode=mode
        self.state=TaskState(objects,site['revision']);self.arms=arms if arms is not None else make_arms(site,'synthetic')
        require(set(self.arms)=={'left','right'},'TWO_ARMS')
        self.observer=observer if observer is not None else SyntheticObserver(self.root,self.arms,classes,site['revision'])
        if mode=='simulate':
            require(all(getattr(x,'execution_source',None)=='SAPIEN_PHYSX' for x in self.arms.values()),'PHYSICS_EXECUTORS_REQUIRED')
            require(getattr(self.observer,'observation_source',None)=='SAPIEN_PHYSX','PHYSICS_OBSERVER_REQUIRED')
        self.memory=Keyframes(site['revision'])
        self.recorder=Recorder(root);self.skills=Skills(self);self.stop=threading.Event();self.seen=set();self.local_sequence=0;self.latest=None
        self.decision_in_progress=False
        (self.root/'site.json').write_text(json.dumps(site,indent=2)+'\n')
    def observe(self,obj=None):
        with self.recorder.timed(obj,'camera_readback_s'):
            obs=self.observer.capture();self.state.bind_observation(obs);self.latest=obs
            self.recorder.emit('OBSERVATION',obs)
        return obs
    def context(self,task):
        if self.latest is None:self.observe()
        return {'schema':'bimanual-context-v1','task':task,'requested_effort':'medium','task_state':self.state.snapshot(),
           'current_images':self.memory.attachments(self.latest,self.state.active_object),
           'keyframe_references':self.memory.projection(self.state.active_object),'mode':'SYNTHETIC_ONLY' if self.mode=='synthetic' else 'SIMULATE',
           'recent_execution_evidence':[x for x in self.recorder.rows if x['kind'] in ('SKILL_RESULT','OWNERSHIP_EVIDENCE')][-5:],
           'evidence_rule':'Historical references are not current images. Predictions do not establish grasp, ownership or placement.'}
    def invalidate_revision(self,revision):
        self.state.invalidate_revision(revision);self.memory.invalidate(revision)
        self.observer.revision=copy.deepcopy(revision);self.latest=None
        self.recorder.emit('REVISION_INVALIDATED',{'revision':revision,'old_targets_valid':False})
    def event(self,name,a):
        obs=self.observe(a['object_id']);e=self.observer.confirm(name,a['object_id'],a['operation_id'],self.state,obs)
        self.recorder.emit('OWNERSHIP_EVIDENCE',e);self.state.confirm(name,e,a['operation_id'])
    def gate(self,arm,kind,value):
        require(not self.stop.is_set(),'STOP_NO_NEW_COMMANDS');require(not self.state.fault,'RECOVERY_REQUIRED')
        require(arm in ('left','right'),'ARM_ROUTE');h=self.state.handoff;phase=self.state.phase
        if kind=='set_gripper' and arm=='left' and value>self.arms[arm].read_state()['opening']:
            require(phase=='left_pick' or h=='RIGHT_HOLDING_CONFIRMED','LEFT_RELEASE_FORBIDDEN')
        if kind=='set_gripper' and arm=='right' and value>self.arms[arm].read_state()['opening']:
            require(phase=='right_at_destination','RIGHT_RELEASE_FORBIDDEN')
        # No right-side transport while left still occupies the shared handoff region.
        if kind=='move' and arm=='right' and value not in ('right_receive',):
            require(h=='RIGHT_OWNS_OBJECT','LEFT_NOT_CLEAR')
    def command(self,arm,kind,value,a):
        self.gate(arm,kind,value);self.local_sequence+=1
        local_id=a['operation_id']+':'+str(self.local_sequence);other='right' if arm=='left' else 'left'
        require(self.arms[other].hold()['commands_sent']==0,'OTHER_ARM_HOLD')
        internal={'operation_id':a['operation_id'],'local_id':local_id,'arm_id':arm,'other_arm':'hold','kind':kind,'value':value,
                  'state_version':self.state.version,'revision':self.state.revision,'source':'SKILL_CONTROLLER_ASSISTED'}
        self.recorder.emit('SKILL_INTERNAL_ACTION',internal)
        before={name:executor.read_state() for name,executor in self.arms.items()}
        claim=self.root/('dispatch-'+str(self.local_sequence)+'.json')
        with claim.open('x') as f:json.dump(internal,f)
        out=None;start=time.monotonic()
        try:
            if kind=='move':
                target=self.site['synthetic_waypoints' if self.mode=='synthetic' else 'simulation_waypoints'][value]
                expected='SYNTHETIC_NOT_FIELD_VALIDATED' if self.mode=='synthetic' else 'SIMULATION_NOT_FIELD_VALIDATED'
                require(target['arm_id']==arm and target['source']==expected,'WAYPOINT_ROUTE')
                require(target['revision']==self.state.revision,'STALE_TARGET')
                out=self.arms[arm].move_to_pose(target['pose'],target['frame'],target['tool_frame'],local_id)
            elif kind=='delta':out=self.arms[arm].move_delta(value['translation'],value['rotation'],value['frame'],local_id)
            elif kind=='set_gripper':out=self.arms[arm].set_gripper(value,local_id)
            else:raise SkillFailure('UNSUPPORTED_COMMAND')
            require(isinstance(out,dict) and ('ok' in out or 'return_code' in out),'EXECUTION_RESULT_UNAVAILABLE')
            require(('ok' not in out or out['ok'] is True) and
                    ('return_code' not in out or type(out['return_code']) is int and out['return_code']==0),'EXECUTION_FAILED')
            return out
        finally:
            # Preserve a possibly dispatched unknown-ACK command without retry or recovery action.
            matching=[c for c in getattr(self.arms[arm],'calls',[]) if c['operation_id']==local_id]
            raw=copy.deepcopy(out or (matching[-1] if matching else {'operation_id':local_id,'dispatched':False,'hardware_calls':0}))
            raw.update(phase=self.state.phase,high_level_operation=a['operation_id'],synthetic=self.mode=='synthetic')
            self.recorder.emit('RAW_HARDWARE_COMMAND' if self.mode=='synthetic' else 'RAW_BACKEND_COMMAND',raw)
            after={name:executor.read_state() for name,executor in self.arms.items()}
            self.recorder.emit('MEASURED_FEEDBACK',{'operation_id':a['operation_id'],'local_id':local_id,'before':before,'after':after,
                      'actual_delta':[y-x for x,y in zip(before[arm]['pose'],after[arm]['pose'])],
                      'source':'MOCK' if self.mode=='synthetic' else 'SAPIEN_PHYSX','object_result':'unknown; requires independent observation'})
            metric='gripper_s' if kind=='set_gripper' else 'arm_motion_s'
            self.recorder.objects[a['object_id']][metric]+=time.monotonic()-start
            self.recorder.objects[a['object_id']]['internal_action_count']+=1
    def move(self,arm,waypoint,a):return self.command(arm,'move',waypoint,a)
    def grip(self,arm,opening,a):return self.command(arm,'set_gripper',opening,a)
    def execute(self,raw):
        a=parse(raw);self.state.admit(a)
        require(not self.stop.is_set(),'STOP_NO_NEW_DECISIONS');require(not self.decision_in_progress,'SEQUENTIAL_ONLY')
        require(a['operation_id'] not in self.seen,'HIGH_LEVEL_OPERATION_ALREADY_CONSUMED')
        self.seen.add(a['operation_id']);self.decision_in_progress=True
        obj=a['object_id'];kind=a['action'];start=time.monotonic()
        if obj:self.recorder.begin_object(obj);self.recorder.objects[obj]['synthetic_decisions']+=1
        self.recorder.emit('ASTRA_DECISION',{'raw_proposal':raw,'parsed':a,'source':'SCRIPTED_SYNTHETIC_NOT_ASTRA' if self.mode=='synthetic' else 'INJECTED_PROPOSAL_NOT_MODEL_VERIFIED','real_model_calls':0})
        result={'operation_id':a['operation_id'],'object_id':obj,'action':kind,'status':'STARTED','real_hardware_calls':0}
        try:
            before=self.observe(obj)
            self.recorder.emit('MODEL_CONTEXT_PREPARED',self.context('Sort fruit into plate and clutter into box using left-to-right handoff.'))
            if obj:self.memory.store('previous_action_before',before,obj,'Before explicit high-level skill',a['operation_id'])
            if kind=='OBSERVE':pass
            elif kind=='SELECT_OBJECT':
                e=self.observer.confirm('IDENTITY_CLASS_CONFIRMED',obj,a['operation_id'],self.state,before)
                self.recorder.emit('CLASSIFICATION_EVIDENCE',e);self.state.select(a,e)
                self.memory.store('last_clear_object_view',before,obj,'Synthetic clear identity evidence',a['operation_id'])
                self.memory.store('last_clear_destination_view',before,obj,'Synthetic fixed destination evidence',a['operation_id'])
            elif kind=='DELTA_CORRECTION':
                require(self.state.phase in ('left_pick','right_place'),'DELTA_NOT_DURING_HANDOFF')
                require(a['arm_id']==('left' if self.state.phase=='left_pick' else 'right'),'DELTA_OWNER')
                self.command(a['arm_id'],'delta',{'translation':a['translation_m'],'rotation':a['rotation_rpy_rad'],'frame':a['frame']},a)
            else:
                function={'LEFT_PICK':'left_pick','LEFT_PRESENT':'left_present','BIMANUAL_HANDOFF':'handoff','RIGHT_PLACE':'right_place','VERIFY':'verify','RECOVER':'recover'}[kind]
                getattr(self.skills,function)(a)
            result['status']='COMPLETED_WITH_RECORDED_EVIDENCE'
        except Exception as exc:
            self.state.fail(type(exc).__name__+':'+str(exc));result.update(status='RECOVER_REQUIRED',error=str(exc))
            self.recorder.emit('FAULT',{'reason':str(exc),'no_automatic_retry':True,'no_automatic_release':True,'state':self.state.snapshot()})
        finally:
            result['duration_s']=time.monotonic()-start;result['after_state']=self.state.snapshot();self.recorder.emit('SKILL_RESULT',result)
            try:
                after=self.observe(obj)
                if obj:self.memory.store('previous_action_after',after,obj,'Actual synthetic skill consequence, not predicted outcome',a['operation_id'])
            except Exception as exc:
                self.state.fail('AFTER_OBSERVATION_FAILED:'+str(exc))
                result.update(status='RECOVER_REQUIRED',error=str(exc))
                self.recorder.emit('OBSERVATION_FAILURE',{'error':str(exc)})
            finally:self.decision_in_progress=False
        return result
