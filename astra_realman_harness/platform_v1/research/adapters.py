"""Composition into the existing Owner, not another runtime or physical owner."""
from .contracts import VERSION, plan_schema, semantic_schema
from .public_store import PublicStore
from .broker import Broker
from .world_head import WorldHead
from .supervisor import Supervisor
from .native_subagent import NativeCodexSubagentBackend
from . import chunk_plan, fusion, integration

class ResearchAdapters:
    fields = {
        'research_capabilities': set(),
        'broker_submit': {'request'}, 'broker_poll': {'request_id'}, 'broker_cancel': {'request_id'},
        'world_submit': {'observation_ids','evidence_ids','backend','reference_world_id'},
        'world_poll': {'request_id'}, 'world_cancel': {'request_id'},
        'supervisor_from_broker': {'request_id'}, 'supervisor_load': {'plan'},
        'supervisor_step': {'plan_id'}, 'supervisor_cancel': {'plan_id'},
        'supervisor_policy': {'plan_id','mode','K_cap'},
        'lwh_prepare': {'observation_id'}, 'lwh_fuse': {'geometry_request_id','semantic_evidence_id'},
        'lwh_action': {'world_id','task','task_binding','H'}}

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
            'plan_schema':chunk_plan.plan_schema(),'semantic_schema':fusion.semantic_schema(),
            'legacy_plan_schema':plan_schema(),'legacy_semantic_schema':semantic_schema(),
            'model_roles':['semantic_e0','action','local_reground'],'max_model_in_flight':1,
            'shared_attempt_cap':self.owner.max_requests,'geometry_timeout_s':10,
            'generic_identity_verifier':'UNKNOWN_NO_EQUIVALENT_VERIFIER',
            'geometry_workers':['legacy_rgb_rays_v1','bbox_rays_v1','da3_small_v1'],
            'learned_geometry_status':'CONFIGURED_NOT_ACCEPTED' if self.world.learned_config else 'NOT_CONFIGURED_NOT_ACCEPTED',
            'coarse_plan_m':1,'model_concurrency_status':'NATIVE_NOT_ACCEPTED',
            'automatic_physical_submission':False}

    def dispatch(self,method,params):
        if not isinstance(params,dict) or set(params)!=self.fields[method]:raise ValueError('RESEARCH_PARAMETERS')
        if method=='research_capabilities':return self.capabilities()
        # Poll/cancel remain readable during STOP; no new work or execution admitted.
        if not method.endswith(('_poll','_cancel')):self.owner.admit()
        if method=='lwh_prepare':
            # Explicit RPC is necessary; default startup never consumes requests.
            oid=params['observation_id'];self.owner.source_obs(oid)
            if self.broker.config is None:raise ValueError('MODEL_DISABLED')
            if not self.world.learned_config:raise ValueError('DA3_NOT_CONFIGURED_NOT_ACCEPTED')
            geometry=self.world.submit([oid],[],'da3_small_v1')
            try:semantic=self.broker.submit(integration.semantic_request(oid))
            except Exception:
                self.world.cancel(geometry['request_id']);raise
            return {'geometry':geometry['request_id'],'semantic':semantic['request_id'],
                'concurrency_claim':'JOBS_SUBMITTED_SAME_FROZEN_INPUT_NATIVE_EA_NOT_VERIFIED'}
        if method=='lwh_fuse':
            row=self.world.poll(params['geometry_request_id'])
            if row['binding']['execution_epoch']!=self.owner.epoch:raise ValueError('STALE_FUSION_EPOCH')
            return fusion.fuse(self.store,row,params['semantic_evidence_id'])
        if method=='lwh_action':
            w=self.store.get_world(params['world_id']);oid=w['binding']['observation_ids'][-1]
            self.owner.source_obs(oid)
            if w['world_revision']!=self.store.revision:raise ValueError('STALE_ACTION_WORLD')
            return self.broker.submit(integration.action_request(w,self.store.get(oid),params['task'],params['task_binding'],params['H']))
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
