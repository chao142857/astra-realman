# Formal Batch 01 — 零生成验收与授权草稿

零生成准备 **PASS**。本轮新增真实 Astra 派发 **0**；所有模拟 Bridge 结果仅用于工程验收，不作为 Astra 能力结果。

## 请确认的矩阵

| 条件 | 变化 | 独立 episode | 原数值执行器物理见证 |
|---|---|---:|---|
| A_fixed | 原固定共享工位，左臂初始占位，右臂先访问 | 3 | PASS |
| B_shift_y40 | 两臂目标共同向世界 Y +40 mm 平移 | 3 | PASS |
| C_roles_swapped | 右臂初始占位，左臂先访问，终态角色交换 | 3 | PASS |

顺序：`A1 B1 C1 B2 C2 A2 C3 A3 B3`。不安排真实 shadow。每局最多 7 次派发，全局最多 50 次、从首次派发前紧接的原子预留起最多 3600 秒。9 局最坏需要 63 次，因此最后若干局可能被全局上限截断；不补跑、不替换或按结果重排。

完整任务、评分和统计口径见 [冻结方案](COORDINATION_BATCH01_PLAN_20261015.md)。几何位置与时序的变化都在真实调用前确定，本轮未调用 Astra 选择难度。

## 最终新 campaign

- ID：`38ec72e4d49d43d7972a1ce24f1e6d69`。
- 绝对根目录：`/home/alex/astra_spatial_capability/rm65-coordination-batch01-prep-20261015/experiments/rm65_handoff_v1/evidence/coordination_campaigns/REAL_batch01_20261015_02`。
- 当前状态：`DRAFT`，`reserved_budget=0`，首派发时间为空。
- [授权草稿](evidence/coordination_campaigns/REAL_batch01_20261015_02/authorization_REQUEST_NOT_GRANTED.json)：`generation_authorized=false`、`max_dispatches=0`、计划上限 50。
- [只读 DRAFT 快照](evidence/coordination_campaigns/REAL_batch01_20261015_02/ledger_DRAFT_readonly.json)；不存在 GRANTED。
- 冻结 SHA256：`974eaabecb516abdc164a5da735a372aad42d9a6dbbc0a1e8de1a6e6ef924118`，绑定 45 项源代码/任务/依赖记录哈希。
- 代码基于 `6afd5a8`；新增实现仅在 `coordination_batch01/`，原 Bridge、`action_interface.py`、`dual_scene.py`、原评分及安全保护源码不变。

原未授权草稿 `d189d23f911c47a0a73ea98a8780183f` 保留在 `REAL_batch01_20261015_01`，未更新其 ledger 或授权。它绑定修复前的非生成探针哈希，不能用于最终代码；本轮请求确认的是上面的新 ID。

## 验收记录

| 项目 | 结果与证据 |
|---|---|
| 三个条件的物理可执行性 | 3/3 PASS；02 号见证重复验证，逐步物理记录独立重评分一致 |
| 确实需要双臂协调 | 三类直接进入已占用区域的负对照均被原碰撞预检拒绝，推进 0 物理步 |
| 四视角/标定/目标事实 | 三份 [公共输入预览](evidence/coordination_batch01_preparation/public_input_previews) 通过原 RGB SHA 和 GT 隔离验证 |
| 门禁、协议、评分及原回归 | 63 项测试通过：`coordination_batch01.tests workspace_tests transfer_safety_tests`，见 `unit_tests_05.stderr.log` |
| 九局完整 mock＋PhysX | `MOCK_mock_full_03`：9/9 工程闭环通过、46 次模拟派发、独立重评分一致；不是 Astra 成功率 |
| 拒绝与后续调整链路 | 第一局不可达提案被原执行器拒绝；原反馈进入下一轮；模拟新提案被接受，没有自动目标修正 |
| HTTP 403 整批停止 | `MOCK_mock_stop403_02`：仅 1 次模拟派发即 STOPPED；后续 8 局均未开始 |
| 全局 50 / 每局 7 / 单调时钟 3600 | 单元验收覆盖跨局累计、边界处停止、单 worker、未知状态不恢复及预算不退款 |
| 中断不推进物理 | 中断分支不执行终态保持，输出 NOT_SCORED 并保留预留；不把中断伪装为空间失败 |
| Mac 实际非生成检查 | ChatGPT 登录、CLI version/help、原服务及隧道、190 秒配置通过 |
| Ubuntu 实际非生成检查 | 最终新 ID 的未知路径返回正确认证 404、错误认证 403；没有用 `/decide` 探活 |
| 历史保护/零生成 | 原 CTAG 和已结束 workspace ledger SHA 不变；实际生产 job 列表仍为原 5 个 |

