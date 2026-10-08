# E1-Async / E1-B v1 设计卡

状态：离线延迟 stub 增量。不是真实 Astra 性能结果。E1-B 属于 E1；E2/E3/E4、双臂、多 agent、B2 均不在范围。

## E1 分类与冻结边界

- E1-A：既有 M 单原语 / S 完整技能、`physics_paused` 调度。冻结运行时 `1b5e1842e90887d347819daefa422cbabea29c21`；四回合账本 `69aae843cca898541059fc02d1878bd2e44f6889`。
- 四回合历史目录：`/home/alex/astra-realman_ws/astra-sim-ms-pilot-delivery-20261008`。10 次真实调用，所有回合均保留。其归档 SHA256 为 `2ef5eac09bbdb7ba9ec533c29bf1e05ff666e1bb9bc14b018ba998a066cd0d8a`。
- 更早的 `f7c8da1`、`3e7fcd5`、首次 CLI 启动失败和后续单 S 成功仍为历史/通道证据。此卡只新增索引分类，不改任何旧报告或哈希。
- E1-B：RTC-inspired 技能级前瞻。这里借鉴“执行已批准动作时计算下一段”的概念；未实现或声称复现 RTC 的动作块去噪、轨迹拼接或训练算法。
- 旧 E1-A 的暂停物理结果不能作为 E1-B 同步基线。B0 必须在新时间协议下重测。

## 最小可运行决策任务

保留同一 held 初始化、三路当前 RGB、公开目标表、四原语展开、控制器、规划器、每步监控、每原语 holding/slip 检查和独立评分。无新物理参数或速度。首版两个 skill 是同一原语目录的前缀/后缀：

1. `approach_checkpoint` = approach。初始任务只要求把 held 物品移到既有接近点，后续交付指令尚未发布。决策可批准此动作、保持或 STOP；不能提前批准释放。
2. `finish_place` = release_pose → release → retract。approach 的第 100 个物理步后，发布独立公共任务指令：“放到固定绿标”或“保持物品，不得释放”。该信息决定是否继续释放；它不是物体 GT、接触真值、预测成功或评分。取消指令必须改变行为。

B0 在 approach 完成后才发第二请求；B1 在任务指令发布时只发一个前瞻请求，同时继续已批准的 approach。两组都在任务发布点捕获三图，也都在实际接续点捕获新三图。B1 不把执行中的 RGB 当作接续点实拍；提交门使用当下真实本体状态和原公共检查。B0 的请求观测比 B1 新，这是异步的内在信息龄差异，须报告，不能声称输入状态精确相同。

这是**延迟任务信息的协议 fixture**。stub 直接映射文本；它不证明语言理解，也不声称这一简单二选一必须使用 LLM。阶段二之所以存在，是任务信息晚到，而不是为了凑调用数。不得在初始全知任务中人为插入这一事件。若真实场景允许提前生成条件计划，未来必须把条件计划控制器列为强基线；当前 concrete-skill 协议没有条件分支解释器，不能据此宣称异步优于所有规划方式。

`known-goal` 起点已知完整任务：保留 `full_place` 四原语单次完整计划强基线；B0/B1 均只允许一次请求，不能机械拆成两次。它不是 delayed-goal 配对样本。

## 进程与调度边界

- 唯一 owner 进程/线程拥有场景、render、检查、执行和评分。通过冻结 scene 已有 `step_hook` 加入节奏；不编辑旧物理代码。
- 一个 Python stub 子进程只读 `input_only` 中的不可变 JSON 和三张图；输入逐份 SHA256，文件只读。owner 不把 backend、场景、GT、接触或评分对象交给 worker。文件投影与单 worker 边界不是通用操作系统沙箱声明。
- 最大 1 个 in-flight 请求、1 个待提交候选；有候选时也不能再开请求；无自动重试，无后台队列。
- 复用 `1b5e184` 的 `worker_environment` / `worker_paths`，保留 nvm launcher 目录和白名单；SAPIEN 入口先用既有 preflight 执行版本/help 检查，不传提示词。
- 本轮 worker 是延迟 stub，**不运行 Codex infer**。后续真实 worker 应直接调用既有 `codex_astra_mac_bridge.infer`，复用其工具关闭/输入隔离/medium，不能另开服务；真实 adapter 尚未在此入口启用，需先完成接口映射离线审查。

## 候选契约与提交

快照绑定 run_id、source_observation_id、source_step、当前执行计划完整动作及 hash、expected_join_id、目标 revision、goal_epoch、完整公开目录/展开及单位/frame/tool/来源。预期接续 pose 标 `EXPECTED_NOT_OBSERVED`。snapshot SHA256 绑定附件哈希；候选必须原样回传 binding 和适用条件，只允许 offered skill / hold / stop。

接续点由 owner 读取新实际 state：来源观测保持原 ID/step；不改旧 ID/revision，不重复施加 delta。接续 pose 位置误差 <10 mm、姿态误差 <0.05 rad，符合原 move 成功阈值；随后仍逐原语运行原 holding/slip 检查。计划/接续点/目标版本/goal_epoch 改变、父执行失败、STOP、超时、畸形或过期结果均不采用。候选消费一次，失败也不能重交。目标取消测试更新的是实际公共任务内容与 goal_epoch，冻结几何目标 revision 不改。

有效绑定的 STOP 在收到后的首个 owner 步边界取消 worker/当前执行并禁止新动作，不要求达到预期接续 pose；外部 STOP 同样终止。普通缺候选/hold 在保持原 drive targets 的情况下推进物理，离线验收窗口结束后终止回合，绝不隐式释放。执行或协议异常停止回合，不重试。独立物体评分只在完整技能执行后记录，绝不进入 worker 输入。

## 离线入口

在仓库根目录执行（输出目录必须全新）：

```bash
/home/alex/astra/.venv/bin/python astra_realman_harness/scripts/run_e1_async_offline.py \
  --output /tmp/e1-async-unique-B1 --condition B1 --backend fixture --delay-s 0.25
```

真实仿真物理 + stub（无模型）：

```bash
/home/alex/astra/.venv/bin/python astra_realman_harness/scripts/run_e1_async_offline.py \
  --output /tmp/e1-async-unique-sapien-B1 --condition B1 --backend sapien \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --delay-s 0.8 --video
```

B0 只换 condition；强基线追加 `--scenario known-goal`。故障 fixture 使用 `--case target-change|execution-failure|late|stop|model-stop|deny`；其中 late 测试请求应设 `--request-timeout-s 0.3 --delay-s 0.01`。入口不存在 local-cli 或硬件选项。`report_e1_async_offline.py OUTPUT_ROOT` 输出 rollup.json、REPORT.md、timeline.svg。
