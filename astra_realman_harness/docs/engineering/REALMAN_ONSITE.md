# RealMan现场软件接口核验（未连接、未执行）

复用 `realman_api2_readonly.SDKReadOnly`、`realman_state`、`lab_gripper_adapter`、`left_executor`、`arm_stack`、`execution_verification`。没有新建驱动/控制框架。本轮读取实际源码；不根据仿真替现场参数填值。

模板 `config/engineering/realman_readonly_template.json` 中实际IP/port/arm、SDK哈希、控制器/序列号/固件、world→base、work/tool、法兰→抓取TCP、RPY约定、夹爪身份、开度→gap、电流→力、持物证据、运动中STOP和故障恢复均为UNKNOWN；`execution_permitted=false`。

| 顺序 | 现场只读/软件核验 | 未核实前的界限 |
|---|---|---|
| 1 | 核实安装SDK Python/.so路径和SHA256、实际控制器/固件/型号及唯一机械臂身份 | 当前固定SDK路径为/home/tongji/aloha/RealMan_Control/Robotic_Arm；本机不存在，不另找版本自动替换 |
| 2 | 读取arm state、work_before/tool_before及after，保留返回码/原始字段/主机接收时间 | 快照非原子；SDK返回m/rad、关节deg，原JSON整数缩放走另一代码路径，不能重复缩放；设备曝光/时间同步和新鲜度上限UNKNOWN |
| 3 | 用文档与现场测量确认状态pose的reference/target frame、world/base/tool/TCP与姿态约定 | 相同frame名字或零偏置不能建立绑定；仿真绝对动态pad-center+wxyz不能直接当真机XYZ/RPY增量；旋转应在确认坐标后组合，不能假定RPY逐项加法等价 |
| 4 | 确认安装夹爪、实际行程、位置反馈、RM-plus speed/current/sys_state/dof_err、命令ACK | hand_follow_pos单发保持；0..1000位置与仿真opening不等价；ACK/到位/电流不证明接触或持物，电流→力仍UNKNOWN。此只读入口尚不采夹爪额外字段，现场须先验证已有读取协议 |
| 5 | 独立核验急停链、SDK运动中停止调用、ACK/制动完成时序 | `rm_movej_p(...,1,0,0,1)`为阻塞调用；现executor仅在发送前/通道间/settling响应软件STOP，不能声明已停住在途运动；`arm_stack.hold()`为返回状态、commands_sent=0，不是物理保持 |
| 6 | 复核已执行部分、超时/断线/故障码/失败回读、停止后恢复协议 | 不自动重发，不自动清错，不把部分成功合成完整成功；阻塞中的状态/取消是否生效UNKNOWN；进程退出不是急停证据 |
| 7 | 完成以上证据后另行授权有界低速执行验收 | 现1mm/0.5deg位姿残差核验不证明抓持。软件准备通过不是硬件验收。机械安装/刚度/重新标定不在本轮实施范围 |

以下命令可在当前机器运行，只做文件/配置检查，不import SDK/.so、不建连。UNKNOWN模板应返回NOT_READY（退出码2），这是正确拒绝：

```bash
CODE=/home/alex/astra-realman_ws/astra-realman-shared-pnp-engineering-20261009/astra_realman_harness
/home/alex/astra/.venv/bin/python "$CODE/scripts/prepare_realman_readonly.py" \
  --config "$CODE/config/engineering/realman_readonly_template.json" \
  --output /tmp/realman-static-check-new-01
```

后续现场完成真实地址/SDK哈希核验、并另行授权**只读连接**后，才使用下列单臂单快照入口；本轮没有执行：

```bash
# 用独立现场配置副本替换UNKNOWN；勿修改原模板冒充已核实。
# SDK日志受现有io_utils路径边界限制，输出必须在harness下且不存在。
timeout --signal=TERM --kill-after=5s 30s /home/alex/astra/.venv/bin/python "$CODE/scripts/prepare_realman_readonly.py" \
  --config "$CODE/config/engineering/realman_readonly_site.json" \
  --output "$CODE/logs/realman-readonly-site-01" --connect-readonly
```

此入口只复用connect/read/close白名单，没有动作、夹爪发送、设置frame、清故障分支；仅一份快照，无重试。外层超时仅限制诊断进程，不代表硬件STOP；被强杀时SDK句柄清理可能未完成，必须保留日志核查。读取工作/tool的定义仍不能消除末端pose绑定UNKNOWN。
