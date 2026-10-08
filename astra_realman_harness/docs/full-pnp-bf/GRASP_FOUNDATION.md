# 共享抓取、接触执行与真机软件接口预备

2026-10-09。源基线 `41e67f970b98421d36f6d8cccce215e8e674353a`。
本增量最小修复为闭爪后的接触资格检查和执行中的失接触停止；**30mm/opening=0 的穿透根因尚未解决**。不把保护性停止称作抓取成功。

旧结果全部保留；原 qualification 仍为 B=FAIL、F=NOT_RUN、真实请求2、硬件0。当前不扩展 B/F 或 E1–E4，不调用 Astra、不连接硬件。本次新增5个独立工程物理进程（1个否决方案、4个最终回归），没有补跑到成功。

## 最小共享修复

仅在 `sim_skills/full_pnp/backend.py` 接入 `grasp_control.py`；B/F均经过同一个 owner/backend。冻结的 scene、动作分派、payload、requirements、infer环境、物理参数及 −2mm 阈值不变。

| 信号 | 新语义与处理 |
|---|---|
| 原 gripper 命令返回 ok / GRIPPER_EXIT | 仅表示原命令流程结束，不能证明持物 |
| 闭爪接触资格 | 原 latch 存在，且原200步稳定段末尾至少50个连续物理步具有双侧接触（dt=4ms，共0.2s）；无额外等待/二次闭爪 |
| 闭爪后失接触或未建立接触 | 返回明确失败、hold并停止；不上抬、不自动重试 |
| 通过接触资格后连续缺失20步 | 原安全检查优先；随后报 `GRASP_CONTACT_LOST_DURING_EXECUTION`，由原 tick 保存异常并停止。0.08s窗长借用原评分窗，但本保护不等待位移/滑移达到评分阈值 |
| 开爪 / 容差内 no-op | 开爪解除持物接触监测；no-op不重新宣称抓取成立，保留已有有效监测 |
| 稳定持物 | 策略关闭后独立私有评分：连续至少300步、抬升≥50mm、双侧接触、相对滑移≤30mm；桌面闭合接触不等于稳定持物 |

保留原150步闭合目标插值、200步稳定段、0.005rad预载及0.1Nm latch cap。原 gripper 正常调用仅一次。接触真值用于已声明的共同模拟底层辅助/私有评分；不将对象坐标、接触序列或评分送入 B/E/A wire。可见反馈仅保留明确执行失败。工程动作答案只存在专项脚本。

接触定义继续复用原 `bilateral_pad_contact()`：两侧 Support_Link 对物体各有 separation≤0.2mm 且 impulse模长>1e-6 的点。**它按完整连杆碰撞体命名，不证明两个点都在末端指垫区域**。本增量没有更换碰撞体或伪装成真实触觉。新增私有 `grasp_execution_private.jsonl` 保存命令结束、接触资格和失接触事件；独立 assessment 不覆盖原全任务评分。

## 工程回归与时间轴

各新进程用同一资产、原等待步数、XY/姿态和物理速度。Z=40mm、opening=0.45以及相对上抬80mm来自既有工程参考。没有setup_held、直接写物体状态或模型请求；不是精确状态克隆。

| Z / opening | 结果 | 最小 separation | 抬升后300步保持最低高度 | 首次双侧 / latch / 终止step |
|---|---|---:|---:|---|
| 30mm / 0 | 原安全保护中止，GRASP_FAILED | −2.328300mm | 未执行上抬 | 15866 / 15867 / 15875 |
| 30mm / 0.45 | 命令结束但接触丢失，GRASP_FAILED | −0.036956mm | 阻止上抬 | 15995 / 15996 / 16087 |
| 40mm / 0 | STABLE_HOLD_VERIFIED | −1.233162mm | 82.664622mm | 15853 / 15854 / 16770 |
| 40mm / 0.45 | STABLE_HOLD_VERIFIED | −0.109890mm | 80.045877mm | 15985 / 15986 / 16765 |

四格均属 `ENGINEERING_CONTROL_REGRESSION`，只检查接近/抓取/上抬/保持，不执行运输放置退出，不代表完整任务或 Astra 成功率。前两格停止后没有继续物理步。30/.45 在命令结束前已连续90步缺失接触；旧流程允许继续上抬，新流程明确阻止。

四格逐步私有物理状态与原工程四格的共同前缀完全相等；全部共享控制器hash `ff6fdd31bcb38e78272a79fdc032fed6b6d9d1af507128013e4e52131392a473`。这支持最终修复没有改变既有驱动轨迹。独立assessment及backend.finish写入是在首格启动后补齐，专项runner不调用finish；不能声称各格整个源码树hash均相同。运行源码hash、dirty状态和实际命令均保留。

初始化墙钟依次1.524/1.423/1.834/1.356s，初始化物理均3.3s；进程总墙钟72.373/73.562/77.427/76.714s，物理总时间63.500/64.348/67.080/67.060s。分项原值见 final_report.json。

先前尝试的闭合setpoint速率上限0.84rad/s在30/0仍触发原穿透保护，已否决且完整保存；未推广，也未补跑该方案剩余三格。不能据此断言真实闭合速度无影响，实际qvel与接触几何/求解器仍耦合。

## 归因证据等级及剩余缺口

