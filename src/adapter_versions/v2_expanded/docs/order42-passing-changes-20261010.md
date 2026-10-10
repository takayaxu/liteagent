# Order 42: passing working-tree changes retained (2026-10-10)

> 2026-10-10 入口核对：Order 42 本轮批次为 PASS；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010/raw/run-1/42-libreoffice_impress-a434992a-89df-4577-925c-0c58b747f0f4/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-42)。下文是本文件所述运行的记录，历史路径不作为最新入口。

- Task: `a434992a-89df-4577-925c-0c58b747f0f4`.
- Test-only batch receipt: `experiments/osworld-api-split-test-only-20261010/results.json`; native OSWorld evaluator reward **1.0**, 8 steps, 185.139 seconds, termination `agent_done`.
- Preserved trajectory: `/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010/raw/run-1/42-libreoffice_impress-a434992a-89df-4577-925c-0c58b747f0f4/trajectory_manifest.json`.
- Change retained: Reject formatting non-content roles for a content-only instruction before dispatch; flatten the role-formatting and background tool schemas while preserving Adapter validation.
- The batch evaluated the complete working tree, including other pending changes. This receipt is not a new run of the isolated committed snapshot. No model/evaluator rerun was made during submission; staged Python syntax and whitespace are checked.
- The implementation and this development record are committed together; see this file's Git history for the corresponding commit.
