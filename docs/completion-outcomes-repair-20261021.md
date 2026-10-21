# 完成判定与修复链路：2026-10-21

开发分支：`codex/api-split-liuxv`。修复起点：`82aaa69`。本次没有改动独立集成工作树。

## 问题和本次行为

原先透视表/图表的完成条件累计成功创建调用；重复替换同名对象也可能满足次数条件，
对象分组或结果错误则不会影响该条件。`workbook.inspect` 对透视表只返回名称和占用
范围，完成门也无法据此区分“按两个维度分别求和”和“两张交叉表”。修复工具面依赖
模型主动提出偏差或提交被拒绝的完成声明；普通阶段过滤又可能隐藏已经读过的读取工具。

新增 `completion_outcomes.py`，从用户指令和实际 Adapter 证据生成缺项列表：

- `code`、`kind`：区分缺少观察与已观察到不符。
- `target`、`expected`、`observed`、`evidence_step`：明确对象、要求、实际状态和证据位置。
- `repair_actions`：列出解决该缺项可用的公开动作。

完成门在 `missing` 和 `outcome_issues` 中报告这些缺项。拒绝回包保留结构化诊断，
模型上下文在压缩后补充同一份实时缺项列表。模型无须先发现偏差、调用
`completion_revise` 或提交一次 `propose_done`，即可取得检查、替换、保存工具。
缺项没有消失前，阶段过滤和“只剩保存/结束”的收缩不能遮住这些工具。

修复仍由模型选择完整参数并调用公开 API，运行时不自动创建对象、不改写调用参数。
如果新的原生检查证明前一次正确请求没有实现要求，可再次执行模型选择的同名
`replace=true` 修复；旧的矛盾证据不能无限授权相同请求重试。

## 本版核验范围

1. Calc 的透视表/图表数量改为最终原生对象清单，重复调用不计为多个结果。
2. 对能从指令和唯一源表头绑定的“每个分类分别求总和”透视表，检查分组、聚合函数、
   百分比模式、源工作表和完整源范围；每个请求的分类恰好对应一个独立结果。
3. 检查透视表输出范围是否重叠。分类汇总值、缺失/重复分类和总计对照完整源数据计算，
   最终输出必须在最新修改及保存后完整回读；允许一次读取包含多个目标的完整矩形。
4. 最终原生清单必须晚于最新修改及保存；旧清单不能声称刚创建的表仍然不存在。
   不完整清单、原生检查失败、截断/局部/无关读取、已知不同工作簿的读取不能充当证据。
5. 优先使用完整的 `adapter_response.result`，不把模型上下文被裁剪当作对象不存在。
   搜索、完成声明和审计事件不算文件修改。

UNO 检查增加透视表字段定义和源范围，使用 `getCount/getByIndex` 读取持久化对象，
避免已保存透视表 `getElementNames()` 返回空字段名的问题。`range.read` 返回工作簿 URL，
便于检查读取是否属于当前目标。

这是通用缺项与修复接口的第一版具体检查器。复杂交叉表、百分比、自定义分组等请求
继续使用已有语义检查和模型审查，不强行解释成独立求和。图表本次补的是原生对象数量，
没有宣称已经验证所有图表设置；其他应用也没有因此获得任意自然语言要求的完整自动证明。

## 单题证据与验证

诊断题目为配置 `order: 4` / `source_order: 70`，原始 UUID
`535364ea-05bd-46ea-9937-9f55c68507e8`。题目编号只用于配置和开发记录，不参与运行时判断。
完整阅读原始任务及失败事件后确认：两张对象实际是互换行列维度的交叉表，原完成门只
要求补一次保存。

原失败证据目录：
`/home/liuxv/liteagent1021/runs/liteagent1021-thinking100-20261021T062953289949Z/results/workers/worker-04/raw/run-1/04-libreoffice_calc-535364ea-05bd-46ea-9937-9f55c68507e8/`。

旧失败轨迹回放：
`/home/liuxv/liteagent-local-runs/completion-outcome-repair-20261021/old-failure-replay.json`。
原第 8 步及原来会通过的第 10 步现在都被拒绝；原生字段尚未返回时，报告定义证据缺失，
不会用原模型调用参数冒充原生对象定义。

