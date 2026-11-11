# 大粒度 API 拆分与关联题目复跑

更新：2026-11-11。基点：`codex/v4`，`306b70b4433e6070fb4f05400070e5a952a8a905`。
用户本次授权范围为截图中的 11 个入口；旧 `API_SPLIT_TASK.md` 的范围限制不覆盖本次请求。
审核方式：主代理自行审核，不开子 agent。旧执行失败 31 题队列仍暂停，不混入本批结果。

## 原子边界与禁止项

一次公开写调用只完成一个独立的用户操作。单个设置可以涉及实现该设置所需的多个底层字段，但不能顺带修改其他设置、开启应用、保存导出或完成整题。输入路径、对象、参数、顺序与判断由模型决定。

不得用改名规避拆分，不新增多设置 `values/settings/operations` 字典、批量循环宏、按题号分支、内置答案或自动解题工具。私有底层代码可以复用，但旧组合入口必须从公开动作列表、工具 schema、搜索、跨应用转发及直接分发中移除或明确拒绝。只写“一次传一个”不算拆分。

## 11 个入口与目标契约

以下新名称为实施目标；只有下方进度明确记录后才算已实施。所有设置写入后读取目标设置验证，并用定向测试确认无关设置保持原值；非法参数在修改前拒绝。

| 旧入口 | 已核实的问题 | 拆分目标与参数 |
| --- | --- | --- |
| `chrome.settings.set` | `settings` 可同时修改 8 个设置 | `settings.set_do_not_track(enabled)`、`set_safe_browsing(enabled)`、`set_profile_name(name)`、`set_startup_mode(mode)`、`set_appearance(appearance)`、`set_clear_on_exit(enabled)`、`set_font_size(size)`、`set_search_engine(engine)`；值域沿用旧验证，不捆绑重启 |
| `gimp.image.adjust` | 一次亮度/对比度/饱和度调整后保存，并可打开 GUI；旧默认校验为 if/elif，组合效果可能漏验 | 分离图像载入、单效果 `image.set_brightness` / `image.set_contrast` / `image.set_saturation`、保存/导出、GUI 打开。先落实可持续编辑的图像身份，不能把每个新效果接口仍写成“载入→调整→保存→打开”的解题流程；数值范围分别保留 -127..127、-127..127、-100..100。导出复用现有 `image.export` 前需确认它读取的是已保存文件而非未保存 GUI 缓冲 |
| `vs_code.debugging.configure` | 可改 6 个独立调试设置 | 每个字段一个 `debugging.set_<field>(value, path?)`：focus_editor_on_break、inline_values、internal_console、open_debug_view、show_breakpoints_in_overview_ruler、show_inline_breakpoint_candidates |
| `vs_code.editor.configure` | 可改 8 个编辑器设置 | 每个字段一个 `editor.set_<field>(value, path?)`：wrap_tabs、word_wrap、word_wrap_column、minimap_enabled、line_numbers、sticky_scroll_enabled、smooth_scrolling、render_whitespace |
| `vs_code.files.configure` | 可改 6 个文件设置 | 每个字段一个 `files.set_<field>(value, path?)`：auto_save、auto_save_delay_ms、trim_trailing_whitespace、insert_final_newline、trim_final_newlines、hot_exit。自动保存模式和延迟必须分两次写入 |
| `vs_code.settings.update` | 任意多键 values，可绕过语义接口 | 取消公开任意字典写入；已知设置走上述单设置接口，诊断/排除设置保留各自独立语义动作。私有 JSON merge 可复用，不能仍可公开调用组合入口 |
| `vlc.preferences.configure` | 8 类偏好可组合，recording_directory/location 是同一语义的两个输入形式 | 单设置 `preferences.set_global_play_pause_hotkey`、`set_maximum_volume_percent`、`set_volume_slider_color`、`set_minimal_interface`、`set_exit_after_playback`、`set_allow_multiple_instances`、`set_show_background_cone`、`set_recording_directory`。各自只接受本设置；重启/播放另调原子接口 |
| `vlc.config.update` | 任意多键 values，构成旁路 | 取消公开组合写入；已有偏好映射到单设置接口。额外确有需求的配置另建单设置契约，不恢复任意多键入口 |
| `os.desktop.set_accessibility_scale` | 同时写文字缩放、启放大镜、放大倍数 | 复用现有 `desktop.set_setting(schema,key,value)`，一次一个 GSettings key；文字缩放不隐式开启放大镜。三项分别是 `org.gnome.desktop.interface/text-scaling-factor`、`org.gnome.desktop.a11y.applications/screen-magnifier-enabled`、`org.gnome.desktop.a11y.magnifier/mag-factor` |
| `os.desktop.set_dim_inactive` | idle_dim 与 idle_delay 可同时写 | 同样复用单 key `desktop.set_setting`；`org.gnome.settings-daemon.plugins.power/idle-dim` 与 `org.gnome.desktop.session/idle-delay` 独立调用 |
| `os.archive.create_extract` | 已有 `archive.create_zip` / `archive.extract_zip`，但旧入口仍公开 | 保留两原子接口；创建只收 archive_path/input_paths/base_directory?/overwrite?，解压只收 archive_path/destination_directory/overwrite?；两者不接受 mode 或对方字段；移除旧公开入口，底层私有 ZIP 实现可复用 |

