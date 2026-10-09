"""Evidence gate independent of numeric health and independent of physical safety.

Public-plane checks are opt-in host contracts, not inferred from a goal's GT.
Unknown evidence never becomes task-usable because numbers happen to be finite.
"""
import numpy as np
from .contracts import digest

VERSION='astra.geometry_quality.v1'

def table_mask(rgb):
    """Archived grey-blue tabletop DIAGNOSTIC profile, not generic semantics."""
    r,g,b=np.asarray(rgb,float).transpose(2,0,1)
    return (b-r>5)&(g-r>3)&(abs(b-g)<20)&(r>40)

def assess(state, observation, images, public_plane=None):
    samples=state.get('surface_samples',[])
    numeric=bool(samples) and all(np.isfinite(p['point_world_m']).all() for p in samples)
    reasons=[];views={};consistent='unknown'
    if not numeric:reasons.append('NO_FINITE_GEOMETRY')
    elif public_plane is None:reasons.append('NO_INDEPENDENT_GEOMETRY_SUPPORT')
    else:
        n=np.asarray(public_plane['normal'],float);offset=float(public_plane['offset'])
        if not np.isclose(np.linalg.norm(n),1):raise ValueError('PUBLIC_PLANE_NORMAL')
        for camera,rgb in images.items():
            mask=table_mask(rgb);h,w=mask.shape;zs=[]
            for p in samples:
                if p['camera']!=camera:continue
                u,v=np.rint(p['pixel']).astype(int)
                if 0<=u<w and 0<=v<h and mask[v,u]:zs.append(abs(np.dot(p['point_world_m'],n)+offset))
            views[camera]={'samples':len(zs),'median_abs_plane_m':float(np.median(zs)) if zs else None,
                'p90_abs_plane_m':float(np.quantile(zs,.9)) if zs else None}
        supported=[v for v in views.values() if v['samples']>=8]
        if any(v['median_abs_plane_m']>.03 or v['p90_abs_plane_m']>.06 for v in supported):
            consistent='fail';reasons.append('PUBLIC_PLANE_CONFLICT')
        elif len(supported)>=2:consistent='pass'
        else:reasons.append('INSUFFICIENT_PUBLIC_PLANE_SAMPLES')
    return {'version':VERSION,'numeric_valid':'pass' if numeric else 'fail','self_consistent':consistent,
        'task_usable':'fail' if consistent=='fail' or not numeric else 'unknown',
        'reason':reasons or ['TASK_ENTITY_PRECISION_AND_ASSOCIATION_NOT_ESTABLISHED'],
        'views':views,'observation_id':observation['observation_id'],
        'state_geometry_sha256':digest(samples) if numeric else None,'grants_execution':False}

def require_task_usable(world, task_binding):
    state=world['state'];q=state.get('geometry_quality',{})
    if any(q.get(k)!='pass' for k in ('numeric_valid','self_consistent','task_usable')):
        raise ValueError('GEOMETRY_NOT_TASK_USABLE')
    if q.get('observation_id')!=state['observation_id']:raise ValueError('STALE_GEOMETRY_QUALITY')
    for identity in (task_binding.get('object_id'),task_binding.get('goal_id')):
        if not identity:continue
        e=state.get('entities',{}).get(identity,{})
        if e.get('status')!='coarse' or e.get('measurement_kind') not in ('current_depth_region','current_RGB_plane_constraint'):
            raise ValueError('REQUIRED_CURRENT_3D_MEASUREMENT_UNKNOWN')
