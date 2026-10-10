# 当前公开 API 与定制运行时复审（2026-10-10）

## 结论与范围

**仍然存在大粒度公开 API 和明确的题目定制运行逻辑。** 枚举当前十个 Adapter 的 schema.ACTIONS 与 LiteAgent public_actions 得到 **221 个公开 action**；对历史 P0、固定 28 题相关契约、模型侧 schema overlay、Runner 参数注入及关键实现作定向代码审查。不是对 221 个 action 的每条执行路径进行穷尽验证。依据为当前工作区（包含未提交代码），不是只有 HEAD 的快照；没有启动单元测试、GUI、模型或 evaluator，没有修复实现。

历史文档中的 217 是旧快照统计；本次 221 为当前 checkout 新口径，不能直接把旧 P0/P1/保留数量搬过来。完整注册/公开清单与 11 个剩余大粒度工具的模型侧 schema 保存于 `api-customization-review-20261010.json`。

## 明确定制与隐藏决策

| 优先级 | 位置/关联动作 | 证据与问题 | 处理建议 |
|---|---|---|---|
| P0 | `calc_adapter/uno_worker.py:1355`，workbook.create_new，关联 108 | 用固定表头 Year/#Applied/#Supported/Success Rate 触发第 4 列 `0.00"%"` 格式。创建并填表之外，隐式执行题目特定格式 mutation；输入中没有显式选择该格式。当前未提交 diff 直接包含这一分支。 | 移除按表头识别的隐式行为；让模型显式调用通用 number-format action。 |
| P0 | `integrations/lite_agent/batch_table_semantics.py:174`、`:454`、`:516`、`:630`，关联 108 | 固定 GRF/HKU、学科名称、grf19–grf23 文件名、2019–2023 年份、四个表头、固定学科排序；提取目标行/列、计算 success_rate、构造期望行并在通用写入时强制匹配。属于按题面组织的领域求解器，数值虽从真实观察取出，仍非通用结构契约。 | 通用观察只返回所请求窗口与原生行列；年份、学科、公式、排序由模型显式选择。校验限制到类型、尺寸、来源引用等通用属性。 |
| P0 | `integrations/lite_agent/batch_table_semantics.py:2754`、`:2845`；`adapter_results.py:102`、`:829`；`agent_protocol.py:148`，关联 107 | ECS 文件名/2015–2023、9 个 block 中取 8 校、四学科固定序位、Computing Science 目标行、supported/application 计算与矩阵构造；跨年聚合只保留特定学科/Total，并在提示中固定年份。通用 range.write 被套上领域专用答案矩阵。 | 泛化表格窗口与来源索引，保留模型选择目标行列、公式和输出布局的决定；不能仅改函数名或把求解器移到 Runner。 |
| P0 | `integrations/lite_agent/recovery_surface.py:223`、`:305`；`execution_engine.py:376`；`tool_surface.py:790`，关联 107/108 | repair_confirm 只收 repair_id/confirm；Runner 自动构造 ECS 矩阵或五年 GRF 行，然后用 corrected_arguments 执行 range.write/create_new。模型仅确认整体结果，缺少对每个计算与写入参数的显式调用；它是一项暴露在控制工具里的定制宏，而非普通错误说明。 | 返回可操作错误与原始证据，让模型重新提交公开 mutation 参数；不要用定制矩阵替换模型参数。 |
| P1 待泛化 | `integrations/lite_agent/agent_protocol.py` 的 system_prompt；`batch_table_semantics.py:303`、`:388`，关联 95/96 | 公共提示对多文档任务注入 first-author/affiliation/brace-email 配对和排序的完整特定步骤，适用描述宽于“第一作者”题目。结果校验也内置该领域选择规则。数据来自观察，不等于来自 golden，但仍可能将任务求解步骤藏入通用运行层。 | 把作者/邮箱与所需数量作为模型从当前用户指令选择的字段；审查非第一作者、通讯作者等反例，避免全局套用该流程。 |
| P1 需区别对待 | `execution_engine.py:463`、`tool_surface.py:698`；Impress cleanup/picture 计划，关联 54/60 | 已提交代码能向零参数工具注入完整 geometry/cleanup 步骤；单次实际只执行一个动作，数值从用户要求和当前观察推导，所以不能直接等同于批量 mutation 或硬编码答案。但 Runner 替模型选择对象和参数的边界需要进一步复核，不能因是零参数工具就认定粒度合格。 | 保留原子公开动作，明确对象选择和参数出处；用不同页面/形状/指令的反例复核其通用性。 |

