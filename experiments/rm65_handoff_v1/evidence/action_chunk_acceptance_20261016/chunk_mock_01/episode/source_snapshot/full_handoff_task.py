"""Full original task, table initial state. Reuse existing four-RGB transport."""
import copy
import importlib.util
import action_interface as original

TASK='handoff_place_full'
INSTRUCTION=('完整任务：初始红色方块在桌面，左右臂空手、夹爪打开。'
    '由左臂抓起方块，完成双臂交接；左臂释放后右臂独立持物，'
    '由右臂搬到蓝色目标区域、松开，并使方块稳定放置。'
    '你从抓取前接管，自主决定全部数值 TCP 目标、夹爪操作和动作次序。'
    '目标区域中心及尺寸见 task_policy。不得把抓取、接取或退出阶段当作整任务完成。'
    'done=false 时给出非空动作组；done=true 时 actions 必须为 []，表示停止并被动观察2秒。'
    '末端目标使用给定的共同世界坐标和四元数约定。仅输出给定JSON schema。')
POLICY={'task_id':TASK,'initial_condition':'cube on table; both arms empty; both grippers open',
        'target_zone_center_xy_m':[.52,.16],'target_zone_half_size_m':.07,
        'required_complete_process':['left_table_pickup','physical_handoff','right_independent_hold','right_carry','right_release_and_stable_place'],
        'phase_completion_is_not_task_success':True}


def context_from_observation(obs,history):
    c,images=original.context_from_observation(obs,history)
    c.update(instruction=INSTRUCTION,task_policy=copy.deepcopy(POLICY))
    validate_context(c,images);return c,images


def validate_context(c,images):
    if c.get('instruction')!=INSTRUCTION or c.get('task_policy')!=POLICY:raise ValueError('FULL_TASK_CONTRACT_CHANGED')
    check=copy.deepcopy(c);check.pop('task_policy');check['instruction']=original.INSTRUCTION
    original.validate_context(check,images)


spec=importlib.util.spec_from_file_location('spatial_eval._full_handoff_transport',original.V0/'spatial_eval/mac_bridge.py')
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
transport.validate_context=validate_context
transport.parameter_audit=lambda r:original.full_command_audit(r.get('command'))


class FullAdapter(transport.MacBridgeAdapter):
    def __init__(self,config):super().__init__(config,offline_test=True,timeout_limit_s=180)
    def infer(self,context,images,folder,*,real=False,timeout_s=180):
        if real:raise ValueError('NEW_FULL_TASK_AUTHORIZATION_REQUIRED')
        return super().infer(context,images,folder,real=False,timeout_s=timeout_s)
