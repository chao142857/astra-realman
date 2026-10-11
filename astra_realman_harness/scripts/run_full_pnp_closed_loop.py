"""Single authorized T1 episode. Existing Broker/WorldHead/Owner only; no retries."""
import argparse,ast,hashlib,json,math,shutil,signal,sys,time,traceback,uuid
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
TASK={'id':'RUN_FULL_PNP_SINGLE_RED_TO_OBSERVED_GREEN','revision':'1','stage':'T1_PREGRASP_APPROACH'}
TASK_TEXT=('Pick the red cuboid, carry it to the observed green placement region, release stably and retreat with open empty gripper. '
 'Bind the actual red cuboid geometry ID; classify robot/table separately. For the green planar destination absent from geometry IDs, '
 'request new_planar_region with an actual image bbox and evidence refs. Do not invent region XYZ, object pose, contact or holding state.')
PROTOCOL={'scope':'RUN_FULL_PNP','new_episodes':1,'semantic_max':2,'action_max':8,'owner_single_action_max':40,'m':1,'H_max':4,
 'request_timeout_s':90,'wall_s':1200,'seed':2,'settle_steps':120,
 'completion':{'independent':'unchanged FullTaskBackend.finish plus assess_grasp: >=50mm actual lift, >=300 steps stable bilateral carry, no closed drop, existing region placement/stability and release/exit gates',
 'online':'separate RGBD/FK visual hypotheses; close not held; current release inside observed region, open gap>70mm, tool Z>=80mm, separation>=30mm, stable released evidence'},
 'recheck':{'join_position_max_m':.01,'join_rotation_max_rad':.05,'stationary_target_shift_max_m':.03,
 'carrying_visual_vs_FK_residual_max_m':.03,'close_alone_never_held':True,'gripper_barrier':'fresh observation then new Action request'},
 'application_retry':0,'HTTP_SSE_retry':0,'unbounded_retry':False,'fallback':0,'hardware':0,'training':0,'native_concurrency':0,
 'scene':'same original FullTaskBackend simple red/green scene, empty preparation; no layout changes',
 'unchanged_owner_caps':{'accepted_chunks':12,'observations':64},'expected_contact':'unchanged SharedGraspController and scene collision/contact handling'}
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
    result={'status':'INCOMPLETE','FULL_PNP_result':'NOT_COMPLETED','new_SAPIEN_episode_attempts':1,'K':0,'E':0,'A':0,'hardware':0,'training':0,'native_concurrency':0}
    def timeout(*_):raise TimeoutError('TOTAL_EPISODE_WALL_DEADLINE')
    signal.signal(signal.SIGTERM,timeout);signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,1180)
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
        return measured,current,check
    def model(req,kind):
        nonlocal stage
        stage=kind+'_REQUEST';idx=sum(c['kind']==kind for c in calls)+1
        if idx>(2 if kind=='E' else 8):raise ValueError('MODEL_BUDGET')
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
        owner=Owner(assets,run,seed=2,budget_s=max(1,1170-(time.monotonic()-started)),source='RUN_FULL_PNP',infer_config=InferConfig(str(launcher),fixture=False),max_requests=10,backend_factory=RGBDObservationBackend)
        owner.deadline=min(owner.deadline,started+1170);owner.enable_research_adapters();ad=owner.research
        ad.broker.pnp_episode_authorization=owner.id
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
        stage='INITIAL_CURRENT_RECHECK'
        w,o,initial_check=current_recheck(w,o,pose(o),'initial_current')
        if not initial_check['valid']:raise RuntimeError('INITIAL_CURRENT_TARGET_UNSUPPORTED')
        if w['state']['pnp_destination']['status']!='current_region':raise RuntimeError('DESTINATION_UNKNOWN:'+w['state']['pnp_destination']['reason'])
        for chunk in range(1,9):
            arow=model(pnp_proposal.request(w,o),'A');stage='ACTION_CONTRACT'
            if arow['role']!=pnp_proposal.ROLE or arow['provenance']!='MODEL_RAW':raise RuntimeError('NOT_NORMAL_REAL_PNP_ACTION')
            ar=arow['parsed']['result'];d=arow['pnp_candidate']
            if digest(ar)!=d['proposal_sha256'] or digest(d['actions'])!=d['actions_sha256']:raise RuntimeError('PROPOSAL_DERIVATION_HASH')
            if ar['decision']!='planned':
                result.update(status='MODEL_'+ar['decision'].upper(),stop_reason=ar['reason']);break
            stage='PRE_FIRST_CURRENT_RECHECK'
            w,o,first_check=current_recheck(w,o,pose(o),'before_chunk_'+str(chunk))
            if not first_check['valid']:
                result.update(status='STOP_CURRENT_RECHECK_INVALID',stop_reason='CURRENT_IDENTITY_OR_GEOMETRY_OR_JOIN_UNSUPPORTED');break
            for index,action in enumerate(d['actions'],1):
                stage='OWNER_ADMISSION';owner.admit()
                if attempted>=40:raise RuntimeError('FORTY_LOW_LEVEL_SUBMISSION_CAP')
                if ad.store.current_world_id!=w['world_id'] or w['binding']['execution_epoch']!=owner.epoch:raise RuntimeError('STALE_CURRENT_WORLD')
                inter=w['state']['pnp_interaction']
                if action['type']=='move_pose' and inter['gripper_event']=='close' and not inter['carrying_seen']:
                    dx=[action['pose'][i]-pose(o)[i] for i in range(3)]
                    if dx[2]<=0 or math.hypot(*dx[:2])>.01:
                        raise RuntimeError('TRIAL_LIFT_EVIDENCE_REQUIRED_BEFORE_TRANSPORT')
                t=time.monotonic();before_pose=pose(o)
                rows.append({'chunk':chunk,'index':index,'phase':ar['phase'],'mode':ar['mode'],'model_original_action':clone(action),
                    'model_request_id':arow['request_id'],'source':d['source'],'WH_before':brief(w).get(target),
                    'interaction_before':clone(w['state']['pnp_interaction']),'actual_start':before_pose,
                    'waiting_model_s':calls[-1]['wall_s'],'submitted_monotonic':t,'status':'SUBMITTING'})
                save(out/'TRAJECTORY.json',rows);attempted+=1
                owner.execution_origin={**clone(d['source']),'waypoint_index':index,'H_max':4,'m':1,'phase':ar['phase']}
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
                save(out/'TRAJECTORY.json',rows)
                if not check['valid']:
                    result.update(status='STOP_SUFFIX_INVALID',stop_reason='CURRENT_IDENTITY_GEOMETRY_OR_CARRY_EVIDENCE_UNSUPPORTED');break
                # No pre-boundary future state survives a real gripper event.
                if action['type']=='gripper':break
            if result['status']!='INCOMPLETE':break
        if result['status']=='INCOMPLETE':result.update(status='STOP_ACTION_BUDGET',stop_reason='Eight Action calls ended without a finished verdict')
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
        online_ready=(inter['carrying_seen'] and inter['released_stable_observed'] and inside and o['state']['actual_pad_gap_m']>.07
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
        save(out/'ONLINE_RESULT_SEALED.json',{**result,'K':K,'E':sum(c['kind']=='E' for c in calls),'A':sum(c['kind']=='A' for c in calls)})
        save(out/'ONLINE_SEAL.json',{str(p.relative_to(out)):sha(p) for folder in ('observations','worlds','semantic_sealed') for p in (out/folder).rglob('*') if p.is_file()} | {'ONLINE_RESULT_SEALED.json':sha(out/'ONLINE_RESULT_SEALED.json')})
        if owner:
            try:
                # Original private evaluator; ended policy cannot consume its output.
                owner.ended=True
                score=owner.b.finish('done' if result['status']=='MODEL_FINISHED' else 'not_done')
                save(out/'INDEPENDENT_SCORE.json',score)
                result['FULL_PNP_result']='PASS' if score['status']=='PASS' and score['grasp_execution_assessment']['stable_hold_seen'] else 'FAIL'
            except BaseException as scoring_exc:
                save(out/'SCORING_ERROR.json',{'error':repr(scoring_exc)});result['FULL_PNP_result']='SCORING_FAILED'
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
