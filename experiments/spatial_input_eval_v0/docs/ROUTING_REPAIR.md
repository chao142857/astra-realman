# 真实 Astra 链路诊断与修复（2026-10-12）

本文保留此前30秒阶段的诊断与交付记录。最新的一次已授权90秒 qualification A 验收及后续无生成路由检查见 [QUALIFICATION_ACCEPTANCE.md](QUALIFICATION_ACCEPTANCE.md)：真实输出仍为空，无生成 workspace 路由已验证成功，C 未启动。

修复分支 `codex/spatial-input-eval-routing-fix-20261012` 从 V0 后续归档提交 `9a7d608` 创建，包含原始 `b8bf9e6`，不覆盖原分支。只修改独立实验模块。

当前确认了两层阻塞：外层 managed execution 的网络限制，以及真实 A 尝试中的本地 worker 30 秒超时。网络已找到可重复通过的启动方式，**有效真实 JSON 尚未取得，修复验收仍未通过**。本次已授权并启动 1 次真实 A 调用，未重试、未发 C；usage UNKNOWN、score=null，不能归为模型空间判断失败。

## 证据审查与网络对照

先完整审查 `evidence/real_ac_s1/` 的 39 个非运行时产物，保存 SHA256 和一致性检查到 [initial_evidence_review.json](../evidence/routing_repair/initial_evidence_review.json)。请求、wire/context/stdin、图片与 seal、schema、模型和 medium 参数、ephemeral 标志、冻结 worker 源码及挂载均一致。历史 CLI 原始输出为空，模型目录刷新连接失败，workspace routing 重连及 WebSocket→HTTPS 回退，最后 exit=1。没有最终回答或 usage。

`worker_environment()` 在启动器及 bridge 内各过滤一次，代理变量均不在白名单。宿主机有指向 `127.0.0.1:7897` 的代理。诊断只试验 `HTTPS_PROXY/https_proxy/NO_PROXY/no_proxy`，没有把它们加入生产白名单，也没有无条件继承环境来执行模型。

相同 DNS、TCP、启用证书验证的无认证 HTTPS GET（两个 models 元数据地址；不发生成请求）：

| 执行边界 | 环境 | DNS/TCP/TLS 结果 |
|---|---|---|
| 外层 managed，net:[4026533518] | 当前宿主变量 | 连接本地代理 EPERM errno=1 |
| 外层 managed | 过滤后的宿主变量 | DNS EAI_AGAIN errno=-3 |
| 外层 managed + 原 bwrap | 原生产过滤变量 | DNS EAI_AGAIN errno=-3 |
| 外层 managed + 原 bwrap | 仅添加候选 HTTPS 代理变量 | 连接代理 EPERM errno=1 |
| 实际 host，net:[4026531840] | 以上四种环境 | DNS/TCP PASS；两个 HTTPS 地址均经验证 TLS 返回 HTTP 401 |

HTTP 401 只证明网络/TLS，不证明账号权限。原 bwrap 的 `--unshare-all`、`--share-net` 和所有挂载保留；`--share-net` 共享的是**启动器所在网络命名空间**，无法越过外层网络限制。resolver、CA bundle 保持相同。worker 看不到源工作区、GT 或 evaluator；auth 仍只在原路径 readonly mount，未复制/删除/重新登录。详情见 [network_diagnosis.json](../evidence/routing_repair/network_diagnosis.json) 和 `managed_network/host_network/` 原始证据。

因此当前证据支持 `OUTER_EXECUTION_NETWORK_BOUNDARY_CONFIRMED`。必要修正是经批准使用 host 网络启动现有 bwrap，不是扩展代理白名单。历史日志未记录网络 namespace，不能仅凭复现断言这是历史故障的唯一原因。

## CLI、登录与路由边界

同一内层隔离中 CLI 为 0.162.1，本地 login status 为 ChatGPT 登录。所有 CLI 配置来自原 `bridge.command()`，不改 provider/base_url/模型/工具开关，不读取用户 config/rules。版本或本地登录成功不能证明推理成功。

`debug models` 即使网络失败也可能 exit=0，静默输出内置目录。早期未辨识回退的证据仍保留在 `cli_managed_network/cli_host_network/`，不作为远程成功证据。随后在全新隔离目录内与 `debug models --bundled` 对照：

| 执行边界 | 原过滤环境 / 候选代理环境 | models 检查 |
|---|---|---|
| managed | 两者相同 | 11 项，等于 bundled：没有远程成功证据 |
| host | 两者相同 | 10 项，与 bundled 不同，包含 Astra：远程元数据证据 |

