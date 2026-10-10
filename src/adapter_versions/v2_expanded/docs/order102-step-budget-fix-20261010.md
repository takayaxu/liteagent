# Order 102: estimate organization steps from observed inventory

Date: 2026-10-10 (Asia/Shanghai).

## Preserved failure

- Order 102, `869de13e-bef9-4b91-ba51-f6708c40b096`, multi_apps.
- Latest failure: `experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/`.
- This individual episode ran 15:20:41–15:37:33 Asia/Shanghai, 1012.175 seconds, 45 recorded steps, formal evaluator reward **0.0**. The containing batch completed later; its timestamps are not this episode's timestamps.
- Manually reviewed the complete public task definition, all 45 events, actual reader and move responses, classification checks, saved model requests, call index, model audits, episode controls and original evaluator result. The prior two misclassifications were corrected in this run. Thirteen objects were checked and physically moved; the remaining source was read successfully at step 45.
- Step 45 returned 8000 characters of PDF content including title, authors and abstract, with Adapter status `ok` and verification passed. Organization progress still reported the current object as unclassified/unmoved. The request index ends at step 45; its model audit remains pending. No classification or move was proposed after that read.
- Root cause: `max_steps=45` exhausted the runner's global loop. The normal exhaustion path fell through to evaluation without a termination reason. A same-VM soft restart does not reset the global budget. Fourteen three-phase objects alone require 42 operations before discovery, correction and completion overhead.
- Earlier single-task acceptance (`classification-check-retry8`) used a 75-step budget and formally passed. The user explicitly authorized repairing the new preserved failure.

## Minimal reusable change

- Keep `--max-steps` as the immutable hard cap. Add opt-in `--initial-step-budget`, constrained to 1..max_steps. Without it, existing fixed-budget behavior is retained.
- After the first complete authoritative source discovery, estimate once from RuntimeState's existing deduplicated, destination-filtered pending source ledger: `used_steps + pending_sources * (3 phase steps + 1 retry/extra-read step) + 4 completion/reserve steps`.
- The effective episode budget is `min(hard_cap, max(initial_budget, estimate))`. Record policy, original/effective/hard budgets, source counts, observation step, estimate components and whether the estimate exceeds the hard cap in task results and the trajectory manifest. Nested directory inspections and soft restarts cannot recalculate/reset this estimate.
- Incomplete discovery and unrelated workflows do not trigger estimation. The estimator selects no category, performs no mutation and exposes no task-specific information to the model. Time, no-progress and local recovery limits remain explicit independent bounds.
- Ordinary budget exhaustion now records `termination_reason=step_budget_exhausted`, used/effective/hard step counts and the pending model audit, and sends an explicit failure episode boundary before the original evaluator runs. Existing terminal outcomes and failure reasons are preserved.
- Touched files: `scripts/organization_step_budget.py` and only budget-related additions in the already-dirty `scripts/run_lite_agent_pilot.py`. No API changes or replacements are necessary: PDF extraction and all classification/move operations worked in the preserved failure. No frozen v1, pinned evaluator or historical raw evidence is modified.

## Focused verification

- Host-only replay of the preserved public instruction and first three events: incomplete discovery gives no estimate; 14 sources exclude destination folders; initial 45/hard 75 gives **63**; a hard cap of 50 clips the estimate and records insufficiency; a larger initial budget does not shrink; unrelated domains receive no estimate. No replay authorized a live mutation.
- Executed the actual runner exhaustion AST branch with bounded host mocks: fixed limit hit, extension permits continuation, previous termination reason preserved, completed state preserved, and explicit FAIL boundary only on actual exhaustion.
- Changed Python passed Ruff and compilation; `git diff --check` passed. No general regression suite or other task evaluation was run for this repair.

## Single-task verification

