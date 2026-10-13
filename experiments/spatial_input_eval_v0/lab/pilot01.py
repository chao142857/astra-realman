#!/usr/bin/env python3
"""Pilot 01: one durable reservation and one original bridge dispatch per `next`.

This coordinator does not implement inference, change prompts, or score answers.
It calls the existing V0 runner and applies the user's stricter batch stop rules.
"""
import argparse
import base64
import copy
import datetime
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
from contextlib import contextmanager

from spatial_eval import cli
from spatial_eval.adapter import PARAMETERS, HARNESS
from spatial_eval.inputs import build_input, load_snapshot
from spatial_eval.mac_bridge import validate_context
from spatial_eval.schema import read, strict_json

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parents[1]
SUITE = MODULE/'evidence/lab_20261013/sim_suite_initial'
HISTORY = MODULE/'evidence/authorized_mac_A_s5_second'
CONFIG = MODULE/'lab/mac_bridge.yanglab.json'
A, C = 'RGB_MULTI_VIEW', 'RGB_ORACLE_3D'
SCENES = ['lab_s1_relations', 'lab_s2_occlusion', 'lab_s3_narrow_container',
          'lab_s4_rotated_fit', 'lab_s5_placement', 'lab_s6_held_object_detour']
BUDGET = 24


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    """Atomic durable state: a crash cannot erase a reservation already dispatched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    with temp.open('w') as out:
        json.dump(value, out, ensure_ascii=False, allow_nan=False, indent=2)
        out.write('\n'); out.flush(); os.fsync(out.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def locked(root):
    # One global lab lock covers all output directories; flock is released on exit.
    with Path('/tmp/astra-spatial-pilot01.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('ANOTHER_PILOT_RUNNER_ACTIVE') from None
        yield


def schedule():
    priority = [(4, 'plan', C), (5, 'plan', A), (5, 'plan', C)]
    priority += [(s, 'understand', c) for s in (1, 2, 3) for c in (A, C)]
    rest = [(s, t, c) for s in range(6) for t in ('understand', 'plan') for c in (A, C)
            if (s, t, c) not in priority and (s, t, c) != (4, 'plan', A)]
    jobs = priority+rest+[(4, 'plan', A)]
    require(len(jobs) == BUDGET, 'SCHEDULE_BUDGET')
    return [dict(index=i+1, scene_id=SCENES[s], task_id=t, condition=c,
                 role='independent_repeat' if i == 23 else 'primary',
                 stage=1 if i < 3 else 2 if i < 9 else 4 if i == 23 else 3,
                 directory=f'runs/{i+1:02d}_{SCENES[s]}_{t}_{"A" if c == A else "C"}')
            for i, (s, t, c) in enumerate(jobs)]


def key(job):
    return '/'.join(job[x] for x in ('scene_id', 'task_id', 'condition'))


def payload_for(scene, task_id, condition):
    s = load_snapshot(SUITE/scene/'snapshot.json')
    t = next(t for t in s['task'] if t['task_id'] == task_id)
    context, manifest, images = build_input(s, t, condition)
    validate_context(context, images)
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    from scripts.structured_outputs import compile_schema
    from scripts.codex_astra_mac_bridge import validate_payload
    schema, _ = compile_schema(context['output_schema'])
    payload = dict(context=context, images=[base64.b64encode(p.read_bytes()).decode() for p in images],
                   schema=schema, authoritative_schema=context['output_schema'])
    validate_payload(payload)
    return payload, manifest


def normalized_command(result):
    run = result['local_log']
    require(isinstance(run, str) and run.startswith('/private/tmp/codex-astra-bridge/'), 'REMOTE_RUN_PATH')
    return [v.replace(run, '<RUN>') for v in result['command']]


def freeze():
    from verify_suite import verify
    records = verify(SUITE)  # RGB-D, calibration, private GT, witness and isolation canary, no model.
    fingerprints = {}
    for scene in SCENES:
        for task in ('understand', 'plan'):
            left, lm = payload_for(scene, task, A)
            right, rm = payload_for(scene, task, C)
            without_geometry = copy.deepcopy(right)
            without_geometry['context']['geometry'] = None
            require(left == without_geometry and lm['task_prompt_sha256'] == rm['task_prompt_sha256'], 'AC_PARITY')
            for condition, payload in ((A, left), (C, right)):
                fingerprints['/'.join((scene, task, condition))] = digest(payload)
    historical = read(HISTORY/'sample-0000/request.json')
    require(digest(historical) == fingerprints['/'.join((SCENES[4], 'plan', A))], 'HISTORICAL_INPUT_MISMATCH')
    require(read(HISTORY/'sample-0000/model_parameters.json') == PARAMETERS, 'HISTORICAL_PARAMETERS')
    require(read(HISTORY/'run_manifest.json')['snapshot_sha256'] == [sha(SUITE/SCENES[4]/'snapshot.json')], 'HISTORICAL_SNAPSHOT')
    protected = list(SUITE.rglob('*'))+list(HISTORY.rglob('*'))
    protected += list((MODULE/'spatial_eval').glob('*.py'))
    protected += [HARNESS/'scripts/codex_astra_mac_bridge.py', HARNESS/'scripts/structured_outputs.py',
                  HARNESS/'sim_skills/full_pnp/timing.py', CONFIG]
    hashes = {str(p.relative_to(REPO)): sha(p) for p in sorted(protected) if p.is_file() and '__pycache__' not in p.parts}
    result = dict(status='PASS', model_parameters=PARAMETERS, payload_sha256=fingerprints,
                  file_sha256=hashes, scenes=records, historical_s5_A='EXACT_PAYLOAD_AND_PARAMETERS_MATCH',
                  normalized_command=normalized_command(read(HISTORY/'sample-0000/bridge_result.json')),
                  no_new_generation=True, frozen_at=now())
    return result


def verify_seal(seal):
    require(seal['model_parameters'] == PARAMETERS, 'MODEL_PARAMETER_DRIFT')
    for rel, expected in seal['file_sha256'].items():
        require(sha(REPO/rel) == expected, 'FROZEN_FILE_CHANGED:'+rel)


def inspect_result(run, job, seal):
    """Only fully completed valid responses are capability observations, including score zero."""
    run = Path(run); folder = run/'sample-0000'
    rows = read(run/'results.json')
    require(len(rows) == 1, 'ONE_RESULT_REQUIRED')
    row = rows[0]
    transport = read(folder/'transport.json')
    response = read(folder/'response.json')
    require(transport.get('dispatch_attempts') == 1 and transport.get('retries') == 0, 'DISPATCH_COUNT')
    require(transport.get('http_status') == 200 and transport.get('cancel_attempts') == 0, 'TRANSPORT_FAILURE_OR_TIMEOUT')
    require(response.get('return_code') == 0, 'CLI_EXIT_OR_UNKNOWN_COMPLETION')
    require(not response.get('error'), 'RESPONSE_ERROR:'+str(response.get('error')))
    require(bool(response.get('raw', '').strip()), 'EMPTY_OUTPUT')
    events = [strict_json(line) for line in response['events'].splitlines() if line.strip()]
    require(all(isinstance(e, dict) for e in events), 'EVENT_OBJECT_REQUIRED')
    completed = [e for e in events if e.get('type') == 'turn.completed']
    require(len(completed) == 1, 'EXACTLY_ONE_TURN_COMPLETED_REQUIRED')
    require(not any(e.get('type') in ('turn.failed', 'error') for e in events), 'TERMINAL_EVENT_FAILURE')
    threads = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
    require(len(threads) == 1, 'ONE_EPHEMERAL_THREAD_REQUIRED')
    require(transport.get('remote_model_parameter_audit') == 'PASS', 'PARAMETER_AUDIT')
    native = read(folder/'bridge_result.json')
    require(normalized_command(native) == seal['normalized_command'], 'CLI_FLAGS_OR_CODE_MODE_DRIFT')
    require(read(folder/'model_parameters.json') == PARAMETERS, 'MODEL_PARAMETERS')
    require(digest(read(folder/'request.json')) == seal['payload_sha256'][key(job)], 'DISPATCHED_PAYLOAD_CHANGED')
    require(row['parse_status'] == 'VALID' and row['score_status'] == 'SCORED', 'INVALID_STRUCTURED_OUTPUT')
    require(all(row[k] == job[k] for k in ('scene_id', 'task_id', 'condition')), 'RESULT_IDENTITY')
    require(row['source'] == 'REAL_ASTRA_ATTEMPT', 'NON_REAL_RESULT')
    usage = completed[0].get('usage')
    require(isinstance(usage, dict) and usage == row['token_usage'], 'COMPLETION_USAGE_MISMATCH')
    # Re-score saved bytes with the existing parser/evaluator; never repair the model answer.
    s = load_snapshot(SUITE/job['scene_id']/'snapshot.json')
    t = next(t for t in s['task'] if t['task_id'] == job['task_id'])
    rescored = cli.assess_response(response, s, t)
    require(rescored['evaluation'] == row['evaluation'], 'OFFLINE_RESCORE_MISMATCH')
    return dict(status='VALID', thread_id=threads[0], request_id=transport['request_id'],
                native_log=native['local_log'], native_latency_s=native['latency_s'],
                score=row['score'], failed_constraints=row['evaluation']['error_types'],
                token_usage=usage, wall_latency_s=row['latency_s'], terminal_event=completed[0],
                payload_and_command='PASS', offline_rescore='PASS')


def summarize(root, ledger):
    primary = [dict(read(HISTORY/'results.json')[0], origin='historical',
                    artifact=os.path.relpath(HISTORY/'sample-0000', root), new_budget_cost=0)]
    repeats = []; invalid = []
    for record in ledger['reservations']:
        if record['status'] != 'VALID':
            invalid.append(record); continue
        row = read(root/record['directory']/'results.json')[0]
        row.update(origin='pilot01_new', new_budget_cost=1,
                   artifact=record['directory']+'/sample-0000', audit=record['audit'])
        (repeats if record['role'] == 'independent_repeat' else primary).append(row)
    pairs = []
    for scene in SCENES:
        for task in ('understand', 'plan'):
            group = {r['condition']: r for r in primary if (r['scene_id'], r['task_id']) == (scene, task)}
            if set(group) != {A, C}:
                continue
            a, c = group[A], group[C]
            pair = dict(scene_id=scene, task_id=task, frozen_parity='PASS', A=a, C=c,
                        delta_C_minus_A=dict(score=c['score']-a['score'], latency_s=c['latency_s']-a['latency_s'],
                          **{k:c['token_usage'][k]-a['token_usage'][k] for k in ('input_tokens', 'output_tokens')}))
            pairs.append(pair); save(root/'pairs'/f'{scene}_{task}.json', pair)
    summary = dict(status=ledger['status'], authorized_new_budget=BUDGET,
                   reserved_new_budget=len(ledger['reservations']), remaining_new_budget=BUDGET-len(ledger['reservations']),
                   valid_new_samples=sum(r['status']=='VALID' for r in ledger['reservations']),
                   invalid_or_infrastructure_samples=len(invalid),
                   counts_by_nonvalid_status={s:sum(r['status']==s for r in invalid) for s in sorted({r['status'] for r in invalid})},
                   primary_valid_samples=len(primary), completed_pairs=len(pairs), repeat_valid_samples=len(repeats),
                   groups={}, paired_deltas=[{k:p[k] for k in ('scene_id', 'task_id', 'delta_C_minus_A')} for p in pairs],
                   limitations=['Exploratory descriptive statistics only; six scenes, related tasks, no significance or generalization claim.',
                                'S4 orientation is prescribed; it is not autonomous orientation planning.',
                                'S5 A has a binary ceiling; equal A/C scores do not establish geometry has no value.',
                                'Static OBB geometry, no dynamics, support, IK or real hardware.'])
    for task in ('understand', 'plan'):
        for condition in (A, C):
            rows = [r for r in primary if r['task_id']==task and r['condition']==condition]
            details = [d for r in rows for d in r['evaluation'].get('details', [])]
            errors = [d['geometric_error_m'] for d in details if d['geometric_error_m'] is not None]
            n = len(rows)
            value = dict(n=n, all_constraints_passed=sum(r['evaluation']['success'] for r in rows),
                         mean_task_score=sum(r['score'] for r in rows)/n if n else None,
                         mean_latency_s=sum(r['latency_s'] for r in rows)/n if n else None,
                         total_latency_s=sum(r['latency_s'] for r in rows),
                         token_totals={k:sum(r['token_usage'].get(k, 0) for r in rows) for k in
                                       ('input_tokens', 'output_tokens', 'reasoning_output_tokens', 'cached_input_tokens')})
            if task == 'understand':
                value.update(correct_questions=sum(d['within_tolerance'] for d in details), questions=len(details),
                             numeric_question_count=len(errors), mean_numeric_error_m=sum(errors)/len(errors) if errors else None,
                             by_question_type={kind:dict(n=len(ds), correct=sum(d['within_tolerance'] for d in ds),
                                mean_error_m=sum(d['geometric_error_m'] for d in ds)/len(ds) if ds[0]['geometric_error_m'] is not None else None)
                                for kind in sorted({d['type'] for d in details})
                                for ds in [[d for d in details if d['type']==kind]]})
            summary['groups'][task+'/'+condition] = value
    save(root/'primary_results.json', primary); save(root/'repeat_results.json', repeats)
    save(root/'nonvalid_results.json', invalid); save(root/'summary.json', summary)
    save(root/'failure_index.json', [dict(scene_id=r['scene_id'], task_id=r['task_id'], condition=r['condition'],
         constraints=r['evaluation']['constraints'], errors=r['error_types'], artifact=r['artifact'])
         for r in primary+repeats if r['error_types']])
    return summary


def initialize(root):
    require(not root.exists(), 'OUTPUT_ALREADY_EXISTS_NO_NEW_BUDGET')
    # This authorization has a single canonical ledger; changing output cannot reset it.
    require(root == MODULE/'evidence/pilot01_20261013', 'CANONICAL_PILOT01_LEDGER_REQUIRED')
    seal = freeze()
    history_job = dict(scene_id=SCENES[4], task_id='plan', condition=A)
    audit = inspect_result(HISTORY, history_job, seal)
    root.mkdir(parents=True)
    save(root/'frozen_preflight.json', seal)
    save(root/'historical_pair_audit.json', audit)
    state = dict(status='READY', authorization='2026-10-13 user Pilot 01 up to 24 NEW dispatches',
                 max_new_dispatches=BUDGET, deadline_s=90, retries=0, ephemeral=True,
                 created_at=now(), jobs=schedule(), reservations=[], historical_dispatches_in_new_budget=0)
    save(root/'ledger.json', state); summarize(root, state)
    print('PREFLIGHT PASS: 24 payloads; historical S5 A exact match; new dispatches=0', flush=True)


def next_request(root):
    ledger = read(root/'ledger.json'); seal = read(root/'frozen_preflight.json')
    require(ledger['status'] == 'READY', 'BATCH_STOPPED_OR_COMPLETE')
    require(ledger['max_new_dispatches'] == BUDGET and ledger['jobs'] == schedule(), 'BUDGET_OR_ORDER_CHANGED')
    require(len(ledger['reservations']) < BUDGET, 'BUDGET_EXHAUSTED')
    require(all(r['status'] == 'VALID' for r in ledger['reservations']), 'IN_FLIGHT_OR_FAILED_NO_RETRY')
    verify_seal(seal)
    # GET is a non-generating readiness probe on the original handler (expected 501).
    link = http.client.HTTPConnection('127.0.0.1', 18766, timeout=5)
    try:
        link.request('GET', '/'); response = link.getresponse(); response.read()
        require(response.status == 501, 'BRIDGE_NON_GENERATING_PROBE_FAILED')
    finally:
        link.close()
    job = copy.deepcopy(ledger['jobs'][len(ledger['reservations'])])
    payload, _ = payload_for(job['scene_id'], job['task_id'], job['condition'])
    require(digest(payload) == seal['payload_sha256'][key(job)], 'FROZEN_INPUT_DRIFT')
    require(not (root/job['directory']).exists(), 'OUTPUT_EXISTS_NO_RETRY')
    job.update(status='IN_FLIGHT', reserved_at=now())
    ledger['reservations'].append(job)
    # Reservation is never refunded, even if the process crashes before HTTP dispatch.
    save(root/'ledger.json', ledger)
    print('DISPATCH_RESERVED '+json.dumps({k:job[k] for k in ('index','scene_id','task_id','condition','role')}), flush=True)
    try:
        cli.run([SUITE/job['scene_id']/'snapshot.json'], root/job['directory'], [job['condition']],
                real=True, max_real_calls=1, timing_mode='qualification', backend='mac-bridge',
                bridge_config=CONFIG, task_ids=[job['task_id']])
        audit = inspect_result(root/job['directory'], job, seal)
        previous_threads = {r['audit']['thread_id'] for r in ledger['reservations'][:-1]}
        previous_threads.add(read(root/'historical_pair_audit.json')['thread_id'])
        require(audit['thread_id'] not in previous_threads, 'EPHEMERAL_THREAD_REUSED')
        verify_seal(seal)
        job.update(status='VALID', audit=audit, finished_at=now())
        if len(ledger['reservations']) == BUDGET:
            ledger['status'] = 'COMPLETE'
    except BaseException as exc:
        # Stop on any uncertainty; no recovery path dispatches again automatically.
        job.update(status='STOPPED_UNVALIDATED', failure=type(exc).__name__+':'+str(exc), finished_at=now())
        ledger['status'] = 'STOPPED'
    save(root/'ledger.json', ledger)
    summary = summarize(root, ledger)
    print(json.dumps(dict(batch_status=ledger['status'], consumed=len(ledger['reservations']),
                          sample_status=job['status'], score=job.get('audit', {}).get('score'),
                          completed_pairs=summary['completed_pairs'], failure=job.get('failure'))), flush=True)
    return 0 if job['status']=='VALID' else 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init', 'next', 'report'])
    p.add_argument('--output', type=Path, default=MODULE/'evidence/pilot01_20261013')
    args = p.parse_args(); root = args.output.resolve()
    require(root == MODULE/'evidence/pilot01_20261013', 'CANONICAL_PILOT01_LEDGER_REQUIRED')
    with locked(root):
        if args.action == 'init':
            initialize(root); return 0
        if args.action == 'report':
            print(json.dumps(summarize(root, read(root/'ledger.json')), indent=2)); return 0
        try:
            return next_request(root)
        except Exception as exc:
            # Includes non-generating preflight/link failures. Stops the whole batch.
            ledger = read(root/'ledger.json')
            if ledger['status'] != 'COMPLETE':
                ledger.update(status='STOPPED', stop_reason=type(exc).__name__+':'+str(exc), stopped_at=now())
                save(root/'ledger.json', ledger); summarize(root, ledger)
            print('STOP: '+str(exc), flush=True); return 2


if __name__ == '__main__':
    raise SystemExit(main())
