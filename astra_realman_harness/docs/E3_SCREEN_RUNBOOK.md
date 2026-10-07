# E3：八个旧检查点 × 四种history请求

本入口只做固定日志推理，**没有硬件执行路径**。原任务、当前三图、状态/frame、原H5D1 diagnostics+action协议保持不变。不是rollout，不能用旧轨迹未来结果给新action判抓取成功。本批不实现或启动E1/E2/E4，不扩大到712/630请求。

## 已准备的数据与条件

目录 `logs/e3-screen-32-20261007/`，来源 `logs/e3-source-20261007/`。`manifest.json` 固定32项、请求次序、输入/schema/图片/代码hash。`docs/e3/input_index.csv` 为实际32项输入索引；每项原task、source run/step、observation_id、五条history step、三张附件路径/hash均已展开。源run定义和版本见 `docs/BASELINE_ALIGNMENT.md`。

| 检查点 | 原history steps | 原任务 |
|---|---|---|
| A06 | 1–5 | 把网球放到透明盒子里 |
| A12 | 7–11 | 同上 |
| A28 | 23–27 | 同上；27为REJECTED_IK |
| A36 | 31–35 | 同上；不输入36的实际结果 |
| B06 | 1–5 | 把三个白色方块堆叠在一起，叠成三层高 |
| B12 | 7–11 | 同上 |
| B22 | 17–21 | 同上；21为REJECTED_IK |
| B25 | 20–24 | 同上；保留21未执行记录，不推定已恢复目标 |

每点对应T0/T1/T2/T3各一次。次序按检查点轮换，四个条件在每个位置各出现两次；无模型结果后择优换点。

- **T0**：原history内容，其他字段原样。传输沿用原bridge的JSON序列化。
- **T1**：重复JSON子树字典引用＋请求内解码说明，所有值可无损还原。数字不取整，false/null/unknown/空容器不合并；测试逐叶类型和值。真正送的是压缩结构，不是解码后历史。
- **T2**：与T3共同protected envelope，按最近优先选完整事件；不跳过放不下的最近事件去选更早事件。
- **T3**：同codec、同预算、同protected envelope；优先最新事件、窗口内没有显式解决证据的失败、最新明确holding事件、其他最近事件。没有holding证据就保留unknown；不把模型意见写成事实，不新增任务规划。

T2/T3 history预算=该点T1实际序列化history UTF-8字节的50%向下取整，**包括字典、解码说明和protected envelope**。protected超过预算，两者均回退T1，记录原因/超出量；不截断半个事件。共同保护原事件身份/顺序/时间/物体unknown，最新完整实测state、proposal/实发/回读区分，以及未解决失败的原proposal、IK/SDK结果；当前task/frame/schema等全部history外字段原样保留。`fact_inventory.json` 逐JSON pointer列原值、保留/删除、解码目标位置。删除是缺失，不是false。

**本批离线已发现T2与T3在8/8点生成完全相同输入。** 预算只容纳1条完整事件（B22为2条），失败关键事实已在共同protected中。因此不能用这批结果声称事件优先胜过最近优先；不同输出也可能只是重复推理波动。仍按用户要求准备32项，不为制造差异扩大历史/增加检查点。本轮没有真实token或延迟收益结论。

## 在Mac运行

无需登录Ubuntu、启动bridge服务、连接相机或运行GUI。使用当前Mac既有Codex认证；固定官方`gpt-6-astra`、medium、read-only、ephemeral、三图、原output schema，模型工具禁用。复用 `scripts/codex_astra_mac_bridge.py:infer/command`，不调用其main；现有现场bridge与进程不变。CLI版本本轮只读查询为0.160.0。

先离线复核（0模型调用）：

```bash
cd /Users/tangchao/Desktop/资料/P7/astra-e3-history-screen-20261007/astra_realman_harness
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  scripts/run_e3_screen.py verify --batch logs/e3-screen-32-20261007
```

**只有你运行下面这条才实际发送32个模型请求；没有机器人动作：**

```bash
cd /Users/tangchao/Desktop/资料/P7/astra-e3-history-screen-20261007/astra_realman_harness
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  scripts/run_e3_screen.py infer \
  --batch logs/e3-screen-32-20261007 --authorize-32-real-requests
```

串行，32次上限，每项最多120s推理等待，不自动重试/补样本/修复输出。不接受自选endpoint、模型、effort或executor参数。单项backend/格式失败记入分母并进行下一项；Ctrl-C取消当前请求并终止剩余请求。批次有exclusive `inference.claim`，重复启动拒绝；中断后也不自动resume，避免未知结果被重复计费。保留claim和日志，不通过删claim假装首次启动。全部超时的推理等待上界64分钟，进程准备/退出、报告和归档开销另计；不承诺完成时间或美元费用。

推理结束/中断后查看报表，再用已有归档导出：

```bash
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  scripts/run_e3_screen.py report --batch logs/e3-screen-32-20261007
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  scripts/run_e3_screen.py archive --batch logs/e3-screen-32-20261007
```

归档复用 `episode_archive.archive_episode`，输出路径由命令打印；归档是可移植展示副本，保持原batch和源证据作为逐字节核对依据。history中的远端旧图片路径只是引用，未复制的历史图可能列MISSING_IMAGE警告；模型实际三附件在每项`attachments.json`与内容hash中核实，不把缺少历史图称为丢失当前模型输入。若已生成离线归档，后续推理产物须另行归档快照，不能沿用旧receipt冒充完成版。

## 日志与人工标签

每项独立文件：`model_input.json` / `prompt.txt`、`attachments.json`、`schema.json`、`projection.json`、`fact_inventory.json`、`replay_manifest.json`；真实调用后增加`decision/command.json`、raw/events/stderr/backend_result、`diagnostics.json`、`parsed_action.json`、`result.json`。没有executed action或after state的新数据；不能写空SDK成功掩盖没执行。原bridge逐字节stdin另留在每项`result.json`引用的Mac临时日志目录。

`request_report.csv/json`：32项状态、派发尝试、输入字节、projection耗时、CLI backend耗时、总耗时、input/cached/output usage、错误/回退，以及条件汇总。字节不是token，未知usage=null，不计为0；cached是input的子集，不与input重复相加。backend耗时含CLI进程与网络，不是纯模型计算；total包含准备/解析，不能再和子耗时相加。

`human_labels.template.json` 每点两名评审：当前可见物体/阶段/遮挡；持物或接触可否确认；可接受下一动作集合（非唯一标准delta）；IK拒绝是否未执行；本判断所必需的history事实；证据引用与分歧裁决。当前标签全待填。先看同一检查点的合法历史/当前三图标注，再盲评随机化的条件输出；不看旧未来结果替新动作判成功。标签不会进入prompt，模型无法通过工具读取它。

## 离线重建与验收

```bash
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  tests/test_e3_history_screen.py -v
```

如果需要重建准备包，在未存在的新输出目录运行`prepare`；不覆盖本批冻结输入。重建不意味着授权追加模型预算：

```bash
/Users/tangchao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B \
  scripts/run_e3_screen.py prepare --source logs/e3-source-20261007 \
  --output logs/e3-screen-32-rebuilt-20261007
```

旧日志/PNG按原项目规则留在ignored logs，不新增上传私人实验图片的行为。代码与报告索引在独立Mac分支，未部署现场。
