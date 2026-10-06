# Astra history / 短诊断准备交付

本轮完成的是离线实现和数据流验收。未调用真实模型、连接实验室相机或操作机械臂；不能据此判定首次放置失败、远离框、空释放的真实原因，也没有成功率提升结论。

## 代码位置与基线

- 独立工作副本：`/Users/tangchao/Desktop/资料/P7/astra-history-prep-20261007`
- 分支：`codex/history-diagnostics-20261007`
- 远端核对的基线：`22bfb2e549e6ca98b741ba84f254d4c1bbe66225`，与任务文档一致。
- 未改动 P7/astra-realman-upload、P7/astra-harness-20261005 或资料/astra 的原有文件及未提交工作。
- 在目标仓库和所查上级目录中未发现适用的 AGENTS.md。
- 已检查 launcher → runner → context → backend → executor 实际调用链。最近真机日志文件不在本地；已检索 P7 中的备份及资料/astra 归档。后者的历史归档说明与 evidence 属于另一套较早的仿真/控制基线，不能替代本次放框片段。

## 实际修改

所有路径相对仓库根目录。

| 文件 | 用途 |
|---|---|
| `.gitignore` | 排除日志、缓存和 bridge token |
| `astra_realman_harness/history_diagnostics.py` | 完成态 transition、history、严格 envelope 解码、证据约束 |
| `astra_realman_harness/schema/left_decision.schema.json` | 四段短诊断 + 原八字段 action；每字段 1–600 字符，提示 1–2 句 |
| `astra_realman_harness/scripts/run_left_history_diagnostics.py` | 独立三视角自动闭环；统一 profile、预算、日志和失败回读 |
| `astra_realman_harness/run_official_astra_history_diagnostics.sh` | 新 launcher；任务只输入一次 |
| `astra_realman_harness/left_terminal.py` | call_astra 增加可选 schema_path / decoder，默认仍为旧协议 |
| `astra_realman_harness/codex_astra_backend.py` | 附件清单、准备/传输计时、真实 usage；原传输、错误拒绝路径不变 |
| `astra_realman_harness/left_executor.py` | 可选计时器；运动函数、数值、速度、夹爪等待、guard 和无重试语义保持 |
| `astra_realman_harness/timing.py` | monotonic 父子阶段计时 |
| `astra_realman_harness/scripts/prepare_history_replay.py` | 固定时刻四种输入；可选真实单次推理；严格读取最终记录 |
| `astra_realman_harness/scripts/report_history_experiment.py` | 每步/总量/中位数、阶段分组、独立结果与阶段分开计数 |
| `astra_realman_harness/scripts/prepare_history_experiment.py` | 六局顺序、统一任务和预算、命令及现场记录模板 |
| `astra_realman_harness/fixtures/synthetic_history.py` | 明确标记的 synthetic 状态与 1 像素图片，无场景判断依据 |
| `astra_realman_harness/scripts/demo_history_profiles.py` | 一条命令生成四种真实请求格式 |
| `astra_realman_harness/tests/test_history_diagnostics.py` | 新增离线行为验收 |
| 本文及 `docs/history-prep-verification/` | 交付说明与原始测试结果 |

原四视角/三视角/旧 history5 launcher 和 runner、八字段 schema、IK 模块、pose_telemetry、Mac bridge 均未修改。共享模块只增加可选注入或观测计时。

## 四种输入差异

| Profile | 完成态历史条数 | 输出 | 图片 |
|---|---:|---|---|
| H1D0 | 最近 1 条 | 原 action | 同组三张当前图 |
| H5D0 | 最近 5 条 | 原 action | 同组三张当前图 |
| H1D1 | 最近 1 条 | diagnostics + action | 同组三张当前图 |
| H5D1 | 最近 5 条 | diagnostics + action | 同组三张当前图 |

H1 不是无 history。四组固定 gpt-6-astra / low / 1% / left_wrist→tabletop→overhead。D1 不附加历史图、不回灌旧诊断、不增加调用次数、不修改动作数值。legacy1/legacy5 保留，但反馈内容不同，不能用 legacy→H5D1 单独估计诊断收益。

