"""Fixed old-log E3 screening. Pure projections; no robot/camera/executor imports.

The only inference route is an explicitly requested, once-only local CLI batch.
Original H5D1 parsing, measured-history checks, image checks and archive are reused.
"""
import copy
import csv
import hashlib
import json
import math
import time
import statistics
from collections import Counter
from pathlib import Path

from io_utils import ROOT, read_json, strict_json, new_run, write_json
from history_diagnostics import TransitionHistory, decode, DECISION_SCHEMA
from scripts.prepare_history_replay import decision_observation, ready_time
from replay_evidence import image_record

CONDITIONS = ('T0', 'T1', 'T2', 'T3')
CHECKPOINTS = ('A06', 'A12', 'A28', 'A36', 'B06', 'B12', 'B22', 'B25')
CODE_FILES = ('e3_history_screen.py', 'scripts/run_e3_screen.py',
              'scripts/codex_astra_mac_bridge.py', 'scripts/prepare_history_replay.py',
              'history_diagnostics.py', 'left_terminal.py', 'decision_backends.py',
              'io_utils.py', 'replay_evidence.py', 'episode_archive.py',
              'schema/left_decision.schema.json')
CODEC_GUIDE = ('Lossless JSON dictionary: recursively replace an object containing only $e3 '
               'with dictionary[index]. $literal contains escaped key/value pairs. '
               'All other values are literal. Decode data before reading history. '
               'For budgeted history, protected contains measured facts; events contains '
               'only selected complete transitions, oldest first. Omitted facts are unknown, '
               'not false. Only current images are attached. No prior model opinions included.')


def wire(value):
    # Match the reused Mac bridge's actual stdin serialization (spaces included).
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(wire(value).encode()).hexdigest()


def size(value):
    return len(wire(value).encode())


def pack(value):
    """Deduplicate identical JSON subtrees; retain types, order, null and all numbers."""
    counts = Counter()
    def scan(v):
        if isinstance(v, (dict, list, str)) and size(v) >= 64:
            counts[wire(v)] += 1
        if isinstance(v, dict):
            for child in v.values(): scan(child)
        elif isinstance(v, list):
            for child in v: scan(child)
    scan(value)
    table, indices = [], {}
    def encode(v):
        key = wire(v)
        if counts[key] > 1 and key in indices:
            return {'$e3': indices[key]}
        if isinstance(v, dict):
            pairs = [(k, encode(x)) for k, x in v.items()]
            out = ({'$literal': pairs} if '$e3' in v or '$literal' in v else dict(pairs))
        elif isinstance(v, list): out = [encode(x) for x in v]
        else: out = v
        if counts[key] > 1:
            indices[key] = len(table); table.append(out)
            return {'$e3': indices[key]}
        return out
    data = encode(value)
    return {'encoding': 'e3-json-dictionary-v1', 'guide': CODEC_GUIDE,
            'dictionary': table, 'data': data}


def unpack(value):
    if value['encoding'] != 'e3-json-dictionary-v1': raise ValueError('CODEC_VERSION')
    table = value['dictionary']
    def dec(v, stack=()):
        if isinstance(v, dict):
            if set(v) == {'$e3'}:
                n = v['$e3']
                if type(n) is not int or not 0 <= n < len(table) or n in stack:
                    raise ValueError('INVALID_REFERENCE')
                return dec(table[n], stack+(n,))
            if set(v) == {'$literal'}:
                return {k: dec(x, stack) for k, x in v['$literal']}
            return {k: dec(x, stack) for k, x in v.items()}
        if isinstance(v, list): return [dec(x, stack) for x in v]
        return v
    return dec(value['data'])


def facts(value, path=''):
    """JSON pointer leaves, including empty containers; type-sensitive audit inventory."""
    if isinstance(value, dict) and value:
        return {p: x for k, v in value.items() for p, x in facts(
            v, path+'/'+k.replace('~', '~0').replace('/', '~1')).items()}
    if isinstance(value, list) and value:
        return {p: x for i, v in enumerate(value) for p, x in facts(v, path+'/'+str(i)).items()}
    return {path: value}


