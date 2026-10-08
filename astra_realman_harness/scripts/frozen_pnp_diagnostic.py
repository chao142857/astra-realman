#!/usr/bin/env python3
"""Prepare frozen B input; explicitly enable ONE 90s infer, parse only, no scene."""
import argparse
import base64
import fcntl
import hashlib
import json
import jsonschema
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.codex_astra_mac_bridge import command
from sim_skills.full_pnp.infer_process import CLI,InferConfig,sandbox_command
from sim_skills.full_pnp.wire import existing_infer_payload,strict_json,parse_bridge_record

CAP_S=90.

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,data):Path(path).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def inventory(root):return {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()}

def required_order_only(value):
    # JSON Schema required lists are sets. Comparison only: never sent or written back.
    if isinstance(value,dict):return {k:sorted(v) if k=='required' and isinstance(v,list) else required_order_only(v) for k,v in value.items()}
    if isinstance(value,list):return [required_order_only(v) for v in value]
    return value


def inspect_request(source):
    """Read only; validate source bytes against what the original infer really sent."""
    source=Path(source).resolve();payload=strict_json((source/'input_payload.json').read_bytes())
    if payload!=existing_infer_payload(source/'input_only'):raise ValueError('FINAL_PAYLOAD_MISMATCH')
    if (source/'input_only/payload.json').read_bytes()!=(source/'input_payload.json').read_bytes():raise ValueError('FROZEN_PAYLOAD_COPY')
    wire=payload['context']
    if wire['role']!='B':raise ValueError('ONLY_FROZEN_B_REQUEST')
    bridges=list((source/'infer_output/bridge').glob('*'))
    if len(bridges)!=1:raise ValueError('EXACTLY_ONE_ORIGINAL_INFER_REQUIRED')
    bridge=bridges[0];record=strict_json((bridge/'result.json').read_bytes())
    cmd=strict_json((bridge/'command.json').read_bytes());old_run=Path(record['local_log'])
    images=[old_run/'input_only'/('image-%d.png'%i) for i in range(len(payload['images']))]
    if cmd!=command(old_run,images,cmd[0]) or record['command']!=cmd:raise ValueError('ORIGINAL_CLI_CONFIG_MISMATCH')
    context=json.dumps(payload['context'],ensure_ascii=False,allow_nan=False).encode()
    schema=json.dumps(payload['schema'],allow_nan=False).encode()
    if any((bridge/name).read_bytes()!=context for name in ('prompt.json','input_only/context.json')):raise ValueError('ACTUAL_PROMPT_MISMATCH')
    if (bridge/'schema.json').read_bytes()!=schema:raise ValueError('ACTUAL_SCHEMA_MISMATCH')
    jsonschema.Draft202012Validator.check_schema(payload['schema'])
    owner_schema=strict_json((source/'schema.json').read_bytes())
    if required_order_only(owner_schema)!=required_order_only(payload['schema']):raise ValueError('OWNER_SCHEMA_MISMATCH')
    attachments=strict_json((bridge/'attachments.json').read_bytes())
    if len(attachments)!=len(payload['images']):raise ValueError('ACTUAL_ATTACHMENT_COUNT')
    image_hashes=[]
    for i,blob in enumerate(payload['images']):
        data=base64.b64decode(blob,validate=True);actual=bridge/'input_only'/('image-%d.png'%i)
        if actual.read_bytes()!=data or attachments[i]['sha256']!=digest(actual):raise ValueError('ACTUAL_PNG_MISMATCH')
        image_hashes.append(digest(actual))
    events=(bridge/'events.jsonl').read_text();stderr=(bridge/'stderr.log').read_text()
    if record['events']!=events or record['stderr']!=stderr:raise ValueError('ORIGINAL_EVENT_OR_STDERR_MISMATCH')
    evidence=event_summary(events)
    report={'status':'SOURCE_VERIFIED_NO_REQUEST','source_request':str(source),'bridge':str(bridge),
        'original_attempt':strict_json((source/'attempt.json').read_bytes()),'source_request_files':inventory(source),
        'payload_sha256':digest(source/'input_payload.json'),'wire_sha256':digest(source/'input_only/wire.json'),
        'prompt_sha256':digest(bridge/'prompt.json'),'schema_sha256':digest(bridge/'schema.json'),'image_sha256':image_hashes,
        'original_command':cmd,'original_environment':strict_json((bridge/'environment.json').read_bytes()),
        'owner_schema_order_only_difference':owner_schema!=payload['schema'],
        'original_latency_s':record.get('latency_s'),'original_error':record.get('error'),
        'original_return_code':record.get('return_code'),'original_raw_bytes':len(record.get('raw','').encode()),
        'events':evidence,'new_real_model_calls':0,'hardware_calls':0,'physics_scene_calls':0}
    return report,payload


