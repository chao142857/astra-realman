# RM65 双臂模型准备与原生 cuRobo 接口

本轮实际完成现场资产盘点、mesh存在性/哈希核验以及左右两份独立单臂候选生成。只解析XML/JSON/YAML，不导入历史任务程序、RealMan SDK、仿真器或规划器。结果为`TWO_SEPARATE_NOMINAL_ARMS_PREPARED_NOT_REGISTERED`，不是已经验收的真实双臂规划模型。

## 可复用资产

| 组件 | yanglab实际路径 | 复用范围与限制 |
|---|---|---|
| 名义RM65单臂URDF | `/home/tongji/alex/rm65-handoff-runtime-20261014/assets/vendor/target_models_20260921/rm_description/urdf/rm_65.urdf` | 9,163 bytes，SHA `ed8800aef0cce10f20ce5e1bf4091b4e1d9dd3275b8e662fd44dde2e5dba6418`；关节链、名义限位和几何可复用，实际型号/DH/FK未核对 |
| 七份机械臂STL | 上述vendor根下`rm_description/meshes/rm_65_arm/{base_link,link1…link6}.STL` | 全部实际存在并计算SHA；不跨机复制或提交mesh |
| 历史单臂+夹爪模型 | `/home/tongji/alex/rm65-contact-servo-yanglab-20261017/experiments/rm65_handoff_v1/runtime_config/{planning.urdf,assembly.urdf,assembly.json}` | CTAG2F90-D及相机装配线索；不是当前实测安装/TCP；不复用其中任务控制逻辑 |
| 历史cuRobo配置 | 同runtime_config下`curobo.yml` | 六关节顺序/球体配置可供重新审核；URDF配置路径`/home/alex/astra/configs/rm65_ctag_reference/planning.urdf`在yanglab不存在；不能直接启动 |
| Phase0.5 Codec | `aspire_realman_phase05/src/aspire_realman/codec.py` | `left_joint_1…6`、`right_joint_1…6`及deg→rad规则；命名兼容不等于现场控制器顺序/符号/零偏已验证 |

历史assembly明确写有temporary flange→gripper 8mm、wrist camera `[0,-0.09,0.045]m`、base_world `[-0.19,0,0.03]m`及“temporary 30mm mounting stand; not laboratory measurement”。这些值只作为历史来源证据，没有写入新候选模型或当作当前真实标定。历史`ee_link=Link6`是法兰，不是实际抓取TCP。历史retract和夹爪lock值是模拟配置，不是Home或当前夹爪读数。

原配置有1,479个碰撞球、15个link；旧assembly记录过cuRobo kernel <1024限制和当时改用mplib/OMPL/FCL。该记录不证明当前环境必然同样失败，需在独立规划环境复现；本轮没有安装/启动cuRobo或放宽碰撞检查。

## 六轴关节与输出模型

名义链为`base_link → Link1 → … → Link6`，关节局部axis均`[0,0,1]`，不能解释成世界系共轴。origin/RPY原样保留，具体值见`evidence/rm65_inventory.json`。以下仅为源URDF名义值，非当前控制器读回：

| 原关节 | 左/右候选关节 | 下/上限 rad | 最大速度 rad/s | effort Nm |
|---|---|---|---:|---:|
| joint1 | left_joint_1 / right_joint_1 | -3.1 / 3.1 | 3.14 | 60 |
| joint2 | left_joint_2 / right_joint_2 | -2.268 / 2.268 | 3.14 | 60 |
| joint3 | left_joint_3 / right_joint_3 | -2.355 / 2.355 | 3.92 | 30 |
| joint4 | left_joint_4 / right_joint_4 | -3.1 / 3.1 | 3.92 | 10 |
| joint5 | left_joint_5 / right_joint_5 | -2.233 / 2.233 | 3.92 | 10 |
| joint6 | left_joint_6 / right_joint_6 | -6.28 / 6.28 | 3.92 | 10 |

新目录`/home/tongji/alex/aspire_realman_phase1b_20261020/evidence/rm65-candidates/`实际生成：

