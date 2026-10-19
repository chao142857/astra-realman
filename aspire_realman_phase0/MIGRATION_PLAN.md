# 迁移方案与只读审计

## 结论与审计范围

选择独立 `RealManAdapter`，保留 ASPIRE 的 Agent 启动提示、原生 Skills、`CapApi`、持久 `EmbeddedAgentRuntime` 与 MCP。适配器只负责硬件身份、单位/坐标、观测、通用执行和可核验回执；不迁移香蕉抓取/交接专家程序，也不把 ASTRA 的动作规划器或任务提示塞进 ASPIRE。

本轮通过既有 `ssh yanglab` 读取文件、`/proc`、`/sys`、GPU/编译器元数据。**没有初始化 RealMan SDK、连接机器人 IP、打开 RealSense pipeline、请求原 GUI API、启动模型/provider 或停止服务。** 所有新文件只写 Mac 新隔离目录；远端仅运行内存中的读取脚本。OS 自身 SSH 审计日志等不属于应用部署改动。

网络先读 `NETWORK-P0-20261016`。实际 `ssh -G yanglab` 为 `tongji@100.69.48.93:22`，与政策中的历史 `100.78.222.78` 不同，小流量 hostname 请求成功；没有修改代理、TUN、SSH、凭据、驱动或环境。现场已有 Mihomo/Clash 监听，不套用历史“无代理”的描述。没有读取或保存认证文件。上游只取固定提交的选择性源码，Git pack 合计约 306 KiB；未取媒体/mesh/子模块/权重。只读缓存不进提交。

## 现场真实目录、版本与环境

| 项目 | 本轮实际核对 | 迁移影响 |
|---|---|---|
| 主机 | `tongji-Precision-3680`；SSH 初始目录 `/home/tongji` | 部署路径不能由本地副本推断 |
| 当前 GUI/实验工程 H | `/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness` | PID 1268122 的 cwd 与脚本均来自 H；8888 硬件 GUI 已在运行 |
| H 所属 Git | HEAD `0ec0472687e7c7c6500d1cfa0c76a67b1d57871b`，分支 `codex/realman-chunk-gui-migration-20261017`，大量 modified/untracked | 不是远端成功归档分支的干净 checkout；以文件 SHA 为准 |
| 标定工程 O | `/home/tongji/alex/astra_onsite_1011/astra_realman_harness` | HEAD `431f112c…`；三相机与采集/标定代码存在未提交增量，不能只 clone HEAD |
| GUI 的三相机参数 | 指向 O 的 `config/engineering/three_camera_calibration_20261011.json` | H 本地没有同名三相机配置；实际跨部署引用已核实 |
| 本地独立分支基点 | `chao142857/astra-realman` 的 `3d765ab9cd8a41fe226db1fd7ea507998752440b` | 仅在新分支新增本目录；不改 V17 成功归档分支 |
| GPU | RTX 3060，12288 MiB，driver 535.230.02；初始占用约451 MiB | 不能据显存断言 SAM3+cuRobo 能共驻，需后续独立基准 |
| CUDA | nvidia-smi 显示兼容上限 CUDA 12.2；`/usr/local/cuda/bin/nvcc` 为12.1.105 | 区分驱动支持上限与实际 toolkit；没运行 CUDA kernel/编译验证 |
| Python | system3.8.10；conda base3.13.13；dp/aloha3.9.18；xr_pico3.10.19；lerobot3.12.13 | ASPIRE要求 `>=3.10,<3.13`，system/dp/aloha/base 均不匹配；不升级它们 |
| 既有依赖 | dp: torch2.1.0+cu121、NumPy1.24.4、RealSense2.56.5；xr_pico: torch2.12.1、NumPy2.2.6；lerobot: torch2.7.1+cu118、NumPy2.2.6 | 所查环境均没有 mcp、SAM3、cuRobo、FastAPI、uvicorn；读取 distribution 元数据，未 import torch/SDK |
| 既有服务 | PID26282:8886离线GUI；32647:8771右腕归档预览；110607:8890本地静态HTTP；1268122:8888硬件GUI | 结束复查见证据，未停止/重启/抢端口 |
| 相机占用 | `/dev/video0..5` 属于同一USB设备；GUI PID1268122持有 `/dev/video4,5` | 多个 video 节点不等于多台相机，未打开/重配 |
| 当前可见USB | 8086:0b07 D435，serial `027223021284`，与历史四路不同 | 原四路“当前在线”未验证；不猜角色，不自动替换 serial |

完整 Git status、进程 argv/cwd、已安装包与 serial 在 `evidence/host_audit.json`。最终同PID复核与源码比较在 `evidence/final_readonly_verification.json`。当前没有观察到 ASPIRE/SAM3/cuRobo 服务或双臂任务 worker；这不是对其它用户/容器/未来进程的全机保证。

