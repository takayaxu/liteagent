# Order 91：创建空表后的显式写入与保存（2026-10-12）

<!-- order91-save-path-20261013 begin -->
Order 91 保存路径发现与恢复修复：**PASS / reward=1.0**，10 步、359.121 秒、agent_done；北京时间 2026-10-13 10:40:53 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-save-path-repair-20261013.md)。第二轮完整批次保持原记录，本次单题通过独立登记。
<!-- order91-save-path-20261013 end -->

Order 91 创建、写入、保存独立调用修复：**PASS / reward=1.0**，21 步、465.449 秒、agent_done；北京时间 2026-10-12 17:37:12 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-create-write-save-20261012.md)。10 月 12 日完整批次仍保留 25 PASS、2 FAIL、1 未评分，本次单题结果单独登记。

Task ID：`d9b7c649-c975-4f53-88f5-940b29c47247`。本轮仅修复并复跑 Order 91，一次正式尝试通过；原 evaluator 与 expected 未修改。

## 修复依据

人工核对原指令、任务定义及完整失败链路：daily 文件夹最新五封邮件按时间升序，将 sender_name、sender_address、subject、CC、number_of_attachments 写入桌面 report.xlsx。

最近失败于北京时间 2026-10-12 14:05:43 完成：0.0，23 步，728.76 秒，stalled_no_progress。[保留结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-full-rerun-20261012/order-91/results.json)；[完整失败轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-full-rerun-20261012/order-91/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)；[失败单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-full-rerun-20261012.md)。

- 第 1–2 步已成功发现并调用 messages.query；10 月 10 日搜索优先级修复有效。
- 第 3–4 步误读尚未存在的输出文件；第 6 步创建空表，saved=false、written_cells=0。
- 第 7–15 步九次重复 inspect；创建返回虽提示后续写入/保存，当时可调用 schema 未展示对应路由。
- soft restart 保留 VM；第 20 步才搜索 write，第 21 步五列表头写到六列范围，RANGE_INVALID；第 23 步重复原错误，最终未生成 report.xlsx。

10 月 10 日历史通过时 create_new 仍接受 headers/rows 并保存；本次保持现有拆分，不恢复该大粒度契约。

## 最小实现

1. generic_routing.created_workbook_routes 仅根据执行账本中的 Calc 创建结果识别空白未保存工作簿，立即提供 range.write 与 workbook.save_as；发生写入尝试后提供 range.read。保存、打开/读取另一工作簿、转换或观察到已有 URL 后结束该交接。
2. tool_surface 用创建后的写入/保存调用面替换此前的邮件/文件读取与重复 inspect 候选，保留 tools_search；当前精确显式搜索优先。模型自行选择调用、工作表、数据矩阵、范围和输出 URL。
3. range.write 的维度错误直接说明目标与矩阵的实际行列数，要求改正后重新提交；说明 A1 范围端点按包含方式计数。严格校验仍发生在写入前，不自动缩范围或补值。

四个活动文件已修改：generic_routing.py、tool_surface.py、calc_adapter/schema.py、calc_adapter/tool_manifest.py。本次未新增 action，没有题目 ID、答案、固定范围或完整题目操作序列进入运行时代码。

## 最小验证

- 临时定向 replay：原失败第 6 步之后立即展示 write/save，九次旧 inspect 后仍有消费工具；五列矩阵写六列拒绝且反馈计数，匹配范围通过；失败写入可读回；成功 save_as 后交接结束。未新增仓库测试或运行通用回归。
- 四个改动 Python 文件 Ruff 与 diff 检查通过。
- 真实 request_0005 schema 的 x-allowed-routes 仅为 range.write、workbook.save_as，下一步即实际调用写入，证明工具已展示。
- 实际产物为 6×5：表头与五行数据逐格对照 messages.query 输出一致，顺序一致，空 CC 为 blank，附件数为数值；原离线 evaluator result.txt=1.0。
- 四个源码哈希与本次 Runner 的启动 seal、当前工作区一致。完整 seal 及哈希见 [源码封存](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-create-write-save-20261012/runner-source-seal.json) 和 [增量基线哈希](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-create-write-save-20261012/source-hashes.json)。