def event_summary(raw):
    parsed=[];errors=[]
    for i,line in enumerate(raw.splitlines()):
        try:
            value=strict_json(line)
            if not isinstance(value,dict):raise ValueError('EVENT_NOT_OBJECT')
            parsed.append(value)
        except Exception as exc:errors.append({'line':i+1,'error':str(exc)})
    usages=[e for e in parsed if 'usage' in e]
    return {'types':[e.get('type') for e in parsed],'turn_completed':any(e.get('type')=='turn.completed' for e in parsed),
        'turn_completed_count':sum(e.get('type')=='turn.completed' for e in parsed),'event_parse_errors':errors,
        'usage_events':usages,'usage_raw':usages[0]['usage'] if len(usages)==1 else None,
        'error_items':[e for e in parsed if e.get('type') in ('error','turn.failed') or e.get('item',{}).get('type')=='error']}


def prepare(source,output):
    source=Path(source).resolve();root=Path(output).resolve()
    if root==source or root.is_relative_to(source) or source.is_relative_to(root) or (source.parent.name=='workers' and root.is_relative_to(source.parents[3])):raise ValueError('OUTPUT_MUST_NOT_OVERLAP_SOURCE')
    report,payload=inspect_request(source)
    root.mkdir(parents=True,exist_ok=False);frozen=root/'frozen';inp=frozen/'input_only';inp.mkdir(parents=True)
    for name in ('wire.json','payload.json',*[x['file'] for x in payload['context']['attachments']]):
        shutil.copyfile(source/'input_only'/name,inp/name)
    bridge=Path(report['bridge'])
    for name in ('prompt.json','schema.json'):shutil.copyfile(bridge/name,frozen/name)
    shutil.copyfile(source/'input_payload.json',frozen/'input_payload.json')
    save(frozen/'original-command.json',report['original_command'])
    save(root/'source-inspection.json',report)
    for path in frozen.rglob('*'):
        if path.is_file():path.chmod(0o444)
    manifest={'source_request':str(source),'frozen_files':inventory(frozen),'timeout_s':CAP_S,'attempt_cap':1,
        'model':'gpt-6-astra','effort':'medium','executable':report['original_command'][0],
        'source_bridge_sha256':digest(source/'worker_code/bridge.py'),
        'source_attempt_retained':True,'execution_allowed':False,'old_binding_preserved':True}
    save(root/'prepared.json',manifest)
    return report


def verify_prepared(root):
    meta=strict_json((root/'prepared.json').read_bytes())
    if inventory(root/'frozen')!=meta['frozen_files']:raise ValueError('PREPARED_INPUT_CHANGED')
    if meta['timeout_s']!=CAP_S or meta['attempt_cap']!=1 or meta['execution_allowed'] is not False:raise ValueError('DIAGNOSTIC_LIMITS')
    bridge=Path(__file__).with_name('codex_astra_mac_bridge.py')
    if digest(bridge)!=meta['source_bridge_sha256']:raise ValueError('VERIFIED_INFER_CHANGED')
    payload=strict_json((root/'frozen/input_payload.json').read_bytes())
    if payload!=existing_infer_payload(root/'frozen/input_only'):raise ValueError('PREPARED_PAYLOAD_MISMATCH')
    return meta,payload