进一步只读提取失败运行保存的 `result-00-SummerSales.xlsx` 的原生 pivot/cache XML，
补充到历史检查事件做独立对照，得到两条 `pivot.definition_mismatch`，分别指出两张表
的额外列分组；同时确认无需先拒绝完成声明，修复工具已直接开放。完整报告：
`/home/liuxv/liteagent-local-runs/completion-outcome-repair-20261021/saved-failure-outcome-replay.json`。
这一步没有读取 golden，也没有把离线提取代码或题目参数接入实际运行时。

定向检查：95 通过，22 排除。排除的两组测试中有 20 项在原始 HEAD 独立导出目录也失败：
18 项将仅含协议方法的 mixin 当作完整 agent 使用，2 项期待旧的转发 schema 结构。
没有以这些既存失败为理由修改无关运行时代码。另外 2 项同组直接调用测试被选择表达式一并排除。

```bash
PYTHONPATH=$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  src/adapter_versions/v2_expanded/tests/test_completion_outcomes.py \
  src/adapter_versions/v2_expanded/tests/test_calc_pivot_observation.py \
  src/adapter_versions/v2_expanded/tests/test_calc_date_observation.py \
  src/adapter_versions/v2_expanded/tests/test_calc_pivot_output_contract.py \
  src/adapter_versions/v2_expanded/tests/test_completion_observed_mismatch_recovery.py \
  src/adapter_versions/v2_expanded/tests/test_hybrid_gui_completion.py \
  -k 'not output_and_optional_readback_reach_actual_model_messages and not relative_pivot_destination_contract_preserves_model_arguments'
```

仅复跑这一题，使用隔离源码快照、原始任务与 evaluator；不修改 golden 或 evaluator。
运行目录：`/home/liuxv/liteagent-local-runs/completion-outcome-repair-20261021/order004-verified/`。
正式结果：`passed`，原始 evaluator `reward=1.0`，`generic_api_only`。
第 10 步完成声明因缺少保存被拒绝；第 11 步保存，第 12 步原生检查，
第 13/14 步回读两张输出，第 15 步完成门通过，随后终态审计通过
（审计独立记录在 `model_audits.jsonl`，不另计为执行步）。
运行源码和配置完整性检查均为 true。源码摘要：
`1c1e1f8baaeaccbbc149aa530a7fa25d11796e28938469f785e1ff66211b9f74`。

本次真实模型直接创建了正确的两张独立分组表；它验证的是自动补齐保存/最终检查/回读的
闭环。错误定义的识别与替换工具开放由旧失败文件回放及定向执行测试验证，没有把本次
成功运行描述成模型曾经修正过错误定义。

结果：`order004-verified/results/results.json`；完整事件：
`order004-verified/results/raw/run-1/04-libreoffice_calc-535364ea-05bd-46ea-9937-9f55c68507e8/lite_agent_events.jsonl`；
汇总：`/home/liuxv/liteagent-local-runs/completion-outcome-repair-20261021/verification-summary.json`。

此前两次启动在调试检查阶段主动停止；`order004-run2`
执行到原生透视表检查，发现 UNO 的普通聚合可返回 `Reference=None`，已将该合法空值
解释为无变换并补充测试。`order004-run3` 在源读取阶段停止，随后统一了完整 hint 与
截断原始回包的证据优先级，并补充“已发出但失败的修改使旧证据失效”的检查。
`order004-run4` 在创建阶段停止，补齐修复工具面对真实 catalog 搜索结果的承接，避免
搜索到的其他公开修复工具被早返回逻辑遮住。上述诊断运行均未记作正式任务验收。

`order004-final` 验证了真实原生定义读取正常，以及完成声明缺少源读取时被拒绝。
模型随后只读取表头，暴露“完整返回矩形不等于完整数据源”的边界，最终版将源证据
绑定到原生 used range（没有 used range 时才使用原生对象的源范围），并要求至少一行
数据。只读表头或局部数据不会触发错误的定义修复建议，而会继续报告完整源证据缺失。