```bash
/opt/anaconda3/bin/ruff check \
 src/adapter_versions/v2_expanded/integrations/lite_agent/generic_routing.py \
 src/adapter_versions/v2_expanded/integrations/lite_agent/tool_surface.py \
 src/adapter_versions/v2_expanded/calc_adapter/schema.py \
 src/adapter_versions/v2_expanded/calc_adapter/tool_manifest.py
```

## 正式单题结果与限制

Episode UTC 2026-10-12 09:29:26.879452–09:37:12.328634（北京时间 17:29:26–17:37:12）；模型 Qwen3.5-9B、non_thinking、temperature=0、8192 tokens，新 VM，generic_api_only。

| 步骤 | 模型实际动作与结果 |
|---|---|
| 1–2 | 搜索并查询 latest=5、ascending 的邮件 |
| 3–4 | 搜索并创建空白 Sheet1，未写入、未保存 |
| 5 | 五列表头写到 A1:F1，按新计数提示拒绝 |
| 6 | 模型自己改成 A1:E1，写入五个表头成功 |
| 7 | 模型提交五行数据到 A2:E6，25 格成功 |
| 8–9 | 错误 URL file:///desktop/report.xlsx 保存失败，重复请求被拦截 |
| 10–19 | 重复搜索，没有新增写入；此效率问题如实保留 |
| 20 | 模型自行改为 file:///home/user/Desktop/report.xlsx，显式 save_as 成功，5091 bytes |
| 21 | propose_done；随后第 22 次模型请求仅审计确认，不计新事件 |

results 与 manifest 均 agent_done；21 次模型审计完成、pending=null，0 次 soft restart、0 次 completion rejection。未执行独立 range.read，写入返回带读回、保存返回带文件/格式校验；另外开发者离线核对了实际 XLSX。manifest 的 adapter_verifier_passed_calls=0 不改写，各执行事件嵌套 verification_passed=true 单独解释。

配置里虽复制了 initial_step_budget=45，但本次实际命令未传 --initial-step-budget，Runner 记录 **fixed 75**，区别于前次初始45/硬上限75。通过用21步，未依赖超过45步的预算；不能声称运行条件完全相同。其余本地25步、soft restart上限1、1800秒与最近批次一致。

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
/var/lib/liteagent-shared/python-env/bin/python -u \
src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
--config src/adapter_versions/v2_expanded/experiments/configs/osworld-order91-create-write-save-20261012.json \
--result-dir src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012 \
--orders 91 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
--reasoning-mode non_thinking --max-steps 75 --max-local-steps 25 \
--max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1800 \
--max-output-tokens 8192 --request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```

[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/result.txt)；[trajectory manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/trajectory_manifest.json)；[evaluator产物清单](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/evaluator_artifacts/manifest.json)；[实际 report.xlsx](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/evaluator_artifacts/result-00-report.xlsx)；[完整结果回执及SHA-256](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-create-write-save-20261012/result-receipt.json)。

## 交付与集成边界

共享工作区在本题开始前已有其他题未提交改动。本题源码增量已应用，但不能把四个文件整文件提交，否则会混入其他题。增量补丁 [implementation.patch](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/deliveries/order91-create-write-save-20261012/implementation.patch) 与前后 SHA-256 单独交付；应在对应共享基线上应用，当前工作区已经应用，不要重复应用。git apply --cached --check 对 HEAD 的两处路由上下文失败，证明它依赖当前未提交基线，不能将孤立 HEAD 当作本次验收源码。

本次提交只登记本题增量交付、配置、验收日志和本题文档写回。完整批次与历史原始结果不改写；最新 MD/JSON 仅更新 Order 91 或增加本次 followup，不给其他未提交实现背书。提交号见下方收尾回执。

Order 91 本题增量交付提交：`c6698fc`（独立源码补丁、基线哈希、配置、PASS 回执、日志与本题文档增量；四个活动源码文件已应用在共享工作区，未整文件提交）。
