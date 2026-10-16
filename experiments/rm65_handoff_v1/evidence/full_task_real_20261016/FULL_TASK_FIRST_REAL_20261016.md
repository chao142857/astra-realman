# Astra 完整抓取—交接—放置：首次真实探索结果

**完整任务未完成；批次已 STOPPED。实际派发4/16次，未重试，剩余12次不再使用。**

执行基线 `d713a49a115937dcb3183c44bcfd82978d19e49b`，batch `ba904d1bf5e441c3b5ec105fe5312147`，yanglab，`gpt-6-astra / medium`，单 worker、独立 ephemeral、客户端180秒/服务端190秒，无 shadow。2026-10-16 14:55（Asia/Shanghai）完成新的实际 Mac/yanglab 非生成预检，第一条预留于14:55:31。

本轮开始前，DRAFT为0次预留、空runs，101项冻结哈希通过；GRANTED仅按用户授权改变三个字段，私密保存。原1.1m布局、四视角、chunk_v2、右侧接触保持、IK/通用细分与2mm保护均未修改。正常物理reset/100 ticks后Astra从桌面方块、两臂空手打开状态接管；没有专家初始化或任务动作注入。

## 逐轮实际结果

| 决策 | 原始提案摘要 | 实际执行 | 推理墙钟(s) | 输入token | 输出token | reported reasoning |
|---|---|---|---:|---:|---:|---:|
| 1 | 左臂接近 `[.05,0,.215]`，下降至`.030`/`.027`，随后计划`bilateral_hold=.15` | 接近和下降已执行；第三stage闭爪轨迹被FCL预检拒绝；闭爪未执行 | 46.782 | 15,235 | 663 | 484 |
| 2 | 左臂高度依次`.045→.050→…→.080` | 全部执行通过；仍空手 | 31.399 | 75,280 | 537 | 115 |
| 3 | 左臂高度`.100→.045→.080→…→.180` | 全部执行通过；仍空手 | 37.482 | 97,148 | 595 | 173 |
| 4 | 计划再次下降；第3个stage包含两个左臂TCP动作（`mode=sequential`） | 真实模型正常完成，但本地额外动作约束拒绝；该提案的任何动作均未执行，立即停批 | 43.609 | 95,044 | 768 | 294 |

全部原始回答见 `evidence/full_task_real_20261016/episode/decision_*/raw.txt`。第4条在验收前停批，因此没有通常的`proposal.json`和动作`receipt.json`；原raw、bridge_result、HTTP响应、CLI事件、错误栈仍完整存在，未补写成“已执行提案”。

## 最早阻塞与最终停批应分开解释

**最早执行阻塞：决策1的第三个stage（零基index=2）闭爪轨迹碰撞预检拒绝。** 原始命令为`left / opening_fraction=0.15 / contact_mode=bilateral_hold`。前面的下降已执行；闭爪子组`executed=false`。原原因：

```
INTERPOLATED_COLLISION:left:105:
L__ctag_Left_Support_Link / table_2
L__ctag_Right_Support_Link / table_2
L__ctag_Right_2_Link / target_cube_4
```

该闭爪子组未实际执行。它说明该闭合提案与原执行器的几何预检不相容；本轮没有跳过检查或进行额外碰撞真值实验，不能仅凭这个回执断言真实接触必然发生，也不能将其归为右夹爪持物失稳。模型获得原始拒绝反馈后，确实改变了后续高度提案。

**最终停批：决策4触发`DUPLICATE_ARM_IN_STAGE`。准备阶段漏检了公开schema与本地解析器之间的限制不一致。**

第4条是有效JSON，原Bridge的JSON schema验收通过，`return_code=0`、HTTP200、`turn.completed`、usage与参数核验齐全。独立使用请求携带的公开`output_schema`再次验证也通过。但本地`parse_chunk()`额外要求每stage的机械臂唯一，因两个左臂操作而拒绝。

公开schema只有每stage至多两个动作，未表达按`arm`唯一；公开ordering文字为“sequential finishes each listed arm operation before the next”，也没有明确告知该唯一性限制。因此应将最终中止记为**公开接口与本地验收约束不一致**，不能直接记作Astra空间规划或时序推理能力失败。这里的`sequential`重复同臂写法与真正的并行同臂冲突也应区分。

严格按本次纪律停止是正确的；本轮没有去重、重排、合并动作、修改schema、放宽解析或续跑。本次不能提供完整任务能力成功率结论。

## Astra实际完成了什么

