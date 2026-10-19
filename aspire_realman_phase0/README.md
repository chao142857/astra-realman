# ASPIRE v1.0 → RealMan：Phase 0

**结论：采用独立 RealMan Adapter；当前只完成只读审计和离线准备，不具备真实双臂执行条件。** ASPIRE 固定为 `fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`（提交说明 `ASPIRE v1.0 release`）。本包是接口草案和拒绝派发的 Replay 实现，尚不是可直接挂载的原生 `EnvironmentAdapter`。

现场审计跨过午夜，证据时间为 **2026-10-20（Asia/Shanghai）**；隔离目录及分支沿用启动日期 20261019。

- [迁移方案、现场组件复用、阻塞与实施顺序](MIGRATION_PLAN.md)
- [坐标清单、现有外参及缺失标定](FRAMES.md)
- [六个接口、原生 CAP/MCP 接入边界](INTERFACES.md)
- [离线验收结果与证据索引](VALIDATION.md)

当前关键阻塞：本次 sysfs 快照仅有 `027223021284` D435，未确认历史四路在线；没有双基座共同坐标和实体抓取 TCP；桌面历史深度验证失败；现有 Python 环境未同时满足 ASPIRE 核心及 provider 依赖。没有安装依赖或改动原环境。

## 最短复现

在仓库根目录运行（仅标准库，不需要网络或设备）：

```bash
python3 -B aspire_realman_phase0/tools/run_offline_tests.py
```

本次结果：19 项标准库测试通过，8 项原生测试在该命令下明确跳过。完整原生核心检查使用**已有** Python 3.12 + NumPy 运行时和本地固定源码缓存，本次 27/27 通过：

```bash
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B \
  aspire_realman_phase0/tools/run_offline_tests.py --aspire-source .cache/ASPIRE
```

`.cache/ASPIRE` 不随本分支推送。其它机器需自行提供同一提交的源码路径，且使用现有 Python 3.10–3.12 + NumPy；没有这些条件时只运行标准库检查，不能把 skip 当原生测试通过。`tools/audit_remote.py` 是 SSH 仅读文件/进程的人工复查入口，不属于最短离线测试，不会自动运行。

**边界：** 本包没有 SDK/相机/网络传输构造器，没有 motion enable 参数；`move_to_pose`、`move_to_joints`、`move_synchronized`、`set_gripper`、`open_gripper`、`close_gripper`、`set_grippers`、`step`、`execute_trajectory`、`reset`、`go_home` 全部无条件拒绝。未运行 Agent 任务、Home、夹爪、伺服、碰撞硬件测试或真实轨迹。原部署、服务、V17 归档保持原样；本轮不自动进入 Phase 1。
