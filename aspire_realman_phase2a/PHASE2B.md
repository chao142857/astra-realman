# Phase 2B：本体 GPU 正向闭环已通过，完整装配仍阻塞

基线 `02efb6026d05e9e0a58a2c69b2abf25aaf2f142a`，ASPIRE `fa00f0e`，
cuRobo `a35a708`。复用 Phase 2A 目录、独立环境、原 mesh 和 GPU 缓存，无新增依赖下载。
本阶段没有机器人连接、相机启动、SDK 导入、物理派发或任务模型执行。

| 验收项 | 实际结果 |
|---|---|
| 原始完整装配 | 原 2,958 球与碰撞策略保留，球包络自碰撞仍存在；不记完整基线 PASS |
| 几何根因 | 原始 STL 三角面、同一 URDF FK、完整 BVH/SAT 面相交检查；球包络重叠不等于源 mesh 相交 |
| 源数据能否支持几何修正 | 未发现可由原始资产直接证明的 URDF 变换错误；未修正、未移动安装位置、未缩球或新增忽略对 |
| ARM_ONLY GPU | 原厂本体关节/mesh 与装配本体逐项匹配；12 关节、1,416 原本体球、501,264 跨臂球对；真实 FK、IK、单臂 joint/pose、双臂 pose 规划通过 |
| 原生 CAP/MCP → Stub | 三个运动工具的真实 GPU 轨迹经重采样后 GPU 检查、限位、速度、离散加速度/jerk 检查进入 Stub，回读成功 |
| 反例 | GPU IK 对 100 m 目标返回 422 unreachable；重合双臂由实际 CUDA kernel 检出 15,024 个跨臂相交球对，同臂相交为零，CAP 拒绝且 Stub tick=0；场景包围障碍反例的 scene term 为正 |
| 会话取消 | 新增通用原生 cancel_job → operation_controller → Stub abort；真实 27 waypoint 轨迹中段只执行 8 tick，确认后零新增 tick，终态 cancelled；后续动作拒绝且零新增 Provider 请求 |
| 执行故障 | 同一真实 GPU 轨迹用于超时、控制器错误/异常、反馈错误/不一致、重复 ID、起点变化、无双臂时序能力验收，全部按合同拒绝或停止 |

以上所有成功均限定为 **ARM_ONLY_DIAGNOSTIC + SYNTHETIC 基座 + Stub**。
不包含完整夹爪、腕相机、实际抓取 TCP 或现场障碍；虚拟共同 tick 不证明真实双臂同步。
峰值 allocated=8,250,578,432 B，reserved=9,040,822,272 B，RTX 3060 12 GB。
11 项 CPU 回归通过；它们不代替实际 GPU/MCP 证据。

## 几何证据

`phase2b_geometry.py` 只读取冻结模型和原 STL，分别报告原始 link 球心/半径、
base/link 与参考 frame 的完整矩阵、球相交量、原 mesh 三角面相交、包含关系和三视图。
未用 convex hull 冒充原 mesh，也未用球相交推断实体穿透深度。
算法保留分离盒、交叉盒和共面接触盒的诊断结果；数值容差 1e-8 m。

- `Link5` 球 20：局部中心 `[0,-0.125,0]` m，r=0.021650635094611 m。
  `ctag_base_link` 球 227：局部中心 `[0,0,0]`，r=0.010392304845413 m。
  两球在同一 FK 下相距约 0.027 m，重叠 **5.04294 mm**。
  所查 joint6=-π、-π/2、0、π/2、π 的结果相同；这个夹爪球心位于 joint6 旋转轴上，
  转动 joint6 不会消除此关键球对重叠。原 mesh 包围盒间隔至少 **36.99987 mm**，
  不存在源 mesh 面相交；夹爪基座 STL 非闭合，不能对其宣称完整实体包含判定。
- 左右 `_1_Link / _2_Link`：遵循原厂 mimic 关系，master=0、-0.455、-0.91 rad，
  球重叠分别约 **15.48306、14.86144、15.53076 mm**；所有所查原 mesh 面均无相交，
  闭合网格逐连通分量的包含检查也未发现嵌套。
- 关键 link 的独立 mesh FK 对实际 cuRobo GPU 球心最大误差 **1.23e-7 m**，
  原 buffer 后球半径误差小于 **3.89e-10 m**，没有靠不同 FK 制造 mesh/球差异。

这将名义模型的阻塞定位到过度包络的碰撞球，而不是已证明的 STL 穿透或 URDF 安装错误。
原始资产仍只写临时 8 mm flange adapter；缺少现场装配 CAD/尺寸与碰撞覆盖验收，
因此保留 **BLOCKED_PHYSICAL_GEOMETRY_EVIDENCE**。此前内部接触排除提案保持关闭。

## 原生取消与反馈修复

