# Order 102：固定 28 题批次失败轨迹（2026-10-10）

> 2026-10-10 入口核对：Order 102 本轮批次为 FAIL；最新已核对运行为 FAIL。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-102)。下文是本文件所述运行的记录，历史路径不作为最新入口。

本记录对应固定 28 题测试批次 `osworld-api-split-test-only-20261010-resume1` 的 Order 102，**FAIL / reward=0.0**。此前 `osworld-order102-qwen-20261010-classification-check` 及 retry1–retry8 是历史分类检查运行，不是本轮失败轨迹。

- 本轮事件轨迹：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)，45 条事件。
- 完整轨迹索引：[trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/trajectory_manifest.json)。
- 批次原始结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)，Order 102、task `869de13e-bef9-4b91-ba51-f6708c40b096`。
- 原始评分：[result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/result.txt)，内容 `0.0`。
- evaluator 对照证据：[manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/evaluator_artifacts/manifest.json)。
- 模型调用记录：[llm_call_log.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/llm_call_log.jsonl)。
- status=failed，45 步，duration_seconds=1012.175，termination_reason=null，terminated_by_agent=false；本轮全局步数预算为 45。
- 首条事件：2026-10-10T15:23:31.539280+08:00；末条事件：2026-10-10T15:37:17.800183+08:00（Asia/Shanghai）。事件时间不含完整初始化与 evaluator 收尾耗时。
- evaluator 学术论文目标目录列表缺少 `paper01.pdf`；这是输出差异证据，完整根因尚未分析。本轮失败不能被此前 retry8 的 47 步 PASS 覆盖，二者运行预算不同。
- 事件文件 SHA-256：`b3bba54cac360bcfe672816b09ba9e85a84b1c58762adcd903ac226970a515ab`。

此次仅补充轨迹入口，未追加、复制或重写原始事件文件，未修复实现、未复跑。
