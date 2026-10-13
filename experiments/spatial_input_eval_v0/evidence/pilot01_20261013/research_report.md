# Pilot 01 实际 A/C 评测

批次状态：**STOPPED**。新增预算已保留 4/24；确认 HTTP 派发 4 次。
新增结果分类：{"valid": 3, "infrastructure_failure": 1}。主实验有效样本 4/24，完整配对 2/12；独立 S5 A 复测 0/1。
历史 S5 A（0091de8）原始文件未修改，不计新增预算。复测独立报告，不替换主配对。

| 类别 | 输入 | 有效任务 | 全部约束通过 | 平均任务分 | 数值题平均误差 m | 平均耗时 s |
|---|---|---:|---:|---:|---:|---:|
| understand | A | 0 | 0/0 | — | — | — |
| understand | C | 0 | 0/0 | — | — | — |
| plan | A | 2 | 2/2 | 1.000 | — | 25.799 |
| plan | C | 2 | 2/2 | 1.000 | — | 18.070 |

空间理解题目正确率：

- A：0/0；按题型和米制误差见 summary.json、understanding_questions.csv。
- C：0/0；按题型和米制误差见 summary.json、understanding_questions.csv。

| 场景 | 任务 | A 分数 | C 分数 | C−A 分数 | C−A 输入 token | C−A 输出 token | C−A 耗时 s |
|---|---|---:|---:|---:|---:|---:|---:|
| lab_s5_placement | plan | 1.000 | 1.000 | 0.000 | 407 | -266 | -14.394 |
| lab_s6_held_object_detour | plan | 1.000 | 1.000 | 0.000 | 548 | -47 | -1.063 |

几何失败（完整原始答案与逐题 / 逐约束评分保存在各 sample-0000）：

- 已完成的有效样本中暂无几何失败。

独立 S5 A 复测：

- 尚未执行。

新增派发的已知 token 合计：input=35963，output=396（reasoning 是 output 的子集，不重复相加）。已知客户端等待耗时合计 145.657s；包括历史样本的主实验统计另列于 research_metrics.json。

所有 A/C 输入与历史配对均经冻结 payload、图像 SHA、任务、schema 和模型参数一致性核验。每个有效新样本均有独立 ephemeral thread、turn.completed、完整 CLI command、usage 与离线重评分审计。

S5/S6 为主要规划任务；S4 朝向由任务规定，不代表自主选择朝向。S5 历史 A 已满分，同分不等于几何信息无效。六个静态场景及其相关任务只支持探索性描述；不做统计显著性或总体泛化结论。评分不涵盖动力学、支撑稳定性、IK 或真实硬件。
