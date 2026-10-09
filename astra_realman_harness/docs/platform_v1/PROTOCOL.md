# astra.realman.platform.v1

此协议冻结读写边界，不包含研究算法。传输为单研究进程 ↔ 单物理owner的stdin/stdout JSON Lines。禁止NaN、重复JSON键和额外RPC顶层字段；解析错误保留原始字节并结束owner运行。每条请求不超过1 MiB。

请求：`{"version":"astra.realman.platform.v1","id":1,"method":"observe","params":{}}`。
返回：同version/id与`ok`；成功为`result`，失败为公开`error`代码。未知错误详情仅在private；错误字符串不传递GT。Client校验应答绑定。RPC调用与结果均有owner日志，失败不是唯一需要剔除的回合。

| 方法 | 参数 | 语义 |
|---|---|---|
| reset | 无 | 新owner第一次绑定并采图；已初始化空夹爪；第二次拒绝 |
| observe | 无 | 重新拍摄三路RGB、当前机器人状态、相机位姿/内参；返回冻结观测 |
| execute | chunk, source_observation_id, proposal_id（null或有效token） | validate_actions → 源epoch/TTL → 当前采图 → owner最低RGB依赖 → 执行；gripper末项前新测量检查 |
| infer | source_observation_id | 已授权且配置的既有FullSlot/CLI处理冻结三路输入；只返回严格解析的原candidate，不自动执行chunk |
| commit | proposal_id | 消费该原candidate；chunk走execute，observe返回新图，finish关闭控制；原stop在infer返回时即停止 |
| events | after：非负sequence游标 | 返回该序号之后公开事件；序号从1开始 |
| stop | 无 | 设置原STOP并取消worker；不重发、不恢复动作 |
| finish | verdict：done/not_done/unknown | 不可逆结束控制；返回closed，不返回评分 |
| score_private | **禁止RPC** | owner关闭控制后调用原FullTaskBackend.finish；研究进程无此方法 |

model candidate只能按原actions、source与token提交一次。执行/提交前不允许将旧delta重复应用、改旧source版本或无token替换待提交候选。每次已开始的chunk，无论成功失败，增加execution epoch；旧图不能用于下一chunk。gripper必须是chunk末项，后续必须使用新测量。合法observe/finish不占动作chunk。

## 动作、状态与时间

沿用`full_pnp_candidate_v2`：每chunk 1..3个动作；`move_pose.pose=[x,y,z,qw,qx,qy,qz]`是world中**动态指垫中心**米坐标及Link6单位四元数wxyz；`gripper.opening`范围[0,1]；`hold.seconds`为(0,2]。不是法兰绝对pose或真机XYZ/RPY增量。

`observe`返回`astra.shared.observation.v1`投影：assembly/fixed/wrist三个640×480 PNG及SHA256、各自camera pose与intrinsic/resolution；SAPIEN相机坐标为+x向前、+y左、+z上。标定直接来自该次相机pose，不伪造硬件标定。

允许的本体字段来自既有`state_projection`：step、stopped、joint_names/qpos、法兰pose、两指垫实际中心、平均中心、pad gap、master qpos。**不含物体GT、接触真值、专家目标、评分、depth或点云。** opening命令和执行ok不证明抓住物体，holding_status明确UNKNOWN。

`captured_monotonic`是owner完成采图的本机单调时间，`capture_span_s`覆盖三路顺序采图；不是硬件曝光同步。每个RGB的`sensor_exposure_timestamp=null`。跨机器/重启的monotonic不能直接比较。事件附episode_id、sequence、monotonic、physics_step、source；初始化与回合时间分开。dt=4ms，每步至少按既有步长墙钟节奏执行；渲染/规划期间会落后，不能由物理步数替代墙钟成本。

返回执行结果包含逐动作ok/合法误差字段、公开错误码、actual_state、结束单调时间/步数、已返回动作及未执行余项。正常失败保留已完成前缀；失败的已尝试动作在results中，不当作未执行余项。意外backend异常时可能已经发生运动，`execution_outcome=UNKNOWN_AFTER_BACKEND_EXCEPTION`，未执行数量/列表为null，另列unknown actions，禁止声称全部没执行。

上限：默认120s回合，可显式设置0<budget≤300s；初始化另计。infer单请求≤min(90s,回合剩余)，所有失败占attempt；真实模式显式N≤20，假CLI模式固定1。每回合≤12动作chunk、≤64次公共采图（包括owner检查采图）；源图180s TTL。原适配器还保留60 action requests、2次闭爪尝试等更内层限额；先到的限制生效。第12 chunk后仍可observe/finish，不能有第13动作chunk。没有自动重试或自动扩额。

外部SIGINT/SIGTERM或传入stop在下一物理step前检查；阻塞规划期间仍需返回到检查点，**不是硬件急停时延保证**。owner预算在step/请求边界检查，初始化/阻塞原生调用没有新增硬实时watchdog。启动/清理异常保留result；结束的研究子进程先等待3s，再TERM等待3s，仍未退出则KILL并回收。

## 边界与证据

研究进程只挂载自己的单文件程序、固定client、解释器和`/public`，网络/PID隔离。模型worker复用原沙箱，仅冻结输入、worker代码、指定Node/Codex前缀与output；假模式无auth/网络。真实模式未来显式授权才复用既有auth，预检在创建scene前完成，不发提示词。

`ENGINEERING_REFERENCE`公开动作参数被遮去，但实际测得的机器人状态保留；参考脚本只在指定参考进程内。infer生成的wire没有脚本目标或工程轨迹，兼容history为空，GT不用于生成策略目标。共享控制器已有接触latch及FCL payload辅助来自仿真，属于公开声明的底层工程辅助；不宣称纯RGB端到端。

- `public/`：版本化events、合法观测、图片和哈希index。只把此目录交给策略/replay。
- `private/scene/`：原始状态、接触/执行、未剪辑视频、独立评分。研究者可在策略关闭后诊断，不向策略挂载。
- `private/workers/request-NNN/`：冻结wire/payload、schema、附件、实际command/env、raw、events、stderr、parsed、usage、attempt各阶段；usage缺失保留null，服务端未返回身份等仍unknown。
- `private/research_stdout.bin`：包括错误/半截RPC的原始字节（最终适配层）；`research_stderr.log`、owner_events记录请求/错误/执行。
- 根`started.json/result.json`：启动命令、版本/文件哈希、初始化/回合墙钟与物理时间、调用计数、退出状态、评分状态（仅研究者可见）。

`Replay`只打开`public` bundle，校验manifest和RGB，不导入模拟器、不执行策略/动作、不能评分。历史转换器只读取原timeline/图像，不从private score补造成功标签；按原时间记录返回动作结果。工程动作参数不导出。实时reset要求新进程，Replay.reset只重置读取游标。
