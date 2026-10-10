# OSWorld 102: minimal checked organization transitions

> 2026-10-10 入口核对：Order 102 本轮批次为 FAIL；最新已核对运行为 FAIL。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-102)。下文是本文件所述运行的记录，历史路径不作为最新入口。

Date: 2026-10-10 (Asia/Shanghai; run starts 2026-10-09 UTC).

## 最新运行入口（2026-10-10）

**后续固定 28 题批次中，Order 102 已再次 FAIL，reward=0.0，45 步，1012.175 秒。** 本轮最新失败事件见 [lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)，索引和评分见 [最新失败记录](order102-latest-failure-20261010.md)。本文件以下 classification-check/retry1–retry8 是历史开发运行；其“Raw results”与“Final acceptance”不代表本轮最新结果。

## Historical single-task acceptance

- Historical accepted single-task run: `experiments/osworld-order102-qwen-20261010-classification-check-retry8/`, completed 2026-10-09 19:12 UTC.
- Original post-episode evaluator: **PASS, reward 1.0** (`results.json`: `metadata.status=completed`, task `status=passed`; raw `result.txt=1.0`). **47 recorded steps**, **1031.276 seconds**, termination `agent_done`, no task/evaluator error.
- All **14 source objects** had independently passed classification and physically verified moves: **5 academic papers, 2 coding project directories, 7 miscellaneous objects**. **0 skip calls; 0 target-category-directory moves**. No expected placements were supplied to runtime or the model.
- The checker rejected the planner's incorrect category for the nested Python project at step 35; corrected classification passed at step 36 before its verified move at step 37. The public-information PDF was classified as miscellaneous. The first XLSX required one bounded exact-quotation correction at step 20. There were no checker transport/protocol terminal failures.
- Focused checks: **85 passed in 4.11 s**; changed Python passed Ruff; `git diff --check` passed. Earlier interrupted diagnostics below remain preserved and are not counted as evaluator successes.
- Endpoint/model: `https://qwen.jinmaoapi.cc.cd/v1`, `Qwen3.5-9B`, non-thinking; HF mirror `https://hf-mirror.com`. Only order 102 was run, not a full or cross-application benchmark.

## Scope and preserved evidence

- Current task: order 102, `869de13e-bef9-4b91-ba51-f6708c40b096`, multi_apps.
- Diagnosis: `order102-reader-route-fix-20261009.md`; original failed trace remains unchanged in `experiments/osworld-order102-qwen-20261009-reader-fix/`.
- Original causes: launcher success incorrectly counted as reading, screenshots omitted on later turns, no independent classification check, read-only prerequisite accepted incorrect skips, and target category folders remained in the source inventory.
- This repair uses only the public instruction and observed content. No task IDs, expected filenames, category answers or evaluator artifacts are embedded in runtime code. No frozen v1, pinned OSWorld or old raw evidence is modified. Existing unrelated worktree edits are preserved.

## Minimal repair

1. Preserve the current object's actual reader result. A successful `desktop.open_path` is not a read marker. Visual observation includes the latest screenshot for both the planner and independent checker. Loading/wrong-window/insufficient-content verdicts cannot authorize any disposition; permit a narrow observation retry after insufficient evidence (up to three identical-path successful launcher observations for duplicate-retry exemption).
2. Add `organization__verify_current`: a separate, isolated request to the configured model reclassifies the same source from the original instruction and actual observation. It does not receive the planner's proposed classification/evidence. Require independently matching move/retain decisions and exact directory, sufficient evidence, and a check tied to the source, instruction and observation version. Fail closed on disagreement or checker errors.
3. Only a passed retain/current-location compliance check exposes `organization__skip_current`. Catch-all instructions prohibit retaining an unplaced source outside the declared destinations. Neither reading nor a failed check advances the source. Remove the legacy read->rename shortcut and prevent the billing completion shortcut from bypassing the per-source ledger in move workflows.
4. Only a passed move check exposes the exact checked rename source/destination pair. Advance only after Adapter physical verification passes. An executed move without passed verification remains pending and exposes failure reporting, not a blind mutation retry.
5. Resolve declared destination directories from generic literal destination syntax and observed guest paths. Exclude those directory objects from the source inventory, preserve their exclusion in lease-bound prompts, and protect them in runtime rename validation. The isolated checker never executes file operations.

Touched implementation: `organization_validation.py`, `state_core.py`, `tool_surface.py`, `agent_protocol.py`, `execution_engine.py`, `filesystem_contexts.py` under `integrations/lite_agent/`. Focused contract fixtures/tests are in `tests/test_filesystem_move_discovery.py`.