固定 ASPIRE 本来只有 steering 和 close，没有公开 cancel-job API。
`patches/0003-native-session-cancel.patch` 只增加通用会话取消、MCP `cancel_job(job_id)`
与 HTTP `POST /jobs/{job_id}/cancel`，要求精确的活动 job ID 和支持取消的 controller。
不支持的 controller 返回不可用；错误/已结束 ID 被拒绝。没有修改 Agent、Prompt、Skills 或任务决策。
取消确认只表示已提交 cooperative abort；终态由执行线程的真实结果反馈确定。
本轮已验收 MCP 主动 cancel_job；不把断开 HTTP 或客户端取消等待自动等同于执行中止。

首次中段取消检查没有进入暂停点，原始失败日志保留。排查发现：CAP 缓存请求开度
0.4329，V17 wire=432、Stub 回读 0.432，旧浮点相等预检把它视为夹爪变化。
现在只接受有效 wire 完全一致的 hold，wire 432→433 仍拒绝；臂轨迹不派发夹爪命令。
没有通过放宽运动误差、关闭碰撞或更换验收目标掩盖该错误。

`control.py` 通过原有 operation_controller 扩展点连接取消，abort 与 Stub packet 用锁串行化。
取消后保持 latch，不自动复位；下一动作不进入规划器。正常关闭同样唤醒并停止本进程 Stub。
不存在可启用的真实 SDK transport 或 allow-motion 模式。

## 复现与原始证据

执行目录：`/home/tongji/alex/aspire_realman_phase2a_20261020`。
在已经准备好的同一环境，最短全阶段复现（输出目录必须全新）：

```bash
ssh yanglab 'cd /home/tongji/alex/aspire_realman_phase2a_20261020 && bash aspire_realman_phase2a/tools/reproduce_phase2b.sh evidence/phase2b/review-01'
```

入口不下载、不应用补丁、不连接设备。`prepare_native_cancel.py` 为显式准备步骤，
只接受三个 pristine 固定上游文件的已知 SHA；重复应用会拒绝。ARM_ONLY 构建命令保存在
`tools/build_arm_only.py` 的参数合同中，输入保持原 vendor、planning.urdf、curobo.yml。
原 Phase 2A `reproduce.sh` 仍使用完整装配，预期继续返回模型阻塞。

完整原始证据均留在执行主机 `evidence/phase2b/`：

- `geometry-source-01/`：11 组完整矩阵/球对/三角面结果和 PNG 三视图。
- `geometry-review-01/`：逐连通分量包含检查与实际 GPU FK 对照。
- `native-arm-only-first/`：首次成功的原生 MCP wire、GPU 轨迹、Stub ledgers。
- `native-arm-only-controls-01/` 与同名 `.log`：首次取消验收失败、异常栈和已成功项目。
- `native-arm-only-controls-02/`：最终原生调用、真实轨迹 NPZ、逐 tick 回读、cancel receipt、故障逐案 claim/result。
- `gpu-arm-only-cross-negative/`：实际 CUDA 跨臂球对 NPY、GPU gate 拒绝及零 Stub tick。
- `stub-regression-02/` 与同名 `.log`：11 项 CPU 合同回归原始结果。

仓库只保存必要源码、三个派生摘要及最后的 SHA256 证据索引，不推原 mesh、大日志、NPZ 或图像。
索引为 `evidence/phase2b/remote-evidence-index.json`，对应主机 `evidence/phase2b-delivery-index.json`，
SHA256 `cdd82de9cd4b7f52da5fa7324d0c77b0f7b17b5bfa207cc53e75ee5ff57fc651`。
核验通过：27 份本地/远端源码一致、132 份原始证据、6 份模型、71 份 ASPIRE 和 443 份 cuRobo 文件；
冻结 Phase 2A 原始证据无变化。
`archive_evidence.py --phase2b` 会核验冻结 Phase 2A 原始证据、六份模型、原本体球与忽略对、
ASPIRE 已知补丁和 cuRobo 源码；它不将摘要冒充原始证据。

## 完整迁移的确切剩余项

1. **完整装配几何**：核对 RM65 型号/法兰系，测量 flange→CTAG origin 的实际厚度、偏移和朝向；
   获得夹爪连杆厚度/销轴位置/闭环耦合的 CAD，验证 master 开度、follower 关系与当前安装。
   确认腕相机壳体/支架；随后在独立候选中审核碰撞覆盖。现有原始球不能绕过。
2. **现场状态与标定**：单臂身份、供电、端点、唯一 SDK owner、明确只读授权；核对单位、关节符号、
   Work/Tool、状态错误和时间戳；实测公共 World、实际左右抓取 TCP、相机外参及 raw/aligned 深度。
3. **真实执行 transport 尚未实现/验收**：控制周期、RM65 CANFD 七浮点 C 存储约定、跟随模式、
   反馈时限/误差、中止、真正同步启动与偏差界限。不能把两个顺序阻塞 RPC 作为同步，也不能删除硬拒绝直接上机。
4. **完整模型任务基线尚未运行**：先以经过现场几何验收的完整模型重复 GPU→原生 CAP/MCP→Stub；
   再取得另行明确的真实控制授权和控制验收，最后运行原生 ASPIRE 任务决策与感知闭环。
   ARM_ONLY 正向软件链路和原生会话取消已不再是该阶段的软件阻塞。
