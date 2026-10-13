# Pilot 02 零生成验收（2026-10-13）

基线 `dc5891a`；实现分支 `codex/spatial-pilot02-dispatcher-20261013`。
本阶段真实生成请求 **0**，未创建真实授权文件，未接触生产 bridge 或硬件。

| 启动前检查 | 结果 | 证据 |
|---|---|---|
| 冻结输入、prompt、schema、RGB、Oracle 与原生产代码 | PASS | 全部 607 个封存文件 SHA256 一致，新增文件方式实现 |
| `task_policy` 完整传输与校验 | PASS | 20/20 输入；缺失、篡改、GT 注入均在派发前拒绝 |
| 原 HTTP/认证/超时/取消逻辑复用 | PASS | 私有模块加载原传输，无复制 HTTP 实现或共享全局修改 |
| 全部 A/C 协议 | PASS | 20 份输入、10 对；A/C 公共内容除 geometry 外相同 |
| Pilot 02 独立评分与重评分 | PASS | 所有归档结果与独立读取重评分一致；使用 `pilot02_contract.score()` |
| fixed / upright_free_yaw 正负对照 | PASS | 有效失败保留 0 分；替代可行朝向通过；倒置正 z 约束失败；不修正答案 |
| JSON、事件、return code、参数、传输门禁 | PASS | 非法/空输出、缺完成/重复完成/失败事件、错误码、参数/Code Mode 漂移均 NOT_SCORED |
| 403 / 409 / 超时 / 取消 | PASS | 不重试；取消确认不视为完成；未知结果停止 |
| 独立预算 ledger / 默认 dry-run | PASS | 请求前持久预留；无新授权不派发；最多 20；180 秒；单请求；不可替换授权 |
| 中断恢复 / 防重复 / 防并行 | PASS | 崩溃不退款、不重发；只从确认归档恢复下一项；重复 session 拒绝；主机独占锁 |
| 旧测试回归 | PASS | ubuntu-robot **111/111**，其中原有 **94/94**，新增 **17/17** |
| 新的真实生成授权 | 未满足 | 当前预算 0，必须另行获得最多 20 次授权 |
| 指定执行主机的生产 bridge / tunnel / token 配置 | 待启动前检查 | 本轮只使用临时模拟服务，未证明生产链路在线；禁止用 `/decide` 健康检查 |

**软件离线门禁已通过，具备申请 20 次新真实生成授权的条件；尚不具备立即执行真实批次的授权。** 正式启动还需要在指定单一主机确认原 Mac bridge 链路及该主机的认证路径。

## 记录

- 最终回归：`evidence/pilot02_dispatcher_acceptance_20261013/linux_full_tests_final.log`，111 项，22.593 秒。
- 最终模拟归档：`evidence/pilot02_runs/offline_acceptance_final_20261013/`。
- Mac 最终新增测试：`mac_new_tests_final.log`，17/17，10.899 秒；取回 Linux 归档后在 Mac 无网络独立重评分 92 项全部一致，见 `cross_host_archive_audit.json`。
- 最终验收：其中 `acceptance.json`，20 次有序模拟派发 + 72 项协议故障/正负对照，共 92 次 **fake HTTP** `/decide`，1 次非生成取消。
- 最终每项包含完整原始输出、events、传输回执、输入 SHA、模拟 usage、客户端耗时、约束评分及独立重评分。模拟 token 与分数不能作为 Astra 能力结果。
- `ledger.json` 中 `mode=OFFLINE_FIXTURE`，其 20 次预留为模拟预算；不能转换为真实批次。实际真实派发数为 0。
- 首轮 Linux 通过记录和 `offline_acceptance_20261013/` 也原样保留。随后增加原始回执/请求 ID/截止时间/归档路径检查，重新运行最终验收。首轮 ledger 绑定首轮源码哈希，不应用最终源码恢复，最终目录是本次交付的可重评分证据。
- `mac_new_tests_attempt01.log` 保留初次测试问题：Mac 临时目录 `/var` 与规范路径 `/private/var` 不一致，授权测试夹具失败；只修正了测试夹具的规范路径，未放宽授权匹配。

运行说明和未来真实命令见 `docs/PILOT02_DISPATCHER.md`。真实命令本轮未执行。任何新重现应使用独立输出目录，原 Pilot 01 和本次所有旧记录均不覆盖。
