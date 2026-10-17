# Astra × RealMan — 2026-10-17 研究归档索引

> **状态：研究主线暂停。** 本索引用于保全代码、定位实验、交接与复核，不代表已完成统一的最终发布、复现审计或后续科研性能验证。
>
> **Status: research paused.** This is a preservation and navigation index, not an assertion that every branch was merged, tested, or released.

## 仓库边界

- `main` 保留 2026-10-05 的首个公开真机集成 baseline；它**不是**后来所有仿真、真机与评测工作的合集。
- 后续工作分布于独立的实验分支。这些分支包含不同模型/策略、观测路径、物理场景和执行协议，**不应直接批量合并**为“最终最强版”。
- **仿真、启发式 stub、工程脚本、真实 Astra 推理及真实机械臂执行必须分别计账。** 某个工程验收 PASS 不等于模型成功率、跨场景泛化或真机任务成功。
- 原始现场录像、RGB-D、服务配置、部分封存输入及日志可能只存在于实验工作站或外部归档。Git 仓库内容本身不能证明这些外部文件仍可获取。
- 本次整理不运行模型、不操作机器人、不改旧实验轨迹或评分、不删除原有分支。

## 主要里程碑（按研究用途索引）

| 代码快照（固定提交） | Head SHA | 主题 | 已知证据边界 |
|---|---|---|---|
| [`main`](https://github.com/chao142857/astra-realman/tree/22bfb2e549e6ca98b741ba84f254d4c1bbe66225) | `22bfb2e549e6` | 2026-10-05 RealMan v0.1 baseline | First public robot integration snapshot; not the newest experiment |
| [`codex/history-diagnostics-20261007`](https://github.com/chao142857/astra-realman/tree/39a043e4b29ec7e18b1c1f057ebce2aa59a831b2) | `39a043e4b29e` | History / observation diagnostics | Offline harness and replay preparation; no new live Astra or robot execution in that acceptance |
| [`codex/full-pnp-bf-final-review-20261008`](https://github.com/chao142857/astra-realman/tree/99ac3117b47cd7b567c1887d6bbc637b14abd765) | `99ac3117b47c` | SAPIEN full PnP and B/F comparison | Complete scripted/heuristic-stub engineering episodes; results are not real-Astra policy performance |
| [`codex/research-platform-v1-20261009`](https://github.com/chao142857/astra-realman/tree/d7737ddca2b28ab10a6550b686521fd100e46a5a) | `d7737ddca2b2` | Research-ready simulation harness | Offline interface and limited SAPIEN engineering reference accepted; no live Astra or hardware in this acceptance |
| [`1011`](https://github.com/chao142857/astra-realman/tree/431f112c80f13a997a8ac1df81cbc3644c1d30ae) | `431f112c80f1` | Persistent World / chunk A/B handoff | 2026-10-11 frozen integration handoff; the recorded simulation A/B results were mixed, not an overall win |
| [`codex/spatial-pilot02-continuation-real-20261013`](https://github.com/chao142857/astra-realman/tree/fe9eb3abed858a4a6130cfcb4fdd19aeb24dbbb2) | `fe9eb3abed85` | Spatial-input pilot | Pilot and continuation artifacts; see branch records before drawing ability or improvement conclusions |
| [`codex/rm65-dual-handoff-v1-yanglab-20261014`](https://github.com/chao142857/astra-realman/tree/89f1d951f80353e636c9dc68be34c4242299b425) | `89f1d951f803` | Dual-RM65 shared-scene foundation | Simulation interface and handoff engineering; full autonomous handoff/placement was not established |
| [`codex/rm65-coordination-batch01-results-20261015`](https://github.com/chao142857/astra-realman/tree/5f7dcd3aedb132f3fc5600769e607dbdbf7803d0) | `5f7dcd3aedb1` | RM65 coordination batch | Task-specific evaluation artifacts; retain original scoring and failures |
| [`codex/rm65-full-task-first-real-20261016`](https://github.com/chao142857/astra-realman/tree/624d80fd249bd748569230f17a0d96bdcfd074c1) | `624d80fd249b` | RM65 full-task first live Astra batch | Recorded STOPPED after 4 of 16 permitted dispatches; no successful full handoff/placement |
| [`codex/rm65-contact-servo-yanglab-20261017`](https://github.com/chao142857/astra-realman/tree/c3330268e6288ebde1ea232c56fd29f00c80032b) | `c3330268e628` | RM65 contact/servo development | Later experimental engineering state; not certified as a successful full-task baseline |
| [`codex/realman-chunk-gui-migration-20261017`](https://github.com/chao142857/astra-realman/tree/d6fb17ceb156276fd5bc77a2798a35e234a0fe5b) | `d6fb17ceb156` | RealMan action-chunk GUI migration | Separate engineering line; do not infer integration with the RM65 branch |

以上仅是阅读入口，不是对其余分支的丢弃建议。全部 63 个原始远端分支的名称与 head SHA 记录在 [ARCHIVE_BRANCH_MANIFEST_20261017.tsv](ARCHIVE_BRANCH_MANIFEST_20261017.tsv)。

## 阅读与复核顺序

1. **了解最初真机接入：** 先读 `main` 的 README、`astra_realman_harness/` 与 `docs/`；它只代表初始版本。
2. **了解感知输入与 History：** 查阅 `history-diagnostics` 和 `spatial-pilot02` 的方案、输入构造、原始协议与评测证据；区分离线准备、真实调用和真实动作。
3. **了解仿真抓放和工程接口：** 从 `full-pnp-bf-final-review` 的 `astra_realman_harness/docs/full-pnp-bf/` 和 `research-platform-v1` 的 `docs/platform_v1/` 开始；不要将 stub 与真实模型混用。
4. **了解 Persistent World 实验：** 读取 `1011` 的 `LAB_CODEX_HANDOFF_1011.md` 和 `docs/lab_1011/HANDOFF.md`，保留失败、尚未运行的条件和外部证据缺口。
5. **了解后期 RM65：** 按 10 月 14—17 日的快照查看 `experiments/rm65_handoff_v1/` 及对应报告；区分场景/协议验收与完整任务完成。

## 分支整理原则（尚未执行删除）

目标是让分支页易于阅读，**同时保留每个原分支 head 的可恢复引用**。

1. 先核对所有电脑上的 worktree、`git status`、未 push 的提交和实验室外部原始数据，分别做备份；本 manifest **只覆盖 GitHub 已推送的 63 个分支**。
2. 使用 `git clone --mirror` 取得全部 Git refs，校验 manifest 并保存离线完整 `git bundle --all`；验证能够在另一个空仓库恢复。Git LFS、未跟踪文件、原始日志、外部软件/凭据需另外处理。
3. 对准备删除的**每一个**原远端分支 head 建立不可移动的 `archive/heads/<original-branch>` tag，并核对 GitHub 上 tag 指向本清单中的 SHA。只有离线备份与远端 tag **双重验证**通过，才讨论清理工作分支。
4. 审阅需长期保留的里程碑入口，保留 `main` 与必要的少量工作分支，其他分支进入**待人工确认的删除清单**。不要按日期、命名或“已合并”猜测可以安全删除。
5. 清理之后复核 GitHub PR/README/链接可用性，并保留 branch→SHA→tag 的映射及恢复步骤。

> **安全约束：** 目前没有删除任何原分支、没有改变任何旧提交、没有打 tags，也没有宣布完成了可恢复备份。删除操作必须由仓库所有者在验证后明确批准。

## 项目结论与后续使用

这一阶段的主要成果是可审计的机器人接入、观测—决策—执行闭环、仿真工程平台、状态/History 诊断和多轮失败记录。完整的真机双臂抓取—交接—放置任务**尚未形成已验证的稳定成功基线**。

代码保留作研究基础设施与历史对照，而不是把尚未证明的 Astra 能力包装为算法成果。如果未来重启，先重新定义可测量的研究问题、明确模型行为与宿主控制各自的责任，并以独立评测为依据。
