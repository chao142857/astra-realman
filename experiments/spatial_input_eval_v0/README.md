# Astra Spatial Input Evaluation V0

2026-10-13 yanglab 纯仿真验收见 [lab/README.md](lab/README.md)：实验室实际 33/33 测试通过，新增六个真实 SAPIEN GPU 静态场景、18 组多视角 RGB-D、12 道任务、24 份 A/C 输入及 mock 闭环。独立重渲染的 72 个资产逐字节一致，GT 隔离和 provider payload 验证通过。一键启动脚本已实际运行成功。新真实 Astra 生成请求为 **0**；原生 CLI 当前为 API-key 认证、无 ChatGPT workspace route，真实 JSON 验收仍待认证确认和用户单独授权。以下个人 Ubuntu 的历史记录保持原样，不能当作实验室现状。

2026-10-12 独立修复分支最新验收见 [QUALIFICATION_ACCEPTANCE.md](docs/QUALIFICATION_ACCEPTANCE.md)：原 bwrap 在宿主机网络完成无生成 workspace 路由发现，但唯一一次 qualification A 在90秒超时，无有效 JSON，C未启动。测试31/31 PASS。此前网络与30秒计时修复见 [ROUTING_REPAIR.md](docs/ROUTING_REPAIR.md)。以下 V0 结果作为原始交付记录保留。

可执行的离线空间输入评测模块，复用原 Astra `infer_process → infer_worker → bridge.infer()`。默认 mock；不训练、不连接运动接口。当前交付完成了数据读取、A/C 输入构建、严格 JSON、独立几何评分、成对比较和失败索引；真实模型对照被网络路由故障阻塞。

## 本机验证结果

Ubuntu 22.04.5 LTS。系统 Python 3.14.7 可运行标准库测试及 mock；现有 `/home/alex/astra/.venv/bin/python` 是 3.10.12，并有真实 transport 所需 jsonschema 4.26.0、bwrap 和 Node/Codex。

| 检查 | 结果与证据 |
|---|---|
| V0 单元测试 | **23/23 PASS**，`evidence/unit_tests/` |
| 序列化与语义 schema | 7 个 snapshot PASS；3 类输出通过现有 Astra compiler |
| 六个合成 fixture，每场景两道任务 | 24 条 A/C mock 记录、12 对；`evidence/mock_suite/` |
| 1 个历史 SAPIEN 快照，三视角 RGB-D 与同一步 GT | 已接入，两道任务；4 条 A/C mock 记录、2 对；`evidence/s1_archive/`、`evidence/mock_s1/` |
| 无模型消耗的生产沙箱预检 | PASS，Codex CLI 0.162.1；`evidence/preflight/` |
| 获授权的最多 2 次真实请求 | 实际启动 **1 个 A infer 尝试**，无模型回答，usage UNKNOWN；C 未启动 |
| 真实 A/C 对照 | **BLOCKED**：CLI `workspace routing discovery failed`，return_code=1；不是模型空间判断失败 |
| 原项目额外的 infer fixture 回归 | 18 项中 7 PASS、7 FAIL、4 ERROR；诊断为 fixture net namespace 的 `NETLINK_ROUTE` socket 权限限制。不是 V0 23 项测试，也不能声称原套件全通过 |
| 真机 / 新仿真场景 / 训练 / IK | 均为 0 |

正式真实尝试的当前分类见 [`evidence/real_ac_final/summary.md`](evidence/real_ac_final/summary.md) 和 results.json：`NO_MODEL_RESPONSE / NOT_SCORED / score=null`。首次尝试全部原始请求/事件/worker 结果保存在 `evidence/real_ac_s1/`；早期派生报告将空输出记为解析失败和零分，已修正评分器，并用**纯离线 rescore**生成 `real_ac_final`，没有再次请求。不要用首次派生零分作能力结论。

六个 fixture 是小型、示意 PNG + 解析几何测试，明确 `SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION`；不是六个已运行的真实仿真场景。历史 S1 图像是原始 SAPIEN renderer 输出，不能称为真实照片。当前没有可靠标注的真实照片样本，也没有显著改善结论。

## 实际验证过的运行命令

在本次 worktree 中运行：

```bash
cd /home/alex/astra_spatial_capability/eval-v0
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
python3 -m unittest discover -s experiments/spatial_input_eval_v0/tests -v
```

可重复运行的最小 mock 闭环（每次使用新的输出目录；拒绝覆盖已有结果）：

```bash
RUN_ROOT=$(mktemp -d /tmp/astra-spatial-v0.XXXXXX)
python3 -m spatial_eval.cli fixtures --output "$RUN_ROOT/fixtures"
python3 -m spatial_eval.cli run \
  --snapshot "$RUN_ROOT"/fixtures/*/snapshot.json \
  --output "$RUN_ROOT/mock"
```

