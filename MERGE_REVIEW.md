# 合并前修改意见

更新日期：2026-10-21

> 整理回执（2026-10-21）：以下意见保留原文，其中 `HEAD=e1ef6ad` 和“53 个未提交源码变化”是整理前状态。当前开发基线为 `026e829`，53 个文件已全部提交；本次按要求创建独立集成候选 `codex/integration-api-split-20261021`，提交 `1bcf371`。相对最初导入基线纳入 74 修改、17 新增，完整排除 `1142019` 的三个路径及文档、实验产物和外部绝对链接。目录与交付索引见 [项目结构与集成目录](docs/project-structure.md)。Ruff、diff 检查通过；相关测试 171 通过、8 失败，8 项均在原开发源码复现，未宣称正式验收通过。

## 范围

本文只评估项目结构和后续合并可行性，不是正式交付验收。当前不要求全量回归，不得新增、扩大或强化门禁，也不要为了合并再次重构目录。

## 当前结论

- `src/adapter_versions/v2_expanded/` 内部没有大规模搬迁：相对当前共同内容基线，有 74 个已有源码或测试文件修改、18 个新增文件，未发现删除或重命名。
- 与主仓库有 55 个同文件并行修改；本次文本三方合并模拟未发现行级冲突，但集成后仍需检查语义兼容性。
- 本仓库与主仓库没有可直接使用的共同 Git 历史，而且本仓库源码位于 `src/adapter_versions/...`，主仓库源码位于 `adapter_versions/...`。不要直接执行普通 `git merge`。
- 当前分支 HEAD `e1ef6ad` 之外仍有 53 个未提交的源码或测试变化（47 个修改、6 个新增）。只交付或合并该 HEAD 会漏掉修改。
- `src/adapter_versions/v2_expanded/src` 是指向 `/home/liuxv/liteagent-analysis/...` 的外部绝对软链接，不能进入补丁、压缩包或主仓库。
- 提交 `1142019` 修改了 pinned OSWorld evaluator/任务数据，不能进入集成结果。

## 必须整理

1. 保留现有开发分支和历史，不重写历史；新建一个专门的 integration 分支或干净 worktree。
2. 逐项确认上述 53 个未提交源码/测试变化，只把确实属于本次 API 拆分和修复的内容整理成提交。不要批量提交整个工作区。
3. 集成提交只包含需要合并的源码、测试和确有必要的部署文件。排除 `docs/experiments/`、实验结果、缓存、临时文件和批量运行产物。
4. 完全排除 pinned `third_party/OSWorld`、evaluator、任务 JSON、golden 数据以及提交 `1142019` 带来的相关变更。不要删除历史证据，只是不把它们放入集成提交。
5. 排除外部绝对软链接 `src/adapter_versions/v2_expanded/src`。
6. 保持现有 `v2_expanded` 内部目录和包入口，不移动模块，不调整依赖、Docker 或部署结构来“方便合并”。
7. 可以保留本仓库的外层 `src/`。生成补丁时说明主仓库应用补丁需要剥离该前缀；不要因此重排本仓库。

## 需要提供的集成材料

- 最终 integration commit SHA。
- 相对最初导入基线的 `git diff --name-status`。
- 包含二进制变化的完整 patch，例如 `git diff --binary` 产物。
- 一份简短清单，明确哪些未提交文件被纳入、哪些文件因实验产物、外部链接或 evaluator 修改而被排除。

## 最小检查

- 运行 `git diff --check`。
- 对改动的 Python 文件运行 Ruff。
- 只运行已有的相关 focused tests；不要求全量测试，不新增任何门禁或测试框架。
- 确认 integration worktree 中没有意外的 OSWorld/evaluator 变化和外部绝对软链接。

完成以上整理后即可进入独立 integration worktree 合并，不需要重新设计项目结构。
