# liuxv：大粒度 API 拆分任务

<!-- order99-checker-consistency-20261013 begin -->
Order 99 checker 判定/理由一致性修复：**PASS / reward=1.0，18 步，495.091 秒，agent_done**；北京时间 2026-10-13T11:08:26.751075+08:00 完成。原第 15 步的 move/retain 矛盾已消除，第 16 步保留并推进，第 18 步正常完成。schema/提示先给事实理由再给动作；首次判定冲突时最多独立复核一次，只反馈 checker 自己的判定，不泄露执行模型答案、不自动覆盖动作。交付 `e6c8e1e`（独立增量补丁与基线 hash；活动源码已应用）。

[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl) / [轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-checker-consistency-20261013/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order99-checker-consistency-repair-20261013.md) / [固定最新入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order99-latest.md) / [证据回执](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order99-checker-consistency-result-20261013.json)。13 项定向检查、4 项临时 contract、真实证据重放与纠错重放、Ruff 通过。原批次 FAIL 与分数保持不变，单题 PASS 独立登记。
<!-- order99-checker-consistency-20261013 end -->


> 2026-10-10 全部 28 题结果与轨迹已核对：请从 [统一逐题入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md) 查询。固定批次 23/28 PASS；91、99、102 后续单题 PASS；最新已核对结果 26/28 PASS，仅 107、108 仍 FAIL。下方旧日期段落中的“当前/最新/PASS”只适用于各自记录的运行条件。

历史 API 拆分工作分支：`codex/api-split-liuxv`。2026-10-26 起主活动源码为 `/home/liuxv/liteagent` 的 `codex/v4`；后续工作以 README 和当前活动分支为准。

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

> Order 60 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-60)；本节保留其原始日期与实验条件。

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

> Order 67 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-67)；本节保留其原始日期与实验条件。

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

> Order 68 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-68)；本节保留其原始日期与实验条件。

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

> Order 81 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-81)；本节保留其原始日期与实验条件。

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

> Order 83 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-83)；本节保留其原始日期与实验条件。

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

> Order 91 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-91)；本节保留其原始日期与实验条件。

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

> Order 95 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-95)；本节保留其原始日期与实验条件。

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

> Order 102 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-102)；本节保留其原始日期与实验条件。

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

> Order 121 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-121)；本节保留其原始日期与实验条件。

