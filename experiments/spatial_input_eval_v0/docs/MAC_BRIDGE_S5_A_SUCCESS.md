# 真实 S5 A 首次有效 JSON 与独立评分通过

在用户新授权“一次、90 秒截止、不自动重试”后，使用提交 `8da20ae` 的冻结代码和输入，
通过原 Mac ChatGPT → SSH bridge 完成一个 `lab_s5_placement / plan / RGB_MULTI_VIEW` 样本。
本轮只派发 1 次，CLI 记录 1 个完成回合，未重试、未取消、未调用 C 条件。

| 验收项 | 实际结果 |
| --- | --- |
| 模型 / 参数 | gpt-6-astra / medium / openai / ephemeral，归档 command 审计 PASS |
| 认证 | 同一原 worker 环境确认 ChatGPT 登录，认证内容未复制或输出 |
| 输入 | 原三张 RGB、标定与固定任务；A 的 geometry 为 null；不传 depth、GT、witness |
| HTTP / CLI | 200 / return_code 0 / error null |
| 截止时间 / 耗时 | 90 秒 / 32.177 秒（Mac worker 31.669 秒） |
| JSON 解析 | VALID；生产 schema 校验及 V0 严格解析通过 |
| 独立评分 | SCORED，score 1.0，四项约束全部通过 |
| 离线重评分 | 同一冻结 snapshot 和已归档 raw 得到完全相同结果，新增模型调用 0 |
| CLI usage | input 11600；output 367，其中 reasoning output 316；cached input 0 |

模型原始 JSON：

```json
{"object_id":"target","position_m":[0.62,0.145,0.1],"quaternion_wxyz":[1,0,0,0],"waypoints_m":[]}
```

坐标单位为米，坐标系 robot_base（本仿真与 world 重合）。评分器确认：正确目标对象、
完整体积处于允许区域、满足障碍净空、满足规定朝向。这是静态几何放置结果，没有真机动作。
朝向在任务中已规定，因此此结果只支持这个样本的位置选择成功，不是自主朝向规划证据。

## 日志与 Code Mode 的实际观察

CLI 事件含 `thread.started`、`turn.started`、一个 agent_message、`turn.completed` 和真实 usage。
还保留两条被 CLI 标为 error item 的启动消息：

- skip_host_skill_discovery 是开发中的 feature。
- Code Mode host 被禁用，Code Mode 不可用。

本次这些消息没有阻止无工具的结构化回答；worker 正常退出且原 bridge 的本地校验通过。
没有修改 bridge、模型参数、Code Mode 开关或原生产代码，也没有为压制警告更改用户配置。
这说明当前原配置能够完成本次三图 JSON 请求，不证明所有 Code Mode 工具路径均可用。

## 归档和复现

目录：`evidence/authorized_mac_A_s5_second/`。

- `authorization.json`：本轮独立授权与派发前检查。
- `sample-0000/`：冻结 wire、图片、参数、原 HTTP body、bridge_result、raw/events/stderr、传输与评分。
- `mac_native/`：匹配到的 Mac 原始生成目录中的 prompt、三张 RGB、command、schema audit、原生结果与事件。
- `native_archive_audit.json`：两端原始结果一致、冻结输入/图片 SHA 一致、原模型参数一致的核验。
- `rescore/`：读取已保存 raw 后独立重评分；不启动模型或仿真。
- `delivery.json`、`artifact_seal.json`：结果索引及文件校验清单。
- 同级 `authorized_mac_A_s5_second.launch.log`：真实 runner 启动结果。

依照既有 ARTIFACT_POLICY，Mac runtime SQLite 缓存不入 Git，排除清单保存在 native_archive_audit；
输入、原始生成结果、事件、schema 审计、评分和复现信息均归档。未复制任何认证文件。

实验室离线重评分命令（输出目录应为新的）：

```bash
cd /home/tongji/alex/spatial-eval-mac-bridge-20261013
PYTHONPATH=experiments/spatial_input_eval_v0 \
  /home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python -m spatial_eval.cli rescore \
  --snapshot experiments/spatial_input_eval_v0/evidence/lab_20261013/sim_suite_initial/lab_s5_placement/snapshot.json \
  --source-run experiments/spatial_input_eval_v0/evidence/authorized_mac_A_s5_second \
  --output experiments/spatial_input_eval_v0/evidence/s5_A_offline_rescore_reproduction
```

这一条 A 样本不能用于估计总体能力或 A/C 增益。当前已具备开展后续同任务 A/C 比较的链路基础；
新的真实请求仍须单独授权，本轮未继续 C 或 S6。
