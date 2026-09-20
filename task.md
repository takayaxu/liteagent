# Task: 按题目拆分大粒度 API，并逐题跑通

负责人：`liuxv`

工作分支：`codex/api-split-liuxv`

## 目标

负责 Calc、Impress、Writer、Thunderbird 的 API 粒度收窄。让模型每次只选择一个独立语义动作，并在动作失败后得到明确反馈；不得把多个互不相关的设置、变换或隐藏副作用塞进一个调用。

本任务只做 Adapter 契约和最小调用方调整，不新增门禁，不运行全量 OSWorld 评测。

## 执行方式（必须遵守）

1. **唯一的推进单位是具体 OSWorld 题目，不是 API。** 任一时刻只处理一道题；当前题没有通过前，不得开始下一题，更不能按下面的 API 清单逐项机械施工。
2. 每题开始前，必须人工打开并完整阅读该题的用户指令、任务定义和已有失败轨迹，再结合模型当时实际调用的工具、schema、Adapter 实现和调用链，判断这道题真正需要拆分哪些大粒度 API。
3. 只修改当前题完成所必需的 API。若一道题同时依赖多个大粒度 API，可以在这一题的闭环中逐个拆开；不得顺手拆分当前题没有使用的 API，也不得夹带下一题的改动。
4. 拆分后直接单独复跑当前这一题，以该题的正式离线 evaluator 结果为准。当前题通过才算完成，随后才能挑选并查看下一题。
5. 如果当前题仍然失败，必须让 Codex 调研本次运行的完整轨迹文件，至少核对模型看到的工具说明、模型参数、Adapter 返回、实际执行结果、verification 和离线 evaluator 结果，定位错误发生在哪一层。开发者可以自己提出方案，也可以让 Codex 提出和实现方案；采用最小且可复用的修复后，继续只跑同一题，直到通过。
6. 不需要新增或运行通用回归测试，也不要跑跨应用回归、fixed-189 或其他全量评测。只做当前题复跑、当前改动所需的最小 contract/静态检查，以及改动 Python 文件的 Ruff。
7. 阅读题目和轨迹仅用于离线诊断。题目 ID 可以记录在开发日志和结果目录中，但不得把任务 ID、golden 内容、期望答案、固定坐标或从单题推导出的完整操作序列写入模型可见的 schema、提示词或运行时代码。

当前已经完成的 `thunderbird.mail.configure` 契约改动不能视为一道题已经完成。下一步先选择并人工检查一条实际使用该 API 的题目，单独复跑并修到该题通过，再处理其他题目。

## P0 API 候选清单（不是执行顺序）

以下只是人工查看当前题目和轨迹后用于定位大粒度 API 的候选库存。只有当前题实际涉及的 API 才能进入本题改动。

1. `thunderbird.mail.configure`
   - 拆开签名、回复引用、子目录过滤、统一收件箱和主题设置。
   - 一个模型调用不得同时修改多个语义设置或同时写 `prefs.js` 与 `xulstore.json`。
2. `thunderbird.filters.configure`
   - 一次只配置一条 filter rule。
   - `move_to_local_folder` 先显式调用 `folders.ensure_local`；forward 不创建文件夹。
3. `thunderbird.preferences.update`
   - 一次只 set 或 remove 一个精确 preference key，或者取消该底层入口的模型可见性。
4. `libreoffice_writer.document.add_page_numbers`
   - 保留现有页脚，只创建或更新页码字段。
   - 不得清空整个 footer。
5. `libreoffice_impress.slide.format_text_roles`
   - 删除异构 `overrides`，一次调用只应用一个共享格式规则。
6. `libreoffice_impress.slides.format_text_roles`
   - 删除异构 `overrides`；多页只允许同一个规则，并在 mutation 前完整 preflight。
7. `libreoffice_impress.slide.set_role_text`
   - 只保留 role text replacement。
   - 格式化由模型随后显式调用 `slide.format_text_roles` 或 `shape.format_text`。
8. `libreoffice_calc.range.text_transform`
   - 把有序 `operations` 数组缩成一次一个 transform；多个变换由模型连续调用。

## P1 API 候选清单（仅在当前题涉及到时复核）

以下 API 不要求直接拆分。先检查是否存在隐式发现、异构 mutation 或不可恢复副作用，然后在审计文档记录“保留/拆分”及理由：

- `libreoffice_calc.workbook.create_new`
- `libreoffice_writer.document.extract_images`
- `libreoffice_writer.document.remove_highlighting`
- `libreoffice_writer.document.set_font`
- `libreoffice_writer.document.transform_case`
- `thunderbird.messages.export_eml`

`slides.format_text_roles` 移除 overrides 后还要复核多页同构批处理是否应保留。

## 交付要求

- 一道题形成一个独立闭环并留下清晰提交；同一道题需要拆多个 API 时可以有多个连续提交，但任何提交都不得混入下一题。
- 同步更新模型可见 schema/description、运行时 validation、dispatch/worker、默认 verification 和调用方；按上述串行闭环做最小定向验证，不扩建回归测试集。
- 不能只修改描述而继续接受旧的大粒度参数。
- 非法组合必须返回可操作的 Adapter 错误，明确冲突字段和正确调用方式。
- 每道题记录题目 ID、人工查看的原始轨迹、确认的失败原因、本题实际拆分的 API、复跑结果、结果/新轨迹位置和提交号；未通过时继续记录下一次修复依据，不得切换题目。
- 只运行当前题、当前改动所需的最小 focused check 和改动 Python 文件的 Ruff；不跑通用回归、fixed-189 或其他全量评测。
- 不修改 Chrome、GIMP、OS、VS Code、VLC、Multi-Apps，也不做无关重构。
- 不加入任务 ID、golden 内容、答案、固定坐标、题目短语或 task-aware 路由。

## 参考

- 详细实施说明：[`API_SPLIT_TASK.md`](API_SPLIT_TASK.md)
- 216 项全量审计和源码证据：[`docs/api-granularity-audit-20260920.md`](docs/api-granularity-audit-20260920.md)

每完成并通过一道题，把该题结果和涉及 API 的 replacement、提交号及实际命令补到开发记录；API 状态变化再同步到审计文档，最后交给集成人员统一合并。