- 题目：`f5c13cdd-205c-4719-a562-348ae5cd1d91`。题面要求从付款记录中识别未付款人员，并把对应地址加入已经打开的 Thunderbird 草稿收件人栏；原始题目、配置和历史失败审计见 `src/third_party/OSWorld/evaluation_examples/examples/multi_apps/f5c13cdd-205c-4719-a562-348ae5cd1d91.json`、`src/adapter_versions/v2_expanded/experiments/configs/generic-only-coverage-order121-v126.json` 及 `src/adapter_versions/v2_expanded/docs/project-progress.md` 的 Order 121 条目。
- 人工轨迹判断：本题只有两个独立动作：`libreoffice_calc.workbook.read_file`（读取模型选定的本地表格）和 `thunderbird.compose.set_recipients`（编辑已打开草稿的 To 字段）。历史失败集中在模型没有先完成表格观察，或没有发现已有收件人编辑路由；没有出现 P0 候选的异构 mutation、批量独立设置或隐式写入。
- API replacement：两项均保留，不新增组合 API。`workbook.read_file` 只读且限制路径、工作表/范围和行列窗口；需要已打开工作簿的精确单一区域时由模型另行调用 `range.read`。`compose.set_recipients` 只接收一组模型选定的纯地址，`append`/`replace` 仅选择同一 To 字段的状态迁移，支持可选已观察 subject 消歧；worker 只操作地址 pill 并逐项回读，禁止创建或发送消息。搜索目录已包含 spreadsheet/read-file 及 receiver/recipient/draft 术语，恢复面不会把这两个动作合并。
- 实现提交：本题不需要源码变更；现有窄契约来自导入快照 `b800fd9` 及其后续 Thunderbird 路由提交。新增本记录的提交为当前 Order 121 文档提交。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded python -m pytest -q src/adapter_versions/v2_expanded/tests/test_recovery_surface.py src/adapter_versions/v2_expanded/tests/test_active_workbook_discovery.py src/adapter_versions/v2_expanded/tests/test_spreadsheet_open_semantics.py src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`，结果 **156 passed**；搜索复核确认表格读取和收件人编辑均能从多应用目录检索到，`git diff --check` 通过。
- 单题结果：历史正式 Order 121 复跑在 `src/adapter_versions/v2_expanded/docs/project-progress.md` 的最终审计中记录为 evaluator **PASS / 1.0**（8 events，`compose.set_recipients` 追加四个模型选定地址，随后完成提议）；当前 checkout 未携带该历史运行的原始结果目录，因此本次仅复核冻结配置、题目定义、现有轨迹审计和当前契约测试，没有伪造新的 evaluator 结果或改写模型参数。

## Order 152（2026-09-27）

> Order 152 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-152)；本节保留其原始日期与实验条件。

- 题目：`9bc3cc16-074a-45ac-9bdc-b2a362e1daf3`；要求把收件箱全部邮件分别备份为 `.eml` 到用户指定目录。题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/9bc3cc16-074a-45ac-9bdc-b2a362e1daf3.json`，历史 baseline/candidate 配置分别为 `generic-only-coverage-order152-v155.json` 和 `generic-only-coverage-order152-export-eml-schema-v156.json`。
- 人工判断：本题只涉及 `thunderbird.messages.export_eml`。它是一个显式同构批处理事务：一次调用只选择一个可见文件夹和一个输出目录，Adapter 在当前 profile 中解析 mailbox 后逐封写出 `.eml`；输出目录已有 `.eml` 时 fail-closed，不删除或覆盖已有文件。因此按 P1 复核结论保留，不拆成逐邮件 API，也不增加题目专用路由。
- API state：模型可见 schema 使用 `folder_name` + `output_dir`；runtime validation、dispatch、worker 默认 `exported_eml` verification 和 folder resolver 保持一致。Adapter 仍兼容内部 `source` + `destination` 旧契约，但模型 schema 不暴露它；混用两套参数会返回明确 `INVALID_REQUEST`。
- 实现提交：`be6c7af`（`fix(order152): validate export eml contract`）；在 action dispatch 入口执行完整参数校验，避免 worker 绕过混合契约拒绝。
- focused checks：`test_mail_selector_contract.py` **30 passed**；`/opt/anaconda3/bin/ruff check` 对改动 Thunderbird action/test 通过；`git diff --check` 通过。
- 正式 OSWorld 单题结果：配置 `src/adapter_versions/v2_expanded/experiments/configs/formal-order152-20260927.json`，结果目录 `src/adapter_versions/v2_expanded/experiments/formal-order152-20260927-rerun2/`。原始 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`；模型实际调用 `messages.export_eml(folder_name="Inbox", output_dir="~/emails.bak")`，Adapter 返回 `count=6` 且 `exported_eml` verification 通过。完整轨迹位于 `src/adapter_versions/v2_expanded/experiments/formal-order152-20260927-rerun2/workers/worker-00/raw/run-1/152-thunderbird-9bc3cc16-074a-45ac-9bdc-b2a362e1daf3/`，实际 served model 为 `Qwen3.5-9B-Q4_K_M`，thinking mode 为 `non_thinking`。

## Order 157（2026-09-28）

> Order 157 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-157)；本节保留其原始日期与实验条件。

- 题目：`3f49d2cc-f400-4e7d-90cc-9b18e401cc31`；要求在 Thunderbird 中启用 Unified Folders/unified inbox。完整题面来自 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/3f49d2cc-f400-4e7d-90cc-9b18e401cc31.json`。固定 coverage 配置为 `generic-only-coverage-order157-v158.json`；该配置没有保留可审计的原始运行轨迹，因此没有把缺失轨迹当作失败原因或答案证据。
- 人工判断：本题只涉及原 `thunderbird.mail.configure` 中的 `unified_inbox` 语义。它应独立表达一个 folder-tree view mode mutation，并只更新 `xulstore.json` 的 `messenger.xhtml/folderTree/mode`；不应同时修改 prefs.js 或接受签名、回复引用、过滤器、主题等异构 setting。
- API replacement：新增模型可见 `thunderbird.inbox.set_unified(enabled)`，并在 schema、runtime validation、dispatch、worker 默认 `json_path` verification 和 catalog action surface 中保持同名窄契约。旧 `mail.configure` 不再接受组合参数，返回带 replacement actions 的 `UNSUPPORTED_ACTION`。本题不新增 task-aware 路由或固定值以外的运行时逻辑。
- focused checks：本题相关 contract 用例 **5 passed**（unified/combined/identity-setting surface）；Thunderbird action、schema、manifest、worker 和 mail contract 执行 Ruff 通过。整组 mail contract 为 **86 passed，2 个与本题无关的 recovery-surface 失败**，失败来自共享工作树中并行 Order 107 的未提交 generic routing 变更。
- 正式 OSWorld 单题结果：配置 `src/adapter_versions/v2_expanded/experiments/configs/formal-order157-20260928.json`，有效结果目录为 `src/adapter_versions/v2_expanded/experiments/local-order157-unified-inbox-20260928-rerun2/`。原始 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`，`result.txt` 为 `1.0`；模型实际调用 `inbox.set_unified(enabled=true)`，Adapter 通过 `xulstore.json` 的 `chrome://messenger/content/messenger.xhtml/folderTree/mode=smart` verification。完整轨迹位于 `src/adapter_versions/v2_expanded/experiments/local-order157-unified-inbox-20260928-rerun2/workers/worker-00/raw/run-1/157-thunderbird-3f49d2cc-f400-4e7d-90cc-9b18e401cc31/`，其中 `adapter_calls.jsonl` 保留实际调用证据；实际 served model 为 `Qwen3.5-9B-Q4_K_M`，thinking mode 为 `non_thinking`。

## Order 158（2026-09-29）

> Order 158 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-158)；本节保留其原始日期与实验条件。

