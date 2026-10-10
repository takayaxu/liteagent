# 公开 API 粒度复查与拆分清单

日期：2026-09-20

## 结论

本次从十个 Adapter 的 `schema.ACTIONS` 重新枚举公开面；增加 Thunderbird identity
发现动作后，共 **217** 个 action。复查结果为：

- **P0 必拆/收窄 18 个**：一个调用可表达多个互相独立的设置、多个有顺序的变换、把两种操作模式合并在同一个入口，或带有未声明的破坏性副作用。
- **P1 复核 15 个**：粒度较大，但可能属于显式同构批处理或应用原生事务；先写保留理由和反例，再决定是否拆，不要机械拆分。
- **保留 184 个**：当前可解释为单一语义操作、只读查询、保存/导出、显式同构批处理或纯传输。

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
| liuxv | `thunderbird.preferences.update` | 任意 values map 加 remove list 可一次改动多个无关偏好 | 退役模型可见的底层入口；由窄语义 action 负责已支持的偏好设置 |
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
| `libreoffice_calc.range.text_transform` | 保留 action 名，将有序 `operations` 数组替换为必填单值 `transform`；组合清理必须按顺序连续调用，前一次 `destination_range` 作为后一次来源。运行时在写入前预检全部源单元格，旧 `operations` 返回 replacement 指引。为消除本题反复出现的空 Save As 参数，`workbook.save` 同步收窄为零参数原位保存，并新增要求显式 `.ods/.xlsx` 路径的 `workbook.save_as`。 | `b5db15c` | `test_calc_text_transform_contract.py`、text-transform header contract 及两个 save recovery contract focused pytest（14 passed）；10 个改动 Python 文件 Ruff 通过；Order 20 正式离线 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`。 |
| `thunderbird.mail.configure` | 保留 action 名；`signature_text`、`quote_original_on_reply`、`automatic_filters_on_subfolders`、`unified_inbox`、`dark_mode` 严格五选一。`identity` 只允许用于签名或回复引用。每次调用只写 `prefs.js` 或 `xulstore.json` 中的一处存储。新增只读 `identities.query`，在 identity-specific mutation 前返回 profile 中的精确 identity/account/email 映射。 | `0b6b25e`, `27a6552` | 初始收窄：邮件契约 focused pytest（75 passed）。identity 发现修复：`/var/lib/liteagent-shared/python-env/bin/python -m pytest tests/test_mail_selector_contract.py -q`（21 passed）；8 个改动 Python 文件执行 `ruff check` 通过。Order 153 单题正式复跑 `status=passed`、`reward=1.0`。 |
| `thunderbird.filters.configure` | 保留 action 名；`filters: [rule, ...]` 改为 `filter: rule`，一次只创建或更新一条。move 前由模型调用 `folders.ensure_local`；不存在则在修改规则文件前报错；forward 不创建文件夹。连续调用保留其他规则，同名规则更新，默认验证限定在单条规则块内。 | `4ac68e4` | `PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py`（25 passed）；`/opt/anaconda3/bin/ruff check` 和 `ruff format --check`（8 个改动 Python 文件通过）；Order 154 单题正式离线 evaluator `status=passed`、`reward=1.0`。 |
| `libreoffice_writer.document.add_page_numbers` | 保留 action 名和单一 `position` 参数；已有原生页码字段仅更新对齐、编号类型和 offset，没有页码字段时在独立页脚段落创建。已有页脚文本、其他字段和未使用页样式保持不变；默认 verification 回读每个目标页脚的原生页码字段和对齐。 | `3d9b616` | `test_writer_page_numbers.py` 与 `test_writer_footer_observation.py` focused pytest（12 passed）；4 个改动 Python 文件 Ruff 通过；Order 67 正式离线 evaluator `status=passed`、`reward=1.0`，final integrity `ok`。 |
| `libreoffice_impress.slide.format_text_roles` | 保留单页 action，移除 `overrides`；每次调用只应用一个共享格式规则。需要不同角色规则时由模型分别调用；运行时拒绝旧参数并说明如何拆分，原生逐对象回读仍负责验证。 | `3f6326e` | `test_impress_single_role_rule.py`、`test_impress_color_schema.py`、`test_strict_impress_completion.py` focused pytest（25 passed）；改动 Python 文件 Ruff 通过；Order 41 正式离线 evaluator `status=passed`、`reward=1.0`。 |
| `libreoffice_impress.slides.format_text_roles` | 保留 action 名，移除异构 `overrides`；显式 `slides` 上的每个角色只应用同一条共享格式规则，其他规则由模型另行调用。schema、运行时与 worker 均拒绝旧组合；所有目标页及角色先完成 preflight，再逐对象回读验证。 | `2254aab` | `test_impress_multislide_shared_rule.py`、`test_impress_color_schema.py`、`test_strict_impress_completion.py` focused pytest（25 passed）；5 个改动 Python 文件 Ruff 通过；Order 42 正式离线 evaluator `passed`、`reward=1.0`，final integrity `ok`。该题实际使用单元素 `slides`；双页 preflight/状态保留由 focused test 覆盖。 |
| `libreoffice_impress.slides.format_text_roles`（Order 59 imported PPTX route） | 保留 role API 作为 imported visual-title 的首选原子 mutation；Adapter 从 live inspection 解析可靠的视觉标题路径并回读验证。仅 role API 失败时按 observation-derived 路径逐个 fallback 到 `shape.format_text`；颜色比较规范化为 `#000000`，未完成全部 mutation、save 和 post-save inspect 前不暴露完成操作。 | `5301ab8` | Order 59 正式离线 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`；最终链路为 `presentation.inspect -> slides.format_text_roles -> presentation.save -> presentation.inspect -> propose_done`，结果见 `experiments/local-impress-multislide-title-59-retry12-20260921/workers/worker-00/results.json`。 |
| `libreoffice_impress.slide.set_role_text` | 保留 action 名，只接受 `slide`、`role`、`text` 并替换、回读文本；格式字段在 mutation 前返回可操作错误，要求模型随后独立调用 `slide.format_text_roles` 或 `shape.format_text`。LiteAgent 对同时要求文本和格式的角色更新分阶段要求两个独立、Adapter-confirmed mutation。 | `5601740` | `test_impress_role_text_split.py`、`test_impress_single_role_rule.py`、`test_impress_multislide_shared_rule.py`、`test_strict_impress_completion.py` focused pytest（20 passed）；涉及文件 Ruff 通过；Order 47 正式离线 evaluator `status=passed`、`reward=1.0`，final integrity `ok`。 |
| `thunderbird.preferences.update` | 退役公开 action、直连 schema、运行时 validation/dispatch 和默认 verification；内部 `update_preferences` helper 仅供 `mail.configure` 等窄语义 action 使用。旧 action 请求在 mutation 前返回 `UNSUPPORTED_ACTION`。 | `07fa09c` | `test_mail_selector_contract.py`（27 passed）；5 个改动 Python 文件 `ruff check` 通过，4 个专属 Thunderbird/测试文件 `ruff format --check` 通过。Order 159 拆分后正式离线 evaluator `status=passed`、`reward=1.0`。 |

### 单题闭环记录

