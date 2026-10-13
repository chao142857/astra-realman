# Pilot 01 实际 A/C 评测

批次状态：**READY**。累计预算已保留 16/24（前阶段 4 次）；本阶段确认 HTTP 派发 12 次。
新增结果分类：{"valid": 12}。主实验有效样本 16/24，完整配对 8/12；独立 S5 A 复测 0/1。
历史 S5 A（0091de8）原始文件未修改，不计新增预算。复测独立报告，不替换主配对。

| 类别 | 输入 | 有效任务 | 全部约束通过 | 平均任务分 | 数值题平均误差 m | 平均耗时 s |
|---|---|---:|---:|---:|---:|---:|
| understand | A | 4 | 2/4 | 0.833 | 0.004 | 118.592 |
| understand | C | 4 | 4/4 | 1.000 | 0.000 | 27.114 |
| plan | A | 4 | 4/4 | 1.000 | — | 23.464 |
| plan | C | 4 | 4/4 | 1.000 | — | 19.606 |

空间理解题目正确率：

- A：30/36；按题型和米制误差见 summary.json、understanding_questions.csv。
- C：36/36；按题型和米制误差见 summary.json、understanding_questions.csv。

| 场景 | 任务 | A 分数 | C 分数 | C−A 分数 | C−A 输入 token | C−A 输出 token | C−A 耗时 s |
|---|---|---:|---:|---:|---:|---:|---:|
| lab_s1_relations | plan | 1.000 | 1.000 | 0.000 | 417 | -36 | 1.208 |
| lab_s1_relations | understand | 0.667 | 1.000 | 0.333 | 397 | -2197 | -99.823 |
| lab_s2_occlusion | plan | 1.000 | 1.000 | 0.000 | 397 | 0 | -1.179 |
| lab_s2_occlusion | understand | 1.000 | 1.000 | 0.000 | 387 | -1861 | -82.711 |
| lab_s3_narrow_container | understand | 0.667 | 1.000 | 0.333 | 967 | -2418 | -98.208 |
| lab_s4_rotated_fit | understand | 1.000 | 1.000 | 0.000 | 894 | -1966 | -85.170 |
| lab_s5_placement | plan | 1.000 | 1.000 | 0.000 | 407 | -266 | -14.394 |
| lab_s6_held_object_detour | plan | 1.000 | 1.000 | 0.000 | 548 | -47 | -1.063 |

几何失败（完整原始答案与逐题 / 逐约束评分保存在各 sample-0000）：

- lab_s3_narrow_container/understand/RGB_MULTI_VIEW：UNDERSTANDING:position, UNDERSTANDING:top_height, UNDERSTANDING:size；score=0.6666666666666666。
- lab_s1_relations/understand/RGB_MULTI_VIEW：UNDERSTANDING:position, UNDERSTANDING:top_height, UNDERSTANDING:size；score=0.6666666666666666。

独立 S5 A 复测：

- 尚未执行。

本阶段新增派发的已知 token 合计：input=145199，output=10804（reasoning 是 output 的子集，不重复相加）。已知客户端等待耗时合计 667.367s；并发时该值是各请求等待之和，并非批次墙钟耗时。包括历史样本的主实验统计另列于 research_metrics.json。

所有 A/C 输入与历史配对均经冻结 payload、图像 SHA、任务、schema 和模型参数一致性核验。每个有效新样本均有独立 ephemeral thread、turn.completed、完整 CLI command、usage 与离线重评分审计。

S5/S6 为主要规划任务；S4 朝向由任务规定，不代表自主选择朝向。S5 历史 A 已满分，同分不等于几何信息无效。六个静态场景及其相关任务只支持探索性描述；不做统计显著性或总体泛化结论。评分不涵盖动力学、支撑稳定性、IK 或真实硬件。

用户在第 4 次（S2 A）90 秒超时后明确选择四个隔离 worker、180 秒的新阶段。累计预算未增加；先前超时保留且消耗一次。S2 A 新请求是明确授权后的独立重测。S5/S6 plan 的原 90 秒串行配对作为 carryover 保留，其他任务在 180 秒四并发阶段执行；各行保留 deadline_s/concurrency。不能把跨阶段延迟变化单独归因为几何信息。剩余 20 次若全部用于补齐主矩阵，则没有额外 S5 A 复测预算。
