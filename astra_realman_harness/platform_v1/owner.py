"""Thin single-owner facade over unchanged FullTaskBackend and infer slot.
No memory, view selection, asynchronous proposal planning or learned controller.
"""
import copy,hashlib,json,math,time,uuid
from pathlib import Path
from engineering.public_view import observation as project_observation,execution as project_execution,robot_state
from sim_skills.full_pnp.backend import FullTaskBackend
from sim_skills.full_pnp.protocol import validate_actions,Memory,wire_base,CandidateGate,VERSION as ACTION_VERSION
from sim_skills.full_pnp import dependencies,rgb
from sim_skills.full_pnp.slot import FullSlot
from sim_skills.async_v1 import sha,Rejected
from platform_v1.client import VERSION

class Owner:
    def __init__(self,assets,root,*,seed=2,budget_s=120,source='RESEARCH_PROGRAM',infer_config=None,max_requests=0,backend_factory=FullTaskBackend):
        self.root=Path(root);self.private=self.root/'private';self.public=self.root/'public'
        self.private.mkdir();self.public.mkdir();self.id=uuid.uuid4().hex;self.source=source
        self.ended=False;self.reset_done=False;self.chunks=0;self.epoch=0;self.parent='INITIAL_EMPTY';self.active=None
        self.observations={};self.events_log=[];self.proposal=None;self.gate=CandidateGate();self.inbox_poll=lambda:None
        self.raw=(self.private/'owner_events.jsonl').open('x',buffering=1);self.pub=(self.public/'events.jsonl').open('x',buffering=1)
        self.started=time.monotonic();init=self.started
        self.b=backend_factory(assets,self.private/'scene',seed,True)
        self.init_wall=time.monotonic()-init;self.initial_step=self.b.steps;self.started=time.monotonic();self.deadline=self.started+budget_s
        self.last_step=self.started;self.b.s.step_hook=self.hook;self.b.gripper_guard=self.before_gripper
        self.slot=FullSlot(self.private/'workers',self.private_event,infer_config=infer_config,max_attempts=max_requests,mode='qualification')
        self.infer_config=infer_config;self.max_requests=max_requests
        self.emit('start',{'source':source,'episode_id':self.id,'budget_s':budget_s,'initialization_wall_s':self.init_wall,
           'initialization_physics_s':self.initial_step*self.b.dt,'time_protocol':'wall_paced_hold_while_waiting_and_approved_motion; dt=0.004; no speed changes',
           'reset':'fresh owner process; no setup_held; not exact clone','score_access':'PRIVATE_OWNER_ONLY'})
    def private_event(self,kind,data):
        self.raw.write(json.dumps({'kind':kind,'monotonic':time.monotonic(),'step':self.b.steps,'data':data},allow_nan=False)+'\n')
    def emit(self,kind,data):
        r={'version':VERSION,'sequence':len(self.events_log)+1,'episode_id':self.id,'kind':kind,'source':self.source,
           'monotonic':time.monotonic(),'physics_step':self.b.steps,'data':data}
        self.events_log.append(r);self.pub.write(json.dumps(r,allow_nan=False)+'\n');return r
    def admit(self):
        if self.ended or self.b.stopped:raise Rejected('CONTROL_CLOSED_OR_STOPPED')
        if time.monotonic()>=self.deadline:self.b.stop();raise Rejected('EPISODE_DEADLINE')
    def hook(self,when):
        if when=='after_step':self.b.private_step_hook(when);self.last_step=time.monotonic();return
        self.inbox_poll()
        if self.b.stopped:raise Rejected('STOPPED')
        if time.monotonic()>=self.deadline:self.b.stop();raise Rejected('EPISODE_DEADLINE')
        delay=self.last_step+self.b.dt-time.monotonic()
        if delay>0:time.sleep(delay)
    def idle(self):
        self.admit();self.b.s.tick(1)
    def observe(self):
        self.admit()
        if len(self.observations)>=64:raise Rejected('OBSERVATION_CAP_64')
        obs=self.b.observe();folder='o-%04d'%len(self.observations)
        public=project_observation(obs,self.public/folder)
        for im in public['rgb']:im['file']=folder+'/'+im['file']
        public.update(version=VERSION,episode_id=self.id,source=self.source)
        self.observations[obs['observation_id']]={'raw':obs,'public':public,'epoch':self.epoch}
        self.emit('observation',public);return public
    def source_obs(self,identity):
        self.admit()
        if identity not in self.observations:raise Rejected('UNKNOWN_OBSERVATION')
        row=self.observations[identity]
        if row['epoch']!=self.epoch:raise Rejected('STALE_EXECUTION_EPOCH')
        if time.monotonic()-row['raw']['captured_monotonic']>=180:raise Rejected('OBSERVATION_EXPIRED')
        return row['raw']
    def before_gripper(self,action):
        fresh=self.observe();actual=self.observations[fresh['observation_id']]['raw'];a=self.active
        check=dependencies.check([action],a['source'],actual,rgb.features(a['source']),rgb.features(actual),model_requirements=a['requirements'])
        pose=a['expected'];s=actual['state'];d=math.dist(s['actual_grasp_center_world'],pose[:3]);rot=dependencies.angle(s['flange_pose_world'][3:],pose[3:])
        check['join_error']={'distance_m':d,'rotation_rad':rot}
        if not math.isfinite(d) or not math.isfinite(rot) or d>=.01 or rot>=.05:check['status']='invalid'
        self.private_event('PRE_GRIPPER_CHECK',check);return actual,check
    def binding(self,obs):
        return {'episode_id':self.id,'request_id':'request-%03d'%(self.slot.calls+1),'source_observation_id':obs['observation_id'],
          'source_step':obs['state']['sim_step'],'task_revision':'red_to_green_v1','calibration_revision':'frozen_rm65_cameras_v1',
          'action_interface_revision':ACTION_VERSION,'history_cutoff':time.monotonic(),'history_revision':0,'parent_plan_id':self.parent,
          'expected_join_id':self.parent+':AFTER','barrier_epoch':self.epoch,'preparation_started_monotonic':time.monotonic()}
    def infer(self,source_observation_id):
        obs=self.source_obs(source_observation_id)
        if self.infer_config is None or self.max_requests==0:raise Rejected('MODEL_DISABLED')
        if self.proposal is not None:raise Rejected('ONE_PENDING_PROPOSAL')
        s=obs['state'];expected=[*s['actual_grasp_center_world'],*s['flange_pose_world'][3:]]
        # Empty compatibility history only. Research memory is supplied by the new project, not implemented here.
        wire=wire_base(obs,self.binding(obs),{'status':'completed','id':self.parent},expected,Memory(),'B',self.chunks,'B')
        self.slot.submit_wire(wire,obs,delay_s=0,timeout_s=min(90,self.deadline-time.monotonic()),episode_deadline=self.deadline)
        while self.slot.job:
            self.idle();self.slot.poll()
        if self.slot.pending is None:raise Rejected('MODEL_TIMEOUT_OR_LATE_NO_RETRY')
        self.proposal=self.slot.pending;self.slot.pending=None
        candidate=self.proposal['candidate'];token=self.proposal['digest']
        self.emit('model_proposal',{'proposal_id':token,'operation':candidate['operation'],'source':self.infer_config.source,'raw_from_existing_bridge':True})
        if candidate['operation']=='stop':self.stop()
        return {'proposal_id':token,'candidate':candidate,'source':self.infer_config.source}
    def execute(self,chunk,source_observation_id,proposal_id=None):
        self.admit();validate_actions(chunk)
        if self.chunks>=12:raise Rejected('ACTION_CHUNK_CAP_12')
        source=self.source_obs(source_observation_id);requirements=[];item=None
        if proposal_id is not None:
            item=self.proposal;self.proposal=None
            if not item or item['digest']!=proposal_id:raise Rejected('UNKNOWN_OR_CONSUMED_PROPOSAL')
            c=item['candidate']
            if c['operation']!='chunk' or c['actions']!=chunk or c['binding']['source_observation_id']!=source_observation_id:raise Rejected('RAW_ACTION_OR_SOURCE_MISMATCH')
            requirements=c['requirements']
        elif self.proposal is not None:raise Rejected('PENDING_PROPOSAL_REQUIRES_TOKEN')
        public=self.observe();current=self.observations[public['observation_id']]['raw']
        check=dependencies.check(chunk,source,current,rgb.features(source),rgb.features(current),model_requirements=requirements)
        self.private_event('ADMISSION_CHECK',check)
        if item:self.gate.validate(item,self.binding(source),current['state'],time.monotonic(),check,{a['id'] for a in item['snapshot']['attachments']})
        elif check['status']!='valid':raise Rejected('OWNER_RGB_'+check['status'].upper())
        expected=[*current['state']['actual_grasp_center_world'],*current['state']['flange_pose_world'][3:]]
        for a in chunk:
            if a['type']=='move_pose':expected=a['pose']
        self.chunks+=1;self.active={'source':current,'expected':expected,'requirements':requirements}
        raw_request={'chunk':chunk,'source_observation_id':source_observation_id,'proposal_id':proposal_id}
        self.private_event('EXECUTE_REQUEST',raw_request)
        self.emit('action_begin',{'chunk_id':self.chunks,'actions':self.public_actions(chunk),'source_observation_id':source_observation_id})
        ticket={'owner_admitted':True,'candidate_id':proposal_id or 'research-%d'%self.chunks,'commit_observation_id':current['observation_id']}
        outcome_unknown=False
        try:result=self.b.execute_chunk(chunk,ticket,current)
        except Exception as exc:
            outcome_unknown=True
            self.b.stop();result={'ok':False,'results':[],'unexecuted_count':None,'error':str(exc),'execution_outcome':'UNKNOWN_AFTER_BACKEND_EXCEPTION'}
        finally:self.active=None
        self.private_event('EXECUTE_RESULT',result);safe=project_execution(dict(result,unexecuted_count=0) if outcome_unknown else result)
        safe.update(actual_state=robot_state(self.b.s.state()),completed_monotonic=time.monotonic(),physics_step=self.b.steps)
        safe['actions']=[{'action':self.public_actions([v['action']])[0],'completed':v['result'].get('ok') is True} for v in result.get('results',[])]
        safe['unexecuted_actions']=self.public_actions(chunk[len(result.get('results',[])):]);safe['chunk_id']=self.chunks
        if outcome_unknown:
            # An unexpected backend exception may have happened after physical motion.
            # Neither an empty response nor an exception establishes non-execution.
            safe.update(execution_outcome='UNKNOWN_AFTER_BACKEND_EXCEPTION',unexecuted_count=None,
                        unexecuted_actions=None,actions_with_unknown_outcome=self.public_actions(chunk))
        self.epoch+=1;self.parent='chunk-%d'%self.chunks
        self.emit('execution',safe)
        if not result['ok']:self.b.stop();self.slot.cancel()
        return safe
    def commit(self,proposal_id):
        """Consume the unchanged raw operation, including observe/finish; never repair it."""
        item=self.proposal
        if not item or item['digest']!=proposal_id:raise Rejected('UNKNOWN_OR_CONSUMED_PROPOSAL')
        c=item['candidate'];identity=c['binding']['source_observation_id'];op=c['operation']
        if op=='chunk':return self.execute(c['actions'],identity,proposal_id)
        self.proposal=None
        source=self.source_obs(identity);public=self.observe();current=self.observations[public['observation_id']]['raw']
        check=dependencies.check([],source,current,rgb.features(source),rgb.features(current),model_requirements=c['requirements'])
        self.gate.validate(item,self.binding(source),current['state'],time.monotonic(),check,{a['id'] for a in item['snapshot']['attachments']})
        if op=='observe':return public
        if op=='finish':
            self.ended=True;self.verdict=c['verdict'];return {'closed':True,'score':'PRIVATE_NOT_RETURNED'}
        raise Rejected('UNSUPPORTED_COMMIT_OPERATION')
    def public_actions(self,actions):
        if self.source=='ENGINEERING_REFERENCE':return [{'type':a['type'],'parameters':'REDACTED_ENGINEERING_REFERENCE'} for a in actions]
        return copy.deepcopy(actions)
    def stop(self):
        self.b.stop();self.slot.cancel();self.proposal=None;self.emit('stop',{'reason':'PUBLIC_STOP'});return {'stopped':True}
    def dispatch(self,request):
        if request.get('version')!=VERSION:raise Rejected('PROTOCOL_VERSION')
        if set(request)!={'version','id','method','params'} or type(request['id']) is not int:raise Rejected('REQUEST_SCHEMA')
        method=request['method'];p=request['params']
        fields={'reset':set(),'observe':set(),'execute':{'chunk','source_observation_id','proposal_id'},'infer':{'source_observation_id'},'commit':{'proposal_id'},'events':{'after'},'finish':{'verdict'},'stop':set()}
        if method not in fields:raise Rejected('PRIVATE_OR_UNSUPPORTED_METHOD')
        if not isinstance(p,dict) or set(p)!=fields[method]:raise Rejected('PARAMETERS')
        if method=='reset':
            if self.reset_done:raise Rejected('RESET_REQUIRES_FRESH_OWNER_PROCESS')
            self.reset_done=True;return self.observe()
        if method=='events':
            if type(p['after']) is not int or p['after']<0:raise Rejected('EVENT_CURSOR')
            return self.events_log[p['after']:]
        if method=='finish':
            if p['verdict'] not in ('done','not_done','unknown'):raise Rejected('VERDICT')
            self.ended=True;self.verdict=p['verdict'];return {'closed':True,'score':'PRIVATE_NOT_RETURNED'}
        return getattr(self,method)(**p)
    def score_private(self):
        """Owner lifecycle only: never registered as a policy RPC method."""
        self.ended=True;self.slot.cancel();self.proposal=None
        if time.monotonic()>=self.deadline:self.b.stop()
        self.b.s.step_hook=self.hook
        score=self.b.finish(getattr(self,'verdict','unknown'))
        (self.private/'score_private.json').write_text(json.dumps(score,indent=2)+'\n');return score
    def close(self):
        self.slot.cancel();self.b.s.step_hook=None;self.b.close();self.raw.close();self.pub.close()
