# liuxv：大粒度 API 拆分任务

工作分支：`codex/api-split-liuxv`

完整复查见 [`docs/api-granularity-audit-20260920.md`](docs/api-granularity-audit-20260920.md)。实际执行边界以 [`task.md`](task.md) 的 28 道固定 Order 为准；除原 Calc、Impress、Writer、Thunderbird 范围外，还包括 `os.pdf.extract_text_batch` 的完整六题组。

## P0 候选库存（不是执行顺序）

以下编号只用于阅读当前题目和轨迹时定位相关旧 action。必须按 `task.md` 一题一题推进，不能按本清单逐项施工。

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
- `os.pdf.extract_text_batch`（Orders 95、96、99、102、107、108；整个题组仅归 liuxv）

另外，`slides.format_text_roles` 去掉 overrides 后复核一次：只有“显式多页 + 完全相同规则 + mutation 前全量 preflight”同时成立，才保留多页批处理。

## 每题交付要求

1. 模型可见 schema/description、运行时 validation、dispatch/worker、默认 verification 和调用方必须同步更新，不能保留两套不一致契约。
2. 删除或隔离旧大粒度入口；不能只在描述里说“一次一个”，实现却仍接受多个独立效果。
3. 非法组合要返回可操作的 Adapter 错误，让模型知道哪个字段冲突以及下一次应怎样调用。
4. 新增或调整最小针对性测试，至少覆盖一个有效调用、一个被拒绝的大粒度组合、一个 verification 失败或状态保留场景。
5. 只运行该 action 所属 Adapter 的针对性 pytest、相关契约测试和改动 Python 文件的 Ruff。不要跑全量评测。
6. 一道题形成一个独立闭环；提交信息写清 Order、涉及的旧入口、replacement 和实际验证命令。

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
- 除 `task.md` 固定 PDF 题组所必需的 `os.pdf.extract_text_batch` 和 Multi-Apps 调用面外，不修改 Chrome、GIMP、其他 OS、VS Code、VLC；共享 LiteAgent 文件只做当前题必需的最小改动。
- 不顺手重构无关代码，不提交结果目录、缓存、虚拟环境、镜像或凭据。

每完成一道题，把该题的 replacement、提交号和 focused check 结果补到审计文档；固定清单完成后再交给集成人员决定是否做更大范围测试。

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

## Order 81 开发记录（2026-09-22）

- 题目：`d53ff5ee-3b1a-431e-b2be-30ed2673079b`；要求把 Writer 文档中的全部大写文本转换为小写。输入和 golden 只从本地镜像缓存读取；输入 SHA-256 为 `26932140b262b8886b42d82e3a8acd1e48a4c9c97abe803791e9cf1ab10d3ce8`，golden SHA-256 为 `4bf3cec92ae61e1263f4bd54131c03ec90f6dbc8f70159a3a1fdc6be10cfc19a`，两者均通过 ZIP 完整性检查。
- API replacement：P1 复核结论为保留 `document.transform_case(mode)`，不拆分 action。`mode` 严格且仅允许 `lower` 或 `title`，一次调用只选择一条互斥的全文同构大小写规则，不含操作数组、范围选择或第二个独立副作用。运行时在自动保存前对正文和表格段落逐项原生回读；任一写入未持久化即返回 `VERIFICATION_FAILED`。
- 实现提交：`3d98fd27363b13d79754f6af09fd9367e875ae3b`（`fix(order81): verify whole-document case transforms`）。
- focused checks：`test_writer_transform_case.py` 与 `test_bounded_writer_decomposition.py` **46 passed**；Writer schema、worker 和新增测试执行 `/opt/anaconda3/bin/ruff check ...` 通过；`git diff --check` 通过。
- 实际单题命令：

  ```bash
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  HF_ENDPOINT=https://hf-mirror.com \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-writer-transform-case-81-20260922.json \
  --orders 81 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-writer-transform-case-81-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 300 \
  --max-output-tokens 512 --reasoning-mode non_thinking \
  --temperature 0 --request-timeout 180
  ```

