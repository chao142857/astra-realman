# yanglab 部署与零生成复验

执行主机已迁移为 **yanglab**（`tongji-Precision-3680`）。基线为 `8cd224e89cac6e96c94b1550e1bff00504842485`，独立分支 `codex/rm65-action-chunk-yanglab-20261016`。

工作目录：`/home/tongji/alex/rm65-action-chunk-yanglab-20261016/experiments/rm65_handoff_v1`。

仅新增进程级运行配置 `runtime.action-chunk.yanglab.sh`、本记录及验收证据。Astra 的决策权、action chunk、模型接口、夹爪控制器、数值执行器、1.1 m 布局、四视角及原 2 mm 穿透保护均未改变。正式模型回合仍从桌面方块、双臂空手/开爪开始，私有工程初始化只用于执行器验收。

## 现有环境复用

- 原 Python：`/home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python`，Python 3.10.19。
- 原依赖：`/home/tongji/alex/rm65-handoff-runtime-20261014/deps`。
- 原资产：`/home/tongji/alex/rm65-handoff-runtime-20261014/assets`，56 项哈希全部通过。
- GPU：RTX 3060 12 GiB，驱动 535.230.02。
- SAPIEN 3.0.0b1、PhysX `105.1-physx-5.3.1.patch0`、mplib 0.2.1、NumPy 1.26.4、SciPy 1.10.1；没有安装或升级依赖。
- 原始 TGS / solver / dt=0.004 秒；当前独立版本的 URDF effort 模式、右接触保持 D=0 控制器沿用基线。

遵循 NETWORK-P0-20261016，复用已有 SSH 路径与本地 Git 缓存，使用增量 bundle 导入。没有改代理、DNS、认证、SSH 配置或任何机器人硬件。未向 yanglab 复制 GitHub/模型凭据。

## 实际验收

| 项目 | yanglab 结果 |
|---|---|
| 精确代码/历史归档 | 基线提交一致，原 action chunk 归档 2144 项哈希通过 |
| 离线协议/语义 | 19/19 通过 |
| 本地 mock → 四视角 → 数值动作 → PhysX 反馈 | 通过；2 次合成 RPC，真实模型请求 0，生产 Bridge 连接 0 |
| 正式入口初态 | step=100，桌面方块、双臂空手/开爪，专家初始化动作 0；推理期间物理推进 0 |
| 右臂独立保持 7 秒 | 通过 |
| 单个目标自动均匀细分 72 节点 / 66.8 秒物理持物 | 通过；两个原始调用者折点的固定姿态折线亦通过 |
| 正常开爪 / 空载位置闭合 / 空夹负对照 | 通过；空夹保持明确失败且不自动修正或重试 |
| 3° yaw 受限姿态变体 | 保留 **FAIL**：step 28614，`PAD_PENETRATION`，最大报告有效夹垫接触穿透 2.326672 mm |

固定姿态完整验收共 33,799 步、135.196 秒仿真；yaw 变体至 28,614 步、114.456 秒仿真。与 Ubuntu 已归档原始记录逐步比较：全部 **62,413** 个样本的左右臂 qpos、物块位姿、驱动目标及双侧接触状态完全一致（该集合不包含墙钟和渲染像素）。两次的新独立持物重评分也与各自保存结果完全一致。

固定姿态运行最大报告有效夹垫接触穿透为 0.495569 mm（含工程初始化）；右臂长段为 0.288751 mm。接触保护、安全阈值及原失败没有被放宽或改写。

这是**部署成功且已知物理限制保持不变**，不是“yaw 已修复”或“Astra 已完成全任务”。仍沿用原报告关于左桌面闭爪显式保持回执和任意持物转向尚未可靠的限制。未开始新的夹爪优化或参数扫描。

13 个原有 worktree 的 HEAD 与未提交状态均保持不变，包括旧 `episode.lock` 和未提交诊断目录。旧 STOPPED ledger 哈希保持：
`2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1`。

真实 Astra 请求 **0**，新 ledger **0**，旧额度不转移。真实推理入口保持关闭，取得新授权后再刷新 Mac Bridge 的生产预检。

## 启动与复现

```bash
ssh yanglab
cd /home/tongji/alex/rm65-action-chunk-yanglab-20261016/experiments/rm65_handoff_v1
source runtime.action-chunk.yanglab.sh

# 协议/语义回归，不需要生产 Bridge
"$RM65_PYTHON" -m unittest numeric_chunk_tests offline_tests -v

# 从桌面空手初态开始的完整任务入口 mock 验收
"$RM65_PYTHON" full_handoff_offline_test.py \
  --action-interface chunk_v2 --right-hold-control master_damping0_v3 \
  --output evidence/YOUR_NEW_UNIQUE_YANGLAB_MOCK

# 私有执行器验收；不作为模型任务成功
"$RM65_PYTHON" numeric_chunk_physics.py --fixed-orientation-regression \
  --output evidence/YOUR_NEW_UNIQUE_FIXED_ORIENTATION_TEST

# 已知 yaw 边界，预期返回非零并保留物理保护中止
"$RM65_PYTHON" numeric_chunk_physics.py \
  --output evidence/YOUR_NEW_UNIQUE_YAW_TEST
```

正式全任务的公共入口仍为 `run_episode.py --task handoff_place_full --action-interface chunk_v2 --right-hold-control master_damping0_v3`；当前版本仅接受合成 mock 凭据，`--real` 会在创建仿真或请求之前拒绝。没有新的本任务授权不能派发。

实际输出位于 `evidence/yanglab_migration_20261016/`：四视角 RGB/标定、完整原始视频、数值轨迹、原始动作及反馈、无损原始日志、独立比较结果。新视频均来自本次 yanglab 的 SAPIEN 渲染，不能算作真实 Astra 自主动作录像。
