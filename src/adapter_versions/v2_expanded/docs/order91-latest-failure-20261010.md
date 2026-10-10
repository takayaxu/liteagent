# Order 91：本轮最新失败轨迹（2026-10-10）

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

此次仅补充单题日志和轨迹入口，未追加、复制或重写原始事件文件，未修复实现、未复跑。
