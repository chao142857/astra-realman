# Pilot 02 收束与公共 RGB-D 几何 B 离线原型

基线 `fe9eb3a`。本阶段新增真实 Astra 生成请求 **0**；不启动 bridge，不恢复、重置或修改任何历史 ledger。仅使用已完成的四个绕障／自主 yaw 场景；不重新渲染，不增加场景。

## Pilot 02 主结果

保留两个执行阶段，主结果为 **19 份协议有效输出、9 对完整配对**。原批次第 12 条维持 `NOT_SCORED`，只引用原事后附录，不进入以下成功率、耗时或 token 均值。

| 执行阶段 | 题型 | A 成功/有效 | C 成功/有效 | A/C 平均客户端秒 | A/C 平均 reported reasoning tokens |
|---|---|---:|---:|---:|---:|
| 原批次 | 放置 | 5/5 | 6/6 | 41.282 / 20.493 | 545.20 / 38.33 |
| 续测 | 受限绕障 | 2/2 | 2/2 | 54.152 / 21.351 | 706 / 43.5 |
| 续测 | 自主 yaw | 2/2 | 2/2 | 56.462 / 22.458 | 806 / 60 |

原批次 `953a8d18a01447599664db2170862d98` 保持 STOPPED，续测 `bc2fbd0b683f4190a81945d251372a42` 保持 BUDGET_EXHAUSTED。两阶段均为单 worker、180 秒客户端上限；客户端派发 12 + 8，不等同于可精确控制的上游生成次数。无效协议输出不计能力零分。逐条缓存、阶段及资源记录在 `pilot02_closeout/summary.json`。上述为有限样本描述，token 不是内部计算量、客户端耗时不是纯模型时间；旧 A/C 不作为未来重复样本。

## 感知边界与可观测性

使用原三视角 RGB、光学 z 深度、有效像素掩码和 A 条件公共标定。深度定义来自原采集代码的公开格式约定：SAPIEN Position 的负 z；反投影转换 OpenCV 右/下/前到 SAPIEN 前/左/上，再使用公共相机位姿变换。

`export_public.py` 只读取冻结 A context、RGB，以及原 npz 的 `depth_m`、`valid` 两个数组。原 npz 包含的 segmentation **没有加载或导出**。不读取 snapshot、capture 的 actor 信息、私有规格、witness 或评分答案。`public_rgbd/manifest.json` 逐文件记录 SHA。

估计器先独立复制到 `/tmp`，运行时只有白名单公共数据。`isolated_run.py` 的审计钩子拒绝仓库树的数据访问、其他 JSON/PNG/NPY/NPZ、网络和子进程；拒绝探针及实际公共读取列表归档。该边界用于约束可信脚本的数据访问，不宣称是抵御恶意代码的操作系统沙箱。

三视角中均能以 RGB 阈值识别红色目标和中性灰障碍候选，深度足够支持目标包围盒和主要顶面估计；每视角有效深度数、目标像素数、候选像素数均记录在 `diagnostic_public.json`。公共 RGB 预览可人工检查槽口、挡板和横杆。但侧面、底面和完整内部体积的可观测性不由这些计数保证。颜色规则只适用于本次受控渲染颜色，不代表通用视觉分割能力。

## 最小实现与冻结

无需训练、重建网络、GPU 或模拟器执行。复用 NumPy/SciPy/Pillow：RGB 颜色阈值 → 多视角深度反投影 → 红色目标 upright 最小面积包围盒 → 观测主高度平面去除 → 灰色顶面投影到观测拟合方向的 5 mm 网格 → 保留空隙的矩形分解和竖直挤出。

仅基于公共观测调整过顶面网格方向，以减少斜槽的轴对齐小盒数量；最终版本为 `public_rgbd_boxes.v1`。第一次读取 GT 的独立诊断之前，已生成 `inputs_B/freeze.json` 固定估计器 SHA、算法配置、geometry、context 和 RGB。GT 诊断后重新核验全部哈希，没有回写或据此调整 B。

复用现有 geometry schema，`source=RECONSTRUCTION`，障碍 ID 为匿名估计 ID。不扩展模型 context、不修改 instruction、task_policy、输出 schema、RGB 或评分；B 与冻结 A 只有 geometry 字段不同。公共任务体积仍在任务文本中，未伪造感知 regions。局限和来源放在版本化侧文件中，**当前模型 context 不包含逐盒置信度/缺失区域说明**，这是原型限制。

所有目标盒由观测估计；台面、未看到的底面和背面明确记为缺失。竖直挤出是显式建模假设，不是测得的完整三维实体，也没有 GT 补全。

## 独立诊断：B v1 的实际限制

独立 `diagnose.py` 在冻结之后读取 GT，只写 `independent_diagnostics/`。不会导入桥接器或派发器。诊断不修改 B、模型答案、历史评分或阈值。

