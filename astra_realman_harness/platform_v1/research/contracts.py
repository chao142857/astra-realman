"""Versioned research data contracts, independent of scene access."""
import hashlib
import json
import math
import jsonschema
from sim_skills.full_pnp.wire import strict_json, obj
from sim_skills.full_pnp.protocol import validate_actions

VERSION = 'astra.research.adapters.v1'
WORLD_VERSION = 'astra.world.public.v1'
PLAN_VERSION = 'astra.action_chunk_plan.v1'
ROLES = ('semantic_e0', 'action', 'local_reground')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

def clone(value):
    return strict_json(json.dumps(value, allow_nan=False))

def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('RESEARCH_FIELDS')

def schema_check(schema):
    if len(json.dumps(schema, allow_nan=False)) > 65536:
        raise ValueError('SCHEMA_SIZE')
    def scan(x):
        if isinstance(x, dict):
            if any(k in x for k in ('$ref', '$dynamicRef', '$recursiveRef')):
                raise ValueError('SCHEMA_REFERENCES_DISABLED')
            for v in x.values(): scan(v)
        elif isinstance(x, list):
            for v in x: scan(v)
    scan(schema)
    jsonschema.Draft202012Validator.check_schema(schema)

def plan_schema():
    action = {'oneOf': [
        obj({'type': {'const': 'move_pose'}, 'pose': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 7, 'maxItems': 7}}),
        obj({'type': {'const': 'gripper'}, 'opening': {'type': 'number', 'minimum': 0, 'maximum': 1}}),
        obj({'type': {'const': 'hold'}, 'seconds': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 2}})]}
    return obj({'version': {'const': PLAN_VERSION}, 'H': {'enum': [1, 4, 6, 8]},
        'waypoints': {'type': 'array', 'items': action, 'minItems': 1, 'maxItems': 8},
        'world_id': {'type': 'string'}, 'world_revision': {'type': 'integer', 'minimum': 1},
        'source_observation_id': {'type': 'string'}, 'execution_epoch': {'type': 'integer', 'minimum': 0},
        'task_binding': obj({'profile': {'type': 'string'}, 'object_id': {'type': 'string'}, 'goal_id': {'type': 'string'}}),
        'semantics': {'const': 'PREDICTED_WAYPOINTS_NOT_MEASURED'}})

def validate_plan(plan):
    if plan.get('version') == 'astra.action_chunk_plan.v2':
        from .chunk_plan import validate
        return validate(plan)
    jsonschema.validate(plan, plan_schema())
    if type(plan['H']) is not int or len(plan['waypoints']) != plan['H']:
        raise ValueError('H_LENGTH')
    for action in plan['waypoints']: validate_actions([action])

def micro_chunks(actions):
    """One action per owner submission. Legacy gripper barriers remain intact."""
    result, part = [], []
    for a in actions:
        part.append(clone(a))
        if len(part) == 1 or a['type'] == 'gripper':
            validate_actions(part); result.append(part); part = []
    if part: validate_actions(part); result.append(part)
    return result

def semantic_schema():
    region = obj({'entity_id': {'type': 'string'}, 'label': {'type': 'string'},
        'attachment_id': {'type': 'string'},
        'bbox': {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'minItems': 4, 'maxItems': 4},
        'identity_status': {'enum': ['hypothesis', 'unknown']}})
    return obj({'regions': {'type': 'array', 'items': region, 'maxItems': 32},
        'association': {'type': ['string', 'null']}})