- 题目：`f201fbc3-44e6-46fc-bcaa-432f9815454c`；要求关闭 Thunderbird 回复中的原文引用，使回复不再带缩进和 `>`。完整题面和 evaluator 定义来自 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/f201fbc3-44e6-46fc-bcaa-432f9815454c.json`。
- 人工轨迹判断：本题只有一个 mutation，目标是现有 identity 的 `mail.identity.<identity>.auto_quote=false`。原组合入口 `mail.configure` 将签名、回复引用、过滤器、Unified Folders 和主题混在同一个 union；本题实际需要的最小 replacement 是 `identity.set_reply_quoting`，并先用只读 `identities.query` 获取精确 profile identity。没有新增题目专用路由或固定答案。
- API replacement：沿用 `4da4729`/`a09b33b` 已完成的独立 action。模型可见 schema、catalog、instruction routing、runtime validation、dispatch、worker 和默认 preference verification 均只接受 `identity` + `enabled`；运行时只写 `prefs.js` 的 `mail.identity.<identity>.auto_quote`，不会触碰其他 mail/xulstore 设置。旧 `mail.configure` 在 mutation 前返回带 replacement actions 的 `UNSUPPORTED_ACTION`。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded python -m pytest -q src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`，结果 **32 passed**；相关 Thunderbird action/schema/manifest/worker、catalog 和 instruction routing 执行 Ruff 通过；`git diff --check` 通过。
- 单题复跑：首次配置 `src/adapter_versions/v2_expanded/experiments/configs/formal-order158-20260929.json` 因原始 Hugging Face 下载超时记录为 `environment_failure`，没有模型动作；完整失败轨迹保留在 `src/adapter_versions/v2_expanded/experiments/formal-order158-20260929/workers/worker-00/raw/run-1/158-thunderbird-f201fbc3-44e6-46fc-bcaa-432f9815454c/`。使用 `HF_ENDPOINT=https://hf-mirror.com` 重试后，结果位于 `src/adapter_versions/v2_expanded/experiments/formal-order158-20260929-retry1/workers/worker-00/results.json`，原始轨迹位于同目录 `raw/run-1/158-thunderbird-f201fbc3-44e6-46fc-bcaa-432f9815454c/`；模型调用链为 `identities.query -> identity.set_reply_quoting(identity="id1", enabled=false) -> propose_done`，Adapter preference verification 观察到 `mail.identity.id1.auto_quote=false`，正式 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`。
- 实际复跑命令：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/formal-order158-20260929.json --orders 158 --result-dir src/adapter_versions/v2_expanded/experiments/formal-order158-20260929-retry1/workers/worker-00 --base-url https://qwen1.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B-Q4_K_M --max-steps 30 --max-local-steps 20 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 600 --max-output-tokens 512 --reasoning-mode non_thinking --request-timeout 240 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1
  ```
- 2026-10-03 endpoint 重跑：使用冻结配置 `src/adapter_versions/v2_expanded/experiments/configs/formal-order158-20261003.json`，将 `base_url` 切换为 `https://qwen.jinmaoapi.cc.cd/v1`。结果位于 `src/adapter_versions/v2_expanded/experiments/formal-order158-20261003-retry3/workers/worker-00/results.json`，完整轨迹位于同目录 `raw/run-1/158-thunderbird-f201fbc3-44e6-46fc-bcaa-432f9815454c/`；模型调用链为 `identities.query -> identity.set_reply_quoting(identity="id1", enabled=false) -> DONE`，Adapter verification 通过，正式 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`。此前 `formal-order158-20261002-retry2` 的 `model_protocol_failure` 保留为未评分重跑，不影响本 PASS。
## Order 160 开发记录（2026-09-29）

> Order 160 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-160)；本节保留其原始日期与实验条件。

- 题目：`08c73485-7c6d-4681-999d-919f5c32dcfa`；要求让 Thunderbird 现有消息过滤器自动应用到 IMAP 子文件夹。
- API replacement：使用单一 `filters.set_subfolder_application(enabled)`；本题不需要 `filters.configure`。修正通用 Thunderbird 意图识别，避免把“应用现有过滤器到子文件夹”误判为新增具体规则。
- 结果：首次运行已成功写入并验证三项 preference，但 completion gate 错误要求 `filters.configure`，保留于 `experiments/local-order160-subfolder-filters-20260929/`。修复后 retry1 通过，`status=passed`、`reward=1.0`、`termination_reason=agent_done`；结果见 `experiments/local-order160-subfolder-filters-20260929-retry1/`。
- 2026-10-02 重跑记录：retry2 因 Docker VM readiness 超时为 `environment_failure`；retry3 因 Thunderbird 窗口未就绪为 `model_protocol_failure`；retry4 发现通用 Runner 收尾读取未初始化的 `route`，虽 Adapter 返回 200 且 preference verification 通过，仍被记录为协议失败。补上 `route = None` 初始化并通过 focused test **5 passed** 后，retry5 正式 evaluator 通过：`status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`。结果见 `experiments/local-order160-subfolder-filters-20261002-retry5/`，完整调用轨迹见该目录下 `raw/run-1/160-thunderbird-08c73485-7c6d-4681-999d-919f5c32dcfa/adapter_calls.jsonl`。
- focused checks：`test_mail_selector_contract.py` **34 passed**；`/opt/anaconda3/bin/ruff check src/adapter_versions/v2_expanded/integrations/lite_agent/thunderbird_filter_semantics.py src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py` 通过。
- 实际复跑命令：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com \
  PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" \
  /var/lib/liteagent-shared/python-env/bin/python \
  src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
  --config src/adapter_versions/v2_expanded/experiments/configs/local-order160-subfolder-filters-20260929.json \
  --orders 160 \
  --result-dir src/adapter_versions/v2_expanded/experiments/local-order160-subfolder-filters-20260929-retry1/workers/worker-00 \
  --base-url https://qwen1.jinmaoapi.cc.cd/v1 \
  --model Qwen3.5-9B-Q4_K_M --reasoning-mode non_thinking \
  --max-steps 30 --max-local-steps 20 --max-soft-restarts 1 \
  --max-no-progress-steps 8 --max-agent-seconds 600 \
  --max-output-tokens 512 --top-k 7 --temperature 0 \
  --request-timeout 240 --model-retries 3
  ```

