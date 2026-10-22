# Astra × RealMan

**一份关于真机操作、空间理解与具身系统集成的实验研究记录。**

[English](README.md) · [简体中文](README_CN.md) · [GitHub 仓库](https://github.com/chao142857/astra-realman)

> **项目状态：研究阶段归档（2026 年 10 月）。** 这条研究线的主动开发已结束。本仓库保留真机集成、实验分支、失败分析与可复核记录，**不代表已经实现稳定泛化的机器人操作系统**。分支整理可能仍在执行中；下文固定 commit 链接不依赖新分支是否已创建。

## 项目简介

Astra × RealMan 研究的是：当多模态决策后端进入真实机器人的操作闭环，系统会遇到哪些感知、规划与执行问题？项目将相机观测与机器人状态、结构化动作建议、宿主侧合法性检查、机械臂或仿真执行，以及动作后的反馈与验证连接起来。

2026 年 10 月，工作从 RealMan 真机 baseline 逐步扩展到 History、双臂调度、空间输入评测、RM65 仿真交接、一次真实双臂完整任务，以及独立的 ASPIRE 迁移尝试。

本仓库中的**集成实现和实验 harness 由 [@chao142857](https://github.com/chao142857) 开发**。Astra、ASPIRE、SAM3、cuRobo、RealMan 硬件及其 SDK 均为外部技术，不是本仓库自主开发的模型或硬件。

### 探索的核心问题

- **空间感知与 grounding**：给通用模型多视角 RGB、估计几何还是 Oracle 几何？如何表达不可见区域和不可靠的几何边界？
- **闭环决策与执行**：History、Action Chunk、持物状态、IK、碰撞检查、执行反馈应如何配合，且不把工程补救误记成模型能力？
- **仿真到真机**：当真实标定、夹爪接触、延迟与驱动接口加入后，哪些离线结论依然成立，哪些必须重新验证？

这些是相互关联、但没有最终收敛成一套已完整验收的统一系统的研究分支。

## 主要实验结果与边界

| 研究线 | 实际记录 | 不能据此宣称 |
| --- | --- | --- |
| **真机 V17** | 2026-10-18，RealMan 双臂现场完成**一次经操作者确认的香蕉抓取—交接—放置**。保留记录为 `MODEL_DONE`、**33 次客户端请求**、总墙钟 **1,176.3 秒**。 | 没有独立物理自动评分或足够重复试验，**不能推出稳定成功率**。其后的 V19 未完成任务。 |
| **空间输入评测** | 研究 **A：多视角 RGB**、**B：估计几何**、**C：Oracle 几何**。在独立六场景 B-v2 几何测试中，合法路径保留数 **20/214 → 206/214**，但同时**错误接受 182 个非法 yaw 姿态**。 | 几何指标提升不等于 Astra 操作成功率提升；该 B-v2 验证的真实 Astra 请求数为 **0**。Oracle 不是真实可部署感知。 |
| **RM65 双臂仿真** | 完成接触/顺序执行接口验证、**D4 共 38 组**动作的物理回放，以及抓持/释放单项验证。 | 该研究线没有完成真实模型驱动的完整抓取—交接—放置；原 D1 在 **2.191 mm** 穿透时仍被保护停止。 |
| **Persistent World** | 建立 Geometry-First World、语义绑定、来源校验、Action Chunk 和动作后状态更新的实验链路。 | 10/11 的有限 A/B 中，普通 FULL_SYSTEM 失败、普通 VANILLA 通过，**没有证据证明整体收益**。 |
| **ASPIRE 感知** | 官方 SAM3 与原生 HTTP 在封存 RGB 图像上跑通；返回的前五个 Mask 与参考一致（**IoU = 1.0**）。 | 尚未获得合格的三维定位。受异常深度影响，原始 OBB 长轴达 **1.519 m**；World/TCP 未完成验收。 |
| **ASPIRE 离线规划** | 原生 CAP/MCP 接入 GPU 规划及 Stub 执行/反馈链路，在 **`ARM_ONLY_DIAGNOSTIC + SYNTHETIC`** 条件下通过。 | 不代表完整装配、真实驱动或真机任务通过；完整碰撞几何仍受阻，真实物理派发被硬拒绝。 |

**这里严格区分真机现场观察、真实模型请求、仿真物理回放、Oracle 输入以及合成/Stub 诊断。** 不同来源的 PASS 不可以互相替代。

## 仓库入口

下表是**精简完成后拟保留的五个分支入口**。右侧固定 SHA 为实际历史快照，在精简完成前后都可以直接阅读。`main` 保留 10 月 5 日的原始程序 baseline；顶层 README 改为项目导航，不把后续研究代码全部合并到 `main`。

| 分支入口 | 内容 | 固定快照 |
| --- | --- | --- |
| [`main`](https://github.com/chao142857/astra-realman/tree/main) | 最初 RealMan v0.1 baseline 与归档导航 | [`22bfb2e5`](https://github.com/chao142857/astra-realman/tree/22bfb2e549e6ca98b741ba84f254d4c1bbe66225) |
| [`realman/v17`](https://github.com/chao142857/astra-realman/tree/realman/v17) | 真机 GUI、V17 成功现场快照、V19 记录 | [`3d765ab9`](https://github.com/chao142857/astra-realman/tree/3d765ab9cd8a41fe226db1fd7ea507998752440b) |
| [`research/spatial`](https://github.com/chao142857/astra-realman/tree/research/spatial) | 空间 A/B/C、Pilot、估计几何与反例 | [`6484545b`](https://github.com/chao142857/astra-realman/tree/6484545bb3d760a0753cc33f10e6e4f35e0acb5a) |
| [`research/rm65`](https://github.com/chao142857/astra-realman/tree/research/rm65) | 双 RM65 仿真、接触诊断与 Action Chunk | [`c3330268`](https://github.com/chao142857/astra-realman/tree/c3330268e6288ebde1ea232c56fd29f00c80032b) |
| [`develop/aspire`](https://github.com/chao142857/astra-realman/tree/develop/aspire) | ASPIRE Phase 0–2B 迁移尝试；非真机完整系统 | [`c7597fc2`](https://github.com/chao142857/astra-realman/tree/c7597fc27c8744044741888a9e6fff6e60a891cf) |

原 75 个远端分支头拟用带命名空间的归档 tag 保留；只有完成**远端 tag 读回核验、独立完整 Git 备份与恢复验证**，才可以删除旧分支入口。Git 对象备份不等于实验主机原始视频、RGB-D 或未提交文件的备份。

## 时间线与证据入口

| 日期（2026） | 阶段 | 对应记录 |
| --- | --- | --- |
| 10/05—06 | 初始真机 baseline | [原始中文 README](https://github.com/chao142857/astra-realman/blob/22bfb2e549e6ca98b741ba84f254d4c1bbe66225/README_CN.md) |
| 10/07—09 | History、双臂、PnP 工程及脚本/Stub 验证 | [PnP 工程快照](https://github.com/chao142857/astra-realman/tree/d5757f232d0886b1736460d8d2b5218d79f855ac) |
| 10/09—11 | Persistent World 与 Action Chunk | [1011 交接及 A/B 边界](https://github.com/chao142857/astra-realman/blob/431f112c80f13a997a8ac1df81cbc3644c1d30ae/LAB_CODEX_HANDOFF_1011.md) |
| 10/12—14 | 空间输入 A/B/C、Pilot、B v2 | [Pilot02 续批](https://github.com/chao142857/astra-realman/blob/6484545bb3d760a0753cc33f10e6e4f35e0acb5a/experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01/CONTINUATION_REPORT.md) · [B-v2 漏检反例](https://github.com/chao142857/astra-realman/blob/6484545bb3d760a0753cc33f10e6e4f35e0acb5a/experiments/spatial_input_eval_v0/evidence/b_v2_20261014/REPORT.md) |
| 10/14—17 | RM65 仿真与接触/执行工程 | [接触预检及顺序动作验收](https://github.com/chao142857/astra-realman/blob/c3330268e6288ebde1ea232c56fd29f00c80032b/experiments/rm65_handoff_v1/INTERFACE_REPAIR_YANGLAB_20261017.md) |
| 10/17—18 | 真机 GUI、V17/V19 | [V17 现场快照与证据索引](https://github.com/chao142857/astra-realman/blob/3d765ab9cd8a41fe226db1fd7ea507998752440b/astra_realman_harness/docs/V17_SUCCESS_SNAPSHOT_20261018.md) · [V17/V19 分别记账](https://github.com/chao142857/astra-realman/blob/3d765ab9cd8a41fe226db1fd7ea507998752440b/astra_realman_harness/docs/banana_v17_v19_light_20261018/README.md) |
| 10/19—21 | ASPIRE Phase 0–2B | [SAM3 与三维几何限制](https://github.com/chao142857/astra-realman/blob/c7597fc27c8744044741888a9e6fff6e60a891cf/aspire_realman_phase1b/README.md) · [Phase 2B GPU/Stub 与剩余阻塞](https://github.com/chao142857/astra-realman/blob/c7597fc27c8744044741888a9e6fff6e60a891cf/aspire_realman_phase2a/PHASE2B.md) |

## 复现与安全边界

- **先选定固定快照。** 各研究分支的条件不同；日期更晚不代表模型更强、工程已全部合并或覆盖此前的真机结果。
- **按对应实验报告判读。** 某项结果可能来自模型、物理引擎、脚本、启发式 Stub 或合成输入，不能混写为统一的 Astra 成功率。
- **Git 仓库不是完整实验数据备份。** 大量原始视频、RGB-D、轨迹、模型及部分哈希清单仍保留在实验工作站。V17 文档记录了外部归档路径与校验值，不表示这些原始文件已公开上传。
- **文档不构成真机运动授权。** 历史脚本与仿真配置不能直接视为硬件安全方案；实际设备、坐标系、TCP、相机外参、碰撞覆盖、监督与停止机制均需另行核验。

## 阶段总结

这个项目留下的不是一套已经稳定解决双臂操作的通用框架，而是**可检查的真机闭环工程、一次真实的完整交接成功、空间输入与接触机制中的反例，以及一条尚未完成的 ASPIRE 迁移路径**。

感知证据能否可靠落到 World、几何缺失会如何影响规划、模型决策和宿主执行之间如何明确责任、一次成功能否重复——这些问题没有被一次 Demo 消除。因此，这里同样保留失败、未完成的试验和判断边界。

**维护者／集成与实验：** [@chao142857](https://github.com/chao142857)  
**实验记录区间：** 2026-10-05 至 2026-10-21  
**阶段审查：** 2026-10-22
