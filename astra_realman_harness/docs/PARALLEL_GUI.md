# 单 Astra 双臂 GUI（2026-10-07）

独立版本基于 `2896c02`；不热更新现有测试目录，不自动启动真机。

## 测试结束后切换

先让当前 episode 结束，正常退出旧 GUI（释放相机）。新旧 GUI 不应同时占用相机。保留当前官方 Codex bridge；parallel 入口会核对实际调用的 medium 配置。

在工作站终端运行准备好的独立副本：

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B \
  /home/tongji/alex/astra_parallel_gui_20261007/astra_realman_harness/scripts/run_astra_gui.py \
  --port 8877
```

工作站浏览器打开 `http://127.0.0.1:8877`。选择「单 Astra · 双臂动作组」，输入 task。默认 Shadow；现场选择 Execute 并点击启动后才执行。默认 100 次决策、7200 秒。原 H/D 和 legacy 条件保留原 50 步上限。

停止本回合阻止后续下发，并等待在途 SDK 返回；不保证立即打断正在执行的运动，也不自动回位。

## 显示内容

- 四路相机：左腕、桌面、俯视、右腕；parallel 使用四路，旧三路条件仍只用三路。
- 一个 Astra 输出一个 action group；显示 parallel / sequential、左/右动作、未参与臂的保持状态。
- 每臂独立显示预检查、dispatch journal、实发命令、SDK 返回、after pose、夹爪和错误。
- dispatch claim 仅表示开始下发，不能证明执行成功。
- 下一轮模型推理期间保留上一条已执行决策；新动作开始下发时更新。拒绝、停止、done 立即显示；可手动选择历史步骤。
- 公开输出和原始终端保留；不补写模型内部推理。
- 原始 proposal、per-arm 执行日志分开保留在归档；回放支持 group 日志。

GUI 通过原共享相机服务为 runner 提供图像，没有重复开启 pipeline。未改 group schema、Astra task、数值、IK、executor 或机器人控制方式。仅添加 GUI 启动参数兼容和现有锁接口。

## 离线验收

`tests/test_parallel_gui.py`：参数映射、四路检查、独立回读、claim 未完成、IK 拒绝、停止原因。
`tests/test_gui_decision_retention.js`：上一条保留、新下发更新、拒绝显示、人工历史选择。
另回归 parallel、GUI HTTP、整轮归档和回放。浏览器使用 `run_astra_gui.py --demo` 验收合成动作组，不调用模型/硬件。

这里接入的是单 Astra 双臂动作组 runtime，未声称实现任意双臂路径碰撞检查或自动交接规划。真实双臂 GUI 操作待现场显式启动验证。
