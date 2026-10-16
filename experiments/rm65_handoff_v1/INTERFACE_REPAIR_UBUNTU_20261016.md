# Ubuntu 接口修复验收：真实 PhysX 回放，渲染待恢复

基于 `624d80f`，迁移分支 `codex/rm65-interface-repair-ubuntu-20261016`。原 yanglab WIP 记录保留在 `INTERFACE_REPAIR_20261016.md`，本文件补充实际物理验收结果。

**本轮真实 Astra 请求 0、Bridge 连接 0、新授权账本 0。没有恢复旧 STOPPED ledger。** 双 RM65、1.1 m、原四视角配置、右夹持控制器、IK、2 mm 原生保护和旧评分保持不变。

## 验收结论

| 项目 | 实际结果 |
|---|---|
| P0 接触一致预检/执行 | 真实 PhysX 验证：不再将空载过闭合假定为接触终态，逐步监测；正常抓取通过，危险接触仍停机 |
| 原始 Decision 1 | 原动作不改，先双侧接触、锁定，随后指垫穿透 2.191056 mm，立即原生保护停机；没有放行成成功 |
| 原始 D1 旧拒绝 | 原执行函数精确复现 `INTERPOLATED_COLLISION:left:105`；旧预测的撞桌/非指垫碰块，在新接触回放停机前未出现 |
| P1 原始 Decision 4 | 从精确重建的 D3 终态执行，38 个数值子组完成；两个相同 left 动作分别执行，未覆盖/去重 |
| 空桌面闭爪负对照 | 实测构型出现 Right Support Link/table FCL 禁碰立即停止，停止前无双侧接触 |
| 正常抓取/抬起回归 | 闭爪命令完成但未宣称稳定抓取；独立抬起后 2 秒持续双侧持物通过 |
| 显式开爪回归 | 脱离双侧接触，方块落桌，随后 2 秒连续桌面支撑且位置不变；仅是释放接口回归 |
| 离线测试 | 59 项通过 |
| 视频/新 RGB | **未完成**：NVIDIA 既有内核软锁死阻塞渲染，真实物理回放明确采用无渲染模式 |
| 完整抓取—交接—放置 | **未完成，未由本次回放证明可执行** |

## 原始 Decision 1 的拒绝是否合理

旧 `index=105` 来自以空载目标推进的 FCL 预测，闭爪实际未执行。这种预测不能证明接触锁定后的真实闭合轨迹一定撞桌。

本轮用原始 raw、原正常桌面初态、原 `.027 m / .15 / bilateral_hold`，保留原伺服与有限预压。数据在 `evidence/interface_repair_ubuntu_20261016/contact_d1_physics_01/`：

- 闭爪前 step **11675**，完整双臂实测状态、物体位姿/速度、目标和原生接触记录与历史精确一致。
- step **11819** 首次双侧接触，闭爪开始后 **0.576 s**。
- step **11820** 两个连续接触样本后锁定，之后不再推进空载闭合 ramp。保持目标约 **−0.452033 rad**；原请求的空载终点仍为 **−0.7735 rad**，原提案未更改。
- step **11837**，锁定后 **0.068 s**，Right Support Link/方块最大穿透 **2.191056 mm**，原 `PAD_PENETRATION` 立即中止。此时实际主关节约 **−0.466785 rad**。
- 中止前没有实测 FCL 禁碰，也未记录到左夹爪与桌面、非指垫连杆与方块接触。方块仍受桌面支撑，不能将双侧接触当成独立抓取成功。

**原拒绝的保守安全作用不能撤销；但其空载预测理由不能冒充实际发生的撞桌。** 当前证据是接触锁定后的物理过冲/穿透，未证明唯一根因。`.15` 在当前执行控制下未安全完成，既不能回填为成功，也不能仅凭此认定 Astra 空间规划错误。本轮未调整开度、目标、姿态、伺服或保护来消除失败。

接触时序图：`evidence/interface_repair_ubuntu_20261016/decision1_contact_timing.png`。它是物理日志曲线，不是仿真 RGB 或录像。

## Decision 4 顺序证据

用归档原执行函数及前三条原提案推进到 step **27325**；不仅 qpos，还比较完整 `arms`、原生 `contacts`、物块位姿/速度、drive targets、双侧接触，均精确一致。随后原始 Decision 4 原文交给新公开协议和执行器。

第三阶段两个相同 left TCP 操作：

| 原列表 index | 实际 start/end step | 起点 TCP xyz（m） |
|---|---|---|
| 0 | 34425 → 34650 | 0.050016806, 0.000000790, 0.030009838 |
| 1 | 34650 → 34875 | 0.049993445, 0.000000952, 0.029977725 |

第二项起点与第一项执行回执的实测 TCP 精确相同。原始列表、原目标、两个操作和顺序均保留。全部 38 子组结束于 step **36150**，无安全保护。该回答全部是 TCP 动作，不含闭爪；完成 D4 不代表抓取或整任务完成。

parallel 重复 arm 在公开语义校验阶段拒绝；同一属性跨项唯一性不冒充原 Bridge schema 子集能独立强制的规则。合法左右臂 parallel 调度及顺序混合动作单测通过。

