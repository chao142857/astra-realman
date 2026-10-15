"""Independent actual-state process scoring for workspace_yield only."""
import numpy as np
from scipy.spatial.transform import Rotation
from workspace_task import CRITERIA, validate_policy


def at_goal(state, goal):
    p = np.linalg.norm(np.asarray(state['actual_grasp_center_world'])-goal[:3])
    r = (Rotation.from_quat(np.roll(goal[3:], -1)).inv() * Rotation.from_quat(np.roll(state['flange_pose_world'][3:], -1))).magnitude()
    return bool(p < CRITERIA['position_tolerance_m'] and r < CRITERIA['orientation_tolerance_rad'])


def forbidden(row):
    result = []
    for contact in row['contacts']:
        names = contact['names']
        if any(n.startswith('L__') for n in names) and any(n.startswith('R__') for n in names):
            result.append({'kind': 'INTERARM', 'names': names})
        for prefix, stand in [('L__', 'mounting_stand'), ('R__', 'right_mounting_stand')]:
            own = [n for n in names if n.startswith(prefix)]
            environment = [n for n in names if n in ('table', 'mounting_stand', 'right_mounting_stand')]
            if own and environment and not (own == [prefix+'base_link'] and all(n in ('table', stand) for n in environment)):
                result.append({'kind': 'UNEXPECTED_TABLE_OR_STAND', 'names': names})
    return result


def assess(rows, dt, public_policy, *, safety_stop=False):
    validate_policy(public_policy)
    right = left = 0
    right_done = left_done = None
    bad = []
    terminal = []
    gaps = []
    for row in rows:
        rgoal = at_goal(row['arms']['right'], public_policy['right_goal_world_wxyz'])
        lgoal = at_goal(row['arms']['left'], public_policy['left_goal_world_wxyz'])
        if right_done is None:
            right = right + 1 if rgoal else 0
            if right*dt >= CRITERIA['dwell_s']-1e-8:
                right_done = row['step']
        else:
            left = left + 1 if lgoal else 0
            if left*dt >= CRITERIA['dwell_s']-1e-8 and left_done is None:
                left_done = row['step']
        violations = forbidden(row)
        bad.extend({'step': row['step'], **v} for v in violations)
        open_ = all(row['arms'][s]['actual_pad_gap_m'] > CRITERIA['minimum_open_gap_m'] for s in ('left', 'right'))
        gaps.extend(row['arms'][s]['actual_pad_gap_m'] for s in ('left', 'right'))
        terminal.append(lgoal and at_goal(row['arms']['right'], public_policy['initial_right_ready_world_wxyz']) and open_ and not violations)
    n = int(round(CRITERIA['terminal_hold_s']/dt))
    checks = {'right_dwell_0_5s': right_done is not None,
              'subsequent_left_dwell_0_5s': left_done is not None,
              'no_interarm_contact': not any(v['kind']=='INTERARM' for v in bad),
              'no_unexpected_arm_table_contact': not any(v['kind']=='UNEXPECTED_TABLE_OR_STAND' for v in bad),
              'grippers_remain_open': bool(gaps) and min(gaps)>CRITERIA['minimum_open_gap_m'],
              'final_goals_continuous_2s': len(terminal)>=n and all(terminal[-n:]),
              'no_physical_protection_stop': not safety_stop}
    return {'criteria': CRITERIA, 'checks': checks, 'pass': all(checks.values()),
            'right_dwell_completed_step': right_done, 'later_left_dwell_completed_step': left_done,
            'violations': bad, 'minimum_actual_gap_m': min(gaps) if gaps else None,
            'source': 'PRIVATE_ACTUAL_PHYSICS_NOT_MODEL_CONTEXT'}


if __name__ == '__main__':
    import argparse,json
    from pathlib import Path
    from decision4_trace import read_rows
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args()
    episode=json.loads((a.folder/'episode.json').read_text())
    public=json.loads((a.folder/'workspace_public_policy.json').read_text())
    rows=[r for r in read_rows(a.folder) if r['step']>=episode['task_start_step']]
    score=assess(rows,.004,public,safety_stop=episode['status']=='PHYSICAL_EXECUTION_FAILURE')
    (a.folder/'independent_workspace_score.json').write_text(json.dumps(score,indent=2)+'\n')
    print(json.dumps(score,indent=2))
