# 最小适配层与原生ASPIRE接入

## 接口放置

保持调用链：原生Agent/Skills → 原生MCP `CapMcpBridge` → 同一个 `EmbeddedAgentRuntime` / `CapApi` → **独立RealManAdapter** → 既有观测owner与通用执行worker。新adapter不负责高层任务决策。Agent没有shell/SDK旁路；本轮offline包完全不构造硬件链路。

以下分清原生合同和本轮草案，避免把能返回JSON当成已完成原生集成：`offline.py` 是metadata replay，因共同坐标/TCP缺失，故意返回带 `native_robot_state_ready=false` 的draft；不能直接作为CAP EnvironmentAdapter。将来typed adapter的输入/输出与CAP严格相同；额外来源/质量信息通过版本化observation envelope、runtime cache与diagnostics保留，不能静默丢弃。

## 六个接口合同

| 接口与输入 | 目标原生输出 | 单位、坐标与来源 | Phase0边界 |
|---|---|---|---|
| `get_observation(camera_names=None)`（CAP层可筛camera） | `Observation(cameras,robot_state,task_context,timestamp_s)`；camera=`CameraObservation(rgb,depth_m,intrinsics,frame,camera_pose,timestamp_s)` | RGB8 H×W×3，aligned optical-Z depth m，K对应对齐color平面；`frame`是真实serial optical，`camera_pose`为已绑定parent中的光学pose。来源为既有单一producer缓存/封存RGB-D | 返回历史四路RGB引用及各时戳，不打开引用路径或video；不假装有depth数组/实时帧。未来质量不足或serial不匹配的camera只能展示RGB，不参与metric scene |
| `get_robot_state()` | `RobotState`：per-arm joints/velocity、EEF poses、gripper、joint_names、同一base_frame、embodiment、timestamp | joint deg→rad一次，xyz m保持，RPY rad→WXYZ；EEF目标须明确是物理TCP还是Arm_Tip。来源SDK原始state/work/tool/RM-plus，带before/after帧指纹和接收时间 | draft保留两臂各自frame和原UNKNOWN；velocity缺失为null+valid=false；共同base/TCP未知则不构造假原生RobotState。CAP当前不支持velocity validity，需要保留旁路元数据/显式扩展 |
| `localize_object(query,*,camera_name=None,target_frame=None)` | `LocalizationResult(ok,geometry,segmentation,point_cloud,error)` | **属于CapApi，不是EnvironmentAdapter方法**。原生同一份Observation→SAM3 mask→mask_to_point_cloud→estimate_geometry。target_frame默认state.base_frame；光学反投影需要真实aligned depth/K/T | 本轮返回明确不可定位，无SAM3/真实几何。未来无可用深度、外参/姿态过期、未知frame或质量不达标须拒绝，不生成单位阵、不跨未标定双基座 |
| `move_to_pose(target_pose,tolerance=0.01,max_steps=120,*,arm='primary',strategy=None)` | `ExecutionResult`，含原始error、steps、final_observation、final_errors与diagnostics | **属于CapApi**，pose绝对position m＋frame＋WXYZ或`rpy_deg`二选一；ASPIRE输入RPY是deg，SDK是rad。strategy选择通用IK/规划；内部`adapter.execute_trajectory`负责派发合同 | draft第一行拒绝，即使payload异常也不触发规划/读取。未来 `T_W_E_target=T_W_G_target @ inverse(T_E_G)`；再按真实base/work转换。不把绝对pose当增量，或重算为另一目标 |
| `move_synchronized(targets,tolerance=0.01,max_steps=120,strategy=None)` | `ExecutionResult`；规划产生`SynchronizedTrajectory`同dt、同waypoint数、两臂expected_start | **属于CapApi**。targets每臂为Pose或joint rad数组；共同W、双臂碰撞模型与真实同步执行能力均必须成立；pose tolerance m，joint tolerance rad，不混单位 | draft无条件拒绝。现两线程同时阻塞RPC不满足共享control tick；未来需有经实测的共同时间表/偏差界与失败/中止语义，不支持时显式UNSUPPORTED，不能悄悄串行冒充同步 |
| `set_gripper(position,*,arm='primary')` | `ExecutionResult`；返回实测开度/原始telemetry、SDK应答及未知接触状态 | CAP与adapter都有此接口；normalized0闭/1开→现场整数0..1000，编码是开度指令，不等于毫米/力。只显式gripper调用改变目标 | draft无条件SAFETY_INTERLOCK。真实实现区分command accepted、实际到位、力控停止、稳定持物；接触/持物不能仅由pos/current/return0判成功 |

执行结果应保留：operation id、源observation id/哈希、命令原值、frame/calibration fingerprint、派发前状态、实际派发通道/时间、SDK原返回、after实测、时间/跟踪误差、硬件动作计数、错误/未知状态。超时/断连之后结果未知不能自动重试；同operation id不能再次发命令。`commands_sent=0` 由本包无transport的实现及测试佐证，不是现场控制器遥测断言。

