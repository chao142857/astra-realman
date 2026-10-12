# S1 qualification A：真实链路验收与超时诊断

本次严格执行用户新授权的 **1 次**冻结 S1 空间理解 A 请求，qualification 模式，90 秒单次上限。真实调用在已验证的宿主机网络 namespace `net:[4026531840]` 启动原 bwrap；不是在外层 managed namespace 重复命令。**验收失败：90.19 秒后没有模型完成事件、没有非空输出。** 没有重试、没有延长到 180/300 秒，没有运行 C；进入 C 的有效 JSON 条件未满足。

| 验收项 | 结果 |
|---|---|
| 正常模型完成事件 | FAIL：无 `turn.completed` |
| 非空真实模型输出 | FAIL：`raw=""` |
| 严格 JSON/schema | 无输出可验证，`NO_MODEL_RESPONSE` |
| 独立评分器 | 已执行并离线复核一致；`NOT_SCORED, score=null`，没有空间判断分数 |
| 请求、响应、耗时、可得 usage 保存 | PASS；请求/原始 events/stderr/response/计时/评分均保存；usage 不可得，保留 null |

机器可读结论：[qualification_acceptance.json](../evidence/routing_repair/qualification_acceptance.json)。完整真实产物：[real_A_qualification/](../evidence/routing_repair/real_A_qualification/)。新授权及已耗尽预算单独记录在 `qualification_authorization_record.json`，此前准备计划与早期失败产物保留原样。

## 实际发生了什么

启动器在调用前核验 namespace 等于前次 host 网络对照值，并写入 `qualification_A_launcher.json`。worker 的 `infer_started.json` 记录 `mode=qualification, timeout_s=90`；worker deadline=95 秒，launcher timeout=110 秒。payload SHA256 为 `d06af366b15d2eacdda8cafb69d479ab4fcef3e11a7e42c6672b6128033b607a`，完整 request 和 model_parameters 与原冻结失败 A 完全一致。只选择已有 timing profile；模型仍为 `gpt-6-astra`、medium、OpenAI provider，原 bridge/worker 和所有工具开关未改。

真实事件只有 `thread.started`、两条启动 warning（skip_host_skill_discovery / code-mode host disabled）、`turn.started`。没有可见 reasoning、agent message、输出增量、完成或 usage。约 65 秒时也只有这些事件。CLI runtime logs 表为 0 行；ephemeral state 的 threads 表为 0 行。因此本地 `turn.started` 不能用来证明服务端已接收请求，也不能把空事件流解释为“模型一定正在慢速推理”。

catalog 还记录 default_reasoning_summary=`none`，当前保存的是 CLI `--json` 事件而不是原始 HTTP/SSE 流。推理期间没有 reasoning 事件也不能用来排除隐藏推理；必须补足发送/传输观测才能作更细归因。

90 秒后原 bridge 触发 `TimeoutError:MODEL_TIMEOUT` 并终止 CLI。记录的 CLI return_code=0 不能抵消该 timeout error；应用退出码=1，独立评分器正确保留基础设施失败。进程观察发生在结束后，匹配数为 0，不能作为调用期间的连接证据。

## 超时后的零生成诊断

所有以下检查都保留原 bwrap 与生产环境过滤，不发送 `exec`、`thread/start`、`turn/start` 或 Responses 生成请求。协议字段依据当前 CLI 自己生成的 experimental JSON schema；完整 schema 产物也归档。

| 层级 | 新证据 | 可以得出的结论 |
|---|---|---|
| 账号 / workspace routing | 原 bwrap 中 `account/read(refreshToken=false)` 1.70 秒成功；workspaceRouting.backendOrigin=`https://chatgpt.com`，accountRoutingOverride=`NO_CONSTRAINT` | 当前隔离环境能完成账号与路由元数据发现；不是笼统的“routing failed” |
| 同一路由检查复现 | 独立 `run_metadata_probe.py` 入口再次成功，生成请求数=0 | 无生成的路由发现可复现；不是实际推理复现 |
| 账号配额 | `account/rateLimits/read` 1.92 秒成功；ordinaryUsageAllowed=true，窗口使用48%，spendControlReached=false，rateLimitReachedType=null | 未发现账号级配额耗尽；不证明 Astra 单模型权限或本次生成被服务端接收 |
| provider schema / payload | 原 `validate_payload` 和 jsonschema schema 校验 PASS | 没有发现本地 schema 编译/冻结 payload 拒绝；不等于服务器接受 schema |
| 图像 | 三张原始 PNG 各640×480 RGB，Pillow verify/load PASS；总94,287字节，SHA均一致 | 没有发现损坏、截断或错误图片；没有改图、裁图或减视角 |
| 原 prompt 与 native image input | CLI `debug prompt-input` 返回合法 JSON；原 prompt 完整匹配，input_image=3，图片读取错误=0 | 本地 CLI 可构造这些输入；debug 渲染没有实际生成或服务端验证 |

