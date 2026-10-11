# 实验室 Codex 交接：Persistent World + Astra 真机测试

日期：2026-10-11。请先阅读本文件，再检查实验室实际源码和设备；不要仅凭 README、历史 PASS 或本交接直接执行运动。

## 1. 本次任务与授权边界

用户已到实验室，准备开始真机测试。当前交接任务是梳理现状、核验现场连接并推进最小必要真机接入；本文件本身不是某个动作、夹爪闭合或完整自主 PnP 的授权。

先核对现场实际机器人、相机、驱动、坐标与急停。只读核验、模型请求、机械臂运动及夹爪操作的授权范围应分清；开始真实设备操作前，与现场用户一次性确认本次具体范围和预算，不逐阶段反复申请已授权事项。不沿用历史仿真授权或已消费 claim。

研究主线固定：Semantic + Geometry-First Persistent World Head + Action Chunk + World Update + Adaptive Replanning。不要重建平台、换 World Head、训练网络、优化缓存、扩大 Schema 框架或再次研究仿真夹爪穿透。先让现场可用的最小闭环成立。

## 2. 代码与交接基准

- 仓库：`https://github.com/chao142857/astra-realman.git`
- 分支：`1011`
- 运行源码基准：`48f0eccba892b6acbdee54a938a9f61af10f50d7`
- 本文是后续文档增量；以 `git log` 确认文档提交与上述源码基准的关系。
- 开发端 worktree：`/home/alex/astra-realman_ws/astra-realman-1011`
- harness：仓库内 `astra_realman_harness/`

实验室路径不一定相同。先执行以下无设备操作的检查：

```bash
pwd
git rev-parse --show-toplevel
git status --short
git branch --show-current
git log -3 --oneline
git remote -v
```

有本地修改时保留，不 reset/clean/stash/覆盖。若现场未取得 `1011`，在确认目录和修改状态后 fetch，并用新 worktree 读取；不要覆盖实验室原驱动。不要把 `/home/alex/...` 或旧 `/home/tongji/...` 硬改成当前目录后直接执行。

## 3. 已完成什么，尚未证明什么

已积累真实 Astra 请求与 SAPIEN 闭环：公开 RGB-D 建图、Semantic 绑定、当前观测复核、Action Chunk、接触后局部重新关联、持物/释放边界、运输放置及独立评分。模型动作与宿主可信来源绑定分离。普通 Update 不调用 Astra；祖先证明缓存保留当前证据完整校验和完整递归审计路径。

最新缓存批次交接时的冻结结果：

| 回合 | 原结论 | 策略 K | 墙钟 |
|---|---|---:|---:|
| 普通 FULL_SYSTEM | FAIL_STOP / PNP_FINE_CONTRACT | 9 | 284.786 s |
| 普通 VANILLA_ASTRA | PASS / MODEL_FINISHED | 11 | 276.283 s |
| 遮挡 FULL_SYSTEM | FAIL_STOP / INFER_FAILED_NO_RETRY | 7 | 225.363 s |
| 遮挡 VANILLA_ASTRA | 交接时尚未运行；不得填入结果 | — | — |

这些是仿真单次结果，不证明真机执行、统计优势或跨布局泛化。A 的本地动作合同拒绝、服务失败与真实碰撞/控制失败分别记录。此前成功仿真记录继续保留，但不能据此宣布当前真机链已验收。

原档案在开发端：`/home/alex/astra-realman_ws/ab-cached-scenes-20261011`。Git 中没有原视频、RGB-D、点云、provider 凭据与全部封存输入。实验室缺失资料时明确记录，不补造 hash、raw、评分或当前状态。

## 4. 最重要的源码边界

