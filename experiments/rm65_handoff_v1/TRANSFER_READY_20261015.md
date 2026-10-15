# 1.1 m Ready Pose 与 handoff_transfer_only

执行主机：yanglab / `tongji-Precision-3680`。
本轮真实 Astra 客户端派发 **0**，没有借用旧实验授权。

## 当前交付

- 最终布局为 `scene_v4_ready_transfer_1100.json`：基座中心距 **1.100 m**，
  世界坐标 X 为左 **-0.190 m**、右 **0.910 m**，中心仍为 0.360 m。
  1.296 m 的 v2/v3 配置、图像、失败和测试记录均保留。
- overhead、tabletop_front、两腕部相机的配置与上一版逐项一致。
  上方视轴相对水平面实测 **74.999998°**；腕部相机仍随各自腕部运动。
  桌面尺寸、控制器、PhysX 参数和 **2 mm** 接触保护未变。
- 左右 Ready 分别配置，单位 rad：
  - 左 `[0.08, 0.10, -1.50, 0, -1.7415926536, 0.08]`
  - 右 `[-0.10, 0.05, -1.55, 0, -1.6415926536, -0.12]`
  这是依据 URDF/FK、关节限位与物理检查选定的工程姿态，不是照片测量值。
- `transfer_ready_1100_acceptance_01` 的两个实际 reset 完全复现初态；
  drive target 与配置一致，末端朝下，无自碰撞、互臂或桌面碰撞。
  开口夹爪在精确零限位处有最大约 **7.8e-9 rad** 的引擎数值越界，
  如实保留 exact-limit=false；原有 **0.002 rad** 容差检查通过，未改保护。
- 两次左臂物理拾取均通过，右臂实测保持 Ready，最大关节误差约
  **1.15e-6 rad**。独立左持物观察 **3 s**：相对平移漂移
  **0.000260 mm**、相对转角 **0.0000732°**，最大夹垫穿透
  **0.1093 mm**，没有掉落或互臂接触。原判据的 left_hold 也通过。

抓取初始化用方块保存在左臂可达区域 `(0.05, 0, 0.026)` m；旧中央
方块和其 IK 失败记录不改。脚本只执行左臂拾取、抬起与持物，随后停止。
没有专家接取、交接或退出动作进入 Astra 回合。

图像、标定和视频：

- `evidence/transfer_ready_1100_render_01/observation/`：最终 Ready 四张原始 RGB、
  四视角拼图、独立场景预览及标定；实际基座距离 **1.099999964 m**。
- `evidence/transfer_ready_1100_acceptance_01/reset_0/handoff_initial/`：
  左臂持物的四视角与实测状态，即模型接管前初态。
- `.../reset_0/execution.mp4` 与 `.../reset_1/execution.mp4`：实际拾取与持物录像。
  它们不是 Astra 录像，也不是已完成双臂交接的录像。

## Astra / 控制器边界

任务仅为：左臂持物 → 模型决定接取与释放 → 右臂独立持物并退出。
不要求最终放置。原完整任务及失败结果保留，不作为这个子任务的启动门槛。

`run_episode.py --task handoff_transfer_only` 复用原四 RGB 输入、严格 JSON
解析、Mac Bridge HTTP/超时/取消/参数和事件验收、`execute_action()` 及
同一个数值执行器。没有复制 HTTP 客户端、修改原生产 Bridge 或 Code Mode。
模型自主给出世界 TCP `[x,y,z,w,x,y,z]`、夹爪开度和顺序/并行关系。
执行层只选择 IK、固定关节插值、碰撞/限位拒绝及接触驱动，不改目标。
左拾取初始化允许原 OMPL 专家；模型阶段没有 OMPL 自动绕障。

四 RGB、标定、实测机器人状态与最近两组原提案/回执进入输入。
物体 GT、接触真值、专家轨迹、私有候选和评测结果不进入模型输入。
推理期间物理时间暂停；动作阶段推进物理。done 后有固定 2 s 被动保持
观察，不执行专家动作，不声称实时异步协调。

`shadow` 只保存和验收原回答，绝不执行；`execute` 必须已有同批次有效
真实 shadow，重新 reset 后发起新决策，不把 shadow 回答塞入其上下文。
IK、碰撞和限位拒绝保存原提案及原回执，可继续下一次决策。
传输/协议异常、状态未知或物理保护停机则停止，不自动重试或修正。

## 实际验收与评估

- 原 7 项协议回归通过，新增 8 项权限/物理判据单元测试通过。
- 最终 `transfer_1100_offline_01`：模拟 HTTP shadow 1 次不执行；执行模式
  3 次模拟回答中，越界原目标原样被拒绝，随后合法右 TCP 上移 5 mm
  实际执行，再停止。推理时物理推进均为 0；两份原始日志独立重评分一致。
  这些是接口验收，不是 Astra 能力结果。