- Order 20，task `a9f325aa-8c05-4e4f-8341-9e4358565f4f`：完整题目及原始 evaluator 定义在 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_calc/a9f325aa-8c05-4e4f-8341-9e4358565f4f.json`。题目要求把源列复制到目标列并依次压缩空白、转换为 title case；旧 `range.text_transform.operations` 在一次调用中隐藏两个可独立验证的有序决策。本题只将该数组收窄为一次一个 `transform`，未写入题目内容、固定坐标或答案。
- 拆分后 retry3 的完整轨迹在 `src/adapter_versions/v2_expanded/experiments/local-calc-text-transform-20-split-retry3-20260920/workers/worker-00/raw/run-1/20-libreoffice_calc-a9f325aa-8c05-4e4f-8341-9e4358565f4f/`：两次单一 transform、原位保存和目标区间读回均成功，但原始 golden 文件预取超时，正式 evaluator 未运行。retry5 与 retry8 再次完成两个 transform，却都在保存阶段生成 `workbook.save(url="")`；schema 正确拒绝后，模型服务重试遇到 `524`/timeout。通用修复因此把保存入口拆成零参数原位 `workbook.save` 与显式路径 `workbook.save_as`，避免用空字符串表达“没有 Save As 目标”。
- 最终有效轨迹在 `src/adapter_versions/v2_expanded/experiments/local-calc-text-transform-20-split-retry9-20260920/workers/worker-00/raw/run-1/20-libreoffice_calc-a9f325aa-8c05-4e4f-8341-9e4358565f4f/`，结果在同一 worker 的 `results.json`。模型依次检查工作簿、读取源列、调用 `collapse_whitespace` 写入目标列、对目标列原位调用 `title_case`、以 `{}` 原位保存，再检查工作簿和读回目标列；所有 Adapter verification 均通过。原始离线 evaluator 最终 `status=passed`、`reward=1.0`、`termination_reason=agent_done`。实际 focused 命令：`python -m pytest -q tests/test_calc_text_transform_contract.py tests/test_bounded_calc_formula_batch.py::test_text_transform_destination_description_preserves_headers tests/test_generic_completion_save_recovery.py::test_calc_save_recovery_keeps_zero_argument_in_place_save tests/test_generic_completion_save_recovery.py::test_calc_save_as_requires_target_without_expert_filter`；Ruff：`python -m ruff check calc_adapter/schema.py calc_adapter/tool_manifest.py calc_adapter/uno_worker.py integrations/lite_agent/adapter_results.py integrations/lite_agent/completion_policy.py integrations/lite_agent/semantic_requirements.py integrations/lite_agent/standard_location_semantics.py integrations/lite_agent/tool_catalog.py integrations/openapa_osworld/tool_catalog.py tests/test_calc_text_transform_contract.py tests/test_generic_completion_save_recovery.py`；单题命令：`python scripts/run_lite_agent_pilot.py --config experiments/configs/local-calc-text-transform-20-split-retry9-20260920.json --result-dir experiments/local-calc-text-transform-20-split-retry9-20260920/workers/worker-00 --orders 20 --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 300 --model qwen3.5-4b --base-url https://qwen.jinmaoapi.cc.cd/v1 --top-k 7 --reasoning-mode non_thinking --temperature 0 --max-output-tokens 512 --request-timeout 180 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1 --screen-width 1920 --screen-height 1080`（工作目录为 `src/adapter_versions/v2_expanded`）。
- Order 153，task `3f28fe4f-5d9d-4994-a456-efd78cfae1a3`：设置两行纯文本签名。首次有效运行位于 `experiments/local-mail-configure-single-20260920-retry1/workers/worker-00/results.json`，`reward=0.0`；模型将可见邮箱地址误作内部 identity，三次调用均在 mutation 前以 `params.identity contains unsupported characters` 被拒绝。
- 通用修复提交 `27a6552` 增加无参数只读 `identities.query`，返回 identity、email、display name、account、server 和 hostname 映射；签名与回复引用指令把该查询和 `mail.configure` 同时列为必需动作，配置契约要求使用查询返回的精确 identity。
- 同题 retry2 位于 `experiments/local-mail-configure-single-20260920-retry2/workers/worker-00/results.json`。模型第 1 步查询得到 `id1`，第 2 步调用 `mail.configure`，Adapter verification 通过；原始离线 evaluator 最终 `status=passed`、`reward=1.0`、`termination_reason=agent_done`。
- Order 153 后续粒度收窄：提交 `4da4729` 将五路 `mail.configure` 联合入口从模型可见 schema、公开 action catalog、运行时 dispatch 和默认 verification 中退役，替换为 `identity.set_plain_text_signature`、`identity.set_reply_quoting`、`filters.set_subfolder_application`、`inbox.set_unified` 和 `theme.set_dark_mode` 五个单语义 action；路由关键词同步提交于 `a09b33b`。签名仍作为一个原子事务同时写入文本和 `htmlSig=false`；identity 级 action 在停止 Thunderbird 或写入 profile 前从 live `prefs.js` 预检 identity，未知值返回 `IDENTITY_NOT_FOUND` 和可操作的 `identities.query` 指引。
- 当前源码定向验证：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_mail_selector_contract.py src/adapter_versions/v2_expanded/tests/test_recovery_surface.py::test_recipient_search_keeps_other_mail_operations_discoverable`（36 passed）；涉及 Python 文件 Ruff 通过。
- Order 153 正式复跑使用 `src/adapter_versions/v2_expanded/experiments/configs/formal-order153-five-actions-retry3-20260928.json`，结果位于 `src/adapter_versions/v2_expanded/experiments/formal-order153-five-actions-retry3-20260928/workers/worker-00/results.json`，原始轨迹位于同一 worker 的 `raw/run-1/153-thunderbird-3f28fe4f-5d9d-4994-a456-efd78cfae1a3/`。模型调用链为 `identities.query -> identity.set_plain_text_signature -> propose_done`；两个 Adapter verification 均通过，正式离线 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/formal-order153-five-actions-retry3-20260928.json --orders 153 --result-dir src/adapter_versions/v2_expanded/experiments/formal-order153-five-actions-retry3-20260928/workers/worker-00 --model Qwen3.5-9B-Q4_K_M --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-steps 30 --max-local-steps 15 --max-soft-restarts 1 --max-no-progress-steps 8 --max-agent-seconds 300 --top-k 7 --reasoning-mode non_thinking --temperature 0 --max-output-tokens 512 --request-timeout 180 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1 --screen-width 1920 --screen-height 1080`。
- Order 154，task `5203d847-2572-4150-912a-03f062254390`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/5203d847-2572-4150-912a-03f062254390.json`。历史 v305/v306 的原始轨迹不在本工作区；本地拆分前基准的完整原始轨迹是 `src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-baseline-retry3-20260920/workers/worker-00/raw/run-1/154-thunderbird-5203d847-2572-4150-912a-03f062254390/`，结果为同一 worker 的 `results.json`（`passed`, `1.0`）。模型第 1 步显式建本地文件夹，第 2 步以旧 `filters` 数组配置一条规则；Adapter 同一步又隐式建该文件夹。基准通过但隐藏副作用和 50 条异构规则容量仍违反单一语义契约；旧 writer 覆盖全部规则文件，还会使拆分后的连续调用丢失早先规则。
- 初次本地基准预取原始 Hugging Face URL 超时，记录在 `experiments/local-filter-configure-154-baseline-20260920/workers/worker-00/results.json`（`environment_failure`，模型未运行）；从同一数据集路径的可用镜像预取到 OSWorld 标准缓存并与已有原 URL 缓存核对 SHA-256 后，retry3 的环境与原始 evaluator 均正常。两次中间配置因并发源码 seal 变化在模型启动前被拒绝，无评测分数。
- 本题通用修复提交 `4ac68e4`；拆分后轨迹在 `src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-split-20260920/workers/worker-00/raw/run-1/154-thunderbird-5203d847-2572-4150-912a-03f062254390/`，结果在同一 worker 的 `results.json`。模型第 1 步显式 `folders.ensure_local`，第 2 步仅传 `filters.configure(filter={...})`，Adapter 的单规则 verification 通过且无隐式建目录；正式离线 evaluator 判定 `passed`, `reward=1.0`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-filter-configure-154-split-20260920.json --orders 154 --result-dir src/adapter_versions/v2_expanded/experiments/local-filter-configure-154-split-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。
- Order 159，task `10a730d5-d414-4b40-b479-684bed1ae522`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/thunderbird/10a730d5-d414-4b40-b479-684bed1ae522.json`，要求启用完整深色模式。首次基准因原始 Hugging Face URL 超时在模型启动前结束；retry1/retry2 因并发源码 seal 变化在模型启动前被门禁拒绝。复用同一原始 URL 的既有 Thunderbird profile 缓存并核对 SHA-256 `8a714a4102d6f3aa604c0fd2bb96e63ba51594485977ed5c8dd19af846ae07e8` 后，有效基线 retry3 位于 `src/adapter_versions/v2_expanded/experiments/local-preferences-update-159-baseline-retry3-20260920/workers/worker-00/`，正式 evaluator 为 `passed`, `reward=1.0`。
- 有效基线的 top-k 和完整调用轨迹均未包含 `preferences.update`；模型第 1 步调用 `mail.configure(dark_mode=true)`，Adapter verification 读回 `extensions.activeThemeID` 成功，第 2 步完成。该题已有窄语义 replacement，任意 key 底层入口既非完成本题所需，又允许绕过语义约束批量修改无关偏好，因此提交 `07fa09c` 将其从公开 schema、validation、dispatch 和默认 verification 中退役，并保留内部 profile helper。
- 拆分后完整轨迹在 `src/adapter_versions/v2_expanded/experiments/local-preferences-update-159-retired-20260920/workers/worker-00/raw/run-1/159-thunderbird-10a730d5-d414-4b40-b479-684bed1ae522/`，结果在同一 worker 的 `results.json`：模型仍调用单一语义 `mail.configure(dark_mode=true)`，Adapter verification 通过，正式离线 evaluator 判定 `passed`, `reward=1.0`, `termination_reason=agent_done`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-preferences-update-159-retired-20260920.json --orders 159 --result-dir src/adapter_versions/v2_expanded/experiments/local-preferences-update-159-retired-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。
- Order 67，task `0e47de2a-32e0-456c-a366-8c607ef7a9d2`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_writer/0e47de2a-32e0-456c-a366-8c607ef7a9d2.json`，要求为每页添加左下角页码。历史 frozen config 记录旧模型会反复选择正确 action，但旧 opaque 参数调用在 mutation 前被拒绝；对应原始轨迹不在本工作区。当前源码的额外失败风险是先选中并清空整个 `FooterText`，会删除与本 action 无关的页脚内容。提交 `3d9b616` 改为只创建或更新原生页码字段，并增加页脚文本保留、已有字段原位更新、非法破坏性参数拒绝和 read-back 失败测试。
- 首次本地复跑在模型启动前因原始 Hugging Face URL 超时成为 `environment_failure`；从同一数据集路径的可用镜像预取到 OSWorld 标准原 URL 缓存，输入 DOCX SHA-256 为 `14bf1830fe564811f847eb688fc36ae5c64317481f7aaad7473965d035cd2b28`，并通过 ZIP 完整性检查。中间重试已得到 evaluator `1.0`，但因共享工作区并行源码变化未通过 final seal，未作为最终闭环。
- 最终有效轨迹在 `src/adapter_versions/v2_expanded/experiments/local-writer-page-numbers-67-split-retry3-20260920/workers/worker-00/raw/run-1/67-libreoffice_writer-0e47de2a-32e0-456c-a366-8c607ef7a9d2/`，结果在同一 worker 的 `results.json`。模型第 1 步调用 `document.add_page_numbers(position="bottom_left")`，Adapter 原生页码字段和保存 verification 均通过；第 2 步 inspect 再读回左对齐字段。正式离线 evaluator `passed`, `reward=1.0`, `termination_reason=agent_done`，final integrity `ok`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-writer-page-numbers-67-split-retry3-20260920.json --orders 67 --result-dir src/adapter_versions/v2_expanded/experiments/local-writer-page-numbers-67-split-retry3-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。
- 2026-09-22 当前源码复验不改变 API 分类：`document.add_page_numbers` 仍是已完成的窄 replacement，未新增同义入口。qwen1 retry4 使用原始 URL 对应的 UUID 缓存输入，聚焦测试 `12 passed`、Ruff 通过；模型执行 `document.add_page_numbers(position="bottom_left") -> document.inspect -> propose_done`，正式 evaluator 再次得到 `status=passed`、`reward=1.0`、`termination_reason=agent_done`。完整当前命令记录在 `API_SPLIT_TASK.md`，结果位于 `experiments/local-writer-page-numbers-67-split-retry4-20260922/workers/worker-00/results.json`。
- Order 41，task `986fc832-6af2-417c-8845-9272b3a1528b`：完整指令、配置和 evaluator 定义在 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_impress/986fc832-6af2-417c-8845-9272b3a1528b.json`。旧历史原始轨迹不在本工作区；本地基准在模型启动前因并发源码 seal 变化被拒绝，因此没有可用于分析的旧模型调用。源码显示旧单页契约允许在共享规则后追加至多 8 条异构 `overrides`，而本题正需对正文单独加下划线、对全页统一改色；一次模型调用能够隐藏两条独立决策。只收窄本题实际使用的 `slide.format_text_roles`，未引入题目专属参数或操作序列。
- 首次拆分后运行的完整原始轨迹在 `src/adapter_versions/v2_expanded/experiments/local-impress-role-41-split-20260920/workers/worker-00/raw/run-1/41-libreoffice_impress-986fc832-6af2-417c-8845-9272b3a1528b/`，预取输入 PPTX 时原始 Hugging Face 地址超时，`environment_failure` 且无模型步骤或 evaluator 分数；两次重试在模型启动前因并发源码 seal 变化被拒绝。对同一数据集路径的可用镜像预取两份原始 PPTX 至 OSWorld 标准 URL 缓存，并通过 ZIP 完整性检查；输入 SHA-256 为 `5ea88b468b11c3d4171b76eb614adf780b8aaf40b9dd0625930225e2fd399ccd`，evaluator 文件 SHA-256 为 `8b8f42587cf9c6a94b8f0f4cbdae9c97dc8c57c00b3f3f87decbf966d394ed12`。
- 有效单题轨迹在 `src/adapter_versions/v2_expanded/experiments/local-impress-role-41-split-retry3-20260920/workers/worker-00/raw/run-1/41-libreoffice_impress-986fc832-6af2-417c-8845-9272b3a1528b/`，结果在同一 worker 的 `results.json`：模型看到的 `slide.format_text_roles` schema 无 `overrides`；第 2 步对正文加下划线、第 3 步对全页着色，均为单规则调用且 Adapter verification 通过。模型之后短暂给表格加下划线并显式撤销；保存后检查确认标题和表格未加下划线、正文已加下划线、全页颜色正确。正式离线 evaluator `passed`, `reward=1.0`, `termination_reason=agent_done`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-impress-role-41-split-retry1-20260920.json --orders 41 --result-dir src/adapter_versions/v2_expanded/experiments/local-impress-role-41-split-retry3-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。
- Order 47，task `08aced46-45a2-48d7-993b-ed3fb5b32302`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_impress/08aced46-45a2-48d7-993b-ed3fb5b32302.json`，要求把第 2 页标题替换为 `Note` 并右对齐。历史 v252 标记为失败、v279 为该题引入组合式 `slide.set_role_text`，但对应原始轨迹不在本工作区。旧契约在一次调用中同时替换文本和应用最多八种格式属性，隐藏了两个独立决策；提交 `5601740` 将其收窄为纯文本替换，并让模型通过独立 `slide.format_text_roles` mutation 完成格式要求。
- 拆分前基准在 `src/adapter_versions/v2_expanded/experiments/local-set-role-text-47-baseline-20260920/workers/worker-00/`：原始 Hugging Face 输入地址超时，模型未启动，结果为 `environment_failure` 且无 evaluator 分数；其后并行源码变化导致 frozen source seal 不再匹配。随后从同一数据集路径的可用镜像预取输入和 evaluator golden 到 OSWorld 标准缓存，并保持原任务定义和原始离线 evaluator 不变。
- 拆分后完整轨迹在 `src/adapter_versions/v2_expanded/experiments/local-set-role-text-47-split-20260920/workers/worker-00/raw/run-1/47-libreoffice_impress-08aced46-45a2-48d7-993b-ed3fb5b32302/`，结果在同一 worker 的 `results.json`。模型依次调用 `presentation.inspect(slides=[1])`、`slide.set_role_text(slide=1, role="title", text="Note")`、`slide.format_text_roles(slide=1, roles=["title"], alignment="right")`，两个 mutation 的 Adapter verification 均通过。后续 inspect 错误报告左对齐，模型重复检查并以 `stalled_no_progress` 终止；保存后的 PPTX 经正式 evaluator 检查标题为 `Note`、段落为右对齐，最终仍为 `status=passed`, `reward=1.0`，final integrity `ok`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-set-role-text-47-split-20260920.json --orders 47 --result-dir src/adapter_versions/v2_expanded/experiments/local-set-role-text-47-split-20260920/workers/worker-00 --base-url https://qwen.jinmaoapi.cc.cd/v1 --max-local-steps 15`。
- Order 52，task `af2d657a-e6b3-4c6a-9f67-9e3ed015974c`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_impress/af2d657a-e6b3-4c6a-9f67-9e3ed015974c.json`，要求在第 1 页写入标题 `Happy Family` 并设为 `Microsoft JhengHei`。历史元数据中 v252 为 `failed`、v279 为 `passed`，但历史原始轨迹不在本工作区。该题真正涉及的旧大粒度 API 仍是 `slide.set_role_text`：文本替换和字体格式是两个可独立失败、独立验证的 mutation，应分别调用纯文本 `slide.set_role_text` 与单规则 `slide.format_text_roles`。此通用拆分已由 Order 47 的提交 `5601740` 完成，因此本题不需要新增或修改 Adapter API。
- 初次运行 `local-set-role-text-52-split-20260920` 在模型启动前因原始 Hugging Face 输入文件预取超时成为 `environment_failure`。从同一数据集路径的可用镜像预取输入和 golden 到 OSWorld 标准缓存后，输入 PPTX SHA-256 为 `af0ba4350a65bb9c0529f3f7489d8de7153325b46ecfcff0c7844290d7b8d9bc`，golden SHA-256 为 `287d5fba662f5eb531b7fd10f97d1c892f10cb4b7035c7161d2ca59bacdc3822`，两者均通过 ZIP 完整性检查。retry1 已正确完成两个 mutation 和保存，但 evaluator 查找 plain cache filename `9_1_Gold.pptx` 时再次访问原站超时，结果为 `evaluation_failure`、无 reward；补齐同一 golden 的标准缓存文件名后再执行 retry2。
- 最终有效轨迹在 `src/adapter_versions/v2_expanded/experiments/local-set-role-text-52-split-retry2-20260920/workers/worker-00/raw/run-1/52-libreoffice_impress-af2d657a-e6b3-4c6a-9f67-9e3ed015974c/`，结果在同一 worker 的 `results.json`。模型依次调用 `presentation.inspect(slides=[0])`、`slide.set_role_text(slide=0, role="title", text="Happy Family")`、`slide.format_text_roles(slide=0, roles=["title"], font_name="Microsoft JhengHei")`、再次 inspect、`presentation.save(url="file:///home/user/Desktop/9_1.pptx")` 并完成；两个 mutation 均返回 `status=ok` 且 Adapter verification 通过，回读得到 `CharFontName="Microsoft JhengHei"`。原始离线 evaluator 比对标题成功，最终 `status=passed`、`reward=1.0`、`termination_reason=agent_done`，最终源码与配置完整性 `ok`；evaluator result artifact SHA-256 为 `999b30482b06f45a799ae602ad21fd7de8e74e6c936a35580139b8f3abb6d239`。
- Order 53，task `57667013-ea97-417c-9dce-2713091e6e2a`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_impress/57667013-ea97-417c-9dce-2713091e6e2a.json`，要求把第 5 页所有文本框字体改为精确黄色。历史原始轨迹不在本工作区；v222-v224 配置说明先后修复过全页文本颜色路由、保存回读推进和完成声明恢复，v252 元数据为 `passed`。本题真正涉及的 API 只有 `slide.format_text_roles(slide, roles, color)`；一个页面内全部文本框接受同一共享规则，不包含逐成员独立决策，因此不需要继续拆 Adapter API。首次本地运行 `local-impress-textbox-color-53-current-20260920` 中 mutation schema 已正确暴露，但模型 17 步均重复 `presentation.inspect(slides=[4])`，未执行 mutation，正式 evaluator 为 `failed`、`reward=0.0`。
- 通用修复为全页文本框颜色意图接入现有阶段路由：首次结构检查后，在匹配 mutation 成功前只暴露 `slide.format_text_roles`，不推导或注入任何调用参数。有效轨迹在 `src/adapter_versions/v2_expanded/experiments/local-impress-textbox-color-53-current-retry1-20260920/workers/worker-00/raw/run-1/53-libreoffice_impress-57667013-ea97-417c-9dce-2713091e6e2a/`，结果在同一 worker 的 `results.json`。模型第 1 步检查第 5 页，第 2 步自主调用 `slide.format_text_roles(slide=4, roles=["all"], color="yellow")`，Adapter 对 7 个递归文本形状逐一写入并回读 `CharColor=16776960`；后续重复 inspect 均读到黄色。虽然 Agent 以 `stalled_no_progress` 结束，OSWorld 原始评测收尾保存的结果与 `1_2_Gold_all_fonts.pptx` 匹配，正式 evaluator 最终 `status=passed`、`reward=1.0`、`path_class=generic_api_only`，完整性重验 `ok`；结果 artifact SHA-256 为 `fa218d3b55194aec4ed8d55c21011aec295f607fce05b2a566269c0d69ce8e2a`。聚焦测试：`PYTHONPATH=. pytest -q tests/test_impress_textbox_color_progression.py tests/test_impress_role_text_split.py`（6 passed）；Ruff：`ruff check integrations/lite_agent/impress_textboxes.py integrations/lite_agent/action_selection.py tests/test_impress_textbox_color_progression.py`。
- Order 59，task `4ed5abd0-8b5d-47bd-839f-cacfa15ca37a`：题目要求将第 2、3、5 页标题设为黑色并加下划线。历史失败的根因是 imported PPTX 没有原生 `TitleTextShape`，模型反复猜测错误标题路径；本题需要依赖 Adapter 已确认的 visual-title role resolution，而不是暴露未经观察的 selector。提交 `5301ab8` 保留 `slides.format_text_roles` 作为首选原子 mutation，role 失败才逐个使用 observation-derived `shape.format_text` fallback；颜色按规范化 `#000000` 比较，全部标题 mutation、save 和 post-save inspect 成功前不暴露完成操作。
- Order 59 最终轨迹在 `src/adapter_versions/v2_expanded/experiments/local-impress-multislide-title-59-retry12-20260921/workers/worker-00/`，结果为 `status=passed`、`reward=1.0`、`termination_reason=agent_done`。实际命令和完整 replacement 记录在上方 P0 表及 `src/adapter_versions/v2_expanded/docs/project-progress.md`；源码编译检查 `python -m compileall -q src/adapter_versions/v2_expanded/integrations/lite_agent` 通过。
- Order 52、53、54 的 API 状态回填：三题均没有新增公开 Adapter action。Order 52 复用 `5601740` 的 `slide.set_role_text` 文本/格式拆分；Order 53 保留单一共享规则 `slide.format_text_roles`，实现提交为 `9af6716`；Order 54 保留已有 `slide.remove_personal_information` 与独立标题格式化 mutation，按 observation-derived next-step 计划串行执行，最终共享实现提交为 `5301ab8`。三题的通过结果、结果路径和实际命令已补入 [project-progress.md](../src/adapter_versions/v2_expanded/docs/project-progress.md) 的 backfill 小节。
- Order 42，task `a434992a-89df-4577-925c-0c58b747f0f4`：完整题目定义为 `src/third_party/OSWorld/evaluation_examples/examples/libreoffice_impress/a434992a-89df-4577-925c-0c58b747f0f4.json`；历史记录 `src/adapter_versions/v2_expanded/docs/project-progress.md` 确认旧轨迹实际调用 `slides.format_text_roles`，但旧原始轨迹在另一账号目录、当前用户无读取权限。本题需要正文统一字号和颜色，旧 action 同时接受额外异构 `overrides`；提交 `2254aab` 仅收窄该多页 action，没有写入题目内容或特例。
- 本地 `local-impress-p0-6-order42-20260920` 在模型前因并发源码 seal 变化拒绝；`retry1` 的输入预取遇到原站超时且最终 seal 变化；`retry2` 的 Agent 执行 9 步、模型选中单规则多页 action，但 evaluator 参考文件预取原站超时且最终 seal 变化，均不能当作评分。用镜像取得同一数据集路径的原始输入与参考 PPTX，放到 OSWorld 标准 task cache，`unzip -t` 均通过；SHA-256 分别为 `63093912c1dc5da7cf0bc6b7fca084f91796092ab5a9f2e83de82451be87ed55`、`60573eb1490cf7c9952b6adf61b96b338ddbd18977df6a352cf91edbdf8f7616`。原始任务配置及 evaluator 未修改，参考文件未进入 Agent 上下文。
- 有效轨迹为 `src/adapter_versions/v2_expanded/experiments/local-impress-p0-6-order42-retry3-20260920/workers/worker-01/raw/run-1/42-libreoffice_impress-a434992a-89df-4577-925c-0c58b747f0f4/`，汇总为 `workers/worker-01/results.json` 及 supervisor 顶层 `results.json`。模型第 2 步调用 `slides.format_text_roles(slides=[0], roles=["content"], font_size=12, color="orange")`，返回单条规则和逐对象属性回读，Adapter verification `passed=true`；之后独立设置背景、保存并检查。正式离线 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`、`path_class=generic_api_only`，最终源码与配置完整性 `ok`。实际命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/supervise_lite_agent_parallel.py --config src/adapter_versions/v2_expanded/experiments/configs/local-impress-p0-6-order42-retry3-20260920.json --result-dir src/adapter_versions/v2_expanded/experiments/local-impress-p0-6-order42-retry3-20260920 --workers 1 --base-urls https://qwen.jinmaoapi.cc.cd/v1 --model qwen3.5-4b --python /var/lib/liteagent-shared/python-env/bin/python --max-steps 50 --max-local-steps 25 --max-agent-seconds 600 --max-output-tokens 512 --reasoning-mode non_thinking --request-timeout 180`。focused 命令：`PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_impress_multislide_shared_rule.py src/adapter_versions/v2_expanded/tests/test_impress_color_schema.py src/adapter_versions/v2_expanded/tests/test_strict_impress_completion.py`；Ruff：`ruff check src/adapter_versions/v2_expanded/impress_adapter/schema.py src/adapter_versions/v2_expanded/impress_adapter/tool_manifest.py src/adapter_versions/v2_expanded/impress_adapter/uno_worker.py src/adapter_versions/v2_expanded/integrations/openapa_osworld/tool_catalog.py src/adapter_versions/v2_expanded/tests/test_impress_multislide_shared_rule.py`。

