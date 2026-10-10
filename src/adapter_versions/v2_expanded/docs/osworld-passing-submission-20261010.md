# OSWorld 本轮验证与通过题目提交审计（2026-10-10）

本轮按 task.md 固定顺序串行测试 28 题；原始 OSWorld evaluator 判定 **23 PASS / 5 FAIL（82.14%）**。使用 Qwen3.5-9B、非思考模式、Docker/KVM、45 全局步、25 本地步、一次 soft restart、1200 秒 Agent 预算。测试阶段没有修复。

## 后续最新单题结果

Order 91 已完成搜索排序修复并单独通过原始 evaluator：**PASS / reward=1.0**，5 步、471.024 秒、agent_done。实现提交 `84a3a4c`；首轮日志提交 `76ab5c3`。证据见 [单题日志](order91-query-priority-fix-20261010.md)、[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json)、[正式日志](../../../../API_SPLIT_TASK.md#order-91--后续搜索修复-pass2026-10-10) 与 [最新入口](index.md)。下面表格仍记录原始 28 题批次，原始 FAIL 与 23/28 保持不变；JSON 回执另加 isolated_reruns 和 latest_results 字段保存此次单题结果。

Order 99 清单发现与跨文件对照修复的最终回执：`retry5` 为 **PASS / reward=1.0**，45 步、1386.762 秒、`generic_api_only`；manifest 为 `max_steps`，results.json 的 termination_reason 仍未填写（null），`terminated_by_agent=false`。第三张匹配发票的 checker disposition=move 与理由中的匹配/retain 结论矛盾，check 未通过，文件保持原位；未正常 agent_done。

[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json)；[最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json)；[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)；[evaluator 产物索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/evaluator_artifacts/manifest.json)；[单题日志](order99-inventory-repair-20261010.md)；[正式日志](../../../../API_SPLIT_TASK.md#order-99-本轮修复2026-10-10)。交付提交 `f0afcaa`（独立增量补丁与 SHA-256 基线）；收尾证据提交 `37202a6`。评分来自已记录的共享工作区，源码集成边界见单题日志。JSON 的 isolated_reruns/latest_results 已补入 Order 99；原批次 Order 99 FAIL 与 23/28 保持不变。

## 提交边界

用户随后要求提交本轮通过题目的最后未提交改动并更新审计。本次按题目提交 42、54、60、121 中可明确归属的代码块和已有 focused fixtures/tests，并补入 158 的既有 endpoint 回执。其他通过题目的拆分实现已在历史分支提交中；本次不据 PASS 给混合工作区的所有改动背书。

原通过题目提交阶段，91、99、102、107、108 在本轮均 FAIL，对应修复与无法单独归属的共享改动未纳入该阶段提交。后续 Order 91 的搜索排序改动独立提交为 `84a3a4c`，单题正式复跑通过；其他未归属改动不属于该提交。没有修改或删除原始实验文件、task.md 或其他既有源码内容；共享文件采用代码块级暂存。

本轮结果来自完整工作区，其中含其他未提交改动；拆分后的提交快照没有重新进行 OSWorld 评测。因此下面的 PASS 是原始批次结果，不宣称这些孤立提交已单独复跑。提交后的 Python 快照通过语法检查和 Ruff；提交 diff 通过 whitespace 检查，未额外运行单元测试或模型。

## 逐题记录

| Order | 应用 | 原始 evaluator | Reward | 步数 | 秒 | 本次实现提交 | 备注 |
|---:|---|---|---:|---:|---:|---|---|
| 20 | calc | PASS | 1.0 | 8 | 187.362 | — | 实现已在历史提交；本次更新验证回执 |
| 41 | impress | PASS | 1.0 | 7 | 167.772 | — | 实现已在历史提交；本次更新验证回执 |
| 42 | impress | PASS | 1.0 | 8 | 185.139 | 6985f92 | 内容角色约束、格式工具 schema |
| 47 | impress | PASS | 1.0 | 22 | 314.337 | — | stalled_no_progress，但 evaluator 通过 |
| 52 | impress | PASS | 1.0 | 7 | 161.671 | — | 实现已在历史提交；本次更新验证回执 |
| 53 | impress | PASS | 1.0 | 22 | 329.124 | — | stalled_no_progress，但 evaluator 通过 |
| 54 | impress | PASS | 1.0 | 16 | 287.525 | faecaad | cleanup 保存、完整回读与完成控制 |
| 59 | impress | PASS | 1.0 | 5 | 149.556 | — | 实现已在历史提交；本次更新验证回执 |
| 60 | impress | PASS | 1.0 | 13 | 264.510 | 82a3dbb | 图片高度步骤的观测约束与执行校验 |
| 67 | writer | PASS | 1.0 | 4 | 262.598 | — | 实现已在历史提交；本次更新验证回执 |
| 68 | writer | PASS | 1.0 | 4 | 162.636 | — | 实现已在历史提交；本次更新验证回执 |
| 81 | writer | PASS | 1.0 | 4 | 218.805 | — | 实现已在历史提交；本次更新验证回执 |
| 83 | writer | PASS | 1.0 | 3 | 124.532 | — | 实现已在历史提交；本次更新验证回执 |
| 91 | multi_apps | FAIL | 0.0 | 45 | 644.449 | — | 原批次文件获取 404；后续单题 PASS 见上方记录，提交 84a3a4c |
| 95 | multi_apps | PASS | 1.0 | 9 | 344.024 | — | 实现已在历史提交；本次更新验证回执 |
| 96 | multi_apps | PASS | 1.0 | 9 | 333.377 | — | 实现已在历史提交；本次更新验证回执 |
| 99 | multi_apps | FAIL | 0.0 | 45 | 475.856 | — | 45 步上限；结果文件获取 404 |
| 102 | multi_apps | FAIL | 0.0 | 45 | 1012.175 | — | 45 步上限；目标目录缺少 paper01.pdf |
| 107 | multi_apps | FAIL | 0.0 | 45 | 505.698 | — | 45 步上限；supported_rate.xlsx 对照检查未通过 |
| 108 | multi_apps | FAIL | 0.0 | 45 | 657.675 | — | 45 步上限；结果表格获取 404 |
| 121 | multi_apps | PASS | 1.0 | 6 | 284.406 | 0cb4e62 | 完整读取后转入收件人动作发现 |
| 152 | thunderbird | PASS | 1.0 | 2 | 124.849 | — | 实现已在历史提交；本次更新验证回执 |
| 153 | thunderbird | PASS | 1.0 | 3 | 121.201 | — | 实现已在历史提交；本次更新验证回执 |
| 154 | thunderbird | PASS | 1.0 | 3 | 125.068 | — | 实现已在历史提交；本次更新验证回执 |
| 157 | thunderbird | PASS | 1.0 | 2 | 110.001 | — | 实现已在历史提交；本次更新验证回执 |
| 158 | thunderbird | PASS | 1.0 | 3 | 763.666 | — | 长时间停顿后完成 |
| 159 | thunderbird | PASS | 1.0 | 2 | 123.161 | — | 实现已在历史提交；本次更新验证回执 |
| 160 | thunderbird | PASS | 1.0 | 2 | 123.239 | — | 实现已在历史提交；本次更新验证回执 |

## 证据位置

- 首批 20–60 共 9 条完成任务记录：`experiments/osworld-api-split-test-only-20261010/results.json`。该批次被中断，metadata.status 留为 running；9 条任务 reward 均为 1.0。原始 metadata 未改写。
- 续跑 67–160 共 19 条：`experiments/osworld-api-split-test-only-20261010-resume1/results.json`，metadata.status=completed，runner exit=0。
- 精简审计回执：`docs/osworld-passing-submission-20261010.json`，包含全部 task ID、reward、终止状态、原始 trajectory_manifest 位置以及两份结果文件 SHA-256；不提交录像或大体积原始结果。
- 本次单题提交记录：`docs/order42-passing-changes-20261010.md`、`docs/order54-passing-changes-20261010.md`、`docs/order60-passing-changes-20261010.md`、`docs/order121-passing-changes-20261010.md`。记录中的实现提交通过各文件 Git history 可追溯。

## 失败题目正式日志

本轮 91、99、102、107、108 的详细结果已补入 [正式开发日志](../../../../API_SPLIT_TASK.md#2026-10-10-本轮失败题目正式运行日志)，记录原始评分、步数、耗时、终止字段、失败表现和每题完整证据位置。最初仅补日志；后续 Order 91 的单题搜索修复 PASS 已追加至正式日志，原批次结果保持不变。

## 五题单题日志入口核对

2026-10-10 核对并补齐：[Order 91](order91-latest-failure-20261010.md)、[Order 99](order99-latest-failure-20261010.md)、[Order 102](order102-latest-failure-20261010.md)、[Order 107](order107-latest-failure-20261010.md)、[Order 108](order108-latest-failure-20261010.md)。五题均以本轮 resume1 目录为事件来源，逐一核对 45 条事件、原始 result.txt=0.0、结果字段及事件 SHA-256。旧单题运行与本轮失败分别保留。
