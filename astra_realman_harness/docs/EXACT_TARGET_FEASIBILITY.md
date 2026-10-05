# Exact-target proposal / feasibility / execution（2026-10-05）

三、四视角均生效。task 与 schema 不变，不修改 Astra 原始 delta 或 target；没有缩放、替代 waypoint、投影、自动 recovery。

1. Proposal：保存 raw_proposal.txt、parsed_action.json、planned_commands.json。target 保持 fresh current xyz/rpy + 原始 delta 的现有逐项相加语义。
2. Feasibility：exact_target_feasibility.py 调用已有 SDK rm_algo_inverse_kinematics，q_in=新鲜关节角（deg），q_pose=原始 target（m/rad），flag=1（欧拉角）。只求解一次，不发送运动。
3. Execution：PASS_IK 且检查与 action/state/target 的绑定一致时，使用原始 target 调用既有 rm_movej_p；IK 解只用于诊断，不转为 joint command。无机械臂动作时 NOT_REQUIRED，夹爪沿用已验证路径。

返回1 -> REJECTED_IK，不构造 executor、不发送任何 actuator channel（包括同 proposal 的夹爪），重新观察。previous.last_result 包含 status、original_target、feasibility.status/return_code/reason/planner_status、command=null channels；下一轮由 Astra 自己决策。

返回0 + 有效解 -> PASS_IK。负数、未知值、非法解、异常 -> CHECK_ERROR，停止。真实硬件命令返回失败/异常仍停止，禁止把实际执行失败冒充 preflight 拒绝。

当前没有已核实的独立无执行轨迹规划器，因此 planner_status=NOT_CHECKED_NO_INDEPENDENT_PLANNER；不伪造 REJECTED_PLANNING，也不宣称 IK 通过就已证明路径无碰撞。现有 frame/state/error/时效校验、控制器限位、50轮上界和人工 STOP 保留。

每步独立文件：raw_proposal.txt、parsed_action.json、planned_commands.json、feasibility.json、executed_action.json、sdk_result.json、execution_result.json（真实模式）、after_state.json、next_observation.json。拒绝时执行文件记录空命令，实际 after state 重新读取。模型下一轮能看到失败，但不会收到改动作建议。原始失败 IK 返回数组保留为 raw_ik_return；不作为有效关节解。

启动命令未变，先结束旧进程再重启，正在运行的 Python 不会热更新。三视角 scripts/run_left_terminal.py；四视角 scripts/run_left_fourview.py。--live --execute 启用真实执行；省略 --execute 为 dry-run。--replay 仍不加载 SDK。软件 STOP 阻止后续命令，不能保证中断已发送的阻塞运动。

验证：11 项 feasibility/完整循环 mock + 11 项 executor mock + 21 项接口 + 7 项四视角测试，共50项通过。三/四视角均覆盖“第一轮拒绝 -> 下一轮接收失败上下文 -> 新原始动作执行 -> done”；覆盖 SDK 异常、硬件失败停止和目标/状态绑定。无新 Astra 调用，无硬件运动。

SDK 本地接口证据：/home/tongji/aloha/RealMan_Control/Robotic_Arm/rm_robot_interface.py:5762；参数 flag 定义 rm_ctypes_wrap.py:3389。独立只读原目标对照证据：logs/movej-p-readonly-diagnosis-20261005T090516Z。
