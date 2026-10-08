#!/usr/bin/env python3
"""Full task offline ONLY. No real-model or hardware launch option."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.backend import FullTaskBackend


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--condition',choices=('script','B','F'),required=True)
    p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=2);p.add_argument('--video',action='store_true')
    p.add_argument('--delay-s',type=float,default=.8);p.add_argument('--budget-s',type=float,default=120)
    p.add_argument('--request-timeout-s',type=float,default=30);p.add_argument('--max-stub-calls',type=int,default=32)
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();backend=runtime=None
    r={'status':'INCOMPLETE','condition':a.condition,'source':'OFFLINE_NOT_ASTRA','real_model_calls':0,'hardware_calls':0,
       'seed':a.seed,'command':[sys.executable,*sys.argv],'pid':os.getpid(),
       'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
       'git_status':subprocess.check_output(['git','status','--short'],text=True),
       'reset':'fresh process; recorded initialization, not exact state clone'}
    base=Path(__file__).resolve().parents[1]
    sources=[Path(__file__),*sorted((base/'sim_skills/full_pnp').glob('*.py')),
             base/'sim_skills/rm65.py',base/'sim_skills/async_v1.py',base/'sim_skills/model.py',base/'scripts/codex_astra_mac_bridge.py']
    r['source_sha256']={str(f.relative_to(base)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    def stop(*_):
        if runtime:runtime.stop('EXTERNAL_STOP')
        elif backend:backend.stop()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        if not 0<a.budget_s<=300 or not 0<a.request_timeout_s<=30 or not 1<=a.max_stub_calls<=64 or not 0<=a.delay_s<=30:
            raise ValueError('OFFLINE_LIMITS: episode<=300s request<=30s attempts<=64 delay<=30s')
        r['asset_manifest_sha256']=hashlib.sha256((a.assets/'asset_manifest.json').read_bytes()).hexdigest()
        from scripts.codex_astra_mac_bridge import preflight
        r['cli_preflight']=preflight('/home/alex/.nvm/versions/node/v22.23.2/bin/codex',a.output/'cli-preflight')
        if r['cli_preflight']['status']!='PASS':raise RuntimeError('CLI_PREFLIGHT_FAILED')
        init=time.monotonic();backend=FullTaskBackend(a.assets,a.output/'scene',a.seed,a.video)
        r.update(initialization_wall_s=time.monotonic()-init,initialization_physics_s=backend.steps*backend.dt,
                 empty_start=backend.provenance)
        from sim_skills.full_pnp.runtime import FullRuntime
        runtime=FullRuntime(backend,a.output/'episode',condition=a.condition,delay_s=a.delay_s,
                            budget_s=a.budget_s,timeout_s=a.request_timeout_s,max_calls=a.max_stub_calls)
        r['episode']=runtime.run();r['status']=r['episode']['status']
    except Exception as exc:
        r.update(status='FAIL' if backend else 'BLOCKED',error=repr(exc));traceback.print_exc()
    finally:
        if backend:backend.close()
        r['process_wall_s']=time.monotonic()-start
        (a.output/'result.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
    return 0 if r['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
