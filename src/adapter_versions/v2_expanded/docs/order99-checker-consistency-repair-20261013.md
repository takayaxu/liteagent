# Order 99：checker 判定与理由一致性修复（2026-10-13）

任务：`337d318b-aa07-4f4f-b763-89d9a2dd013f`。固定入口：[order99-latest.md](order99-latest.md)。

## 原失败与原因

人工核对第二轮完整复跑的任务定义、全部 45 条事件、实际 Adapter 调用、模型请求、verification 和评分。原轨迹：[事件](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-full-rerun2-20261012/order-99/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)。该轮 FAIL / 0.0，45 步，step_budget_exhausted。

第 8 步不匹配发票已移动且嵌套 Adapter verification=true；第 12 步第二张匹配发票成功保留。第 14 步正确读取第三张匹配发票。从第 15 到 45 步，执行模型请求 retain；checker 原始返回 disposition=move，却在 reason 中说明金额/商户匹配且应保留。31 个 checker 请求的规范化内容完全相同，temperature=0，第 26 步 soft restart 后仍重复。

checker 现有契约先输出 disposition/destination_directory，再输出 reason；运行时仅校验 schema、引用和与执行模型判定的一致性。JSON 合法的理由/动作矛盾不会触发已有 schema 重试；外层再次 verify 时没有反馈此前矛盾，形成相同请求循环。字段生成次序是可改善的结构因素，不据轨迹推断模型内部原因。

预算耗尽后 runner 向 OSWorld 发送 FAIL，原始 evaluator 因最后动作为 FAIL 直接返回 0；evaluator 产物捕获随后取得的目标/expected PDF 哈希相同。因此原评分 0 保留，不能用文件相同覆盖它。

## 本题通用增量

仅修改 `integrations/lite_agent/organization_validation.py`：

- checker schema 和提示统一为 observed_type、evidence_quote、reason、disposition、destination_directory；先说明事实和动作结论，再生成实现该结论的字段。
- 首次 checker 判定与执行模型不同，最多增加一次独立复核。反馈只包含 checker 自己的五个判定字段，要求重读原始证据、核对理由/动作/目录；不提供执行模型的动作、理由或期望答案，允许有证据的原判定保持不变。
- 沿用最多两次调用的边界和已有 schema/引用纠错。最终不一致仍不放行；程序不解析理由来强制覆盖判定，不移动或跳过对象。
- 原始 checker draft 留在诊断轨迹；反馈不包含原始响应元数据。保留有界只读 PDF、显式 find 与单对象 rename，没有新增大粒度 API、任务路由、答案或 golden。

## 最小验证

- 已有 focused 检查：`PYTHONPATH=src/adapter_versions/v2_expanded /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_filesystem_move_discovery.py -k 'independent or checker or checked_move'`：13 passed，57 deselected。
- 临时 4 项 contract：两个方向的矛盾可纠正；真实独立分歧仍失败；原本一致只调用一次；执行模型答案与原始响应元数据不进入 checker。未新增通用测试。
- `/opt/anaconda3/bin/ruff check src/adapter_versions/v2_expanded/integrations/lite_agent/organization_validation.py` 通过。共享 Python 环境的 Ruff wrapper 缺失，改用现有 Ruff 可执行文件。
- 原第 15 步证据用相同 Qwen3.5-9B/non_thinking/temperature=0 在线重放：一次返回 retain，reason 与动作一致。
- 将原矛盾 draft 注入首次返回，再真实调用同一模型复核：第二次返回 retain，通过校验。证据：[直接重放](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/live-replay.json)、[纠错重放](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/live-correction-replay.json)。

## 单题复跑

使用与原失败相同的模型及预算：45 初始步、75 硬上限、25 本地步、1 次 soft restart、1800 秒、8192 输出 tokens；只运行 Order 99，不运行其他题或全量评测。

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
/opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
--config src/adapter_versions/v2_expanded/experiments/configs/osworld-order99-checker-consistency-20261013.json \
--result-dir src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013 \
--orders 99 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
--reasoning-mode non_thinking --max-steps 75 --initial-step-budget 45 \
--max-local-steps 25 --max-soft-restarts 1 --max-no-progress-steps 8 \
--max-agent-seconds 1800 --max-output-tokens 8192 --request-timeout 240 \
--model-retries 3 --top-k 7 --temperature 0
```

## 交付边界

该源码文件在本次开始时已存在、未跟踪，含此前多个题目的共享依赖；本次实际修复已应用活动源码。交付 [独立增量补丁](order99-checker-consistency-20261013.patch) 和 [修复前后 SHA-256](order99-checker-consistency-20261013-hashes.json)，只包含本次改动，不把整个未跟踪源文件归入本题。不宣称提交裸 HEAD 包含所有工作区运行依赖；评分对应记录的共享工作区。

## 最终回执

**PASS / reward=1.0，18 步，495.091 秒，agent_done，terminated_by_agent=true**；北京时间 2026-10-13T11:08:26.751075+08:00 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl) / [轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json)；[机器可读回执](order99-checker-consistency-result-20261013.json)。

第 7–8 步判定并移动唯一不匹配发票，物理 verification=true。第 10 步执行模型对匹配发票提出 move，checker 独立复核仍坚持有证据的 retain，未被执行模型答案诱导；第 11–12 步模型纠正并保留。第 13 步旧 reader 路径被拒绝，第 14 步恢复。原卡点第 15 步 checker 直接返回 retain，reason 与动作一致；第 16 步成功保留并推进。第 17 步完成声明仍描述未完成工作，被 completion gate 拒绝；第 18 步纠正完成声明后正常结束。无需 soft restart。

实际 6 个 Adapter 调用均返回 ok（find、4 次 PDF 读取、1 次 rename）。manifest 的 adapter_verifier_passed_calls 仍为 0，保留原始汇总字段；第 8 步嵌套物理 verification=true。正式 result.txt=1.0，evaluator 目标 PDF 与 expected SHA-256 相同。

交付提交 `e6c8e1e`。本题补丁已校验：对保存的共享源码基线应用补丁后，SHA-256 与活动修复源码完全一致。仅复跑当前题；两轮完整批次及历史失败、历史 PASS 保持原记录。
