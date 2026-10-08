# Requirements 协议修复与 B 抓取只读诊断

基于 `9202ded` 独立增量。原 `full-pnp-qualification-bf-pair-01` 保持 **B=FAIL、F=NOT_RUN、真实调用3次**，不重新分类、不回写。此前30秒超时和90秒冻结诊断记录同样保留。本轮新增真实模型调用0、物理场景启动0、硬件调用0；未继承任何旧额度。

## 修复边界

`sim_skills/full_pnp/requirements.py` 是唯一可声明RGB谓词定义：

`scene_healthy`、`object_static`、`goal_static`、`object_near_tool`、`object_at_goal`。

输出schema枚举、模型wire中的 `model_requirements_contract` 及RGB说明、raw解析、CandidateGate、owner依赖入口和RGB检查器共用此定义。新说明单独标记 `model_rgb_requirements_v1`，由冻结wire/hash记录；动作接口v2与owner几何规则v1不变。

schema拒绝未知值、错误类型、缺字段或空数组；解析还要求 `scene_healthy`，`finish/done`还要求 `object_at_goal`。缺失/未知条件不会被补写、删除、改名、弱化或重试。成功解析的B/A动作和E选图/bbox仍原样来自各自raw；E结构不变，无RGB动作stub回退。

owner的 `bounded_upward_withdrawal` 是依据动作和实测状态计算的动作分类；RGB三角化、对象与工具相对位移等是owner自动检查。它们与模型可声明的五个RGB谓词属于不同命名空间。模型不能声明 `current_triangulated_object` 或 `object_tracks_tool` 来替代实测核验。模型只声明 `scene_healthy` 时，owner依然按动作补上原有最低依赖；未改变运动、开闭爪判定、夹爪边界新证据屏障或任何几何阈值。

仅为保持原离线RGB worker可导入，共享定义文件随原worker/rgb文件一并复制到其隔离目录。真实infer路径继续使用原环境与infer；没有新增服务、工具或fallback。runtime、pair、watchdog、模型/medium、图片投影、记忆、控制器、物理参数和独立评分源码未改。

## B-003 定向证据

原raw中的 `requirements` 为 `scene_healthy, current_triangulated_object, bounded_upward_withdrawal`。旧schema为任意字符串数组，因此旧解析READY之后，提交阶段RGB检查器抛出 `UNSUPPORTED_RGB_REQUIREMENT`。新schema只接受五个谓词，离线重放原raw会在 **PARSE_FAILED、READY之前** 拒绝；保留raw与attempt，不形成候选、不执行或重新调用。

测试夹具是原raw、原wire、原schema的逐字节副本，附来源路径和SHA256：`tests/fixtures/qualification_b003_requirements/`。raw SHA256：`a8eab8b33307a41a939a325b3ecad38f8d0764d6c13a38b50cf68ade5e45d881`。没有改binding或用新观测套用旧候选。原B-001/002 raw也只读通过新解析且内容相同，绝未执行。

本次7项新增定向测试全部通过，既有81项回归全部通过。覆盖共用词表、非法/缺失声明、finish规则、owner最低依赖、几何检查前拒绝、原B-003旧schema接受/新schema拒绝及失败计数无READY/重试。最初一次测试夹具误用无source属性的假config，修正夹具后7项通过；初次日志另存，未涉及模型/物理调用。

## 抓取分析与证据边界

研究者私有GT诊断、原RGB图版、逐步接触/状态统计、GT脚本比较图、精确测试命令及hash核验放在独立目录：

`/home/alex/astra-realman_ws/astra-requirements-grasp-evidence-20261008/`

入口为 `B001_GRASP_DIAGNOSIS.md`；数值来自原始 `private_scoring_trace.jsonl`、`phases.jsonl`、`events.jsonl`、动作与RGB，不只来自final_score。证据以VERIFIED/INFERRED/UNKNOWN分开。GT参照是历史 `script-final`（`3182e95`），物理配置和assets manifest相同，但版本/进程/等待时间不同，不是精确状态克隆或单因素因果实验。诊断不证明任何新动作会成功。

GT坐标、接触真值、参照动作计划仅用于研究者离线诊断；不导入策略，不增加worker挂载，不进入新wire/schema。协议说明中没有新增正确抓取/释放坐标、GT ROI或接触结果。

## 下一次真实入口（等待新的显式授权）

代码提供新一轮qualification入口；当前授权额度0。若用户另行批准，计划上限仍为B/F各1个全新回合、900秒/回合、单请求≤min(90秒，剩余时间)、20次attempt/回合，总计40次；全部角色及失败计数。12 chunk、2次重观测、1在途/1未来候选、1260秒watchdog和300秒内完成记录不变。不将原批次剩余次数转入新批次。

```bash
/home/alex/astra/.venv/bin/python \
  /home/alex/astra-realman_ws/astra-realman-full-pnp-requirements-20261008/astra_realman_harness/scripts/run_full_pnp_pair.py \
  --mode qualification \
  --enable-real-bf-pair \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --output /home/alex/astra-realman_ws/full-pnp-qualification-bf-requirements-01
```

本轮未执行该命令。输出目录必须不存在；每组新进程从空夹爪场景采集新RGB并请求，不载入诊断候选或GT脚本。合法STOP/任务失败和异常处理沿用原配对协议，不补跑到成功。新schema的真实服务端接受情况与真实任务成功仍待下一次授权运行核验；服务端身份/effort/内部重试无回执保持unknown。
