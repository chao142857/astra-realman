# Phase 1B 前的明确缺口

Phase 1A 已提供单桌面相机的真实 RGB-D → LiveSource → Native CAP monitor → EmbeddedAgentRuntime → 原生 MCP HTTP 链路。原生 `Observation` 还要求真实 `RobotState`；当前机械臂断电，不能构造完整对象。软件已显式拒绝这类查询。相机 monitor 的成功不是机器人观测闭环成功。

| 项目 | 现状与下一步 | 边界 |
|---|---|---|
| 桌面 D435 `346222072496` | 能短时采集；需现场确认当前安装、遮挡、深度孔洞与已知距离样本 | 全图非零深度比例只是可用性指标，不是测距误差；不使用历史外参承诺准确三维定位 |
| 左腕 `254522073676`、顶视 `344422071480`、右腕 `348522072063` | SDK 未枚举；现场接线/供电复查 | 不进行 USB reset、驱动/固件修改、serial 替换或外参猜测 |
| 两臂只读状态 | 本轮未连接 SDK；在后续明确现场授权、供电与安全条件满足后，只读读取 joint/endpoint/Work/Tool/错误/夹爪 telemetry | 不启动执行器、Home、夹爪、伺服；不能沿用 V17 状态充当当前值 |
| 机械臂时间戳 | 左右臂均为 null；后续每次读取记录 host monotonic 接收区间、控制器时间域及误差界 | 不跨不同设备时间域直接相减；USB 全局时间也不是曝光同步证明 |
| 左/右基座 → 公共 World | 缺少实测双基座配准；无默认矩阵 | 需要独立测量与 holdout；禁止单位矩阵和仿真双臂间距 |
| Work/Arm_Tip 与实际抓取 TCP | 历史 Work/Tool 定义有指纹；当前定义和两侧实际夹持中心尚需复核 | 本轮没有 binding、TCP 或 World 数值；历史端点不等于真实夹持中心 |
| 相机外参 | 历史左腕/右腕/三相机资产原样保留；当前桌面安装/深度未重新验证 | 工厂 depth→color 只用于相机内部对齐，不能当相机→World |
| 官方 SAM3 | 官方源码/独立依赖已安装，导入与CUDA基础运算通过；真实照片预检因权重缺失而BLOCKED，需用户提供已授权路径 | 不绕开 HF gate；模型推理性能只能在加载真实权重后报告 |
| SAM3依赖兼容 | decord0.6内部wheel标签cp36，pip check平台警告；3.12实际导入成功 | 不改wheel元数据；视频解码/跟踪未验收；模型PTX/Triton仍需真权重实测 |
| 原生 localize_object | 缺少完整真实状态与当前几何变换；SAM3 尚未加载 | 当前 MCP 不宣告 segmentation available，不生成假 mask 或 World 点 |
| RM65 双臂 / cuRobo | 继承 Phase0.5 model_requirements.json；URDF/meshes/关节顺序/限位/碰撞球/夹爪几何/实际 TCP/双基座仍待绑定 | 无 Mock IK/Planner 冒充后端；无 Panda fallback；无真实轨迹 dispatch |

建议顺序：先交付权重并完成封存 RGB 上的官方 SAM3 单图推理、记录冷/热耗时和峰值显存；再用同一 owner 的 snapshot 输入原生 SAM3 HTTP provider 做二维结果关联。并行处理缺失相机的物理接线。随后在后续授权范围内采集真实双臂只读状态并建立时序误差界，再独立实测 World、TCP、外参和深度，最后才研究完整 Observation/三维定位。任何运动阶段都需要新的明确授权，本分支没有 enable-motion 开关。