## 组件复用表

| 现场/上游组件 | 已核对的实现/资产 | 复用方式与边界 |
|---|---|---|
| RealMan API2 | `/home/tongji/aloha/RealMan_Control/Robotic_Arm/rm_robot_interface.py`；对应 `libs/linux_x86/libapi_c.so`，库1765544B | 保留已验证路径与版本锁；源码SHA `dac840a7…`，库SHA `53106459…`。未装/换SDK；未验证本轮控制器连接 |
| `SDKReadOnly` | H/`realman_api2_readonly.py`，allowlist为生命周期＋当前state/work/tool | 可以做将来的只读worker。`with` 会 rm_init/create，不能因为名叫只读就随意与已有句柄混用；本轮未构造。原 canonical 的UNKNOWN保留 |
| `arm_stack` | H/`arm_stack.py`，两端点 `.19`左、`.18`右，8080 | 复用读状态/帧指纹/回执格式；RM-plus读取是额外gripper只读调用，不在SDKReadOnly自己的三项READS里。不要把工厂/构造器直接当安全适配器 |
| `RealArmExecutor` | H/`left_executor.py`，single-use、独占claim、先检查再一次下发 | 可复用命令审计与after反馈思想。动作是 `rm_movej_p(pose,1,0,0,1)` 阻塞终点命令；不等于固定周期轨迹或已验证路径，不直接承担ASPIRE同步轨迹合同 |
| 精确IK检查 | H/`exact_target_feasibility.py` | 明确 `ENDPOINT_IK_ONLY` / `NOT_CHECKED_NO_INDEPENDENT_PLANNER`。只证明终点IK，不作为整路径、互臂碰撞证据 |
| 夹爪 | `LabGripperAdapter`、RM-plus原始pos/speed/current/state；0..1→0..1000 | 编码、反馈、失败语义可复用。非力标定、非毫米开度、非双侧接触/持物真值；独立 `set_gripper`，不能运动时无意重发release |
| 共享RGB | H/`astra_gui.py:CameraHub` → `camera_session.py`；`shared_cameras.py`客户端 | 单一producer与帧身份/时戳设计可复用；现producer只启用color。现有snapshot写H/logs，本轮未调用；不能称已接上跨进程只读RGB-D总线 |
| 真实RGB-D | H/`onsite_sequence.py:OnsiteStreams` 与 `scripts/capture_onsite_rgbd.py`，底层 `/home/tongji/aloha/RealMan_Control/realsense.py` | 复用对齐depth、Z16、mask、factory K、scale、depth→color、设备/host时间格式。现采集器会打开pipeline并写旧logs，不能与GUI并行直接启动；后续由既有owner输出或另获安排 |
| 左腕+桌面+上方 | O三相机包，SHA `820ea57e…` | 历史外参/内参及验证误差复用；桌面深度质量失败必须传播，不把三路全标“验收通过” |
| 右腕 | H/`config/engineering/right_wrist_calibration_20261017.json` | 复用16姿态(11训/5留出)估计和485帧原始路径；不改写三相机包，不作为实体TCP |
| V17/V19日志 | H/logs下三个原始run，见下表 | 复用观测/提案/执行/after证据与Replay；不把成功轨迹变成Agent专家控制器，不重放命令 |
| ASPIRE Agent/Prompt/Skills | 固定提交的AGENTS、`.agents/skills`、`docs/system2-agent-guide.md` | 原生操作模式保留；仅新增通用RealMan能力文档，不能沿用YAM特定几何或默认mink模型。Phase0未启动Agent |
| CAP / Embedded / MCP | `CapApi`、`EmbeddedAgentRuntime`、`server.create_app`、`CapMcpBridge` | 保留原生程序执行、job/steer/terminal反馈、MCP transport。需新的runtime工厂和少量类型/模型注册扩展，详见接口文档 |
| SAM3 | 原生`Sam3Provider`，HTTP分割服务 | 将来对同一帧RGB做mask，再由原生RGB-D几何定位；不另建任务识别专家控制器。本轮只用Mock mask |
| cuRobo | 原生client/规划合同/服务隔离方式 | 需真实RM65双臂模型、关节名/限位/碰撞体/真实基座/TCP和model注册；不能发送YAM/dual-Panda模型来“凑六轴” |

源码和配置精确 SHA、不存在的历史猜测路径也保存在 `deployed_file_manifest.json` / `extra_file_manifest.json`；未把找不到 `lab_cameras.py`/`camera_hub.py` 误写成现场缺少相机模块，真正类在上述文件。

## 原始日志核对

