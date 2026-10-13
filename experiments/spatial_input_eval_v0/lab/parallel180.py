#!/usr/bin/env python3
"""Explicit user amendment: four isolated workers, 180 s, original cumulative cap 24.

Only one four-request wave per invocation. Any failure stops later waves and sends
non-generating cancellation to other in-flight jobs. No request is retried here.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import http.client
import json
import os
from pathlib import Path
import threading
import pilot01 as base
from spatial_eval.mac_bridge import MacBridgeAdapter, MacBridgeConfig
from spatial_eval.report import reports

ROOT=base.MODULE/'evidence/pilot01_parallel180_20261013'
PRIOR=base.MODULE/'evidence/pilot01_20261013'
TOKEN=Path('/home/tongji/alex/astra_realman_harness/config/codex_astra_bridge.token')
TOTAL_BUDGET=24


def prior_state():
    state=base.read(PRIOR/'ledger.json')
    base.require(state['status']=='STOPPED', 'PREVIOUS_PHASE_MUST_REMAIN_STOPPED')
    base.require(len(state['reservations'])==4, 'PRIOR_BUDGET_MISMATCH')
    return state


def plan():
    existing={base.key(r) for r in base.read(PRIOR/'primary_results.json')}
    pending=[j for j in base.schedule() if j['role']=='primary' and base.key(j) not in existing]
    base.require(len(pending)==20, 'REMAINING_PRIMARY_MATRIX')
    return [dict(j,index=i+5,phase_index=i+1,wave=i//4+1,worker=i%4+1,deadline_s=180,concurrency=4,
                 directory=f'runs/{i+5:02d}_{j["scene_id"]}_{j["task_id"]}_{"A" if j["condition"]==base.A else "C"}_180s')
            for i,j in enumerate(pending)]


def baseline():
    rows=copy.deepcopy(base.read(PRIOR/'primary_results.json'))
    for r in rows:
        r['artifact']=os.path.relpath((PRIOR/r['artifact']).resolve(), ROOT)
        r.update(deadline_s=90,concurrency=1,phase='pilot01_90s')
    return rows


def report(state):
    return base.summarize(ROOT,state,baseline_rows=baseline(),budget=20)


class AbortableAdapter(MacBridgeAdapter):
    def __init__(self,config,abort):
        super().__init__(config,timeout_limit_s=180)
        self.abort=abort

    def _post(self,path,body,token,timeout_s):
        if path=='/decide' and self.abort.is_set():
            raise OSError('BATCH_ALREADY_STOPPED_BEFORE_DISPATCH')
        return super()._post(path,body,token,timeout_s)


def run_one(job,seal,abort):
    output=ROOT/job['directory']; output.mkdir(parents=True,exist_ok=False)
    s=base.load_snapshot(base.SUITE/job['scene_id']/'snapshot.json')
    t=next(t for t in s['task'] if t['task_id']==job['task_id'])
    context,manifest,images=base.build_input(s,t,job['condition'])
    adapter=AbortableAdapter(MacBridgeConfig(f'http://127.0.0.1:{18770+job["worker"]}',TOKEN),abort)
    response=adapter.infer(context,images,output/'sample-0000',real=True,timeout_s=180)
    row=dict(scene_id=s['scene_id'],task_id=t['task_id'],condition=job['condition'],
             artifact='sample-0000',source=response['source'],model_calls=response['model_calls'],
             raw_output=response['raw'],latency_s=response['wall_latency_s'],token_usage=response.get('usage'),
             **{k:v for k,v in manifest.items() if k not in ('scene_id','task_id','condition')})
    row.update(base.cli.assess_response(response,s,t))
    base.save(output/'sample-0000/evaluation.json',row['evaluation'])
    reports([row],output)
    base.save(output/'run_manifest.json',dict(real_enabled=True,max_real_calls=1,planned_samples=1,
        recorded_samples=1,model_calls=response['model_calls'],completed=True,backend='mac-bridge',
        timing_mode='USER_AUTHORIZED_PARALLEL_180',request_timeout_s=180,worker=job['worker'],
        max_concurrency=4,task_ids=[job['task_id']],snapshot_sha256=[base.sha(base.SUITE/job['scene_id']/'snapshot.json')]))
    audit=base.inspect_result(output,job,seal)
    audit.update(deadline_s=180,worker=job['worker'])
    return audit


def cancel_peer(job):
    """One original non-generating /cancel; acknowledgment is not proof of completion."""
    folder=ROOT/job['directory']/'sample-0000'
    if not (folder/'bridge_request.json').exists():
        return dict(status='NO_REQUEST_ID_YET_ABORT_GUARD_ACTIVE',new_generations=0)
    rid=base.read(folder/'bridge_request.json')['request_id']
    cfg=MacBridgeConfig(f'http://127.0.0.1:{18770+job["worker"]}',TOKEN)
    adapter=MacBridgeAdapter(cfg,timeout_limit_s=180)
    result=dict(request_id=rid,new_generations=0,ack_does_not_prove_cancellation=True)
    try:
        status,body=adapter._post('/cancel',json.dumps({'request_id':rid}).encode(),TOKEN.read_text().strip(),3)
        result.update(http_status=status,response=json.loads(body))
    except Exception as exc:
        result.update(error_type=type(exc).__name__)
    base.save(folder/'peer_cancel.json',result)
    return result


def initialize():
    prior=prior_state()
    base.require(not ROOT.exists(),'PHASE_EXISTS_CANNOT_RESET_BUDGET')
    seal=base.freeze()
    # Input payload and full model command must match the 90 s phase byte-for-byte.
    old=base.read(PRIOR/'frozen_preflight.json')
    for k in ('payload_sha256','normalized_command','model_parameters'):
        base.require(seal[k]==old[k],'AMENDMENT_CHANGED_FROZEN_MODEL_INPUT:'+k)
    ROOT.mkdir(parents=True)
    seal['prior_ledger_sha256']=base.sha(PRIOR/'ledger.json')
    base.save(ROOT/'frozen_preflight.json',seal)
    state=dict(status='READY',phase='pilot01_parallel180',authorization='User explicitly selected four isolated workers with offline acceptance and 180 s deadline',
        created_at=base.now(),max_cumulative_dispatches=24,prior_budget_consumed=len(prior['reservations']),
        max_new_dispatches=20,deadline_s=180,concurrency=4,automatic_retries=0,jobs=plan(),reservations=[],
        final_S5_A_repeat='OMITTED_IF_PRIMARY_MATRIX_USES_REMAINING_20; no extra authorization inferred')
    base.save(ROOT/'ledger.json',state);report(state)
    print('PASS: amended phase initialized; prior budget=4, remaining=20, frozen payloads/command unchanged',flush=True)


def execute_wave(state,seal,runner=run_one,canceller=cancel_peer):
    """Budget reservation and scheduling core, independently testable without network."""
    base.require(state['status']=='READY','BATCH_STOPPED_OR_COMPLETE')
    base.require(state['prior_budget_consumed']==4 and state['max_cumulative_dispatches']==24,'CUMULATIVE_BUDGET_CHANGED')
    base.require(state['jobs']==plan(),'JOB_ORDER_CHANGED')
    base.require(all(r['status']=='VALID' for r in state['reservations']),'CRASH_OR_FAILURE_NO_RETRY')
    consumed=state['prior_budget_consumed']+len(state['reservations'])
    base.require(consumed<24,'CUMULATIVE_BUDGET_EXHAUSTED')
    pending=copy.deepcopy(state['jobs'][len(state['reservations']):len(state['reservations'])+min(4,24-consumed)])
    abort=threading.Event()
    for job in pending:
        base.require(not (ROOT/job['directory']).exists(),'OUTPUT_ALREADY_EXISTS')
        job.update(status='IN_FLIGHT',reserved_at=base.now())
        state['reservations'].append(job)
    # Reserve the whole wave before any future can dispatch. Crash => no budget refund.
    base.save(ROOT/'ledger.json',state)
    print('WAVE_RESERVED '+json.dumps(dict(indices=[j['index'] for j in pending],cumulative_reserved=4+len(state['reservations']))),flush=True)
    previous_threads={r['audit']['thread_id'] for r in state['reservations'][:-len(pending)]}
    previous_threads.add(base.read(PRIOR/'historical_pair_audit.json')['thread_id'])
    previous_threads.update(r['audit']['thread_id'] for r in prior_state()['reservations'] if r['status']=='VALID')
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(runner,j,seal,abort):j for j in pending}
        for future in as_completed(futures):
            job=futures[future]
            try:
                audit=future.result()
                base.require(audit['thread_id'] not in previous_threads,'EPHEMERAL_THREAD_REUSED')
                previous_threads.add(audit['thread_id'])
                job.update(status='VALID',audit=audit,finished_at=base.now())
            except BaseException as exc:
                job.update(status='STOPPED_UNVALIDATED',failure=type(exc).__name__+':'+str(exc),finished_at=base.now())
                state['status']='STOPPED';abort.set()
                base.save(ROOT/'ledger.json',state)
                for peer_future,peer in futures.items():
                    if peer is not job and not peer_future.done() and 'peer_cancel' not in peer:
                        peer['peer_cancel']=canceller(peer)
            base.save(ROOT/'ledger.json',state)
            report(state)
            print(json.dumps(dict(index=job['index'],status=job['status'],score=job.get('audit',{}).get('score'),
                                  failure=job.get('failure'),batch_status=state['status'])),flush=True)
    if state['status']=='READY' and 4+len(state['reservations'])==24:state['status']='COMPLETE'
    base.save(ROOT/'ledger.json',state);report(state)
    return 0 if state['status'] in ('READY','COMPLETE') else 2


def next_wave():
    state=base.read(ROOT/'ledger.json');seal=base.read(ROOT/'frozen_preflight.json')
    base.require(state['status']=='READY','BATCH_STOPPED_OR_COMPLETE')
    prior_state();base.require(base.sha(PRIOR/'ledger.json')==seal['prior_ledger_sha256'],'PRIOR_BUDGET_CHANGED')
    base.verify_seal(seal)
    acceptance=base.read(ROOT/'offline_acceptance.json')
    base.require(acceptance['status']=='PASS' and acceptance['workers']==4,'FOUR_WORKER_OFFLINE_ACCEPTANCE_REQUIRED')
    for worker in range(1,5):
        link=http.client.HTTPConnection('127.0.0.1',18770+worker,timeout=5)
        try:
            link.request('GET','/');response=link.getresponse();response.read()
            base.require(response.status==501,'WORKER_LINK_FAILURE')
        finally:link.close()
    code=execute_wave(state,seal)
    base.verify_seal(seal)
    return code


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['init','wave','report']);args=p.parse_args()
    with base.locked(ROOT):
        if args.action=='init':initialize();return 0
        if args.action=='report':report(base.read(ROOT/'ledger.json'));return 0
        try:return next_wave()
        except Exception as exc:
            state=base.read(ROOT/'ledger.json')
            if state['status']!='COMPLETE':
                state.update(status='STOPPED',failure=type(exc).__name__+':'+str(exc),stopped_at=base.now())
                base.save(ROOT/'ledger.json',state);report(state)
            print('STOP: '+str(exc),flush=True);return 2


if __name__=='__main__':raise SystemExit(main())
