# Research Structured Outputs repair v1

**OFFLINE_SCHEMA_READY**。基线 `81da808f9014e8dec9cb78e658defc092b757252`；独立分支 `codex/research-strict-schema-v1-20261009`。本轮真实 Astra、SAPIEN episode、硬件、训练及物理动作提交均为 **0**。没有申请或消费新的 E₀ 授权。

这里的 READY 只表示代码与离线合同验收通过。真实生产服务端接受、Astra 语义质量、W₀ 质量、真实 A 规划及 native subagent 并发均未验收。

## 失败原因与源码修复

已冻结的第二次失败是 `invalid_json_schema`：实际发送的 `properties.binding` 只有复杂 `const`，没有显式 `type`。这是本地生成器未遵循 provider 子集造成的服务端请求拒绝；不是 Astra 语义错误。未修改旧 raw、events、usage、schema 或评分。

完整逐路径清单在 [SCHEMA_ISSUES.json](SCHEMA_ISSUES.json)：包含基线生成器与实际失败请求的 **75 个问题节点**，每项记录原节点、原因、新 Schema 和字段路径。最终每个节点的检查记录见 [generated](generated) 中的 `*.audit.json`。主要类别：

| 原位置 | 问题 | 修复和保留的本地约束 |
|---|---|---|
| Broker `$.properties.binding` | 无类型的对象 const | 展开为 typed closed object；所有字段 required；运行时原值 const 和收到 raw 后的逐字段一致性检查仍有效 |
| binding 下 episode_id / request_id / execution_epoch / world_id / world_revision / observation_ids / evidence_ids | 原来仅隐含于整个 const | 明确 string/integer/null/array；E₀ world_id、world_revision 均只能为 null；数组的精确顺序和值继续本地检查 |
| `$.properties.evidence_refs.items` | enum 没有 type | string enum，值域仅限发送的附件及允许的 evidence；数组非空 |
| SemanticScene v2 version、kind、identity_status、visibility、predicate、status | const/enum 缺类型 | 生成器补类型；provider 使用 typed singleton enum；本地 scene schema、实例/关系引用、bbox 顺序和跨视角重复检查全部保留 |
| ActionChunkPlan version、profile_id、m、H、semantics、waypoint.type、boundary_after、task.stage、termination.kind | const/enum 缺类型 | typed generation schema；H=1/4/6/8、m=1；所有行为限制继续 `chunk_plan.validate` |
| Action request 的 H/world/epoch/source observation/origin/task/task_binding/read_versions/evidence_refs | 绑定时用 const 替换了原字段合同 | 本地保留原字段约束并叠加 const；provider 展开复合常量；绑定值在 dispatch 前也须满足原合同 |
| `read_versions.additionalProperties` | 动态任意键的对象不能作为严格输出 | 请求时冻结世界读集，展开完整键集、required 和 additionalProperties=false；未绑定模板禁止 dispatch；收到 raw 后再与冻结及当前世界版本比较 |
| origin_pose_world / preconditions / evidence_refs 的数组 const | 仅复杂 const 不适合直接发送 | provider 使用 typed items、枚举支持集和长度；精确数组值/顺序仍受 authoritative const 约束 |
| legacy research Action v1 `waypoints.items.oneOf` | provider 不支持 oneOf | generation 使用嵌套 anyOf；各分支 typed/closed；本地仍执行原 oneOf 排他性以及动作验证 |
| minLength/maxLength/uniqueItems/minProperties/maxProperties | 本轮保守 provider profile 不发送这些关键字 | 逐项记录为 local-only，完整原约束仍验证，非放宽接收合同 |
| 仅 Draft202012Validator.check_schema | 只证明 JSON Schema 合法 | 增加独立递归 provider 子集检查；发送前失败关闭；返回后 provider/local/role 三层均通过才发布证据 |

新增 `scripts/structured_outputs.py` 是唯一 provider 编译/检查入口，由 Broker、legacy payload/parser 和实际 bridge 共用，并由现有 infer sandbox 挂载。没有第二套 Broker、Supervisor 或模型框架。`contracts.schema_check` 仍仅承担 authoritative JSON Schema 结构检查，不能单独作为 provider 验收。

