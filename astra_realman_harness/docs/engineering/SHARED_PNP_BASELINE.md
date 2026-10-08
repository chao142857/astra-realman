# Astra × RealMan 共享工程底座：完整抓放基线

2026-10-09，基于冻结 `91be1a458aef5f74b95b34372fb817ad85e9a693`，独立分支 `codex/shared-pnp-engineering-20261009`。

本工作树负责共享物理执行、测量、评分隔离及真机软件接口准备。World-Anchored Memory、异步调度、视角选择、History、Subagent研究方法已移交独立项目；此处不继续扩展E1–E4，不修改B/F决策方法。历史代码、真实失败与研究卡保留为历史记录，不代表本树新授权。

结论：**参考布局的完整抓放已通过；跨布局可靠性仍未建立。** 本轮7个物理进程：首条参考1次，冻结布局3×2次；真实Astra0、硬件0、B/F0、自动重试0。没有放宽−2mm阈值、关闭碰撞、改物理参数或中途写物体状态。

## 首条完整参考回合（已冻结）

标记 `ENGINEERING_REFERENCE`，复用原 `run_full_pnp_offline.py --condition script`、FullTaskBackend、ModelAdapter、grasp_control、mplib/OMPL/FCL和独立评分。原隔离 `scripted.py` 使用工程对象/目标坐标：接近至40mm、opening=0.45、闭爪后相对上抬80mm、运输、下降、释放、退出。GT参考只在工程脚本/私有评分，不流入模型投影。

首回合 `reference-001`：空夹爪准备→接近→闭爪资格确认→抬升和保持→运输→下降→释放→退出→稳定评分，7个chunk、10个成功动作、1次抓取。原全任务评分与新增离线逐阶段核验均为PASS。

- 实际物体运输XY距离230.026733mm；运输最低抬升78.975795mm、全过程闭合且双侧接触，最大相对滑移0.032128mm。
- 最大抬升92.884777mm；最终放置XY误差0.868873mm，释放/稳定放置/退出均满足，退出指垫中心到对象box的最小距离73.100872mm。
- 初始化墙钟2.018s、物理3.3s；执行及评分墙钟22.291s、物理16.924s。进程墙钟包含CLI版本/help预检及清理，原值见result.json。无推理请求，旧runner构造的slot未启动worker。
- 原视频 `scene/execution.mp4` 完整解码199帧，索引step100→5050、间隔25步，10fps。它是未剪辑的 **fixed+wrist两路** 合成记录；当前RGB观测仍有assembly/fixed/wrist三路。视频按物理时间采样，不是墙钟录像；前100步初始化未入视频，闭爪/完整任务全过程在录制范围。关键帧图仅作索引，不替代原视频。
- 105个原始文件的hash在 `reference-001.FROZEN.json` 固定；后续分析写到旁路，不回写原result/score。原legacy字段 `model_action_decisions` 是分派计数，不是真实模型调用。

## 三布局 × 两次：所有结果

布局事先固定在 `config/engineering/layouts_v1.json` 和 `layouts_prepared/prepared.json`；只改变初始化的 `cube_initial_xyz` 和 `place_zone_xy`。独立复制的asset包除assembly.json这两个字段外逐文件相同，URDF/mesh/控制器/相机/物理参数不变；新manifest公开标记差异。没有中途set_pose或setup_held。

所有回合seed=2，均为新进程初始化、同一工程脚本和节奏；重复并非状态克隆。布局由坐标区分，不由seed区分。名义物体z=26mm，重力稳定后约25.00068mm；逐回合配置、实际位姿和来源保存在 `acceptance_cases.json`。

| 回合 | 物体初始XY → 目标XY（m） | 结果/阶段 | 成功动作数 | 执行墙钟 / 物理时间（s） |
|---|---|---|---:|---:|
| L1-r1 | (0.36,−0.06) → (0.36,0.17) | PASS，完整抓放 | 10 | 22.778 / 16.924 |
| L1-r2 | 同L1，新进程 | PASS，完整抓放 | 10 | 22.452 / 16.924 |
| L2-r1 | (0.33,−0.10) → (0.33,0.13) | FAIL，闭爪后失接触 | 3 | 8.127 / 6.132 |
| L2-r2 | 同L2，新进程 | FAIL，闭爪后失接触 | 3 | 8.136 / 6.132 |
| L3-r1 | (0.39,−0.03) → (0.39,0.15) | FAIL，首接近IK拒绝 | 0 | 0.073 / 0 |
| L3-r2 | 同L3，新进程 | FAIL，首接近IK拒绝 | 0 | 0.073 / 0 |

