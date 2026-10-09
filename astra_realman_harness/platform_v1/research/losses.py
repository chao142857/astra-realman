"""Separate research decisions. Neither can authorize an owner submission.

Forecast is an explicit coarse persistence hypothesis, not DA3 output/dynamics.
Missing association/error is unknown, never zero.
"""
import math
import numpy as np
from .contracts import clone, digest
from .chunk_plan import pose_error

def forecast(plan, state):
    required={plan['task_binding']['object_id'],plan['task_binding']['goal_id']}
    return {'version':'astra.lwh_forecast.v1','plan_sha256':digest(plan),
        'world_id':plan['world_id'],'world_revision':plan['world_revision'],
        'source_observation_id':plan['source_observation_id'],
        'kind':'COARSE_PERSISTENCE_HYPOTHESIS_NOT_MEASUREMENT',
        'after_waypoint':[{'index':w['index'],'nominal_end_offset_s':w['nominal_end_offset_s'],
            'depends_on_completed_prefix':list(range(1,w['index']+1)),
            'robot_pad_pose_world':clone(w['pose']),
            'entity_positions':{i:clone(e['point_world_m']) for i,e in state['entities'].items() if i in required and e['status']=='coarse'}}
            for w in plan['waypoints']]}

def compare(prediction, current, completed_at):
    if current['captured_monotonic'] < completed_at: raise ValueError('OBSERVATION_BEFORE_COMPLETION')
    s=current['robot_state'];pose=[*s['actual_grasp_center_world'],*s['flange_pose_world'][3:]]
    distance,angle=pose_error(prediction['robot_pad_pose_world'],pose)
    errors={i:(math.dist(p,current['entities'][i]['point_world_m'])
        if i in current['entities'] and current['entities'][i]['status']=='coarse' else None)
        for i,p in prediction['entity_positions'].items()}
    return {'robot_translation_m':distance,'robot_rotation_rad':angle,
        'entity_prediction_error_m':errors,'observation_residual_m':current.get('observation_residual_m'),
        'observation_residual_status':current.get('observation_residual_status','CURRENT_ASSOCIATION_REQUIRED'),
        'captured_monotonic':current['captured_monotonic'],'completion_monotonic':completed_at}

def projective_residual(reference, current, observation):
    """Static-world depth consistency, not semantic correspondence or contact error.

    Only near-pixel depth samples overlap. Missing support stays unknown. Occlusion
    may create a residual; it does not prove that a remembered object moved.
    """
    from .da3_geometry import calibrated_cameras, CAMERAS
    ext,k=calibrated_cameras(observation);errors=[]
    for i,camera in enumerate(CAMERAS):
        now=[p for p in current.get('surface_samples',[]) if p['camera']==camera]
        if not now:continue
        pixels=np.array([p['pixel'] for p in now]);points=np.array([p['point_world_m'] for p in now])
        for old in reference.get('surface_samples',[]):
            x=ext[i][:3,:3]@np.asarray(old['point_world_m'])+ext[i][:3,3]
            if x[2]<=0:continue
            uv=k[i]@x;uv=uv[:2]/uv[2];dist=np.linalg.norm(pixels-uv,axis=1);j=int(dist.argmin())
            if dist[j]<=2.:errors.append(float(np.linalg.norm(points[j]-old['point_world_m'])))
    return {'observation_residual_m':float(np.median(errors)) if len(errors)>=8 else None,
        'observation_residual_status':'STATIC_SCENE_PROJECTIVE_MEDIAN' if len(errors)>=8 else 'INSUFFICIENT_CURRENT_PIXEL_SUPPORT',
        'matched_samples':len(errors)}

def decide_chunk(*,completed,planned,K_cap,mode,preconditions,residual,visibility,boundary=False):
    if mode not in ('fixed','adaptive') or not 1<=K_cap<=planned: raise ValueError('K_POLICY')
    reasons=[]
    if completed>=K_cap: reasons.append('PREFIX_CAP')
    if boundary: reasons.append('PHYSICAL_OR_STAGE_BOUNDARY')
    if not preconditions: reasons.append('PRECONDITION_UNKNOWN_OR_INVALID')
    if residual is not None and (residual['robot_translation_m']>=.01 or residual['robot_rotation_rad']>=.05):
        reasons.append('PREDICTED_JOIN_MISMATCH')
    if mode=='adaptive':
        if visibility!='visible': reasons.append('VISIBILITY_NOT_ESTABLISHED')
        if residual is None: reasons.append('LOSS_UNKNOWN')
        else:
            # Research stop criteria; do not modify the owner's stricter independent gates.
            vals=[*residual['entity_prediction_error_m'].values(),residual['observation_residual_m']]
            if not vals or any(v is None for v in vals): reasons.append('LOSS_UNKNOWN')
            elif any(not math.isfinite(v) or v<0 or v>.03 for v in vals): reasons.append('LOSS_EXCEEDED')
    return {'name':'L_chunk','continue_next':not reasons,'reasons':reasons,'grants_execution':False}

def decide_world(*,identity_conflict=False,persistent_unknown=False,geometry_loss=None,query_budget=0):
    needs_semantics=identity_conflict or persistent_unknown
    return {'name':'L_world','semantic_review_needed':needs_semantics,
        'recommend_query':needs_semantics and query_budget>0,
        'reason':'SEMANTIC_OR_ASSOCIATION_UNRESOLVED' if needs_semantics else 'NO_SEMANTIC_TRIGGER',
        'geometry_loss':geometry_loss,'dispatches_model':False,
        'value_estimate':'NOT_ESTIMATED','query_budget_remaining':query_budget}
