# Order 99: organization destination validation

> 2026-10-10 入口核对：Order 99 本轮批次为 FAIL；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-99)。下文是本文件所述运行的记录，历史路径不作为最新入口。

## 本轮最新失败入口（2026-10-10）

后续固定 28 题批次 Order 99 为 **FAIL / reward=0.0**，45 步，475.856 秒。完整本轮轨迹、评分和原始文件哈希见 [单题最新失败日志](order99-latest-failure-20261010.md)。本文以下内容是此前独立运行/修复历史，不代表本轮最新结果。

## Preserved failure

- Task: `337d318b-aa07-4f4f-b763-89d9a2dd013f` (order 99).
- Previous evidence: `experiments/osworld-order99-qwen-20261009-rerun2/`.
- Endpoint/model: `https://qwen.jinmaoapi.cc.cd/v1`, `Qwen3.5-9B`.
- The user instruction requests moving discrepant invoices into `problematic`.
- At step 7, the model selected the requested folder with an exact observed source path. The execution engine rejected it because the destination parent was not one of three hard-coded category names. Retries ended in `stalled_no_progress`, evaluator reward `0.0`.
- The same category names also appeared in the system prompt and observation marker. This run did not show a PEG-format or HTTP transport failure.

## Reusable change

- Remove fixed category names from the organization prompt, observation marker, destination validation, and inventory filters. Classification criteria and folder names come from the user instruction and the model's content-based decision.
- Keep current-object selection, content evidence, exact paths, and basename-preservation validation.
- Reject no-op organization renames with guidance to use the explicit retain/skip transition.
- Forward the model's exact destination unchanged. The existing OS rename implementation already creates missing parent directories.
- No task identifiers, requested folder names, or expected invoice answers were added to runtime code.
- No API was split or expanded in this repair; it corrects the generic organization contract.

## Validation

- Focused filesystem organization checks: **32 passed**.
- Ruff on all four changed Python files: passed.
- `git diff --check`: passed.
- New run: `experiments/osworld-order99-qwen-20261009-destination-fix/`.
- First attempt: `environment_failure`, reward `null`, no model task actions. All three OS adapter deployment attempts timed out during `apt-get update` (45 seconds); logs also showed PackageKit index lock contention and a missing Google Chrome repository signing key. The failed episode was preserved.
- Retry: `experiments/osworld-order99-qwen-20261009-destination-fix-retry1/`, same command below with this result-directory suffix. Formal evaluator **passed**, reward **1.0**, 10 steps, termination `agent_done`, total duration 341.54 seconds. Model protocol and transport failure counters were both zero.
- Retry environment provisioning: before task execution, installed the missing OCR packages in the fresh guest with `apt-get -o DPkg::Lock::Timeout=90 install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng` via the existing `CommandRunner.sudo`, using the already available package indexes. Exit code 0; OS adapter deployment then reported healthy. No task documents or evaluator settings were changed by this provisioning step. The deployment script itself was not changed.
- Existing unrelated worktree changes were retained; no commit created.

## Successful execution and remaining limitation

The retry read the bank statement (step 4), explicitly retained it (step 5), read the first invoice (step 6), and moved that invoice into the model-selected destination (step 7). The move returned `executed=true` and `verification_passed=true` with the exact requested destination. The offline evaluator retrieved the target PDF and returned 1.0.

This is an evaluator pass, not evidence that every invoice was reviewed. At step 8 the model-visible tool surface contained only `propose_done`, although two observed invoices had not been read. The existing `_billing_reconciliation_complete` shortcut checks only already-read invoices; after the observed unmatched invoice is moved, it can return true before the inventory is exhausted. Completion attempts at steps 8 and 9 were rejected for describing unfinished work; step 10's completion claim was accepted. The task's pinned evaluator checks the designated target PDF only. This separate early-completion issue is recorded here and was not changed in this destination-validation repair.

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
  /opt/anaconda3/bin/python3.13 -u \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/osworld-order99-qwen-20261009-destination-fix.json \
  --result-dir src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261009-destination-fix \
  --orders 99 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
  --reasoning-mode non_thinking --max-steps 45 --max-local-steps 25 \
  --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1200 \
  --max-output-tokens 8192 --request-timeout 240 --model-retries 3 \
  --top-k 7 --temperature 0
```
