# Pilot 01 离线分析与 Pilot 02 冻结交付

本次真实生成预算和实际派发均为 **0**。从 `b103ee5` 新建分支 `codex/spatial-pilot02-offline-20261013`；不修改任何基线已跟踪文件，不重置旧 ledger，不执行旧批次的 next/wave，不连接硬件。`9beb20d` 保存首个完整交付检查点，后续提交追加 ubuntu-robot 的独立 Linux 验收。

## Pilot 01：保留评分，增加解释

[完整分析](../evidence/pilot01_analysis_20261013/REPORT.md)含逐题、场景及题型 CSV，2/5/10/20 mm 曲线，数值敏感性，以及六对/去缓存五对的 token 和时间统计。

| 内容 | A | C |
|---|---:|---:|
| 原始理解正确数 | **45/54** | **54/54** |
| 关系与容纳判断 | 30/30 | 30/30 |
| 直接数值（位置、尺寸向量） | 6/12 | 12/12 |
| 几何计算（顶高、间隙标量） | 9/12 | 12/12 |
| 统一加 10 nm 的事后敏感性视图 | 49/54 | 54/54 |
| 规划几何合法性 | 6/6 | 6/6 |

敏感性视图不替换 45/54，四个边界项高于 5 mm 仅约 2–4 nm。位置与尺寸分别用向量 L2；顶高、间隙分别用绝对标量误差，不合成一个“精度”。

六对有效理解都来自 180 s/四 worker 阶段。90 s/串行阶段只有一次超时理解请求，token 未知，不能据此估计并发的因果效果。六对平均客户端耗时为 A 124.86 s、C 29.45 s；剔除 S2 这一有缓存命中的整对后，五对为 A 128.04 s、C 30.10 s。reasoning tokens 是 output 的子集，其余输出单列；缓存输入是 input 的子集。token 不等于精确内部计算量，客户端等待也不等于模型计算时间。

[全部规划回放](../evidence/pilot01_replay_20261013/README.md)包含 12 份原始输出、36 张原图标定叠加、12 张独立几何视图，以及路径长度与区域面余量/SAT 投影阈值。S6 A/C 路径长 1.22/1.00 m，均合法；不声称最优。SAT 投影阈值没有冒充欧氏距离。S3 的规划区域在窄容器之外；S4 姿态由任务规定，均不作更强能力解读。

这些是有限场景的探索性描述，不作显著性、总体泛化或内部推理机制结论。

## Pilot 02：10 个真实仿真预览

[设计与评分方案](PILOT02_OFFLINE.md)和[三视角拼图](../evidence/pilot02_preview_20261013/suite_v2/preview_all.png)对应：

- 6 个放置余量样例：每侧 3/10/30 mm，各有落点空间互换的两个变体。
- 2 个受限绕障样例：公开 z=0.03–0.25 m 工作空间，通行侧互换，固定抬高不能通过。
- 2 个自主朝向样例：不给目标四元数，公开规则只限制竖直，评分接受全部几何合法 yaw。

30 份 RGB-D、标定、分割和 PhysX 回读 GT 完整保存。每例都有私有可行解、其他可行解和无效负对照；将另一变体的可行解用于当前场景会失败。已声明的固定落点/角落/绕行/yaw 策略无法同时通过同一变体对。可见性检查针对关键开口边界，不能据此保证 RGB 的 3 mm 测量精度。

[冻结清单](../evidence/pilot02_freeze_20261013/artifact_seal.json)封存 607 份源代码、数据及证据；[未来 A/C 顺序](../evidence/pilot02_freeze_20261013/future_ac_order.json)固定 20 份输入，5 个 A 先、5 个 C 先，全部样例纳入。本阶段没有新运行 ledger，这个顺序文件不会派发请求。

第一轮 renderer 失败记录及九份已完成快照保留在 `suite/`；正式集合只使用 `suite_v2/` 的 10 份快照。未按模型成败挑选样本。

## 验收与接入边界

[ubuntu-robot 验收](../evidence/ubuntu_robot_offline_20261013/acceptance_summary.json)结果为 **94/94 测试通过**，607 项冻结哈希全部一致，30 份 RGB-D/GT 与 20 份输入隔离复验通过。原 Mac 的 93/94 日志和 socket 平台差异仍保留；不删除失败记录。yanglab 的初次完整测试因 SSH 断开而完成状态未知，不将其报告为通过。

公共 `task_policy` 已通过原生产 bridge 的 payload/schema 离线校验，但现有 V0 MacBridgeAdapter 的七字段限制不接受该新字段。**下一阶段仍需独立 Pilot 02 adapter/dispatcher 的离线验收，完整传递 policy 并调用 Pilot 02 scorer，然后取得新的真实生成授权。** 不能直接运行旧 CLI、不能删掉 policy 绕过验证；8 并行部署未在本轮启动。

## 可复现命令

ubuntu-robot 独立工作目录：`/home/alex/astra-realman_ws/spatial-pilot02-offline-20261013`。复用 Python：`/home/alex/astra/.venv/bin/python`。

```bash
cd /home/alex/astra-realman_ws/spatial-pilot02-offline-20261013
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
PY=/home/alex/astra/.venv/bin/python

# 只读复用冻结数据，运行全部 fixture 测试、RGB-D/GT、A/C 隔离验收。
# 必须指定一个不存在的新输出目录；不调用模型，也不重新渲染。
SPATIAL_VALIDATE_PYTHON="$PY" bash \
  experiments/spatial_input_eval_v0/lab/validate_offline_on_linux.sh \
  /tmp/pilot02-independent-acceptance-new

# 可选独立再生成分析/回放，输出目录同样必须不存在。
$PY -B experiments/spatial_input_eval_v0/lab/analyze_pilot01.py \
  --output /tmp/pilot01-analysis-new
$PY -B experiments/spatial_input_eval_v0/lab/replay_pilot01.py \
  --output /tmp/pilot01-replay-new
```

如需另做 GPU 渲染复现，使用设计文档的 `pilot02_render.py` 命令并保存为新的输出目录；不得覆盖已冻结输入。该 GPU 命令已在 yanglab 验收，本轮 ubuntu-robot 主要复验已归档数据，不声称在第二台机器再次渲染过。
