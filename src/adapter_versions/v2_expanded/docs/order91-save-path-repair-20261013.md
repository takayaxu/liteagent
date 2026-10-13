# Order 91：保存父目录发现与数据保留修复（2026-10-13）

Order 91 保存路径发现与恢复修复：**PASS / reward=1.0**，10 步、359.121 秒、agent_done；北京时间 2026-10-13 10:40:53 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-save-path-repair-20261013.md)。第二轮完整批次保持原记录，本次单题通过独立登记。

Task ID：`d9b7c649-c975-4f53-88f5-940b29c47247`。本轮只修复/复跑 Order 91；一轮正式尝试通过，原 evaluator 与 expected 未修改。

## 最新失败依据

人工读取原指令、任务定义、35条事件及模型请求schema/返回/verification/evaluator。daily 最新五封邮件按时间升序，写桌面report.xlsx，五个字段由模型从查询结果组织。

第二轮失败于北京时间2026-10-12 22:07:28：0.0、35步、729.505秒、stalled_no_progress。[失败结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-full-rerun2-20261012/order-91/results.json)；[失败事件](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-full-rerun2-20261012/order-91/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)；[失败日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-full-rerun2-20261012.md)。

- 第4步创建空白表，5–6步自行纠正五列表头范围，7步成功写入五封邮件25格；创建后的工具交接修复有效。
- 第8–9步错误 /desktop/report.xlsx 保存失败并重复；第14步错误地调用in-place save，未保存文档要求save_as。
- 第17步猜测 /Users/anonym/Desktop/report.xlsx，持续失败；没有执行任何路径发现。搜索recovery把整个save_as列入excluded_routes，但实际工具schema仍提供save_as。
- 第22步soft restart保留VM；26步把三行值写四行范围拒绝，27步补空白行覆盖已完成数据，丢掉一封邮件。28–35步继续猜错父目录，改.ods也失败。
- evaluator取回 /home/user/Desktop/report.xlsx 两组三次失败，result=[null]，原始评分0.0。

## 本题最小通用修复

- Calc save_as 在任何计算/保存之前检查父目录存在、是目录且可写。失败返回 OUTPUT_PARENT_INVALID、实际父目录和状态、运行用户home、os.filesystem.find入口；不创建目录、不改URL、不写文件或单元格。原生保存异常也明确现有工作簿内容仍在，只需修正保存参数。
- 模型完成写入尝试后，创建交接调用面提供 os.filesystem.find。模型选择 roots/name_patterns/kind，工具返回真实目录，模型决定文件名和URL；提示 ~/ 是运行用户home，不注入题目路径或自动发现/保存。
- 一旦模型尝试保存而尚未成功，普通交接只展示读回、目录发现、save_as，移除鼓励重写的默认write路由；保留跨soft restart的成功写入。明确数据有误时模型仍可显式搜索range.write，未禁止合法编辑。
- 参数化action始终可搜索；重复失败仅拦截对应标准化参数。只有无参数API的一种请求能等价于整个action。搜索recovery块明确 exact_normalized_arguments，不再让某个坏URL排除全部save_as；模型可提交不同URL。
- 六个文件增量：generic_routing.py、tool_surface.py、state_core.py、execution_engine.py、calc_adapter/uno_worker.py、calc_adapter/tool_manifest.py。create_new仍只新建空表，write/save仍独立；没有题目ID、golden、固定布局、答案或隐藏参数注入。

## 定向验证与运行条件

临时focused replay对原35步失败账本验证：写入后可find；保存失败后保留save/read/find而不提供默认write；原坏URL被拦截而改URL不被拦截，search仍返回save_as；soft restart继续保留数据；精确写入搜索仍能显式申请编辑。父目录不存在或是文件时，mock确认calculateAll/storeAsURL均未调用且未创建目录；合法目录可保存。没有增加仓库通用测试或运行其他题。六文件Ruff、diff检查通过。

