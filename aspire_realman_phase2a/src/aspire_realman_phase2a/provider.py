"""Small model registry/validation extension for pinned native cuRobo service."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import yaml
from fastapi import HTTPException
from .model import MODEL,ARMS,NAMES,FRAME,load_manifest,sha


def manifest():
    path=os.environ.get('ASPIRE_REALMAN_MODEL_MANIFEST')
    if not path:raise HTTPException(503,'RM65_MODEL_MANIFEST_REQUIRED_NO_DEFAULT_LAYOUT')
    try:return load_manifest(path)
    except Exception as exc:raise HTTPException(503,str(exc)) from exc


def validate_request(req):
    m=manifest()
    if req.model!=MODEL or req.base_frame!=FRAME or set(req.joint_positions)!=set(ARMS):
        raise HTTPException(400,'RM65_EXPLICIT_SYNTHETIC_FRAME_AND_BOTH_ARMS_REQUIRED')
    for arm in ARMS:
        if req.joint_names.get(arm)!=list(NAMES[arm]) or req.end_effector_links.get(arm)!=m['end_effector_links'][arm]:
            raise HTTPException(400,'RM65_EXACT_JOINT_ORDER_AND_FLANGE_LINK_REQUIRED')
        transform=np.asarray(req.base_transforms.get(arm),float)
        if transform.shape!=(4,4) or not np.all(np.isfinite(transform)) or not np.allclose(transform,m['layout']['base_transforms'][arm],rtol=0,atol=1e-9):
            raise HTTPException(400,'RM65_CONTEXT_TRANSFORM_DIFFERS_FROM_GENERATED_MODEL')
        check_limits(arm,req.joint_positions[arm],m)
    targets=getattr(req,'targets',None)
    if targets is None and hasattr(req,'target'):targets={req.arm:req.target}
    for arm,target in (targets or {}).items():
        if arm not in ARMS:raise HTTPException(400,'UNKNOWN_RM65_ARM')
        if target.type=='joints':check_limits(arm,target.joint_positions,m)
        else:
            q=np.asarray(target.quaternion_wxyz,float);xyz=np.asarray(target.position,float)
            if target.frame!=FRAME or xyz.shape!=(3,) or not np.isfinite(xyz).all() or q.shape!=(4,) or not np.isfinite(q).all() or not np.isclose(np.linalg.norm(q),1,atol=1e-5):
                raise HTTPException(400,'RM65_FINITE_UNIT_QUATERNION_POSE_IN_SYNTHETIC_FRAME_REQUIRED')
    return m


def check_limits(arm,q,m):
    values=np.asarray(q,float);limits=m['joint_limits'][arm]
    if values.shape!=(6,) or not np.isfinite(values).all():raise HTTPException(400,'RM65_SIX_FINITE_JOINTS')
    if any(v<lim['lower'] or v>lim['upper'] for v,lim in zip(values,limits)):
        raise HTTPException(400,'RM65_JOINT_LIMIT_VIOLATION_NO_CLIPPING')


def config_for(req):
    m=validate_request(req)
    # A single-arm native response contains ONLY that arm. Freeze all six
    # inactive joints in the collision model; never discard a moving other arm.
    arm=getattr(req,'arm',None)
    if arm is None:return m['config']['path']
    inactive=next(a for a in ARMS if a!=arm)
    key=hashlib.sha256(json.dumps({'config':m['config']['sha256'],'arm':arm,
        'inactive':req.joint_positions[inactive]},sort_keys=True).encode()).hexdigest()[:20]
    output=Path(m['config']['path']).parent/'single_arm_locked';output.mkdir(exist_ok=True)
    path=output/(key+'.yml')
    if not path.exists():
        config=yaml.safe_load(Path(m['config']['path']).read_text());kin=config['robot_cfg']['kinematics']
        kin['lock_joints'].update(dict(zip(NAMES[inactive],req.joint_positions[inactive])))
        c=kin['cspace'];c['joint_names']=list(NAMES[arm]);c['default_joint_position']=m['default_positions'][arm]
        c['null_space_weight']=[1.]*6;c['cspace_distance_weight']=[1.]*6
        path.write_text(yaml.safe_dump(config,sort_keys=False))
    return str(path)


def ordered_state(req,expected):
    m=validate_request(req)
    names=[n for a in ARMS for n in NAMES[a]]
    values=np.concatenate([req.joint_positions[a] for a in ARMS])
    if len(expected)==6:
        arm=getattr(req,'arm',None)
        if arm not in ARMS or list(expected)!=list(NAMES[arm]):raise HTTPException(400,'RM65_ACTIVE_LOCKED_MODEL_ORDER_MISMATCH')
    elif list(expected)!=names:raise HTTPException(400,'RM65_DUAL_MODEL_ORDER_MISMATCH')
    return np.array([values[names.index(n)] for n in expected],float)


def install_validation_routes(service):
    """Post-resampling check against REAL GPU feasibility, no execution calls."""
    from pydantic import Field
    class CheckRequest(service.BaseRequest):
        waypoints:dict[str,list[list[float]]]
        dt_s:float=Field(gt=0)
    @service.app.post('/v1/realman/validate_trajectory')
    def validate_trajectory(req:CheckRequest):
        import torch
        m=validate_request(req)
        if not np.isfinite(req.dt_s):raise HTTPException(400,'FINITE_TRAJECTORY_PERIOD_REQUIRED')
        if set(req.waypoints)-set(ARMS):raise HTTPException(400,'UNKNOWN_TRAJECTORY_ARM')
        counts={len(v) for v in req.waypoints.values()}
        if len(counts)!=1 or not counts or not 1<=next(iter(counts))<=5000:raise HTTPException(400,'BOUNDED_EQUAL_LENGTH_TRAJECTORIES_REQUIRED')
        count=next(iter(counts));parts=[]
        for arm in ARMS:
            values=np.asarray(req.waypoints.get(arm,[req.joint_positions[arm]]*count),float)
            for row in values:check_limits(arm,row,m)
            vmax=np.array([l['velocity'] for l in m['joint_limits'][arm]])
            if count>1 and np.any(np.abs(np.diff(values,axis=0))/req.dt_s > vmax+1e-5):raise HTTPException(400,'TRAJECTORY_VELOCITY_LIMIT')
            parts.append(values)
        planner=service._planner(req)
        q=torch.as_tensor(np.concatenate(parts,axis=1),device='cuda',dtype=torch.float32)
        mask=planner.graph_planner.check_samples_feasibility(q).detach().cpu().numpy().astype(bool).reshape(-1)
        return {'ok':bool(mask.all()),'backend':'ACTUAL_CUROBO_GPU','checks':['joint_limits','velocity_limits','self_collision_including_cross_arm','scene_collision'],
            'waypoints':count,'feasible':mask.tolist(),'synthetic_layout':True,'physical_execution':False}
