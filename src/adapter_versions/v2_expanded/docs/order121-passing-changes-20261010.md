# Order 121: passing working-tree changes retained (2026-10-10)

- Task: `f5c13cdd-205c-4719-a562-348ae5cd1d91`.
- Test-only batch receipt: `experiments/osworld-api-split-test-only-20261010-resume1/results.json`; native OSWorld evaluator reward **1.0**, 6 steps, 284.406 seconds, termination `agent_done`.
- Preserved trajectory: `/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/121-multi_apps-f5c13cdd-205c-4719-a562-348ae5cd1d91/trajectory_manifest.json`.
- Change retained: Retain completed source-reading progress through context fitting, require discovery of the requested mail-recipient route instead of repeating Calc reads, and use the current workbook.read_file route in recovery and row-transfer staging.
- The batch evaluated the complete working tree, including other pending changes. This receipt is not a new run of the isolated committed snapshot. No model/evaluator rerun was made during submission; staged Python syntax and whitespace are checked.
- The implementation and this development record are committed together; see this file's Git history for the corresponding commit.