依据 [OpenAI 官方 Structured Outputs 规范](https://developers.openai.com/api/docs/guides/structured-outputs)，profile `astra.structured_outputs.v1` 要求 root object、所有对象 closed、properties/required 完整匹配、nullable 显式类型、typed enum/const/items，递归检查 anyOf 分支。拒绝 refs、任意动态对象、allOf/not/if/then/else/dependencies 等未实现约束投影；不做静默猜测。仅明确支持的 2020-12 `$schema` 注解会留在 local schema。

上限：5000 properties、10 层（本实现保守计入数组 items）、120000 字符的属性名/enum/const 总量、1000 enum 值，以及单个 >250 项 string enum 的 15000 字符限制。额外保留 **64 KiB** 本地 Schema 大小上限。所有 11 个正式输出都通过；不对任意外部 JSON Schema 承诺兼容。

## 信任边界与兼容性

- `binding` 是 Broker 生成的可信元数据。模型只回显给定值，不证明来源；返回 raw 后执行严格 JSON 解析（拒绝重复键/NaN）、provider schema、完整 local schema、binding、epoch/world、role 引用检查，再发布 evidence。
- `MODEL_RAW`、raw SHA256、wire hash 和原始计划来源仍由现有 runtime `source_stamp` 在收到 raw 后生成；模型伪造来源字段会被拒绝。
- Broker 的 `row.schema` 保持 authoritative 合同，另存 `provider_schema`。Supervisor 的唯一调整是读取 typed 字段中的 `const`；仍要求每个绑定字段具备 const 且严格相等。新增测试证明删掉 const 仍拒绝。H/K 分离、m=1、原 owner admission 和动作安全检查没有放宽。
- 所有 request/payload 增加 `authoritative_schema`，它供本地校验，**不加入模型 prompt**。bridge 发送 `schema`，并检查它与 authoritative 的编译结果一致。两份 Schema、profile、hash、转换原因均封存。
- legacy FullSlot B/E/A 的实际生成器、解析、infer/commit 回归通过；legacy 1–3 动作、gripper barrier、Owner、IK、碰撞、STOP、时间/位移阈值未改。冻结诊断工具区分 owner authoritative 和 provider 文件，并校验编译器源码 hash。旧 pre-repair payload/bundle 不能自动转为新的真实调用授权。
- WorldHead、RGB-D 估计器、integration 请求语义未改；fusion.py 仅改 semantic schema 的类型声明，`fuse` 及其后的几何代码逐字不变。
- 旧 S1 capture source pins 完全保留。因此在新分支执行旧采集入口应被 `CAPTURE_SOURCE_CHANGED` 拒绝。测试明确验证这个拒绝，而非重写 pins 让旧授权继续生效。

## 最终生产 Schema

[MANIFEST.json](generated/MANIFEST.json) 包含全部 11 份最终输出以及 provider/local hash。这些是正式 Broker envelope 和正式生成器产物，不是简化测试 schema。

| 输出 | provider SHA256 |
|---|---|
| [S1 E₀](generated/e0.provider.schema.json) | `97cd5139fc23280bb1ac0704f2e27b71acd93cc5f3e936de6253dc4f40c1cc70` |
| [ActionChunkPlan v2 H4](generated/action_h4.provider.schema.json) | `d4699f41e0a0bb2c9fa0bf85ddf6632c38efdbc3c8320406154da26c69bba7a7` |

E₀ 使用原 `rm65:0002` binding、三路原图、原 prompt/任务，world_id/world_revision=null、evidence_ids=[]。新 Schema 修复不改变 SemanticScene v2 的结果格式。A H4 使用明确标注的 **SYNTHETIC 世界和机器人状态**，不声称已有真实 W₀ 或规划。该世界、观测及其版本合同一并保存；未来真实 W₀ 的 IDs、读集和 epoch 不同，必须重新生成并审计 hash。

另有 H1/H6/H8、SemanticScene v2 local_reground、regions 兼容合同、research Action v1、legacy B/E/A 的完整 Schema。未绑定的 `ActionChunkPlan.authoritative.template.schema.json` 是本地模板，不允许直接作为 provider schema。

## 验证结果

- **197/197** 离线回归通过：[REGRESSION.log](REGRESSION.log)。覆盖 Broker 正反向解析、legacy infer/commit、Supervisor、Semantic 接口、冻结输入、STOP、epoch、gripper barrier、桥接、错误归档。测试使用 fake 执行器，不产生新物理 episode。
- **11 份输出、457 个 Schema 节点**递归扫描通过。逐路径记录在 generated 下 audit 文件中。
- 合同拒绝分支包括：缺失/错误 binding；null/string 错配；缺失/空/未发送 evidence_refs；额外字段；错误目标/关系/实例 ID；bbox 反向；H 与长度不符；读集改变或额外键；无合法边界的 stage_terminal；错误预测依赖；伪造 MODEL_RAW/raw hash；过期 epoch/world；重复 JSON 键、NaN、畸形 raw；不兼容嵌套 schema 在创建进程前拒绝。
- **7/7 实际 Codex 0.161.0 离线 exec 分支通过**：[CLI_RESULTS.json](CLI_RESULTS.json)。E₀、合成 A H4、local_reground 通过；畸形 raw、错误 binding、HTTP 503、流中断均按预期拒绝。每个分支只有 **1 次本地 POST**，无应用重试。
- [ACTUAL_CLI_REQUEST_AUDIT.json](ACTUAL_CLI_REQUEST_AUDIT.json) 保留实际收到的 Schema、每节点结果、有效 argv、prompt/payload/body hash、图片 hash、隔离网络接口/路由和输出来源。完整原始 body、CLI events、stderr、raw、parsed/失败记录、墙钟在 `/home/alex/astra-realman_ws/research-schema-offline-20261009/cli-accepted`。

离线启动链：现有 Broker 的准备路径 → 原 sandbox_command → 同一 infer_worker → 同一 bridge → 已验收启动器 → 固定 native CLI → 本地 TLS CONNECT endpoint。测试只在 bridge 子进程环境边界注入测试 CA/proxy；生产源码的路由配置、模型与 effort 未改。bwrap `--unshare-all`，只有 loopback，没有默认外部路由；不挂载 auth.json，不使用真实 token。测试端点**先检查真实收到的 Schema、strict=true、gpt-6-astra、medium、三路图片 hash 和完整原 prompt**，通过后才返回明确合成答案。

启动器 SHA256 `29235c85a8d99f3423cde184aa4653341a70a815bc0abb6a5ae78cea7539945b`；native CLI SHA256 `9a820c17865fa825d04db416818679a9d63bd72e50835c396f496e5684626c9c`。有效 provider `s1_openai_no_retry`，request_max_retries=0、stream_max_retries=0、unbounded_connection_retries=false；requires_openai_auth=true，未加 base_url 或切换账号。无凭据离线实际 URL 为 `api.openai.com/v1/responses`，这不验证生产 ChatGPT 账号的内部路由或服务端内部重试。

缺失 usage 的额外发现：Codex 0.161.0 对无 usage 的 response.completed 会产生全零 CLI usage 事件。现在完整保留 usage_events，缺失/默认全零记为 `usage=null`、`UNKNOWN_MISSING_OR_DEFAULT_ZERO`，不计作真实 0 token。所有七个分支都验证了这一点。

[冻结校验](FROZEN_VERIFICATION.json)：9 个旧目录共 **3,245 文件**，无增加/删除/改动；两次失败的原 DELIVERY_MANIFEST 也分别验证。G1 的 PARTIAL_PASS、61mm 失败，以及 DA3/SAM/VisualHull 失败均保持原样。开发中发现的失败日志、初版导出和测试端点记录另存证据目录，没有覆盖后标成通过。

## 仅离线重现命令

从本分支 `astra_realman_harness` 目录运行，`--output` 必须是不存在的新目录：

```bash
/home/alex/astra/.venv/bin/python -B scripts/verify_structured_outputs_offline.py \
  --frozen-attempt /home/alex/astra-realman_ws/semantic-s1-e0-authorized-02-20261009 \
  --launcher /home/alex/astra-realman_ws/semantic-s1-provider-fix-20261009/runtime_cli/bin/codex \
  --output /home/alex/astra-realman_ws/research-schema-offline-recheck
```

此入口硬性使用 fixture provenance、禁外网 namespace 和本地 endpoint，没有真实请求模式。依赖当前 `/home/alex/astra/.venv` 的 jsonschema 4.26.0、Pillow，以及系统 bwrap/openssl。worker 的同一 venv 挂载已通过实际 exec 检验。

新真实 E₀ 尚未授权：必须另建单次授权和 claim，重新封存本分支源码、最终 Schema、输入及启动器 hashes。不得复用已消费 attempt，不会由本次离线验收自动提交请求。
