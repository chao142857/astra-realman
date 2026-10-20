# Native Adapter、Codec、Runtime与MCP

## 实际完成的代码

| 组件 | 实现与状态 |
|---|---|
| 六轴类型注册 | 隔离ASPIRE `JOINT_DIMENSIONS['realman']=6`。真实RealMan数据不再标成yam_real，原生ArmCommand/RobotAction/Trajectory/RobotState均识别六轴 |
| `codec.py` | SDK joint deg→rad一次；xyz保持m；RPY rad→矩阵→WXYZ；严格核对arm/work/tool指纹、有限值、开度；显式转换图，无跨基座/世界/TCP默认值；腕相机按当前endpoint pose组合，并检查时间偏差 |
| `RealManAdapter` | 实现全部原生 `EnvironmentAdapter` 方法，`isinstance(...,EnvironmentAdapter)`通过；读接口返回真正的 `RobotState` / `Observation` / `TaskContext`，命令接口返回原生typed refusal |
| 原子观测源 | `MemorySource.read/publish` 在锁内交换整份已采集snapshot，序号必须增加；保持source kind和相机role/serial绑定；它从不主动采集。监控读取同一缓存，不新建相机/SDK |
| `ReplaySource` | 本地记录JSON；未显式指定assets_root时不打开原图路径；有root时限制路径、20MiB上限、检查原SHA后读取PNG/NPY（allow_pickle=false），从不执行proposal或自动前进 |
| `build_realman_runtime` | 使用原生 `CapApi`、`ToolRegistry`、`EmbeddedAgentRuntime`、`server.create_app`，保留 `/mcp/`、`/health`、`/steer`。没有使用build_yam_runtime、YAM station、Portal/CAN或既有GUI |
| MCP HTTP | 测试使用真正TCP loopback、uvicorn、MCP1.26 StreamableHTTP ClientSession；覆盖初始化/工具发现/observe图像/state/Mock localize/job/steer和动作拒绝 |
| Planning接口 | 显式阻断CapApi默认Panda/identity fallback；真实model/TCP未绑定时拒绝planning context。未实现可执行RM65/cuRobo规划器，不虚报可用 |

为测试原生动作工具schema，工厂在原生枚举名 `curobo` / `curobo-integrated` 下放置的是本地 `RefusingIK` / `RefusingPlanner`，没有HTTP/GPU后端；capability graph中的configured名称不代表真实cuRobo可用。定位测试同样显式使用MockSegmentation，没有SAM3模型请求。

上游补丁只有3个文件5行新增：contracts注册realman和通用RobotState.metadata；API在规划状态副本中保留metadata；session在状态回执中保留metadata。补丁见 `patches/0001-realman-contracts.patch`。没有改Agent任务决策、Prompt、Skills、MCP transport、原生高层规划算法或Home程序；没有香蕉交接专家代码。

## 坐标与数据质量

原生RobotState要求所有EEF共用一个base_frame。双臂合成测试使用明确标注SYNTHETIC的非重合base变换；**真实双臂Replay缺跨基座变换时立即拒绝**。可显式选择只读left scope，把base_frame设为该臂已有 `realman:left:work:World`；这是该帧对自身的数学关系，没有把未知双臂变换填单位阵。

真实历史endpoint使用封存零work/tool的条件性数值证据并匹配指纹，保留原 `frame_semantics_status=UNKNOWN`。EEF在这里是Arm_Tip控制器端点，不是已测实际抓取TCP；metadata明确 `actual_grasp_TCP=null`、`motion_permitted=false`。需要现场新鲜绑定才能用于当前只读观测。

SDK没有提供速度时，原生向量合同需要有限数组，因此放置**明确标注UNMEASURED_NUMERIC_PLACEHOLDER**的零向量，并通过新增通用metadata直接传到原生MCP状态回执；不把它解释为实测静止。源提供速度时才标SOURCE_REPORTED并deg/s→rad/s。metadata也保留source kind、端点含义、绑定证据和未知持物状态。

RGB-only或无合格外参的相机可以展示，但其usable depth全为0（原生合同的无效深度编码，不是制造正深度）；camera_pose只表达optical→自身，不伪造world pose。原深度记录不被改写。估计/未复核外参不获得VERIFIED资格；tabletop历史异常深度不能自动参与公制定位。腕相机动态pose还要有同时间robot state；检查时间差不等于证明曝光同步。

如果缓存中相机消失，metadata明确missing/stale；原生session可能保留最后一张用于显示，但标记为过期，不能当当前决策帧。Native get_observation只使用当前完整snapshot，不从旧帧拼装新观测。

## 运动拒绝边界

1. 无真实命令transport、SDK导入、相机pipeline构造或allow-motion选项。
2. raw `step`、`execute_trajectory`、`set_gripper`、`set_grippers`、`go_home`、`reset` 无条件拒绝。包括原生RealMan Trajectory/SynchronizedTrajectory输入，步骤与派发数为0。
3. 原生CAP `move_to_joints`、`move_to_pose`、`move_synchronized`、`set_gripper` 与Home程序通过真实MCP调用均失败；可能在模型/标定/规划边界先拒绝，或到adapter的safety_interlock拒绝。不会因拒绝原因不同而下发其它动作。
4. Home程序在Mock adapter的首个开爪请求处被拒绝，未到Home，更没有真实夹爪动作。这里是测试固定程序的拒绝机制，不是操作机械臂。
5. 已构造的原生CAP没有自动记下当前状态作为Home（明确传入空home map）。运行时只拥有自己线程/应用；关闭不停止既有服务或设备owner。

## 新克隆复现（仅新隔离目录）

优先复用已有固定源码缓存。没有缓存时才选择性获取CPU源码；不取模型、mesh、媒体或子模块：

```bash
mkdir -p .cache/ASPIRE
git -C .cache/ASPIRE init
git -C .cache/ASPIRE remote add origin https://github.com/NVlabs/ASPIRE.git
git -C .cache/ASPIRE fetch --depth=1 --filter=blob:none origin fa00f0ef2bc1d91d594b9aa502c22133c9f538f7
git -C .cache/ASPIRE sparse-checkout init --no-cone
git -C .cache/ASPIRE sparse-checkout set --no-cone '/src/cap_harness/**/*.py' '/src/cap_harness/*.py' '/README.md' '/LICENSE' '/NOTICE' '/pyproject.toml'
git -C .cache/ASPIRE checkout --detach FETCH_HEAD
python3.12 -m venv .venv
.venv/bin/python -m pip install -r aspire_realman_phase05/requirements.lock
.venv/bin/python -B aspire_realman_phase05/tools/prepare_upstream.py
.venv/bin/python -B aspire_realman_phase05/tools/run_validation.py
```

prepare_upstream只允许修改本隔离工作区里的源码，固定HEAD、补丁前后SHA及71份runtime源码SHA全部验证；不接受任意现场目录。依赖是MCP/HTTP/CPU最小集合，未安装完整YAM/CUDA/provider/model环境；通过PYTHONPATH加载固定CPU源码，不声称已经安装可运行所有ASPIRE后端的完整发行版。
