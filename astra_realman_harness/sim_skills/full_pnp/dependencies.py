"""Common owner evidence predicates. RGB/calibration/proprioception only; no target generator."""
import math
import numpy as np
from sim_skills.full_pnp import rgb
from sim_skills.full_pnp.requirements import validate_requirements

REVISION='owner_dependencies_v1'
CONTRACT={
 'revision':REVISION,
 'namespace':'Automatic owner checks and action classifications, not names the model may declare in requirements; see model_requirements_contract.',
 'empty_evidence':'single-task-object RGB triangulation: >=2 camera rays, >=15deg baseline, positive depth, residual <=15mm; object/tool distance >90mm',
 'possible_payload':'same triangulation, object/tool distance <=60mm; proximity is not grasp truth',
 'unknown':'missing/ambiguous RGB, degenerate/inconsistent rays, or distance in (60,90]mm; no empty inference from gripper opening alone',
 'move_empty':'object_static; stationary target-object anchor may not move, goal may change during object approach',
 'move_possible_payload':'goal_static + object_near_tool + object/tool relative-vector change <=30mm; object may move with tool',
 'bounded_upward_withdrawal':'dz in (1,150]mm, xy <=10mm, rotation <=0.05rad; current triangulated object required; object/goal may move',
 'move_noop':'<=1mm and <=0.005rad; scene_healthy only',
 'opening':'<=0.005rad target-current is skipped no-op; clear empty permits pregrasp opening; possible payload requires goal_static/object_near_tool/object_at_goal; unknown holds',
 'closing':'object_static; recheck at actual gripper boundary',
 'model_requirements':'union with these owner minimums; cannot remove owner dependencies',
 'scope':'fixed single red task object; engineering RGB evidence, not GT, contact truth or general object identity'}


def angle(a,b):
    if not np.isfinite([*a,*b]).all() or np.linalg.norm(a)<1e-12 or np.linalg.norm(b)<1e-12:return math.inf
    return 2*math.acos(min(1.,abs(float(np.dot(a,b)))/(np.linalg.norm(a)*np.linalg.norm(b))))


def hand_evidence(features,cal,state):
    rays=[]
    for camera,f in features.items():
        o=f['object']
        if o['status']!='visible':continue
        k=np.asarray(cal[camera]['intrinsic']);u,v=o['centroid']
        ray=rgb.rotation(cal[camera])@np.array([1.,-(u-k[0,2])/k[0,0],-(v-k[1,2])/k[1,1]])
        rays.append((camera,np.asarray(cal[camera]['pose_world_xyz_wxyz'][:3]),ray/np.linalg.norm(ray)))
    out={'status':'unknown','method':'RGB_RAYS_NOT_GT','views':[x[0] for x in rays]}
    if len(rays)<2:return dict(out,reason='INSUFFICIENT_VIEWS')
    baseline=max(math.acos(min(1.,abs(float(a[2]@b[2])))) for a in rays for b in rays)
    if baseline<math.radians(15):return dict(out,reason='DEGENERATE_RAYS')
    projections=[np.eye(3)-np.outer(v,v) for _,_,v in rays]
    p=np.linalg.lstsq(sum(projections),sum(m@ray[1] for m,ray in zip(projections,rays)),rcond=None)[0]
    residual=max(float(np.linalg.norm(m@(p-ray[1]))) for m,ray in zip(projections,rays))
    if residual>.015 or any(float((p-origin)@direction)<=0 for _,origin,direction in rays):
        return dict(out,reason='INCONSISTENT_RGB_RAYS',residual_m=residual)
    relative=p-np.asarray(state['actual_grasp_center_world']);distance=float(np.linalg.norm(relative))
    return dict(out,status='empty' if distance>.09 else 'possible_payload' if distance<=.06 else 'unknown',
                relative_object_to_tool_m=relative.tolist(),distance_m=distance,residual_m=residual,
                reason='RGB_GEOMETRIC_EVIDENCE_NOT_HOLDING_FACT')


def gripper_kind(action,state,evidence):
    delta=-.91*(1-action['opening'])-state['gripper_master_rad']
    if abs(delta)<=.005:return 'noop'
    if delta<0:return 'close'
    return {'empty':'empty_open','possible_payload':'release','unknown':'unknown_open'}[evidence['status']]


