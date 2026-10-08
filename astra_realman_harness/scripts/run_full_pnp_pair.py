#!/usr/bin/env python3
"""Explicitly enabled one-shot B/F simulation pair. Never a hardware/service entry."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.infer_process import CLI,InferConfig,isolated_preflight

LIMITS={'conditions':['B','F'],'episodes_per_condition':1,'episode_budget_s':300,
        'attempts_per_episode':20,'total_attempt_cap':40,'request_timeout_s':30,'action_chunk_cap':12,
        'seed':2,'video':False,'max_in_flight':1,'max_pending':1}


def save(path,data):path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def source_hashes():
    base=Path(__file__).resolve().parents[1]
    paths=[*base.joinpath('sim_skills').rglob('*.py'),*base.joinpath('scripts').glob('*.py'),
           base/'config/sim_rm65_targets.json',base/'bimanual_demo/primitives.py',base/'decision_backends.py',base/'io_utils.py']
    return {str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def episode(a):
    """Fresh owner process; preflight before scene creation; no CLI retry."""
    from sim_skills.full_pnp.runtime import FullRuntime
    from scripts.audit_full_pnp_offline import audit
    root=a.output;root.mkdir(parents=True,exist_ok=False);backend=runtime=None;started=time.monotonic();cancelled=False
    result={'status':'INCOMPLETE','condition':a.episode,'source':'LOCAL_CODEX_ASTRA_RAW','real_model_calls':0,'hardware_calls':0,
            'limits':LIMITS,'command':[sys.executable,*sys.argv],'pid':os.getpid(),'seed':2,'video':False,
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=Path(__file__).parent).strip(),
            'source_sha256':source_hashes(),'reset':'fresh process; recorded initialization, not exact state clone',
            'server_model':'unknown','server_effort':'unknown','server_internal_retries':'unknown'}
    def stop(*_):
        nonlocal cancelled
        cancelled=True
        if runtime:runtime.stop('EXTERNAL_STOP')
        elif backend:backend.stop()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    lock=open('/tmp/astra-full-pnp-infer-owner-%d.lock'%os.getuid(),'a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        config=InferConfig(a.codex_executable)
        result['asset_manifest_sha256']=hashlib.sha256((a.assets/'asset_manifest.json').read_bytes()).hexdigest()
        result['cli_preflight']=isolated_preflight(config,root/'cli-preflight')
        if result['cli_preflight']['status']!='PASS':raise RuntimeError('CLI_PREFLIGHT_FAILED')
        if cancelled:raise RuntimeError('CANCELLED_BEFORE_SCENE')
        from sim_skills.full_pnp.backend import FullTaskBackend
        init=time.monotonic();backend=FullTaskBackend(a.assets,root/'scene',2,False)
        result.update(initialization_wall_s=time.monotonic()-init,initialization_physics_s=backend.steps*backend.dt,
                      empty_start=backend.provenance)
        if cancelled:raise RuntimeError('CANCELLED_BEFORE_EPISODE')
        runtime=FullRuntime(backend,root/'episode',condition=a.episode,budget_s=300,timeout_s=30,max_calls=20,infer_config=config)
        result['episode']=runtime.run();result['status']=result['episode']['status']
    except Exception as exc:result.update(status='FAIL' if backend else 'BLOCKED',error=repr(exc))
    finally:
        if runtime:
            runtime.slot.cancel();result['real_model_calls']=runtime.slot.infer_calls
            result['all_role_attempts']=runtime.slot.calls
        if backend:
            try:backend.close()
            except Exception as exc:result['cleanup_error']=repr(exc)
        result.update(process_wall_s=time.monotonic()-started,cancelled=cancelled)
        save(root/'result.json',result)
        try:
            report=audit(root);result['audit_status']=report['status']
            result['audit_integrity_ok']=not report['failure'] and not report['artifact_issues'] and all(
                row.get('wire_status')=='PASS' for row in report['requests'])
        except Exception as exc:result['audit_error']=repr(exc)
        save(root/'result.json',result);lock.close()
    return 0 if result['status']=='PASS' else 1


def classify(result,return_code):
    """No replacement runs. Infrastructure/protocol/execute faults abort the pair."""
    e=result.get('episode') or {}
    if result.get('cancelled') or result.get('error') or result.get('cleanup_error') or result.get('audit_error') or result.get('audit_integrity_ok') is False:
        return True
    if return_code not in (0,1) or not e or e.get('all_role_attempts',21)>20:return True
    if any(a['status']!='READY' for a in e.get('attempts',[])):return True
    error=e.get('error') or ''
    return bool(error and not (e['status']=='STOPPED' and 'STOP_NO_NEW_COMMAND' in error))


def pair(a):
    root=a.output;root.mkdir(parents=True,exist_ok=False)
    ledger={'scope':'ONE_SHOT_FULL_PNP_BF_PAIR_NOT_PERFORMANCE_CONCLUSION','limits':LIMITS,
            'inherited_budget':0,'hardware_calls':0,'source_sha256':source_hashes(),
            'episodes':[{'condition':c,'status':'NOT_RUN','allocated_attempts':20} for c in ('B','F')]}
    def persist():save(root/'ledger.json',ledger)
    process=None;cancelled=False;abort=None
    def stop(*_):
        nonlocal cancelled
        cancelled=True
        if process and process.poll() is None:process.terminate()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    lock=open('/tmp/astra-full-pnp-pair-%d.lock'%os.getuid(),'a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);persist()
        for row in ledger['episodes']:
            if abort or cancelled:
                row['reason']=abort or 'BATCH_CANCELLED';persist();continue
            if source_hashes()!=ledger['source_sha256']:raise RuntimeError('SOURCE_DRIFT')
            dest=root/row['condition']
            cmd=[sys.executable,str(Path(__file__).resolve()),'--enable-real-bf-pair','--episode',row['condition'],
                 '--assets',str(a.assets),'--output',str(dest),'--codex-executable',a.codex_executable]
            row.update(command=cmd,status='LAUNCHING');persist()
            try:
                with (root/(row['condition']+'.stdout.log')).open('x') as out,(root/(row['condition']+'.stderr.log')).open('x') as err:
                    process=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=out,stderr=err)
                    try:code=process.wait(timeout=600)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:process.wait(timeout=10)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
                        raise RuntimeError('OWNER_WATCHDOG_TIMEOUT_NO_RETRY')
                result=json.loads((dest/'result.json').read_text())
                row.update(status=result['status'],return_code=code,result=result,
                           actual_attempts=result.get('all_role_attempts',0),real_model_calls=result['real_model_calls'])
                if classify(result,code):abort='INTERFACE_PROTOCOL_EXECUTION_OR_BUDGET_FAILURE'
            except Exception as exc:
                row.update(status='ABORTED',reason=repr(exc),actual_attempts=None,real_model_calls=None);abort=repr(exc)
            finally:process=None;persist()
    except Exception as exc:abort=repr(exc)
    finally:
        ledger.update(abort_reason=abort,cancelled=cancelled,finished=True)
        # Missing records remain unknown, never silently counted as zero.
        counts=[r.get('actual_attempts',0 if r['status']=='NOT_RUN' else None) for r in ledger['episodes']]
        ledger['total_attempts']=sum(counts) if all(isinstance(n,int) for n in counts) else None
        persist();lock.close()
    print(json.dumps({'output':str(root),'abort_reason':abort,'total_attempts':ledger['total_attempts']}))
    return 1 if abort or cancelled else 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--enable-real-bf-pair',action='store_true',help='Explicit new authorization, never inherited')
    p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--codex-executable',default=CLI)
    p.add_argument('--episode',choices=('B','F'),help=argparse.SUPPRESS)
    a=p.parse_args()
    if not a.enable_real_bf_pair:p.error('NO AUTHORIZATION: requires --enable-real-bf-pair; no preflight, scene or infer started')
    a.output=a.output.resolve();a.assets=a.assets.resolve()
    return episode(a) if a.episode else pair(a)


if __name__=='__main__':raise SystemExit(main())
