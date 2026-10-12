# 产出归档与推送要求

用户于 2026-10-12 明确要求：以后所有这些产出文件都要 git push。

本项目默认将代码、配置、测试、输入快照、图片、原始请求/响应、日志、失败记录、CSV/JSON、报告和文档全部提交并推送到独立实验分支，核对远端 SHA。早期或失败产出也保留，后续通过单独结果与说明标注，不仅保留最终汇总。临时复现生成的实验文件也应归档到模块后推送。

本次补充 `evidence/fixtures`、`mock_fixtures`、`mock_archive` 的首次 smoke 产出，以及 `evidence/readme_reproduction` 中 README 在 /tmp 实际复现的文件。它们是同一实现的重复验证，不增加独立场景或真实模型样本计数。

首次 fixtures 的 geometry.source 历史字段为 SIMULATOR_TRUTH，但其 snapshot.provenance 已明确为 SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION；这些仅是合成测试，不是实际模拟器真值。正式 fixture_suite 已使用正确的 SYNTHETIC_FIXTURE_TRUTH 标签。初次真实失败派生零分报告也保留，当前正确分类以 real_ac_final 为准。原始历史证据不改写。

认证凭证、程序缓存和运行时数据库不属于实验交付产出，不提交。若网络或远端限制导致未推送，须明确记录具体文件和原因，不能默认为已推送。