正式episode北京时间 2026-10-13 10:34:54–2026-10-13 10:40:53。Qwen3.5-9B、non_thinking、temperature0、8192tokens、初始45/硬上限75、本地25、soft restart上限1、1800秒，新VM，与最新第二轮批次对应条件一致。实际step_budget={"policy": "observed_organization_inventory", "initial_limit": 45, "hard_limit": 75, "effective_limit": 45, "estimate": null}。

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
/var/lib/liteagent-shared/python-env/bin/python -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
--config src/adapter_versions/v2_expanded/experiments/configs/osworld-order91-save-path-20261013.json \
--result-dir src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013 \
--orders 91 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B --reasoning-mode non_thinking \
--max-steps 75 --initial-step-budget 45 --max-local-steps 25 --max-soft-restarts 1 \
--max-no-progress-steps 8 --max-agent-seconds 1800 --max-output-tokens 8192 \
--request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```

## 实际调用

| 步骤 | 操作 | 参数摘要 | 结果 |
|---|---|---|---|
| 1 | tools_search | Thunderbird messages query latest 5 daily folder | 成功 |
| 2 | messages.query | {'folder_name': 'daily', 'limit': 5, 'select_from': 'latest', 'order': 'ascending'} | 成功 |
| 3 | workbook.read_file | {'path': '/home/user/Desktop/report.xlsx'} | FILE_NOT_FOUND |
| 4 | tools_search | libreoffice_calc workbook create new | 成功 |
| 5 | workbook.create_new | {} | 成功 |
| 6 | range.write | {'sheet': 'Sheet1', 'range': 'A1:F1'} | RANGE_INVALID |
| 7 | range.write | {'sheet': 'Sheet1', 'range': 'A1:E1'} | 成功 |
| 8 | range.write | {'sheet': 'Sheet1', 'range': 'A2:E6'} | 成功 |
| 9 | workbook.save_as | {'url': 'file:///home/user/Desktop/report.xlsx'} | 成功 |
| 10 | propose_done | {} | 成功 |

结果/manifest终止原因分别为 agent_done / agent_done。episode_control={"global_steps": 11, "local_step": 10, "retry": 0, "soft_restart_count": 0, "soft_restart_vm_policy": "preserve_current_vm", "model_audit_count": 10, "model_audit_trace": "model_audits.jsonl", "pending_model_audit": null}。原始汇总字段保留；实际事件嵌套verification单独核对。实际XLSX为6×5，表头及25个数据单元格逐格与查询结果一致，空CC为blank，附件数为数值。数据写完后无再次写入；10次审计全部完成，0soft restart。此次合法父目录通过preflight，没有实际执行filesystem.find或错误父目录分支；这些恢复分支由保留失败replay及定向mock验证。模型completion evidence把25格称为含表头，实际为5格表头+25格数据，原文保留，不改写证据。

[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/result.txt)；[轨迹manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/trajectory_manifest.json)；[evaluator产物清单](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/evaluator_artifacts/manifest.json)；[完整SHA-256回执](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-save-path-20261013/result-receipt.json)；[Runner源码seal](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-save-path-20261013/runner-source-seal.json)。


定向检查实际命令：

```bash
PYTHONPATH=src/adapter_versions/v2_expanded /var/lib/liteagent-shared/python-env/bin/python /tmp/order91-save-path-20261013/focused_check.py
/opt/anaconda3/bin/ruff check \
 src/adapter_versions/v2_expanded/integrations/lite_agent/generic_routing.py \
 src/adapter_versions/v2_expanded/integrations/lite_agent/tool_surface.py \
 src/adapter_versions/v2_expanded/integrations/lite_agent/state_core.py \
 src/adapter_versions/v2_expanded/integrations/lite_agent/execution_engine.py \
 src/adapter_versions/v2_expanded/calc_adapter/uno_worker.py \
 src/adapter_versions/v2_expanded/calc_adapter/tool_manifest.py
```

源码增量对 HEAD 的 git apply --cached --check 在两处创建交接上下文不匹配；交付以本次共享基线补丁和hash为准。补丁反向检查通过，确认已准确应用。

## 交付与写回边界

共享工作区有其他题未提交修改。本题六文件增量已应用；[独立源码补丁](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-save-path-20261013/implementation.patch) 与 [前后基线SHA-256](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-save-path-20261013/source-hashes.json) 单独交付，不整文件混入其他题。五个模型进程文件hash与本次Runner启动seal一致；Calc worker hash与guest_file_inventory中的实际部署文件一致。当前工作区已应用补丁，集成时不要重复应用；本次PASS对应seal中组合源码，不给全部共享修改背书。

审计、正式日志、单题日志、统一最新MD/JSON及第二轮followup已写回。批次records及聚合不改写，其他题记录不更新；原始失败轨迹不覆盖。提交号见收尾回执。

Order 91 本题增量交付提交：`d90bcd0`（六文件源码增量补丁、基线hash、配置、PASS回执与日志；活动源码已应用于共享工作区，未整文件提交其他题修改）。
