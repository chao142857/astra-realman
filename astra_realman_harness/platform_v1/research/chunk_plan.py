"""Unified v2 proposal contract. Runtime provenance is stamped AFTER raw receipt.

No execution authority, controller, model client or future observations here.
"""
import math
import jsonschema
from sim_skills.full_pnp.wire import obj
from sim_skills.full_pnp.protocol import validate_actions
from .contracts import clone, digest

VERSION = 'astra.action_chunk_plan.v2'
PROFILE = 'coarse_pad_waypoint_v1'
PRECONDITIONS = ['current_geometry', 'target_identity_hypothesis', 'measured_join',
                 'visibility', 'owner_admission']

def plan_schema():
    string = {'type': 'string', 'minLength': 1}
    pose = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 7, 'maxItems': 7}
    waypoint = obj({'index': {'type': 'integer', 'minimum': 1, 'maximum': 8},
        'type': {'const': 'move_pose'}, 'pose': pose,
        'nominal_end_offset_s': {'type': 'number', 'exclusiveMinimum': 0},
        'preconditions': {'const': PRECONDITIONS},
        'prediction_dependencies': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}},
        'boundary_after': {'enum': ['none', 'precontact_handoff', 'phase_end']}})
    return obj({'version': {'const': VERSION}, 'profile_id': {'const': PROFILE},
        'm': {'const': 1}, 'H': {'enum': [1, 4, 6, 8]},
        'world_id': string, 'world_revision': {'type': 'integer', 'minimum': 1},
        'execution_epoch': {'type': 'integer', 'minimum': 0}, 'source_observation_id': string,
        'origin_pose_world': pose,
        'task_binding': obj({'profile': string, 'object_id': string, 'goal_id': {'type': 'string'}}),
        'task': obj({'id': string, 'revision': string, 'stage': {'enum': [
            'T1_PREGRASP_APPROACH', 'T2_TRANSPORT_PREPLACE', 'T3_UNEXPECTED_CHANGE', 'T4_SEMANTIC_SELECTION']}}),
        'read_versions': {'type': 'object', 'minProperties': 1,
            'additionalProperties': {'type': 'integer', 'minimum': 1}},
        'evidence_refs': {'type': 'array', 'items': string, 'minItems': 1, 'uniqueItems': True},
        'waypoints': {'type': 'array', 'items': waypoint, 'minItems': 1, 'maxItems': 8},
        'termination': obj({'kind': {'enum': ['horizon_filled', 'stage_terminal']}, 'reason': string}),
        'semantics': {'const': 'PREDICTED_WAYPOINTS_NOT_MEASURED'}})

def pose_error(a, b):
    for p in (a, b):
        if len(p) != 7 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p):
            raise ValueError('INVALID_POSE')
        if abs(sum(v*v for v in p[3:])-1) > .002: raise ValueError('QUATERNION')
    dot = abs(sum(x*y for x,y in zip(a[3:], b[3:])))
    norm = math.sqrt(sum(x*x for x in a[3:])*sum(x*x for x in b[3:]))
    return math.dist(a[:3], b[:3]), 2*math.acos(min(1., dot/norm))

def validate(plan):
    jsonschema.validate(plan, plan_schema())
    # Clone also rejects nonfinite values in unbounded JSON number fields.
    clone(plan)
    n = len(plan['waypoints'])
    if n > plan['H']: raise ValueError('H_LENGTH')
    terminal = plan['termination']['kind'] == 'stage_terminal'
    if not terminal and n != plan['H']: raise ValueError('H_NOT_FILLED')
    if terminal and plan['waypoints'][-1]['boundary_after'] == 'none':
        raise ValueError('UNJUSTIFIED_STAGE_TERMINAL')
    last = plan['origin_pose_world']
    for i,w in enumerate(plan['waypoints'], 1):
        if w['index'] != i or w['nominal_end_offset_s'] != 2.*i: raise ValueError('WAYPOINT_TIME_OR_INDEX')
        if w['prediction_dependencies'] != list(range(1,i)): raise ValueError('PREDICTION_PREFIX')
        if w['boundary_after'] != 'none' and (i != n or not terminal): raise ValueError('CROSSED_STAGE_BOUNDARY')
        d,a = pose_error(last,w['pose'])
        if d > .05+1e-9 or a > .15+1e-9: raise ValueError('COARSE_STEP_TOO_LARGE')
        if d < 1e-9 and a < 1e-9: raise ValueError('NOOP_PADDING')
        if d < .02 and a < .05 and not (terminal and i == n): raise ValueError('MICROSTEP_PADDING')
        validate_actions([{'type':'move_pose','pose':w['pose']}])
        last=w['pose']

def actions(plan):
    return [{'type':'move_pose','pose':clone(w['pose'])} for w in plan['waypoints']]

def request_schema(world, observation, task, task_binding, H, evidence_ids):
    """Bind all non-planning fields BEFORE the request; A cannot omit a read set."""
    schema=plan_schema()
    state=observation['state']
    constants={'H':H, 'world_id':world['world_id'], 'world_revision':world['world_revision'],
        'execution_epoch':observation['execution_epoch'], 'source_observation_id':observation['observation_id'],
        'origin_pose_world':[*state['actual_grasp_center_world'],*state['flange_pose_world'][3:]],
        'task':task, 'task_binding':task_binding, 'read_versions':world['read_versions'],
        'evidence_refs':evidence_ids}
    for key,value in constants.items(): schema['properties'][key]={'const':clone(value)}
    return schema

def source_stamp(row):
    """The model cannot self-report a hash of its not-yet-produced raw answer."""
    import hashlib
    if row['status'] != 'READY' or row['role'] != 'action' or not row.get('raw'):
        raise ValueError('ACTION_RAW_REQUIRED')
    return {'producer':row['provenance'], 'request_id':row['request_id'],
        'raw_sha256':hashlib.sha256(row['raw'].encode()).hexdigest(),
        'evidence_id':row['evidence_id'], 'wire_sha256':row['wire_sha256'],
        'binding':clone(row['binding']), 'plan_sha256':digest(row['parsed']['result'])}
