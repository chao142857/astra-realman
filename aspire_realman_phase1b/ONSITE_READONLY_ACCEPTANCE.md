# 真实只读验收准备：现场确认前不执行

基线`a2cc90d1`。本轮只修正metadata语义、验证离线行为、准备命令与记录。当前状态为**PREPARED_NOT_AUTHORIZED_NOT_RUN**，没有任何新的现场授权或真实验收结论；不连接机械臂，不开启相机，不运行任务模型。原始SAM3、几何及历史资产保持不变，不新增Harness/WorldHead/专家/几何模型。

## metadata合同

| 字段 | 精确定义 |
|---|---|
| query_ok | 已成功读取、返回一个经过验证的最后缓存样本；不等于本次SDK调用成功。无样本/查询异常时原生MCP isError=true，没有成功payload |
| ok | 兼容别名，严格等于query_ok；ok_semantics声明仅表示查询成功。外层MCP/job的ok同样不能证明实时 |
| live_current | LIVE_SDK_READ_ONLY来源、owner运行无故障、同host/boot域，SDK返回epoch年龄和整个接收区间年龄均通过现有门限。只表示主机侧当前，不表示控制器内部采样时刻已验证、机器人无错误或动作可用 |
| controller_measurement_freshness | 当前SDK没有控制器采样时间或独立延迟上界，因此固定UNVERIFIED；device_measurement_freshness_verified=false。不能由live_current=true升级成已验证 |

历史、过期、跨域、故障/关闭后的最后缓存可以返回query_ok=true，但live_current=false。保留owner_error、来源序号和原始时间；不把最后一次正常样本换时间冒充新读数。monitor仍stale，完整RobotState/Observation仍拒绝，所有运动硬拒绝。失败采样本身留SDK原始文件，诊断payload的sequence仍指向最后正常样本。若API已关闭或无缓存，则查询报错，不填空状态。

新增两个聚焦测试覆盖上述分类与实际localhost MCP往返；连同原有6项质量回归共8项通过，71份上游源码匹配。正向live_current分支使用明确的单元测试时钟/返回码注入，不是真实LIVE证据。首次HTTP测试受Mac沙箱端口绑定限制，复用现有解释器在允许localhost的执行权限下通过；不安装依赖、不允许非loopback连接或访问设备。

## 使用现有入口，不建立新验收框架

下述命令在yanglab现有隔离目录执行。先确认使用本轮已推送/同步的候选提交并记录git提交或源码SHA，而不是无提示运行旧版本。解释器继续用Phase1A .venv，不改dp/aloha/驱动环境。

**目前唯一可执行的预检**（纯文件校验，无SDK导入或连接）：

```bash
cd /home/tongji/alex/aspire_realman_phase1b_20261020
/home/tongji/alex/aspire_realman_phase1a_20261020/.venv/bin/python -B \
  aspire_realman_phase1a/tools/serve_readonly_state.py \
  --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE
```

复制`onsite_readonly_record.template.json`为新的会话记录，先填session、操作者、软件提交；确认字段保持null/false，直到**用户明确确认单臂供电、物理设备身份、控制器端点、没有其他SDK Owner和只读授权**。SSH可达、进程检查或模板本身不是授权。合作锁和/proc/net/tcp也不是跨主机/命名空间的唯一owner证明。

## 现场确认之后：一次有界读取与MCP核对

以下是**待执行模板，本轮不运行**。设置`SESSION`为现有隔离目录下尚不存在的新会话目录；`CONFIRMED_ARM/CONTROLLER_IPV4/CONTROLLER_PORT`必须来自用户确认，不能用历史IP猜测。准备新会话父目录、复制记录模板，不覆盖旧日志。`SDK_RUN=$SESSION/sdk`尚不存在。先填写设备身份和授权出处，确认参数只对该单臂和只读范围有效。

授权后准备新会话目录（SESSION须在既有隔离工作区内）：

```bash
: "${SESSION:?填写全新会话目录，不复用旧run}"
mkdir "$SESSION"
cp aspire_realman_phase1b/onsite_readonly_record.template.json "$SESSION/record.json"
SDK_RUN="$SESSION/sdk"
```

终端A在获得上述确认后运行30秒，不带任何motion/Home/reset参数：

```bash
set -o pipefail
/home/tongji/alex/aspire_realman_phase1a_20261020/.venv/bin/python -B \
  aspire_realman_phase1a/tools/serve_readonly_state.py \
  --aspire-source /home/tongji/alex/aspire_realman_phase1a_20261020/.cache/ASPIRE \
  --arm "$CONFIRMED_ARM" --robot-host "$CONTROLLER_IPV4" --robot-port "$CONTROLLER_PORT" \
  --output "$SDK_RUN" --seconds 30 --period 0.5 --connect-readonly \
  --onsite-power-confirmed --onsite-read-authorized --sole-sdk-owner-confirmed \
  2>&1 | tee "$SESSION/sdk-console.log"
```

保存完整stdout/stderr至会话父目录的sdk-console.log，不仅保留成功摘要。运行中终端B读取**这个run**的mcp-endpoint.json。下面的只读客户端只接入localhost，不调用Home、夹爪、观察任务模型或任意程序：