- 当前结果：`status=passed`、`reward=1.0`、`path_class=generic_api_only`；原始 `compare_docx_files` evaluator 返回 `1.0`。第 1 步即调用 `document.transform_case(mode="lower")`，Adapter 返回 `paragraphs_changed=14`、`paragraphs_verified=18` 并成功保存，随后 `document.inspect` 回读为小写。模型之后重复检查并以 `termination_reason=stalled_no_progress` 收尾，但结果文档仍与 golden 匹配。结果见 `src/adapter_versions/v2_expanded/experiments/local-writer-transform-case-81-20260922/workers/worker-00/results.json`。

## Order 83 开发记录（2026-09-22）

- 题目：`e528b65e-1107-4b8c-8988-490e4fece599`；要求把 Writer 文档中每个单词的首字母改为大写。输入和 golden 只从本地镜像缓存读取；输入 SHA-256 为 `b7a84074837e33be184bac095e0c6824bd818a79791c3358ef2cdcd352f046b4`，golden SHA-256 为 `6b2a1968cd8ba4a91ebf122d11a6168ffdc9fec314e1641b8f635fe7644ad74b`，两者均通过 ZIP 完整性检查。
- 历史与本题判断：历史 recovery 轨迹已证明模型实际选择 `document.transform_case(mode="title")`；该 action 与 Order 81 的 `lower` 共用同一窄契约和同构全文事务，因此本题不新增、不拆分 API。新增 title-case focused 用例只验证通用的首个英文字母转换和原生回读。
- API replacement：保留 `document.transform_case(mode)`；`mode` 仍严格为互斥的 `lower` 或 `title`，不接受操作数组、范围选择或额外副作用。实现提交沿用 `3d98fd27363b13d79754f6af09fd9367e875ae3b`；本题新增测试提交为 `140f7db`（`test(order83): cover Writer title-case transform`）。
- focused checks：`test_writer_transform_case.py` **6 passed**；新增测试 Ruff 通过；输入与 golden `unzip -t` 通过。
- 第一次单题运行因 qwen1 两次 `522` 消耗了 300 秒 episode 上限，未产生 evaluator 分数；保留在 `experiments/local-writer-transform-case-83-20260922/`。随后仅增加同一协议的 600 秒传输余量，未改源码或注入参数。
- 实际通过命令：

  ```bash
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  HF_ENDPOINT=https://hf-mirror.com \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-writer-transform-case-83-retry1-20260922.json \
  --orders 83 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-writer-transform-case-83-retry1-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 600 \
  --max-output-tokens 512 --reasoning-mode non_thinking \
  --temperature 0 --request-timeout 180
  ```

- 当前结果：`status=passed`、`reward=1.0`、`path_class=generic_api_only`、`termination_reason=stalled_no_progress`；原始 `compare_docx_files` evaluator 返回 `1.0`。第 1 步 `document.transform_case(mode="title")` 返回 `paragraphs_changed=3`、`paragraphs_verified=4` 并自动保存，结果见 `src/adapter_versions/v2_expanded/experiments/local-writer-transform-case-83-retry1-20260922/workers/worker-00/results.json`。

## Order 91 开发记录（2026-09-22）

- 题目：`d9b7c649-c975-4f53-88f5-940b29c47247`；要求从 Thunderbird `daily` 文件夹提取最新 5 封邮件，按最早到最近排序，在桌面创建 `report.xlsx`，列出 `sender_name`、`sender_address`、`subject`、`CC`、`number_of_attachments`。题面、历史轨迹和最终轨迹均未向模型暴露题目 ID、golden 或 evaluator 内容。
- 人工轨迹判断：历史失败依次暴露了邮件查询缺失、跨应用结果未保留、Calc 无新建工作簿入口，以及模型混淆“选最新”和“返回排序”。本题实际需要的独立 API 是 `thunderbird.messages.query` 和 `libreoffice_calc.workbook.create_new`；`range.write`、显式 save/save_as 均不是本题必须的额外 mutation。
- API replacement：保留 `messages.query` 的单一查询契约，强化 `select_from` 与 `order` 的正交语义；新增通用边界校验，指令要求 latest/most-recent 时拒绝 `select_from="earliest"`，要求下一次用 `select_from="latest"`，不改写模型参数、不注入邮件数据。Calc 使用已有 `workbook.create_new`，一次以模型提供的 headers/rows 创建并保存工作簿；未新增宏 API。
- 实现提交：`d077b18f02805becaa8f5ff21bb7d1c27b5e8c2c`（`fix(order91): guard latest mail selection semantics`）。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded pytest -q src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`，结果 **27 passed**；`git diff --check` 通过。
- 实际单题命令：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com \
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-mail-report-91-20260922.json \
  --orders 91 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-mail-report-91-retry4-20260922/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --max-steps 35 --max-local-steps 20 --max-agent-seconds 900
  ```

