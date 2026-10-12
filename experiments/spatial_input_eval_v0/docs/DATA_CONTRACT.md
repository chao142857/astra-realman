# SceneSnapshot V0 与评分定义

`schema/scene_snapshot.schema.json` / `geometry.schema.json` 给出序列化契约；`inputs.py` 和 `geometry.py` 补充单位四元数、引用、图像 SHA、同步和禁止额外字段的语义检查。输出契约位于 `schema/*.output.schema.json`。

## 数据边界

- `observations`：PNG 图像引用和 SHA、depth 的归档引用、每相机 intrinsic/resolution/pose/axes、joint_names/qpos_rad/flange_pose、同步声明。模型只接收 RGB 附件、标定、机器人状态和同步信息；三组都不发送 depth 像素。
- `geometry.reconstruction`：B 的实测重建几何，`source=RECONSTRUCTION`，缺失时明确 `GEOMETRY_UNAVAILABLE`，不会拿 oracle 代替。
- `geometry.oracle`：C 的仿真或独立测量几何。合成测试数据用 `SYNTHETIC_FIXTURE_TRUTH`，禁止真实模型模式接受合成 fixture。
- `ground_truth`：独立评测器读入；从不被序列化进模型上下文、路径或挂载。允许为 null，此时 `NOT_SCORED`、score=null，不能制造成功率。
- `task`：包含 task_id、kind、instruction、frame、questions、constraints、tolerance_m；各条件完全相同。无评分字段或参考规划。

几何元素统一为 `id / center_m[3] / size_m[3] / quaternion_wxyz[4]`，分为 `objects / regions / obstacles`。`regions` 表示允许的内部空间，`obstacles` 表示实体箱体；其他物体也是实体障碍。容器内腔作为 region，墙体需要单独的 obstacle 箱体。V0 不支持任意 mesh、多面体、未知尺寸或概率几何；不要将它们静默近似成“已验证”箱体。

`renderings=[]` 预留俯视/正交渲染槽位；非空会明确拒绝，避免误称已经发送了渲染输入。C 并不保证几何身份、尺寸、遮挡信息等额外因素能独立归因；这些均记录在 input manifest。原始相同 RGB 保持像素 SHA 相同。

## 坐标与任务

全局 frame 固定 `robot_base`、米、右手系：+x 前、+y 左、+z 上。所有位姿指物体中心，不是 TCP。单位四元数为 wxyz，符号正负等价。没有根据单张图片定义“左边”。

历史 S1 场景中基座与 world 同方向，基座世界平移为 `[0,0,0.03]` 米，源码的 root Pose 没有旋转。因此所有位置和相机位置减去这项平移，朝向保持不变。桌面在 base z=-0.03，物体中心可能为负高度，这是合法坐标。

空间理解问题：

| type | 输入引用 | 模型有效输出字段 | 独立评分 |
|---|---|---|---|
| relation | object_id、other_id、axis | relation | 对中心沿该正向轴的差值判 less/equal/greater；equal 使用 tolerance_m |
| position | object_id | vector_m | 中心欧氏误差 |
| height | object_id、reference=center/top/bottom | scalar_m | 中心或所有 OBB 角点的最高/最低 base z，绝对误差 |
| size | object_id | vector_m | 物体局部三个轴的尺寸，欧氏误差 |
| gap | object_id、other_id、axis | scalar_m | 两个 OBB 在该轴的投影区间之间的非负间隙；重叠为 0 |
| fit | object_id、region_id、quaternion_wxyz | fits | 在给定姿态是否存在完整体积容纳；对中心对称 OBB 内腔，将中心对齐即为尺度判断 |

所有答案字段都必须出现；只有该题对应字段非 null。问题不可缺失、重复或额外添加。每题使用同一个 tolerance_m；relations、每项几何误差、容差内比例和错误 question_id 保存在详细评估中。

规划输出固定为 `object_id / position_m / quaternion_wxyz / waypoints_m`。placement 的 waypoints 为空。path 的点是物体中心，排除明确的起点、包含终点，最后一点必须等于 position_m。姿态沿全路径固定；没有对中间旋转进行插值。输入 constraints 指定物体、允许体积、障碍 clearance、可选所需姿态和角度容差；path 另含 start_position 与凸 workspace region。

目标合法性检查全部 8 个角点，测量 tolerance 不扩张允许空间。全路径检查连续 OBB 运动的 SAT 交叠区间，能发现极薄障碍及路径点之间的穿透。与障碍接触视为碰撞；clearance 是各 SAT 轴上的保守安全间隙，不能称为精确欧氏距离。workspace 凸，因此所有端点完整容纳可保证直线段容纳。完全静态几何定义，不隐含稳定放置、支撑、可达、手爪或机械臂碰撞、IK 或动力学。

只要全部约束通过就得 1；任一违例为 0，逐项记录错误。没有唯一参考位姿/轨迹，也没有字符串相似度。

## 请求、解析与比较

每条 request.json 保存冻结 context、实际 base64 图片、provider schema 和 authoritative schema；raw.txt、response.json、worker stdout/stderr、events、command、usage 保存原始证据。`parse_prediction()` 严格拒绝重复键、NaN、无限值、代码围栏、尾随文本、非法字段及非单位四元数；不裁剪、补 JSON 或修改模型决策。

有可靠 GT 的非空、格式错误模型回答可记为 0；没有回答或 transport/CLI 故障记 `NO_MODEL_RESPONSE / NOT_SCORED / null`。API 故障不成为空间准确率的分母。原始 worker 有时 return_code!=0 但 error=null，所以同时检查两项。

默认 mock 明确 `MOCK_NOT_ASTRA`，它不接收 GT。输入条件比较按 scene_id/task_id 成对，要求相同 source、task/prompt hash、可评分状态；缺失 B 或失败真实请求不伪造成一组比较。结果包含 CSV、完整 JSON、paired_comparison.json、summary.md、failure_index.json。V0 只提供描述性均值和差值，显著性 `NOT_ESTABLISHED`；六个测试 fixture 和同场景多任务不是独立实验重复。

未来 B 数据直接填入 `geometry.reconstruction`（同 frame/units/box schema），并以 `--conditions RGB_MULTI_VIEW RGB_RECON_3D RGB_ORACLE_3D` 运行。不能改变其他条件或用模拟真值冒充 reconstruction。公开数据集扩展类在 `data.py`，目前调用会显式 NotImplementedError。