## P1 复核清单

| 负责人 | API | 需要确认的边界 |
| --- | --- | --- |
| liuxv | `libreoffice_calc.workbook.create_new` | 同时创建工作簿、写 headers/rows；确认这是一个原生新建事务，而不是隐藏的多步文档生成 |
| liuxv | `libreoffice_writer.document.extract_images` | 批量导出文档图片；确认所有成员使用完全相同规则且没有隐式选择 |
| liuxv | `libreoffice_writer.document.remove_highlighting` | 可覆盖大范围；确认只执行一个明确的高亮移除规则 |
| liuxv | `thunderbird.messages.export_eml` | 可导出整个文件夹；确认文件夹和输出目录显式且没有挑选消息的隐藏逻辑 |
| pengzhe | `os.user.ensure_account` | 可能同时创建账号并修改账号属性；确认一个调用只对应一个账户声明式事务 |
| pengzhe | `os.archive.compress_file` | 压缩验证后还可删除源文件；确认它是明确、可恢复的原生事务，否则拆成 compress 与 delete |
| pengzhe | `os.filesystem.copy_to_directories` | 一个 source 复制到最多 64 个 destination 且隐式创建目录；确认是同构显式复制且没有目录发现 |
| pengzhe | `os.filesystem.rename` | overwrite 可递归删除现有目标目录并隐式创建 parent；确认这些是明确 rename 契约而非隐藏 mutation |
| pengzhe | `os.desktop.mime_associations.set` | 可一次给最多 20 个 MIME 类型设置默认应用；确认它们是同一个显式同构规则 |
| pengzhe | `os.image.extract_text_batch` | 批量只读 OCR；确认边界有界且不解释内容或决定后续动作 |
| liuxv | `os.pdf.extract_text_batch` | 批量只读 PDF 文本提取；确认边界有界且不解释内容或决定后续动作。Orders 95、96、99、102、107、108 整组归 liuxv |
| pengzhe | `vs_code.workspace.open` | `close_existing` 会关闭全部 VS Code 窗口，失败路径还可能终止进程；确认生命周期副作用被明确声明 |
| pengzhe | `vs_code.workspace.set_folders` | 未限长 folders 数组整体替换 workspace；确认是应用原生显式同构事务 |
| pengzhe | `vs_code.workspace.add_folders` | 未限长 folders 数组批量追加；确认是应用原生显式同构事务 |
| pengzhe | `vlc.playback.open` | 打开媒体会终止/重启当前 VLC，并另外切换 loop | 确认生命周期是公开契约且 loop 不应成为独立 mutation |

