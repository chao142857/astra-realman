# Parallel 真机反馈回归与桌面保护缺口（2026-10-17）

本次仅离线修复。模型请求、机器人动作均为0。旧实验及STOPPED记录未修改。

## 已部署

当前状态、最近执行回执、有界8步历史统一保留第一自由度 dof_state、dof_err、current、speed、position、sys_state、逐字段有效性及读取时间。历史缺字段/缺时间保持未知，不伪造。电流仅报告SDK原始单位，不当作接触力或驱动力矩。新增机械臂执行后、夹爪通道判断前的实测状态进入回执。

按用户确认设备语义，dof_state=3报告“力控到位停止”，与目标开度到位、抓取确认分别记录。实际安装的 `/home/tongji/aloha/RealMan_Control/Robotic_Arm/rm_ctypes_wrap.py:3143` 的 rm_udp_hand_state_t 文档也列出3为力控到位停止，但注明为厂商示例；rm_plus_state_info_t 本身没有同等枚举说明，因此未把所有其他厂商枚举扩展为确定事实。没有将状态3当成故障或已抓住物体。

入口暂停：HardwareConsole.start、run_parallel_arms（连接SDK/调用模型之前）、真实worker的execute均拒绝新自动回合。无CLI绕过选项。GUI进程未重启；已加载旧GUI代码启动子进程时，新runner仍会立即拒绝。保留只读状态/历史导出。撤销暂停须另行完成实机几何与保护审查，不应只删掉门禁。

## 原始步骤10–16离线核查

源：yanglab `astra_realman_harness/logs/parallel-arms-20261017T110346-98e72ce1`。未修改原记录。

|步|主要派发|开度变化|闭爪后状态|
|---|---|---|---|
|10|TCP下降15mm，无新夹爪指令|1000→1000|2|
|11|夹爪目标450|1000→449|2|
|12|夹爪目标300|449→436|3，dof_err=0，current=97|
|13|TCP上升20mm，无新夹爪指令|436→300|由3变2，current约98→16|
|14|夹爪目标800|299→799|2|
|15|TCP下降25mm，无新夹爪指令|799→799|2|
|16|夹爪目标300|799→507|3，dof_err=0，current=97|

D13输入z=.210893、开度436；运动前预检z=.210868、开度436、状态3、电流103。机械臂运动后的between-channels采样z=.231085、开度300、状态2、电流17。随后夹爪通道判定已在容差内，未发新闭合命令。故变化发生在机械臂通道内；与原300目标在阻挡变化后继续实现相容，但现有离散采样不能证明内部控制全过程或唯一接触原因。

已逐行检查7步×4路归档决策图像的有标签预览。D12/13低位夹指与香蕉/桌面接近，关键指垫接触面遮挡，不能从RGB确证撞桌或精确接触部位。D14输入（D13动作后）仍见香蕉在桌面，不能确认抓取。决策前图像不是动作中连续接触测量。未由图片估计毫米安全高度。

归档核查命令（只读输入，输出必须为新文件）：

```bash
cd /home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness
/home/tongji/miniconda3/envs/dp/bin/python -B scripts/replay_parallel_telemetry.py \
 logs/parallel-arms-20261017T110346-98e72ce1 /tmp/parallel-10-16-telemetry-audit-new.json
```

已运行输出 `/tmp/parallel-10-16-telemetry-audit.json` 保存各输入/回执/图片SHA、原提案、摘要和多时点状态；D13断言通过。原图留在原目录；小型预览 `/tmp/astra-10-16-preview.jpg` 仅用于视觉核查，未推送。

## 桌面碰撞保护：未完成，不可运行

真实parallel调用 rm_movej_p；check_exact_target明确是ENDPOINT_IK_ONLY，路径规划状态NOT_CHECKED_NO_INDEPENDENT_PLANNER。当前无经过验证的全路径桌面碰撞检查。SDK阻塞运动和夹爪持续位置目标还意味着“没有新夹爪命令”不能当作夹指几何不变化。

现存RM65/CTAG URDF是仿真参考，未证实与实装夹指/附件及其开度运动学一致。历史控制器World/Arm_Tip定义不等于真实指垫TCP校准。未找到可用于安全认证的桌面平面、边界及误差界与各自控制器World的绑定；现有相机标定也不等同于此绑定。没有猜偏移、照搬仿真、设置经验安全Z或把终点IK当碰撞检查。

因此本次补的是fail-closed暂停门禁，**不是完成了几何碰撞保护**。还需实装工具/夹指运动几何与frame来源、两臂坐标下的桌面几何和误差界，以及实际执行轨迹（含持续夹爪目标）扫掠检查/及时停止路径。缺少这些，不能安全恢复真机自动抓取，也不能离线判定D12/16到底接触了桌面。没有修改模型动作或自动插入恢复动作。

## 验证

Mac与yanglab各61项parallel离线测试通过。覆盖当前模型输入、历史/中间反馈字段不丢失、状态3与位置到位/抓取分离、缺失字段不置零、原量化容差和并行协议。真实worker旧执行单元测试仅在纯mock会话内模拟解除暂停；生产门禁独立测试保持拒绝。

yanglab实际runner启动检查在任何SDK/model连接前返回PARALLEL_AUTOMATION_PAUSED（预期非零退出）。未实际执行新的夹爪、关节或模型请求。后续需要实机几何证据后才能实现并验证真正碰撞保护。
