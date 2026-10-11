"""One newly authorized transport/place episode with separate engineering initialization. Existing Broker/WorldHead/Owner only; no retries."""
import argparse,ast,hashlib,json,jsonschema,math,shutil,signal,sys,time,traceback,uuid
from pathlib import Path
from platform_v1.owner import Owner
from platform_v1.research.rgbd_sensor import RGBDObservationBackend
from platform_v1.research.contracts import digest,clone
from platform_v1.research import action_proposal,chunk_plan,losses,pnp_proposal
from platform_v1.research.review_contracts import grounding_request
from platform_v1.research.semantic_binding import import_grounding_archive
from sim_skills.full_pnp.infer_process import InferConfig
from scripts.structured_outputs import check_provider

ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parents[1]
TASK={'id':'RUN_TRANSPORT_PLACE_FROM_HELD','revision':'1','stage':'T2_TRANSPORT_PREPLACE'}
TASK_TEXT=('Before engineering grasp initialization, identify the red cuboid and the observed green destination for the subsequent transport/place task. Identity only: do not assert that grasp or holding has occurred. '
 'Bind the actual red cuboid geometry ID; classify robot/table separately. For the green planar destination absent from geometry IDs, '
 'request new_planar_region with an actual image bbox and evidence refs. Do not invent region XYZ, object pose, contact or holding state.')
PROTOCOL={'scope':'RUN_TRANSPORT_PLACE_FROM_HELD','new_episodes':1,'semantic_max':100000,'action_max':100000,'owner_single_action_max':80,'m':1,'H_max':4,
 'request_timeout_s':90,'wall_s':1800,'seed':2,'settle_steps':120,
 'completion':{'independent':'unchanged FullTaskBackend.finish physical_success; model_finished independently from raw decision; engineering grasp never policy credit',
 'online':'separate RGBD/FK visual hypotheses; close not held; current release inside observed region, open gap>70mm, tool Z>=80mm, separation>=30mm, stable released evidence'},
 'recheck':{'join_position_max_m':.01,'join_rotation_max_rad':.05,'stationary_target_shift_max_m':.03,
 'carrying_visual_vs_FK_residual_max_m':.03,'close_alone_never_held':True,'gripper_barrier':'fresh observation then new Action request'},
 'application_retry':0,'HTTP_SSE_retry':0,'unbounded_retry':False,'fallback':0,'hardware':0,'training':0,'native_concurrency':0,
 'scene':'same original FullTaskBackend simple red/green scene, empty preparation; no layout changes',
 'owner_budget':{'accepted_single_action_chunks':80,'observations':512,'default_owner_cap_unchanged':12},'shared_tool':'calibrated_grasp_request.v1','comparison':'FULL_SYSTEM_vs_VANILLA_ASTRA_two_fresh_episodes_sequential_no_rerun','order':['FULL_SYSTEM','VANILLA_ASTRA'],'authorization':'NEW_HELD_RUN_AUTHORIZATION_REQUIRED','development_recovery':'target_local_reassociation.v1' ,'expected_contact':'unchanged SharedGraspController and scene collision/contact handling',
 'initialization':{'source':'ENGINEERING_PRIVATE_SETUP_NOT_ASTRA_POLICY','max_submissions':12,'max_wall_s':180,'included_in_total_80':True,'postclose_lift_m':.08,'hold_s':1.2,'no_retry':True,'GT_online':False,'held_world':'public pre-grasp Build and Semantic identity; current RGBD/FK and actual completion World Updates through initialization; held current target and destination required before Action'}}
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pose(o):return [*o['state']['actual_grasp_center_world'],*o['state']['flange_pose_world'][3:]]
def brief(w):
    return {i:{k:e.get(k) for k in ('point_world_m','bounds_world_m','coarse_observed_bounds_world_m','status','semantic_category','semantic_status','visibility','temporal_association','geometry_residual','reason')} for i,e in w['state']['entities'].items()}
def seal_semantic(out,b,row,request,store,w):
    if b.calls!=1 or b.infer_calls!=1:raise ValueError('SEMANTIC_ATTEMPT_COUNT')
    dest=out/'semantic_sealed';dest.mkdir()
    shutil.copytree(b.root/row['request_id'],dest/'broker/broker-001')
    eid=row['evidence_id'];e=store.get_evidence(eid)
    for name,value in [('REQUEST.json',request),('RAW_RESPONSE.json',{'raw':row['raw']}),('PARSED_RESPONSE.json',{'parsed':row['parsed']}),
        (eid+'.json',e),('MODEL_RESULT.json',{'status':'READY','broker_submissions':b.calls,'infer_started_count':b.infer_calls,'evidence_id':eid,'qualified_request_id':out.name+'/'+row['request_id']}),
        ('PROVENANCE_AUDIT.json',{'raw_utf8_sha256':hashlib.sha256(row['raw'].encode()).hexdigest(),'input_wire_sha256':row['wire_sha256']})]:save(dest/name,value)
    for a,n in [('schema.json','PROVIDER_SCHEMA.json'),('authoritative_schema.json','AUTHORITATIVE_SCHEMA.json')]:shutil.copyfile(b.root/row['request_id']/a,dest/n)
    files={str(p.relative_to(dest)):sha(p) for p in dest.rglob('*') if p.is_file()}
    save(dest/'MODEL_RESULT_SEAL.json',{'sealed_before_independent_review':True,'files':files})
    save(dest/'DELIVERY_MANIFEST.json',{str(p.relative_to(dest)):sha(p) for p in dest.rglob('*') if p.is_file()})
    import_grounding_archive(store,dest,sha(dest/'DELIVERY_MANIFEST.json'),w['world_id'],eid)
    return eid

