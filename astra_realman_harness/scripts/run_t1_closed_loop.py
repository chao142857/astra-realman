"""Single authorized T1 episode. Existing Broker/WorldHead/Owner only; no retries."""
import argparse,ast,hashlib,json,math,shutil,signal,sys,time,traceback,uuid
from pathlib import Path
from platform_v1.owner import Owner
from platform_v1.research.rgbd_sensor import RGBDObservationBackend
from platform_v1.research.contracts import digest,clone
from platform_v1.research import action_proposal,chunk_plan,losses,t1_proposal
from platform_v1.research.review_contracts import grounding_request
from platform_v1.research.semantic_binding import import_grounding_archive
from sim_skills.full_pnp.infer_process import InferConfig
from scripts.structured_outputs import check_provider

ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parents[1]
TASK={'id':'RUN_T1_SINGLE_RED_PRECONTACT','revision':'1','stage':'T1_PREGRASP_APPROACH'}
TASK_TEXT='Approach the red cuboid in the current scene to a noncontact ready pose above it, without grasp, contact or gripper actions. Identify the actual red task object, not the robot, camera, table or planar green region.'
PROTOCOL={'scope':'RUN_T1_CLOSED_LOOP','new_episodes':1,'semantic_max':1,'action_max':2,'owner_single_action_max':8,'m':1,'H_max':4,'request_timeout_s':90,'wall_s':600,'seed':2,'settle_steps':120,
    'completion':{'xy_to_current_observed_bounds_midpoint_m':.020,'above_current_observed_top_z_m':[.060,.100],'orientation_from_initial_rad_max':.05,'requires_fresh_post_action_update':True,'interpretation':'ESTIMATOR_DEFINED_T1_READINESS_NOT_GRASP_SUCCESS'},
    'suffix_checks':{'join_position_max_m':.01,'join_rotation_max_rad':.05,'target_surface_displacement_max_m':.03,'association':'unique_current_match','target_status':'coarse','visibility':'at_least_one_current_view'},
    'application_retry':0,'HTTP_SSE_retry':0,'unbounded_retry':False,'fallback':0,'hardware':0,'training':0,'native_concurrency':0,'new_models':'none; existing RGBD estimator only','scene':'original FullTaskBackend simple single-red task; no layout changes'}
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pose(o):return [*o['state']['actual_grasp_center_world'],*o['state']['flange_pose_world'][3:]]
def brief(w):
    return {i:{k:e.get(k) for k in ('point_world_m','bounds_world_m','coarse_observed_bounds_world_m','status','semantic_category','semantic_status','visibility','temporal_association','geometry_residual','reason')} for i,e in w['state']['entities'].items()}
def complete(w,o,initial_q):
    target=w['state'].get('task_target_geometry_id');e=w['state']['entities'].get(target,{})
    bounds=e.get('bounds_world_m') or e.get('coarse_observed_bounds_world_m')
    if e.get('status')!='coarse' or not bounds:return {'ready':False,'reason':'TARGET_UNKNOWN'}
    xy=math.dist(pose(o)[:2],[(a+b)/2 for a,b in zip(*bounds)][:2]);dz=pose(o)[2]-bounds[1][2]
    rot=chunk_plan.pose_error([0,0,0,*initial_q],[0,0,0,*pose(o)[3:]])[1]
    return {'ready':xy<=.02 and .06<=dz<=.10 and rot<=.05,'xy_error_m':xy,'height_above_observed_top_m':dz,'orientation_error_rad':rot,'target':target}
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

