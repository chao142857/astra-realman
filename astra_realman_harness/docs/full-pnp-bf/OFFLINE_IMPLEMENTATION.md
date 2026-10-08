# 阶段1–3离线增量

基于 `2db1e3f`，保留设计卡和既有代码/结果。本文件是增量状态说明；旧文档中的“未实施”描述其冻结时点。验收数值另见 `OFFLINE_ACCEPTANCE.md`。

## 运行入口

```bash
/home/alex/astra/.venv/bin/python astra_realman_harness/scripts/run_full_pnp_offline.py \
  --condition F \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --output /tmp/full-pnp-UNIQUE --video
```

`--condition script|B|F`；每次使用全新目录和进程。默认完整任务120s、每请求30s且不超过剩余预算、最多32次**stub**请求，延迟0.8s。没有真实模型开关，不继承旧9请求预算。版本/帮助预检不发送提示词。脚本答案只存在 script 分支的私有文件；B/F worker 只能读冻结输入。

`scripts/audit_full_pnp_offline.py OUTPUT` 逐个检查实际 `input_only/wire.json`、PNG、`input_payload.json`、schema和worker raw，并生成时间轴。`input_payload.json` 是现有 `codex_astra_mac_bridge.infer` 形状的离线投影，**没有发送 Astra**。本轮调用0、硬件0；API、token usage、服务端身份/effort/内部重试均未测，unknown/null。

## 共同物理链

`FullTaskBackend`继承原`RM65Backend`的hash校验、场景/渲染/视频；只增加object-independent空手准备。新任务`setup_held`直接报错。完整旧`ModelAdapter`按原hash只读复制，复用dispatch/update_payload/record_step/finish；不启动AF_UNIX服务。绕开旧四原语adapter的任意夹爪后detach：闭合保持规划payload，打开才detach；无物理焊接或瞬移。底层FCL几何、接触预载和载荷几何是已声明的共同GT辅助，不能生成策略抓取/释放坐标。

共同chunk为1–3个原绝对`move_pose`/`gripper`/`hold`；gripper必须末尾；不提供move_delta。owner提交票据分别保存原候选source和**真实新采集**commit观测，原候选不改号。单owner独占scene和render；同一step_hook串行组合私有评分、worker轮询和最小4ms节奏，无追赶加速。B等待保持，F仅执行已批准父chunk。

私有评分在策略关闭后进行；旧完整抓放评分加退出判据：指垫中心z≥80mm、最小指垫中心至物体定向盒距离≥30mm、无双侧接触；旧评分还要求打开夹爪、稳定抬升≥50mm连续300步、未闭夹爪掉落、目标区稳定释放。退出的几何测量是**指垫中心**，不是全夹爪mesh距离。旧score字段`model_action_decisions`计owner dispatch，不能当API调用数。

## F职责与输入隔离

E和A是宿主调度的独立进程/请求，单槽串行；E看三路缩略图，返回选图、bbox、未知/假设；A看当前全局+所选细节/合法裁图+可选旧帧，依赖E产物hash。源码只复用已有worker lifecycle和白名单环境，没有新服务。bwrap只挂载系统/venv、冻结`/input`和`worker.py/rgb.py`，无scene、score、脚本答案、凭据、宿主网络。

初始、抓取后、释放后必须E调用；其它段只在当前RGB检查有效时复用，并单独计E调用/复用。历史最多5个完成transition、8个来源假设，保留未解决失败；预测接续点标PREDICTED，未来事件禁止入实测历史。旧bbox仅历史定位，identity仅未确认假设；当前对象可见状态和ROI须由当前RGB重新检测。相机变化/对象未知时不复用旧ROI并触发E。

非夹爪chunk执行40步后可冻结下一轮输入，整个E→A可以在运动中推进，最多一个未来候选。包含gripper的chunk不预取；结束新观测后提升barrier epoch并清空E缓存。父执行失败/STOP取消并丢弃未来候选；过期/协议/启动失败无自动重试。RGB失效可以在新观测下显式重提，最多2次，全部计费；不是复用旧候选。无有效候选时保持驱动目标。

## RGB提交门（共享工程检测器）

实际像素连通域：红`r>60,r>1.8g,r>1.8b`；绿`g>45,g>1.35r,g>1.3b`。少于18像素、第二分量≥最大35%、边界裁切、低图像方差均unknown；没有GT mask。静态检查要求相机姿态不变、两帧可辨组件、质心位移≤6px、面积比[0.25,4]、颜色cos≥0.95。近工具检查使用真实机器人指垫中心投影与当前红组件的1.5 bbox对角线距离；放置表观检查用当前红/绿质心距离≤绿框对角线0.6倍。它们是工程表观约束，**不是身份/接触/三维放置正确性的证明**。

所有可辨视图若有矛盾则拒绝；其余视图明确unknown时至少一个有效视图才通过；全部unknown保持/重看。相同blank图hash不能通过。关闭夹爪强制object_static；打开强制goal_static+object_near_tool；done强制object_at_goal；所有提案强制scene_healthy。每个采用候选保存逐视图数值和真实接续位姿检查（<10mm/<0.05rad）。本轮检测器适用于固定红块/绿区，不声称通用视觉能力。

## 计时和成本

初始化与完整任务分开；完整任务从首观测前到独立稳定评分结束。冷启动、物理时间、墙钟、各请求启动/结束/准备、所有捕获帧、裁图、历史、取消/重提及保持计入证据。推理重叠仅算**最终被采用候选依赖**的worker实际计算区间与其父计划EXEC/GRIPPER区间的交集；不把进程启动或已批准hold当运动重叠。接续等待从父chunk结束到有效候选提交，包括新图/检查；首个冷启动单列。

## 声明与缺口

script使用GT答案，只证明物理链。B/F使用当前RGB、标定、公开平面先验估计坐标，但阶段策略是手写stub；ROI已实际生成/附入A，当前启发式坐标估计仍用全幅细节图。因此不证明Astra视觉决策、ROI收益、真实角色推理或系统提速。真实infer生命周期尚未启用；不通过调用工具模拟真实请求。严重遮挡恢复、不同可达初始化配置和真实模型结束判断，仍需后续离线开发/另授权验证。
