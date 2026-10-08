# B/E/A infer 接线离线验收

实现提交 `9b092e96655ce4b4b0551d36847eb70fe30fbfb2`；冻结 `4aa89a2` / `99ac311` 与所有旧结果保留。106 项回归 PASS（旧 88 + 新 18，18.568s）。真实模型、物理场景、硬件、实验室连接、coding subagent 均 **0**。不继承旧预算，本轮真实批次未启用。

已将 B/E/A 真实 raw 接入同一 FullSlot：准备前计 attempt，冻结输入，单在途/单候选，取消/晚到与原始 usage 账本。B/A 不合成动作、E 不合成选图/bbox；失败无格式修复、无 RGB stub 回退、无自动重试。原 bridge、动作/物理适配器、owner 检查、schema、RGB 检查、控制器和目标文件 hash 均与冻结版本一致。

真实 CLI 只执行 version/help，隔离 worker 内预检 PASS：launcher `/home/alex/.nvm/versions/node/v22.23.2/bin/codex`；解析脚本 `.../lib/node_modules/@openai/codex/bin/codex.js`；node `.../bin/node` = `v22.23.2`；Codex `0.161.0`。没有发送提示词。

| 保留样例（全是假进程/假 backend） | attempt/角色 | 终态 | 冻结/实际 infer 输入检查 | 审计 |
|---|---|---|---|---|
| B-finish | 1 / B | READY → finish | PASS / PASS | 完整 |
| F-E-A-finish | 2 / E,A | READY → finish | PASS / PASS | 完整 |
| E-malformed-no-A | 1 / E | PARSE_FAILED，未启动 A | PASS / PASS | 完整 |
| B-partial-timeout | 1 / B | CANCELLED，raw 部分输出保留 | PASS / PASS | 完整 |
| B-API-failure | 1 / B | PARSE_FAILED，CLI exit17 | PASS / PASS | 完整 |

这些 finish 仅为生命周期夹具终点；fake score、tick 时间不是真实物理评分/时间。未扩大 stub 物理验收，不证明 Astra 视觉决策能力或异步提速。首次样例目录的五个夹具路径断言失败也保留；见 [开发失败说明](/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008/DEVELOPMENT_FAILURES.md)。

审计证据：[总记录](/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008/ACCEPTANCE.json)、[106项回归](/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008/final-106-regressions.log)、[原始失败/部分输出](/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008/fake-lifecycle-v2/B-partial-timeout/wire_audit.json)、[E→A raw依赖](/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008/fake-lifecycle-v2/F-E-A-finish/wire_audit.json)。全部证据位于 `/home/alex/astra-realman_ws/astra-full-pnp-infer-evidence-20261008`，附 SHA256SUMS。

未来唯一配对入口及准确命令见 [INFER_WORKER_WIRING.md](INFER_WORKER_WIRING.md)。必须用户另行显式启用；固定 B/F 各1回合、300秒/回合、20 attempts/回合、总40、单请求≤min(30秒,剩余预算)。全部角色/失败占额度，合法STOP和失败保留，不补跑；基础设施/协议/执行异常停止后续组。服务端身份、effort、内部重试仍 unknown；真实 API、认证刷新与实际 B/F 闭环结果均待核验。