| 场景 | 中心 L2 mm | 排序尺寸向量 L2 mm | 高度标量绝对误差 mm | 障碍体积 precision | recall | B 估计秒 | 准备及预览秒 |
|---|---:|---:|---:|---:|---:|---:|---:|
| b_open_minus | 0.456 | 1.999 | 0.611 | 0.4420 | 1.000 | 0.497 | 0.018 |
| b_open_plus | 0.456 | 1.999 | 0.611 | 0.4372 | 1.000 | 0.456 | 0.018 |
| c_slot_030 | 0.554 | 2.096 | 0.832 | 0.9760 | 1.000 | 0.623 | 0.015 |
| c_slot_120 | 0.554 | 2.096 | 0.832 | 0.9720 | 1.000 | 0.632 | 0.014 |

尺寸排序处理盒局部轴互换，另报角点集合 Hausdorff 误差（约 1.31–1.53 mm），不把排序尺寸误差当 yaw 误差。位置/尺寸向量误差与高度标量误差分别保留。

障碍 precision/recall 来自 **10 mm 采样占据体积**；分母包含任务相关非台面 GT 障碍，台面遗漏另列，逐障碍覆盖率已保存。它不是精确表面覆盖率、欧氏 clearance 或碰撞安全认证。100% sampled recall 不能证明 2 mm 间隙估计可靠。算法 5 mm 网格本身已粗于任务的 2 mm clearance。

绕障的主要失败是将悬空横杆挤出到底部平面，形成虚假墙体；这解释了约 44% 的 precision。两组 yaw 槽形较好地保留可见空隙，但仍有网格离散和未观测表面假设。**保留这个失败的 v1，不按诊断回填或修正。** 原图叠加预览展示估计盒；独立 GT 视图放在评测目录，绝不作为模型输入。

计时来自 Ubuntu-Robot 本次实际 `perf_counter` 测量（暖文件系统、单次离线观察）；估计含 RGB-D 加载，准备字段含 context/RGB 写入及预览。另保存 A/B/C 已有输入复制耗时，明确不含重建或推理。这些均不是未来完整端到端推理耗时。B context 大小约 10.4–16.9 KB，C 约 9.1–9.2 KB；字节数不是 token 数。

## 下一轮 A/B/C 清单（无授权、无派发器调用）

`future_abc_plan.json` 和其独立 SHA 固定：四场景 × A/B/C × 三次全新重复 = **36 次未来客户端派发**。使用循环 Latin 位置平衡，每场景各条件在三个位置各出现一次；不是随机设计，也不声称完全平衡前后条件效应。模型 gpt-6-astra/medium，单 worker、ephemeral、180/190 秒，无自动重试，原协议失败立即停止，几何零分保留。

每个样本记录公共观测加载、几何估计/读取、输入组装、请求 wall time、校验评分归档时间；B 每次重新运行冻结估计器并核验 geometry SHA，不将一次估计成本摊给全部重复。端到端从加载输入之前到评分归档之后计时。历史传感器采集时间单列；缓存数据回放不冒充实时采集。保留原始 reported usage/cache 字段，缺失为 null；主分析全部协议有效新样本，次分析排除任何 reported cache hit 的配对并单列缓存未知。不用改 prompt 的方法清缓存。

B 额外使用深度，A 没有深度，因此此设计比较实际 RGB 与 RGB-D 导出几何的效果，不能解释为仅改变表示的因果收益。C 的完整真值与 B 的可观测性差异也必须单列。

当前交付是 **离线原型 PASS，真实批次未就绪**：已有 4 份 schema 合法 B 输入，但已知横杆虚假占据与 mm 量化限制需在未来授权前明确接受，或另起版本改进并重新冻结；本轮不据 GT 修改 v1。现有冻结 Pilot02 dispatcher 不接受此 36 项计划，尚未新增 A/B/C dispatcher 适配；不可拿旧 next/wave 或 ledger 运行。当前真实预算始终为 0。

## 复现（ubuntu-robot，仅离线）

```bash
cd /home/alex/astra-realman_ws/spatial-b-offline-prototype-20261013
PY=/home/alex/astra/.venv/bin/python
MOD=experiments/spatial_input_eval_v0
LAB="$MOD/lab/b_prototype"
SCRATCH=$(mktemp -d /tmp/astra-b-offline.XXXXXX)
$PY "$LAB/export_public.py" --suite "$MOD/evidence/pilot02_preview_20261013/suite_v2" --output "$SCRATCH/public"
cp "$LAB/estimate.py" "$SCRATCH/estimate.py"
$PY "$LAB/isolated_run.py" --estimator "$SCRATCH/estimate.py" --public "$SCRATCH/public" --output "$SCRATCH/B" --deny-root /home/alex/astra-realman_ws
PYTHONPATH="$MOD" $PY "$LAB/diagnose.py" --suite "$MOD/evidence/pilot02_preview_20261013/suite_v2" --estimates "$SCRATCH/B" --output "$SCRATCH/diagnostics"
PYTHONPATH="$MOD" $PY "$LAB/preview.py" --inputs "$SCRATCH/B" --output "$SCRATCH/previews"
PYTHONPATH="$MOD" $PY -m unittest discover -s "$MOD/tests"
```

输出必须是新目录，脚本拒绝覆盖既有输出。122 项离线测试通过，包括相机坐标转换、旋转包围盒、保留槽口的矩形分解、含不可加载私有 segmentation 数组的白名单导出，以及原 Pilot01/Pilot02 测试。原生产 bridge、冻结源文件、历史输入/评分/ledger 均无修改。
