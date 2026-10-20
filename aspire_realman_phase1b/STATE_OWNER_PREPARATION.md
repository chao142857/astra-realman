# 单臂真实只读状态owner：准备完成，现场接入未启用

本轮未确认机械臂供电或取得新的现场读取授权，SDK导入/连接/读臂/动作数均0。复用已有工作区和`aspire_realman_live`包，只新增邻近的`state_owner.py`接收缓存，不新增框架、设备驱动、SDK连接器、任务策略或MCP层。原LiveSource、Adapter、Runtime Factory及运动拒绝未改。

## 已实现边界

`SingleArmStateOwner`一次明确一个arm（优先left）、producer id、source kind和host boot/clock id。接收未来唯一SDK owner已经采集的`SDKReadOnly.snapshot(arm)`样本及host monotonic读取区间；本模块没有SDK/socket/subprocess导入，`connect/start/poll_once`无条件拒绝。它不是已经在线运行的真机owner。

- 检查单臂归属、六个有限joint deg、SDK xyz米/RPY弧度、Work/Tool前后稳定及可选预期指纹；不对SDK值再次做毫度/毫米换算。
- 声明LIVE的样本须有5项成功SDK返回码。缓存序号/读取区间严格递增，LIVE源时间不允许重复刷新；拒绝后owner失败状态保留，旧样本不能继续标为正常。
- 源state时间保留SDKReadOnly的host epoch `state.finished_at`，另保留host monotonic起止区间；不是控制器采样时刻。没有controller时间时明确null/未知，不推断测量延迟。
- 历史模式永不标成live；新缓存接收时间不会更新历史源时间。跨host/boot域不相减。相机/状态的同域host接收区间只报告可能差值上下界，不能称曝光同步。
- velocity缺失为null，gripper缺失为null，保留system_error、Work/Tool/端点UNKNOWN及非原子采样标记。不补零速度、夹爪状态、共同World或TCP。
- `as_native_state()`拒绝，`native_robot_state_available=false`。当前未绑定CAP，未通过历史或合成数据伪造完整Observation。

`check_state_owner_preparation.py`仅以既有封存历史left状态验证上述边界及只读返回副本，并注入错arm、坏单位、变帧、重复序号、缺少真实SDK读取记录、跨时间域等错误。结果为`OFFLINE_OWNER_CONTRACT_PREPARATION_PASS_NOT_LIVE_INTEGRATION`，不算真机测试；`evidence/state_owner_preparation.json`保留原历史样本SHA和明确source kind。

## 现场实际代码映射

以下文件在yanglab实际部署目录只读审阅、未导入，SHA与Phase0一致；没有根据GitHub副本猜测行为：

| 文件 | SHA256 | 事实 |
|---|---|---|
| `H/realman_api2_readonly.py` | `b690a92982b0a111f60b193ad34b67ccc60ea26ebe31eb88f59d663fc9e0aef7` | SDKReadOnly的READS仅current_arm_state/current_work_frame/current_tool_frame；进入context会加载SDK并rm_init，不可因名字含readonly就随意实例化 |
| `H/arm_stack.py` | `b1206688f9de53fdbdb6a2eb75fc0f53fe6ea7e52e0dcedadec3fa46748415f9` | capture_states还会额外调用RM-plus gripper读取，并可能采相机；不直接当本轮单臂纯状态owner启动入口 |
| `H/realman_state.py` | `5f5ce26c2fbd5dfb6dafdfad2b93e9308d471032649882ec86f55ee809c58f22` | 包含TCP原始毫度/微米转换路径，不能与SDK已是deg/m/rad的canonical混用 |

H=`/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness`。

SDKReadOnly实际`sample=service.snapshot('left')`次序为work_before→tool_before→state→work_after→tool_after；分别调用`rm_get_current_work_frame`、`rm_get_current_tool_frame`、`rm_get_current_arm_state`。失败时canonical=None，不能填默认值。规范化源保留pose frame_semantics_status=UNKNOWN、reference/target=null、snapshot_atomic=false。该snapshot没有速度或夹爪反馈；arm_stack的额外RM-plus读取不在SDKReadOnly三项READS中，不能静默扩大allowlist。

## 后续现场接入顺序（本轮未执行）

1. 现场确认供电、只读授权与现有SDK owner；若已有owner则从该owner订阅，不创建竞争句柄。新会话的SDK lifecycle仅限已审核版本、明确left scope和新日志目录，不启动GUI/执行器/后台运动循环。
2. 唯一SDK worker在`SDKReadOnly.snapshot('left')`调用前后记录同host boot id下的monotonic/epoch区间及完整返回码，原始事件写新目录；状态、Work/Tool指纹、错误都由该样本提供。设备时间未知就保留未知。
3. 通过inbox发布原始sample及读取区间；当前关节/原始端点可先作为单臂诊断展示。先做源新鲜度、重复帧、错误和断线检查，不把session refresh时间当采样时间。
4. 现场核对当前Work/Tool、端点reference/target及硬件身份/DH/FK；历史零Work/Tool不能当新的语义绑定。单臂可使用明确的该臂参考系，不要求先伪造公共World。实体TCP仍不因此自动已知。
5. 确认速度/夹爪真实反馈能否在审核后的只读边界提供。现有native RobotState要求速度与夹爪数值；Phase0.5 Replay Codec用过带metadata的未测速度占位，**不能未经决策直接复用到真实live数据**。本轮保持拒绝，不通过0填充让native state看似完整。
6. 有上述当前证据后，才在现有LiveSource/Codec/Factory上做最小单臂绑定；相机与状态join必须保留双方源时间及区间，先单臂scope再讨论双臂公共坐标。当前inbox没有接入实时runtime，单臂typed RobotState与完整CAP Observation仍是后续工作。

本轮所有运动入口继续由原Adapter/CAP硬拒绝；不存在动作开关、Home推断、夹爪命令、自动恢复或任务专家。用于准备的历史/错误样本永不成为当前机器人状态。

复现准备检查（新输出文件）：

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
/home/tongji/alex/aspire_realman_phase1a_20261020/.sam3-venv/bin/python -B \
  aspire_realman_phase1b/tools/check_state_owner_preparation.py \
  --output evidence/state-owner-preparation-recheck-new.json
```