def check(actions,source,current,source_features,current_features,*,start_pose=None,model_requirements=(),approach_evidence=None):
    """Return required tests and measured votes, never an action or corrected coordinate."""
    validate_requirements(model_requirements)
    old=hand_evidence(source_features,source['calibration'],source['state'])
    new=hand_evidence(current_features,current['calibration'],current['state'])
    required={'scene_healthy',*model_requirements};extra=[];kinds=[]
    pose=start_pose or [*current['state']['actual_grasp_center_world'],*current['state']['flange_pose_world'][3:]]
    moved=False
    for action in actions:
        if action['type']=='move_pose':
            target=action['pose'];d=np.asarray(target[:3])-pose[:3];rotation=angle(target[3:],pose[3:])
            if np.linalg.norm(d)<=.001 and rotation<=.005:kind='move_noop'
            elif .001<d[2]<=.15 and np.linalg.norm(d[:2])<=.01 and rotation<=.05:
                kind='bounded_upward_withdrawal'
                extra.append({'requirement':'current_object_observable','status':'valid' if new['status']!='unknown' else 'unknown'})
            elif (approach_evidence and approach_evidence.get('status')=='supported'
                  and approach_evidence.get('source_observation_id')==source['observation_id']
                  and approach_evidence.get('current_observation_id')==current['observation_id']
                  and old['status']==new['status']=='unknown'
                  and all(v.get('reason')=='RGB_GEOMETRIC_EVIDENCE_NOT_HOLDING_FACT'
                          and .06<v.get('distance_m',float('inf'))<=.09 for v in (old,new))):
                kind='empty_approach_history_rgbd';required.add('object_static')
                extra.append({'requirement':'empty_approach_current_evidence','status':'valid','evidence':approach_evidence})
            elif old['status']=='empty':kind='empty_approach';required.add('object_static')
            elif old['status']=='possible_payload':
                kind='possible_payload_motion';required.update(('goal_static','object_near_tool'))
                drift=(float(np.linalg.norm(np.asarray(new['relative_object_to_tool_m'])-old['relative_object_to_tool_m']))
                       if new['status']!='unknown' else None)
                extra.append({'requirement':'object_tracks_tool','relative_change_m':drift,
                              'status':'unknown' if drift is None else 'valid' if drift<=.03 else 'invalid'})
            else:
                kind='unknown_motion';extra.append({'requirement':'object_dependence_known','status':'unknown'})
            kinds.append(kind);pose=target;moved=True
        elif action['type']=='gripper':
            if moved:
                kinds.append('gripper_deferred_to_actual_boundary');continue
            kind=gripper_kind(action,current['state'],new);kinds.append(kind)
            if kind=='close':required.add('object_static')
            elif kind=='release':required.update(('goal_static','object_near_tool','object_at_goal'))
            elif kind=='unknown_open':extra.append({'requirement':'opening_state_known','status':'unknown'})
    result=rgb.compare(source_features,current_features,source['calibration'],current['calibration'],sorted(required),current['state'])
    result['checks']+=extra
    votes=[x['status'] for x in result['checks']]
    result.update(status='invalid' if 'invalid' in votes else 'unknown' if 'unknown' in votes else 'valid',
                  owner_revision=REVISION,action_kinds=kinds,source_hand_evidence=old,current_hand_evidence=new,
                  owner_required=sorted(required),empty_approach_evidence=approach_evidence)
    return result


