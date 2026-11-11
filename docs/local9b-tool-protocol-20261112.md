# 本地 Qwen3.5-9B 工具调用协议修复

## 现象和根因

`c6495e1` 的 12 并发全量已按用户要求停止；中止前有 37 次题目终态被标记为
`model_protocol_failure`，其余 152 题未完成。该批没有有效的全量通过率。
HTTP 200 和非空 `reasoning_content` 不能证明生成了工具调用；客户端连续三次
收到 `finish_reason=stop`、空 `tool_calls` 后正确拒绝执行。

全量配置沿用了 vLLM 所需的 `stop=["\n</function>\n</tool_call>"]` 和
`include_stop_str_in_output=true`。本地 llama.cpp 不实现后一个扩展，匹配 stop
后先从生成缓冲中截去结束标记，原生工具解析器无法收到完整调用。
服务源码证据为本机 `llama.cpp-api/tools/server/server-context.cpp` 的
`find_stopping_strings`、`generated.truncate(pos + stop_pos)` 及不发送 stop 的分支。

这与此前 Ascend 的 `uniqueItems` grammar 编译错误不同，也不是推理槽数或断流问题。

## 最小修复

新增 `configs/single-task-local9b-thinking.json`：

- 本地 endpoint：`http://127.0.0.1:18009/v1`，Qwen3.5-9B thinking。
- `protocol.tool_call_stop_sequence=null`，服务原生解析完整工具调用。
- 此配置也不会启用依赖该 XML stop 的 vLLM 专用空参数 structural_tag 约束。
- 保留模型、原始工具契约、本地严格参数校验、每轮单调用、100 步和 1800 秒预算。
- 包含同一组有序 189 题；不新增定制 API 或任务工作流。
- 不设置 `model.served_root`：本地模型列表未提供 root，权重路径从 `/props` 单独留证。

Agent、Adapter 和 evaluator 源码均保持 `c6495e1`；云端配置保持原值。
并行 supervisor 后续使用本地模型时也必须使用本配置的 stop 语义，不能再复制云端 stop。

## 验证证据

仓库外证据目录：
`/home/liuxv/liteagent-local-runs/local9b-protocol-repair-20261112/`。

1. 原始失败请求重放：保留 stop 时只有思考，无工具调用。
2. 同请求去掉 stop：返回一个 `adapter__workbook_inspect({})`。
3. 同请求去掉 stop 和 vLLM 扩展并使用 required：同样返回正确调用。
4. 实际 StructuredToolModelClient 的 12 并发流式请求全部通过严格校验：6 个原始
   截图空参数调用，6 个含数组参数的调用；原始请求和 transport 字节均保留。
5. Order 2 原题正式复跑 PASS，reward 1.0，9 步，307.451 秒，协议错误 0。
6. Order 3 原题正式复跑 PASS，reward 1.0，7 步，292.205 秒。
7. 两题模型请求错误共 0；源码、配置、OSWorld 三项完整性均 true，入口退出码 0。
8. 汇总回执为上述目录下 verification.json。

`original.json`、`no_stop.json`、`native_required.json` 保存 A/B 响应；
`stream-verification.json` 保存并发回执；`rerun23/` 保存两题完整日志及评分。
全量旧记录及停止回执位于原运行目录，不覆盖，也未自动重启全量。
