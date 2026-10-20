# ASPIRE → RealMan Phase 1A

基于 `05bea2bf2de766476a615188a94a69b647cc220c`；上游仍为 `fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`，沿用 Phase0.5 的六轴/状态 metadata 小补丁。本目录增加真实相机 LiveSource，不改 Agent 决策、Prompt、Skills、原生 MCP/server/session 或历史 Replay。没有任务专家程序、机械臂 SDK 连接或运动 transport。

已在 yanglab 完成真实桌面 D435 RGB-D → 原生 CAP monitor → EmbeddedAgentRuntime → MCP HTTP 验证。最终 84 帧、5.50 s；三次 observe 均返回真实图像，序列递增、state 为空，完整 `Observation` 明确不可用。相机现已释放。官方SAM3独立环境已完成源码安装、导入和CUDA基础运算验证；真实照片推理明确BLOCKED于尚未提供的本地权重，另记录decord平台标签警告。所有运动入口硬拒绝；capability graph 的 Mock IK/Planner 与 physical motion 都为 false，IK/轨迹/pose planner 为空；没有配置 Mock 感知。原生 MCP 仍保留部分动作 schema 供明确的 safety_interlock 返回，不能将 schema 的存在当作执行能力。

- [实现与坐标、时序边界](DESIGN.md)
- [真实采集、深度质量与 MCP 证据](VALIDATION.md)
- [官方 SAM3 安装与阻塞](SAM3.md)
- [Phase 1B 缺口与现场事项](NEXT_PHASE_1B.md)

现场独立目录：`/home/tongji/alex/aspire_realman_phase1a_20261020`。`.venv` 为 native MCP/相机独立 Python3.12 环境；`.sam3-venv` 为官方 SAM3 的另一独立环境，均不继承 system-site-packages。未修改 dp/aloha、旧 GUI、V17/V19。

最短软件复现，无硬件：

```bash
ssh yanglab 'cd /home/tongji/alex/aspire_realman_phase1a_20261020 && .venv/bin/python -B aspire_realman_phase1a/tools/run_quality_tests.py'
```

重新采集是单独的显式操作，每次都先检查锁、`fuser /dev/video*` 和 SDK serial；若有任何 owner 则拒绝。输出目录必须全新。它会只读开启桌面相机数秒并在退出时关闭自己创建的 pipeline，不会启动 Agent 或连接机械臂：

```bash
ssh yanglab 'cd /home/tongji/alex/aspire_realman_phase1a_20261020 && .venv/bin/python -B aspire_realman_phase1a/tools/capture_validate.py --capture-tabletop --seconds 4 --output evidence/live-new'
```

原始照片、Z16、depth.npy、完整逐帧报告与模型/环境留在 yanglab，不进 Git。仓库只含源码、依赖/版本锁、轻量质量摘要和明确标注的测试结果。新克隆需先按 Phase0.5 `tools/prepare_upstream.py` 准备固定上游，再创建 venv 安装 `requirements-live.txt`；不要对 partial upstream 执行不受限的 Git status 触发隐式下载。
