"""Two actual resets, Ready Pose checks, and physical left pickup; no generation."""
import argparse
import json
import os
import traceback
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parent
os.environ['RM65_LAYOUT'] = str(root/'scene_v3_ready_transfer.json')
from dual_scene import DualScene, LAYOUT, initial_arm_q
from initial_transfer import prepare_left

a.output.mkdir(parents=True, exist_ok=False)
report = {'real_model_calls': 0, 'ready_resets': [], 'status': 'RUNNING'}
try:
    for reset in range(2):
        w = DualScene(a.output/f'reset_{reset}')
        try:
            w.start_video()
            ready = {}
            for side, arm in w.arms.items():
                q = arm.robot.qpos; limits = arm.robot.get_qlimits()
                drives = np.array([j.get_drive_target()[0] for j in arm.joints])
                expected = np.array(initial_arm_q(side))
                excess = np.maximum(limits[:,0]-q, q-limits[:,1])
                tolerance = arm.cfg['control']['joint_limit_tolerance_rad']
                tool_z = Rotation.from_quat(np.roll(arm.state()['flange_pose_world'][3:], -1)).apply([0, 0, 1])
                ready[side] = {'actual_qpos': q.tolist(), 'drive_targets': drives.tolist(),
                    'joint_limits': limits.tolist(), 'all_joints_within_limits': bool(np.all(q>=limits[:,0]) and np.all(q<=limits[:,1])),
                    'max_limit_excess_rad': float(max(0., excess.max())), 'original_limit_tolerance_rad': tolerance,
                    'within_original_limit_tolerance': bool(np.all(excess<=tolerance)),
                    'arm_drive_matches_config': bool(np.allclose(drives[arm.arm_indices], expected, atol=1e-6)),
                    'max_arm_tracking_error_rad': float(np.max(abs(q[arm.arm_indices]-expected))),
                    'tool_downward_cosine': float(-tool_z[2])}
                arm.init_planner()
            pairs = []
            for arm in w.arms.values():
                arm.motion.update_from_simulation()
                for c in arm.motion.planning_world.check_collision():
                    if c.link_name1.startswith(('L__','R__')) or c.link_name2.startswith(('L__','R__')):
                        pairs.append([c.object_name1,c.link_name1,c.object_name2,c.link_name2])
            row = {'arms': ready, 'fcl_collision_pairs': pairs}
            w.observe(w.output/'ready_observation');w.phase_name='ready_pose_hold';w.tick(250)
            report['ready_resets'].append(row)
            assert not pairs and all(x['within_original_limit_tolerance'] and x['arm_drive_matches_config'] and x['max_arm_tracking_error_rad']<.01 and x['tool_downward_cosine']>.999 for x in ready.values()), row
            prepare_left(w)
            report.setdefault('left_pickup_runs', []).append({'reset': reset, 'steps': w.steps,
                'left_bilateral_contact': w.arms['left'].bilateral_pad_contact(), 'right_held_ready': True})
        finally:
            w.close()
    report['reset_max_qpos_difference_rad'] = max(float(np.max(abs(np.array(report['ready_resets'][0]['arms'][s]['actual_qpos'])-np.array(report['ready_resets'][1]['arms'][s]['actual_qpos'])))) for s in ('left','right'))
    assert report['reset_max_qpos_difference_rad']<1e-6
    report['status']='PASS'
except Exception as exc:
    report.update(status='FAIL', error=repr(exc), traceback=traceback.format_exc())
    traceback.print_exc()
finally:
    (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report), flush=True)
