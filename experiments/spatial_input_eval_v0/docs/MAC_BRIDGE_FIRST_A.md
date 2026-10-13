# 首次获授权 S5 A：生成前依赖失败

后续状态：2026-10-13 09:48 已用独立环境恢复原 bridge，隧道验证通过，仍未再次生成。见 [隧道恢复记录](MAC_BRIDGE_TUNNEL_RECOVERY.md)。本文保留首次失败的历史记录。

用户明确授权“已恢复，授权一次”。在提交 `5f7e4fa` 的代码上执行了一个冻结样本：
`lab_s5_placement / plan / RGB_MULTI_VIEW`，gpt-6-astra / medium，qualification 90 秒，
预算 1。执行前确认 Mac 18767、实验室 18766 均监听，输出目录不存在，无运行中的评测进程。

## 实际结果

| 项目 | 结果 |
| --- | --- |
| HTTP | 200；认证与 SSH/HTTP 通路已打通 |
| request_id | `3c62b21146bd483d920a212d39031dc3` |
| 派发次数 | 1 |
| 重试 / C 条件 / 取消 | 0 / 0 / 0 |
| 耗时 | 0.053 秒 |
| bridge error | `ModuleNotFoundError:No module named 'jsonschema'` |
| raw / events / stderr | 均为空；无模型 JSON |
| return_code / usage | null / unknown |
| 解析 / 评分 | NO_MODEL_RESPONSE / NOT_SCORED，score null |

原始响应、输入、model parameters、HTTP body、评测报告和 launch log 均归档到
`evidence/authorized_mac_A_s5_first/` 及同名 `.launch.log`。`model_calls=1` 是保守派发预算，
不代表服务端成功生成；本轮无 worker 启动证据，失败已定位于启动 worker 前。

## 具体原因与证据

活动原 bridge PID 71211 使用 Xcode Python 3.9.6，运行原
`astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py`。
该脚本 SHA256 为 `922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae`，未修改。
其 `infer()` 首先调用 `validate_payload()` → `compile_schema()`，后者 import jsonschema；
此步骤发生在创建生成目录及 Popen Codex 之前。

使用同一系统 Python 对同一冻结 payload 的离线预检，复现了完全相同的缺包错误。
此前 version/help preflight 漏了 Python schema 编译依赖；新增的
`lab/mac_payload_preflight.py` 检查完整 provider/authoritative schema、三张 PNG 的 base64/SHA
及本地输出 schema smoke。它不读取认证、不发 HTTP、不执行 CLI，并禁止 Popen。

## 已完成的离线修复准备

建立独立环境 `experiments/spatial_input_eval_v0/.mac-bridge-venv/`（Python 3.11.16），
安装与实验室一致的六项锁定 schema 依赖，未修改系统 Python。完整 payload 预检通过，
jsonschema 4.26.0，三张 SHA 与首轮请求一致。venv 不入 Git，锁定依赖、安装日志、失败/成功预检记录入 Git。
新增回归测试覆盖完整负载成功和缺 jsonschema 时在 worker 前拒绝。
实验室完整离线回归实际通过 51/51，日志为 `unit_after_dependency_fix.log`。

原 bridge、原认证、模型参数、硬件程序均未修改；原服务未停止或重启，仍需切换解释器。
单次派发预算已用完，按“不自动重试”的要求没有再次发送 `/decide`。
Code Mode 和当前 Astra 生成可用性仍未验证。

## Mac 上的重启命令（本次未执行，无自动生成）

先在原 bridge 的终端按 Ctrl-C 正常停止原进程，然后用准备好的环境启动同一原脚本：

```bash
/Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013/experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python \
  /Users/tangchao/Desktop/资料/P7/astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py \
  --mode lab --executable /opt/homebrew/bin/codex
```

这保留原 ChatGPT 认证、原 token、原隧道与原 bridge 代码。恢复监听后仍需新的明确授权，
才能使用新的输出目录再次发一个 S5 A；不要复用已归档目录或自动开始 C。

## 离线复现命令

```bash
cd /Users/tangchao/Desktop/资料/P7/spatial-eval-mac-bridge-20261013
/opt/homebrew/bin/python3.11 -m venv experiments/spatial_input_eval_v0/.mac-bridge-venv
experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python -m pip --isolated install \
  --index-url https://pypi.org/simple \
  -r experiments/spatial_input_eval_v0/lab/requirements.mac-bridge.lock.txt
experiments/spatial_input_eval_v0/.mac-bridge-venv/bin/python \
  experiments/spatial_input_eval_v0/lab/mac_payload_preflight.py \
  --bridge-source /Users/tangchao/Desktop/资料/P7/astra-realman-onsite-1011/astra_realman_harness/scripts/codex_astra_mac_bridge.py \
  --payload experiments/spatial_input_eval_v0/evidence/authorized_mac_A_s5_first/sample-0000/bridge_request.json \
  --output experiments/spatial_input_eval_v0/evidence/mac_payload_preflight_reproduction
```

上面只编译/验证冻结负载和 smoke JSON，零 HTTP、零模型请求。每个输出目录必须为新目录。
