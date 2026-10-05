> 2026-10-05 后续更新：操作者已明确授权切换真实执行。现在新增 `--execute`，默认仍然 dry-run。本文下面原验收记录描述此前版本，不代表当前没有硬件开关。
>
> 真机启动（先 Ctrl-C 停止旧进程）：
> ```bash
> /home/tongji/miniconda3/envs/dp/bin/python -I -B /home/tongji/alex/astra_realman_harness/scripts/run_left_terminal.py --live --execute --model gpt-6-astra --max-steps 50
> ```
> 输入任务后自动执行。显式显示 REAL_EXECUTION。只连接左臂；fresh state/frame/error 检查后，按原值调用 rm_movej_p(pose,1,0,0,1) 和既有 RmArm 数值开度路径。非零返回、反馈读取或状态错误即停，无重试、投影或 recovery。STOP/Ctrl-C 阻止后续命令，并取消等待中的模型进程；已经发送的阻塞 SDK 动作不保证被软件 STOP 中断，紧急情况使用现场物理急停。
>
> 新增 left_executor.py、tests/test_left_executor.py；11 项 mock 执行测试和21项接口测试通过，没有用真实硬件测试这些修改。

# 左臂三视角 / 数值夹爪接口：dry-run 验收版

2026-10-05。本版只修改接口、显示与日志链路，只有 DryRunExecutor，**没有运动开关**。旧成功 baseline 的入口、控制代码及历史日志保留不改；不要用旧 `run_auto_pick.py` 来测试本页的新接口。

## 当前状态

- 左臂专用：仅连接 192.168.1.19，模型上下文只包含 left state、left work/tool frame；不连接或读取其他机械臂。
- 三路固定顺序：left_wrist=254522073676、tabletop=346222072496、overhead=344422071480。操作者于 2026-10-05（Asia/Shanghai）明确确认，role_confirmed=true；依据已记录在配置中。
- 数值 `gripper_opening`：0=fully closed，1=fully open，opening target；不是 force control，也不代表以毫米计的物理指距。与现有 RmArm 映射保持一致：`int(opening*1000)`，该线级整数分辨率单独记录。
- task 由终端输入，原文进入请求，不加 task planning、诊断、confidence、接触处理或恢复提示。
- 开放度 schema 是接口定义，不是抓取策略。已去除 open/close/hold 字符串。若要保持，模型可请求当前开度；已满足的 target 不重复发送。
- done=true 为终止通知，全部 actuator channel 不下发；arm delta 要求零，opening 字段不执行。
- 自动连续运行的交互框架已建立，但目前每轮都 dry-run。每轮重新观察；不等待 EXECUTE。STOP/Ctrl-C 退出。不会回位、闭爪、retry、插入 waypoint 或 recovery。

## 现在可运行的离线验收（不连接任何设备、不调用 Astra）

Mac：
```bash
ssh yanglab
```
工作站终端：
```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B \
  /home/tongji/alex/astra_realman_harness/scripts/run_left_terminal.py \
  --replay /home/tongji/alex/astra_realman_harness/logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json \
  --fixture /home/tongji/alex/astra_realman_harness/tests/left_opening_fixture.json \
  --max-steps 1 --no-preview
```
出现 `Task (verbatim...)` 后输入自己的任务。fixture 固定，**不是 Astra 推理结果**，仅验证输入/输出/日志。归档状态不冒充当前状态，完成一个回放 step 后退出。

## 真实 observation + Astra，仍不执行

相机映射已确认，以下入口可由操作者启动；尚未进行新模型调用验收：
```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B \
  /home/tongji/alex/astra_realman_harness/scripts/run_left_terminal.py \
  --live --model gpt-6-astra --max-steps 50
```
终端输入一次 task，随后输入 `STOP` 加回车可终止；Ctrl-C 同样设置停止标志。模型调用期间可取消本入口启动的模型子进程。只读 SDK 调用需等其返回，软件 STOP 不等于物理急停。没有后台机器人控制进程，没有实际硬件 executor。50 steps 为上界；模型 done、数据/接口/错误异常同样退出。每个 dry-run 的 previous 都明确 `DRY_RUN_NOT_SENT`，不会把拟执行 action 写成执行成功。

