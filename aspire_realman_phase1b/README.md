# ASPIRE → RealMan Phase 1B：远程感知与模型准备

基于`0fb748c172ddbd13b8e21937affb045d4d417bd7`，ASPIRE仍固定`fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`。本轮只修正真实照片脚本并分析封存RGB-D；LiveSource、native CAP/MCP、硬拒绝、历史Replay及封存资产不改。不启动相机、RealMan SDK、机械臂、任务Agent或规划器。

用户最新截图显示Hugging Face已授予模型访问权限，账号审批阻塞已解除。执行环境仍未收到获授权本地权重路径或现场CLI登录确认；先前查过已有工作区/模型缓存未发现候选，没有读取凭据、绕过HF gate或下载替代权重。**没有SAM3分割基线**：官方独立调用预检BLOCKED的实际原因是本地checkpoint不可用，Mask数为null（未调用，不是0）；原生HTTP Provider实际返回503/Model not initialized及typed `provider_unavailable`。原生进程health=true、账号获批与模型就绪明确分开。详见`evidence/weight_access_status.json`、`evidence/sam3_phase1b.json`。

按用户追加要求，已用手工轮廓在真实封存帧上完成Mask→可见点云→原生ASPIRE PCA OBB及光学坐标检查。手工Mask由助手根据放大RGB逐点圈定，未经独立人工复核，不是SAM3，也不是人工精确真值。数据揭示了明显的背景/边界深度污染：原始OBB长轴1.523m不能当目标尺寸。见[几何结果](GEOMETRY.md)。

现场找到可复用RM65单臂URDF、7份mesh、夹爪展开模型和历史cuRobo配置；已生成左右各自独立根的名义六轴候选模型，验证关节origin/axis/limit与源一致。没有用假双基座间距拼装完整双臂，也没有注册为可用规划器。见[模型与注册接口](RM65_MODEL.md)、[现场清单](ONSITE_CHECKLIST.md)。

## 实际结果

| 路径 | 结果 |
|---|---|
| 官方SAM3→真实照片 | 账号访问已获批，执行环境权重路径/下载登录仍待提供；未加载/未推理，耗时/模型峰值显存null |
| 原生SAM3 HTTP→同一封存图像 | native client发送真实PNG，解码像素hash与原图一致；POST /segment返回503，服务尚未解码图像/返回Mask |
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
  --prompt-evidence 'Visible yellow banana on left desk; manually inspected source RGB' \
  --native-http --aspire-source "$ASPIRE"
```

无权重时预期退出1/BLOCKED。收到获授权本地路径后添加`--checkpoint /absolute/path/sam3.pt`；SHA必须等于官方锁定值，`load_from_HF=False`，禁非loopback网络。脚本记录模型加载耗时、三次冷/热调用、实际Mask/Box/Score、峰值allocated/reserved、同帧Mask深度/点云/OBB和原生HTTP结果。**这些成功分支尚未有权重实测，不宣称已通过SAM3验收。**

## 结果语义修正

`--prompt`和`--prompt-evidence`必填，拒绝默认`object`。Prompt `banana`来自本帧左侧可见目标，仅为感知查询，没有交接/控制逻辑。模型完成调用与目标识别分开：0 Mask为`INFERENCE_COMPLETED_NO_TARGET`且识别成功=false；低分数/空Mask不算目标；有候选也只标`CANDIDATES_UNVERIFIED`，识别成功保持null、等待视觉复核。没有实际Mask时不生成Mask叠加图。模型未运行时mask_count=null，不假填0。

实际推理时完整保留三次耗时、raw count/scores/boxes；按原生Provider上限保存前5个实际Mask及SHA。第三次Mask执行几何链路。原生service/client不改源文件，复用同一个已加载模型，避免3060同时容纳两份；记录native客户端重新编码PNG的SHA及服务器实际解码像素SHA，再比较Mask IoU/Score。当前503发生在服务器解码前，`server_pixel_identity_verified=false`，没有冒称端到端推理成功。

本轮新增的是封存真实数据的诊断脚本和模型候选生成，不扩展任务Harness、不新增Mock测试数量。原始图像、Mask/PLY、完整图形和模型mesh留在yanglab；Git只保存必要源码、手工多边形JSON、小型配置与派生数值摘要。用于本轮检查的少量派生预览不进入Git。

最终有限离线验收见`evidence/final_acceptance.json`：实际手工点云/OBB与候选URDF哈希核对、空结果语义回归、最终原生503和输入像素一致性检查。零Mask回归不算模型推理。`evidence/preservation.json`核对三份V17/V19 manifest各371个源码、封存RGB-D和71份原生源码；没有修改原部署或旧Phase1A入口。缺少当前RobotState时本轮不重跑live MCP，不宣称新的完整Observation成功。