## Order 107 开发记录（2026-10-02 endpoint rerun）

> Order 107 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-107)；本节保留其原始日期与实验条件。

**最新运行更正（2026-10-10）：Order 107 最新已记录结果为 FAIL / reward=0.0，45 步、505.698 秒。** 最新结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)；最新事件：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/lite_agent_events.jsonl)。下方 2026-10-02 的 local-ecs-rates-107-strict-rerun11 是历史 PASS，不是最新一轮。

- 题目：`881deb30-9549-4583-a841-8270c65f2a17`；从 2015--2023 的 9 份 ECS PDF 读取各校 `Supported/Application`，写入已打开的 `supported_rate.xlsx`。
- API replacement：保留通用窄链 `os.filesystem.find`（一次发现）→逐文件 `os.pdf.tables.inspect`（9 次有界观察）→`libreoffice_calc.workbook.inspect`→`range.write(B2:I10)`→一次 `range.read` 读回→`workbook.save`→`propose_done`。没有批量 PDF-to-Calc mutation，也没有题目专用解析路由；观察 ledger 完成前不会暴露写入，写入读回后才暴露保存。
- 正式 OSWorld 结果：`status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`。结果文件为 `src/adapter_versions/v2_expanded/experiments/local-ecs-rates-107-strict-rerun11-20261002/workers/worker-00/results.json`，调用轨迹为同目录 `raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/adapter_calls.jsonl`，`result.txt` 为 `1.0`。
- 实现提交：`1f873e3`（`fix(order107): split ECS PDF table observations`）；本次 endpoint/config 复跑无新的 API 行为提交。开发记录和 API 审计同步提交：`cd6273e`（`docs(order107): record qwen endpoint rerun`）。
- focused check：`PYTHONPATH=src/adapter_versions/v2_expanded pytest -q src/adapter_versions/v2_expanded/tests/test_batch_table_stage.py -k 'ecs or native or strict or pdf_table'`，结果 **11 passed**。完整文件测试另有 2 个旧断言仍期待 `spreadsheet.*` 名称（当前实现已使用 `workbook.create_new`），与 Order 107 无关。
- 实际命令：

  ```bash
  HF_ENDPOINT=https://hf-mirror.com PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-ecs-rates-107-strict-rerun11-20261002.json --orders 107 --result-dir src/adapter_versions/v2_expanded/experiments/local-ecs-rates-107-strict-rerun11-20261002/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B-Q4_K_M --max-steps 45 --max-local-steps 25 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 1200 --max-output-tokens 8192 --reasoning-mode non_thinking --temperature 0 --request-timeout 240 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1
  ```

## 2026-10-10 固定 28 题测试及通过改动补交

- 本轮原始 evaluator：23/28 PASS；FAIL：91、99、102、107、108。47、53 的 stalled_no_progress 不影响原始 evaluator reward=1.0。
- 按用户后续要求补交通过题目未提交代码块：42 `6985f92`、54 `faecaad`、60 `82a3dbb`、121 `0cb4e62`。158 既有 endpoint PASS 回执同步补交。其他通过题目沿用历史实现提交。
- 完整逐题表、原始结果/轨迹路径与提交边界：[本轮审计](src/adapter_versions/v2_expanded/docs/osworld-passing-submission-20261010.md)。失败题和无法独立归属的共享改动保留未提交；不修改原始测试结果和 task.md。
- 分数来自本轮完整工作区，不是拆分后 commit 的新模型测试。提交快照 Python 语法、Ruff、whitespace 检查通过，未新增测试或复跑 OSWorld。

## 2026-10-10 本轮失败题目正式运行日志

本轮是固定 28 题的串行测试；下列 5 题均为原始 OSWorld evaluator `status=failed`、`reward=0.0`，实际步数达到配置的 45 步上限。`termination_reason=null`、`terminated_by_agent=false` 为原始结果字段，不能改记为 agent_done 或 stalled_no_progress。本日志保留既有单题 PASS 历史，同时将本轮结果明确记录为 FAIL；最初只补日志。后续 Order 91 已完成单题修复并通过，独立结果见下方 PASS 记录，原始批次结果不变。

