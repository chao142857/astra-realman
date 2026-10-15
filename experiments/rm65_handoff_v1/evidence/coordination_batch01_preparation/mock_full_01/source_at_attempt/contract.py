"""Public task facts, independent scoring and left/right-only initialization."""
import copy
import json
from pathlib import Path
import numpy as np
from action_interface import execute_action
from evaluate_workspace import at_goal, forbidden
from workspace_task import CRITERIA as ORIGINAL_CRITERIA

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = json.loads((HERE/'conditions.json').read_text())
ORDER = json.loads((HERE/'order.json').read_text())
CONDITIONS = {v['id']: v for v in SPEC['conditions']}
CRITERIA = json.loads((HERE/'criteria.json').read_text())
for _key in ('position_tolerance_m','orientation_tolerance_rad','minimum_open_gap_m',
             'max_physical_penetration_m','dwell_s','post_numeric_action_observation_s','terminal_hold_s'):
    assert CRITERIA[_key] == ORIGINAL_CRITERIA[_key], 'ORIGINAL_THRESHOLDS_CHANGED'
TASK = SPEC['task_id']
INSTRUCTION = ('任务 dual_arm_coordination_batch01：按 task_policy.visit_order 完成两个占位阶段，'
    '每只机械臂的 TCP 在其给定目标连续保持至少 0.5 秒。终态第二只臂保持其目标，'
    '第一只臂回到本回合初始 Ready TCP，连续保持 2 秒。双夹爪全程打开，不抓物；'
    '不得互臂接触或发生非预期机械臂/桌面接触。自主决定数值目标和顺序/并行关系。'
    '仅输出给定 JSON schema。done=true 仅表示停止，随后保持驱动目标观察 2 秒，不代表成功。')


def tcp(state):
    return [*state['actual_grasp_center_world'], *state['flange_pose_world'][3:]]


def policy(condition_id, initial_ready):
    c = CONDITIONS[condition_id]
    return {'task_id': TASK, 'condition_id': condition_id,
            'visit_order': c['visit_order'],
            'left_goal_world_wxyz': c['left_goal_world_wxyz'],
            'right_goal_world_wxyz': c['right_goal_world_wxyz'],
            'initial_ready_world_wxyz': copy.deepcopy(initial_ready),
            'dwell_s': .5, 'post_numeric_action_observation_s': .5, 'terminal_hold_s': 2.}


def validate_policy(p):
    if not isinstance(p, dict) or p.get('condition_id') not in CONDITIONS:
        raise ValueError('FROZEN_CONDITION_REQUIRED')
    ready = p.get('initial_ready_world_wxyz', {})
    if set(ready) != {'left', 'right'} or p != policy(p['condition_id'], ready):
        raise ValueError('TASK_POLICY_CHANGED')
    nominal = json.loads((HERE/'ready_reference.json').read_text())
    for side, value in ready.items():
        x = np.asarray(value, float)
        if x.shape != (7,) or not np.isfinite(x).all() or abs(np.linalg.norm(x[3:])-1) > .002:
            raise ValueError('READY_POSE_INVALID')
        if np.linalg.norm(x[:3]-nominal[side][:3]) > 1e-5 or np.max(abs(x[3:]-nominal[side][3:])) > 1e-4:
            raise ValueError('READY_LAYOUT_CHANGED')


def prepare_initial(world, condition_id):
    from dual_scene import CONTROLLER
    if CONTROLLER != 'original' or world.solver_record['mode'] != 'original':
        raise ValueError('ORIGINAL_CONTROLLER_AND_SOLVER_REQUIRED')
    world.numeric_post_hold_steps = 125
    ready = {s: tcp(a.state()) for s, a in world.arms.items()}
    public = policy(condition_id, ready); validate_policy(public)
    side = CONDITIONS[condition_id]['initial_occupant']
    proposal = {'done': False, 'execution': 'sequential', 'actions': [
        {'arm': side, 'kind': 'tcp', 'pose_world_wxyz': public[side+'_goal_world_wxyz'], 'opening_fraction': None}]}
    receipt = execute_action(world, proposal)
    if not receipt['ok']: raise RuntimeError('INITIAL_OCCUPANCY_FAILED:'+str(receipt))
    (world.output/'initialization_PRIVATE.json').write_text(json.dumps({'proposal': proposal, 'receipt': receipt}, indent=2)+'\n')
    world.campaign_policy = public
    world.task_start_step = world.steps
    (world.output/'public_policy.json').write_text(json.dumps(public, indent=2)+'\n')
    return world.observe(world.output/'task_initial')


def assess(rows, dt, public, *, safety_stop=False):
    """Same tolerances/contact rules as V1, with explicit first/second roles."""
    validate_policy(public)
    first, second = public['visit_order']
    count_first = count_second = 0
    first_done = second_done = None
    bad, terminal, gaps = [], [], []
    for row in rows:
        if first_done is None:
            count_first = count_first+1 if at_goal(row['arms'][first], public[first+'_goal_world_wxyz']) else 0
            if count_first*dt >= .5-1e-8: first_done = row['step']
        else:
            count_second = count_second+1 if at_goal(row['arms'][second], public[second+'_goal_world_wxyz']) else 0
            if count_second*dt >= .5-1e-8 and second_done is None: second_done = row['step']
        violations = forbidden(row)
        bad.extend({'step': row['step'], **v} for v in violations)
        gap = [row['arms'][s]['actual_pad_gap_m'] for s in ('left', 'right')]
        gaps.extend(gap)
        terminal.append(at_goal(row['arms'][second], public[second+'_goal_world_wxyz']) and
                        at_goal(row['arms'][first], public['initial_ready_world_wxyz'][first]) and
                        min(gap) > .07 and not violations)
    n = int(round(2./dt))
    checks = {'first_dwell_0_5s': first_done is not None, 'subsequent_second_dwell_0_5s': second_done is not None,
              'no_interarm_contact': not any(v['kind']=='INTERARM' for v in bad),
              'no_unexpected_arm_table_contact': not any(v['kind']=='UNEXPECTED_TABLE_OR_STAND' for v in bad),
              'grippers_remain_open': bool(gaps) and min(gaps)>.07,
              'final_goals_continuous_2s': len(terminal)>=n and all(terminal[-n:]),
              'no_physical_protection_stop': not safety_stop}
    return {'version': 'rm65.coordination.batch01.physical.v1', 'condition_id': public['condition_id'],
            'visit_order': public['visit_order'], 'pass': all(checks.values()), 'checks': checks,
            'first_dwell_completed_step': first_done, 'second_dwell_completed_step': second_done,
            'minimum_actual_gap_m': min(gaps) if gaps else None, 'violations': bad,
            'tolerances': {k: ORIGINAL_CRITERIA[k] for k in ('position_tolerance_m', 'orientation_tolerance_rad', 'max_physical_penetration_m')},
            'source': 'PRIVATE_ACTUAL_PHYSICS_NOT_MODEL_CONTEXT'}


def rescore(folder):
    from decision4_trace import read_rows
    folder = Path(folder); e=json.loads((folder/'episode.json').read_text())
    p=json.loads((folder/'public_policy.json').read_text())
    result=assess([r for r in read_rows(folder) if r['step']>=e['task_start_step']], .004, p,
                  safety_stop=e.get('safety_stop',False))
    (folder/'independent_score.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('episode',type=Path)
    print(json.dumps(rescore(p.parse_args().episode),indent=2))
