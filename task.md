# Task: 拆分大粒度 API

负责人：`liuxv`

工作分支：`codex/api-split-liuxv`

## 目标

负责 Calc、Impress、Writer、Thunderbird 的 API 粒度收窄。让模型每次只选择一个独立语义动作，并在动作失败后得到明确反馈；不得把多个互不相关的设置、变换或隐藏副作用塞进一个调用。

本任务只做 Adapter 契约和最小调用方调整，不新增门禁，不运行全量 OSWorld 评测。

## P0：必须完成

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

## P1：先复核再决定

以下 API 不要求直接拆分。先检查是否存在隐式发现、异构 mutation 或不可恢复副作用，然后在审计文档记录“保留/拆分”及理由：

- `libreoffice_calc.workbook.create_new`
- `libreoffice_writer.document.extract_images`
- `libreoffice_writer.document.remove_highlighting`
- `libreoffice_writer.document.set_font`
- `libreoffice_writer.document.transform_case`
- `thunderbird.messages.export_eml`

`slides.format_text_roles` 移除 overrides 后还要复核多页同构批处理是否应保留。

## 交付要求

- 一个旧 P0 action 一个提交，不把多个拆分任务混在同一提交。
- 同步更新模型可见 schema/description、运行时 validation、dispatch/worker、默认 verification、调用方和针对性测试。
- 不能只修改描述而继续接受旧的大粒度参数。
- 非法组合必须返回可操作的 Adapter 错误，明确冲突字段和正确调用方式。
- 每项至少验证一个成功调用、一个旧大粒度组合被拒绝的场景，以及关键状态/verification 场景。
- 只运行所属 Adapter 的 focused pytest 和改动 Python 文件的 Ruff；不跑 fixed-189 或其他全量评测。
- 不修改 Chrome、GIMP、OS、VS Code、VLC、Multi-Apps，也不做无关重构。
- 不加入任务 ID、golden 内容、答案、固定坐标、题目短语或 task-aware 路由。

## 参考

- 详细实施说明：[`API_SPLIT_TASK.md`](API_SPLIT_TASK.md)
- 216 项全量审计和源码证据：[`docs/api-granularity-audit-20260920.md`](docs/api-granularity-audit-20260920.md)

完成每个 P0 后，把 replacement、提交号和实际测试命令补到审计文档，再交给集成人员统一合并。