工作站浏览器打开终端输出的 `http://127.0.0.1:8765` 看三路画面。HTTP 仅 GET，无机器人控制接口；CameraSession 三路 pipeline 持续打开，预览读取同一 latest buffer，每 500 ms 更新。仅启动上述已确认的三路管线。浏览器显示实时预览，真正送入模型的是每轮保存的 PNG，由 model_input 中的路径/hash 对应；推理期间预览更新不意味着模型持续接收视频。

若在 Mac 远程看预览，登录时改用：
```bash
ssh -L 8765:127.0.0.1:8765 yanglab
```
再在 Mac 浏览器打开同一 localhost URL。终端是任务输入和状态显示，画面在浏览器中展示。

## 每轮输出和独立文件

日志根目录：`/home/tongji/alex/astra_realman_harness/logs/left-terminal-时间-随机ID/`

| 终端阶段 | step-NN 下文件 |
|---|---|
| MODEL INPUT：实际 task、三路路径/顺序、left state、previous、action schema | model_input.json；decision/prompt.txt（真实调用时） |
| ASTRA RAW OUTPUT | raw_proposal.txt；decision/astra_raw.txt；真实调用还保留 last_message.json、events.jsonl、stderr.log |
| PARSED ACTION | parsed_action.json |
| SAFETY | input_validation.json、safety.json |
| PLANNED COMMANDS [NOT SENT] | planned_commands.json |
| EXECUTED ACTION | executed_action.json；dry-run 固定 arm=null、gripper=null |
| SDK RESULT | sdk_result.json；dry-run called=false、return_code=null |
| AFTER STATE | after_state.json |
| NEXT OBSERVATION | next_observation.json，after/ 中真实采集图像或明确标注的历史回放引用 |

真实采集状态另有 input/ 或 after/ 的 left-sdk-sample.json、gripper-raw.json、contact-telemetry.json、observation.json。保存 SDK 已返回的全部原始字段，包括存在的 current/force/effort 字段；字段不存在则 UNKNOWN，不填零，不推导接触力，不新增未验证的读取 API。它们不送给 Astra，不参与接触停止。接口读取错误照常停止。

Astra 原始响应即使解析失败也保留在 decision/astra_raw.txt；模型进程失败/超时在 backend_result.json 记录。模型可观察过程显示运行阶段、耗时和实际输出，不声称提供模型隐藏内部推理。

## 文件职责

- config/left_terminal.json：左端点、三路 serial/顺序/物理确认状态。
- schema/left_opening.schema.json：结构、坐标、开度接口。
- left_terminal.py：模型上下文、严格 parser、输入校验、纯命令预览、模型调用、DryRunExecutor。
- left_preview.py：只读 loopback 预览。
- scripts/run_left_terminal.py：终端 task、STOP、采集、各阶段日志、自动 dry-run loop。
- tests/test_left_terminal.py、tests/left_opening_fixture.json：离线测试。

新入口复用现有 CameraSession、SDKReadOnly、Codex CLI 隔离调用配置；目前不导入 LabGripperAdapter 或调用 rm_movej_p。命令预览保持现有 componentwise XYZ/RPY 相加语义，不缩放、不投影、不做任务规划。控制器限位和 workspace 执行约束未在 dry-run 实际行使，不能把 PASS_DRY_RUN_ONLY 当成硬件执行授权或可达性证明。

## 已完成验收

- 21 项离线测试通过：数值范围、非法值/NaN/Inf、三视角完整性、左臂限定、原始 task 保留、frame/error 校验、STOP 终止自有模型子进程、HTTP 不接受 POST、无运动调用。
- 整链回放：`logs/left-terminal-20261005T080101Z-b2be45ab`。
- `gripper_opening=0.42` -> 预计 wire target=420；原始 proposal、解析结果、预计命令、实际空命令、SDK 未调用结果分别落盘。
- hardware_commands_sent=0；model_calls=0。
- 真实新采集 / 新 schema 的 Astra 返回兼容性：尚未验收。相机物理对应已确认，等待操作者运行真实 dry-run。