共同结果文件：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json`，批次 `metadata.status=completed`。使用 `https://qwen.jinmaoapi.cc.cd/v1`、`Qwen3.5-9B`、non_thinking；45 全局步、25 本地步、一次 soft restart、1200 秒 Agent 预算。以下耗时沿用结果文件的 duration_seconds。

### Order 91 — 本轮 FAIL

> Order 91 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-91)；本节保留其原始日期与实验条件。

- 修复前失败事件入口：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)；[单题失败日志](src/adapter_versions/v2_expanded/docs/order91-latest-failure-20261010.md)。最新单题结果见下方搜索修复 PASS。
- Task ID：`d9b7c649-c975-4f53-88f5-940b29c47247`；应用：`multi_apps`。
- 原始结果：`status=failed`、`reward=0.0`，45 步，644.449 秒；`termination_reason=null`、`terminated_by_agent=false`。
- 已观察到的失败表现：evaluator 获取 `/home/user/Desktop/report.xlsx` 时返回 404；文件读取重试记录显示两组各 3 次尝试，大小均为 null，未获得有效 ZIP；evaluator_artifacts/manifest.json 的 result=[null]。这说明本轮未取到要求的结果表格，尚不能仅凭 404 判定文件未生成还是保存路径不一致。
- 完整原始轨迹：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/`；任务定义与输入指令可见该目录 `original_instruction.txt`，模型参数/工具/返回可见 `llm_requests/`、`llm_call_log.jsonl`、`lite_agent_events.jsonl`。轨迹索引为 `trajectory_manifest.json`，正式评分为 `result.txt`，evaluator 产物索引为 `evaluator_artifacts/manifest.json`。
- 本轮处理：只记录测试结果；无本题新修复、API replacement 或复跑提交。相关未提交实现继续保留，不能以历史 PASS 将本次失败标记为完成。

### Order 91 — 后续搜索修复 PASS（2026-10-10）

> Order 91 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-91)；本节保留其原始日期与实验条件。

- 本轮失败根因已核实：45 步全为相同的 Thunderbird 工具搜索，邮件工具虽然注册但被全题关键词触发的文件/Calc 排名加分挤出前六项，未执行任何邮件查询或表格创建。
- 最小修复：Multi-Apps 搜索优先排列当前查询明确指定的应用及操作名称匹配；未指定应用的搜索保留原排序。API 保留，无新增任务专用逻辑。实现提交：`84a3a4c`。
- 临时定向 contract 检查 8 项、改动 Python Ruff 和差异检查通过；只复跑 Order 91，正式 evaluator `status=passed`、`reward=1.0`，5 步、471.024 秒、`termination_reason=agent_done`、`terminated_by_agent=true`。模型这次使用精确搜索名，原失败的自然语言搜索词另经 contract 检查确认首位命中。
- 北京时间：运行开始 2026-10-10 21:15:54；首次工具事件 21:21:37.448572，末次工具事件 21:23:07.063318。部署 OCR 安装超时由 Runner 自动重试成功，只产生一个模型 episode。
- 最新 [results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json)、[事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl)、[评分 result.txt](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/result.txt)（1.0）。邮件返回 5 条，Calc 保存 `A1:E6`、30 单元格；正式 evaluator 成功取回 5075 字节文件。
- 配置/实际命令/完整证据与哈希：[Order 91 单题日志](src/adapter_versions/v2_expanded/docs/order91-query-priority-fix-20261010.md)。首轮日志提交 `76ab5c3`；[API 审计](docs/api-granularity-audit-20260920.md)、[本轮审计](src/adapter_versions/v2_expanded/docs/osworld-passing-submission-20261010.md) 与 [最新结果入口](src/adapter_versions/v2_expanded/docs/index.md) 同步引用这次独立 PASS。历史失败证据保持不变。

### Order 99 — 本轮 FAIL

> Order 99 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-99)；本节保留其原始日期与实验条件。

- 原批次失败事件轨迹直接入口：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[单题最新失败日志](src/adapter_versions/v2_expanded/docs/order99-latest-failure-20261010.md)。
- Task ID：`337d318b-aa07-4f4f-b763-89d9a2dd013f`；应用：`multi_apps`。
- 原始结果：`status=failed`、`reward=0.0`，45 步，475.856 秒；`termination_reason=null`、`terminated_by_agent=false`。
- 已观察到的失败表现：evaluator 获取目标 PDF 时返回 404；evaluator_artifacts/manifest.json 的 result=[null]，只保存了 expected 文件。当前回执不能证明所有发票已经分类完成；本轮失败不覆盖历史单题 PASS。
- 完整原始轨迹：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/`；任务定义与输入指令可见该目录 `original_instruction.txt`，模型参数/工具/返回可见 `llm_requests/`、`llm_call_log.jsonl`、`lite_agent_events.jsonl`。轨迹索引为 `trajectory_manifest.json`，正式评分为 `result.txt`，evaluator 产物索引为 `evaluator_artifacts/manifest.json`。
- 本轮处理：只记录测试结果；无本题新修复、API replacement 或复跑提交。相关未提交实现继续保留，不能以历史 PASS 将本次失败标记为完成。

