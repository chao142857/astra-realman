# 坐标系、变换与缺失标定

所有变换使用 `T_destination_source`、齐次列向量、平移米：`p_D = T_D_S @ p_S`。光学坐标为+x右、+y下、+z前。四元数使用WXYZ；SDK joint为deg、xyz为m、RPY为rad，矩阵 `Rz(yaw) @ Ry(pitch) @ Rx(roll)`。未知项保留null，不序列化一个单位阵来补齐。

“已验证”在这里指**已读取的历史控制器配置/文件事实**，不是2026-10-20硬件连接或外部精度认证。本轮没有新的机器人连接。

## 坐标系清单

| 坐标系 | 标识/定义 | 状态与证据 |
|---|---|---|
| 左基座 B_L | 左控制器(.19:8080)实体base | 历史身份用户确认、10/11读取RM65/6DOF/ISF/controller3；本轮仅审阅日志 |
| 右基座 B_R | 右控制器(.18:8080)实体base | 历史右腕/双臂日志身份；未完成本轮独立实测及与B_L的绑定 |
| 左Work W_L | `realman:left:work:World` | 历史相对左controller base零offset被读取；只是该臂的World |
| 右Work W_R | `realman:right:work:World` | 右腕包及V17双臂原始state记录零offset；与W_L不是同一物理原点 |
| 共同Work W | 迁移所需的工位参考系，尚未建立 | **缺失**；可以未来选择左base作为坐标规范，但仍需实测右base，不能因此默认重合 |
| 左/右Flange | 各臂机械末端连接法兰 | 与对应SDK active-tool定义逐臂绑定，不能从名字推抓取中心 |
| 左Arm_Tip E_L | `realman:left:tool:Arm_Tip` | 历史相对flange零tool定义，已读；SDK state reference/endpoint原始元数据仍UNKNOWN |
| 右Arm_Tip E_R | `realman:right:tool:Arm_Tip` | 右腕包/双臂日志同上；条件性数值绑定不是通用state语义证明 |
| 实际抓取TCP G_L/G_R | 两爪有效夹持中心、方向、可能随开度变化 | **双侧均缺失**；腕相机外参、零tool、历史沿用仿真TCP线索均不能代替测量 |
| 左腕color optical C_L | `realsense:254522073676:color_optical` | 历史角色left_wrist；相对E_L外参已有估计 |
| 右腕color optical C_R | `realsense:348522072063:color_optical` | 历史right_wrist；相对E_R外参已有估计 |
| 桌面color optical C_T | `realsense:346222072496:color_optical` | 历史tabletop/fixed；相对W_L外参有估计，depth验证部分失败 |
| 上方color optical C_O | `realsense:344422071480:color_optical` | 历史overhead/assembly；相对W_L外参有估计 |
| 各raw depth optical | 同serial的原深度光学坐标 | factory depth→color、内参与尺度在历史包内；不能把raw depth K套在aligned depth上 |
| 当前D435 optical | serial `027223021284`；物理角色未知 | 本轮sysfs可见；**没有**与上述任何角色/外参的绑定 |

## 逐项变换状态

| 变换 | 分类 | 范围与限制 |
|---|---|---|
| `T_B_L_W_L`，`T_F_L_E_L` | 历史配置已验证 | 10/11原始work/tool均零pose；有效性依赖未改配置/装配，本轮未重读 |
| `T_B_R_W_R`，`T_F_R_E_R` | 历史配置已读取 | 右腕包及双臂state为零pose；应在现场只读复核右控制器/DH及安装 |
| `T_W_L_E_L(t)` / `T_W_R_E_R(t)` | 历史条件性数值绑定 | 当前零work/tool时两种state解释数值等价；left连接句柄FK对22封存pose max0.00988mm/0.09395°。不是独立实体TCP测量；实时动态变换本轮缺失 |
| `T_E_L_C_L` | 估计、未独立计量认证 | 平移[-83.5225,32.1645,-14.9896]mm；22姿态原手眼，新采集检查4.868–6.425mm，参考共享祖先 |
| `T_E_R_C_R` | 估计、未独立计量认证 | 平移[-81.6219,39.0255,8.2422]mm；11训/5留出；留出5.453mm/1.003°，最大9.975mm |
| `T_W_L_C_T` | 估计且深度质量有失败 | 四留出对应角点depth RMS1877.821/549.422/5.728/8.089mm，不能删除前两项；末组RGB外参差14.351mm也保留 |
| `T_W_L_C_O` | 估计、共享参考留出检查 | RMS4.35–6.09mm；全数据vs训练变换差7.27mm/0.435°；非外部计量 |
| `T_color_depth`（逐serial） | 历史factory读取 | 真实设备profile给出rotation column-major、translation m；不代表安装外参；当前设备是否仍同一/设置同一待复核 |
| `T_B_L_B_R`、`T_W_W_L`、`T_W_W_R` | **缺失** | 无共同工位/双基座实测；不填ASPIRE YAM的0.62m或旧仿真的1.1m |
| `T_E_L_G_L`、`T_E_R_G_R` | **缺失** | 平移/轴向、夹垫、实际开度与载荷相关偏移待测；没有默认TCP常数 |
| `T_W_C_R(t)` / `T_W_C_L(t)` | **缺失完整有效链** | 单腕手眼估计不足以建立共同W；需同曝光时刻臂pose、已知base/work与时间边界 |
| `T_W_C_new`（027223021284） | **缺失** | 相机角色和当前安装均未知 |

四个真实历史外参的**完整矩阵、parent、来源路径和SHA**见 `evidence/camera_transform_inventory.json`。矩阵通过刚体数值检查，只说明格式/数学合法；全部保持 `ESTIMATED_NOT_INDEPENDENTLY_CERTIFIED`，`execution_authorization=false`。三相机包的棋盘格长14.938675mm、右腕15.036722mm均由机器人尺度估计，不是量具真值。

## 后续现场实测项目

1. 不停止当前服务的前提下，人工确认当前设备/serial/相机角色及安装是否变化；为何只可见新的D435。若需要重新插线/改采集配置，另行安排，不由审计脚本执行。
2. 逐臂只读获取work/tool/安装姿态、controller/固件/实际DH、frame fingerprint及硬件身份；明确state reference与endpoint语义的有效条件，不能只看World名称。
3. 用同一可独立复核参考确定两基座到W的变换、误差/时间/装配版本；使用独立验证点，不以拟合残差自证绝对精度。
4. 左右实际TCP、夹垫坐标与开度—毫米映射；记录安装/工具版本、测量方法和不确定性，验证姿态变换而非仅一个轴向常数。
5. 重新检查桌面异常depth与物理成因、对齐K/scale/valid mask、当前内参/stream设置；保留正深度错误样本。右腕跨独立采集/空间点复核；四路共同外参闭环。
6. 设备曝光时间、host receive、机器人回读之间的延迟/最大偏差及滚动快门条件；采集跨度不能当硬同步。腕相机外参必须结合对齐时刻arm状态。
7. 运动/夹爪/停止/碰撞/接触项目不属于本轮；须有后续明确硬件授权后测，详见迁移顺序。