- `left_rm65_nominal.urdf`：根`left_base_link`，法兰`left_Link6`；8,569 bytes，SHA `fb3a0d2a3c4fce68d48136aa7c1fffeca4ff09a81b6c2fc67e5545445c263d39`。
- `right_rm65_nominal.urdf`：根`right_base_link`，法兰`right_Link6`；8,595 bytes，SHA `5736cf1bc7eeb91991aa021e10a7a16ec86c5744cecfa6c33af12817845f553b`。

两者均核验单一根、6个revolute关节、全部mesh可读及每轴origin/axis/limit与原URDF完全一致。mesh引用原位置，不复制。建议12关节扁平顺序为left 1→6再right 1→6；后续必须对照真实控制器关节ID、方向、零偏、单位和限位，并用只读FK与独立实体参考检查。未添加夹爪、相机、实际TCP或公共World固定关节。缺失跨基座变换时不生成伪双臂装配。

复现（输出目录须全新，前置`PY`定义同README）：

```bash
$PY -B aspire_realman_phase1b/tools/prepare_rm65_candidates.py \
  --vendor /home/tongji/alex/rm65-handoff-runtime-20261014/assets/vendor/target_models_20260921 \
  --runtime-config /home/tongji/alex/rm65-contact-servo-yanglab-20261017/experiments/rm65_handoff_v1/runtime_config \
  --output evidence/rm65-candidates-recheck
```

## 原生注册接口的具体改动点（设计，尚未启用）

固定ASPIRE `fa00f0e`，已有Phase0.5只将`JOINT_DIMENSIONS["realman"]=6`注册到核心合同。**这不等于cuRobo HTTP已支持RM65。** 拟用model id `realman_rm65_dual`，当前不发送该请求、不构造假的`RobotPlanningContext`。

| 原生文件/接口 | 当前行为 | 后续独立通用适配改动 |
|---|---|---|
| `providers/curobo/service.py:BaseRequest` | model Literal仅panda/dual_panda/yam_real | 显式增加RealMan id并绑定审核通过的独立配置；未知id继续拒绝 |
| 同文件`_robot_config` | Panda/YAM后默认走dual-Panda | 显式RealMan分支；模型/标定不全返回不可用，不能落入dual-Panda或YAM布局 |
| 同文件`_validate`、`_joint_goal` | 除YAM外按robosuite 7维 | RealMan每臂6维；左右臂集合、精确关节名、有效刚体变换与配置版本一致性核验 |
| 同文件`_state`、`_requested_indices` | 根据模型名重排；带Panda兼容分支 | RealMan严格按12个精确名称绑定；不得按长度猜测/改名；实测限位偏差应诊断，不静默借用Panda规则 |
| `providers/curobo/client.py:_base_payload` | 已携带model/joints/names/base_transforms/EE links/同系场景云 | 可复用wire；单位m/rad/WXYZ；每个值由真实来源与标定版本提供 |
| 同文件`_default_context` | Panda模型及identity base默认值 | 保留RealMan Adapter当前显式拒绝context，防止进入此fallback |
| `contracts.py:RobotPlanningContext` | model为str，但每臂必须有4×4矩阵、关节名、EE link | 当前缺失项保留null只存在readiness文档，不能作为合法planning context发送 |

公共World需先明确`p_W = T_W_B @ p_B`，左右基座变换都要有实测来源/误差/日期/装配版本。若未来选择左基座为World，左基座自映射的identity只是一种已明确的坐标规范，右基座仍必须实测；也不能在URDF固定关节和context里重复应用同一偏移。双侧实际抓取TCP必须从法兰/Arm_Tip分别绑定，不能把`Link6`当已测TCP。

完成顺序：实际型号/关节与FK绑定 → 当前World/TCP/夹爪和相机碰撞几何 → 生成真实双臂装配/SRDF/碰撞球并审查球数/覆盖 → 注册上述通用接口 → 仅用封存真实状态进行离线FK/IK/碰撞/规划验收。全过程不更改Agent任务决策，不加入交接专家，不产生真实派发。现场剩余项目见`ONSITE_CHECKLIST.md`。
