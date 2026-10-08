# B/F qualification 时限适配

基于冻结 `0677cba`，保留原 30 秒超时回合和独立冻结输入诊断。独立诊断约 42.108 秒合法返回只证明该输入的模型通道，不是物理执行或 B/F 任务成功。本增量仅做时限适配与离线检查；真实请求、物理场景启动、硬件调用均为 0。以下额度等待用户显式启动，未继承任何旧额度。

## 模式与预算

| 限制 | standard（默认，原模式） | qualification（显式指定） |
|---|---|---|
| 回合 | B × 1，F × 1 | B × 1，F × 1 |
| 每回合墙钟预算 | 300 秒 | 900 秒 |
| 单请求上限 | min(30 秒，回合剩余) | min(90 秒，回合剩余) |
| 全角色 attempt | 20/回合，40/配对 | 20/回合，40/配对 |
| 动作 chunk / 显式重观测 | 12 / 2 | 12 / 2 |
| 在途 / 待提交未来候选 | 1 / 1 | 1 / 1 |
| owner watchdog | 600 秒 | 1260 秒 = 启动初始化 300 + 回合 900 + 清理审计 60 |

`timing.py` 提供共同上限，`pair --mode` 传到每个新 owner、FullRuntime、FullSlot 和隔离 infer worker。worker 中原先固定的 `min(30, remaining)` 改为模式上限；仍调用原 `codex_astra_mac_bridge.infer()`。B/E/A 共用 runtime 创建时的一份绝对 monotonic deadline，E 返回再提交 A 时不重置回合时间。冻结输入准备、选图、调用失败、取消及等待都消耗同一回合预算。attempt 在准备前计数；不自动重试、不回退 RGB 动作 stub。

外层从父进程启动 owner 前记时（写入账本并传入子进程），包括 Python 导入、版本/help 预检与场景初始化。qualification 在预检后及 runtime 创建后检查 300 秒启动裕度；超额不进入回合，避免初始化挤占已批准的 900 秒。外层到 1260 秒发送终止，沿用最多 10 秒强杀宽限；这些均不是额外任务或请求额度。原 600 秒 watchdog 保留。同步渲染/规划段沿用旧检查点，不新增硬实时可抢占保证。

单请求 deadline 在 FullSlot 中为 `min(launch_time + request_cap, episode_deadline)`，infer worker 按同一绝对 deadline 再减去自身启动耗时。owner 超时或外部 STOP 仍取消；迟到输出只归档、不采用。取消清理沿用原 4 秒保存 raw/usage 的宽限，计入实际墙钟。模型身份/effort/内部重试没有服务端回执仍为 `unknown`。

`completed_within_300s` 是额外报告字段，不触发停止。定义为回合开始到独立评分 PASS（含原 settling/判断时间）不超过 300 秒；实际秒数记录为 `task_completed_wall_s`。失败或 STOP 为 false、完成时间 null；未运行/初始化失败/缺失结果保持 null。初始化、冷启动、物理时间、回合墙钟继续分列。字段位于 episode summary、result 及配对 ledger。

## 输入与执行边界

原 model/medium、prompt/schema、图像投影、来源记忆、动作接口、控制器、物理参数、提交门、夹爪屏障和工具禁用配置均保持。mode/截止时间只在调度元数据与 worker argv 中，不进入模型 wire。相同冻结观测的 B/E/A payload 在两种模式下逐字节相同；假进程检查 worker 实收上限。

未来运行使用原单回合入口，每组新进程、新空夹爪场景、新图像和新请求。没有诊断候选输入参数，不读取、重绑定或执行冻结诊断中的候选。原回合及冻结诊断归档不回写。接口/协议/执行/预算/审计异常仍停止后续组；合法 STOP/独立任务失败按原配对规则保留。不会补跑到成功。

## 用户显式启动入口（本增量未执行）

下面命令就是新预算的显式启动；输出目录必须不存在。更改输出目录用于新的已授权批次，不代表失败后可以自动重试。

```bash
/home/alex/astra/.venv/bin/python \
  /home/alex/astra-realman_ws/astra-realman-full-pnp-qualification-20261008/astra_realman_harness/scripts/run_full_pnp_pair.py \
  --mode qualification \
  --enable-real-bf-pair \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --output /home/alex/astra-realman_ws/full-pnp-qualification-bf-pair-01
```

恢复原时限可指定 `--mode standard` 或省略 mode；同样要求新的显式授权和不存在的输出目录。没有 `--enable-real-bf-pair` 时在预检、创建输出、scene 或 infer 前拒绝。

## 定向验收范围

12 项新增测试仅验证时限/取消及其必要报告：虚拟 42.108 秒仍运行、90 秒/更早回合截止取消、外部 STOP、E→A 共享剩余时间、全角色失败占 20 次上限、旧 30 秒取消、各角色真实 worker 路径下的假 CLI 时限、payload 相同、300 秒完成记录、pair/watchdog/runtime 参数贯通和显式启用门。假 CLI 禁网且无认证，使用假 backend，不再扩展 stub 物理验收。这些不证明真实视觉决策、物理成功或真实模型提速。

测试命令、完整输出、历史证据前后 hash 与源码保持检查另存于独立资格模式验收目录；真实 B/F 资格试跑仍待用户启动。
