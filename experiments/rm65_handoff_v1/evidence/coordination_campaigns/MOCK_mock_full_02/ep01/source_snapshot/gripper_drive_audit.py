"""One original D4 readback audit, not a model runner or controller sweep."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import traceback
import numpy as np
from diagnose_decision4 import ROOT, EPISODE, provenance, relocate_runtime_mesh_paths, replay_saved
from decision4_trace import read_rows, compare_start


def save(p, value):
    Path(p).write_text(json.dumps(value, indent=2)+'\n')


def drives(arm):
    return {j.name: {'stiffness': j.get_stiffness(), 'damping': j.get_damping(),
                     'force_limit': j.get_force_limit(), 'mode': j.get_drive_mode(),
                     'position_target': float(j.get_drive_target()[0]),
                     'velocity_target': float(j.get_drive_velocity_target()[0])}
            for j in arm.joints}


@contextmanager
def record_tendon_calls(records):
    import sapien.physx as physx
    original = physx.PhysxArticulation.create_fixed_tendon
    def create(art, chain, coefficients, recip_coefficients, *args, **kwargs):
        record = {'chain': [l.name for l in chain], 'coefficients': list(coefficients),
                  'reciprocal_coefficients': list(recip_coefficients), 'args': list(args),
                  'kwargs': dict(kwargs), 'postconstruction_native_tendon_readback': 'API_UNAVAILABLE'}
        result = original(art, chain, coefficients, recip_coefficients, *args, **kwargs)
        records.append((art, record))
        return result
    physx.PhysxArticulation.create_fixed_tendon = create
    try:
        yield
    finally:
        physx.PhysxArticulation.create_fixed_tendon = original


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); output = a.output.resolve()
    assert output.is_relative_to(ROOT/'evidence/gripper_drive_audit_20261015') and not output.exists()
    report = {'new_model_requests': 0, 'controller': 'original', 'status': 'INITIALIZING',
              'historical_provenance': provenance(), 'actual_drive_torque_Nm': 'UNKNOWN_NO_RELIABLE_NATIVE_READBACK',
              'qf_semantics': 'Applied generalized external-force command, not a measured drive/tendon/contact torque.'}
    os.environ['RM65_LAYOUT'] = str(ROOT/'scene_v4_ready_transfer_1100.json')
    assert os.environ.get('RM65_CONTROLLER', 'original') == 'original'
    assert os.environ.get('RM65_SOLVER', 'original') == 'original'
    from dual_scene import DualScene, CONFIG
    report['mesh_relocation'] = relocate_runtime_mesh_paths(CONFIG)
    from initial_transfer import prepare_left
    from action_interface import execute_action
    w = None; stream = None; tendon_calls = []; lifecycle = []
    def snapshot(stage):
        lifecycle.append({'stage': stage, 'step': w.steps,
                          'drives': {s: drives(arm) for s, arm in w.arms.items()}})
    try:
        with record_tendon_calls(tendon_calls):
            w = DualScene(output)
        w.start_video()
        topology = {}
        for side, arm in w.arms.items():
            topology[side] = {'joint_names': arm.names, 'master': arm.names[arm.master],
                              'mimics': arm.mimics,
                              'accepted_tendon_calls': [r for art, r in tendon_calls if art == arm.robot]}
        save(output/'actual_model_topology.json', topology)
        snapshot('after_constructor')
        stream = (output/'pre_step_drive_qf.jsonl').open('x', buffering=1)
        original_step = w.scene.step
        def measured_step():
            row = {'next_step': w.steps+1, 'phase': w.phase_name, 'arms': {}}
            for side, arm in w.arms.items():
                row['arms'][side] = {'drives': drives(arm), 'qpos': arm.robot.get_qpos().tolist(),
                                     'engine_qvel': arm.robot.get_qvel().tolist(),
                                     'external_qf_command': arm.robot.get_qf().tolist(),
                                     'actual_drive_torque_Nm': None}
            stream.write(json.dumps(row)+'\n')
            original_step()
        w.scene.step = measured_step
        for side, arm in w.arms.items():
            original_latch = arm.latch_grasp_contact
            def latch(_original=original_latch, _side=side):
                result = _original(); snapshot('after_contact_latch_'+_side); return result
            arm.latch_grasp_contact = latch
        prepare_left(w); snapshot('after_left_pickup_and_hold')
        historical = read_rows(EPISODE); ref = {r['step']: r for r in historical}
        report['initial_state_match'] = compare_start(w.records[-1], ref[3026])
        assert report['initial_state_match']['comparable']
        actions = [json.loads((EPISODE/f'decision_{i:03d}/proposal.json').read_text()) for i in range(4)]
        for i in range(3):
            result = replay_saved(w, actions[i], 3) if i == 2 else execute_action(w, actions[i])
            assert result['ok'] == (i == 2)
        snapshot('before_original_D4')
        report['pre_D4_state_match'] = compare_start(w.records[-1], ref[3467])
        assert report['pre_D4_state_match']['comparable']
        # One previously declared cross-check path, planned only. No execution,
        # no alternate candidate if rejected. Not used to tune any controller.
        spec = json.loads((ROOT/'evidence/gripper_drive_audit_20261015/predeclared_checks.json').read_text())
        target = spec['heldout']['target_world_wxyz']
        try:
            plan = w.arms['left'].plan_tcp(target)
            np.savez_compressed(output/'heldout_trajectory_FROZEN.npz', **plan)
            report['heldout_plan'] = {'status': 'IK_PLAN_FROZEN_NOT_EXECUTED', 'target': target,
                                      'full_original_collision_precheck_required_before_execution': True,
                                      'position_sha256': hashlib.sha256(plan['position'].tobytes()).hexdigest()}
        except (ValueError, RuntimeError) as exc:
            report['heldout_plan'] = {'status': 'UNAVAILABLE_NO_ALTERNATE_SELECTED', 'error': repr(exc)}
        report['status'] = 'ORIGINAL_D4_AUDIT_RUNNING'
        replay_saved(w, actions[3], 4)
        report['status'] = 'ORIGINAL_D4_COMPLETED'
    except Exception as exc:
        report.update(status='STOPPED', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if w:
            snapshot('after_guard_or_completion_before_close')
            save(output/'drive_lifecycle.json', lifecycle)
            report['last_step'] = w.steps
            if w.records:
                save(output/'last_physics_row_PRIVATE.json', w.records[-1])
            w.frame(); w.close()
        if stream:
            stream.close()
        if output.exists():
            save(output/'audit_result.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
