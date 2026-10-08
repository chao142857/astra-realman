# 实施顺序与实际源码复用

这是方向更新的待办清单；本次没有把B/F标成已运行。源码基准 `1bb8e6b9d40768af7f03532e4176fb3fb2f21196`；各被读文件hash见 SOURCE_AUDIT.json。

## 1. 已核实能力与最小缺口

路径未注明根时相对 `astra_realman_harness/`。旧源 `/home/alex/astra/scripts/` 是只读参考，不直接启动其服务；冻结物理资产为 `/home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets`。

| 现有源码 | 可复用事实 | 新任务要补的薄增量，不能误称已实现 |
|---|---|---|
| 冻结 `scripts/rm65_scene.py`：observe/move_tcp/gripper/tick/monitor | 已有三图、7D pad-center动作、开闭夹爪、接触预载、轨迹/碰撞/跟踪检查与step_hook | 继续同一scene/控制器；主进程独占hook，统一调度与私有评分钩子，不能两个owner覆盖 |
| `sim_skills/rm65.py` | 资产hash校验、三图、本体白名单、旧独立放置评分 | **setup_held用物体GT抓取，禁用**；旧check假定held；旧execute的任意set_gripper后都会300步settle并detach，不能拿来当闭夹爪抓取 |
| 旧源 `rm65_model_bridge.py` ModelAdapter.dispatch/observe/update_payload/finish | 已有1–3 action chunk、绝对pose、gripper、hold、标定、payload更新及全任务抓起/掉落/放置评分 | 冻结引用源码hash后复用动作分派/校准/评分逻辑，增加assembly校准和退出/结果判断；不启动旧AF_UNIX main，不使用其单latest/consumed校验冒充异步候选门 |
| `sim_skills/async_v1.py` | 已验证共同节奏、frozen worker、单slot、源绑定、新状态门、STOP/晚到/重复拒绝 | 将固定approach/finish_place调度推广到共同chunk；删除“第100步发任务消息”作为研究情境的依赖；复用机制而非把旧fixture当完整task |
| `scripts/codex_astra_mac_bridge.py` worker_environment/preflight/infer | 现有Node22路径白名单、工具关闭、medium请求、输入隔离、1–4图与取消/原始日志 | owner全局串行调度E/A/B。BUSY只在HTTP Handler取锁，直接infer本身不提供跨进程锁，必须由owner保证单in-flight；不用main/SSH/新服务 |
| `sim_skills/model.py` | 严格状态/反馈投影、PNG/hashes、explicit授权、真实调用记录 | fixed placement catalog与continue/stop schema不是完整task；增加共同chunk信封及来源校验，不复制固定正确目标目录 |
| `history_diagnostics.py`、`e3_history_screen.py` | 完成后插入、同episode去重、截止时间检查、unknown语义与确定性事件投影 | 原transition面向左臂RPY/真机字段，新增模拟wxyz字段映射；不直接伪造left_terminal数据或把模型诊断当实测 |
| `sim_skills/groups.py` | 真实多调用编排骨架、role/parent hash、evidence_only、无executor句柄 | 现parser绑定bimanual高层proposal；改用共同chunk parser的适配，实际独立E/A请求并保存消息；不能仅改role字符串就声称系统完成 |
| 既有 JSONL/时间轴/usage/归档 | 已有可复核记录和失败保留 | 扩展同一账本的role、crop、history、candidate依赖字段；不另建GUI/数据库/调用框架 |

真值边界：保留声明过的FCL碰撞几何、接触预载及载荷几何更新作为共同底层辅助，它们可拒绝危险动作但不向模型提供精确对象/目标位姿。旧full-task `finish()`包含私有GT评分，必须在策略提交关闭后独立调用。旧 `get_state()`不等于物体状态；闭夹爪/ok也不等于持物。

## 2. 实施阶段

