"""Versioned geometry-to-semantics and permanently non-executable planning review.

Request builders share the existing Broker, schemas and public Store. They do
not instantiate a model client, Supervisor, execution owner or new estimator.
"""
import math
from .contracts import clone
from sim_skills.full_pnp.wire import obj
from . import chunk_plan

GROUNDING_VERSION = 'astra.semantic_grounding.v1'
SHADOW_VERSION = 'astra.action_shadow.v1'
CANDIDATE_VERSION = 'astra.action_shadow_candidate.v2'
CANDIDATE_INSTRUCTION = (
    'NONEXECUTABLE HYPOTHESIS GENERATION, followed by independent planning review; physical admission is separate. '
    'Using the compact world, task and actual robot state, propose a meaningful coarse precontact ActionChunkPlan v2 '
    'candidate if supported as a hypothesis. H=4, m=1, K=0; four waypoints or justified stage_terminal; '
    '20-50mm translation, rotation <=0.15rad, nominal 2s offsets, complete prefix dependencies; no noop padding, contact or gripper. '
    'You need not prove IK, collision or clearance before proposing a candidate. These checks remain NOT_TESTED, '
    'owner admission NOT_GRANTED, and every waypoint a hypothesis. State explicit assumptions and assess all five '
    'waypoint preconditions as supported_by_input, unverified or conflict; never claim an unchecked prerequisite passed. '
    'A precondition names a requirement, not its satisfaction. Never infer hidden free space or claim physical safety. '
    'Observed bounds are surfaces, not exact object/grasp centers. Distinguish task identity hypothesis from absence of semantics. '
    'Use planned only for a meaningful reviewable candidate; choose refused for explicit conflicts, or need_more_evidence '
    'when a meaningful candidate cannot be formed. For either null-plan response, leave precondition assessments empty. '
    'All decisions permanently grant no execution. Do not manufacture MODEL_RAW provenance or change world/read versions.')
REVIEW_ROLES = ('semantic_grounding', 'action_shadow')

def grounding_schema(world):
    ids = sorted(world['state']['entities'])
    if not ids: raise ValueError('NO_GEOMETRY_CANDIDATES')
    identity = {'type': 'string', 'enum': ids}
    text = {'type': 'string', 'minLength': 1}
    refs = {'type': 'array', 'items': text, 'minItems': 1, 'uniqueItems': True}
    item = obj({'geometry_instance_id': identity, 'category': {'type': ['string', 'null']},
        'attributes': {'type': 'array', 'items': text, 'maxItems': 16},
        'disposition': {'type': 'string', 'enum': ['object', 'robot', 'region', 'unknown']},
        'semantic_status': {'type': 'string', 'enum': ['hypothesis', 'unknown']}, 'evidence_refs': refs})
    request = obj({'kind': {'type': 'string', 'enum': ['segmentation', 'reassociation', 'new_planar_region']},
        'geometry_instance_ids': {'type': 'array', 'items': identity, 'uniqueItems': True},
        'camera': {'type': 'string', 'enum': ['assembly', 'fixed', 'wrist']},
        'bbox': {'type': ['array', 'null'], 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'minItems': 4, 'maxItems': 4},
        'reason': text, 'evidence_refs': refs})
    return obj({'version': {'type': 'string', 'const': GROUNDING_VERSION},
        'objects': {'type': 'array', 'items': item, 'minItems': len(ids), 'maxItems': len(ids)},
        'task_target_geometry_id': {'type': ['string', 'null'], 'enum': [*ids, None]},
        'target_status': {'type': 'string', 'enum': ['hypothesis', 'ambiguous', 'unknown']},
        'requests': {'type': 'array', 'items': request, 'maxItems': 16},
        'unknowns': {'type': 'array', 'items': text}})

def planning_review_eligibility(world, observation):
    """Eligibility to REVIEW a proposal, never a claim of task/physical usability.

    No radius cutoff: the historical 20mm gate and result remain unchanged.
    Finite observed support, world/source bindings and explicit uncertainty are
    checked; unknown target/clearance must be expressible as a refusal.
    """
    if world['binding']['execution_epoch'] != observation['execution_epoch']:
        raise ValueError('REVIEW_EPOCH')
    if world['state']['observation_id'] != observation['observation_id'] or world['binding']['observation_ids'] != [observation['observation_id']]:
        raise ValueError('REVIEW_OBSERVATION')
    from .chunk_plan import pose_error
    origin = [*observation['state']['actual_grasp_center_world'], *observation['state']['flange_pose_world'][3:]]
    pose_error(origin, origin)
    rows = {}
    for identity, e in world['state'].get('entities', {}).items():
        bounds = e.get('bounds_world_m') or e.get('coarse_observed_bounds_world_m')
        if bounds is not None:
            if len(bounds) != 2 or any(len(p) != 3 for p in bounds) or any(not math.isfinite(v) for p in bounds for v in p):
                raise ValueError('REVIEW_NONFINITE_GEOMETRY')
        components = e.get('uncertainty_components', {})
        rows[identity] = {'surface_bounds_m': clone(bounds),
            'surface_extent_is_localization_error': False,
            'localization_confidence_radius_m': components.get('localization_confidence_radius_m'),
            'legacy_surface_disagreement_radius_m': e.get('uncertainty_radius_m'),
            'association': clone(e.get('association_uncertainty', {'status': 'unknown_unquantified'})),
            'status': e.get('status', 'unknown'), 'visibility': clone(e.get('visibility', {}))}
    return {'version': 'astra.planning_review_eligibility.v1', 'eligible_to_review': True,
        'world_id': world['world_id'], 'world_revision': world['world_revision'], 'execution_epoch': observation['execution_epoch'],
        'read_versions': clone(world['read_versions']), 'entities': rows,
        'policy': 'review with explicit unknown/refusal; does not certify spatial precision or clearance',
        'legacy_20mm_gate': 'NOT_CHANGED_NOT_OVERRIDDEN', 'grants_execution': False, 'K': 0}

