# 单臂只读入口：可运行软件交付，等待现场接电与授权

基于`5dd2c4b0`，继续使用现有工作区、现有独立环境和ASPIRE `fa00f0e`；原生Agent/Prompt/MCP桥/server/executor及已有历史结果不修改。本轮没有真实SDK导入、机械臂连接、相机打开或动作派发。原生完整RobotState/Observation仍不可用，但基础单臂诊断展示不要求双基座World或实体TCP。

## 运行入口与现场调用范围

`aspire_realman_phase1a/tools/serve_readonly_state.py`默认只输出plan，校验71份ASPIRE源码、现场reader三文件及SDK文件SHA，不导入厂商SDK。真正的读取实现位于`aspire_realman_live/sdk_state.py`：

1. 只有明确`--connect-readonly`及供电、只读授权、唯一owner三个现场确认参数才允许进入。参数是操作者声明，不能由SSH可达、历史日志或进程存活自动推断。当前未提供这些现场确认，也没有执行连接模式。
2. 优先订阅已有owner：新worker只适用于现场确认没有现成SDK owner的情况；现有同进程owner可直接向`SingleArmStateOwner.publish()`发布同合同样本，不能再创建第二个句柄。本入口使用合作文件锁及当前网络命名空间`/proc/net/tcp`检查显式IPv4端点，发现已有连接即拒绝；它们不能取代操作者对其他命名空间/远端owner的确认。
3. 将已核验的现场`realman_api2_readonly.py`、`realman_state.py`、`io_utils.py`逐字复制到**新run/verified_reader/**。原reader的write_json限制写入模块目录，因此复制是避免改写原部署的必要步骤，不是修改driver。SDK Python/so沿用原只读路径并在加载前校验，无版本回退或依赖安装。
4. 生命周期仅`rm_init/create_robot_arm/delete_robot_arm/destroy`；读取仅`rm_get_current_arm_state/current_work_frame/current_tool_frame`。顺序work_before→tool_before→state→work_after→tool_after。无RM-plus夹爪、错误清除、坐标配置或运动API。
5. 每次读取保存完整五返回及各自epoch起止、整个读取的host monotonic/epoch区间、boot clock id；只发布成功且Work/Tool前后一致的canonical。`sdk-sample-NNNNNN.json`独占写入，`latest.json`原子替换，原始SDK事件另存`verified_reader/events/`。失败样本同样保存，随后owner失败，不以旧样本继续表示健康。
6. 有界运行1–60秒，轮询周期0.2–5秒；只启动本进程的localhost MCP。正常结束/Ctrl+C/SIGTERM只清理本进程句柄、SDK和服务器，关闭后的latest明确不可实时使用；没有自动重连、Home或动作开关。物理SDK超时和异常退出仍需现场验收，不将离线清理结果冒充现场结果。

## 语义及CAP/MCP

SDK关节角单位deg，展示同时提供rad；端点xyz单位m，RPY单位rad，不重复按原始TCP整数协议缩放。host source timestamp是SDKReadOnly内state调用的finished_at，非控制器采样时刻；设备时钟及测量延迟上界仍未知。重复源时间、过期、跨boot域和失败owner不能变成当前状态。相机订阅可用时只报告同host接收区间差界，不宣称曝光/控制器同步。

| 字段 | 现有证据与展示 | 仍需现场确认 |
|---|---|---|
| joint 1..6 | 六个SDK原始关节角及单位，单一arm scope | 对应实际型号、关节顺序/方向与当前设备身份 |
| Work定义 | 控制器当前名称、数值、指纹；定义相对该臂controller base | 当前设置是否对应安装；名称World不等于双臂公共World |
| Tool定义 | 当前名称、数值、指纹；定义相对controller flange | Arm_Tip不等于实际夹爪抓取中心或经过物理标定的TCP |
| state.pose | 原样展示xyz/RPY，reference/target保持null，语义UNKNOWN | 当前控制器/固件返回的pose绑定；不能仅凭名称或零offset推定 |
| velocity/gripper | 当前三类SDK读取没有这些字段，保持null | 有审核依据后再决定是否扩充只读反馈；不补零 |

官方[Work API](https://develop.realman-robotics.com/en/robot4th/apipython/classes/workCoordinateConfig/)说明Work定义相对base；[Tool API](https://develop.realman-robotics.com/en/robot4th/apipython/classes/toolCoordinateConfig/)供核对工具定义。[current-state结构](https://develop.realman-robotics.com/robot4th/apic/struct/currentState/)只列当前pose等字段，不能单独完成当前安装的参考/目标绑定。这里不执行文档中的任何示例。

接入沿用`build_live_runtime(source, state_owner=owner)`。无相机时source=None，arm scope只含当前单臂。使用原生ToolRegistry的配置扩展点注册一个metadata函数`get_readonly_state_snapshot`，并通过原生program catalog增加固定一行`result = get_readonly_state_snapshot()`，MCP工具名为**`cap_program_readonly_state`**。它只查询缓存，不连接SDK，不承担任务决策、目标选择或控制。原生MCP桥、server和Agent源码没有改动。

此工具返回source kind、关节/原始端点、Work/Tool、错误、timestamps、质量、缺失字段和motion=false。端点始终标明不是实际抓取中心。真正LIVE且host时序合格时，原生`observe(cameras=[])`可以展示单臂关节及命名为`unbound_sdk_*`的数值；失败/历史/过期则monitor明确stale。历史和离线注入数据只能通过显式带source kind的诊断查询返回，不能进入当前monitor状态。无相机时默认tabletop请求会报告相机缺失，需显式cameras=[]。

原生`cap_get_robot_state`及完整Observation继续拒绝：原生合同要求全部速度、端点Pose与夹爪，而当前数据不完整。这个缺口不阻塞上述基础状态展示，也不通过伪造World/TCP或改Agent逻辑绕过。全部运动入口继续硬拒绝。

## 已执行验证与复现

在yanglab复用Phase1A **`.venv`**（CAP/MCP依赖齐全），不使用仅装SAM3的`.sam3-venv`。一次早期验证误用SAM3环境，实际报缺少httpx；没有安装依赖，改用现有正确解释器。另一次隔离目录缺少已有package文件，已同步必要Python源码，未改原部署。

最终`evidence/readonly-entry-final/validation.json`使用显式`OFFLINE_SDK_TRANSPORT_FIXTURE`：运行实际校验复制的SDKReadOnly类，注入历史数值作为传输fixture；验证五次读取、单位不二次换算、发布、原生HTTP MCP发现/查询、变帧拒绝及delete/destroy清理。没有加载Robotic_Arm或so，没有真实连接。Work前后不同由注入返回触发实际canonical逻辑，不替换canonical函数。基础相机质量6项回归通过、71份ASPIRE源码匹配。已有原始结果SHA另行核对。

新raw RGB-D保存函数的独立序列化检查也通过：raw depth与aligned depth使用不同尺寸输入，确认分别保存；此处是合成数组写盘检查，**不是现场raw capture验收**。完整日志留yanglab，轻量引用/校验见`evidence/readonly_owner_acceptance.json`。

最短无连接预检（已运行）：

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
/home/tongji/alex/aspire_realman_phase1a_20261020/.venv/bin/python -B \
  aspire_realman_phase1a/tools/serve_readonly_state.py \
  --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE
```

复现实际reader/MCP离线验证（输出目录必须全新）：同一解释器运行`aspire_realman_phase1a/tools/validate_readonly_state.py --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE --output evidence/readonly-entry-recheck-new`。

**以下只供现场确认之后执行，本轮没有执行。**在上面的serve命令后指定`--arm left --robot-host <已核对的该臂IPv4> --robot-port <可信配置端口> --output evidence/readonly-onsite-new --seconds 30 --connect-readonly --onsite-power-confirmed --onsite-read-authorized --sole-sdk-owner-confirmed`。启动后`mcp-endpoint.json`记录随机localhost端口；MCP `tools/list`应含`cap_program_readonly_state`，调用后确认source.kind=LIVE_SDK_READ_ONLY及时间质量，再调用observe(cameras=[])。本步骤没有Home、夹爪动作或任何轨迹。

## 下一次现场最小步骤

1. 操作者确认供电、机械臂只读授权、身份/端点、现有owner；从单臂开始。先plan，再有界读取，核对当前Work/Tool和系统错误；不清错、不配置、不运动。
2. 比对当前关节及端点语义，记录控制器实际返回与现场界面/设备配置证据。公共World和实体TCP单独待标定，不作为基础读数阻塞，也不改名冒充已知。
3. 相机按`RAW_CAPTURE_NEXT.md`进行一次同owner短采集，保存真正align前原始流及已知尺度参考；不复用旧aligned深度伪造原始流。
4. 现场验证断线、慢读取、变帧、过期和退出后句柄释放；随后才决定速度/夹爪只读反馈的合同扩充和完整RobotState可行性。当前不自动进入运动阶段。
