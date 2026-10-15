# shared_workspace_yield_v1 首轮真实 Astra 结果

本回合 **PASS**。Astra 自主选择了顺序让行：左臂退出共享区，右臂占位，再让右臂返回初始 Ready、左臂重新占位，最后主动停止。冻结的物理评分与独立重评分完全一致，全部七项判据通过。

这是一个固定场景的一次闭环成功，只支持该布局下的顺序协调结论；本回合没有测试双臂并行协调，也没有测试推理等待期间的实时反应。

## 批次与授权

- 代码基线：`2023f98b70ebe9325b3748fb8856c84d2f41f78a`。
- 执行主机：`ubuntu-robot`，实际 hostname `Ubuntu-Robot`。
- Batch ID：`8ab36cee132046909da2285fde4b4bc3`。
- 远端输出绝对路径：`/home/alex/astra_spatial_capability/rm65-workspace-astra-prep-20261015/experiments/rm65_handoff_v1/evidence/workspace_runs/first_workspace_20261015_01`。
- 模型：`gpt-6-astra / medium`；原 Mac ChatGPT Bridge；每次独立 ephemeral CLI 会话；单 worker；客户端 180 秒、服务端 190 秒；无重试。
- 真实派发 **5/8**：shadow 1 次，执行决策 4 次。全部协议有效，批次状态 `FINISHED`。3 次未使用额度不续用。
- `authorization_GRANTED.json` 与原 REQUEST 草稿仅有用户指定的三个字段不同。原草稿与原 DRAFT ledger 字节快照保留。
- 原 CTAG STOPPED ledger SHA256 仍为 `2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1`，其剩余 11 次未使用。

## 生产检查与输入隔离

Mac 实际 CLI version/help、ChatGPT 登录状态、原 Bridge 进程及 190 秒参数检查通过。Ubuntu 生产检查在 **2026-10-15 08:41:02 UTC** 完成：通过未知路径 `/rm65-transfer-auth-check` 验证正确认证为 404、错误认证为 403，未以 `/decide` 探活。

26 项运行源哈希在运行前后保持一致。所有派发均处于新预检的 15 分钟有效期内。未修改模型配置、场景、数值执行器、夹爪参数、2 mm 保护或冻结评分。

场景继续使用 1.1 m 基座间距、独立 Ready 关节姿态与 overhead / tabletop_front / left_wrist / right_wrist 四视角。原左右腕部视角仍存在部分机器人自身遮挡，本轮未为成功修改相机。

初始化只将左臂移入共享目标，之后专家逻辑停止。真实 shadow 的左臂退让提案 `[0.14, 0, 0.36, ...]` 仅记录，没有执行。执行回合由新仿真实例独立 reset，初始化记录及公共 policy 与 shadow 相同，初始模型历史为空。执行回合第一条退让提案为 `[0.16, 0, 0.36, ...]`。

五次调用的 request ID、thread ID 和 Mac job ID 均独立；20 张实际发送图像的 SHA 均与 Mac 接收文件一致。后续历史只包含本执行回合最近两条原始提案和回执。模型输入没有工程见证序列、负对照回执、物体 GT 或私有评分状态。

CLI 原始事件中保留了原 Bridge 配置产生的两类 `item.completed/item.type=error` 启动提示：skip_host_skill_discovery 实验特性提示、Code Mode host 关闭提示。它们不是顶层 `error`/重连；五次均 return_code=0、无 transport error，并恰有一个 `thread.started` 和一个 `turn.completed`，通过冻结事件验收。未为消除提示修改 Code Mode。

## 原始决策与实际执行

| 执行决策 | Astra 原始选择 | 原执行器结果 | 推理期间客户端墙钟 | reported reasoning tokens |
|---|---|---|---:|---:|
| 1（decision_000） | 左臂 TCP → `[0.16, 0, 0.36, 0, 0.8660254, 0, 0.5]` | 执行成功，随后保持观察 0.5 秒 | 24.02 s | 56 |
| 2（decision_001） | 右臂 TCP → 公共右臂目标 `[0.36, 0, 0.22, -0.5, 0, 0.8660254, 0]` | 执行成功，随后保持观察 0.5 秒 | 24.64 s | 60 |
| 3（decision_002） | `sequential`：右臂回公共初始 Ready，再左臂进入公共左臂目标 | 两动作依原始列表顺序执行，各有 0.5 秒观察 | 23.52 s | 27 |
| 4（decision_003） | `done=true, actions=[]` | 不再移动；自然物理终态保持 2 秒 | 19.87 s | 0 |

表中四元数仅为阅读压缩；完整浮点原值在 `proposal.json` 和 `raw.txt`。所有原始提案原样执行，没有目标修正、自动绕障、专家退让动作或数值拒绝。停止提案不算运动动作；前三次执行决策包含四个实际 TCP 运动。

