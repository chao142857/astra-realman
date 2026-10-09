#!/usr/bin/env python3
"""Local owner + filesystem-isolated independent research program. No hardware imports."""
import argparse,hashlib,json,os,re,select,shutil,signal,subprocess,sys,time,traceback
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from platform_v1.client import VERSION
from sim_skills.full_pnp.wire import strict_json
DURING_MOTION_RPC=frozenset(('research_capabilities','broker_submit','broker_poll','broker_cancel','world_poll','world_cancel','supervisor_cancel'))

def motion_requests(pending):
    """Drain only proposal/read/cancel calls; motion and observation remain serialized."""
    selected=[r for r in pending if r.get('method') in DURING_MOTION_RPC]
    pending[:]=[r for r in pending if r.get('method') not in DURING_MOTION_RPC]
    return selected

def sandbox(program,public):
    app=public.parent/'private/research_code';app.mkdir()
    shutil.copy2(program,app/'research.py');shutil.copy2(BASE/'platform_v1/client.py',app/'platform_client.py')
    venv=str(Path(sys.prefix).resolve())
    command=['/usr/bin/bwrap','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
       '--ro-bind',venv,venv,'--ro-bind',str(app),'/app','--ro-bind',str(public),'/public','--tmpfs','/tmp',
       '--proc','/proc','--dev','/dev','--unshare-all','--die-with-parent','--new-session','--chdir','/app',
       sys.executable,'-B','/app/research.py']
    return command,{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}

def safe_error(exc):
    msg=str(exc)
    return msg if re.fullmatch('[A-Z0-9_]+',msg) else 'OWNER_REJECTED_SEE_PRIVATE_AUDIT'