def shadow_schema(world, observation, task, task_binding):
    eids = list(world['binding'].get('evidence_ids', []))
    # Geometry-only candidates do not yet supply a semantic task binding.
    # A world ID is a read dependency, NOT a fabricated MODEL_RAW evidence ID.
    if not eids: raise ValueError('SHADOW_REAL_SEMANTIC_EVIDENCE_REQUIRED')
    if world['state'].get('semantic_binding_version'):
        selection = world['state']['task_selection']
        if (task != selection['task'] or task_binding['object_id'] != selection['task_target_geometry_id']
                or task_binding['goal_id'] or task_binding['profile'] != 'generic_semantic_v1'):
            raise ValueError('SHADOW_SEMANTIC_TASK_BINDING')
    for key in ('object_id','goal_id'):
        if task_binding[key] and task_binding[key] not in world['state']['entities']: raise ValueError('SHADOW_TASK_INSTANCE')
    plan = chunk_plan.request_schema(world, observation, task, task_binding, 4, eids)
    return obj({'version': {'type': 'string', 'const': SHADOW_VERSION},
        'intent': {'type': 'string', 'const': 'action_shadow'},
        'decision': {'type': 'string', 'enum': ['planned', 'refused', 'need_more_evidence']},
        'plan': {'anyOf': [plan, {'type': 'null'}]},
        'reason': {'type': 'string', 'minLength': 1},
        'unknowns': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}},
        'K': {'type': 'integer', 'const': 0}, 'grants_execution': {'type': 'boolean', 'const': False}})

def grounding_request(world, observation, task_instruction):
    if world['state'].get('initialization') != 'geometry_first_v2': raise ValueError('GEOMETRY_FIRST_WORLD_REQUIRED')
    if world['state']['observation_id'] != observation['observation_id']: raise ValueError('GROUNDING_OBSERVATION')
    return {'backend': 'existing_codex_infer', 'role': 'semantic_grounding', 'world_id': world['world_id'],
        'evidence_ids': [], 'images': [{'observation_id': observation['observation_id'], 'camera': c, 'roi': None} for c in ('assembly','fixed','wrist')],
        'instruction': 'Ground the supplied unclassified geometry candidates using these RGB images and the task. '
            'Return one record per geometry ID, including robot/unknown dispositions. IDs are spatial hypotheses, not known objects. '
            'Do not repeat XYZ or runtime metadata. Bind semantics/attributes and task reference to existing geometry IDs; '
            'request segmentation/reassociation or a new planar region if needed. Preserve unknown and do not invent hidden identities. Task: ' + task_instruction,
        'output_schema': grounding_schema(world), 'timeout_s': 90}

def shadow_request(world, observation, task, task_binding):
    planning_review_eligibility(world, observation)
    return {'backend': 'existing_codex_infer', 'role': 'action_shadow', 'world_id': world['world_id'],
        'evidence_ids': list(world['binding'].get('evidence_ids', [])),
        'images': [{'observation_id': observation['observation_id'], 'camera': c, 'roi': None} for c in ('assembly','fixed','wrist')],
        'instruction': 'NONEXECUTABLE PLANNING REVIEW ONLY. Read the compact world and actual robot state. '
            'Review a possible H4 coarse precontact plan, m=1, K=0. No contact/gripper. '
            'Use ActionChunkPlan v2: 20-50mm steps, rotation <=0.15rad, nominal 2s offsets, complete prefix dependencies; '
            'four steps or justified stage_terminal, no noop padding. Surface bounds are not exact object/grasp centers. '
            'If geometry, identity or required evidence is unknown, return need_more_evidence or refused with null plan. '
            'No result can enter physical execution; grants_execution must remain false.',
        'output_schema': shadow_schema(world, observation, task, task_binding), 'timeout_s': 90}