- 当前结果：`status=passed`、`reward=1.0`。模型先因矛盾的 `select_from="earliest"` 被通用语义校验拒绝，随后用 `select_from="latest"`、`order="ascending"` 查询并用 `workbook.create_new` 写入 5 行和 5 个表头；Adapter 返回 `A1:E6`、30 个单元格并确认已保存。结果见 `src/adapter_versions/v2_expanded/experiments/local-mail-report-91-retry4-20260922/workers/worker-00/results.json`，调用轨迹见同目录 `raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/adapter_calls.jsonl`。
## Order 95 开发记录（2026-09-25 修复后）

- 结果：`status=passed`、`reward=1.0`、`termination_reason=agent_done`。retry20 只执行一次 `os.pdf.extract_text_batch`，随后调用 `libreoffice_calc.workbook.create_new`，写入 4 篇 PDF 的首作者、完整邮箱和 affiliation；结果文件与 golden 完全一致。
- 最小可行修复：在观察完成后，创建表格前校验模型组装的每个 tuple 必须来自同一 PDF 的首作者、完整邮箱和完整 affiliation；拒绝猜测邮箱、共同作者、截断 affiliation 和 `null/none/n/a`。对题面使用 “e-mail” 的表格，要求使用 `Name / Mail / Affiliation` 作为字段标题。校验只返回纠正提示，不替模型填值或跨文档拼接。
- API replacement：保持两个独立 API：`os.pdf.extract_text_batch`（有界、只读观察）和 `libreoffice_calc.workbook.create_new`（模型提供 headers/rows 的原生工作簿创建与保存）。没有新增 PDF-to-workbook 组合 API，也没有任务专用 parser/route。
- 实现提交：`9361c0d`（`fix(order95): validate evidence-derived author assembly`）。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded pytest -q src/adapter_versions/v2_expanded/tests/test_batch_table_stage.py`，结果 **58 passed**；`git diff --check` 通过。
- 实际单题命令（本地 HF mirror/cache，Qwen endpoint）：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-pdf-authors-95-retry20-20260925.json --orders 95 --result-dir src/adapter_versions/v2_expanded/experiments/local-pdf-authors-95-retry20-20260925/workers/worker-00 --base-url https://qwen1.jinmaoapi.cc.cd/v1 --model qwen3.5-4b --max-steps 45 --max-local-steps 25 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1200 --max-output-tokens 768 --reasoning-mode non_thinking --request-timeout 240 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1
  ```

- 证据：`src/adapter_versions/v2_expanded/experiments/local-pdf-authors-95-retry20-20260925/workers/worker-00/results.json`；最终调用轨迹见同目录 `raw/run-1/95-multi_apps-b5062e3e-641c-4e3a-907b-ac864d2e7652/adapter_calls.jsonl`。

### Order 102（2026-09-25）

- 结果：`status=passed`、`reward=1.0`、`termination_reason=agent_done`；结果文件为
  `src/adapter_versions/v2_expanded/experiments/local-file-organize-102-20260925-retry7-20260925/workers/worker-00/results.json`。
- API replacement：保持窄 API 链 `os.filesystem.find(kind=any)`（观察）→可选
  `os.pdf.extract_text_batch`（歧义内容）→逐项 `os.filesystem.rename`（移动），不新增批量组织 API。
  新增通用 observation marker 记录已观察条目和 `classify_and_move` 阶段；标记后禁止重复
  `filesystem.find`，工具面在发现 rename 前只给 `tools_search`，发现后只给 rename，全部完成后只给
  `propose_done`。分类提示要求仅内容确认的学术论文进 `Paper_reading`，代码项目进 `Projects`，其余进
  `Miscellaneous`。
