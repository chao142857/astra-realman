# Spatial Evaluation V0：Mac ChatGPT → SSH bridge 接入

首次获授权 A 的最新结果见 [MAC_BRIDGE_FIRST_A.md](MAC_BRIDGE_FIRST_A.md)：链路在线，但原 Python 缺 jsonschema，生成前失败；独立环境已通过完整 payload 预检，未重试。以下离线状态与计数为前一轮接入验收记录。

基线 `d9000b3`，独立分支 `codex/spatial-eval-mac-bridge-20261013`。
本次只进行离线模拟服务、静态诊断和原 CLI 的 version/help 检查，真实 Astra 生成请求为零。

## 当前状态与下一次真实 A 的条件

2026-10-13 01:06 UTC 的只读检查：Mac `127.0.0.1:18767` 无监听，实验室
`127.0.0.1:18766` 无监听；未发现 bridge/reverse-tunnel 进程。实验室原 token 文件可读，
检查没有读取、复制或输出 token。原 Mac bridge CLI preflight 通过：Node v26.0.0、
Codex CLI 0.160.0。原 worker 环境下 `codex login status` 确认为 ChatGPT 登录，未更改认证。version/help 通过不证明当前 Astra 生成成功。

本次复用了已有通用协议和 ChatGPT 认证路径的设计。没有启动原服务，没有访问生产
`/decide` 或 `/cancel`，没有修改原 bridge、认证、模型、安全开关或任何硬件程序。

下一次真实 A 必须先满足：

1. 用户明确授权一次真实请求，并确认采用已存在的 qualification 90 秒客户端截止时间。
2. 在 Mac 恢复原 bridge 及其 SSH reverse tunnel，使用原 ChatGPT 登录及原实验室 token。
   启动服务本身不产生生成请求；原程序从实验室读取原 token，token 不放进模型输入或仓库。
3. 用 `lsof` / `ss` 核对监听，仍然不以 `/decide` 做健康检查。当前登录是否有效、
   当前 Astra 与原 Code Mode 禁用开关是否兼容，仍需这一次获授权请求来验证。
4. 只发 S5 的一个 `plan` / `RGB_MULTI_VIEW`，预算为 1。先取得有效 JSON；
   随后的 A/C 成对生成需要另外授权。无重试、无模型替换、无 API-key CLI fallback。

Mac 上恢复原服务的命令（本次没有执行）：

```bash
/Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013/experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python /Users/tangchao/Desktop/资料/P7/astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py \
  --mode lab --executable /opt/homebrew/bin/codex
```

以下为首次单次请求命令（随后已获授权并执行，记录见 FIRST_A 文档；当前该目录已存在，不能直接重跑）：

```bash
cd /home/tongji/alex/spatial-eval-mac-bridge-20261013
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
PY=/home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python
$PY -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/lab_20261013/sim_suite_initial/lab_s5_placement/snapshot.json \
  --task-id plan --conditions RGB_MULTI_VIEW \
  --backend mac-bridge --bridge-config experiments/spatial_input_eval_v0/lab/mac_bridge.yanglab.json \
  --real --max-real-calls 1 --timing-mode qualification \
  --output experiments/spatial_input_eval_v0/evidence/authorized_mac_A_s5_first
```

输出目录必须是新的；已有输出不会覆盖。`prepared_next_A` 已离线冻结同一任务及图片，并编译 schema，未发送。

## 通用协议与边界

`MacBridgeAdapter` 独立于旧动作解析器。只使用生产脚本的通用 `validate_payload` 与
schema compiler；不调用旧 `infer`、动作 decoder、SDK 或执行程序。HTTP 用 Python
`http.client` 直接连接显式 `127.0.0.1`，不使用代理、重定向或重试。

| 项目 | 协议 |
| --- | --- |
| 请求 | `POST /decide`, `Authorization: Bearer <原token>` |
| JSON body | `context`, `images`, `schema`, `authoritative_schema`, `request_id` |
| context | 冻结 instruction/frame/task/schema/attachments/calibration/静态状态/同步元数据/可选几何 |
| images | 恰好三张 PNG，严格 base64，冻结 SHA256，单图最多 8 MiB |
| schema | 现有 compiler 的 provider schema；authoritative schema 为 V0 既有输出契约 |
| request_id | 随机 32 字符，与取消请求对应，不进入模型 context |
| 返回 | `raw`, `events`, `stderr`, `return_code`, `error`, `command` 等原字段 |
| 模型核对 | 归档 command 必须是 gpt-6-astra / medium / openai / ephemeral / 三张 RGB |
| 上限 | 请求 48 MiB；响应 8 MiB；客户端整个交换截止时间最多 90 秒 |
| 故障 | 403/409/连接失败/协议错误/参数漂移/超时均 NOT_SCORED；真实 runner 立即停止余下请求 |
| 取消 | 超时后仅一次 `/cancel`，同一 request_id，3 秒上限；不是生成重试 |

原桥的取消 ACK 即使 request_id 已不存在也可能为 true，所以 ACK 不证明任务确实存在或停止。
客户端超时记录 `MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN`，绝不声称服务端未生成。
`model_calls` 对真实 bridge 表示保守的 `/decide` 派发尝试数，403 也占预算；不等于已确认的服务端生成数。
真实 token usage 仅采用 CLI events 中明确报告的 usage，缺失为 unknown；mock 永远为零调用、无 usage。