| 文件/模块（相对 harness） | 实际用途与注意点 |
|---|---|
| `platform_v1/owner.py` | 默认 `sim_skills.full_pnp.backend.FullTaskBackend`；当前最新 Owner 是仿真链，不能当作真机 Owner 已完成 |
| `scripts/run_persistent_chunk_pair_episode.py` | 普通仿真 A/B 入口；不是硬件启动命令 |
| `scripts/run_occluded_chunk_pair_episode.py` | 遮挡仿真入口；不在实验室直接生成遮挡板或重跑物理实验 |
| `platform_v1/research/world_head.py`, `rgbd_world.py` | 复用现有 Build/Update、几何实例和目标局部关联；不创建第二套估计器 |
| `public_store.py`, `semantic_binding.py`, `verification_cache.py` | 来源/版本/真实 MODEL_RAW 校验，祖先缓存与全量审计；不能凭 world_id 跳过可变内容检查 |
| `broker.py`, `pnp_proposal.py`, `action_proposal.py` | 研究请求、最小动作提案、可信宿主绑定；不要让模型回显/覆盖宿主版本与真实 origin |
| `scripts/structured_outputs.py`, `scripts/codex_astra_mac_bridge.py` | Provider Schema 与本地权威合同、图片附件发送前检查 |
| `realman_api2_readonly.py` | 既有 API2 只读适配，白名单为生命周期及状态/work/tool 查询；不是运动执行器 |
| `scripts/prepare_realman_readonly.py` | 默认静态检查；只有 `--connect-readonly` 才连接设备；模板未知值会拒绝 |
| `scripts/audit_realman_foundation.py` | 无设备连接的基础边界审计，可先运行 |
| `camera_session.py` | 当前仅 `rs.stream.color`，返回 RGB 和彩色内参；`extrinsics=None`、base transform 未确认，不能冒称已有真机 RGB-D |
| `config/lab.json` | 历史实验室配置，设备角色、坐标/TCP等多数未确认；IP和序列号不是现场认证 |
| `supervised_live.py`, `scripts/run_supervised_step.py` | 历史固定左臂 +World Z 10mm 一次性路径；有旧证据/固定 claim，且默认 preflight 也连接双臂；不要作为“无设备操作检查”启动 |
| `lab_gripper_adapter.py`, `scripts/smoke_lab_gripper_once.py` | 包装实验室旧夹爪驱动/历史一次性开夹；会操作设备，不要自动运行 |
| `scripts/run_auto_pick.py` | 旧实验室自主执行路径，不能因文件存在就认为已接入最新 Persistent WH 或符合本次授权 |

旧 README 开头“无物理 executor”的概括不足以描述所有后续脚本。以实际入口导入、dispatch 和设备调用为准。

## 5. 现场必须核实的少量关键事实

### 机器人与控制边界

历史 SDK 固定在 `/home/tongji/aloha/RealMan_Control/Robotic_Arm`，库为 `libs/linux_x86/libapi_c.so`；旧夹爪驱动为 `/home/tongji/aloha/RealMan_Control/realman_arm.py`。现场核验实际加载文件和 SHA256，不因加载失败切换 SDK/账号/服务。

历史候选地址是左臂 `192.168.1.19:8080`、右臂 `192.168.1.18:8080`。必须由现场确认物理臂身份与端点；本次若只测单臂，不为方便顺带连接/控制另一臂。

确认：控制器/固件、当前 joint/FK、work/tool frame、基座到世界变换、法兰到实际抓取 TCP、夹爪反馈与安装几何。SDK 末端 pose 在既有转换中为 m/rad，joint 为 deg；不要二次缩放。仿真 quaternion 顺序、现场 SDK RPY 约定分别核对。

独立急停、在途停止 API/ACK、SDK 阻塞/超时/断连后的状态与部分执行政策必须现场确认。软件 STOP 标志不等于已验证硬件急停；不要关闭故障或自动清错、回零、重发不明结果。

### 相机和当前 World

历史相机配置包含四个序列号：`344422071480`、`254522073676`、`346222072496`、`348522072063`，角色均不能视为已确认。三路仿真 Fixed/Assembly/Wrist 不直接等于实验室物理安装。

核验实际可用相机、安装角色、RGB/Depth 对齐、深度 scale、有效深度、K/畸变、相机到世界 T。腕相机 T 必须由实测 FK 与手眼标定得到；桌面平面来自合法测量。同步记录 device/host 时间与各视图偏差，不把非原子读数当成同时采集。

先检查实验室既有 ROS/RealSense/相机采集能力并复用。当前 `camera_session.py` 只有 RGB；如果没有可靠深度或外参，标记相应空间能力 UNKNOWN，不能用仿真 K/T、旧 S1 坐标或人工 task_usable=pass 填洞。

## 6. 建议实验室 Codex 的直接工作顺序