初始化均另计，动作数不含通用空手准备。第一条参考不重复并入六回合统计。这是固定工程回归，不是Astra成功率或B/F结论。

**VERIFIED — L2**：两次在step2268–2271仅有4步双侧接触（16ms）；原latch曾发生，但闭爪结束前连续87步缺失，终点gap50.165882mm，最大物体抬升仅0.059376mm。共同grasp_control报 `GRASP_CONTACT_LOST_AFTER_LATCH` 并停止；没有上抬、运输或释放，属于抓取接触失败，不是运输滑落。

**INFERRED — L2**：有限预载下未保持受载接触，可能与末端实际姿态、两侧接触非对称及连杆动力学有关。**UNKNOWN**：该新回合没有逐点impulse/法向，不能证明单一原因或据此提高驱动/放宽50步资格。原qpos/gap/物体位姿/双侧布尔/事件/视频齐备，见failure_analysis.json。

**VERIFIED — L3**：第一条pad-center目标约[0.389999,−0.030000,0.18]、等效flange z≈0.381465m被原规划器报 `IK Failed! Cannot find valid solution.`；原任务动作0、抓取尝试0，之后未推进任务物理。**UNKNOWN**：这只能证明此姿态/配置下规划器拒绝，尚未区分几何不可达、有效碰撞约束或数值求解原因；不能宣称已验证3组可达布局。原0.18m接近是工程参考路径，未为成功改为较低接近或自动补跑。

原score中的 `safety_abort` 实际使用通用stopped标志；L2/L3停止不等于越过穿透阈值。原 `released/exited` 也可能在初始空手时为true。新增离线完整评分同时要求真实释放/退出chunk完成，避免将初态当任务阶段成功；不修改原评分结果。

## 闭合几何测量

`analyze_gripper_closure.py`只读取已归档四格、URDF、实际qpos和加载碰撞几何，不建立SAPIEN场景。FK与原逐步指垫中心最大差异<0.285微米。完整数据/图在geometry/，不把测量生成的目标送入策略。

固定起始法兰姿态，把实际pad-center变化分成：连杆相对法兰的运动，及机械臂法兰运动/旋转交叉项。对Z40/opening=.45，实测总下降13.479953mm，连杆分量下降13.671127mm，法兰运动抵消0.191174mm。Z30/.45分别为13.475009、13.641611、0.166602mm。**约13.4mm下降主要由闭合连杆运动产生，不是把一个固定TCP简单平移。**

| 名义opening（无载理想mimic） | master q（rad） | 理想pad gap（mm） | 在参考初始法兰下pad中心z（mm） |
|---:|---:|---:|---:|
| 1.00 | 0 | 89.847 | 40.006 |
| 0.75 | −0.2275 | 70.913 | 31.866 |
| 0.50 | −0.4550 | 48.795 | 26.071 |
| 0.45 | −0.5005 | 44.088 | 25.222 |
| 0.00 | −0.9100 | 0.590 | 22.575 |

表为离线运动学推导，**不是有物体时可达到的真实开度**。有载latch会修改目标/实际qpos；比如旧Z40/.45真实终点gap≈50.131mm，而不是44.088mm。完整101点理想曲线与四格实际轨迹分别保存。

四格Support_Link采样扫掠最低顶点距桌面约4.511/4.890/14.652/14.875mm；对应最小记录接触separation为−2.328300/−0.036956/−1.233162/−0.109890mm。扫掠AABB只描述采样包络，不能当作对物体的有符号安全距离或未采样状态保证。原接触凸包覆盖整个Support_Link；不能假设所有接触都发生在末端橡胶指垫。

本轮不改变共享执行控制。证据支持保持动态pad-center语义并在规划/验收中明确它；还不足以支持固定高度补偿、统一把所有抓取改成40mm、改mesh、改预载或速度。下一步应针对L2接触保持与L3首接近IK分别做预先限定的诊断，不能混合改参数后补跑到成功。本轮到此停止物理扩展。

