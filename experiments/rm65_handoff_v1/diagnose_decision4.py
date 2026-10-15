"""Only A/original, B/hold and C/2x-time for the first real fourth decision.

No model invocation, ledger write, object pose writes, controller change or IK
for saved successful trajectories. The original numeric executor and all its
collision/physical guards run unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import traceback
import numpy as np
from decision4_trace import read_rows, compare_start, analyze

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT/'evidence/transfer_runs/first_real_1100_20261015_01'
EPISODE = HISTORY/'execute_01'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def retime(plan, factor):
    assert factor in (1, 2)
    result = {k: np.array(v, copy=True) for k, v in plan.items()}
    if factor == 2:
        n = len(plan['position']); index = np.minimum(np.arange(2*n)/2, n-1)
        result['position'] = np.column_stack([np.interp(index, np.arange(n), plan['position'][:, j]) for j in range(6)])
        result['velocity'] = np.column_stack([np.interp(index, np.arange(n), plan['velocity'][:, j])/2 for j in range(6)])
        assert np.array_equal(result['position'][::2], plan['position'])
        assert np.array_equal(result['velocity'][::2]*2, plan['velocity'])
    return result


def replay_saved(world, action, group, factor=1):
    """Replace only planning with exact archived arrays, not execution or guards."""
    from action_interface import execute_action
    arm = world.arms['left']; original = arm.plan_tcp
    with np.load(EPISODE/f'group_{group:03d}/left_trajectory.npz') as z:
        plan = {k: z[k].copy() for k in z.files}
    assert np.array_equal(np.asarray(action['actions'][0]['pose_world_wxyz']), plan['target_tcp'])
    assert np.max(np.abs(arm.robot.get_qpos()-plan['start_full'])) <= 1e-4, 'ARCHIVED_PLAN_START_MISMATCH'
    plan = retime(plan, factor)
    called = []
    def archived(pose):
        assert not called and np.array_equal(pose, plan['target_tcp'])
        called.append(True)
        return {k: np.array(v, copy=True) for k, v in plan.items()}
    arm.plan_tcp = archived
    try:
        return execute_action(world, action)
    finally:
        arm.plan_tcp = original


def provenance():
    m = json.loads((HISTORY/'artifact_sha256.json').read_text())['sha256']
    for name, digest in m.items():
        assert sha(HISTORY/name) == digest, 'HISTORY_CHANGED:'+name
    old = json.loads((HISTORY/'ledger.json').read_text())
    assert old['status'] == 'STOPPED' and old['reserved_budget'] == 5
    # Do not import the gate or instantiate a Bridge. Verify source bytes directly.
    for name, digest in old['source_hashes'].items():
        if '/' not in name:
            assert sha(ROOT/name) == digest, 'SOURCE_CHANGED:'+name
    return {'historical_ledger_sha256': sha(HISTORY/'ledger.json'),
            'historical_batch_id': old['batch_id'], 'historical_status': 'STOPPED',
            'historical_client_dispatches': 5, 'new_model_requests': 0,
            'saved_d4_npz_sha256': sha(EPISODE/'group_004/left_trajectory.npz'),
            'host': socket.gethostname(), 'source_commit_baseline': 'f2d27bc',
            'diagnostic_source_sha256': sha(__file__)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant', choices=['A', 'B', 'C'], required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    assert socket.gethostname() in ('Ubuntu-Robot', 'tongji-Precision-3680'), 'EXPLICIT_SIMULATION_HOST_REQUIRED'
    output = a.output.resolve()
    assert output.is_relative_to(ROOT/'evidence/decision4_diagnosis_20261015') and not output.exists(), 'NEW_DIAGNOSTIC_OUTPUT_ONLY'
    prov = provenance()
    os.environ['RM65_LAYOUT'] = str(ROOT/'scene_v4_ready_transfer_1100.json')
    assert os.environ.get('RM65_CONTROLLER', 'original') == 'original'
    assert os.environ.get('RM65_SOLVER', 'original') == 'original'
    from dual_scene import DualScene
    from initial_transfer import prepare_left
    from action_interface import execute_action
    from evaluate_transfer import assess
    reference = read_rows(EPISODE); ref = {r['step']: r for r in reference}
    actions = [json.loads((EPISODE/f'decision_{i:03d}/proposal.json').read_text()) for i in range(4)]
    n = len(np.load(EPISODE/'group_004/left_trajectory.npz')['position'])
    # B covers full original planned motion + original 100-step settle, even if A aborts early.
    report = dict(prov, variant=a.variant, status='INITIALIZING', initialization_receipts=[],
                  original_motion_samples=n, stationary_observation_steps=n+100,
                  active_motion_scale=2 if a.variant == 'C' else 1,
                  retiming='C: 2N ticks, half-index interpolation of archived joint polyline; final endpoint repeated once; velocity /2. No IK or path replacement.',
                  instrument='Read-only qvel/drive-velocity sampling after each original physical tick. No extra physical steps.')
    w = None; measurement = None
    try:
        w = DualScene(output); w.start_video()
        measurement = (output/'measurements.jsonl').open('x', buffering=1)
        original_tick = w.tick
        def measured_tick(count):
            for _ in range(count):
                before = w.steps
                try:
                    original_tick(1)
                finally:
                    if w.steps != before:
                        row = {'step': w.steps,
                               'qvel': {s: arm.robot.get_qvel().tolist() for s, arm in w.arms.items()},
                               'drive_velocity_targets': {s: [float(j.get_drive_velocity_target()[0]) for j in arm.joints] for s, arm in w.arms.items()},
                               'object_angular_velocity': w.cube_body.get_angular_velocity().tolist()}
                        measurement.write(json.dumps(row)+'\n')
        w.tick = measured_tick
        prepare_left(w)
        report['after_left_initialization_match'] = compare_start(w.records[-1], ref[3026])
        if not report['after_left_initialization_match']['comparable']:
            raise ValueError('INITIAL_CONTACT_STATE_NOT_COMPARABLE')
        for i in range(3):
            before = w.steps
            receipt = replay_saved(w, actions[i], 3) if i == 2 else execute_action(w, actions[i])
            report['initialization_receipts'].append(receipt)
            if i < 2:
                assert w.steps == before and not receipt['ok'], 'EARLY_PROPOSAL_OUTCOME_CHANGED'
            else:
                assert receipt['ok'], 'THIRD_PROPOSAL_REPLAY_FAILED'
        (output/'before_d4_state_PRIVATE.json').write_text(json.dumps(w.records[-1], indent=2)+'\n')
        report['pre_d4_state_match'] = compare_start(w.records[-1], ref[3467])
        if not report['pre_d4_state_match']['comparable']:
            raise ValueError('PRE_D4_CONTACT_STATE_NOT_COMPARABLE')
        w.observe(output/'before_d4_observation')
        report['start_step'] = w.steps
        report['status'] = 'RUNNING_DIAGNOSTIC'
        if a.variant == 'B':
            w.phase_name = 'diagnostic_B_unchanged_drive_hold'; w.tick(n+100)
            report['receipt'] = {'ok': True, 'fourth_action_executed': False, 'unchanged_drive_hold_steps': n+100}
        else:
            report['receipt'] = replay_saved(w, actions[3], 4, 2 if a.variant == 'C' else 1)
        report['status'] = 'COMPLETED_WITHOUT_PHYSICAL_GUARD' if report['receipt']['ok'] else 'PRECHECK_REJECTED_NOT_PHYSICALLY_COMPARABLE'
    except Exception as exc:
        report.update(status='STOPPED_DIAGNOSTIC', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if measurement is not None:
            measurement.close()
        if w is not None:
            report['last_step'] = w.steps
            report['private_assessment_unchanged_scorer'] = assess(w.records, w.dt)
            (output/'last_physics_state_PRIVATE.json').write_text(json.dumps(w.records[-1], indent=2)+'\n')
            w.frame(); w.observe(output/'final_observation'); w.close()
            if report.get('start_step') is not None:
                analyze(output, output/'trace_analysis', report['start_step'])
        assert sha(HISTORY/'ledger.json') == prov['historical_ledger_sha256'], 'HISTORICAL_LEDGER_CHANGED'
        if output.exists():
            (output/'diagnostic_result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
