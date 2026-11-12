# Local Qwen9B delivery repair

The previous completed batch at 5833efc passed 93/189, with 53 episode deadlines,
31 protocol failures and 12 evaluator failures. Do not combine rerun passes into its score.
25 of the 31 protocol failures had empty arguments for composed object schemas.
Its actual streaming responses had median generation throughput about 2.9 tokens/sec.

## Root causes and repair

The pinned llama.cpp Qwen XML parser uses foreach_parameter, which casts the parsed
JSON Schema root to common_chat_schema_object. Composed roots are conjunctions or
unions; the cast fails, and every argument is silently skipped. The generated grammar
therefore enforces an empty body. Reducing slots from 12 to 4 still reproduces this.
The included deployment-patches/llamacpp-qwen-composed-parameters.patch restores
parameter enumeration from the sibling properties and root required fields. It preserves
property types and does not synthesize arguments. Cross-field constraints remain enforced
by LiteAgent against the original public schema. The upstream XML parser also enumerates
simple properties without enforcing every object-level cross-field constraint; the patch
restores that behavior for composed roots.

The former 1M shared KV configuration disabled Flash Attention on V100. The local
service now uses --ctx-size 786432 --parallel 12 --no-kv-unified: 12 independent 64K
slots, F16 cache, the same F16 text/vision weights, GPUs 3 and 4. The previous batch's
largest observed prompt was 33978 tokens (p99 23065); 64K is an explicit per-request
context limit and must be recorded in the new batch. No agent step/time budget changes.
The latest startup has Flash Attention enabled and no shared-KV fallback warning.

The existing null XML stop remains required. No Agent/Adapter or evaluator logic change.

## Validation

Evidence: /home/liuxv/liteagent-local-runs/local9b-delivery-repair-20261112/.
Four original failing requests (orders 4,164,172,177) return empty objects before
and complete correct parameters after the patch. Twelve concurrent streaming replays
of those actual requests pass their supplied schemas; median generation speed 9.50
tokens/sec. These are protocol/throughput checks, not OSWorld task scores.
Representative original-task reruns and final full189 results are recorded separately.