证据目录分别为 `account_routing_host/`、`metadata_runner_verified/`、`rate_limits_host/`、`frozen_input_host_verified/`。账号邮箱、凭证及身份/重置券 ID 不入 Git；只记录脱敏元数据。没有刷新、删除或复制凭证；auth 一直 readonly mount。

早期 `frozen_input_host/` 的 debug probe 虽 exit=0，但 `--image` 的多个值参数把尾部 JSON prompt 吸收为额外图片名。这是诊断命令的参数错误；已用 `--` 结束图片选项，并追加 prompt 完整匹配、图片数量、读取错误的语义检查。早期产物全部保留，不作为成功输入检查。生产 `exec` 仍以原 `-` 从 stdin 读 prompt，未改动，不能把这个 debug 参数问题归因到真实失败。

另有一个待证实的 CLI 兼容性线索：远程 Astra catalog 的 tool_mode=`code_mode_only`，原命令禁用 code_mode_host，启动会产生 fail-closed warning。该 warning 不是服务端生成错误，现有日志不足以建立它与超时的因果关系；未擅自启用工具或修改生产推理逻辑。

## 当前阻塞层级与边界

当前分类为 **`WORKSPACE_ROUTE_METADATA_VERIFIED_GENERATION_COMPLETION_UNOBSERVED`**。外层网络问题已有正确启动边界；无生成的账号路由发现和本地冻结输入检查通过。真实验收仍阻塞在 **native exec 的生成请求/流式响应阶段**：缺少服务端接收、HTTP/WebSocket 状态及生成进度证据，不能区分客户端运行时停滞、生成传输等待、服务器推理延迟或服务器输入兼容性问题。

没有得到模型完成，不能声称链路修复成功；没有得到预测，不能评价空间题答对几道；也不能将无异常的 account/read 套用为那次 exec 的成功路由证据。详见 [qualification_postmortem.json](../evidence/routing_repair/qualification_postmortem.json)。

下一步如另获一次真实调用授权，应在保持原请求及90秒上限的前提下，先准备能记录请求发送、HTTP/WS 状态与 SSE 事件时间的脱敏观测。先解决生成阶段不可观测的问题，不通过继续放大时间预算或更换模型/输入来掩盖它。本次不再请求模型；C 必须等有效 A JSON 出现。

## Ubuntu 上实际验证的命令

```bash
cd /home/alex/astra_spatial_capability/routing-fix-v0
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
python3 -m unittest discover -s experiments/spatial_input_eval_v0/tests -v
```

本次唯一真实 A 命令，**实际执行结果失败，不自动重跑**。当时通过经批准的 host 执行环境运行并核验 namespace；普通 managed exec 不能代替此边界。

```bash
/home/alex/astra/.venv/bin/python -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --conditions RGB_MULTI_VIEW --real --max-real-calls 1 --timing-mode qualification \
  --output experiments/spatial_input_eval_v0/evidence/routing_repair/real_A_qualification
```

可复现的零生成路由命令已经实际执行成功（每次用新的 output）。namespace 是本次机器实测值，迁移机器后应重新核验，不把该数值当作通用配置。需要批准的 host 运行边界时，脚本本身不会自动提权。

```bash
/home/alex/astra/.venv/bin/python experiments/spatial_input_eval_v0/diagnostics/run_metadata_probe.py \
  --kind account-routing \
  --output experiments/spatial_input_eval_v0/evidence/routing_repair/metadata_runner_verified \
  --expected-netns 'net:[4026531840]'
```

离线验收命令已实际执行，不调用模型，结论 FAIL：

```bash
python3 experiments/spatial_input_eval_v0/diagnostics/assess_qualification.py \
  --run experiments/spatial_input_eval_v0/evidence/routing_repair/real_A_qualification \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --output experiments/spatial_input_eval_v0/evidence/routing_repair/qualification_acceptance.json
```

测试31/31 PASS。本次真实 A 启动1次、有效 JSON 0、C 0、A/C 对照0；修复分支累计有此前 standard 30秒和本次 qualification 90秒两个独立获授权的尝试，二者都没有回答或可得 usage。全部新增代码、协议 schema、早期及修正后的诊断、失败原始输出、测试与报告均提交并推送；普通 runtime SQLite 不入 Git。原始证据和生产 harness 保持不变，见 `qualification_integrity_review.json`。
