# shared_workspace_yield_v1：零生成接入验收

基线 `2a98dfc`；实际离线验收代码 `150d364`；唯一执行主机 ubuntu-robot。新增真实 Astra 客户端请求 **0**。旧 STOPPED ledger、剩余 11 次及全部历史结果保持原样。本轮没有持物实验、控制参数扫描或硬件连接。

## 任务与执行职责

入口仍为 `run_episode.py --task shared_workspace_yield_v1`，复用现有 Mac Bridge 传输、严格解析、CLI 事件验收、数值 IK、共享世界整段碰撞预检与执行器。没有新增 HTTP 实现、自动避障或让行技能。

初始化只执行左臂到共享目标，完成固定物理观察后停止专家逻辑；右臂保持 Ready。每个新进程重新 reset，shadow 与 execute 的首次上下文均为空历史，shadow 提案不进入执行回合。

公开任务仅规定右臂占位、随后左臂占位和最终目标。没有“先让左臂退让”的提示，也没有见证中的左 Ready 中间目标、见证序列、负对照回执或私有评分。模型得到两个共享目标 TCP、实测初始右 Ready 终态目标、当前四视角 RGB/标定、双臂状态、最近两条原提案/回执和原数值 schema。TCP 为两夹垫实际中心均值，姿态为世界 Link6 四元数 wxyz。

模型负责所有初始化之后的动作目标、先后/并行、调整与停止。控制器只做原 IK、固定关节插值、预检和安全拒绝；不修改模型目标。

## 时间语义与冻结评分

`workspace_criteria_v1.json` 已在模型调用之前冻结；SHA-256 `4d3c23d08e1a009c847662d9cc4f017a1b2a468728631bbe75199ab60047589c`。独立评分器为 `evaluate_workspace.py`，旧 `evaluate_transfer.py` 和 CTAG 判据未改。

- 每个成功数值动作组结束后清零机械臂关节速度目标，保持最终驱动目标，推进 **125 步 × 0.004 s = 0.5 s** 真实物理观察。顺序组各自观察，并行组共同观察；没有插入移动。旧任务仍保留原 100 步默认值。
- 模型停止或达到执行决策上限后，正常回合再保持 **500 步 = 2 s**。物理保护、协议或传输异常立即停批，不为评分继续推进。
- 右臂在给定位姿持续至少 0.5 s；完成后左臂再持续至少 0.5 s，初态左占位不算后续阶段。
- 最后连续 2 s 左臂在目标、右臂在本回合实测初始 Ready，双夹爪保持打开，无互臂或非预期机械臂/桌面接触。检查完整窗口，不只末帧。
- 位姿容差沿用已验证数值接口：10 mm / 0.05 rad；开度 >70 mm；原 2 mm 物理保护继续生效。桌面/安装座只允许相应 base link 的安装接触。
- 以实际物理记录评分。shadow、初始化失败或协议/基础设施故障标记 NOT_SCORED；合法提案的任务或物理失败与基础设施故障分开保存。预算截断不代表模型永远无法完成。

## 验收记录

| 项目 | 结果 |
|---|---|
| 新旧协议、鉴权、403/409、严格 JSON、完成事件、参数漂移、超时/取消不重试 | PASS |
| task_policy 缺失/篡改、图像 SHA、GT 私有字段隔离 | PASS |
| 新旧权限及物理评分单元测试 | **35/35 PASS** |
| 独立模拟 Bridge shadow | PASS，1 条假回答，未执行动作 |
| 独立 reset 后模拟执行 | PASS，7 条假回答；保留非法目标原提案及原拒绝反馈 |
| 原执行器顺序/并行与观察时间 | PASS；并行组实际双臂同一步运动持续 0.5 s；每组末尾观察 0.5 s |
| 末尾连续 2 s 与独立重评分 | PASS，与运行评分逐项一致 |
| 未授权草稿传给真实一次性入口 | PASS：仿真/派发前拒绝；ledger 字节不变、无输出回合 |
| Mac ChatGPT、原 Bridge、190 s、反向 SSH 和认证 | PASS：北京时间 2026-10-15 16:04:47，认证404 / 错误认证403；未请求 `/decide` |
| 旧 473 份归档及 STOPPED ledger | 哈希核验 PASS |
| 新真实模型请求 / 预留预算 | **0 / 0** |

