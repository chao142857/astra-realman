# 2026-10-09 平台验收

结论：**离线接口与有限SAPIEN验收PASS**，可供独立研究程序通过固定版本client复用。真实Astra=0、硬件=0；未启动新的B/F配对。不是研究性能、泛化率或真机验收结论。

## 本次唯一新增物理回合

证据根：`/home/alex/astra-realman_ws/astra-research-platform-evidence-20261009`。
`online-reference-001`为全新进程空夹爪场景，`ENGINEERING_REFERENCE`。
7个原参考chunk完成接近、闭爪、抬升与保持、运输、下降、释放、退出；第8个chunk只用于验证假CLI原raw的hold(.04s)。共11个实际动作，未尝试第2个物理回合，不根据结果调参。

| 项目 | 实测 |
|---|---:|
| 独立完整任务评分 | PASS |
| 抬升最大值 | 94.055 mm |
| 闭爪双侧稳定持物且高于50mm的最长区间 | 1180步 |
| 放置XY误差 | 0.332 mm |
| released / stable_in_target / exited | true / true / true |
| dropped_while_closed / safety_abort | false / false |
| 物体接触最小separation | −0.1115 mm |
| 初始化墙钟 / 物理时间 | 2.069s / 3.300s |
| 回合墙钟 / 物理时间（含最终稳定评分） | 27.535s / 17.184s |
| 进程总墙钟 | 29.850s |
| 公开观测 / RGB哈希检查 | 19 / 57 |
| 在线验收假infer / 真实Astra / 硬件 | 1 / 0 / 0 |

独立评分来自原`FullTaskBackend.finish`，不仅看闭爪或保持。工程参考脚本的已执行运输/释放/退出与完整分数一同保留。原score中的`model_action_decisions`等是继承的dispatcher计数字段，本回合为工程脚本，不能解释为真实模型请求。

| chunk | 阶段 | 墙钟s | 物理s | 结果 |
|---|---|---:|---:|---|
| 1 | 三段接近 | 7.056 | 5.064 | ok |
| 2 | 闭爪 | 2.205 | 1.400 | ok |
| 3 | 抬升+保持 | 4.141 | 2.764 | ok |
| 4 | 运输 | 3.026 | 1.956 | ok |
| 5 | 下降 | 2.490 | 1.632 | ok |
| 6 | 释放 | 2.253 | 1.400 | ok |
| 7 | 退出 | 2.287 | 1.508 | ok |
| 8 | 假CLI raw hold | 0.043 | 0.040 | ok |

未剪辑原生视频：`online-reference-001/private/scene/execution.mp4`，1280×480、fixed+wrist、10fps、201帧；逐帧解码通过。三路RGB在public快照中；视频不是三路。ffprobe本机缺失，使用OpenCV核对，不安装依赖。视频包含原采样帧而非连续墙钟屏幕录像。

假请求证据在`private/workers/request-001/`：原infer函数、隔离worker、Node v22.23.2、gpt-6-astra/medium客户端配置、工具禁用、严格raw解析均复用。假CLI明确返回FAKE_NOT_ASTRA；`turn.completed=true`仅是假事件。bridge latency=0.100881s；不可视为真实模型延迟。usage原样保留`input_tokens=3,cached_input_tokens=0,output_tokens=2,fixture_only=true`。服务端model/effort/内部重试没有事实证据，保持unknown。

最终wire哈希：`473e7c7c4b4b510347d804c52f28647c76df00733dd821296d5be1b108417418`。最终payload与实际bridge prompt相等、附件哈希通过、raw与parsed相等、执行actions与raw相等；源图step4778，执行后新图step4820。参考目标、专家轨迹、GT与分数未进入wire；兼容history为空。独立研究进程的宿主目录/auth/评分方法不可访问断言通过。

## 历史场景与证据索引

| 场景 | 只读bundle | 原记录 | 本次动作 |
|---|---|---|---|
| 正常完整抓放 | replay/reference | astra-shared-pnp-evidence-20261009/reference-001 | 只读转换；16观测、7结果 |
| 抓取失败 | replay/grasp_failure | layout_runs/L2-r1 | 只读转换；GRASP_CONTACT_LOST_AFTER_LATCH保留 |
| 固定参考IK拒绝 | replay/ik_failure | layout_runs/L3-r1 | 只读转换；IK Failed及2项未执行余项保留 |
| 相机运动 | reference腕部标定 | 8个不同pose | 实际随腕运动；无虚拟相机插值 |
| 操作局部遮挡 | reference/o-0004/fixed.png，原rm65:0006 | 指垫覆盖红方块右侧可见表面 | 人工RGB目视确认局部遮挡；无完美mask/遮挡率GT；颜色组件仍visible |

回放只有合法公开投影，不从分数补造PASS。L2/L3原FAIL不变，也不代表所有布局不可抓/绝对不可达。本轮没有新增严重遮挡或专门失败注入的物理实验；回放足以覆盖首版场景接入。

9月历史另按原`formal_*/result.json`的`classification`复核：SUCCESS8、TASK_FAIL1；第10个无评分。不是从缺失的status字段推断。见`september_verified_classification_index.json`；早期草稿`september_source_index.json`的status:null不作为分类依据。

完整原始路径、哈希、测试命令与审计见证据根`EVIDENCE_INDEX.json`、`online_audit.json`、`raw_execution_binding_audit.json`、`video_audit.json`。旧真实失败与旧工程数据共2062个保护文件复核零变化（`preservation_before/after.json`）。

## 定向测试与修复范围

- 新接口18项测试：版本/字段拒绝、私分数隔离、新进程reset、epoch/STOP、不可改写/重用候选、12chunk上限、部分执行/未知结果、模型observe/finish提交、owner最低门、replay不可执行/篡改检测、预检失败先于scene、真实本地假owner进程的半截/错误RPC与清理异常归档。
- 原专项90项通过：FullSlot/infer假进程、超时/晚到/取消、真实raw严格解析无回退、资格预算、输入/requirements、grasp基础与共享工程投影。只做离线/假进程回归，无新B/F物理回合。
- 物理验收运行源快照在`executed_source_snapshot/`，运行时Git基线为d5757f2+新增文件，逐文件SHA保留。之后仅补强新增层的意外异常“未执行未知”语义、清理错误记录及原RPC字节保存；这些失败分支用上述离线进程测试覆盖，没有为它们重复物理验收。最终提交不把旧结果改写成最终代码再次运行的结果。

可交付的路径：历史replay、独立进程多相机观察、统一chunk执行、既有模型通道假进程提交、新观测、失败/私分数隔离。剩余：真实模型在新外层上的视觉闭环尚未验收；硬件现场参数与运动STOP仍UNKNOWN；通用对象/动态任务、多文件研究程序依赖、自定义模型上下文不在v1能力内。研究算法留在独立项目。
