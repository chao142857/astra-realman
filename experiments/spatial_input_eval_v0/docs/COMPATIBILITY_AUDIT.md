# Astra / Codex 0.162.1 compatibility and transport audit

基线 `192537080cab5a9b6a78f89e1bfd1d495be04a84`；独立分支 `codex/spatial-eval-compat-audit-20261012`。本阶段真实生成预算 **0**，实际新增真实生成 **0**，S1 A/C 未重跑。生产 bridge、模型参数、冻结 S1 prompt/schema、真机文件和原始失败证据保持不变。

## 结论

**Code Mode warning 是非致命的启动/turn 警告，不能据此认定生成被阻断。** 0.162.1 的匹配源码和本地原生 CLI fixture 均支持此结论。catalog 的 `code_mode_only` 确实覆盖 CLI 的 `code_mode=false` / `code_mode_only=false`；关闭 `code_mode_host` 会使执行器不可用，而且 CodeModeOnly 不降级为 Direct。但纯 assistant 文本完成不需要创建 host session。

真实 qualification 仍为 **生成传输/服务器接收与完成边界未确认**。90 秒日志没有 `response.created`、发送状态或流事件的原生阶段观测，不能区分 WS 预热/握手等待、生成发送/接收问题、服务端排队/隐藏推理、schema/image 接受问题。当前日志也没有新的 workspace routing error。此前宿主机原 bwrap 的 account/read 已发现路由，并不证明 `/responses` 或 WS 可用。

## 版本化源码审查