def skill_actions(world,observation,proposal):
    """Explicit tool expansion, never a replacement for a model move_pose."""
    raw=proposal['fine_actions']
    if not (proposal['phase']=='grasp' and proposal['mode']=='fine' and raw==[{'type':'gripper','opening':.45}]):
        raise ValueError('CALIBRATED_SKILL_REQUEST_REQUIRED')
    inter=world['state']['pnp_interaction'];e=world['state']['entities'][inter['target_geometry_id']]
    if not inter['current_support'] or inter['gripper_event']!='none' or inter['status']!='tabletop_target' or e['status']!='coarse':
        raise ValueError('SKILL_CURRENT_TABLETOP_TARGET_REQUIRED')
    if e['observation_id']!=observation['observation_id']:raise ValueError('SKILL_STALE_CURRENT_MEASUREMENT')
    start=pose(observation);point=e['point_world_m']
    plane=world['state']['public_plane']
    if plane['normal']!=[0,0,1]:raise ValueError('SKILL_HORIZONTAL_PUBLIC_PLANE_REQUIRED')
    z=-plane['offset']+.04
    if not (z<=start[2]<=z+.11+1e-6) or math.dist(start[:2],point[:2])>.05 or chunk_plan.pose_error([0,0,0,0,1,0,0],[0,0,0,*start[3:]])[1]>.05:
        raise ValueError('SKILL_PRECONTACT_DOMAIN_NOT_MET')
    if observation['state']['actual_pad_gap_m']<=.07:raise ValueError('SKILL_OPEN_START_REQUIRED')
    actions=[];current=start[:3]
    for goal in ([point[0],point[1],start[2]],[point[0],point[1],z]):
        distance=math.dist(current,goal)
        if distance>1e-5:
            n=math.ceil(distance/.04);origin=current[:]
            for i in range(1,n+1):
                nxt=[origin[j]+(goal[j]-origin[j])*i/n for j in range(3)]
                actions.append({'type':'move_pose','pose':[*nxt,*start[3:]]})
            current=list(goal)
    actions.append({'type':'gripper','opening':.45})
    return actions


def no_action_recovery_route(answer,derived,previous_support,current_valid):
    # This branch cannot produce an action; refused conflicts remain stopped.
    if not derived.get('recovery_only') or derived['actions'] or derived['plan'] is not None or derived['grants_execution'] is not False:
        raise ValueError('RECOVERY_CANNOT_CONTAIN_OR_AUTHORIZE_ACTIONS')
    if answer['proposal'] is not None or answer['fine_actions'] or answer['decision'] not in ('refused','need_more_evidence'):
        raise ValueError('RECOVERY_RAW_NOT_NO_ACTION')
    if answer['decision']=='need_more_evidence' and not previous_support and current_valid:
        return 'NEW_PLAN_FROM_NEW_CURRENT_SUPPORT'
    return 'STOP_NO_EXECUTION_WITH_ORIGINAL_REASON'

def public_initialization_feedback(feedback):
    # Private setup waypoints are not World inputs. Preserve the actual close
    # event and receipt hash; current geometry comes only from sensor RGB-D/FK.
    return {'kind':'ENGINEERING_INITIALIZATION_ACTUAL_COMPLETION',
        'ok':feedback['ok'],'completed_monotonic':feedback['completed_monotonic'],
        'actions':[clone(x) for x in feedback['actions'] if x['action']['type']=='gripper'],
        'original_receipt_sha256':digest(feedback),
        'source':'ACTUAL_OWNER_RECEIPT_WITH_PRIVATE_SETUP_WAYPOINTS_WITHHELD'}

def completion_endpoints(status,score):
    return {'physical_success':score['physical_success'],'model_finished':status=='MODEL_FINISHED',
        'physical_source':'UNCHANGED_INDEPENDENT_SCORER_AFTER_ONLINE_SEAL','model_source':'RAW_FINISHED_DECISION',
        'original_score_status':score['status'],'engineering_grasp_policy_credit':False}

