# Baseline 对齐补页 · 2026-10-07

本页追加本轮实际快照，不修改 `EXPERIMENT_DESIGN.md` / E4旧审查时点的事实。**E3首批是旧 H5D1 单臂真实日志回放，不是双臂技能实验。** 所有核实为文件/Git只读；现场目录、运行进程、控制行为未改动。

| 层次 | 本轮远端实际版本 | 实现与证据边界 |
|---|---|---|
| 旧 H/D | `/home/tongji/alex/astra_lab_20261007`：detached `39a043e4b29ec7e18b1c1f057ebce2aa59a831b2`；**dirty** | `history_diagnostics.py` 最近1/5条实测transition；D1=`diagnostics + action`；左臂Cartesian delta和连续opening。现场dirty涉及launch、GUI、bridge、left terminal/fourview/history入口；HEAD不是完整现场快照。 |
| 双臂低层动作组 | `/home/tongji/alex/astra_parallel_arms_20261007`：`codex/single-astra-parallel-arms-20261007`，`2896c0268a869b1b41fa8020c418c0112ae7b5ec`，clean | `run_parallel_arms.py` / `parallel_arms.py`：单模型输出 `{done, execution, actions}`，每臂最多一条低层动作，独立SDK worker；支持顺序/并行分发。不是高层技能，也不是两个决策agent；本轮未执行，不能据代码宣称真实交接成功。其前置右臂镜像部署为clean `60f4a78c9b0eed0209c6621a48b100dc0445e565`。 |
| 高层 synthetic skill runtime | `/home/tongji/alex/astra_bimanual_sort_20261007`：`codex/bimanual-sort-foundation-20261007`，`5c24866791106711a1945c60435a4d27e639bef6`，clean | `bimanual_demo/runtime.py` 构造 synthetic observer/mock arms，技能与ownership事件不能作为真实物理证据。新2896分支虽有RealArmExecutor适配，Runtime仍直接选择synthetic；不把低层双臂能力等同真实高层skill闭环。 |

**E3来源锁定。** 根目录为旧部署下 `astra_realman_harness/logs/`。A=`left-measured-H5D1-20261007T071622Z-f1df44cd`，检查点6/12/28/36，原task **“把网球放到透明盒子里”**；B=`left-measured-H5D1-20261007T075054Z-27aae930`，检查点6/12/22/25，原task **“把三个白色方块堆叠在一起，叠成三层高”**。两run记录的 `source_revision_base=22bfb2e549e6ca98b741ba84f254d4c1bbe66225`，以各自source_manifest与实际请求为历史证据，不能用今天HEAD替代当时dirty文件。

八点 `model_input.json` 与 `decision/prompt.txt` JSON完全相同；原三附件顺序为左腕 **254522073676**、桌面 **346222072496**、俯视 **344422071480**，24张实际输入图均640×480 PNG，保存原字节SHA256。不新增历史图片；部分当前观测原本来自上一动作after图，保持该绑定。history是调用前最近5条**完整实测transition**；不含当前步结果/未来图片/旧模型diagnostics。调用前状态、frame、task、证据规则和原诊断指令不变，只有history表示/选择作为T0–T3变量。

**输出协议与medium证据。** 各run `action_schema.json` 等于实际context中的schema，也等于本地 `schema/left_decision.schema.json`：四段公开diagnostics＋left Cartesian action，含translation、RPY、opening[0,1]、done，非高层skill或双臂group。八份历史 `decision/command.json` 均为官方provider、`--model gpt-6-astra`、`model_reasoning_effort="medium"`、三次`--image`。原 `history_profile.json` 写low的冲突保留，不静默修史；当前2896 bridge源码已为medium，不能改写旧foundation源码为low的审查事实。命令仅证明客户端请求，上游内部配置仍UNKNOWN。

**本轮实现隔离。** Mac `/Users/tangchao/Desktop/资料/P7/astra-e3-history-screen-20261007`，新分支 `codex/e3-history-screen-20261007` 从2896建立；origin仍为 `https://github.com/chao142857/astra-realman.git`。新增离线E3模块/入口/测试，复用原回放校验、H5D1 parser、image evidence、Mac CLI bridge函数和归档。实际请求由用户显式启动，固定medium；不调用bridge的SSH/server main，不导入硬件executor。来源及请求索引见该工作树 `astra_realman_harness/docs/e3/`，原证据包保存在本地 `logs/e3-source-20261007/`。旧E1/E2/E3文档四文件hash保持不变；不展开712/630预算。
