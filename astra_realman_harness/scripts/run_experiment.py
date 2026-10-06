#!/usr/bin/env python3
"""Unified launch config for measured and legacy experiments; original runners retained."""
import argparse
import fcntl
import importlib.util
import json
import os
import shlex
import signal
import sys
import threading
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, read_json
from experiment_launch import DEFAULTS, ALL_PROFILES, validate, runner_args


def main():
    launch_argv=[sys.executable]+list(sys.orig_argv[1:] if hasattr(sys,'orig_argv') else sys.argv)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings',type=Path,help='JSON settings; explicit flags override it.')
    p.add_argument('--profile',choices=ALL_PROFILES)
    p.add_argument('--mode',choices=['shadow','execute'])
    p.add_argument('--task')
    p.add_argument('--max-steps',type=int)
    p.add_argument('--wall-budget-s',type=float)
    p.add_argument('--phase',choices=['placement','full-pick-place','diagnostic'])
    p.add_argument('--layout-id');p.add_argument('--trial-id')
    p.add_argument('--preview-port',type=int)
    p.add_argument('--no-preview',action='store_true')
    p.add_argument('--lock-path',type=Path,default=Path('/home/tongji/alex/astra_realman_harness/logs/auto-pick.lock'))
    p.add_argument('--print-command',action='store_true')
    a=p.parse_args()
    settings=dict(DEFAULTS)
    if a.settings:settings.update(read_json(a.settings))
    for key in DEFAULTS:
        value=getattr(a,key,None)
        if value is not None:settings[key]=value
    if not settings['task'].strip():
        settings['task']='[启动后输入任务]' if a.print_command else input('Task (verbatim; STOP cancels): ')
    if settings['task'].strip().upper()=='STOP':return 0
    try:settings=validate(settings)
    except ValueError as exc:p.error(str(exc))
    shared=bool(os.environ.get('ASTRA_CAMERA_HUB_URL'))
    argv=runner_args(settings,no_preview=a.no_preview or shared,lock_path=a.lock_path)
    if a.print_command:
        print(shlex.join([sys.executable,'-I','-B']+argv))
        if settings['profile'].startswith('legacy'):
            print('# legacy wall budget is enforced by this wrapper with SIGINT, not by the printed raw runner.')
        return 0
    if shared:
        from shared_cameras import SharedCameraSession
        import types
        sys.modules['camera_session']=types.SimpleNamespace(CameraSession=SharedCameraSession)
    with ExitStack() as stack:
        if settings['profile'].startswith('legacy'):
            (ROOT/'logs').mkdir(exist_ok=True)
            if a.lock_path.resolve() != (ROOT/'logs/auto-pick.lock').resolve():
                lock=stack.enter_context(a.lock_path.open('a+'))
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            # Cooperative stop only; never kill a blocking SDK call or retry commands.
            def expired():
                print('BUDGET → '+json.dumps({'status':'WALL_BUDGET_EXHAUSTED','wall_budget_s':settings['wall_budget_s']}),flush=True)
                os.kill(os.getpid(),signal.SIGINT)
            timer=threading.Timer(settings['wall_budget_s'],expired);timer.daemon=True;timer.start()
            stack.callback(timer.cancel)
        spec=importlib.util.spec_from_file_location('experiment_runner',argv[0])
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        sys.argv=argv
        print('EXPERIMENT CONFIG → '+json.dumps(settings,ensure_ascii=False),flush=True)
        from launch_provenance import snapshot, LaunchRecorder
        manifest=snapshot(settings,launch_argv,a.lock_path)
        with redirect_stdout(LaunchRecorder(sys.stdout,manifest)):
            return runner.main()

if __name__=='__main__':sys.exit(main())
