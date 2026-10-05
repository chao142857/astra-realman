# 本机官方 Codex：终端交互
只更换模型来源，使用现有四视角、左臂 loop。每轮无需 Enter，任务由终端输入一次。
桥接须在 Mac 前台持续运行，机器人脚本在工作站运行。

## Mac 终端 1：启动模型桥接
    ssh yanglab 'cat /home/tongji/alex/astra_realman_harness/scripts/codex_astra_mac_bridge.py' > /tmp/codex_astra_mac_bridge.py
    python3 /tmp/codex_astra_mac_bridge.py

看到 bridge ready 后保持窗口开启。凭据留在 Mac。无 xmapi 回退。

## 工作站终端 2：交互入口
如果使用 Mac 的第二个终端，先运行 ssh yanglab。
    cd /home/tongji/alex/astra_realman_harness
    ./run_official_astra.sh shadow

默认 shadow 使用真实图像/状态和官方模型，不发送 actuator 命令。
本次 wrapper 也保留现有显式 execute 模式：
    ./run_official_astra.sh execute

execute 会发送真实动作；它没有添加碰撞保护或改变现有执行逻辑。
在 Task (verbatim; STOP cancels): 后输入自己的任务并回车，例如：
    Use the left arm to pick up the tennis ball.

模型收到该 task 原文，无 wrapper 前缀或附加任务提示。运行完成后再次启动入口可输入新任务。
输入一次任务后最多 50 轮，所有原有停止条件不变。

## 显示与停止
原终端完整显示 MODEL INPUT / ASTRA RAW OUTPUT / PARSED ACTION / FEASIBILITY /
EXECUTED ACTION / SDK RESULT / AFTER STATE / NEXT OBSERVATION。
工作站浏览器打开 http://127.0.0.1:8765 可看四路相机。
机器人终端输入 STOP 加回车或 Ctrl-C；Mac 桥接单独用 Ctrl-C 停止。
软件 STOP 不能保证中断已进入阻塞 SDK 的动作，不等于物理急停，也不会自动回位或松爪。

## 展开命令（不启动）
    ./run_official_astra.sh execute --print-command
展开为：
    /home/tongji/miniconda3/envs/dp/bin/python -I -B /home/tongji/alex/astra_realman_harness/scripts/run_left_fourview.py --live --model gpt-6-astra --max-steps 50 --execute

## 日志
工作站 /home/tongji/alex/astra_realman_harness/logs/left-fourview-<UTC>-<id>/
Mac 模型原始日志 /private/tmp/codex-astra-bridge/<id>/
本次只增加终端 wrapper 和文档，没有运行真实循环。
