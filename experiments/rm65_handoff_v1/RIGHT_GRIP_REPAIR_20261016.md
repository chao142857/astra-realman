# 右夹爪持续持物修复与完整工程物理回放

基于 `f66f4fc`，ubuntu-robot，2026-10-16。真实 Astra 请求 **0**；没有连接生产 Bridge、创建授权或恢复旧账本。1.1 m 布局、四视角、原资产、质量/摩擦、IK、碰撞预检和 2 mm 保护保持不变。

**右侧七秒独立持物已通过；从桌面抓取到蓝区放置的物理序列已实际走完。原单个大运输动作仍失败。** 完整工程参考采用 106 条显式数值动作，其中后半段为 5 mm 参考目标；这不是执行器自动修正模型提案，也不是 Astra 任务成功。

旧 `full_process_pass` 仍为 **false**，没有覆盖：其 `z<0.06 m` 掉落规则将受控下降时仍被右夹爪持续夹持的 341 步标为掉落。旧稳定放置项通过。下面保留物理事实、工程持物验收与旧评分三者的区别。

## 最小控制改动

`right_hold_velocity_v3.py` 只在原有右侧双接触锁定之后，把主关节原生速度阻尼 D 从 2 改为 0。K=20、位置目标约 −0.446318358 rad、预压 0.005 rad、10 Nm 上限均不变；左臂、从动关节和 tendon 不变。普通开爪继续使用原执行接口并恢复 D=2。

物理依据是原生 qvel 与同关节位置差分出现持续相反的方向。例如原第 7150 步，位置差分约 +0.006206 rad/s（张开），原生 qvel 约 −0.728213 rad/s（闭合）。代入显式 PD 关系，阻尼分量会指向张开。**该分量只是估计，并非隐式 PhysX 驱动实测力矩，也不证明唯一引擎根因。** 单因素对照显示，取消这一项后本场景静态夹持不再逐渐张开，满足严格的独立持物验收。

这不是通用持物运动已经修好的结论：原大运输目标下该控制仍在第 11464 步发生 2.227469 mm 穿透。它没有成为默认历史控制器。

## 闭合状态校准

`calibrate_right_contact.py` 对原始物理记录做 URDF/原 STL 的纯 FK，不向 PhysX 写 qpos。首先求 Pinocchio model→共享 world 的固定变换，并用实际两夹垫点验证，最大坐标误差约 `6.06e-8 m`。

- `opening_fraction` 是指令比例，映射为 `master=-0.91*(1-opening)`，不等于实际开度。理想无接触下，1/.55/.50/.45 分别对应约 89.847/53.421/48.795/44.088 mm 的局部内表面平面间隙。
- 实际 `.45` 接取被原双接触锁定截停，后续目标保持约 −0.446318 rad，而不是继续追赶无物体时的 −0.5005 rad。未修改这个目标或追加闭合预压。
- 原第 7018 步，代表点距离 49.682306 mm，局部接触平面间隙 49.683012 mm。平面间隙沿穿过物体中心的闭合轴计算，**不是全机构最小距离**；内表面拟合最大残差约 0.079 mm。
- 物体中心投影在两片有效夹垫区域内，至最近边界约 10.9 mm。原接取不是仅靠夹垫边缘碰到方块。姿态与接触点仍影响局部穿透，不能用整个立方体的投影宽度直接替代接触区域间隙。
- 原生接触法向、点位置、冲量与间隙保存在 `right_native_readback.jsonl.gz`；分解后的法向/切向冲量只作接触诊断，不称为实测夹爪力矩。七秒无其他支撑的真实物理保持才是独立承载的直接验收。

返回冲量向量的法向/切向投影不能保证包含完整摩擦约束信息；切向投影很小不等于不存在摩擦承载。没有用这些投影宣称完整力平衡或某个唯一接触机制。

`calibration_01` 最初误用了 FK 模型坐标作世界坐标，其物体相对位置分析作废，原文件保留。以 `calibration_world_verified_02` 为准，详见 `CALIBRATION_ERRATA.json`。控制候选未用作废分析值修改目标。

## 三个控制候选，到此停止

| 实际候选 | 唯一主要因素 | 结果 |
|---|---|---|
| 1 `no_native_damping` | 仅右接触保持主关节 D=0 | 2+5 秒持物全部通过；左臂退出、右臂退出通过；原大运输段穿透 2.227469 mm 中止 |
| 2 `position_difference_feedback` | 原 K/D/限力，尝试用位置差分校正右主关节速度目标 | 第 6751 步、接取闭爪阶段穿透 2.053841 mm，淘汰 |
| 3 `all_finger_native_damping_off` | 相比候选 1，再取消五个右从动关节的原生阻尼 | 第 7018 步接取后不能保持双侧接触，淘汰 |

没有提高限力、增加摩擦、降低质量、改 tendon 或继续扫参数。首版源码中的临界阻尼草案没有执行；实际尝试的三个模式由各 `result.json` 的 candidate 字段及独立汇总计数确认。

## 持物与正常开爪回归