| 顺序 | 工作与产物 | 通过条件 | 尚不允许的推断/扩展 |
|---|---|---|---|
| 0 本次 | 冻结旧研究、更新本目录卡片/边界/源码审计 | 旧代码和结果不动，新增真实/硬件额度为0 | 文档完成不等于B/F闭环完成 |
| 1 共同底座薄适配 | 一个完整task owner入口：空夹爪reset、chunk、标定、观测、完成事件、全任务评分；共享时钟/权限/成本；保留旧入口 | offline协议测试及少量脚本/fixture接近-闭合-抬起-运输-释放-退出证明执行能力；脚本GT坐标如使用必须隔离并标非模型 | 不以脚本成功证明视觉闭环，不新建第二模拟器/模型服务 |
| 2 B完整闭环 | 接入共同动作schema、三图/标定/合理历史、observe/finish与错误恢复；先stub验证全部阶段及预算 | 实际发往worker输入无GT/固定目标答案；所有阶段计时/判断可审计；共同控制能力可用 | 未授权真实调用前只交付入口，不宣称B真实模型成功 |
| 3 F最小组合 | 在同一owner加入E→A独立调用、附件选择/ROI、有界来源记忆、单段前瞻与真实接续门 | 独立请求/消息依赖可检查；正常与操作遮挡下可保持/重看；stub重叠、过期/目标变更/父失败/STOP/双提交/ROI与记忆失效通过 | 不要求异步/选图/记忆/分工分别先证明收益；不提高模型并发 |
| 4 B/F真实组合筛查（另授权） | 先正常可见配对，再操作遮挡配对；冻结同版本/共同动作/全部费用；保留失败 | 启动前给出确切回合/总请求/T/K上限和估计成本，显式授权；所有角色和失败占额度 | 旧9请求设计不是授权；不套用M/S成绩、不补跑到成功 |
| 5 组合后替换 | 根据完整结果做必要单项替换和少数关键交互 | 质量/时间/总成本和取消浪费能一起解释，样本量/不确定性如实报告 | 不马上16组全组合，不预设四部分必留 |

阶段2与3可在同一次离线开发增量中推进；“先B”是保证共同任务和比较基准可运行，不是要求B优于某模块，也不是要求四个独立研究先通过。

## 3. 最小验收清单（后续实现时执行）

- 启动和episode起点为空夹爪/桌面物体；禁止调用setup_held或将抓取移到计时外。按实际源码捕获构造/execute调用证明，不只看日志标签。
- B/F同一action_interface_hash、物理资产/控制器/相机hash；移动速度/step节奏一致；全部wait/observe/crop/角色调用成本入账。
- 离线毒化/投影测试：对象GT、目标点、mask、评分、未来图、诊断配置注入observer私有区，最终wire必须没有；以两幅合法不同观测产生不同目标提案的记录检查是否仍硬编码答案。
- 单独验证RGB+标定到实际目标可执行；不得把几何/标定符号错误用更大动作容差掩盖。判定“模型依当前观测可完成”必须等真实授权后的新完整回合，stub不充数。
- 角色E输出动作或A引用未收到图片必须拒绝；parent消息hash不符、同一prompt假分工、多个直接infer进程绕锁必须被识别。
- ROI来源错/相机运动后沿用旧框、遮挡时假装可见、历史未来事件、预测变事实、取消变成功、重复完成事件、未解决失败丢失分别验收。
- 候选源ID不变、commit新观测单列；对象证据不够时保持/重看；不把执行到位当对象不动；同样规则约束B。
- 合法模型stop、外部STOP、API/解析/超时、执行失败、失抓/失落与过早done全部保留。新观察后的显式恢复要新request与父错误记录；基础设施异常无自动重试。
- 最终评分证明抓取/运输/稳定放置/退出，另判模型done正确性；GT评分绝不反馈以便重新试到通过。

本次只完成阶段0。下一步是阶段1–3的离线实现，不是任何真实请求或实验室动作。
