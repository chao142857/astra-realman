"""One no-carry shared-workspace witness, using the original numeric interface.

Private engineering trajectory, not an Astra result or a public action recipe.
No alternate target search, controller variant, bridge or budget ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import traceback

import numpy as np
from scipy.spatial.transform import Rotation
from diagnose_decision4 import ROOT, HISTORY, relocate_runtime_mesh_paths
from fixed_pose_check import LEDGER_SHA, save

SPEC = json.loads((ROOT / 'shared_workspace_yield_v1.json').read_text())


def tcp(state):
    return state['actual_grasp_center_world'] + state['flange_pose_world'][3:]


def at_goal(state, goal):
    p = float(np.linalg.norm(np.asarray(state['actual_grasp_center_world']) - goal[:3]))
    r = float((Rotation.from_quat(np.roll(goal[3:], -1)).inv() *
               Rotation.from_quat(np.roll(state['flange_pose_world'][3:], -1))).magnitude())
    return p < SPEC['position_tolerance_m'] and r < SPEC['orientation_tolerance_rad']


def assess(rows, ready_right, dt):
    n = int(round(SPEC['dwell_s'] / dt))
    right_count = left_count = 0
    right_done = left_done = None
    for r in rows:
        if right_done is None:
            right_count = right_count + 1 if at_goal(r['arms']['right'], SPEC['right_goal_world_wxyz']) else 0
            if right_count >= n:
                right_done = r['step']
        else:
            left_count = left_count + 1 if at_goal(r['arms']['left'], SPEC['left_goal_world_wxyz']) else 0
            if left_count >= n and left_done is None:
                left_done = r['step']
    interarm = [r['step'] for r in rows for c in r['contacts']
                if any(s.startswith('L__') for s in c['names']) and any(s.startswith('R__') for s in c['names'])]
    gaps = [r['arms'][s]['actual_pad_gap_m'] for r in rows for s in ('left', 'right')]
    final = rows[-1]
    checks = {'right_dwell_then_later_left_dwell': right_done is not None and left_done is not None,
              'final_left_at_shared_goal': at_goal(final['arms']['left'], SPEC['left_goal_world_wxyz']),
              'final_right_at_ready': at_goal(final['arms']['right'], ready_right),
              'no_interarm_contact': not interarm,
              'both_grippers_open': min(gaps) > 0.07,
              'no_object_grasp': not any(any(r['bilateral_contact'].values()) for r in rows)}
    return {'checks': checks, 'pass': all(checks.values()),
            'right_dwell_completed_step': right_done, 'later_left_dwell_completed_step': left_done,
            'interarm_contact_steps': interarm, 'minimum_gripper_gap_m': min(gaps)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    output = a.output.resolve()
    assert socket.gethostname() == 'Ubuntu-Robot'
    assert output.is_relative_to(ROOT / 'evidence/shared_workspace_yield_20261015') and not output.exists()
    assert hashlib.sha256((HISTORY / 'ledger.json').read_bytes()).hexdigest() == LEDGER_SHA
    assert os.environ.get('RM65_CONTROLLER', 'original') == os.environ.get('RM65_SOLVER', 'original') == 'original'
    os.environ['RM65_LAYOUT'] = str(ROOT / SPEC['layout'])
    from dual_scene import DualScene, CONFIG
    from action_interface import execute_action
    report = {'status': 'INITIALIZING', 'source': 'PRIVATE_ENGINEERING_NOT_ASTRA', 'new_model_requests': 0,
              'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'spec': SPEC, 'mesh_path_relocation': relocate_runtime_mesh_paths(CONFIG), 'actions': []}
    world = None
    def move(side, goal, label):
        proposal = {'done': False, 'execution': 'sequential', 'actions': [
            {'arm': side, 'kind': 'tcp', 'pose_world_wxyz': goal, 'opening_fraction': None}]}
        receipt = execute_action(world, proposal)
        report['actions'].append({'label': label, 'proposal': proposal, 'receipt': receipt})
        save(output / 'progress_PRIVATE.json', report)
        return receipt
    try:
        world = DualScene(output)
        world.start_video()
        ready = {s: tcp(arm.state()) for s, arm in world.arms.items()}
        report['ready_tcp_world_wxyz'] = ready
        world.observe(output / 'ready_observation')
        if not move('left', SPEC['left_goal_world_wxyz'], 'private_initial_left_occupies_shared')['ok']:
            raise RuntimeError('INITIAL_SHARED_TARGET_REJECTED_NO_ALTERNATE')
        world.phase_name = 'private_shared_initial_dwell'
        world.tick(125)
        report['task_start_step'] = world.steps
        world.observe(output / 'task_initial')
        before = world.steps
        blocked = move('right', SPEC['right_goal_world_wxyz'], 'negative_control_right_enters_occupied_shared')
        report['negative_control'] = {'receipt': blocked, 'physics_steps': world.steps-before,
                                     'must_be_collision_rejection': True}
        reasons = json.dumps(blocked)
        if blocked['ok'] or blocked['executed'] or world.steps != before or 'COLLISION' not in reasons:
            raise RuntimeError('COUPLING_NEGATIVE_CONTROL_NOT_DEMONSTRATED')
        # A single predeclared witness. Every new endpoint uses original IK and
        # full shared-world interpolation precheck; no trajectory replacement.
        witness = [('left', ready['left'], 'left_yields_to_ready'),
                   ('right', SPEC['right_goal_world_wxyz'], 'right_visits_shared'),
                   ('right', ready['right'], 'right_yields_to_ready'),
                   ('left', SPEC['left_goal_world_wxyz'], 'left_returns_shared')]
        for side, goal, label in witness:
            if not move(side, goal, label)['ok']:
                raise RuntimeError('WITNESS_STEP_REJECTED_NO_ALTERNATE:' + label)
            world.phase_name = label + '_dwell'
            world.tick(125)
        world.phase_name = 'witness_final_hold'
        world.tick(500)
        rows = [r for r in world.records if r['step'] >= report['task_start_step']]
        report['assessment'] = assess(rows, ready['right'], world.dt)
        report['status'] = 'PHYSICAL_WITNESS_PASS' if report['assessment']['pass'] else 'PHYSICAL_WITNESS_FAIL'
    except Exception as exc:
        report.update(status='STOPPED', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if world:
            save(output / 'final_state_PRIVATE.json', world.records[-1])
            world.frame()
            world.observe(output / 'final_observation')
            world.close()
        assert hashlib.sha256((HISTORY / 'ledger.json').read_bytes()).hexdigest() == LEDGER_SHA
        if output.exists():
            save(output / 'result.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
