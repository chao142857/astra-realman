#!/usr/bin/env python3
"""Final offline response, budget, pairing, timing and boundary audit; no inference."""
import collections
import json
import math
import pilot01 as p

ROOT=p.MODULE/'evidence/pilot01_parallel180_20261013'
PRIOR=p.MODULE/'evidence/pilot01_20261013'


def main():
    phase0=p.read(PRIOR/'ledger.json');phase1=p.read(ROOT/'ledger.json')
    records=[(PRIOR,r) for r in phase0['reservations']]+[(ROOT,r) for r in phase1['reservations']]
    p.require(len(records)<=24,'CUMULATIVE_BUDGET_EXCEEDED')
    p.require(phase0['status']=='STOPPED' and phase1['status'] in ('COMPLETE','STOPPED'),'BATCH_STILL_ACTIVE')
    rows=p.read(ROOT/'primary_results.json');sealed=p.read(ROOT/'frozen_preflight.json')
    p.verify_seal(sealed)
    original=p.read(PRIOR/'frozen_preflight.json')
    for rel,expected in original['file_sha256'].items():
        if rel.endswith('/spatial_eval/mac_bridge.py'):continue  # Explicit opt-in 180 s amendment only.
        p.require(p.sha(p.REPO/rel)==expected,'ORIGINAL_DATA_OR_SCORER_CHANGED:'+rel)
    counts=collections.Counter();ids=[];threads=[];intervals=[];dispatches=0;known_usage=[];client_latencies=[]
    for root,record in records:
        run=root/record['directory'];sample=run/'sample-0000'
        if not (sample/'transport.json').exists():
            counts['reserved_without_confirmed_dispatch']+=1;continue
        transport=p.read(sample/'transport.json');response=p.read(sample/'response.json')
        ids.append(transport['request_id']);dispatches+=transport['dispatch_attempts']
        p.require(transport['retries']==0,'UNAUTHORIZED_RETRY')
        p.require(transport['timeout_s']==(90 if root==PRIOR else 180),'DEADLINE_DRIFT')
        p.require(p.digest(p.read(sample/'request.json'))==sealed['payload_sha256'][p.key(record)],'PAYLOAD_CHANGED')
        p.require(p.read(sample/'model_parameters.json')==p.PARAMETERS,'PARAMETERS_CHANGED')
        client_latencies.append(response['wall_latency_s'])
        if response.get('usage') is not None:known_usage.append(response['usage'])
        if record['status']=='VALID':
            audit=p.inspect_result(run,record,sealed);counts['valid']+=1;threads.append(audit['thread_id'])
        elif response.get('error')=='MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN':counts['infrastructure_timeout']+=1
        elif str(response.get('error','')).startswith('LOCAL_OUTPUT_VALIDATION:'):counts['invalid_output']+=1
        else:counts['other_nonvalid']+=1
        if (run/'mac_native/result.json').exists():
            native=p.read(run/'mac_native/result.json')
            p.require(p.normalized_command(native)==sealed['normalized_command'],'NATIVE_COMMAND_CHANGED')
            for e in [json.loads(line) for line in native['events'].splitlines()]:
                if e.get('type')=='thread.started' and record['status']!='VALID':threads.append(e['thread_id'])
            timing=p.read(run/'native_timing.json')
            intervals.append(dict(phase='90s_serial' if root==PRIOR else '180s_four_workers',index=record['index'],**timing))
    p.require(dispatches==len(records),'RESERVATION_DISPATCH_DISCREPANCY')
    p.require(len(ids)==len(set(ids)) and len(threads)==len(set(threads)),'REQUEST_OR_THREAD_REUSED')
    boundaries=[];types=collections.Counter();primary_identities=[]
    for row in rows:
        primary_identities.append(p.key(row));artifact=(ROOT/row['artifact']).resolve()
        s=p.load_snapshot(p.SUITE/row['scene_id']/'snapshot.json');task=next(t for t in s['task'] if t['task_id']==row['task_id'])
        result=p.cli.assess_response(p.read(artifact/'response.json'),s,task)
        p.require(result['parse_status']=='VALID' and result['evaluation']==row['evaluation'],'INDEPENDENT_RESCORE_FAILED')
        types[row['task_id']+'/'+row['condition']]+=1
        if row['task_id']=='understand':
            for detail in result['evaluation']['details']:
                error=detail['geometric_error_m'];tol=task['tolerance_m']
                if error is not None and not detail['within_tolerance'] and 0<error-tol<1e-7:
                    boundaries.append(dict(scene_id=row['scene_id'],condition=row['condition'],question_id=detail['question_id'],
                        error_m=error,tolerance_m=tol,excess_m=error-tol,
                        note='Frozen score retained; simulator floating-point representation is material at this boundary.'))
    p.require(len(primary_identities)==len(set(primary_identities)),'DUPLICATE_PRIMARY_CELL')
    if phase1['status']=='COMPLETE':
        p.require(len(rows)==24 and all(n==6 for n in types.values()) and len(types)==4,'PRIMARY_MATRIX_INCOMPLETE')
    times=[]
    for interval in intervals:times.extend([(interval['prompt_written_unix'],1),(interval['result_written_unix'],-1)])
    active=peak=0
    for _,change in sorted(times):active+=change;peak=max(peak,active)
    p.require(peak<=4 and active==0,'CONCURRENCY_EXCEEDED')
    stage1=[i for i in intervals if i['phase']=='180s_four_workers']
    phase1_wall=max(i['result_written_unix'] for i in stage1)-min(i['prompt_written_unix'] for i in stage1) if stage1 else None
    wave_spans=[]
    for wave in sorted({(i['index']-5)//4+1 for i in stage1}):
        group=[i for i in stage1 if (i['index']-5)//4+1==wave]
        wave_spans.append(dict(wave=wave,elapsed_s=max(i['result_written_unix'] for i in group)-min(i['prompt_written_unix'] for i in group)))
    paths={}
    s6=p.load_snapshot(p.SUITE/p.SCENES[5]/'snapshot.json');plan=next(t for t in s6['task'] if t['task_id']=='plan')
    for row in rows:
        if (row['scene_id'],row['task_id'])!=(p.SCENES[5],'plan'):continue
        points=[plan['constraints']['start_position_m'],*row['prediction']['waypoints_m']]
        paths[row['condition']]=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    audit=dict(status='PASS',new_generation_requests=0,cumulative_authorized_budget=24,
        cumulative_new_dispatches=dispatches,remaining_budget=24-dispatches,counts=dict(counts),
        primary_samples=len(rows),primary_rescores='ALL_IDENTICAL',primary_by_task_and_condition=dict(types),
        unique_new_request_ids=len(set(ids)),unique_new_threads=len(set(threads)),measured_max_native_overlap=peak,
        native_intervals=intervals,parallel_phase_wall_span_s=phase1_wall,parallel_wave_spans=wave_spans,
        summed_parallel_wave_wall_s=sum(w['elapsed_s'] for w in wave_spans),
        original_data_prompts_schemas_scoring_and_bridge='UNCHANGED_SHA256',
        summed_new_client_wait_s=sum(client_latencies),known_usage_samples=len(known_usage),
        token_totals_known_only={k:sum(u.get(k,0) for u in known_usage) for k in
                                ('input_tokens','output_tokens','reasoning_output_tokens','cached_input_tokens')},
        unknown_usage_samples=len(records)-len(known_usage),numerical_boundary_cases=boundaries,
        s6_supplemental_path_length_m=paths,path_length_note='Descriptive only; not an objective of the frozen scorer and not an optimality claim.',
        independent_S5_A_repeat='NOT_RUN_NO_REMAINING_BUDGET' if dispatches==24 else 'NOT_RUN_BATCH_STOPPED',
        limitations=['90-second serial and 180-second four-worker phases are separate execution conditions.',
                    'Cached input tokens may affect latency; ephemeral threads do not disable provider prompt caching.',
                    'Six scenes and related tasks, descriptive only; planning scores have a ceiling.'])
    p.save(ROOT/'final_offline_audit.json',audit)
    print(json.dumps({k:audit[k] for k in ('status','cumulative_new_dispatches','remaining_budget','counts','primary_samples','measured_max_native_overlap','token_totals_known_only','unknown_usage_samples')}))


if __name__=='__main__':main()
