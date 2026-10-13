# Pilot 02 八项续测准备（零生成）

基线 `f26728e`。本阶段只新增附录、续测清单、必要的边界适配及离线测试。没有启动原 bridge、生产隧道、真实请求或创建可使用的续测授权记录。

## 固定范围

清单：`evidence/pilot02_continuation_prep_20261013/continuation_manifest.json`。完整复制原预注册顺序的后八项，不重编号其 `planned_order`，不新增或重渲染样例。

| 原顺序 | 场景 | 输入 |
|---:|---|---|
| 13 | p02_b_open_minus | C |
| 14 | p02_b_open_minus | A |
| 15 | p02_b_open_plus | A |
| 16 | p02_b_open_plus | C |
| 17 | p02_c_slot_030 | A |
| 18 | p02_c_slot_030 | C |
| 19 | p02_c_slot_120 | C |
| 20 | p02_c_slot_120 | A |

模型仍为 `gpt-6-astra / medium`，原 context、task_policy、prompt、schema、RGB、Oracle、评分器和阈值不变；单 worker、独立 ephemeral 会话、180 秒客户端截止、190 秒服务端配置、派发器零自动重试。

续测清单明确引用：

- 原批次 ID：`953a8d18a01447599664db2170862d98`。
- 原已消耗客户端派发：12 次。
- 原顺序 SHA256：`3954819dcf2d2aa3be37c6b35d2b56f6bda9d93416d9ed0d91f463eebe00faa4`。
- 原 STOPPED ledger SHA256，以及原批次全部文件的只读完整性清单。

新 ledger 的本地索引 1–8 对应原 `planned_order` 13–20；原第 12 条不在清单中。新预算字段最多为 8 次客户端派发，历史 12 次单独引用，不将新 ledger 的零起点解释成历史预算被重置。

## 最小适配

`lab/pilot02_continuation.py` 只负责后八项范围、旧记录只读核对、新 ledger 和新授权/生产预检门禁。直接复用 `pilot02_dispatcher.advance()`、`perform()`、锁、原子保存、成对报告、原适配器与 `pilot02_contract.score()`；没有新 HTTP、bridge 或评分实现。

默认 `run` 为 dry-run。旧 20 次授权不能用于续测；新授权必须绑定新批次、绝对输出路径、原批次 ID、原顺序哈希、续测清单哈希和历史派发数 12，并明确 `max_dispatches` 为 1–8。新授权不可替换扩容。第九次不会派发，任何未决或无效结果停止且不重试。沿用原引擎，八项全部有效完成后的状态为 `BUDGET_EXHAUSTED`（额度用尽），四对结果单独保存在新目录。

生产检查记录必须新建并绑定新批次、续测清单和 bridge 配置 SHA，验证原 ChatGPT 认证/非生成鉴权路由/隧道、单 worker、模型、190/180 秒超时。旧批次检查记录不能复用；适配器要求启动时检查记录不超过 15 分钟。该记录是操作员对实际检查的记录，不是软件自动证明生产在线。本轮不创建这样的 PASS 记录。

客户端预算不等于上游生成计数。原 CLI 内部重连继续记录在原始 events 中；出现顶层错误仍按原门禁 NOT_SCORED 并停批。不得声称能用客户端预算精确控制或推出上游尝试数，也不把取消确认当成完成。无重连样本统计与协议排除项分开。

## 未来命令（本轮未执行真实模式）

在 `ubuntu-robot` 同步本分支后设置原 Python 环境，然后选择一个不存在的新输出目录：

```bash
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
PY=/home/alex/astra/.venv/bin/python
$PY experiments/spatial_input_eval_v0/lab/pilot02_continuation.py prepare \
  --output experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01
$PY experiments/spatial_input_eval_v0/lab/pilot02_continuation.py run \
  --output experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01
```

上述第二条默认零派发。只有用户明确授权这最多八次续测、实际生产连接检查通过，才由操作员建立新记录并执行：

```bash
$PY experiments/spatial_input_eval_v0/lab/pilot02_continuation.py run \
  --output experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01 \
  --real --authorization /absolute/path/to/new-continuation-authorization.json \
  --preflight /absolute/path/to/fresh-continuation-production-check.json \
  --bridge-config /absolute/path/to/ubuntu-robot-bridge-config.json
```

授权字段：`generation_authorized`、`batch_id`、`output_root`、`order_sha256`、`max_dispatches`（不超过 8）、`deadline_s`（180）、`concurrency`（1）、`user_authorization_statement`、`original_batch_id`、`prior_client_dispatches`（12）、`continuation_manifest_sha256`。

预检字段：`status`、`batch_id`、`execution_host`（ubuntu-robot）、`continuation_manifest_sha256`、`bridge_config_sha256`、`server_timeout_s`（190）、`client_timeout_s`（180）、`single_worker`、`non_generating_auth_and_tunnel_check`、`model`、`reasoning`、`checked_at`（带时区的 ISO 日期）。必须来自实际新检查，不能照抄为 PASS。

## 离线验收

七项专用测试覆盖：八份冻结输入通过模拟原 bridge 完整传输及独立重评分、后缀顺序、旧授权拒绝、新授权最多八次、过期或不匹配预检拒绝、原第十二条注入拒绝、零分继续/协议错误停批、默认 dry-run、原批次所有文件哈希不变。测试用授权只存在于销毁的临时目录，模型子进程被禁止。

```bash
PYTHONPATH=experiments/spatial_input_eval_v0 /home/alex/astra/.venv/bin/python \
  -m unittest discover -s experiments/spatial_input_eval_v0/tests \
  -p test_pilot02_continuation.py -v
```

证据目录：`evidence/pilot02_continuation_prep_20261013/`。主批次目录始终只读；原 STOPPED、12 次派发、NOT_SCORED 和五对主配对均不变。

最终验收：Mac 7/7，ubuntu-robot 7/7；原真实工作树 212 个批次文件哈希未变，607 个冻结文件未变。真实派发 0，未创建持久化续测 ledger 或可使用的新授权。
