# B/F审阅修复验收

运行代码提交 `4aa89a2`，基于 `8e4f815`；保留 `3182e95`、`8e4f815` 及旧结果。三个物理检查进程启动时Git clean。本轮真实模型、硬件、实验室连接、Codex subagent均0，旧40次或其它额度均未继承。没有新真实预算建议或执行。

## 修复与定向回归

共同owner依赖与允许变化见[实现覆盖表](REVIEW_IMPLEMENTATION_COVERAGE.md)，同一契约同时进入wire。移动最低依赖不由模型requirements决定；夹爪区分有证据空手、跳过执行的容差no-op、可能释放和unknown。move+gripper仍合法，实际夹爪前以新RGB/本体状态重新检查；失败保留已执行prefix。第13个动作候选在采用前拒绝，执行入口也拒绝，第12个完成后observe/finish仍允许。

**88项回归PASS：原71项 + 本轮17项定向测试**。包括对象锚点移动、目标改变、随工具运动可通过/相对滑移拒绝、上撤允许变化、空手合理开爪、unknown/no-op/释放区分、退化视线unknown、move+gripper边界成功/失败、新状态采图、12/13边界、raw原样解析与失败无回退、八类失败审计。开发时旧“失败不入history”断言失败过1项；按本次保留部分执行要求更新后通过，说明保存在DEVELOPMENT_NOTES.md，不掩饰成无开发失败。

## 物理路径回归（均非真实模型）

| 检查 | 状态/独立评分 | stub请求/实际worker启动 | 完整chunk | 实际成功动作 | 墙钟/物理(s) |
|---|---|---:|---:|---:|---:|
| B-physical-check | PASS/PASS | 8/8 | 7 | 10 | 31.990/22.948 |
| F-physical-check | PASS/PASS | 16/16 | 7 | 10 | 30.834/21.440 |
| physical-boundary-fault | FAIL/FAIL | 0/0 | 0 | 2 | 3.659/2.704 |

B/F均7个完整chunk、10个动作，夹爪前两次新观测检查分别为close/release且valid；B额外总观测18次、F23次。B/F候选生成/采用/丢弃均8/8/0。F为E8+A8、E复用0。这里只核验修复后的共同执行路径，不比较提速、不扩大研究样本；stub仍不证明真实视觉决策。

物理故障样例使用当前RGB+公开平面计算工程脚本坐标，未读GT生成目标；不标成B/F模型动作。合法chunk含两段move_pose和末尾gripper。移动后明确注入预测接续z偏差+50mm；夹爪前真实采图并实测位置误差49.918mm，门拒绝。两个移动结果保留，unexecuted_count=1，PHYSICAL_GRIPPER_ENTER为0，grasp_attempts=0；独立FAIL和停止原因保留，不继续补跑。脚本、原语票据、视频、时间轴及fixture_checks.json完整保存。通用script分支的episode.source仍保守标为ENGINEERING_GT_SCRIPT；该故障fixture的顶层source/源码hash明确标注RGB脚本，源码只读RGB/标定生成动作。保留原始标签，不回写历史。

## 失败审计样例

每个attempt准备前即落盘；实际进程启动数另记。审计将episode_status=FAIL与audit_complete=true分开，不能把审计可读当任务成功。以下均为明确标注的假进程fixture，不计模型请求/物理结果：

| 样例 | attempt终态 | 已记录阶段 | raw usage |
|---|---|---|---|
| cancelled | CANCELLED | PREPARING → PREPARED → LAUNCHING → STARTED → CANCELLED | null |
| late | LATE_OR_CANCELLED | PREPARING → PREPARED → LAUNCHING → STARTED → RETURNED → PARSING → PARSED → LATE_OR_CANCELLED | null |
| launch_failure | FAILED | PREPARING → PREPARED → LAUNCHING → FAILED | null |
| missing_candidate | PARSE_FAILED | PREPARING → PREPARED → LAUNCHING → STARTED → RETURNED → PARSING → PARSE_FAILED | {"input_tokens": 42, "cached_input_tokens": 7} |
| nonzero_exit | PARSE_FAILED | PREPARING → PREPARED → LAUNCHING → STARTED → RETURNED → PARSING → PARSE_FAILED | {"input_tokens": 42, "cached_input_tokens": 7} |
| partial_raw | PARSE_FAILED | PREPARING → PREPARED → LAUNCHING → STARTED → RETURNED → PARSING → PARSE_FAILED | null |
| prepare_failure | FAILED | PREPARING → FAILED | null |
| timeout | CANCELLED | PREPARING → PREPARED → LAUNCHING → STARTED → CANCELLED | null |

