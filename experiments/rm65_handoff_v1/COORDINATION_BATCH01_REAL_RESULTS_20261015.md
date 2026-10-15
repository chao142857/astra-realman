# Astra Dual-Arm Coordination Batch 01：真实结果

本批次因输出动作协议异常提前停止。冻结顺序的前四局成功，第五局 C2 在第二次请求返回后触发 `DONE_WITH_ACTIONS`，后四局没有启动。共预留并实际派发 **16 次客户端请求**，预算时钟 **473.741 秒**，最终 ledger 为 **STOPPED**。没有 Shadow、自动重试、退款、恢复或替补局。

执行基线为 `11cfe4cfa8f53c035b9f5c3b1ac18e3ff01eaa92`，campaign 为 `38ec72e4d49d43d7972a1ce24f1e6d69`。唯一执行主机 Ubuntu-Robot，使用原 Mac ChatGPT Bridge、`gpt-6-astra / medium`、独立 ephemeral CLI 会话、单 worker、客户端 180 秒 / 服务端 190 秒。冻结 SHA256 为 `974eaabecb516abdc164a5da735a372aad42d9a6dbbc0a1e8de1a6e6ef924118`。

以下 A/B/C 是本批次的任务条件：A 原始共享工位、B 目标 Y 偏移 40 mm、C 双臂角色交换；它们不代表旧静态实验的感知输入条件。

| 顺序 | 局 | 条件 | 交付分类 | 原程序状态 | 派发 / 协议有效 | 执行数值动作组 | 模型等待 s | 物理仿真 s | 完整局墙钟 s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ep01 / A1 | 原始共享工位 | PASS | SUCCESS | 3 / 3 | 4 | 64.655 | 31.804 | 89.138 |
| 2 | ep02 / B1 | Y +40 mm | PASS | SUCCESS | 4 / 4 | 4 | 95.815 | 32.820 | 122.586 |
| 3 | ep03 / C1 | 角色交换 | PASS | SUCCESS | 4 / 4 | 4 | 88.519 | 31.504 | 112.937 |
| 4 | ep04 / B2 | Y +40 mm | PASS | SUCCESS | 3 / 3 | 4 | 64.234 | 32.820 | 92.135 |
| 5 | ep05 / C2 | 角色交换 | FAIL：输出协议 | INFRASTRUCTURE_FAILURE；主评分 NOT_SCORED | 2 / 1 | 2 | 42.678 | 17.800 | 56.197 |
| 6 | ep06 / A2 | 原始共享工位 | NOT_STARTED | NOT_STARTED | 0 / 0 | 0 | — | — | — |
| 7 | ep07 / C3 | 角色交换 | NOT_STARTED | NOT_STARTED | 0 / 0 | 0 | — | — | — |
| 8 | ep08 / A3 | 原始共享工位 | NOT_STARTED | NOT_STARTED | 0 / 0 | 0 | — | — | — |
| 9 | ep09 / B3 | Y +40 mm | NOT_STARTED | NOT_STARTED | 0 / 0 | 0 | — | — | — |

这里将 C2 的交付状态写为协议 FAIL，方便对应用户要求的四种展示标签；原始 `INFRASTRUCTURE_FAILURE`、`NOT_SCORED_INFRASTRUCTURE_OR_UNKNOWN` 和全部评分文件均未改写。没有 TRUNCATED 局。

| 条件 | 计划局数 | 已启动 | 正常完成且可评能力 | 成功 | 协议失败 | 未启动 | 可评局成功率 | 已启动局完成成功率 |
|---|---|---|---|---|---|---|---|---|
| A | 3 | 1 | 1 | 1 | 0 | 2 | 1/1 | 1/1 |
| B | 3 | 2 | 2 | 2 | 0 | 1 | 2/2 | 2/2 |
| C | 3 | 2 | 1 | 1 | 1 | 1 | 1/1 | 1/2 |
| 合计 | 9 | 5 | 4 | 4 | 1 | 4 | 4/4 | 4/5 |

4/4 仅描述正常完成的局；4/5 同时反映协议失败导致的端到端完成损失。C2 没有计为空间能力零分，未启动局没有加入能力成功率的分母。这些是固定小样本的描述，不能推论总体泛化能力或显著性。

