# 完整抓取接口修复：代码初版，物理验收待完成

基于 `624d80f`，独立分支 `codex/rm65-contact-preflight-sequential-fix-20261016`。

**本轮真实Astra请求为0。14项本地单测通过；P0原始Decision1及P1原始Decision4的物理回放尚未运行，不能宣布修复已通过物理验收。** yanglab的`100.78.222.78:22`在创建独立工作树后持续SSH超时，脚本同步也失败。本轮没有连接Mac Bridge或写入历史STOPPED ledger。

## 已实施的P0改动

`contact_preflight_v2.py`和`DualScene.execute_group()`将明确的`bilateral_hold`闭合与确定的数值运动分开：

1. TCP/手臂轨迹、非接触模式闭爪和开爪保持原完整FCL预检。
2. 对接触依赖闭合，手指以当前实测状态参与静态手臂预检；预检明确标为`CONTACT_DEPENDENT_NOT_PROVEN_BY_EMPTY_SPACE_RAMP`，不把最终空载过闭合状态当作接触控制实际会到达的状态，也不声称已经证明闭合安全。
3. 执行时保留原开度目标、原闭合ramp、两次连续双侧接触后锁定及原有限预压；新增每个4ms物理步前/后的实测共享场景FCL检查，settling阶段同样逐步检查。使用原planner的`update_from_simulation()`刷新实际构型/物体；保持原组起点已确定的holder，并刷新其相对碰撞表示，不因闭爪中的新指垫接触而偷偷将仍受桌面支撑的方块提升为“已搬运物体”。不改任何PhysX物体位姿。
4. 仅保留原ACM指垫—物块例外；桌面、非预期连杆、互臂等禁碰不增加例外。出现禁碰几何立即保护停止。原生`tick()`、2mm穿透保护、自碰撞、关节/跟踪保护逐字保持。
5. `contact_guard_PRIVATE.jsonl`记录实测主关节、servo target、夹垫间距、FCL禁碰对、原生全部接触点/法向/冲量/分离距离、双侧接触与锁定时刻。原生保护先触发时保留最后物理记录，绝不为继续调查而越过保护。

这不是对`opening_fraction=.15`的特判，也没有修改其数值。若禁碰先出现仍会拒绝/中止。若第一次禁碰与第一次双侧接触落在同一4ms采样，必须报告“同一采样内先后未知”，不能臆断因果。

**尚未验证的部分：** 原始0.027m/.15方案是否确实在建立正常夹持前撞桌；实测FCL与原生接触的先后；正常已有夹持路径是否会被新守卫保守拒绝；物理安全负对照。因此P0目前状态为`IMPLEMENTED_UNVERIFIED`。

## 已实施的P1改动

`chunk_protocol_v2_1.py`是公开schema和顺序调度的单一来源，版本`numeric_chunk_v2_1`，保持原JSON动作结构与数量上限。

- sequential按原列表逐项生成/执行。允许同一臂重复TCP、夹爪及混合操作。后一个操作的节点只在前一操作执行完后，使用该臂最新实测TCP生成。
- 相同目标的两个顺序操作仍是两个独立操作；不去重、不合并、不覆盖。
- 仅parallel使用按arm的流映射，且先拒绝重复arm，避免同一机械臂并发冲突。
- 回执增加原输入动作index与每项操作起点的实测TCP，便于验证顺序及起点。
- 原总数值子组上限仍为128；在每个子组执行前检查预算，部分执行会明确返回。

公开schema的`description`与`conventions.ordering`明确上述规则。原Bridge支持的保守JSON-schema子集无法表达“数组对象按arm属性唯一”，因此parallel这一跨项限制明确属于公开语义校验，而非声称结构schema能独立强制。顺序同臂合法，不再出现上轮的隐藏sequential限制。未改原生产Bridge/schema编译器。

## 实际通过的离线检查

使用现有Mac bridge venv（未安装依赖）：

```
python -m unittest chunk_protocol_tests contact_guard_tests -v
Ran 14 tests ... OK
```

包括：

