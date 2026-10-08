# B/E/A 真实 infer worker 接线

增量基于冻结 `99ac311`（实现 `4aa89a2`）。只接线与离线生命周期检查，保留旧设计、结果和覆盖表。真实请求、硬件、实验室连接均未授权/未执行；旧额度余额为零。没有新增角色、记忆策略、GUI、运动规则或 stub 物理验收。

## 接线与输入边界

`FullRuntime → FullSlot(infer_config) → bwrap → infer_worker.py → 原 codex_astra_mac_bridge.infer()`。原 bridge 文件未修改；Node/Codex 环境白名单、launcher 优先 PATH、medium、工具关闭、stdin JSON、图片/schema 参数保持原实现。没有另起 HTTP/SSH 服务。

owner 仍独占 scene/render/提交权。worker 只有冻结 wire、最终 payload、PNG；代码只挂载 stdlib wrapper 和原 bridge 的逐字节副本，不挂载 scene、评分、script、RGB 动作 stub 或仓库。真实模式额外挂载原 Node prefix、原 auth.json（原位只读，绝不复制进证据）、DNS/CA，并开放 CLI 所需网络。其余 HOME/工作区不可见。假进程模式不挂载认证、不共享网络。

每个 worker 对 wire/payload/PNG hash 再检查；最终 payload 与 infer 实际生成的 context/schema/附件再次离线核对。原图、选图、旧图和 ROI 规则不变。B/A 的动作、E 的 camera/bbox 完全取自各自 `record.raw`，调用既有严格解析器：不重写绑定、不修 JSON、不回退 RGB stub、不自动重试。E raw 的 packet/hash 才能进入 A。新候选仍经过现有 owner 状态/RGB检查及夹爪新证据屏障。

## 生命周期、取消与成本

所有角色共用同一 FullSlot/episode deadline。attempt 在准备前计数并写账本；PREPARING / PREPARED / LAUNCHING / STARTED / RETURNED / PARSING / PARSED / READY 与失败/取消/晚到分开。READY 仅表示可供 owner 检查，采用/丢弃/提交另在 timeline。实际 worker 启动数、进入 infer 的本地计数另列，不能将这些当服务端内部调用数。

`worker.json` 保存原 bridge record、原 raw/events/stderr/command、原 usage；`parsed.json` 只在严格解析成功时产生。`infer_output/bridge/<id>/` 保留 infer 原始文件。其 `/output/...` 是隔离进程中实际路径，对应宿主的该 request `infer_output/...`，不回写 command 伪装宿主路径。缺 usage 为 null；所有 usage event 原样列出，多个事件不擅自归并，也不将 cached/reasoning 子项再加到 input/output。

取消先写 worker 可见的取消标记，由既有 infer 终止/回收 CLI，最多给 4 秒落盘清理；超时强制终止 bwrap，独立 PID namespace 清理后代。清理时间计入实际墙钟，不增加新请求预算。迟到 raw 保留且不采用。基础设施/解析失败不启动后续角色；晚到/取消不生成可提交候选。

实际采用候选的重叠沿用现有算法，窗口现在是该依赖的本地 infer 开始到返回（包含 CLI 启动/请求准备，并非服务端纯计算时长）；接续点等待继续单列。初始化墙钟/物理时间与回合墙钟/物理时间分列。同步/异步使用原 owner 时间协议；同步渲染/规划段仍不是可抢占硬实时保证。

客户端请求仍是 `gpt-6-astra / medium`。服务端身份、effort、内部重试未有明确回执时为 `unknown`；原 events 可供后续核验，不能用客户端配置替代服务端事实。只读 auth 下的 API/认证刷新尚未经过真实请求验证，失败将完整保留且不重试。

## 一次性 B/F 入口（本轮未启用）

未来由用户另行显式启用后，唯一配对入口为 `scripts/run_full_pnp_pair.py`。无 `--enable-real-bf-pair` 在创建输出/预检/scene 前退出。入口固定 B 后 F，各新进程；共享 seed=2、相同固定场景、视频关闭，记录空手起点，不称精确状态克隆。每次新输出根；目录已存在即拒绝，不能恢复/补跑同一批。

| 限制 | 固定值 |
|---|---|
| 回合 | B × 1、F × 1；全新预算，不继承旧额度 |
| 回合总预算 | 各 300 秒；初始化独立记录 |
| 全角色 attempt | 各最多 20；两组最多 40，准备/启动/返回/解析失败都占本组额度 |
| 单请求 | ≤ min(30 秒，回合剩余预算)，owner 与 worker 共同截止；准备时间计入回合 |
| 在途 / 未来候选 | 各最多 1 |
| 动作 chunk | 沿用最多 12；第 12 个后仍可合法 observe/finish/stop；无第 13 个动作 |
| 重观测 | 沿用最多 2 次显式新观测重提，非 API 重试 |
| 外层看门狗 | 600 秒/进程，覆盖预检、初始化、300 秒回合与退出；不是额外任务时间 |

真实环境预检仍只 version/help，在物理场景创建前执行。合法 STOP/独立任务失败保留，可进入下一个预定组；接口、协议、执行、预算或审计完整性异常中止后续组，NOT_RUN 行仍保留。不追求 continue 或补跑成功。日志含全部角色、失败、取消、等待及观察，不做性能或泛化成功率结论。

未来准确命令（**不要在本轮执行**；output 已存在会退出）：

```bash
cd /home/alex/astra-realman_ws/astra-realman-full-pnp-infer-worker-20261008
/home/alex/astra/.venv/bin/python astra_realman_harness/scripts/run_full_pnp_pair.py \
  --enable-real-bf-pair \
  --assets /home/alex/astra-realman_ws/astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets \
  --output /home/alex/astra-realman_ws/full-pnp-real-bf-pair-01
```

输出 `ledger.json` 包含两组全部结果；每组有 result、wire_audit、timeline、attempt、原始 bridge/parsed 文件。最外层 source hashes 防止两组之间代码漂移；原 FullRuntime 的执行和独立评分复用不变。

## 离线核验边界

新增假 CLI 通过同一个隔离 worker 调用原 infer，检查 B raw 动作、E→A camera/bbox/hash、STOP、失败无 fallback/retry、冻结输入篡改、取消部分输出、顽固 CLI/后代清理、迟到、剩余时间、20/40 cap、显式启用门、预检失败不创建 scene、失败完整审计。使用 fake backend，不调用物理场景，也不代表真实视觉决策或真实模型提速。真实 API 及 B/F 完整闭环结果待另行授权，当前接线不作已验收声明。
