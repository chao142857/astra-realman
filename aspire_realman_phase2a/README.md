# Phase 2A：双 RM65 离线规划与执行适配

Phase 2B 后续实现与实际 GPU 正向闭环见 [PHASE2B.md](PHASE2B.md)。以下为冻结的 Phase 2A 验收范围；完整装配阻塞仍保留。

基线 `24e71b77`；分支 `codex/aspire-realman-phase2a-offline-20261020`。
ASPIRE 固定 `fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`，其 cuRobo gitlink 固定
`a35a708ecfbb26eb9ab2d7ef22c65919c4fae4a9`（V2）。

**尚未得到碰撞有效的双臂规划轨迹，也没有完成规划器到 Stub 的成功轨迹闭环。**
实际 cuRobo GPU 已完成双臂 FK、规划器初始化、约束诊断、场景碰撞和跨臂碰撞计算。
历史完整装配模型存在自碰撞，原生 CAP/MCP 按真实计算结果拒绝三个运动请求。
以下状态不能合并为整体 PASS。

| 项目 | 本轮证据与结论 |
|---|---|
| 真实 GPU FK | 完整 12 关节、2 个 `Link6`、2,958 个碰撞球加载成功；与独立 URDF FK 对照通过 |
| 真实 GPU 规划器 | 原生 MotionPlanner 初始化成功；完整模型默认构型不可行，未返回可执行轨迹 |
| IK、单臂与双臂规划 | 实际调用 cuRobo；IK 返回不可达，规划返回 HTTP 422 `start_self_collision`；不是 Mock 成功 |
| 跨臂碰撞 | 保留 2,187,441 个跨臂球对；故意重合双臂反例中，原 cuRobo CUDA kernel 得到 30,875 个正相交跨臂球对 |
| 场景碰撞 | 原生 Provider 转换场景 mesh；包围障碍物反例的实际 scene constraint 为正，不能只用总体不可行判据代替 |
| GPU 执行前检查 | 原生 CAP → Adapter → HTTP → 实际 GPU：两采样均拒绝，Stub tick=0、硬件命令=0 |
| Stub 执行 | 原生 Trajectory/SynchronizedTrajectory 的时间轴、单位编码、反馈、重复派发、错误、超时、中止与夹爪合同通过离线验收；不代表真实控制 |
| 原生 MCP | 发现、observe、状态及 Stub `cap_set_gripper` 通过；三个运动工具正确传回真实规划拒绝 |
| SDK 真实派发 | 未提供可启用的硬件 transport；入口硬拒绝。端点/透传参数仅做源码审阅和 Stub 编码验证 |
| 真实标定与模型验收 | World、实际 TCP、安装几何与控制验收仍待现场；本轮没有把合成矩阵登记为真实标定 |

## 真实模型与自碰撞阻塞

复用 `aspire_realman_phase1b/RM65_MODEL.md` 中的现场文件：

- `/home/tongji/alex/rm65-contact-servo-yanglab-20261017/experiments/rm65_handoff_v1/runtime_config/planning.urdf`
- 同目录 `curobo.yml`、原 STL、CTAG2F90-D 夹爪和腕部相机装配。
- 模型源文件及所有引用 mesh 均记录 SHA256；原目录没有写入。

`realman_rm65_dual` 的顺序固定为 `left_joint_1..6, right_joint_1..6`，单位 rad；
末端为 `left_Link6/right_Link6`，**名义法兰不等于实际抓取 TCP**。
原配置的球体、padding、忽略对、关节限位、加速度/jerk 限制均保留。
没有增加碰撞忽略对、关闭自碰撞、丢弃附件或用较小球体取得成功结果。

离线基座为左 x=-0.65 m、右 x=+0.65 m/yaw=π，frame=`synthetic:realman_rm65_world`，
标记 `SYNTHETIC_OFFLINE_NOT_REAL_CALIBRATION`。这是软件用例，非现场间距。
重合反例使用另一份明确标记的 SYNTHETIC 布局。实际 World/TCP 保持缺失。

实际默认构型诊断：cspace=0、scene=0、self_collision=2。
球对几何相交包括每臂 `Link5 / ctag_base_link` 最大约 5.04 mm，
以及左右夹爪内部连杆最大约 15.48 mm。
保留原始锁定值与 URDF 限位中点这两种独立构型，各做固定种子 256 个有界 GPU 样本，
均为 0 可行。中点构型仅是 URDF 参数对照，未证明真实夹爪闭环机构或开度映射正确。
这些样本不能证明整个构型空间不可行，但说明不能把当前装配配置直接视为规划基线。
本轮没有继续调安装高度、球半径或碰撞阈值。

