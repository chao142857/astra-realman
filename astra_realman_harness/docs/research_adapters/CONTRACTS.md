# 版本化契约与职责

## 同一个owner与异步传输

旧物理owner、1–3动作execute、gripper末项新证据屏障、STOP/碰撞/关节/接触/−2mm阈值保持。新增ResearchAdapters是owner内组合对象；不是第二物理owner或运行框架。两个worker类型独立：至多1个模型请求、至多1个只读几何请求。所有模型角色与旧infer共享回合deadline与attempt上限。没有按E/A重置预算。

Client.call保留同步语义；begin返回RPC id，wait按id取结果并缓存乱序应答（单调用线程/事件循环接口，不声明线程安全）。owner在原运动step检查点处理Broker submit/poll/cancel、world poll/cancel、能力查询及Supervisor cancel；observe/execute/commit不嵌套。STOP仍使用原停止标志。阻塞原生规划期间没有硬实时服务保证。

模型/几何worker异步返回仅登记结果，不能调用scene或执行。外部研究程序负责E→A依赖、历史、选图与调度。物理执行权仅在owner。一次执行完成会增加epoch；提交期间epoch/revision失配则停止活动段并丢弃剩余预测，已执行部分保留。

## Broker：submit / poll / cancel

`broker_submit(request)`固定字段：backend、role、instruction、images、evidence_ids、world_id、output_schema、timeout_s。

- role = semantic_e0 / action / local_reground，backend = existing_codex_infer；native_codex_subagent单独门控拒绝。
- images为1..4个`{observation_id,camera,roi}`。ID必须已登记于本owner同episode；不接收任意路径/base64输入。历史图可引用但保留原时间/epoch。ROI为源图归一化xyxy，由策略选择并明确标`RESEARCH_REQUEST_NOT_GT`。保存原PNG和派生PNG哈希、整数裁剪框、原分辨率、输出尺寸、源K/T和扣除裁剪原点的selected_intrinsic；不生成“正确ROI”。
- evidence_ids最多16个，必须是既有实际raw输出形成的不可变记录。world_id必须是公开几何worker登记的WorldSnapshot ID；策略不能提交自称WorldSnapshot的任意坐标dict。
- schema是调用者的result schema。外层强制`binding`原样回显、非空合法`evidence_refs`、`result`。schema禁远程/递归引用；raw严格JSON解析与JSON Schema验证，不修格式，不重试，不回退。action只有再通过ActionChunkPlan验证才可load。
- 实际冻结wire/payload/附件交给原`infer_process.sandbox_command`→原`infer_worker`→原`bridge.infer`。Node/Codex环境、medium和工具关闭配置不改。预检在原runner创建scene之前完成。
- 生命周期保存PREPARING、STARTED、RETURNED、PARSING、READY/FAILED/CANCELLED，以及独立OS进程PREPARED/LAUNCHING/STARTED等记录；保留实际command、输入hash、raw/events/stderr/usage和时间。API、解析、启动、取消、超时均无自动重试；缺usage=null，嵌套usage不重复求和，未返回服务端身份/effort/内部重试=unknown。
- 原回合默认120s、允许显式≤300s；单模型请求≤min(90s,请求指定值,剩余回合时间)。旧infer调用和新Broker共享≤20显式attempt。fake默认1，测试才通过`--research-fake-attempts`明确增加。RPC/schema拒绝与启动失败都有审计；进入Broker PREPARING后即占attempt。0模型默认不启动provider。
- READY为数据，不是执行授权；最多一个未消费action结果。cancel后不可采用。真实provider不接受FAKE_MODEL_RAW证据或其派生WorldSnapshot。ENGINEERING_REFERENCE参数仍按原规则遮蔽；公开实测RGB/本体数据可读取，参考答案不进入Broker。

## World Head：公开数据与不确定性

`world_submit(observation_ids,evidence_ids,backend,reference_world_id)`，使用world_poll/world_cancel获取结果。最多8个按时间排序的合法历史观测，末项必须属于当前epoch。输入仅为公开RGB、原图hash、K/T、本体状态、采图时间和已登记语义region假设。输出校验原binding、实际时间/本体来源、粗估计字段/来源和不确定性，不允许声明task_identity_verified。

隔离worker仅挂载冻结input、worker代码和Python环境，无原scene、GT、score、宿主workspace、auth或网络。每次≤min(10s,剩余回合时间)，最多64次。替换几何实现通过WorldHead的operator侧worker_path接口：同冻结协议、记录代码SHA；无checkpoint写死或任意策略侧可执行路径。

