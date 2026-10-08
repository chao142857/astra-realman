# 阶段1–3离线验收（2026-10-08）

运行源码冻结为 `3182e95c3266187300e7db3c3d437df7698f125b`；基于 `2db1e3f`，只新增文件，原策略/物理/模型通道和历史版本不修改。最终三回合启动时 Git clean。验收文档是后续单独提交，不冒称已经随运行存在。

**本轮：真实模型0、硬件0、实验室连接0、Codex subagent0；没有继承旧9请求预算。** 全部B/F结果是延迟RGB启发式stub；script使用隔离GT答案。它们不证明Astra真实视觉决策、真实模型提速或研究性能。

## 最终共同物理验收与B/F轨迹

| 条件 | 完整物理/退出评分 | stub请求 | E调用/复用 | 任务墙钟 / 物理(s) | 初始化墙钟 / 物理(s) | 冷启动(s) | 生成/采用/丢弃 | 采用候选重叠(s) | XY误差(mm) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| script | PASS | 0 | 0/0 | 25.587 / 16.924 | 1.878 / 3.300 | — | 0/0/0 | 0.000 | 0.869 |
| B | PASS | 8 | 0/0 | 36.063 / 22.300 | 2.202 / 3.300 | 1.292 | 8/8/0 | 0.000 | 2.260 |
| F | PASS | 16 | 8/0 | 34.396 / 20.892 | 1.896 / 3.300 | 2.096 | 8/8/0 | 8.234 | 1.857 |

三回合均从空夹爪开始：起点指垫间距89.838mm、master≈−0.000120rad，初始化3.3s物理时间仅含场景settle和通用空手准备。`setup_held`调用0。每回合7 chunks、10底层动作：接近三段 → 闭合 → 抬升+1.2s保持 → 运输 → 下降 → 打开 → 退出；另有结束判断和独立300步稳定评分。原语坐标及顺序原样见各summary的sequence与owner_commit文件。

| 条件 | 最高抬升(mm) | 闭夹爪≥50mm最长连续步数 | 退出pad-center净距(mm) | sequence SHA256 |
|---|---:|---:|---:|---|
| script | 92.885 | 1171 | 73.101 | `6998e67052393d33cf315a07306400960bac79d3bdc87f771fab3bfb362a5d08` |
| B | 93.934 | 1483 | 72.627 | `c8de4718afac15bb8369911142d0a583a7736bbbf44d96630785d3a48ecf2329` |
| F | 92.427 | 1168 | 72.468 | `bf2aa8127f8fd8d31984b45ec83337b97ee0a1a4e2c1473ac5240487ff8c3198` |

共同接口hash `bad13484c23949b6b09047c7a38d30dbf1f14a2169dc0cdec760fe3ec817fb8c`；共同资产manifest hash `a29893c77963942516137eac9f9e5e3690026e374807dc9852220fddca861a43`。资产文件加载时逐个核验；未改变速度、物理参数、接触预载、控制器、相机安装或视频设置。物理结果由独立GT评分给出；`model_verdict=done`来自脚本/stub，不是Astra判断。旧score中的model_action_decisions是owner分派次数，不能当API次数。

## 时间与成本

最终F比B墙钟少1.666s（约4.62%），但这是单对延迟stub、独立物理回合；不作真实提速或性能结论。F的16次stub请求/输入字节均高于B。F所选腕相机在连续运动后姿态变化，5次复用检查明确失效，另有初始/抓取后/释放后3次强制E；因此E8、复用0。没有为降低调用数放宽新证据屏障。另附4个合成状态fixture覆盖合法复用、相机变化、对象不可见、目标变化；不算物理样本。