`slides.format_text_roles` P1 复核：保留显式 `slides` 批处理。模型选择所有目标索引和唯一共享 `roles`/格式规则，worker 先为每页解析形状并确认角色都存在，之后才对任何目标 mutation；后续格式化逐对象回读。`test_impress_multislide_shared_rule.py` 的两页用例确认后页缺失角色时前页未修改，且成功时每页仅有同一条规则。为了兼容模型已有的单元素 `slides` 调用，仍允许单元素列表；它不代表真实多页 evaluator 已验证，实际跨页事务目前只有 focused test 证据。

`document.set_font` P1 复核：保留并转入“保留”状态。模型可见契约只有必填的单值 `font_name`，不接受字体大小、范围选择或多规则列表；worker 对正文和表格的所有文本对象应用同一字体族，同时写入西文、亚洲和复杂文本三个原生字体属性并返回原生 `fonts` 回读。因此它是一个明确的全文同构格式规则，不隐藏独立决策或异构 mutation。实现来源提交为 `b800fd9c8861528bc5dc0c204c88a84163835769`，当前复核不新增代码。Order 68 focused pytest **22 passed**、Ruff 通过；正式单题 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`，实际调用为 `document.set_font(font_name="Times New Roman")`，随后 `document.inspect` 确认三个字体槽均包含目标字体。

`document.transform_case` P1 复核：保留并转入“保留”状态。公开契约严格且仅接受必填单值 `mode`，枚举为 `lower` 或 `title`；每次调用只选择一种互斥的全文同构大小写规则，不接受操作数组、局部范围或额外格式副作用。worker 对正文和表格段落统一变换，并在自动保存前逐段原生回读；任一写入未持久化即返回 `VERIFICATION_FAILED`。实现提交为 `3d98fd27363b13d79754f6af09fd9367e875ae3b`。Order 81 focused pytest **46 passed**、Ruff 通过；正式单题 evaluator `status=passed`、`reward=1.0`，实际 mutation 为 `document.transform_case(mode="lower")`，返回 `paragraphs_changed=14`、`paragraphs_verified=18`。Order 83 又以同一 API 的 `mode="title"` 通过，返回 `paragraphs_changed=3`、`paragraphs_verified=4`；其 title-case focused check **6 passed**。两题均可能在模型重复观察后以 `stalled_no_progress` 收尾，但原始 `compare_docx_files` 均返回 `1.0`。

`thunderbird.messages.query` Order 91 复核：保留。它是有界只读查询，`select_from` 负责从匹配结果的最新/最早一端选取窗口，`order` 只负责返回顺序；两者不是可合并的异构 mutation。新增的通用 latest-selector 语义拒绝保护只拦截 instruction 明确要求 latest/most-recent 而模型传 `select_from="earliest"` 的矛盾调用，不重写参数或注入任务数据。`libreoffice_calc.workbook.create_new` 同题保留，headers/rows 是显式模型数据且创建后自动保存，不新增宏 API。Order 91 正式 evaluator `status=passed`、`reward=1.0`；focused selector check **27 passed**。源码提交为 `d077b18f02805becaa8f5ff21bb7d1c27b5e8c2c`（`fix(order91): guard latest mail selection semantics`）。

`thunderbird.messages.export_eml` Order 152 复核：保留。公开契约只接受可见的 `folder_name` 和绝对或 `~/` 开头的 `output_dir`，没有消息 selector、排序、转发或其它设置字段；每封消息使用同一导出规则写成独立 `.eml`，并在写入前拒绝已有 `.eml` 冲突。Adapter 内部保留 `source`/`destination` 兼容入口以服务旧调用方，但该低级路径未进入模型 schema，混用两套契约会 fail-closed。提交 `be6c7af` 在 action dispatch 入口补上完整参数校验，避免 worker 绕过这条边界。`test_mail_selector_contract.py` **30 passed**、Ruff 通过。正式 OSWorld 单题使用 `src/adapter_versions/v2_expanded/experiments/configs/formal-order152-20260927.json`，结果目录为 `src/adapter_versions/v2_expanded/experiments/formal-order152-20260927-rerun2/`；原始 evaluator `status=passed`、`reward=1.0`、`termination_reason=agent_done`，模型实际调用 `messages.export_eml(folder_name="Inbox", output_dir="~/emails.bak")`，Adapter 导出并验证 6 个 `.eml`，轨迹保存在该结果目录下的 `workers/worker-00/raw/run-1/152-thunderbird-9bc3cc16-074a-45ac-9bdc-b2a362e1daf3/`。

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
| Calc | 31 | `range.text_transform` | `workbook.create_new` | `cells.set_formulas`, `chart.create`, `page.fit_to_pages`, `pivot.create`, `range.copy`, `range.fill_down`, `range.format`, `range.merge`, `range.read`, `range.set_decimal_separator`, `range.set_scaled_display`, `range.set_validation`, `range.write`, `rows.set_hidden`, `sheet.copy`, `sheet.create`, `sheet.move`, `sheet.rename`, `table.reorder_columns`, `table.sort`, `view.freeze_panes`, `view.freeze_range`, `view.set_zoom`, `workbook.convert_file`, `workbook.export`, `workbook.inspect`, `workbook.read_file`, `workbook.save`, `workbook.save_as` |
| Impress | 31 | `slide.format_text_roles`, `slide.set_role_text`, `slides.format_text_roles` | - | `audio.insert`, `master.set_page_number`, `presentation.export`, `presentation.inspect`, `presentation.save`, `presentation.set_page_size`, `settings.set`, `shape.create_text`, `shape.delete`, `shape.export_image`, `shape.fit_to_slide`, `shape.format_text`, `shape.insert_image`, `shape.set_fill`, `shape.set_geometry`, `shape.write_text`, `shape.write_text_native`, `slide.create`, `slide.delete`, `slide.duplicate`, `slide.move`, `slide.set_background`, `slide.set_notes`, `slide.set_transition`, `table.create`, `table.format_text`, `table.replace_row`, `table.write` |
| Chrome | 24 | `settings.set` | - | `bookmark.add_current`, `bookmark.create_folder`, `browser.ensure_running`, `browser.inspect`, `browser.restart`, `extension.load_unpacked`, `page.click`, `page.fill`, `page.goto`, `page.press`, `page.print_pdf`, `page.read`, `page.select`, `page.snapshot`, `page.wait_for`, `privacy.delete_cookies`, `privacy.delete_history`, `shortcut.create_current`, `tab.activate`, `tab.close`, `tab.list`, `tab.open`, `tab.restore_last_closed` |
| GIMP | 12 | `image.adjust` | - | `config.set`, `image.apply_alpha_mask`, `image.convert_indexed`, `image.crop`, `image.export`, `image.flip`, `image.inspect`, `layer.add`, `layer.fill`, `layer.scale`, `layer.translate` |
| OS | 41 | `archive.create_extract`, `desktop.set_accessibility_scale`, `desktop.set_dim_inactive` | `archive.compress_file`, `desktop.mime_associations.set`, `filesystem.copy_to_directories`, `filesystem.rename`, `image.extract_text_batch`, `pdf.extract_text_batch`, `user.ensure_account` | `audio.set_volume`, `clipboard.get`, `clipboard.set`, `command.run`, `desktop.applications.inspect`, `desktop.favorites.list`, `desktop.open_path`, `desktop.remove_favorite`, `desktop.set_setting`, `desktop.set_wallpaper`, `document.convert`, `filesystem.copy`, `filesystem.create_directory`, `filesystem.find`, `filesystem.set_permissions`, `notifications.configure`, `package.install_snap`, `pdf.form.fill`, `pdf.form.inspect`, `pdf.outline.inspect`, `pdf.pages.extract`, `pdf.tables.inspect`, `system.set_timezone`, `terminal.default_profile.inspect`, `terminal.default_profile.set_setting`, `terminal.launch`, `terminal.show_output`, `text.append_each_line`, `trash.list`, `trash.restore`, `window.capture` |
| Writer | 28 | `document.add_page_numbers` | `document.extract_images`, `document.remove_highlighting` | `bookmark.create`, `cross_reference.insert`, `document.append_paragraphs`, `document.export_pdf`, `document.insert_page_break`, `document.inspect`, `document.read_file`, `document.save`, `document.set_font`, `document.transform_case`, `image.insert_at_cursor`, `paragraph.apply_numbering`, `paragraph.clear_text`, `paragraph.replace_text`, `paragraph.set_format`, `paragraph.split`, `settings.set_default_font`, `table.convert_text`, `table.insert_after_text`, `table.insert_at_cursor`, `table.read`, `table.set_cell_text_color`, `text.find`, `text.find_replace`, `text.set_format` |
| VS Code | 27 | `debugging.configure`, `editor.configure`, `files.configure`, `settings.update` | `workspace.add_folders`, `workspace.open`, `workspace.set_folders` | `debug.breakpoint.set`, `debug.continue`, `debug.session.wait`, `debug.start`, `debug.stop`, `debug.variables.read`, `diagnostics.configure`, `editor.open_file`, `explorer.set_exclusion`, `extension.install`, `file.create`, `file.indent_lines`, `file.read_text`, `file.replace_literal`, `keybindings.ensure`, `ui.expand_section`, `ui.open_view`, `workspace.find_files`, `workspace.inspect`, `workspace.write` |
| VLC | 9 | `config.update`, `preferences.configure` | `playback.open` | `media.extract_audio`, `media.extract_frame`, `media.extract_subtitles`, `media.transcode_clip`, `playback.status`, `window.set_fullscreen` |
| Thunderbird | 13 | `filters.configure`, `mail.configure` | `messages.export_eml` | `accounts.remove`, `attachments.save`, `compose.attach`, `compose.set_recipients`, `contacts.export_csv`, `folders.ensure_local`, `identities.query`, `messages.query`, `ui.prefill_account_setup`, `xulstore.update` |
| Multi-Apps | 1 | - | - | `adapter.call` |

总计：31 + 31 + 24 + 12 + 41 + 28 + 27 + 9 + 13 + 1 = **217**；P0 18；P1 15；保留 184。

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

## Order 60 Staging Receipt (2026-09-21)

Order 60 (`e4ef0baf-4b52-4590-a47e-d4d464cca2d7`) retains two independent API
mutations: `shape.set_geometry` for the observed picture height on slide 3 and
`slide.format_text_roles` with `roles=["all"]` for slide 6. No new Adapter action,
schema, or combined mutation was introduced. Commit `d32a2f7` connects the existing
textbox-font-size stage to `impress_semantics.next_action`. After the initial
observation, only `shape.set_geometry` is exposed; after that mutation succeeds,
only the next textbox mutation remains in the tool surface. The first stage still
requires the initial inspection.

The focused progression and related Impress regression suite passed **81 tests**;
Ruff and compileall also passed. The reproducible local command was:

```bash
PYTHONPATH=src/adapter_versions/v2_expanded pytest -q \
  src/adapter_versions/v2_expanded/tests/test_impress_picture_text_progression.py \
  src/adapter_versions/v2_expanded/tests/test_strict_impress_completion.py \
  src/adapter_versions/v2_expanded/tests/test_bounded_impress_decomposition.py \
  src/adapter_versions/v2_expanded/tests/test_impress_picture_edge.py \
  src/adapter_versions/v2_expanded/tests/test_impress_underline_wiring.py \
  src/adapter_versions/v2_expanded/tests/test_impress_role_text_split.py \
  src/adapter_versions/v2_expanded/tests/test_impress_textbox_color_progression.py
