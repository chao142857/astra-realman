# 交付记录

分支：`codex/spatial-input-eval-v0-20261012`，基线 `431f112c80f13a997a8ac1df81cbc3644c1d30ae`。所有提交变化限于 `experiments/spatial_input_eval_v0/`；原源码、控制器、安全层和历史结果未修改。bare 副本及 worktree 位于 `/home/alex/astra_spatial_capability/` 内。

## 验收边界

- V0 独立单元测试 23/23 PASS；完整体积、旋转、薄障碍连续碰撞、合法替代位姿/路径、严格 JSON、GT 隔离、缺失 GT、API 故障、成对统计与不可覆盖输出均覆盖。
- 实际导入 1 个历史 SAPIEN 场景，3 个 RGB + 3 个 depth + 标定/状态，同一步独立 GT；未运行新的仿真场景。
- 正式持久化 mock：六场景两任务 A/C 共 24 条 + 历史场景两任务 A/C 共 4 条，14 对。README 可重复命令还在 `/tmp/astra-spatial-v0.0MePJw/` 验证，临时复跑不作为额外独立样本。
- 生产预检 PASS，模型参数固定 `gpt-6-astra / medium / openai`，没有模型参数覆盖。
- 用户显式授权本次最多 2 个真实请求；实际启动 1 次 A infer 尝试，CLI exit=1、routing discovery failed。0 个完整真实模型回答、0 对真实 A/C、0 次 C 请求；token、远端真正服务调用数 UNKNOWN。应用层不重试，CLI 原始 reconnect 事件保留。
- 当前正式真实状态为 BLOCKED、score=null；见 `evidence/real_ac_final`。初次 raw/request/worker 文件仍完整保留。离线重评分不会启动新模型。
- 补充原项目 18 项 infer fixture 回归：7 PASS、7 FAIL、4 ERROR。最小诊断保存了 `bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`，见 `evidence/legacy_fixture_diagnostic/diagnostic.json`。这是当前 fixture network namespace 限制；真实 production sandbox（share-net）的版本预检通过。未改原 sandbox 或将其降级成可读取 GT 的非隔离调用。
- 3 种输出 schema 通过原 compiler；7 个 snapshot 通过 JSON Schema 和语义检查。源码 SHA 与原干净工作树相同，见 `evidence/source_preservation.json`。
- 真机运动、训练、IK、新动力学验证次数均为 0。

## 未完成

真实有效 A/C 比较仍需排除当前 CLI workspace routing discovery 故障并重新获得可用调用预算；六个不同的实际仿真场景、真实照片可靠 GT 尚未准备。B 只完成同 schema 加载与测试，完整重建算法、几何渲染、两个公开数据集转换未实现。没有显著改善或真实模型准确率结论。

Git 推送和最终 commit SHA 由交付时的 Git 命令验证，最终聊天回复给出具体 SHA；本文件不嵌入自引用 commit hash。origin 为 `https://github.com/chao142857/astra-realman.git`，推送仅创建该独立任务分支，不修改 1011/main。
