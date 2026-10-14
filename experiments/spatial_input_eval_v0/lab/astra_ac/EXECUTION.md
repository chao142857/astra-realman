# 六场景 Astra A C 专用执行接入

绑定 `7512ebe` 中的 `evidence/astra_ac_plan_20261014/future_ac_order.json`，共 24 项、六场景、两个独立重复。A/C 输入、顺序、任务、policy、schema 和原 2 mm SAT clearance 不变。当前真实生成预算为 **0**，只做离线验收，尚未检查生产连接。

## 最小复用范围

`runtime.py` 将原 `pilot02_runtime.py` 加载到独立命名空间，只绑定本轮冻结文件、GT 和任务路径。直接继承原 MacBridgeAdapter，使用同一 HTTP、鉴权、超时、取消、usage、模型/Code Mode 参数校验和事件验收；原 `pilot02_contract.score()` 负责评分。原 `perform()` 负责传输和归档，原 atomic save 和主机排他锁继续使用。没有修改旧运行模块、生产 bridge、认证、评分器或任何重建代码。

新 `dispatch.py` 只处理原引擎硬编码 20 项无法覆盖的 24 项清单、授权绑定、预算、重复与配对。新增 reconnect 诊断拒绝规则，即使随后出现 JSON/turn.completed 也不作为协议有效结果。独立重评分会重新读取原始证据，不复制第一次评分。

## 预算与停止语义

- `prepare` 仅创建新批次、私有权限 ledger，初始 DRY_RUN，预算尚未获授权；目录存在时拒绝覆盖。
- ledger 保存批次 ID、输出路径、冻结顺序及 release 哈希、实现及依赖哈希、原 24 项 jobs 和重复编号。
- 原子 fsync/replace 预留一次预算后才允许进入传输。单 worker，单机共享排他锁，无并发或自动重试。
- 新授权须绑定 batch ID、输出根、顺序/release/实现哈希、1–24 次上限及 180/190 秒、单 worker。不得追加或替换已绑定授权。
- 生产检查须绑定同一批次、实际 Ubuntu-Robot 主机、bridge 配置哈希、190 秒服务端、180 秒客户端及不产生生成的认证/隧道检查；开始执行时不得超过 15 分钟。当前没有生产检查凭证。
- 客户端超时、传输/协议错误、CLI 顶层错误或重连、参数漂移、输入完整性失败、重复 request/thread ID，立即 STOPPED，消耗的预算不退回。
- 有效 JSON 的几何失败保存原答案并计零分，继续下一项。
- 中断留下 RESERVED 或 UNKNOWN，下一次调用会停止而非重发。`reconcile` 只读本地原始输出并保存诊断；不会退款、恢复 STOPPED 或发请求。完成状态未知即使后来找到有效输出，也不自动纳入主结果或续跑。
- 已完成 VALID 项在继续执行前重新验收；被改动的归档立即拒绝。若确实是已持久化 VALID 的正常检查点，可以在原授权范围内继续剩余顺序；任何 STOPPED 批次均不能这样恢复。

只有 `evidence/astra_ac_runs/<new-batch>/` 能执行真实模式；临时 `astra-ac-*` 路径仅用于测试。旧实验路径在读 ledger 前被拒绝。没有复用、读取或重置历史 ledger。

## 独立重复和证据

每次都走一次新传输，产生独立 request_id、独立输出目录，并要求新的 `thread.started.thread_id`。原生产命令严格核对 `--ephemeral`、gpt-6-astra / medium 和 Code Mode 配置；不传 conversation resume。相同输入哈希只是两次重复的控制条件，绝不从第一次归档返回缓存答案。

每项保存请求及输入 SHA、原 raw JSON、CLI events、stderr、桥接返回、完成/传输状态、usage、客户端耗时、原几何约束失败，以及 `assessment.json` 和 `independent_rescore.json`。缓存 token 和 reported reasoning tokens 不存在时保持 null，不伪造为 0。相同答案仍可能来自独立调用；缓存命中也不等于复用旧请求。客户端请求数与不可精确观测的上游生成次数分开记录。

每完成同一 scene/repeat 的 A/C 即保存 `paired_results.json`；不会跨重复或跨场景错配。主结果仍是规划决策，空间事实估计保持 NOT_MEASURED。

## 零生成验收与固定策略

`offline_acceptance.py` 复用原 HTTP Handler，但在监听前将 infer 替换成 fixture。它禁止 subprocess 和生产网络端口，只允许随机 localhost mock 端口。24 项全部执行，包含第 3/15 项合法零分，产生 24 份独立请求/线程和 12 对配对；mock usage 和成功分数不代表 Astra 能力。

固定策略只做原 scorer 检查：公共目标区域中心 + 初始姿态、直线路径、固定正/负侧绕行；yaw 另列固定世界 yaw=0。初始姿态直接取独立 GT，属于绕过感知的简单策略基线，不是 RGB 估计器。没有使用 witness、搜索可行解或按碰撞反馈修正策略。尤其 yaw_01 保留初始朝向即可在公共中心合法放置；必须在真实报告中单独标记，不能把该题成功等同于主动改变朝向能力。

## 当前可执行的零生成命令

```bash
cd /home/alex/astra-realman_ws/spatial-astra-ac-exec-20261014
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0:$PWD/experiments/spatial_input_eval_v0/lab"
PY=/home/alex/astra/.venv/bin/python
$PY -m astra_ac.verify --root experiments/spatial_input_eval_v0/evidence/astra_ac_plan_20261014
$PY -m unittest discover -s experiments/spatial_input_eval_v0/tests
# 必须换新临时目录，不覆盖已归档验收。
$PY -m astra_ac.offline_acceptance --output /tmp/astra-ac-acceptance-NEW
```

真实运行前，等待用户明确授权最多 24 次客户端派发，再重新检查 ubuntu-robot 和 Mac Bridge。以下是未来入口说明，本轮不执行：

```bash
# 仅创建全新 DRY_RUN ledger，无模型请求。
$PY -m astra_ac.dispatch prepare --output experiments/spatial_input_eval_v0/evidence/astra_ac_runs/NEW_BATCH
$PY -m astra_ac.dispatch run --output experiments/spatial_input_eval_v0/evidence/astra_ac_runs/NEW_BATCH
# 只有明确新授权和当次生产预检完成后，才运行带 --real 的入口。
$PY -m astra_ac.dispatch run --output experiments/spatial_input_eval_v0/evidence/astra_ac_runs/NEW_BATCH \
  --real --authorization /path/to/NEW_BATCH_authorization.json \
  --preflight /path/to/NEW_BATCH_production_preflight.json \
  --bridge-config /path/to/existing_bridge_config.json
```

授权 JSON 的完整字段见 `dispatch.authorize()`；生产检查记录字段见 `dispatch.check_preflight()`。本轮不会生成填写为 true 的生产授权模板或“PASS”生产凭证。