额外必须封锁的EnvironmentAdapter入口是 `step`、`execute_trajectory`、`set_grippers`、`reset`，以及CAP/程序层 `go_home`。本轮全部无条件拒绝；不存在allow-motion配置开关。未来真实构造函数也不得隐式Home/夹爪/清错/使能。`close`只释放自己资源，不停止旧服务；monitor从同一缓存读取，不新建机器人或相机owner。

## 固定上游审读结果

- [`CapApi`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/src/cap_harness/api.py)：构造时可能读state并记作home；无需实际home即可构造，但真实基线不应把任意当前姿态当已验收Home。三项高层接口保留，provider通过构造器注入。默认`_planning_context`会退回Panda/dual-Panda与identity base，这条fallback对RealMan必须被显式真实context截断；本轮不进入它。
- [`EmbeddedAgentRuntime`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/src/cap_harness/agent/embedded.py)：只包装持久`LiveAgentSession`，caller拥有env。session创建monitor线程，默认idle2Hz/active5Hz；真实接入必须读owner cache，不能每次monitor新建SDK/pipeline。job接收不等于执行完成；沿用原生terminal反馈。
- [`agent/server.py`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/src/cap_harness/agent/server.py)：`create_app(session)`挂载`/mcp`、`/health`、`/steer`可直接复用；`build_yam_runtime`则硬绑定YamRealAdapter/RuntimeControl/LiveYamAdapter。新建`build_realman_runtime`，不要调用YAM station factory以获取相机或CAN服务。CLI main默认会构造station与kinematics，不适合作本轮只读启动入口。
- [`agent/mcp.py`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/src/cap_harness/agent/mcp.py)：原生StreamableHTTP和allowlist复用；direct工具为`cap_get_robot_state`、`cap_localize_object`、`cap_move_to_joints`、`cap_move_to_pose`、`cap_move_synchronized`、`cap_set_gripper`等。`get_observation`主要经`observe`呈现。无segmentation/IK provider时相应工具会隐藏。YAM controller metadata硬编码allowlist可保留不暴露，或另作通用metadata扩展，不伪造YAM身份。
- [`YamRealAdapter`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/src/cap_harness/yam_real/adapter.py)：可借鉴gate、operation/recording/result设计；底层`YamActionBatch`、Portal/CAN、单位/codec/hold/home/control loop均为YAM专属。`get_planning_context`的identity是因其URDF已内置0.62m几何，并非通用标定策略；对RealMan不能照抄。
- `contracts.py`目前`JOINT_DIMENSIONS`仅behavior/libero/robosuite/yam_real，RealMan未注册会拒绝；RobotState强制所有EEF共享base_frame。原生核心测试实际复现这两项拒绝，说明不能通过一个鸭子类型类完成正确六轴接入。
- [`start_system2_agent.sh`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/scripts/start_system2_agent.sh)：motion-enabled启动提示会要求先Home，原生Home程序还会先开左右夹爪。即使只想测试Agent也不能在本阶段使用该选项；本轮整个启动脚本均未运行。

## 原生MCP、SAM3、cuRobo复用方案

保留CAP的工具名、pose schema、job/steer/terminal图片回执及程序allowlist。Phase0不提供可对外启用的MCP服务器，后续应先在纯Replay运行时检查schema与wire，再经已有owner接入只读模式；不能只依赖工具隐藏来挡动作，adapter/dispatcher还须独立拒绝。

SAM3复用原生`Sam3Provider.segment_text`，只产生mask和置信度。几何仍由CAP对同一Observation反投影；当前V17RGB日志无法替代RGB-D。provider weights和许可/网络访问需要后续准备；现有RTX3060上的实际显存/延迟未验，不凭上游大GPU profile承诺可用。

cuRobo复用`CuRoboProvider`、`/ik`、`/plan`、`/plan_synchronized`与native `MotionStrategy`。服务`BaseRequest.model`目前Literal只有panda/dual_panda/yam_real，维度/关节校验也有YAM专属分支；需新增真实RM65双臂model注册、12关节顺序、限位、真实装配URDF/SRDF/碰撞球、TCP link、实际`T_W_base`及gripper碰撞几何。固定关节若已把base变换编码到URDF，则context中同一模型坐标的identity只能在该已实测绑定下使用，不能拿来填缺失标定，也不能重复应用base偏移。

优先`curobo-integrated`等通用规划服务，而不是直接使用原生默认`mink`的YAM模型；不能关闭碰撞检查强推计划。ASPIRE的规划场景会跳过不在base frame中的相机，可延续“RGB展示/metric几何资格分离”的思想；用显式资格表剔除坏深度，而不是改假深度来凑合同。

**最小必要代码改动清单（后续，未实施）**：注册realman六轴合同；新adapter/codec/runtime工厂与校准资格缓存；cuRobo model/service joint validation扩展；必要的通用metadata expose。Agent、Prompt主体、Skills机制、CAP高层算法和原生MCP transport保持；硬件能力差异通过明确能力与拒绝结果表达，不添加任务特定专家控制器。
