# 公开 API 粒度复查与拆分清单

日期：2026-09-20

## 结论

本次从十个 Adapter 的 `schema.ACTIONS` 重新枚举公开面；增加 Thunderbird identity
发现动作后，共 **217** 个 action。复查结果为：

- **P0 必拆/收窄 19 个**：一个调用可表达多个互相独立的设置、多个有顺序的变换、把两种操作模式合并在同一个入口，或带有未声明的破坏性副作用。
- **P1 复核 17 个**：粒度较大，但可能属于显式同构批处理或应用原生事务；先写保留理由和反例，再决定是否拆，不要机械拆分。
- **保留 181 个**：当前可解释为单一语义操作、只读查询、保存/导出、显式同构批处理或纯传输。

这只是源码审计和任务分配，不是新基线，不改变任何历史分数，也没有运行模型或 evaluator。这里的“必拆”表示契约粒度过大，不表示已发现任务 ID、写死答案或 golden 泄漏。

审计对应的两份源码快照一致，活动源码 seal 为
`a752ab170ff4769cc1f1fef2c1a5f0b99c631e41fedb48727c5e9f9e0f10cfaa`。交付仓库基点分别为
`liuxv: 358cb59`、`pengzhe: 2d80411`。

## 判定规则

P0 满足至少一项：

1. 一个调用允许修改多个互不依赖的设置，模型没有逐项选择和接收反馈的机会。
2. 一个调用串联多个有顺序、可独立失败的变换。
3. 一个入口合并两种不同操作，或在 mutation 内隐式完成另一个应显式选择的 mutation。
4. 一个对象数组允许每项使用不同规则，实际等价于隐藏的动作序列。
5. action 名称和公开描述只声明一个效果，实现却顺带清除或覆盖其他用户内容。

以下情况不因“字段多”或“数组”自动判大粒度：一个目标的一次格式化；模型给出每个成员的显式同构批处理；应用原生保存、导出和转换；有界只读批量读取；纯 Adapter 传输。`command.run` 由模型给出完整 argv，`multi_apps.adapter.call` 只转发一个已选择的下游调用，也不按宏 API 处理。

## P0 必拆/收窄清单

| 负责人 | API | 当前问题 | 目标契约 |
| --- | --- | --- | --- |
| liuxv | `libreoffice_calc.range.text_transform` | `operations` 是有顺序的变换数组 | 每次只允许一个 transform；需要组合时由模型连续调用 |
| liuxv | `libreoffice_impress.slide.format_text_roles` | `overrides` 可在同一调用中追加异构角色规则 | 移除异构 overrides；一次调用只保留一个共享格式规则 |
| liuxv | `libreoffice_impress.slides.format_text_roles` | 多页批处理还可携带异构 overrides | 多页只允许同一规则；不同规则拆成独立模型调用 |
| liuxv | `libreoffice_impress.slide.set_role_text` | 先替换文本，再可选执行八类格式；格式失败时文本已经改变 | 只保留 role text replacement；格式由独立 `slide.format_text_roles` 或 `shape.format_text` 调用完成 |
| liuxv | `libreoffice_writer.document.add_page_numbers` | 声称添加页码，实际会清空每个活动页样式的整个页脚 | 保留已有页脚，仅创建或更新本 action 自己的页码字段；清空页脚必须是独立显式动作 |
| liuxv | `thunderbird.mail.configure` | 一次可改签名、回复引用、过滤行为、统一收件箱和主题，并跨两个配置存储写入 | 一个公开调用只改一个语义设置；跨存储效果不得合并 |
| liuxv | `thunderbird.filters.configure` | 一次接受最多 50 条不同规则，move 规则还会隐式创建本地文件夹 | 一次配置一条规则；`move_to_local_folder` 先显式调用 `folders.ensure_local`，forward 无需该步骤 |
| liuxv | `thunderbird.preferences.update` | 任意 values map 加 remove list 可一次改动多个无关偏好 | 每次只 set 或 remove 一个精确 key |
| pengzhe | `chrome.settings.set` | 一个 map 混合隐私、资料、启动、外观、字体和搜索设置 | 一次只允许一个 setting |
| pengzhe | `gimp.image.adjust` | 一次可串联亮度、对比度和饱和度调整 | 一次只允许一种 adjustment 和一个 amount |
| pengzhe | `os.archive.create_extract` | 同一 action 用 mode 合并创建 ZIP 和解压 ZIP | 拆成明确的 create-ZIP 与 extract-ZIP action |
| pengzhe | `os.desktop.set_accessibility_scale` | 一次同时写文本缩放、放大镜开关和放大倍率三个设置 | 退役组合面并使用单键 `desktop.set_setting`，或拆成独立 text-scale 与 magnifier 动作 |
| pengzhe | `os.desktop.set_dim_inactive` | 一次同时写 session idle-delay 与 power idle-dim 两个独立 key | 一次只改一个设置，或直接使用单键 `desktop.set_setting` |
| pengzhe | `vs_code.debugging.configure` | 一次可改六个相互独立的调试设置 | 一次只改一个语义 setting |
| pengzhe | `vs_code.editor.configure` | 一次可改八个相互独立的编辑器设置 | 一次只改一个语义 setting |
| pengzhe | `vs_code.files.configure` | 一次可改 autosave、空白处理、末尾换行和 hot-exit | 一次只改一个语义 setting；自然耦合值可作为一个结构化值 |
| pengzhe | `vs_code.settings.update` | 任意 values map 可改多个无关 key | 每次只 set 或 remove 一个精确 key |
| pengzhe | `vlc.preferences.configure` | 一次混合快捷键、音量、界面、录制目录、退出和实例策略 | 一次只改一个语义 preference |
| pengzhe | `vlc.config.update` | 任意 values map 可改多个无关 key | 每次只写一个精确 key/value |