1. **先核验，不运动。** 读本交接与实际设备入口、当前配置和运行进程，报告“已确认/未知”及第一个真实阻断。确认不存在占用同一臂/相机的旧控制进程；不要擅自 kill。
2. **只读快照与采集。** 经现场授权，取当前机械臂/夹爪状态、合法 RGB-D 与标定；使用新 episode/观测 ID、时间戳和 hash。不跑新仿真，不调用历史初始化脚本。
3. **复用研究链做当前世界与模型 shadow。** 先验证目标/目的地支持、版本绑定、模型输入大小和附件，必要时一次真正 Semantic。保持 `gpt-6-astra`、`medium` 和原已验证 provider/认证；现场若缺配置，先只读核对，不猜新路由。模型输出不可执行时保持明确标记，不改 Shadow 的 grants_execution。
4. **最小真机执行。** 确认运动链实际保留 Owner、IK、关节/工作空间限制、碰撞/接触与 STOP 后，按现场用户明确授权的低速有界动作开始。只补阻断当次试验的最小连接；没有足够安全/标定证据时指出具体缺口，不绕过检查。仿真 2mm 接触保护不能被当成真机已认证阈值。
5. **闭环继续。** 首步在模型返回后重新观察；每个单动作后：观测→现有 WH Update→一致性检查。剩余 Chunk 失效即终止后缀，按需要重规划。不每 Chunk 固定调用 Semantic；身份冲突/新语义需求才触发。

可先做的无设备操作审计（在 harness 内，使用现场选定 Python）：

```bash
mkdir -p logs
python -B scripts/audit_realman_foundation.py \
  --output logs/hardware_foundation_1011.json
```

输出采用独占创建；存在时换新唯一文件名，不覆盖。`config/engineering/realman_readonly_template.json` 是填写现场真实值的模板，不是可直接运行的已验收配置。不要在没确认路径/IP/授权前追加 `--connect-readonly`。

这不是要求重做一套验收平台；目的是避免把当前仿真 Owner、RGB-only 相机或历史固定真机动作误当成已就绪的最新真机闭环。

## 7. 不变的策略与来源约束

- Astra 决定未来 waypoint、阶段、运输/放置/释放/退出；宿主不得裁剪、插值、替换或预填正确轨迹。
- 宿主绑定实测 origin、任务、target、world/revision/epoch/read_versions 与已验证 Semantic 来源；模型新增 evidence claims 仍须严格检查，不能补写原 raw 的引用。
- H 上限沿用4，m=1；实际 K 由 Runtime/Owner 决定。真机动作数、速度、范围、模型次数和墙钟需现场明确，不能直接继承仿真80动作/1800秒预算。
- HTTP/SSE/application/unbounded retry 与 fallback 保持关闭；运动结果不明时禁止盲重发。
- close 成功不等于 held；持物需当前视觉、FK/反馈支持。携带预测标注来源，遮挡时区分部分支持、历史与 unknown。
- 工程建立持物状态与 Astra 策略分别计账。不要默认在真机执行仿真私有初始化；若现场采用人工/工程持物，明确记录且不算策略抓取成功。
- 目的地必须有当前合法图像/平面或 RGB-D 支持；不能只修红块身份而忽略目的地。
- 不提供 GT、私有布局、旧评分或 A 组答案作为在线定位；旧 S1/W2不是现场当前世界。
- 所有旧失败/raw/评分不改，来源类型真实/模拟/FAKE/历史分别标记。

## 8. 当次试验最小交付

原始视频、带请求 raw 的动作逐步表、目标/目的地当前证据、实际机器人到达状态、K、停止原因。工程动作与策略动作分别计数。

记录 E/A 请求数、tokens/usage（缺失为 unknown）、模型等待、WH估计/当前校验/历史校验/冷证明成本、Owner耗时与总墙钟；顶层互不重复相加。

`physical_success` 与 `model_finished` 分开：释放后物体稳定留在指定区域、夹爪打开且退出才构成完整物理完成；模型说 finished 不能覆盖失败，物理成功也不能伪造模型 finished。

真机没有仿真 GT：使用事先固定的现场独立测量/录像判据，不能拿在线 WH 自评当独立物理评分。首个真实安全/控制问题停止，保存当前图像和原错误；本地可修复软件问题做最小修复，不改已执行轨迹，不补跑伪造结果。

## 9. 可直接发给实验室 Codex 的首条指令

> 请读取 LAB_CODEX_HANDOFF_1011.md，核对1011实际源码、现场机器人/相机/SDK与当前进程。现在先不运动、不操作夹爪、不调用模型。确认现有真机执行与RGB-D/标定入口，指出从当前仿真链迁移到现场的第一个具体阻断；优先复用实验室已有稳定控制与采集。不要扩建平台、不运行历史一次性动作脚本、不放宽安全门。完成只读核对后，给我一份短的现场状态与一次有界真机测试范围/预算，由我确认后在该授权内连续推进，不逐阶段重复申请。