源码主要在 `src/adapter_versions/v2_expanded/{chrome,gimp,vscode,vlc,os}_adapter/`，以及 `integrations/lite_agent/{tool_catalog,adapter_results,...}.py`、`integrations/openapa_osworld/tool_catalog.py`。Chrome 的公开 schema 不在 tool_manifest。修改须贯穿 schema→校验→分发→执行→验证→发现→转发→恢复提示→实际调用者，不能只改工具描述。

## 关联题目

证据基线：
`/home/liuxv/liteagent-local-runs/latest-full189-12workers-20261102T080546Z/source/runs/latest-full189-12workers-20261102T080546Z/`。
任务原文在 `src/third_party/OSWorld/evaluation_examples/examples/<domain>/<UUID>.json`。
“轨迹命中”指该次 `lite_agent_events.jsonl` 的实际调用；“语义关联”需回归但不声称调用过旧 API。

| 接口组 | 189 Order | task UUID | 关联依据 |
| --- | --- | --- | --- |
| ZIP 创建 | 117 | `8df7e444-8e06-4f93-8a1a-c5c974269d82` | 轨迹第7步创建 essay_submission.zip |
| ZIP 解压 | 132 | `aceb0368-56b8-4073-b70e-3dc9aee184e0` | 轨迹第4步解压 exam.zip |
| ZIP 创建 | 100 | `82e3c869-49f6-4305-a7ce-f3e64a0618e7` | 语义关联：筛选照片后压缩 presenter 目录 |
| OS idle dim | 133 | `bedcedc4-4d72-425e-ad62-21960b11fe0d` | 轨迹第1步 idle_dim=false |
| OS text scale | 140 | `3ce045a0-877b-42aa-8d2c-b4a863336ab8` | 轨迹第1步 text_factor=1.5+magnifier_factor=1.5；原题只要求文字放大，额外开启放大镜属于多余副作用 |
| GIMP brightness | 119 | `4c26e3f3-3a14-4d86-b44a-d3cedebbb487` | 轨迹第4步 brightness=40；提取 Impress 图片后调整并另存 |
| VS Code debugging | 177 | `9439a27b-18ae-42d8-9778-5f68f891805e` | 轨迹关闭 focus_editor_on_break |
| VS Code editor | 180 | `276cc624-87ea-4f08-ab93-f770e3790175` | 轨迹 word_wrap_column=50 |
| VS Code editor | 181 | `9d425400-e9b2-4424-9a4b-d4c7abac4140` | 轨迹 wrap_tabs=true |
| VS Code files | 185 | `70745df8-f2f5-42bd-8074-fbc10334fcc5` | 轨迹自动保存 after_delay、500ms；拆后两次调用 |
| VS Code 通用写入口旁路回归 | 176 | `e2b5e914-ffe1-44d2-8e92-58f8c5d92bb2` | 语义关联：Python missing imports 诊断 |
| VS Code 通用写入口旁路回归 | 187 | `c6bf789c-ba3a-4209-971d-b63abf0ab733` | 语义关联：隐藏 __pycache__ |
| VLC recording | 162 | `8ba5ae7a-5ae5-4eab-9fcc-5dd4fe3abf89` | 轨迹 recording_location=desktop |
| VLC hotkey | 167 | `386dbd0e-0241-4a0a-b6a2-6704fba26b1c` | 轨迹全局 Media Play Pause |
| VLC volume | 168 | `9195653c-f4aa-453d-aa95-787f6ccfaae9` | 轨迹最大音量200% |
| VLC slider | 169 | `d06f0d4d-2cd5-4ede-8de9-598629438c6e` | 轨迹滑块 #1a1a1a |
| VLC minimal | 170 | `a5bbbcd5-b398-4c91-83d4-55e1e31bbb81` | 轨迹启用精简界面 |
| VLC exit | 171 | `5ac2891a-eacd-4954-b339-98abba077adb` | 轨迹关闭播放完退出 |
| VLC multiple instances | 172 | `f3977615-2b45-4ac5-8bba-80c17dbe2a37` | 轨迹允许多实例；旧轨迹重复循环需重点检查 |
| VLC background cone | 173 | `215dfd39-f493-4bc3-a027-8a97d72c61bf` | 轨迹隐藏背景锥形图标 |

