"""Plan-to-micro-chunk adapter; policy supplies plan and explicitly requests each step."""
import json
import time
from .contracts import clone,digest,validate_plan,micro_chunks
from .task_evidence import TaskEvidenceAdapter

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
        return clone({k:p.get(k) for k in ('plan_id','status','K_submitted','K_adopted','K_completed','expected_epoch','reason','trace')}) | {'H':p['plan']['H']}

    def load(self,plan,*,broker_request_id=None):
        self.owner.admit();validate_plan(plan)
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
        self.seen.add(key)
        p={'plan_id':key,'plan':clone(plan),'source':provenance,'broker_request_id':broker_request_id,
            'status':'LOADED','segments':micro_chunks(plan['waypoints']),'segment':0,'K_submitted':0,'K_adopted':0,'K_completed':0,
            'expected_epoch':self.owner.epoch,'expected_state':clone(world['state']['robot_state']),
            'world_job':None,'trace':[],'loaded_monotonic':time.monotonic()}
        self.plans[key]=p
        if broker_request_id:
            self.broker.save(self.broker.rows[broker_request_id],'CONSUMED_BY_SUPERVISOR')
            self.broker.action_ready=None
        self.save(p);return self.public(p)

    def from_broker(self,request_id):
        self.broker.tick();row=self.broker.rows.get(request_id)
        if not row or not row.get('parsed'):raise ValueError('BROKER_RESULT_NOT_READY')
        return self.load(row['parsed']['result'],broker_request_id=request_id)

    def discard(self,p,reason):
        p.update(status='DISCARDED',reason=reason)
        if p['world_job'] and self.world.job:self.world.cancel(p['world_job'])
        self.save(p);return self.public(p)

    def invalid_reason(self,p):
        if self.owner.b.stopped:return 'STOP'
        if self.owner.ended:return 'CONTROL_CLOSED'
        if time.monotonic()>=self.owner.deadline:return 'EPISODE_DEADLINE'
        if p['plan']['world_revision']!=self.store.revision:return 'WORLD_REVISION_CHANGED'
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
        segment=p['segments'][p['segment']]
        if p['world_job'] is None:
            if self.world.job:return dict(self.public(p),status='WAITING_WORLD_SLOT')
            obs=self.owner.observe();p['current_source']=obs['observation_id']
            # Shared old RGB geometry is remeasured, never stale bbox/current identity substitution.
            p['world_job']=self.world.submit([obs['observation_id']],[], 'legacy_rgb_rays_v1',p['plan']['world_id'])['request_id']
            p['status']='WAITING_WORLD';self.save(p);return self.public(p)
        job=self.world.poll(p['world_job'])
        if job['status'] not in ('READY','FAILED','CANCELLED'):return self.public(p)
        if job['status']!='READY':return self.discard(p,'WORLD_CHECK_'+job['status'])
        result=job['result'];binding=result['binding']
        if binding['execution_epoch']!=self.owner.epoch or binding['observation_ids'][-1]!=p['current_source']:return self.discard(p,'STALE_WORLD_CHECK')
        source=self.store.get(p['current_source'])
        if time.monotonic()-source['captured_monotonic']>=180:return self.discard(p,'WORLD_CHECK_EXPIRED')
        check=TaskEvidenceAdapter.check(p['plan']['task_binding'],self.store.get_world(p['plan']['world_id'])['state'],result['state'],segment,p['expected_state'])
        self.owner.private_event('TASK_EVIDENCE',check)
        if check['status']!='valid':return self.discard(p,'TASK_EVIDENCE_'+check['status'].upper())
        reason=self.invalid_reason(p)
        if reason:return self.discard(p,reason)
        before=self.owner.epoch;p['status']='EXECUTING';self.active=plan_id;self.save(p)
        origin={'kind':p['source'],'plan_id':plan_id,'broker_request_id':p['broker_request_id'],
                'H':p['plan']['H'],'waypoint_offset':p['K_adopted'],'source_observation_id':p['current_source'],'execution_epoch':before}
        self.owner.execution_origin=origin
        try:
            feedback=self.owner.execute(clone(segment),p['current_source'])
            p['K_submitted']+=len(segment)
            if feedback.get('execution_outcome')=='UNKNOWN_AFTER_BACKEND_EXCEPTION':p['K_adopted']=None
            else:p['K_adopted']+=len(feedback.get('actions',[]))
            p['K_completed']+=sum(a['completed'] is True for a in feedback.get('actions',[]))
            p['trace'].append({'origin':origin,'feedback':feedback,'returned_monotonic':time.monotonic()})
        except Exception as exc:
            self.owner.private_event('SUPERVISOR_REJECTED',{'plan_id':plan_id,'error':repr(exc)})
            return self.discard(p,'OWNER_REJECTED_NO_REPLAY')
        finally:self.active=None;self.owner.execution_origin=None
        if not feedback['ok'] or p['status']=='DISCARDED':return self.discard(p,p.get('reason') or 'PARTIAL_OR_UNKNOWN_EXECUTION_FAILURE')
        if self.owner.epoch!=before+1:return self.discard(p,'UNEXPECTED_EXECUTION_EPOCH_ADVANCE')
        p['expected_epoch']=self.owner.epoch;p['expected_state']=feedback['actual_state'];p['segment']+=1;p['world_job']=None
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