| 条件 | 各请求延迟(s，包含进程/轮询) | 接续等待(s，排除首次冷启动) | 捕获/相机帧 | 附件数/PNG字节 | context UTF8字节 |
|---|---|---|---:|---:|---:|
| B | B:1.074, B:0.980, B:1.071, B:0.972, B:0.963, B:1.065, B:0.959, B:1.152 | 1.326, 1.320, 1.243, 1.285, 1.408, 1.241, 1.468（合计9.292） | 16/48 | 31/929508 | 125849 |
| F | E:0.934, A:0.954, E:0.934, A:0.952, E:0.926, A:1.051, E:0.936, A:0.985, E:0.931, A:0.948, E:0.931, A:0.972, E:0.961, A:0.952, E:0.936, A:0.948 | 0.240, 2.289, 0.178, 0.212, 0.224, 2.200, 0.236（合计5.578） | 21/63 | 60/1099142 | 262659 |

B捕获1.266s、请求准备0.414s、等待保持1363步；F捕获1.692s、请求准备0.528s、等待保持1011步。准备包括裁图/编码/冻结文件；当前未进一步拆开各CPU子项，不能重复加到总墙钟。B/F显式重提0、请求取消0、晚到0、执行错误0。未知input/cached/output等token字段保持null，不记0、不从PNG或UTF8字节推算tokens；stub raw usage=null，无计价金额。

8.234s重叠只累计最终被采用候选所依赖E/A的实际worker计算窗口与父计划EXEC/GRIPPER窗口交集；排除进程启动和批准hold。F的5个采用候选各约1.645–1.649s；闭合/打开后等待约2.289/2.200s保留。B/F均每步至少原dt=4ms、不追赶；实测最小步间隔4.428/4.435ms。初始化、冷启动、物理时间和墙钟分别记录。

时间轴：[B PNG](/home/alex/astra-realman_ws/astra-full-pnp-offline-evidence-20261008/B-final/timeline.png) / [F PNG](/home/alex/astra-realman_ws/astra-full-pnp-offline-evidence-20261008/F-final/timeline.png)；同目录有SVG和逐事件`episode/timeline.jsonl`，请求实际command、环境、wire、schema、raw均在`episode/workers/request-NNN/`。

## 最终wire和隔离检查

71项回归PASS（原输入契约/CLI环境/调用预算/STOP/模拟隔离/异步50项，新完整任务21项）；三回合wire审计PASS，B8+F16共24份最终请求。逐份对实际input_payload、wire、PNG/base64、原始来源hash、裁图/缩放像素、来源step、history cutoff、E消息hash、严格输出schema做核对。所有请求最多4图，重建并发最大1；生成=采用+丢弃，最终没有未记账worker。禁止字段毒化测试覆盖对象GT、接触、评分、脚本答案及calibration私有键；不同像素输入生成不同stub目标，未将完整脚本答案放入B/F投影。

actual infer形状的离线payload与worker读取的wire一致，但**尚未发送真实infer**。源观测与commit新观测分列，预测保持PREDICTED；旧bbox、身份假设、当前可见对象状态、当前ROI分别保存。RGB方法/阈值/unknown条件同时写入wire和[实现说明](OFFLINE_IMPLEMENTATION.md)，没有用GT或图hash相等替代有效性。

bwrap真实隔离探针PASS：只读/input、只含worker.py/rgb.py的/code、无scene/score/script答案/auth挂载、独立network namespace、rm65_scene不可导入。Node/Codex预检无prompt：launcher `/home/alex/.nvm/versions/node/v22.23.2/bin/codex`；解析脚本 `.../lib/node_modules/@openai/codex/bin/codex.js`；实际node `/home/alex/.nvm/versions/node/v22.23.2/bin/node`，v22.23.2；Codex0.161.0；exec --help通过。真实服务端身份/effort/内部重试均unknown。

## 失败/遮挡边界和保留记录

真实物理验收没有异常失败；全部6个开发/冻结回合仍保存。开发v1用dirty源码，不能与冻结版本合并对比，特别是F-v1尚未加入“所选相机变化使E缓存失效”的收紧，E3/A8与复用5不是最终策略成本。