```

An attempted Order 60 pilot with the historical v24 and v323 manifests stopped
at the runner condition gate because those frozen manifests have no current
`condition` object; it did not start a model/VM and has no evaluator score.
The newly sealed local retry1 then failed while prefetching the input PPTX from
Hugging Face; retry2 was rejected by a transient reasoning-gate configuration
(`openapi_url=null`); retry3 reached model preflight but failed on the same
Hugging Face input prefetch timeout before any model tool call. The retry3 result
is preserved at
`src/adapter_versions/v2_expanded/experiments/local-impress-picture-text-60-retry3-20260921/workers/worker-00/results.json`
with `status=environment_failure`, `passed=0`, and no evaluator score. The
implementation commit and this receipt are ready for the integration owner; the
full evaluator rerun still needs a newly sealed condition with a reachable or
pre-cached dataset input.

After correcting the cache key and sealing a retry4 condition, the real VM and
model did start. Its raw run is preserved at
`src/adapter_versions/v2_expanded/experiments/local-impress-picture-text-60-retry4-20260921/workers/worker-00/raw/run-1/60-libreoffice_impress-e4ef0baf-4b52-4590-a47e-d4d464cca2d7/`.
The model made 13 successful `presentation.inspect` calls against slide 3,
never issued either mutation, and ended with `agent_deadline_exhausted`; the
worker result is `passed=0` with no evaluator score. This is a model progression
failure, not an Adapter contract failure: the focused regression suite still
proves that once `shape.set_geometry` succeeds, only the textbox mutation remains
exposed.

Follow-up repair `8cc8729` closes the remaining progression gap: after the
required inspection, `stage_actions`/`filter_tools` hide duplicate
`presentation.inspect` for `shape.set_geometry`; after geometry succeeds they
hide both inspection and geometry while exposing only `slide.format_text_roles`.
Picture receipts now recognize schema-valid `height_measurement` values and
consistent `slide` plus `slide_number` arguments. The focused suite remained
**81 passed** with Ruff clean. Retry5 confirmed the first half in a real VM
(inspect, then geometry) but exposed the receipt-matching bug before this
follow-up; retry6 was sealed against the repaired source but the model endpoint
returned `522/525` on all three attempts before any tool call, so it has no
evaluator score.

Retry7 used the repaired source and a fresh sealed result directory. The real
trajectory confirms the intended mutation progression:
`presentation.inspect -> shape.set_geometry -> slide.format_text_roles`; after
the picture mutation, no picture mutation or inspection was exposed before the
text mutation. The raw run is preserved at
`src/adapter_versions/v2_expanded/experiments/local-impress-picture-text-60-retry7-20260921/workers/worker-00/raw/run-1/60-libreoffice_impress-e4ef0baf-4b52-4590-a47e-d4d464cca2d7/`.
After both mutations the model repeatedly inspected instead of saving and
finished with `agent_deadline_exhausted` (`passed=0`, no evaluator score); this
does not regress the requested picture-to-text staging.

### Order 60 Final Staging Surface (2026-09-22)

The two independent mutation APIs remain unchanged: `shape.set_geometry` and
`slide.format_text_roles`. Commit `7f0d519` adds one-shot post-mutation inspect
stages and save gating. Commit `4b682a5` prevents a saved, Adapter-verified
geometry receipt from being re-exposed when the final inspection focuses on a
different slide. Commit `cb88e13` closes the completed saved-readback surface,
and `6746d30` makes the staged action surface discovery-only, hiding
`gui_action`, `tools_search`, and other bypasses while exactly one of
`presentation.inspect`, `shape.set_geometry`, `slide.format_text_roles`, or
`presentation.save` is pending. No replacement API or combined mutation was
introduced.

The explicit Impress regression suite passed **221 tests**. Retry8 reproduced
the expected seven-call prefix but used a sealed pre-final-readback source and
then re-entered geometry. Retry9 reproduced the same seven-call prefix and
confirmed no geometry re-entry, but repeated inspect after the final read-back.
Retry10 exposed the bypass tools before `6746d30` and was stopped. Retry11 used
the final sealed source and its request artifacts show only the staged action
at each first turn, but the model endpoint returned `502`/`524` before mutation;
no evaluator score is claimed. The runs are preserved in the corresponding
`experiments/local-impress-picture-text-60-retry8-20260922/` through
`retry11-20260922/` directories.

The final completion-surface fix is commit `920031c`: once the saved read-back
is complete, only `propose_done` is exposed. A minimal direct transport probe
returned HTTP 200 before the rerun. Retry13 then passed the original evaluator
with `reward=1.0`; its mutation/read-back prefix contains exactly one inspect
after each mutation and no repeated mutation. No replacement or combined API
was added.

### Order 60 Terminal-Audit Repair (2026-09-22)

The API replacement remains unchanged: `shape.set_geometry` and
`slide.format_text_roles` are still two independent mutations. Commit
`57d69d3ea127154034cc87ce495914dd225e80b1` changes only the post-completion
audit surface. Once a `propose_done` or `fail_task` result has passed the generic
completion gate, the next model turn exposes only that same terminal control;
`tools_search`, `presentation.inspect`, GUI actions and other mutations are no
longer alternatives. This prevents an accepted completion from reopening a
search/inspect loop while preserving the existing one-turn audit boundary.

Focused checks passed: `test_recovery_surface.py` (**56 passed**),
`test_episode_control.py` plus `test_hybrid_gui_completion.py` (**34 passed**),
and Ruff on the three changed Python files. The qwen1 single-task command and
local-cache input are recorded in `API_SPLIT_TASK.md`. Retry19 passed the
original Order 60 evaluator with `status=passed`, `reward=1.0`, and
`termination_reason=agent_done`; the saved PPTX comparison reported
`COMPARISON SUCCESSFUL - Files match`. Result:
`experiments/local-impress-picture-text-60-retry19-20260922/workers/worker-00/results.json`.

### Order 99 API State (2026-09-24)

Order 99 is **PASS** (`reward=1.0`). The public generic flow remains split into
three bounded operations: `os.pdf.extract_text_batch` for observation,
`os.filesystem.create_directory` for destination preparation, and
`os.filesystem.copy_to_directories` for the single-file mutation. No replacement
or combined invoice-reconciliation API was introduced.

The API state changed only in generic routing/recovery: PDF extraction accepts a
unique discovered directory when `active_terminal` is unavailable, and
multi-app search gives invoice/statement extraction plus file-organization
mutations higher relevance than repeated `filesystem.find`. This is reusable
behavior and does not encode Order 99 paths or evaluator data.

Implementation commit: `97adcf2`.

Evidence: `src/adapter_versions/v2_expanded/experiments/local-invoice-discrepancy-99-retry8-20260924/workers/worker-00/results.json`.

### Order 95 API State (backfilled 2026-09-24)

Order 95 is **BLOCKED/FAIL**. The final completed local-Qwen retry returned
`reward=0.0` with `termination_reason=stalled_no_progress`; the generic
v301-v303 lifecycle likewise reached the evaluator but remained content-inexact
(`reward=0.0`). Evidence:
`src/adapter_versions/v2_expanded/experiments/local-pdf-authors-95-retry8-20260922/workers/worker-00/results.json`.

The API state is unchanged and deliberately split:
`os.pdf.extract_text_batch` is the bounded, read-only observation operation;
`libreoffice_calc.workbook.create_new` is the separate native workbook
creation mutation receiving model-supplied headers and rows. No author parser,
task-specific route, or combined PDF-to-spreadsheet API was introduced.
There is no dedicated Order 95 implementation commit; the frozen imported
source is `b800fd9`, with OSWorld pinned at
`091f5ef1d5544bc74953c77875d5feb5bed30108`.

Reproduction command:

```text
HF_ENDPOINT=https://hf-mirror.com /var/lib/liteagent-shared/python-env/bin/python src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py --config src/adapter_versions/v2_expanded/experiments/configs/local-pdf-authors-95-20260922.json --orders 95 --result-dir src/adapter_versions/v2_expanded/experiments/local-pdf-authors-95-retry8-20260922/workers/worker-00 --base-url https://qwen1.jinmaoapi.cc.cd/v1 --model qwen3.5-4b --max-steps 45 --max-local-steps 25 --max-soft-restarts 1 --max-agent-seconds 1200 --max-output-tokens 768 --reasoning-mode non_thinking --request-timeout 240 --model-retries 3 --initial-settle-seconds 10 --action-settle-seconds 2 --evaluator-settle-seconds 5 --evaluator-file-fetch-attempts 3 --evaluator-file-fetch-delay-seconds 1
```

### Order 96 API State (backfilled 2026-09-24)

Order 96 has a historical original-evaluator **PASS** (`reward=1.0`,
`agent_done`, 14 steps; result SHA-256
`36fd81b0da7591e3c9979ba1f5aa21dbe8d17cf21fefec7e9fbeddcb0fb26b90`). The
model used the existing generic spreadsheet/Writer workflow and did not call
the patched `text.find` route, so the result does not establish causal benefit
from that guidance change.

No API replacement was promoted. The existing generic actions remain the
public contract; the v70-v73 matching-row candidates are retained as
non-promoted experiments. Frozen source metadata is
`93d391af26637dbd761b006a810b1f536e77490a` (import snapshot `b800fd9`), and
there is no dedicated Order 96 implementation commit.

Historical reproduction command:

```text
PYTHONPATH="$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld:$PWD/src" /home/liuhao/computer_use/adapter_versions/v2_expanded/.venv-openapa/bin/python src/adapter_versions/v2_expanded/scripts/supervise_lite_agent_parallel.py --config src/adapter_versions/v2_expanded/experiments/configs/holo31-all-roles-order96-optional-format-guidance-retest-20260913-v1.json --result-dir src/adapter_versions/v2_expanded/experiments/holo31-all-roles-order96-optional-format-guidance-retest-20260913-v1-run1 --workers 1 --base-urls http://192.168.0.138:8001/v1 --model holo3.1-4b --python /home/liuhao/computer_use/adapter_versions/v2_expanded/.venv-openapa/bin/python --max-steps 100 --max-local-steps 50 --max-agent-seconds 1800 --max-output-tokens 4096 --reasoning-mode thinking --request-timeout 240
```
### Order 95 API State (validated 2026-09-25)

Order 95 now **PASS** after the minimal evidence-assembly repair. The final local-Qwen retry20 returned `status=passed`, `reward=1.0`, and `termination_reason=agent_done`. The result is preserved at `src/adapter_versions/v2_expanded/experiments/local-pdf-authors-95-retry20-20260925/workers/worker-00/results.json`.

The API state remains intentionally split and generic:

- `os.pdf.extract_text_batch` remains the bounded, read-only observation API.
- `libreoffice_calc.workbook.create_new` remains the separate native workbook mutation receiving model-selected headers and rows.
- The repair adds evidence validation at the generic table contract boundary: after every requested field is observed, rows must preserve each PDF's same-document first-author, complete email, and complete affiliation; placeholder, guessed, cross-document, or shortened values are rejected with a correction message. It does not synthesize values, expose a task-specific parser, combine the two APIs, or reread completed PDFs.

For the task wording `e-mail`, the generic correction requires the concise `Mail` header so the requested field label is preserved. This is a schema/contract correction, not a new API or task route.

Implementation commit: `9361c0d` (`fix(order95): validate evidence-derived author assembly`). Focused check: `58 passed` in `src/adapter_versions/v2_expanded/tests/test_batch_table_stage.py`; `git diff --check` passed. The exact local-mirror/Qwen validation command is recorded in `API_SPLIT_TASK.md` under the Order 95 repair entry.

### Order 102 API State (2026-09-25)

Order 102 is **PASS** (`reward=1.0`, `agent_done`). The API state remains split:
`os.filesystem.find(kind=any)` observes files and directories, optional
`os.pdf.extract_text_batch` reads ambiguous content, and `os.filesystem.rename`
moves each source to its category. The generic runtime now records an
observation-complete marker with exact paths and the next phase
`classify_and_move`; it rejects all later filesystem searches, narrows the
surface to rename after route discovery, and exposes only completion after all
observed sources have moved. No task-specific parser, golden route, or batch
organization API was added.

Evidence: `src/adapter_versions/v2_expanded/experiments/local-file-organize-102-20260925-retry7-20260925/workers/worker-00/results.json`.
Implementation commit: `2eb1acb` (`fix(order102): gate organization after filesystem observation`);
the integration owner should merge it.

### Order 121 API State (2026-09-27)

Order 121 is **PASS** in the preserved historical audit (`src/adapter_versions/v2_expanded/docs/project-progress.md`, the final Order 121 entry). The task uses the existing narrow pair `libreoffice_calc.workbook.read_file` and `thunderbird.compose.set_recipients`. Neither action is a P0 candidate: the Calc operation is bounded read-only observation, while the Thunderbird operation changes only the already-open compose window's To recipient pills and verifies the resulting accessibility state. `append` and `replace` choose the state transition for that one field; they do not combine independent mail settings, create a draft, or send it.

The current contract keeps the two decisions model-visible and sequential. The spreadsheet reader requires an explicit local path and bounds sheet/range and row/column windows; `range.read` remains the separate choice for an already-open workbook and a single contiguous rectangle. The recipient action requires a non-empty model-selected address array, optionally takes an observed exact subject for compose-window disambiguation, and performs native read-back after each address. Search/recovery checks cover both `workbook.read_file` and `compose.set_recipients`; no task-aware route, answer derivation, or combined spreadsheet-to-mail action was added.

Focused validation on the current checkout passed **156 tests** across recovery surface, active-workbook discovery, spreadsheet-open semantics, and the existing mail selector contract. The historical final audit recorded 8 events and evaluator reward `1.0`; its raw result directory is not present in this source snapshot, so this entry does not claim a new evaluator run.

### Order 157 API State (2026-09-28)

Order 157's instruction is to enable Thunderbird's unified inbox view. The required
replacement is the single-setting `thunderbird.inbox.set_unified(enabled)` action.
It writes only the native `xulstore.json` folder-tree mode (`smart` when enabled,
`all` when disabled) and receives a default `json_path` read-back; it does not
touch preferences or accept any other mail setting. The former `mail.configure`
facade is retired and returns actionable replacement actions instead of accepting
the old heterogeneous payload.

The model-visible manifest, runtime validation, dispatch, worker verification and
catalog surface are aligned on this action. Focused unified-inbox contract checks
passed (5 tests) and the Thunderbird files passed Ruff. The formal single-task
result is preserved in
`src/adapter_versions/v2_expanded/experiments/local-order157-unified-inbox-20260928-rerun2/`:
the original evaluator reports `status=passed`, `reward=1.0`, and
`termination_reason=agent_done`; `result.txt` contains `1.0`. The complete raw
trajectory and call evidence are in
`workers/worker-00/raw/run-1/157-thunderbird-3f49d2cc-f400-4e7d-90cc-9b18e401cc31/`,
with `adapter_calls.jsonl` showing the successful
`inbox.set_unified(enabled=true)` call and read-back `mode=smart`. Order 157 is
therefore **PASS**. A later attempt using the same frozen config and a new output
directory was correctly rejected before VM launch because that directory was not
declared by the frozen condition; it did not alter or invalidate the preserved PASS.

### Order 158 API State (2026-09-29)

Order 158 requires disabling quoted original text in replies. The task uses the
single-setting `thunderbird.identity.set_reply_quoting(identity, enabled)` action,
with a preceding read-only `identities.query` to obtain the exact profile identity.
The replacement writes only `mail.identity.<identity>.auto_quote` in `prefs.js` and
returns a preference read-back; it does not expose the retired heterogeneous
`mail.configure` payload or touch unrelated mail settings.

The formal retry is preserved in
`src/adapter_versions/v2_expanded/experiments/formal-order158-20260929-retry1/`.
The first attempt is retained as an environment-only Hugging Face timeout in
`formal-order158-20260929/`; it reached no model action. The successful trajectory
shows `identities.query -> identity.set_reply_quoting(identity="id1", enabled=false)`
and verification of `mail.identity.id1.auto_quote=false`. The original evaluator
reports `status=passed`, `reward=1.0`, and `termination_reason=agent_done`; Order 158
is **PASS**. Focused mail contract validation passed 32 tests and relevant Python
files passed Ruff.
The 2026-10-03 endpoint retry used `https://qwen.jinmaoapi.cc.cd/v1` and is also
preserved in `src/adapter_versions/v2_expanded/experiments/formal-order158-20261003-retry3/`;
it produced the same verified two-action chain and formal evaluator
`status=passed`, `reward=1.0`, `termination_reason=agent_done`.
### Order 160 API State (2026-09-29)

