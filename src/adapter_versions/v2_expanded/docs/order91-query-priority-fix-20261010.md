# Order 91 工具搜索最小修复（2026-10-10）

> 2026-10-10 入口核对：Order 91 本轮批次为 FAIL；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-91)。下文是本文件所述运行的记录，历史路径不作为最新入口。

## 最新单题结果入口

**PASS / reward=1.0**，`termination_reason=agent_done`，5 步，471.024 秒。运行开始于北京时间 2026-10-10 21:15:54；工具事件区间为 21:21:37.448572–21:23:07.063318（Asia/Shanghai）。耗时包含初始化/部署等阶段，工具事件区间不等于完整运行耗时。

- [正式结果 results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json)
- [5 条工具事件 lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)
- [完整轨迹 trajectory_manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/trajectory_manifest.json)
- [正式评分 result.txt（1.0）](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/result.txt)
- [evaluator 产物 manifest.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/evaluator_artifacts/manifest.json)
- [修复前失败日志](order91-latest-failure-20261010.md)、[正式开发日志](../../../../API_SPLIT_TASK.md#order-91--后续搜索修复-pass2026-10-10)、[API 审计](../../../../docs/api-granularity-audit-20260920.md)、[最新结果索引](index.md)

本次单题 PASS 单独记账，原固定 28 题批次仍为 23 PASS / 5 FAIL。实现提交 `84a3a4c`，首轮日志与配置提交 `76ab5c3`。

| 证据文件 | SHA-256 |
|---|---|
| results.json | `5205206e978624bd9b28aec0b27da877b707d8a1019b275c24bdc90d8f82d1c1` |
| lite_agent_events.jsonl | `7b19f3c84b8a20150172c5f64df8b63f4be9c488ed37a2c9f3bd47fc60066aa4` |
| result.txt | `5717e7c840171019a4eeab5b79a7f894a4986eaff93d04ec5b12c9a189f594bf` |
| evaluator_artifacts/manifest.json | `244a5f47f25b997f1574a5b3ed19f6dd1c3882a9b4a8acebaef0f4e2eafc3a78` |

## 原始失败诊断

- Task ID：`d9b7c649-c975-4f53-88f5-940b29c47247`；仅处理当前题。
- 已完整阅读题面、任务定义和最后一次失败轨迹。原始目录：`experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/`。证据包括 `original_instruction.txt`、`lite_agent_events.jsonl`、`llm_call_log.jsonl`、`llm_requests/`、`result.txt` 和 `evaluator_artifacts/manifest.json`。
- 原始结果：45 步，644.449 秒，`status=failed`、`reward=0.0`。45 步均重复搜索 `Thunderbird messages query daily folder`；每次只返回文件查找、目录创建、Calc 读取/检查和文件复制六个工具。无邮件 Adapter 调用、无工作簿创建调用，evaluator 获取桌面结果文件返回 404。
- 原因：工具已注册，但 Multi-Apps 搜索将查询和全题指令词混合后触发文件整理、文件读取和工作簿检查的高额加分，盖过模型当前明确请求的 Thunderbird 邮件查询。

## 最小实现

仅修改 `integrations/lite_agent/tool_catalog.py` 的 Multi-Apps 搜索排序。当前查询明确包含公开 Adapter 的应用名时，该应用中操作名称与原始查询词匹配的结果优先；操作名称匹配数量用于同组排序，既有分数继续打破平局。其他结果仍保留为后备；没有明确应用名的查询保留原排序。没有修改 API/schema、模型参数、邮件数据、题面、evaluator 或旧轨迹，也没有新增任务专用路由。

实现提交：`84a3a4c`（`fix(order91): prioritize queried application and operation`）。

## 最小验证与复跑

- 临时内存 contract 检查共 8 项通过：原始自然语言搜索在 limit=1 时返回邮件查询、Calc 新建搜索首位匹配、精确 action 搜索、排除路由、零 limit，以及三种未指定应用/精确 action 查询与改动前结果一致。未扩建测试集。
- `/opt/anaconda3/bin/ruff check src/adapter_versions/v2_expanded/integrations/lite_agent/tool_catalog.py` 与改动差异检查通过。
- 单题配置：`experiments/configs/osworld-order91-qwen-20261010-query-priority.json`。模型为 `Qwen3.5-9B`、non_thinking，沿用本轮 45/25 步、1200 秒预算。
- 部署期间 OCR 依赖安装超时，Runner 自动重试后成功，只有一次模型 episode。
- 正式结果：`status=passed`、`reward=1.0`、`termination_reason=agent_done`、5 步；`results.json` 位于 `experiments/osworld-order91-qwen-20261010-query-priority/`。
- 新轨迹：`experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/`。模型实际选择精确搜索名，调用顺序为 `tools_search -> messages.query -> tools_search -> workbook.create_new -> propose_done`。邮件返回 5 条、时间升序，Adapter verification 成功；Calc 返回 `A1:E6`、30 单元格、`saved=true`；正式 evaluator 成功读取 5075 字节的结果文件并返回 1.0。原来的自然语言搜索失败通过上述 contract 复现检查验证修复。

实际命令（项目根目录执行）：

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
/opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
--config src/adapter_versions/v2_expanded/experiments/configs/osworld-order91-qwen-20261010-query-priority.json \
--result-dir src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority \
--orders 91 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
--reasoning-mode non_thinking --max-steps 45 --max-local-steps 25 \
--max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1200 \
--max-output-tokens 8192 --request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```