九局完整 mock 之后只修改了非生成探针及其测试，执行器、任务、评分、调度和动作输入源码均未变；机器检查见 `final_source_delta_after_mock.json`。新增探针使用原生产 handler 做了禁止进入 infer 的测试，并通过实际 404/403 检查。最终冻结包含这项修复。

准备过程保留了一个多 episode 路径适配失败的 mock：第一局成功后，第二局重复调用旧一次性路径适配断言失败。修复仅使同一进程的路径适配执行一次，并逐局核对生成配置哈希。失败 `MOCK_mock_full_01` 保持 STOPPED，不恢复；其源码和日志、后续通过的 `mock_full_02/03` 都保留。

实际连接检查中，原 SSH 隧道因网络超时退出，Mac Bridge 服务始终为原 pid 6335。一次恢复遇到远端残留监听，未终止未知进程；只读确认端口释放后按原命令恢复隧道。原服务源码、token、ChatGPT 认证和模型设置都未更换。

非生成探针初次收到 400 的原因是缺少原服务要求的 `request_id`，不是模型请求失败。该证据和修复前源码保留于 `preflight_fix_01`。补齐 32 位 ID 后使用新 DRAFT 绑定最终代码；没有修改原生产 Bridge。

## 实际环境

Ubuntu-Robot；Python 3.10.12；SAPIEN 3.0.0b1；PhysX `105.1-physx-5.3.1.patch0`；mplib 0.2.1；GPU RTX 5060 Laptop / driver 595.84。步长 0.004 秒、求解器 position=10 / velocity=1、原控制器、1.1 m 基座间距及四视角保持不变。实际版本记录位于 `coordination_batch01/environment.json`。

## 后续一次性入口（本轮不执行）

当前预检只是此刻的连接证据。用户确认矩阵和该新 ID 并明确授权后，才创建同批次 GRANTED；正式运行仍需重新做 ≤15 分钟的实际 Mac 和 Ubuntu 预检。

Mac 侧使用新输出目录刷新非生成证明：

```bash
MACPY='/Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013/experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python'
TASK='/Users/tangchao/Desktop/资料/P7/rm65-coordination-batch01-prep-20261015/experiments/rm65_handoff_v1'
"$MACPY" "$TASK/coordination_batch01/mac_preflight.py" \
  --service /private/tmp/rm65-workspace-bridge-20261015/service.json \
  --tunnel /private/tmp/rm65-workspace-bridge-20261015/tunnel.json \
  --campaign-id 38ec72e4d49d43d7972a1ce24f1e6d69 \
  --output "$TASK/evidence/coordination_batch01_preparation/mac_AFTER_AUTH_01/mac_readiness.json"
```

把该证明复制到 ubuntu-robot 的新 campaign 目录后，一次性执行入口为：

```bash
cd /home/alex/astra_spatial_capability/rm65-coordination-batch01-prep-20261015/experiments/rm65_handoff_v1
C="$PWD/evidence/coordination_campaigns/REAL_batch01_20261015_02"
bash coordination_batch01/start_once.sh "$C" \
  "$C/authorization_GRANTED.json" "$C/mac_readiness_FRESH.json" "$C/bridge_config.json"
```

入口先做 Ubuntu 非生成预检，再执行已授权 campaign。不会创建授权、自动重试或恢复任何已开始/结束的 campaign。当前 GRANTED 不存在，因此现在不具备派发权限。

零生成复现命令：

```bash
source runtime.decision4.ubuntu-robot.sh
"$RM65_PYTHON" -m coordination_batch01.run
"$RM65_PYTHON" -m unittest coordination_batch01.tests workspace_tests transfer_safety_tests
"$RM65_PYTHON" -m coordination_batch01.contract \
  evidence/coordination_campaigns/MOCK_mock_full_03/ep01
```

工程见证可用 `python -m coordination_batch01.witness --condition A_fixed --output NEW_DIRECTORY` 复现；B、C 替换对应 condition。必须使用全新输出目录，不覆盖原见证。

所有原始逐步日志仍在执行主机保留；Git 保存 SHA 可核验的无损 `.jsonl.gz`。见 `lossless_archive_manifest.json`。完整矩阵、录像、轨迹、原始模拟提案/回执、独立评分和故障日志随本分支归档。真实 Astra 统计留待新授权后产生。
