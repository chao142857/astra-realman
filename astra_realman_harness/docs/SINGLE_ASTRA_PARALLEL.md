# 单 Astra、双臂并行 harness

本版本在 right mirror 上增加动作组调度，不改变单臂 SDK、IK 或夹爪协议。第四路 348522072063 已根据操作者 2026-10-07 的现场确认标为 right_wrist。保留旧单臂入口、GUI、foundation 和归档。

## 一轮如何工作

1. 父进程采集四路当前图像与两臂 canonical state。
2. 仅一次官方 Astra 调用，任务原文不变，medium。
3. Astra 返回动作组：execution=parallel 或 sequential，最多一个 left action 和一个 right action。每个子动作仍是原八字段格式。未包含的臂保持，不发送指令。
4. 两侧全部完成原 exact-target IK 和状态检查后才允许任意侧下发。任一 IK 拒绝则本组零动作，原提案与原因送下一轮 Astra；API/状态/通信错误停止。
5. parallel 同时启动两侧工作进程请求；sequential 按数组顺序执行，第二臂刷新预检查。
6. 等两侧都返回，保留实际回执与新状态，重新采集四视角，再进入下一次 Astra 调用。没有第二个模型，也没有动作未结束就发下一组。

示例结构（不作为默认动作）：

```json
{
  "done": false,
  "execution": "parallel",
  "actions": [
    {"action_type":"cartesian_delta","arm":"left","frame":"realman:left:work:World","tool_frame":"realman:left:tool:Arm_Tip","translation_m":[0,0,0.001],"rotation_rpy_rad":[0,0,0],"gripper_opening":1,"done":false},
    {"action_type":"cartesian_delta","arm":"right","frame":"realman:right:work:World","tool_frame":"realman:right:tool:Arm_Tip","translation_m":[0,0,0.001],"rotation_rpy_rad":[0,0,0],"gripper_opening":1,"done":false}
  ]
}
```

整个任务完成使用 `done=true, actions=[]`。schema/运行时 parser 拒绝同臂重复、跨臂 frame、NaN/Inf、超出 opening 范围及子动作 done。不同机械臂的 World 仍是各自控制器的坐标系，未进行跨臂变换。

## 为什么每臂一个进程

本地 SDK 文档说明 `rm_movej_p(... block=1)` 会阻塞到位或规划失败；RM_DUAL_MODE 是 SDK 内部线程模式，不是“两机械臂并行”的开关。

`arm_worker.py` 采用 multiprocessing spawn。每个工作进程独占 SDKReadOnly 的初始化、handle、IK 和销毁，分别只连接 .19 或 .18；保留 `rm_movej_p(pose,1,0,0,1)`。父进程只负责模型、相机和调度。没有在同一 SDK 全局 runtime 中并发调用两臂。

并行表示运行时间可重叠，不承诺硬件同步到毫秒。每臂内部仍按原 arm→readback→gripper 顺序执行。

## 错误、停止及作用范围

- 每臂独立命令 journal；不重试已下发命令，不缩放/替换模型数值。
- 一侧失败会设置两侧共用 STOP，阻止后续通道和下一组；另一侧已经发出的阻塞运动可能继续到返回，日志如实记录，不能宣称已撤销。
- Ctrl-C / 输入 STOP 是停止继续下发，不等于硬件急停。未知超时不会 kill SDK 进程或重新发送；进程等待正在进行的调用退出，需现场按既有急停方式处理。
- 新并行入口与本版本 run_arm 共用 `/tmp/astra-realman-actuation.lock`。旧部署/GUI 未使用这把锁，因此不可与旧控制进程同时运行。
- 两侧 endpoint IK 通过不证明两臂的运动路径互不碰撞。本版不新增 planner/标定系统，首次现场并行验证应在各自明确分离的操作区域进行。
- 此低层动作组入口用于独立两臂动作并行，**没有替代 foundation 的 handoff 状态机**。交接需继续使用原先的顺序证据 handshake；不能把右闭爪与左松爪塞进同一个 parallel 组来代替持物确认。新入口尚未集成 handoff belief，也不宣称自动识别交接冲突。

## 入口

新入口为 `scripts/run_parallel_arms.py`。默认 shadow：读取硬件/相机、调用 Astra、两臂 IK，但不发送动作。

```bash
cd /home/tongji/alex/astra_parallel_arms_20261007/astra_realman_harness
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/run_parallel_arms.py --live
```

从终端输入一次 task；每轮自动继续。`--max-steps 100`、`--time-budget-s 7200` 为默认值。

操作者在现场显式启用真实执行时才加 `--execute`。本轮没有运行该命令，也没有启动任何模型或硬件连接。

使用已有官方 Mac bridge，地址仍为 `127.0.0.1:18766`。本分支 bridge 脚本默认 medium；客户端检查实际返回的 command.json 中 effort，若不是 medium 就不发动作。新部署配置目录需复用已有 bridge token 文件，不能提交 token；不会自动重启正在使用的 bridge。不要同时开旧 GUI 控制任务。

现有 GUI 不会自动切到本入口；本版先是独立 CLI。相机仍由原 CameraSession 持续打开，无新相机系统。

## 文件及日志

- `parallel_arms.py`：动作组 schema/parser、全组预检查、并行/顺序协调。
- `arm_worker.py`：独立 SDK 进程、prepare/execute/read 协议。
- `scripts/run_parallel_arms.py`：一次模型调用驱动两臂的闭环。
- `config/arm_mirror.json`：右腕确认。
- `tests/test_parallel_arms.py`：离线并行与协议测试。

每次运行 `logs/parallel-arms-<time>-<id>/`；每步保留 model_input、schema、模型 raw proposal、group_preflight、每臂 dispatch/SDK result/after state、group_result、四路 input/pre-execution/after 图像。worker_result 带实际开始/完成时间。原始 Astra、每臂执行结果分别保存。

## 验证

18项新增离线测试通过，含双侧 barrier 证明实际重叠、顺序与刷新、任一 IK 拒绝零下发、错误收集双方结果、无重试、单侧 hold、模型 done、schema、原数值保持，以及 worker 独立 session/重复 dispatch 拒绝。另有 right mirror 24项和 foundation 37项通过，共79项。测试使用 mock；真实并行运动尚未验证。
