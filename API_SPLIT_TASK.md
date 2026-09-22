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

## Order 60 开发记录（2026-09-22）

- 题目：`e4ef0baf-4b52-4590-a47e-d4d464cca2d7`；本地缓存输入为
  `src/third_party/OSWorld/cache/e4ef0baf-4b52-4590-a47e-d4d464cca2d7/42_2.pptx`。
- API replacement：本题仍保持两个独立 mutation，`shape.set_geometry` 负责观察到的图片高度，`slide.format_text_roles` 负责目标页文本格式；没有新增或合并 API。新增的最小修复只收窄 terminal-audit 工具面：已通过的 `propose_done` 只再暴露对应的 `propose_done`（`fail_task` 同理），隐藏 `tools_search`、`presentation.inspect` 和其它 mutation，避免完成后的重复搜索/检查循环。
- 实现提交：`57d69d3ea127154034cc87ce495914dd225e80b1`（`fix(order60): bound terminal audit to completion control`）。
- focused checks：`test_recovery_surface.py` 全文件 **56 passed**；`test_episode_control.py` 与 `test_hybrid_gui_completion.py` **34 passed**；改动文件 `/opt/anaconda3/bin/ruff check ...` 通过。
- 实际单题命令：

  ```bash
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-impress-picture-text-60-retry19-20260922.json \
  --orders 60 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-impress-picture-text-60-retry19-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 35 --max-local-steps 20 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 600 \
  --max-output-tokens 512 --reasoning-mode non_thinking \
  --temperature 0 --request-timeout 180
  ```

- retry19：`status=passed`、`reward=1.0`、`termination_reason=agent_done`；原始 evaluator 日志为 `COMPARISON SUCCESSFUL - Files match`。轨迹为 `presentation.inspect -> shape.set_geometry -> presentation.inspect -> slide.format_text_roles -> presentation.inspect -> presentation.save -> presentation.inspect -> propose_done`，未再出现 terminal-audit 循环。结果见 `src/adapter_versions/v2_expanded/experiments/local-impress-picture-text-60-retry19-20260922/workers/worker-00/results.json`。

## Order 67 开发记录（2026-09-22）

- 题目：`0e47de2a-32e0-456c-a366-8c607ef7a9d2`；要求为每页左下角添加页码。复验使用 OSWorld 按原始 URL 命中的 UUID 前缀缓存 DOCX；该原始文件没有页脚，evaluator 回写文件与输入缓存相互独立。
- API replacement：保留 `document.add_page_numbers`，公开参数仅为必填 `position`。已有原生页码字段只更新对齐、编号类型和 offset；缺少页码字段时在独立页脚段落创建。已有页脚文本、其它字段和未使用页样式保持不变，禁止破坏性 `clear_footer` 类参数。
- 实现提交：`3d9b616cb172772683672474fd3be0f83b22b6da`（`writer: preserve footer when adding page numbers`）。本次当前源码复验不需要新增 Writer 代码提交。
- focused checks：`test_writer_page_numbers.py` 与 `test_writer_footer_observation.py` **12 passed**；Writer schema、manifest、worker 和页码测试执行 `/opt/anaconda3/bin/ruff check ...` 通过。
- 实际单题命令：

  ```bash
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-writer-page-numbers-67-split-retry4-20260922.json \
  --orders 67 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-writer-page-numbers-67-split-retry4-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 300 \
  --max-output-tokens 512 --reasoning-mode non_thinking \
  --temperature 0 --request-timeout 180
  ```

- retry4：`status=passed`、`reward=1.0`、`termination_reason=agent_done`。轨迹为 `document.add_page_numbers(position="bottom_left") -> document.inspect -> propose_done`，completion gate 通过且没有终止审计循环。结果见 `src/adapter_versions/v2_expanded/experiments/local-writer-page-numbers-67-split-retry4-20260922/workers/worker-00/results.json`。

## Order 68 开发记录（2026-09-22）

- 题目：`0e763496-b6bb-4508-a427-fad0b6c3e195`；要求把全文字体改为 `Times New Roman`。输入从非官方镜像预取到 OSWorld 原始 URL 的 UUID 前缀缓存，DOCX SHA-256 为 `76d9039c2b6c86381cbcf1a87178c6c50bbcf9b1e3d651ddb6e9caa189988430`，ZIP 完整性检查通过；评测未访问 Hugging Face 官方站。
- API replacement：P1 复核结论为保留 `document.set_font(font_name)`，不再拆分。它只接受一个必填字体族字符串，一次调用只表达一条全文字体规则；worker 对正文和表格文本统一写入 `CharFontName`、`CharFontNameAsian`、`CharFontNameComplex`，并通过 `fonts` 原生回读验证。旧 opaque `params` wrapper 已由直接 `font_name` schema 取代，没有第二个同义 action。
- 实现提交：`b800fd9c8861528bc5dc0c204c88a84163835769`（`Import runnable LiteAgent source snapshot`，当前窄 schema、validation、worker 与字体观察测试均包含于该导入提交）；本次复核不需要新增 Writer 代码提交。
- focused checks：`test_writer_font_observation.py` 与 `test_writer_preference_evidence.py` **22 passed**；Writer manifest、schema、worker 和两份测试执行 `/opt/anaconda3/bin/ruff check ...` 通过。
- 实际单题命令：

  ```bash
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  HF_ENDPOINT=https://hf-mirror.com \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-writer-font-68-retain-20260922.json \
  --orders 68 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-writer-font-68-retain-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 300 \
  --max-output-tokens 512 --reasoning-mode non_thinking \
  --temperature 0 --request-timeout 180
  ```

- 当前结果：`status=passed`、`reward=1.0`、`termination_reason=agent_done`。轨迹为 `document.set_font(font_name="Times New Roman") -> document.inspect -> propose_done`；mutation 处理 23 个文本对象，inspect 的西文、亚洲和复杂文本字体回读均包含 `Times New Roman`。结果见 `src/adapter_versions/v2_expanded/experiments/local-writer-font-68-retain-20260922/workers/worker-00/results.json`。
