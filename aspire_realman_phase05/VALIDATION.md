# Phase0.5验收

## 实际结果

| 验证 | 结果 |
|---|---|
| Mac独立Python3.12.13＋固定CPU依赖 | **28/28通过，0 skip** |
| yanglab新独立Python3.12.13 `.venv` | **同一28/28通过，0 skip** |
| 原生MCP HTTP | 两端均实际通过initialize、tools/list、capability graph、observe图像、native state、Mock localization、steer/read_operator_messages、job terminal与动作拒绝 |
| 原机真实历史V17 Replay | 成功返回**4路封存RGB图像**＋真实记录的left-scope RobotState；stale=true；无可用深度的定位明确失败；gripper调用明确失败 |
| 原服务 | 4个服务SIGINT退出，专用父进程自行结束，未用TERM/KILL；4端口释放，video无占用，未自动重启 |
| 原源码/环境 | 最终371/371项实现SHA与V17成功manifest一致；dp/aloha仍3.9.18、NumPy1.24.4、RealSense2.56.5.9235 |
| 真机/模型边界 | 新增真实运动/夹爪/轨迹派发0，真实模型请求0；原生测试不开相机pipeline、不加载SDK，只允许loopback网络连接 |

28项中包含5个真实MCP HTTP测试和23个codec/adapter/replay/cache/模型缺口测试。不是全ASPIRE测试套件，不是硬件精度、控制器通信、SAM3权重推理、cuRobo GPU规划、碰撞或在途停止验收。

历史Replay直接读取H原始PNG并逐项校验记录SHA，像素仅在yanglab本机MCP测试中流动，没有下载到Mac或推送。`observe`成功证明历史图像/协议链路，不能称4路相机当前在线；状态只暴露left scope，不能称共同World已建立。实际SDK只枚举到桌面346…一路，详见ONSITE_STATUS。

## 环境与代码固定

Mac工作区：`/Users/tangchao/Desktop/资料/P7/aspire-realman-phase05-20261020`。

yanglab新工作区：`/home/tongji/alex/aspire_realman_phase05_20261020`。这里的 `.venv` 为独立环境，`include-system-site-packages=false`，没有覆盖原部署或dp/aloha。CPU源码缓存与测试包初次传输约641KB；后续只同步小型代码修正。没有传权重/mesh/图像/视频。

上游HEAD固定fa00f0e完整SHA；隔离副本应用 `0001-realman-contracts.patch`。71份CPU runtime源码通过哈希验证。Native tests用原生CapApi、EmbeddedAgentRuntime及MCP transport，没有通过另写HTTP假服务来冒充原生MCP。

远端依赖初次默认下载遭files.pythonhosted.org read timeout；两个1KB路径测试均成功后，单次pip命令通过既有127.0.0.1:7897代理、复用已有pip缓存完成安装。没有更改全局代理/TUN/SSH/认证配置或重启网络服务；不把小请求成功当作所有下载稳定的证明。

## 发现并修正的问题

- 首轮HTTP测试错误地断言原生compact job含`finished_s`，已按真实公开合同检查`active=false`；未改原生job逻辑迎合测试。
- 首轮远端完整测试有一个测试夹具依赖未打包的Phase0 README作为“root之外路径”；改为测试文件自身的绝对路径，使相同越界检查在两端均成立。
- 新增缓存整帧更新/序号拒绝、缺失相机stale标志、role/serial变化拒绝、非数值及布尔值拒绝、controller原始错误/时戳/非原子性metadata。最终两端全通过。

## 证据文件

| 路径（均在evidence） | 内容 |
|---|---|
| `services_before.json` / `shutdown_sigint.json` / `services_after.json` / `services_final.json` | 重新核实身份、逐PID信号、退出和最终端口/设备状态 |
| `camera_enumeration.json` | 真正RealSense SDK只读枚举，serial/firmware/physical_port和历史四serial是否出现 |
| `camera_usb_correlation.json` / `camera_role_search.json` | USB027…与SDK346…物理路径关联及可信角色记录、有界搜索范围 |
| `native_validation.json` | Mac28项测试和精简MCP wire摘要，含真实初始化版本、工具名/结构结果/图片数量，不含图片base64 |
| `yanglab_native_validation.json` | yanglab相同28项结果与精简wire摘要 |
| `yanglab_historical_replay.json` | 原机原始观测/绑定证据SHA、4路历史PNG SHA、native observe/state/localize拒绝/动作拒绝回执摘要 |
| `deployment_preservation.json` | 最终371项源码比对、dp/aloha版本、新.venv配置、远端实际测试的新源码SHA |
| `environment_notes.json` | 新工作区、缓存/依赖网络处置和未触碰的环境/服务边界 |

## 真实只读闭环仍差什么

参见NEXT_STEPS：当前机器人断电，没有新鲜SDK状态；3路相机未枚举；尚未把真实只读采集owner接入已实现的cache；当前控制器语义/相机安装与深度质量需重核。单臂RGB/state读环可先完成，不必把TCP/共同World当所有只读展示的前置；双臂共同公制定位/规划仍需真实base/TCP/模型证据。

本轮只完成Phase0.5软件/回放验收，没有进入Phase1、没有上电/使能、没有Home/真实夹爪动作/真实轨迹或Agent任务。
