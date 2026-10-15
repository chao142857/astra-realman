# 完整物块路线：释放时丢失右侧夹持，尚未修复

基线 `89f5e61`，ubuntu-robot，2026-10-16。唯一延续路线为
`full_numeric_known_d3_urdf_effort_04`。新增真实 Astra 请求 **0**；未连接生产 Bridge、未建立授权、未恢复旧 ledger。未运行空手任务。

本轮没有获得可采用的控制器修复，也没有完成右臂退出、搬运或蓝区放置。原结果仍是 **INCOMPLETE**，不能把接取阶段计成完整任务成功。

## 原日志与精确回放

`evidence/release_retention_20261015/original_readback_01` 从桌面方块、双臂空手打开开始，执行原数值动作及自然物理持物，不从 qpos 人造恢复物体/接触。一直到释放前第 7018 步，方块完整位姿、左右全关节 qpos 与接触标志和原路线逐步相等，最大差为零。归档提案和轨迹数组也单独核对；见 `verification/independent_checks.json`。

原始失败在同一步复现：右臂独立持物检查结束于第 7968 步，方块已经落桌。原记录 `attempted_stage=left_release` 表示该动作之后的持物检查失败，不是开爪命令被拒绝。

| 原始/只读回放的事件 | 物理步 | 仿真时间 |
|---|---:|---:|
| 左臂开爪命令开始 | 7018 | 28.072 s |
| 首次没有左臂与方块接触 | 7057 | 28.228 s |
| 左夹垫代表点间距超过 70 mm | 7150 | 28.600 s |
| 右双侧接触首次不满足 | 7283 | 29.132 s |
| 方块相对右 TCP 平移变化首次超过 2 mm | 7316 | 29.264 s |
| 首次出现方块/桌面接触 | 7356 | 29.424 s |

右双侧接触在首次中断后曾短暂重建，不能将第一次中断与永久失去接触混为一谈。2 mm 相对位移只是本报告的描述标记，并非修改评分或碰撞阈值。

左臂开爪早期，右侧实际间距约 49.608 mm；到第 7280 步为 50.138 mm、第 7283 步为 50.144 mm，两侧接触冲量逐渐衰减。方块先有亚毫米位置/姿态变化，随后失去持续支撑并下落。这不是此前“物体不动但引擎速度较大”的单纯速度评分问题。

## 驱动与联动证据

右主关节在释放期间原生 getter 始终读回 K=20、D=2、force 模式、限力 10 Nm、位置目标约 −0.446318358 rad、速度目标 0。10 Nm 是原路线已有的 `urdf_effort_hold_v2` 设置，**本轮没有增加**。未发现目标或驱动参数被其他代码覆盖。

在实际关节逐步位置开始张开时，原生 qvel 仍报告明显的闭合方向速度。最终 `analysis_03/report.json` 的对齐采样使用同一物理步的 qpos/qvel：qvel 是该步末瞬时引擎读回，差分是同一关节在 `[t−0.004,t]` 的平均变化，二者不是完全相同的数值量。这一明显差异支持检查数值求解行为，**不足以单独证明 PhysX bug 或唯一根因**。

五条联动误差均按实际 URDF 的父关节、比例和零偏计算，未用单个关节值代替机构关系。尤其 Right_Support 的父关节是 Right_1。释放前后右侧误差总体减小：例如 Left_Support 对 master 的误差从第 7018 步约 1.190 mrad 降到第 7280 步约 −0.037 mrad。不能把这次开爪损失简单归因为联动误差持续扩大，也不能据此证明软约束无影响。

保存了逐步驱动属性、qpos、qvel、外加 qf 命令、接触点、冲量、穿透及方块相对 TCP 位姿。qf 是施加的广义外力命令，接触冲量是引擎接触量；**实际 actuator/tendon 力矩仍 UNKNOWN**。没有用 PD 公式、qf 或接触冲量代替原生驱动力矩真值。

## 仅做的两个有限求解对照，均不采用