现成对照：`logs/synthetic-history-prep-20261007/four-profiles/`。第 7 个固定决策，H1 收到 step 6；H5 收到 step 2–6，其中 step 2 为 IK 拒绝。D0/D1 同 K 的 history、任务和附件完全相同，只有输出 schema 与短诊断说明变化。每组有 `model_input.json`、`decision/prompt.txt`、`decision/attachments.json`，均为准备后的输入，未调用真实模型。

## Transition 与错误语义

每步保存 proposal、actual dispatch、decision/fresh/after pose、SDK/IK、夹爪、错误、相机引用和时间戳。实测位移基于 fresh dispatch-before；旋转残差复用 atan2(sin,cos) wrap。

- IK 拒绝：零下发、空通道、拒绝原因；execution residual 为 null。
- NOOP / done / 仅夹爪 / dry-run：未下发 arm 时 residual 为 null。
- 部分执行后停止：只记录已调用通道，尽量完成 after 回读；回读失败明确 null，不假造位姿。
- closed gripper、SDK 0 和 model done 均不生成抓取/放置成功；物体状态默认 unknown。
- 原始 `after/observation.json` 保留；完成记录另写 `transition.json`，最终 `next_observation.json` 引用其路径。下一轮 history 只加入完成记录，不重建 raw capture.previous。
- 新局新 history；构造请求不会追加，重复 transition 去重并拒绝冲突；对象深拷贝，拒绝未来 step、未来时间与无回读历史。
- 完整响应在 `decision/astra_raw.txt`；合法响应另存 `raw_proposal.txt`、`parsed_action.json`、D1 的 `diagnostics.json`。backend 先拒绝的非法响应仍保留在 decision 目录，不会构造 executor。

## 本地离线验证命令

在独立仓库根目录运行。输出目录需全新，所有日志写入采用独占创建。

```bash
cd '/Users/tangchao/Desktop/资料/P7/astra-history-prep-20261007'
/opt/homebrew/bin/python3 -B -m unittest discover -s astra_realman_harness/tests -p test_history_diagnostics.py -v
/opt/homebrew/bin/python3 -B astra_realman_harness/scripts/demo_history_profiles.py \
  --output astra_realman_harness/logs/synthetic-new-check
ASTRA_PYTHON=/opt/homebrew/bin/python3 bash astra_realman_harness/run_official_astra_history_diagnostics.sh --help
```

已完成结果：

- 新增 9 个测试方法全部通过，含四种 profile 各 7 步的整条 runner→真实 backend 编码/校验→IK→原 executor→回读→下一请求路径；HTTP 模型响应、SDK 和相机均为 mock。没有真实网络推理或硬件下发。
- 覆盖实测偏差、拒绝、history 裁剪/顺序/重复/隔离、未来数据、深拷贝、严格 envelope、动作数值、部分通道失败、失败回读、预算停止。
- 验证同一 transition 在最终日志、backend prompt、replay 输入中相等；每步一次模型调用，三张附件；固定速度调用参数 `(1,0,0,1)`。
- D1 独立离线 fixture 启动通过：`logs/left-measured-H5D1-20261006T155801Z-91abd0c3/summary.json` 为 OFFLINE_REPLAY_COMPLETE，model_calls=0，hardware_commands_sent=0。
- 报表示例：`logs/offline-report-20261007/report.md` 及 JSON。
- 全量：270 项中 214 通过，55 errors、1 failure。未修改基线：261 项中 205 通过，同样的 55 errors、1 failure，56 个失败用例名称完全一致。原因包括缺实验室 observation 日志、bridge token、numpy，以及仓库未含 transforms。没有伪造旧日志或 token 来填平这些失败。详情见 `docs/history-prep-verification/`。
- 全部 Python 文件语法解析、launcher bash -n、git diff --check 通过。

## 实验室隔离部署（仅提供命令，本轮未执行）

打包文件位于本地 P7：`astra-history-prep-20261007.tar.gz`。含代码及说明，不含 logs、token、.git；本地 synthetic 日志可按上述命令重新生成。

Mac 上传：

```bash
scp '/Users/tangchao/Desktop/资料/P7/astra-history-prep-20261007.tar.gz' yanglab:/tmp/astra-history-prep-20261007.tar.gz
```