- focused check：`113 passed`（filesystem discovery/context projection）及 compileall 通过。
- 实际命令：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com PYTHONPATH="$PWD:$PWD/../third_party/OSWorld:$PWD/../" /var/lib/liteagent-shared/python-env/bin/python scripts/run_lite_agent_pilot.py --config experiments/configs/local-file-organize-102-20260925.json --orders 102 --result-dir experiments/local-file-organize-102-20260925-retry7-20260925/workers/worker-00 --base-url https://qwen1.jinmaoapi.cc.cd/v1 --model qwen3.5-4b --max-steps 45 --max-local-steps 25 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1200 --max-output-tokens 768 --reasoning-mode non_thinking --request-timeout 240 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1
  ```

- 实现提交：`2eb1acb`（`fix(order102): gate organization after filesystem observation`）；交由集成人员统一合并。

## Order 121（2026-09-27）

- 题目：`f5c13cdd-205c-4719-a562-348ae5cd1d91`。题面要求从付款记录中识别未付款人员，并把对应地址加入已经打开的 Thunderbird 草稿收件人栏；原始题目、配置和历史失败审计见 `src/third_party/OSWorld/evaluation_examples/examples/multi_apps/f5c13cdd-205c-4719-a562-348ae5cd1d91.json`、`src/adapter_versions/v2_expanded/experiments/configs/generic-only-coverage-order121-v126.json` 及 `src/adapter_versions/v2_expanded/docs/project-progress.md` 的 Order 121 条目。
- 人工轨迹判断：本题只有两个独立动作：`libreoffice_calc.workbook.read_file`（读取模型选定的本地表格）和 `thunderbird.compose.set_recipients`（编辑已打开草稿的 To 字段）。历史失败集中在模型没有先完成表格观察，或没有发现已有收件人编辑路由；没有出现 P0 候选的异构 mutation、批量独立设置或隐式写入。
- API replacement：两项均保留，不新增组合 API。`workbook.read_file` 只读且限制路径、工作表/范围和行列窗口；需要已打开工作簿的精确单一区域时由模型另行调用 `range.read`。`compose.set_recipients` 只接收一组模型选定的纯地址，`append`/`replace` 仅选择同一 To 字段的状态迁移，支持可选已观察 subject 消歧；worker 只操作地址 pill 并逐项回读，禁止创建或发送消息。搜索目录已包含 spreadsheet/read-file 及 receiver/recipient/draft 术语，恢复面不会把这两个动作合并。
- 实现提交：本题不需要源码变更；现有窄契约来自导入快照 `b800fd9` 及其后续 Thunderbird 路由提交。新增本记录的提交为当前 Order 121 文档提交。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded python -m pytest -q src/adapter_versions/v2_expanded/tests/test_recovery_surface.py src/adapter_versions/v2_expanded/tests/test_active_workbook_discovery.py src/adapter_versions/v2_expanded/tests/test_spreadsheet_open_semantics.py src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`，结果 **156 passed**；搜索复核确认表格读取和收件人编辑均能从多应用目录检索到，`git diff --check` 通过。
- 单题结果：历史正式 Order 121 复跑在 `src/adapter_versions/v2_expanded/docs/project-progress.md` 的最终审计中记录为 evaluator **PASS / 1.0**（8 events，`compose.set_recipients` 追加四个模型选定地址，随后完成提议）；当前 checkout 未携带该历史运行的原始结果目录，因此本次仅复核冻结配置、题目定义、现有轨迹审计和当前契约测试，没有伪造新的 evaluator 结果或改写模型参数。

## Order 152（2026-09-27）

