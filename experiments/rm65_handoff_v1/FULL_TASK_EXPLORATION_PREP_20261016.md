# 完整物块任务：夹爪状态与单局探索准备

基于 `8cd224e` 的功能与 `582732b` 的 yanglab 部署增量实施。执行主机仅 yanglab；本轮真实模型请求 **0**。

## 本轮修改

`gripper_state_v3.py` 只补充回执语义，不改变驱动、开度映射、联动或接触参数：

- `command_execution=EXECUTED`：闭爪命令已物理执行；不代表抓取成功。
- `contact_hold_state`：`NOT_REQUESTED`（position）、`NOT_ESTABLISHED` 或 `ESTABLISHED_AT_COMMAND_END`（接触保持）。后者也不证明抬起后稳定持物。
- `stable_grasp=NOT_ASSESSED_BY_SERVO`：稳定抓取只由离线实际物理记录独立判断。

未满足 `bilateral_hold` 仍保留原 `ok=false`、原原因与原始接触值；新增 `failure_scope=REQUESTED_CONTACT_HOLD_CONDITION`、`recoverable_action_feedback=true`、`task_grasp_verdict=NOT_DETERMINED`。当前 chunk 停止，回合继续获取新的模型决策。没有自动抬起或重试。`position` 继续忠实执行模型开度，不做接触锁定。物理保护、未知异常与协议故障仍立即停批。

模型只收到控制器状态及数值执行回执；原始接触点、物体 GT、私有评分、专家目标不进入 context。`latched` 和原始 `bilateral_contact_at_end` 仍从公开历史中移除。控制器状态不是抓取成功评分。

## 实际离线验收

| 检查 | 实际结果 |
|---|---|
| 新旧离线协议/权限测试 | 42/42 PASS；含原超时取消、403/409、重连/参数异常、输入隔离、原子预留、未知状态不可恢复、授权/上下文绑定 |
| 模拟 Bridge：接触未就绪 | 3 次本地模拟回应；未就绪闭爪后仍接收下一次独立决策；无自动抬起；完整任务评分 FALSE |
| 模拟 Bridge：原 chunk 回归 | 2 次本地模拟回应；四视角、正常桌面初态、顺序/并行及零推理期间物理推进通过 |
| 左臂原接近 + `bilateral_hold` 0.45 | 闭爪已执行，末尾双侧接触 FALSE；原 hold 条件失败保留，不能据此判整次抓取失败 |
| 单独提交原工程抬起数值目标 | chunk_v2 实际执行通过；随后 2 秒双侧接触、无右臂/桌面支撑；相对平移漂移 0.000240 mm、转动 0.0000667°，最大夹垫穿透 0.053216 mm |
| `position` 0.45 同接近对照 | FAIL，step 1436 的左夹垫穿透 2.130192 mm；原保护实际停机，不提交抬起、不改闭合值。这不意味着所有 position 闭爪必然失败 |
| 独立重评分 | 四份新运行的原评分均与独立重算一致；无历史评分覆盖 |

闭爪期间左臂六个关节 drive targets 的变化严格为 0。代表性 TCP 高度随手指联动从约 40.075 mm 变至 26.440 mm；它不是固定 flange，也不是偷偷加入抬起。完整证据见 `left_state_transition_audit.json`。

这些工程输入只存在私有验收脚本，不被在线入口导入。测试只证明状态语义和执行接口；不声称完整抓取—交接—放置已经通过。

右侧 `master_damping0_v3`、1.1 m 布局、Ready Pose、四相机、碰撞保护和原评分文件逐字节保留。历史 3° yaw 穿透失败仍在 `evidence/yanglab_migration_20261016/yaw_boundary_01/`，本轮没有锁姿态或重写该结果。

## 单局冻结 DRAFT

- Batch ID：`ba904d1bf5e441c3b5ec105fe5312147`
- 绝对根目录：`/home/tongji/alex/rm65-full-task-exploration-prep-20261016/experiments/rm65_handoff_v1/evidence/full_task_runs/full_table_exploration_20261016_01`
- `ledger.json` 为 DRAFT，`reserved_budget=0`，`runs=[]`。
- `authorization_REQUEST_NOT_GRANTED.json`：`generation_authorized=false`、`max_dispatches=0`；**拟申请最多 16 次执行决策，无 shadow**。
- 冻结 101 项源码/配置/原生产 Bridge 与传输依赖 SHA256。单 worker，`gpt-6-astra / medium`，独立 ephemeral 会话、180/190 秒，无自动重试。
- 新 Gate 复用原原子预算与文件锁；在传输前预留。完整回合不可重新启动，FINISHED/STOPPED/TRUNCATED 均不可恢复。不同任务旧 ledger 不能用于本 Gate。
- 唯一入口从红方块在桌面、双臂空手打开开始，只有正常 reset/100 tick settle，没有工程抓取初始化。最近原始提案与公开回执最多两条。
- Astra 决定全部 waypoint、姿态、开度、时序、交接、退出与放置；执行器仅原 IK、5 mm/1°通用细分、跟踪、夹持伺服与保护。不选择绕障关键点。
- 接触条件未满足与合法 IK/碰撞拒绝可反馈再决策；保护触发/协议异常/传输异常/完成状态未知立即停批。原始模型结果、事件、usage/缓存、延迟、轨迹、四视角视频与独立评分分别归档。
- 保留历史 `evaluate_process` 速度与阶段口径，不把新语义或新工程持物证据回写为旧评分 PASS。该历史输出中的 `model_calls=0` 是旧评分器固定字段，真实派发数以新 ledger/episode 为准。