实现时优先缩窄现有契约，只有语义确实不同才增加窄 action。不要为了“拆分”复制执行器或制造一批同义工具。

### P0 完成记录

| API | Replacement | 实现提交 | 实际验证 |
| --- | --- | --- | --- |
| `thunderbird.mail.configure` | 保留 action 名；`signature_text`、`quote_original_on_reply`、`automatic_filters_on_subfolders`、`unified_inbox`、`dark_mode` 严格五选一。`identity` 只允许用于签名或回复引用。每次调用只写 `prefs.js` 或 `xulstore.json` 中的一处存储。新增只读 `identities.query`，在 identity-specific mutation 前返回 profile 中的精确 identity/account/email 映射。 | `0b6b25e`, `27a6552` | 初始收窄：邮件契约 focused pytest（75 passed）。identity 发现修复：`/var/lib/liteagent-shared/python-env/bin/python -m pytest tests/test_mail_selector_contract.py -q`（21 passed）；8 个改动 Python 文件执行 `ruff check` 通过。Order 153 单题正式复跑 `status=passed`、`reward=1.0`。 |
| `thunderbird.filters.configure` | 保留 action 名；`filters: [rule, ...]` 改为 `filter: rule`，一次只创建或更新一条。move 前由模型调用 `folders.ensure_local`；不存在则在修改规则文件前报错；forward 不创建文件夹。连续调用保留其他规则，同名规则更新，默认验证限定在单条规则块内。 | `4ac68e4` | `PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`（25 passed）；`/opt/anaconda3/bin/ruff check` 和 `ruff format --check`（8 个改动 Python 文件通过）；Order 154 单题正式离线 evaluator `status=passed`、`reward=1.0`。 |

### 单题闭环记录