### Order 102 — 本轮 FAIL

> Order 102 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-102)；本节保留其原始日期与实验条件。

- 原批次失败事件轨迹直接入口：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)；[单题最新失败索引](src/adapter_versions/v2_expanded/docs/order102-latest-failure-20261010.md)。此前 classification-check 为历史运行。
- Task ID：`869de13e-bef9-4b91-ba51-f6708c40b096`；应用：`multi_apps`。
- 原始结果：`status=failed`、`reward=0.0`，45 步，1012.175 秒；`termination_reason=null`、`terminated_by_agent=false`。
- 已观察到的失败表现：evaluator 返回的文件目录列表中，学术论文目录缺少 `paper01.pdf`；另两组 coding/miscellaneous 列表与 manifest 中的 expected 列表一致。该具体输出差异导致本轮未通过；后续根因仍需结合事件轨迹分析。
- 完整原始轨迹：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/`；任务定义与输入指令可见该目录 `original_instruction.txt`，模型参数/工具/返回可见 `llm_requests/`、`llm_call_log.jsonl`、`lite_agent_events.jsonl`。轨迹索引为 `trajectory_manifest.json`，正式评分为 `result.txt`，evaluator 产物索引为 `evaluator_artifacts/manifest.json`。
- 本轮处理：只记录测试结果；无本题新修复、API replacement 或复跑提交。相关未提交实现继续保留，不能以历史 PASS 将本次失败标记为完成。

### Order 107 — 本轮 FAIL

> Order 107 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-107)；本节保留其原始日期与实验条件。

- 最新事件轨迹直接入口：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/lite_agent_events.jsonl)；[单题最新失败日志](src/adapter_versions/v2_expanded/docs/order107-latest-failure-20261010.md)。
- Task ID：`881deb30-9549-4583-a841-8270c65f2a17`；应用：`multi_apps`。
- 原始结果：`status=failed`、`reward=0.0`，45 步，505.698 秒；`termination_reason=null`、`terminated_by_agent=false`。
- 已观察到的失败表现：evaluator 成功取回 `supported_rate.xlsx`，manifest 同时保留 result-00-supported_rate.xlsx 与 expected-00-supported_rate-gt.xlsx，但原始 evaluator 返回 0.0。本轮属于已获取产物但对照检查不通过；尚未逐单元格核对，不将其归因于文件读取 404。
- 完整原始轨迹：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/`；任务定义与输入指令可见该目录 `original_instruction.txt`，模型参数/工具/返回可见 `llm_requests/`、`llm_call_log.jsonl`、`lite_agent_events.jsonl`。轨迹索引为 `trajectory_manifest.json`，正式评分为 `result.txt`，evaluator 产物索引为 `evaluator_artifacts/manifest.json`。
- 本轮处理：只记录测试结果；无本题新修复、API replacement 或复跑提交。相关未提交实现继续保留，不能以历史 PASS 将本次失败标记为完成。

### Order 108 — 本轮 FAIL

> Order 108 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-108)；本节保留其原始日期与实验条件。

- 最新事件轨迹直接入口：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/lite_agent_events.jsonl)；[单题最新失败日志](src/adapter_versions/v2_expanded/docs/order108-latest-failure-20261010.md)。
- Task ID：`7e287123-70ca-47b9-8521-47db09b69b14`；应用：`multi_apps`。
- 原始结果：`status=failed`、`reward=0.0`，45 步，657.675 秒；`termination_reason=null`、`terminated_by_agent=false`。
- 已观察到的失败表现：evaluator 获取 `/home/user/Desktop/GRF-p5y.xlsx` 及转换后的 `/home/user/Desktop/GRF-p5y-Sheet1.csv` 时返回 404；XLSX 重试记录显示两组各 3 次尝试，大小均为 null，未获得有效 ZIP；manifest 的 result=[null]。输出缺失或保存路径问题尚未作根因确认。
- 完整原始轨迹：`src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/108-multi_apps-7e287123-70ca-47b9-8521-47db09b69b14/`；任务定义与输入指令可见该目录 `original_instruction.txt`，模型参数/工具/返回可见 `llm_requests/`、`llm_call_log.jsonl`、`lite_agent_events.jsonl`。轨迹索引为 `trajectory_manifest.json`，正式评分为 `result.txt`，evaluator 产物索引为 `evaluator_artifacts/manifest.json`。
- 本轮处理：只记录测试结果；无本题新修复、API replacement 或复跑提交。相关未提交实现继续保留，不能以历史 PASS 将本次失败标记为完成。

## Order 99 本轮修复（2026-10-10）

> Order 99 的本轮结果及最新轨迹见 [统一入口](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-99)；本节保留其原始日期与实验条件。

