# ASPIRE → RealMan Phase 1B：远程感知与模型准备

**121631d9后的独立标准预处理诊断**见[GEOMETRY_DIAGNOSTICS.md](GEOMETRY_DIAGNOSTICS.md)：同一封存Mask/深度比较13个独立变体，保留全部78个候选和52次原生OBB失败；没有重跑SAM3、改写基准或选择最近/最大群当目标。非原始变体仅标记“ASPIRE + 标准预处理（诊断）”。[单臂只读owner准备](STATE_OWNER_PREPARATION.md)新增无硬件连接能力的接收缓存与边界检查，当前未接入live CAP，运动仍拒绝。

本分支在手工几何交付`ff2cfab1`上继续，初始基线为`0fb748c172ddbd13b8e21937affb045d4d417bd7`；ASPIRE仍固定`fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`。现已下载并校验官方权重，在封存RGB上完成真实SAM3及原生HTTP对照。LiveSource、native CAP/MCP、运动硬拒绝、历史Replay及封存资产不改。不启动相机、RealMan SDK、机械臂、任务Agent或规划器。

**最新真实结果**：用户授权下载后，官方checkpoint大小和SHA均匹配；RTX3060模型加载5.530s，三次调用0.983/0.375/0.374s，唯一通过0.5阈值的候选score=0.921875。原生HTTP三次200，前五Mask与官方结果IoU全部1.0，服务器解码RGB像素hash一致。视觉叠加检查确认最高分Mask覆盖可见香蕉；这是封存单图的二维分割证据，**不是合格的三维定位**。Mask内233个远点导致OBB长轴1.519m，World/TCP仍null。见[真实SAM3实测](SAM3_REAL.md)、`evidence/sam3_real_summary.json`和`evidence/sam3_real_acceptance.json`。

首轮缺权重预检的BLOCKED/503和当时的访问状态仍原样保存在`evidence/weight_access_status.json`、`evidence/sam3_phase1b.json`；它们是历史记录，不代表最新模型状态。账号获批、文件就绪、模型调用完成、目标分割和几何合格继续分别报告。用户显式提供的下载令牌仅经无回显TTY用于进程内HTTP认证，没有写入代码、报告、环境变量或CLI登录配置。

按用户追加要求，已用手工轮廓在真实封存帧上完成Mask→可见点云→原生ASPIRE PCA OBB及光学坐标检查。手工Mask由助手根据放大RGB逐点圈定，未经独立人工复核，不是SAM3，也不是人工精确真值。数据揭示了明显的背景/边界深度污染：原始OBB长轴1.523m不能当目标尺寸。见[几何结果](GEOMETRY.md)。

现场找到可复用RM65单臂URDF、7份mesh、夹爪展开模型和历史cuRobo配置；已生成左右各自独立根的名义六轴候选模型，验证关节origin/axis/limit与源一致。没有用假双基座间距拼装完整双臂，也没有注册为可用规划器。见[模型与注册接口](RM65_MODEL.md)、[现场清单](ONSITE_CHECKLIST.md)。

## 实际结果

| 路径 | 结果 |
|---|---|
| 官方SAM3→真实照片 | 三次真实调用通过；每次200个原始候选，1个通过0.5阈值；实际Mask/Box/Score已保存 |
| 原生SAM3 HTTP→同一封存图像 | 三次POST /segment均200，服务返回前5个候选；与官方Mask逐项IoU=1，输入像素身份已在服务器端核对 |
| SAM3 Mask→相机系点云/OBB | 6,817像素，4,727有效点（69.34%）；Z中位0.493m，233个远点；原始OBB长轴1.519m，不合格 |
| 手工Mask→相机系点云/OBB | 6,809像素，4,767有效点（70.01%）；Z中位0.491m；约211点在1.5–2.3m；原始PCA OBB受污染 |
| 中央ROI深度1.957m | 88.8%的有效点在1.5–2.3m，主要对应后方屏风；桌面选区有效率只有3.20% |
| RM65准备 | 两份独立名义单臂候选、12关节建议顺序；真实World/TCP和控制器绑定仍待验收 |
| 真机执行 | SDK连接0，动作0；缺少真实RobotState时完整CAP Observation继续不可用 |

## 最短复现（全部无运动、无新相机采集）