Order 160 asks Thunderbird to apply existing incoming message filters
automatically on IMAP subfolders. The task uses the single-setting
`thunderbird.filters.set_subfolder_application(enabled)` action. It writes only
the generic preference state required for that setting: enables
`mail.server.default.applyIncomingFilters`, disables
`mail.imap.use_status_for_biff`, and removes the conflicting offline-sync
override. It does not configure any filter rule, create folders, or expose the
retired `preferences.update`/`mail.configure` facades.

The generic instruction classifier was corrected so wording that only asks to
apply filters to subfolders does not additionally require `filters.configure`;
concrete rule criteria or actions still route to the single-rule filter action.
The model-visible schema, validation, dispatch, default preference
verification, and focused contract test remain aligned.

The first formal attempt completed the setting but exposed that completion-gate
misclassification and was retained at
`src/adapter_versions/v2_expanded/experiments/local-order160-subfolder-filters-20260929/`.
The retry passed with `status=passed`, `reward=1.0`, and
`termination_reason=agent_done`; the successful call and three preference
read-backs are in
`src/adapter_versions/v2_expanded/experiments/local-order160-subfolder-filters-20260929-retry1/workers/worker-00/raw/run-1/160-thunderbird-08c73485-7c6d-4681-999d-919f5c32dcfa/adapter_calls.jsonl`,
and `result.txt` contains `1.0`. Focused mail contract validation passed 34
tests and the changed Python files passed Ruff.