| run（全部位于 H/logs） | 原始summary | 本轮实际读取范围 |
|---|---|---|
| `parallel-arms-20261018T142729-853ffbe2` | 33 calls/steps，`MODEL_DONE`；历史V17成功轮 | 原始summary/config/launch_manifest/gui_launch/prompt_documents/auto_archive＋step-001 after observation及model_input |
| `parallel-arms-20261018T145818-fd3d3371` | 26 calls/steps，`STOPPED`；V17失败轮 | 同上 |
| `parallel-arms-20261018T153025-8a4d5e3b` | 43 calls/steps，`STOPPED`；V19不完整轮 | 同上 |

三个原始manifest记录Git `0ec04726…`，371项实现hash map完全相同；最终对当前现场源码逐项复核也为371/371一致，不能用Git分支名区分成功/失败。GitHub归档是后续 `3d765ab9…`，不冒充现场HEAD。原始summary的MODEL_DONE不独立证明物理成功；物理成败沿用10月18日人工/图像审查结论，本轮没有重新读全部图像或连续路径。

V17/V19抽查观测是**四路RGB**，有factory内参、各帧时戳、原图路径/SHA，但`extrinsics=null`，没有depth文件。这些日志不能直接作为`localize_object`的RGB-D输入。本轮另外读取O历史 `onsite-sequence-20261011T091810Z-b9a1cecf/observations/000003/observation.json`，确认三路aligned depth/Z16/mask的元数据、路径与SHA存在；没有复制数组，也没有运行SAM3。

10月18日审查指出V17初态不完全复位、V19接取遮挡/判断不收敛及GUI末尾416字符截断等；作为历史风险保留，不能据此替ASPIRE编写专用交接控制器或宣称唯一根因。本轮没有消耗新增模型预算。

## 两条迁移路线对比

| 维度 | 独立RealMan Adapter（推荐） | 修改YAM驱动 |
|---|---|---|
| 接口边界 | 正确实现EnvironmentAdapter，并向CAP注入真实planning context | 让RM SDK模拟YAM station/Portal/CAN plant语义 |
| 可保留部分 | Agent、Prompt、Skills框架、CAP、session/MCP、SAM3/cuRobo client | 表面保留build_yam_runtime，但需改codec/control/env/transport/server/model |
| 控制差异 | 显式承认阻塞终点命令与固定周期轨迹之间的差距 | 易把两次阻塞RPC误报成YAM共享tick/synchronized batch |
| 几何/模型风险 | 新realman embodiment/model有独立审查边界 | YAM的0.62m双臂模型、home、gripper和CAN假设容易泄漏 |
| 维护 | 小的通用注册扩展＋外置adapter/plugin，现场SDK底座保持 | 深度fork YAM实现，升级/故障归因更困难 |
| 结论 | 少量核心扩展不可避免，仍是最小正确改动 | 不作为首选，不仅仅“换底层函数” |

## 风险、阻塞与预计顺序

1. **Phase0离线准备（本轮完成）**：现场证据和固定源码；draft replay拒绝所有运动；原生核心Mock测试。没有真实模型、MCP HTTP或provider运行，也没有可执行硬件基线。
2. **后续软件隔离实现，预计1–2工作日**：在新目录建立Python3.10–3.12独立环境并固定依赖；注册realman=6及新的runtime工厂；完成原生typed adapter、只读cache、log bridge和MCP离线wire测试。此为估时，不是环境修改授权；缺包/网络/许可先解决，保留现有dp/GUI环境。
3. **现场只读身份/几何复核，通常半天到1天＋现场可用时间**：先解释当前相机serial差异，确认安装/USB和共享owner；按新授权取得真实两臂state/work/tool/DH/版本，核对各坐标有效期，不因本轮历史校准存在就放行。不得自动停止相机owner。
4. **独立计量与规划模型，约1–3工作日且取决于测量条件**：双基座→共同Work、左右实体TCP(含开度相关项)、当前相机安装/深度异常、时间同步边界；RM65 URDF/SRDF/碰撞球与控制器FK对照。未知项不填单位阵或仿真间距。只做离线规划回放，不执行。
5. **明确另获授权的Phase1硬件验收，时间取决于现场结果**：在途停止、限位/跟踪/速度/互臂全路径、夹爪标定与独立回读；先有界单臂，再同步执行语义，不把parallel启动当同步。全部仍通过同一通用接口。
6. **独立Agent真实双臂基线**：模型服务实测显存/延迟/超时，启动状态明确observation-only；有新的模型与硬件任务范围后再运行原生Agent。不导入任务专家轨迹；记录grounding、计划、派发、回读、独立任务结果。不会由本报告自动执行。

当前阻塞真实双臂基线的首要项为相机身份/在线性、共同坐标/TCP、真实碰撞模型和执行/停止合同；环境依赖与GPU兼容/资源也是未验收项。优先完成可独立推进的软件工作，不以安装依赖代替几何与执行验收。