匹配官方 tag `rust-v0.162.1`，源码 commit [`092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`](https://github.com/openai/codex/tree/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d)。[source_pin.json](../evidence/compatibility_audit/source_and_history_final/source_pin.json) 保存来源、24 个文件的原始文件 hash、带行号片段和 URL；附原 LICENSE。没有用当前 main 代替 0.162.1。

| 路径与行号，均相对 `codex-rs/` | 实际行为 |
|---|---|
| `core/src/tools/mod.rs:75–98` | `model_info.tool_mode` 优先于 feature flags。仅 CodeMode 在 host 不可用时允许 Direct fallback，CodeModeOnly 不允许。 |
| `core/src/session/turn_context.rs:1405–1448` | warning 经 `send_event` 发出，函数继续，无 fatal 返回。 |
| `exec/src/event_processor_with_jsonl_output.rs:409–421` | warning 被包装成 `item.completed / item.type=error`，**CodexStatus::Running**；不是 `turn.failed`。 |
| `core/src/tools/code_mode/mod.rs:98–145`；`code-mode/src/remote_session.rs:12–112` | disabled provider 的 availability / create_session 返回错误；执行器调用才会 lazy 创建 session。纯最终文本不调用它。 |
| `core/src/tools/spec_plan.rs:861–1020` | 按 catalog 有效 mode 注册 exec/wait；禁止 flag 不等于所有工具从 wire 消失。 |
| `core/src/client.rs:915–950` | Astra 的 `use_responses_lite=true` 将工具放入 `input[type=additional_tools]`，不放顶层 `tools`。只看顶层会误以为没有工具。 |
| `install-context/src/lib.rs:176–210` | host 从 package resource / CLI 同目录发现；仅加 PATH 不保证能发现。 |

独立本地请求保留完整 Astra catalog、模型 `gpt-6-astra`、medium 和原全部禁用 flags；无图像/schema。真实 native 0.162.1 在断外网、无 auth 的 bwrap 内接收 **fake loopback SSE**，同时产生 warning、非空 `{"offline_fixture":true}`、`turn.completed` 和 fake usage。证据：[最终本地结果](../evidence/compatibility_audit/local_protocol_final/RESULT.json)、[原生 stdout](../evidence/compatibility_audit/local_protocol_final/exec.stdout.jsonl)、[完整 fake 请求](../evidence/compatibility_audit/local_protocol_final/fake_requests.json)。**这是客户端协议测试，不能当成真实 Astra 成功。** fixture 改了 provider transport/auth 为本地无认证 HTTP；未测试 hosted WS/routing/entitlement。

实际 wire 的 AdditionalTools 仍包含 `functions.exec/wait/request_user_input/request_user_input_async`、`clock.sleep` 和 collaboration 管理工具，即使有关 flags 禁用。因此不能把原禁用列表视为完整工具权限白名单，也不能盲目启用 host。该发现未用于修改生产工具策略；本阶段没有任何工具 cell、子代理或真机调用。

## Host 安装和兼容性

匹配 host 位于 `/home/alex/.codex/packages/app-server-daemon/releases/0.162.1-x86_64-unknown-linux-musl/bin/codex-code-mode-host`。release manifest 的 version 为 0.162.1；CLI 原生二进制输出 `codex-cli 0.162.1`。[installed.json](../evidence/compatibility_audit/source_and_history_final/installed.json) 保存二进制 hash 与 manifest。host 无 `--version` 参数，不能声称它独立输出了版本号。

原 bwrap 不挂载该 host；原 CLI sibling 位置也没有匹配 host。当前原配置先选择 Disabled provider，因此警告直接原因是 **feature 禁用**；安装缺失不是唯一原因。旧 plugin host 和其他 release host 没有被替换或使用。

在无网络、无凭证、无 GT 的本地 bwrap 中，匹配 host 的 **V1 handshake、空 session open/shutdown PASS**，[完整 transcript](../evidence/compatibility_audit/local_protocol_final/host_handshake.json)。执行 cells=0，nested tools=0。这验证 IPC 生命周期兼容性，没有验证 JS/V8 执行或 hosted 工具调用。

独立 host-enabled 设计见 [native_text_diagnostic.plan.json](../config/native_text_diagnostic.plan.json)：CLI/host 按 sibling layout 只读挂载，保留 bwrap 和其他禁用项，只改变 `features.code_mode_host=true`，不挂载 GT/评分器/控制器/整个 HOME。**目前没有证据表明文本诊断必须启用 host；此配置未运行 hosted turn。** 若后续工具调用确实需要 host，先在独立配置验证严格工具拒绝策略，不能扩大现有 exec/clock/collaboration 权限。

## 历史真实成功对照

审查两个历史目录的所有成功 worker_record，27 份副本按 thread_id 去重为 **24 次不同的历史完成**；全部非空输出、return_code=0、`turn.completed`、usage 非空，全部也有相同 fail-closed warning。延迟 14.13–39.88 秒。[逐条索引/哈希/有效 argv](../evidence/compatibility_audit/source_and_history_final/historical_comparison.json)；两条完整 raw/events/worker 记录也已归档。这些不是当前 S1 Evaluation 的新样本。

历史 native 为 **0.161.0**。其实际入口是 shim：`semantic-s1-provider-fix-20261009/runtime_cli/bin/codex`，会把 bridge 的 `openai` 改成同一 OpenAI 服务的 `s1_openai_no_retry` 配置 ID，强制 `supports_websockets=false`、request/stream retries=0、unbounded_connection_retries=false。每次保存的 effective_cli_argv 均确认这些设置。历史 seal 中 native/shim hash 与现存二进制/脚本匹配，版本 provenance 不仅来自当前 `--version`。[历史 seal](../evidence/compatibility_audit/source_and_history_final/historical_version_seal.json)。

历史环境为过滤后的 HOME/USER/LOGNAME/LANG 等和 shim PATH，未依赖代理全量继承；此前当前 host 网络检查也确认无代理的原环境可做 DNS/TLS/account-read。因此不增加 proxy 环境白名单。成功对照同时改变了 CLI 版本、传输和任务，**不能把 WS 差异直接当作已经证明的原因**，也不回退生产 CLI。

## 原生生成传输链和观测限制

1. `core/src/session/startup_prewarm.rs:410–465` / `core/src/client.rs:2176–2226` 可以预热 WS；`generate=false` 是连接预热，不是成功推理，也不能当作真实答案事件。它可能等待 Completed。
2. `core/src/client.rs:1030–1085,2237–2305` 根据 provider 的 supports_websockets 和 session fallback 选传输，并执行 workspace auth/routing。built-in OpenAI supports_websockets=true。
3. HTTP：`codex-api/.../endpoint/responses.rs:80–180` → `endpoint/session.rs` 加 auth 并套请求重试 → `http-client/src/transport.rs` 使用 route-aware reqwest 发送与读取 HTTP status/body stream。WS：`responses_websocket/connector.rs` 构建 wss URL、附 auth headers、握手；`responses_websocket.rs` 发送 response.create 并读取原始 frame。
4. `codex-api/src/sse/responses.rs:345–465,528–588` 解码 raw SSE，映射 Created / OutputTextDelta / OutputItemDone / Completed/usage；WS 也复用事件解析。`core/src/session/turn.rs` 更新 turn 和消息状态；`exec/...jsonl_output.rs` 将 app-server notifications 转成用户看到的 JSONL。
5. CLI `--json` 并非 raw 流式协议日志。Created 在 core 中设置 response ID，未必成为 stdout 事件；summary=none 时可能无可见 reasoning。`thread.started/turn.started/warning` 全部可在真实服务器接收前发生。

原 provider 的默认 request retries=4、stream retries=5、stream idle timeout=300000ms、WS connect timeout=15000ms。`model-provider-info/src/lib.rs:699–737` 对普通已有内置 provider 用 `entry().or_insert()`，因此直接写 `model_providers.openai.request_max_retries=0` **不能可靠覆盖内置项**。`core/src/responses_retry.rs:92–166` 还存在 unbounded connection retry 和耗尽后 WS→HTTP fallback；**仅设置 stream retries=0 仍不保证 WS 没有后续 HTTP 生成**。应用层不重试不等于 CLI 网络层零重试。

已验证的受支持观测为 CLI 配置 `otel.exporter / trace_exporter / metrics_exporter` 的本地 OTLP HTTP JSON，`otel.log_user_prompt=false`、`log_agent_responses=false`。本地 fixture 收集了发送 span、HTTP200，以及 raw SSE Created/Delta/Completed 对应事件；[仅白名单阶段记录](../evidence/compatibility_audit/local_protocol_final/sanitized_native_phases.json)。`tools/telemetry_filter.py` 丢弃 resource、用户/账号 ID、error/body、headers、任意字符串，只保留已知 phase 和数值属性；绝不保存原始 OTLP。

WS frame kind 在 0.162.1 telemetry 中主要是 `codex.websocket.event` **metric**，不是完整事件日志；需同时收集 metrics，不能只开 logs。OTLP 是 best-effort；本地快速 503/截断失败中没有收到 OTLP 记录，stdout/stderr 错误仍保存，不能保证超时 kill 前全部导出。不得把 telemetry 缺失当作无发送/无推理。避免全局 trace、raw HTTP headers、TLS 解密抓包或认证转储。

## 故障假设排序

| 顺位 | 假设 / 当前证据强度 | 证据及下一步区分方式 |
|---|---|---|
| 1 | **0.162.1 原生 WS/prewarm/流传输或入口版本差异**；高优先级，未确认因果 | 历史 24 次成功是 0.161.0 HTTP-only；当前是 WS 优先，account HTTP/read 成功但不能验证 WS/responses。需 phase 日志确认 handshake、generate=false 预热与真实发送是否到达。 |
| 2 | **服务器接收后的排队/隐藏推理/模型 turn 权限问题**；UNKNOWN | summary=none、无 Completed/usage；缺少 response.created 和 HTTP/WS status。普通 quota 正常不能证明 Astra turn entitlement。先最小文本请求隔离输入复杂性。 |
| 3 | **CodeModeOnly 选择了不可用工具执行路径**；条件性风险，作为启动 fatal 假设已被反证 | catalog override 和 Disabled provider 均确认；但源码不 fatal，本地当前 CLI 和 24 次历史均 warning 后完成。旧 90 秒日志没有工具调用事件，不能说发生过 host 执行失败。若诊断出现 tool call，再审查工具拒绝/host，不预先启用。 |
| 4 | **S1 图像或 strict schema 的服务端接受问题**；UNKNOWN | 客户端 decode/render/schema PASS，3图 94287 bytes；不能证明服务端支持。先无图无 schema 文本，再单独 tiny JSON，再冻结 S1 A，每步单独预算。 |
| 5 | **代理缺失、宿主机 DNS/TLS、全局账号未登录/普通额度耗尽**；当前 host 证据下较低 | 原 bwrap host filtered env DNS/TLS/account routing/read 和 quota 已 PASS；managed outer 曾明确网络禁止。不能把 managed 的 NETLINK EPERM 或旧 routing failure 归为当前 host 网络故障。后续先验证执行 namespace，绝不继承整个宿主环境。 |

## 下一笔最小请求方案（尚未授权、未执行）

目标只验证原生文本完成：同一 `gpt-6-astra` / medium，原工具 flags/会话与 bwrap，prompt 为 `Reply with exactly ASTRA_TEXT_OK. Do not use tools.`，无图像、无 output schema、无几何评分，90 秒上限。保存原始输入/输出/完成事件/耗时/可获得 usage 和安全 phase 日志。

原内置 WS 配置不能直接满足“一笔请求、不得自动重试”的约束。因此推荐先使用**独立诊断配置 ID，仍为同一 OpenAI 服务和现有认证/路由**，HTTP/SSE、request/stream retries=0、unbounded retries=false，不修改生产 bridge。本地注入 503 和截断 SSE 均验证：1 次 fake `/responses`、失败即停、无完成/输出，[503](../evidence/compatibility_audit/local_http503_no_retry/RESULT.json) / [截断](../evidence/compatibility_audit/local_truncate_no_retry/RESULT.json)。这不是另一模型/备用服务商；传输差异必须在下一笔授权中明确。

下一笔拟申请 **最多 1 次真实文本生成**。执行前还须为诊断 launcher 验证 tool-driven follow-up 和 auth recovery/replay 的阻断，不能凭零 retry 设置就宣称所有情况下恰好一笔。当前提供的是 **PLAN_ONLY**，无执行 API，无授权自动生效或重试。若要保持原 built-in WS 完全不变，须先另设计并离线验证单笔 outbound generation guard；当前不建议直接重跑。

必须在已验证联网的宿主机执行原 bwrap；不能在受限外层仅调整 timing 重跑。失败后按 handshake/prewarm、HTTP/WS status、Created、Delta、Completed 区分层级；90 秒无进展即停，不自动加到 180/300 秒。文本成功后，tiny strict JSON、冻结 S1 A、同任务 C 均各自重新授权，不自动进入下一阶段。

## 框架和实际 SAPIEN 交付

新增 `spatial_eval/sapien_scenes.py` 是独立静态 exporter，只导入 SAPIEN/PIL/NumPy 和实验 schema/输入 helper；不导入 owner、模型 adapter、IK 或真机控制。

六场景为 clear、occluded、narrow_container、rotated_cuboid、thin_obstacle、detour_wall。实际同静态状态 3 视角 RGB-D，每场景 understanding + placement/path 两题；**6 场景、18 RGB-D、12 任务**。无 physics step，明确无动力学/支持/抓取/机器人可达性结论，robot state 是空且 world==base 为显式仿真坐标约定。

GT extractor 仅读取实际 PhysX actor pose、collider local pose、box half_size 的 `physics_state.json`；container interior 从实际墙内表面和地板顶面计算。捕获前后 state 相等并 sealed，所有 RGB/depth/validity/calibration/snapshot/hash 验证通过；B 保持 null。C 只传几何，不传正确放置/路径/评分。质量检查：[validation.json](../evidence/sapien_six_v0_attempt1/validation.json)，[contact sheet](../evidence/sapien_six_v0_attempt1/captures/contact_sheet.jpg)。MESA PCI warning 与 camera pose API deprecation 原始 stderr 保留；实际 RGB 可见且 depth 有有效值，不能把 warning 当作未渲染，也不修改驱动。

41 单元测试 PASS，包括原 31 项、warning/host lifecycle、no-network/no-auth mount、遥测去敏、零预算 plan、故障不重试、真实渲染 seal/GT firewall、实际碰撞状态变化影响 GT、合法完整体积/绕行和碰撞路径失败。另执行 24 条 **MOCK_NOT_ASTRA** A/C 样本（12任务×2条件），全部结构解析 VALID，保存完整 CSV/JSON/失败索引；[mock manifest](../evidence/sapien_six_v0_mock/run_manifest.json)。mock 分数不得作为模型性能。

## 实际验证命令

以下在 Ubuntu 本 worktree 使用；每次使用新的输出目录，不覆盖归档。local protocol 的 bwrap 需允许 net namespace 的宿主机执行，内部仍 `--unshare-all`，**没有 `--share-net` 和 auth mount**；它不会访问模型服务。

```bash
cd /home/alex/astra_spatial_capability/routing-fix-v0/experiments/spatial_input_eval_v0
python3 -m unittest discover -s tests -v
python3 tools/collect_compatibility_evidence.py --output /tmp/astra-compat-source-new
python3 tools/local_protocol_probe.py --output /tmp/astra-local-text-new
python3 tools/local_protocol_probe.py --case http503 --output /tmp/astra-local-503-new
python3 tools/local_protocol_probe.py --case stream_truncate --output /tmp/astra-local-truncate-new
python3 tools/prepare_native_text_plan.py --output /tmp/astra-next-text-plan-new.json
/home/alex/astra/.venv/bin/python -m spatial_eval.sapien_scenes \
  --config config/sapien_six_static.json --output /tmp/astra-six-scenes-new
/home/alex/astra/.venv/bin/python tools/validate_sapien_exports.py \
  --captures evidence/sapien_six_v0_attempt1/captures --output /tmp/astra-rgbd-validation-new.json
python3 -m spatial_eval.cli run \
  --snapshot evidence/sapien_six_v0_attempt1/captures/sapien_*/snapshot.json \
  --conditions RGB_MULTI_VIEW RGB_ORACLE_3D --output /tmp/astra-six-mock-new
```

上述参数组合已用 evidence 下各独立目录实际验证；`/tmp/*-new` 是重新运行时需要选择未存在的目的路径。source collector 需要本机 `/tmp/astra-codex-01621-source` 精确 pin；迁移后按 source_pin 的 URL/tag 重新 shallow clone。渲染需本机现有 SAPIEN 3.0.0b1 venv/GPU 可访问环境；不安装或改变依赖。

早期 managed fixture 因 NETLINK EPERM 失败；第一次 host fixture 脚本根路径错误，随后修正，失败 launcher 也已保留。遥测初次计数包含 local analytics/turn-costs POST（非生成），最终版本只记录 `/responses` 为 inference POST。validation 工具初次缺少模块导入路径，已修正并通过。所有早期文件保留，不将失败重写成 PASS。

未完成：真实 Astra 0.162.1 hosted 文本/JSON 完成、精确当前 WS 根因、host JS 工具执行验证、真实 S1 A/C 对照。这里没有给出已恢复链路或模型能力改善结论。
