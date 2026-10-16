"""One user-specified engineering target after the corrected physical D3 prefix.

No bridge, inference, ledger creation, new controller, or alternate target.
Only the already executed D3 prefix uses its saved trajectory. The NEW target
uses the unchanged numeric executor, including its original IK and precheck.
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
from diagnose_decision4 import ROOT, HISTORY, EPISODE, relocate_runtime_mesh_paths
from decision4_trace import compare_start, relative, angle, pad_penetration
from gripper_fix_regression import replay

TARGET = [0.34, 0, 0.22, 0, 1, 0, 0]
LEDGER_SHA = '2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1'
EVIDENCE = ROOT / 'evidence/fixed_pose_feasibility_20261015'


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def metrics(rows, dt):
    if not rows:
        return None
    p0, r0 = relative(rows[0])
    values = [relative(r) for r in rows]
    gaps = [r['arms']['left']['actual_pad_gap_m'] for r in rows]
    return {
        'first_step': rows[0]['step'], 'last_step': rows[-1]['step'],
        'elapsed_s': (rows[-1]['step'] - rows[0]['step']) * dt,
        'left_bilateral_every_step': all(r['bilateral_contact']['left'] for r in rows),
        'right_bilateral_any_step': any(r['bilateral_contact']['right'] for r in rows),
        'gap_range_m': [min(gaps), max(gaps)],
        'max_pad_penetration_mm': max(max(pad_penetration(r).values(), default=0.) for r in rows),
        'max_relative_translation_m': max(float(np.linalg.norm(p-p0)) for p, _ in values),
        'max_relative_rotation_deg': max(angle(r0, rot) for _, rot in values),
        'relative_position_first_last_m': [p0.tolist(), values[-1][0].tolist()],
        'object_position_first_last_world_m': [rows[0]['object_pose'][:3], rows[-1]['object_pose'][:3]],
        'minimum_object_z_m': min(r['object_pose'][2] for r in rows),
        'object_table_contact_any': any('target_cube' in c['names'] and 'table' in c['names']
                                        for r in rows for c in r['contacts']),
    }


def prepare_d3(world):
    """Private engineering prefix only. Does not execute any handoff/receiving."""
    from initial_transfer import prepare_left
    from action_interface import execute_action
    prepare_left(world)
    for i in range(3):
        action = json.loads((EPISODE / f'decision_{i:03d}/proposal.json').read_text())
        receipt = (replay(world, action, EPISODE / 'group_003/left_trajectory.npz')
                   if i == 2 else execute_action(world, action))
        if receipt['ok'] != (i == 2):
            raise RuntimeError('D3_PHYSICAL_PREFIX_CHANGED')
    reference = json.loads((ROOT / 'evidence/gripper_drive_audit_20261015/'
                           'fixed_hold_01/before_case_state_PRIVATE.json').read_text())
    comparison = compare_start(world.records[-1], reference)
    if not comparison['comparable']:
        raise RuntimeError('CORRECTED_STABLE_D3_STATE_MISMATCH:' + str(comparison))
    return comparison


def prepare_fixed_pose(world, report):
    """Reusable engineering initialization; expert logic ends on return.

    Failure propagates. There is no fallback pose, IK bypass, object write, or
    receiving/release/exit behavior. This is not a model-proposed action.
    """
    from action_interface import execute_action
    report['d3_start_comparison'] = prepare_d3(world)
    report['motion_start_step'] = world.steps
    save(world.output / 'before_target_state_PRIVATE.json', world.records[-1])
    world.observe(world.output / 'before_target_observation')
    proposal = {'done': False, 'execution': 'sequential', 'actions': [
        {'arm': 'left', 'kind': 'tcp', 'pose_world_wxyz': TARGET, 'opening_fraction': None}]}
    save(world.output / 'engineering_proposal.json', proposal)
    # Intentionally NO monkeypatch of plan_tcp: this new target must pass IK.
    report['target_receipt'] = execute_action(world, proposal)
    if not report['target_receipt']['ok']:
        report['status'] = 'NUMERIC_TARGET_REJECTED_OR_RESIDUAL_FAILURE'
        return None
    report['hold_start_step'] = world.steps
    world.phase_name = 'engineering_fixed_pose_post_motion_hold_2s'
    world.tick(500)
    report['hold_end_step'] = world.steps
    return world.observe(world.output / 'engineering_handoff_initial')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if socket.gethostname() != 'Ubuntu-Robot':
        raise ValueError('UBUNTU_ROBOT_ONLY')
    if not output.is_relative_to(EVIDENCE) or output.exists():
        raise ValueError('NEW_INDEPENDENT_OUTPUT_REQUIRED')
    if hashlib.sha256((HISTORY / 'ledger.json').read_bytes()).hexdigest() != LEDGER_SHA:
        raise ValueError('OLD_LEDGER_CHANGED')
    if os.environ.get('RM65_CONTROLLER', 'original') != 'original' or os.environ.get('RM65_SOLVER', 'original') != 'original':
        raise ValueError('ORIGINAL_CONTROLLER_AND_SOLVER_REQUIRED')
    os.environ['RM65_LAYOUT'] = str(ROOT / 'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene, CONFIG
    from evaluate_transfer import assess, CRITERIA
    report = {'status': 'INITIALIZING', 'new_model_requests': 0,
              'target_world_wxyz': TARGET, 'source': 'USER_SPECIFIED_ENGINEERING_NOT_ASTRA_D4',
              'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'original_ledger_sha256': LEDGER_SHA,
              'mesh_path_relocation': relocate_runtime_mesh_paths(CONFIG)}
    world = None
    try:
        world = DualScene(output)
        world.start_video()
        observation = prepare_fixed_pose(world, report)
        if observation is not None:
            report['status'] = 'MOTION_AND_2S_HOLD_COMPLETED'
    except Exception as exc:
        report.update(status='STOPPED', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if world:
            start = report.get('motion_start_step', world.steps)
            hold = report.get('hold_start_step')
            report['motion_metrics'] = metrics([r for r in world.records if start <= r['step'] <= (hold or world.steps)], world.dt)
            report['hold_metrics'] = metrics([r for r in world.records if hold is not None and r['step'] >= hold], world.dt)
            report['unchanged_transfer_assessment'] = assess(world.records, world.dt)
            m = report['motion_metrics']
            h = report['hold_metrics']
            report['engineering_pass'] = bool(report['status'] == 'MOTION_AND_2S_HOLD_COMPLETED'
                and report['unchanged_transfer_assessment']['checks']['initial_left_physical_hold']
                and all(x['left_bilateral_every_step'] and not x['object_table_contact_any']
                        and x['minimum_object_z_m'] > CRITERIA['minimum_object_center_z_m']
                        and x['max_pad_penetration_mm'] <= CRITERIA['max_pad_penetration_m']*1000
                        and x['max_relative_translation_m'] <= CRITERIA['relative_translation_drift_max_m']
                        and x['max_relative_rotation_deg'] <= CRITERIA['relative_rotation_drift_max_deg']
                        for x in (m, h)))
            report['selected_route'] = 'A_NEW_ENGINEERING_INITIALIZATION' if report['engineering_pass'] else 'B_PAUSE_CTAG_CARRYING'
            save(output / 'final_state_PRIVATE.json', world.records[-1])
            world.frame()
            world.observe(output / 'final_observation')
            world.close()
        if hashlib.sha256((HISTORY / 'ledger.json').read_bytes()).hexdigest() != LEDGER_SHA:
            raise ValueError('OLD_LEDGER_CHANGED')
        if output.exists():
            save(output / 'result.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
