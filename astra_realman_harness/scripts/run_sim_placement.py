#!/usr/bin/env python3
"""One bounded physics episode. Does not import any hardware transport."""
import argparse
import importlib.metadata
import json
import os
import signal
import threading
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim_skills.rm65 import RM65Backend, ASSISTANCE
from sim_skills.runtime import PlacementRuntime, ScriptedPolicy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--condition', choices=('M', 'S'), default='S')
    p.add_argument('--seed', type=int, default=2)
    p.add_argument('--video', action='store_true')
    p.add_argument('--smoke-only', action='store_true')
    p.add_argument('--check-stop', action='store_true', help='Qualification: stop after held setup, then prove zero new commands')
    p.add_argument('--budget-s', type=float, default=120)
    p.add_argument('--model', choices=('stub', 'local-cli'), default='stub')
    p.add_argument('--authorize-model', action='store_true')
    p.add_argument('--max-model-requests', type=int, default=0)
    p.add_argument('--codex-executable', type=Path)
    p.add_argument('--targets', type=Path, default=Path(__file__).resolve().parents[1] / 'config/sim_rm65_targets.json')
    a = p.parse_args()
    if a.check_stop and (a.smoke_only or a.model!='stub'):
        p.error('--check-stop requires stub placement mode')
    policy = ScriptedPolicy()
    if a.model == 'local-cli':
        if not a.authorize_model or not a.codex_executable or not 1 <= a.max_model_requests <= 4:
            p.error('local-cli requires --authorize-model --max-model-requests 1..4 --codex-executable PATH')
        from sim_skills.model import LocalPolicy
        policy = LocalPolicy(a.codex_executable, a.output / 'model-worker', authorized=True,
                             max_requests=a.max_model_requests)
        print(json.dumps({'real_model_request_limit': a.max_model_requests, 'model': 'gpt-6-astra',
                          'effort': 'medium', 'decision_budget_s': a.budget_s}), flush=True)
    elif a.authorize_model or a.max_model_requests:
        p.error('model authorization flags require --model local-cli')
    a.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = {'status': 'INCOMPLETE', 'model_calls': 0, 'hardware_calls': 0,
              'seed': a.seed, 'reset': 'fresh process + recorded reinitialization; not exact state restore',
              'privileged_assistance': ASSISTANCE, 'pid': os.getpid(),
              'command': sys.argv, 'versions': {x: importlib.metadata.version(x)
                  for x in ('sapien', 'mplib', 'numpy', 'scipy', 'toppra')},
              'renderer': 'default raster', 'camera_resolution': [640, 480]}
    backend = None
    runtime = None
    stop_requested = threading.Event()
    def stop(*_):
        stop_requested.set()
        if runtime is not None:runtime.stop()
        if backend is not None:backend.stop()
        if hasattr(policy, 'stop_event'):policy.stop_event.set()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    (a.output / 'result.json').write_text(json.dumps(result, indent=2))
    try:
        backend = RM65Backend(a.assets, a.output / 'scene', a.seed, a.video)
        if stop_requested.is_set():
            backend.stop()
            raise RuntimeError('STOP_DURING_INITIALIZATION')
        before = backend.observe()
        step = backend.steps
        time.sleep(.05)
        result['paused_wait_verified'] = backend.steps == step
        backend.s.tick(5)
        result['explicit_step_verified'] = backend.steps == step + 5
        result['initial_observation'] = before
        if a.smoke_only:
            # Zero-joint reset is fully extended upward; +Z there has no IK.
            # Reuse the legacy service's generic workspace preparation pose.
            target = [.30, 0., .15, 0., 1., 0., 0.]
            result['legal_move'] = backend.s.move_tcp(target)
            result['final_observation'] = backend.observe()
            result['status'] = 'PASS' if result['legal_move']['ok'] else 'FAIL'
        else:
            result['setup'] = backend.setup_held()
            targets = json.loads(a.targets.read_text())
            (a.output / 'targets.json').write_text(json.dumps(targets, indent=2))
            runtime = PlacementRuntime(backend, targets, a.output / 'placement',
                                       condition=a.condition, policy=policy, budget_s=a.budget_s,
                                       max_requests=a.max_model_requests if a.model=='local-cli' else 4)
            if a.check_stop:
                stop_step, stop_actions = backend.steps, backend.s.action_count
                runtime.stop()
            result['placement'] = runtime.run()
            result['status'] = result['placement']['status']
            if a.check_stop:
                result['stop_qualification'] = {'expected_placement_status':'FAIL',
                    'new_physics_steps':backend.steps-stop_step, 'new_scene_actions':backend.s.action_count-stop_actions,
                    'new_model_attempts':result['placement']['model_attempts']}
                result['status'] = 'PASS' if (result['placement']['status']=='FAIL' and
                    backend.steps==stop_step and backend.s.action_count==stop_actions and
                    result['placement']['model_attempts']==0) else 'FAIL'
                result['scope'] = 'STOP_PROTOCOL_TEST_NOT_PLACEMENT_SUCCESS'
    except Exception as exc:
        result.update(status='FAIL' if backend else 'BLOCKED', error=repr(exc))
        traceback.print_exc()
    finally:
        result['model_calls'] = policy.calls
        if backend:
            result.update(physics_steps=backend.steps, dt=backend.dt,
                          physics_time_s=backend.steps * backend.dt,
                          scene_action_calls=backend.s.action_count)
            backend.close()
        result['wall_time_s'] = time.monotonic() - started
        result['simulated_seconds_per_wall_second'] = result.get('physics_time_s', 0) / result['wall_time_s']
        (a.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
