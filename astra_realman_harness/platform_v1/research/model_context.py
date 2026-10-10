"""Bounded read-only model views of the existing Store. No state estimation."""
import json
from .contracts import clone,digest

QUERY_VERSION='astra.world_query.v1'
VISIBILITY_VERSION='observed_support_v1'
MAX_CONTEXT_BYTES=128*1024

def calibration_key(calibration):
    # Live extrinsics belong to each measurement; intrinsics/axes/rig contract
    # is a stable dependency. The existing FK camera check remains mandatory.
    return 'calibration/'+digest({c:{k:v for k,v in x.items() if k!='pose_world_xyz_wxyz'} for c,x in calibration.items()})

def canonical_visibility(value):
    return {'visible_RGB_support':'visible','visible_support':'visible'}.get(value,value)

def observation_view(observation,role):
    keys=('schema','version','episode_id','observation_id','execution_epoch','captured_monotonic','capture_span_s','frame','pose_convention')
    out={k:clone(observation[k]) for k in keys if k in observation}
    allowed=('intrinsic','pose_world_xyz_wxyz','resolution','axes')
    out['calibration']={c:{k:clone(v[k]) for k in allowed if k in v} for c,v in observation['calibration'].items()}
    if role in ('action','action_shadow'):
        from engineering.public_view import robot_state
        out['state']=robot_state(observation['state'])
    # Semantic roles never receive depth descriptors, arrays, robot/task state,
    # arbitrary extension fields or host paths. Selected RGB travels separately.
    return out

def validate_initial_semantic_request(request):
    version=request.get('output_schema',{}).get('properties',{}).get('version',{}).get('const')
    if request['role']!='semantic_e0' or version!='astra.semantic_scene.v2':return
    images=request['images']
    if request['world_id'] is not None or request['evidence_ids']:
        raise ValueError('INITIAL_E0_RGB_GEOMETRY_ONLY')
    if len(images)!=3 or {x['camera'] for x in images}!={'assembly','fixed','wrist'} or len({x['observation_id'] for x in images})!=1 or any(x['roi'] is not None for x in images):
        raise ValueError('INITIAL_E0_THREE_FROZEN_FULL_RGB_REQUIRED')

def _select(value,keys):return {k:clone(value[k]) for k in keys if k in value}