模拟回答只是工程接口测试，不是 Astra 表现。前两次单元验收的局部变量遮蔽和 sparse checkout 缺文件失败日志均保留；修复后的最终结果为上述 35/35。

Mac 生产脚本 SHA 仍为 `922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae`，模型、medium、ephemeral 和 Code Mode 开关均保持原样。Ubuntu 不存在旧 yanglab 传输口令路径，因此仅为此连接配置独立 Bearer 口令，保留原认证方式；ChatGPT 认证与旧口令均未修改。口令位于 Git 之外的私有目录，没有归档或进入模型输入。

## 新批次与授权草稿

- Batch ID：`8ab36cee132046909da2285fde4b4bc3`
- 绝对根目录：`/home/alex/astra_spatial_capability/rm65-workspace-astra-prep-20261015/experiments/rm65_handoff_v1/evidence/workspace_runs/first_workspace_20261015_01`
- `ledger.json`：**DRAFT**，reserved_budget=0，runs=[]，authorization=null。
- `authorization_REQUEST_NOT_GRANTED.json`：generation_authorized=false，max_dispatches=0；仅规划 **1 shadow + 最多 7 execute = 8**。
- 授权绑定版本、task、batch ID、绝对目录和 26 项源代码/资产 SHA。派发前原子预留，单 worker，180 s 客户端 / 190 s 服务端，不自动重试。未知完成状态立即 STOPPED，不恢复。
- 服务与隧道当前在线待命，未创建任何生成作业。生产预检门禁要求不超过 **15 分钟**；新授权到达后必须重新做实际非生成检查，不能仅改时间戳。

## 运行命令

零生成验收命令（输出必须换成不存在的新目录）：

```bash
cd /home/alex/astra_spatial_capability/rm65-workspace-astra-prep-20261015/experiments/rm65_handoff_v1
source runtime.decision4.ubuntu-robot.sh
"$RM65_PYTHON" -m unittest workspace_tests transfer_safety_tests
"$RM65_PYTHON" transfer_offline_test.py --task shared_workspace_yield_v1 \
  --output evidence/workspace_preparation_20261015/NEW_MOCK_OUTPUT
```

收到新授权后，先将该授权与同一 DRAFT 绑定成 `authorization_GRANTED.json`，并保存新的 Mac 实测证明。Ubuntu 非生成预检仍用原安全路径：

```bash
B="$PWD/evidence/workspace_runs/first_workspace_20261015_01"
"$RM65_PYTHON" transfer_preflight.py --task shared_workspace_yield_v1 \
  --budget-root "$B" --bridge-config "$B/bridge_config.json" \
  --mac-proof "$B/mac_readiness_FRESH.json" --output "$B/production_preflight_FRESH.json"
```

然后一次性运行 shadow → 独立 reset → 最多7次执行决策：

```bash
bash workspace_authorized_once.sh "$B" "$B/authorization_GRANTED.json" \
  "$B/production_preflight_FRESH.json" "$B/bridge_config.json"
```

**当前没有 GRANTED 文件，不能派发。** 一次性脚本不会生成授权；shadow 无效就不进入 execute。重复启动会被已有回合/ledger 门禁拒绝，不会补预算。

独立重评分：

```bash
"$RM65_PYTHON" evaluate_workspace.py "$B/execute_01"
```

验收原始输出、模型参数协议样本、视频、轨迹、接触、失败日志、Mac CLI 检查和汇总在 `evidence/workspace_preparation_20261015/`。旧 ledger SHA 仍为 `2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1`。
