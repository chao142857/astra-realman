# Pilot 02 第 12 条：独立事后附录

基线 `f26728e`。本附录不修改原始结果、主评分、主配对、无重连耗时统计或 STOPPED ledger。本轮新增真实请求为 **0**。

原批次 `953a8d18a01447599664db2170862d98`，第 12 次客户端派发：`p02_a_m30_plus / RGB_MULTI_VIEW`。

原 CLI 先记录顶层错误：`Reconnecting... 2/5`，说明 WebSocket 在响应完成前断开。之后确实返回了 JSON、一个 `turn.completed`，HTTP 状态 200、进程返回码 0。原门禁排除任何顶层 `error` 事件，因此归档仍为 `NOT_SCORED`、score null、`COMPLETION_NOT_CONFIRMED`。该标签在本例表示协议未被接受，**不表示完成事件缺失**。

原回答保持为：

```json
{"object_id":"target","position_m":[0.62,0.11,0.12],"quaternion_wxyz":[1,0,0,0],"waypoints_m":[]}
```

仅对这个保存的 raw 使用原严格 JSON 解析器及 `pilot02_contract.score()` 进行事后几何检查，得到 **1.0**：物体正确、完整体积位于允许区域、放置无碰撞、固定朝向满足约束，四项均通过，朝向误差 0。结果与 raw SHA 保存在独立的 `evidence/pilot02_continuation_prep_20261013/run12_posthoc_geometry.json`。

该几何检查只回答“保存下来的答案是否满足几何条件”，不恢复协议有效性。它不纳入主成功率、不补成第六对主 A/C、不进入无重连耗时或 token 比较；原 11 份有效结果、1 份 NOT_SCORED、5 对完整主配对保持不变。

第 12 条客户端耗时约 109.58 秒；该数值属于含重连的原始记录。CLI 重连次数与客户端派发预算分别记录，不根据 `2/5` 推断实际上游生成次数，也不退款或重发第 12 条。