def run(a):
    if not 0<a.budget_s<=300:raise ValueError('BUDGET_0_TO_300_REQUIRED')
    if a.fake_cli and a.enable_real_model:raise ValueError('MODEL_MODE_CONFLICT')
    if not a.enable_real_model and a.model_max_requests:raise ValueError('NO_INHERITED_MODEL_BUDGET')
    if a.enable_real_model and not 1<=a.model_max_requests<=20:raise ValueError('EXPLICIT_NEW_MODEL_CAP_REQUIRED')
    if getattr(a,'research_fake_attempts',1)!=1 and not (getattr(a,'research_adapters',False) and a.fake_cli):raise ValueError('FAKE_RESEARCH_CAP_REQUIRES_FAKE_MODE')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    record={'version':VERSION,'status':'STARTING','source':a.source,'command':[sys.executable,*sys.argv],
      'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
      'git_status':subprocess.check_output(['git','status','--short'],cwd=BASE,text=True),'hardware_calls':0,'real_model_calls':0,
      'source_sha256':{str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*sorted((BASE/'platform_v1').rglob('*.py')),*sorted((BASE/'sim_skills/full_pnp').glob('*.py'))]},
      'seed':a.seed,'assets_manifest_sha256':hashlib.sha256((a.assets/'asset_manifest.json').read_bytes()).hexdigest()}
    (a.output/'started.json').write_text(json.dumps(record,indent=2))
    owner=None;proc=None;stream=None;rpc_raw=None;started=time.monotonic();pending=[];buffer=b'';eof=False
    def stop(*_):
        if owner:owner.b.stop()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    def dispatch_reply(r):
        owner.private_event('RPC_REQUEST',r)
        try:
            result=owner.dispatch(r);reply={'version':VERSION,'id':r.get('id'),'ok':True,'result':result}
        except Exception as exc:
            owner.private_event('RPC_ERROR',{'error':repr(exc),'request':r})
            owner.emit('error',{'code':safe_error(exc),'request_id':r.get('id')})
            reply={'version':VERSION,'id':r.get('id'),'ok':False,'error':safe_error(exc)}
        proc.stdin.write((json.dumps(reply,allow_nan=False)+'\n').encode());proc.stdin.flush()
    def poll():
        nonlocal buffer,eof
        if getattr(owner,'research',None) and getattr(owner,'active',None):
            for request in motion_requests(pending):dispatch_reply(request)
        if not proc or eof:return
        if select.select([proc.stdout],[],[],0)[0]:
            chunk=os.read(proc.stdout.fileno(),65536)
            if not chunk:eof=True;return
            rpc_raw.write(chunk);rpc_raw.flush() # preserve malformed/partial RPC bytes too
            buffer+=chunk
            if len(buffer)>1024*1024:raise RuntimeError('REQUEST_BYTES_CAP')
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1);r=strict_json(line.decode())
                if not isinstance(r,dict):raise ValueError('RPC_OBJECT_REQUIRED')
                if getattr(owner,'research',None) and getattr(owner,'active',None) and r.get('method') in DURING_MOTION_RPC:
                    # Proposal/read/cancel RPC only: never nested observe/execute/commit.
                    dispatch_reply(r);continue
                pending.append(r)
                if r.get('method')=='stop':owner.b.stop() # no scene access; owner hook stops before next step
                if r.get('version')==VERSION and set(r)=={'version','id','method','params'} and getattr(owner,'research',None) and r.get('method') in ('broker_cancel','world_cancel','supervisor_cancel'):
                    # Cancellation only, including during motion. Normal requests stay queued.
                    owner.research.dispatch(r['method'],r['params'])
    try:
        from sim_skills.full_pnp.infer_process import InferConfig,isolated_preflight
        config=InferConfig(str(a.fake_cli.absolute()),fixture=True) if a.fake_cli else InferConfig() if a.enable_real_model else None
        if config and isolated_preflight(config,a.output/'preflight')['status']!='PASS':
            raise RuntimeError('INFER_PREFLIGHT_FAILED_BEFORE_SCENE')
        from platform_v1.owner import Owner
        owner=Owner(a.assets,a.output,seed=a.seed,budget_s=a.budget_s,source=a.source,infer_config=config,max_requests=getattr(a,'research_fake_attempts',1) if a.fake_cli else a.model_max_requests)
        if getattr(a,'research_adapters',False):owner.enable_research_adapters()
        command,env=sandbox(a.program,owner.public);record['research_process_command']=command
        (owner.private/'research_command.json').write_text(json.dumps(command,indent=2))
        stream=(owner.private/'research_stderr.log').open('x')
        rpc_raw=(owner.private/'research_stdout.bin').open('xb')
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stream,env=env)
        owner.inbox_poll=poll
        while not owner.ended:
            poll()
            if pending:
                dispatch_reply(pending.pop(0))
            elif eof:raise RuntimeError('RESEARCH_PROGRAM_EOF_WITHOUT_FINISH')
            else:owner.idle()
            if owner.b.stopped and not pending:break
        record['status']='POLICY_CLOSED' if owner.ended else 'STOPPED'
    except Exception as exc:
        record.update(status='FAILED',error=repr(exc));traceback.print_exc()
        if owner:owner.b.stop()
    finally:
        if proc:
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            record['research_return_code']=proc.returncode
            if proc.returncode!=0 and record['status']=='POLICY_CLOSED':record['status']='RESEARCH_PROCESS_FAILED'
        if owner:
            owner.inbox_poll=lambda:None
            try:record['private_score_status']=owner.score_private()['status']
            except Exception as exc:record['private_score_error']=repr(exc)
            record.update(chunks=owner.chunks,observations=len(owner.observations),attempts=list(owner.slot.attempts.values()),
                fake_model_attempts=owner.slot.calls if a.fake_cli else 0,
                real_model_attempts=owner.slot.calls if a.enable_real_model else 0,
                real_model_calls=owner.slot.infer_calls if a.enable_real_model else 0,
                inference_function_calls=owner.slot.infer_calls,initialization_wall_s=owner.init_wall,
                episode_wall_s=time.monotonic()-owner.started,episode_physics_s=(owner.b.steps-owner.initial_step)*owner.b.dt)
            if getattr(owner,'research',None):
                broker=owner.research.broker
                record.update(research_adapter_version='astra.research.adapters.v1',broker_attempts=list(broker.rows.values()),
                    world_attempts=list(owner.research.world.rows.values()),
                    real_model_calls=record['real_model_calls']+(broker.infer_calls if a.enable_real_model else 0),
                    real_model_attempts=record['real_model_attempts']+(broker.calls if a.enable_real_model else 0),
                    fake_model_attempts=record['fake_model_attempts']+(broker.calls if a.fake_cli else 0),
                    inference_function_calls=record['inference_function_calls']+broker.infer_calls)
            try:owner.emit('closed',{'control_closed':True,'score':'PRIVATE_NOT_RETURNED'})
            except Exception as exc:record['event_close_error']=repr(exc)
            try:owner.close()
            except Exception as exc:record.update(cleanup_error=repr(exc),status='CLEANUP_FAILED')
            files={str(p.relative_to(owner.public)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(owner.public.rglob('*')) if p.is_file()}
            (owner.public/'index.json').write_text(json.dumps({'version':VERSION,'source':a.source,'files':files,'score_included':False,'mode':'READ_ONLY_REPLAY'},indent=2))
        if stream:stream.close()
        if rpc_raw:rpc_raw.close()
        record['process_wall_s']=time.monotonic()-started
        (a.output/'result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:record.get(k) for k in ('status','private_score_status','fake_model_attempts','real_model_calls','hardware_calls')}))
    return 0 if record['status']=='POLICY_CLOSED' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--program',type=Path,required=True);p.add_argument('--source',choices=['RESEARCH_PROGRAM','ENGINEERING_REFERENCE'],default='RESEARCH_PROGRAM')
    p.add_argument('--seed',type=int,default=2);p.add_argument('--budget-s',type=float,default=120)
    p.add_argument('--fake-cli',type=Path);p.add_argument('--enable-real-model',action='store_true');p.add_argument('--model-max-requests',type=int,default=0)
    p.add_argument('--research-adapters',action='store_true')
    p.add_argument('--research-fake-attempts',type=int,choices=range(1,21),default=1)
    raise SystemExit(run(p.parse_args()))