189 题中没有独立 Chrome/GIMP domain，因此下列题无该批 Order；用 domain+UUID 定位，运行器配置中的本地索引不得冒充原189题号。

| domain | task UUID | 设置/回归范围 |
| --- | --- | --- |
| chrome | `030eeff7-b492-4218-b312-701ec99ee0cc` | Do Not Track |
| chrome | `9656a811-9b5b-4ddf-99c7-5117bcef0626` | Safe Browsing |
| chrome | `2ae9ba84-3a0d-4d4c-8338-3a1478dc5fe3` | profile name Thomas |
| chrome | `3299584d-8f11-4457-bf4c-ce98f7600250` | startup mode |
| chrome | `93eabf48-6a27-4cb6-b963-7d5fe1e0d3a9` | appearance |
| chrome | `99146c54-4f37-4ab8-9327-5f3291665e1e` | clear on exit |
| chrome | `af630914-714e-4a24-a7bb-f9af687d3b91` | font size |
| chrome | `bb5e4c0d-f964-439c-97b6-bdb9747de3f4` | Bing |
| chrome | `6766f2b8-8a72-417f-a9e5-56fcaa735837` | 语义回归：解压 extension 后加载 |
| gimp | `7a4deb26-d57d-4ea9-9a73-630f66a7b568` | 减少亮度 |
| gimp | `e19bd559-633b-4b02-940f-d946248f088e` | 减少亮度并存桌面 |
| gimp | `f723c744-e62c-4ae6-98d1-750d3cd7d79d` | 提高对比度 |
| gimp | `554785e9-4523-4e7a-b8e1-8016f565f56a` | 提高饱和度 |
| gimp | `2e6f678f-472d-4c55-99cc-8e7c5c402a71` | 多图亮度50；由模型枚举逐张处理，不能新增整目录解题宏 |
| gimp | `77b8ab4d-994f-43ac-8930-8ca087d7c4b4` | 语义回归：独立 JPEG 导出 |

`vs_code.settings.update` 和 `vlc.config.update` 未在这189轨迹中直接命中；仍须通过对应语义设置题验证拆后没有公开旁路。

## 执行顺序和验收

1. ZIP：关闭旧双模式入口，保留现有创建/解压；117→132→100，独立 extension 解压题在 Chrome 组回归。
2. OS：将组合桌面设置迁移至已有单 key 设置；133→140。
3. VS Code：先拆三组语义设置，再关闭任意字典入口；177→180→181→185，再176→187回归。
4. VLC：拆八类偏好并关闭任意字典入口；162→167→168→169→170→171→172→173。
5. Chrome：八种单设置动作，对应八道独立题，再 extension 解压回归。
6. GIMP：先处理可持续图像状态和独立保存边界，再亮度/对比度/饱和度；119及六道独立题。

每组均先实际拆 API、同步所有公开面与调用者、做定向检查并提交候选，再从干净候选建立独立工作树正式复跑。一题一跑，不热改运行中源码。检测旧入口拒绝、原子参数不接受组合/对方字段、跨应用 route 与 provider schema 一致、无关设置不变、校验失败无写入，以及 ZIP 字节/目录/安全约束保留。

模型使用本机 `http://127.0.0.1:18009/v1`，`Qwen3.5-9B` thinking，100步/1800秒，配置 `tool_call_stop_sequence=null` 与当前本地服务协议一致。原始任务、输入、参考、pinned evaluator 和评分阈值不改。运行器 `bin/run-osworld.py --orders ... --config ... --result-dir ...` 从配置 tasks 选择，因此独立 Chrome/GIMP 也可通过明确 domain/task_id 的独立配置运行；记录本地索引与原189 Order的区别。

