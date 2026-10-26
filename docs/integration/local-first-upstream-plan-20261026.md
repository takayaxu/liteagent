# 以本地源码为底座的增量集成方案

方案版本：LOCAL-FIRST-002，已由用户在 2026-10-26 授权实施为 v4，并明确要求 12 并发全量一次。下文原方案中的“仅制定方案”、逐题审批和不启动全量限制，由这条最新授权替代；能力边界、排除项和原始评分条件保留。执行范围见 [v4 回执](v4-20261026.md)。

## 目标与固定版本

保留本地已实现、已验证的修复，从 `qwq-code/liteagent` 吸收本地确实缺少的能力。验收目标是在相同模型和预算下让仍失败的题目获得正式 OSWorld PASS，而不是让两边文件相同。

- 本地活动分支：`codex/api-split-liuxv`，本次读取的最新提交 `1d3df6397d4847619240e9f46dab6731b8f1e666`。相较上一份比较中的 `315d460`，新增提交仅更新修复台账，运行源码未变。
- 上游来源：[`qwq-code/liteagent@990f019`](https://github.com/qwq-code/liteagent/tree/990f019de25313cc98f504e16ac8cd4c21ed75e2)。本方案按这个固定提交检查，不自动跟随上游后续变化。
- 运行包：双方均为 `src/adapter_versions/v2_expanded/`。已核对上游源码快照与固定 Git 提交的文件内容一致。
- 固定条件：沿用本地昇腾 Qwen3.5-9B thinking、100 步、1800 秒和原始 evaluator，不通过更换模型或放宽检查获取 PASS。

先前比较发现核心 Python 有 89 个共有文件内容不同、11 个本地独有模块和 13 个上游独有模块。本方案进一步检查了 Adapter 的动作注册、schema、实现及模块接入点；“对方有同名文件、本地没有”不直接等于功能缺口。

## 一、明确保留的本地底座

以下模块及其调用关系保留，不用上游文件整体覆盖：

- Calc 公式来源、百分比、透视表定位与原生结果检查：`calc_formula_contract.py`、`calc_percentage_outcomes.py`、`calc_pivot_layout.py`、`qwen_pivot_schema.py` 及本地 `completion_outcomes.py`。
- 完成审查、读后审查、文件组织账本和当前单题修复成果，包括本地 `completion_review.py`、`read_audit_gate.py`、`organization_validation.py`、`pdf_table_selection.py`。
- 模型客户端中的流式聚合、硬截止时间、重复推理恢复、transport trace、空参数 grammar 处理和原始参数校验。
- 本地已拆分的 Thunderbird 单设置接口、`workbook.save_as`、必要的 vendor 资源与已有部署入口。
- 原始 OSWorld、任务定义、golden、评测结果及共享环境。其他进程的候选修复不自动并入本方案。

允许修改这些文件的**局部接入点**以增加能力；不删除上述支持，也不引入第二套互相矛盾的状态或完成判定流程。

## 二、优先吸收的真实缺口

下表的题号只用于选择验证样本，不写入运行时代码，也不代表已经证明这些题目的最新失败都由相应缺口造成。实施前仍按 `repair_skill.md` 读最新轨迹，必要时无补丁复跑；本地已通过就不为该题添加补丁。

| 批次 | 本地缺口与拟吸收能力 | 上游来源及本地接入 | 验证方向与边界 |
| --- | --- | --- | --- |
| A1 | Writer 创建一个空白文档：`document.create` | Writer `schema.py`、`tool_manifest.py`、`uno_worker.py` 中该动作的最小实现；接入本地工具目录与发现 | 113/114/115 等跨应用写入；创建后由模型另行写内容、保存；拒绝覆盖已有文件，不接入复合文档生成流程 |
| A2 | Writer 按模型选择的分隔符和字段稳定去重：`document.deduplicate_records` | 新增 `paragraph_dedup.py`，同步接入 Writer schema、worker 和公开工具 | 74 等按字段去重；保留首次记录、原有顺序、其他字段与空段落，错误在 mutation 前发现；核验段落边界及保存后结果 |
| A3 | Thunderbird 对明确选中邮件设置同一种标志：`messages.update_flags` | 移植该动作的 schema、manifest、actions/worker、原生回读与返回字段 | 155 等邮件加星；模型先查询并选择 folder/mailbox_indices；不替模型搜索邮件，不恢复本地已退役的 `mail.configure` |
| A4 | VLC 对一个完整视频翻转并导出：`media.flip_video` | 移植参数与单操作实现、worker dispatch、媒体校验，保留已有转码/截帧能力 | 166；输入、输出、翻转轴都由模型选择；验证生成媒体，而不是只看命令成功；不自动选择视频或附加剪辑 |
| B1 | Writer 无损追加一个文本文件：`document.append_text_file`；按匹配位置格式化：`text.set_format_in_match` | 只吸收这两个动作的实现和参数契约，保持每次一个源文件或一个匹配区域 | 减少长文本由模型重抄、逐段找偏移的错误；不自动遍历多个文件、决定顺序、生成内容或保存 |
| B2 | 从明确指定的已保存 Writer 文件导出 PDF：`document.export_file_pdf` | 增加私有文件快照导出路径；保留本地现有 `document.export_pdf` | 文件导出时不切换或关闭用户正在编辑的文档；对未保存内容明确区分，不把已有“当前文档导出”当成缺失能力 |
| C1 | 固定路由的参数平铺：`atomic_tool_surface.py` | 只在本地 `model_client.py` 的发送/返回边界接入 `atomic_provider_surface` 和 `restore_adapter_arguments` | 用当前失败请求证明多层包装问题后实施；保留流式、deadline、reasoning、trace、pivot schema 和 grammar；先校验平铺参数，再恢复原始调用并执行原始 schema/路由校验 |
| D1 | guest 离线准备剪贴板与 OCR、安装事务超时与恢复 | `clipboard_dependency.py`、`desktop_dependencies.py`、`package_install.py` 和安装脚本/健康检查/部署轮询的必要片段 | 110、OCR 相关题目的环境准备；只操作本轮独占 guest，先验证资源来源及哈希，不能在正式推理阶段临时安装依赖 |

执行顺序建议为 **A1 → A2 → A3 → A4 → B → C**，一次只实施一个可独立验证的能力。D1 若已被最新环境失败证据确认阻塞，则先解决该准备阶段问题；否则不为集成主动重置共享 guest。每个批次可拆为多个单题闭环，不能一次把表中所有动作塞入候选后再评测。

### D1 需要先补齐的交付条件

上游安装逻辑引用 `vendor/clipboard/*.deb`、`vendor/ocr/` 及校验清单，但该 GitHub 提交未携带 `os_adapter/vendor/`。因此这三个 Python 文件不是可直接拷贝即用的部署补丁。

实施前需确定包来源、guest 架构与版本、完整依赖、哈希和离线投递方式，核对本地已有 wheel。包安装总预算须与 setup timeout 以及宿主控制接口限制一致；保留对本轮安装子进程的局部终止及 dpkg 状态诊断，不清锁或杀其他进程。不能为补齐这个缺口删除本地已有 PDF 依赖。

## 三、只吸收补充部分，不当作全新能力

| 项目 | 本地已有内容 | 拟吸收的差额与限制 |
| --- | --- | --- |
| GIMP 导出 | `image.export` 已在本地 schema/worker 注册 | 上游有更明确的 `input_path/output_path/loader/quality` manifest。核对本地工具投影后，仅修正缺失说明或契约不一致，不重复实现导出 |
| VLC 本地发现 | 已可通过 OS `filesystem.find` 找媒体 | 上游 `playback.find_local` 仅在 VLC 作用域缺少可达发现工具时接入；不能自动选择文件并播放，不为同一能力平添强制步骤 |
| Impress 几何动作 | 已有 `shape.set_geometry` | `shape.move/resize/align_to_slide` 属于更窄的参数面，不是完整新能力；只有最新轨迹证明参数面是障碍时，复用本地 geometry 校验与实现增加必要入口 |
| ZIP 创建和解压 | 已有 `archive.create_extract` | 可按需借鉴 `archive.create_zip/extract_zip` 的单操作参数面；保持兼容，复用已有底层实现，不计为新增文件处理能力 |
| 零结果搜索生命周期 | 已有发现、搜索与停滞处理 | 借鉴上游 `local_file_discovery.py` 的“状态发生变化后允许重新搜索”与 `request_blocks` 失效逻辑；只失效陈旧观察，不把临时无匹配当成永久禁止，也不放开无限重试 |
| VS Code 对话框识别与文件创建发现 | 已有 accessibility 状态和编辑器动作 | 吸收 `_visible_dialogs` 等独立可达性改进以及新建文件的发现接入；不覆盖本地整个 VS Code Adapter 或运行状态层 |
| Calc 参数检查 | 已有矩阵几何与公式契约检查 | `argument_handoff.py` 的矩阵部分先去重；邮件选择器部分若本地确无对应反馈再接入。错误只指明矛盾，不推断或改写模型参数 |
| Calc 观察检查 | 已有原生结果和完成审查 | `calc_observation_checks.py` 仅补充空计算列、图表类别轴等尚未覆盖的事实检查；与现有检查合并去重，修改后旧观察必须失效 |
| 批量覆盖和输出文件证据 | 已有保存、完成审查和组织账本 | `batch_progress.py`、`output_artifact_semantics.py` 只补充缺项证据；先统一 `effective_canonical_action`、回执及 `_issue` 结构，不另建一套完成门 |
| 图片重命名后的身份追踪 | 已有发现与文件组织状态 | 可吸收 `visual_file_identity.py` 的路径迁移/身份失效规则；只提供事实状态，不由辅助代码决定“下一张必须操作什么” |

## 四、本轮不直接接入的上游逻辑

1. **不引入 `positive_find_handoff.py` 的整套流程。** 它按压缩/移动/修改时间的指令形态识别工作流，并会移除 `filesystem.find` 与 `tools_search`；与“不定制 API 流、不封闭模型调查路径”的本地要求存在冲突。若需要文件清单证据，只抽取可复用的事实处理函数，方案另审。
2. **不直接引入 `structural_observation_recovery.py` 的终态工具收缩。** 它在特定重复观察后会把工具收缩为搜索、完成、失败。先保留本地已修复的调查与修复工具可达性；可借鉴重复观察检测，不复制该策略。
3. **不整套接入 `bounded_recovery.py`。** 本地已有停滞、软重启和重复推理恢复。只在有新证据时借鉴具体的同目标/同参数/同结果判定，防止两套恢复逻辑互相屏蔽工具。
4. **不恢复 `mail.configure`、`preferences.update` 等已被本地拆分的宽入口。** `mail.identities.list` 与本地 `identities.query` 先做语义对照；不因对方有这个名字就新增重复接口。
5. **不直接引入 `presentation.create_summary_slide`。** 上游代码手工创建标题和正文形状，并不是调用 Impress 原生 Summary Slide 功能。不能把它当成题目要求的原生功能；其中样式与布局选择也不由模型提供。
6. **不直接引入 `slides.create_from_images` 的复合流程。** 它可创建多页、插图并替换原有页面，包含多个效果；本地已有创建页和插图原语。先保留模型自主组合，不为特定题新增宏流程。
7. **不整体替换 `model_client.py`、`state_model.py`、`tool_surface.py`、`execution_engine.py`、`completion_outcomes.py`。** 上游服务适配和本地状态字段不同，只允许按上述能力做局部、可追溯的移植。

这些排除项不能以“对方曾通过更多题”为理由自动恢复；上游历史分数不证明对应实现适合本地约束。

## 五、13 个上游独有模块的去向

| 独有模块 | 处理决定 |
| --- | --- |
| `atomic_tool_surface.py` | C1：增加无损接口投影，保留本地执行契约 |
| `paragraph_dedup.py` | A2：增加字段稳定去重能力 |
| `clipboard_dependency.py`、`desktop_dependencies.py`、`package_install.py` | D1：依赖资产与安装条件补齐后移植 |
| `argument_handoff.py` | 去重 Calc 部分，按证据补充邮件参数反馈 |
| `batch_progress.py` | 仅补充本地缺少的批量证据核对 |
| `calc_observation_checks.py` | 仅补充本地缺少的原生观察检查 |
| `output_artifact_semantics.py` | 合入现有完成审查，不新增并行完成门 |
| `visual_file_identity.py` | 借鉴身份追踪，不引入固定操作顺序 |
| `bounded_recovery.py` | 不整套接入，保留本地恢复机制 |
| `structural_observation_recovery.py` | 不接入工具收缩，只按需要复用观察检测 |
| `positive_find_handoff.py` | 暂不接入按指令形态封闭工具的流程 |

## 六、实施、验证和交付方式

1. **审核的是具体单项移植。** 总方案通过后，每项仍需给出最新失败轨迹、拟改函数、依赖和普遍性说明，按 `repair_skill.md` 选择人工或独立子 agent 审核。当前请求仅制定方案，不默认为已授权关闭人工审核。
2. **每项独立工作树。** 从实施时活动分支最新 HEAD 创建 `codex/integrate-<capability>-<unique-id>`；不要把本方案固定 SHA 当作未来永远最新的基点。不得覆盖其他进行中的单题候选或修改其台账条目。
3. **按能力移植而非拷贝文件。** 同步增量更新公开 schema、参数校验、实现、dispatch、verification、context_hint、工具发现及必要的 completion 元数据。本地多应用转发与原生调用应遵守同一契约。
4. **最小定向检查。** 优先复用上游对应能力的既有测试，补充本地接入所需的最小契约覆盖；运行改动 Python 的 Ruff、`git diff --check`、`bin/check.sh`。不整套复制对方 58 个新增测试或启动通用全量回归。
5. **先提交，再复跑。** 从个人候选提交创建干净的运行工作树，保留源码 seal、配置、模型身份、原始轨迹和原始 evaluator 结果。共享 guest 使用统一绝对路径锁，已占用则等待。
6. **同题正式通过后才接纳。** 不把接口探针成功或单元测试通过记为整题 PASS；失败回到最新轨迹和审核节点。模型无补丁已通过的题目只更新台账，不制造补丁。
7. **集成时不覆盖并行成果。** 组合到活动最新提交后，若运行源码或条件改变，重新验证当前题。通过后串行合入、维护 `repair_skill.md` 已修复表并正常推送 GitHub；不强推。

推荐的第一项是 **A1：Writer `document.create`**：本地确无该动作，上游边界为“新建一个空白文件”，依赖和参数面较小，适合先验证跨应用接入。候选题从 113/114/115 中选择一个未被其他进程认领、且最新轨迹确实受创建能力影响的任务；若证据不支持，则换另一个有证据支持的能力，不强行把该题改造成这条 API 路径。

## 七、成果如何计量

- 每个已接纳批次记录：上游来源、移植函数/契约、本地补丁提交、候选正式 PASS、集成提交、条件与证据。
- 运行源码保持本地修复的连续性；本地独有模块和窄接口不因上游缺少而被删去。
- 分别记录新增正式通过、无补丁复跑通过、仍失败及受环境阻塞的题目。新增接口数和新增文件数都不是通过题数。
- 对方 `124/189` 来自其独立版本与条件，不与本地 16 道孤立 PASS 拼接。集成后的全量通过率只能由同一冻结提交的一次完整评测给出；本方案不自动授权全量评测。

## 审核结论栏

待审核：是否认可“保留本地底座、按真实缺口逐项吸收、正式单题 PASS 后合入”的范围与顺序。任何新增宏 API、模型服务变更、恢复旧宽接口或取消本地检查，都不属于本方案。