实验室终端解包至全新目录（mkdir 如发现目录已存在则停止，先核对；勿覆盖）：

```bash
mkdir /home/tongji/alex/astra_history_prep_20261007 && \
tar -xzf /tmp/astra-history-prep-20261007.tar.gz -C /home/tongji/alex/astra_history_prep_20261007
ln -s /home/tongji/alex/astra_realman_harness/config/codex_astra_bridge.token \
  /home/tongji/alex/astra_history_prep_20261007/astra_realman_harness/config/codex_astra_bridge.token
```

token 只在同一工作站引用原文件，不复制凭据到 Mac 或交付包。新 live 入口默认使用原 `/home/tongji/alex/astra_realman_harness/logs/auto-pick.lock`，避免新旧目录分别加锁而同时控制。`--lock-path` 仅用于测试或明确迁移后的共享锁位置。

Mac bridge 沿用已工作的会话。若需启动，在 Mac 独立终端执行原命令：

```bash
ssh yanglab 'cat /home/tongji/alex/astra_realman_harness/scripts/codex_astra_mac_bridge.py' > /tmp/codex_astra_mac_bridge.py
python3 /tmp/codex_astra_mac_bridge.py
```

该 bridge 已接受请求携带的 schema；不需改模型会话机制。实际 D1 schema 接受性、官方模型可用性与登录状态仍需现场第一条真实请求核实。

## 原入口与新入口的准确命令

原四视角复现、legacy1 三视角、legacy5（实验室）：

```bash
bash /home/tongji/alex/astra_realman_harness/run_official_astra.sh execute
bash /home/tongji/alex/astra_realman_harness/run_official_astra_threeview.sh execute
bash /home/tongji/alex/astra_realman_harness/run_official_astra_threeview_history5.sh execute
```

新 H5D0（输入任务一次，随后自动闭环）：

```bash
cd /home/tongji/alex/astra_history_prep_20261007/astra_realman_harness
bash ./run_official_astra_history_diagnostics.sh execute \
  --profile H5D0 --max-steps 10 --wall-budget-s 480 --layout-id L1 --trial-id placement-01
```

新 H5D1：

```bash
bash ./run_official_astra_history_diagnostics.sh execute \
  --profile H5D1 --max-steps 10 --wall-budget-s 480 --layout-id L1 --trial-id placement-02
```

切换 `--profile H1D0/H1D1/H5D0/H5D1` 即可。`shadow` 替代 `execute` 为真实观测与模型、零动作的模式。默认 shadow。`--task '原样任务'` 可免任务输入。STOP + Enter / Ctrl-C 沿用原停止路径。`execute --print-command --profile H5D1` 只打印启动命令。

墙钟预算使用 monotonic；到期取消模型、阻止后续通道/步骤。现有 block=1 运动不能被此软件预算立即中断；在途阻塞 SDK 返回及回读可能造成超时，记录 budget_overrun_s，不暗示 480 秒硬实时急停。

## 六局放框与至多三局完整抓放

在新 harness 目录初始化计划，任务输入一次。六条命令存入文本，逐局恢复起点后执行对应一条：

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/prepare_history_experiment.py \
  --output logs/placement-plan-20261007 --max-steps 10 --wall-budget-s 480
```

顺序：L1 D0→D1，L2 D1→D0，L3 D0→D1。共用 task、10 次决策、480 秒；如预算不够应在整组开始前统一修改。`plan.json` 保存 run 路径、起点、夹持、介入、偏离与独立证据；每局第一组图和位姿在该局 `step-01/input/`。不要直接把六条命令串起来，局间需要恢复布局和可靠夹持，局内无需逐步 Enter。

根据预算内独立完成、恢复情况、无效动作与耗时选择候选，随后执行最多三局：

```bash
bash ./run_official_astra_history_diagnostics.sh execute --profile H5D1 \
  --phase full-pick-place --trial-id full-01 --layout-id full-L1 --max-steps 50 --wall-budget-s 1200