全部8例都有wire_audit.json、阶段时刻/分段耗时、attempt原始文件清单/hash、stdout/stderr（启动前不存在输出时明确缺失），没有合法candidate也能完成报告。缺usage为null；两个注入usage的样例原样保留input_tokens=42和cached_input_tokens=7，**不加为49**。晚到合法raw保留原候选用于审计，但没有提交；取消/启动/API/解析失败无自动重试。

示例入口：[截断raw审计](/home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008/failure-audits/partial_raw/wire_audit.json)、[取消审计](/home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008/failure-audits/cancelled/wire_audit.json)、[物理部分执行失败](/home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008/physical-boundary-fault/result.json)、[夹爪未执行断言](/home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008/physical-boundary-fault/fixture_checks.json)。

## raw与真实infer待核验入口

`scripts/check_full_pnp_raw.py`只准备现有bridge的input/schema/command，复用现有环境函数，解析提供的bridge raw，不调用infer。B/A动作、E选图与bbox均从raw严格校验后原样返回，不产生修复动作、不回退RGB stub。没有raw时为WIRE_READY_NO_RAW_NO_PROPOSAL。保存的B/E/A stub raw被明确包装为离线bridge-shaped fixture验证，三者RAW_VALIDATED_NOT_EXECUTED；注入API错误后FAIL_NO_FALLBACK、candidate=null。均未声称Astra返回。

版本/help预检PASS：launcher `/home/alex/.nvm/versions/node/v22.23.2/bin/codex`，resolved script `/home/alex/.nvm/versions/node/v22.23.2/lib/node_modules/@openai/codex/bin/codex.js`，实际node `/home/alex/.nvm/versions/node/v22.23.2/bin/node` / v22.23.2，Codex0.161.0；白名单与工具关闭保持。预检没有发送prompt；真实服务端身份/effort/内部重试仍unknown。

```bash
/home/alex/astra/.venv/bin/python astra_realman_harness/scripts/check_full_pnp_raw.py \
  --input-only /home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008/B-physical-check/episode/workers/request-001/input_only \
  --output /tmp/full-pnp-raw-check-UNIQUE --preflight
```

若另有真实bridge返回文件，可加`--bridge-record PATH`做离线解析；这仍不会发请求或执行动作。真实worker端到端生命周期、取消/总预算/隔离及API回包验收尚未执行。

## 实际可用上限与覆盖边界

| 项目 | 当前离线实现 |
|---|---|
| 完整回合墙钟 | 默认120s，可配置(0,300]s；初始化/CLI预检单列 |
| 单worker请求等待 | 可配置(0,30]s，启动时≤剩余回合预算；准备时间也计回合总墙钟 |
| 所有角色attempt | 默认32，配置1–64；准备/启动/解析失败、取消同样占attempt；实际启动进程数另记 |
| chunk/动作 | 最多12个动作chunk，每chunk1–3动作，单hold≤2s；第12个之后observe/finish/stop仍受请求/时间上限 |
| 并发和重观测 | 单worker在途、单未来候选；最多2次显式新观测重提，无基础设施失败自动重试 |
| 真实请求授权 | 0；无旧额度余额，无自动真实入口 |

物理节奏仍最小4ms且无追赶，运动速度不改。时间守卫在owner/step边界检查，同步渲染/规划段不是硬实时可抢占保证；观察、准备、边界检查和评分均计成本。

记忆实际为最近5条已终结执行事件+F最近8条来源E假设；失败/部分执行不冒充成功，缺after为null。只有最后失败的保留投影，未实现错误解决状态机。未实现事件重要性优先、对象最后可见关键帧库、长期身份跟踪/语义检索/摘要遗忘优化；最近动作前fixed图不等于最后可见关键帧能力。不为凑四组件将这些标为完成。

全部新证据位于 `/home/alex/astra-realman_ws/astra-full-pnp-review-evidence-20261008`；旧目录和旧提交不变。
