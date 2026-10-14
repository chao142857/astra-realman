# RM65 双臂物理仿真：yanglab 离线接入（未通过完整交接）

**当前状态：执行层阻塞；真实 Astra 生成 0 次，真实硬件连接 0 次。**
单臂抓放、双臂共享场景、左臂持物初始化、数值动作接口、本地假 Bridge 闭环已实际运行。
尚未获得完整双臂交接并放置成功的视频。不得将本目录的 PASS（初始化/接口）解释为交接成功或 Astra 能力证据。

## 已验证的结果

|证据目录（均在 evidence/）|实际结果|
|---|---|
|single_arm_smoke_02|原 RM65 单臂 PhysX 抓取、抬起、放置及原终态评分 PASS；有视频|
|dual_shared_smoke_01|一个 SAPIEN Scene 内两台 articulation，三路 RGB，PASS|
|handoff_initial_repeat_01|reset 后重新物理抓取并抬起；3331 步、13.324 秒仿真时间，PASS；到此专家停止|
|numeric_interface_final|双夹爪同组并行、左臂数值 TCP 移动、非法整组零执行拒绝，PASS|
|offline_tests_final2.log|7 项 unittest PASS，包含多个协议负例；本地假 HTTP 服务，零生成|
|offline_episode_final|假 Bridge 两次独立返回→右夹爪动作→再观测→停止，真实物理执行，PASS；无交接成功声明|
|final_baseline_01|完整脚本 FAIL：第 5685 步、22.740 秒，右夹爪 PAD_PENETRATION；有完整失败视频、源码快照和原始轨迹|

最终基线私有过程分析：左臂最长连续持物 9.776 秒；右臂无左臂/桌面接触、双侧夹爪接触且低速的最长连续段 **0.740 秒**（左夹爪实测开度 >70 mm）。
之后右侧 Support_Link 对方块的接触穿透达 **2.3076 mm**，超过沿用的 2 mm 保护阈值，停止在放置前。
第一版分析仅排除了左臂接触力，曾报告 1.124 秒；没有要求左夹爪已经打开，不能等同于释放后的持物。第一版结果保留，主描述采用补齐实际释放条件的 v2（0.740 秒）。
无记录到互臂物理接触。短暂独立持物不能抵消随后发生的物理保护失败。
`process_evaluation_v2.json` 的过程判据与原单臂终态评分分开保存；完整任务未通过。

## 代码和物理资产

基于 `6484545`，独立 worktree `/home/tongji/alex/rm65-dual-handoff-20261014`，分支 `codex/rm65-dual-handoff-yanglab-20261014`。
不使用 ubuntu-robot 或 RoboTwin，不修改旧 worktree、生产 Bridge、SDK、IK 源文件或旧结果。
复用 `astra_realman_harness/sim_skills/rm65.py`、`scripts/prepare_rm65_sim.py` 和 yanglab 历史 `rm65_scene.py`。
历史资产来源：`/home/tongji/alex/ASTRA_LAB_2026-10-02/01_CODE/astra_controller`。
资产存在，原始归档 URDF 含旧 `/home/alex/astra/vendor` 路径；仅在独立复制资产内修正路径并重算 manifest。

`rm65_assets_frozen.tar.gz` 保存实际使用的 56 文件资产集；`environment_lock.json` 保存 manifest、包版本和轮子 SHA。
资产仍是 RM65 + CTAG2F90-D **历史临时装配模型**，相机安装位与夹爪参数不是实验室硬件标定。本实验不能声称验证真机精度。
归档中的 `run_expert.py` 仅提供原场景依赖的 `write_json`；其 RoboTwin runner 没有实例化或运行。

已有 Python 3.10 venv：`/home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python`。
复用 numpy 1.26.4 / SAPIEN 3.0.0b1；缺失 mplib 0.2.1 等依赖安装到独立
`/home/tongji/alex/rm65-handoff-runtime-20261014/deps`，没有升级原环境。
`requirements-isolated.txt` 记录新增运行依赖；toppra 0.6.3 使用本机编译轮子，具体 SHA 见 lock。

最终物理参数仍为原 dt=0.004 s、重力 −9.81、摩擦 0.5、5 cm / 0.01 kg 动态方块及原 URDF 惯性。
两台基座位姿：左 `[0,0,0.03; 1,0,0,0]`，右 `[0.75,-0.30,0.03; 0,0,0,1]`（世界米、wxyz）。
早期右基座 y=0 的诊断独立保留；偏置布局用于获得公共接近空间，未依据模型结果选择。
最终目标区域为中心 `[0.60,0.16]`、边长 0.14 m 的蓝色标记。
原 table 共用，目标方块始终是自由动态刚体。没有物体绑定、weld 或运行中写物体位姿。

## 模型与控制器分别负责什么