| 保留目录 | 类型 | 状态 | 墙钟(s) | stub调用 | E调用/复用 |
|---|---|---|---:|---:|---:|
| script-v1 | 开发记录，不合并 | PASS | 22.367 | 0 | 0/0 |
| B-v1 | 开发记录，不合并 | PASS | 33.099 | 8 | 0/0 |
| F-v1 | 开发记录，不合并 | PASS | 33.747 | 11 | 3/5 |
| script-final | 冻结验收 | PASS | 25.587 | 0 | 0/0 |
| B-final | 冻结验收 | PASS | 36.063 | 8 | 0/0 |
| F-final | 冻结验收 | PASS | 34.396 | 16 | 8/0 |

故障fixture（均明确标注非物理）：外部/模型STOP、父执行失败、目标revision变化、RGB目标移动/unknown/多目标歧义、重复提交/完成、晚到/超时、未收到证据引用、E hash错、E输出动作、第二worker拒绝、未来历史、夹爪屏障、无有效候选保持，全部PASS。这些预期拒绝保留在测试/fixture记录，不计为真实模型失败。未做故障注入后的额外SAPIEN成功补跑。

正常与局部操作遮挡的实际例子：F-final/scene/obs_0002/fixed.png物体清晰；obs_0007/fixed.png夹爪遮住物体部分侧面；wrist近景目标区域有不可见/裁切。逐帧RGB诊断中B的wrist目标unknown12/16，F为16/21；fixed和assembly可用。不能把视野外/裁切全部称为遮挡。红块在所有采集视角仍保留足够像素；严重/全视角遮挡导致保持并恢复的**真实物理轨迹尚未覆盖**，该路径目前只有合成图/状态fixture。

剩余缺口：真实Astra worker/infer生命周期接线尚未启用，该路径输入/取消/预算隔离还需离线核验（既有CLI版本/帮助预检已通过）；真实模型输出schema/视觉目标/结束判断未验证；ROI已附入A但stub仍用全幅细节图估计，未证明ROI或来源记忆带来收益；单个固定工程初始化不覆盖不同可达位置、严重遮挡、失抓/失落后的完整恢复；取消/分项编码开销只有现有账本，不等于API usage。不会将这些空缺记为PASS。

## 下一批新预算（仅建议，未授权/未执行）

**先1个B/F配对，共2回合；每回合最多20次attempt，总计最多40次；完整任务240s/回合，每请求≤min(30s,剩余时间)。** 同一gpt-6-astra/medium配置，全局1个在途、1个未来候选，最多2次新观测重提，完成chunk上限12；E/A/B、取消、失败、重提均占额度，不区分“顶层A”而隐藏E。

依据：冻结B需8次、F需16次；为F最多2次新观测E→A留4次余量，两条件用同一20次上限。真实延迟可能耗尽240s，不承诺成功，也不追加请求。首对保持当前固定配置/seed2，新进程记录起点，不叫状态克隆；不作为研究样本量或E1非劣预算。先补真实worker冻结输入/隔离/预算的离线接线检查，再请求该新额度；当前执行仍关闭。STOP、启动/API/解析/超时/执行协议异常不自动重试或补跑，不展开E2/E3/E4。没有旧预算余额转入；缺真实usage/价格时不虚构token或金额。

## 实际入口与证据

参见[运行与RGB规则](OFFLINE_IMPLEMENTATION.md)。实际完整命令在每回合result.json；运行入口 `astra_realman_harness/scripts/run_full_pnp_offline.py`，审计入口 `astra_realman_harness/scripts/audit_full_pnp_offline.py`。全部证据：[/home/alex/astra-realman_ws/astra-full-pnp-offline-evidence-20261008](/home/alex/astra-realman_ws/astra-full-pnp-offline-evidence-20261008)。共同物理评分、视频、原语票据、24份wire/raw、hash清单与失败fixture均保留。
