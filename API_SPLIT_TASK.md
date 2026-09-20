# liuxv：大粒度 API 拆分任务

工作分支：`codex/api-split-liuxv`

完整复查见 [`docs/api-granularity-audit-20260920.md`](docs/api-granularity-audit-20260920.md)。你负责 Calc、Impress、Writer、Thunderbird，共 102 个公开 action；其中 P0 8 个、P1 6 个、当前保留 88 个。

## P0 实施顺序

每个编号对应一个旧公开 action，完成后单独提交。不要把多个编号塞进一个提交。

1. `thunderbird.mail.configure`
   - 一次只改一个语义设置；不得在一个模型调用中同时写 `prefs.js` 和 `xulstore.json`。
   - 签名、回复引用、子目录过滤、统一收件箱和主题应是彼此独立的窄契约。
2. `thunderbird.filters.configure`
   - 改为一次一条 filter rule。
   - `move_to_local_folder` 要求模型先显式调用 `folders.ensure_local`；forward 不需要创建文件夹。
3. `thunderbird.preferences.update`
   - 一次只能 set 或 remove 一个精确 preference key；也可以不再向模型公开这个底层入口。
4. `libreoffice_writer.document.add_page_numbers`
   - 保留已有页脚内容，只创建或更新本 action 自己的页码字段。
   - 不允许清空整个 footer；若将来需要清空，必须是单独显式 action。
5. `libreoffice_impress.slide.format_text_roles`
   - 删除异构 `overrides`；一次调用只应用一个共享格式规则。
6. `libreoffice_impress.slides.format_text_roles`
   - 删除异构 `overrides`；多页只能共享同一规则，并在 mutation 前完成全量 preflight。
7. `libreoffice_impress.slide.set_role_text`
   - 只保留 semantic-role 文本替换；移除同一调用中的可选格式字段。
   - 文本格式由模型随后显式调用 `slide.format_text_roles` 或 `shape.format_text`，避免格式失败时留下部分文本 mutation。
8. `libreoffice_calc.range.text_transform`
   - 把有序 `operations` 数组缩成一次一个 transform；多个 transform 由模型顺序调用。

“一次一个 setting/transform”可以通过窄 action，也可以通过带判别字段的单一 action 实现；选择能让模型最容易理解、且不会制造同义工具的形式。

## P1 复核

以下 6 项先读实现并在审计文档写“保留或拆分”的理由，不默认改代码：

- `libreoffice_calc.workbook.create_new`
- `libreoffice_writer.document.extract_images`
- `libreoffice_writer.document.remove_highlighting`
- `libreoffice_writer.document.set_font`
- `libreoffice_writer.document.transform_case`
- `thunderbird.messages.export_eml`

另外，`slides.format_text_roles` 去掉 overrides 后复核一次：只有“显式多页 + 完全相同规则 + mutation 前全量 preflight”同时成立，才保留多页批处理。

## 每项交付要求

1. 模型可见 schema/description、运行时 validation、dispatch/worker、默认 verification 和调用方必须同步更新，不能保留两套不一致契约。
2. 删除或隔离旧大粒度入口；不能只在描述里说“一次一个”，实现却仍接受多个独立效果。
3. 非法组合要返回可操作的 Adapter 错误，让模型知道哪个字段冲突以及下一次应怎样调用。
4. 新增或调整最小针对性测试，至少覆盖一个有效调用、一个被拒绝的大粒度组合、一个 verification 失败或状态保留场景。
5. 只运行该 action 所属 Adapter 的针对性 pytest、相关契约测试和改动 Python 文件的 Ruff。不要跑全量评测。
6. 一个旧 action 一个提交；提交信息写清旧入口、replacement 和实际测试命令。

可复用的本地环境：

```bash
cd /home/liuxv/liteagent
export PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src"
PYTHON=/var/lib/liteagent-shared/python-env/bin/python
$PYTHON -m pytest -q src/adapter_versions/v2_expanded/tests/<focused_test.py>
$PYTHON -m ruff check <changed_python_files>
```

## 明确不做

- 不新增、加严或复制门禁，不建立新的 audit/gate framework。
- 不跑 fixed-189、全量 OSWorld、模型对比或 promotion 流程。
- 不加入任务 ID、题目固定短语、golden 内容、固定坐标、答案、任务级 action 序列或 task-aware 路由。
- 不修改 Chrome、GIMP、OS、VS Code、VLC、Multi-Apps；共享 LiteAgent 文件只有在删除旧 action 引用时才做最小改动。
- 不顺手重构无关代码，不提交结果目录、缓存、虚拟环境、镜像或凭据。

完成 P0 后，把每项的 replacement、提交号和 focused test 结果补到审计文档，再交给集成人员决定是否做更大范围测试。
