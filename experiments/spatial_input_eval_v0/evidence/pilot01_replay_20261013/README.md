# Pilot 01 私有规划回放与几何描述

基线 b103ee5；12 份真实规划输出全部重评分与归档原评分逐字段一致，原始 12/12 成功保持不变。生成请求为 0。

本目录只用于人类分析，包含独立 GT，不是模型输入。原图保持不变，叠加图由原始 RGB、冻结标定和原始模型输出离线生成。

每份输出含三个原始相机视图的标注、一个独立正交几何诊断图和四面板回放。叠加的 GT 边可以穿过遮挡物；它们不是模型实际看见的像素。正交图不是 SAPIEN 渲染。

## 指标定义

- **区域面余量**：物体八个角点到允许区域六个内侧平面的最小有符号距离，单位 mm；正值表示完全位于区域内。这是区域面的几何量。
- **SAT 投影阈值**：保持原 `swept_collision` 算法，寻找向每个单位 SAT 轴的投影半径和增加相同标量后，首次发生接触/碰撞的阈值。报告 60 次二分的无碰撞下界和碰撞上界；它**不是精确欧氏障碍距离**。下界减任务规定的 2 mm 是该同一投影规则下的附加余量。
- **路径余量**：SAT 对全部连续线段检验，没有按稀疏点采样；固定姿态下，凸工作空间的区域面余量最小值出现在路径端点或折点。
- **路径长度**：从题目给定起点、依次经过原始 waypoints 的中心折线长度。无路径任务记为不适用，不虚构搬运轨迹。不声称最优路径。

| 场景 | 条件 | 原分数 | 路径 m | 落点区域面 mm | 落点 SAT 投影阈值 mm | 全路径 SAT 投影阈值 mm | 工作空间面 mm |
|---|---|---:|---:|---:|---:|---:|---:|
| [lab_s1_relations](lab_s1_relations_A/replay.png) | RGB_MULTI_VIEW | 1.0 | — | 39.999999 | 55.000000 | — | — |
| [lab_s1_relations](lab_s1_relations_C/replay.png) | RGB_ORACLE_3D | 1.0 | — | 39.999999 | 55.000000 | — | — |
| [lab_s2_occlusion](lab_s2_occlusion_A/replay.png) | RGB_MULTI_VIEW | 1.0 | — | 39.999999 | 55.000000 | — | — |
| [lab_s2_occlusion](lab_s2_occlusion_C/replay.png) | RGB_ORACLE_3D | 1.0 | — | 39.999999 | 55.000000 | — | — |
| [lab_s3_narrow_container](lab_s3_narrow_container_A/replay.png) | RGB_MULTI_VIEW | 1.0 | — | 40.000001 | 65.000002 | — | — |
| [lab_s3_narrow_container](lab_s3_narrow_container_C/replay.png) | RGB_ORACLE_3D | 1.0 | — | 40.000001 | 65.000002 | — | — |
| [lab_s4_rotated_fit](lab_s4_rotated_fit_A/replay.png) | RGB_MULTI_VIEW | 1.0 | — | 15.000001 | 14.999998 | — | — |
| [lab_s4_rotated_fit](lab_s4_rotated_fit_C/replay.png) | RGB_ORACLE_3D | 1.0 | — | 15.000001 | 14.999998 | — | — |
| [lab_s5_placement](lab_s5_placement_A/replay.png) | RGB_MULTI_VIEW | 1.0 | — | 20.000001 | 35.000016 | — | — |
| [lab_s5_placement](lab_s5_placement_C/replay.png) | RGB_ORACLE_3D | 1.0 | — | 20.000001 | 35.000016 | — | — |
| [lab_s6_held_object_detour](lab_s6_held_object_detour_A/replay.png) | RGB_MULTI_VIEW | 1.0 | 1.220 | 50.000001 | 95.000001 | 95.000001 | 20.000001 |
| [lab_s6_held_object_detour](lab_s6_held_object_detour_C/replay.png) | RGB_ORACLE_3D | 1.0 | 1.000 | 50.000001 | 95.000001 | 29.999994 | 80.000001 |

S5 A/C 落点 y 分别为 0.145/0.150 m，均满足原任务。S6 A/C 均采用抬高绕障，最高中心 z 分别为 0.46/0.35 m，路径分别为 1.22/1.00 m；原任务没有最短路径或能耗目标。较短路径不等于已证明最优，二元合法率相同也不意味着几何信息无效。

S4 的四元数由题目给定；该成功不作为自主朝向选择能力证据。规划任务不检查机器人可达性、动力学、抓取稳定性或支撑条件。

## 复现

在仓库根目录，使用包含 Pillow 的离线 Python：

```bash
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
python experiments/spatial_input_eval_v0/lab/replay_pilot01.py --output /tmp/pilot01-replay-new
```

输出目录必须不存在。脚本只读取冻结数据和原始结果；不导入模型 adapter，不接触任何 ledger。源文件 SHA 和相机投影交叉校验记录见 JSON。