自动审批拒绝过“排除固定/锁定为同一刚体的内部接触对”的运行，因为可能违反不得削弱
碰撞检查的约束。该运行未执行，代码已撤回。
2026-10-21（Asia/Shanghai），用户明确选择“保持策略，按模型阻塞交付”。
`evidence/proposed-rigid-contacts.json` 作为**未应用、未运行、已关闭**的历史提案保留；
每臂 26 对，且不能消除活动关节两侧的 `Link5 / ctag_base_link` 问题。
保留全部原始碰撞检查，交付状态为 `BLOCKED_SELF_COLLISION`。
没有把提案加入任何实际模型或复现命令；本次决定不触发进一步提案测试、GPU 重跑或硬件操作。

## 已实现的软件

| 文件 | 行为 |
|---|---|
| `src/aspire_realman_phase2a/model.py` | 从现场历史模型生成双臂 URDF/V2 配置，锁定夹爪构型；记录几何、源文件、合成变换和 provenance |
| `provider.py` | RealMan 模型注册辅助、严格 frame/关节顺序/限位校验、单臂规划锁住另一臂；新增实际 GPU 轨迹复查端点 |
| `adapter.py` | 实现原生 EnvironmentAdapter；原生 joint/pose/synchronized 轨迹通路；执行前检查重采样后的全部关节、速度、自碰撞和场景约束 |
| `execution.py` | 单/双臂等间隔时间戳，rad→SDK deg 编码，Stub 回读，持久单次 claim、无自动重试、反馈错误、超时、中止；物理入口始终拒绝 |
| `runtime.py` | 原生 CapApi、RobotPlanningContext、ToolRegistry、EmbeddedAgentRuntime、server/MCP；可注入既有 SAM3 Provider，不更改任务决策逻辑 |
| `patches/0001-*` | 只扩展原生 cuRobo service 的模型与六轴合同；client、Agent、MCP、Prompt/Skills 未改 |
| `compat.py`、`patches/0002-*` | Warp 1.9.1 缺失 `wp.func(module=...)` 参数的局部注册兼容；SDF/梯度函数原样，3 种障碍物重载均保留 |

所有 State、相机和反馈均为明确的 `SYNTHETIC_OFFLINE`/`STUB_ONLY`。
没有合成状态混入真实 LiveSource 或原只读 owner。原生真实 Observation 的前置条件没有放宽。
既有 SAM3 Provider、单臂只读组件、封存 RGB-D、V17/V19 资产没有修改；没有重新运行 SAM3。

## 执行合同与能力边界

`cap_move_to_joints` 的原生 `step` 调用在本 Adapter 中先走实际 cuRobo 单臂规划，
另一臂六关节锁定；`cap_move_to_pose` 使用原生 integrated pose planner；
`cap_move_synchronized` 使用完整 12 关节规划及原生 SynchronizedTrajectory。
成功轨迹还必须通过实际 GPU 的重采样后复查才可进入 Stub。当前模型未产生成功轨迹。

轨迹使用每臂 Nx6 rad、严格关节名、共同 dt/相对秒时间戳和 expected_start。
Stub 双臂在同一个虚拟 tick 更新；回读同样明确标为 Stub。
单次派发 ID 以独占文件 claim 并 fsync；派发失败后不重试。
中止只阻止剩余 Stub tick，超时按虚拟时钟验收；没有声称它们证明实际急停或实时调度。
原生会话的运行中取消到执行器中止联动未实现/验收；不能把执行器注入式中止测试算作该联动通过。

SDK 源码 SHA `dac840a77e62280056674fbfb763cf6c4d93084406435fff3445872cf6b1f580`：

- V17 验证过 `rm_movej_p(pose_m_rad,1,0,0,1)` 阻塞终点逻辑；复用其 claim/无重试/回读原则，未复用任务轨迹。
- `rm_movej` 端点编码把六个 rad 转成 deg；仅源码合同，不冒充 V17 验证过的时间轨迹。
- `rm_movej_canfd` 编码生成六个 degree 参数；该现场 SDK 内部使用七浮点 C 存储，RM65 约定仍未实测。
  高跟随模式要求周期不超过 10 ms；本轮 Stub 是显式低跟随参数，不能直接证明 20 Hz 真实控制合格。
- 夹爪沿用 V17 `hand_follow_pos`、`int(opening*1000)`、set_state ACK 与位置回读合同。
  原生 MCP 请求 0.4329，Stub wire=432、反馈=0.432；`grasp_confirmed=UNKNOWN`。

**两个阻塞终点 RPC 不构成同步轨迹。** 本轮没有真实同步启动触发、硬件带时标缓冲或
双臂偏差保证；不支持 timed-dual 的 transport 会拒绝，绝不退回左右依次移动。
物理 `PhysicalDispatch` 无条件抛出 SAFETY_INTERLOCK，没有 allow-motion 开关或真实 SDK 导入。

## 实际环境与复现