### Order 107 API State (2026-09-29)

**最新运行更正（2026-10-10）：Order 107 最新已记录结果为 FAIL / reward=0.0，45 步、505.698 秒。** 最新结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)；最新事件：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/lite_agent_events.jsonl)。下方 2026-10-02 的 local-ecs-rates-107-strict-rerun11 是历史 PASS，不是最新一轮。

Order 107 is **PASS** (`status=passed`, `reward=1.0`,
`termination_reason=agent_done`). The evaluator evidence is preserved at
`src/adapter_versions/v2_expanded/experiments/local-ecs-rates-107-retry92-20260929/workers/worker-00/results.json`.

The API state is intentionally decomposed into bounded observation and atomic
Calc mutations:

- `os.filesystem.find` discovers the PDF inputs once.
- `os.pdf.tables.inspect` is called once for each of the nine PDFs. This is the
  bounded continuation unit; a nine-document batch is not exposed because the
  Qwen response can be interrupted before all source observations are returned.
- `libreoffice_calc.workbook.inspect` observes the active workbook, followed by
  `libreoffice_calc.range.read`, `libreoffice_calc.range.write`, a read-back
  `range.read`, and `libreoffice_calc.workbook.save`.

The generic state machine records completion of all nine structured PDF
observations, derives the next action from the observation ledger, prevents
repeated GUI/search/PDF calls, and exposes only the next valid consumer action.
After the successful write and read-back it exposes save, and after save it
exposes only `propose_done`. No task-specific parser, combined PDF-to-sheet
mutation, or golden route was added. The model-visible API replacement is
therefore a sequence of existing generic actions, with lifecycle gating rather
than a larger facade.

