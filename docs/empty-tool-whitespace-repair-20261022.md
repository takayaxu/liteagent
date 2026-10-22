# Qwen 空参数工具的空白循环修复

`workspace.inspect` 读取当前工作区，不需要调用者提供参数，所以公开 schema 为
`type=object`、`properties={}`、`required=[]`、`additionalProperties=false`。
JSON 调用参数为 `{}`；Qwen 原生 XML 调用则没有 `<parameter=...>` 子标签。
空参数是合法契约，不等于要求模型生成空白。

183 三次断流的直接诊断证据保存在
`/home/liuxv/liteagent-local-runs/183-transport-diagnosis-20261022/root-cause.md`。
服务端生成的 Qwen XML grammar 使用 `max_whitespace_cnt=null`，模型在空参数
体内循环生成换行。工具解析器没有输出这些换行，聊天 SSE 静默后被截断。

客户端现在仅在 Qwen3.5、配置了完整原生工具结束标记、且当前工具面包含空参数
工具时，显式传入 Qwen XML structural_tag。保留所有工具的原始公开 schema；
只将无参数工具的 `max_whitespace_cnt` 设置为 1，其他工具保持原约束。
限制作用于 XML 参数体中的语法空白，不截断思考，也不清理参数字符串内部的空白。

当前 endpoint 会用自动 grammar 覆盖 `tool_choice=required` 的显式约束，实测
即使提供 `max_whitespace_cnt=1`，服务端 render 回读仍为 null。因而此分支使用
`tool_choice=auto` 保留显式 grammar，由 `at_least_one=true` 和
`stop_after_first=true` 强制必须且只生成一个调用。`parallel_tool_calls=false`、
完整结束标记、thinking、输出预算及客户端工具数量/schema/路由校验继续保留。
其他模型、无完整原生结束标记、无空参数工具的请求继续使用原请求方式。

真实 endpoint 验证使用最新活动源码复跑所保存的 183 首轮提示、图片和工具列表，
由修改后的 `StructuredToolModelClient` 发起请求，保留 Qwen3.5-9B、thinking、
temperature=0、8192 token 上限。服务端 render 回读确认空白上限 1 及单调用约束，
请求约 13 秒完成，返回 `adapter__workspace_inspect`、参数 `{}`、
`finish_reason=tool_calls`，客户端校验通过。
请求及结果见同一诊断目录的 `fixed-client-request.json`、
`fixed-client-render.json`、`fixed-client-result.json`。

本次验证仅重放首轮模型请求，没有执行 OSWorld 工具或更新 183 评分。

## 分隔符编码与完整任务验证

显式约束中的 `begin`、`end`、`triggers` 必须使用真实换行，与完整结束标记一致。
早期未提交实现误写为字面量反斜杠加 n，导致第 4 题返回带该后缀的非法工作表名；
当前实现已修正三处分隔符，并增加真实换行回归断言。保留失败提示、图片和工具列表，
只修正约束分隔符的请求级对照返回合法的 `{"name":"Sheet2"}`。

修正后完整复跑第 4 题，原始 evaluator reward=1.0。随后结合最终完成门修复，
活动源码第 4、147 题分别以 14 步、5 步正常 `agent_done`，均 reward=1.0。
条件、源码摘要和原始证据见 `docs/final-completion-gate-20261022.md` 及
`/home/liuxv/liteagent-local-runs/final-completion-gate-20261022/verification-summary.json`。