## 正负物理回归

已有工程抓取输入仅用于离线控制验收，不进入在线模型输入。`.45 / bilateral_hold` 关闭后仍如实报告未建立接触保持，后续独立给出的抬起动作执行后，2 秒真实双侧持物：相对平移漂移 **0.000240 mm**、相对转角 **0.000067°**，最大指垫穿透 **0.053216 mm**。没有自动抬起或替模型选择夹紧值。

显式 `opening_fraction=1 / position` 后，末尾 2 秒无双侧接触、连续桌面支撑、物块 xyz 范围均为 0。报告中的旧过程评分仍独立保留；该高处释放测试不是完整任务放置成功，也不掩盖旧过程评分的掉落记录。

负对照预先固定为：将 D1 所有 TCP 的世界 Y 平移 **+0.12 m**，使闭爪位于空桌面；其余 `.027 m`、`.15`、姿态、接触模式不变。这是独立工程负对照，绝不是改写后当作原 Astra 答案。step **14542**，实测 `L__ctag_Right_Support_Link / table` FCL 禁碰触发停止，双侧接触从未建立。没有为了完成原动作增加桌面碰撞例外。

## 环境、原始记录及渲染限制

- 主机 `Ubuntu-Robot`；现有 Python 3.10.12、SAPIEN 3.0.0b1、mplib 0.2.1、NumPy 1.26.4、SciPy 1.10.1，无安装/升级。
- 56 项原资产哈希全部通过。既有 `urdf_effort_hold_v2` 加原已验证右侧接触保持控制；原求解器、dt=0.004、布局及四相机配置未变。
- 12 份本工作树历史 ledger 在本轮前后 SHA 完全一致。原结果文件未改；没有访问或恢复原主机私有生产账本。
- 最初四视角回放卡在渲染器初始化，物理步数 0，进程已终止并保留原输出。内核 `nvidia-modeset` 的约三小时软锁死日志先于该回放启动。现有 Intel Vulkan 不支持该集显 PCI ID，软件 Vulkan 缺扩展，均有界检查后保留日志；未改驱动、网络或重启系统。
- `replay_without_rendering.py` 只被离线诊断显式 `--physics-only` 导入，省略视觉构建、RGB 和视频；仍使用真正 PhysX CPU scene、原 URDF 惯量/碰撞解析、驱动、IK/FCL 和原生保护。精确历史状态/完整接触对比是其等价性证据。它不在在线 episode 入口中，未用静态 PNG、mock 或状态瞬移代替物理。
- `.jsonl.gz` 是完整逐步物理、事件和接触日志的 SHA 验证无损压缩，未压缩原件仍在 ubuntu-robot。各动作、轨迹 NPZ、回执和接触日志公开归档；完整源码快照保留主机，公开各次快照的 SHA 清单并单独提交源码，避免重复上传 723 份代码副本。`independent_analysis.json` 优先读取公开压缩原件，是独立只读核验，不覆盖任何旧评分。
- 自动审批曾拒绝未逐项审查的整包公开推送，随后缩小载荷并进行内容审查。`publication_audit.json` 记录公开文件类型、全部压缩日志的 JSON 解析、NPZ 无 pickle 数值检查、PRIVATE 字段清单和认证字段/密钥模式检查。这里 PRIVATE 指“不进入模型的仿真真值”：接触、运动学、数值轨迹与工程对照目标，不能混同为可公开的认证材料。授权文件、bridge 配置和 token 不在该载荷中。

## 复现

```bash
ssh ubuntu-robot
cd /home/alex/astra_spatial_capability/rm65-interface-repair-ubuntu-20261016/experiments/rm65_handoff_v1
source runtime.interface-repair.ubuntu-robot.sh
"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests transfer_safety_tests \
  full_task_prep_tests chunk_protocol_tests contact_guard_tests -v

# 每次使用全新输出目录；不连接 Bridge、不调用模型。
RUN="evidence/interface_replay_$(date +%Y%m%d_%H%M%S)"
"$RM65_PYTHON" interface_replay.py --physics-only --case legacy_d1 --output "$RUN/legacy_d1"
"$RM65_PYTHON" interface_replay.py --physics-only --case contact_d1 --output "$RUN/contact_d1"
"$RM65_PYTHON" interface_replay.py --physics-only --case sequential_d4 --output "$RUN/sequential_d4"
"$RM65_PYTHON" interface_table_negative.py --physics-only --output "$RUN/vacant_table"
"$RM65_PYTHON" left_grasp_semantics_physics.py --physics-only --release-regression \
  --mode bilateral_hold --output "$RUN/grasp_release"
```

各案例独立 reset；同一案例触发保护即结束，不越过保护继续。GPU 恢复后省略 `--physics-only`，原四相机和录像入口不变，必须使用新输出目录。没有新鲜录像前不宣布视频验收完成。

**剩余阻塞：** `.027/.15` 原动作在接触锁定后仍发生原生穿透中止；完整物理交接放置未由本轮证明；GPU 渲染待恢复。本轮不继续调参、不启动真实 Astra。下一轮模型调用仍需新的冻结与明确授权。
