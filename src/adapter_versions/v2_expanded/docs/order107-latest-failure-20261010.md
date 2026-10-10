# Order 107：本轮最新失败轨迹（2026-10-10）

本记录对应固定 28 题测试批次 `osworld-api-split-test-only-20261010-resume1` 的 Order 107，**FAIL / reward=0.0**。其他独立运行或历史 PASS 不代表本轮结果。

- Task ID：`881deb30-9549-4583-a841-8270c65f2a17`；应用：`multi_apps`。
- 本轮事件轨迹：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/lite_agent_events.jsonl)，45 条事件。
- 完整轨迹索引：[trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/trajectory_manifest.json)。
- 批次原始结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)，对应 Order 107。
- 原始评分：[result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/result.txt)，内容 `0.0`。
- evaluator 对照证据：[manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/evaluator_artifacts/manifest.json)。
- 模型调用记录：[llm_call_log.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/llm_call_log.jsonl)。
- status=failed，45 步，duration_seconds=505.698，termination_reason=null，terminated_by_agent=false；本轮全局步数预算为 45。
- 首条事件：2026-10-10T15:40:31.093579+08:00；末条事件：2026-10-10T15:45:46.702490+08:00（Asia/Shanghai）。事件时间不含完整初始化与 evaluator 收尾耗时。
- 已观察到的失败表现：evaluator 成功获取 supported_rate.xlsx，保存了 result 和 expected 两份表格，但评分为 0.0；尚未逐单元格分析失败根因。
- 事件文件 SHA-256：`cb0cb16ebf4d506d90b9f4ad07cf98772b0c553629c344347ad8de16b453c1e7`。

此次仅补充单题日志和轨迹入口，未追加、复制或重写原始事件文件，未修复实现、未复跑。
