# 15 道模型请求截止题的基线复跑

原始批次 `latest-full189-12workers-20261102T080546Z` 的15道deadline题，按用户指定先做无补丁串行复跑。所有运行从活动提交 `bb71960f775c433c8b6bfee4257b855fcc4cebfa` 的独立干净工作树启动；运行源码摘要与原全量相同。保持 Qwen3.5-9B thinking、100步、1800秒、原OSWorld任务和evaluator；并发从原全量12降为单题串行，作为复跑条件明确记录。

用户于2026-11-03明确“关闭子agent，自己审核修复”；本聊天之后使用主agent自审，human_review=false、subagents=false，覆盖repair_skill独立子agent审核约定。

15题已全部复跑：3题PASS，无新增源码补丁；6题deadline/null；5题failed/0；1题模型传输失败/null。三项源码、配置和OSWorld完整性核验全部为true。NULL不换算成业务0分；本轮结果不改写原全量分数。

| Order | task ID | 正式结果 | reward | 秒 |
| --- | --- | --- | --- | --- |
| 4 | `535364ea-05bd-46ea-9937-9f55c68507e8` | agent_deadline_exhausted | None | 1862.239 |
| 8 | `26a8440e-c166-4c50-aef4-bfb77314b46b` | agent_deadline_exhausted | None | 1855.345 |
| 13 | `0326d92d-d218-48a8-9ca1-981cd6d064c7` | passed | 1.0 | 938.334 |
| 28 | `21ab7b40-77c2-4ae6-8321-e00d3a086c73` | failed | 0.0 | 688.217 |
| 37 | `ac9bb6cb-1888-43ab-81e4-a98a547918cd` | passed | 1.0 | 733.466 |
| 65 | `0a0faba3-5580-44df-965d-f562a99b291c` | failed | 0.0 | 1877.901 |
| 76 | `8472fece-c7dd-4241-8d65-9b3cd1a0b568` | agent_deadline_exhausted | None | 1863.654 |
| 82 | `e246f6d8-78d7-44ac-b668-fcf47946cb50` | passed | 1.0 | 1012.423 |
| 101 | `185f29bd-5da0-40a6-b69c-ba7f4e0324ef` | agent_deadline_exhausted | None | 1929.443 |
| 104 | `1f18aa87-af6f-41ef-9853-cdb8f32ebdea` | model_transport_failure | None | 1934.93 |
| 107 | `881deb30-9549-4583-a841-8270c65f2a17` | failed | 0.0 | 1570.521 |
| 109 | `5bc63fb9-276a-4439-a7c1-9dc76401737f` | failed | 0.0 | 1429.232 |
| 114 | `bb83cab4-e5c7-42c7-a67b-e46068032b86` | agent_deadline_exhausted | None | 1924.031 |
| 132 | `aceb0368-56b8-4073-b70e-3dc9aee184e0` | failed | 0.0 | 560.371 |
| 172 | `f3977615-2b45-4ac5-8bba-80c17dbe2a37` | agent_deadline_exhausted | None | 1859.427 |

逐题结果、原始轨迹、源码身份和完整性见 [baseline-receipt.json](baseline-receipt.json)。正式PASS只表示原始evaluator通过，不扩大为所有内容逐项一致。

## 当前修复

按原队列从Order4开始；候选方案 `independent-sum-schema-v1` 经主agent自审通过。最新基线48事件显示模型创建交叉表、后续混合分组并不断换名创建，完成检查已报告独立汇总差异。修复只在既有独立分组语义和完整源数据可解析时，把已有完成契约同步至pivot.create参数schema；保留模型选择分组、表名和位置，不变更API路由、评估、预算或自动代写操作。

候选 `6d4a582`：191项定向检查通过、1项跳过，18个真实prefix/最终通用约束schema回放通过，Ruff、diff、source/import检查通过。回放是本地schema核查，不能代替正式PASS；恢复路径通过共享最终约束验证，未声称真实服务生成已验证。v1正式run002因第二张表relative destination对象被Qwen工具解析器字符串化而model_protocol_failure/null，三完整性true、未集成。v2候选 `9c0167b` 采用已有标量位置表达，191项检查通过1跳过、Ruff/diff/source检查通过；新run003正式PASS1.0/agent_done，11事件、359.826秒，三完整性true、自有容器已清空。保存产物恰有两张独立求和表，总额均为2368.15；原evaluator比较透视字段/筛选定义，位置和所有格式不在其覆盖范围。结果见 [order004-receipt.json](order004-receipt.json)。候选已验证，等待集成和推送。

证据根目录：`/home/liuxv/liteagent-local-runs/repair-timeouts15-20261103`。

本批当前4/15确认通过（4、13、37、82）；其余11题待修，下一题8。