## 最早停止原因

[C2 第2条原始返回](evidence/coordination_batch01_real_20261015/run/ep05/decision_001/raw.txt) 同时包含 `done: true` 与两条 TCP 动作。JSON 语法有效，HTTP 200，CLI return code 0，恰好一个 `turn.completed`，参数核验通过；原解析器在 `parse_action()` 抛出 `ValueError('DONE_WITH_ACTIONS')`。这一条没有执行回执，物理步数仍为上一条有效动作的终点 4450。没有将 `done` 改为 false，也没有执行假想修复后的动作。

原门禁在动作解析成功后才调用 `Gate.complete()`，因此最后一条 ledger 记录原样保留 `RESERVED`。保存的完成事件与退出码证明该客户端请求已经完成；`ep05/episode.json` 同样记录 `completion_unknown: false`。这里不能将 RESERVED 直接解读为远端仍在生成，也不能退款或重新派发。

公开输出 schema 只分别限制 `done` 与 `actions` 的字段类型，没有编码两者的互斥关系；公开任务文字说明 `done=true` 表示停止，但没有明确写出 `actions=[]`。这是本轮接口表达的限制，不能凭此把停批归因为网络故障或双臂空间决策错误。现有冻结协议及输出均保留，不在本批次修正。

原汇总器把协议、传输、未知状态统一放在 `INFRASTRUCTURE_FAILURE` 类。此次的精确子类是 **模型输出违反动作协议**。16 次请求均返回完成事件，0 个 HTTP 故障，0 个原生 CLI 顶层错误或重连，0 次模型请求重试。原 CLI 的 item 级配置警告保留在事件中，未修改原 Code Mode 配置。

## 实际协调表现及边界

四局成功轨迹都满足：第一只臂占位至少 0.5 秒，随后第二只臂占位至少 0.5 秒，最终第二只臂在目标、第一只臂回到初始 Ready 并持续 2 秒；夹爪保持打开，未出现评分禁止的互臂/桌面接触或物理保护停机。1.1 m 布局、四视角、原数值执行器与 2 mm 穿透保护均未改变。

Astra 自行给出退让与进位的数值目标和动作顺序，执行层执行原 IK、碰撞预检和插值，没有插入专家退让。A/B 条件由右臂先占位，C 条件由左臂先占位，C1 实际完成了角色交换。B1、B2 均完成 Y +40 mm 目标，分别用了 4、3 次决策；任务结果一致，动作打包和结束确认的决策粒度不同。

B1/B2 展开的四个数值目标动作相同，视频字节 SHA256 也相同，原始物理日志 SHA256 不同；所有文件均原样保留。两局的模型请求、thread、CLI 作业和上下文分别独立，不能用相同的视频哈希推断复用了模型回答。见 [重复轨迹核对](evidence/coordination_batch01_real_20261015/analysis/repeat_trajectory_comparison.json)。

全部已执行提案均为 sequential，累计 18 个实际数值动作组、0 个数值拒绝、0 次物理保护。由于没有发生合法拒绝，无法测量拒绝后重规划能力；由于没有执行 parallel 提案，不能据此声称验证了并行动作协调。模型等待时物理步数保持不变，本轮也不能证明实时异步反应能力。

目标 TCP 是公开任务条件；本轮评测其协调和时序执行，不把复述给定坐标视为空间事实推断。三种条件各三次的重复设计因协议停批未完成，A 仅一局、C 仅一局正常完成，重复稳定性仍受样本不足限制。

## Token、时间与独立评分

| 指标 | 所有16次请求，包含协议无效的最后1次 |
|---|---|
| 输入 tokens | 260,079 |
| 输出 tokens（原 CLI 字段） | 2,138 |
| reported reasoning_output_tokens | 445 |
| cached_input_tokens | 7,040 |
| 缓存命中请求 | 1 / 16 |
| cache_write_input_tokens | 0 |
| 客户端推理等待合计 | 355.901 s |
| 客户端推理等待均值 | 22.244 s / 请求 |
| 实际物理仿真合计（含各局初始化） | 146.748 s |
| 预算累计墙钟 | 473.741 s |
| 有效动作决策数（含合法停止） | 15 |
| 实际客户端派发数 | 16 |

