# 真实采集与 MCP 验收

最终原始证据在 yanglab：`/home/tongji/alex/aspire_realman_phase1a_20261020/evidence/live-final/`。`report.json` 是完整逐帧报告，first/last 包含 RGB PNG、aligned Z16.npy、aligned depth-m.npy 和 snapshot.json。仓库 `evidence/live_capture_summary.json` 为派生质量统计和选定 MCP 响应，明确不是全量原始归档；其中保存原始报告和每份保留资产的路径、大小与 SHA256。没有将图像/深度/完整日志跨主机复制或推送。

| 指标 | 最终实测 |
|---|---|
| 物理设备 | Intel RealSense D435，SDK `346222072496`，固件5.16.0.1，USB3.2 |
| 模式 | 640×480 RGB8 30Hz / Z16 depth15Hz；沿用已有驱动默认 profile |
| 数据 | 84组严格递增 RGB-D，5.5037 s；配对交付间隔中位数66.71ms |
| 时间域 | RGB/depth均为SDK `timestamp_domain.global_time`；host boot/monotonic独立记录 |
| 接收/最老设备帧龄（quality计算时） | 中位44.69ms，P95 50.12ms，最大70.87ms；84/84满足1s门槛 |
| RGB/depth时间差 | 中位3.42ms，P95 5.02ms，最大35.64ms；非曝光硬同步证明 |
| 全图有效深度比例 | 最小43.21%，中位46.03%，最大46.68%；其余主要为0，未补洞 |
| 中央宽高各一半ROI有效比例 | 首帧63.41%，末帧66.95%；也有明显空洞 |
| 有效深度单位 | 当前设备depth scale 0.0010000000474974513m/Z16；保存float32m与原始Z16 |
| current World/TCP | 全部null，geometry_eligible=false；未使用历史外参作准确性结论 |
| 机械臂 | 没有SDK连接，状态与时间戳不可用，没有合成替代 |
| 退出后 | owner closed，最后帧stale=true，/dev/video0..5无占用 |

有效比例、分位数及ROI统计描述当前场景，不能代替已知距离靶标、外参 holdout 或三维定位误差实测。相机工厂内参和内部对齐已读取，当前安装和外部几何仍未认证。

MCP 使用原生 `server.create_app`、Streamable HTTP manager 和 MCP ClientSession，在127.0.0.1临时端口真实HTTP连接；没有启动LLM Agent。完成 initialize、tools/list、get_capability_graph、三次observe、状态查询及动作拒绝。observe均包含一个真实image content，state={}，相机 metadata 明示 CAMERA_MONITOR_ONLY 与完整 Observation 不可用。状态查询isError；动作请求isError/safety_interlock、steps_executed=0、dispatch_attempted=false。工具schema中没有cap_move_to_pose或cap_localize_object；IK/planning/segmentation未配置，Mock IK/Planner available=false。

程序测试中的“Home”仅调用原生MCP Home schema验证拒绝；其第一个open_gripper已在CAP interlock处结束，没有机械臂连接、夹爪动作、Home或运动。raw adapter与CAP边界均无实际transport。解释器的audit hook拒绝任何非loopback socket.connect，且硬件模块检查没有加载RealMan SDK。

初次采集 `live-01` 已保留原始失败判定：pyrealsense2实际时间域字符串带 `timestamp_domain.` 前缀，最初门禁不识别，全部fail-closed stale；没有把它报告为fresh。修正准确枚举值后，`live-02`及最终采集通过。三次短时pipeline均已释放；没有reset/retry硬件。最终报告中的software_sha256锁定实测当时源码，后续仅整理错误文字、保留step的原生返回类型及软件回归，不重新解释旧数据。

独立软件回归只覆盖必要边界：重复帧/错误owner和serial拒绝、旧exposure被新receipt掩盖、未知时间域、无效深度/过大RGB-D时差、停止owner仍stale、无状态/规划fallback，以及StepResult/安全拒绝类型。Mac和yanglab运行结果见轻量JSON；这些注入fixture明确不是live证据。ASPIRE的71份runtime源码哈希仍与Phase0.5锁一致，历史Replay/Phase0.5源码没有改动。

本轮结束后重新只读比对V17成功、V17失败、V19三份封存launch_manifest及其部署源文件：每份371/371相符。`evidence/preservation.json`记录具体范围；没有声称重新哈希所有历史图像或完整日志。旧GUI未重启，日志/配置/归档未修改。
