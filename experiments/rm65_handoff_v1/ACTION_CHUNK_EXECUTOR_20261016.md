# 完整任务的决策权与通用数值执行验收

本版让 Astra 决定从桌面抓取到右臂放置的全部动作。新增 `numeric_chunk_v2` 只细分调用者给出的路径，不选择抓取点、交接点、退出路线或放置点。真实 Astra 请求 **0**，生产 Bridge 连接 **0**，没有创建授权账本，也没有恢复历史 STOPPED 账本。

基于已归档的候选 1 / `d81c831`，独立分支 `codex/rm65-action-chunk-executor-20261016`。旧 106 个私有工程 waypoint、失败、评分及视频全部保留；它们没有进入在线执行器。

## 权责和公开协议

模型负责抓取位置、闭爪指令、交接位置、左右臂顺序/并行、关键 waypoint、退出路线、放置位置及释放时机。它可以一次生成多个 `stages`；每阶段有 `sequential` / `parallel`、左右臂数值操作和 `observe_s`。TCP 操作可包含多个 `waypoints_world_wxyz`；不会从任务阶段自动补点。空动作阶段只做明确请求的被动观察。

控制器负责：原最近 IK、关节轨迹跟踪、接触伺服、原共享世界 FCL 预检及 PhysX 保护。没有 OMPL 绕障、专家退让、目标吸附或目标修正。模型指定的每个折点均保留；需要绕障时，模型必须自行给出折点。

完整机器可读协议见 `evidence/action_chunk_acceptance_20261016/public_contract_v2.json`。公开模块 `numeric_action_chunk.py`、`chunk_handoff_task.py` 不导入工程参考路线；物理工程初始化只在独立的私有验收程序 `numeric_chunk_physics.py` 中使用。

### TCP 与时间

- 共同世界坐标，米；四元数 `[w,x,y,z]` 为 Link6 世界姿态；TCP 为实际两夹垫代表面中心的均值，随夹爪机构变化。
- 从当前实测 TCP 开始，按调用者给出的 waypoint 顺序，以直线位置、最短四元数 SLERP 固定细分：每段最多 5 mm / 1°。不生成绕障点。
- 每个节点仍走原 `execute_group()`：最近 IK、关节三次插值（最短 0.5 秒）、0.4 秒保持。**这是慢速 stop-and-settle 跟踪，不是精确 Cartesian servo，也不承诺模型指定的连续速度。**
- 同一 parallel 子组在相同物理时间步实际重叠执行；短路径先完成后保持，夹爪操作与第一个 TCP 节点同时执行。不会暗中改成专家顺序。
- 每个节点在运动前完整预检；后续节点可能拒绝，因此 chunk 可以部分执行。回执记录具体阶段、子组、原命令、已执行范围及失败原因，不重试。
- 当前数值组结束后检查全部实际样本与该短段的位置/姿态差异，以及端点残差。公开跟踪验收界限为 2 mm / 1°；超界停止后续子组。它与原 **2 mm 接触穿透保护** 是不同指标，后者仍在每个 PhysX 步即时生效。
- 姿态跟踪诊断采用对该短段两个端点的最近角距离，是保守的端点距离指标，不冒称精确 SLERP 轨迹误差；位置诊断是线段横向/端点距离，不是时间同步误差。
- 推理时不推进物理；阶段观察只推进物理、不添加动作。最多 8 阶段、每臂操作 16 个 waypoint、累计 128 个数值子组。`done=true` 只请求停止与末尾 2 秒观察，不代表任务成功。

### 夹爪

`opening_fraction` 明确是空载机构位置命令：`master_target = -0.91*(1-opening_fraction)`，0 闭、1 开。它不是实测毫米开度；观测中的夹垫代表点距离也不等于真实最小接触间隙。

`position` 忠实跟踪请求的主关节目标，不自动接触锁定。`bilateral_hold` 仅在模型请求闭合时启用：连续两帧双侧接触后停止闭合斜坡，用当前实测主关节角减原有 0.005 rad 预压作为保持目标，并限制该 **伺服目标** 不比模型请求更闭合。实际关节仍可能因动力学过冲偏离目标，原监测/保护继续生效。结束时没有双侧接触则明确返回 `GRIPPER_BILATERAL_HOLD_NOT_ESTABLISHED`，不猜测新目标。

右侧采用候选 1 独立版本 `right_contact_hold_master_damping0_v3`：接触锁定后仅右主关节 D=0，K、URDF 10 Nm 上限和联动不变；开爪恢复原 D=2。无私有专家目标参与保持目标计算，无 qpos 强写、方块绑定、质量/摩擦修改。原生实际驱动力矩仍为未知。

完整原始回执及接触留在本地证据中；模型历史使用单独的 `public_feedback.json`，剔除私有双侧接触真值和锁定标记。模型收到请求目标、实际关节/开度、实际伺服目标及执行失败回执，不收到物块 GT、接触点、专家路线或私有评测状态。

## 实际离线物理结果

所有场景保持 ubuntu-robot 的 1.1 m 双 RM65、四视角、原 PhysX/依赖/碰撞保护。本次没有继续调夹紧力、tendon、质量、摩擦或求解器。

