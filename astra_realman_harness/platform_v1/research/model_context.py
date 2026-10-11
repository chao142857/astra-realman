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
    if role in ('action','action_shadow','t1_action_proposal','pnp_action_proposal'):
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
        'geometry_provenance','semantic_provenance','geometry_update_version','task_target_current_support','current_unknowns','fk_camera_check','update_input_provenance','pnp_interaction','pnp_destination'))
    selected={}
    for identity in ids:
        e=entities[identity]
        v=_select(e,('entity_id','instance_id','label','kind','identity_status','status','point_world_m','bounds_world_m',
            'uncertainty_radius_m','uncertainty_semantics','center_semantics','visibility','motion','measurement_kind',
            'held_relation','reason','observation_id','captured_monotonic','semantic_source','semantic_evidence_id',
            'current_evidence','contributing_views','view_disagreement_m','displacement_from_previous_measurement_m',
            'geometry_instance_id','candidate_type','objectness','semantic_status','robot_exclusion',
            'coarse_observed_bounds_world_m','association_evidence','association_uncertainty','uncertainty_components',
            'semantic_category','semantic_attributes','semantic_disposition','historical_semantics','geometry_residual','temporal_association','semantic_attribute_time_scope'))
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
        if state.get('current_unknowns'):small['current_geometry_unknowns']=clone(state['current_unknowns'])
        small['unknowns_scope']='current semantic hypotheses; geometry initialization notes retained separately'
        if state.get('geometry_update_version'):
            small['historical_semantic_unknowns']=small['unknowns']
            small['unknowns']=[x['entity_id']+': '+x['reason'] for x in state.get('current_unknowns',[])]
            small['unknowns_scope']='current sensor/identity gaps; original model unknown statements are historical, not re-evaluated'
    static=state.get('scene_layers',{}).get('static',{})
    small['scene_summary']={'static_kind':static.get('kind','unknown'),'static_point_count':len(static.get('points',[])),
        'current_support_count':static.get('current_support_count',0),'unclassified_geometry':'not guaranteed static',
        'collision_free_space':'unknown; point-cloud absence is not clearance evidence'}
    out.update(state=small,query={'version':QUERY_VERSION,'entity_ids':ids,'source_state_sha256':digest(state),
        'grants_execution':False,'omissions':['dense points','pixel masks','tracking seed arrays'],'silent_truncation':False})
    if len(json.dumps(out,sort_keys=True,allow_nan=False).encode())>max_bytes:raise ValueError('WORLD_QUERY_TOO_LARGE')
    return out


def pnp_current_view(world):
    """Task-time projection only; full geometry, receipts and history stay in Store."""
    state=world['state'];entities={}
    for identity,e in state['entities'].items():
        v=_select(e,('geometry_instance_id','status','identity_status','point_world_m','bounds_world_m',
            'coarse_observed_bounds_world_m','uncertainty_radius_m','uncertainty_semantics','center_semantics',
            'visibility','motion','measurement_kind','held_relation','reason','observation_id',
            'semantic_category','semantic_attributes','semantic_disposition','semantic_status',
            'candidate_type','robot_exclusion','geometry_residual','semantic_attribute_time_scope'))
        v['association']=_select(e.get('temporal_association',{}),('status','candidates','mode','semantic_carry'))
        v['association_uncertainty']=_select(e.get('association_uncertainty',{}),('identity_guaranteed','method','temporal_status','competing_current_candidates','merged_robot_component_not_promoted'))
        v['views']=[_select(x,('camera','bbox','observation_id','visibility')) for x in e.get('views',[])]
        if e.get('historical_geometry') and e.get('status')!='coarse':
            v['last_seen_not_current']=_select(e['historical_geometry'],('point_world_m','bounds_world_m','coarse_observed_bounds_world_m','observation_id'))
        v['surface_scope']='visible measured support only; unknown/robot surfaces are occupied or unresolved, never certified free space'
        entities[identity]=v
    small=_select(state,('observation_id','captured_monotonic','public_plane','geometry_quality','task_target_geometry_id',
        'task_target_current_support','current_unknowns','fk_camera_check','rebuild_needed'))
    small['task']=clone(state['task_selection']['task'])
    small['identity_status']=state['task_selection']['status']
    inter=state.get('pnp_interaction',{})
    small['pnp_interaction']={k:clone(v) for k,v in inter.items() if k!='tracking_measurement'}
    if inter.get('tracking_measurement'):
        small['pnp_interaction']['local_surface_support']=_select(inter['tracking_measurement'],('status','reason','support_status','shape_support_fraction','geometry_scope'))
    goal=state.get('pnp_destination',{})
    small['pnp_destination']={k:clone(v) for k,v in goal.items() if k not in ('semantic_support','views')}
    small['pnp_destination']['views']=[_select(v,('camera','observation_id','bounds_world_m','points')) for v in goal.get('views',[])]
    small['recent_execution_feedback']=_select(state.get('execution_feedback',{}),('kind','ok','actions','error_code','unexecuted_count','completed_monotonic'))
    small['historical_semantic_unknowns']=clone(state.get('semantic_unknowns',[]))
    small['entities']=entities
    small['collision_free_space']='UNKNOWN: cloud absence is not clearance; all original Owner/IK/collision/contact/STOP checks still required'
    return {'world_id':world['world_id'],'world_revision':world['world_revision'],
        'execution_epoch':world['binding']['execution_epoch'],'state':small,
        'query':{'version':QUERY_VERSION,'role_projection':'pnp_action_proposal','projection':'current_task_state_v1',
            'source_state_sha256':digest(state),'read_versions_sha256':digest(world['read_versions']),
            'grants_execution':False,'host_retains':['complete points and masks','historical snapshots','source receipts and read_versions','raw logs'],
            'silent_truncation':False}}


def role_world_view(store, world_id, role):
    """Existing query projection plus explicit review-role metadata whitelist."""
    if role=='pnp_action_proposal' and not getattr(store,'pair_current_only',False):
        return pnp_current_view(store.get_world(world_id))
    out = store.query_world(world_id)
    if role not in ('semantic_grounding', 'action_shadow', 't1_action_proposal','pnp_action_proposal'): return out
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
    if role in ('action_shadow','t1_action_proposal','pnp_action_proposal'):
        from .review_contracts import planning_review_eligibility
        o = store.get(state['observation_id'])
        out['planning_review'] = planning_review_eligibility(store.get_world(world_id), o)
    out['query']['role_projection'] = role
    out['query']['grants_execution'] = False
    if role=='pnp_action_proposal' and getattr(store,'pair_current_only',False):
        # Matched input-history ablation, NOT a different safety estimator.
        # Identity/semantic hypotheses and current control-event phase are shared.
        for key in ('history_semantics','geometry_initialization_unknowns','historical_semantic_unknowns'):
            state.pop(key,None)
        for e in state['entities'].values():
            for key in ('historical_geometry','historical_semantics','displacement_from_previous_measurement_m',
                        'geometry_residual','temporal_association','motion'):
                e.pop(key,None)
        inter=state.get('pnp_interaction',{})
        for key in ('initial_object_xyz_m','carry_anchor_flange_local_m','FK_carry_prediction_world_m',
                    'prediction_source','current_visual_vs_carry_prediction_residual_m','current_position_shift_m'):
            inter.pop(key,None)
        out['query']['input_history_condition']='CURRENT_RGBD_ONLY_WITH_SHARED_SEMANTICS_AND_CONTROL_PHASE'
        out['query']['omissions'].append('persistent geometric history and predictions')
    return out
