# E1-B 离线验收记录 — 2026-10-08

结论：最小离线调度增量通过。**DELAYED_STUB_NOT_ASTRA**；未测试真实 Astra 异步收益，不是正式 E1 非劣或泛化结论。旧 M/S 只归档为 E1-A。

执行代码提交：`7b92fa8275aeb88d75863d36f2e4c591921ece06`，基于 `69aae84`。最终三次 SAPIEN 和八次协议 fixture 均记录该提交且启动时工作树干净。随后仅补此验收记录及报表对中断区间的统计，不改变执行代码。

## 最终 SAPIEN + 延迟 stub 验收

每次全新进程，seed2，既有资产/目标/速度/控制器/检查/三图/视频；stub 延迟0.8 s，单 worker。初始化不计入放置120 s预算。

| 条件 | stub 请求 | 初始化墙钟 / 物理 s | cold start s | 放置墙钟 / 物理 s | stub与动作重叠 s | 独立评分 | XY误差 mm |
|---|---:|---:|---:|---:|---:|---|---:|
| B0 / delayed-goal | 2 | 3.510 / 11.228 | 0.875 | 11.635 / 9.888 | 0.000 | PASS | 0.303230 |
| B1 / delayed-goal | 2 | 3.635 / 11.228 | 0.894 | 10.897 / 9.168 | 0.801 | PASS | 0.296281 |
| known-goal 完整计划 | 1 | 3.920 / 11.228 | 0.891 | 10.802 / 9.164 | 0.000 | PASS | 0.307145 |

三次动作+独立评分的物理时间均8.452 s；其余物理时间是保持等待。不是动作加速或放慢B1。三次序列均 `approach → release_pose → release → retract`，规范JSON SHA256：`402e7702aeb3a62c4517d80aa259d84efc4f4c08074ca4e271b009b9e8b5031e`。该 hash 使用新增 sha() 的 json.dumps(sort_keys=True, allow_nan=False) 编码，不能与其他JSON序列化 hash 直接比较。

这里只能确认指定 stub 延迟下的重叠机制，不能从单次墙钟差异推出真实模型速度优势。known-goal 强基线保留一次调用；delayed-goal 的双阶段任务消息并非原固定场景输入，旧 physics_paused 结果未进入表。

## 协议验收与回归

- 13项新增 unittest：B0/B1同节奏与真正重叠、接续采用、新鲜实际状态验证、目标/goal/plan/revision/join变化、执行失败、两种STOP、超时与晚到、重复提交、无候选保持、单slot/线程所有权、实际wire输入GT投影与附件哈希、输入准备消耗预算、原公共检查拒绝。
- 既有29项 sim_skills、4项 CLI环境、4项M/S预算账本：全部通过。合计50项。
- 八个持久化协议fixture：B0正常/B1正常PASS；deny和目标取消保持；注入执行失败FAIL；超时保持且不重试；外部STOP与worker STOP均STOPPED。以上是预期验收结果，不能把fixture PASS称为物理成功。
- 最终21个wire快照、63张附件验证通过；所有入口实测最大in-flight1、pending1。原目录/完整展开/目标知识与单位/frame/tool/revision/来源进入快照，expected_join明确标为预期。
- Node `v22.23.2`，Codex CLI `0.161.0`，版本/help preflight通过。launcher `/home/alex/.nvm/versions/node/v22.23.2/bin/codex`，Node同目录；使用既有环境构造函数。没有发送真实提示词或调用infer。
- 视频沿用1280×480、10fps H.264；三份视频均能解码。图示将评分独立标色，不把评分/保持算推理-动作重叠。

## 冻结与失败保留

冻结worktree `f7c8da1`、`3e7fcd5`、`1b5e184`、`69aae84` 均干净。新实现只添加文件，既有运行时/策略/物理代码零修改；56个资产哈希一致。首次模型失败118文件、通道成功93文件、M/S批次513文件，共724历史清单文件均哈希一致。

保留本轮早期三次SAPIEN和八次fixture开发记录，不与最终验收混合。最终运行前加入了更及时的worker STOP处理，早期结果不能冒称来自最终代码。首次单测因测试替身返回空env导致PATH KeyError，随后修复；原失败日志保留。沙箱内GPU只读枚举受限，获准主机执行后验证可用。首次Git提交缺身份未写入提交，随后沿用历史Codex本地身份完成，无全局配置改动。MESA旧核显驱动警告和matplotlib只读缓存警告原样留存/记录，不改依赖。

真实模型调用0、硬件调用0、subagent0。本轮所有任务运行均为离线stub。服务端身份/effort/内部重试未核验；不根据本地配置补为事实。

## 交付与后续预算

持久化代码：`/home/alex/astra-realman_ws/astra-realman-e1-async-20261008`。
证据：`/home/alex/astra-realman_ws/astra-e1-async-offline-delivery-20261008/ASTRA_E1_ASYNC_OFFLINE_20261008_v1`，最终表在 `final/REPORT.md`，时间轴 `final/timeline-verified.png` / `timeline.svg`，逐事件 `*/episode/timeline.jsonl`，实际command/raw候选/哈希在每个worker目录，异常索引 `local-failures.json`，全部文件含交付清单。

下一批建议严格按 [时间协议与预算](TIMING_AND_BUDGET.md)：5回合、最多9次Astra medium，单并发，每回合120s、单请求≤min(30s,剩余预算)。**本轮授权为0，后续预算尚未执行**。真实入口仍需将既有infer映射到此候选协议并离线审核；没有另造调用服务或启用真实请求开关。不扩B2、E2/E3/E4、双臂或多agent。
