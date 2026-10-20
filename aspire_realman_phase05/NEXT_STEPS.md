# 真实只读闭环与规划接入的剩余项

## 基础Observation-only读环

已经具备：原生typed Adapter/Codec、原子缓存接口、Runtime Factory、MCP HTTP；合成观测/状态/定位全链路与历史只读Replay可运行。尚未连接真实SDK或启动当前相机stream。

基础单臂RGB＋状态展示不要求先测实体TCP或双基座共同World。下一步可由**新的只读采集owner**产生带身份/时戳/work/tool指纹的snapshot，再publish给当前Adapter；不得拿合成state填充离线机械臂。需要：

- 机械臂恢复只读状态可读条件；当前操作者已关电，不能取得新鲜state。本轮不自动上电/使能，也没有尝试连接断电机器人。
- 重新核对当前state reference/endpoint语义、控制器身份/work/tool/DH/版本；历史条件绑定不能直接当今天有效。
- 当前桌面D435的stream设置、factory K、depth scale、对齐/validity、角色与安装重新确认；另三路缺失需现场接线/供电/集线器检查。USB枚举与GUI占用已经分开核对。
- 把现有只读SDK与RGB-D格式接成**单一owner**，接入本轮实现的原子cache；验收freshness、帧号/时间域、跨进程生命周期和失联时missing/stale。当前源仅支持调用者提供的snapshot/本地Replay，没有假称已实现/验收真实硬件后端。
- 新只读runtime独立端口/工作区，实际工具schema和状态质量先核对；保持adapter硬拒绝。可先每臂单独scope，不为了显示双臂而补假共同World。

这些是只读采集部署和现场设备可用性缺口，不意味着本轮有运动授权。模型真实任务也尚未启动。

## 双臂公制观测、TCP与cuRobo

`model_requirements.json` 把所有未实测项保留为null；`planning_readiness()` 给出缺口并始终保持物理planning/运动不放行。

| 项目 | 当前状态 | 接入要求 |
|---|---|---|
| B_L/B_R→共同Work | 缺失 | 选择真实参考系后分别测量，保存方向、尺度、误差/日期/装配版本和独立验证点；原生state与point cloud用同一W |
| Arm_Tip→实际抓取TCP | 左右均缺失 | 平移/轴、夹垫、开度相关项、安装版本与不确定性；不是腕相机外参或零tool，也不沿用仿真数值 |
| 相机光学→W | 历史4路已有估计，当前安装有效性未复核 | SDK serial作为key；RGB-D/深度质量门槛、腕部时间同步、误差传播；桌面历史失败样本保留 |
| RM65双臂模型 | 没有已独立验收的真实装配模型 | 12关节次序/轴/限位，逐臂实际DH/FK、基座安装/末端/夹爪碰撞体/自碰撞及互臂过滤；比对控制器FK，不用Panda/YAM模型 |
| cuRobo model注册 | 原生服务只支持panda/dual_panda/yam_real | 后续增加 `realman_rm65_dual` 的schema、model factory、joint validation、end_effector links与碰撞配置；client/protocol/Native CapApi复用 |
| 变换编码 | 尚未有真实定义 | 选择URDF固定关节或planning context表达base；不能重复叠加，不能用identity填未知位置。YAM0.62m、旧仿真1.1m均不作实测 |
| 执行与同步 | 当前只拒绝 | SDK阻塞终点RPC不等于固定周期/同tick同步；需要时间/路径/跟踪、失败未知、操作id去重和在途停止验收。此项须后续明确硬件授权 |

推荐软件顺序：先完成真实只读owner和单臂scope闭环；再独立测量共同World/TCP并建立RM65模型；在离线记录上检查SAM3几何与cuRobo规划；最后才讨论另行授权的执行合同测试。没有为了这些接入修改Agent任务决策或添加任务专家程序。
