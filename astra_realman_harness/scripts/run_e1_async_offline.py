#!/usr/bin/env python3
"""E1-B offline only. Delayed stub subprocess; no real-model launch option."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

PROCESS_ENTRY=time.monotonic()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.async_v1 import AsyncRuntime


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--backend',choices=('fixture','sapien'),default='fixture')
    p.add_argument('--assets',type=Path)
    p.add_argument('--condition',choices=('B0','B1'),required=True)
    p.add_argument('--scenario',choices=('known-goal','delayed-goal'),default='delayed-goal')
    p.add_argument('--case',choices=('normal','deny','target-change','execution-failure','late','stop','model-stop'),default='normal')
    p.add_argument('--delay-s',type=float,default=.25)
    p.add_argument('--budget-s',type=float,default=120)
    p.add_argument('--request-timeout-s',type=float,default=30)
    p.add_argument('--hold-limit-s',type=float,default=.5)
    p.add_argument('--lookahead-steps',type=int,default=100)
    p.add_argument('--seed',type=int,default=2)
    p.add_argument('--video',action='store_true')
    a=p.parse_args()
    if a.backend=='sapien' and not a.assets:p.error('sapien requires hash-protected --assets')
    if a.case not in ('normal','deny','model-stop') and a.condition!='B1':p.error('fault injections require B1')
    if a.case!='normal' and a.scenario!='delayed-goal':p.error('fault/task fixtures require delayed-goal')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[2]
    result={'status':'INCOMPLETE','source':'DELAYED_STUB_NOT_ASTRA','model_calls':0,'hardware_calls':0,
            'subagents':0,'seed':a.seed,'backend':a.backend,'pid':os.getpid(),
            'command':[sys.executable,*sys.argv],'cwd':os.getcwd(),
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'git_status':subprocess.check_output(['git','status','--short'],cwd=root,text=True),
            'reset':'fresh process and reinitialization; not exact state clone',
            'video':a.video,'process_entry_monotonic':PROCESS_ENTRY}
    backend=runtime=None;stop_requested=False
    def stop(*_):
        nonlocal stop_requested
        stop_requested=True
        if runtime:runtime.stop('EXTERNAL_STOP')
        elif backend:backend.stop()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        if a.backend=='sapien':
            from scripts.codex_astra_mac_bridge import preflight
            from sim_skills.rm65 import RM65Backend,ASSISTANCE
            # Version/help only, no prompt. Before scene creation.
            result['cli_preflight']=preflight('/home/alex/.nvm/versions/node/v22.23.2/bin/codex',a.output/'cli-preflight')
            if result['cli_preflight']['status']!='PASS':raise RuntimeError('CLI_PREFLIGHT_FAILED')
            if stop_requested:raise RuntimeError('STOP_BEFORE_SCENE')
            result['privileged_assistance']=ASSISTANCE
            init=time.monotonic();backend=RM65Backend(a.assets,a.output/'scene',a.seed,a.video)
            # Override only wait-mode metadata on this new instance, not frozen class/code.
            backend.decision_wait_mode='owner_wall_paced_hold_or_approved_motion'
        else:
            from sim_skills.async_fixture import FixtureBackend
            init=time.monotonic();backend=FixtureBackend(a.output/'scene')
        if stop_requested:backend.stop();raise RuntimeError('STOP_DURING_INITIALIZATION')
        result['setup']=backend.setup_held()
        result['initialization_wall_s']=time.monotonic()-init
        result['initialization_physics_s']=backend.steps*backend.dt
        result['start_state']=backend.s.state()
        targets_path=Path(__file__).resolve().parents[1]/'config/sim_rm65_targets.json'
        targets=json.loads(targets_path.read_text())
        (a.output/'targets.json').write_text(json.dumps(targets,indent=2)+'\n')
        runtime=AsyncRuntime(backend,targets,a.output/'episode',condition=a.condition,scenario=a.scenario,case=a.case,
                 delay_s=a.delay_s,budget_s=a.budget_s,request_timeout_s=a.request_timeout_s,
                 hold_limit_s=a.hold_limit_s,lookahead_steps=a.lookahead_steps)
        result['episode']=runtime.run();result['status']=result['episode']['status']
    except Exception as exc:
        result.update(status='FAIL' if backend else 'BLOCKED',error=repr(exc));traceback.print_exc()
    finally:
        if backend:backend.close()
        result['process_wall_s']=time.monotonic()-PROCESS_ENTRY
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
