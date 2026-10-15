"""Task facts and left-only initialization. No receiving/yielding witness here."""
import copy
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
CRITERIA = json.loads((ROOT / 'workspace_criteria_v1.json').read_text())
TASK = 'shared_workspace_yield_v1'
INSTRUCTION = ('任务 shared_workspace_yield_v1：完成两个占位阶段：右臂 TCP 在其给定目标位姿连续保持至少 0.5 秒，'
               '之后左臂 TCP 在其给定目标位姿连续保持至少 0.5 秒。终态左臂在给定目标，右臂回到本回合初始 Ready TCP，'
               '并连续保持 2 秒。两个夹爪全程保持打开，不抓物；不得互臂接触或发生非预期机械臂/桌面接触。'
               '目标位姿见 task_policy。自主决定所有后续数值目标、动作及顺序/并行关系。仅输出给定 JSON schema。'
               'done=true 表示停止，随后仅保持驱动目标观察 2 秒，不代表成功。')


def policy(ready_right):
    return {'task_id': TASK,
            'left_goal_world_wxyz': copy.deepcopy(CRITERIA['left_goal_world_wxyz']),
            'right_goal_world_wxyz': copy.deepcopy(CRITERIA['right_goal_world_wxyz']),
            'initial_right_ready_world_wxyz': list(ready_right),
            'dwell_s': CRITERIA['dwell_s'], 'post_numeric_action_observation_s': CRITERIA['post_numeric_action_observation_s'],
            'terminal_hold_s': CRITERIA['terminal_hold_s']}


def validate_policy(value):
    if not isinstance(value, dict):
        raise ValueError('WORKSPACE_POLICY_REQUIRED')
    expected = policy(value.get('initial_right_ready_world_wxyz', []))
    if value != expected or len(expected['initial_right_ready_world_wxyz']) != 7:
        raise ValueError('WORKSPACE_POLICY_CHANGED')
    ready = np.asarray(value['initial_right_ready_world_wxyz'], float)
    nominal = np.asarray(CRITERIA['nominal_initial_right_ready_world_wxyz'])
    if not np.isfinite(ready).all() or np.linalg.norm(ready[:3]-nominal[:3]) > 1e-5 or np.max(abs(ready[3:]-nominal[3:])) > 1e-4:
        raise ValueError('INITIAL_READY_NOT_FROZEN_LAYOUT')


def prepare_initial(world):
    from action_interface import execute_action
    world.numeric_post_hold_steps = 125
    state = world.arms['right'].state()
    public = policy([*state['actual_grasp_center_world'], *state['flange_pose_world'][3:]])
    validate_policy(public)
    proposal = {'done': False, 'execution': 'sequential', 'actions': [
        {'arm': 'left', 'kind': 'tcp', 'pose_world_wxyz': CRITERIA['left_goal_world_wxyz'], 'opening_fraction': None}]}
    receipt = execute_action(world, proposal)
    if not receipt['ok']:
        raise RuntimeError('WORKSPACE_LEFT_ONLY_INITIALIZATION_FAILED:' + str(receipt))
    (world.output / 'initialization_PRIVATE.json').write_text(json.dumps({'proposal': proposal, 'receipt': receipt}, indent=2)+'\n')
    world.workspace_policy = public
    (world.output / 'workspace_public_policy.json').write_text(json.dumps(public, indent=2)+'\n')
    world.workspace_task_start_step = world.steps
    # No expert motion follows. Public context is created with empty history.
    return world.observe(world.output / 'workspace_initial')
