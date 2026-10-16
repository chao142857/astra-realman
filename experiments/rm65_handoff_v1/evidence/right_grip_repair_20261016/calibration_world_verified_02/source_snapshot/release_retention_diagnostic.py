"""Private, zero-model replay of known_d3_urdf_effort_04 with read-only telemetry.

Same table initialization, numeric proposals and executor. No body/qpos writes,
no force tuning, no task-level helper is exposed to the public model interface.
"""
import argparse
import json
import os
from pathlib import Path
import traceback

import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--right-solver-control', action='store_true',
                   help='Single declared local solver control, 32 position / 8 velocity iterations after receiving.')
    p.add_argument('--pgs-controller-check', action='store_true',
                   help='Existing PGS integration with unchanged urdf_effort_hold_v2; archived numeric prefix.')
    args = p.parse_args()
    assert not (args.right_solver_control and args.pgs_controller_check)
    root = Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT'] = str(root/'scene_v4_ready_transfer_1100.json')
    assert os.environ['RM65_CONTROLLER'] == 'urdf_effort_hold_v2'
    assert os.environ.get('RM65_SOLVER', 'original') == 'original'
    from dual_scene import DualScene, CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from gripper_drive_audit import drives
    from full_handoff_reference import run_reference
    from evaluate_process import evaluate
    relocate_runtime_mesh_paths(CONFIG)
    import sapien
    original_create = sapien.Engine.create_scene
    if args.pgs_controller_check:
        def create_pgs(engine, config=None):
            cfg = sapien.physx.get_scene_config(); cfg.enable_tgs = False
            return original_create(engine, cfg)
        sapien.Engine.create_scene = create_pgs
    w = None; stream = None
    report = {'model_requests': 0, 'source_route': 'full_numeric_known_d3_urdf_effort_04',
              'status': 'RUNNING', 'variant': ('PGS_with_unchanged_urdf_effort_hold_v2' if args.pgs_controller_check else ('right_solver_32_8_after_receive' if args.right_solver_control else 'read_only_drive_and_contact_telemetry')),
              'measured_actuator_and_tendon_torque': 'UNKNOWN_API_UNAVAILABLE'}
    try:
        w = DualScene(args.output)
        sapien.Engine.create_scene = original_create
        report['actual_enable_tgs'] = bool(sapien.physx.get_scene_config().enable_tgs)
        assert report['actual_enable_tgs'] is (not args.pgs_controller_check)
        import action_interface
        original_execute = action_interface.execute_action
        calls = 0
        def execute(world, action):
            nonlocal calls
            calls += 1
            if calls == 10:
                if not args.pgs_controller_check: assert world.steps == 7018, 'PRESERVED_PREFIX_STEP_MISMATCH'
                (world.output/'before_left_release_PRIVATE.json').write_text(json.dumps(world.records[-1], indent=2)+'\n')
                if args.right_solver_control:
                    arm = world.arms['right'].robot
                    record = {'step': world.steps, 'scope': 'right articulation constraint solver only',
                        'before': [arm.get_solver_position_iterations(), arm.get_solver_velocity_iterations()],
                        'requested': [32, 8], 'gripper_drive_and_targets_unchanged': True}
                    arm.set_solver_position_iterations(32); arm.set_solver_velocity_iterations(8)
                    record['after'] = [arm.get_solver_position_iterations(), arm.get_solver_velocity_iterations()]
                    report['local_solver_control'] = record
            return original_execute(world, action)
        action_interface.execute_action = execute
        stream = (w.output/'readback.jsonl').open('x', buffering=1)
        original_step = w.scene.step
        def step():
            if w.steps >= 100:
                row = {'before_step': w.steps+1, 'phase': w.phase_name, 'arms': {}}
                for side, arm in w.arms.items():
                    row['arms'][side] = {'drives': drives(arm),
                        'qpos': arm.robot.get_qpos().tolist(),
                        'qvel': arm.robot.get_qvel().tolist(),
                        'external_qf_command_NOT_measured_torque': arm.robot.get_qf().tolist()}
                stream.write(json.dumps(row)+'\n')
            original_step()
        w.scene.step = step
        w.start_video(); w.observe(w.output/'table_initial')
        prefix = None
        if args.pgs_controller_check:
            original = root/'evidence/full_handoff_restore_20261015/full_numeric_known_d3_urdf_effort_04'
            prefix = [json.loads((original/f'reference_{i:03d}/proposal_PRIVATE.json').read_text()) for i in range(10)]
            report['numeric_prefix_source'] = str(original)
            report['first_10_numeric_proposals_unchanged'] = True
        run_reference(w, report, fixed_pickup_orientation=True, frozen_numeric_prefix=prefix)
    except Exception as exc:
        report.update(status='INCOMPLETE', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if 'original_execute' in locals(): action_interface.execute_action = original_execute
        sapien.Engine.create_scene = original_create
        if stream: stream.close()
        if w:
            report.update(last_step=w.steps, sim_time_s=w.steps*w.dt)
            w.observe(w.output/'final_observation'); w.close()
            report['historical_process_score_unchanged'] = evaluate(w.output)
            (w.output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if report['status'] == 'INCOMPLETE': raise SystemExit(1)


if __name__ == '__main__': main()