def compact_world(world,entity_ids=None,max_bytes=MAX_CONTEXT_BYTES):
    state=world['state'];entities=state.get('entities',{});ids=list(entities) if entity_ids is None else list(entity_ids)
    if len(ids)!=len(set(ids)) or not set(ids)<=set(entities):raise ValueError('WORLD_QUERY_ENTITY_IDS')
    if type(max_bytes) is not int or not 0<max_bytes<=MAX_CONTEXT_BYTES:raise ValueError('WORLD_QUERY_BUDGET')
    out=_select(world,('version','world_id','world_revision','created_monotonic','binding','provenance','read_versions','semantics'))
    small=_select(state,('backend','geometry_backend','observation_id','captured_monotonic','robot_state','scene_healthy',
        'geometry_only','task_identity_verified','task_target_id','public_plane','geometry_quality',
        'semantic_evidence_id','semantic_source','relations','unknowns','history_semantics','rebuild_needed','initialization',
        'semantic_binding_version','task_target_geometry_id','task_selection','semantic_unknowns','semantic_requests',
        'geometry_provenance','semantic_provenance'))
    selected={}
    for identity in ids:
        e=entities[identity]
        v=_select(e,('entity_id','instance_id','label','kind','identity_status','status','point_world_m','bounds_world_m',
            'uncertainty_radius_m','uncertainty_semantics','center_semantics','visibility','motion','measurement_kind',
            'held_relation','reason','observation_id','captured_monotonic','semantic_source','semantic_evidence_id',
            'current_evidence','contributing_views','view_disagreement_m','displacement_from_previous_measurement_m',
            'geometry_instance_id','candidate_type','objectness','semantic_status','robot_exclusion',
            'coarse_observed_bounds_world_m','association_evidence','association_uncertainty','uncertainty_components',
            'semantic_category','semantic_attributes','semantic_disposition'))
        v['views']=[_select(x,('camera','bbox','observation_id','attachment_id','producer','visibility','association')) for x in e.get('views',[])]
        historical=e.get('historical_geometry')
        if historical:v['historical_geometry']={**_select(historical,('point_world_m','observation_id','captured_monotonic')),'measurement_kind':'historical_not_current'}
        v['surface_reference']={'point_count':len(e.get('surface_cloud',[])),'sha256':digest(e.get('surface_cloud',[])),
            'retained_in':'WorldStore','complete_volume':False}
        v['candidate_surface_reference']={'point_count':len(e.get('candidate_surface_cloud',[])),
            'sha256':digest(e.get('candidate_surface_cloud',[])),'retained_in':'WorldStore','complete_volume':False}
        selected[identity]=v
    small['entities']=selected
    if state.get('semantic_binding_version'):
        # Initial geometry correctly had no semantic labels. Keep that historical
        # layer explicit instead of presenting it as the current semantic answer.
        small['geometry_initialization_unknowns']=small.pop('unknowns',[])
        small['unknowns']=clone(state['semantic_unknowns'])
        small['unknowns_scope']='current semantic hypotheses; geometry initialization notes retained separately'
    static=state.get('scene_layers',{}).get('static',{})
    small['scene_summary']={'static_kind':static.get('kind','unknown'),'static_point_count':len(static.get('points',[])),
        'current_support_count':static.get('current_support_count',0),'unclassified_geometry':'not guaranteed static',
        'collision_free_space':'unknown; point-cloud absence is not clearance evidence'}
    out.update(state=small,query={'version':QUERY_VERSION,'entity_ids':ids,'source_state_sha256':digest(state),
        'grants_execution':False,'omissions':['dense points','pixel masks','tracking seed arrays'],'silent_truncation':False})
    if len(json.dumps(out,sort_keys=True,allow_nan=False).encode())>max_bytes:raise ValueError('WORLD_QUERY_TOO_LARGE')
    return out


def role_world_view(store, world_id, role):
    """Existing query projection plus explicit review-role metadata whitelist."""
    out = store.query_world(world_id)
    if role not in ('semantic_grounding', 'action_shadow'): return out
    state = out['state']
    if role == 'semantic_grounding':
        state.pop('robot_state', None)
        for key in ('semantic_source', 'semantic_evidence_id', 'relations', 'task_target_id'):
            state.pop(key, None)
    elif 'robot_state' in state:
        from engineering.public_view import robot_state
        state['robot_state'] = robot_state(state['robot_state'])
    for entity in state['entities'].values():
        entity['current_evidence'] = [_select(row, ('camera', 'observation_id', 'captured_monotonic',
            'current_points', 'pixels', 'depth_sha256', 'RGB_source_sha256', 'validity_sha256',
            'calibration_sha256', 'sensor_frame_id', 'mask_pixels', 'valid_depth_pixels',
            'depth_support_fraction', 'status', 'surface_median_world_m', 'producer', 'semantic_evidence_id'))
            for row in entity.get('current_evidence', [])]
        entity['views'] = [_select(row, ('camera', 'bbox', 'observation_id', 'attachment_id', 'producer', 'visibility'))
            for row in entity.get('views', [])]
    if role == 'semantic_grounding':
        positioned = [(i,e['point_world_m']) for i,e in state['entities'].items() if e.get('point_world_m') is not None]
        state['geometry_relations'] = [{'subject':a, 'object':b,
            'observed_bounds_midpoint_delta_world_m':[q-p for p,q in zip(pa,pb)],
            'source':'CURRENT_GEOMETRY_NOT_SEMANTIC_RELATION'}
            for index,(a,pa) in enumerate(positioned) for b,pb in positioned[index+1:]]
    if role == 'action_shadow':
        from .review_contracts import planning_review_eligibility
        o = store.get(state['observation_id'])
        out['planning_review'] = planning_review_eligibility(store.get_world(world_id), o)
    out['query']['role_projection'] = role
    out['query']['grants_execution'] = False
    return out
