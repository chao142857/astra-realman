"""Plan-to-micro-chunk adapter; policy supplies plan and explicitly requests each step."""
import json
import time
from .contracts import clone,digest,validate_plan,micro_chunks
from .task_evidence import TaskEvidenceAdapter
from . import chunk_plan, losses
from .fusion import current_regions

class Supervisor:
    def __init__(self,owner,store,world,broker,root):
        self.owner=owner;self.store=store;self.world=world;self.broker=broker;self.root=root
        self.plans={};self.seen=set();self.active=None

    def save(self,p):
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/(p['plan_id']+'.json')).write_text(json.dumps(p,indent=2,allow_nan=False))
        self.owner.private_event('PLAN_STAGE',{'plan_id':p['plan_id'],'status':p['status'],'H':p['plan']['H'],
            'K_adopted':p['K_adopted'],'K_completed':p['K_completed'],'reason':p.get('reason')})

    def public(self,p):
        return clone({k:p.get(k) for k in ('plan_id','status','K_attempted','K_submitted','K_adopted','K_completed',
            'expected_epoch','reason','trace','source_stamp','last_losses','H_planned')}) | {'H':p['plan']['H'],'m':1}

    def load(self,plan,*,broker_request_id=None):
        # Reject review results before even consulting Owner, regardless of task_usable.
        row = self.broker.rows.get(broker_request_id, {}) if broker_request_id else {}
        if row.get('role') in ('action_shadow','semantic_grounding') or row.get('execution_class') == 'REVIEW_ONLY' or plan.get('intent') == 'action_shadow':
            raise ValueError('REVIEW_RESULT_NEVER_EXECUTABLE')
        validate_plan(plan)
        v2=plan['version']==chunk_plan.VERSION
        if v2 and not broker_request_id: raise ValueError('V2_REQUIRES_BROKER_RAW')
        if broker_request_id:
            check = self.broker.rows.get(broker_request_id)
            if not check or check['status'] != 'READY' or check['role'] != 'action': raise ValueError('ACTION_BROKER_RESULT_REQUIRED')
        self.owner.admit()
        provenance='ENGINEERING_REFERENCE' if self.owner.source=='ENGINEERING_REFERENCE' else 'RESEARCH_PROGRAM'
        if broker_request_id:
            row=self.broker.rows.get(broker_request_id)
            if not row or row['status']!='READY' or row['role']!='action':raise ValueError('ACTION_BROKER_RESULT_REQUIRED')
            if row['parsed']['result']!=plan:raise ValueError('RAW_PLAN_MISMATCH')
            b=row['binding']
            if b['world_id']!=plan['world_id'] or b['world_revision']!=plan['world_revision'] or b['execution_epoch']!=plan['execution_epoch'] or plan['source_observation_id'] not in b['observation_ids']:
                raise ValueError('RAW_PLAN_BINDING_MISMATCH')
            provenance=row['provenance']
        if any(p['status'] not in ('COMPLETED','DISCARDED') for p in self.plans.values()):raise ValueError('ONE_PLAN')
        key=digest(plan)
        if key in self.seen:raise ValueError('PLAN_ALREADY_CONSUMED')
        world=self.store.get_world(plan['world_id'])
        if world['world_revision']!=plan['world_revision'] or self.store.revision!=plan['world_revision']:raise ValueError('STALE_WORLD_REVISION')
        if plan['execution_epoch']!=self.owner.epoch:raise ValueError('STALE_PLAN_EPOCH')
        self.owner.source_obs(plan['source_observation_id'])
        if world['binding']['observation_ids'][-1]!=plan['source_observation_id'] or world['binding']['execution_epoch']!=plan['execution_epoch']:
            raise ValueError('WORLD_PLAN_SOURCE_MISMATCH')
        if v2:
            from .geometry_quality import require_task_usable
            require_task_usable(world,plan['task_binding'])
            if world['state']['backend']!='semantic_lwh_v1': raise ValueError('FUSED_LWH_WORLD_REQUIRED')
            if plan['read_versions']!=world['read_versions'] or plan['read_versions']!=self.store.read_versions: raise ValueError('READ_VERSIONS_MISMATCH')
            if not set(plan['evidence_refs'])<=set(row['parsed']['evidence_refs']): raise ValueError('UNBOUND_PLAN_EVIDENCE')
            # These fields must have been request constants, not invented by A.
            for name in ('H','world_id','world_revision','execution_epoch','source_observation_id',
                         'origin_pose_world','task','task_binding','read_versions','evidence_refs'):
                bound=row['schema']['properties']['result']['properties'].get(name,{})
                # Typed schemas add constraints alongside const; exact trusted
                # value binding remains mandatory (including empty/null values).
                if 'const' not in bound or bound['const']!=plan[name]:
                    raise ValueError('PLAN_REQUEST_NOT_BOUND')
            source=self.store.get(plan['source_observation_id'])['state']
            if plan['origin_pose_world']!=[*source['actual_grasp_center_world'],*source['flange_pose_world'][3:]]: raise ValueError('ORIGIN_POSE_MISMATCH')
        self.seen.add(key)
        p={'plan_id':key,'plan':clone(plan),'source':provenance,'broker_request_id':broker_request_id,
            'status':'LOADED','segments':micro_chunks(chunk_plan.actions(plan) if v2 else plan['waypoints']),
            'segment':0,'K_attempted':0,'K_submitted':0,'K_adopted':0,'K_completed':0,'H_planned':len(plan['waypoints']),
            'expected_epoch':self.owner.epoch,'expected_state':clone(world['state']['robot_state']),
            'world_job':None,'trace':[],'loaded_monotonic':time.monotonic(),
            'v2':v2,'post_pending':False,'ready_result':None,'last_losses':None,
            'check_backend':world['state'].get('geometry_backend','legacy_rgb_rays_v1'),
            'current_world_id':world['world_id'],
            'source_stamp':chunk_plan.source_stamp(row) if v2 else None,
            'forecast':losses.forecast(plan,world['state']) if v2 else None,
            'K_policy':{'mode':'adaptive','K_cap':len(plan['waypoints'])}}
        self.plans[key]=p
        if broker_request_id:
            self.broker.save(self.broker.rows[broker_request_id],'CONSUMED_BY_SUPERVISOR')
            self.broker.action_ready=None
        self.save(p);return self.public(p)

    def from_broker(self,request_id):
        self.broker.tick();row=self.broker.rows.get(request_id)
        if not row or not row.get('parsed'):raise ValueError('BROKER_RESULT_NOT_READY')
        return self.load(row['parsed']['result'],broker_request_id=request_id)

    def policy(self,plan_id,mode,K_cap):
        p=self.plans[plan_id]
        if not p['v2'] or p['status']!='LOADED' or p['K_attempted']:raise ValueError('POLICY_BEFORE_EXECUTION_ONLY')
        if mode not in ('fixed','adaptive') or type(K_cap) is not int or not 1<=K_cap<=p['H_planned']:raise ValueError('K_POLICY')
        p['K_policy']={'mode':mode,'K_cap':K_cap};self.save(p);return self.public(p)

    def discard(self,p,reason):
        p.update(status='DISCARDED',reason=reason)
        if p['world_job'] and self.world.job:self.world.cancel(p['world_job'])
        self.save(p);return self.public(p)

    def invalid_reason(self,p):
        if self.owner.b.stopped:return 'STOP'
        if self.owner.ended:return 'CONTROL_CLOSED'
        if time.monotonic()>=self.owner.deadline:return 'EPISODE_DEADLINE'
        if p['v2']:
            if p['plan']['read_versions']!=self.store.read_versions:return 'READ_DEPENDENCY_CHANGED'
        elif p['plan']['world_revision']!=self.store.revision:return 'WORLD_REVISION_CHANGED'
        if p['expected_epoch']!=self.owner.epoch:return 'EXECUTION_EPOCH_CHANGED'
        return None

    def guard_active(self):
        if not self.active:return
        p=self.plans[self.active];reason=self.invalid_reason(p)
        if reason or p['status']=='DISCARDED':
            self.discard(p,reason or 'PLAN_CANCELLED');self.owner.b.stop()

    def step(self,plan_id):
        if plan_id not in self.plans:raise ValueError('UNKNOWN_PLAN')
        p=self.plans[plan_id]
        if p['status'] in ('COMPLETED','DISCARDED'):return self.public(p)
        reason=self.invalid_reason(p)
        if reason:return self.discard(p,reason)
        if p['world_job'] is None and p['ready_result'] is None:
            if self.world.job:return dict(self.public(p),status='WAITING_WORLD_SLOT')
            obs=self.owner.observe();p['current_source']=obs['observation_id']
            # Remeasure the configured public geometry; no stale bbox substitution.
            try:
                if p['v2']:
                    completed=p['trace'][-1]['feedback']['completed_monotonic'] if p['trace'] else 0.
                    p['ready_result']=self.world.update(p['current_world_id'],obs['observation_id'],completed)
                    p['current_world_id']=p['ready_result']['world_id']
                else:
                    p['world_job']=self.world.submit([obs['observation_id']],[],p['check_backend'],p['plan']['world_id'])['request_id']
            except Exception as exc:
                self.owner.private_event('WORLD_CHECK_REJECTED',{'error':repr(exc)})
                return self.discard(p,'WORLD_CHECK_UNAVAILABLE')
            p['status']='WAITING_WORLD';self.save(p);return self.public(p)
        job={'status':'READY','result':p.pop('ready_result')} if p.get('ready_result') is not None else self.world.poll(p['world_job'])
        p.setdefault('ready_result',None)
        if job['status'] not in ('READY','FAILED','CANCELLED'):return self.public(p)
        if job['status']!='READY':return self.discard(p,'WORLD_CHECK_'+job['status'])
        result=job['result'];binding=result['binding']
        if binding['execution_epoch']!=self.owner.epoch or binding['observation_ids'][-1]!=p['current_source']:return self.discard(p,'STALE_WORLD_CHECK')
        source=self.store.get(p['current_source'])
        if time.monotonic()-source['captured_monotonic']>=180:return self.discard(p,'WORLD_CHECK_EXPIRED')
        if p['v2']:
            from .model_context import calibration_key
            if calibration_key(source['calibration']) not in p['plan']['read_versions']:return self.discard(p,'CALIBRATION_CONTRACT_CHANGED')
        if p['v2'] and p['post_pending']:
            reference=self.store.get_world(p['plan']['world_id'])['state']
            measured=result['state']
            residual=losses.compare(p['forecast']['after_waypoint'][p['segment']-1],measured,p['trace'][-1]['feedback']['completed_monotonic'])
            boundary=p['plan']['waypoints'][p['segment']-1]['boundary_after']!='none'
            next_segment=p['segments'][p['segment']] if p['segment']<len(p['segments']) else []
            evidence=TaskEvidenceAdapter.check(p['plan']['task_binding'],reference,measured,next_segment,p['expected_state'])
            target=measured['entities'].get(p['plan']['task_binding']['object_id'],{})
            from .model_context import canonical_visibility
            visible='visible' if any(canonical_visibility(v)=='visible' for v in target.get('visibility',{}).values()) else 'unknown'
            chunk=losses.decide_chunk(completed=p['K_completed'],planned=p['H_planned'],
                K_cap=p['K_policy']['K_cap'],mode=p['K_policy']['mode'],preconditions=evidence['status']=='valid',
                residual=residual,visibility=visible,boundary=boundary)
            world_loss=losses.decide_world(persistent_unknown=target.get('status')!='coarse',geometry_loss=residual,query_budget=0)
            p['last_losses']={'L_chunk':chunk,'L_world':world_loss,'residual':residual,
                'current_observation_id':p['current_source'],'current_world_check':result['binding']}
            p['trace'][-1]['post_check']=clone(p['last_losses']);p['post_pending']=False;p['world_job']=None
            p['ready_result']={**result,'state':measured}
            if p['segment']==len(p['segments']):
                p['status']='COMPLETED';p['reason']='PREFIX_COMPLETED_POSTCHECK_RECORDED_NOT_TASK_SUCCESS'
            elif not chunk['continue_next']:
                return self.discard(p,'L_CHUNK_'+chunk['reasons'][0])
            else:p['status']='READY_FOR_NEXT_STEP'
            self.save(p);return self.public(p)
        segment=p['segments'][p['segment']]
        if p['v2']:
            from .geometry_quality import require_task_usable
            try:require_task_usable(result,p['plan']['task_binding'])
            except ValueError:return self.discard(p,'GEOMETRY_NOT_TASK_USABLE')
            expected=p['plan']['origin_pose_world'] if p['segment']==0 else p['plan']['waypoints'][p['segment']-1]['pose']
            s=result['state']['robot_state']
            distance,rotation=chunk_plan.pose_error(expected,[*s['actual_grasp_center_world'],*s['flange_pose_world'][3:]])
            if distance>=.01 or rotation>=.05:return self.discard(p,'PREDICTED_START_JOIN_MISMATCH')
        check=TaskEvidenceAdapter.check(p['plan']['task_binding'],self.store.get_world(p['plan']['world_id'])['state'],result['state'],segment,p['expected_state'])
        self.owner.private_event('TASK_EVIDENCE',check)
        if check['status']!='valid':return self.discard(p,'TASK_EVIDENCE_'+check['status'].upper())
        reason=self.invalid_reason(p)
        if reason:return self.discard(p,reason)
        before=self.owner.epoch;p['status']='EXECUTING';self.active=plan_id;self.save(p)
        origin={'kind':p['source'],'plan_id':plan_id,'broker_request_id':p['broker_request_id'],
                'H':p['plan']['H'],'waypoint_offset':p['K_adopted'],'source_observation_id':p['current_source'],'execution_epoch':before}
        origin.update(original_world_id=p['plan']['world_id'],original_world_revision=p['plan']['world_revision'],
            original_source_observation_id=p['plan']['source_observation_id'],source_stamp=p['source_stamp'])
        self.owner.execution_origin=origin;p['K_attempted']+=1;submitted_at=time.monotonic()
        try:
            feedback=self.owner.execute(clone(segment),p['current_source'])
            p['K_submitted']+=len(segment)
            if feedback.get('execution_outcome')=='UNKNOWN_AFTER_BACKEND_EXCEPTION':p['K_adopted']=None
            else:p['K_adopted']+=len(feedback.get('actions',[]))
            p['K_completed']+=sum(a['completed'] is True for a in feedback.get('actions',[]))
            p['trace'].append({'origin':origin,'feedback':feedback,'submitted_monotonic':submitted_at,
                'returned_monotonic':time.monotonic(), 'nominal_end_offset_s':p['plan']['waypoints'][p['segment']].get('nominal_end_offset_s')})
        except Exception as exc:
            self.owner.private_event('SUPERVISOR_REJECTED',{'plan_id':plan_id,'error':repr(exc)})
            return self.discard(p,'OWNER_REJECTED_NO_REPLAY')
        finally:self.active=None;self.owner.execution_origin=None
        if not feedback['ok'] or p['status']=='DISCARDED':return self.discard(p,p.get('reason') or 'PARTIAL_OR_UNKNOWN_EXECUTION_FAILURE')
        if self.owner.epoch!=before+1:return self.discard(p,'UNEXPECTED_EXECUTION_EPOCH_ADVANCE')
        p['expected_epoch']=self.owner.epoch;p['expected_state']=feedback['actual_state'];p['segment']+=1;p['world_job']=None
        if p['v2']:
            p['post_pending']=True;p['status']='POST_CHECK_REQUIRED';self.save(p)
            # No additional model request. Final waypoint also requires this observation.
            return self.step(plan_id)
        if any(a['type']=='gripper' for a in segment) and p['segment']<len(p['segments']):
            return self.discard(p,'GRIPPER_BARRIER_REQUIRES_NEW_EVIDENCE_AND_PLAN')
        p['status']='COMPLETED' if p['segment']==len(p['segments']) else 'READY_FOR_NEXT_STEP'
        self.save(p);return self.public(p)

    def cancel(self,plan_id):
        if plan_id not in self.plans:raise ValueError('UNKNOWN_PLAN')
        if self.plans[plan_id]['status'] in ('COMPLETED','DISCARDED'):return self.public(self.plans[plan_id])
        return self.discard(self.plans[plan_id],'EXTERNAL_CANCEL')

    def close(self):
        for p in self.plans.values():
            if p['status'] not in ('COMPLETED','DISCARDED'):self.discard(p,'OWNER_CLOSED')