```

这里 H5D1 仅为候选命令示例，现场根据前六局选择；完整抓放预算独立记录，不混入短放框比较。

每局将 `independent_observation.template.json` 复制为同目录 `independent_observation.json` 后人工填写。`actual_stable_in_basket` 用 true/false/"unknown"，必须有 observer、evidence、episode_id；录像/独立观察确认球入框且夹爪离开后保持稳定。模板并不构成观察证据。恢复、画面矛盾、无效动作、人工介入和起点偏离也记录在该文件。模型输入不会读取它。

## 固定观测检查与耗时报告

新日志：给定决策 step，只读此前完成 transition，冻结本步 input_observation。默认只生成输入：

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/prepare_history_replay.py \
  --run logs/实际回合目录 --step 3 --output logs/fixed-step3
```

需要真实模型固定观测对照时添加 `--infer --profiles H5D0 H5D1`，每条件一次调用，永不执行动作。新动作与旧轨迹不同后，后续旧图不能用作其 rollout 或成功标签。

旧日志添加 `--import-legacy`。工具要求每个前缀的完整 `next_observation.json`、实际执行记录、pre-execution、原始 proposal 与 feasibility；缺任何字段就失败，不退回不完整 after/observation。路径迁移后应先保留/修复图像路径和哈希的对应关系，不能把错误图片硬配上。已有真机失败片段缺失，本轮未声称完成真实回放。

汇总多局（填写具体日志目录）：

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/report_history_experiment.py \
  logs/实际回合1 logs/实际回合2 --output logs/experiment-report-20261007
```

生成 `report.md`、`report.json`、`counts_by_phase_profile.json`。后者区分 placement/full-pick-place 及各 profile 的实际独立完成数、unknown 和 model_done；不是统计显著性报告。

计时分层：episode→step→backend / executor / IK / capture；executor 内含 arm、between-channels capture、gripper communication / settle。backend 内含请求准备与包含远端 CLI 的 HTTP 区间；CLI 是子项，不能再次相加。transport-only 无可靠独立边界，固定 null。step_other 仅用互不重叠的同级阶段相减。旧日志缺细分项记 unavailable；保留 camera_capture 原始指标及真正的 turn.completed.usage，没有 usage 则 null。

运动速度保持现有 `rm_movej_p(pose,1,0,0,1)`。[RealMan 官方文档](https://develop.realman-robotics.com/robot/apipython/classes/movePlan/)说明速度参数取 1–100；本轮不把速度变化混入 H/D 对比。提示仅借鉴多轮实际反馈与简短证据摘要，不声称复现 CaP-X 的独立视觉差分模型或 REFLECT 的感知系统。

## 日志与回滚

- 实验室新运行：`/home/tongji/alex/astra_history_prep_20261007/astra_realman_harness/logs/left-measured-<profile>-<UTC时间>-<id>/`。
- 每步：model_input、decision/prompt、attachments、原响应、diagnostics（D1）、action、计划、IK、实际下发、原始 capture、最终 transition、next_observation、timing。
- 每局：history_profile（含完整 task 和预算）、source_manifest（实际代码 hash）、独立标注模板、summary。
- Mac CLI：原 `/private/tmp/codex-astra-bridge/<uuid>/`。
- 回滚：结束新进程后直接启动上面原目录的旧命令。新部署没有覆盖旧目录；无需 reset、删日志或恢复 token。保留失败局和旧日志。
- 本地回滚：原目录完全不变；独立仓库中可用 `git diff 22bfb2e` 审阅所有增量，勿用 hard reset 清理其他工作。

## 仍须现场核实

1. 实际部署代码 hash、官方 bridge/model/low、三视角顺序及原共享锁；新 profile 第一条真实请求检查 prompt、附件和 schema，无须重复整套离线测试。
2. schema 的真实 CLI 接受性与 D1 输出质量：证据是否对应当前图，未知视觉变化是否保留 unknown。
3. 找回首次放置失败→远离框→空释放以及 IK 拒绝后的原始日志和录像；按决策时刻做固定观测比较。
4. 真机 actual pose、夹爪、SDK/IK 与 transition 是否一致，逐阶段耗时及 block=1 超预算情况。
5. 三种可重复布局、可靠起始夹持、六局独立标注与候选最多三局串联验证。历史、视觉判断、动作选择、执行偏差、延迟哪一层主导，应由这些具体证据判断。