def candidate_shadow_schema(world, observation, task, task_binding):
    """New research wrapper; the inner ActionChunkPlan v2 remains unchanged."""
    schema = shadow_schema(world, observation, task, task_binding)
    schema['properties']['version']['const'] = CANDIDATE_VERSION
    checks = obj({k:{'type':'string','const':v} for k,v in {
        'IK':'NOT_TESTED','collision':'NOT_TESTED','clearance':'NOT_TESTED',
        'owner_admission':'NOT_GRANTED','hidden_space':'UNKNOWN_NOT_FREE'}.items()})
    assessment = obj({'waypoint_index':{'type':'integer','minimum':1,'maximum':4},
        'precondition':{'type':'string','enum':chunk_plan.PRECONDITIONS},
        'status':{'type':'string','enum':['supported_by_input','unverified','conflict']},
        'basis':{'type':'string','minLength':1},
        'evidence_refs':{'type':'array','items':{'type':'string','minLength':1},'uniqueItems':True}})
    fields = {'planning_level':{'type':'string','const':'HYPOTHESIS_GENERATION'},
        'review_status':{'type':'string','const':'INDEPENDENT_REVIEW_PENDING'},
        'all_waypoints_are_hypotheses':{'type':'boolean','const':True},
        'physical_checks':checks,
        'assumptions':{'type':'array','items':{'type':'string','minLength':1},'maxItems':16},
        'precondition_assessments':{'type':'array','items':assessment,'maxItems':20}}
    schema['properties'].update(fields);schema['required'].extend(fields)
    return schema

def candidate_shadow_request(world, observation, task, task_binding):
    request = shadow_request(world, observation, task, task_binding)
    request.update(instruction=CANDIDATE_INSTRUCTION,
        output_schema=candidate_shadow_schema(world,observation,task,task_binding))
    return request

def validate_candidate_result(result, attachments, binding, world):
    """Check machine-readable claims; free text still needs independent review."""
    ledger=result['precondition_assessments'];plan=result['plan']
    if plan is None:
        if ledger:raise ValueError('NULL_CANDIDATE_PRECONDITIONS')
        return
    target=world['state']['entities'][plan['task_binding']['object_id']]
    if target.get('status')!='coarse' or target.get('point_world_m') is None:
        raise ValueError('CANDIDATE_CURRENT_TARGET_REQUIRED')
    if not result['assumptions']:raise ValueError('CANDIDATE_ASSUMPTIONS_REQUIRED')
    keys=[(x['waypoint_index'],x['precondition']) for x in ledger]
    expected={(i,p) for i in range(1,len(plan['waypoints'])+1) for p in chunk_plan.PRECONDITIONS}
    if len(keys)!=len(set(keys)) or set(keys)!=expected:raise ValueError('CANDIDATE_PRECONDITION_COVERAGE')
    allowed={x['id'] for x in attachments}|set(binding['evidence_ids'])
    for x in ledger:
        if not set(x['evidence_refs'])<=allowed:raise ValueError('CANDIDATE_UNSENT_EVIDENCE')
        if x['status']=='conflict':raise ValueError('PLANNED_WITH_EXPLICIT_CONFLICT')
        if x['precondition']=='owner_admission' and x['status']!='unverified':
            raise ValueError('CANDIDATE_OWNER_NOT_ADMITTED')
        if x['status']=='supported_by_input':
            if not x['evidence_refs']:raise ValueError('CANDIDATE_SUPPORT_WITHOUT_EVIDENCE')
            if x['precondition']=='target_identity_hypothesis' and target.get('semantic_status')!='hypothesis':
                raise ValueError('CANDIDATE_TARGET_IDENTITY_UNSUPPORTED')
            if x['precondition']=='visibility' and not target.get('views'):
                raise ValueError('CANDIDATE_VISIBILITY_UNSUPPORTED')

def validate_review_request(request, world, observation):
    if world is None: raise ValueError('REVIEW_WORLD_REQUIRED')
    if len(request['images']) != 3 or {x['camera'] for x in request['images']} != {'fixed','assembly','wrist'} or any(x['roi'] is not None or x['observation_id'] != world['state']['observation_id'] for x in request['images']):
        raise ValueError('REVIEW_THREE_FROZEN_IMAGES')
    if request['role'] == 'semantic_grounding':
        if request['evidence_ids'] or world['state'].get('initialization') != 'geometry_first_v2': raise ValueError('GROUNDING_GEOMETRY_ONLY')
        expected = grounding_schema(world)
    else:
        planning_review_eligibility(world, observation)
        supplied = request['output_schema']
        try:
            p = supplied['properties']['plan']['anyOf'][0]['properties']
            candidate = supplied['properties']['version']['const']==CANDIDATE_VERSION
            factory = candidate_shadow_schema if candidate else shadow_schema
            expected = factory(world, observation, p['task']['const'], p['task_binding']['const'])
            if candidate and request['instruction']!=CANDIDATE_INSTRUCTION:raise ValueError('CANDIDATE_VERSIONED_PROMPT')
        except (KeyError, TypeError, IndexError) as exc: raise ValueError('SHADOW_BOUND_SCHEMA_REQUIRED') from exc
        if request['evidence_ids'] != list(world['binding'].get('evidence_ids', [])): raise ValueError('SHADOW_EVIDENCE_BINDING')
    if request['output_schema'] != expected: raise ValueError('REVIEW_SCHEMA_MISMATCH')
