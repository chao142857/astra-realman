"""One fail-closed compiler for Broker and bridge (also copied into infer sandbox).

Provider schema is a generation constraint, never the authoritative contract.
The unchanged local schema and role validators MUST both validate returned raw.
Profile: https://developers.openai.com/api/docs/guides/structured-outputs
Conservative, reference-free subset; 64 KiB local cap is stricter than provider.
"""
import copy
import hashlib
import json
import math

VERSION = 'astra.structured_outputs.v1'
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
TYPES = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}
LOCAL_ONLY = {'minLength', 'maxLength', 'uniqueItems', 'minProperties', 'maxProperties'}
KEYS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum',
        'const', 'anyOf', 'description', 'title', 'minimum', 'maximum',
        'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'minItems', 'maxItems',
        'pattern', 'format'}
FORMATS = {'date-time', 'time', 'date', 'duration', 'email', 'hostname', 'ipv4', 'ipv6', 'uuid'}

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def kind(v):
    if v is None: return 'null'
    if type(v) is bool: return 'boolean'
    if type(v) is int: return 'integer'
    if type(v) is float and math.isfinite(v): return 'number'
    if isinstance(v, str): return 'string'
    if isinstance(v, list): return 'array'
    if isinstance(v, dict): return 'object'
    raise ValueError('SCHEMA_NON_JSON_VALUE')

def types_of(values):
    types = sorted({kind(v) for v in values})
    if not types: raise ValueError('SCHEMA_EMPTY_ENUM')
    if 'number' in types and 'integer' in types: types.remove('integer')
    return types[0] if len(types) == 1 else types

def constant(value):
    """Typed exact local binding. No source/provenance is supplied by the model."""
    t = kind(value)
    out = {'type': t, 'const': copy.deepcopy(value)}
    if t == 'object':
        out.update(properties={k: constant(value[k]) for k in sorted(value)},
                   required=sorted(value), additionalProperties=False)
    elif t == 'array':
        out.update(minItems=len(value), maxItems=len(value),
                   items={'type': types_of(value), 'enum': copy.deepcopy(value)} if value else {'type': 'string'})
    return out

