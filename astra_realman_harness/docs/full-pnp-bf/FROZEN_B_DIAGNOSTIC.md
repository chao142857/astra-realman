# 首条 B 超时：只读诊断与独立 frozen-input 入口

基于 `a579a5e`，保留冻结 `9b092e9` / `a579a5e` 及 `4aa89a2` / `99ac311`。本轮仅源码、输入和日志核查，以及假进程检查；真实模型/物理场景/硬件调用均 0。旧 B/F 入口、30 秒条件、控制器、安全门、物理参数及所有策略文件未修改。

## 原运行与观察事实

只读源：`/home/alex/astra-realman_ws/full-pnp-real-bf-pair-20261008T184352/B/episode/workers/request-001`。旧账本 B=FAIL，actual_attempts=1、real_model_calls=1；F=NOT_RUN，total_attempts=1。该 attempt 未删除、未返还额度、未重新分类成成功。

- 原 FullSlot 终态 CANCELLED / REQUEST_TIMEOUT。原 infer timeout 参数为 29.956295502s；原 infer latency 29.980641662s，error=`RuntimeError:CANCELLED`。return_code=0 不表示模型成功。
- 原事件只有 thread.started、两个 item.completed/error 启动提示、turn.started；没有 turn.completed、turn.failed 或候选 raw；usage=null。stderr 只有 `Reading prompt from stdin...`。
- wire 8509 bytes，input_payload 129657 bytes。payload、冻结图片、实际 infer 的 context/prompt/schema/PNG、附件记录与真实 CLI command 一致。schema 通过本地 JSON Schema 检查。owner 保存的 schema 只有 binding.required 排序不同，集合/约束等价；实际发送 schema 原字节保留，不重新排序后发送。
- wire / 实际 prompt SHA256：`a3c53b96aac8a9592a222dd109a1920cd6b2fe7bd113fa6190e1dc870f9efd1a`。
- input_payload SHA256：`d0cb041762f430f5b368f5411a75a5093f7da6f59fb947a60f1dfb41caf3fc61`。
- 实际 schema SHA256：`99b1d0ade749c6e9fa2618b3037eef737743f114b33ef0aea7dd5cdca8023cc7`。

| 当前图（均640×480 PNG） | bytes | SHA256 |
|---|---:|---|
| assembly | 20563 | `2d6dab3425b37992bd7964bf06b53acbce53c1a37fd8a7751807979038d9940c` |
| fixed | 24280 | `431478e41a19f25e05999623d9d83fcc8a31697d9d31cfb23cbafc2b18dcc90f` |
| wrist | 43966 | `4e0345b2ab7e2690fa68858ee183a13f5a869944c252651dee879643a4157475` |

## Code Mode 提示判断

该提示不是“CLI 因 Code Mode 关闭而立即失败”的证据：本次提示后有 turn.started。更直接的历史对照为旧 M/S seed2-S 请求 `bb4abff4980d40a7a1d5d3fba4008978`：完全相同提示、相同工具禁用列表之后，11.719239412s 收到合法 raw、turn.completed 和 usage，error=null。对照原文件路径/hash、事件和禁用列表保存在新证据目录 `historical-warning-comparison.json`。不将旧任务时间用来推断新任务应有延迟。

据此将其判为**非致命启动提示**；本次 30 秒未完成的具体原因仍 UNKNOWN。既无完成回执，也无可据以区分排队/服务端计算/网络停顿的记录；不把 turn.started 当服务端已接受的证明。原 runtime SQLite 只在新目录副本上读取，其 logs 表没有可用行，原数据库未打开写入。

[OpenAI Docs 的非交互模式说明](https://learn.chatgpt.com/docs/non-interactive-mode)区分 turn.started / turn.completed 等事件，并说明 output-last-message/schema 参数。官方页面未直接解释这条 Code Mode 提示的具体阻塞语义；上述判定以本地原始事件及成功对照为依据。没有启用 code_mode_host 或任何其它工具，也没有压制/改写提示。

## 独立入口与不变边界

新增 `scripts/frozen_pnp_diagnostic.py`（prepare/run）与仅用于该诊断的 `frozen_pnp_infer_worker.py`。复用**原样未改**的 `infer()`、环境白名单、原 bwrap 构造函数、launcher/Node 路径、认证挂载与工具关闭配置。旧 FullSlot worker 的 30 秒上限保持原状。

prepare 只读检查并复制冻结数据，不启动 CLI/model/scene。当前准备包位于：

`/home/alex/astra-realman_ws/astra-frozen-b-diagnostic-evidence-20261008/prepared`

`frozen/` 保存原 wire、payload、PNG、实际 prompt/schema/CLI command；`prepared.json` 保存 hash 与独立上限。绑定中的旧 observation/revision/time 完全保留，不冒充新观测。任何冻结字节/hash 或原 infer 源码漂移均在发送前失败。

run 需要 `--authorize-one-astra-request`。每个准备包只允许创建一次 `request-001`；目录已存在即拒绝，准备/启动/API/超时/解析失败都不能重用该包。不自动重试，也不续跑原 B/F。全部角色仍只有此次 B 的冻结请求，不启动 F。

独立请求预算固定 **90 秒、最多 1 次本地 infer**；这是新诊断条件，不改 B/F 实验条件，不继承旧额度。owner 与 worker 共用截止时刻；到时取消，最多另给 4 秒退出/原始数据落盘清理，完整墙钟另记。共用原全局单 infer 锁，避免与 B/F 并发。

新 `request-001/` 保留实际 command、冻结输入、bridge 原文件、raw.txt、events.jsonl、stderr.log、worker stderr、原 usage 字段/事件、耗时、turn.completed 布尔及次数、attempt阶段与 parsed.json。缺 usage=null，可能的子项不重复相加。raw 严格解析、绑定/证据引用/动作结构检查；合法 candidate 只标记 PARSED_OFFLINE_NOT_EXECUTED。无当前真实状态，实时 RGB/接续适用性为 NOT_CHECKED_NO_LIVE_STATE，绝不执行动作或启动 SAPIEN。

客户端仍请求 gpt-6-astra / medium；服务端身份、effort、内部重试没有明确回执时仍 unknown。原始错误、提示和部分输出保留，不从客户端配置推断服务端事实。

## 未来显式启动命令（本轮未执行）

```bash
/home/alex/astra/.venv/bin/python \
  /home/alex/astra-realman_ws/astra-realman-frozen-b-diagnostic-20261008/astra_realman_harness/scripts/frozen_pnp_diagnostic.py run \
  --prepared /home/alex/astra-realman_ws/astra-frozen-b-diagnostic-evidence-20261008/prepared \
  --authorize-one-astra-request
```

新请求归档路径是该 prepared 目录下的 `request-001/`。当前目录尚未创建，请求数为 0；等待用户另行显式授权。

## 离线验收

31 项回归 PASS：既有 CLI 环境4项、B/E/A worker18项、新诊断9项（7.855s）。新增覆盖精确输入复制、schema顺序语义比较、未授权零启动、90秒传递且不沿用30秒、raw动作仅解析、格式/API/启动失败、超时部分输出、冻结篡改、唯一attempt不可复用、usage/turn.completed以及提示保留。测试推理进程均为无网络/无认证假 CLI，不证明真实请求将于90秒内返回。

开发过程中首次准备检查将 schema.required 的列表顺序当成内容不一致，发送前退出、真实调用0。已改为仅在离线比较时按 required 集合核对；发送字节仍原样。此失败保留于新证据 `DEVELOPMENT_NOTES.md`。其余旧历史记录未覆盖。