| 阶段 | 实际物理证据 |
|---|---|
| 左臂接近、调整高度 | 已执行；117个数值子组来自Astra目标的原通用细分，非专家waypoint；另1个子组预检拒绝 |
| 左臂闭爪与稳定抓取 | 未完成；实际执行闭爪命令数为0，双侧夹持ticks为0 |
| 双臂交接 | 未开始 |
| 右臂独立持物、退出、搬运 | 未开始 |
| 右臂释放并稳定放入蓝色区域 | 未开始 |
| 完整任务 | FALSE，保留原评分；独立重评分完全一致 |

两臂实测夹垫间距始终约89.84–89.85mm，均保持打开；物块中心高度约25.00mm（reset最初短暂最高25.84mm），一直在原桌面位置。没有物理保护触发、实际互臂接触或夹垫穿透；无右臂持物，因此本轮不能验证右侧持物控制器，也没有复现/改变历史3° yaw失败。

## 请求、耗时与完整性

- 客户端派发4次；4个不同thread，4次CLI正常完成；3条通过本地动作验收，第4条被本地语义校验拒绝。
- 全部HTTP200，原模型命令参数审计PASS；未出现CLI顶层错误、重连、超时、取消或自动重试。
- 总输入282,707 token；输出2,563 token，其中reported reasoning 1,066，其余1,497；所有reported缓存命中均为0。
- 推理客户端墙钟合计159.272秒；完整episode墙钟229.122秒；物理仿真109.300秒/27,325步（含0.400秒reset settle）。推理期间物理暂停。
- token是CLI报告用量，不是精确内部计算量；推理墙钟包含网络、客户端和服务端等待，不等于纯模型计算时间。
- 最近两条原始回执随细分组数变大，后续输入达到约75k–97k token。本轮没有据此更改上下文，也没有证明它与第4条输出存在因果关系。
- 101项冻结代码/依赖哈希停批后仍一致；旧CTAG STOPPED账本SHA仍为`2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1`，历史11次余额未使用。
- 原新批次ledger保留STOPPED、reserved_budget=4；前三行VALID，第4行仍RESERVED，因为原Gate只有全部本地验收成功才写VALID。**这不代表远端尚在生成**：已保存第4条`turn.completed`、rc0和原始回答。事后分类为“CLI完成但动作验收拒绝”，不手改原ledger、不退预算。
- 4指客户端派发；不声称客户端能精确控制或测出上游内部生成次数。

## 交付文件

全部位于`evidence/full_task_real_20261016/`：

- `episode/execution.mp4`：本局真实PhysX四视角录像，完整保留执行到停批的过程，未剪成成功视频。
- `episode/table_initial/`、`observation_*/`、`final_observation/`：原四视角RGB、标定与机器人实测状态。
- `episode/decision_000..003/`：原始context/图像SHA、raw、Bridge响应、CLI events无损gzip、usage、前3轮动作及执行回执。
- `episode/group_*/`、`chunk_*/`：全部原数值子组目标、关节轨迹、碰撞预检、实际执行回执与tracking检查。
- `episode/physics.jsonl.gz`及各arm日志：逐物理步TCP、关节、夹爪实际/目标值、接触及方块状态；原JSONL留在yanglab，归档gzip可逆并有SHA。
- `tcp_gripper_trace.csv.gz`、`actual_tcp_gripper_trace.png`：实际TCP、关节、夹爪开度/目标与双侧接触轨迹。
- `mac_native/`：4次原Mac CLI命令、schema/audit、native events与结果，事件与返回值逐字节一致；未复制runtime数据库或认证文件。
- `analysis_summary.json`、`decisions_summary.json`、`decisions.csv`：逐轮统计与错误分类。
- `episode/independent_score.json`、`post_run_integrity.json`：原冻结评分独立重算和完整性证据。
- `final_ledger_PUBLIC_REDACTED.json`：最终账本的公开脱敏副本，省去内嵌私有授权内容，包含原私有ledger的SHA；不是可执行或可恢复的ledger。

真实GRANTED、原含授权内容的ledger及认证文件只留在yanglab原私有目录，没有推送GitHub。准备提交中原DRAFT是历史快照，不代表本局当前状态；当前状态以本报告和公开最终脱敏副本为准。

仅离线重算本次统计：

```bash
cd /home/tongji/alex/rm65-full-task-exploration-prep-20261016/experiments/rm65_handoff_v1
source runtime.action-chunk.yanglab.sh
"$RM65_PYTHON" evidence/full_task_runs/full_table_exploration_20261016_01/analyze_archived_run.py
```

该命令不导入Bridge、不调用模型、不推进仿真。**本批次没有恢复或再次启动命令。**