- Order 153，task `3f28fe4f-5d9d-4994-a456-efd78cfae1a3`：设置两行纯文本签名。首次有效运行位于 `experiments/local-mail-configure-single-20260920-retry1/workers/worker-00/results.json`，`reward=0.0`；模型将可见邮箱地址误作内部 identity，三次调用均在 mutation 前以 `params.identity contains unsupported characters` 被拒绝。
- 通用修复提交 `27a6552` 增加无参数只读 `identities.query`，返回 identity、email、display name、account、server 和 hostname 映射；签名与回复引用指令把该查询和 `mail.configure` 同时列为必需动作，配置契约要求使用查询返回的精确 identity。
- 同题 retry2 位于 `experiments/local-mail-configure-single-20260920-retry2/workers/worker-00/results.json`。模型第 1 步查询得到 `id1`，第 2 步调用 `mail.configure`，Adapter verification 通过；原始离线 evaluator 最终 `status=passed`、`reward=1.0`、`termination_reason=agent_done`。
- Order 154，task `5203d847-2572-4150-912a-03f062254390`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/5203d847-2572-4150-912a-03f062254390.json`。历史 v305/v306 的原始轨迹不在本工作区；本地拆分前基准的完整原始轨迹是 `src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-baseline-retry3-20260920/workers/worker-00/raw/run-1/154-thunderbird-5203d847-2572-4150-912a-03f062254390/`，结果为同一 worker 的 `results.json`（`passed`, `1.0`）。模型第 1 步显式建本地文件夹，第 2 步以旧 `filters` 数组配置一条规则；Adapter 同一步又隐式建该文件夹。基准通过但隐藏副作用和 50 条异构规则容量仍违反单一语义契约；旧 writer 覆盖全部规则文件，还会使拆分后的连续调用丢失早先规则。
- 初次本地基准预取原始 Hugging Face URL 超时，记录在 `experiments/local-filter-configure-154-baseline-20260920/workers/worker-00/results.json`（`environment_failure`，模型未运行）；从同一数据集路径的可用镜像预取到 OSWorld 标准缓存并与已有原 URL 缓存核对 SHA-256 后，retry3 的环境与原始 evaluator 均正常。两次中间配置因并发源码 seal 变化在模型启动前被拒绝，无评测分数。
- 本题通用修复提交 `4ac68e4`；拆分后轨迹在 `src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-split-20260920/workers/worker-00/raw/run-1/154-thunderbird-5203d847-2572-4150-912a-03f062254390/`，结果在同一 worker 的 `results.json`。模型第 1 步显式 `folders.ensure_local`，第 2 步仅传 `filters.configure(filter={...})`，Adapter 的单规则 verification 通过且无隐式建目录；正式离线 evaluator 判定 `passed`, `reward=1.0`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-filter-configure-154-split-20260920.json --orders 154 --result-dir src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-split-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。

## P1 复核清单

| 负责人 | API | 需要确认的边界 |
| --- | --- | --- |
| liuxv | `libreoffice_calc.workbook.create_new` | 同时创建工作簿、写 headers/rows；确认这是一个原生新建事务，而不是隐藏的多步文档生成 |
| liuxv | `libreoffice_writer.document.extract_images` | 批量导出文档图片；确认所有成员使用完全相同规则且没有隐式选择 |
| liuxv | `libreoffice_writer.document.remove_highlighting` | 可覆盖大范围；确认只执行一个明确的高亮移除规则 |
| liuxv | `libreoffice_writer.document.set_font` | 可覆盖大范围；确认只执行一个明确字体规则 |
| liuxv | `libreoffice_writer.document.transform_case` | 可覆盖大范围；确认只执行一种 case transform |
| liuxv | `thunderbird.messages.export_eml` | 可导出整个文件夹；确认文件夹和输出目录显式且没有挑选消息的隐藏逻辑 |
| pengzhe | `os.user.ensure_account` | 可能同时创建账号并修改账号属性；确认一个调用只对应一个账户声明式事务 |
| pengzhe | `os.archive.compress_file` | 压缩验证后还可删除源文件；确认它是明确、可恢复的原生事务，否则拆成 compress 与 delete |
| pengzhe | `os.filesystem.copy_to_directories` | 一个 source 复制到最多 64 个 destination 且隐式创建目录；确认是同构显式复制且没有目录发现 |
| pengzhe | `os.filesystem.rename` | overwrite 可递归删除现有目标目录并隐式创建 parent；确认这些是明确 rename 契约而非隐藏 mutation |
| pengzhe | `os.desktop.mime_associations.set` | 可一次给最多 20 个 MIME 类型设置默认应用；确认它们是同一个显式同构规则 |
| pengzhe | `os.image.extract_text_batch` | 批量只读 OCR；确认边界有界且不解释内容或决定后续动作 |
| pengzhe | `os.pdf.extract_text_batch` | 批量只读 PDF 文本提取；确认边界有界且不解释内容或决定后续动作 |
| pengzhe | `vs_code.workspace.open` | `close_existing` 会关闭全部 VS Code 窗口，失败路径还可能终止进程；确认生命周期副作用被明确声明 |
| pengzhe | `vs_code.workspace.set_folders` | 未限长 folders 数组整体替换 workspace；确认是应用原生显式同构事务 |
| pengzhe | `vs_code.workspace.add_folders` | 未限长 folders 数组批量追加；确认是应用原生显式同构事务 |
| pengzhe | `vlc.playback.open` | 打开媒体会终止/重启当前 VLC，并另外切换 loop | 确认生命周期是公开契约且 loop 不应成为独立 mutation |

`slides.format_text_roles` 完成 P0 的 overrides 删除后，还要做一次 P1 保留复核：多页必须只应用一个共享规则，并在执行前完整 preflight；否则继续拆成逐页调用。

P1 默认不改代码。只有源码证据证明它包含独立决策或异构 mutation 才进入拆分；保留时把理由补到本文件。

## 旧审计覆盖核对

与 v422 的 `strict-tool-granularity-audit.json` 交叉核对，当前 217 项中有 184 项在旧清单出现：125 项旧标为 `atomic_generic`、19 项 `read_only`、5 项 `save`、1 项 `composite_split_required`，另有 34 项当时是 `unreviewed`。还有 33 项是在该审计后加入。旧分类只是对照，不覆盖本次源码复查；例如若干旧 `atomic_generic` 在本次被重新列入 P0。

没有发现 `schema.ACTIONS` 之外仍被 Agent 暴露的 Adapter action。LiteAgent 的搜索目录覆盖全部 217 项；其中 34 项尚无 `DIRECT_ACTION_SCHEMAS`，会使用通用参数 wrapper 和文本 signature 暴露。Codex Desktop MCP 使用 `public_actions ∩ DIRECT_ACTION_SCHEMAS`，因此不加载这 34 项；去掉同样不作为下游直连工具的 `multi_apps.adapter.call` 后，Codex MCP 当前最多加载 182 个下游 Adapter action。这个“缺 Direct schema 的 34 项”与下面 v422 的 34 个 `unreviewed` 不是同一个集合，不能混为一谈。

缺 Direct schema 的 34 项分布为：Chrome 22 项（除 `browser.inspect`、`settings.set` 外的全部公开 action）、GIMP 9 项（除 `image.inspect`、`image.adjust`、`image.crop` 外）、OS 的 `package.install_snap`、Writer 的 `document.insert_page_break`、Thunderbird 的 `xulstore.update`。这是一项 Codex MCP 覆盖差异，不自动表示它们是大粒度 API。

### 旧清单中未审查的 34 项

- Chrome（21）：`bookmark.add_current`、`bookmark.create_folder`、`browser.ensure_running`、`browser.restart`、`extension.load_unpacked`、`page.click`、`page.fill`、`page.goto`、`page.press`、`page.print_pdf`、`page.read`、`page.select`、`page.wait_for`、`privacy.delete_cookies`、`privacy.delete_history`、`shortcut.create_current`、`tab.activate`、`tab.close`、`tab.list`、`tab.open`、`tab.restore_last_closed`。
- GIMP（9）：`config.set`、`image.apply_alpha_mask`、`image.convert_indexed`、`image.export`、`image.flip`、`layer.add`、`layer.fill`、`layer.scale`、`layer.translate`。
- OS（2）：`audio.set_volume`、`package.install_snap`。
- Writer（1）：`document.insert_page_break`。
- Thunderbird（1）：`xulstore.update`。

本次逐项读过契约后，这 34 项均可暂列保留：每项是单一 mutation、单一导航/生命周期动作或只读动作。`xulstore.update` 的 keys 是一个嵌套 JSON 路径的有序分段，一次只写一个明确 path/value，并不是多个独立 key 的批处理。

### v422 后新增的 33 项

- Calc（1）：`cells.set_formulas`。
- Impress（1）：`presentation.set_page_size`。
- OS（10）：`archive.compress_file`、`desktop.favorites.list`、`document.convert`、`filesystem.copy`、`pdf.form.fill`、`pdf.form.inspect`、`pdf.tables.inspect`、`terminal.default_profile.inspect`、`terminal.default_profile.set_setting`、`trash.list`。
- Writer（11）：`bookmark.create`、`cross_reference.insert`、`document.append_paragraphs`、`document.read_file`、`paragraph.apply_numbering`、`paragraph.clear_text`、`paragraph.replace_text`、`table.convert_text`、`table.read`、`text.find`、`text.set_format`。
- VS Code（9）：`debug.breakpoint.set`、`debug.continue`、`debug.session.wait`、`debug.start`、`debug.stop`、`debug.variables.read`、`editor.open_file`、`ui.expand_section`、`ui.open_view`。
- Thunderbird（1）：`identities.query`。

这 33 项中有 32 项当前可保留；`archive.compress_file` 因可在压缩后删除源文件列入 P1，先确认它是否属于明确的原生事务。其余是单目标动作、显式同构写入、应用原生转换或有界只读观察。特别地，`pdf.form.fill` 和 `cells.set_formulas` 虽可一次提交多个显式值，但每个成员都由模型给出，集合使用同一个公开契约，不包含字段发现或答案推导。

## 217 项全量清单

表中 P0/P1 与上文相同；“保留”列是本次明确检查过、当前不进入拆分队列的剩余项。三列互斥，合计必须等于每行公开数。

| Adapter | 公开数 | P0 | P1 | 保留 |
| --- | ---: | --- | --- | --- |
| Calc | 30 | `range.text_transform` | `workbook.create_new` | `cells.set_formulas`, `chart.create`, `page.fit_to_pages`, `pivot.create`, `range.copy`, `range.fill_down`, `range.format`, `range.merge`, `range.read`, `range.set_decimal_separator`, `range.set_scaled_display`, `range.set_validation`, `range.write`, `rows.set_hidden`, `sheet.copy`, `sheet.create`, `sheet.move`, `sheet.rename`, `table.reorder_columns`, `table.sort`, `view.freeze_panes`, `view.freeze_range`, `view.set_zoom`, `workbook.convert_file`, `workbook.export`, `workbook.inspect`, `workbook.read_file`, `workbook.save` |
| Impress | 31 | `slide.format_text_roles`, `slide.set_role_text`, `slides.format_text_roles` | - | `audio.insert`, `master.set_page_number`, `presentation.export`, `presentation.inspect`, `presentation.save`, `presentation.set_page_size`, `settings.set`, `shape.create_text`, `shape.delete`, `shape.export_image`, `shape.fit_to_slide`, `shape.format_text`, `shape.insert_image`, `shape.set_fill`, `shape.set_geometry`, `shape.write_text`, `shape.write_text_native`, `slide.create`, `slide.delete`, `slide.duplicate`, `slide.move`, `slide.set_background`, `slide.set_notes`, `slide.set_transition`, `table.create`, `table.format_text`, `table.replace_row`, `table.write` |
| Chrome | 24 | `settings.set` | - | `bookmark.add_current`, `bookmark.create_folder`, `browser.ensure_running`, `browser.inspect`, `browser.restart`, `extension.load_unpacked`, `page.click`, `page.fill`, `page.goto`, `page.press`, `page.print_pdf`, `page.read`, `page.select`, `page.snapshot`, `page.wait_for`, `privacy.delete_cookies`, `privacy.delete_history`, `shortcut.create_current`, `tab.activate`, `tab.close`, `tab.list`, `tab.open`, `tab.restore_last_closed` |
| GIMP | 12 | `image.adjust` | - | `config.set`, `image.apply_alpha_mask`, `image.convert_indexed`, `image.crop`, `image.export`, `image.flip`, `image.inspect`, `layer.add`, `layer.fill`, `layer.scale`, `layer.translate` |
| OS | 41 | `archive.create_extract`, `desktop.set_accessibility_scale`, `desktop.set_dim_inactive` | `archive.compress_file`, `desktop.mime_associations.set`, `filesystem.copy_to_directories`, `filesystem.rename`, `image.extract_text_batch`, `pdf.extract_text_batch`, `user.ensure_account` | `audio.set_volume`, `clipboard.get`, `clipboard.set`, `command.run`, `desktop.applications.inspect`, `desktop.favorites.list`, `desktop.open_path`, `desktop.remove_favorite`, `desktop.set_setting`, `desktop.set_wallpaper`, `document.convert`, `filesystem.copy`, `filesystem.create_directory`, `filesystem.find`, `filesystem.set_permissions`, `notifications.configure`, `package.install_snap`, `pdf.form.fill`, `pdf.form.inspect`, `pdf.outline.inspect`, `pdf.pages.extract`, `pdf.tables.inspect`, `system.set_timezone`, `terminal.default_profile.inspect`, `terminal.default_profile.set_setting`, `terminal.launch`, `terminal.show_output`, `text.append_each_line`, `trash.list`, `trash.restore`, `window.capture` |
| Writer | 28 | `document.add_page_numbers` | `document.extract_images`, `document.remove_highlighting`, `document.set_font`, `document.transform_case` | `bookmark.create`, `cross_reference.insert`, `document.append_paragraphs`, `document.export_pdf`, `document.insert_page_break`, `document.inspect`, `document.read_file`, `document.save`, `image.insert_at_cursor`, `paragraph.apply_numbering`, `paragraph.clear_text`, `paragraph.replace_text`, `paragraph.set_format`, `paragraph.split`, `settings.set_default_font`, `table.convert_text`, `table.insert_after_text`, `table.insert_at_cursor`, `table.read`, `table.set_cell_text_color`, `text.find`, `text.find_replace`, `text.set_format` |
| VS Code | 27 | `debugging.configure`, `editor.configure`, `files.configure`, `settings.update` | `workspace.add_folders`, `workspace.open`, `workspace.set_folders` | `debug.breakpoint.set`, `debug.continue`, `debug.session.wait`, `debug.start`, `debug.stop`, `debug.variables.read`, `diagnostics.configure`, `editor.open_file`, `explorer.set_exclusion`, `extension.install`, `file.create`, `file.indent_lines`, `file.read_text`, `file.replace_literal`, `keybindings.ensure`, `ui.expand_section`, `ui.open_view`, `workspace.find_files`, `workspace.inspect`, `workspace.write` |
| VLC | 9 | `config.update`, `preferences.configure` | `playback.open` | `media.extract_audio`, `media.extract_frame`, `media.extract_subtitles`, `media.transcode_clip`, `playback.status`, `window.set_fullscreen` |
| Thunderbird | 14 | `filters.configure`, `mail.configure`, `preferences.update` | `messages.export_eml` | `accounts.remove`, `attachments.save`, `compose.attach`, `compose.set_recipients`, `contacts.export_csv`, `folders.ensure_local`, `identities.query`, `messages.query`, `ui.prefill_account_setup`, `xulstore.update` |
| Multi-Apps | 1 | - | - | `adapter.call` |

总计：30 + 31 + 24 + 12 + 41 + 28 + 27 + 9 + 14 + 1 = **217**；P0 19；P1 17；保留 181。

## 关键源码证据

- `calc_adapter/tool_manifest.py:686`：`range.text_transform.operations` 是有序数组。
- `impress_adapter/tool_manifest.py:530`、`:594`：两个 role-format action 都允许 `overrides`。
- `impress_adapter/tool_manifest.py:564` 与 `impress_adapter/uno_worker.py:1750`：`slide.set_role_text` 先写文本，再执行可独立失败的可选格式化。
- `writer_adapter/tool_manifest.py:304` 与 `writer_adapter/uno_worker.py:2048`：页码 action 遍历活动页样式，并在 `uno_worker.py:2063` 清空整个页脚后插入页码。
- `thunderbird_adapter/actions.py:37`、`:172`：语义设置扇出，并可能同时写 `prefs.js` 和 `xulstore.json`。
- `thunderbird_adapter/filter_contract.py:53`、`:163`：最多 50 条规则，并从规则隐式收集本地文件夹。
- `chrome_adapter/schema.py:78`、`:163`、`:346`：八类无关设置共用一个 settings map。
- `gimp_adapter/tool_manifest.py:20` 与 `gimp_adapter/worker.py:23`：多个调整可共同执行，但默认 verifier 还会在第一个命中分支提前返回。
- `os_adapter/tool_manifest.py:833`：创建和解压由同一 action 的 mode 分支承担。
- `os_adapter/actions.py:1061`、`:1083`：两个 desktop 便利动作各自扇出为多个独立 GSettings 写入。
- `vscode_adapter/tool_manifest.py:152`、`:208`、`:537` 与 `vscode_adapter/schema.py:206`：多个设置族和任意 values map。
- `vlc_adapter/tool_manifest.py:22` 与 `vlc_adapter/schema.py:141`：九类偏好和任意 values map。

## 实施边界

- 不增加、加严或复制任何门禁；不建立新的审计框架。
- 不跑全量评测。每拆一个旧 action，只跑该 Adapter 的契约/worker/verifier 针对性测试和改动 Python 的 Ruff。
- 不把任务 ID、题目固定短语、golden 内容、固定坐标、答案或任务级动作序列放进运行时、schema、提示词或默认值。
- 每个旧大粒度 action 单独提交。提交应同时更新模型可见 schema、运行时 validation、dispatch/worker、默认 verification 和相应测试，不能留下两套不一致契约。
- 两位负责人只改各自 Adapter；共享 LiteAgent 路由只有在删除旧 action 引用时才做最小修改，并在提交说明中标出。
- P0 完成后更新本文件的状态和 replacement；P1 先记录“拆/留”理由。全量测试和基线冻结由集成人员另行决定。
