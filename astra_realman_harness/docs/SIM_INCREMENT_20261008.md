# 模拟与技能增量 1 · 2026-10-08

本次交付是物理后端、共享放置链及实验接口的工程增量。**不是一周计划全部完成，不是 Astra 实验结果或真机验收。**

## 版本与保留范围

- 原仓库 `/home/alex/astra-realman` HEAD = `ca65f2e00cfc246df54e174f12544901bea36c46`，与任务基线一致，最终 tracked/untracked Git 状态干净。
- 开发分支 `codex/sim-skills-20261008`；冻结 commit 见交付包 `MANIFEST.json` 和本分支 HEAD。没有 push、部署实验室或修改旧 Astra 代码。
- 旧 RM65 来源 `/home/alex/astra` HEAD = `82d6f16650485d7696a42600fed1c2d6a2451713`。56 个复用文件逐个记录源/副本 SHA256；原文件复核未变。
- 从本地已有远端分支恢复 E3 commit `3fd5c66493de77545a5c77091432e68a578027d5` 的代码、入口、测试与设计卡；原始导入 hash 在 `docs/e3/IMPORT_PROVENANCE.json`。只给 E3 CLI 增加本机 executable/run-root 参数，未改 T0–T3/H5D1 定义。旧冻结 batch 因代码 hash 变化必须由原始资料重建，不能绕过校验。
- 不更改 legacy、H/D、并行动作组 schema、GUI 或现场参数。最终任务仍为左拾取→双臂交接→右分类投放。

## 已实现

1. `scripts/prepare_rm65_sim.py` 冻结旧 SAPIEN 场景/资产；URDF 使用可搬迁相对路径，RT 改为 default raster。物理参数、驱动、规划器、碰撞与跟踪门槛保持原值。
2. `sim_skills/rm65.py` 是真实 PhysX 适配器，返回当前 RGB、本体状态、后端结果；未知原语拒绝。`bimanual_demo/runtime.py` 接受显式 arms/observer 注入，不再只能构造 mock；本次没有实现双臂物理适配器。
3. `bimanual_demo/primitives.py` 被原双臂 right_place 和模拟 M/S 共用：approach→release_pose→release→retract。相同目标、控制器、速度、检查与观察边界；M 每原语请求一次，S 技能入口请求一次。失败均停止、无自动释放/重试。当前决策空间是固定放置链 continue/stop，不能据此声称通用技能选择或完整 E1 性能验收。
4. 模拟目标单列 `config/sim_rm65_targets.json`，带 backend/frame/tool/revision/来源/范围。动态指垫中心位置与 Link6 wxyz 姿态有显式转换及测试，不直接互传 RealMan RPY 数组。转换函数尚未用于真实控制。
5. 本地 CLI 复用旧 bridge 的推理函数，支持路径、工作目录、端口/token 文件配置。lab 默认 SSH 入口保留；`--mode local` 不调用 yanglab。真实请求仅经显式 `--model local-cli --authorize-model --max-model-requests`；单 in-flight，medium、工具关闭、input_only PNG/白名单上下文、raw/parsed/schema/usage/延迟留档。read-only 本身不是文件读取隔离的证明，工具禁用、白名单导出和事件拒绝共同约束；实际 CLI/API 响应资格仍未验证。
6. `prepare_sim_request.py` 可导出当前图、resize、父图/派生图 hash、在线调度 phase 与选择成本；ROI 接口仅接受有在线来源的记录。history 复用原 E3 lossless codec，保留 round-trip/pointer/字节预算及回退。不把字节当 token，不把通用开发投影冒充原 E2 正式条件。
7. E3 原 32 请求入口已恢复；真实源 PNG/日志缺失，本次 7 个离线测试通过、1 个真实资料验收跳过。**没有准备出本机真实 32 请求批次，也没有调用模型。**
8. E4 `groups.py` 实现 1/2/2/2 串行编排、相同 common 输入、parent hash、KEEP/REVISE/NO_PROPOSAL、短 claims、原 inner parser；第二次失败不回退。28 stub 调用通过，仅协议 fixture，4 点来自同一个模拟来源回合，不是官方 G 数据集或 4 个独立物理样本。没有 E4 真模型入口或执行器接入。

## 物理结果与资源