def main(out):
    # Fixed task must fail locally before authorization consumption, scene or E/A.
    jsonschema.validate(TASK,chunk_plan.plan_schema()['properties']['task'])
    if not isinstance(TASK_TEXT,str) or not TASK_TEXT.strip():raise ValueError('EMPTY_FIXED_TASK_TEXT')
    if json.loads((out/'PROTOCOL.json').read_text())!=PROTOCOL:raise ValueError('PROTOCOL_CHANGED')
    expected=json.loads((out/'SOURCE_SHA256.json').read_text())
    for p,h in expected.items():
        if sha(ROOT/p)!=h:raise ValueError('SOURCE_CHANGED:'+p)
    auth=json.loads((out/'AUTHORIZATION.json').read_text())
    if not auth['granted'] or auth['scope']!=PROTOCOL['scope']:raise ValueError('AUTHORIZATION')
    condition=auth['condition'];full=condition=='FULL_SYSTEM'
    pnp_proposal.AB_RESOURCE_CONTRACT=True
    from scripts.ab_sensor_model import run_vanilla,history_entry
    from platform_v1.research.public_store import PublicStore
    sensor_store=None;own_history=[];no_progress=0
    if condition not in PROTOCOL['order']:raise ValueError('PAIR_CONDITION')
    launcher=Path(auth['launcher'])
    if sha(launcher)!=auth['launcher_sha256'] or sha(launcher.parent.parent/'libexec/codex')!=auth['binary_sha256']:raise ValueError('LAUNCHER_CHANGED')
    settings=next(ast.literal_eval(n.value) for n in ast.parse(launcher.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='settings' for t in n.targets))
    if any(settings[k]!='0' for k in ('model_providers.s1_openai_no_retry.request_max_retries','model_providers.s1_openai_no_retry.stream_max_retries')) or settings['features.unbounded_connection_retries']!='false':raise ValueError('RETRIES_ENABLED')
    with (out/'EPISODE_CLAIM.json').open('x') as f:json.dump({'authorization_id':auth['id'],'consumed_unix':time.time(),'no_retry':True},f)
    started=time.monotonic();owner=None;rows=[];calls=[];worlds=[];rechecks=[];recoveries=[];K=0;attempted=0;stage='INITIALIZE';initial_q=None;init_K=0;policy_start_step=None;init_attempted=0
    result={'status':'INCOMPLETE','transport_place_result':'NOT_COMPLETED','new_SAPIEN_episode_attempts':1,'K':0,'E':0,'A':0,'hardware':0,'training':0,'native_concurrency':0,'condition':condition,'skill_grasp_credit':'ENGINEERING_INITIALIZATION_EXCLUDED_FROM_ASTRA_POLICY','experiment':'RUN_TRANSPORT_PLACE_FROM_HELD'}
    def timeout(*_):raise TimeoutError('TOTAL_EPISODE_WALL_DEADLINE')
    signal.signal(signal.SIGTERM,timeout);signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,1780)
    def capture():
        o=owner.observe()
        if sensor_store is not None:sensor_store.observe(o,owner.epoch)
        save(out/'observations'/(o['observation_id'].replace(':','_')+'.json'),o);return o
    def keep(w,label):
        save(out/'worlds'/(str(w['world_revision'])+'_'+label+'.json'),w);worlds.append({'world_id':w['world_id'],'revision':w['world_revision'],'entities':brief(w),'label':label})
        save(out/'WORLD_TRACE.json',worlds)
    def current_recheck(world, observation, expected_pose, label, feedback=None, current=None):
        # Both model-latency refresh and post-action suffix use this exact path.
        # No-action receipt records only a host sensing boundary, never an Owner completion.
        begin=time.monotonic()
        if feedback is None:
            boundary=time.monotonic()
            feedback={'kind':'OBSERVATION_ONLY_NO_ACTION','ok':True,'actions':[],
                'owner_submissions':0,'completed_monotonic':boundary,
                'source_observation_id':observation['observation_id'],
                'execution_epoch':owner.epoch,'ok_scope':'HOST_SENSING_BOUNDARY_NOT_CONTROL_SUCCESS'}
        if current is None:current=capture()
        measured=ad.world.update(world['world_id'],current['observation_id'],
            feedback['completed_monotonic'],execution_feedback={**feedback,'run_full_pnp':True})
        keep(measured,label)
        entity=measured['state']['entities'].get(target,{})
        interaction=measured['state']['pnp_interaction'];destination=measured['state']['pnp_destination']
        shift=interaction['current_position_shift_m']
        supported=interaction['current_support']
        distance,rotation=chunk_plan.pose_error(expected_pose,pose(current))
        is_boundary=any(x.get('completed') and x['action']['type']=='gripper' for x in feedback.get('actions',[]))
        # Closing changes pad-center offset. Validate measured flange, not a fake
        # stationary pad center across the gripper kinematic boundary.
        if is_boundary:
            distance,rotation=chunk_plan.pose_error(observation['state']['flange_pose_world'],current['state']['flange_pose_world'])
        if interaction['gripper_event']=='close':
            residual=interaction['current_visual_vs_carry_prediction_residual_m']
            consistent=supported and residual is not None and residual<=.03
        else:consistent=supported and (shift is None or shift<=.03)
        valid=feedback['ok'] and consistent and distance<.01 and rotation<.05
        check={'label':label,'previous_world_id':world['world_id'],'current_world_id':measured['world_id'],
            'observation_id':current['observation_id'],'feedback_kind':feedback.get('kind','ACTUAL_OWNER_COMPLETION'),
            'supported':supported,'valid':valid,'target':target,'target_current':brief(measured).get(target),
            'pnp_interaction':interaction,'pnp_destination':destination,'gripper_boundary':is_boundary,
            'target_surface_displacement_m':shift,'join_position_m':distance,'join_rotation_rad':rotation,
            'association':measured['state']['temporal_association'],
            'current_evidence':entity.get('current_evidence',[]),'wall_s':time.monotonic()-begin}
        rechecks.append(check);save(out/'CURRENT_RECHECKS.json',rechecks)
        if not feedback['ok'] or not math.isfinite(distance+rotation) or distance>=.01 or rotation>=.05:
            raise RuntimeError('CURRENT_MEASURED_JOIN_CONTROL_MISMATCH')
        return measured,current,check
    def initialize_held(observation):
        # Private engineering setup only, excluded from policy credit. Original
        # guarded Owner/grasp control. Setup target coordinates never reach WH/E/A.
        nonlocal K,attempted,stage,init_K,init_attempted,w
        begin=time.monotonic();initial_step=owner.b.steps
        episode_deadline=owner.deadline
        owner.deadline=min(episode_deadline,begin+PROTOCOL['initialization']['max_wall_s'])
        def perform(action):
            nonlocal observation,K,attempted,stage,init_K,init_attempted,w
            if init_attempted>=12 or attempted>=80:raise RuntimeError('ENGINEERING_INITIALIZATION_ACTION_CAP')
            stage='ENGINEERING_HELD_INITIALIZATION';owner.admit()
            start_pose=pose(observation);attempted+=1;init_attempted+=1
            row={'chunk':0,'index':init_attempted,'phase':'engineering_held_initialization','mode':'engineering',
                 'model_original_action':None,'model_original_skill_request':None,'model_request_id':None,
                 'executed_action':clone(action),'action_source':'ENGINEERING_INITIALIZATION_NOT_POLICY',
                 'source':{'producer':'ENGINEERING_INITIALIZATION','policy_grasp_credit':False},
                 'actual_start':start_pose,'submitted_monotonic':time.monotonic(),'status':'SUBMITTING'}
            rows.append(row);save(out/'TRAJECTORY.json',rows)
            owner.execution_origin=clone(row['source'])
            try:fb=owner.execute([clone(action)],observation['observation_id'])
            finally:owner.execution_origin=None
            count=sum(a['completed'] is True for a in fb['actions']);K+=count;init_K+=count
            row.update(feedback=fb,K_total=K,owner_wall_s=time.monotonic()-row['submitted_monotonic'],
              actual_reached=[*fb['actual_state']['actual_grasp_center_world'],*fb['actual_state']['flange_pose_world'][3:]])
            save(out/'TRAJECTORY.json',rows)
            if not fb['ok']:raise RuntimeError('INITIALIZATION_OWNER_CONTROL_FAILED:'+str(fb))
            previous=observation;observation=capture()
            # Keep public identity through contact using actual completion and
            # current RGB-D/FK. Unknown robot-linked occupancy remains in WH.
            expected=action['pose'] if action['type']=='move_pose' else start_pose
            if full:
                w,observation,check=current_recheck(w,previous,expected,
                    'initialization_after_'+str(init_attempted),public_initialization_feedback(fb),current=observation)
                row.update(update_wall_s=check['wall_s'],WH_after=brief(w).get(target),
                    interaction_after=check['pnp_interaction'],destination_after=check['pnp_destination'])
            row.update(status='COMPLETED',post_observation_id=observation['observation_id'])
            own_history.append(history_entry(observation,[],public_initialization_feedback(fb)))
            save(out/'TRAJECTORY.json',rows)
        # Existing engineering setup uses private scene XY. It is NOT an online
        # object estimate; neither these coordinates nor qualification truth
        # enter the public World Update or model input.
        x,y=owner.b.s.object_pose()[:2]
        for z in (.15,.04):perform({'type':'move_pose','pose':[x,y,z,0,1,0,0]})
        perform({'type':'gripper','opening':.45})
        start=pose(observation)
        for dz in (.04,.08):perform({'type':'move_pose','pose':[start[0],start[1],start[2]+dz,*start[3:]]})
        perform({'type':'hold','seconds':1.2})
        # Original private engineering qualification gates the initialization
        # only; these truth arrays are never supplied to WH or the model.
        from sim_skills.full_pnp.grasp_assessment import assess_grasp
        assessment=assess_grasp(owner.b.adapter.score_trace,owner.b.adapter.initial_z,
            owner.b.grasp_controller.last_close,stopped=owner.b.stopped)
        save(out/'ENGINEERING_INITIALIZATION_PRIVATE_SCORE.json',assessment)
        if not assessment['stable_hold_seen'] or not assessment['contact_qualified_after_close']:
            raise RuntimeError('ENGINEERING_INITIALIZATION_NOT_STABLY_HELD')
        save(out/'HELD_BOUNDARY.json',{'source':'ENGINEERING_INITIALIZATION_NOT_POLICY',
            'policy_grasp_credit':False,'initial_step':initial_step,'policy_start_step':owner.b.steps,
            'initialization_completed_K':init_K,'initialization_submissions':init_attempted,
            'observation_id':observation['observation_id'],'wall_s':time.monotonic()-begin,
            'private_score_not_in_model_or_WH_input':True})
        owner.deadline=episode_deadline
        return observation

    def model(req,kind):
        nonlocal stage
        stage=kind+'_REQUEST';idx=sum(c['kind']==kind for c in calls)+1
        if time.monotonic()>=owner.deadline:raise TimeoutError('MODEL_WALL_BUDGET')
        save(out/('request_'+kind+str(idx)+'.json'),req)
        with (out/('REQUEST_CLAIM_'+kind+str(idx)+'.json')).open('x') as f:json.dump({'kind':kind,'index':idx,'authorization_id':auth['id'],'request_sha256':digest(req),'retry':False},f)
        t=time.monotonic();calls.append({'kind':kind,'index':idx,'started_monotonic':t,'status':'SUBMITTING',
            'trigger':'INITIAL_TARGET_AND_DESTINATION_SEMANTICS' if kind=='E' else 'CURRENT_HELD_WORLD_OR_COMPLETED_CHUNK_OR_RECOVERY',
            'world_id':req['world_id'],'observation_ids':[x['observation_id'] for x in req['images']]});save(out/'CALLS.json',calls)
        b=owner.research.broker
        try:
            save(out/'OWN_SUBTASK_HISTORY.json',own_history)
            b.ab_recent_history=clone(own_history)
            rid=b.submit(req)['request_id'];calls[-1]['request_id']=rid
            while b.job:
                b.tick()
                if b.job:owner.idle()
            row=b.rows[rid];calls[-1].update(status=row['status'],error=row['error'],usage=row['usage_raw'],wall_s=time.monotonic()-t,raw_sha256=hashlib.sha256((row['raw'] or '').encode()).hexdigest())
            save(out/'CALLS.json',calls)
            # Raw, parsed, worker events and schemas are already written by the original Broker.
            save(out/('MODEL_SEAL_'+kind+str(idx)+'.json'),{'files':{str(p.relative_to(out)):sha(p) for p in (b.root/rid).rglob('*') if p.is_file()},'sealed_before_review':True})
            if row['status']!='READY':raise RuntimeError('MODEL_'+row['status']+':'+str(row['error']))
            return row
        finally:
            calls[-1]['wall_s']=time.monotonic()-t;save(out/'CALLS.json',calls)
    try:
        run=out/'episode';run.mkdir()
        assets=WS/'astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets'
        owner=Owner(assets,run,seed=2,budget_s=max(1,1770-(time.monotonic()-started)),source='RUN_FULL_PNP',infer_config=InferConfig(str(launcher),fixture=False),max_requests=100000,backend_factory=RGBDObservationBackend,execution_chunk_budget=80,observation_budget=512)
        owner.deadline=min(owner.deadline,started+1770)
        if full:
            owner.enable_research_adapters();ad=owner.research
            ad.broker.pnp_episode_authorization=owner.id
            ad.broker.pnp_request_cap=100000;ad.broker.ab_sensor_input=True
            sensor_store=ad.store
        else:
            sensor_store=PublicStore(owner.public,owner.id)
        # Host-only timing: no model context, sensor, action or scheduling changes.
        import functools, inspect
        from platform_v1.research import semantic_binding as binding_module, rgbd_world
        cache=sensor_store.verification_cache
        if not sensor_store.validation_cache_enabled or not cache.enabled:
            raise RuntimeError('REQUIRED_ANCESTOR_CACHE_NOT_ENABLED')
        save(out/'RUNTIME_CACHE_AUDIT.json',{
            'enabled':cache.enabled,'source_root':str(ROOT),
            'cache_module':inspect.getfile(type(cache)),
            'cache_sha256':sha(Path(inspect.getfile(type(cache)))),
            'binding_module':binding_module.__file__,
            'binding_sha256':sha(Path(binding_module.__file__)),
            'current_root_full_validation':True,'ancestor_only_proof_reuse':True,
            'ordinary_update_Astra_calls_required':0,
            'source_manifest_sha256':sha(out/'SOURCE_SHA256.json'),
            'cold_proofs_initial_count':len(cache.proofs)})
        timing_stack=[]
        def timed(obj,name,label):
            original=getattr(obj,name)
            @functools.wraps(original)
            def call(*args,**kwargs):
                category=label
                if name=='validate_geometry_update':
                    current=kwargs.get('require_current',args[2] if len(args)>2 else True)
                    world=args[1]
                    category=('current_world_validation' if current else
                        ('historical_warm_validation' if world['world_id'] in cache.proofs else 'historical_cold_validation'))
                if name=='remember':
                    category='cold_proof_record' if args[0]['world_id'] not in cache.proofs else 'proof_refresh'
                entry={'category':category,'start':time.monotonic(),'children_s':0.,'depth':len(timing_stack)}
                timing_stack.append(entry)
                before_calls=(owner.research.broker.calls if full else 0) if name=='update' else None
                before_metrics=dict(cache.metrics) if name=='update' else None
                success=False
                try:
                    value=original(*args,**kwargs);success=True;return value
                finally:
                    end=time.monotonic();timing_stack.pop();wall=end-entry['start']
                    if timing_stack:timing_stack[-1]['children_s']+=wall
                    record={**entry,'end':end,'wall_s':wall,'self_s':wall-entry['children_s'],'ok':success}
                    if name=='update':
                        after_calls=owner.research.broker.calls if full else 0
                        record.update(Astra_submissions=after_calls-before_calls,
                            cache_metrics_delta={k:cache.metrics[k]-before_metrics[k] for k in cache.metrics})
                        if after_calls!=before_calls:raise RuntimeError('ORDINARY_UPDATE_DISPATCHED_MODEL')
                    with (out/'HOST_TIMING.jsonl').open('a') as stream:stream.write(json.dumps(record)+'\n')
            setattr(obj,name,call)
        timed(binding_module,'validate_geometry_update','world_validation')
        timed(binding_module,'validate_persistent_world','semantic_source_validation')
        timed(cache,'hit','history_proof_guard')
        timed(cache,'remember','proof_record')
        timed(sensor_store,'get_world','world_clone')
        timed(sensor_store,'image','RGB_read_verify')
        timed(sensor_store,'depth','Depth_read_verify_decode')
        timed(sensor_store,'publish_world','world_publish')
        timed(binding_module,'register_geometry_update','update_receipt')
        timed(owner,'execute','Owner_execute')
        timed(owner,'observe','current_observation')
        if full:
            timed(ad.world,'update','WH_Update_API')
            timed(rgbd_world,'update_geometry_first','current_estimation')
            timed(ad.broker,'validate_world_source','Broker_source_validation')
        for _ in range(120):owner.idle()
        if full:
            ad.world.public_plane={'normal':[0,0,1],'offset':0,'height_uncertainty_m':.002,'source':'declared public table plane; no actor data'}
            # Bind public tabletop identity before contact merges target/robot.
            stage='PREGRASP_RGBD_BUILD';o=capture();initial_q=pose(o)[3:]
            cfg=json.loads((ROOT/'config/research/geometry_first_v2.json').read_text())
            w=ad.world.build_geometry_first(o['observation_id'],cfg);keep(w,'geometry')
            req=grounding_request(w,o,TASK_TEXT);erow=model(req,'E');stage='SEMANTIC_BIND'
            eid=seal_semantic(out,ad.broker,erow,req,ad.store,w)
            w=ad.world.bind_semantic_grounding(w['world_id'],eid,TASK);keep(w,'semantic')
            target=w['state']['task_target_geometry_id']
            if target is None or w['state']['entities'][target]['status']!='coarse':raise RuntimeError('SEMANTIC_TARGET_NOT_CURRENT_COARSE')
            if w['state']['entities'][target]['semantic_disposition']!='object':raise RuntimeError('TASK_TARGET_NOT_OBJECT')
            stage='PREGRASP_CURRENT_RECHECK'
            w,o,pre_check=current_recheck(w,o,pose(o),'pregrasp_identity_and_destination')
            if not pre_check['valid']:raise RuntimeError('PREGRASP_CURRENT_TARGET_UNSUPPORTED')
            if w['state']['pnp_destination']['status']!='current_region':raise RuntimeError('DESTINATION_UNKNOWN:'+w['state']['pnp_destination']['reason'])
            # Existing initialization/control unchanged. Each actual action updates
            # this same World; the true CLOSE event reaches local reassociation then.
            o=initialize_held(o);policy_start_step=owner.b.steps
            stage='INITIAL_CURRENT_RECHECK'
            w,o,initial_check=current_recheck(w,o,pose(o),'held_current')
            if o['state']['sim_step']<policy_start_step:raise RuntimeError('PREHELD_WORLD_INPUT')
            if not initial_check['valid']:raise RuntimeError('INITIAL_CURRENT_TARGET_UNSUPPORTED')
            if w['state']['pnp_destination']['status']!='current_region':raise RuntimeError('DESTINATION_UNKNOWN:'+w['state']['pnp_destination']['reason'])
            stage='HELD_CURRENT_WORLD_READY'
        else:
            o=initialize_held(capture());policy_start_step=owner.b.steps
            o=capture();initial_q=pose(o)[3:]
        # Start the strategy history AFTER engineering initialization. No private setup answers.
        own_history=[history_entry(o,[],{'kind':'SUBTASK_START_AFTER_ENGINEERING_INITIALIZATION','ok':True})]
        save(out/'OWN_SUBTASK_START.json',own_history[0])
        for chunk in range(1,100001):
            if time.monotonic()>=owner.deadline:raise TimeoutError('COMMON_WALL_BUDGET')
            if not full:
                idx=sum(c['kind']=='A' for c in calls)+1
                with (out/('REQUEST_CLAIM_A'+str(idx)+'.json')).open('x') as f:json.dump({'kind':'A','index':idx,'authorization_id':auth['id'],'no_retry':True},f)
                t=time.monotonic();calls.append({'kind':'A','index':idx,'status':'SUBMITTING','trigger':'VANILLA_MODEL_SELECTED_NEXT_CHUNK_OR_OBSERVATION','started_monotonic':t});save(out/'CALLS.json',calls)
                save(out/'OWN_SUBTASK_HISTORY.json',own_history)
                try:vr=run_vanilla(owner,sensor_store,o,out/'vanilla_model',idx,own_history,owner.deadline)
                except BaseException as exc:
                    calls[-1].update(status='FAILED',error=repr(exc),wall_s=time.monotonic()-t);save(out/'CALLS.json',calls);raise
                calls[-1].update(status='READY',wall_s=time.monotonic()-t,usage=vr['usage'],request_id=vr['source']['request_id']);save(out/'CALLS.json',calls)
                ar=vr['parsed']['result']
                if ar['decision']=='finished':result.update(status='MODEL_FINISHED',stop_reason=ar['reason']);break
                if ar['decision']!='planned':
                    o=capture();no_progress+=1
                    recoveries.append({'decision':ar['decision'],'reason':ar['reason'],'observation_id':o['observation_id'],'source':'VANILLA_SELF_REQUESTED_OBSERVATION'});save(out/'RECOVERIES.json',recoveries)
                    own_history.append(history_entry(o,[],{'ok':True},ar))
                    if no_progress>=3:result.update(status='STOP_PERSISTENT_NO_PROGRESS',stop_reason=ar['reason']);break
                    continue
                no_progress=0
                if ar['phase'] in ('approach','grasp') or any(a['type']=='gripper' and a['opening']<.5 for a in vr['actions']):raise RuntimeError('TRANSPORT_TASK_FORBIDS_NEW_GRASP')
                # No WH association/suffix decisions in vanilla. Owner measures
                # fresh RGB/FK and enforces the original dependencies per action.
                for index,action in enumerate(vr['actions'],1):
                    if attempted>=80:raise RuntimeError('COMMON_ACTION_RUNAWAY_CAP')
                    owner.admit();attempted+=1;t=time.monotonic()
                    row={'chunk':chunk,'index':index,'phase':ar['phase'],'mode':ar['mode'],'model_original_action':clone(action),'executed_action':clone(action),'action_source':'MODEL_RAW','model_request_id':vr['source']['request_id'],'source':vr['source'],'actual_start':pose(o),'status':'SUBMITTING','submitted_monotonic':t,'waiting_model_s':calls[-1]['wall_s']};rows.append(row);save(out/'TRAJECTORY.json',rows)
                    owner.execution_origin=clone(vr['source'])
                    try:fb=owner.execute([clone(action)],o['observation_id'])
                    finally:owner.execution_origin=None
                    K+=sum(a['completed'] is True for a in fb['actions']);row.update(feedback=fb,K_total=K,owner_wall_s=time.monotonic()-t,actual_reached=[*fb['actual_state']['actual_grasp_center_world'],*fb['actual_state']['flange_pose_world'][3:]])
                    save(out/'TRAJECTORY.json',rows)
                    if not fb['ok']:raise RuntimeError('OWNER_CONTROL_FAILED:'+str(fb))
                    o=capture();row.update(status='COMPLETED',post_observation_id=o['observation_id'],update_wall_s=0.,WH_after=None);own_history.append(history_entry(o,[action],fb,ar));save(out/'TRAJECTORY.json',rows)
                    if action['type']=='gripper':break
                continue
            save(out/('MODEL_WORLD_QUERY_'+str(chunk)+'.json'),__import__('platform_v1.research.model_context',fromlist=['role_world_view']).role_world_view(ad.store,w['world_id'],pnp_proposal.ROLE))
            arow=model(pnp_proposal.request(w,o),'A');stage='ACTION_CONTRACT'
            if arow['role']!=pnp_proposal.ROLE or arow['provenance']!='MODEL_RAW':raise RuntimeError('NOT_NORMAL_REAL_PNP_ACTION')
            ar=arow['parsed']['result'];d=arow['pnp_candidate']
            if digest(ar)!=d['proposal_sha256'] or digest(d['actions'])!=d['actions_sha256']:raise RuntimeError('PROPOSAL_DERIVATION_HASH')
            if ar['decision']!='planned':
                if d.get('recovery_only'):
                    stage='NO_ACTION_RECOVERY'
                    previous_support=w['state']['pnp_interaction']['current_support']
                    w,o,recovery_check=current_recheck(w,o,pose(o),'recovery_after_A_'+str(chunk))
                    route=no_action_recovery_route(ar,d,previous_support,recovery_check['valid'])
                    recoveries.append({'chunk':chunk,'boundary':'MODEL_NO_ACTION','raw_decision':ar['decision'],
                        'raw_reason':ar['reason'],'owner_submissions':0,'grants_execution':False,'route':route,
                        'canceled_actions':0,'current_observation_id':o['observation_id'],'new_support':recovery_check['supported']})
                    save(out/'RECOVERIES.json',recoveries)
                    no_progress+=1
                    own_history.append(history_entry(o,[],{'ok':True},ar))
                    if no_progress<3:continue
                result.update(status='MODEL_'+ar['decision'].upper(),stop_reason=ar['reason']);break
            no_progress=0
            stage='PRE_FIRST_CURRENT_RECHECK'
            w,o,first_check=current_recheck(w,o,pose(o),'before_chunk_'+str(chunk))
            if not first_check['valid']:
                recoveries.append({'chunk':chunk,'boundary':'PRE_FIRST','reason':'CURRENT_IDENTITY_OR_GEOMETRY_OR_JOIN_UNSUPPORTED','canceled_actions':len(d['actions']),'next':'NEW_REQUEST_CURRENT_OBSERVATION_NO_EXECUTION'});save(out/'RECOVERIES.json',recoveries)
                continue
            if ar['phase'] in ('approach','grasp') or any(a['type']=='gripper' and a['opening']<.5 for a in d['actions']):
                raise RuntimeError('TRANSPORT_TASK_FORBIDS_NEW_GRASP')
            local_skill=any(a['type']=='gripper' and a['opening']<.5 for a in d['actions'])
            actions=skill_actions(w,o,ar) if local_skill else clone(d['actions'])
            if local_skill:save(out/('SKILL_EXPANSION_'+str(chunk)+'.json'),{'contract':'calibrated_grasp_request.v1','model_original_request':ar,'source_world_id':w['world_id'],'source_observation_id':o['observation_id'],'actions':actions,'source':'ENGINEERING_LOCAL_SKILL_CURRENT_RGBD_PUBLIC_PLANE','policy_grasp_credit':False})
            for index,action in enumerate(actions,1):
                stage='OWNER_ADMISSION';owner.admit()
                if attempted>=80:raise RuntimeError('COMMON_ACTION_RUNAWAY_CAP')
                if ad.store.current_world_id!=w['world_id'] or w['binding']['execution_epoch']!=owner.epoch:raise RuntimeError('STALE_CURRENT_WORLD')
                inter=w['state']['pnp_interaction']
                if action['type']=='move_pose' and inter['gripper_event']=='close' and not (inter['carrying_seen'] or
                        (policy_start_step is not None and inter['current_support'] and
                         inter['current_visual_vs_carry_prediction_residual_m'] is not None and
                         inter['current_visual_vs_carry_prediction_residual_m']<=.03)):
                    dx=[action['pose'][i]-pose(o)[i] for i in range(3)]
                    if dx[2]<=0 or math.hypot(*dx[:2])>.01:
                        raise RuntimeError('TRIAL_LIFT_EVIDENCE_REQUIRED_BEFORE_TRANSPORT')
                t=time.monotonic();before_pose=pose(o)
                rows.append({'chunk':chunk,'index':index,'phase':ar['phase'],'mode':ar['mode'],'model_original_action':None if local_skill else clone(action),'executed_action':clone(action),'action_source':'ENGINEERING_LOCAL_SKILL' if local_skill else 'MODEL_RAW','model_original_skill_request':clone(ar['fine_actions']) if local_skill else None,
                    'model_request_id':arow['request_id'],'source':d['source'],'WH_before':brief(w).get(target),
                    'interaction_before':clone(w['state']['pnp_interaction']),'actual_start':before_pose,
                    'waiting_model_s':calls[-1]['wall_s'],'submitted_monotonic':t,'status':'SUBMITTING'})
                save(out/'TRAJECTORY.json',rows);attempted+=1
                owner.execution_origin={**clone(d['source']),'waypoint_index':index,'H_max':4,'m':1,'phase':ar['phase'],'action_source':'ENGINEERING_LOCAL_SKILL' if local_skill else 'MODEL_RAW'}
                try:fb=owner.execute([clone(action)],o['observation_id'])
                finally:owner.execution_origin=None
                rows[-1].update(feedback=fb,owner_wall_s=time.monotonic()-t,actual_reached=[*fb['actual_state']['actual_grasp_center_world'],*fb['actual_state']['flange_pose_world'][3:]])
                K+=sum(x['completed'] is True for x in fb['actions']);rows[-1]['K_total']=K;save(out/'TRAJECTORY.json',rows)
                if not fb['ok']:raise RuntimeError('OWNER_CONTROL_FAILED:'+str(fb))
                stage='POST_ACTION_RGBD_UPDATE'
                expected=action['pose'] if action['type']=='move_pose' else before_pose
                w,o,check=current_recheck(w,o,expected,'after_'+str(K),fb)
                rows[-1].update(status='COMPLETED',update_wall_s=check['wall_s'],WH_after=brief(w).get(target),
                    interaction_after=check['pnp_interaction'],destination_after=check['pnp_destination'],
                    post_observation_id=o['observation_id'],suffix_supported=check['valid'])
                own_history.append(history_entry(o,[action],fb,ar))
                save(out/'TRAJECTORY.json',rows)
                if not check['valid']:
                    recoveries.append({'chunk':chunk,'boundary':'POST_ACTION','after_K':K,'reason':'CURRENT_IDENTITY_GEOMETRY_OR_CARRY_EVIDENCE_UNSUPPORTED','canceled_actions':len(actions)-index,'next':'NEW_REQUEST_CURRENT_OBSERVATION_NO_EXECUTION'});save(out/'RECOVERIES.json',recoveries);break
                # No pre-boundary future state survives a real gripper event.
                if action['type']=='gripper':break
            if result['status']!='INCOMPLETE':break
        if result['status']=='INCOMPLETE':result.update(status='STOP_ACTION_BUDGET',stop_reason='Common resource boundary ended without finished verdict')
        if full:
            result['online_interaction']=clone(w['state'].get('pnp_interaction'))
            result['online_destination']=clone(w['state'].get('pnp_destination'))
            inter=w['state']['pnp_interaction'];goal=w['state']['pnp_destination'];xyz=inter['current_xyz_m']
            inside=(xyz is not None and goal['status']=='current_region' and all(goal['bounds_world_m'][0][i]<=xyz[i]<=goal['bounds_world_m'][1][i] for i in (0,1)))
            bounds=w['state']['entities'].get(target,{}).get('bounds_world_m')
            clearance=None
            if bounds:
                import numpy as np
                pads=np.asarray(o['state']['actual_pad_centers_world']);lo,hi=np.asarray(bounds)
                clearance=float(np.linalg.norm(np.maximum(np.maximum(lo-pads,pads-hi),0),axis=1).min())
            online_ready=(policy_start_step is not None and inter['released_stable_observed'] and inside and o['state']['actual_pad_gap_m']>.07
                and pose(o)[2]>=.08 and clearance is not None and clearance>=.03)
            result['online_completion']={'status':'VISUAL_HYPOTHESIS_COMPLETE' if online_ready else 'NOT_ESTABLISHED','inside_observed_region':inside,'pad_to_current_bounds_clearance_m':clearance,'GT_used':False}

    except BaseException as exc:
        result.update(status='FAIL_STOP',stop_stage=stage,stop_reason=repr(exc));save(out/'EXCEPTION.json',{'error':repr(exc),'traceback':traceback.format_exc()})
        if rows and rows[-1]['status']=='SUBMITTING':rows[-1].update(status='REJECTED_OR_UNKNOWN',error=repr(exc));save(out/'TRAJECTORY.json',rows)
        print(traceback.format_exc(),flush=True)
        if owner:
            try:owner.stop()
            except BaseException:pass
    finally:
        result.update(policy_start_step=policy_start_step,K_engineering_initialization=init_K,K_Astra_policy=K-init_K,initialization_submissions=init_attempted)
        save(out/'OWN_SUBTASK_HISTORY.json',own_history)
        result['model_finished']=result['status']=='MODEL_FINISHED'
        result['physical_success']=None  # independent scorer runs only after this online seal
        save(out/'ONLINE_RESULT_SEALED.json',{**result,'K':K,'E':sum(c['kind']=='E' for c in calls),'A':sum(c['kind']=='A' for c in calls)})
        save(out/'ONLINE_SEAL.json',{str(p.relative_to(out)):sha(p) for folder in ('observations','worlds','semantic_sealed') for p in (out/folder).rglob('*') if p.is_file()} | {'ONLINE_RESULT_SEALED.json':sha(out/'ONLINE_RESULT_SEALED.json')})
        if owner:
            try:
                # Original private evaluator; ended policy cannot consume its output.
                owner.ended=True
                score=owner.b.finish('done' if result['status']=='MODEL_FINISHED' else 'not_done')
                if policy_start_step is not None:
                    import numpy as np
                    trace=[x for x in owner.b.adapter.score_trace if x['step']>=policy_start_step]
                    if trace:
                        xy=np.array([x['object_pose'][:2] for x in trace])
                        score['transport_from_held']={'source':'INDEPENDENT_PRIVATE_TRACE_AFTER_ONLINE_SEAL',
                            'policy_grasp_credit':False,'policy_start_step':policy_start_step,
                            'net_xy_displacement_m':float(np.linalg.norm(xy[-1]-xy[0])),
                            'max_xy_excursion_m':float(np.linalg.norm(xy-xy[0],axis=1).max()),
                            'sampled_xy_path_length_m':float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum()),
                            'path_length_includes_simulation_jitter':True}
                score['policy_grasp_credit']=False
                save(out/'INDEPENDENT_SCORE.json',score)
                result['physical_success']=score['physical_success']
                result['independent_legacy_status']=score['status']
                result['transport_place_result']='PASS' if score['physical_success'] else 'FAIL'
                save(out/'ENDPOINTS.json',completion_endpoints(result['status'],score))
            except BaseException as scoring_exc:
                save(out/'SCORING_ERROR.json',{'error':repr(scoring_exc)});result['transport_place_result']='SCORING_FAILED'
        if sensor_store is not None and hasattr(sensor_store,'verification_cache'):
            save(out/'RUNTIME_CACHE_FINAL.json',{'enabled':sensor_store.verification_cache.enabled,
                'proofs':len(sensor_store.verification_cache.proofs),'metrics':sensor_store.verification_cache.metrics})
        if owner:
            result.update(episode_id=owner.id,Owner_accepted_chunks=owner.chunks,initialization_wall_s=owner.init_wall,final_physics_step=owner.b.steps)
            owner.close()
        signal.setitimer(signal.ITIMER_REAL,0)
        result.update(K=K,owner_submissions_attempted=attempted,E=sum(c['kind']=='E' for c in calls),A=sum(c['kind']=='A' for c in calls),
            recoveries=recoveries,total_wall_s=time.monotonic()-started,model_wait_s=sum(c['wall_s'] for c in calls),calls=calls,
            task_usable_not_modified=True,shadow_results_used=0,IK_collision_clearance='See actual Owner/backend records; unsubmitted paths NOT_TESTED')
        save(out/'RESULT.json',result);save(out/'TRAJECTORY.json',rows)
        save(out/'FINAL_SEAL.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name not in ('FINAL_SEAL.json','RUN.log')})
        print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();main(a.out)
