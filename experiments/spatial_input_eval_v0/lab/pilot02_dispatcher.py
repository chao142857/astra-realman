#!/usr/bin/env python3
"""Independent, sequential Pilot02 dispatcher. Default dry-run; no implicit grant."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
from pilot02_runtime import (MODULE, ORDER, sha, verify_frozen, job_input, read,
    Pilot02MacBridgeAdapter, MacBridgeConfig, record_and_rescore, assess)


def now():return datetime.now(timezone.utc).isoformat()

def save(path,value):
    path=Path(path);data=(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        d=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(temp):os.unlink(temp)

@contextmanager
def lock():
    # One host-wide Pilot02 dispatcher, not a Pilot01 lock or ledger.
    path=Path(tempfile.gettempdir())/f'astra-spatial-pilot02-dispatch-{os.getuid()}.lock'
    with path.open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('ANOTHER_PILOT02_DISPATCHER_ACTIVE') from None
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def safe_root(root):
    root=Path(root).resolve()
    if root.is_relative_to(MODULE) and not root.is_relative_to(MODULE/'evidence/pilot02_runs'):
        raise ValueError('OUTPUT_MUST_NOT_TOUCH_FROZEN_EVIDENCE')
    return root


def implementation_hashes():
    return {name:sha(Path(__file__).with_name(name)) for name in ('pilot02_dispatcher.py','pilot02_runtime.py')}

def expected_source(state):
    return 'REAL_ASTRA_ATTEMPT' if state['mode']=='REAL' else 'FAKE_MAC_BRIDGE_NOT_ASTRA'

def prepare(root):
    order=verify_frozen();root=safe_root(root)
    # Refuse existing directories; never reset an old or interrupted ledger.
    root.parent.mkdir(parents=True,exist_ok=True);root.mkdir(exist_ok=False)
    for job in order['ordered_samples']:job_input(job)
    state={'version':'pilot02.dispatcher.v1','batch_id':uuid.uuid4().hex,'root':str(root),
           'order_sha256':sha(ORDER),'status':'DRY_RUN','created_at':now(),
           'mode':'DRY_RUN','implementation_sha256':implementation_hashes(),'authorization':None,'reserved_budget':0,'jobs':order['ordered_samples'],'runs':[],
           'deadline_s':180,'concurrency':1,'automatic_retries':0}
    save(root/'ledger.json',state);return state


def load(root):
    root=safe_root(root);state=read(root/'ledger.json');order=verify_frozen()
    if state['implementation_sha256']!=implementation_hashes():raise ValueError('DISPATCHER_SOURCE_CHANGED')
    if state['mode'] not in ('DRY_RUN','REAL','OFFLINE_FIXTURE'):raise ValueError('LEDGER_MODE')
    if state['root']!=str(root) or state['jobs']!=order['ordered_samples'] or state['order_sha256']!=sha(ORDER):
        raise ValueError('LEDGER_SCOPE_OR_ORDER_CHANGED')
    if state['version']!='pilot02.dispatcher.v1' or state['deadline_s']!=180 or state['concurrency']!=1 or state['automatic_retries']!=0:
        raise ValueError('LEDGER_PROTOCOL_CHANGED')
    if state['reserved_budget']!=len(state['runs']) or len(state['runs'])>20:raise ValueError('BUDGET_INTEGRITY')
    for i,r in enumerate(state['runs']):
        if r['index']!=i+1 or r['job']!=state['jobs'][i] or r['artifact']!=f'run-{i+1:03d}':raise ValueError('RESERVATION_ORDER_CHANGED')
    return state


def authorize(state,path):
    grant=read(path)
    expected={'generation_authorized','batch_id','output_root','order_sha256','max_dispatches','deadline_s','concurrency','user_authorization_statement'}
    if set(grant)!=expected or grant['generation_authorized'] is not True:raise ValueError('NEW_USER_AUTHORIZATION_REQUIRED')
    if (grant['batch_id']!=state['batch_id'] or grant['output_root']!=state['root'] or grant['order_sha256']!=state['order_sha256']
        or type(grant['max_dispatches']) is not int or not 1<=grant['max_dispatches']<=20
        or grant['deadline_s']!=180 or grant['concurrency']!=1
        or not isinstance(grant['user_authorization_statement'],str) or not grant['user_authorization_statement'].strip()):
        raise ValueError('AUTHORIZATION_SCOPE_MISMATCH')
    bound={'sha256':sha(path),'grant':grant}
    if state['authorization'] is not None and state['authorization']!=bound:raise ValueError('AUTHORIZATION_CANNOT_BE_REPLACED')
    if state['authorization'] is None:
        if state['status']!='DRY_RUN' or state['mode']!='DRY_RUN' or state['runs']:raise ValueError('AUTHORIZATION_STATE')
        state['authorization']=bound;state['status']='READY';state['mode']='REAL'
    return state


def dry_run(root):
    state=load(root)
    return {'status':'DRY_RUN_NO_DISPATCH','batch_id':state['batch_id'],'order_sha256':state['order_sha256'],
            'planned_samples':len(state['jobs']),'reserved_budget':state['reserved_budget'],'real_dispatches_this_command':0}


def perform(job,folder,config,*,offline=False):
    context,images,*_=job_input(job)
    adapter=Pilot02MacBridgeAdapter(config,job,offline_test=offline)
    if not offline:adapter._reserved_dispatch=True
    try:adapter.infer(context,images,folder,real=not offline,timeout_s=180)
    except BaseException:
        # Reuse the exact transport's non-generating cancel route, never retry.
        request=Path(folder)/'bridge_request.json'
        if request.exists():
            receipt={'completion':'UNKNOWN','cancel_attempts':1,'ack_is_not_completion':True}
            try:
                status,body=adapter._post('/cancel',json.dumps({'request_id':read(request)['request_id']}).encode(),
                                          config.token_file.read_text().strip(),3)
                receipt['http_status']=status
            except Exception:receipt['cancel_transport_failed']=True
            save(Path(folder)/'interrupt_cancel.json',receipt)
        raise
    return record_and_rescore(folder,job)


def paired_report(root,state):
    pairs=[]
    for i in range(0,20,2):
        rows=[r for r in state['runs'] if r['index'] in (i+1,i+2)]
        if len(rows)==2 and all(r['status']=='VALID' for r in rows):
            by={r['job']['condition']:r for r in rows};a=by['RGB_MULTI_VIEW'];c=by['RGB_ORACLE_3D']
            pairs.append({'scene_id':a['job']['scene_id_private_catalog_only'],'A':a['assessment']['score'],
                          'C':c['assessment']['score'],'C_minus_A':c['assessment']['score']-a['assessment']['score'],
                          'source':a['assessment']['source'],'descriptive_only':True})
    save(Path(root)/'paired_results.json',pairs)


def advance(root,state,runner,limit):
    """Shared engine; tests pass a fake runner. Caller holds exclusive lock."""
    root=Path(root)
    if state['status'] not in ('READY',):raise ValueError('BATCH_NOT_READY')
    if state['mode']=='REAL':
        if state['authorization'] is None or limit!=state['authorization']['grant']['max_dispatches']:raise ValueError('AUTHORIZED_BUDGET_REQUIRED')
    elif state['mode']!='OFFLINE_FIXTURE':raise ValueError('NO_DISPATCH_MODE')
    if any(r['status']!='VALID' for r in state['runs']):
        state['status']='STOPPED';save(root/'ledger.json',state)
        raise ValueError('UNRESOLVED_RESERVATION_REQUIRES_RECONCILE')
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('BUDGET_LIMIT')
    while len(state['runs'])<min(limit,20):
        verify_frozen();idx=len(state['runs'])+1;job=state['jobs'][idx-1];job_input(job)
        folder=root/f'run-{idx:03d}'
        if folder.exists():raise ValueError('OUTPUT_ALREADY_EXISTS_NO_RETRY')
        row={'index':idx,'job':job,'status':'RESERVED','reserved_at':now(),'artifact':folder.name}
        state['runs'].append(row);state['reserved_budget']=len(state['runs'])
        save(root/'ledger.json',state)  # Durable reservation before any possible HTTP.
        try:
            result=runner(job,folder)
            if result.get('source')!=expected_source(state):
                result=dict(result,status='NOT_SCORED',score=None,failure='RESULT_SOURCE_MISMATCH')
            if result['status']=='VALID' and any(r.get('assessment',{}).get('thread_id')==result['thread_id'] for r in state['runs'][:-1]):
                result=dict(result,status='NOT_SCORED',score=None,failure='REUSED_THREAD_ID')
            row['assessment']=result;row['finished_at']=now()
            row['status']='VALID' if result['status']=='VALID' else 'STOPPED_INVALID_OR_UNKNOWN'
            if row['status']!='VALID':state['status']='STOPPED'
        except BaseException as exc:
            row.update(status='UNKNOWN',error_class=type(exc).__name__,interrupted_at=now());state['status']='STOPPED'
            save(root/'ledger.json',state);paired_report(root,state);raise
        save(root/'ledger.json',state);paired_report(root,state)
        if state['status']=='STOPPED':return state
    state['status']='COMPLETE' if len(state['runs'])==20 else 'BUDGET_EXHAUSTED'
    save(root/'ledger.json',state);return state


def run(root,*,real=False,authorization=None,config=None):
    with lock():
        state=load(root)
        if not real:return dry_run(root)
        if authorization is None or config is None:raise ValueError('NEW_USER_AUTHORIZATION_AND_CONFIG_REQUIRED')
        state=authorize(state,authorization)
        save(Path(root)/'ledger.json',state)
        return advance(root,state,lambda j,p:perform(j,p,config),state['authorization']['grant']['max_dispatches'])


def reconcile(root):
    """No network, no dispatch, no budget refunds; recover only confirmed local evidence."""
    with lock():
        root=Path(root);state=load(root)
        if not state['runs']:raise ValueError('NOTHING_TO_RECONCILE')
        for row in state['runs']:
            if row['status']=='VALID':
                if assess(root/row['artifact'],row['job'])!=row['assessment']:raise ValueError('COMPLETED_ARCHIVE_CHANGED')
            else:
                result=assess(root/row['artifact'],row['job'])
                row['reconciliation']={'at':now(),'assessment':result}
                if result['status']=='VALID' and result['source']==expected_source(state):row.update(status='VALID',assessment=result)
        tids=[r['assessment']['thread_id'] for r in state['runs'] if r['status']=='VALID']
        good=all(r['status']=='VALID' for r in state['runs']) and len(tids)==len(set(tids))
        state['status']=('COMPLETE' if len(state['runs'])==20 else 'READY') if good else 'STOPPED'
        save(root/'ledger.json',state);paired_report(root,state)
        return state


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','reconcile','status']);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--real',action='store_true');p.add_argument('--authorization',type=Path);p.add_argument('--bridge-config',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        if a.real or a.authorization:raise ValueError('PREPARE_IS_ALWAYS_DRY_RUN')
        with lock():result=prepare(a.output)
    elif a.action=='run':result=run(a.output,real=a.real,authorization=a.authorization,
                                     config=MacBridgeConfig.load(a.bridge_config) if a.real and a.bridge_config else None)
    elif a.action=='reconcile':result=reconcile(a.output)
    else:result=load(a.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('jobs','runs','authorization')},indent=2))

if __name__=='__main__':main()