The independent checker uses the same service/model in a fresh context; agreement is an additional validation barrier, not a mathematical guarantee of semantic correctness. Insufficient evidence/disagreement stops progression rather than guessing or silently skipping.

## Focused checks

```bash
PYTHONPATH=src/adapter_versions/v2_expanded /opt/anaconda3/bin/python3.13 -m pytest -q \
  src/adapter_versions/v2_expanded/tests/test_filesystem_move_discovery.py \
  src/adapter_versions/v2_expanded/tests/test_active_workbook_discovery.py
```

Result: **68 passed**. New cases cover independent disagreement, physical verification failure, catch-all retention rejection, checked valid retention, destination exclusion, loading/visual evidence handling, checker transport failure, observation retry and stale-check invalidation. Changed runtime/test Python files passed Ruff; `git diff --check` passed. No full or cross-application regression run.

## Fresh single-task OSWorld verification

- Config: `experiments/configs/osworld-order102-qwen-20261010-classification-check.json`.
- Raw results: `experiments/osworld-order102-qwen-20261010-classification-check/`.
- Endpoint/model: `https://qwen.jinmaoapi.cc.cd/v1`, `Qwen3.5-9B`, non-thinking, temperature 0, output cap 8192. Isolated checker cap 2048, timeout cap 120 s.
- HF: `https://hf-mirror.com`; fresh Docker guest; task files/evaluator unchanged.
- Bounds increased from 45/25 steps and 1200 seconds to 75/50 steps and 1500 seconds to account for the explicit per-source check phase. One same-VM soft restart allowed; all attempts preserved, no best-of.
- Initial observed behavior: step 5 refused a still-loading PPT; step 7 independently rejected the planner's wrong academic-paper classification; step 8 accepted the corrected disposition and step 9 performed its verified move.
- Final evaluator result: **failed, reward 0.0**, 49 recorded steps / 50 global steps, `agent_done`, 1085.417 seconds, no soft restart. All 14 moves had passed classification checks and physical verification; there were no skip calls or target-directory moves. Twelve placements matched the evaluator, but two semantic mistakes remained.
- Actual remaining mistakes: step 29 independently mislabeled `Family Status Equality-Eng (Aug 2021).pdf` as a research report, although the observed content is a public-information/statistics summary citing other studies. Step 38 classified `assign1-data_python3` from its top-level screenshot as a dataset, without inspecting the visible nested `pacman` folder. These mistakes demonstrate that isolated model agreement alone is not sufficient.
- No commit made in the shared, extensively dirty worktree.

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
  /opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/osworld-order102-qwen-20261010-classification-check.json \
  --result-dir src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-classification-check \
  --orders 102 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
  --reasoning-mode non_thinking --max-steps 75 --max-local-steps 50 \
  --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1500 \
  --max-output-tokens 8192 --request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```

## Evidence-grounding follow-up (same task only)

- Require a bounded recursive `filesystem.find` of only the exact current source directory before its classification. Constrain roots to that source, kind to `any`, patterns to `['*']`, recursion to true, depth to 1..4 and results to 1..200. This is content observation, not global inventory rediscovery. Preserve the first authoritative inventory; nested descendants never become new source objects.
- The independent verdict first identifies the observed genre and provides verbatim excerpts, then chooses a disposition. Structured content requires nonempty, exact observed quotations; invented/missing quotations fail closed. Clarify the generic distinction between original research and summaries quoting research/statistics, rather than adding filename/category rules.
- Follow-up focused checks: **73 passed**, including nested-source discovery without inventory replacement, refusal of top-level-only directory classification, and exact/missing/invented quotation contracts. Changed Python passed Ruff; diff check passed.
- Follow-up config/result directory: `osworld-order102-qwen-20261010-classification-check-retry1`; **interrupted by the agent for diagnosis**, not evaluator-tested. The runner preserved 11 events, `reward=null`, `duration_seconds=1040.924`, and cleaned up the guest after SIGINT to its verified run PID. Its generic interruption label says "interrupted by user"; the actual decision here was agent-initiated after identifying the quotation contract problem. No raw records were rewritten.
- Its first structured PDF check chose the correct category but included a third "quote" that summarized and joined text with ellipses. The exact quotation validator correctly refused it. Checker streaming responses were also unusually slow (roughly 160 seconds each), so further repetition was not useful.
- Simplify the checker contract to ONE short contiguous `evidence_quote` (maximum 240 characters); explicitly prohibit summaries and added ellipses. Normalize only whitespace/line wrapping during quote matching, never words. Add a focused contract for accepted line wraps and refused paraphrases. Final focused result: **74 passed**, Ruff/diff checks passed.
- A host-only synthetic single-string schema service probe returned in **10.689 seconds**. This is a transport/schema diagnostic, not a benchmark pass or proof of a server-side latency cause.
- A matched short-text array-schema probe returned in **10.172 seconds**. Both small requests were fast, so the array field alone does not explain the real episode's slow streaming responses. The single-excerpt change fixes the demonstrated grounding/summary contract problem; it is not presented as a confirmed server-latency repair.
- Follow-up `osworld-order102-qwen-20261010-classification-check-retry2`: **interrupted by the agent for bounded-checker diagnosis**, 9 preserved events, `reward=null`, 657.795 seconds, guest cleanup completed. It confirmed loading refusal and accepted the correct PPT category after another observation. No evaluator result is claimed for this interruption.
- Replaying the same saved public visual checker input with a 512-token output cap returned a complete, valid insufficient-evidence verdict in **50.443 seconds**, versus roughly 200 seconds for the real 2048-token-cap call. This supports bounding the small verifier's output; it does not establish a gateway/vLLM root cause. Probe results never authorize live episode actions.
- Final checker contract: observed type at most 80 characters, one contiguous evidence excerpt at most 240, and one concise factual reason at most 300. Independent request cap **512**; planner cap remains **8192**. Preserve configured thinking/presence/stop controls. Final focused checks remain **74 passed**, with an assertion that the independent output cap is 512; Ruff and diff check passed.
- Follow-up `osworld-order102-qwen-20261010-classification-check-retry3`: **interrupted by the agent after demonstrated semantic/protocol failures**, 16 preserved events, `reward=null`, 483.899 seconds, guest cleanup completed. Step 7 called the PPT an academic presentation yet still agreed to move it into the paper category. The subsequent PDF checker repeatedly violated its schema. Shorter responses reduced runtime, but did not solve semantic entailment or protocol self-repair.
- A read-only replay of the failed PDF checker returned the exact protocol cause: an undeclared localized `原因` key alongside the valid English `reason` key. The replay took 19.874 seconds. This was not a failed reader or an `expected peg-native format` failure. No replay result authorized live operations.

## Final compatibility and protocol tightening

- Parse explicit category requirements from the public instruction's literal destination clauses. Filter only incompatible destinations, without choosing a replacement: known presentations/tables/directories cannot establish a scholarly article, and ordinary documents cannot establish a software project. A completely observed PDF needs primary publication/abstract-and-research evidence before satisfying a scholarly-article criterion; partial/unknown content remains for independent assessment. Named target folders and filenames are not encoded in these rules.
- Apply the same current-object compatibility set to the planner's verification schema, the isolated checker's destination enum, and runtime validation. Include rejection facts in the isolated evidence context. This prevents agreement between two models from overriding an observed type/criterion conflict.
- Permit one bounded independent schema correction for a protocol error, using English field names and compact schema hints, without supplying the planner's proposed answer or raw failed response. Configuration/model-identity failures are not retried. Preserve raw failed replies in runner-owned event diagnostics, excluded from the model context; repeated failure cannot advance or authorize a move/skip.
- Focused verification includes known-type exclusion, complete summary versus primary publication, a scholarly letter without an abstract, partial-content handling, bounded correction and raw-diagnostic isolation. Final focused checks: **81 passed in 3.83 s**; changed Python files passed Ruff and `git diff --check` passed. Repeated checker schema failure makes exactly two attempts, retains the current source and keeps raw failed replies out of planner context.
- Follow-up `osworld-order102-qwen-20261010-classification-check-retry4`: **interrupted by the agent for protocol diagnosis**, 16 preserved events, `reward=null`, 630.543 seconds; guest cleanup completed. The first PPT and first paper were checked and physically moved correctly, with no skip or target-folder move. The second PDF's checker repeatedly returned an undeclared `truth\n</parameter` field alongside the boolean evidence status; even the bounded correction failed. Strict validation refused it and did not advance the source. This proves a response-contract failure, not a reader failure; the available client evidence does not localize model generation versus gateway parsing.

## Minimal response-contract follow-up

- Remove the redundant boolean `evidence_sufficient` from the independent model's wire contract. Its existing `disposition=insufficient_evidence` is the sole evidence-status decision. Runtime still returns a boolean evidence-sufficiency result after verbatim-quote and disposition checks. All five remaining fields are required and unknown fields still fail; no malformed-response field is dropped or repaired into a successful verdict.
- A read-only replay of the **same public observation** that failed in retry4 returned a complete, strictly valid five-field verdict in **17.035 seconds**. This is a diagnostic comparison, not a live-episode authorization or an evaluator pass.
- Post-change focused checks: **81 passed in 4.86 s**, including insufficient visual evidence and no-advance tests; changed Python passed Ruff and `git diff --check` passed. The checker schema is asserted to contain exactly the five declared fields with `additionalProperties=false`.
- Follow-up `osworld-order102-qwen-20261010-classification-check-retry5`: **interrupted by the agent for grounding diagnosis**, 22 preserved events, `reward=null`, 607.605 seconds, guest cleanup completed. Five-field responses resolved the reproduced second-PDF protocol error; PPT and three papers were correctly checked and moved. Recursive directory discovery exposed actual C sources, but the checker repeatedly combined separate filenames into one comma-separated quotation. Exact quotation matching refused all those verdicts, preserving the source and exposing no skip/move authorization.
- Clarify only the directory-listing evidence contract: copy ONE returned entry's exact `name` or `path` field, never concatenate names. A read-only replay of the same directory observation returned an exact observed path and passed grounded classification in **12.608 seconds**. No live mutations were performed by the probe.
- Final focused checks: **82 passed**; add a directory fixture proving individually valid names concatenated into a fabricated quote still fail without advancing. Changed Python passed Ruff; `git diff --check` passed.
- Follow-up config/result: `osworld-order102-qwen-20261010-classification-check-retry6`; interrupted for ledger diagnosis as recorded below. Same endpoint/model, planner 8192/checker 512 tokens, 75/50 steps, 1800 Agent seconds and one soft restart allowed. Every attempt is preserved; interrupted trials are not evaluator passes.

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
  /opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/osworld-order102-qwen-20261010-classification-check-retry6.json \
  --result-dir src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-classification-check-retry6 \
  --orders 102 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
  --reasoning-mode non_thinking --max-steps 75 --max-local-steps 50 \
  --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1800 \
  --max-output-tokens 8192 --request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```