现场新目录：`/home/tongji/alex/aspire_realman_phase1b_20261020`。复用Phase1A已经隔离的`.sam3-venv`执行，不修改其依赖。全部原始数据只读来自`/home/tongji/alex/aspire_realman_phase1a_20261020/evidence/live-final/last/`。

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
PY=/home/tongji/alex/aspire_realman_phase1a_20261020/.sam3-venv/bin/python
ASPIRE=/home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE
SNAPSHOT=/home/tongji/alex/aspire_realman_phase1a_20261020/evidence/live-final/last/snapshot.json
$PY -B aspire_realman_phase1b/tools/manual_mask_geometry.py --snapshot "$SNAPSHOT" \
  --annotation aspire_realman_phase1b/manual_annotation.json \
  --aspire-source "$ASPIRE" --output evidence/manual-mask-recheck
```

输出目录必须全新；会产生真实手工Mask、71KB可见点云PLY、OBB数值及派生叠加/点云图。所有结果都标明`NOT_SAM3_BASELINE`、camera optical frame、World=null、accuracy未认证。

修正后的真实SAM3入口：

```bash
$PY -B aspire_realman_phase1a/tools/sam3_real_photo.py \
  --image /home/tongji/alex/aspire_realman_phase1a_20261020/evidence/live-final/last/rgb.png \
  --image-sha256 cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06 \
  --output evidence/sam3-recheck.json --prompt banana \
  --checkpoint .cache/weights/sam3.pt \
  --prompt-evidence 'Visible yellow banana on left desk; manually inspected source RGB' \
  --native-http --aspire-source "$ASPIRE"
```

SHA必须等于官方锁定值，`load_from_HF=False`，禁非loopback网络；缺失权重仍退出1/BLOCKED。上述路径已实测。更短的入口为`bash aspire_realman_phase1b/tools/run_sealed_sam3.sh .cache/weights/sam3.pt evidence/sam3-recheck-new.json`，把CUDA/Triton等缓存也限定在新工作区。每次须使用新的输出名。

## 结果语义修正

`--prompt`和`--prompt-evidence`必填，拒绝默认`object`。Prompt `banana`来自本帧左侧可见目标，仅为感知查询，没有交接/控制逻辑。模型完成调用与目标识别分开：0 Mask为`INFERENCE_COMPLETED_NO_TARGET`且识别成功=false；低分数/空Mask不算目标；有候选也只标`CANDIDATES_UNVERIFIED`，识别成功保持null、等待视觉复核。没有实际Mask时不生成Mask叠加图。模型未运行时mask_count=null，不假填0。

实际推理时完整保留三次耗时、raw count/scores/boxes；按原生Provider上限保存前5个实际Mask及SHA。第三次Mask执行几何链路。原生service/client不改源文件，复用同一个已加载模型，避免3060同时容纳两份；记录native客户端重新编码PNG的SHA及服务器实际解码像素SHA，再比较Mask IoU/Score。首轮缺权重503发生在服务器解码前；最新三次200已实际解码并通过`server_pixel_identity_verified=true`，两轮证据分别保留。

本轮新增的是封存真实数据的诊断脚本和模型候选生成，不扩展任务Harness、不新增Mock测试数量。原始图像、Mask/PLY、完整图形和模型mesh留在yanglab；Git只保存必要源码、手工多边形JSON、小型配置与派生数值摘要。用于本轮检查的少量派生预览不进入Git。

最终有限离线验收见`evidence/final_acceptance.json`：实际手工点云/OBB与候选URDF哈希核对、空结果语义回归、最终原生503和输入像素一致性检查。零Mask回归不算模型推理。`evidence/preservation.json`核对三份V17/V19 manifest各371个源码、封存RGB-D和71份原生源码；没有修改原部署或旧Phase1A入口。缺少当前RobotState时本轮不重跑live MCP，不宣称新的完整Observation成功。

以上有限验收属于前一次手工几何交付。最新`sam3_real_acceptance.json`记录真实模型与原生HTTP通过、权重二次SHA、原始RGB-D/部署/71份原生源码的再次封存核验，以及视频设备无当前用户可见占用、临时下载转发已释放。模型原始报告/Mask/点云保留yanglab，Git只保留必要数值摘要及其完整原报告SHA；派生预览不进Git。
