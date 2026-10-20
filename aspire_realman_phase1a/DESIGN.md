# LiveSource 与 native 接入

`LiveSource.publish(camera, owner_id=...)` 接收单一采集 owner 已取得的完整样本；`read()` 在锁内返回一致副本，保留采集/接收时间，不更新时间戳、不读硬件、不加载 Replay。Snapshot 包含 `LIVE`、owner id、递增序列、角色/SDK serial、RGB uint8 H×W×3、aligned optical-Z depth float32 m、内参、设备帧号/时间域、host boot id+monotonic、接收 epoch。状态来源固定 `UNAVAILABLE_ARMS_POWERED_OFF`，canonical_states 为空。重复/倒退的 RGB 或 depth 帧号、角色映射变化、另一 owner、时钟域不匹配均拒绝。

现场旧 GUI 已于 Phase0.5 正常退出，本轮复查没有现存 owner。验收使用 `LabRGBDOwner` 作为唯一短期 owner，复用真实已部署 `RealSenseCamera` factory、原有 640×480 RGB30/depth15 profiles、`rs.align(color)` 和工厂 depth scale/intrinsics。LiveSource 和 MCP 消费方不开第二个 pipeline。RGB30/depth15 导致深度帧复用时，owner 丢弃重复 pair，不伪造新 RGB-D。锁只协调采用此协议的 owner；`fuser` 额外检查既有进程，第三方并发启动的竞态仍需现场保持唯一 owner 的操作约束。

不调用原驱动 `read_frame/read_align_frame` 的超时重启分支，而直接有界 `wait_for_frames`；异常保留最后帧但标记 owner failed/stale，不重启设备。未调用 set_option、曝光修改、硬件 reset、USB/固件/标定写入或 SDKReadOnly。

`LiveRealManAdapter` 扩展 Phase0.5 的只读拒绝实现，提供 native `monitor_snapshot`，真实图像可独立进入 session 缓存。`get_robot_state` / `get_observation` 明确抛出 unavailable，不调用历史 codec 构造假状态，也不把不完整对象塞进 native Observation。`build_live_runtime` 使用原生 CapApi、ToolRegistry、EmbeddedAgentRuntime、create_app/MCP；仅增加部署策略：空 home map、无 IK/planning/segmentation provider，并把所有 CAP 动作入口绑定到 native safety_interlock 返回。adapter 的 raw step/trajectory/gripper/Home/reset 仍各自拒绝。`step` 保留 StepResult，其他动作保留 ExecutionResult。

native MCP 的 `observe` 是 station camera monitor，不是成功取得完整 `cap_harness.contracts.Observation`。响应 metadata 明示 `observation_kind=CAMERA_MONITOR_ONLY`、`full_cap_observation_available=false`、缺失原因与两臂时间戳 null；state={}。MCP `cap_get_robot_state` 返回 isError。保留动作 schema 但请求返回 isError/safety_interlock，zero steps/no dispatch；物理执行能力字段 false，未将 RefusingIK/RefusingPlanner 当作 cuRobo 注册。

# 质量门禁

- **新鲜度**：同一 host boot 的 monotonic 计算接收帧龄；SDK 原始 RGB/depth `timestamp_domain.global_time` 才可与 host epoch 作有界比较。未知/hardware_clock 没有独立 clock model 时 exposure freshness 未验证，fail closed。global_time 表示 SDK 的主机相关时间，不能宣称硬同步。当前阈值为 1 s，未来时间容差 50 ms。
- **旧帧**：接收时间与设备时间分别保留，新的 receipt 不掩盖旧 device timestamp。两帧号必须各自严格递增；停止/异常 owner 立即 stale。native session 会按 age 重算 stale，因此对不可认证时间域/停止 owner 使用 `stale_after_ms=-1` 保留拒绝状态，不会在刷新缓存时恢复为 fresh。
- **对齐与深度**：RGB uint8、depth float32 m、尺寸一致、depth_to_color、正焦距有效内参为接入条件；实际对齐后的 depth 内参与 color 对比一致。有效像素仅定义为 finite 且 >0，不补洞、不滤掉失败样本。有效比例 ≥0.10 和同域时差 ≤50 ms 只是光学数据可检查的工程门槛，绝不是测距/定位准确度证书。
- **状态关联**：两臂时间戳、camera-arm skew 始终 null。没有真实 telemetry 即不能通过完整 Observation 门禁；本轮不实现 synthetic fallback 或读取机械臂端点。

# 坐标与单位

| 坐标/变换 | 本轮状态 |
|---|---|
| 桌面 color optical | 已从当前设备 profile 读取内参；+x右/+y下/+z前；RGB对齐后的 depth 为 optical-Z，单位m |
| 桌面 raw depth optical → color optical | 已读取当前设备工厂 rotation/translation（m），由 SDK 内部 align 使用；不是外部标定 |
| `027223021284` | USB descriptor serial，同一个 D435 的 sysfs 标识；SDK/calibration key 仍为 `346222072496` |
| 桌面/顶视 → 真实 Work/World | 历史文件存在，但当前安装与深度未复核；本轮不加载、不输出矩阵，geometry_eligible=false |
| 左/右腕 optical → Arm_Tip | 历史手眼估计资产保留；当前腕相机缺失，未独立复核，不启用 |
| 左基座、右基座、各自 Work | 两臂断电，本轮无当前状态、无当前 Work/Tool 指纹；历史证据不能充当实时值 |
| 左基座 ↔ 右基座 ↔ 公共 World | 缺少现场实测配准；null，无单位矩阵/仿真间距 fallback |
| Arm_Tip → 实际抓取 TCP | 两臂均未绑定当前实际夹持中心；null |

native SAM3 HTTP 的图像协议和官方 `Sam3Processor` 可复用；收到二维 mask 不等于取得 World 位置。当前 segmentation 未就绪，native MCP 不宣告 localize_object available。完整几何链路和 RM65/cuRobo 仍按 Phase0.5 readiness 清单处理，不引入任务专家。