## 只读数据边界

新 `engineering/public_view.py` 提供冻结RGB+hash、单调时间戳与采集跨度、标定、机器人状态、公开执行回执/错误码；不提供owner句柄、不提交动作。动作提案用原 `parse_actual_raw`解析，来源必须是MODEL_RAW，保留raw hash；没有格式修复或RGB动作stub回退。

工程运行导出器只读取 OBSERVATION / CHUNK_END；不读取计划答案、result/score/private trace。工程参考action/目标被省略，公开回执保留实际本体反馈/完成与失败，holding仍UNKNOWN。任意原始错误字符串保留在私有审计档，公开接口只给有限错误码，防止嵌套GT泄漏。当前样例public_reference有23项记录，不是新的模型请求输入或模型能力证据。

三路图是顺序采集，不是同时曝光；时间戳为owner采集完成的monotonic时间，单张硬件曝光时间为null/UNKNOWN。仿真相机参数不是真机标定。此处不维护新World Memory、History策略、视角选择、异步或Subagent算法。

## 真机准备

[现场清单及配置/命令](REALMAN_ONSITE.md)。本轮只读源审查、fake SDK单测、配置检查；模板实际结果NOT_READY，SDK路径不存在/哈希未知，设备连接0。任何真机动作权限仍为false。

## 验证、归档与限制

111项定向测试通过：新增工程布局/只读边界/真实raw解析/初态不是释放退出，原grasp_control、requirements、完整任务runtime/review和SDK只读/镜像mock。没有新增同类stub物理回合。完整评分的参考/运输/释放/退出均分项保留；各视频完整解码且帧索引连续。

当前唯一验收表为 `acceptance_cases.json`。早期报告草稿保留；其中初态release/exit显示与视频视角文字已在独立验收表修正，原场景结果从未改动。一次离线分析遇到L3空trace，已明确处理为未执行任务物理，而非填造状态；没有触发新物理运行。

代码交付：`/home/alex/astra-realman_ws/astra-realman-shared-pnp-engineering-20261009`。
证据交付：`/home/alex/astra-realman_ws/astra-shared-pnp-evidence-20261009`。
实际运行命令、Git状态、源码hash、配置、raw反馈和失败保存于每回合result.json及批次attempts.jsonl。首回合来自干净91be1a4；六回合运行时新增薄账本尚未提交，但底层/决策模块hash未变。不要把这些运行改称最终新提交下的重新执行。批次结束后仅补强了薄账本对启动异常/外层超时的保留，和公开导出的归档迁移路径；已运行的七回合未重跑。

## 可运行入口（本轮不自动再执行）

```bash
CODE=/home/alex/astra-realman_ws/astra-realman-shared-pnp-engineering-20261009/astra_realman_harness
ASSETS=/home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets
PY=/home/alex/astra/.venv/bin/python

# 一条工程参考完整回合；输出必须全新。没有模型请求选项。
cd "$CODE/.."
PYTHONDONTWRITEBYTECODE=1 timeout --signal=TERM --kill-after=5s 360s "$PY" "$CODE/scripts/run_full_pnp_offline.py" \
  --condition script --assets "$ASSETS" --output /home/alex/astra-realman_ws/engineering-reference-new-01 \
  --seed 2 --video --budget-s 300

# 冻结新布局批次，然后单次消费；失败也不删除CONSUMED标记或重跑。
"$PY" "$CODE/scripts/run_engineering_pnp.py" prepare --assets "$ASSETS" \
  --reference /home/alex/astra-realman_ws/engineering-reference-new-01 \
  --output /home/alex/astra-realman_ws/engineering-layouts-new-01
"$PY" "$CODE/scripts/run_engineering_pnp.py" run \
  --prepared /home/alex/astra-realman_ws/engineering-layouts-new-01 \
  --output /home/alex/astra-realman_ws/engineering-layout-results-new-01
```

入口预算：每回合300s控制/评分，360s外层总时限加终止清理5s；每条工程脚本至多7个chunk/10个动作，保留原12 chunk owner上限及原grasp保护；每新批次精确6条，不重试。所有模型/硬件额度为0。上述命令供另次明确启动，不表示本轮继续执行。