## 非生成生产预检

2026-10-16 实际确认：Mac ChatGPT 登录正常；原 Bridge PID 6335、源码 SHA `922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae` 不变，服务端 190 秒。新独立 yanglab SSH reverse tunnel PID 86159 连接原 `18767` 至 yanglab `127.0.0.1:18766`；没有修改原服务、代理、SSH 配置或既有会话。

首次绑定此 batch 的 Mac 预检 PASS；yanglab 资产检查通过，但旧认证与故意错误认证均返回 403。保留该 FAIL 记录。只使用认证后的未知路径 `/rm65-transfer-auth-check`，**没有访问 `/decide`**。原认证 token SHA 与当前 Mac 服务不一致。

自动审批首次拒绝向新远端私有路径复制当前 token，理由是当时尚未明确授权。用户随后明确回复“允许私密同步，仅做非生成预检”，之后才同步至 `/home/tongji/.local/state/astra-full-task-20261016/`（目录0700、文件0600），未改原 Bridge、认证方式或推送凭据。

刷新后的 `mac_readiness_02.json` 与 `host_preflight_02.json` 均 PASS（2026-10-16 06:22 UTC）；真实/错误认证为404/403，56项资产通过，代码101项哈希一致。DRAFT仍为0次预留，没有GRANTED。生产预检不等于生成授权；未来开跑仍需本任务的新明确预算及15分钟内重新预检。

## 复现与未来启动

离线命令（请使用新输出目录，不覆盖已有证据）：

```bash
ssh yanglab
cd /home/tongji/alex/rm65-full-task-exploration-prep-20261016/experiments/rm65_handoff_v1
source runtime.action-chunk.yanglab.sh
"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests transfer_safety_tests full_task_prep_tests -v
"$RM65_PYTHON" full_handoff_offline_test.py --action-interface chunk_v2 \
  --right-hold-control master_damping0_v3 --contact-timing --output /tmp/rm65-close-timing-new
"$RM65_PYTHON" left_grasp_semantics_physics.py --mode bilateral_hold --output /tmp/rm65-left-close-lift-new
```

未来须先由用户明确批准此 batch 的最多 16 次新请求。保持 REQUEST 文件绑定字段不变，仅据新授权另建私有 GRANTED，设置明确预算和授权原文；本轮没有创建 GRANTED。刷新同 batch 的 Mac proof（仅 version/help/login/listener/tunnel，无生成）：

```bash
# Mac：现有 bridge venv，输出必须新建；有效期最多15分钟。
cd /Users/tangchao/Desktop/资料/P7/rm65-full-task-exploration-prep-20261016/experiments/rm65_handoff_v1
/Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013/experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python \
  full_task_preflight.py mac --batch-id ba904d1bf5e441c3b5ec105fe5312147 \
  --service /private/tmp/rm65-workspace-bridge-20261015/service.json \
  --tunnel /private/tmp/rm65-full-task-bridge-20261016/tunnel.json \
  --output /tmp/rm65-full-task-mac-FRESH.json
# 将无凭据的 proof 传到下方 B/mac_readiness_FRESH.json。
```

正式一次性启动（**当前不可执行：尚未获得真实生成授权**）：

```bash
cd /home/tongji/alex/rm65-full-task-exploration-prep-20261016/experiments/rm65_handoff_v1
B="$PWD/evidence/full_task_runs/full_table_exploration_20261016_01"
bash full_task_authorized_once.sh "$B" "$B/authorization_GRANTED.json" \
  "$B/mac_readiness_FRESH.json" /home/tongji/.local/state/astra-full-task-20261016/bridge_config.json
```

该私有 config 已在获得同步许可后创建；脚本不会复制凭据、授予权限或自动重试。入口重新执行 host 非生成预检，检查新鲜 Mac proof、同批次哈希、56 个资产与认证后，才允许一次闭环。

原始证据：`evidence/full_task_preparation_20261016/`。25 份 JSONL 以无损 gzip 和 SHA256 清单归档，原文件留在 yanglab。原 STOPPED ledger SHA `2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1` 不变，5 次已用、11 次历史余额未使用。
