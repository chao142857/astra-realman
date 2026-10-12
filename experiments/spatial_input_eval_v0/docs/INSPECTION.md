# 阶段 1：实际检查与最小方案（2026-10-12）

当前 `/home/alex/astra_spatial_capability` 起初没有有效 Git 元数据；`.git` 是只读空占位目录。`/home/alex/astra-realman_ws` 是多个源码快照和证据目录的集合，不是单一仓库。

选用干净的 `/home/alex/astra-realman_ws/astra-realman-1011`，分支 `1011`，提交 `431f112c80f13a997a8ac1df81cbc3644c1d30ae`。只读检查后，在当前可写目录建立独立 bare 副本 `repository.git`，从该副本创建 `eval-v0` worktree，分支 `codex/spatial-input-eval-v0-20261012`。原项目 Git 元数据和工作树均不写入。远端 `origin/1011` 实测与基线 SHA 相同；远端任务分支在推送前不存在。

## 可复用内容

| 实际源码 / 数据 | 确认的内容 | V0 使用方式 |
|---|---|---|
| `astra_realman_harness/sim_skills/full_pnp/infer_process.py` | bwrap 隔离；只读挂载冻结输入、认证；不挂载 scene、GT 或控制器 | 直接调用原 `sandbox_command` / `isolated_preflight` |
| `sim_skills/full_pnp/infer_worker.py` | 校验输入/图像 SHA；调用 `bridge.infer`；保存原始结果、事件、用量 | 不修改，直接运行原 worker |
| `scripts/codex_astra_mac_bridge.py` | `gpt-6-astra`、medium、OpenAI provider、ephemeral；禁用工具；原始 JSON 及本地 schema 验证 | 完全复用 `infer()`，没有第二套 SDK/HTTP 客户端 |
| `scripts/structured_outputs.py` | 本地和 provider schema 编译/验证 | 复用编译器；三类输出契约均已编译通过 |
| `codex_astra_backend.py` / `config/decision_backend.json` | 旧 Mac loopback 桥；图像限原日志目录，需 token | 核查但不启新服务；选用已有 Ubuntu local infer 链 |
| `providers.py` / `config/lab.json` | 早期 proposal HTTP 接口；endpoint/model/key 配置为空 | 不使用，不臆造 endpoint |
| `scripts/prepare_s1_capture.py:worker` | 同一冻结物理步生成公共 RGB-D，封存后直接读取 actor pose 做独立评分真值 | 核实历史快照的同一步 GT 来源，不调用 owner 或执行接口 |
| `/home/alex/astra-realman_ws/semantic-s1-capture-20261009` | 三张 640×480 PNG、depth、标定、状态、PUBLIC_SEAL、3 个 5 cm cube 的私有物理位姿 | 实际导入 1 个历史快照，复制并校验原图和 depth SHA |
| `acve-p0-1011/research/action_conditioned_evidence/data` | 已存在观测索引、历史、图像、ROI 评分资料 | 仅检查接入线索；不将其推断 world/参考 ROI 当作几何 GT |
| `/home/alex/astra/ASTRA_LAB_2026-10-02/01_CODE/astra_controller/scripts/rm65_scene.py` | RM65 SAPIEN/PhysX 场景、物体/桌面/相机；不是 MuJoCo，也不是 RoboTwin wrapper | 源码审查确认坐标和 base translation；V0 不实例化场景或规划器 |
| `/home/alex/astra/vendor/RoboTwin/envs/_base_task.py` | 现有 RoboTwin 使用 SAPIEN renderer/scene | 检查了源码和 Git 状态，未运行新的 RoboTwin 场景 |
| 原 `tests/test_full_pnp_infer.py` | fake CLI / 沙箱 / 失败 / 取消回归测试 | 补充运行；当前 fixture net namespace 权限受限，结果另列 |

`/home/alex/astra` 含历史未跟踪归档和文档；未清理或修改。未发现需要复用的当前 Astra MuJoCo 导出链；没有把其他项目的 MuJoCo 训练环境改造成重复平台。日志图像有可读文件，但本次采用的样本已经由源码确认是仿真图像，不能称为真实照片。没有验证到可用于几何评分的真实照片标注集。

## 最小实现与边界

新增代码只在 `experiments/spatial_input_eval_v0/`。标准库实现数据验证、输入投影、mock、严格解析、OBB 几何评分、报告和 CLI。真实请求只增加对现有 sandbox/worker 的调用包装。系统 Python 3.14.7 可执行 mock 和测试；真实包装复用现有 `/home/alex/astra/.venv/bin/python`（3.10.12，jsonschema 4.26.0），无需安装依赖。

先闭合 A/C：相同 RGB、相同标定和状态、相同任务提示和输出 schema，C 只增加允许的几何箱体。B 仅加载 snapshot 中 `geometry.reconstruction`，不运行重建算法。公开数据集只提供显式未实现的适配器扩展点。

评测独立读取 GT；A 的模型沙箱看不到 GT，C 看不到 GT 字段、评分或参考答案，只能看到另行导出的几何。导入器读取公开观测、配置中的基座平移、直接测得的物体几何、封存信息和捕获绑定元数据，不读取旧任务放置答案、轨迹或成功率。新任务的允许空间是声明的几何约束，具有连续的多个合法解。

不运行真机、IK、训练或新动力学验证。路径为完整 OBB 在固定姿态下的分段直线平移，连续 SAT 检查，不能据此声称机械臂可执行。