- Config: `experiments/configs/osworld-order102-qwen-20261010-inventory-step-budget.json`.
- Result directory: `experiments/osworld-order102-qwen-20261010-inventory-step-budget/`.
- Initial 45 steps, hard cap 75, per-plan 50, one same-VM restart, 1800 Agent seconds. The latter parameters match the prior passing single-task protocol; the preserved batch failure used local 25 and 1200 seconds. Changed runtime conditions are recorded, not presented as an identical-condition rerun.
- Fresh Docker guest; same Qwen3.5-9B endpoint/model, non-thinking, planner 8192/checker 512 tokens, temperature 0. Only order 102 is selected. Every attempt is preserved and the original offline evaluator loads after the episode.
- First attempt: agent-interrupted for model-generation diagnosis, 1 preserved event, reward null, 713.6 seconds; guest cleanup completed. The raw generic interruption text says user interrupted, but the agent initiated this bounded diagnostic interruption. The directory-discovery request streamed for approximately nine minutes without returning a complete proposal. A 64-token synthetic service probe completed in 4.255 seconds; a read-only replay of the same saved public discovery request with a 512-token cap took 38.847 seconds, hit finish_reason=length and returned an invalid nested name_patterns array. These probes diagnose generation/response behavior, not a benchmark failure or a live operation authorization. The budget estimate had not yet triggered.
- Follow-up config/result directory: `osworld-order102-qwen-20261010-inventory-step-budget-retry1`; planner output cap reduced to 2048, all other listed parameters preserved. The changed cap is recorded explicitly; this is not an identical-generation-condition rerun. This attempt was agent-interrupted after repeated discovery protocol failures; 1 event preserved, reward null, 608.855 seconds, guest cleanup completed. Original evaluator was not run.
- Read-only replay compared the current discovery whole-array enum against an equivalent singleton item enum. The former generated a nested array; the latter generated the exact one-dimensional wildcard list. Both used their complete output caps, so this is schema compatibility evidence, not proof of a transport latency repair. Change only the two organization wildcard schemas to a one-element array with a string item enum. Runtime validation still requires exactly `["*"]`. Focused JSON-schema acceptance/rejection checks passed, and 6 existing directory/inventory tests passed; Ruff passed.
- Follow-up config/result: `osworld-order102-qwen-20261010-inventory-step-budget-retry2`; planner cap 512, checker cap 512. All other listed parameters preserved. Formal evaluator **failed, reward 0.0**, 48 events, 1127.175 seconds, agent_done. Budget estimate triggered at step 2 for 14 sources: initial 45 -> effective 62, immutable hard cap 75. Step 45 read the final PDF, step 46 checked it, step 47 physically moved it; step 48 proposed completion and the following audit confirmed it. This directly verifies removal of the budget cutoff. All 14 moves physically passed, but one unrelated semantic error remained: the complete Writer assignment/instruction document was incorrectly labeled scholarly by the independent checker and moved into the article category.
- Reviewed its complete 4585-character Writer observation, planner proposals at steps 32–33, isolated verdicts, schema exclusions and actual move at step 34. Existing complete-document article compatibility covered only PDFs, leaving complete Writer documents to unconstrained model agreement. Extend that existing primary-publication/abstract-and-research evidence check to demonstrably complete Writer reads. Partial/unknown Writer text remains for independent assessment. This is format coverage of the same generic category constraint; no filenames, answers, IDs or source phrases are added.
- Host-only checks: the preserved complete assignment observation excludes the scholarly destination, synthetic original-research text permits it, and partial Writer content remains unconstrained. Ruff passed.
- Follow-up config/result: `osworld-order102-qwen-20261010-inventory-step-budget-retry3`; same parameters as retry2. Formal evaluator **PASS, reward 1.0**, 47 recorded events, 1077.597 seconds, termination `agent_done`, no task/evaluator error. Initial 45 -> effective 62 at step 2 for 14 sources; hard cap 75. Final PDF read at step 44, independently checked at step 45 and physically moved at step 46; completion at step 47 confirmed by the following audit. All 14 source moves passed physical verification. The assignment was classified into miscellaneous at step 32 and moved at step 33. Raw result.txt=1.0. No other orders were run.
- Episode global_steps=48 includes final audit; no soft restart used. Current estimator and classifier source hashes match the passing run. tool_surface.py changed concurrently after the episode seal; the passing result applies to its preserved episode version, while both singleton wildcard schema fixes remain in the current file. Do not overwrite concurrent edits.

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
  /opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/osworld-order102-qwen-20261010-inventory-step-budget.json \
  --result-dir src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget \
  --orders 102 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
  --reasoning-mode non_thinking --max-steps 75 --initial-step-budget 45 \
  --max-local-steps 50 --max-soft-restarts 1 --max-no-progress-steps 8 \
  --max-agent-seconds 1800 --max-output-tokens 8192 --request-timeout 240 \
  --model-retries 3 --top-k 7 --temperature 0
```

## Commit

The independent budget commit contains only runner budget hunks, new estimator, this diagnosis and four new single-task configs. The two singleton schema changes and complete-Writer compatibility follow-up remain in the working tree: their containing implementation was already extensively modified/untracked before this task, and staging whole functions/files would absorb prior work. The passing result validates the combined episode source, not the isolated budget commit alone. Preserve these edits for integration.

Budget implementation commit: `4894e6f` (`fix(runner): estimate organization step budget from observed sources`). Scope: seven files, only the isolated budget implementation/config/diagnosis. Auxiliary current-task schema/classification fixes are present but unstaged as described above.
