# Order 91：固定 28 题批次失败轨迹（2026-10-10）

> 2026-10-10 入口核对：Order 91 本轮批次为 FAIL；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-91)。下文是本文件所述运行的记录，历史路径不作为最新入口。

**后续单题已修复并正式 PASS / reward=1.0。** 最新结果见 [Order 91 单题日志](order91-query-priority-fix-20261010.md) 与 [results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json)。下面保留修复前最新失败证据；文件名中的 latest-failure 仅指失败记录。

本记录对应固定 28 题测试批次 `osworld-api-split-test-only-20261010-resume1` 的 Order 91，**FAIL / reward=0.0**。其他独立运行或历史 PASS 不代表本轮结果。

- Task ID：`d9b7c649-c975-4f53-88f5-940b29c47247`；应用：`multi_apps`。
- 本轮事件轨迹：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)，45 条事件。
- 完整轨迹索引：[trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/trajectory_manifest.json)。
- 批次原始结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)，对应 Order 91。
- 原始评分：[result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/result.txt)，内容 `0.0`。
- evaluator 对照证据：[manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/evaluator_artifacts/manifest.json)。
- 模型调用记录：[llm_call_log.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/llm_call_log.jsonl)。
- status=failed，45 步，duration_seconds=644.449，termination_reason=null，terminated_by_agent=false；本轮全局步数预算为 45。
- 首条事件：2026-10-10T14:53:35.445764+08:00；末条事件：2026-10-10T14:59:38.675706+08:00（Asia/Shanghai）。事件时间不含完整初始化与 evaluator 收尾耗时。
- 已观察到的失败表现：evaluator 未取得要求的 report.xlsx；产物 manifest 的 result=[null]，取回文件时返回 404。未将该表现直接判为完整根因。
- 事件文件 SHA-256：`35538edf008b36ef2741c5142b303205f70f12955568bd758523d726fade0ca4`。

最初仅补充单题失败日志和轨迹入口。后续完整诊断确认：45 步全部重复同一 Thunderbird 搜索；邮件工具已注册，但被文件/Calc 搜索加分挤出结果，未执行邮件查询或工作簿创建。实现提交 `84a3a4c` 调整通用搜索排序后，单独复跑以 5 步、471.024 秒、agent_done 和 reward=1.0 收尾；完整配置、命令与证据见上方单题日志。原始失败事件及评分未改写。