以上是 4 组 P0 与 2 组 P1，按代码机制分组，不是 6 个独立 Adapter action。未看到这几处从 evaluator/golden 读取答案，不能据此宣称 golden 泄漏；同样，没有 task ID 条件也不能排除按年份/学科/表头/题目短语实现的定制逻辑。

## 仍公开的 11 个历史大粒度入口

下面均通过 strict_generic build_tools 只读枚举确认仍有模型可见工具；schema 和实现不限制为单个独立设置。它们是已确认的粒度问题，本次证据不足以把每项称作题目定制求解器。

| 应用 | 公开 API | 证据 |
|---|---|---|
| Chrome | settings.set | schema.py:346 接受非空 settings map，不限制只含一个设置。 |
| GIMP | image.adjust | schema.py:199 可同时接受 brightness、contrast、saturation；应一次选择一种 adjustment。 |
| OS | archive.create_extract | 同一 action 仍通过 mode=create/extract 合并两种不同语义；分支参数已区分，但没有拆成两个入口。 |
| OS | desktop.set_accessibility_scale | actions.py:1097 一次写 text-scaling-factor、screen-magnifier-enabled、mag-factor，包含隐式打开放大镜。 |
| OS | desktop.set_dim_inactive | actions.py:1119 可同时写 idle-delay 和 idle-dim。 |
| VS Code | debugging.configure | schema.py:210 至少一个配置，不限制一次一个；actions.py:152 把多个配置转成 settings_update map。 |
| VS Code | editor.configure | schema.py:264 允许多种独立编辑器设置同时出现。 |
| VS Code | files.configure | schema.py:284 允许 autosave、空白处理、末尾换行、hot-exit 等独立设置并存。 |
| VS Code | settings.update | schema.py:206 values map 未限单 key。 |
| VLC | preferences.configure | schema.py:156 包含音量、热键、界面、录制路径、退出及实例策略，允许同时修改。 |
| VLC | config.update | schema.py:141 非空 values map，允许多个无关 key。 |

这些跨应用入口不在 liuxv 固定 28 题当前修复范围内，本次只记录现 checkout 状态，不能推断其他分支是否已经完成对应拆分。

## 已收窄与可保留的边界

- Calc range.text_transform 的旧 operations 明确拒绝，只接受单 transform（schema.py:755）。
- Impress slide/slides.format_text_roles 明确拒绝 overrides，限制一个共享格式规则（schema.py:446）；一次多项字体属性属于同一格式化决策，不仅因字段多而判定为宏。
- Thunderbird mail.configure 已退役；preferences.update 不在 ACTIONS/public_actions 中；identity、theme、inbox 设置已独立。filters.configure 只接受一条 filter（schema.py:179），move 所需文件夹由独立 ensure_local 创建。
- os.pdf.extract_text_batch 属于有界同构只读批处理，本次没有证据证明它自身完成 PDF-to-Calc 求解/写入；目前定制部分集中在 Runner 的内容解释和参数替换，拆开只读批处理无法消除这些问题。
- workbook.create_new 的创建、填充、保存可视作单个文档事务；P0 是按固定表头追加的隐藏领域格式，而非简单认定“创建并保存”一定需要拆开。

## 审计处理

本轮复审覆盖先前“没有 task-specific parser/route”结论的实际工作区边界：107/108 的既有通用性描述不能代表当前源码，已发现的固定领域解释/repair_confirm 应单独登记为未通过通用性审查。23 题 evaluator PASS 只说明原生评分满足，不证明 API 粒度或运行时求解过程合规。此次仅更新复审报告及主审计，不修改实现和原始实验，不重评历史分数。
