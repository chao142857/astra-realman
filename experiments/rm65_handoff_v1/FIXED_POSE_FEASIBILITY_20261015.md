# 单个固定姿态检查与下一轮路线

基线 `55395ef`；执行主机 ubuntu-robot。新增 Astra 请求 **0**，没有连接 Mac Bridge、创建授权 ledger 或使用旧剩余预算。原控制器、碰撞预检、2 mm 保护、四视角及 1.1 m 布局均未修改。

## 唯一持物目标：未通过 IK，未执行

从修复返回值后的物理抓取及归档 D3 恢复。与 `fixed_hold_01/before_case_state_PRIVATE.json` 比较，双臂 qpos、驱动目标、开度、物体位置、相对位置和接触对差异均为零；相对旋转比较存在约 0.0000024° 的浮点残差，原比较器通过。

只尝试用户指定的工程目标 `[0.34,0,0.22,0,1,0,0]`。这是独立工程对照，**不是原 Astra D4**。

原执行器返回：

```text
IK_REJECTED_NO_VALID_SOLUTION
pure_clik_success: false
within_joint_limits: false
collision_pairs: []
goal_unchanged: true
executed: false
```

此处 `within_joint_limits=false` 是 CLIK 没有得到候选时的派生标志，不能独立证明关节越界；空碰撞列表也不能证明目标无碰撞。准确结论是当前原 IK 未找到有效解，不是全局不可达证明。新目标执行物理步数为 0，未继续做 2 秒保持，也没有尝试其他持物目标。

拒绝时左夹爪仍双侧接触，实际开度 50.050224 mm，夹垫最大穿透 0.101628 mm；物体中心 `[0.1206628084,0.0000280247,0.1788694412]` m。全部原始状态和回执位于 `evidence/fixed_pose_feasibility_20261015/check_01/`。

**选择路线 B：暂停 CTAG 持物交接，不继续调夹爪或 PhysX。**

## 无持物双臂共享区任务：物理见证通过

固定任务 `shared_workspace_yield_v1`：左臂初始占用共享工位；右臂必须先到共享目标持续至少 0.5 秒，之后左臂再到自身共享目标持续至少 0.5 秒，最终右臂回到本回合初始 Ready TCP。双夹爪保持打开，不抓物。两个目标 TCP 均在 `[0.36,0,0.22]` m，使用各自明确的 Link6 世界姿态。模型可自主选择退让位置、动作和并行/先后关系。

这不是两个互不影响的单臂运动：左臂占用时，右臂直接进入被 `IK_REJECTED_COLLISION` 拒绝；纯 IK 收敛且在限位内，检测到 4 对左右夹爪链接冲突。该负对照没有执行，物理步数为 0。

唯一工程见证为：左臂退回 Ready → 右臂进入共享区并保持 → 右臂退出 → 左臂重新进入并保持。每个目标均使用原 IK、原整段共享世界碰撞预检与关节插值，无路径替换。实际全部执行通过，最终再保持 2 秒。

- 右臂持续占用完成于第 4568 步，随后左臂持续占用完成于第 7679 步；最终目标均满足原执行器的 10 mm / 0.05 rad 位姿容差。
- 全程没有互臂接触或物理保护停机；最小实际夹爪开度 89.799712 mm，没有建立物体夹持。
- 任务段实际仿真时间 26.996 秒；完整日志 8449 步。独立离线重评分与运行结果相同。

物理视频、初态四视角、实际关节轨迹、接触日志及负对照回执位于 `evidence/shared_workspace_yield_20261015/baseline_01/`。这是一条工程可行性见证，不是 Astra 成功结果，也不证明唯一或最优时序。

## 下一轮 Astra 的最小条件

公开任务与观测预览已保存为 `public_task_preview.json` 和 `input_preview_NOT_DISPATCHABLE.json`。预览仅复用原观测 allowlist、四张 RGB、标定、双臂实测状态、数值动作 schema 与空历史；不含专家退让点、动作序列、负对照回执、物体 GT 或接触真值。

尚未把新任务挂接到真实派发入口：旧 `handoff_transfer_only` 门禁与 STOPPED ledger 保持原样，预览故意不可直接派发。下一轮只需把新 task_id、此物理初态与顺序评分绑定到现有分步闭环；初始化仅执行左臂进入共享区并停止，不执行专家后续让行。随后进行新的非生成生产预检，并取得独立新批次授权。建议先一局最多 8 次决策；如保留 shadow，合计为 1 次 shadow + 最多 7 次执行决策。旧剩余 11 次绝不使用。

真实调用仍沿用单个 gpt-6-astra / medium、原 Mac ChatGPT Bridge、180 秒客户端 / 190 秒服务端和独立 ephemeral 会话；推理期间暂停物理时间。此处只是下一轮条件，没有建立新授权或检测生成端点。

模型负责选择退让目标、数值 TCP、先后或并行以及观察/停止；控制器仍只负责原 IK、固定插值、碰撞预检与物理安全拒绝。没有自动让行技能。

## 实际复现命令

每次输出必须是不存在的新目录。原结果保留，不能覆盖或以重试替换。

```bash
cd /home/alex/astra_spatial_capability/rm65-fixed-pose-feasibility-20261015/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh

# 实际运行代码 cb5586f：唯一持物目标，原 IK 拒绝
"$RM65_PYTHON" fixed_pose_check.py \
  --output evidence/fixed_pose_feasibility_20261015/check_01

# 实际运行代码 ddc46fd：唯一无持物共享区物理见证，通过
"$RM65_PYTHON" shared_workspace_yield.py \
  --output evidence/shared_workspace_yield_20261015/baseline_01
```

归档使用无损 gzip；远端未压缩原日志同时保留。旧 ledger SHA-256 仍为 `2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1`。本分支没有修改任何旧结果、旧评分或旧授权记录。
