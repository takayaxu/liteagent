# 工具路由 schema 组装修复

102 题的本地失败轨迹位于
`/home/liuxv/liteagent-local-runs/transport-rerun-102-119-147-183-20261022/results/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/`。
首轮 `tools_search` 成功返回六个候选路由。文件整理流程先限定
`os.filesystem.find`，通用约束随后重新加入六个候选，导致 `payload.params`
从详细 schema 变为只有 `type` 和 `description` 的对象。后续访问
`params["properties"]` 时触发 `KeyError`，第二次模型请求尚未发出。

`constrain_adapter_call_routes()` 现使用扁平的 adapter/action 枚举和
`x-allowed-routes` 精确配对与新请求取交集，不再通过旧的 `oneOf` 识别已有路由。
重复应用相同或更宽的路由集合时保留已有参数约束；交集为空时移除执行工具。
从多个路由缩小为单个路由时恢复该路由的详细参数 schema。客户端 schema
校验和精确路由校验继续生效。

验证：原始 102 首轮事件离线重放通过，工具列表保持仅允许
`os.filesystem.find`，`kind=any`、`recursive=false` 和工具目录哈希均正常。
路由组合及文件整理相关测试 76 项通过、1 项排除；该排除项及额外 schema
反馈测试中的另 3 项失败均已用改动前实现复现。`bin/check.sh` 通过。
本次为离线修复验证，未重新运行 OSWorld，不更新 102 题的既有评分。
