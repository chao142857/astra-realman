# ASPIRE → RealMan：Phase 0.5 Native CAP/MCP

本轮已经实现并测试原生接入，不再只是Phase0的JSON接口草案。基点 `f12e22b1`；ASPIRE固定 `fa00f0ef2bc1d91d594b9aa502c22133c9f538f7`，只在新隔离副本应用5行通用扩展。Mac与yanglab均已通过28/28项测试；原机历史Replay经MCP返回4路封存图像，所有运动调用被拒绝。

- [服务清理、相机复查与Phase0结论修正](ONSITE_STATUS.md)
- [Native Adapter/Codec/Runtime完成度、执行边界](NATIVE_INTEGRATION.md)
- [World/TCP、RM65双臂模型、cuRobo及真实只读闭环缺口](NEXT_STEPS.md)
- [验收结果及证据索引](VALIDATION.md)

## 已有工作区最短复现

Mac，新独立Python3.12环境：

```bash
cd /Users/tangchao/Desktop/资料/P7/aspire-realman-phase05-20261020
.venv/bin/python -B aspire_realman_phase05/tools/run_validation.py
```

测试会在127.0.0.1临时端口启动并关闭自己的MCP HTTP服务器；测试解释器拒绝非loopback连接，不导入RealMan/RealSense SDK，不调用模型或硬件。

新克隆的源码准备、依赖版本和受控补丁方式见 [NATIVE_INTEGRATION.md](NATIVE_INTEGRATION.md)。`.venv`、`.cache/ASPIRE`、模型和图像不进Git；精确依赖在 `requirements.lock`，71份上游CPU源码哈希在 `upstream.lock.json`。

手工查看纯合成MCP服务器（Ctrl+C结束，只绑定本机；不会启动Agent）：

```bash
.venv/bin/python -B aspire_realman_phase05/tools/serve_synthetic.py --port 18222
```

**本包没有真实执行transport或allow-motion选项。** 原生Home程序/运动工具的测试只验证它们在Mock适配器处失败，不会连接机械臂。未知双基座与TCP仍为null；历史Replay不冒充当前实时观测。
