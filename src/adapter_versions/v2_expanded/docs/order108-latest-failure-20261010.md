# Order 108：本轮最新失败轨迹（2026-10-10）

本记录对应固定 28 题测试批次 `osworld-api-split-test-only-20261010-resume1` 的 Order 108，**FAIL / reward=0.0**。其他独立运行或历史 PASS 不代表本轮结果。

- Task ID：`7e287123-70ca-47b9-8521-47db09b69b14`；应用：`multi_apps`。
- 本轮事件轨迹：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/lite_agent_events.jsonl)，45 条事件。
- 完整轨迹索引：[trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/trajectory_manifest.json)。
- 批次原始结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)，对应 Order 108。
- 原始评分：[result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/result.txt)，内容 `0.0`。
- evaluator 对照证据：[manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/evaluator_artifacts/manifest.json)。
- 模型调用记录：[llm_call_log.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/llm_call_log.jsonl)。
- status=failed，45 步，duration_seconds=657.675，termination_reason=null，terminated_by_agent=false；本轮全局步数预算为 45。
- 首条事件：2026-10-10T15:48:43.357304+08:00；末条事件：2026-10-10T15:54:38.846447+08:00（Asia/Shanghai）。事件时间不含完整初始化与 evaluator 收尾耗时。
- 已观察到的失败表现：evaluator 未取得 GRF-p5y.xlsx 及其转换 CSV，读取返回 404；产物 manifest 的 result=[null]。未将该表现直接判为完整根因。
- 事件文件 SHA-256：`963d1074273ccbaeecdb095e007e8bf312341159c268e377709111e245de5da2`。

此次仅补充单题日志和轨迹入口，未追加、复制或重写原始事件文件，未修复实现、未复跑。