- `transfer_criteria_v1.json` 单独版本化：右臂双侧接触、无左/桌面支持，
  连续 2 s 持物，物体/右 TCP 相对漂移不超过 2 mm、5°；物体从接取位置
  位移至少 80 mm 且远离左 TCP 至少额外 40 mm，退出后继续持物 2 s。
  不使用唯一交接坐标或轨迹。原 2 mm 穿透保护不变。
  原速度/完整放置判据仍另存报告；旧失败评分没有被覆盖。
- 新评分来自私有物理记录，只在回合结束后计算，不给模型下一步建议。
  预算截断保留为截断；基础设施失败不记成空间能力零分。

## 生产准备与新授权

Mac 原 ChatGPT 登录、原 Bridge 单 worker、190 s 服务端已核对；
yanglab `127.0.0.1:18766` 反向隧道及认证通过。预检只使用原 handler
未知路径 `/rm65-transfer-auth-check`：正确认证 404，错误认证 403；
**没有使用 `/decide` 做健康检查**。本任务专用 Bridge 没有生成 job 目录。
真实 shadow 是否能成功仍须首次授权调用确认。

最终 1.1 m 的专用草稿：

- batch ID：`80b7eea8ee064f86b7f1628f9619c084`
- 绝对根：`/home/tongji/alex/rm65-transfer-ready-yanglab-20261015/experiments/rm65_handoff_v1/evidence/transfer_runs/first_transfer_1100_20261015`
- `ledger.json`：DRAFT、authorization=null、reserved_budget=0。
- `authorization_REQUEST_NOT_GRANTED.json`：generation_authorized=false、max_dispatches=0。
  它不是授权。早先 1.296 m 的准备草稿保持原样，不能用于本版派发。

申请一次新授权上限 **16 次客户端请求总计**：先 **1 次真实 shadow**，
然后最多 **15 次动作闭环决策**。gpt-6-astra / medium，客户端 180 s、
服务端 190 s、单 worker、独立 ephemeral 会话。所有请求派发前原子预留；
中断/未知不退款、不重置、不自动恢复。只计客户端派发预算，不能声称
客户端准确控制了上游生成次数。授权后仍须刷新不超过 15 分钟的生产预检。

## 已验证和未来命令

yanglab 上执行（每个输出目录必须全新）：

```bash
cd /home/tongji/alex/rm65-transfer-ready-yanglab-20261015/experiments/rm65_handoff_v1
source runtime.sh
"$RM65_PYTHON" ready_acceptance.py --output evidence/ready_REPRO_NEW
"$RM65_PYTHON" transfer_offline_test.py --output evidence/mock_REPRO_NEW
"$RM65_PYTHON" transfer_safety_tests.py
```

**以下真实命令尚未运行，必须先得到新授权、填好本批次 grant 并刷新预检。**
现有 Mac 服务启动参数是原 `codex_astra_mac_bridge.py --mode lab
--executable /opt/homebrew/bin/codex --port 18767 --timeout-s 190`。
Mac 的 `mac_transfer_readiness.py` 可重新进行非生成检查；其 `--launcher`
为 `/private/tmp/rm65-transfer-mac-bridge-20261015/launcher.json`。
将新的 Mac proof 传至 yanglab，用 `transfer_preflight.py` 绑定本批次，
输出新文件，不覆盖旧预检。服务若退出，须恢复并重新检查。

```bash
B=evidence/transfer_runs/first_transfer_1100_20261015
# NEW_AUTHORIZED_GRANT.json 必须来自本任务的新明确授权，不能使用 REQUEST。
"$RM65_PYTHON" run_episode.py --task handoff_transfer_only --real --mode shadow \
  --budget-root "$B" --output "$B/shadow_01" --max-decisions 1 \
  --authorization "$B/NEW_AUTHORIZED_GRANT.json" \
  --preflight "$B/NEW_PRODUCTION_PREFLIGHT.json" --bridge-config "$B/bridge_config.json"
# 有效 shadow 后，共享同一累计预算；不是另加 15/16 次预算。
"$RM65_PYTHON" run_episode.py --task handoff_transfer_only --real --mode execute \
  --budget-root "$B" --output "$B/execute_01" --max-decisions 15 \
  --authorization "$B/NEW_AUTHORIZED_GRANT.json" \
  --preflight "$B/NEW_PRODUCTION_PREFLIGHT.json" --bridge-config "$B/bridge_config.json"
```

全部旧资产、依赖、历史 ledger 和结果不变。新增原始物理流保留在 yanglab；
Git 保存可逆 gzip、源码快照、哈希、原图、视频和独立评估。
