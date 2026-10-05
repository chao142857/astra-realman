# 独立四视角入口（2026-10-05）

三视角入口及配置保持不变。四视角新增 serial 348522072063，附在原三路之后，role=additional_view，物理安装位置不作假设。不连接、读取或操控右臂。

先结束三视角运行（STOP/回车或 Ctrl-C，已下发动作未必立即停止），不要同时打开两个入口争用相机和左臂。物理初始场景由操作者恢复；程序不会自动回位。保持同一 task 原文比较，不增加提示。

工作站终端：
```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B \
  /home/tongji/alex/astra_realman_harness/scripts/run_left_fourview.py \
  --live --execute --model gpt-6-astra --max-steps 50
```

输入和三视角实验完全相同的 task。真实运动模式为 REAL_EXECUTION；去掉 --execute 则只 dry-run。

预览 http://127.0.0.1:8765；第四张图片会显示 additional_view 和 serial。模型实际请求的 images_in_attachment_order 应有4项，robot_states 仍仅 left。同一 schema、数值开度、rm_movej_p、夹爪执行和错误停止策略；共用 left_executor.py。STOP/Ctrl-C 阻止后续命令，紧急情况用物理急停。

四视角日志：/home/tongji/alex/astra_realman_harness/logs/left-fourview-时间-ID/
三视角日志仍为 left-terminal-时间-ID。

七项离线测试通过；历史图像+fixture端到端回放通过，运动0、模型调用0。尚未启动四路真实采集/真实模型验收。观察结果不能仅凭一次成功或失败归因于视角数量。