- 保留 fixed-28 最新原始 FAIL：45 步工具搜索、0 个 Adapter 调用、reward=0.0。完整人工诊断及单题修复见 [Order 99 记录](src/adapter_versions/v2_expanded/docs/order99-inventory-repair-20261010.md)。
- 本题增量：解释 inventory 前置条件并消费发现工具；初始清单全量枚举所选来源目录；对照参考内容跨对象保留；统一 checker retain 目录契约；移动拒绝后重新分类；retain 路径绑定当前对象。保留有界只读 `os.pdf.extract_text_batch`，不新增大粒度 API。
- `retry3` 正式 evaluator PASS（1.0，25 步，stalled_no_progress）；`retry4` PASS（1.0，45 步，manifest=max_steps）。两轮仍有执行收尾限制，记录中明确区分 evaluator 通过和完整处理证明。最终 `retry5` PASS（1.0，45 步，manifest=max_steps，1386.762 秒）；读取流水与三张发票，仅不匹配发票移动且验证通过，匹配文件保持原位。第三张匹配发票的 checker disposition/理由仍矛盾，未正常 agent_done，此限制已记录。
- 当前定向检查 70 passed，实际轨迹 contract replay 与 Ruff 通过；不扩建回归、不跑其他 Order。
- 本工作区存在原有共享改动，本题源码已应用；交付以独立增量补丁及 SHA-256 基线清单保存，避免把其他失败题共享代码混入本题提交。集成说明见本题记录。

- Order 99 本题增量交付提交：`f0afcaa`（补丁、基线 hash、配置、开发记录和 API 审计）；活动源码修复已应用在共享工作区，具体集成边界见本题记录。
- 最终证据写回（该运行于北京时间 2026-10-10 21:59:51 完成）：[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json)；[最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json)；[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)；[evaluator 产物索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/evaluator_artifacts/manifest.json)。
- 原始字段区分：manifest=`max_steps`；results.json termination_reason 未填写（null），terminated_by_agent=false。保留 checker 收尾限制，不记为正常 agent_done。
- 收尾证据提交 `37202a6`；原始 fixed-28 仍为 23/28，本题后续 PASS 单独登记。

## Order 102 清单步数预算修复与正式 PASS（2026-10-10）

最新正式单题结果：**PASS / reward=1.0**，47 条事件、1077.597 秒，results 与 manifest 均为 `agent_done`；北京时间 2026-10-10 22:45:40–23:03:38（episode 起止）。实验 `osworld-order102-qwen-20261010-inventory-step-budget-retry3`，task `869de13e-bef9-4b91-ba51-f6708c40b096`。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget-retry3/results.json)、[事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget-retry3/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/lite_agent_events.jsonl)、[轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget-retry3/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/trajectory_manifest.json)、[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget-retry3/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/result.txt)、[evaluator 产物索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order102-qwen-20261010-inventory-step-budget-retry3/raw/run-1/102-multi_apps-869de13e-bef9-4b91-ba51-f6708c40b096/evaluator_artifacts/manifest.json)；[单题修复日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order102-step-budget-fix-20261010.md)。

- 根因：保留批次 FAIL（45 步、1012.175 秒、reward=0.0）第 45 步成功读取 paper01.pdf；全局步数耗尽后没有下一次检验/移动请求，results termination_reason=null、manifest=max_steps。完整模型请求、审计、Adapter 返回及 evaluator 差异已逐项核对。
- 通用修复：新增可选 initial-step-budget，max-steps 始终为硬上限；仅首次完整、去重且排除目标目录的来源清单触发一次估算 `used_steps + pending_sources * (3+1) + 4`。不完整发现、无关任务、嵌套目录与 soft restart 不重置预算；结果/manifest 记录估算和是否截顶。实际耗尽明确记为 step_budget_exhausted 并发出 FAIL 边界。未新增 Adapter action、题目 ID 路由、答案或隐藏移动。
- 本题复跑过程：首轮/ retry1 为主动诊断中断（reward=null，各 1 条事件），均保留原始记录；发现 schema 的整数组 enum 生成嵌套数组，两个组织发现 schema 改为单一字符串 item enum，运行时仍仅接受 ["*"]。retry2 为正式 FAIL（0.0，48 步、1127.175 秒），最后 PDF 已完成读/检验/移动，剩余错误是完整 Writer 作业说明被误当学术论文；将既有完整 PDF 的主论文兼容性约束扩展到已证实完整的 Writer 读取，部分内容仍独立判定。retry3 正式通过。
- 通过轨迹：第 2 步观察 14 个来源，初始 45 → 有效 62，硬上限 75；最后 PDF 第 44 步读取、第 45 步独立检验、第 46 步移动且物理验证通过；第 47 步完成、第 48 步仅审计确认。14 个来源移动均验证通过；47 次审计完成、pending_model_audit=null、无 soft restart。manifest adapter_verifier_passed_calls=0 与事件嵌套 verification 的汇总差异保留，不改写原始字段。
- 条件：Qwen3.5-9B、同 endpoint、non_thinking、temperature=0，新 Docker guest，原始离线 evaluator 在 episode 后加载。相对批次硬上限 45 → 75（初始仍 45）、local 25 → 50、Agent 秒数 1200 → 1800、planner 输出 8192 → 512；checker 512、no-progress=8、soft-restart 上限 1。条件变化显式记账。仅复跑 Order 102。
- 最小检查：保留清单 replay、硬上限/不收缩/不重估、实际 runner 耗尽分支 mock、singleton schema 接受/拒绝与完整/部分 Writer 兼容性检查；6 个既有目录/清单测试、Ruff、编译及 diff 检查通过。未扩建通用回归或跑其他题。
- 提交边界：预算实现 `4894e6f`，首轮验收日志 `20fd8b5`。两个 singleton schema 与完整 Writer 分类辅助修复仍在原已修改/未跟踪的共享源码中，未整文件暂存。PASS 验证保存的组合 episode 源码，不能给孤立预算提交或当前全部共享改动背书；tool_surface.py 在 episode source seal 后另有并发修改，详见单题日志。

