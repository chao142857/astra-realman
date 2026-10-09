# 离线验收与未完成项

本轮真实模型调用0、硬件0、原生Codex子agent调用0、新SAPIEN回合0。仅离线OS进程/假执行器验收，不能据此宣称视觉决策、物理可靠性或真实并发提速。证据根：`/home/alex/astra-realman_ws/astra-research-adapters-evidence-20261009`。

| 项目 | 结果 / 实际覆盖 |
|---|---|
| 基线审查 | 原分支本地和origin均d7737dd，原树干净；336个基线跟踪文件已hash |
| Broker多角色 | semantic_e0/action/local_reground，实际不同图片/ROI/schema，冻结wire=实际prompt；原infer环境/worker/function复用 |
| 图片与schema路由 | 实际Node假CLI按`--image`读取图片计算hash并记录收到的role/schema hash；ROI有原图和裁剪hash、selected K，bbox绑定附件 |
| World Head | 真实独立bwrap进程，无scene/score/auth挂载；来源、时间、K/T/版本、粗不确定性及历史bbox失效检查 |
| H/K | H=8明确拆3+3+2，在假执行器完成K=8；每段新source与epoch；支持H=1/4/6/8，错长度拒绝 |
| 失效 | world_revision/epoch在段中变化时STOP；段间变化丢弃；gripper后余项丢弃；部分失败保留，异常结果K=null |
| Generic Task Evidence | 多对象/目标关联没有等价checker时unknown拒绝；不通过模型声明、label替换或省略旧检查放行 |
| 原Baseline | 旧infer/commit保留；旧平台18项与既有专项90项通过；物理/SDK/模型后端文件无改动；历史参考PASS原始证据57张RGB/原wire重新离线核对 |
| 原生Codex subagent | UNVERIFIED_DISABLED；仅独立接口门，未实现/验收真实父子传输驱动、图片路由或父子usage，不冒称已完成 |

## 测试记录

- `delivery_tests.log`：新增29项 + 原platform_v1 18项，共47项PASS，无跳过。
- `baseline_regression.log`：原platform_v1 18项 + 既有infer/预算/共享工程/抓取/requirements等90项，共108项PASS，无跳过。与上项有18项重叠，合计137个不同测试。
- `h8_delivery_demo/`：最终源码、独立研究子进程、原runner+owner、真实隔离假CLI进程，三角色3个attempt，H8分段采用。假分数FAIL固定值只用于防止误称物理PASS，见OFFLINE_ACCEPTANCE.json。
- `async_ea_demo_queue_fix/`：外部程序先发execute再依次提交E→A。两个真实OS假CLI进程与同一段假执行重叠约0.743s、0.749s，PID与实际单调时间在OFFLINE_ACCEPTANCE.json。最多1个模型在途；这不是原生父子模型调用，也不是真实模型性能。A原raw预测H8，物理采用K0：执行后原epoch过期，拒绝加载，无改source或重放。
- `original_reference_audit.json` / `reference_replay.log`：原工程完整抓放PASS记录的回放/hash/输入链核对。**本轮没有重跑参考物理评分**，不将旧PASS改称新代码物理PASS。
- `preservation_check.json`：392个旧平台证据文件零变化。仅3个已有文件做接线改动：platform_v1/client.py、owner.py、scripts/run_research_platform.py。原控制器、碰撞/接触阈值、SDK、infer_process、infer_worker、bridge、FullSlot和B/F代码不改。

## 失败与修复保留

`async_ea_demo/`原失败完整保留，状态FAIL、2个假attempt；未覆盖或重新分类。原因：同一管道读取中execute之后已入队的Broker请求未在运动检查点处理，E/A延后启动，示例对预期失效错误码的断言随之失败。修复只在原runner中提取允许的只读/提案/取消RPC；observe/execute/commit继续串行。`test_already_queued_proposals_drain_during_motion_without_nested_execute`与真实假进程重测覆盖该问题。

测试故意触发的API失败、解析错误、半截raw、cancel、deadline、单视角/旧bbox unknown、失配及部分执行均在各测试独立目录保存attempt/raw/process日志。初始测试/演示也保留，不筛掉失败。usage按原始对象存储，不相加output_tokens_details子项；无返回usage为null。

## 明确剩余缺口

1. 原生subagent当前是**拒绝执行的可选backend门**，不是已可用的真实parent/child驱动。必须在单独授权后先核对实际图片路由、父子ID/调用事件、usage、取消/超时及模型并发预算，之后才可实现/启用该transport。原工具关闭通道不会自动启用multi_agent。
2. 真实Astra在新Broker的动态角色/schema下未验收；本轮只证明原环境与infer函数接线。真实视觉判断和几何准确性没有新结论。
3. 泛化身份/目标关系、遮挡后身份延续没有等价任务checker；相关动作仍unknown/拒绝。当前LWH是粗几何worker契约与两种公共输入模式，不是完整3DGS或训练模型。worker可按同协议更换，模型权重/额外依赖挂载尚需独立配置与验收。
4. Async E/A传输可用；从旧epoch生成的全新A计划不会自动接续已完成动作。通用预测接续点采用、跨epoch有效性规则与研究调度策略不在此增量中，也没有用更宽安全门实现“成功异步”。
5. 本轮没有SAPIEN新物理回合；原完整参考任务只做历史链审计和离线契约回归。启用新接口后的物理研究验收需后续有界授权，不能把假执行器视为物理控制。
6. RealMan现场SDK、world/base/tool/TCP、夹爪传感及运动中STOP继续UNKNOWN。未连接实验室或硬件。

能力已经通过固定client/版本化RPC提供；研究模型、选图策略、记忆、何时re-ground和组合实验继续在新项目实现。没有新增GUI、数据库、研究框架或第五个研究方向。
