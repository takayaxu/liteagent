# OSWorld 本轮验证与通过题目提交审计（2026-10-10）

本轮按 task.md 固定顺序串行测试 28 题；原始 OSWorld evaluator 判定 **23 PASS / 5 FAIL（82.14%）**。使用 Qwen3.5-9B、非思考模式、Docker/KVM、45 全局步、25 本地步、一次 soft restart、1200 秒 Agent 预算。测试阶段没有修复。

## 提交边界

用户随后要求提交本轮通过题目的最后未提交改动并更新审计。本次按题目提交 42、54、60、121 中可明确归属的代码块和已有 focused fixtures/tests，并补入 158 的既有 endpoint 回执。其他通过题目的拆分实现已在历史分支提交中；本次不据 PASS 给混合工作区的所有改动背书。

91、99、102、107、108 在本轮均 FAIL，对应后续修复、相关实验、组织分类 checker、ECS/GRF 写回以及无法单独归属的共享协议/运行器改动继续保留为未提交。没有修改或删除原始实验文件、task.md 或其他既有源码内容；共享文件采用代码块级暂存。

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
| 91 | multi_apps | FAIL | 0.0 | 45 | 644.449 | — | 45 步上限；结果文件获取 404 |
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

本轮 91、99、102、107、108 的详细结果已补入 [正式开发日志](../../../../API_SPLIT_TASK.md#2026-10-10-本轮失败题目正式运行日志)，记录原始评分、步数、耗时、终止字段、失败表现和每题完整证据位置。此次只补日志，不做修复或复跑，原始结果保持不变。