Token 分类按原 CLI 原样相加，不将 reported reasoning tokens 解释为精确内部计算量，也不假定输出与 reasoning 字段必须互斥。缓存、逐次客户端延迟及原生 CLI 延迟见 [per_dispatch.csv](evidence/coordination_batch01_real_20261015/analysis/per_dispatch.csv)。客户端等待、完整 episode 墙钟与物理时间分别报告；客户端时间包含桥接、排队、网络与服务处理。

16 次请求分别具有唯一 thread ID、request ID 和原 CLI input_only 目录，均使用 ephemeral。五局的首条模型 context 都有空 history，后续只保留本局最近两条原提案与回执；没有跨局传入历史输出。缓存命中不代表复用了前一局的回答。

运行时每局已经独立重评分，结束后又用冻结 `contract.assess()` 对保存的原始物理轨迹只读复核。五局都与原 `independent_score.json` 及 `posthoc_actual_state_score` 一致：四个主评分 PASS；C2 的事后状态仅完成第一阶段，主评分继续 NOT_SCORED。详见 [只读复核记录](evidence/coordination_batch01_real_20261015/analysis/independent_verification.json)。

## 原始证据与保密

每局视频及原始证据：

- [A1 视频](evidence/coordination_batch01_real_20261015/run/ep01/execution.mp4)，[原始提案和回执](evidence/coordination_batch01_real_20261015/run/ep01/decision_000/)。
- [B1 视频](evidence/coordination_batch01_real_20261015/run/ep02/execution.mp4)。
- [C1 视频](evidence/coordination_batch01_real_20261015/run/ep03/execution.mp4)。
- [B2 视频](evidence/coordination_batch01_real_20261015/run/ep04/execution.mp4)。
- [C2 截止视频](evidence/coordination_batch01_real_20261015/run/ep05/execution.mp4)，[原始停止点](evidence/coordination_batch01_real_20261015/run/ep05/episode.json)。

视频按物理仿真帧记录，模型等待期间物理暂停；视频时长不等于现实 episode 墙钟。各局包含四视角原图、标定、输入、模型输出/事件、usage、执行回执、关节/接触物理轨迹及评分。另保存16个原生 Mac CLI 作业的文件白名单副本，不复制 runtime 或认证文件。

五段 MP4 均已实际逐帧解码通过，分辨率 1280×960、10 fps；解码帧数与文件 SHA 见 [录像核验](evidence/coordination_batch01_real_20261015/analysis/video_verification.json)。

ubuntu-robot 的权威目录仍为 `/home/alex/astra_spatial_capability/rm65-coordination-batch01-prep-20261015/experiments/rm65_handoff_v1/evidence/coordination_campaigns/REAL_batch01_20261015_02`。原私有授权、原 live ledger、STOPPED 状态、原 JSONL 全部保留；不恢复该批次，不使用未派发的34次额度。

Git 发布的是独立 [公开 ledger 副本](evidence/coordination_batch01_real_20261015/run/ledger_PUBLIC_SANITIZED.json)，明确标记 sanitized，保留权威 ledger SHA256，省略嵌入的授权正文。授权文件、口令、认证文件及敏感 bridge 配置没有进入本次提交。原物理 JSONL 在发布副本中无损 gzip，源字节 SHA 与归档 SHA 见 [manifest](evidence/coordination_batch01_real_20261015/run/source_to_archive_manifest.json)。

结束后45项冻结源码/资产哈希全部相符，原 CTAG STOPPED 及旧 workspace ledger 哈希未变，详见 [completion_integrity.json](evidence/coordination_batch01_real_20261015/run/completion_integrity.json)。公开源码仍保留准备阶段的只读 DRAFT；真实最终状态以新增公开副本为准，没有覆盖旧记录。

离线重建描述统计（不调用模型）：

```bash
cd experiments/rm65_handoff_v1
python3 evidence/coordination_batch01_real_20261015/analysis/derive_report.py
```

历史一次性入口为 `coordination_batch01/start_once.sh`；本 campaign 已 STOPPED，不应再次启动。若要继续模型实验，需要另行明确范围、冻结和授权，本次没有创建新 ledger。
