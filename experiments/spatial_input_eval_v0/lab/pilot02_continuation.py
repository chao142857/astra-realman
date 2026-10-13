#!/usr/bin/env python3
"""Eight-job continuation boundary; reuses the original dispatcher engine and scorer."""
import argparse
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone
import pilot02_dispatcher as base
import pilot02_runtime as runtime

PREP=runtime.MODULE/'evidence/pilot02_continuation_prep_20261013'
MANIFEST=PREP/'continuation_manifest.json'
OLD=runtime.MODULE/'evidence/pilot02_runs/pilot02_real_01'
MANIFEST_SHA='2df52de971fdb2759b56ede59a346f2362331c1bd4fbaae73685c00d382f7d5e'
OLD_HASHES_SHA='6108e7017149b2950b07b2c7254242027a7fbcf253c2dae8c10d6cb3c222445d'


def frozen():
    if runtime.sha(MANIFEST)!=MANIFEST_SHA or runtime.sha(PREP/'original_batch_hashes.json')!=OLD_HASHES_SHA:
        raise ValueError('CONTINUATION_MANIFEST_CHANGED')
    manifest=runtime.read(MANIFEST);order=runtime.verify_frozen()
    if manifest['ordered_samples']!=order['ordered_samples'][12:]:raise ValueError('CONTINUATION_ORDER_CHANGED')
    if runtime.sha(OLD/'ledger.json')!=manifest['original_ledger_sha256']:raise ValueError('OLD_LEDGER_CHANGED')
    for name,digest in runtime.read(PREP/'original_batch_hashes.json').items():
        if runtime.sha(runtime.MODULE/name)!=digest:raise ValueError('OLD_EVIDENCE_CHANGED')
    for job in manifest['ordered_samples']:runtime.job_input(job)
    return manifest


def hashes():
    return dict(base.implementation_hashes(),pilot02_continuation=runtime.sha(__file__))


def safe_root(root):
    root=base.safe_root(root)
    if root.is_relative_to(OLD):raise ValueError('OLD_BATCH_READ_ONLY')
    return root


def prepare(root):
    manifest=frozen();root=safe_root(root)
    root.parent.mkdir(parents=True,exist_ok=True);root.mkdir(exist_ok=False)
    state={'version':'pilot02.continuation.v1','batch_id':uuid.uuid4().hex,'root':str(root),'created_at':base.now(),
           'status':'DRY_RUN','mode':'DRY_RUN','authorization':None,'reserved_budget':0,'runs':[],
           'jobs':manifest['ordered_samples'],'deadline_s':180,'concurrency':1,'automatic_retries':0,
           'order_sha256':manifest['original_order_sha256'],'continuation_manifest_sha256':MANIFEST_SHA,
           'original_batch_id':manifest['original_batch_id'],'original_ledger_sha256':manifest['original_ledger_sha256'],
           'prior_client_dispatches':12,'max_new_client_dispatches':8,'implementation_sha256':hashes(),
           'upstream_generation_attempts':'UNKNOWN; client dispatch budget is not an upstream generation counter'}
    base.save(root/'ledger.json',state);return state


def load(root):
    root=safe_root(root);manifest=frozen();s=runtime.read(root/'ledger.json')
    expected={'version':'pilot02.continuation.v1','root':str(root),'jobs':manifest['ordered_samples'],
              'deadline_s':180,'concurrency':1,'automatic_retries':0,'order_sha256':manifest['original_order_sha256'],
              'continuation_manifest_sha256':MANIFEST_SHA,'original_batch_id':manifest['original_batch_id'],
              'original_ledger_sha256':manifest['original_ledger_sha256'],'prior_client_dispatches':12,
              'max_new_client_dispatches':8,'implementation_sha256':hashes()}
    if any(s.get(k)!=v for k,v in expected.items()):raise ValueError('CONTINUATION_SCOPE_CHANGED')
    if s['mode'] not in ('DRY_RUN','REAL','OFFLINE_FIXTURE'):raise ValueError('MODE')
    if s['reserved_budget']!=len(s['runs']) or len(s['runs'])>8:raise ValueError('CONTINUATION_BUDGET')
    for i,row in enumerate(s['runs']):
        if row['index']!=i+1 or row['job']!=s['jobs'][i] or row['artifact']!=f'run-{i+1:03d}':raise ValueError('CONTINUATION_RESERVATION_ORDER')
    return s