主后端冻结为 SAPIEN `3.0.0b1` / mplib `0.2.1` / NumPy `1.26.4` / SciPy `1.10.1` / TOPPRA `0.6.3`，复用 `/home/alex/astra/.venv/bin/python`，未安装/升级依赖。RTX 5060 Laptop 8151 MiB，驱动 595.84。三路 assembly/fixed/wrist RGB 均 640×480；光栅截图已目视检查，视频有效性见交付 evidence。

- 首次 smoke 保留为 FAIL：从零关节伸直初态继续 +Z 10 mm，IK 拒绝。没有执行该位移，未删失败。
- 修正 smoke 使用旧服务通用准备位 `[.30,0,.15,0,1,0,0]`，PASS；暂停等待不推进，显式 tick 推进 5 步。
- 下表 10 回合均从新进程重建并物理抓取初始化；setup 不计作模型抓取。记录 seed，明确不是完整状态 snapshot restore。
- 每回合共 4925 步 × .004 s = 19.700 s 物理时间，其中放置段 2113 步 = 8.452 s；setup 5 次场景动作、放置 4 次。所有模型等待期 physics paused。
- GPU 每约 0.5 s 采样：模拟进程峰值 478 MiB，全卡峰值 1205 MiB（含桌面）；不是连续精确峰值。未启动训练或加载模型权重。
- 第一回合启用了 execution.mp4，其余未录视频，墙钟不能作为公平 M/S 时延实验。这里的 wall 包含创建场景/初始化/渲染/日志，模型耗时是 stub，不报告模型提速。

| 回合 | 独立评分 | stub 决策边界 | 放置原语 | XY 误差 mm | 整回合 wall s |
|---|---|---:|---:|---:|---:|
| seed-02-M | PASS | 4 | 4 | 0.6450 | 6.366 |
| seed-02-S | PASS | 1 | 4 | 0.6450 | 2.763 |
| seed-03-M | PASS | 4 | 4 | 0.5246 | 2.601 |
| seed-03-S | PASS | 1 | 4 | 0.5246 | 2.457 |
| seed-04-M | PASS | 4 | 4 | 0.4146 | 2.437 |
| seed-04-S | PASS | 1 | 4 | 0.4146 | 2.462 |
| seed-05-M | PASS | 4 | 4 | 0.3722 | 2.596 |
| seed-05-S | PASS | 1 | 4 | 0.3722 | 2.831 |
| seed-06-M | PASS | 4 | 4 | 0.3646 | 2.721 |
| seed-06-S | PASS | 1 | 4 | 0.3646 | 2.577 |

冻结前另有一对 M/S 回归 smoke，均 PASS，单列 `final-smoke-pair/`，不加进原 10 回合表。STOP 实物理场景资格检查 `stop-qualification/`：持物后停止，新的模型请求/原语/物理步均 0；其 placement 为预期 FAIL，只把停止协议标 PASS。

**特权信息账本**：ENGINEERING_ORACLE。初始化抓取使用物体几何；持物 gate 使用双侧物理接触与相对运动；FCL 使用场景碰撞几何和 payload 几何；继承有限 `.005 rad` preload / `.1 Nm` drive limit。这不是纯 RGB 全链路。物理立方体保持自由动态，无中途传送、焊接或贴合。独立 evaluator 读真值，只在终止后评分；truth、contact_latch、score、future 不进入模型白名单上下文。unknown 与观测可判定性尚未进行人工标签评估。

## 测试与已知缺口

- 新增模拟/模型隔离/转换/E4 合计 31 个测试 PASS；原 simulation_scale 6 个 PASS；原 bimanual 37 个 PASS。
- E3 8 项：7 PASS、1 SKIP（本机原始归档资料未安装）。
- 同环境原基线 416 项：8 failures / 55 errors；最终分支 455 项：同样 8 failures / 55 errors，另 1 skip；新增失败集合为空。不能写成全套 PASS。常见原错误涉及实验室绝对路径、旧日志 fixture、bridge token 文件缺失。完整日志/逐用例比较见 `regression-comparison.json`。
- 实际外部 Astra/模型请求 **0**，实验室/机器人/夹爪硬件调用 **0**。CLI 子进程资格测试使用本地 fake executable，其 usage 是 fixture，不能加入模型成本。
- CLI `0.160.0` help 与官方参数文档核对过；实际服务端模型/effort、账号授权和真实 usage 未验证。没有读取或复制登录凭据。
- EXPERIMENT_DESIGN.md、IMPLEMENTATION_DELTA.md 正文未找到；E4 卡已从分支恢复。原 E3 A/B 日志与24张 PNG 未找到，索引不能代替资料。
- 未实施真实双臂模拟 handover；未做真实模型闭环、E1/E2/E3 性能比较或现场动作；未声称 sim-to-real 控制等价。

