# 审阅修复与实现覆盖（独立增量）

基于`8e4f815`，保留`3182e95`和全部旧结果。本轮真实请求/硬件0，旧40次及其它额度均不继承。只修共同owner检查、夹爪边界、失败账本和12-chunk边界；不改变B/F研究条件、动作schema、控制器、物理参数、相机或速度。

| 能力 | 实际实现/边界 |
|---|---|
| 共同运动最低依赖 | `dependencies.py`按当前RGB+标定+本体测量推导，模型只能追加条件。空手普通接近要求object_static；可能携物运动要求goal_static、object_near_tool及物体/工具相对向量变化≤30mm。物体可随工具运动。 |
| 有界上撤/微小运动 | 上升1–150mm、xy≤10mm、转角≤0.05rad要求当前对象可核验，允许对象/目标变化；≤1mm/0.005rad微小移动保留scene_healthy与原控制器检查。没有统一要求所有move object_static。 |
| 空手证据 | 当前唯一红色组件、至少2个已标定视角，视线基线≥15°、正深度、交线残差≤15mm。对象/指垫中心距离>90mm为任务对象分离证据；≤60mm只判可能携物，60–90mm或不可辨为unknown。此三角测量只出检查谓词/相对量，**不生成动作坐标**；只适用于声明的单对象工程场景，不是接触或通用空手真值。 |
| 开合夹爪 | 目标master与实测差≤0.005rad为no-op，直接跳过物理夹爪和legacy状态变化。明确空手可预抓开爪；可能持物的开爪要求goal_static、object_near_tool、object_at_goal；unknown保持/拒绝。关闭要求object_static。合理开爪不靠prompt禁令处理。 |
| move+gripper | 合法chunk仍允许。既有dispatch先执行prefix；夹爪前owner实际重采RGB/本体并核验10mm/0.05rad接续、最低依赖和模型附加条件，再独立dispatch最后夹爪。失败保留prefix结果，夹爪及余项不执行；无需新增模型请求。新source/commit/边界观测分列，不改旧观测号。 |
| 失败/取消账本 | 每attempt在准备前落盘；PREPARING/PREPARED、LAUNCHING/STARTED、RETURNED、PARSING/PARSED/失败，以及候选提交/采用/丢弃分别有时刻。原stdout/stderr、非零退出、截断JSON、缺candidate、超时/取消均保留；usage未知为null，不重复相加子项。失败审计完成不等于任务成功。 |
| 历史的真实内容 | B/F均为**最近5条已终结执行事件**（完整成功或明确失败/部分执行），F另保留**最近8条来源E假设**。本次增加失败prefix/未执行项记录；after未采集时为null，不能伪造完成观测。成功、失败/部分、attempted及no-op不混写成完整执行。 |
| 当前错误保留 | 可投影最后一条失败为unresolved_error；**没有错误解决状态机**，不会声称已按事件重要性选择/清除问题。当前执行故障停止回合。 |
| 尚未实现的记忆策略 | 无事件重要性排序、语义检索、对象级最后可见关键帧库、长期身份跟踪、证据压缩/摘要、遗忘优化或恢复策略。旧图只是最近动作前fixed图；E历史假设始终未确认。不能称为已完成设计中的全部事件优先/最后可见能力。 |
| E调用与复用 | 各自计数；保留E原raw/hash。旧bbox只是历史框，owner RGB重定位信息另列，不冒充新的E输出；相机运动、unknown、gripper屏障使复用失效。当前启发式stub无真实视觉能力证明。 |
| raw到提案 | `wire.parse_actual_raw/parse_bridge_record`严格校验并原样返回B/A动作或E选图/bbox；API/退出/解析错误均报错，**没有RGB动作stub回退**。`check_full_pnp_raw.py`仅准备文件、复用既有CLI环境/command并核验提供的actual raw，可选version/help预检；没有infer调用。 |
| 12-chunk上限 | 允许第12个动作chunk，禁止第13个进入物理执行；第12个完成后observe/finish/stop仍可合法处理，但仍受共同时间、请求和重观测上限约束。 |

实际离线入口`run_full_pnp_offline.py`：默认完整回合120s，可配置(0,300]s；单请求(0,30]s且≤剩余时间；所有角色attempt默认32、可配置1–64（准备/启动失败同样占attempt），实际进程启动数另记；最多12个动作chunk、每chunk 1–3动作、单次hold≤2s、最多2次新观测重提；全局1个在途worker、1个未来候选。原legacy夹爪抓取尝试上限2和底层检查保留。以上是**离线能力上限，不是真实调用授权**。

真实worker生命周期接线仍未启用；待核验入口`scripts/check_full_pnp_raw.py --input-only FROZEN_INPUT --bridge-record ACTUAL_RESULT --output NEW_DIR [--preflight]`。无raw时仅准备输入，不生成候选；有raw时解析原文，不执行动作。真实取消/预算/隔离和API回包仍待另授权前核验，本轮不发送请求，不自动开始新批次。