- **VERIFIED**：Support_Link实际碰撞是整个25顶点凸包；最深点在近端局部y≈24mm，末端y≈60mm也有超过−2mm的点。latch后继续穿透存在，不能靠剔除近端点解释成安全正常接触。闭合使pad中心下降约13.4mm。40mm两格在当前条件下稳定持物；30mm两格未通过。
- **INFERRED**：抓取几何与闭合接触动力学的交互是主要根因候选；结果支持高度/目标开度改变接触过程，但没有证明唯一因果因素。
- **UNKNOWN**：mesh近似、实际闭合速度、mimic约束/求解器、预载和扭矩cap各自的因果贡献。原真实回合无闭爪视频及完整法向/impulse；工程复现不能补写历史测量。当前不修改mesh、抓取语义或驱动参数，不放宽穿透阈值。
- 20步失接触停止通过fake scene定向单测；本轮未新增有意抬升后失抓的物理干预。稳定资格仅覆盖这四个固定工程条件，尚无广泛抓取可靠性结论。

## 定向测试与保全

109项相关测试通过（`regressions-verified.log`）：新接触状态/连续性/原安全优先/失接触/STOP/no-op/独立评分/B-E-A最终wire隔离、现有requirements/runtime/review/qualification预算和部分RealMan只读/左右镜像fake接口。

早期失败日志均保留。部分旧测试依赖未提供的实验室driver、历史untracked observation、legacy transforms；初次worktree缺少忽略的logs目录；fake CLI受限环境的bwrap失败另有日志，最终在允许的隔离执行环境通过。**不是全仓所有历史测试通过**，没有安装或升级依赖。

817项旧源/资产/结果hash及此前228项工程诊断归档hash全部匹配；冻结41e67f9工作树仍干净。本次真实模型=0、硬件=0、B/F回合=0。

## 真机软件接口及现场待核验清单

只读取现有代码，未import SDK、加载设备driver或建连；`audit_realman_foundation.py`保存源码hash与实际缺失路径。`hardware_ready=false`，物理执行仍为 NOT_VERIFIED。

| 已有路径 / 语义 | 差异与现场待核验 |
|---|---|
| `realman_api2_readonly.py` 生命周期/只读allowlist | 固定的/home/tongji SDK路径本机缺失；核对现场SDK/.so/driver/config哈希、控制器/固件/型号和返回码 |
| `realman_state.py` 与API2反馈 | JSON整数缩放与API2浮点m/rad、关节deg不可混用；核对采样时间、反馈新鲜度和错误返回 |
| `left_executor.py` 动作 | 仿真绝对world pad-center+wxyz；真机当前控制器pose+XYZ/RPY delta，不能直接代换；核对work/tool/TCP/姿态及动态夹爪偏置映射 |
| `lab_gripper_adapter.py` / `arm_stack.capture_states` | 保留原hand_follow_pos单发与RM-plus原始pos/speed/current/sys_state/dof_err；确认安装夹爪身份、行程/开度→实际间距；ACK、电流、到位均不证明双侧抓持，不能假定安装CTAG |
| 阻塞 `rm_movej_p(...,1,0,0,1)` / STOP | 现路径在发送前、通道间和settling检查flag；没有已验证的运动中硬件stop路径。mock证明阻塞调用内收到STOP后不会再发夹爪，但不能宣称已经停止运动；先核验独立急停链及SDK停机语义 |
| `arm_stack.hold()` | 当前只回HOLD/commands_sent=0，不是经过物理验证的保持命令 |
| 故障与结果核验 | 保留raw返回、部分发送及失败回读，不自动重发；现场核对超时、断线、STOP、恢复边界和命令→反馈时序。现有1mm/0.5deg位姿残差检查不是持物检查 |

通用api2_frame_evidence仍有UNKNOWN，既有supervised_live的特定World-Z10mm证据不能升级为任意公共坐标映射。现场应先只读核验，再在另行授权后做有界低速动作。机械底座安装、刚度改造与重新标定不在本轮范围内。

## 归档与离线入口

交付代码：`/home/alex/astra-realman_ws/astra-realman-grasp-foundation-20261009`。
交付证据：`/home/alex/astra-realman_ws/astra-grasp-foundation-evidence-20261009`。
入口均要求新输出路径，不覆写旧结果；以下仅供复核，不自动执行新的物理回合。

```bash
# 静态SDK/接口清单：不导入驱动、不连接设备
/home/alex/astra/.venv/bin/python /home/alex/astra-realman_ws/astra-realman-grasp-foundation-20261009/astra_realman_harness/scripts/audit_realman_foundation.py --output /tmp/realman-foundation-audit-new.json

# 单个独立工程物理回归：非Astra、非B/F
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python /home/alex/astra-realman_ws/astra-realman-grasp-foundation-20261009/astra_realman_harness/scripts/run_grasp_contact_regression.py \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --z-mm 40 --opening 0.45 --output /tmp/grasp-engineering-new-40-045
```

回归详表 `final_report.json`；时间轴/原物理前缀比较 `physical_prefix_and_timeline.json`；旧结果保全 `preservation_after.json`；源码与现场清单 `realman_preparation.json`；整体验收 `acceptance.json`。旧穿透归因仍见独立的 `astra-grasp-causality-evidence-20261008/REPORT.txt`。没有新增真实模型预算或后续实验自动启动入口。