- 题目：`9bc3cc16-074a-45ac-9bdc-b2a362e1daf3`；要求把收件箱全部邮件分别备份为 `.eml` 到用户指定目录。题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/9bc3cc16-074a-45ac-9bdc-b2a362e1daf3.json`，历史 baseline/candidate 配置分别为 `generic-only-coverage-order152-v155.json` 和 `generic-only-coverage-order152-export-eml-schema-v156.json`。
- 人工判断：本题只涉及 `thunderbird.messages.export_eml`。它是一个显式同构批处理事务：一次调用只选择一个可见文件夹和一个输出目录，Adapter 在当前 profile 中解析 mailbox 后逐封写出 `.eml`；输出目录已有 `.eml` 时 fail-closed，不删除或覆盖已有文件。因此按 P1 复核结论保留，不拆成逐邮件 API，也不增加题目专用路由。
- API state：模型可见 schema 使用 `folder_name` + `output_dir`；runtime validation、dispatch、worker 默认 `exported_eml` verification 和 folder resolver 保持一致。Adapter 仍兼容内部 `source` + `destination` 旧契约，但模型 schema 不暴露它；混用两套参数会返回明确 `INVALID_REQUEST`。
- 实现提交：`be6c7af`（`fix(order152): validate export eml contract`）；在 action dispatch 入口执行完整参数校验，避免 worker 绕过混合契约拒绝。
- focused checks：`test_mail_selector_contract.py` **30 passed**；`/opt/anaconda3/bin/ruff check` 对改动 Thunderbird action/test 通过；`git diff --check` 通过。
- 正式 OSWorld 单题结果：配置 `src/adapter_versions/v2_expanded/experiments/configs/formal-order152-20260927.json`，结果目录 `src/adapter_versions/v2_expanded/experiments/formal-order152-20260927-rerun2/`。原始 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`；模型实际调用 `messages.export_eml(folder_name="Inbox", output_dir="~/emails.bak")`，Adapter 返回 `count=6` 且 `exported_eml` verification 通过。完整轨迹位于 `src/adapter_versions/v2_expanded/experiments/formal-order152-20260927-rerun2/workers/worker-00/raw/run-1/152-thunderbird-9bc3cc16-074a-45ac-9bdc-b2a362e1daf3/`，实际 served model 为 `Qwen3.5-9B-Q4_K_M`，thinking mode 为 `non_thinking`。

## Order 157（2026-09-28）

- 题目：`3f49d2cc-f400-4e7d-90cc-9b18e401cc31`；要求在 Thunderbird 中启用 Unified Folders/unified inbox。完整题面来自 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/3f49d2cc-f400-4e7d-90cc-9b18e401cc31.json`。固定 coverage 配置为 `generic-only-coverage-order157-v158.json`；该配置没有保留可审计的原始运行轨迹，因此没有把缺失轨迹当作失败原因或答案证据。
- 人工判断：本题只涉及原 `thunderbird.mail.configure` 中的 `unified_inbox` 语义。它应独立表达一个 folder-tree view mode mutation，并只更新 `xulstore.json` 的 `messenger.xhtml/folderTree/mode`；不应同时修改 prefs.js 或接受签名、回复引用、过滤器、主题等异构 setting。
- API replacement：新增模型可见 `thunderbird.inbox.set_unified(enabled)`，并在 schema、runtime validation、dispatch、worker 默认 `json_path` verification 和 catalog action surface 中保持同名窄契约。旧 `mail.configure` 不再接受组合参数，返回带 replacement actions 的 `UNSUPPORTED_ACTION`。本题不新增 task-aware 路由或固定值以外的运行时逻辑。
- focused checks：本题相关 contract 用例 **5 passed**（unified/combined/identity-setting surface）；Thunderbird action、schema、manifest、worker 和 mail contract 执行 Ruff 通过。整组 mail contract 为 **86 passed，2 个与本题无关的 recovery-surface 失败**，失败来自共享工作树中并行 Order 107 的未提交 generic routing 变更。
- 单题运行：曾按 `formal-order157-20260928.json` 尝试在 `local-order157-unified-inbox-20260928/` 运行；runner 在启动前因共享工作树并行 Order 107 进程造成 source-tree seal 漂移而拒绝，未产生 evaluator 结果或轨迹，故本题当前记为 blocked，不能宣称 OSWorld PASS。
