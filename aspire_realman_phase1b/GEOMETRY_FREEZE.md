# 几何诊断收尾与固定参数跨观测复核

原始SAM3、Mask、点云、aligned depth、原生OBB及前轮全部诊断保留。原始封存帧本轮跳过，没有重跑SAM3或继续调参。三维连通是下一轮优先验证的候选生成方法，SOR为常规对照，均标记ASPIRE + standard preprocessing并独立于原生基线；20mm、2σ没有被选定为通用最优。

已固定参数不变：三维半径5/10/20mm；SOR k=16、ddof=0、1/2/3σ。没有新学习模型、任务专家或目标尺寸/深度先验。

## 其他真实观测：仅固定图像区域复核

盘点现有Phase1A live-01/live-02/live-final三个短采集的首尾帧共6份真实RGB-D；其中原始final/last明确跳过，仅处理其余5份。它们属于同一桌面连续/重复观测，没有独立场景证据，也没有各观测单独的目标Mask。

因此复核使用原始Mask的**固定6817像素支持区域**，不是跨帧SAM3分割、Mask跟踪或目标覆盖率。相机安装/场景对应也未经独立参考认证。深度变化可能让同一像素落在不同表面，跨观测像素重叠只能建立诊断候选关系，不能当物体身份或位移真值。

| 观测 | 区域有效点 / 6817像素 | 3D群数5/10/20mm |
|---|---:|---|
| live-01/first |3491 / 51.21%|65 / 6 / 3|
| live-01/last |4623 / 67.82%|5 / 4 / 4|
| live-02/first |3479 / 51.03%|82 / 10 / 3|
| live-02/last |4848 / 71.12%|18 / 3 / 3|
| live-final/first |4256 / 62.43%|10 / 6 / 3|

所有群（含退化/少点OBB失败）与SOR保留/排除数均保留，没有按最近/最大群选目标。原生PCA OBB中心、轴向、尺寸、点群深度分布和RGB覆盖范围写入远端完整报告。相邻保存观测之间每个固定参数的全部非零像素重叠关系记录分裂/合并、中心变化和符号不变对应轴夹角；缺失深度不补点，轴歧义不隐藏。

结果不支持固定SOR 2σ：例如live-02/last中2σ保留4606点，仍把不同深度表面合成中心约[-0.218,-0.008,1.190]m的盒；1σ在该观测保留4559点形成较小盒，但在live-01/first的1σ同样混合深度。这里没有据此重新选参数。

三维连通的群数和像素覆盖也明显变化。20mm跨观测关系仍有分裂/合并，不能把每帧相同ID当同一个物体。全部像素重叠候选边的中心差可达约1.47m：这是固定图像区域在近/远深度之间重新分配的候选差异，**不是物体实际移动了1.47m**。例如live-01首尾帧20mm的全部重叠候选边，对应PCA轴角变化范围为3.80°–87.57°。轴向变化亦受候选变化、PCA轴接近/交换影响，没有宣称实际目标姿态稳定或精确。

## 证据和复现

轻量摘要`evidence/cross_observation_summary.json`包含6份资产身份、原帧跳过标记、5份区域覆盖/分群计数、全部参数的分裂合并摘要、中心差与轴角范围，以及完整报告SHA。

完整结果保留yanglab：`/home/tongji/alex/aspire_realman_phase1b_20261020/evidence/cross-observations-fixed-01/cross-observation.json`（718521B，SHA256 `4e472e8bc1882b4d28266adb2b885a418c250c33c92006129b07ccf0d7d96d3e`）。逐候选/逐关系数值不以少量最好候选替代。未传输原RGB-D/Mask/云。

复现入口`tools/check_other_observations.py`只读取这些已有文件，参数写死为上述已冻结网格，并按输入RGB SHA跳过原final/last。使用已有`.sam3-venv/bin/python`、OPENBLAS_NUM_THREADS=1/OMP_NUM_THREADS=1，指定`--capture-root /home/tongji/alex/aspire_realman_phase1a_20261020/evidence --baseline-report evidence/sam3-real.json --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE --output evidence/cross-observations-recheck-new`。不是下一轮再调参的入口。

本轮几何工作到此收尾。后续缺口是各新观测真实目标Mask、独立摆放/场景及已知尺度参考、同帧align前原始流；下一步实施重点是`READONLY_OWNER.md`的单臂只读入口和`RAW_CAPTURE_NEXT.md`的现场短采集。
