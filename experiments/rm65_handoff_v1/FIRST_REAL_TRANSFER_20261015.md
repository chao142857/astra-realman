# 首次真实 Astra transfer-only 回合：物理保护中止

执行主机 yanglab；任务 `handoff_transfer_only`。基线 `194d49b`，唯一生产源码变更为一次性 shadow 门禁，代码提交 `99dec05`；shadow 阶段已单独提交 `3a8df53`。独立分支为 `codex/rm65-transfer-first-real-yanglab-20261015`。

本轮实际消耗 **5/16 次客户端派发：1 次 shadow、4 次闭环**。五份输出均通过冻结的协议/参数/完成事件验收。第 4 次闭环动作在物理执行中触发原 2 mm 夹垫穿透保护，立即停止；没有自动重试，没有使用其余 11 次预算。本轮没有完成交接，不能将本次物理中止解释为 Astra 永远不能完成任务。

## 批次与生产预检

- 批次 ID：`2860b79c46e649d2a4e597128186c76b`。
- 唯一输出绝对路径：`/home/tongji/alex/rm65-transfer-first-real-yanglab-20261015/experiments/rm65_handoff_v1/evidence/transfer_runs/first_real_1100_20261015_01`。
- 新 DRAFT、新授权记录分别创建；原 DRAFT 与所有旧 ledger 保留。最终 ledger 为 `STOPPED / PHYSICAL_EXECUTION_FAILURE`，5 个已派发行均 `VALID`（表示协议有效，不表示物理任务成功）。禁止恢复该批次。
- 非生成 Mac 检查分别于 2026-10-15 10:27:12、10:32:21（上海时间）通过；yanglab 绑定预检于 10:30:18、10:32:48 通过。派发前均不足 15 分钟。
- ChatGPT 登录、Mac `127.0.0.1:18767` 专用服务、yanglab `127.0.0.1:18766` 反向隧道均通过；用认证后的未知路径返回 404、错误认证返回 403 检查，未用 `/decide` 做健康检查。
- 服务端 190 s、客户端 180 s；单 worker，`gpt-6-astra / medium`，独立 ephemeral CLI 会话。原生产 bridge SHA-256 为 `922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae`，未修改认证、Code Mode 或模型配置。
- 10 项安全/门禁测试、7 项原协议测试通过。修复禁止第二次 shadow，也禁止仅伪造布尔标志开启 execute；execute 必须有本批次已封存且再次验收有效的 shadow。

## 仿真与能力解释边界

实际两次运行均使用 `scene_v4_ready_transfer_1100.json`：基座间距 1.100 m，四相机角色不变，左右独立 Ready q，原夹爪控制、10/1 求解迭代、0.004 s 物理步长、0.1 Nm 接触锁定力矩及 2 mm 保护未变。无物体绑定、运行时物体位姿改写或真实硬件通信。两次均重新物理抓取，左臂初始稳定持物 3 s。

私有零生成端点检查中，右 TCP 的两个预声明区域端点通过原 IK/碰撞检查，详见 `evidence/first_real_preflight_20261015/receiving_endpoints/probe_PRIVATE.json`。只检查端点，未证明双臂完整路径、接触接取或退出可行；未将候选点或诊断加入 Astra 输入。前两次 IK 拒绝因此只报告为当前数值执行器未找到有效解，不证明全局不可达，也不能直接归因为模型能力不足。

模型输入仅四 RGB、标定、实测双臂关节/TCP/夹爪开度、任务、最近两步原提案与真实回执；不包含 GT 接触、物体位姿或专家目标。独立审计验证两个阶段首个请求 `recent_history=[]`，shadow 不进入 execute 历史；五个 thread ID、request ID 互不相同。推理期间物理推进步数均为 0。模型负责目标和时序，原执行器负责最近 IK、固定关节插值、碰撞预检与物理安全拒绝，没有修正任何模型目标。

## 逐轮结果

| 阶段 | 原始提案概要（world，米，wxyz） | 实际结果 | 客户端墙钟 s | 输入 tokens | 输出 tokens | reported reasoning tokens |
|---|---|---|---:|---:|---:|---:|
| shadow | 并行：左 `[.34,0,.25,0,1,0,0]`，右 `[.52,0,.23,.5,-.5,-.5,.5]` | 只记录，0 动作/0 物理执行步 | 27.810 | 14080 | 366 | 260 |
| 闭环 1 | 并行：左 `[.35,0,.24,0,1,0,0]`，右 `[.53,0,.24,.5,-.5,-.5,.5]` | IK 拒绝，0 执行步；右臂计划未执行 | 21.717 | 14117 | 282 | 176 |
| 闭环 2 | 左 `[.28,0,.18,0,1,0,0]` | IK 拒绝，0 执行步 | 16.569 | 14266 | 106 | 44 |
| 闭环 3 | 左 `[.12,0,.18,0,1,0,0]` | 实际执行 441 步/1.764 s；终点误差 0.714 mm、0.00243 rad | 15.158 | 14423 | 106 | 44 |
| 闭环 4 | 左 `[.34,0,.22,0,.8660254,0,.5]` | 执行 377 步/1.508 s 后 PAD_PENETRATION 中止 | 23.906 | 15292 | 364 | 296 |