| 有限验收 | 结果 | 实际证据 |
|---|---|---|
| 显式右侧接触保持，左侧释放后 7 秒 | PASS | 双侧接触持续；相对漂移 0.0002455 mm，最大报告夹垫穿透 0.2689 mm |
| 只给一个长距离 TCP 终点 | PASS | 通用生成 72 个节点，含末尾观察共 66.8 秒；相对物体漂移 0.004958 mm，最大报告右夹垫穿透 0.2888 mm |
| 两个调用者给定折点、保持初始姿态 | PASS，11 个节点 / 11.9 秒 | 相对漂移 0.0008974 mm；最大报告右夹垫穿透 0.2895 mm |
| 相同折线位置加 3° 世界 yaw | **FAIL / 安全中止** | 第 3 个子组执行中、step 28614，`PAD_PENETRATION`；报告接触穿透 2.3267 mm 超过原 2 mm 保护。没有执行到完整 3° 目标 |
| 正常 `position` 开爪 | PASS | 实测代表点距离 88.632 mm，无双侧夹持，D 恢复 2 |
| 空夹 `bilateral_hold` | 预声明负对照成立 | 明确失败，450 物理步，无自动重试/自动换目标 |
| 空载 `position` 闭合及随后显式打开 | PASS | 正常位置命令执行；清理动作是独立测试指令，不是执行器自动修正 |

注意区分**物块相对 TCP 漂移**与**TCP 跟踪误差**：长直段最大位置横向/端点距离 1.746 mm、最大端点残差 1.283 mm；固定姿态折线分别 1.958 mm / 1.424 mm。不能把物块微小相对漂移说成 TCP 的微米级路径精度。所报穿透来自原记录中的有效冲量接触点。

`held_tracking_01` 也保留为 FAIL：新的显式保持验收在原左臂桌面闭爪结束时检测不到双侧接触。独立复核证明该段物块和两臂 qpos 与旧流程逐步完全相同；不是控制器新增物理退化，原流程是在后续抬起中实际建立持物。没有把这一严格回执改成成功。后续持物执行验收的左臂初始化明确使用旧工程流程，**不冒称新版从桌面抓取已完整通过**。

固定姿态变体是看见 yaw 失败后做的明确隔离对照，不替换原试验，也不证明唯一根因。目前证据支持有限的固定姿态平移与折线，不支持“任意持物姿态动作均可靠”。本轮没有再调参或改写失败目标。

## 接入与验证

- 19 项离线单元/原协议回归通过。包含严格 JSON、重复字段、模型/完成事件、403/409、超时取消、无重试、GT/图像隔离、并行与顺序、只观察、拒绝/部分执行和物理异常归档。新版离线 adapter 仅接受固定的测试用合成凭据，拒绝把生产凭据当作 mock 使用。
- 最终新 chunk 与原 V1 各通过本地模拟 Bridge 的实际 PhysX 闭环；四视角、table takeover step=100、双臂空手且开爪、专家初始化动作=0、推理期间物理推进=0。mock 不作为 Astra 能力或完整物块任务成功证据。
- 复用既有 MacBridge HTTP/鉴权/超时/usage/参数审计与原始事件验收；只替换新版公共 schema 及解析器。生产 Bridge/认证/模型/Code Mode 均未改变。
- 原历史 1931 份归档文件哈希不变；原评分、布局及 ledger 单独核验。独立从原始物理记录重新评分，与新有限验收的全部保存评分完全一致。
- 真实入口仍严格阻止 `--real`，历史额度不能使用。后续正式模型回合仍须新授权，并从桌面方块、双臂空手/开爪开始；不能使用本验收的私有持物初始化。

## 已实际运行的命令

在 ubuntu-robot：

```bash
cd /home/alex/astra_spatial_capability/rm65-right-grip-repair-20261016/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh

"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests -v

# 新版完整任务入口的本地模拟协议/物理回归：从桌面开始，无专家抓取
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" full_handoff_offline_test.py \
  --action-interface chunk_v2 --right-hold-control master_damping0_v3 \
  --output evidence/YOUR_NEW_UNIQUE_MOCK_DIRECTORY

# 私有执行器验收；原始 yaw 变体预期会物理中止，不是模型失败
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" numeric_chunk_physics.py \
  --output evidence/YOUR_NEW_UNIQUE_YAW_TEST_DIRECTORY

# 明确的固定姿态隔离回归，不覆盖上述失败
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" numeric_chunk_physics.py \
  --fixed-orientation-regression \
  --output evidence/YOUR_NEW_UNIQUE_FIXED_POSE_DIRECTORY
```

实际在线接口入口形式为 `run_episode.py --task handoff_place_full --action-interface chunk_v2 --right-hold-control master_damping0_v3`，当前仅接受新的本地 mock 配置，真实派发被授权门禁阻止。它不导入本文件中的工程初始化。

证据目录 `evidence/action_chunk_acceptance_20261016/` 保留全部尝试、完整视频、轨迹、原始动作、子组回执、独立图和日志。`generic_fixed_tracking_actual.mp4` 只截取工程初始化后的通用执行段；`held_yaw_failure_actual.mp4` 为原始失败。它们都不是 Astra 生成的动作录像。
