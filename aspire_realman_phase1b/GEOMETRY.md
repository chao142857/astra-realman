# 同一封存帧上的几何检查

输入固定RGB SHA `cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06`，aligned depth SHA `6d27e56122cac9de7c5244a48462661f792399d9fb79a9933f26267bc151b18c`。640×480，color #174/depth #91，SDK global_time差5.15ms。文件哈希、尺寸、color/aligned-depth K一致、Z16×工厂scale与float32米制depth一致（本帧最大残差0）均已核对。不是新的live采集。

| 手工视觉选区（像素xyxy，右下不含） | 有效深度比例 | 有效Z中位数 | 解释边界 |
|---|---:|---:|---|
| 中央 [160,120,480,360] |66.95%|1.957m|包括屏风、桌面和部分目标；88.8%有效点位于1.5–2.3m |
| 屏风 [280,80,480,230] |90.42%|2.060m|远背景；不是目标 |
| 桌面 [200,320,480,470] |3.20%|1.921m|绝大部分无深度；少量非零值也不能认定真实桌面距离 |
| 香蕉邻域 [75,245,260,290] |60.85%|0.495m|矩形仅用于诊断，不是物体Mask |
| 右侧半截蓝碗邻域 [500,245,640,290] |32.54%|0.461m|混有背景；未作为分割目标 |

RGB/Depth/Validity对照及1.5–2.3m深度落点叠加图直接显示：中央大部分有效点落在屏风一带，桌面大面积缺失。全图46.01%非零深度不能证明空间定位合格。没有做补洞、背景剔除、外参修正或深度阈值分割来制造合格结果。

## 手工轮廓链路（明确非SAM3）

`manual_annotation.json`保存逐点可复现轮廓、原图SHA、边界约1–3像素不确定性和标注者说明。轮廓包括目标暗色右端，排除桌面/投影阴影，但未经独立人工精确复核。栅格化后6,809像素，4,767点具有finite Z>0（70.01%）。有效Z的P1/P50/P99为0.445/0.491/1.939m；其中约211点（4.43%）位于1.5–2.3m。放大图显示远点主要集中在右端与上边缘，需区分手工边界不确定性、对齐边界混合/遮挡和真实深度错误；本轮不能单凭这些数据认定具体物理原因。

对所有有效点（含远点）按实际K反投影，`+X右/+Y下/+Z前`，单位m，frame=`realsense:346222072496:color_optical`。点云保留原图颜色，不补不可见形状。调用未改的ASPIRE `estimate_geometry`（PCA OBB）：

- 中心约 `[-0.20243, 0.01474, 1.19468] m`。
- extents约 `[1.52346, 0.15704, 0.11721] m`。
- 四元数WXYZ `[0.485825,-0.464091,-0.532318,-0.515007]`。
- OBB包含全部4,767个点，旋转det≈1；投影往返最大误差2.84e-14px。

这些检查证明数据关联、坐标计算和函数链路工作；往返误差是内部一致性，不是独立测距精度。**1.523m长轴及1.195m中心被少量远点显著拉偏，不能当物体尺寸/抓取位姿。** 不删除远点后只报“好看”的OBB，不转换为World，不生成机器人目标。当前geometry_accuracy_qualified=false。

## 资产位置

新隔离目录`/home/tongji/alex/aspire_realman_phase1b_20261020/evidence/`：

- `depth-regions/`：RGB/Depth/Validity对照、手工视觉ROI、1.5–2.3m落点图及整帧可见场景PLY。
- `manual-mask/manual-mask.png`：实际手工多边形Mask，非SAM3。
- `manual-mask/manual-banana-visible-cloud.ply`：71,683 bytes，SHA `e1f53aff04e9772699ac766a6d23121b27497925b9f5a21b0eb64168077064b0`。
- `manual-mask/manual-mask-geometry-preview.jpg`、`manual-cloud-xz-preview.png`、`far-depth-points-zoom.jpg`：原始污染与双深度群可检查。

具体文件SHA/路径和未取整统计在`evidence/depth_report.json`、`evidence/manual_geometry_report.json`。独立物理精度、桌面支持平面、目标实际尺寸与当前外参仍需要现场已知尺度/距离参考物验证。