def authorize(s,path):
    grant=runtime.read(path)
    expected={'generation_authorized','batch_id','output_root','order_sha256','max_dispatches','deadline_s','concurrency',
              'user_authorization_statement','original_batch_id','prior_client_dispatches','continuation_manifest_sha256'}
    if set(grant)!=expected or grant['generation_authorized'] is not True:raise ValueError('NEW_CONTINUATION_AUTHORIZATION_REQUIRED')
    for key,state_key in [('batch_id','batch_id'),('output_root','root'),('order_sha256','order_sha256'),
                          ('original_batch_id','original_batch_id'),('prior_client_dispatches','prior_client_dispatches'),
                          ('continuation_manifest_sha256','continuation_manifest_sha256')]:
        if grant[key]!=s[state_key]:raise ValueError('CONTINUATION_AUTHORIZATION_SCOPE')
    if type(grant['max_dispatches']) is not int or not 1<=grant['max_dispatches']<=8:raise ValueError('CONTINUATION_MAXIMUM_EIGHT')
    if grant['deadline_s']!=180 or grant['concurrency']!=1 or not isinstance(grant['user_authorization_statement'],str) or not grant['user_authorization_statement'].strip():
        raise ValueError('CONTINUATION_AUTHORIZATION_POLICY')
    bound={'sha256':runtime.sha(path),'grant':grant}
    if s['authorization'] is not None and s['authorization']!=bound:raise ValueError('AUTHORIZATION_CANNOT_BE_REPLACED')
    if s['authorization'] is None:
        if s['mode']!='DRY_RUN' or s['status']!='DRY_RUN' or s['runs']:raise ValueError('AUTHORIZATION_STATE')
        s.update(authorization=bound,mode='REAL',status='READY')
    return s


def check_preflight(s,path,config):
    p=runtime.read(path)
    if (p.get('status')!='PASS' or p.get('batch_id')!=s['batch_id'] or p.get('execution_host')!='ubuntu-robot'
        or p.get('continuation_manifest_sha256')!=MANIFEST_SHA or p.get('bridge_config_sha256')!=runtime.sha(config)
        or p.get('server_timeout_s')!=190 or p.get('client_timeout_s')!=180 or p.get('single_worker') is not True
        or p.get('non_generating_auth_and_tunnel_check') is not True or p.get('model')!='gpt-6-astra' or p.get('reasoning')!='medium'):
        raise ValueError('FRESH_CONTINUATION_PRODUCTION_CHECK_REQUIRED')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(p['checked_at'])).total_seconds()
    if not 0<=age<=900:raise ValueError('PRODUCTION_CHECK_STALE')


def run(root,*,real=False,authorization=None,preflight=None,config=None):
    with base.lock():
        s=load(root)
        if not real:return {'status':'DRY_RUN_NO_DISPATCH','batch_id':s['batch_id'],'original_orders':[j['planned_order'] for j in s['jobs']],
                            'new_dispatches':0,'reserved_budget':s['reserved_budget'],'prior_client_dispatches':12,'max_new_client_dispatches':8}
        if any(x is None for x in (authorization,preflight,config)):raise ValueError('NEW_AUTHORIZATION_AND_PRODUCTION_CHECK_REQUIRED')
        s=authorize(s,authorization);check_preflight(s,preflight,config)
        bridge=runtime.MacBridgeConfig.load(config)
        base.save(Path(root)/'ledger.json',s)
        # Local indices 1..8 map to unchanged original planned_order 13..20.
        # Reuse the sealed reservation/stop/pairing/transport/scoring engine.
        return base.advance(root,s,lambda job,path:base.perform(job,path,bridge),s['authorization']['grant']['max_dispatches'])


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','status']);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--real',action='store_true');p.add_argument('--authorization',type=Path);p.add_argument('--preflight',type=Path);p.add_argument('--bridge-config',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        if a.real or a.authorization:raise ValueError('PREPARE_IS_DRY_RUN')
        with base.lock():result=prepare(a.output)
    elif a.action=='status':result=load(a.output)
    else:result=run(a.output,real=a.real,authorization=a.authorization,preflight=a.preflight,config=a.bridge_config)
    print(json.dumps({k:v for k,v in result.items() if k not in ('jobs','runs','authorization')},indent=2))

if __name__=='__main__':main()