失败后逐项核对实际模型请求、工具说明/参数、执行结果、状态读回、完成判定及评分：

- 先分清服务超时、协议/参数错误、工具实现错误和模型业务判断。`agent_deadline_exhausted`、`reward=null` 不是已判定业务错误或通过。
- 阶段提示只根据实际已完成事实推进：发现对象→读取当前状态→明确下一次原子调用及字段→读回核验→必要的独立保存/重启→完成。提示保留未完成要求，不凭工具出现在候选列表就宣布进入阶段。
- 仍失败时进一步明确当前对象、真实参数范围、剩余操作和停止条件；每次新版本、提交、新目录复跑。已读回正确且无后续修改时不反复重写/重启/全量审核。提示不能包含参考答案、任务 UUID 分支或替模型完成判断。
- 原 evaluator 正式 PASS、源码/配置/OSWorld 完整性都通过后才集成该组候选。单测、HTTP200、模型宣称完成、手工看到正确、历史PASS均不能替代本批拆分后PASS。

本批运行证据计划根目录：`/home/liuxv/liteagent-local-runs/split-api-20261111/`。逐题保存 task身份、基点/候选提交、实际配置、完整事件、原评分、完整性、提示版本与集成结论。只关闭本批自有进程/guest。

## 实施进度

以下候选均在仓库外独立工作树，未作为已通过修复集成到主分支。完整性/原评分均逐题保存。

| 组 | 候选分支/提交 | 定向检查 | 正式复跑 |
| --- | --- | --- | --- |
| ZIP | `codex/split-api-20261111` / `69999f3` | 49 PASS；公开旧入口、搜索与执行分发已移除 | Order117 run-001 PASS1.0，14步357.173秒，三完整性true；132 run-001因评分公式循环诊断停止，无正式分 |
| ZIP关联评分阶段提示 | `codex/split-zip-grading-stage-20261111` / `36925d5` | 20 PASS | 132 run-002运行中；仅提示比较来源字母常量、数字标记、分号，禁止自引用评分格，未自动生成答案/公式 |
| OS | `codex/split-os-settings-20261111` / `cbd9f25` | 21 PASS；组合入口删除，单key修改无额外副作用 | 待复跑133/140 |
| VS Code | `codex/split-vscode-20261111` / `bbf10c6` | 34 PASS；20个单设置动作，四旧入口拒绝，指令只选相关设置 | 待正式复跑 |
| VLC | `codex/split-vlc-20261111` | 16 PASS；8个单偏好动作，两个旧入口拒绝 | 待正式复跑 |
| Chrome | `codex/split-chrome-20261111` / `d645082` | 11 PASS；8个单设置动作，旧入口拒绝 | 待正式复跑 |
| GIMP | `codex/split-gimp-20261111` / `2b9295f` | 5 PASS；会话、三个单效果、独立保存和GUI打开 | 待原生执行及正式题目验收；单测不能证明GIMP真实效果 |

GIMP具体契约落为 `image.open_session(path)` → `image.set_brightness/set_contrast/set_saturation(image_id,value)` → `image.save_session(image_id,output_path)`；独立只读 `image.inspect_session(image_id)`，独立GUI `image.open_session_gui(image_id)`。模型选择每张图、效果、值、输出位置和调用顺序。内部不可变XCF修订仅持久化编辑状态，效果接口不接收输出路径、不导出、不打开GUI。新效果值以亮度/对比度整数（避免旧浮点静默截断）、饱和度数值公开。原文件与非目标效果保持；校验失败不推进会话指针。

Chrome保存设置仍需要暂时停止并恢复正在运行的Chrome以避免配置被浏览器覆盖，这是已有配置持久化机制，不是额外修改偏好；单设置接口未增加重启参数。原子契约按独立用户意图划分，相关底层字段仍由同一语义实现负责。

另有2项Writer宏测试在候选与未修改主分支完全同现（`document.deduplicate_records`遗留），未混记为本次新增故障，也不在本次范围顺手扩改。所有组均通过源码导入检查；文档中PASS仅指明确列出的原题正式评分，其他PASS指对应定向检查。
