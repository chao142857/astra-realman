"""One owner and the existing single-worker lifecycle, generalized to full-task chunks."""
import copy
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid
from sim_skills.async_v1 import sha,Rejected
from sim_skills.model import state_projection
from sim_skills.full_pnp.protocol import VERSION,INTERFACE,Memory,CandidateGate,wire_base,validate_actions
from sim_skills.full_pnp.slot import FullSlot
from sim_skills.full_pnp import rgb
from sim_skills.full_pnp import dependencies
from sim_skills.full_pnp.timing import timing_limits


class FullRuntime:
    def __init__(self,backend,output,*,condition,delay_s=.8,budget_s=120,timeout_s=30,max_calls=32,infer_config=None,mode='standard'):
        limits=timing_limits(mode)
        if condition not in ('script','B','F') or not 0<budget_s<=limits['episode_budget_s'] or not 0<timeout_s<=limits['request_timeout_s'] or not 0<=delay_s<=30:raise ValueError('CONFIG')
        if type(max_calls) is not int or not 1<=max_calls<=64:raise ValueError('CALL_CAP')
        self.mode=mode
        self.b=backend;self.condition=condition;self.root=Path(output);self.root.mkdir(parents=True,exist_ok=False)
        self.owner=threading.get_ident();self.started=time.monotonic();self.first_step=backend.steps
        self.deadline=self.started+budget_s;self.budget=budget_s;self.timeout=timeout_s;self.delay=delay_s;self.max_calls=max_calls
        self.events=[];self.stream=(self.root/'timeline.jsonl').open('x',buffering=1)
        self.memory=Memory();self.gate=CandidateGate();self.slot=FullSlot(self.root/'workers',self.emit,infer_config=infer_config,max_attempts=max_calls,mode=mode)
        self.episode_id=uuid.uuid4().hex;self.completed=0;self.parent='INITIAL_EMPTY';self.barrier_epoch=0
        self.active=None;self.cycle=None;self.candidate=None;self.evidence=None;self.past=None
        self.last_step=time.monotonic();self.intervals=[];self.stopped=False;self.hold_steps=0
        self.join_started=self.started;self.cold=None;self.e_calls=0;self.e_reuses=0;self.adopted=[];self.discarded=[]
        self.windows={};self.segments=[];self.segment_open={};self.observation_count=0;self.replans=0
        self.original_phase=backend.s.phase;backend.s.phase=self.phase
        self.b.s.step_hook=self.hook
        self.b.gripper_guard=self.before_gripper
        self.emit('EPISODE_START',{'condition':condition,'source':self.slot.source,'action_interface':INTERFACE,
                  'mode':mode,'episode_deadline_monotonic':self.deadline,'budget_s':budget_s,'request_timeout_s':timeout_s,
                  'input_boundary':'frozen RGB/proprioception only; script answers private; worker OS isolated'})
    def emit(self,kind,data):
        if threading.get_ident()!=self.owner:raise RuntimeError('SCENE_OWNER_ONLY')
        now=time.monotonic();e={'kind':kind,'wall_monotonic':now,'wall_elapsed_s':now-self.started,
             'physics_step':self.b.steps,'physics_elapsed_s':(self.b.steps-self.first_step)*self.b.dt,'data':copy.deepcopy(data)}
        self.events.append(e);self.stream.write(json.dumps(e,allow_nan=False)+'\n')
        if kind=='REQUEST_END' and data.get('record') and all(isinstance(data['record'].get(k),(int,float)) for k in ('worker_started_monotonic','worker_finished_monotonic')):
            r=data['record'];self.windows[data['request']]=[r['worker_started_monotonic'],r['worker_finished_monotonic']]
    def phase(self,name,**data):
        self.original_phase(name,**data)
        if name in ('EXEC_ENTER','GRIPPER_ENTER'):
            self.segment_open[name.split('_')[0]]=time.monotonic()
            self.emit('PHYSICAL_'+name,{'parent_plan_id':self.active['id'] if self.active else None,**data})
        elif name in ('EXEC_EXIT','GRIPPER_EXIT'):
            start=self.segment_open.pop(name.split('_')[0],None)
            if start is not None:self.segments.append({'start':start,'end':time.monotonic(),'plan':self.active['id'] if self.active else None})
            self.emit('PHYSICAL_'+name,{'parent_plan_id':self.active['id'] if self.active else None,**data})
    def discard_pending(self,reason):
        if self.candidate:
            event={'candidate_id':self.candidate['digest'],'reason':reason,'dependencies':self.candidate.get('dependencies',[])}
            self.discarded.append(event);self.emit('CANDIDATE_DISCARDED',event);self.candidate=None
        self.cycle=None
    def stop(self,reason):
        self.stopped=True;self.discard_pending(reason);self.slot.cancel();self.b.stop();self.emit('STOP',{'reason':reason})
    def admit(self):
        if self.stopped or self.b.stopped:raise Rejected('STOP_NO_NEW_COMMAND')
        if time.monotonic()>=self.deadline:raise Rejected('EPISODE_DEADLINE')
    def hook(self,when):
        if threading.get_ident()!=self.owner:raise RuntimeError('SCENE_OWNER_ONLY')
        if when=='after_step':
            self.b.private_step_hook(when)
            now=time.monotonic();self.intervals.append(now-self.last_step);self.last_step=now;return
        self.admit();self.poll()
        if self.active and not self.active['lookahead_done'] and self.b.steps-self.active['start_step']>=40:
            self.active['lookahead_done']=True
            if self.condition=='F' and not any(a['type']=='gripper' for a in self.active['actions']):
                obs=self.capture('LOOKAHEAD_WHILE_EXECUTING');self.begin_cycle(obs,predicted=True)
            elif self.condition=='F':self.emit('GRIPPER_BARRIER_NO_PREFETCH',{'parent_plan_id':self.active['id']})
        delay=self.last_step+self.b.dt-time.monotonic()
        if delay>0:time.sleep(delay)
        self.admit()
    def capture(self,reason):
        self.admit();obs=self.b.observe();self.observation_count+=1
        self.emit('OBSERVATION',{'reason':reason,'observation_id':obs['observation_id'],'captured_monotonic':obs['captured_monotonic'],
                  'capture_span_s':obs['capture_span_s'],'state':obs['state'],'images':obs['images'],'calibration':obs['calibration']})
        return obs
    def binding(self,obs):
        return {'episode_id':self.episode_id,'request_id':'pending','source_observation_id':obs['observation_id'],
             'source_observation_sha256':sha({'id':obs['observation_id'],'state':state_projection(obs['state']),'images':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in obs['images'].items()}}),
             'source_step':obs['state']['sim_step'],'task_revision':'red_to_green_v1','calibration_revision':'frozen_rm65_cameras_v1',
             'action_interface_revision':VERSION,'history_cutoff':time.monotonic(),'history_revision':self.memory.revision,
             'parent_plan_id':self.parent,'expected_join_id':self.parent+':AFTER','barrier_epoch':self.barrier_epoch,
             'preparation_started_monotonic':time.monotonic()}
    def begin_cycle(self,obs,predicted=False):
        if self.cycle or self.candidate or self.slot.job or self.slot.pending:raise Rejected('PIPELINE_OCCUPIED')
        f=rgb.features(obs);execution={'status':'executing' if predicted else 'completed','id':self.parent,
                                    'actions':self.active['actions'] if predicted else []}
        expected=self.active['expected'] if predicted else [*obs['state']['actual_grasp_center_world'],*obs['state']['flange_pose_world'][3:]]
        template=wire_base(obs,self.binding(obs),execution,expected,self.memory,self.condition,self.completed,'B' if self.condition=='B' else 'E')
        self.cycle={'obs':obs,'features':f,'template':template,'predicted':predicted,'dependencies':[],'packet':None,'reuse':None}
        if self.condition=='F':
            reuse=None
            if self.evidence and self.evidence['barrier_epoch']==self.barrier_epoch:
                old=self.evidence;reuse=rgb.reuse_packet(old['packet'],old['features'],f,old['obs']['calibration'],obs['calibration'],obs['observation_id'])
            if reuse and reuse['eligible']:
                self.e_reuses+=1;self.cycle.update(packet=self.evidence['packet'],reuse=reuse)
                self.cycle['dependencies'].append(self.evidence['request']);self.emit('E_REUSED',reuse);self.submit('A')
            else:
                self.emit('E_REQUIRED',{'barrier_epoch':self.barrier_epoch,'reuse_check':reuse});self.submit('E')
        else:self.submit('B')
    def submit(self,role):
        self.admit()
        if self.slot.calls>=self.max_calls:raise Rejected('ALL_ROLE_REQUEST_CAP')
        cycle=self.cycle;w=copy.deepcopy(cycle['template']);w['role']=role
        w['binding']['request_id']='request-%03d'%(self.slot.calls+1);w['binding']['preparation_started_monotonic']=time.monotonic()
        w['evidence_packet']=copy.deepcopy(cycle['packet']);w['evidence_packet_hash']=sha(cycle['packet']) if cycle['packet'] else None
        w['evidence_reuse']=copy.deepcopy(cycle['reuse'])
        if role=='E':self.e_calls+=1
        self.slot.submit_wire(w,cycle['obs'],delay_s=self.delay,timeout_s=self.timeout,episode_deadline=self.deadline,
                              evidence=cycle['packet'],reuse=cycle['reuse'],past=self.past)
        cycle['dependencies'].append(self.slot.calls)
    def poll(self):
        had_job=self.slot.job is not None;self.slot.poll()
        if self.slot.pending is None:
            if had_job and self.slot.job is None and self.cycle:raise Rejected('WORKER_TIMEOUT_OR_LATE_NO_RETRY')
            return
        item=self.slot.pending;self.slot.pending=None;out=item['candidate']
        if item['snapshot']['role']=='E':
            required={'kind','binding','selected_camera','bbox','claims','evidence_refs','source'}
            if set(out)!=required or out['kind']!='evidence' or out['binding']!=item['snapshot']['binding']:raise Rejected('E_SCHEMA')
            if out['selected_camera'] not in ('fixed','wrist'):raise Rejected('E_CAMERA')
            if not isinstance(out['claims'],dict) or set(out['claims'])!={'object_visible','identity','holding'} or not all(isinstance(v,str) for v in out['claims'].values()):raise Rejected('E_CLAIMS')
            allowed={a['id'] for a in item['snapshot']['attachments']}
            if not out['evidence_refs'] or any(r not in allowed for r in out['evidence_refs']):raise Rejected('E_UNSEEN_REFERENCE')
            if out['bbox'] is not None:
                box=out['bbox']
                if len(box)!=4 or not all(type(v) in (int,float) for v in box) or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise Rejected('E_ROI')
            self.evidence={'packet':out,'features':self.cycle['features'],'obs':self.cycle['obs'],'barrier_epoch':self.barrier_epoch,'request':item['request']}
            self.memory.hypothesis(out);self.cycle['packet']=out
            self.emit('E_COMPLETED',{'request':item['request'],'packet_sha256':sha(out),'original_observation_id':out['binding']['source_observation_id']})
            self.submit('A');return
        if self.candidate:raise Rejected('SECOND_FUTURE_CANDIDATE')
        item.update(cycle=self.cycle,dependencies=list(self.cycle['dependencies']))
        self.candidate=item;self.cycle=None
        self.emit('CANDIDATE_GENERATED',{'candidate_id':item['digest'],'request':item['request'],'binding':out.get('binding'),'operation':out.get('operation'),'dependencies':item['dependencies']})
        if out.get('operation')=='stop' and out.get('binding')==item['snapshot']['binding']:
            self.stop('WORKER_STOP');raise Rejected('STOP_NO_NEW_COMMAND')
    def wait(self,duration=None):
        start=time.monotonic();self.emit('HOLD_BEGIN',{'reason':'WAIT_VALID_PROPOSAL','drive_targets':'retained'})
        while True:
            self.admit();self.poll()
            if duration is None and self.candidate is not None:break
            if duration is None and not self.slot.job and not self.cycle:raise Rejected('NO_VALID_PROPOSAL')
            if duration is not None and time.monotonic()-start>=duration:break
            self.hold_steps+=1;self.b.s.tick(1)
        self.emit('HOLD_END',{'duration_s':time.monotonic()-start})
    def adopt(self):
        item=self.candidate;candidate=item['candidate'];cycle=item['cycle'];actual=None;check=None
        self.emit('CANDIDATE_SUBMIT_BEGIN',{'candidate_id':item['digest'],'request':item['request']})
        try:
            if candidate.get('operation')=='chunk' and self.completed>=12:raise Rejected('COMPLETED_CHUNK_CAP_12')
            actual=self.capture('COMMIT_FRESH_OBSERVATION');current_features=rgb.features(actual)
            check=dependencies.check(candidate['actions'],cycle['obs'],actual,cycle['features'],current_features,
                                     start_pose=item['snapshot']['expected_join']['pad_pose'],model_requirements=candidate['requirements'])
            self.gate.validate(item,self.binding(actual),actual['state'],time.monotonic(),check,{v['id'] for v in item['snapshot']['attachments']})
        except Exception as exc:
            self.candidate=None
            event={'candidate_id':item['digest'],'reason':str(exc),'rgb':check,'source_observation_id':cycle['obs']['observation_id'],
                   'commit_observation_id':actual['observation_id'] if actual else None,'dependencies':item['dependencies']}
            self.discarded.append(event);self.emit('CANDIDATE_DISCARDED',event)
            if isinstance(exc,Rejected) and str(exc).startswith(('RGB_UNKNOWN','RGB_INVALID')) and self.replans<2:
                self.replans+=1;self.evidence=None
                self.emit('NEW_OBSERVATION_REPLAN',{'cause':str(exc),'not_api_retry':True,'replan':self.replans});self.begin_cycle(actual)
                return None,None
            raise
        self.candidate=None
        overlap=0.
        for dep in set(item['dependencies']):
            if dep not in self.windows:continue
            lo,hi=self.windows[dep]
            overlap+=sum(max(0,min(hi,x['end'])-max(lo,x['start'])) for x in self.segments if x['plan']==candidate['binding']['parent_plan_id'])
        record={'candidate_id':item['digest'],'source_observation_id':cycle['obs']['observation_id'],'commit_observation_id':actual['observation_id'],
                'source_step':cycle['obs']['state']['sim_step'],'commit_step':actual['state']['sim_step'],'rgb':check,
                'dependencies':item['dependencies'],'adopted_inference_execution_overlap_s':overlap,
                'join_wait_for_valid_proposal_s':time.monotonic()-self.join_started,
                'operation':candidate['operation'],'actions':candidate['actions'],'parent_plan_id':candidate['binding']['parent_plan_id']}
        self.adopted.append(record);self.emit('CANDIDATE_ADOPTED',record)
        if self.cold is None:self.cold=time.monotonic()-self.started
        return candidate,actual
    def before_gripper(self,action):
        actual=self.capture('PRE_GRIPPER_FRESH');source=self.active['guard_source']
        check=dependencies.check([action],source,actual,rgb.features(source),rgb.features(actual),model_requirements=self.active.get('model_requirements',()))
        p=self.active['expected'];state=actual['state']
        distance=sum((a-b)**2 for a,b in zip(state['actual_grasp_center_world'],p[:3]))**.5
        rotation=dependencies.angle(state['flange_pose_world'][3:],p[3:])
        check['join_error']={'distance_m':distance,'rotation_rad':rotation}
        if not math.isfinite(distance) or not math.isfinite(rotation) or distance>=.01 or rotation>=.05:
            check['status']='invalid';check['state_error']='PRE_GRIPPER_JOIN_MISMATCH'
        self.emit('PRE_GRIPPER_CHECK',{'observation_id':actual['observation_id'],'check':check})
        return actual,check
    def execute(self,actions,source,commit,candidate_id,model_requirements=()):
        validate_actions(actions)
        if self.completed>=12:raise Rejected('COMPLETED_CHUNK_CAP_12')
        plan_id=sha({'episode':self.episode_id,'index':self.completed,'candidate':candidate_id,'actions':actions})
        expected=[*commit['state']['actual_grasp_center_world'],*commit['state']['flange_pose_world'][3:]]
        for action in actions:
            if action['type']=='move_pose':expected=action['pose']
        self.parent=plan_id;self.active={'id':plan_id,'actions':actions,'expected':expected,'start_step':self.b.steps,'lookahead_done':False,'guard_source':commit,'model_requirements':model_requirements}
        ticket={'owner_admitted':True,'candidate_id':candidate_id,'source_observation_id':source,'commit_observation_id':commit['observation_id'],'parent_plan_id':plan_id}
        self.emit('CHUNK_BEGIN',{'plan_id':plan_id,'actions':actions,'ticket':ticket})
        result=self.b.execute_chunk(actions,ticket,commit)
        self.join_started=time.monotonic();self.emit('CHUNK_END',{'plan_id':plan_id,'result':result});self.active=None
        if not result['ok']:
            self.memory.complete(plan_id,commit,None,actions,result,time.monotonic())
            self.emit('PARENT_FAILED_INVALIDATE',{'candidate':self.candidate['digest'] if self.candidate else None})
            self.discard_pending('PARENT_EXECUTION_FAILED');self.slot.cancel()
            raise Rejected('EXECUTION_FAILED:'+str(result))
        after=self.capture('POST_EXECUTION_FRESH');self.completed+=1
        self.memory.complete(plan_id,commit,after,actions,result,time.monotonic())
        if any(a['type']=='gripper' for a in actions):
            self.barrier_epoch+=1;self.evidence=None
            if self.cycle or self.candidate or self.slot.job:raise Rejected('GRIPPER_BARRIER_PIPELINE_LEAK')
            self.emit('GRIPPER_EVIDENCE_BARRIER',{'new_epoch':self.barrier_epoch,'post_gripper_observation_id':after['observation_id']})
        self.past=commit
        return after
    def run_script(self):
        from sim_skills.full_pnp.scripted import engineering_script
        plan=engineering_script(self.b,self.root)
        for index,chunk in enumerate(plan):
            obs=self.capture('ENGINEERING_SCRIPT_COMMIT')
            actions=chunk.get('actions')
            if actions is None:
                p=obs['state']['actual_grasp_center_world']
                actions=[{'type':'move_pose','pose':[p[0],p[1],p[2]+chunk['relative_lift_after_closure'],0,1,0,0]},
                         {'type':'hold','seconds':1.2}]
            self.execute(actions,'PRIVATE_SCRIPT_ANSWERS',obs,'script-%d'%index)
        return self.b.finish('done')
    def run(self):
        score=None;error=None;status='INCOMPLETE';completion_wall=None
        try:
            if self.condition=='script':score=self.run_script();status=score['status']
            else:
                self.begin_cycle(self.capture('INITIAL_EMPTY_TASK'))
                while True:
                    self.wait();candidate,obs=self.adopt()
                    if candidate is None:continue
                    op=candidate['operation']
                    if op=='finish':
                        self.slot.cancel();self.emit('POLICY_CLOSED',{});score=self.b.finish(candidate['verdict']);status=score['status'];break
                    if op=='observe':
                        if self.replans>=2:raise Rejected('UNKNOWN_NO_VALID_PROPOSAL')
                        self.replans+=1;self.evidence=None;self.begin_cycle(self.capture('REQUESTED_REOBSERVE'));continue
                    after=self.execute(candidate['actions'],candidate['binding']['source_observation_id'],obs,sha(candidate),candidate['requirements'])
                    if not self.cycle and not self.candidate:self.begin_cycle(after)
            # Success is established by the unchanged independent scorer, including
            # its settling/judgment time. STOP/failure is never task completion.
            if status=='PASS':completion_wall=time.monotonic()-self.started
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc);status='STOPPED' if self.stopped else 'FAIL'
            self.emit('FAULT',{'error':error});self.stop(error)
            if not getattr(getattr(self.b,'adapter',None),'ended',True):
                self.emit('POLICY_CLOSED',{'reason':'FAULT_OR_STOP; no further physical settling'})
                try:score=self.b.finish('unknown')
                except Exception as scoring_exc:self.emit('SCORING_FAILURE',{'error':repr(scoring_exc)})
        finally:
            for segment,start in self.segment_open.items():
                self.emit('PHYSICAL_INTERRUPTED',{'segment':segment,'started_monotonic':start,'parent_plan_id':self.active['id'] if self.active else None})
            self.discard_pending('TERMINAL_UNUSED');self.slot.cancel();self.b.s.step_hook=None;self.b.s.phase=self.original_phase
            self.emit('TERMINAL',{'status':status,'score':score})
            summary={'status':status,'error':error,'condition':self.condition,'source':'ENGINEERING_GT_SCRIPT' if self.condition=='script' else self.slot.source,
                'mode':self.mode,'episode_deadline_monotonic':self.deadline,
                'task_completed_wall_s':completion_wall,'completed_within_300s':completion_wall is not None and completion_wall<=300,
                'completion_clock':'episode start through independent PASS, including settling/judgment; excludes initialization/cleanup',
                'real_model_calls':self.slot.infer_calls if self.slot.infer_config and not self.slot.infer_config.fixture else 0,
                'hardware_calls':0,'all_role_attempts':self.slot.calls,'infer_function_calls':self.slot.infer_calls,
                'stub_attempts':0 if self.slot.infer_config else self.slot.calls,'E_calls':self.e_calls,'E_reuses':self.e_reuses,
                'worker_process_launches':self.slot.launches,'attempts':list(self.slot.attempts.values()),'action_chunk_cap':12,
                'max_in_flight':self.slot.max_in_flight,'max_pending':self.slot.max_pending,'completed_chunks':self.completed,
                'candidate_generated':sum(e['kind']=='CANDIDATE_GENERATED' for e in self.events),'candidate_adopted':len(self.adopted),'candidate_discarded':len(self.discarded),
                'adopted_inference_execution_overlap_s':sum(x['adopted_inference_execution_overlap_s'] for x in self.adopted),
                'join_waits_s':[x['join_wait_for_valid_proposal_s'] for x in self.adopted],
                'continuation_join_waits_s':[x['join_wait_for_valid_proposal_s'] for x in self.adopted if x['parent_plan_id']!='INITIAL_EMPTY'],
                'wall_s':time.monotonic()-self.started,'physics_s':(self.b.steps-self.first_step)*self.b.dt,'cold_start_s':self.cold,
                'observations':self.observation_count,'camera_frames':3*self.observation_count,'hold_steps':self.hold_steps,'replans':self.replans,
                'step_interval_min_s':min(self.intervals) if self.intervals else None,'step_interval_max_s':max(self.intervals) if self.intervals else None,
                'step_interval_mean_s':sum(self.intervals)/len(self.intervals) if self.intervals else None,'budget_s':self.budget,
                'request_timeout_s':self.timeout,'all_roles_request_cap':self.max_calls,'dt_s':self.b.dt,'score':score,
                'sequence':[e['data']['actions'] for e in self.events if e['kind']=='CHUNK_BEGIN'],'interface_sha256':sha(INTERFACE)}
            summary['sequence_sha256']=sha(summary['sequence'])
            summary['request_costs']=[{'event':e['kind'],**e['data']} for e in self.events if e['kind'] in ('REQUEST_START','REQUEST_END','REQUEST_CANCELLED')]
            (self.root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');self.stream.close()
        return summary
