# 实际源码审查，2026-10-09

审查基线：d7737ddca2b28ab10a6550b686521fd100e46a5a。原工作树干净；git ls-remote核对origin/codex/research-platform-v1-20261009同哈希。origin=https://github.com/chao142857/astra-realman.git。相对d5757f2仅14个新增文件，924行，无原物理或模型后端改动。

| 实际代码 | 已有能力 | 阻断/薄增量 |
|---|---|---|
| platform_v1/owner.py::infer, commit | 单owner，旧B wire，三路当前图，空Memory，CandidateGate | 保留原路径；新research RPC组合到同owner |
| platform_v1/client.py::Client | 串行JSONL客户端，哈希PNG，Replay只读 | 增加独立submit/poll/cancel方法，submit返回后执行可与OS worker重叠 |
| full_pnp/slot.py | B/E/A固定schema投影与解析，单槽attempt账本 | 不强行复用固定role分支；新Broker复用更底层infer_process/infer_worker/bridge |
| full_pnp/infer_process.py, infer_worker.py | bwrap输入隔离、原Node环境、frozen hash、截止/取消、原始usage | 原文件不改；动态wire仍使用同worker payload契约 |
| scripts/codex_astra_mac_bridge.py | infer接受context/images/schema，最多4图，medium，关闭工具与multi_agent | 新Broker可用动态schema；原生subagent不能伪装为此工具关闭通道 |
| full_pnp/dependencies.py, requirements.py, rgb.py | 单红块/绿区几何/RGB最低检查；缺证据unknown | 泛化身份/目标关联不能等价；新TaskEvidence只增加约束，不替换或削弱owner检查 |
| full_pnp/backend.py::execute_chunk | 1–3动作，gripper末项前新状态/RGB检查，部分结果 | Supervisor H=1/4/6/8拆micro-chunk；gripper后放弃剩余预测，需新证据/计划 |
| legacy_model_bridge.py, grasp_control.py | 既有物理执行、STOP、碰撞、关节/接触、完整评分 | 原文件及安全阈值不改 |

官方文档核对：https://developers.openai.com/codex/multi-agent （本轮只读获取）。官方描述原生子agent及继承父权限，但该页面不足以证明当前CLI的指定图片到子调用路由和逐父子usage证据。原native后端必须单独验收真实parent/child IDs、图片哈希、raw/events、usage/重叠时间；本轮真实模型0，保持UNVERIFIED_DISABLED。不会通过解除原infer工具禁用、coroutine或两个fake进程宣称原生并发。

测试范围：离线单元/实际假进程、既有参考记录回放及原测试；不启动新的完整研究实验，不调用模型或硬件。研究策略（semantic规划、记忆更新、任务选图、何时re-ground、异步调度策略）继续由独立项目实现。此增量只提供输入输出/执行连接件。