- 624d80f原始Decision4的公开schema与控制语义验收通过，答案未修改。
- 顺序同臂、同臂混合操作、相同操作不去重、后续操作读取前一操作后的实测状态。
- parallel同臂冲突在调度前拒绝，合法左右臂保持重叠调度。
- 原Bridge的schema编译器接受新schema。
- 安全守卫不根据目标值或是否已锁定放行桌面/非预期连杆禁碰。
- 原生监测、IK、ACM、接触判定与锁定函数AST一致；1.1m布局、右侧控制器、评分与持物碰撞代码字节一致。
- 所有Python源文件语法检查通过，`git diff --check`通过。

上述是协议与守卫单元测试，**不是PhysX抓取成功证据**。完整旧测试及新增数值执行器集成测试尚待yanglab运行。临时安装NumPy被自动审批拒绝，未执行；已改用现有依赖完成上述本地测试。

## 原始拒绝能说明什么

`evidence/interface_repair_20261016/original_refusal_audit.json`从原归档提取：Decision1最后子组是左臂`opening=.15/bilateral_hold`，预检index105拒绝，`executed=false`，原实际状态停在step11675，未建立双侧接触。

该index对应空载预测，不是已经执行的物理步。因此只读原日志不足以确定危险实际发生在接触之前还是之后。**目前既不能认定原拒绝一定错误，也不能宣布.15可以安全抓取。**

## 已准备的有限物理回放入口

`interface_replay.py`只读归档raw，不调用Bridge。它从正常桌面空手初态推进物理，重放原动作，不设置物体姿态、绑定物体或只恢复机器人qpos。

- `legacy_d1`：使用归档624d80f执行函数及chunk，要求复现index105，并逐项比较step11675的关节、物体位姿/速度、drive targets与双侧接触。
- `contact_d1`：原始Decision1通过新执行器，任何实际保护立即停止，保留完整动作与接触日志。
- `sequential_d4`：使用原始前3条及原执行函数物理重建step27325；先核对实际状态精确一致，再把完全相同的Decision4交给新执行器。这样不会因新的D1闭合路径改变，而把另一种初态冒充旧D4回放。

恢复yanglab后，在同步本分支到其独立worktree并核对后使用：

```bash
cd /home/tongji/alex/rm65-contact-preflight-sequential-fix-20261016/experiments/rm65_handoff_v1
source runtime.action-chunk.yanglab.sh
"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests transfer_safety_tests \
  full_task_prep_tests chunk_protocol_tests contact_guard_tests -v
"$RM65_PYTHON" interface_replay.py --case legacy_d1 \
  --output evidence/interface_repair_20261016/legacy_d1_01
"$RM65_PYTHON" interface_replay.py --case contact_d1 \
  --output evidence/interface_repair_20261016/contact_d1_01
"$RM65_PYTHON" interface_replay.py --case sequential_d4 \
  --output evidence/interface_repair_20261016/sequential_d4_01
```

每次回放必须用新输出目录；脚本记录结果，不自动重试。三个案例是独立reset；任一案例触发保护后不继续其物理执行。

另须运行已有`left_grasp_semantics_physics.py --mode bilateral_hold`正常夹持回归及已存危险负对照，确认实际指垫接触仍可建立、危险仍被阻止。不得用单测替代这些物理验收，也不得把该工程回归目标放入Astra决策。

## 当前交付状态

| 项目 | 状态 |
|---|---|
| P0接触一致安全流程代码 | 已实施，物理未验收 |
| P1原始D4协议/调度逻辑 | 本地测试通过 |
| P1实际SAPIEN顺序回放 | 未运行 |
| P2原始D1、D4物理结果与视频 | 待yanglab连接恢复 |
| 原0.15拒绝是否合理 | 尚不能由现有记录判定 |
| 完整任务执行层是否已解除阻塞 | 尚未证明 |
| 真实Astra生成 | 0 |
| 新授权/旧ledger恢复 | 无 |

目前唯一继续物理验收所缺的是yanglab远程连接。不要用此分支开始新的真实模型回合。
