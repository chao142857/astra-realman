# Phase0离线验收与证据

## 执行结果

- 标准库 Python3.9.6：**19项通过，8项原生核心检查明确skip**，详见 `evidence/offline_stdlib_tests.json`。
- 已有bundled Python3.12.14 / NumPy2.3.5＋固定ASPIRE源码：**27/27通过，0 skip**，详见 `evidence/offline_native_tests.json`。没有pip/conda/uv安装，没有改现场dp/aloha等环境。
- 本轮新增机器人/夹爪派发、相机pipeline、模型请求均为**0**。这是本轮实现/命令范围的计数，不是对其它用户或既有服务动作的全局遥测结论。
- 真实MCP HTTP transport、SAM3权重推理、cuRobo GPU规划、全ASPIRE测试套件、真实SDK通信/机械精度/同步/碰撞/在途停止均**未运行**。所查环境缺MCP/FastAPI/uvicorn/SAM3/cuRobo依赖，记录为后续环境缺口，不自动安装或启动。

首个native Mock测试批次为25通过/2失败：测试夹具遗漏 `ExecutionResult.steps_executed` 必填字段，且常数深度平面被原生几何正确拒绝为退化三维包围盒。已仅修正新工作区测试夹具（补零步回执、使用非平面synthetic depth），同批27项全通过；没有改上游或现场实现来绕过失败。

## 测试覆盖与含义

| 组别 | 实际检查 | 不代表什么 |
|---|---|---|
| 派发拒绝 | pose/joints/synchronized/gripper/open/close/set_grippers/step/trajectory/home/reset先拒绝；poison payload不被读取；没有enable参数；不接受任意hardware source | 不是底层控制器机械急停试验 |
| Replay合同 | 原始step-001 **after** observation投影、4个历史RGB serial、哈希/路径、copy隔离、不打开记录的文件/设备路径、历史帧不冒充fresh live | 不代表当前4相机在线或已加载像素/depth |
| 单位/坐标 | joint deg→rad一次；xyz不缩放；RPY rad→WXYZ；SDK原UNKNOWN不覆盖；两base/TCP保留null；缺velocity不编零 | 不代表实现了共同World或已测实体TCP |
| 反馈错误 | arm身份/unstable work/tool/非有限joint/错误单位/非法gripper拒绝；opening与grasp分离 | 不代表闭爪接触/力/承载已验证 |
| 标定文件 | 4个真实历史矩阵数学上刚体，全部保留估计标签/false执行授权 | 不代表几何外部精度验收或新设备安装仍有效 |
| 原生CAP | 未改源码的pose schema/度转四元数、observation/state、Mock mask＋synthetic RGB-D反投影、gripper/trajectory到拒绝边界、无planner的pose/sync失败 | 不代表真实SAM3/cuRobo可用或已验证硬件规划 |
| 原生session | Embedded runtime仅启动本地Mock job、terminal失败回执与关闭 | 没有启动Agent模型/HTTP监听器/GUI/相机 |
| 原生限制 | RealMan未注册、EEF不同base被RobotState拒绝，实际测试复现 | 没有用YAM别名/identity阵绕过RealMan缺失标定 |

原生测试中的yam_real维度身份只属于显式synthetic夹具，数据全部人造且没有设备传输。真实Replay从未被标成YAM。标准库包是draft JSON接口，仍需后续真实embodiment注册及typed adapter实现。

## 证据索引

| 文件 | 内容与审计粒度 |
|---|---|
| `evidence/upstream_lock.json` | ASPIRE完整提交及所审关键源码/原生Skills的SHA；未初始化submodules、未取权重。release为commit说明；包元数据version仍0.1.0，不假设存在v1.0 tag |
| `evidence/host_audit.json` | 2026-10-20 00:01:04+08只读快照：两个repo状态、process argv/cwd、设备fd、sysfs serial、GPU/包metadata/监听端口。未读env变量或认证值 |
| `evidence/final_readonly_verification.json` | 00:08:26+08原四服务PID仍在；当前371项实现与V17成功manifest全部相同；原关键源码SHA、控制YAML、GPU与当前USB复核 |
| `evidence/deployed_file_manifest.json` | 本轮读取的现场SDK/部署/标定/原始run小文件路径、字节数、原始文件SHA；不存在文件也保留error |
| `evidence/extra_file_manifest.json` | 实际CameraSession/shared-client/arm_mirror与一份RGB-D描述的指纹 |
| `evidence/camera_transform_inventory.json` | 四历史相机真实外参完整矩阵、parent、serial、来源SHA、估计/未复核当前mount状态；base/TCP null |
| `evidence/rgbd_metadata_inventory.json` | O封存000003三路真实aligned depth/Z16/mask的路径/哈希/单位/K与时间域；不是数组本身，数组未复制或重算 |
| `evidence/historical_runs.json` | V17成功、失败、V19原summary/launch参数/相机与371项实现一致性摘要；每份原文件SHA；不是完整原始日志 |
| `evidence/replay_snapshot.json` | 一份V17成功轮step-001 after观测的字段投影，用于离线接口检查；原文件SHA与来源路径完整，明确metadata only |
| `evidence/offline_*_tests.json` | 运行解释器、数量、skip、结果与范围 |

原图、视频、完整逐步日志、轨迹、SDK二进制、ASPIRE源码和模型均不随此分支提交。现场完整原始证据仍在H/O对应logs，后续审查用路径与SHA定位，不把本报告片段当完整归档。

## 已知限制与后续验收

只读文件/进程快照不证明控制器现在可连、服务健康、相机画面新鲜或安装未动。本轮没有查询8888的鉴权state/capture接口，更没有rescan/stop。新的相机serial与历史不一致是明确阻塞，物理原因未知。

后续先在新隔离环境补typed adapter/MCP wire，完成坐标和独立计量后再讨论真实执行。当前结果是“可继续离线实现”，不是“真实双臂基线已经建立”。Phase1及任何真实模型任务/运动均需后续明确安排，本轮不自动进入。
