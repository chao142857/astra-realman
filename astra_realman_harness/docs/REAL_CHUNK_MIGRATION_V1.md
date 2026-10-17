# RealMan chunk 协议与 GUI：离线迁移 V1

2026-10-17。基于实机 onsite `431f112c` 的独立分支。生产 onsite 及其未提交标定文件不变。

## 本次已接入

- `chunk_protocol_v2_1.py` 从仿真修复 `c3330268` 原样提取，保持 stage / TCP waypoints / gripper 结构。`real_chunk_adapter.py` 使用原 `strict_json`，验证有限数值、单位 wxyz 四元数和并行冲突。
- sequential 允许重复机械臂：按 stage/operation 编号存储，不用 arm 字典覆盖。每操作从前一项执行后的 backend 回读状态开始。parallel 在 fake 中作为同组节点处理，不串行改写模型意图；这不是硬件同步验证。
- 模型段内最多 5 mm / 1° 插值，每操作至多128节点；原 waypoint 精确保留，不选绕障路线或注入任务阶段动作。当前仅离线展开，不声称连续 rm_movej_p 的实测路径已验收。
- 明确区分命令执行、接触保持、稳定抓取。`position` 命令返回不代表抓取；缺传感依据的 contact/hold 为 UNKNOWN / NOT_ASSESSED。`bilateral_hold` 在当前实机迁移版本明确拒绝，不替模型选择开度或降级成 position。
- 提供显式 `T_world_work` / `T_tool_tcp` 下的纯数值 SDK 目标预览：`inv(T_world_work) * T_world_tcp * inv(T_tool_tcp)`，输出 xyz米、ZYX对应RPY弧度。没有默认标定、1.1m实体假设、隐式TCP偏移或SDK派发；RPY奇异点明确拒绝。
- 不可覆盖的原始提案、SHA、逐节点 claim、回读、逐操作回执与最终状态。未知/异常停止，无重试、无恢复旧操作。fake claim 不是模型请求账本，也不消耗历史预算。
- 复用原 GUI 的 HTTP 服务、权限检查、历史选择与组件，增加离线提案编辑及有序操作时间线、原始/回读展开、JSON报告。旧单臂/双臂 GUI 与老执行器保留。

## 启动

在 yanglab（仅 localhost；已有 Python，无依赖安装）：

```bash
cd /home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness
/home/tongji/miniconda3/envs/aloha/bin/python scripts/run_real_chunk_offline.py --port 8886
```

实验室本机浏览器打开 `http://127.0.0.1:8886`。Mac 如需访问，可单独建立仅本地转发：

```bash
ssh -N -L 18886:127.0.0.1:8886 yanglab
```

Mac 打开 `http://127.0.0.1:18886`。此入口默认无真实摄像头、SDK、Bridge；页面无法切换成真机执行。

单次离线验收或读取用户指定的归档 JSON：

```bash
/home/tongji/miniconda3/envs/aloha/bin/python scripts/run_real_chunk_offline.py --once
/home/tongji/miniconda3/envs/aloha/bin/python scripts/run_real_chunk_offline.py --once --proposal /absolute/path/to/raw.txt
```

所有回执写入新 `logs/real-chunk-offline-<uuid>/`，同路径不可重用。默认fixture只是数值合同测试，不是专家抓取/交接/放置路线。照片、视频不伪造；GUI四相机槽位显示未连接。旧仿真提案的世界坐标不能直接当作真机目标。

## 实际验收范围及限制

新迁移23项单元测试、2项localhost HTTP测试；旧 parallel GUI 6项、GUI 14项、parallel coordinator 18项，共63项；另有4条原JS决策保留断言与JS语法检查。用下述命令复现：

```bash
cd tests
/home/tongji/miniconda3/envs/aloha/bin/python -m unittest test_real_chunk_migration test_real_chunk_http test_parallel_gui test_astra_gui test_parallel_arms -q
node test_gui_decision_retention.js
```

初次Mac受限环境禁止localhost监听；以本地网络测试权限重跑HTTP。额外尝试老 `test_left_executor` / `test_exact_target_feasibility` 的22项遇到缺失归档夹具 `logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json`；不把这些项目计入PASS，不伪造历史夹具。这些模块本次未修改。

**未完成真机动作验收，也没有接通新的模型闭环。** 本轮 model=0、hardware=0、真实相机=0。`offline_manifest.json` 固定生成授权false、预算0、硬件许可false；不是新真实DRAFT/GRANTED账本。没有读取/修改旧授权或STOPPED账本。

实际执行前仍需：左右base/world/tool/TCP当前标定，四相机映射/标定和时间一致性，实际开度/接触保持能力，共享空间整段碰撞检查，SDK实际路径/跟踪与在途停止验收。现有 ENDPOINT_IK_ONLY 不能替代这些项目。新的模型验收/预算与实机许可接入需在这些绑定明确后进行，不能仅解除一个bool开关就运动。

本版本不会移植PhysX参数、仿真2mm穿透读数、专家目标、完整handoff技能或历史剩余额度。Astra今后仍从桌面方块、双臂空手初态决定整个抓取—交接—放置；fake完成或SDK应答不记为任务成功。

## 数据与流量

本分支只提交必要源码、测试和本文。日志/截图留本机，未提交视频、RGB、完整物理日志或凭据。yanglab 通过已有 onsite 对象库和小型增量 bundle 创建独立worktree；不覆盖原部署、不升级环境。
