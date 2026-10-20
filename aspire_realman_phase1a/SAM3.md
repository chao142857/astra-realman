# 官方 SAM3 实际环境准备

官方源码固定 `facebookresearch/sam3@7f473cfd983d5eb43040ff608f66bff0d7bdcb53`；153份安装后的Python源码/tokenizer校验值在 `sam3.lock.json`。它与 ASPIRE `.gitmodules` 中的 `Max-Fu/sam3` fork 区分记录，没有把 fork 当作官方版本。

[官方安装说明](https://github.com/facebookresearch/sam3/tree/7f473cfd983d5eb43040ff608f66bff0d7bdcb53)列出的先决条件是Python≥3.12、PyTorch≥2.7、CUDA≥12.6；其pyproject声明Python≥3.8，但本轮按README使用3.12。官方numpy约束≥1.26,<2，因此SAM3另建`.sam3-venv`，与native MCP相机`.venv`的numpy2.3.5隔离，不降级原环境。

用户已明确授权大文件/运行依赖下载；未修改系统驱动、CUDA toolkit、dp/aloha或现有服务。独立环境使用官方 [PyTorch 2.7.1/torchvision0.22.1/cu126组合](https://pytorch.org/get-started/previous-versions/)。ASPIRE原生`providers-sam3` extra另外固定torch2.9.1/torchvision0.24.1；本轮是官方SAM3独立依赖预检，不宣称已经按该extra完整认证原生模型服务。native CAP/MCP客户端自身不依赖Torch。后续原生HTTP provider需用真实权重再做实测。

RTX3060物理显存12288MiB，驱动535.230.02；主机RAM约31GiB。不能仅因nvidia-smi显示CUDA12.2就断言cu126一定不可用，也不能据此宣称模型兼容。[NVIDIA CUDA12.x minor compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)对驱动/特性/PTX仍有限制。本轮单独记录官方导入与小型BF16 CUDA kernel检查，明确它不是SAM3推理，其显存/耗时不能替代模型性能。

官方权重：`facebook/sam3@3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt`，3,450,062,241 bytes，SHA256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`。HF仓库为manual gated，现场没有该权重缓存和HF凭证；官方resolve HEAD返回401。用户将另行准备已获授权的本地路径。没有尝试替代镜像、绕开gate、接受协议或读取/写入凭据。

`tools/sam3_real_photo.py` 使用新封存的真实640×480 RGB及SHA验证，实际尝试官方模块导入；本地checkpoint不存在就返回BLOCKED，模型耗时和峰值显存均null，不生成Mock mask或随机权重结果。只有文件存在、SHA匹配、官方源码一致、CUDA就绪，才会以`load_from_HF=False`构建官方模型、运行三次set_image+set_text_prompt并记录冷/热耗时与峰值allocated/reserved。解释器禁止非loopback网络连接，不会自动下载权重或联系机械臂。

最终实测：官方 image model / processor 导入成功，153份源码/tokenizer哈希一致；ASPIRE原生SAM3 service模块也能在该环境导入，但_MODEL/_PROCESSOR均未初始化。Torch 2.7.1+cu126、torchvision0.22.1+cu126、numpy1.26.4；RTX3060支持BF16，小型CUDA运算通过。真实照片SHA与640×480尺寸验证成功，最终唯一模型推理阻塞为本地checkpoint缺失，模型没有加载、mask没有返回、推理耗时与模型峰值显存均null。

`pip check`返回1：`decord 0.6.0 is not supported on this platform`。该公开wheel文件名允许py3安装，但内部WHEEL标签为`cp36-cp36m-manylinux2010_x86_64`；Python3.12实际导入成功。未篡改wheel标签让检查变绿，也未宣称视频解码/跟踪已通过。这是后续模型/视频部署兼容性事项，照片路径仍必须用真实权重做最终验证。基础CUDA成功同样不能保证模型中所有PTX/Triton算子兼容R535驱动。

当前安装与运行预检的最终结果见 `evidence/sam3_runtime_probe.json`、`evidence/sam3_real_photo.json` 和环境冻结清单。权重未提供时，没有可报告的真实SAM3模型推理速度或峰值显存。

已有现场目录最短复现，无相机/机械臂操作：

```bash
cd /home/tongji/alex/aspire_realman_phase1a_20261020
.sam3-venv/bin/python -B aspire_realman_phase1a/tools/sam3_runtime_probe.py
.sam3-venv/bin/python -B aspire_realman_phase1a/tools/sam3_real_photo.py \
  --image evidence/live-final/last/rgb.png \
  --image-sha256 cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06 \
  --output evidence/sam3-real-photo-recheck.json
```

第二条在没有权重时预期退出1/BLOCKED。收到已授权路径后添加 `--checkpoint /absolute/path/to/sam3.pt`；仍只对封存照片推理，不开启相机、不调用Agent任务或机械臂。真实推理之后才考虑把同一owner的snapshot交给ASPIRE原生SAM3 HTTP wire，并以同一图像hash关联二维mask。没有完整真实RobotState与当前几何证据时，不能开放native三维localize_object或宣称Observation闭环完成。
