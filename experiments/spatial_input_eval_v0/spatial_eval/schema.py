"""Strict JSON and shared output contracts, using only the standard library."""
import json
import math
from pathlib import Path

CONDITIONS = ('RGB_MULTI_VIEW', 'RGB_RECON_3D', 'RGB_ORACLE_3D')
KINDS = ('understanding', 'placement', 'path')

def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY:' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('NONFINITE_JSON:' + value)
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    finite_tree(result)
    return result

def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('NONFINITE_NUMBER')
    if isinstance(value, dict):
        for v in value.values(): finite_tree(v)
    if isinstance(value, list):
        for v in value: finite_tree(v)

def read(path):
    return strict_json(Path(path).read_text())

def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('SCHEMA_FIELDS:' + ','.join(required))

def number(v):
    return type(v) in (int, float) and math.isfinite(v)

def vector(v, n):
    if not isinstance(v, list) or len(v) != n or not all(number(x) for x in v):
        raise ValueError('FINITE_VECTOR_' + str(n))
    return v

def quaternion(v):
    vector(v, 4)
    if abs(sum(x*x for x in v) - 1) > 1e-4:
        raise ValueError('UNIT_QUATERNION_REQUIRED')
    return v

def obj(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}

def arr(n):
    return {'type':'array', 'items':{'type':'number'}, 'minItems':n, 'maxItems':n}

def nullable(s):
    return {'anyOf':[s, {'type':'null'}]}

def output_schema(kind):
    if kind == 'understanding':
        return obj({'answers':{'type':'array', 'items':obj({
            'question_id':{'type':'string'}, 'relation':nullable({'type':'string'}),
            'scalar_m':nullable({'type':'number'}), 'vector_m':nullable(arr(3)),
            'fits':nullable({'type':'boolean'})})}})
    return obj({'object_id':{'type':'string'}, 'position_m':arr(3), 'quaternion_wxyz':arr(4),
                'waypoints_m':{'type':'array', 'items':arr(3)}})

def parse_prediction(raw, task):
    p = strict_json(raw)
    if task['kind'] == 'understanding':
        fields(p, ['answers'])
        if not isinstance(p['answers'], list): raise ValueError('ANSWERS_ARRAY')
        expected = {q['question_id']:q for q in task['questions']}
        seen = set()
        slots = {'relation':'relation', 'position':'vector_m', 'size':'vector_m',
                 'height':'scalar_m', 'gap':'scalar_m', 'fit':'fits'}
        for a in p['answers']:
            fields(a, ['question_id','relation','scalar_m','vector_m','fits'])
            qid = a['question_id']
            if not isinstance(qid,str) or qid not in expected or qid in seen: raise ValueError('ANSWER_ID')
            seen.add(qid)
            slot = slots[expected[qid]['type']]
            if any(a[k] is not None for k in slots.values() if k != slot): raise ValueError('UNUSED_ANSWER_FIELDS')
            if slot == 'vector_m': vector(a[slot],3)
            elif slot == 'scalar_m' and not number(a[slot]): raise ValueError('ANSWER_NUMBER')
            elif slot == 'fits' and type(a[slot]) is not bool: raise ValueError('ANSWER_BOOL')
            elif slot == 'relation' and a[slot] not in ('less','equal','greater'): raise ValueError('ANSWER_RELATION')
        if seen != set(expected): raise ValueError('MISSING_ANSWERS')
    else:
        fields(p, ['object_id','position_m','quaternion_wxyz','waypoints_m'])
        if not isinstance(p['object_id'],str): raise ValueError('OBJECT_ID_STRING')
        vector(p['position_m'],3); quaternion(p['quaternion_wxyz'])
        if not isinstance(p['waypoints_m'],list) or len(p['waypoints_m']) > 64: raise ValueError('WAYPOINT_COUNT')
        for v in p['waypoints_m']: vector(v,3)
        if task['kind'] == 'path' and not p['waypoints_m']: raise ValueError('PATH_REQUIRED')
        if task['kind'] == 'placement' and p['waypoints_m']: raise ValueError('PLACEMENT_WAYPOINTS_EMPTY')
    return p