候选 1 的原数值前半段从桌面真实抓取开始，与原基线在控制改动前第 6698 步以前逐步相等。原十条数值提案保持相等。没有预抓取初态、物体绑定、运行中 qpos 写入或瞬移。

严格验收窗口为第 7469–9218 步：先 2 秒，再额外 5 秒。每一步均为右侧双接触、无左臂/桌面支撑、无互臂接触，未触发保护：

| 工程指标 | 七秒窗口实际结果 |
|---|---:|
| 最大相对右 TCP 平移变化 | 约 0.0002455 mm |
| 最大相对姿态变化 | 约 0.0001468° |
| 最大夹垫穿透 | 约 0.268863 mm |

这些极小变化是仿真记录中的数值，不表示真实传感测量精度。验收上限仍是 2 mm、5°、2 mm，没有借助原生世界速度过滤改判旧结果。

`release_regression_versioned_controller_01` 使用提取后的同一版本控制器重新完成从桌面抓取及七秒保持，随后通过原 `execute_action()` 发出 opening=1。后续 2 秒实际开度始终超过 70 mm、右双侧接触消失、方块持续桌面支撑，D=2 恢复。此项是正常开爪回归，不是蓝区整任务成功。

## 完整运输与放置

候选 1 通过持物后立即执行后半段，没有停在接住方块。原单个大运输目标执行失败的原始录像和记录保留。随后控制器参数完全不变，仅私有工程参考显式给出沿原运输线/下降线的 5 mm 目标，每一条都独立经过同一 IK、共享碰撞预检、关节插值及实际 PhysX。

`fixed_controller_fine_transport_01` 实际完成 106 条数值动作、33024 个物理步（132.096 s），完成左臂抓取→接取→释放→右侧独立持物→双方退出→运输→下降→开爪→蓝区稳定放置。最大夹垫穿透约 0.495569 mm，没有互臂接触或保护中止。最终方块中心约 `[0.520479, 0.160112, 0.025001] m`，右侧开度约 88.698 mm。

私有细目标只存在于 `full_handoff_reference.py` 的工程路径选项。**公开执行器不会替 Astra 自动细分、减速、改目标或插入专家路径。** 106 动作参考不证明未来短预算模型回合能完成，也不证明原大动作已可安全执行。

### 原评分为何仍 FAIL

原评分在第 31734–32074 步标记掉落：中心高度从约 59.983 mm 受控降至 54.768 mm，仍为右双侧接触、无桌面接触。第 32074 步之后才开始命令右夹爪打开。其 `z<0.06` 启发式与这段受控下降不匹配。

旧 `full_process_pass=false`、341 个标记、旧阈值及所有子项原样保留，不以本报告覆盖。独立报告另列每个标记时刻的夹持/桌面证据。原 `left_hold`、`right_independent_hold`、`stable_place`、`no_interarm_contact`、`no_pad_penetration_abort` 均通过。这里报告的是观察到完整物理序列，**没有宣称旧冻结评分 PASS**。

## 复现

```bash
cd /home/alex/astra_spatial_capability/rm65-right-grip-repair-20261016/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" right_grip_repair.py \
  --candidate no_native_damping --fine-transport-reference \
  --output evidence/right_grip_repair_20261016/NEW_full_physical_reference
```

每次必须使用不存在的新输出目录。去掉 `--fine-transport-reference` 可复现已保留的原运输失败；加入 `--release-regression` 可复核正常开爪。后两种不计为完整任务成功。

全任务模型入口仍是 `run_episode.py --task handoff_place_full`，显式选项 `--right-hold-control master_damping0_v3` 安装相同接触保持设置，需显式使用已有 `urdf_effort_hold_v2` 基础控制器。默认仍为 original；没有私有路径或工程初始化进入模型回合。

7 项原协议测试通过；`versioned_full_task_mock_01` 验证四视角、桌面空手初态、第 100 步接管、专家动作 0、两次本地 mock、未授权真实请求在派发前阻断。当前 `--real` 仍禁止，真实 Astra 请求为 0。

## 材料

- 原对照：`evidence/full_handoff_restore_20261015/full_numeric_known_d3_urdf_effort_04/`，及 `evidence/release_retention_20261015/original_readback_01/`，全部保留。
- 完整物理录像：`evidence/right_grip_repair_20261016/fixed_controller_fine_transport_01/execution.mp4`。
- 独立持物原始帧片段：`evidence/right_grip_repair_20261016/right_independent_hold_actual.mp4`；来源帧/物理步见 `verification/hold_clip_source.json`。
- 完整阶段拼图：`evidence/right_grip_repair_20261016/full_sequence_actual_rgb.png`。
- 独立重评分与前半段比较：`evidence/right_grip_repair_20261016/independent_analysis_01/`。
- 原生全部接触点复核、历史账本/资产哈希、视频解码和无损日志清单：`evidence/right_grip_repair_20261016/verification/`。

未压缩日志留在 ubuntu-robot；Git 保存无损 gzip。物理修复与工程参考均未算作 Astra 成功。未来正式模型回合必须从桌面初态自行完成全部任务，并另行取得新授权，不使用旧剩余 11 次。
