"""Private engineering diagnosis of old initialization goals in the wider layout.

Endpoint IK only. Never executes a trajectory, repairs a target, or calls a model.
"""
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
os.environ['RM65_LAYOUT'] = str(root / 'scene_v2_wide180.json')
from dual_scene import DualScene

world = DualScene(args.output)
rows = []
try:
    actual = {side: arm.state() for side, arm in world.arms.items()}
    cases = [(side, 'actual_FK_roundtrip',
              state['actual_grasp_center_world'] + state['flange_pose_world'][3:])
             for side, state in actual.items()]
    cases += [('right', 'old_initial_right_park', [.55, .18, .18, 0, 0, 1, 0]),
              ('left', 'old_initial_left_pregrasp', [.36, 0, .18, 0, 1, 0, 0]),
              ('left', 'old_initial_left_grasp', [.36, 0, .04, 0, 1, 0, 0])]
    for side, name, pose in cases:
        row = {'arm': side, 'case': name, 'target_tcp_world_wxyz': pose, 'executed': False}
        try:
            plan = world.arms[side].plan_tcp(pose)
            row.update(status='IK_ENDPOINT_PASS_ONLY', solution_arm_q=plan['position'][-1].tolist())
        except (ValueError, RuntimeError) as exc:
            row.update(status='REJECTED', reason=str(exc))
        rows.append(row)
        print(json.dumps(row), flush=True)
    (world.output / 'probe.json').write_text(json.dumps({
        'checks': rows, 'physics_steps': world.steps, 'sim_time_s': world.steps*world.dt,
        'action_groups': world.group_count, 'model_calls': 0,
        'scope': 'Fixed endpoint IK queries, not a proof of global reachability or infeasibility.'
    }, indent=2)+'\n')
finally:
    world.close()
