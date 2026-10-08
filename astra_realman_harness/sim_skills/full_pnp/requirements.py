"""Single model-declarable RGB vocabulary; no scene, targets or action generation."""

REVISION='model_rgb_requirements_v1'
PREDICATES={
    'scene_healthy':'current image standard deviation >8 in at least one view',
    'object_static':'unique visible red component in same-pose source/current camera; shift <=6px, area ratio [0.25,4], color cosine >=0.95',
    'goal_static':'same test as object_static on green marker',
    'object_near_tool':'current red centroid within 1.5 object bbox diagonals of projected measured pad center; not proof of grasp',
    'object_at_goal':'current red and green centroids within 0.6 green bbox diagonal; independent physics scoring remains separate',
}
ALLOWED=tuple(PREDICATES)
CONTRACT={
    'revision':REVISION,
    'allowed':list(ALLOWED),
    'meanings':PREDICATES,
    'required':'Every B/A candidate must declare scene_healthy; finish with verdict done also requires object_at_goal.',
    'owner_boundary':'Only allowed names may appear in requirements. Owner action classifications and automatic geometric tests are not model-declarable predicates. In particular bounded_upward_withdrawal and current_triangulated_object are not allowed.',
    'minimum_checks':'Owner independently adds its existing action/state dependencies even when the model declares only scene_healthy. Declarations can add checks but cannot remove owner checks.',
    'unknown_name':'Reject unchanged; never drop, translate, repair, weaken or retry an unknown requirement.',
}


def validate_requirements(values,*,require_scene=False,require_goal=False):
    """Validate without modifying the caller's list or mapping owner concepts."""
    if not isinstance(values,(list,tuple)) or any(not isinstance(v,str) for v in values):
        raise ValueError('RGB_REQUIREMENTS_TYPE')
    unknown=[v for v in values if v not in ALLOWED]
    if unknown:raise ValueError('UNSUPPORTED_RGB_REQUIREMENT:'+','.join(unknown))
    if require_scene and 'scene_healthy' not in values:raise ValueError('RGB_REQUIREMENTS_MISSING_SCENE_HEALTHY')
    if require_goal and 'object_at_goal' not in values:raise ValueError('FINISH_RGB_REQUIREMENTS')


def requirements_schema():
    return {'type':'array','items':{'type':'string','enum':list(ALLOWED)},'minItems':1}