def empty_approach_evidence(store, world, source, current, initialization, history):
    """Narrow Owner proof, not a WH-wide validity override or a holding detector.

    Empty initialization + complete no-close execution history + current static
    tabletop target and freshly reprojected depth. Existing numerical geometry
    scales are reused; payload distance thresholds above are unchanged.
    """
    from platform_v1.research.object_tracking import fk_camera_consistency
    from platform_v1.research.da3_geometry import calibrated_cameras, CAMERAS
    from platform_v1.research.object_world import project
    from platform_v1.research.contracts import digest
    out={'status':'unknown','method':'EMPTY_INITIALIZATION_HISTORY_CURRENT_RGBD',
         'source_observation_id':source['observation_id'],'current_observation_id':current['observation_id'],
         'history_sha256':digest(history),'grants_execution':False}
    def reject(reason):return dict(out,reason=reason)
    initial=initialization.get('start_state',{})
    if initialization.get('setup_held_calls')!=0 or initialization.get('initialization')!='generic empty-hand preparation; object-independent':
        return reject('EMPTY_INITIALIZATION_NOT_WITNESSED')
    if initial.get('actual_pad_gap_m',0)<=.07 or abs(initial.get('gripper_master_rad',float('inf')))>.005:
        return reject('INITIAL_OPEN_KINEMATICS_UNSUPPORTED')
    if len(history)!=source['execution_epoch']:return reject('INCOMPLETE_OWNER_HISTORY')
    if any(h.get('gripper_close_requested') or h.get('completed') is not True for h in history):
        return reject('CLOSE_OR_INCOMPLETE_EXECUTION_HISTORY')
    if current['state'].get('stopped') or source['state'].get('stopped'):return reject('STOPPED')
    if any(o['state']['actual_pad_gap_m']<=.07 or abs(o['state']['gripper_master_rad']-initial['gripper_master_rad'])>.005 for o in (source,current)):
        return reject('CURRENT_GRIPPER_CONTRADICTS_EMPTY_HISTORY')
    if source['execution_epoch']!=current['execution_epoch'] or world['binding']['execution_epoch']!=current['execution_epoch']:
        return reject('EPOCH_MISMATCH')
    if world['state']['observation_id']!=source['observation_id'] or current['captured_monotonic']<source['captured_monotonic']:
        return reject('CURRENT_SOURCE_BINDING')
    if fk_camera_consistency(source,current)['status']!='pass':return reject('FK_CAMERA_CONFLICT')
    s=world['state'];target=s.get('task_target_geometry_id');e=s.get('entities',{}).get(target,{})
    inter=s.get('pnp_interaction',{})
    if (e.get('status')!='coarse' or e.get('semantic_status')!='hypothesis'
        or e.get('temporal_association',{}).get('status')!='unique_current_match'
        or inter.get('gripper_event')!='none' or inter.get('carrying_seen') or inter.get('status')!='tabletop_target'):
        return reject('TARGET_OR_INTERACTION_NOT_STATIC_APPROACH')
    if not e.get('bounds_world_m') or e['bounds_world_m'][0][2]>s['object_config']['discovery']['table_support_band_m']:
        return reject('NO_CURRENT_TABLE_SUPPORT')
    if not inter.get('initial_object_xyz_m') or math.dist(e['point_world_m'],inter['initial_object_xyz_m'])>.03:
        return reject('TARGET_DISPLACEMENT_CONTRADICTION')
    cloud=np.asarray(e.get('surface_cloud',[]),float).reshape(-1,3)
    if not len(cloud):return reject('NO_CURRENT_TARGET_SURFACE')
    ext,ks=calibrated_cameras(current);views=[]
    threshold=s['object_config']['discovery']['surface_agreement_m']
    minimum=s['object_config']['discovery']['min_symmetric_surface_fraction']
    for i,c in enumerate(CAMERAS):
        # PublicStore validates RGB, depth, validity, alignment and hashes.
        store.image(current['observation_id'],c);depth,valid,meta=store.depth(current['observation_id'],c)
        uv,z=project(cloud,ext[i],ks[i]);pix=np.rint(uv).astype(int);h,w=depth.shape
        inside=(z>0)&np.isfinite(uv).all(axis=1)&(pix[:,0]>=0)&(pix[:,0]<w)&(pix[:,1]>=0)&(pix[:,1]<h)
        pp=pix[inside];zz=z[inside]
        if not len(pp):continue
        available=valid[pp[:,1],pp[:,0]];difference=np.abs(depth[pp[:,1],pp[:,0]]-zz)
        fraction=float(np.mean(available&(difference<=threshold)))
        views.append({'camera':c,'projected_points':len(pp),'current_surface_support_fraction':fraction,
          'supported':len(pp)>=s['object_config']['geometry']['min_points_per_view'] and fraction>=minimum,
          'depth_sha256':meta['depth']['sha256'],'rgb_sha256':meta['aligned_rgb_sha256']})
    out.update(world_id=world['world_id'],world_revision=world['world_revision'],target_id=target,views=views,
        initialization_sha256=digest(initialization),current_observation_sha256=digest(current))
    if sum(v['supported'] for v in views)<2:return reject('CURRENT_MULTIVIEW_DEPTH_UNSUPPORTED')
    return dict(out,status='supported',reason='EMPTY_HISTORY_WITH_CURRENT_STATIC_TABLE_TARGET')
