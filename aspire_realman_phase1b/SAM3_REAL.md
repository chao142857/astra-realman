# 真实 SAM3 单图与原生 HTTP 实测

2026-10-20，延续`ff2cfab1`手工几何交付。实际使用官方SAM3源码`7f473cfd983d5eb43040ff608f66bff0d7bdcb53`、官方`facebook/sam3@3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt`，没有使用Mock、随机权重、替代模型或任务专家。

权重在yanglab新工作区`.cache/weights/sam3.pt`，3,450,062,241 bytes，SHA256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`。SHA下载后及最终验收各核对一次。首段代理传输在2,345,664,512 bytes处主动Ctrl+C，随后利用两次各1KB成功探测的官方CDN `us.aws.cdn.hf.co`直连续传剩余1,104,397,729 bytes；没有重复完整下载。旧`sam3_download_interrupted.json`的FAILED是人为切换路线时的原始记录，不是模型或自发传输失败。签名URL及令牌均未记录；下载令牌只经无回显TTY进入进程内存，未运行HF CLI login或写入凭据配置。本轮临时SSH转发已关闭，原有网络/SSH/代理保持原样。

## 输入、结果与语义

输入为Phase1A封存`live-final/last/rgb.png`：SHA `cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06`，640×480，color #174/depth #91，同帧aligned depth及K/尺度哈希检查通过；不是新的live采集。Prompt `banana`来自原图左侧可见目标，只是二维感知查询，没有交接策略。

`confidence_threshold=0.0`时每次返回200个原始Mask候选，**不表示200个目标**；其中仅1个通过显式0.5分数阈值。前三次最高分均0.921875，Box XYXY像素为`[81.2604,243.2361,261.3438,289.6923]`。最高分Mask 6,817像素，三次PNG SHA均`3cfb957f039dea3e293dde598220628702e0bb335e8f3d2b4f78cccfae89ee81`。其余前5候选分数约0.09131、0.05347、0.04736、0.04541，均未当作识别成功。

助手已检查原图叠加与放大图：最高分Mask覆盖可见香蕉主体及暗色右端；这是视觉合理性核验，不是独立人工精确真值或公制精度验收。原始模型报告仍保留`CANDIDATES_UNVERIFIED`/目标确认null，不篡改模型原始输出；独立验收记录`VISIBLE_BANANA_MASK_SANITY_PASS`，同时明确边界及空间精度未认证。原手工轮廓IoU≈0.91054仅作对照，手工轮廓本身不是精确真值。

## 实际耗时与显存

同一独立`.sam3-venv`，Python3.12、torch2.7.1+cu126、torchvision0.22.1、numpy1.26.4；153份官方源码/tokenizer哈希通过。RTX3060 12GiB，驱动535.230.02。未修改驱动、CUDA toolkit、dp/aloha或依赖。模型按原生服务使用的`enable_inst_interactivity=True`构建、BF16 autocast/eval、compile=False；加载后复用同一模型进行官方和原生调用，没有同时加载两份。

| 项目 | 实测 |
|---|---:|
| 模型构建/加载（权重SHA检查之后计时） | 5.529519 s |
| 官方第一次调用 | 0.982888 s |
| 官方第二次调用 | 0.375309 s |
| 官方第三次调用 | 0.374282 s |
| 官方peak allocated / reserved | 5,784,627,200 / 6,341,787,648 bytes（5.387 / 5.906 GiB） |
| 原生HTTP三次端到端 | 0.569910 / 0.568496 / 0.562763 s |
| 原生peak allocated / reserved | 5,793,146,880 / 6,366,953,472 bytes（5.395 / 5.930 GiB） |

第一次为本进程模型的首次`set_image+set_text_prompt`，不是宣称主机/驱动所有缓存都冷。官方调用耗时在CUDA synchronize之间测量，包含图像与文本前向，不含落盘与CPU几何；HTTP时间还包含PNG编码、网络、返回解码等。每轮CPU输出保存后释放旧GPU image state，保留正常缓存；没有为美化reserved数字每轮强制empty_cache。原生源码自身的缓存处理保持原样。CUDA/Triton/扩展缓存均写入新工作区`.cache/sam3-runtime/`。

本路径没有OOM或CUDA/PTX错误，因此没有更换GPU或修改驱动的依据。该结论只覆盖当前单张640×480输入、官方内部预处理及文本分割路径；不证明视频、并发、多相机、大分辨率或cuRobo可用。ASPIRE的providers-sam3 extra另固定Torch2.9.1，本轮并未改装成该extra；实测是固定原生service/client与上述官方环境的HTTP集成。历史decord wheel标签的pip check问题保留，不宣称视频依赖全部通过。

## 原生 Provider 集成

复用未修改的ASPIRE `fa00f0e` SAM3 service和`Sam3Provider`，经真实TCP loopback HTTP发送同一RGB。已加载官方模型注入service运行时对象；不是执行原生CLI的自动下载路径。原生service SHA保持`2b92c1a964e197d40bb653ac8725086d64cbbcd155913ae17bb9b81def605920`，没有改Agent、Prompt或任务决策。

三次`POST /segment`均200/typed ok=true，原生限制最多返回前5候选；它们与官方前5候选逐项Mask IoU=1.0、分数差0.0。模型Mask数200与Provider返回数5是预期上限差别。客户端重新编码PNG文件SHA可能变化，但服务器三次实际解码RGB像素SHA均与原输入像素SHA `9d8a454410a13e082be01d16b480cdbfdee13e0e824615cc3853f51cef9d516c`一致。空Prompt仍为typed invalid_request且0个HTTP请求。HTTP进程与模型生命周期均在测试后释放；没有常驻新感知服务。

这里只构造相机自身光学系下的CameraObservation，自映射不代表已知相机→World外参。没有构造完整CAP Observation/伪RobotState，没有启用MCP三维localize/IK/Planner或改变readonly capability graph；原生MCP完整观测继续因缺真实状态明确不可用。

## 实际 Mask 的深度与几何

Mask与同一封存RGB-D关联：4,727/6,817像素具有finite Z>0（69.341%），Z P1/P50/P99为0.445/0.493/1.939m。233个有效点（4.929%）位于1.5–2.3m，主要在右端/边缘；原因仍需现场区分对齐边界、遮挡、返回错误及边界不确定性。没有补洞或删除远点制造合理尺寸。

全部有效点反投影到`realsense:346222072496:color_optical`，+X右/+Y下/+Z前，单位m；原生PCA OBB中心`[-0.200732,0.020826,1.192379]m`，extents`[1.518505,0.148945,0.114511]m`。远点把OBB显著拉长，它描述原始可见深度返回，**不是目标尺寸或可执行抓取位姿**。camera-frame geometry accuracy=false，World/TCP均null。中央ROI的1.957m背景和桌面3.20%有效率问题继续存在，详见`GEOMETRY.md`。

## 证据与复现

yanglab根目录`/home/tongji/alex/aspire_realman_phase1b_20261020/`：

- `evidence/sam3-real.json`及`.log`：完整原始三轮输出、全部200候选分数/Box、实际错误处理、输入hash、原生对照；完整报告SHA/字节数见Git数值摘要的`full_raw_report_reference`。
- `evidence/sam3-real/official-run3-mask-0.png`：真实最高分Mask；其余轮次与原生Mask也保留原位置。
- `evidence/sam3-real/official-run3-0-visible-cloud.ply`：71,083 bytes，SHA `015d57f8ab322b5a6790d7b77f201b3fa6101322e765b6cfa088688cfaa78a82`。
- `evidence/sam3-real-review/sam3-real-preview.jpg`：实际SAM3叠加/放大/有效深度及远点对照，142,245 bytes，SHA `616c6ebc8a619df8d6612a3ce89bc3184ee500b873a89bcd2a04f337228924b0`。
- `evidence/sam3-real-acceptance.json`：权重、原始RGB-D、V17/V19三份manifest各371源码、71份原生源码再次核验通过；原Phase1A入口未修改；当前用户可见video设备无占用，17897下载转发已释放；相机pipeline/SDK连接/动作数均0。

Git保留轻量`sam3_real_summary.json`与`sam3_real_acceptance.json`、下载/网络探测数值及必要源码，不上传权重、原始RGB-D、Mask/PLY、完整日志或派生图片。

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
bash aspire_realman_phase1b/tools/run_sealed_sam3.sh .cache/weights/sam3.pt evidence/sam3-recheck-new.json
```

输出名必须全新。完整Observation-only仍需三路缺失相机恢复、双臂真实只读状态与时间域、当前公共World/外参/TCP及深度质量独立验收；RM65名义模型和cuRobo接口准备见`RM65_MODEL.md`，现场清单见`ONSITE_CHECKLIST.md`。权重与本单图二维分割已不再是阻塞项。
