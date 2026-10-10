# Order 99：固定 28 题批次失败轨迹（2026-10-10）

> 2026-10-10 入口核对：Order 99 本轮批次为 FAIL；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-99)。下文是本文件所述运行的记录，历史路径不作为最新入口。

本记录对应固定 28 题测试批次 `osworld-api-split-test-only-20261010-resume1` 的 Order 99，**FAIL / reward=0.0**。其他独立运行或历史 PASS 不代表本轮结果。

- Task ID：`337d318b-aa07-4f4f-b763-89d9a2dd013f`；应用：`multi_apps`。
- 本轮事件轨迹：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)，45 条事件。
- 完整轨迹索引：[trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json)。
- 批次原始结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)，对应 Order 99。
- 原始评分：[result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)，内容 `0.0`。
- evaluator 对照证据：[manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/evaluator_artifacts/manifest.json)。
- 模型调用记录：[llm_call_log.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/llm_call_log.jsonl)。
- status=failed，45 步，duration_seconds=475.856，termination_reason=null，terminated_by_agent=false；本轮全局步数预算为 45。
- 首条事件：2026-10-10T15:15:16.863088+08:00；末条事件：2026-10-10T15:19:55.324373+08:00（Asia/Shanghai）。事件时间不含完整初始化与 evaluator 收尾耗时。
- 已观察到的失败表现：evaluator 未取得要求的目标 PDF；产物 manifest 的 result=[null]，取回文件时返回 404。未将该表现直接判为完整根因。
- 事件文件 SHA-256：`7aa5d95d61e352fa87e75f5928e70e187bc53b7e9fcd65e704405ddf20b6d3a8`。

此次仅补充单题日志和轨迹入口，未追加、复制或重写原始事件文件，未修复实现、未复跑。
