# 离线验收记录（2026-10-07）

基线：39a043e4b29ec7e18b1c1f057ebce2aa59a831b2。

- 新增 `test_bimanual_foundation.py`：37/37 PASS，标准库即可运行。
- synthetic nominal：apple→plate，tennis_ball→box；两次 handoff/sort 事件成立。
- synthetic handoff-failure：拒绝 right-holding 证据后进入 RECOVER，不发送 left release；显式恢复证据 + 新 operation 后完成两物体。
- synthetic unknown-ack：未知回执不自动重发；独立 synthetic checkpoint 证据恢复后，新的决策继续并完成两物体。
- 三种场景全部 `real_model_calls=0`、`real_hardware_calls=0`，图片为显式 1px fixture；不是物理抓取成功记录。
- 归档测试逐文件核对 ZIP 与 manifest SHA256。所有 RAW_HARDWARE_COMMAND 标注 mock 来源；未发送命令不能复用上一条回执。

测试命令：

```bash
python3 -I -B tests/test_bimanual_foundation.py
./launch/bimanual_synthetic.sh --scenario all
```

## 保留旧基线的回归对照

使用 Mac bundled Python3.12 对旧基线和新分支均运行 `python3 -B -m unittest discover -s tests -p 'test_*.py'`：

- 原 39a043e：317 tests，1 failure + 61 errors。
- 新分支首次全套：352 tests（当时新增35项），**相同的1 failure + 61 errors**；按完整测试名称集合比较，新增失败为0。
- 后续补充2项新测试（image/evidence绑定、bool版本拒绝），新套件单独37项通过。

旧错误包含工作站绝对路径依赖（例如 RealMan driver）、沙箱禁止 localhost 端口绑定；旧 Codex backend 的返回码断言失败也在基线重现。未修改旧测试或旧控制器以掩盖失败。完整套件不能宣称全绿。

JSON schema 文件已生成；运行时严格 parser 在上述测试中验证。Mac 未安装 `jsonschema`，额外的第三方 validator 尝试未运行，未为此安装依赖。未来真实 backend 的 structured-output 兼容性仍需单独 shadow 验证。

未执行：真实模型、机器人读写、相机采集、运动/夹爪、外部 API、现场双臂路径验证。
