"""Common owner evidence predicates. RGB/calibration/proprioception only; no target generator."""
import math
import numpy as np
from sim_skills.full_pnp import rgb

REVISION='owner_dependencies_v1'
CONTRACT={
 'revision':REVISION,
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


def check(actions,source,current,source_features,current_features,*,start_pose=None,model_requirements=()):
    """Return required tests and measured votes, never an action or corrected coordinate."""
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
                  owner_required=sorted(required))
    return result