## Typed source reconciliation follow-up

- `osworld-order102-qwen-20261010-classification-check-retry6` was **interrupted by the agent for ledger diagnosis**, 24 preserved events, `reward=null`, 509.7 seconds; guest cleanup completed. Directory discovery, exact quotation, independent classification and physical move all passed at steps 16–18. However, progress still showed the old directory pending, so the planner repeated a completed rename.
- Root cause: ledger reconciliation called `filesystem_organization_check({'path': source})`, losing `kind=directory`. The evidence lookup therefore ignored the directory's successful recursive listing and invalidated its observation-bound check. This is a runtime source-type/state-transition defect, not a wrong category or physical move failure.
- Minimal change: retain authoritative typed inventory entries during reconciliation and pass those exact entries into move/retain check lookup. A directory can now advance after a passed physical move; a failed physical move still cannot advance. No new inventory discovery, destination selection or mutation is performed by reconciliation.
- Focused directory tests now cover success -> next source, physical verification failure -> same source, and joined quotation -> same source. Final focused checks: **83 passed**; changed Python passed Ruff; `git diff --check` passed.
- Follow-up config/result: `osworld-order102-qwen-20261010-classification-check-retry7`; interrupted for quotation-contract diagnosis as recorded below. Same run command as retry6, replacing config and result paths with retry7; all other parameters unchanged.