def has_issue(event):
    # No claim of resolution is inferred from a later successful, different command.
    return (event.get('execution_status') not in ('EXECUTED', 'MODEL_DONE', 'NOOP')
            or bool(event.get('execution_error')) or bool(event.get('readback_error'))
            or event.get('readback_available') is not True
            or any(event.get('after_validation_errors', [])))


def protected_history(history):
    """Common facts for both lossy arms; no inferred object identity/stage/contact."""
    keys = ('version', 'episode_id', 'step', 'decision_observation_id', 'after_observation_id',
            'proposed_action', 'executed_command', 'hardware_commands_sent', 'executed_channels',
            'execution_status', 'execution_error', 'sdk_result', 'actual_after_pose',
            'gripper_after', 'robot_errors', 'readback_error', 'readback_available',
            'after_validation_errors', 'object_state', 'timestamps')
    protected, mapping = [], {}
    for i, event in enumerate(history):
        # Always retain order and object uncertainty for every event. Retain the latest
        # complete measured state and unresolved failure facts, including original target.
        selected = keys if i == len(history)-1 or has_issue(event) else (
            'episode_id', 'step', 'execution_status', 'object_state', 'timestamps')
        record = {k: copy.deepcopy(event[k]) for k in selected if k in event}
        if has_issue(event): record['feasibility'] = copy.deepcopy(event.get('feasibility'))
        protected.append(record)
        for pointer in facts(record):
            mapping['/'+str(i)+pointer] = '/protected/'+str(i)+pointer
    return protected, mapping


def project(history, condition):
    start = time.monotonic()
    t1 = pack(history)
    if wire(unpack(t1)) != wire(history): raise ValueError('T1_ROUNDTRIP')
    budget = size(t1)//2
    selected, fallback, mapping = list(range(len(history))), None, {}
    if condition == 'T0': projected = copy.deepcopy(history)
    elif condition == 'T1': projected = t1
    elif condition in ('T2', 'T3'):
        protected, mapping = protected_history(history)
        def candidate(indices):
            return pack({'protected': protected, 'events': [history[i] for i in sorted(indices)]})
        projected = candidate([]); selected = []
        if size(projected) > budget:
            fallback = 'PROTECTED_ENVELOPE_EXCEEDS_50_PERCENT_BUDGET'
            projected, selected, mapping = t1, list(range(len(history))), {}
        else:
            recent = list(reversed(range(len(history))))
            if condition == 'T2': priority = recent
            else:
                issues = [i for i in recent if has_issue(history[i])]
                holding = [i for i in recent if history[i].get('object_state', {}).get('holding')
                           not in (None, 'unknown')]
                priority = list(dict.fromkeys(recent[:1] + issues + holding[:1] + recent))
            for i in priority:
                proposed = candidate(selected+[i])
                if size(proposed) <= budget:
                    selected.append(i); projected = proposed
                elif condition == 'T2':
                    # Recency baseline is a contiguous suffix, never skip a larger recent
                    # event to fit an older event. T3 may select by declared relevance.
                    break
            selected.sort()
    else: raise ValueError('UNKNOWN_CONDITION')
    if condition in ('T0','T1') or fallback:
        mapping = {p: p for p in facts(history)}
    else:
        for j, i in enumerate(selected):
            for p in facts(history[i]): mapping['/'+str(i)+p] = '/events/'+str(j)+p
    audit = [{'source_pointer':'/history'+p, 'value':v,
              'retained':p in mapping, 'decoded_pointer':mapping.get(p),
              'reason':'retained verbatim' if p in mapping else 'whole-event budget omission'}
             for p, v in facts(history).items()]
    # Check every claimed retained fact against the actual decoded request.
    decoded = projected if condition == 'T0' else unpack(projected)
    decoded_facts = facts(decoded)
    for row in audit:
        if row['retained'] and wire(decoded_facts[row['decoded_pointer']]) != wire(row['value']):
            raise ValueError('FACT_PRESERVATION_MISMATCH')
    meta = {'condition':condition,'effective_condition':'T1' if fallback else condition,
            't1_roundtrip':True, 'budget_bytes':budget if condition in ('T2','T3') else None,
            't1_history_bytes':size(t1), 'actual_history_bytes':size(projected),
            'fallback_reason':fallback, 'selected_complete_steps':[history[i]['step'] for i in selected],
            'retained_facts':sum(x['retained'] for x in audit), 'total_facts':len(audit),
            'projection_latency_s':time.monotonic()-start,
            'budget_unit':'UTF-8 bytes including codec guide/dictionary; NOT tokens'}
    return projected, audit, meta


