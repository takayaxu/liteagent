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

## Order4 修复记录

按原队列从Order4开始；候选方案 `independent-sum-schema-v1` 经主agent自审通过。最新基线48事件显示模型创建交叉表、后续混合分组并不断换名创建，完成检查已报告独立汇总差异。修复只在既有独立分组语义和完整源数据可解析时，把已有完成契约同步至pivot.create参数schema；保留模型选择分组、表名和位置，不变更API路由、评估、预算或自动代写操作。

候选 `6d4a582`：191项定向检查通过、1项跳过，18个真实prefix/最终通用约束schema回放通过，Ruff、diff、source/import检查通过。回放是本地schema核查，不能代替正式PASS；恢复路径通过共享最终约束验证，未声称真实服务生成已验证。v1正式run002因第二张表relative destination对象被Qwen工具解析器字符串化而model_protocol_failure/null，三完整性true、未集成。v2候选 `9c0167b` 采用已有标量位置表达，191项检查通过1跳过、Ruff/diff/source检查通过；新run003正式PASS1.0/agent_done，11事件、359.826秒，三完整性true、自有容器已清空。保存产物恰有两张独立求和表，总额均为2368.15；原evaluator比较透视字段/筛选定义，位置和所有格式不在其覆盖范围。结果见 [order004-receipt.json](order004-receipt.json)。Order4补丁与回执已本地集成至3b43e0e；GitHub连接/TLS失败，当前待正常推送及远端核验。

证据根目录：`/home/liuxv/liteagent-local-runs/repair-timeouts15-20261103`。

本批最新为9/15正式通过（4、8、13、28、37、76、82、104、172）；65按用户要求跳过，101按用户要求放弃，107、109、114、132共4题仍待修。历史基线分数保留。

## Order8

候选 `f5959b0` 仅增加已有月度两列表契约说明及更具体的缺行反馈，schema/工具路由/执行/完成门规则不变。63focused、10真实prefix、Ruff/diff/bin检查通过；5项旧oneOf结构断言在未改基线同样失败。run002原模型/100步1800秒/原评估，正式PASS1.0，15事件492.666秒，三完整性true、自有容器清空。保存结果7行2列，6个月各有同行总额，原Sheet1单元格逐值保留。初始月份列误写公式被模型改回标签；两次完成申请因缺保存后inventory被拒，14inspect后15完成。回执见 [order008-receipt.json](order008-receipt.json)，候选待集成，不声称全程一次正确。

## Order28

最新基线failed0：24行period rate被再乘100；旧通用单位说明实际送达，原完成检查未核算单位。自审v1增加保守原生年率单位/每年期数/输出数值检查；run002证实新增反馈将显示格式混入单位错误，精确中断后v2分离数值与原有格式核验。run003在gate已通过时仍只看到历史拒绝，v3增加compaction后当前claim资格说明。run004证实inventory/header合并缺项无步骤证据，模型反复引用保存前inventory；v4仅拆清相同谓词诊断，公开实际检查步与最后修改/保存步，不改变freshness要求。前三轮无正式评分，不算0分或PASS；三完整性均true，精确自有资源清理，原日志保留。

最终候选 `7b6b3e3`，run005原9Bthinking/100步1800秒/原task/evaluator正式PASS1.0，21事件681.173秒，三完整性true。保存24数值全部为原输入年率/每年期数，原A/B值与原XLSX逐值保留，只有C20绿色。模型初始公式正确，17完成因缺保存/结构检查拒绝后18save19inspect20读全列21完成；仍有重复设置绿色请求被拒。121focused/5真实prefix诊断不变检查及Ruff/diff/bincheck通过；v3另165focused通过，2项旧GRF测试在未改v2同失败。回执见 [order028-receipt.json](order028-receipt.json)，本地待集成。

## 最新进展（2026-11-04）

用户开启人工审核后，直接指定101使用逐轮阶段提示，再明确放弃101、继续104，并授权“跑不过就不断收紧”。104按该方向由主agent在本对话审核、迭代和监测，无子agent。101候选未集成，65仍跳过。

104第三版候选 `5dad2a6`，run008原模型、100步/1800秒、原任务和评估正式PASS1.0，25步675.131秒，源码/配置/OSWorld三项完整性均true，自有运行进程退出、容器清空。保留Test1的原答案，只补写Test2、Test3，最终DOCX各部分各一组答案；原评估忽略大小写和空白，实际比参考少一个空白分隔段，不声称逐段布局完全一致。

修复只收紧提示：根据实际源/目标读取与原生段落证据逐步给出发现、读取、定位、保存及读回动作；写入时只显示当前部分的题干、选项和字符位置清单，段落索引来自实际观察；搜索/读回时不重发所有试卷或旧的空目标快照。工具/schema/完成门/模型/预算/原评估不变，答案由模型判断。前两版的deadline/null和诊断中止均保留，不改记为0或PASS。详见 [order104.json](order104.json)。
