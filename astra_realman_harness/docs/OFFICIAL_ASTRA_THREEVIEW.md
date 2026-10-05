# 官方 Codex Astra 三视角入口
新增独立入口 run_official_astra_threeview.sh。当前四路进程、文件和配置均不修改。

三路固定顺序：
1. left_wrist 254522073676
2. tabletop 346222072496
3. overhead 344422071480

排除 additional_view 348522072063。只读取/控制左臂。
复用现有 run_left_terminal.py、CodexAstraBackend 和 Mac 官方 ChatGPT 桥接。
任务、action schema、parser、safety、IK 和 executor 均未修改。

## 等当前四路运行结束后再启动
Mac 上现有官方模型桥接可继续复用，无需重启或另开桥接。
在工作站终端：
    cd /home/tongji/alex/astra_realman_harness
    ./run_official_astra_threeview.sh execute

看到 Task 提示后输入任务。默认不带模式或使用 shadow 是真实采集但不发送动作。
不要与四路同时运行：共用相机、机械臂和 auto-pick.lock。
现有脚本的互斥锁继续生效，没有更改或绕过。

## 对照
四路原入口：./run_official_astra.sh execute
三路新入口：./run_official_astra_threeview.sh execute
三路日志：logs/left-terminal-<UTC>-<id>/
相机页面：工作站 http://127.0.0.1:8765
STOP/Ctrl-C 的行为完全沿用现有 runner；不是物理急停。

## 离线验收
bash -n 通过；--print-command 仅展开命令，不启动 runner。
历史四路观测经现有三路 context builder 选择后，仅剩指定三路。
Mac 官方命令生成器产生恰好三个 --image 参数，model=gpt-6-astra/provider=openai。
未采集相机、未连接机器人、未调用模型、未触碰运行锁。
11个既有入口/控制/backend/config文件 SHA256 前后不变。