复用机器上的实际历史快照，校验图片/depth、公共 seal 和 truth capture binding；不创建新仿真：

```bash
python3 -m spatial_eval.cli import-archive \
  --archive /home/alex/astra-realman_ws/semantic-s1-capture-20261009 \
  --output "$RUN_ROOT/s1"
python3 -m spatial_eval.cli run \
  --snapshot "$RUN_ROOT/s1/snapshot.json" \
  --output "$RUN_ROOT/mock-s1"
```

迁移机器后也可以直接读取随交付保存的 PNG/depth/snapshot：

```bash
python3 -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot.json \
  --output "$RUN_ROOT/mock-bundled-s1"
```

无模型请求的版本/help 预检（同一 production sandbox）：

```bash
/home/alex/astra/.venv/bin/python -m spatial_eval.cli preflight \
  --output "$RUN_ROOT/preflight"
```

本次真实尝试实际运行了下面的命令，**结果失败，不能列为已成功命令**。仅在希望消耗真实请求且排除路由问题后手动开启；这不是默认复现步骤，也不会自动重试：

```bash
/home/alex/astra/.venv/bin/python -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --conditions RGB_MULTI_VIEW RGB_ORACLE_3D \
  --real --max-real-calls 2 \
  --output "$RUN_ROOT/real-ac"
```

模型、medium 推理配置、工具禁用和会话隔离由原 `bridge.command()` 保持，框架没有参数覆盖开关。没有 auth 文件复制、secret 保存或 fallback provider。`--max-real-calls` 先校验完整请求数，所有条件先验证可用性，真实失败即停止剩余请求；CLI 内部的 reconnect 事件完整保留，应用层无重试。infer_started 仅证明启动了调用链，远端实际服务请求数仍 UNKNOWN。

离线重评分已实际验证，不再调用模型：

```bash
python3 -m spatial_eval.cli rescore \
  --snapshot experiments/spatial_input_eval_v0/evidence/s1_archive/snapshot_understanding.json \
  --source-run experiments/spatial_input_eval_v0/evidence/real_ac_s1 \
  --output "$RUN_ROOT/rescored-real"
```

## 输入、输出与扩展

A 为同一组同步 RGB + 标定/坐标/状态；B 加载 `geometry.reconstruction`；C 加载 `geometry.oracle`。geometry 与 ground_truth 分开，不从 GT 自动填充缺失的 B/C。B 与 C 用同一米制箱体 schema，预留 rendering 槽位。B 的加载接口和三组比较已测试，完整重建算法未实现。后续填入实际 reconstruction 后可显式选择三组条件；不可用时明确失败。

`task` 定义机器可评分的正轴关系、位置、顶部高度、尺寸、投影间隙和定向容纳，以及放置和持物体关键点规划。原始 JSON 不被修复。目标位姿验证完整 OBB 体积；路径在固定朝向下连续碰撞检查，不以唯一参考轨迹评分。完整语义和限制见 [DATA_CONTRACT.md](docs/DATA_CONTRACT.md)。

每个输出目录包含 `results.csv / results.json / paired_comparison.json / summary.md / failure_index.json`，逐样本有 request/response/raw/evaluation/worker 日志。结果按 scene_id/task_id/condition 定位；error_types 指向失败的问题、约束或路径 segment/obstacle。用量缺失保持 null，不能推算。

模型沙箱仅挂载实验输入，不挂载 evaluator 的 GT、原控制器或私有证据；A 不发送 3D geometry，C 只发送允许的物体/内腔/障碍几何，不发送答案/评分/历史动作。条件之间没有会话历史。oracle 导入器和评分器可以读取独立真值，但它们不运行在模型 worker 内。

暂未完成：真实 A/C 有效回答与比较、6 个不同的真实仿真场景导出、真实照片可靠 GT、完整 B 重建、几何图像渲染、RoboSpatial-Home / TraceSpatial-Bench 实际数据转换、重复测量和统计显著性。公开数据扩展类明确未实现，不伪造接入记录。

Git 独立分支与原源码保护检查见 [INSPECTION.md](docs/INSPECTION.md)；最终交付计数及 Git 状态见 [DELIVERY.md](docs/DELIVERY.md)。

所有实验产出默认提交并推送，包含早期、失败及临时复现归档；详见 [ARTIFACT_POLICY.md](docs/ARTIFACT_POLICY.md)。

实验室仿真通过既有 Mac ChatGPT / SSH bridge 的接入、离线验收及单次真实调用前置条件见 [MAC_BRIDGE_INTEGRATION.md](docs/MAC_BRIDGE_INTEGRATION.md)。真实调用仍需单独授权。
