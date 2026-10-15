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
    args = p.parse_args()
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
    w = None; stream = None
    report = {'model_requests': 0, 'source_route': 'full_numeric_known_d3_urdf_effort_04',
              'status': 'RUNNING', 'variant': 'read_only_drive_and_contact_telemetry',
              'measured_actuator_and_tendon_torque': 'UNKNOWN_API_UNAVAILABLE'}
    try:
        w = DualScene(args.output)
        stream = (w.output/'readback.jsonl').open('x', buffering=1)
        original_step = w.scene.step
        def step():
            if w.steps >= 6400:
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
        run_reference(w, report, fixed_pickup_orientation=True)
    except Exception as exc:
        report.update(status='INCOMPLETE', error=repr(exc), traceback=traceback.format_exc())
    finally:
        if stream: stream.close()
        if w:
            report.update(last_step=w.steps, sim_time_s=w.steps*w.dt)
            w.observe(w.output/'final_observation'); w.close()
            report['historical_process_score_unchanged'] = evaluate(w.output)
            (w.output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if report['status'] == 'INCOMPLETE': raise SystemExit(1)


if __name__ == '__main__': main()