- `legacy_rgb_rays_v1`复用原RGB颜色组件提取，用当前多视角射线给单红块/绿区粗位置。
- `bbox_rays_v1`消费semantic_e0/local_reground**实际raw**中的regions：entity_id、label、attachment_id、bbox、identity_status。bbox归一化坐标针对实际发送的附件，经ROI变换恢复原图坐标。不能引用未发送图片、把旧图bbox当当前状态，或把两个不同图区域中心当已验证同名点。
- 多视角必须来自同一当前观测；至少2视角、15°基线、正深度、残差≤15mm。退化/冲突、单视角、旧bbox、图像不健康、bbox在选定ROI边界被裁剪等返回unknown、point=null。coarse坐标只在对应点假设下成立；≥20mm的uncertainty_radius是启发式下限，不是校准置信界、正确抓取目标或碰撞裕度。几何输出不证明语义身份。

`WorldSnapshot`格式：version=`astra.world.public.v1`、world_id（内容hash）、world_revision、binding（episode、epoch、观测/evidence IDs、capture_times、calibration_hashes）、created_monotonic、state（WorldState）、provenance。所有记录不可变。普通publish增加registry revision；binding中的world_revision记录请求发起时基线，外层snapshot.world_revision是新发布版本。

有reference_world_id时返回`WorldCheck`，绑定新的实际观测/epoch和既有snapshot，**不增加world revision，也不修改原snapshot的版本/来源**。它为当前实测几何检查，不是把预期结果写成实测。任何其他publish造成revision改变，正在执行的原计划失效。

## ActionChunkPlan / Supervisor

schema由research_capabilities.plan_schema提供：version=`astra.action_chunk_plan.v1`；H∈{1,4,6,8}；恰好H个waypoints；world_id/world_revision、source_observation_id、execution_epoch、task_binding；semantics固定PREDICTED_WAYPOINTS_NOT_MEASURED。

waypoint为单个旧协议move_pose/gripper/hold，单位和frame完全沿用原动态pad-center xyz米+Link6 wxyz；不接受delta，不插值或偷偷修改目标。micro_chunks仅分组至多3项；遇gripper结束当前组。

- supervisor_from_broker只装载role=action原始result；修改raw计划、伪造MODEL_RAW来源、错WorldSnapshot或源观测/epoch均拒绝。supervisor_load允许新项目自行提出计划，明确标RESEARCH_PROGRAM；工程运行标ENGINEERING_REFERENCE，不能冒充模型输出。
- supervisor_step第一次拍新公开观测并提交WorldCheck；返回WAITING_WORLD。再次step才检查当前真实本体join、LWH结果、TaskEvidence、world revision和epoch，再调用**原Owner.execute**。原owner会再采图做RGB最低检查；move+gripper仍在夹爪实际执行前做原检查。不默认通过unknown。
- 每段绑定新的source_observation_id和当时execution_epoch。本计划已验证的成功执行只允许epoch恰好+1；并保存实际反馈作为下一段期望本体join。其他epoch/revision变化、STOP、取消、部分失败或结果未知均丢弃剩余计划，无自动重放。gripper后的剩余预测直接丢弃，必须新观测、新证据、新计划。
- H是预测长度；K_submitted是送给owner的段动作数；K_adopted是执行器返回已尝试项数（包含失败项）；K_completed是明确完成项数。意外backend异常时K_adopted=null，不能从空result推断全部未执行。每项保留原执行反馈、未执行余项和来源。
- supervisor状态只完成命令链，不宣称抓取/任务成功；独立GT评分仍只在关闭策略后由owner处理。

## Generic Task Evidence

输入绑定真实请求来源的entity/goal IDs、WorldSnapshot与当前WorldCheck；不接受模型一句“identity verified”作为真值。当前只有两个明确作用域：scene_only_v1只允许无对象断言的hold；legacy_red_green_v1对应既有声明单红块/绿区并要求当前粗几何与原owner全部检查。机器人join变化≥10mm/0.05rad拒绝；anchor世界/近工具相对变化>30mm拒绝。这些是额外检查，不替换原RGB/物理门。

多对象真实身份、目标关联、遮挡后的再识别、跨对象稳定性没有已验证等价checker。它们继续unknown/拒绝，不能通过改标签、省略requirements或generic profile映射到红/绿来放行。将来替换TaskEvidenceAdapter需要等价检查与定向回归；本轮没有实现研究身份记忆或调度算法。