执行主机新目录：`/home/tongji/alex/aspire_realman_phase2a_20261020`。
独立 `.venv`，通过只读路径复用旧 SAM3 环境的 Torch 2.7.1+cu126/numpy 1.26.4 和 CAP 依赖；
新包只装在本轮 `.venv`。RTX 3060 12 GB，驱动 535.230.02，复用 CUDA 12.1 头文件和现有 CUDA 库。
未更新驱动、整套 Torch、dp/aloha 环境或网络配置。依赖下载在本轮 250 MB 授权内，官方 SHA256
和体积见主机 `evidence/downloads/{planned,verified}.json`。cuRobo 只取 443 个必要源码/配置文件，4,148,067 B，未取大模型资产。
包括 CUDA 最小依赖、小流量探测和必要源码的文件体积保守上界为 201,775,675 B；这不是 VPS 计费测量。

实际 native MCP 验收峰值 allocated=2,606,070,784 B、reserved=2,971,664,384 B。
首轮缺少 six，随后发现 Warp module 参数不兼容；错误日志保留。
完成局部兼容后，原始 2,958 球模型能在 GPU 初始化，不需要球体压缩或降低碰撞检查。

最短复现（**当前预期退出 1，表示真实规划被自碰撞拒绝；不是整体 PASS**）：

```bash
ssh yanglab 'cd /home/tongji/alex/aspire_realman_phase2a_20261020 && bash aspire_realman_phase2a/tools/reproduce.sh evidence/reproduce-review-01'
```

命令只运行 CPU 合同验收及原生 CAP/MCP+实际 GPU；不下载、不启动相机、不导入 SDK。
输出目录必须是新目录。详细 GPU/collision 入口：

```bash
CUDA_HOME=/usr/local/cuda-12.1 .venv/bin/python -B aspire_realman_phase2a/tools/gpu_probe.py \
  --manifest evidence/model-coincident/model.json --output evidence/negative-review-01 \
  --planner --warp-cubin --expect-start-infeasible --http-gate
```

新工作区从固定源码准备时，先应用基线 Phase0.5 patch，再运行本轮 `prepare_native.py`。
cuRobo 可用 `fetch_curobo_sources.py` 复用/校验 source-only 缓存，再应用 `prepare_curobo_compat.py`。
这些准备步骤不会由复现入口自动下载或修改环境。完整新依赖版本在 `requirements-runtime.txt`。

## 原始证据与后续事项

主机 `evidence/` 保留所有原始构建、失败日志、GPU result、原生 MCP wire、Stub feedback、
claim/result、模型 manifest、采样 NPZ 和实际 GPU 球对结果 NPY；轻量索引记录路径、体积及 SHA256。
完整最终索引为主机 `evidence/phase2a-delivery-verified.json`，本仓库对应
`evidence/remote-evidence-index.json`；最终 Stub 逐案原始记录在主机 `evidence/stub-execution-final/`。
本仓库只推必要源码、补丁、轻量验收摘要和索引；不复制原 STL、大日志、轨迹或环境。
`evidence/native-original-01/summary.json` 中的总 `ok=false` 是预期模型阻塞，不可改写为迁移成功。

软件剩余：当前完整装配模型必须先解决/验收真实几何及内部接触定义；成功的 GPU 轨迹→
原生 CAP/MCP→Stub 路径仍需实际回归。真实 SDK transport、控制周期、同步触发/偏差和执行中
停止尚未实现/验收，不能只删除硬拒绝开关后接真机。
原生运行时中途取消的联动也需补齐并做软件回归；目前只验收了执行器的中止合同。

下次到实验室按以下顺序完成；本轮没有代替现场授权：

1. 确认单臂供电、身份、端点、唯一 SDK owner，明确只读授权；用基线已有有界只读入口核对关节顺序、deg/rad、Work/Tool、错误和读取时序、正常退出。
2. 核对实际夹爪连杆、flange adapter、腕相机安装，取得正确 CAD/URDF 及合法夹爪构型/耦合；独立验证碰撞覆盖，解释当前 5/15 mm 相交，保留原模型作对照。
3. 恢复其余三相机；用同一 owner 保存 raw/aligned RGB-D、profiles、内外参、scale、帧号、时间域和接收区间，配合已知尺度参考验深度。
4. 实测双基座公共 World、各相机外参和实际抓取 TCP；核对名义 RM65 型号/DH/限位/FK及现场碰撞物。
5. 先让修正后的完整模型通过离线 GPU+原生 MCP 成功轨迹闭环。之后另行明确授权真实控制验收：单臂低速、反馈/超时/中止、CANFD 六轴约定与周期、双臂同步能力和偏差，再讨论 ASPIRE 原生真机任务基线。

没有现场状态/标定/控制验收前，不启动 Home、夹爪、伺服、轨迹或真实任务模型。
