# Research adapters v1 — 基于 platform_v1 的薄接口增量

基线d7737dd；新增适配协议`astra.research.adapters.v1`，保留`astra.realman.platform.v1`和原infer/commit。旧仓库提供环境、动作和测量，新项目提供Semantic Agent、World Head模型、视角选择、历史、Selective Re-grounding及调度策略。本增量没有SAPIEN/SDK/控制器重实现。

[实际源码差异审查](SOURCE_REVIEW.md)在实现前完成；[接口与约束](CONTRACTS.md)；[验收与缺口](ACCEPTANCE.md)。工作树：`/home/alex/astra-realman_ws/astra-realman-research-adapters-v1-20261009`。分支：`codex/research-adapters-v1-20261009`。锁定交付提交，不复制模拟器和控制器。

## 可直接运行的离线验收

以下使用真实OS隔离进程、假Codex输出和明确的测试执行器。无SAPIEN实例、真实Astra、硬件或原生subagent。`private_score_status=FAIL`是测试执行器固定值，不是新的物理失败/成功结果。

```bash
CODE=/home/alex/astra-realman_ws/astra-realman-research-adapters-v1-20261009/astra_realman_harness
PY=/home/alex/astra/.venv/bin/python

# 全新输出目录：三角色图片/schema、公共几何、H8 -> 3+3+2 -> K8
"$PY" "$CODE/scripts/offline_research_adapters_demo.py" \
  --scenario h8 --output /tmp/research-adapters-h8-new-01

# 全新输出目录：执行期间E完成后启动A；结束后拒绝旧epoch计划
"$PY" "$CODE/scripts/offline_research_adapters_demo.py" \
  --scenario async_ea --output /tmp/research-adapters-async-new-01

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CODE:$CODE/tests" \
  "$PY" -m unittest test_research_adapters test_platform_v1 -v
```

`tests/research_fixtures.py`仅被上述离线入口和测试加载。在线入口不import它，模型失败后无测试执行器或RGB动作stub回退。

## 独立研究程序的真实接口

一个程序文件通过原runner挂入`/app`，导入固定版本`platform_client.Client`。模型进程在owner之外运行、读冻结输入。方法示意（具体可运行程序见examples）：

```python
p = Client()
o = p.reset()
cap = p.research_capabilities()
request = p.broker_submit({
    'backend': 'existing_codex_infer', 'role': 'semantic_e0',
    'instruction': 'Describe regions; bbox coordinates are normalized in the selected attachment.',
    'images': [{'observation_id': o['observation_id'], 'camera': 'fixed', 'roi': None}],
    'evidence_ids': [], 'world_id': None,
    'output_schema': cap['semantic_schema'], 'timeout_s': 30,
})
reply = p.broker_poll(request['request_id'])  # STARTED / READY / FAILED / CANCELLED
# READY不会执行动作。显式load仅装载，supervisor_step才尝试执行一段。
```

`research_adapter_client.py`演示三角色及H/K；`async_ea_transport_fixture.py`演示`begin('execute',...)`后继续Broker调用，最后`wait(execution_id)`收取配对结果。**这些是连接件示例，不是研究方法或推荐调用次数**。只读几何可调用`world_submit/poll/cancel`；任意图片/ROI选择与何时请求由外部程序决定。

未来在已有SAPIEN owner启用适配器的入口如下。本轮只交付命令，未运行新的物理回合：

```bash
"$PY" "$CODE/scripts/prepare_research_fake_cli.py" --output /tmp/research-dynamic-fake-cli-new-01
"$PY" "$CODE/scripts/run_research_platform.py" \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --output /tmp/research-adapters-sapien-new-01 \
  --program "$CODE/examples/research_platform/research_adapter_client.py" \
  --research-adapters --fake-cli /tmp/research-dynamic-fake-cli-new-01/bin/codex \
  --research-fake-attempts 3 --budget-s 120
```

原Baseline参考任务的既有命令见`docs/platform_v1/START_HERE.md`；不加`--research-adapters`即原默认模式。新增flag开启后，旧infer与Broker共享显式总attempt上限和一个模型在途槽，没有按角色重置时间。默认真实模型预算0。原真实开关及显式上限仍存在但本轮**不授权**；不能把fake次数当成真实额度。

原生Codex subagent是独立backend名称`native_codex_subagent`，当前仅实现能力/验收门，submit明确拒绝。没有把direct CLI、线程、coroutine或多个假进程叫原生父子调用。真实父子传输驱动、图片实际路由、usage和取消验收均是后续单独授权项。

## 非目标与当前阻断

泛化身份/目标关联没有等价验证器，Generic Task Evidence返回unknown并拒绝受此约束的动作；目前可执行的Supervisor profile仅原单红块/绿区声明范围及无对象断言的scene-only hold。世界几何是带不确定性的粗估计，不是抓取位姿、身份真值或碰撞安全证明。跨执行epoch产生的全新A计划不自动重绑；本轮能运行Async E/A传输，未实现预测接续点的通用跨epoch采用规则。

真机状态继续沿用`docs/engineering/REALMAN_ONSITE.md`的UNKNOWN清单，没有建连或修改SDK。原native父子调用、新适配层真实视觉能力、新研究方法和新物理性能均未验收。