修正后的证据见 `cli_managed_verified/cli_host_verified/`。没有升级 CLI、重新生成凭证或换服务商。metadata 成功不能代替 workspace 路由与推理验收。

## 已授权真实 A 尝试与第二层阻塞

用户在本次修复中授权最多 1 次 S1 A 请求后，用 host 网络执行原 A 请求。完整产物保存于 [real_A_recovered/](../evidence/routing_repair/real_A_recovered/)；目录名不是成功标记。

结果为 `TimeoutError:MODEL_TIMEOUT`，30.10 秒；没有 JSON、没有 usage、独立评分 `NOT_SCORED`。events 有 `thread.started/turn.started`，未出现此前 routing discovery 重连错误，也没有 `turn.completed`；不能据此断言推理路由已经恢复。CLI runtime logs 数据库没有日志行。退出码被记录为 0，但 bridge 的 error 非空，评分器正确保留基础设施失败。

具体来源：实验 adapter 的 worker 总 deadline=90 秒；原 `infer_worker.py` 默认 mode=standard，执行 `min(timing_limits(mode)['request_timeout_s'], remaining_deadline)`；原 `timing.py` standard 的单次上限是 30 秒。`infer_started.json` 明确记录 `timeout_s=30, mode=standard`。原 bridge 在超时后 terminate CLI，因此这不是已经证实的服务端超时。详情见 [real_attempt_diagnosis.json](../evidence/routing_repair/real_attempt_diagnosis.json)。

实验 CLI 现已增加 `--timing-mode qualification`，复用生产已有 90 秒 profile，worker deadline=95 秒、launcher timeout=110 秒。默认 standard 行为保持不变；计时不投影到模型输入。生产 bridge、worker、timing、控制器、安全层及 GT 隔离源码未修改。测试验证两种模式的 request 与 model_parameters 完全一致，非法/无界 mode 被拒绝。

下一次 A 请求已准备到 `prepared_A_qualification/`，整个 payload 与原失败请求完全一致。**必须另获最多 1 次真实 A 授权才执行**；本次上一笔授权已耗尽。90 秒是否足够、是否能取得有效 JSON 尚未验证。不自动重试，也不启动 C。

## 实际验证过的命令

从修复 worktree 运行，输出目录必须全新；诊断不发模型生成请求。网络对照各运行过一次 managed 和一次经批准的 host 执行。普通 Ubuntu 终端直接使用宿主机网络；Codex managed 执行中，host 对照必须通过批准的 `require_escalated` 调用运行，不能靠脚本自行绕过外层边界。

```bash
cd /home/alex/astra_spatial_capability/routing-fix-v0
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
python3 -m unittest discover -s experiments/spatial_input_eval_v0/tests -v

/home/alex/astra/.venv/bin/python experiments/spatial_input_eval_v0/diagnostics/compare_network.py \
  --output /tmp/astra-routing-network-NEW
/home/alex/astra/.venv/bin/python experiments/spatial_input_eval_v0/diagnostics/compare_cli.py \
  --output /tmp/astra-routing-cli-NEW
python3 experiments/spatial_input_eval_v0/diagnostics/diagnose_network.py \
  --managed experiments/spatial_input_eval_v0/evidence/routing_repair/managed_network/comparison.json \
  --host experiments/spatial_input_eval_v0/evidence/routing_repair/host_network/comparison.json \
  --output /tmp/astra-routing-diagnosis-NEW.json
```

这次实际运行且失败的真实命令（不要自动重跑）：

```bash
/home/alex/astra/.venv/bin/python -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --conditions RGB_MULTI_VIEW --real --max-real-calls 1 \
  --output experiments/spatial_input_eval_v0/evidence/routing_repair/real_A_recovered
```

准备好的下一步命令（尚未执行，不算成功复现命令）：

```bash
/home/alex/astra/.venv/bin/python -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --conditions RGB_MULTI_VIEW --real --max-real-calls 1 --timing-mode qualification \
  --output experiments/spatial_input_eval_v0/evidence/routing_repair/real_A_qualification
```

测试为 29/29 PASS（23 项 V0、5 项网络诊断、1 项计时/输入不变回归），原始测试日志含早期 27/28 项及最终 29 项版本，全部保留。诊断和测试无生成消耗；真实启动 1 次、有效 JSON 0、A/C 对照 0。远端实际服务调用/内部重试及 token 数 UNKNOWN。原始失败产物、源码与请求的保护校验见 `integrity_review.json`。所有新增代码、早期证据、失败请求、准备输入及报告提交并推送；不推凭证或普通 runtime SQLite。