def check_provider(schema):
    """Strict recursive provider subset check, with a record for EVERY schema node."""
    import jsonschema
    if len(encoded(schema)) > 65536: raise ValueError('SCHEMA_SIZE_64K')
    jsonschema.Draft202012Validator.check_schema(schema)
    if not isinstance(schema, dict) or schema.get('type') != 'object' or 'anyOf' in schema:
        raise ValueError('SCHEMA_ROOT_OBJECT_REQUIRED')
    rows = []; counts = {'properties': 0, 'enum_values': 0, 'strings': 0, 'depth': 0}
    def visit(s, path, depth):
        def fail(reason): raise ValueError(path + ':' + reason)
        if not isinstance(s, dict): fail('SCHEMA_NODE_OBJECT')
        extra = set(s) - KEYS
        if extra: fail('UNSUPPORTED_KEYWORDS:' + ','.join(sorted(extra)))
        counts['depth'] = max(counts['depth'], depth)
        if depth > 10: fail('SCHEMA_DEPTH_10')
        ts = s.get('type'); ts = ts if isinstance(ts, list) else [ts]
        union = s.get('anyOf')
        if union is not None:
            if not isinstance(union, list) or not union: fail('ANYOF_BRANCHES')
            for i, branch in enumerate(union): visit(branch, path + '/anyOf/' + str(i), depth)
        if ts == [None] and union is not None:
            if set(s) - {'anyOf', 'description', 'title'}: fail('UNTYPED_COMBINATOR_SIBLINGS')
        elif any(t not in TYPES for t in ts) or len(ts) != len(set(ts)): fail('EXPLICIT_TYPE_REQUIRED')
        for key in ('const', 'enum'):
            if key not in s: continue
            values = [s[key]] if key == 'const' else s[key]
            if not isinstance(values, list) or not values: fail('ENUM_EMPTY_OR_TYPE')
            for v in values:
                t = kind(v)
                if t in ('object', 'array'): fail('COMPOUND_ENUM_CONST_LOCAL_ONLY')
                if t not in ts and not (t == 'integer' and 'number' in ts): fail('ENUM_CONST_TYPE')
            text_size = sum(len(v) for v in values if isinstance(v, str))
            counts['strings'] += text_size
            if key == 'enum':
                counts['enum_values'] += len(values)
                if len(values) > 250 and text_size > 15000: fail('ENUM_STRING_LIMIT')
        if 'object' in ts:
            p = s.get('properties'); r = s.get('required')
            if not isinstance(p, dict) or not isinstance(r, list) or len(set(r)) != len(r) or set(r) != set(p): fail('CLOSED_REQUIRED_PROPERTIES')
            if s.get('additionalProperties') is not False: fail('DYNAMIC_OBJECT_NOT_SUPPORTED')
            counts['properties'] += len(p); counts['strings'] += sum(len(k) for k in p)
            for k, v in p.items(): visit(v, path + '/properties/' + k.replace('~', '~0').replace('/', '~1'), depth + 1)
        elif any(k in s for k in ('properties', 'required', 'additionalProperties')): fail('OBJECT_KEYWORD_TYPE')
        if 'array' in ts:
            if not isinstance(s.get('items'), dict): fail('ARRAY_ITEMS_REQUIRED')
            visit(s['items'], path + '/items', depth + 1)
        elif any(k in s for k in ('items', 'minItems', 'maxItems')): fail('ARRAY_KEYWORD_TYPE')
        if any(k in s for k in ('pattern', 'format')) and 'string' not in ts: fail('STRING_KEYWORD_TYPE')
        if 'format' in s and s['format'] not in FORMATS: fail('UNSUPPORTED_FORMAT')
        if any(k in s for k in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf')) and not set(ts) & {'integer', 'number'}: fail('NUMBER_KEYWORD_TYPE')
        for k in ('minItems', 'maxItems'):
            if k in s and (type(s[k]) is not int or s[k] < 0): fail('ARRAY_BOUND_TYPE')
        if s.get('minItems', 0) > s.get('maxItems', float('inf')): fail('ARRAY_BOUNDS')
        rows.append({'path': path, 'status': 'PASS', 'type': s.get('type', 'anyOf')})
    visit(schema, '$', 1)
    if counts['properties'] > 5000 or counts['enum_values'] > 1000 or counts['strings'] > 120000:
        raise ValueError('SCHEMA_AGGREGATE_LIMIT:' + str(counts))
    return {'profile': VERSION, 'status': 'PASS', 'counts': counts, 'bytes': len(encoded(schema)), 'nodes': rows}

def compile_schema(authoritative):
    """Never silently drops arbitrary keywords or opens an object/map."""
    import jsonschema
    if len(encoded(authoritative)) > 65536: raise ValueError('SCHEMA_SIZE_64K')
    jsonschema.Draft202012Validator.check_schema(authoritative)
    def scan_original(s, path):
        if not isinstance(s, dict): raise ValueError(path + ':SCHEMA_NODE_OBJECT')
        unsupported=set(s)-KEYS-LOCAL_ONLY-{'oneOf','$schema'}
        if unsupported: raise ValueError(path+':UNSUPPORTED_KEYWORDS:'+','.join(sorted(unsupported)))
        if '$schema' in s and s['$schema']!=DIALECT:raise ValueError(path+':UNSUPPORTED_DIALECT')
        for key,value in s.get('properties',{}).items():scan_original(value,path+'/properties/'+key)
        for key in ('items','additionalProperties'):
            if isinstance(s.get(key),dict):scan_original(s[key],path+'/'+key)
        for key in ('anyOf','oneOf'):
            for i,child in enumerate(s.get(key,[])):scan_original(child,path+'/'+key+'/'+str(i))
    scan_original(authoritative,'$')
    changes = []
    def visit(s, path):
        if not isinstance(s, dict): raise ValueError(path + ':SCHEMA_NODE_OBJECT')
        s = copy.deepcopy(s)
        def note(reason): changes.append({'path': path, 'reason': reason, 'enforced': 'authoritative_local'})
        if '$schema' in s:
            s.pop('$schema');note('2020-12 dialect annotation retained locally')
        if 'const' in s:
            value = s['const']; inferred = constant(value)
            jsonschema.Draft202012Validator(s).validate(value)
            if 'type' in s and s['type'] != inferred['type']:
                ts = s['type'] if isinstance(s['type'], list) else [s['type']]
                if inferred['type'] not in ts and not (inferred['type'] == 'integer' and 'number' in ts):
                    raise ValueError(path + ':CONST_TYPE_CONFLICT')
            # Expand frozen dynamic keys, keeping original map constraints local.
            if kind(value) in ('object', 'array'):
                retained = {k:v for k,v in s.items() if k not in ('const','type','properties','required','additionalProperties','items','minItems','maxItems')}
                s = {**inferred, **retained}; s.pop('const'); note('compound const expanded; exact equality remains local')
            else:
                s.setdefault('type', inferred['type']); s['enum'] = [s.pop('const')]
                note('scalar const compiled as typed singleton enum')
        elif 'type' not in s and 'enum' in s:
            s['type'] = types_of(s['enum']); note('explicit enum type inferred')
        if 'oneOf' in s:
            if 'anyOf' in s: raise ValueError(path + ':MIXED_COMBINATORS')
            s['anyOf'] = s.pop('oneOf'); note('oneOf generation union; exclusive match retained locally')
        for key in LOCAL_ONLY & set(s):
            s.pop(key); note(key + ' retained only in authoritative local contract')
        if 'properties' in s:
            s['properties'] = {k:visit(v,path+'/properties/'+k) for k,v in s['properties'].items()}
        if 'items' in s: s['items'] = visit(s['items'], path+'/items')
        if 'anyOf' in s: s['anyOf'] = [visit(v,path+'/anyOf/'+str(i)) for i,v in enumerate(s['anyOf'])]
        return s
    provider = visit(authoritative, '$')
    audit = check_provider(provider)
    audit.update(authoritative_sha256=sha(authoritative), provider_sha256=sha(provider), changes=changes)
    return provider, audit

def validate_local(answer, authoritative, provider):
    import jsonschema
    # This also refuses NaN/Infinity, unlike ordinary JSON schema number checks.
    encoded(answer)
    for schema in (authoritative, provider):
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(answer)