模型负责退让目标、两臂目标与顺序、结束时机。控制器负责最近 IK、关节三次插值、全共享世界 FCL 预检、实测状态反馈和原物理保护，不使用 OMPL 自动改道。两个 articulation 始终在同一 SAPIEN Scene 中推进真实物理。无 weld、无运行中物体姿态写入，也无硬件连接。

## 冻结物理评分

使用原 `workspace_criteria_v1.json`（SHA256 `4d3c23d08e1a009c847662d9cc4f017a1b2a468728631bbe75199ab60047589c`）与原 `evaluate_workspace.py`。评分读取实测状态及活动接触，不把命令到达视为完成。

| 判据 | 结果 |
|---|---|
| 右臂有效占位 ≥ 0.5 s | PASS，step 3706 完成，任务开始后 8.424 s |
| 随后左臂有效占位 ≥ 0.5 s | PASS，step 6039 完成，任务开始后 17.756 s |
| 无互臂活动接触 | PASS |
| 无非预期机械臂/桌面或支座接触 | PASS |
| 双夹爪全程打开 | PASS，最小实际开度 89.7997 mm |
| 终态左臂目标、右臂初始 Ready 连续保持 2 s | PASS，step 6124–6624 |
| 无物理保护中止 | PASS |

位置与姿态容差仍为 10 mm / 0.05 rad，2 mm 穿透保护保持原值。原运行评分与从归档逐步物理记录独立计算的 `independent_workspace_score.json` 完全相同。

任务阶段仿真时间 20.096 秒，连同初始化总计 26.496 秒；所有推理期间 `inference_physics_steps=0`。录像按仿真时间记录，省略网络等待，包含左臂初始化。原视频从 reset 稳定阶段后开始采集，执行录像为 26.1 秒、261 帧、10 fps、1280×960；不是整回合墙钟时长。已解码检查首、中、末帧。

## Token 与墙钟

| 阶段 | 派发数 | input_tokens | output_tokens | reasoning_output_tokens | cached_input_tokens | 客户端推理等待合计 | Mac CLI 子进程合计 |
|---|---:|---:|---:|---:|---:|---:|---:|
| shadow | 1 | 14,346 | 132 | 61 | 0 | 28.22 s | 22.88 s |
| execute | 4 | 64,242 | 463 | 143 | 0 | 92.05 s | 73.18 s |
| 全批次 | 5 | 78,588 | 595 | 204 | 0 | 120.27 s | 96.05 s |

`cache_write_input_tokens` 均为 0。按 CLI 原字段分别报告 output 与 reasoning，不将其相加解释为内部计算量。客户端等待和 Mac 子进程墙钟都包含等待及开销，不代表纯模型计算时间。闭环各决策的 whole_step_wall_s 合计 107.44 秒，不含场景初始化及循环外末尾保持。

## 证据与离线复核

- [真实执行录像](evidence/workspace_runs/first_workspace_20261015_01/execute_01/execution.mp4)
- [Shadow 录像（只有初始化，没有模型动作）](evidence/workspace_runs/first_workspace_20261015_01/shadow_01/execution.mp4)
- [逐轮原始模型提案与回执](evidence/workspace_runs/first_workspace_20261015_01/execute_01)
- [独立物理评分](evidence/workspace_runs/first_workspace_20261015_01/execute_01/independent_workspace_score.json)
- [逐请求 token、耗时、输入 SHA 与会话 ID](evidence/workspace_real_20261015/dispatch_metrics.csv)
- [离线复核结果](evidence/workspace_real_20261015/summary.json)
- [Mac 原始 CLI jobs](evidence/workspace_real_20261015/mac_raw_jobs)
- [正式授权与 FINISHED ledger](evidence/workspace_runs/first_workspace_20261015_01)

源机器和本地均保留原始 `physics.jsonl`；Git 同时归档逐字节可还原的 `.jsonl.gz`，SHA 见 `lossless_physics_archive.json`。原 `artifact_sha256.json` 是准备阶段的 DRAFT 清单，保持原样；其中 ledger 哈希对应新增保留的 `ledger_DRAFT_before_authorization.json`。完成阶段另有独立 `real_result_artifact_sha256.json`，不改写准备阶段证据。

在 ubuntu-robot 原工作目录进行零生成复核：

```bash
cd /home/alex/astra_spatial_capability/rm65-workspace-astra-prep-20261015/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh
B="$PWD/evidence/workspace_runs/first_workspace_20261015_01"
"$RM65_PYTHON" evaluate_workspace.py "$B/execute_01"
"$RM65_PYTHON" evidence/workspace_real_20261015/analyze_saved_run.py
```

本次实际执行的是以下一次性入口；批次已经 FINISHED，不能重新运行或恢复：

```bash
bash workspace_authorized_once.sh "$B" "$B/authorization_GRANTED.json" \
  "$B/production_preflight_FRESH.json" "$B/bridge_config.json"
```

该结果未改变历史 CTAG、Pilot 01/02、B1/B2 或其他 ledger 的结论。需要新回合时须另行明确授权。
