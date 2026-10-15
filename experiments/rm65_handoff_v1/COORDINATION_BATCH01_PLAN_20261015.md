# Astra Dual-Arm Coordination — Formal Batch 01

本轮为零生成准备。基线 `6afd5a8`，执行主机仅 `ubuntu-robot`。任务是双 RM65 无持物共享工位协调；不继续 CTAG 持物研究，不连接硬件。没有创建本实验的真实生成授权。

## 冻结矩阵

三个条件各计划 3 个独立 episode，共 9 局。A/B/C 在这里表示任务条件。

| 条件 | 初态 | 共享 TCP 目标位置（m） | 占位顺序 | 终态 |
|---|---|---|---|---|
| A_fixed | 左臂已占位 | `[0.36, 0, 0.22]` | 右臂，然后左臂 | 左臂在目标，右臂回本局初始 Ready |
| B_shift_y40 | 左臂已占位 | `[0.36, 0.04, 0.22]` | 右臂，然后左臂 | 左臂在目标，右臂回本局初始 Ready |
| C_roles_swapped | 右臂已占位 | `[0.36, 0, 0.22]` | 左臂，然后右臂 | 右臂在目标，左臂回本局初始 Ready |

目标四元数沿用各臂原有已验证方向；完整七维 TCP 在 `coordination_batch01/conditions.json`。B 是在真实模型调用前预声明的世界 Y 方向 +40 mm 变化，没有根据模型成败选择样例。C 保留真实左右机械臂身份与基座位置，仅交换任务角色和初始占位臂。

固定调用顺序为：

```
ep01 A1 → ep02 B1 → ep03 C1 → ep04 B2 → ep05 C2 → ep06 A2
→ ep07 C3 → ep08 A3 → ep09 B3
```

完整顺序见 `coordination_batch01/order.json`。不安排真实 shadow：原传输和数值动作协议已有真实 shadow 验收，本轮使用零生成协议验收。

每局最多 7 次派发；9 局最坏需要 63 次，**全 campaign 的上限仍严格为 50 次**。因此末轮可能被累计预算或时间截断。前两轮各条件都安排两局；第三轮按预先冻结顺序执行，不根据前面的成功或失败重新分配，不补跑或替换。未完成、未开始和被截断的局全部报告。该设计平衡计划 episode 数，不保证实际请求数相同。

## 物理工程见证

三个条件均通过原数值执行器的固定工程轨迹：仅初始化占位臂，然后由工程脚本完成退让、另一臂占位、退出、原占位臂返回；最终自然物理保持 2 秒。工程见证是可执行性证据，不是模型结果。

每个条件都有独立负对照：在原占位臂仍占用目标时，直接让另一臂进入目标。三者均被原碰撞预检拒绝，物理推进为 0，证明不是两个互不影响的单臂动作。

最终见证目录：

- [A 固定条件录像](evidence/coordination_batch01_preparation/witnesses/A_fixed_02/execution.mp4)
- [B 平移条件录像](evidence/coordination_batch01_preparation/witnesses/B_shift_y40_02/execution.mp4)
- [C 角色交换录像](evidence/coordination_batch01_preparation/witnesses/C_roles_swapped_02/execution.mp4)

对应 `witness_PRIVATE.json`、四视角初态/终态、逐步物理日志、实际关节轨迹和碰撞回执均保留。`coordination_batch01/witness_manifest.json` 绑定这些证据的哈希。01 号工程运行也保留，02 号是在明确 Ready 参考和最终任务契约下的重复验证。

布局仍为原 1.1 m 双基座间距、独立左右 Ready 关节、四视角；原最近 IK、关节三次插值、共享世界 FCL 预检、夹爪驱动和 2 mm 穿透保护不变。每个成功数值动作组后观察 0.5 秒，顺序组逐个执行，并行组保持原同时执行语义。模型推理期间物理时间暂停。本实验不检验持续运动中的实时动态反应。

## 模型任务和输入隔离

每局新建同一布局的独立物理场景，按对应条件仅初始化占位臂，然后停止工程动作。Astra 自主提出所有后续数值 TCP、夹爪命令和顺序/并行关系。不会把工程 Ready 退让路线放进执行器。

公共输入只有：任务和目标、占位顺序、两臂本局初始 Ready 数值、当前实测关节/TCP/开度、四路 RGB 与标定、本局最近两条原始提案及回执。目标与占位顺序是任务要求；不提示应先让哪只臂退让。

模型输入没有工程见证、私有负对照、物体 GT 或评分状态。新任务验证器复用原状态/历史 allowlist、RGB SHA 检查及 GT 隔离检查；HTTP、超时、取消、usage 和参数核验复用原 Bridge 传输。输出 schema 和动作含义完全沿用原 `action_interface.py`，该文件未修改。

每次模型调用独立 ephemeral 会话。新 episode 的 `recent_history=[]`；后续上下文仅包含当前局最后两条原始动作及回执。所有 request ID 和 thread ID 在整个 campaign 内检查唯一性。

## 评分和统计口径

评分在模型调用前冻结于 `coordination_batch01/criteria.json`：