本次写回 API 审计、正式日志、单题日志、MD/JSON 最新入口和提交审计；原始事件与结果文件不修改。fixed-28 保持 23/28；各题最新已核对结果为 26/28 PASS，仅 107、108 仍 FAIL。

## Order 91 创建后显式写入与保存正式 PASS（2026-10-12）

Order 91 创建、写入、保存独立调用修复：**PASS / reward=1.0**，21 步、465.449 秒、agent_done；北京时间 2026-10-12 17:37:12 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-create-write-save-20261012/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-create-write-save-20261012.md)。10 月 12 日完整批次仍保留 25 PASS、2 FAIL、1 未评分，本次单题结果单独登记。

- 修复依据：最新批次23步/0.0，创建空表后九次inspect，写入/保存未在工具面交接；后续五列矩阵写六列且重复失败。保留历史结果与轨迹。
- 本题增量：根据已执行空白未保存工作簿状态展示range.write/workbook.save_as；写入尝试后range.read；模型决定数据、范围、路径。维度拒绝明确目标与矩阵实际行列数，原严格校验保留，不代填参数。保留create_new空表契约及10月10日搜索排序修复。
- 一次正式单题复跑通过：4创建，5范围失败，6模型纠正表头，7写25格，8–9错误路径保存失败，10–19重复搜索，20模型改正URL并显式保存，21完成；21审计、0soft restart。实际XLSX6×5与邮件查询逐格一致，原evaluator=1.0。
- 本次固定75步（命令未传initial-step-budget），区别于前次初始45；实际21步。Qwen3.5-9B/non_thinking，8192tokens，temperature0，25本地步、1800秒。实际命令、源码seal、SHA-256与保留限制详见单题日志。
- 定向contract replay、四文件Ruff及差异检查通过；只跑Order91。共享源码已应用，本题增量补丁与基线hash单独交付，避免整文件混入其他题未提交修改。本次PASS仅代表seal中组合源码。
- 审计、正式日志、单题日志和最新结果MD/JSON已同步；完整10月12日批次维持25PASS/2FAIL/1未评分。

Order 91 本题增量交付提交：`c6698fc`（独立源码补丁、基线哈希、配置、PASS 回执、日志与本题文档增量；四个活动源码文件已应用在共享工作区，未整文件提交）。

## Order 91 保存父目录发现与恢复正式 PASS（2026-10-13）

Order 91 保存路径发现与恢复修复：**PASS / reward=1.0**，10 步、359.121 秒、agent_done；北京时间 2026-10-13 10:40:53 完成。[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order91-save-path-20261013/raw/run-1/91-multi_apps-d9b7c649-c975-4f53-88f5-940b29c47247/lite_agent_events.jsonl) / [单题日志](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/order91-save-path-repair-20261013.md)。第二轮完整批次保持原记录，本次单题通过独立登记。

- 依据：第二轮35步/0.0，五封邮件已写好但保存猜错父目录；坏URL导致整个save_as被搜索排除，重启后重写又破坏数据。
- 修复：保存前父目录preflight与可操作反馈；写入后提供filesystem.find；保存失败保留成功数据并优先read/find/save，显式edit搜索仍允许；重复拦截按标准化参数，搜索与调用面保持一致。六文件增量，不合并create/write/save，不代填路径或数据。
- 正式单题命令、实际调用、Ruff/focused检查、源码seal及证据SHA-256见单题日志。仅跑Order91，当前初始45/硬上限75，与最新批次条件一致。
- 本题源码已应用在共享工作区；独立增量补丁/hash交付，避免整文件暂存其他题。正式日志、API审计、单题日志、最新结果入口同步；完整批次不改写。

Order 91 本题增量交付提交：`d90bcd0`（六文件源码增量补丁、基线hash、配置、PASS回执与日志；活动源码已应用于共享工作区，未整文件提交其他题修改）。

<!-- order91-save-path-writeback-receipt begin -->
本次写回核对：Order 91 于北京时间 **2026-10-13 10:40:53** 完成，**PASS / 1.0，10 步，359.121 秒，agent_done**。增量补丁与验收证据提交 `d90bcd0`，收尾记录 `8d6662b`；六文件活动源码已应用于共享工作区，提交边界为本题增量补丁。结果、事件、manifest、评分及产物 SHA-256 已逐一复核。正式复跑未触发错误父目录或 filesystem.find，相关分支以旧失败 replay 和定向检查验证；这项验证范围在单题日志保留。历史失败与完整批次记录不覆盖。
<!-- order91-save-path-writeback-receipt end -->
