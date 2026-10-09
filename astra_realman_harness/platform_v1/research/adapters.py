"""Composition into the existing Owner, not another runtime or physical owner."""
from .contracts import VERSION, plan_schema, semantic_schema
from .public_store import PublicStore
from .broker import Broker
from .world_head import WorldHead
from .supervisor import Supervisor
from .native_subagent import NativeCodexSubagentBackend

class ResearchAdapters:
    fields = {
        'research_capabilities': set(),
        'broker_submit': {'request'}, 'broker_poll': {'request_id'}, 'broker_cancel': {'request_id'},
        'world_submit': {'observation_ids','evidence_ids','backend','reference_world_id'},
        'world_poll': {'request_id'}, 'world_cancel': {'request_id'},
        'supervisor_from_broker': {'request_id'}, 'supervisor_load': {'plan'},
        'supervisor_step': {'plan_id'}, 'supervisor_cancel': {'plan_id'}}

    def __init__(self, owner):
        self.owner=owner;self.closed=False
        self.store=PublicStore(owner.public,owner.id)
        for row in owner.observations.values():self.store.observe(row['public'],row['epoch'])
        self.broker=Broker(owner.private/'research_broker',self.store,owner.infer_config,
            deadline=owner.deadline,epoch=lambda:owner.epoch,
            allowance=lambda:owner.max_requests-owner.slot.calls-self.broker.calls,
            baseline_busy=lambda:bool(owner.slot.job or owner.proposal),emit=owner.private_event)
        self.world=WorldHead(owner.private/'world_head',self.store,epoch=lambda:owner.epoch,
            deadline=owner.deadline,emit=owner.private_event)
        self.supervisor=Supervisor(owner,self.store,self.world,self.broker,owner.private/'plans')

    def capabilities(self):
        return {'version':VERSION,'native_subagent':NativeCodexSubagentBackend.capabilities(),
            'plan_schema':plan_schema(),'semantic_schema':semantic_schema(),
            'model_roles':['semantic_e0','action','local_reground'],'max_model_in_flight':1,
            'shared_attempt_cap':self.owner.max_requests,'geometry_timeout_s':10,
            'generic_identity_verifier':'UNKNOWN_NO_EQUIVALENT_VERIFIER',
            'geometry_workers':['legacy_rgb_rays_v1','bbox_rays_v1'],
            'automatic_physical_submission':False}

    def dispatch(self,method,params):
        if not isinstance(params,dict) or set(params)!=self.fields[method]:raise ValueError('RESEARCH_PARAMETERS')
        if method=='research_capabilities':return self.capabilities()
        # Poll/cancel remain readable during STOP; no new work or execution admitted.
        if not method.endswith(('_poll','_cancel')):self.owner.admit()
        if method.startswith('broker_'):return getattr(self.broker,method[7:])(**params)
        if method.startswith('world_'):return getattr(self.world,method[6:])(**params)
        if method.startswith('supervisor_'):return getattr(self.supervisor,method[11:])(**params)
        raise ValueError('RESEARCH_METHOD')

    def tick(self):
        if self.closed:return
        if self.owner.b.stopped:self.cancel_pending()
        self.broker.tick();self.world.tick();self.supervisor.guard_active()

    def cancel_pending(self):
        if self.broker.job:self.broker.job[1].cancel('OWNER_STOP')
        if self.world.job:self.world.job[1].cancel('OWNER_STOP')

    def close(self):
        if self.closed:return
        self.closed=True;self.supervisor.close();self.broker.close();self.world.close()