def csv_write(path, rows):
    if not rows: return
    with path.open('w', newline='', encoding='utf-8') as out:
        w = csv.DictWriter(out, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def check_command(command):
    configs = [command[i+1] for i, x in enumerate(command[:-1]) if x == '-c']
    if [x for x in configs if x.startswith('model_reasoning_effort=')] != ['model_reasoning_effort="medium"']:
        raise ValueError('ACTUAL_MEDIUM_REQUIRED')
    if command[command.index('--model')+1] != 'gpt-6-astra': raise ValueError('MODEL_MISMATCH')
    if command.count('--image') != 3: raise ValueError('THREE_IMAGES_REQUIRED')


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    index = read_json(source/'source_index.json')
    if tuple(c['id'] for c in index['checkpoints']) != CHECKPOINTS: raise ValueError('FIXED_EIGHT_CHECKPOINTS')
    for name, item in index['files'].items():
        p = (source/name).resolve()
        if not p.is_relative_to(source) or hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('SOURCE_HASH_MISMATCH:'+name)
    new_run(output)
    rows, labels, source_checks = [], [], []
    for count, cp in enumerate(index['checkpoints']):
        step = source/cp['local_step']; run = step.parent
        original = read_json(step/'model_input.json')
        if strict_json((step/'decision/prompt.txt').read_text()) != original: raise ValueError('ACTUAL_PROMPT_MISMATCH')
        if read_json(step/'decision/attachments.json') != original['images_in_attachment_order']:
            raise ValueError('ACTUAL_ATTACHMENT_MISMATCH')
        check_command(read_json(step/'decision/command.json'))
        schema = read_json(run/'action_schema.json')
        if schema != original['action_schema'] or schema != read_json(DECISION_SCHEMA):
            raise ValueError('ORIGINAL_H5D1_SCHEMA_CHANGED')
        obs = decision_observation(step)
        obs['decision_ready_at'] = ready_time(obs)
        images = []
        # Preserve original prompt path strings; --image transports local identical PNGs.
        # As with the original Mac bridge, paths in context are provenance, not tool access.
        for camera, src in zip(original['images_in_attachment_order'], cp['images']):
            if camera['image_path'] != src['source']: raise ValueError('IMAGE_ORDER_MISMATCH')
            local = str(source/src['relative_path'])
            item = dict(camera, image_path=local, sha256=src['sha256'])
            evidence = image_record(item, original['observation_id'])
            if not evidence['available'] or [evidence['width'],evidence['height']] != [640,480]:
                raise ValueError('IMAGE_EVIDENCE_INVALID')
            images.append(item)
        if len(images) != 3 or [x['role'] for x in images] != ['left_wrist','tabletop','overhead']:
            raise ValueError('ORIGINAL_THREE_VIEWS_REQUIRED')
        replay_obs = copy.deepcopy(obs)
        for c, item in zip(replay_obs['cameras'], images):
            if c['serial'] != item['serial']: raise ValueError('OBS_IMAGE_ORDER')
            c['image_path'] = item['image_path']
        history = TransitionHistory('H5D1', original['episode_id'])
        for n in range(1, cp['step']): history.append(read_json(run/f'step-{n:02}/transition.json'))
        replayed = history.context(replay_obs, schema, cp['step'])
        replayed['images_in_attachment_order'] = copy.deepcopy(original['images_in_attachment_order'])
        if replayed != original: raise ValueError('ORIGINAL_REPLAY_CONTEXT_DIFF:'+cp['id'])
        source_checks.append({'checkpoint':cp['id'],'replay_equal':True,'task':original['task'],
            'history_steps':[t['step'] for t in original['history']], 'schema_sha256':digest(schema),
            'actual_command_sha256':hashlib.sha256((step/'decision/command.json').read_bytes()).hexdigest(),
            'actual_effort':'medium','profile_effort':read_json(run/'history_profile.json')['reasoning_effort']})
        # Balanced, predeclared order; each condition occupies each position twice.
        order = CONDITIONS[count%4:]+CONDITIONS[:count%4]
        for condition in order:
            request_id = cp['id']+'-'+condition
            folder = new_run(output/request_id)
            value, inventory, meta = project(original['history'], condition)
            context = copy.deepcopy(original); context['history'] = value
            write_json(folder/'model_input.json', context)
            (folder/'prompt.txt').write_text(wire(context), encoding='utf-8')
            write_json(folder/'schema.json', schema)
            write_json(folder/'attachments.json', images)
            write_json(folder/'fact_inventory.json', inventory)
            write_json(folder/'projection.json', meta)
            write_json(folder/'replay_manifest.json', dict(cp, mode='FIXED_OBSERVATION_NOT_ROLLOUT',
                original_prompt_sha256=hashlib.sha256((step/'decision/prompt.txt').read_bytes()).hexdigest(),
                task_unchanged=True, non_history_fields_unchanged=True, output_schema_unchanged=True))
            rows.append(dict(request_order=len(rows)+1, request_id=request_id, checkpoint=cp['id'],
                task=original['task'], source_run=cp['run'], source_step=cp['step'],
                observation_id=original['observation_id'], history_steps=';'.join(str(t['step']) for t in original['history']),
                prompt=str(folder/'prompt.txt'), prompt_sha256=hashlib.sha256((folder/'prompt.txt').read_bytes()).hexdigest(),
                fact_inventory_sha256=hashlib.sha256((folder/'fact_inventory.json').read_bytes()).hexdigest(),
                schema_sha256=digest(schema), images=';'.join(x['image_path'] for x in images),
                image_sha256=';'.join(x['sha256'] for x in images), input_bytes=size(context), **meta))
        labels.append({'checkpoint':cp['id'],'observer_1':None,'observer_2':None,
            'current_visible_facts':None,'object_identity_and_stage':None,
            'holding_or_contact':'UNKNOWN_UNLABELED','acceptable_action_set':None,
            'ik_rejected_not_executed_distinction':None,'history_facts_required_for_judgment':None,
            'occlusion_and_ambiguity':None,'evidence_references':[], 'adjudication':None,
            'post_hoc_never_model_input':True})
    for cp in CHECKPOINTS:
        pair = [r for r in rows if r['checkpoint']==cp and r['condition'] in ('T2','T3')]
        matched = abs(pair[0]['actual_history_bytes']-pair[1]['actual_history_bytes'])/max(r['actual_history_bytes'] for r in pair) <= .05
        for r in rows:
            if r['checkpoint']==cp: r['t2_t3_within_5_percent_bytes'] = matched
    manifest = {'mode':'E3_OFFLINE_PREPARED_NOT_INFERRED','request_limit':32, 'timeout_s':120,
        'hardware_commands_sent':0,'model_calls':0,'synthetic':False,'source':str(source),
        'source_index_sha256':hashlib.sha256((source/'source_index.json').read_bytes()).hexdigest(),
        'conditions':list(CONDITIONS),'checkpoints':list(CHECKPOINTS),'requests':rows,
        'source_checks':source_checks,'no_retry':True,'future_outcomes_not_valid_counterfactual_labels':True,
        'code_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in CODE_FILES}}
    write_json(output/'manifest.json',manifest)
    csv_write(output/'input_index.csv',rows)
    write_json(output/'human_labels.template.json',labels)
    write_json(output/'summary.json',{'status':'OFFLINE_PREPARED','model_calls':0,'hardware_commands_sent':0})
    report(output)
    return manifest


def validate_batch(batch):
    batch = Path(batch).resolve(); manifest = read_json(batch/'manifest.json')
    rows = manifest['requests']
    for name, sha in manifest['code_sha256'].items():
        if name not in CODE_FILES or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('FROZEN_CODE_CHANGED:'+name)
    if set(manifest['code_sha256'])!=set(CODE_FILES): raise ValueError('CODE_MANIFEST_INCOMPLETE')
    if len(rows) != 32 or {(r['checkpoint'],r['condition']) for r in rows} != {(c,t) for c in CHECKPOINTS for t in CONDITIONS}:
        raise ValueError('NOT_FIXED_32_MATRIX')
    source = Path(manifest['source'])
    if hashlib.sha256((source/'source_index.json').read_bytes()).hexdigest()!=manifest['source_index_sha256']:
        raise ValueError('SOURCE_INDEX_CHANGED')
    for row in rows:
        if row['request_id'] != row['checkpoint']+'-'+row['condition']: raise ValueError('REQUEST_ID_MISMATCH')
        folder = batch/row['request_id']; context = read_json(folder/'model_input.json')
        if hashlib.sha256((folder/'prompt.txt').read_bytes()).hexdigest()!=row['prompt_sha256'] or strict_json((folder/'prompt.txt').read_text()) != context:
            raise ValueError('FROZEN_REQUEST_CHANGED')
        if hashlib.sha256((folder/'fact_inventory.json').read_bytes()).hexdigest()!=row['fact_inventory_sha256']:
            raise ValueError('FACT_INVENTORY_CHANGED')
        schema = read_json(folder/'schema.json')
        if digest(schema)!=row['schema_sha256'] or schema!=context['action_schema'] or schema!=read_json(DECISION_SCHEMA):
            raise ValueError('SCHEMA_CHANGED')
        images = read_json(folder/'attachments.json')
        if len(images)!=3 or ';'.join(c['sha256'] for c in images)!=row['image_sha256']:
            raise ValueError('ATTACHMENTS_CHANGED')
        if [c['role'] for c in images] != ['left_wrist','tabletop','overhead']:
            raise ValueError('ATTACHMENT_ROLE_CHANGED')
        if any(not image_record(c)['available'] for c in images): raise ValueError('IMAGE_CHANGED')
    return manifest


def report(batch):
    batch = Path(batch); manifest = read_json(batch/'manifest.json'); rows=[]
    for r in manifest['requests']:
        p = batch/r['request_id']/'result.json'; result = read_json(p) if p.exists() else {}
        rows.append({k:r[k] for k in ('request_order','request_id','checkpoint','condition','input_bytes',
            'actual_history_bytes','budget_bytes','fallback_reason','projection_latency_s')} | {
            'status':result.get('status','NOT_RUN'), 'request_attempted':result.get('request_attempted',False),
            'backend_latency_s':result.get('backend_latency_s'), 'total_latency_s':result.get('total_latency_s'),
            'input_tokens':result.get('usage',{}).get('input_tokens'),
            'cached_input_tokens':result.get('usage',{}).get('cached_input_tokens'),
            'output_tokens':result.get('usage',{}).get('output_tokens'), 'error':result.get('error')})
    csv_write(batch/'request_report.csv', rows)
    write_report = {'planned':32,'attempted':sum(r['request_attempted'] for r in rows),
        'valid':sum(r['status']=='VALID_H5D1' for r in rows),'hardware_commands_sent':0,
        'unknown_usage_is_not_zero':True,'fixed_observation_not_physical_success_rate':True,
        't2_t3_identical_inputs':sum(
            (batch/(cp+'-T2')/'prompt.txt').read_bytes()==(batch/(cp+'-T3')/'prompt.txt').read_bytes()
            for cp in CHECKPOINTS),
        'rows':rows}
    groups={}
    for c in CONDITIONS:
        selected=[r for r in rows if r['condition']==c]
        latency=[r['backend_latency_s'] for r in selected if r['backend_latency_s'] is not None]
        groups[c]={'planned':8,'attempted':sum(r['request_attempted'] for r in selected),
            'valid':sum(r['status']=='VALID_H5D1' for r in selected),
            'median_backend_latency_s':statistics.median(latency) if latency else None,
            'fallbacks':sum(r['fallback_reason'] is not None for r in selected),
            'token_totals_known_only':{k:sum(r[k] for r in selected if r[k] is not None)
                if any(r[k] is not None for r in selected) else None
                for k in ('input_tokens','cached_input_tokens','output_tokens')},
            'usage_missing_requests':sum(r['request_attempted'] and r['input_tokens'] is None for r in selected)}
    write_report['by_condition']=groups
    # Rebuildable report only; raw inputs/results never overwritten.
    (batch/'request_report.json').write_text(json.dumps(write_report,ensure_ascii=False,indent=2))
    return write_report


def infer(batch, *, authorize_32=False, executable='/opt/homebrew/bin/codex', run_root='/private/tmp/codex-astra-bridge'):
    if not authorize_32: raise ValueError('EXPLICIT_32_REQUEST_OPT_IN_REQUIRED')
    batch = Path(batch).resolve(); manifest = validate_batch(batch)
    # Exclusive batch claim. Even a crash/interrupt must not silently repeat calls.
    with (batch/'inference.claim').open('x') as f: f.write(str(time.time()))
    from scripts.codex_astra_mac_bridge import command, infer as local_infer
    from decision_backends import check_events
    import base64
    import threading
    stop = threading.Event()
    try:
        for row in manifest['requests']:
            folder=batch/row['request_id']; start=time.monotonic()
            result={'status':'BACKEND_ERROR','request_attempted':False,'usage':{},'hardware_commands_sent':0}
            try:
                context=read_json(folder/'model_input.json'); schema=read_json(folder/'schema.json')
                images=read_json(folder/'attachments.json')
                # Reuse the exact official local CLI transport. main() (SSH tunnel) is
                # never called; SDKs and live observations are unavailable here.
                check_command(command(folder,[Path(c['image_path']) for c in images],executable))
                payload={'context':context,'schema':schema,
                         'images':[base64.b64encode(Path(c['image_path']).read_bytes()).decode() for c in images]}
                write_json(folder/'dispatch.json',{'request_attempted':True,'at':time.time(),'retry':False})
                result['request_attempted']=True
                response=local_infer(payload,stop,executable=executable,run_root=run_root)
                decision=new_run(folder/'decision')
                write_json(decision/'command.json',response['command']); check_command(response['command'])
                for name,key in (('astra_raw.txt','raw'),('events.jsonl','events'),('stderr.log','stderr')):
                    (decision/name).write_text(response[key],encoding='utf-8')
                write_json(decision/'backend_result.json',response)
                result['backend_latency_s']=response['latency_s']
                result['backend_log']=response['local_log']
                for line in response['events'].splitlines():
                    try: event=json.loads(line)
                    except ValueError: continue
                    if event.get('type')=='turn.completed':
                        usage=event.get('usage') or {}
                        result['usage']={k:v for k,v in usage.items() if type(v) is int and v>=0} if isinstance(usage,dict) else {}
                if response['error'] or response['return_code']!=0:
                    raise ValueError('BACKEND_FAILURE:'+str(response['error'] or response['return_code']))
                if strict_json(check_events(response['events']))!=strict_json(response['raw']):
                    raise ValueError('FINAL_MESSAGE_MISMATCH')
                result['status']='OUTPUT_INVALID'
                diagnostics, action=decode(response['raw'],'H5D1')
                write_json(folder/'diagnostics.json',diagnostics); write_json(folder/'parsed_action.json',action)
                result['status']='VALID_H5D1'
            except KeyboardInterrupt:
                stop.set(); result['status']='CANCELLED'; result['error']='HUMAN_INTERRUPT'; raise
            except Exception as exc: result['error']=type(exc).__name__+':'+str(exc)
            finally:
                result['total_latency_s']=time.monotonic()-start
                write_json(folder/'result.json',result); report(batch)
                print(row['request_id']+' | '+result['status']+' | no hardware',flush=True)
    finally:
        final=report(batch)
        (batch/'summary.json').write_text(json.dumps({'status':'OFFLINE_REQUEST_BATCH_FINISHED_OR_INTERRUPTED',
            'model_calls':final['attempted'],'hardware_commands_sent':0,'planned':32,
            'valid':final['valid'],'physical_success':'NOT_EVALUATED'},indent=2))


def archive(batch):
    # Existing portable archive exports requests and original images. Historical
    # image references are not supplied historical images; missing refs stay warnings.
    from episode_archive import archive_episode
    return archive_episode(Path(batch),'E3 fixed observations: 32 requests, no hardware')