```bash
/home/tongji/alex/aspire_realman_phase1a_20261020/.venv/bin/python -B - "$SDK_RUN" <<'PY'
import asyncio,json,sys,math
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
run=Path(sys.argv[1]).resolve()
url=json.loads((run/'mcp-endpoint.json').read_text())['url']
assert urlparse(url).scheme=='http' and urlparse(url).hostname in ('127.0.0.1','::1')
async def check():
    async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
        async with streamable_http_client(url,http_client=client) as (r,w,_):
            async with ClientSession(r,w,read_timeout_seconds=timedelta(seconds=10)) as session:
                await session.initialize()
                tools=await session.list_tools()
                with (run/'onsite-mcp-tools.json').open('x') as f:json.dump(tools.model_dump(mode='json'),f,indent=2)
                assert 'cap_program_readonly_state' in [t.name for t in tools.tools]
                response=await session.call_tool('cap_program_readonly_state',{})
                with (run/'onsite-mcp-state.json').open('x') as f:json.dump(response.model_dump(mode='json'),f,indent=2)
                assert not response.isError, 'STOP: native MCP query failed; full response saved'
                value=response.structuredContent['job']['result']['result']
                assert value['query_ok'] and value['ok']==value['query_ok']
                assert value['source']['kind']=='LIVE_SDK_READ_ONLY' and value['live_current']
                assert value['controller_measurement_freshness']=='UNVERIFIED'
                packet=json.loads((run/f"sdk-sample-{value['source']['sequence']:06d}.json").read_text())
                raw=packet['sdk_sample']['canonical']
                assert packet['arm_scope']==value['source']['arm_scope']
                assert value['telemetry']['joint_positions_deg']==raw['joint_deg']
                assert len(value['telemetry']['joint_positions_rad'])==len(raw['joint_deg'])==6
                assert all(math.isclose(x,math.radians(y),abs_tol=1e-12) for x,y in zip(value['telemetry']['joint_positions_rad'],raw['joint_deg']))
                assert value['endpoint']['xyz_m']==raw['ee_pose']['xyz_m']
                assert value['endpoint']['rpy_rad']==raw['ee_pose']['rpy_rad']
                assert value['timestamps']['source_epoch_s']==raw['timestamp']
                assert value['timestamps']['read_interval_monotonic_s']==packet['read_interval_monotonic_s']
                assert value['timestamps']['host_clock_id']==packet['host_clock_id']
                assert raw['ee_pose']['units']=={'xyz':'m','rpy':'rad'}
                assert value['frames']['active_work']==raw['work_frame']
                assert value['frames']['active_tool']==raw['tool_frame']
                assert raw['system_error']['has_error'] is False
                assert not value['motion_permitted'] and not value['full_cap_observation_available']
                print('QUERY_AND_HOST_CURRENT_CHECK_PASSED; CONTROLLER_MEASUREMENT_FRESHNESS_UNVERIFIED')
asyncio.run(check())
PY
```

客户端任一断言失败：保存完整响应和原始样本，向终端A的**该进程**发正常Ctrl+C并报告；不填默认值、不换端点重试、不清除错误或自动复位。预期缺失的速度/夹爪和端点UNKNOWN只允许明确展示，不能作为完整Observation/抓取位姿。Work名为World不代表双臂World，Arm_Tip不代表实际抓取中心。

## 正常退出与故障记录

让有界run正常结束；核对report.json、latest.json和verified_reader/events。记录同进程connect的单臂/handle、delete/destroy返回码；latest的owner_running/live_current应为false。记录本进程SDK socket及localhost端口退出前后状态，核对其他用户/owner/SSH/系统服务未受影响。当前审阅reader的delete事件没有单独记录handle参数，需结合该进程connection_info、单臂connected映射和固定源码核对；无法独立证明的项目填写LIMITED/NOT_VERIFIED，不把“进程没了”当所有权完整证据。

连接故障检查使用另一个全新run，并且**故障方式也需现场另外确认**：记录操作者批准的断链方式及时间，不改共享网络、SSH、Tailscale、控制器配置或其他owner，不通过伪造/猜测IP发起探测，也不自动重启/复位。没有获批方式则记NOT_TESTED，不临时扩大操作范围。自然发生的连接错误可以保存作为实际故障证据，但须注明不可控条件。

验收点：失败SDK返回/异常及原始事件保留；无默认canonical、无自动重连；旧缓存若仍可查询，query_ok=true而live_current=false且owner_error明确；observe为stale。清理仍仅限本进程拥有的句柄。若厂商调用不返回或清理失败，保留最后start事件与等待情况、停止并报告；不使用广泛pkill、killall或kill -9。SDK真实超时行为不能由本轮离线测试证明。

## 另行授权的相机短采集与深度参考

按`RAW_CAPTURE_NEXT.md`的既有入口，在单独获得相机采集许可、确认唯一owner和实际serial后执行；机器人授权不自动等于相机授权。使用新目录保存真实align前RGB/Z16、align后深度、双方profiles/K/畸变、工厂外参/scale、帧号/设备时间域/host接收区间及所有原始失败数据。先填入实际已知尺寸/独立距离、目标/桌面/背景覆盖范围和预定判据，再采集；本轮不预填尺度、深度或精度门限。只检验真实几何，不追加学习模型或再次调同一封存帧。

每个阶段都把全部原始文件留现场：SDK所有start/result/exception、每次样本、latest、服务控制台、MCP原始响应、正常退出/故障证据、相机raw/aligned及参考记录；对完整文件列出路径、字节数和SHA256，不能以摘要替代原始证据。只读和深度结果分别标PASS/FAIL/BLOCKED/NOT_TESTED，并保留UNVERIFIED的测量时序项。没有两项现场验收证据前不讨论启用双臂World/TCP/cuRobo，更不启动运动阶段。
