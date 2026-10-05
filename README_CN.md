# Astra × RealMan

[![English](https://img.shields.io/badge/Language-English-2ea44f)](README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-blue)](README_CN.md)

用于在 RealMan 平台上运行 Astra 风格视觉-语言决策闭环的实验性真机操作系统。

> **状态：** v0.1 —— 首个公开真机 baseline 快照（2026-10-05）。  
> 本仓库仍在持续开发中，后续版本与实验会继续在这里迭代。

## 这个仓库是什么

这是我搭建的一套真机集成与实验栈，用于将多模态决策后端接入 RealMan 机械臂，生成结构化操作动作，并在执行后继续读取机器人状态与视觉观测，形成闭环。

仓库包含第一版真机 baseline 所使用的 RealMan 接入、相机与观测管线、决策后端适配、动作协议、执行与安全检查、遥测与验证、回放工具、测试以及实验运行脚本。

**本仓库中的集成实现与实验管线由 [@chao142857](https://github.com/chao142857) 开发。**  
Astra / 模型后端、RealMan 硬件以及 RealMan SDK 属于外部依赖；本仓库是围绕这些系统构建的独立研究集成与实验实现，并不声称实现了这些上游系统本身。

## 当前 baseline

当前快照记录了第一版用于 RealMan 真机操作实验的端到端 baseline。

核心组件包括：

- 多视角 RGB 观测与持久化相机会话；
- RealMan 机器人状态与坐标系接入；
- 显式 Cartesian 位移与夹爪指令的结构化动作 proposal；
- 可插拔决策后端，包括当前 Codex / Astra 实验路径；
- 坐标系、安全性、可行性与执行条件检查；
- supervised / step-wise 真机执行工具；
- 执行遥测、结果验证、回放与离线测试；
- 用于复现实验快照的文件清单与哈希记录。

简化后的数据流如下：

```text
多视角 RGB + 机器人状态
            ↓
        决策后端
            ↓
      结构化动作 proposal
            ↓
 坐标系 / 安全 / 可行性检查
            ↓
        机器人执行器
            ↓
    遥测 + 状态验证
            ↓
        下一次观测
```

## 仓库结构

```text
astra_realman_harness/
├── decision_backends.py        # 决策后端抽象 / 模型接入
├── codex_astra_backend.py      # 当前 Astra / Codex 后端路径
├── observation.py              # 观测构建
├── camera_session.py           # 多相机会话与采集
├── realman_state.py            # RealMan 状态接入
├── decision_protocol.py        # 结构化动作协议
├── decision_safety.py          # 安全 / 合法性检查
├── supervised_step.py          # 监督式单步执行
├── supervised_live.py          # 实时监督执行路径
├── execution_telemetry.py      # 执行遥测与日志
├── execution_verification.py   # 动作执行后验证
├── scripts/                    # 实验 / 回放脚本
├── config/                     # 实验配置
├── schema/                     # 动作 schema
├── docs/                       # 工程说明 / 证据记录
└── tests/                      # 离线测试

SNAPSHOT.md
SNAPSHOT_SHA256.json
```

## 说明

这是一个**实验性研究 harness**，并不是生产级机器人控制 SDK，也不是经过安全认证的控制系统。

代码中同时保留了较早的 shadow / dry-run 安全路径以及后续真机执行实验路径。归档快照里部分路径和配置与原实验工作站绑定，迁移到其他机器时需要适配。

第一版会作为 baseline 被保留下来。后续工作会继续围绕决策闭环、执行可靠性、推理延迟、放置精度以及更高层次的推理能力迭代，同时保留早期版本用于复现和对照。

## 后续开发

项目仍在持续推进中。后续 RealMan 真机实验与新的系统版本会继续更新到这个仓库。