1. visit_order 第一只臂在其目标连续占位 ≥0.5 秒。
2. 此后第二只臂在其目标连续占位 ≥0.5 秒，初始占位不提前计功。
3. 终态第二只臂在目标、第一只臂回本局初始 Ready，连续保持 2 秒。
4. 全程无活动互臂接触、无非预期机械臂/桌面或支座接触，夹爪实测开度始终 >70 mm，且无物理保护中止。

位置 10 mm、姿态 0.05 rad、2 mm 穿透保护均与 V1 相同。目标判断和接触规则直接复用原 `evaluate_workspace.at_goal()` / `forbidden()`；仅将左右固定顺序参数化为本条件的第一/第二角色。A 条件的评分与原 V1 有一致性测试。旧 CTAG 及旧 workspace 评分文件保持原样。

每局保存原始响应、CLI events、严格 JSON 解析结果、模型参数、usage/缓存、推理墙钟、完整 episode 墙钟、含初始化及任务阶段的仿真时间、原提案、原回执、实际执行/部分执行动作组数量、IK/碰撞/限位拒绝、物理保护和录像。episode 墙钟从初始化开始，到最终观测和物理场景关闭；独立重评分属于后处理，仍计入累计 campaign 墙钟。归档后从物理日志重新独立评分并核对一致。

拒绝后记录下一条提案是否变化及是否被接受，这只表示可观察行为，不推断隐藏思维过程。拒绝本身不立即结束回合，模型可在剩余预算内重新规划。

分类如下：

- `SUCCESS`：实际物理评分通过，包括完整终态保持。
- `TASK_FAILURE`：模型主动停止但未通过，或触发原物理安全保护；后者另有安全标记，并停止整个 campaign。执行器内部或文件 I/O 等异常另计为基础设施故障。
- `BUDGET_TRUNCATED`：任务未完成而触及本局 7 次、累计 50 次或 3600 秒限制；保留当时物理评分，不作无限预算下失败的结论。
- `INFRASTRUCTURE_FAILURE`：协议、传输、参数漂移、中断或未知完成状态；主能力评分为 NOT_SCORED，私有实际状态可事后检查。
- `NOT_STARTED`：因全局限额或停批未开始的冻结项目。

统计同时报告成功数/已开始局数、成功数/未截断且可评估局数、各类数量，以及分条件和总体平均决策次数、派发次数、推理等待和完整 episode 耗时。token 按 CLI reported 字段原样保留；不把 token 当作精确内部计算量，也不把客户端等待当作纯模型计算时间。小样本只做描述统计，不能据此估计广泛泛化能力。

## 全局预算与时间门禁

`coordination_batch01/gate.py` 使用原子写入（临时文件、fsync、replace）和整个 campaign 持有的单 worker 文件锁。所有 episode 共用一份累计 ledger，派发前永久预留预算；即使派发/完成状态不明也不退款。实际 HTTP 派发状态另外保存在 transport 记录中，不声称能准确控制上游服务内部生成次数。

3600 秒使用单调时钟，从第一次预留、紧接首次客户端派发之前起算；后续 reset、推理和物理执行都计入，跨局不重置。客户端单次上限 180 秒，临近全局截止时有效等待缩短到剩余时间。截止后不新增生成，也不继续物理步进；取消和证据落盘可有少量收尾时间，原取消最多 3 秒，不属于重试或新增生成。

协议异常、HTTP 403/409、超时、CLI 顶层错误/重连、未知完成、输入完整性或独立评分不一致、物理保护中止都会停止整个 campaign。无自动重试，无自动避障或目标修正。`FINISHED`、`STOPPED`、`LIMIT_REACHED` 均不可恢复；发现遗留 `RUNNING` 时标记为中断/未知并拒绝重启。原所有 ledger 不读取作为授权，不改写、不继承额度。

## 启动和授权

默认命令只打印 dry-run，不连接 Bridge：

```bash
cd /home/alex/astra_spatial_capability/rm65-coordination-batch01-prep-20261015/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh
"$RM65_PYTHON" -m coordination_batch01.run
```

新的真实 DRAFT 路径、campaign ID、冻结哈希和验收记录见本目录的准备验收报告。本轮 `authorization_REQUEST_NOT_GRANTED.json` 为 false、max_dispatches=0；不存在正式 GRANTED。

未来须先确认本矩阵和新 campaign，并明确授权最多 50 次。授权后保持草稿的版本、路径、source_hashes、freeze_sha256 和所有运行参数，生成对应 GRANTED。Mac 侧用 `coordination_batch01/mac_preflight.py` 检查原服务、原隧道、ChatGPT login、CLI version/help；不调用 `/decide`。随后一次性入口会重新做 Ubuntu 的认证/隧道非生成检查并在 15 分钟有效期内执行：

```bash
bash coordination_batch01/start_once.sh "$CAMPAIGN" \
  "$CAMPAIGN/authorization_GRANTED.json" "$FRESH_MAC_PROOF" "$CAMPAIGN/bridge_config.json"
```

该命令现在不得执行真实生成。真实模型仍固定 `gpt-6-astra / medium`、原 Mac ChatGPT Bridge、客户端 180 / 服务端 190 秒、单 worker。所有影子/执行请求若日后计划改变，必须重新冻结与授权，不能在运行时临时添加。