两个 IK 回执均为 `IK_REJECTED_NO_VALID_SOLUTION`，细项 `pure_clik_success=false, within_joint_limits=false, collision_pairs=[]`；保留全部原提案并原样反馈。模型随后缩短左臂位移并成功移动一次，但没有右臂接取、夹爪关闭或左臂释放动作得以执行。

共 72178 输入 tokens、1224 输出 tokens，其中 reported reasoning tokens 820；所有 `cached_input_tokens=0`。累计客户端等待 105.160 s，其中闭环 77.350 s。tokens 为 CLI 报告，不能解释为精确内部计算量；客户端耗时包含网络、CLI 和 Bridge 开销。客户端只准确记录 5 次派发，上游实际生成次数标记 `UNKNOWN`。

原生事件保留每次的两个 `item.completed / item.type=error` 项：`skip_host_skill_discovery` 开发功能警告、`Code Mode is unavailable because code-mode host is disabled`。没有顶层 `error`、`turn.failed`、重连或未知完成状态。冻结验收器接受这些 item 级信息；原配置未改变，未隐去这些事件。

## 最早失败与独立物理评分

最早动作拒绝是闭环 1 的 IK 拒绝。导致整局停止的最早物理故障是闭环 4：`numeric_group_4` 的第 3844 步（仿真 15.376 s），**左臂夹爪**的 `L__ctag_Right_Support_Link` 与 `target_cube` 最小 separation `-0.002597680315375328 m`。名称中的 Right 指左夹爪的一侧，并非右机械臂。该动作计划 1374 个关节插值样本，执行至第 377 步时中止。原穿透阈值保持 0.002 m。

| 冻结 transfer_criteria_v1 检查 | 结果 |
|---|---|
| 左臂初始物理稳定持物 | PASS，3.000 s；相对漂移约 0.000342 mm、0.0000771° |
| 右臂独立持续持物 | 未建立，右臂双侧接触从未出现 |
| 右臂持物退出 | 未建立 |
| 无掉落 | PASS，直到中止时刻 |
| 无互臂接触 | PASS，直到中止时刻 |
| 原夹垫穿透限制 | FAIL，最大 2.598 mm |
| transfer_only_pass | false；PHYSICAL_EXECUTION_FAILURE |

从全量原始物理记录重新调用冻结 `evaluate_transfer.assess()`，shadow 和 execute 两阶段均与运行时评分精确相同。另行调用未修改的旧 `evaluate_process.evaluate()`：闭环最长旧速度判据左持物 3.636 s，右独立持物 0 s；保留旧判据完整结果。旧函数返回的硬编码 `model_calls=0` 不用于请求统计；该字段原样保存并明确标注，以本批次 ledger 的 5 次为准。原评分包含放置检查，放置不属于本任务，不能据此增加本轮失败项目。

## 录像、证据及离线复核

批次目录中的：

- `execute_01/execution.mp4`：完整四视角真实 PhysX 录像，含脚本左臂抓取初始化。
- `execute_01/astra_motion_excerpt.mp4`：从上述原视频 11.7 s 处提取的模型动作片段，未重新仿真。
- `execute_01/last_recorded_video_frame.png`：原视频末帧，物理第 3825 步，距保护触发早 0.076 s；不可冒充精确故障瞬间渲染。
- `shadow_01/decision_000` 与 `execute_01/decision_000..003`：原始 JSON、CLI 事件、usage、参数、输入 SHA、原提案、未改写回执和逐轮时间。
- `execute_01/physics.jsonl.gz`、`group_*/left_trajectory.npz`：全部实际状态/drive target/开度/接触，以及预计算轨迹；计划轨迹与实际物理轨迹分别保存。
- `execute_01/physical_stop_analysis_PRIVATE.json`：触发接触点、冲量、物体速度/姿态、实测状态、驱动目标和逐阶段统计。仅评测端使用。
- `independent_audit_PRIVATE.json`、独立评分与旧速度判据结果：可追溯原始评分。
- `mac_native_cli/`：五个原 Mac job 的事件、原结果、命令、prompt/schema/图像；没有认证文件。runtime 临时缓存未作为证据复制。
- `source_snapshot/`：实际运行源码与配置；`history_unchanged_check.json` 确认旧结果/ledger/阈值与生产 bridge 未改写。

离线重新评分（在 yanglab 上，不生成、不执行动作）：

```bash
cd /home/tongji/alex/rm65-transfer-first-real-yanglab-20261015/experiments/rm65_handoff_v1
source runtime.sh
B=evidence/transfer_runs/first_real_1100_20261015_01
"$RM65_PYTHON" evidence/first_real_preflight_20261015/audit_real_run_PRIVATE.py "$B"
```

真实运行命令已逐字归档到该批次 `executed_commands.txt`，仅作复现记录。本轮 STOPPED ledger 不再启动；继续真实实验须另行明确授权。本轮不修接触控制器、不调安全阈值、不把物理中止改写为成功，也不继续开发平台。
