# Order 42: passing working-tree changes retained (2026-10-10)

- Task: `a434992a-89df-4577-925c-0c58b747f0f4`.
- Test-only batch receipt: `experiments/osworld-api-split-test-only-20261010/results.json`; native OSWorld evaluator reward **1.0**, 8 steps, 185.139 seconds, termination `agent_done`.
- Preserved trajectory: `/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010/raw/run-1/42-libreoffice_impress-a434992a-89df-4577-925c-0c58b747f0f4/trajectory_manifest.json`.
- Change retained: Reject formatting non-content roles for a content-only instruction before dispatch; flatten the role-formatting and background tool schemas while preserving Adapter validation.
- The batch evaluated the complete working tree, including other pending changes. This receipt is not a new run of the isolated committed snapshot. No model/evaluator rerun was made during submission; staged Python syntax and whitespace are checked.
- The implementation and this development record are committed together; see this file's Git history for the corresponding commit.
