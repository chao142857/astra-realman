# 旧服务与相机：2026-10-20

## 服务退出结果

08:19的重新核实确认以下进程仍为tongji所有，argv/cwd/端口符合指定实验服务。没有其它工作区Python实验runner/arm_worker，`ss -tnp`没有既有192.168.1.18/19:8080连接。操作者已明确报告机械臂电源关闭；本轮未连接机器人验证电源。

| 服务 | 本轮实际PID | 信号与结果 |
|---|---:|---|
| 8888硬件GUI | 1268122 | 逐PID核对启动tick/argv/cwd后SIGINT，退出 |
| 8886离线GUI | 26282 | SIGINT，退出 |
| 8771右腕归档回放 | 32647 | SIGINT，退出 |
| 8890静态文件服务 | 110607 | SIGINT，退出 |
| 静态服务专用bash父进程 | 110606 | 子服务结束后自行退出，未发送额外信号 |

没有使用SIGTERM、SIGKILL、killall、pkill、进程组信号或GUI rescan；没有重启任何旧服务。退出后8888/8886/8771/8890不再监听，`fuser /dev/video*`无占用。SSH/Tailscale/Clash与其它系统/用户进程保持；没有改原源码/配置或删除、覆盖原始日志/归档。正常退出可能由原服务自身完成日志flush，这是SIGINT正常清理的一部分。

证据：`services_before.json`、`shutdown_sigint.json`、`services_after.json`。执行脚本每次发送信号前再次核实当前用户、完整argv/cwd/start_ticks，并在发现其它实验进程或机器人既有连接时拒绝操作；提交的脚本模板没有预装历史PID目标，不能不经核实批量重用。

## 相机实际状态与Phase0修正

**确认目前只有历史桌面D435一路，不是四路恢复。**

| 标识层/相机 | 结果 |
|---|---|
| USB descriptor serial | `027223021284`，Intel RealSense Depth Camera435，8086:0b07 |
| RealSense SDK serial | **`346222072496`**；firmware5.16.0.1，USB3.2，Stereo Module＋RGB Camera |
| 关联依据 | SDK physical_port指向 `/sys/devices/.../usb2/2-1/2-1:1.0/video4linux/video0`；video0..5的共同USB父节点正是 `usb2/2-1`，其USB descriptor serial是027… |
| 可信角色记录 | 原部署 `config/arm_mirror.json` 将SDK serial346…明确映射为tabletop，role_confirmed=true；三相机历史包也一致 |
| 左腕254522073676 | SDK未枚举 |
| 上方344422071480 | SDK未枚举 |
| 右腕348522072063 | SDK未枚举 |
| video0..5占用 | 旧服务退出后无进程占用；六个节点属于同一D435，不是六台相机 |

因此，Phase0仅根据sysfs把027…描述成“与四路不同的新序列号、角色未知”过于保守：**它是同一当前可见桌面D435的USB层标识，SDK层标识为346…**。本轮用SDK枚举和相同物理路径建立了关联；不把两种serial混入标定键。没有证据表明另三台相机先前只是被GUI隐藏，更不能声称SIGINT让四路全部重新枚举。

对027…还做了有界源码/配置/文档检索（17366个小文本文件，无匹配）；角色判断来自SDK serial与既有可信角色表，不来自这个“无匹配”。没有USB reset、重插模拟、设备替换、驱动/固件重装或修改相机参数。

SDK枚举只用了现有dp解释器的 `rs.context().query_devices()` 和设备元数据，没有构造pipeline或启动stream；dp/aloha包未改。设备标识关联不证明当前安装姿态与历史标定相同，也不消除桌面深度历史失败。其余三路需要现场核查供电、USB/集线器、接线，记为物理阻塞，不阻止软件测试。

完整证据见 `camera_enumeration.json`、`camera_usb_correlation.json`、`camera_role_search.json`。相机枚举结论与Native Adapter测试分开，不用历史图像冒充当前画面。