## 已运行的复现入口

以下命令已在独立 worktree 执行；`/tmp/astra-sim-evidence-20261008` 中的原结果不可复用为新输出。交付包目录为 `source/` 与 `evidence/`，可以用其中的 `evidence/assets` 直接启动。每条写输出命令必须使用不存在的新目录。

```bash
# 从源资产建立独立副本（已运行）
python3 astra_realman_harness/scripts/prepare_rm65_sim.py   --source /home/alex/astra --output /tmp/astra-sim-evidence-20261008/assets

# 10 回合工程验收（已运行）
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python   astra_realman_harness/scripts/run_sim_acceptance.py   --assets /tmp/astra-sim-evidence-20261008/assets   --output /tmp/astra-sim-evidence-20261008/acceptance-01 --pairs 5

# 有限 STOP 验收（已运行）
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python   astra_realman_harness/scripts/run_sim_placement.py   --assets /tmp/astra-sim-evidence-20261008/assets   --output /tmp/astra-sim-evidence-20261008/stop-qualification --check-stop

# 当前 RGB 派生图与 history 导出，0 请求（已运行）
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python   astra_realman_harness/scripts/prepare_sim_request.py   --events /tmp/astra-sim-evidence-20261008/final-smoke-pair/seed-02-M/placement/events.jsonl   --request-index 3 --output /tmp/astra-sim-evidence-20261008/prepared-request-final   --resize 320 240 --history lossless

# E4 28 stub 协议调用，0 真模型请求（已运行）
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python   astra_realman_harness/scripts/run_e4_sim_protocol.py   --events /tmp/astra-sim-evidence-20261008/final-smoke-pair/seed-02-M/placement/events.jsonl   --output /tmp/astra-sim-evidence-20261008/e4-protocol-final
```

全套测试命令：`PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python -m unittest discover -s astra_realman_harness/tests`。网络相关测试仅使用 loopback fixtures，需在允许本地 socket 的环境运行。原依赖环境与 Python 可执行文件不在包内，版本锁文件随 evidence 保存。

## 下一步唯一优先事项（未授权，未运行）

授权 **最多 1 次 gpt-6-astra / medium、S 条件、固定工程场景** 的真实请求，验证本机账号/响应与实际 medium 请求记录。总决策预算 120 s，单请求最多剩余预算；无格式修复、重试、第二角色。若模型 stop/失败则不执行后续技能。只影响新模拟场景，绝不连接实验室。

下面是已实现的显式入口；当前只完成 help/本地 stub 参数验证，**真实请求行为未验收**。运行该命令即会消耗一次模型请求上限，因此本次未执行：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python   astra_realman_harness/scripts/run_sim_placement.py   --assets /tmp/astra-sim-evidence-20261008/assets   --output /tmp/astra-sim-model-one-request-NEW   --condition S --model local-cli --authorize-model --max-model-requests 1   --codex-executable /home/alex/.nvm/versions/node/v22.23.2/bin/codex --budget-s 120
```

旧 E3 32 请求必须先取得原 source 包并重新 prepare/verify；`run_e3_screen.py infer --authorize-32-real-requests` 是另一个预算，不由上面 1 次许可覆盖。不得把 E4 protocol fixture 升格成正式 G 开发集。

## 现场待核验

`config/sim_field_acceptance.template.json` 所有项保留 NOT_VERIFIED，无可执行目标：左右身份、工具/TCP、共同坐标、相机/布局 revision、示教目标和完整路径、独立持物/交接/退出证据、真实运动/夹爪、STOP 与碰撞净空。模拟参数不能复制为现场目标；先逐技能验收，再采集最终双臂任务。

## CLI 参数参考

仅用于核对接口，不证明本机账户/服务端行为：
- https://developers.openai.com/codex/cli/reference/
- https://developers.openai.com/codex/config-reference/
