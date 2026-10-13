# Mac bridge 隧道恢复记录

2026-10-13 09:48（Asia/Shanghai）：已恢复原 bridge 与反向隧道。
服务在后台运行，Mac bridge PID 为 73538，解释器为此前准备的独立 Python 3.11.16 环境。
本次没有 `/decide`、取消或 Astra 生成请求；下一次真实 A 仍需新的明确授权。

## 原因和处置

截图中先出现 SSH broken pipe，随后新启动均报 `remote port forwarding failed for listen port 18766`。
检查时 Mac 上已经没有 bridge、18767 监听或反向隧道客户端，但实验室 18766 仍监听。
实验室留下了 09:21:22 建立的 `sshd: tongji` 会话 PID 720771（父 PID 720716），
没有终端、没有子命令，与旧 `ssh -N` 转发一致。09:24 建立的交互会话 PID 722768 单独保留。

普通用户不能读取 sshd 的 root-only fd 表，因此先用进程结构识别旧转发会话。
执行前再次核对用户、父 PID、命令和没有子命令，再只对 720771 发 SIGTERM。
随后 18766 立即消失、交互会话仍在，确认该残留会话是占用来源。
未使用 sudo 密码，未重启 sshd 主服务，未批量终止 SSH 会话。

使用独立 venv 对本轮冻结 payload 再次完成纯离线预检，schema、三张 RGB 的 SHA、
本地输出 schema smoke 均通过，然后启动同一个原 bridge 文件，保留原参数与认证方式。
源文件 SHA256 仍为 `922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae`。

## 实际验收

- Mac `127.0.0.1:18767`：Python PID 73538 监听。
- 实验室 `127.0.0.1:18766`：反向转发监听。
- 从实验室发送一次 `GET /`，HTTP 501，Server 为 `BaseHTTP/0.6 Python/3.11.16`。
- 原 Handler 没有 GET 处理器，501 是预期结果；该请求不会进入 POST `/decide` 的生成逻辑。
- 原 bridge、认证文件、模型参数与硬件程序均未修改。
- 当前无自动重启或生成重试策略。监听通路通过不证明 Astra 生成可用。

`bridge ready` 在原脚本中早于反向转发结果确认，因此不能只凭这行输出判断隧道成功。
本次使用监听检查加非生成 GET 验证完整通路。

## 运行与记录位置

后台运行命令为原脚本加新解释器（已经执行，不需再启动第二份）：

```bash
/Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013/experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python -B \
  /Users/tangchao/Desktop/资料/P7/astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py \
  --mode lab --executable /opt/homebrew/bin/codex
```

实时日志：`/private/tmp/astra-spatial-mac-bridge-service-20261013.log`。
归档：`evidence/mac_bridge_tunnel_recovery_20261013/`，包含恢复前证据、启动命令/PID、
完整 payload 预检、GET/监听验收和启动日志快照。PID 是本次记录，不应当作以后可直接复用的终止目标。
后续如果再出现端口冲突，应重新核对占用会话，不能照抄旧 PID 或批量杀 SSH。