Implementation commit: `1f873e3` (`fix(order107): split ECS PDF table observations`).
Focused contract validation: `86 passed` in
`src/adapter_versions/v2_expanded/tests/test_batch_table_stage.py`.

### Order 107 endpoint rerun (2026-10-02)

**最新运行更正（2026-10-10）：Order 107 最新已记录结果为 FAIL / reward=0.0，45 步、505.698 秒。** 最新结果：[results.json](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/results.json)；最新事件：[lite_agent_events.jsonl](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/107-multi_apps-881deb30-9549-4583-a841-8270c65f2a17/lite_agent_events.jsonl)。下方 2026-10-02 的 local-ecs-rates-107-strict-rerun11 是历史 PASS，不是最新一轮。

The same generic API replacement was rerun against the requested Qwen endpoint
`https://qwen.jinmaoapi.cc.cd/v1` with the local Hugging Face mirror. The run
passed the original OSWorld evaluator with `status=passed`, `reward=1.0`, and
`termination_reason=agent_done`. Evidence is preserved at
`src/adapter_versions/v2_expanded/experiments/local-ecs-rates-107-strict-rerun11-20261002/workers/worker-00/results.json`;
the adapter trace is in its adjacent `raw/run-1/107-multi_apps-*/adapter_calls.jsonl`.

The observed sequence was one `os.filesystem.find`, nine bounded
`os.pdf.tables.inspect` calls, `libreoffice_calc.workbook.inspect`, one
`range.write` to `B2:I10`, one post-write `range.read`, `workbook.save`, and
`propose_done`. No repeated PDF search or task-specific combined mutation was
exposed. The implementation remains commit `1f873e3`
(`fix(order107): split ECS PDF table observations`); this rerun only changed the
endpoint/configuration and produced no new API surface.

## 2026-10-10：固定 28 题测试与通过改动提交

本轮完整顺序测试由原始 OSWorld evaluator 判定 **23 通过、5 失败，82.14%**。通过 Order：`20, 41, 42, 47, 52, 53, 54, 59, 60, 67, 68, 81, 83, 95, 96, 121, 152, 153, 154, 157, 158, 159, 160`。失败 Order：`91, 99, 102, 107, 108`，均 reward=0.0、45 步；47、53 虽 stalled_no_progress，正式 evaluator 仍 reward=1.0。本记录只更新本轮回执，不将早先 PASS 改写或当作本轮 PASS。

用户随后授权提交通过题目最后未提交改动。按题目拆分保留：

| Order | 本次提交 | 改动与 API 审计状态 |
|---:|---|---|
| 42 | `6985f92` | 内容格式 mutation 限制为 content/body 角色；扁平化模型侧 role-format/background schema；Adapter 原始契约仍校验参数 |
| 54 | `faecaad` | cleanup 完成后必须保存并回读全部受影响页，再展示原生完成控制；shape.format_text 模型侧 schema 扁平化 |
| 60 | `82a3dbb` | 图片高度动作绑定实际 presentation 观测；执行前验证目标，只允许匹配当前步骤的几何参数注入 |
| 121 | `0cb4e62` | 完整源读取后转入 mail-recipient route 发现；保留 workflow_progress，恢复提示使用 workbook.read_file |

其余通过题目已有历史实现提交，本次补充验证回执；158 既有 endpoint 重跑记录一起补交。失败题目和无法独立归属的共享改动未纳入上述实现提交。上述模型 schema/运行流程调整没有新增 Adapter API 或改变本表原始 217 action 计数。本轮分数来自带未提交内容的完整工作区，拆分提交快照未重新评测；提交快照 Python 语法、Ruff 与 whitespace 检查通过。

完整 28 题表、单题回执、提交边界和证据索引见 [本轮提交审计](../src/adapter_versions/v2_expanded/docs/osworld-passing-submission-20261010.md)，精简数据见 [JSON 回执](../src/adapter_versions/v2_expanded/docs/osworld-passing-submission-20261010.json)。原始实验内容保持不变。

### 本轮 FAIL 的正式日志回填（2026-10-10）

91、99、102、107、108 的本轮逐题 FAIL 回执已补入 [正式开发日志](../API_SPLIT_TASK.md#2026-10-10-本轮失败题目正式运行日志)。每题记录 task ID、原始 status/reward、45 步、耗时、termination_reason=null、完整轨迹、evaluator 产物与已观察到的输出差异。91/99/108 未获取要求的输出文件；102 学术论文目录缺少 paper01.pdf；107 成功获取表格但对照未通过。上述表现尚未被当作完整根因结论，历史 PASS 与本轮 FAIL 分别保留。本次为日志补交，无 API 修改或新测试。

### Order 91 后续单题修复与正式 PASS（2026-10-10）

最新单题结果为 **PASS / reward=1.0**：`osworld-order91-qwen-20261010-query-priority`，5 步、471.024 秒、`termination_reason=agent_done`。首次/末次工具事件分别为北京时间 21:21:37、21:23:07。原始批次的 23/28 与本题 FAIL/0.0 保留；这次单题复跑单独记账。

失败根因已从完整轨迹确认：45 步均重复同一 Thunderbird 搜索，公开库中存在 `messages.query`，但全题关键词触发的文件/Calc 排名加分将其挤出前六项。实现提交 `84a3a4c` 仅调整 Multi-Apps 搜索排序，优先当前查询明确指定的应用及操作名称匹配。`thunderbird.messages.query` 与 `libreoffice_calc.workbook.create_new` 继续保留原 API 契约，无新增 action 或题目专用逻辑。8 项临时定向 contract 检查、Ruff 和差异检查通过。

正式 evaluator 成功读取桌面 `report.xlsx`；邮件查询返回最新 5 条并时间升序，工作簿写入 `A1:E6`、30 单元格且已保存。模型这次使用精确工具名；失败中的自然语言搜索词已在定向检查中复现并确认首位命中。新 [结果回执](../src/adapter_versions/v2_expanded/experiments/osworld-order91-qwen-20261010-query-priority/results.json)、[单题日志](../src/adapter_versions/v2_expanded/docs/order91-query-priority-fix-20261010.md)、[正式日志](../API_SPLIT_TASK.md#order-91--后续搜索修复-pass2026-10-10)、[最新入口](../src/adapter_versions/v2_expanded/docs/index.md) 已同步。首轮记录提交 `76ab5c3`。

## 2026-10-10：大粒度与题目定制逻辑复审

当前 checkout 枚举为 **221 个公开 action**（含未提交实现），不能沿用旧 217 的数量结论。定向复审确认：Calc create_new 存在按固定 GRF 表头隐式设置百分比格式；Runner 存在固定 GRF/ECS 年份、学科、表格布局、矩阵计算，以及只需确认即代模型写入的 repair_confirm 宏。它们列为 **4 组 P0 定制/隐藏决策问题**；first-author 领域流程和 Impress 参数注入另列 **2 组 P1 待泛化/复核问题**。没有据此认定 golden 泄漏。

Chrome/GIMP/OS/VS Code/VLC 共 **11 个历史大粒度入口**仍可通过 strict_generic 工具面访问。这些是粒度问题，不一概等同于定制求解器。已拆分的 Calc text_transform、Impress role formatting、Thunderbird 单设置/单过滤器契约仍保留。

先前 107/108 中“没有题目专用解析/组合”的历史描述不能代表当前工作区；当前固定领域解析及参数替换未通过本次通用性复审。原始 evaluator PASS 不替代 API 粒度审查。源码与原始实验保持不变。完整证据、位置与处理建议见 [复审报告](../src/adapter_versions/v2_expanded/docs/api-customization-review-20261010.md)，公开清单及工具 schema 见 [复审快照](../src/adapter_versions/v2_expanded/docs/api-customization-review-20261010.json)。

### Order 99：最新 FAIL 的单题修复（2026-10-10）

本轮 45 步纯工具搜索的 FAIL 已按完整模型请求诊断，并在单题重跑中取得 evaluator PASS。保留 `os.pdf.extract_text_batch` 作为有界只读观察，保留显式发现和单对象移动；收窄整理的初始清单参数，同步模型 schema/运行时 validation，并修复对照证据保留、retain 目录契约和拒绝后的恢复。没有新增大粒度 API、golden、任务 ID 路由或答案。完整验证与评分限制、每次结果、增量补丁及共享工作区集成边界见 [Order 99 修复记录](../src/adapter_versions/v2_expanded/docs/order99-inventory-repair-20261010.md)。