def main(out):
    if json.loads((out/'PROTOCOL.json').read_text())!=PROTOCOL:raise ValueError('PROTOCOL_CHANGED')
    expected=json.loads((out/'SOURCE_SHA256.json').read_text())
    for p,h in expected.items():
        if sha(ROOT/p)!=h:raise ValueError('SOURCE_CHANGED:'+p)
    auth=json.loads((out/'AUTHORIZATION.json').read_text())
    if not auth['granted'] or auth['scope']!=PROTOCOL['scope']:raise ValueError('AUTHORIZATION')
    launcher=Path(auth['launcher'])
    if sha(launcher)!=auth['launcher_sha256'] or sha(launcher.parent.parent/'libexec/codex')!=auth['binary_sha256']:raise ValueError('LAUNCHER_CHANGED')
    settings=next(ast.literal_eval(n.value) for n in ast.parse(launcher.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='settings' for t in n.targets))
    if any(settings[k]!='0' for k in ('model_providers.s1_openai_no_retry.request_max_retries','model_providers.s1_openai_no_retry.stream_max_retries')) or settings['features.unbounded_connection_retries']!='false':raise ValueError('RETRIES_ENABLED')
    with (out/'EPISODE_CLAIM.json').open('x') as f:json.dump({'authorization_id':auth['id'],'consumed_unix':time.time(),'no_retry':True},f)
    started=time.monotonic();owner=None;rows=[];calls=[];worlds=[];rechecks=[];K=0;attempted=0;stage='INITIALIZE';initial_q=None
    result={'status':'INCOMPLETE','T1_result':'NOT_COMPLETED','new_SAPIEN_episode_attempts':1,'K':0,'E':0,'A':0,'hardware':0,'training':0,'native_concurrency':0}
    def timeout(*_):raise TimeoutError('TOTAL_EPISODE_WALL_DEADLINE')
    signal.signal(signal.SIGTERM,timeout);signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,585)
    def capture():
        o=owner.observe();save(out/'observations'/(o['observation_id'].replace(':','_')+'.json'),o);return o
    def keep(w,label):
        save(out/'worlds'/(str(w['world_revision'])+'_'+label+'.json'),w);worlds.append({'world_id':w['world_id'],'revision':w['world_revision'],'entities':brief(w),'label':label})
        save(out/'WORLD_TRACE.json',worlds)
    def current_recheck(world, observation, expected_pose, label, feedback=None):
        # Both model-latency refresh and post-action suffix use this exact path.
        # No-action receipt records only a host sensing boundary, never an Owner completion.
        begin=time.monotonic()
        if feedback is None:
            boundary=time.monotonic()
            feedback={'kind':'OBSERVATION_ONLY_NO_ACTION','ok':True,'actions':[],
                'owner_submissions':0,'completed_monotonic':boundary,
                'source_observation_id':observation['observation_id'],
                'execution_epoch':owner.epoch,'ok_scope':'HOST_SENSING_BOUNDARY_NOT_CONTROL_SUCCESS'}
        current=capture()
        measured=ad.world.update(world['world_id'],current['observation_id'],
            feedback['completed_monotonic'],execution_feedback=feedback)
        keep(measured,label)
        entity=measured['state']['entities'].get(target,{})
        shift=(entity.get('geometry_residual') or {}).get('surface_median_displacement_m')
        supported=(entity.get('status')=='coarse' and entity.get('semantic_status')=='hypothesis'
            and entity.get('temporal_association',{}).get('status')=='unique_current_match'
            and bool(entity.get('current_evidence')))
        distance,rotation=chunk_plan.pose_error(expected_pose,pose(current))
        valid=(feedback['ok'] and supported and shift is not None and shift<=.03
            and distance<.01 and rotation<.05)
        check={'label':label,'previous_world_id':world['world_id'],'current_world_id':measured['world_id'],
            'observation_id':current['observation_id'],'feedback_kind':feedback.get('kind','ACTUAL_OWNER_COMPLETION'),
            'supported':supported,'valid':valid,'target':target,'target_current':brief(measured).get(target),
            'target_surface_displacement_m':shift,'join_position_m':distance,'join_rotation_rad':rotation,
            'association':measured['state']['temporal_association'],
            'current_evidence':entity.get('current_evidence',[]),'wall_s':time.monotonic()-begin}
        rechecks.append(check);save(out/'CURRENT_RECHECKS.json',rechecks)
        return measured,current,check
    def model(req,kind):
        nonlocal stage
        stage=kind+'_REQUEST';idx=sum(c['kind']==kind for c in calls)+1
        if idx>(1 if kind=='E' else 2):raise ValueError('MODEL_BUDGET')
        save(out/('request_'+kind+str(idx)+'.json'),req)
        with (out/('REQUEST_CLAIM_'+kind+str(idx)+'.json')).open('x') as f:json.dump({'kind':kind,'index':idx,'authorization_id':auth['id'],'request_sha256':digest(req),'retry':False},f)
        t=time.monotonic();calls.append({'kind':kind,'index':idx,'started_monotonic':t,'status':'SUBMITTING'});save(out/'CALLS.json',calls)
        b=owner.research.broker
        try:
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
        owner=Owner(assets,run,seed=2,budget_s=max(1,580-(time.monotonic()-started)),source='RUN_T1_CLOSED_LOOP',infer_config=InferConfig(str(launcher),fixture=False),max_requests=3,backend_factory=RGBDObservationBackend)
        owner.deadline=min(owner.deadline,started+580);owner.enable_research_adapters();ad=owner.research
        ad.broker.t1_episode_authorization=owner.id
        ad.world.public_plane={'normal':[0,0,1],'offset':0,'height_uncertainty_m':.002,'source':'declared public table plane; no actor data'}
        for _ in range(120):owner.idle()
        stage='INITIAL_RGBD_BUILD';o=capture();initial_q=pose(o)[3:]
        cfg=json.loads((ROOT/'config/research/geometry_first_v2.json').read_text())
        w=ad.world.build_geometry_first(o['observation_id'],cfg);keep(w,'geometry')
        req=grounding_request(w,o,TASK_TEXT);erow=model(req,'E');stage='SEMANTIC_BIND'
        eid=seal_semantic(out,ad.broker,erow,req,ad.store,w)
        w=ad.world.bind_semantic_grounding(w['world_id'],eid,TASK);keep(w,'semantic')
        target=w['state']['task_target_geometry_id']
        if target is None or w['state']['entities'][target]['status']!='coarse':raise RuntimeError('SEMANTIC_TARGET_NOT_CURRENT_COARSE')
        if w['state']['entities'][target]['semantic_disposition']!='object':raise RuntimeError('TASK_TARGET_NOT_OBJECT')
        for chunk in range(1,3):
            if complete(w,o,initial_q)['ready']:
                result.update(status='COMPLETED',T1_result='ESTIMATOR_READY_BEFORE_NEXT_CHUNK');break
            arow=model(t1_proposal.request(w,o),'A');stage='ACTION_CONTRACT'
            if arow['role']!=t1_proposal.ROLE or arow['provenance']!='MODEL_RAW':raise RuntimeError('NOT_NORMAL_REAL_T1_ACTION')
            ar=arow['parsed']['result']
            if ar['decision']!='planned':
                result.update(status='STOP_MODEL_'+ar['decision'].upper(),stop_reason=ar['reason']);break
            d=arow['t1_candidate'];p=d['plan']
            if digest(ar)!=d['proposal_sha256'] or digest(p)!=d['internal_plan_sha256']:raise RuntimeError('PROPOSAL_DERIVATION_HASH')
            reference=w;prediction=losses.forecast(p,w['state'])
            stage='PRE_FIRST_CURRENT_RECHECK'
            w,o,first_check=current_recheck(w,o,p['origin_pose_world'],'before_chunk_'+str(chunk))
            if not first_check['valid']:
                result.update(status='STOP_CURRENT_RECHECK_INVALID',stop_reason='CURRENT_ASSOCIATION_OR_GEOMETRY_OR_JOIN_NOT_SUPPORTED');break
            if complete(w,o,initial_q)['ready']:
                result.update(status='COMPLETED',T1_result='ESTIMATOR_READY_CURRENT_RECHECK');break
            for waypoint in p['waypoints']:
                stage='OWNER_ADMISSION';owner.admit()
                if attempted>=8:raise RuntimeError('EIGHT_SUBMISSION_CAP')
                if ad.store.current_world_id!=w['world_id'] or ad.store.revision!=w['world_revision'] or w['binding']['execution_epoch']!=owner.epoch:raise RuntimeError('STALE_CURRENT_WORLD')
                expected=p['origin_pose_world'] if waypoint['index']==1 else p['waypoints'][waypoint['index']-2]['pose']
                actual=pose(o);dist,rot=chunk_plan.pose_error(expected,actual)
                if dist>=.01 or rot>=.05:raise RuntimeError('MEASURED_JOIN_MISMATCH')
                e=w['state']['entities'].get(target,{})
                if e.get('status')!='coarse' or e.get('semantic_status')!='hypothesis':raise RuntimeError('CURRENT_TARGET_UNKNOWN')
                action={'type':'move_pose','pose':clone(waypoint['pose'])};t=time.monotonic()
                rows.append({'chunk':chunk,'index':waypoint['index'],'model_original_waypoint':clone(waypoint),'model_request_id':arow['request_id'],
                    'source':d['source'],'WH_before':brief(w).get(target),'actual_start':actual,'waiting_model_s':calls[-1]['wall_s'],'submitted_monotonic':t,'status':'SUBMITTING'})
                save(out/'TRAJECTORY.json',rows);attempted+=1
                owner.execution_origin={'kind':'MODEL_RAW','role':t1_proposal.ROLE,'request_id':arow['request_id'],'raw_sha256':d['source']['raw_sha256'],
                    'original_world_id':p['world_id'],'original_world_revision':p['world_revision'],'original_epoch':p['execution_epoch'],'waypoint_index':waypoint['index'],'H':4,'m':1}
                try:fb=owner.execute([action],o['observation_id'])
                finally:owner.execution_origin=None
                rows[-1].update(feedback=fb,owner_wall_s=time.monotonic()-t,actual_reached=[*fb['actual_state']['actual_grasp_center_world'],*fb['actual_state']['flange_pose_world'][3:]])
                K+=sum(x['completed'] is True for x in fb['actions']);rows[-1]['K_total']=K;save(out/'TRAJECTORY.json',rows)
                if not fb['ok']:raise RuntimeError('OWNER_CONTROL_FAILED:'+str(fb))
                stage='POST_ACTION_RGBD_UPDATE'
                w,o,check=current_recheck(w,o,waypoint['pose'],'after_'+str(K),fb)
                rows[-1].update(update_wall_s=check['wall_s'],WH_after=brief(w).get(target),post_observation_id=o['observation_id'])
                stage='SUFFIX_CHECK'
                residual=losses.compare(prediction['after_waypoint'][waypoint['index']-1],w['state'],fb['completed_monotonic'])
                shift=check['target_surface_displacement_m'];supported=check['supported'];safe_suffix=check['valid']
                readiness=complete(w,o,initial_q)
                rows[-1].update(status='COMPLETED',residual=residual,target_surface_displacement_m=shift,suffix_supported=safe_suffix,T1_check=readiness)
                save(out/'TRAJECTORY.json',rows)
                if readiness['ready'] and supported:
                    result.update(status='COMPLETED',T1_result='ESTIMATOR_READY_POST_ACTION');break
                if not safe_suffix:
                    result.update(status='STOP_SUFFIX_INVALID',stop_reason='CURRENT_ASSOCIATION_OR_GEOMETRY_OR_JOIN_NOT_SUPPORTED');break
            if result['status']!='INCOMPLETE':break
        if result['status']=='INCOMPLETE':result.update(status='STOP_ACTION_BUDGET',stop_reason='Two normal chunks completed without meeting fixed T1 criterion')
    except BaseException as exc:
        result.update(status='FAIL_STOP',stop_stage=stage,stop_reason=repr(exc));save(out/'EXCEPTION.json',{'error':repr(exc),'traceback':traceback.format_exc()})
        if rows and rows[-1]['status']=='SUBMITTING':rows[-1].update(status='REJECTED_OR_UNKNOWN',error=repr(exc));save(out/'TRAJECTORY.json',rows)
        print(traceback.format_exc(),flush=True)
        if owner:
            try:owner.stop()
            except BaseException:pass
    finally:
        if owner:
            result.update(episode_id=owner.id,Owner_accepted_chunks=owner.chunks,initialization_wall_s=owner.init_wall,final_physics_step=owner.b.steps)
            owner.close()
        signal.setitimer(signal.ITIMER_REAL,0)
        result.update(K=K,owner_submissions_attempted=attempted,E=sum(c['kind']=='E' for c in calls),A=sum(c['kind']=='A' for c in calls),
            total_wall_s=time.monotonic()-started,model_wait_s=sum(c['wall_s'] for c in calls),calls=calls,
            task_usable_not_modified=True,shadow_results_used=0,IK_collision_clearance='See actual Owner/backend records; unsubmitted paths NOT_TESTED')
        save(out/'RESULT.json',result);save(out/'TRAJECTORY.json',rows)
        save(out/'FINAL_SEAL.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name not in ('FINAL_SEAL.json','RUN.log')})
        print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();main(a.out)