def launch_command(run,config,deadline,payload_hash):
    cmd,env=sandbox_command(run,config)
    src=Path(__file__).with_name('frozen_pnp_infer_worker.py')
    dest=run/'worker_code/frozen_pnp_infer_worker.py';dest.write_bytes(src.read_bytes());dest.chmod(0o444)
    cmd[cmd.index('/code/infer_worker.py')]='/code/frozen_pnp_infer_worker.py'
    cmd+=['--payload-sha256',payload_hash,'--deadline',str(deadline)]
    return cmd,env


def run_once(prepared,*,authorized=False,config=None,timeout_s=CAP_S):
    if not authorized:raise ValueError('EXPLICIT_ONE_REQUEST_AUTHORIZATION_REQUIRED')
    config=config or InferConfig()
    if not config.fixture and timeout_s!=CAP_S:raise ValueError('REAL_DIAGNOSTIC_FIXED_90S')
    if not 0<timeout_s<=CAP_S:raise ValueError('TIMEOUT_CAP')
    root=Path(prepared).resolve();run=root/'request-001';run.mkdir(exist_ok=False) # consumes this bundle, even on failure
    start=time.monotonic();stopped=False;proc=None;lock=None
    report={'status':'PREPARING','attempt':1,'attempt_cap':1,'timeout_s':timeout_s,'source':config.source,
        'real_model_calls':0,'infer_entry_markers':0,'hardware_calls':0,'physics_scene_calls':0,'executed_actions':0,
        'candidate':None,'live_state_applicability':'NOT_CHECKED_NO_LIVE_STATE','turn_completed':False,'usage_raw':None,
        'server_model':'unknown','server_effort':'unknown','server_internal_retries':'unknown','stages':[]}
    def mark(stage,**data):
        report.update(status=stage,**data);report['stages'].append({'stage':stage,'monotonic':time.monotonic()});save(run/'attempt.json',report)
    def cancel(*_):
        nonlocal stopped
        stopped=True
        if (run/'infer_output').exists():(run/'infer_output/CANCEL').touch()
    old={sig:signal.signal(sig,cancel) for sig in (signal.SIGTERM,signal.SIGINT)}
    def reap():
        if proc and proc.poll() is None:
            cancel()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    try:
        mark('PREPARING');meta,payload=verify_prepared(root)
        if not config.fixture and config.executable!=meta['executable']:raise ValueError('CLI_ENTRY_CHANGED')
        lock=open('/tmp/astra-full-pnp-infer-owner-%d.lock'%os.getuid(),'a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        shutil.copytree(root/'frozen/input_only',run/'input_only');(run/'runtime').mkdir()
        deadline=time.monotonic()+timeout_s
        cmd,env=launch_command(run,config,deadline,digest(run/'input_only/payload.json'))
        save(run/'command.json',cmd);mark('PREPARED',deadline_monotonic=deadline)
        if stopped:raise RuntimeError('CANCELLED_BEFORE_LAUNCH')
        with (run/'worker.json').open('x') as stdout,(run/'worker-stderr.log').open('x') as stderr:
            mark('LAUNCHING');proc=subprocess.Popen(cmd,env=env,cwd=run/'input_only',stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
            mark('STARTED',pid=proc.pid)
            while proc.poll() is None:
                if stopped or time.monotonic()>=deadline:
                    report['stop_reason']='EXTERNAL_CANCEL' if stopped else 'DIAGNOSTIC_TIMEOUT';reap();break
                time.sleep(.02)
        mark('RETURNED',worker_return_code=proc.returncode)
        record=strict_json((run/'worker.json').read_bytes())
        report['bridge_error']=record.get('error');report['bridge_return_code']=record.get('return_code')
        report['infer_wall_s']=record.get('latency_s')
        if stopped or time.monotonic()>=deadline:raise RuntimeError('CANCELLED_OR_LATE_NO_RETRY')
        if proc.returncode!=0:raise RuntimeError('WORKER_FAILED_NO_RETRY')
        # No owner, backend, SAPIEN or execution path; only structural/binding checks.
        mark('PARSING');candidate=parse_bridge_record(record,payload['context'])
        receipt=event_summary(record.get('events',''))
        if receipt['turn_completed_count']!=1 or receipt['event_parse_errors'] or any(t in receipt['types'] for t in ('turn.failed','error')):
            raise ValueError('INVALID_OR_MISSING_TURN_COMPLETED')
        from sim_skills.full_pnp.protocol import validate_actions
        if candidate['operation']=='chunk':validate_actions(candidate['actions'])
        elif candidate['actions']:raise ValueError('NON_CHUNK_ACTIONS')
        report['candidate']=candidate;save(run/'parsed.json',candidate);mark('PARSED_OFFLINE_NOT_EXECUTED')
    except Exception as exc:mark('FAILED_NO_RETRY',error=type(exc).__name__+':'+str(exc))
    finally:
        reap()
        try:
            bridges=list((run/'infer_output/bridge').glob('*'))
            if len(bridges)==1:
                bridge=bridges[0]
                for source,name in (('last_message.json','raw.txt'),('events.jsonl','events.jsonl'),('stderr.log','stderr.log')):
                    path=bridge/source
                    if path.exists():shutil.copyfile(path,run/name)
                    else:(run/name).write_bytes(b'')
                report.update(event_summary((run/'events.jsonl').read_text()))
                report['actual_wire_unchanged']=all((bridge/src).read_bytes()==(root/'frozen'/dst).read_bytes() for src,dst in
                    [('prompt.json','prompt.json'),('input_only/context.json','prompt.json'),('schema.json','schema.json')]) and all(
                        (bridge/'input_only'/('image-%d.png'%i)).read_bytes()==base64.b64decode(blob) for i,blob in enumerate(payload['images']))
                actual=strict_json((bridge/'command.json').read_bytes());old_cmd=strict_json((root/'frozen/original-command.json').read_bytes())
                old_prefix=str(Path(old_cmd[old_cmd.index('--cd')+1]).parent);new_prefix=str(Path(actual[actual.index('--cd')+1]).parent)
                normalized=[v.replace(new_prefix,old_prefix) for v in actual];normalized[0]=old_cmd[0] if config.fixture else normalized[0]
                report['cli_config_unchanged_except_run_paths']=normalized==old_cmd
                if not report['actual_wire_unchanged'] or not report['cli_config_unchanged_except_run_paths']:
                    report.update(status='FAILED_NO_RETRY',error='ACTUAL_INPUT_OR_COMMAND_DRIFT',candidate=None)
        except Exception as exc:
            report.update(status='FAILED_NO_RETRY',artifact_error=repr(exc),candidate=None)
        report['infer_entry_markers']=int((run/'infer_output/infer_started.json').exists())
        report['real_model_calls']=0 if config.fixture else report['infer_entry_markers']
        for name in ('raw.txt','events.jsonl','stderr.log'):
            if not (run/name).exists():(run/name).write_bytes(b'')
        report['files_sha256']={k:v for k,v in inventory(run).items() if k not in ('attempt.json','result.json')}
        report['total_wall_s']=time.monotonic()-start
        save(run/'attempt.json',report);save(run/'result.json',report)
        for sig,handler in old.items():signal.signal(sig,handler)
        if lock:lock.close()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--source-request',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--prepared',type=Path,required=True);run.add_argument('--authorize-one-astra-request',action='store_true')
    a=p.parse_args()
    if a.mode=='prepare':r=prepare(a.source_request,a.output)
    else:
        if not a.authorize_one_astra_request:p.error('NO AUTHORIZATION: requires --authorize-one-astra-request; no request started')
        r=run_once(a.prepared,authorized=True)
    print(json.dumps({k:r[k] for k in ('status','new_real_model_calls','real_model_calls','turn_completed','error') if k in r}))
    return 1 if r['status']=='FAILED_NO_RETRY' else 0


if __name__=='__main__':raise SystemExit(main())