| 对照 | 保留与改变 | 实际结果 |
|---|---|---|
| `right_solver_control_01` | 第 7018 步前逐步状态完全相等；释放前仅右 articulation 的约束求解迭代 10/1→32/8；驱动、目标、路径、质量、摩擦均不变 | 第 7023 步左夹垫穿透 **2.661618 mm**，原保护立即中止。不是修复 |
| `pgs_same_controller_01` | 已有 PGS 积分模式，保留原数值提案及相同夹爪控制器；从桌面开始 | 第 2697 步 `LEFT_PICK_NOT_HOLDING`。未到接取阶段，**不可用作右夹爪对照** |

没有继续扫描求解器、力矩、刚度、阻尼、质量、摩擦或姿态。上述配置只存在于私有诊断脚本，未成为默认控制器或模型执行器。全部失败、原始日志、视频和中间分析均保留；中间分析的空窗口错误及修正也保留在 command_logs，最终以 analysis_03 为准。

## 当前最早阻塞与继续条件

原数值接口可执行到右侧接触建立和左臂开爪；右侧随后不能持续保持方块。没有足够证据支持一个安全、可泛化的局部控制修复，因此本轮不盲目追加夹紧力，也不将失败的求解变体作为修复提交。缺少的是能区分位置驱动、软联动与接触约束作用的可靠原生驱动/约束力或相应求解证据，不能仅靠 qpos/qvel 的时间先后认定唯一根因。

在这个阻塞解除前，右臂退出/搬运/指定区域放置保持 **NOT_REACHED**。原私有完整路线的后半段仍保留，后续必须实际走完并独立评分；不能以“接住了”结束或回填旧 Astra 结果。

## 完整模型回合仍从抓取前接管

`run_episode.py --task handoff_place_full`、公开数值执行器和完整过程评分均未修改。`from_table_mock_01` 实际跑了物理 reset 和两次本地模拟协议请求：四视角、双方空手打开、方块在桌面、专家初始化动作 0；推理等待期间物理不推进。未授权 `--real` 在场景创建和派发前拒绝。7 项原协议测试通过。Mock 只验收接口，未声称完成任务。

真实正式回合仍必须由 Astra 从桌面抓取前负责抓取→交接→右臂退出/搬运→蓝区放置全部数值动作。这里的私有工程提案、GT 和动作序列不进入模型输入。

## 复现与材料

在本独立 worktree 的 `experiments/rm65_handoff_v1` 内：

```bash
source runtime.decision4.ubuntu-robot.sh
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" release_retention_diagnostic.py \
  --output evidence/release_retention_20261015/NEW_original_readback

# 两个诊断变体均失败；仅复核时使用，不是生产修复。
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" release_retention_diagnostic.py \
  --right-solver-control --output evidence/release_retention_20261015/NEW_solver_control
RM65_CONTROLLER=urdf_effort_hold_v2 "$RM65_PYTHON" release_retention_diagnostic.py \
  --pgs-controller-check --output evidence/release_retention_20261015/NEW_pgs_check

"$RM65_PYTHON" offline_tests.py
"$RM65_PYTHON" full_handoff_offline_test.py \
  --output evidence/release_retention_20261015/NEW_from_table_mock
```

每个输出目录必须不存在，不覆盖旧记录。`readback.jsonl.gz`、`physics.jsonl.gz` 为无损归档，未压缩原件仍留在 ubuntu-robot；需要重新调用旧 evaluate_process 时先解压到独立临时副本。

主要材料：

- `evidence/release_retention_20261015/original_readback_01/execution.mp4`：从桌面开始直到原失败的四视角真实仿真回放。
- `evidence/release_retention_20261015/release_timeline.png`：左臂释放至落桌的原始渲染帧。
- `evidence/release_retention_20261015/analysis_03/release_comparison.png`：开度、差分速度、联动误差、相对位移和穿透。
- `evidence/release_retention_20261015/verification/`：独立重评分、原提案/轨迹数组、旧 ledger 和资产完整性、视频解码及无损归档清单。

没有 teleport、weld、运行中 qpos 强写、碰撞关闭、专家目标在线替换或安全阈值放宽。旧 CTAG 和空手实验 ledger 的 SHA-256 保持不变；空手 PASS 不计入物块任务。