归档包括输入副本、wire 请求、参数、原 HTTP body、原 bridge_result、raw/events/stderr、
response、transport、V0 evaluation 与成对报告。token 文件路径只在独立环境配置中，
Authorization/token 不归档；认证文件、GT、witness、评分器答案不进入 body/context/input_only。

三张 RGB、任务、schema、模型参数、解析器、评分器对 A/C 相同，只有 C 的 geometry 增加。
评分仍由现有 `assess_response` / `parse_prediction` / `evaluate` 完成。非空非法模型 JSON
作为解析失败计 0；传输失败或无返回保持 NOT_SCORED。原生产 bridge 的 Code Mode 配置不改动，
旧成功记录不能证明新 CLI/当前账号的生成兼容性。

## 离线验收与复现

模拟服务在随机 loopback 端口运行，明确禁止 18766/18767。它加载原 Handler 的独立模块，
在开始监听前将该模块的 infer 替换为无 GT 的 smoke predictor。真实 CLI 的 Popen 在测试中
被禁止；不启动主程序、不读取原 token、无硬件连接。临时随机测试 token 在目录外并随后清理。
最终 49/49 单元测试通过（新增 16 项 bridge 测试）；24 份输入形成 12 对，9 类故障归档通过，六场景 RGB-D/GT/隔离复检通过。
这些输出全部标记 `FAKE_MAC_BRIDGE_NOT_ASTRA`，只能说明协议和评测链路可用。

```bash
cd /home/tongji/alex/spatial-eval-mac-bridge-20261013
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
PY=/home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python
$PY -m unittest discover -s experiments/spatial_input_eval_v0/tests -v
$PY experiments/spatial_input_eval_v0/lab/mac_bridge_acceptance.py \
  --suite experiments/spatial_input_eval_v0/evidence/lab_20261013/sim_suite_initial \
  --output experiments/spatial_input_eval_v0/evidence/mac_bridge_reproduction
$PY experiments/spatial_input_eval_v0/lab/verify_suite.py \
  --suite experiments/spatial_input_eval_v0/evidence/lab_20261013/sim_suite_initial \
  --output experiments/spatial_input_eval_v0/evidence/mac_bridge_dataset_recheck
```

只读 Mac 状态复现（version/help，零模型请求）：

```bash
python3 experiments/spatial_input_eval_v0/lab/inspect_mac_bridge.py \
  --original-bridge /Users/tangchao/Desktop/资料/P7/astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py \
  --output experiments/spatial_input_eval_v0/evidence/mac_bridge_health_recheck
```

归档位置 `evidence/mac_bridge_20261013/`：最终 health（mac_health_auth_confirmed）、原 CLI preflight、unit logs、
protocol_acceptance 的 24 个样本 / 12 对报告、9 类故障、task_review、下一次冻结 A、artifact seal。
第一轮只读检查器因 ps 的非 UTF-8 进程参数失败，失败记录保留；修正解码后完成检查。

## 任务难度标注

| 场景 | 首轮定位 | 解释 |
| --- | --- | --- |
| S1/S2/S3 | 空间理解与简单放置控制 | 不作为主要规划难度证据 |
| S4 rotated_fit | 规定朝向的几何容纳 | 当前要求已给定四元数，不是自主选择朝向 |
| S5 placement | 主要规划测试 | 区域中心放置会碰撞，必须选择满足完整体积与净空的其他位置 |
| S6 held_object_detour | 主要规划测试 | 从起点到合法终点的直线路径碰撞；必须规划持物体完整体积的连续无碰撞路径 |

S4 后续独立建立 `plan_free_orientation`，将 required_quaternion 置 null，重新冻结 A/C，
让模型自行返回四元数；不改动当前 24 份输入。该变体本次仅列为 DEFERRED。
所有场景仍是静态盒体几何：无动力学、支撑稳定性、机械臂可达性或最短路径评分。
S6 允许任意可行三维绕行，包括越过障碍，并固定持物朝向；不能据此声称姿态路径规划能力。
任务区域尺寸/位置已在 A/C 均给出。Oracle 和评分 GT 同来自仿真，但 witness/正确答案只保留在私有评分数据中。

## 一次获授权请求的最小诊断

| 证据 | 可定位的边界 |
| --- | --- |
| 无监听 / 连接拒绝 | bridge / tunnel 尚未恢复，不能说明 Astra 服务状态 |
| HTTP 403 / 409 | bridge 鉴权 / 忙碌拒绝；不应重试或扩大预算 |
| HTTP 200 + rc 非零 / stderr | Mac CLI 启动、配置解析或账号路由失败；读取已生成日志定位 |
| HTTP 200 + rc 0 + schema 错误 | 模型输出契约错误，由 V0 解析器处理 |
| 客户端截止时间 + cancel ACK | 完成状态 unknown；只读检查 Mac 对应时间的 runtime/events/stderr/result |
| 明确的 CLI turn/usage 事件 | 可证明进展或完成，单凭进程存活/日志空白不能判定服务端正在生成 |

如日志明确提示 Code Mode 不兼容，记录证据并向用户提出独立的后续修复；本次不修改
原 bridge 的 Code Mode 开关，也不再请求模型“试一试”。
