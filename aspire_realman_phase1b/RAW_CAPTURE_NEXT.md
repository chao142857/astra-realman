# 下一次现场RGB-D短采集：已备入口，本轮未打开设备

复用现有`LabRGBDOwner`的唯一pipeline、设备检查与锁；新增可选raw_archive，不创建第二个相机owner。历史Replay、封存输入与旧结果不修改。当前缺少现场raw流和已知尺度参考，故仍不能唯一归因aligned深度污染或认证三维精度。

现场确认已有相机owner：有则先在该owner发布/保存，不能抢占；无则使用原入口的设备占用检查和合作锁。确认桌面SDK serial仍为346222072496；其他三路未恢复前仍作为物理缺口，不能猜映射。

新选项`--save-raw-streams --reference-description <实际参考物/尺度/距离及摆放记录>`启用同一frameset保存：

- rs.align之前立即复制raw RGB及raw depth Z16，之后保存aligned RGB、Z16、米制深度；不将aligned Z16改名为raw。各帧独立新目录，不覆盖旧采集。
- 当前双方实际stream profiles、格式/fps/内参/畸变、工厂depth→color外参和depth scale；每帧raw intrinsics及aligned intrinsics、双方帧号/时间戳/时间域、支持的metadata、host wait/receive monotonic区间和boot id。
- 每个资产SHA、设备角色/serial、owner、已知尺度参考的操作者描述。参考描述不是软件实测或精度认证；World仍为null。最多保存60对，其他采集质量记录照常保留。

与原入口一样不写曝光/标定/固件/USB选项，不reset，不修改相机配置资产。已通过合成不同尺寸raw/aligned数组的序列化检查；实际profile和原始流内容需要现场运行后验收。

仅供现场明确采集授权、无其他owner且放好参考物后执行；本轮不执行：

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
/home/tongji/alex/aspire_realman_phase1a_20261020/.venv/bin/python -B \
  aspire_realman_phase1a/tools/capture_validate.py \
  --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE \
  --capture-tabletop --seconds 4 --output evidence/onsite-raw-new \
  --save-raw-streams --reference-description '<现场实际尺度/距离/摆放，不填写猜测值>'
```

检查raw-frames/*/snapshot.json内的实际尺寸、raw/aligned帧对应关系、profiles与哈希。用已知尺度参考覆盖目标、桌面、背景及深度边缘，检查原始返回、遮挡/像素竞争和对齐后分配；保留失败帧，不只保存最好帧。逐点重投影必须使用当前raw depth内参/畸变、scale及工厂外参，并明确遮挡/多对一处理；采集前不生成伪重投影证据。

下一轮候选方法保持独立：三维连通作为优先候选生成，SOR为常规对照；仍使用已冻结5/10/20mm及1/2/3σ网格作公平复核，不把20mm或2σ确认为最优。新增场景应包含不同摆放/距离和参考，不将同一短采集首尾帧当独立场景。