- 模型：交接地点、数值 TCP 位姿、左右臂次序/并行关系、夹爪指令、是否调整或停止。
- 控制器：最近 IK 解、固定三次关节插值、逐模拟步 FCL 配置碰撞预检、实际物理接触与限位保护、原有限力矩夹爪闭合。
- 专家初始化：允许读取物体 GT，只完成左臂抓取和抬起。此后公开 history 为空，不包含专家动作。
- **专家参考使用原 mplib/OMPL 自动运动规划；模型动作执行器不使用 OMPL，只插值和拒绝。二者不等价。** 不能将专家绕障能力归为 Astra，也尚未证明模型接口能完成完整交接。
- 夹爪沿用原接触停闭/有限弹簧预载：双侧接触两步后施加 0.005 rad 预载、0.1 Nm 上限。它不是物体附着约束，但属于执行器的接触反馈辅助，明确计入控制器责任。
- FCL 预检可访问仿真碰撞几何，只用于拒绝，不反馈正确目标或自动改写提案。持物形状没有被当作刚性附着体自动规划；实际物体碰撞仍监测，预检不提供连续空间安全证明。

动作 schema：一次每臂最多一个 `tcp` 或 `gripper`，省略的臂保持。
`tcp` 是当前实际两内侧 pad 面中心的均值；姿态是世界系 **Link6** 的 wxyz，不是自行猜测的工具四元数。
夹爪输入为 0..1 命令比例；实测开度单独用 `actual_pad_gap_m` 表示。
并行模式在同一个 `scene.step()` 推进两臂驱动，不使用两个独立仿真或假并发。
相机身份为 table/left_wrist/right_wrist，保存各自内参、外参与 RGB SHA。
公共输入只有这些图像/标定、两臂实际状态、固定任务/坐标约定、最近两组原始模型动作与执行回执。
不包含物体 GT、接触真值、专家轨迹、正确交接点或 witness。

## yanglab 可复现命令

输出目录必须新建；禁止覆盖已有证据。

```bash
ssh yanglab
cd /home/tongji/alex/rm65-dual-handoff-20261014/experiments/rm65_handoff_v0
source runtime.sh

# 已实际运行成功的原单臂 smoke（具体参数见 --help）
"$RM65_PYTHON" single_smoke.py --output evidence/my_single_smoke

# 共享场景与可复现 handoff_only 初态
"$RM65_PYTHON" dual_script.py --smoke-only --output evidence/my_dual_smoke
"$RM65_PYTHON" dual_script.py --handoff-only --output evidence/my_left_held

# 完整脚本：当前预期复现 PAD_PENETRATION，不应标记成功
"$RM65_PYTHON" dual_script.py --output evidence/my_full_baseline
"$RM65_PYTHON" evaluate_process.py evidence/my_full_baseline

# 真实 PhysX 数值动作接口、零生成 HTTP 协议与闭环
"$RM65_PYTHON" interface_smoke.py --output evidence/my_numeric_interface
"$RM65_PYTHON" offline_tests.py
"$RM65_PYTHON" offline_episode_test.py --output evidence/my_fake_episode
```

`run_episode.py --real --output ...` **会在连接/创建场景前拒绝**。
没有真实模型可运行许可或就绪声明；真实入口被硬性封闭。
日后完整脚本与模型执行层验收通过后，建议单局 handoff_only 最多 16 次独立 Astra 决策，仿真控制步数另计。
仍需本任务的新明确授权和 Mac 登录/专用 Bridge/隧道/认证、190 s 服务端/180 s 客户端生产预检。
本轮没有联系生产 Bridge、没有创建授权 ledger，也不继承静态评测授权。

## 阻塞与诊断边界

侧向接近 IK 失败已分离为关节可达/互臂夹爪支撑结构碰撞问题；当前从前方接近可执行。
右臂接取后仍有接触数值/控制稳定性问题，根因尚未证明，不能归因于 Astra。
归档包括原参数、额外闭合、较高 solver iterations、1 ms 积分诊断。
后两项没有改善且破坏左臂抓取，已恢复原参数；没有放宽 2 mm 阈值、修改质量/摩擦或隐藏失败。
另有首次单侧接触即限力的控制诊断：两臂同时使用会失去左臂持物；仅右臂使用、含延长至 4.6 秒闭合的版本仍未建立稳定双侧接触。这些候选仅保留在各诊断运行的源码快照，不进入默认控制器。
下一项必要工作是隔离右夹爪垂直夹持时的驱动/接触稳定性，先获得完整脚本物理成功；不应先运行 Astra。

## 原始证据与复核

每个模拟步保存实际关节、TCP、实测开度、物体真值、速度、接触位置/冲量/穿透、阶段和仿真/墙钟时间。
GT 文件只用于私有评估。实际轨迹与提案/回执分别保存；最后 `final_baseline_01/source_snapshot` 封存复现源码。
视频以 10 fps 按仿真时间编码；推理期间无物理步进，不能声称实时动态反应。

yanglab 原始 `.jsonl` 全部保留。Git 保存逐文件 `.jsonl.gz` 无损副本和 `raw_archive_manifest.json` 的原始/压缩 SHA256。
在新 checkout 分析日志前，可解压副本（不要覆盖已有原始文件）：

```bash
"$RM65_PYTHON" - <<'PY'
import gzip,pathlib
for p in pathlib.Path('evidence').rglob('*.jsonl.gz'):
    raw=p.with_suffix('')
    if not raw.exists(): raw.write_bytes(gzip.decompress(p.read_bytes()))
PY
```

保存的假 token 仅是本地测试字符串，不是生产认证。本目录没有生产认证文件。
