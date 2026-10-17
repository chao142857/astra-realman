# yanglab：接触预检与顺序动作接口验收

基于 `624d80f`，独立分支 `codex/rm65-contact-servo-yanglab-20261017`。移入已在 Ubuntu 验证的接口修复源码，复用 yanglab 本地资产和依赖；没有下载历史结果包。真实 Astra 请求 **0**，生产 Bridge 连接 **0**。历史 STOPPED 授权未恢复。

## 交付结论

- **P0 接触一致预检已通过正负物理回归**：仅对显式 `bilateral_hold` 的接触闭合，不再把空载持续闭合轨迹误认为实际接触终态。手臂/其他运动仍预检，闭合前后每个 4 ms 物理步及稳定观察均检查实测构型，原碰撞例外和原生 2 mm 穿透保护不变。
- **P1 顺序动作已通过原 D4 物理回放**：sequential 同臂两操作按原列表执行；parallel 同臂冲突拒绝。原 D4 共 38 个数值动作组通过，包含两个相同 left 目标，没有去重、合并或替换。
- **原 D1 仍无法安全完成**：原 `.027 m / .15 / bilateral_hold` 在双接触锁定后穿透 2.191056 mm，原保护停止。旧空载 index105 拒绝不能证明实际会撞桌；本轮实际停机前没有原预测的指垫撞桌或非指垫碰块，但存在真实接触穿透风险。不能将此回填为成功或单独归因于 Astra 空间决策。
- 完整抓取—交接—放置 **未由本轮完成**。正常抓取释放回归和 D4 空手移动通过都不能代替整任务成功。

## 实际四视角回放

原始记录根目录（仅保存在 yanglab）：
`/home/tongji/alex/rm65-contact-servo-yanglab-20261017/experiments/rm65_handoff_v1/evidence/interface_repair_yanglab_20261017/`

每个目录都有 `execution.mp4`、原始物理日志、数值轨迹、执行回执、实际四视角 RGB；摘要及 SHA 见同目录 `PUBLIC_LIGHT/`。没有合成图像冒充渲染。

| 独立 reset 回放 | 结果 | 最终物理步 | 最大指垫穿透 |
|---|---|---:|---:|
| contact_d1_original_01 | 原动作接触锁定后保护中止 | 11837 | 2.191056 mm |
| contact_d1_readback_02 | 增加只读伺服采样，精确复现 | 11837 | 2.191056 mm |
| contact_d1_left_v4_01 | 独立候选：左锁定后 D=0，失败，不采用 | 11829 | 2.371140 mm |
| contact_d1_slow2_01 | 独立候选：闭合 ramp 时间翻倍，失败，不采用 | 12020 | 2.045333 mm |
| sequential_d4_01 | 原 D4 全部 38 组执行完成 | 36150 | 0 |
| vacant_table_01 | 实测 Support Link/table 禁碰被拦截，负对照通过 | 14542 | 0 |
| grasp_release_01 | 正常抓取、独立抬起持物、显式释放回归通过 | 9567 | 0.099725 mm |

正对照的独立 2 秒持物：持续双侧接触且无其他支撑，相对漂移/转角远低于 2 mm/5°，该窗口最大穿透 0.053216 mm。显式 opening=1 后双侧接触解除，最后 2 秒连续桌面支撑、物块位置不变。抬起和释放是离线单独测试输入，执行器没有自动插入；这不是完整任务放置。

负对照沿用已声明的 D1 世界 Y +0.12 m 空桌面测试，其余请求不变。双侧接触尚未建立时，FCL 检出 `L__ctag_Right_Support_Link/table` 并停止。它是安全回归，不是修改后的 Astra 答案。

## 最小控制对照的依据及限制

原 D1 第 11820 步锁定，保持目标约 −0.452033 rad；第 11837 步实际主关节约 −0.466785 rad，已比目标更闭合。没有目标覆盖或盲目提高夹紧力。

只读采样显示：第 11818 步实际位置差分 −1.185261 rad/s，而步前原生 qvel 为 +3.961776 rad/s；第 11837 步分别为 −0.700139 与 −9.688465 rad/s。两种量不一致，不能把原生速度直接解释为实际关节运动，也不能把显式 PD 推算当作 PhysX 实测驱动力矩。原生驱动力矩仍记为未知。

因此仅做了两个有界单因素候选：移除左接触保持阻尼；或者保持所有 K/D/限力、将闭合 ramp 从 150 步改为 300 步。均未通过，**均不作为正式控制器修复启用**，不再继续参数扫描。右侧已验证控制器、质量/摩擦、模型目标、预压和 2 mm 保护均未改。候选失败不证明唯一引擎根因，也不证明所有抓取都不可执行。

候选代码只由离线 replay 显式选择；`run_episode.py` 默认控制没有采用这两个候选。后续需另行确认此接触构型的执行限制，不能依靠降低阈值、修改原提案或强行继续取得 PASS。

## 一致性和环境

- D1 关闭前 step11675，与历史完整 arms、接触、物体位姿/速度、目标和双侧接触状态逐项相等。
- D4 前按原前三条提案和归档执行函数重建至 step27325，同样逐项相等；没有只写 qpos 或绑定物体。
- D4 stage2 的原 index0：34425→34650；原 index1：34650→34875。后一操作起点采用前一回执的实测 TCP。
- 59 项离线测试通过；19 份当前工作区已追踪历史 ledger 与基线字节相等。原实际 full-task ledger 仍 STOPPED，reserved_budget=4，runs=4；未使用剩余预算。
- NVIDIA RTX3060 /535.230.02；Python3.10.19、SAPIEN3.0.0b1、mplib0.2.1、NumPy1.26.4、SciPy1.10.1。使用现有56项哈希校验资产，无依赖升级。
- 1.1m 布局、四视角、原生监控、IK、碰撞矩阵和旧评分未改。七份视频在主机完整解码验证；原生物理数据和所有失败保留。

## 复现

```bash
ssh yanglab
cd /home/tongji/alex/rm65-contact-servo-yanglab-20261017/experiments/rm65_handoff_v1
source runtime.action-chunk.yanglab.sh
"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests transfer_safety_tests full_task_prep_tests chunk_protocol_tests contact_guard_tests -q
# 输出必须是不存在的新目录；原D1预期触发保护，不越过停止继续执行。
"$RM65_PYTHON" interface_replay.py --case contact_d1 --output evidence/NEW_d1
"$RM65_PYTHON" interface_replay.py --case sequential_d4 --output evidence/NEW_d4
"$RM65_PYTHON" interface_table_negative.py --output evidence/NEW_table_negative
"$RM65_PYTHON" left_grasp_semantics_physics.py --mode bilateral_hold --release-regression --output evidence/NEW_grasp_release
```

拒绝候选的精确复现选项分别为 `--left-contact-hold native_damping0_v4`、`--contact-closure-time-scale 2`，不能把其物理失败替换原模型结果。此处不提供真实模型启动授权。

只发布必要源码、此报告及 `PUBLIC_LIGHT` 小摘要/哈希；视频、RGB、完整日志、NPZ、重复源码快照保留执行主机，未上传。
