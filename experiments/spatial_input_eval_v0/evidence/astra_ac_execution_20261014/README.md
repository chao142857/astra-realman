# 六场景 A C 专用派发器离线验收

基线 `7512ebe`。离线验收 **PASS**，当前真实生成 **0 次**。没有生产 bridge 连接，没有真实授权记录。代码只新增本轮执行绑定，不改原 24 项顺序、输入、评分、场景或 B 几何版本。

| 检查 | 结果 |
|---|---|
| 24 项冻结顺序、两次重复、12 份输入及 release 哈希 | PASS |
| 原 HTTP Handler + 原 Mac Bridge transport 的 24 次 mock | PASS |
| 每次派发前持久化 RESERVED，budget=次数 | PASS |
| 24 个不同 request ID 与 thread ID，原 ephemeral 命令核验 | PASS |
| 第 3/15 项合法 JSON 的零分后继续 | PASS |
| 24 份原输出、事件、usage、延迟、双份独立评分 | PASS |
| 12 个 scene/repeat A/C 配对 | PASS |
| 默认 dry-run、无授权禁止真实运行、授权范围/预算不可扩展 | PASS |
| 403、409、超时取消、非法/空 JSON、无/重复完成事件 | PASS |
| CLI 错误、reconnect、模型和 Code Mode 漂移 | PASS |
| hash/policy/schema/RGB/GT 字段篡改、旧路径拒绝 | PASS |
| 主机单 worker 排他锁、ledger 权限 0600 | PASS |
| 中断/残留 RESERVED 停止、重评分恢复不退款不重发 | PASS |
| 新增 15 项专用测试 + 原 136 项回归 | **151/151 PASS** |
| 回传后原始字节核对及原 GT scorer 重评分 | **24/24 PASS** |
| 当前 ubuntu-robot ↔ Mac Bridge 生产认证/隧道/190 秒超时 | **NOT_CHECKED，等待新授权后重新检查** |

Mock 分数与 token 全部是 fixture，不代表 Astra 能力。mock 中缺失缓存字段保留 null；reported reasoning tokens 按原字段存档。两个重复确实执行独立 mock HTTP 请求，而非读取第一次的结果。真实模式还须相同的 request/thread 唯一性、ephemeral 参数和完成事件检查；客户端无法保证或计量上游内部生成次数。

## 固定策略对照

仅使用公共目标中心和预先固定的几种动作。初始姿态取 GT 初态，属于绕过感知的简单基线；不读取 witness，不搜索或根据失败修正动作。完整原动作和评分在 `offline_acceptance/fixed_strategy_controls.json`。

| 场景 | 公共中心 + 保留初始姿态（路径为直线） | 固定负 y 绕行 | 固定正 y 绕行 | 固定世界 yaw=0 |
|---|---:|---:|---:|---:|
| path_01 | 0 | 1 | 0 | — |
| path_02 | 0 | 0 | 1 | — |
| path_03 | 0 | 1 | 0 | — |
| yaw_01 | **1** | — | — | 0 |
| yaw_02 | 0 | — | — | 0 |
| yaw_03 | 0 | — | — | 0 |

yaw_01 的成功不要求改变初始朝向，后续真实报告须单列。固定同一侧绕行不能通过三个路径场景。这里只说明任务与简单策略关系，不是模型实验，也不是一轮重建审查。

## 原始证据

- `tests.log`：151 项完整回归；出现的旧 dispatcher 文本来自历史模拟测试，不是真实批次执行。
- `offline_acceptance/mock_batch/ledger.json`：**OFFLINE_FIXTURE** ledger，24 次虚拟预算全部消耗，未包含真实授权。
- `offline_acceptance/mock_batch/run-001` 至 `run-024`：原始 HTTP、CLI fixture events、输入、模型参数、两次独立评分。
- `offline_acceptance/mock_batch/paired_results.json`：12 对重复内 A/C。
- `offline_acceptance/summary.json`：模型/生产连接计数均为 0。
- `archive_recheck.json`：回传后字节与独立几何评分一致。
- `integrity.json` / `manifest.json`：历史保留和新材料文件哈希。

归档内 ledger 保留原 `/tmp/astra-ac-acceptance-final-20261014` 路径，仅作证据；不得将它搬作真实 ledger 或更新为 REAL。所有测试凭据均为明确写死的假 token，不是生产认证。

[未来启动、授权字段与停止恢复说明](../../lab/astra_ac/EXECUTION.md)。离线已具备申请最多 24 次真实客户端派发的条件。当前暂停：收到新的明确授权后，先做新批次生产预检，再创建独立真实批次并绑定授权，不能直接运行历史 next/wave。