## Bounded quotation-contract correction

- `osworld-order102-qwen-20261010-classification-check-retry7` was **interrupted by the agent for quotation-contract diagnosis**, 24 preserved events, `reward=null`, 636.783 seconds; guest cleanup completed. The first source directory was correctly checked, moved and advanced to the next XLSX, confirming the typed reconciliation fix. The XLSX was correctly identified as tabular data but its verifier kept serializing two rows as the quotation, which did not match any single original string value.
- Clarify the same generic evidence contract for all structured observations: quote one contiguous excerpt from one string value; a table uses one original cell's text, a directory one entry's name/path. Do not serialize containers or concatenate values. Exact matching still normalizes only whitespace.
- Share the existing two-attempt bound between schema and quotation correction. On the first invalid quotation, request a fresh classification against the same observation with only the contract error hint, never the planner's proposed answer or the failed raw reply. Preserve the first draft in internal diagnostics. Repeated invalid quotation still produces a failed check and cannot authorize a move or skip.
- Read-only production replay of the same saved public XLSX observation: **32.88 seconds**, one bounded quotation retry, exact original cell quotation `Location`, `quotes_verified=true`, `passed=true`. This is not a benchmark pass or live action authorization.
- Final focused checks: **85 passed in 4.11 s**; changed Python passed Ruff; `git diff --check` passed. New tests cover correction success, repeated correction failure, no planner-answer leakage and internal-only failed-draft diagnostics.
- Final config/result: `osworld-order102-qwen-20261010-classification-check-retry8`; **PASS, reward 1.0**, with the actual episode/evaluator findings recorded in Final acceptance. Same command as retry6, replacing config and result paths with retry8; all other parameters unchanged.
