# Qwen 透视表生成契约修复

## 原因与修复

第 24 题失败轨迹来自仓库外的
`/home/liuxv/liteagent-local-runs/task24-spacing-fixed-qwen9b-20261023T124043Z/`。
生成的 `pivot.create` 反复只有 `row_fields`、`data_fields`，遗漏源表、源范围、
目标表、定位和名称。服务端 XGrammar 0.2.8 编译根 `oneOf` 时只展开局部分支，
没有把同级 `properties`、`required` 与分支求交；`allOf` 同级约束也不能直接依赖。
因而原始 JSON Schema 拒绝的缺参调用，却成为生成语法允许的结果。提示模型重试
不能补救一个不允许生成完整参数的语法。

修复位于活动源码的 `integrations/lite_agent/qwen_pivot_schema.py`，由
`model_client.py::_qwen_schema_compatible_tools` 在 Qwen3.5 请求构造时调用。

- 每个分类分支都合并公共字段、类型、必填项及嵌套数据字段约束。
- 将绝对定位和相对定位展开为独立的完整闭合对象；前者必须有 `destination`，
  后者必须同时有 `below_range`、`blank_rows`，通过移除互斥字段并保留
  `additionalProperties=false` 表达互斥关系。
- 将观察到的前一透视表范围与其条件间距约束一起展开。其余合法 A1 引用使用
  有限字符串集合的精确正则补集，保留标题下零空行等合法定位；不通过删除条件
  或把所有引用统一限制为表间间距来规避编译问题。
- 各分类使用不同的完整 `row_fields` 常量；相对引用的已观察集合与其补集互斥。
  虽然编译器提示 `oneOf` 按 `anyOf` 编译，这些展开后的分支在契约上仍互斥。
- 根层保留完整 `properties`，供 Qwen 工具解析器识别数值、数组等参数类型。
  直接工具和嵌套的 `adapter.call.payload.params` 使用同一转换。
- 未识别的根约束、条件形状、重叠分类会在发请求前报错，不静默删约束。

原始工具 schema 不变，模型返回后继续以它执行 `Draft202012Validator` 校验。
没有增加补参、默认源范围、字段猜测、跳过校验或放松完成门。此次转换仅覆盖
当前透视表契约，并非通用 JSON Schema 编译器。既有 `uniqueItems` 兼容处理属于
此前的 `0489a9d` 提交，本次没有扩展该处理。

## 验证

证据目录：`/home/liuxv/liteagent-local-runs/pivot-schema-contract-fix-20261023/`。

1. 在华为云服务端使用实际 XGrammar 0.2.8 对历史失败时的真实 schema 编译验证：
   完整绝对/相对调用可生成，历史两字段缺参调用及逐项缺参调用均被拒绝，8 项通过。
2. 对带已观察范围条件的契约进行 29 项对照；原始与转换后的 JSON Schema
   判定完全一致。28 项原生 XML 编译结果也一致，覆盖必填项、分类、聚合、
   比例模式、间距、非法范围及多余嵌套字段。
3. 另一个混用定位参数样本暴露了原生 XML 字符串可吞入参数结束标签的边界歧义，
   不能据此宣称编译器能独立代替校验。它仍被两个 schema 拒绝；客户端回归矩阵
   在自动 grammar 和显式 structural tag 两条路径均确认所有不合法返回被拒绝。
   此问题没有通过扩大接受集合来处理。测试中的整数字段字符串以带引号的 XML
   内容表示；裸 `1` 在该协议中本来就表示整数，不能用来证明类型约束失效。
4. 实际调用华为云 Qwen3.5-9B，自动 grammar 和含空工具时的显式 structural tag
   路径各请求一次。模型均返回完整源表、源范围、目标表、名称、相对范围、间距、
   分组及计数字段，并通过原始 schema 校验。这两次仅验证协议，关闭 thinking、
   输出预算 512；不代表第 24 题完整 thinking 轨迹通过。
5. 六个相关测试文件合计 **261 通过、1 跳过、2 既有失败**。跳过项需要本地
   `xgrammar`，其对应服务端编译已单独执行。两项失败为 GRF 自动修复旧测试，
   在未修改的 `0489a9d` Git 导出源码上也复现：
   `test_grf_rejection_supplies_authoritative_row_correction_to_model`、
   `test_repair_confirmation_executes_contract_rows_without_model_rows`。
   新增文件的 Ruff 检查、`git diff --check` 和 `bin/check.sh` 通过。

本次没有启动 OSWorld 全流程。后续按 README 从已提交源码的新工作树复跑，
不能把本次协议探针当作任务评分。
