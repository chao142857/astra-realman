# 右腕手眼采集与离线估计 · 2026-10-17

用户手动摆右臂，同一块11×7内角点棋盘固定桌面。复用10月11日只读采集器及网页预览，仅增加arm参数、右腕序列号映射和日志按实际arm存储。右臂192.168.1.18，右腕348522072063；桌面/上方参考画面同时保存。未发送运动、夹爪或Astra请求。

## 数据

执行目录 `/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness`。

- `logs/right-wrist-calibration-20261017-session1`：485帧，485.86秒，用户确认完成后SIGINT正常退出，`RECORDER_CTRL_C`；原图、RGB-D、机器人原始回读、棋盘角点及录像全部保留。
- 268帧右腕角点可用。按连续三帧停稳、2mm/1°机器人变化和1px角点移动门限选取；对已有选中姿态按10mm或7°去重，得16个不同姿态。先固定按时间每第三个姿态留出：11训练、5验证。
- `logs/right-wrist-calibration-20261017-analysis1/selection_policy.json` 在求解前写入。全部筛选、排除项和源数据SHA在同目录；未按拟合误差删掉差样本。
- `config/engineering/right_wrist_calibration_20261017.json` 是独立结果包；不覆盖原三相机结果。

## 数值结果

训练固定棋盘一致性 RMS：2.015mm / 0.436°；留出 RMS：5.453mm / 1.003°；留出最大位置残差9.975mm（帧425，仍保留）。棋盘格长由训练机器人平移共同估计为15.0367mm，未硬填名义15mm。

`T_Arm_Tip_camera_optical` 的平移为 **[-81.6219, 39.0255, 8.2422] mm**；完整旋转矩阵见结果包。齐次列向量、平移米，光学轴右/下/前。绑定本次右臂零World/零Arm_Tip数值条件；没有改写原SDK state中的UNKNOWN元数据。

复用 `inspect_onsite_handeye.solve()` / `choose_corner_order()`，其合成已知解自检通过。对称棋盘的180°角点次序在训练集求解；留出集仅按旋转一致性消歧，不用于拟合X/Y/格长。此为同一轮采集的留出一致性，不是独立外部计量，不声称实体毫米级绝对精度或运动许可。

此次没有测实体夹持中心TCP，也没有求左/右基座间变换。用户指出历史真机使用仿真相同TCP值，此线索保留，不能把本次相机变换误称成TCP标定；旧应用层偏移仍须按具体配置核对。

## 复算（不连接设备）

```bash
cd /home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness
/home/tongji/miniconda3/envs/dp/bin/python -B scripts/analyze_right_wrist_session.py \
 --run logs/right-wrist-calibration-20261017-session1 \
 --output logs/right-wrist-calibration-20261017-analysis-reproduction
```

输出目录必须不存在。预览 `http://127.0.0.1:8771` 已转为结束后的归档画面；Mac转发是 `http://127.0.0.1:28771`，不是还在采集。只推必要源码、标定JSON和本文；图像、深度、录像保留yanglab，不自动下载或推送。
