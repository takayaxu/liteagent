# Order 108 写回审计与集成交接

> 2026-10-10 入口核对：Order 108 本轮批次为 FAIL；最新已核对运行为 FAIL。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-108)。下文是本文件所述运行的记录，历史路径不作为最新入口。

## 本轮最新失败入口（2026-10-10）

后续固定 28 题批次 Order 108 为 **FAIL / reward=0.0**，45 步，657.675 秒。完整本轮轨迹、评分和原始文件哈希见 [单题最新失败日志](order108-latest-failure-20261010.md)。本文以下内容是此前独立运行/修复历史，不代表本轮最新结果。

日期：2026-09-30
任务：OSWorld Order 108，GRF 2019-2023 HKU `Computing Science & Information Technology` 结果写入 `GRF-p5y.xlsx`。

## 最终状态

- OSWorld：`status=passed`
- reward：`1.0`
- termination：`agent_done`
- 路径：`generic_api_only`
- 工具事件：12 个；全局回合：13 个
- completion rejection：0
- terminal audit：已完成，`review_step=13`

最终结果目录：

`experiments/local-order108-current-20260930-percent-format-rerun1/`

## 状态过程

| 阶段 | 事件 | 状态 |
| --- | --- | --- |
| 来源发现 | `filesystem.find` 找到 `grf19.pdf` 至 `grf23.pdf` | 5 个源文件完整存在 |
| 结构化读取 | 对 5 个 PDF 分别调用 `pdf.tables.inspect` | 目标学科行和 HKU Application/Supported 列均被观察 |
| 首次写回 | `workbook.create_new` | 被确定性校验拒绝；模型提交了错误的 41/64、46/73 等数据 |
| 结构化修复 | `repair_confirm(repair_id=grf-workbook-create-repair-10)` | runner 从内存 repair contract 注入正确 rows；模型没有重写 rows 或重读 PDF |
| 修复写回 | `workbook.create_new` | `executed=true`、`saved=true`、`verification_passed=true`，数据范围 `A1:D6` |
| 完成声明 | `propose_done` | completion gate 通过 |
| 终端审计 | 第二个 `propose_done` 审计回合 | 确认终端结果并提交 `agent_done` |
| OSWorld evaluator | 读取 xlsx 和 CSV 并执行 `sheet_print` 比较 | 通过，reward `1.0` |

## 写回审计

repair contract 注入的最终 rows 为：

```text
2019, 25, 7, 28.0
2020, 17, 7, 41.18
2021, 23, 7, 30.43
2022, 23, 9, 39.13
2023, 20, 5, 25.0
```

这些值保持为“百分数点”数值，而不是 `0.28` 形式的小数比例。写入器在识别精确表头
`["Year", "#Applied", "#Supported", "Success Rate"]` 后，对 `D2:D6` 应用
`0.00"%"` 格式，因此导出显示为两位小数并带百分号。

实现位置：

- [uno_worker.py](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/calc_adapter/uno_worker.py:1355)
- [回归测试](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/tests/test_calc_create_new_overwrite.py:109)

使用字面量百分号是有意的：若对 `28.0` 直接使用标准 `0.00%`，LibreOffice 会显示为 `2800.00%`。

## Evaluator 证据

最终 CSV 内容为：

```text
Year,#Applied,#Supported,Success Rate
2019,25,7,28.00%
2020,17,7,41.18%
2021,23,7,30.43%
2022,23,9,39.13%
2023,20,5,25.00%
```

结果文件和原始事件：

- [worker results](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/local-order108-current-20260930-percent-format-rerun1/workers/worker-00/results.json)
- [事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/local-order108-current-20260930-percent-format-rerun1/workers/worker-00/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/lite_agent_events.jsonl)
- [模型审计轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/local-order108-current-20260930-percent-format-rerun1/workers/worker-00/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/model_audits.jsonl)
- [evaluator artifacts manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/local-order108-current-20260930-percent-format-rerun1/workers/worker-00/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/evaluator_artifacts/manifest.json)

## 集成注意事项

1. 保留 repair contract 的单向约束：模型只确认 `repair_id`，不能重新手写 rows、搜索或重读来源。
2. 保留写入前的目标行/目标列确定性校验；首轮错误写回必须在 adapter 执行前拒绝。
3. 百分比格式必须与存储单位匹配：当前 GRF contract 存储的是百分数点，使用 `0.00"%"`；若未来改存 `0.28`，才使用标准 `0.00%`。
4. 集成后至少运行 `test_calc_create_new_overwrite.py`、`test_recovery_surface.py`、`test_protocol_recovery.py`，并复核导出的 CSV，而不能只检查 xlsx 内部数值。
5. 本轮是本地单题验证，不是 baseline promotion 证据；不要覆盖旧实验目录或复用旧 source seal。

## 验证记录

本次相关测试结果：`123 passed`；Ruff 和 `git diff --check` 均通过。
