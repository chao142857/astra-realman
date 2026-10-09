# Research-Ready Platform v1

基于 `d5757f2`，新增薄适配层。旧仓库负责环境、动作、测量与私有评分；研究项目负责记忆、选择和调度。本次未修改现有模拟器、ModelAdapter、grasp_control、规划器、动作协议、RGB/接触/STOP检查、−2 mm阈值或B/F算法。

离线与有限仿真验收通过：一次独立进程完整工程抓放PASS，随后一次假CLI原始提案经原infer通道执行并获得新观测。真实Astra=0，硬件=0。脚本和假CLI不证明真实视觉决策能力；真机不是已验收的平台。

## 固定版本复用

工作树：`/home/alex/astra-realman_ws/astra-realman-research-platform-v1-20261009`。
证据：`/home/alex/astra-realman_ws/astra-research-platform-evidence-20261009`。
版本：`astra.realman.platform.v1`；动作版本：`full_pnp_candidate_v2`。
交付提交见该工作树 `git rev-parse HEAD`，研究项目应锁定完整提交号，启动该版本的owner，勿复制模拟器/控制器。

独立研究程序只需 `from platform_client import Client`。owner将**指定的单个Python程序**与固定版本client挂到隔离进程 `/app`；程序只能读取 `/public`，不能读取owner私有日志/scene、宿主研究目录或auth。调用时stdout只发送JSON RPC，诊断输出使用stderr。示例：

```python
from platform_client import Client
p = Client()
o = p.reset()                       # 新进程中的空夹爪场景
rgb_bytes = p.rgb(o, 'wrist')         # 校验当前PNG与SHA256
r = p.execute([{'type':'hold','seconds':0.04}], o['observation_id'])
if r['ok']:
    newer = p.observe()               # 真正再渲染，不复用旧图
p.finish('unknown')                  # 关闭控制；不返回私有分数
```

`examples/research_platform/model_once.py`展示固定兼容模型接口：`infer(observation_id)` → 来自原始输出的candidate → `commit(proposal_id)` → 新观测。无重试、无动作stub回退。`ENGINEERING_REFERENCE`示例单独存放，目标参数不进入infer输入。

## 可运行命令

```bash
CODE=/home/alex/astra-realman_ws/astra-realman-research-platform-v1-20261009/astra_realman_harness
EVIDENCE=/home/alex/astra-realman_ws/astra-research-platform-evidence-20261009
PY=/home/alex/astra/.venv/bin/python
ASSETS=/home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets
```

只读历史回放；不启动SAPIEN、策略执行、模型或硬件：

```bash
"$PY" "$CODE/scripts/platform_replay.py" read --bundle "$EVIDENCE/replay/reference"
"$PY" "$CODE/scripts/platform_replay.py" read --bundle "$EVIDENCE/replay/grasp_failure"
"$PY" "$CODE/scripts/platform_replay.py" read --bundle "$EVIDENCE/replay/ik_failure"
```

从新研究进程在线读三路图（生成新的空夹爪场景，不执行任务动作；每次output必须全新）：

```bash
"$PY" "$CODE/scripts/run_research_platform.py" \
  --assets "$ASSETS" --output /tmp/research-observe-new-01 \
  --program "$CODE/examples/research_platform/observe_only.py" --budget-s 120
```

重现工程完整抓放及假模型验收的入口（本次已运行一次，不自动再次执行）：

```bash
"$PY" "$CODE/scripts/prepare_platform_fake_cli.py" --output /tmp/platform-fake-cli-new-01
"$PY" "$CODE/scripts/run_research_platform.py" \
  --assets "$ASSETS" --output /tmp/research-reference-new-01 \
  --program "$CODE/examples/research_platform/reference_fixture.py" \
  --source ENGINEERING_REFERENCE \
  --fake-cli /tmp/platform-fake-cli-new-01/bin/codex --budget-s 120
```

仅核验假模型到动作链可把program改为 `model_once.py`，source保留默认 `RESEARCH_PROGRAM`。替换为独立研究项目的单个Python入口也用同一 `--program`。如需多文件模块、网络模型、自定义模型上下文，应在新项目及单独授权下提供明示依赖/通道；v1没有任意宿主目录或网络挂载。

模型默认关闭。未来真实通道需要**另行授权**，并同时传入 `--enable-real-model --model-max-requests N`（1..20）；不继承旧预算。本轮未运行该模式。原隔离环境、Node/Codex启动及infer均复用，不启用工具或Code Mode，模型/medium不变。上述预算是代码能力上限，不构成授权。

离线检查与测试：

```bash
"$PY" "$CODE/scripts/audit_research_platform.py" \
  --run "$EVIDENCE/online-reference-001" --output /tmp/platform-audit-new-01.json
PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest discover \
  -s "$CODE/tests" -p test_platform_v1.py -v
```

## 平台界限与剩余工作

- 参考单红方块任务已接通；不是通用对象、任意布局或任意机械臂平台。L2失接触和L3固定参考首段IK拒绝继续保留FAIL，详情见证据索引。
- owner仍使用共享颜色RGB依赖检查，遮挡造成unknown时会拒绝运动；不为研究需求默认放行。在线可以通过现有机械臂动作使腕部相机运动，没有新增相机传感器、外部遮挡生成器或研究视角策略。
- v1调用串行，最多1个在途infer和1个未来候选；无研究异步算法。owner在外部计算/模型等待时进行保持步进，执行中检查STOP；渲染/规划耗时不补帧，不承诺硬实时或物理时间等于墙钟时间。
- reset = 退出旧owner、全新output、重新启动进程。一个owner内重复reset拒绝；不声称精确状态克隆。默认seed2与原固定场景相同，seed不是布局。
- 兼容infer固定为原任务B接口、三路当前图与空历史；不实现新项目的记忆/选图/上下文策略。新项目也可直接产生合法chunk，执行仍统一由owner提交。
- 真实Astra在该新适配层未验收。本轮证明既有函数/CLI路径接通、隔离、严格解析、提交与新观测；不能推断服务端身份、effort或内部重试事实。
- 真机SDK、坐标绑定、夹爪反馈和运动中STOP未现场确认，继续UNKNOWN。复用[现场核验清单](../engineering/REALMAN_ONSITE.md)与配置模板，不启动任何设备。真实硬件安全闭环是后续现场阻断项。

协议见[PROTOCOL.md](PROTOCOL.md)，本次证据见[ACCEPTANCE.md](ACCEPTANCE.md)。
