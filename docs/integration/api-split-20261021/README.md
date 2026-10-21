# API 修复集成材料（2026-10-21）

开发分支：codex/api-split-liuxv；开发源码提交：026e829e7626d1a0880e5fb365de219039df577c。
最初导入基线：b800fd9c8861528bc5dc0c204c88a84163835769。
独立集成分支：codex/integration-api-split-20261021。
最终 integration commit SHA：1bcf3718d1b8ec65c31c792ef29c8d65fe303745。
工作树：/home/liuxv/liteagent-integration-worktrees/api-split-20261021。

本目录是保存在开发分支的交付副本，可从 GitHub 获取。独立集成分支只保存源码/测试增量；本机原始交付目录仍在 /home/liuxv/liteagent-integration-deliveries/api-split-20261021/。
本文绝对路径用于本机定位，在其他机器使用下载后的补丁路径。

## 文件

- api-split.patch：相对最初导入基线的 git diff --binary --full-index；仅源码/测试。
- name-status.tsv：同一范围的 git diff --name-status。
- scope-manifest.json：所有纳入与排除文件、原因及完整版本身份；包含原 53 项源码清单。
- verification.json：检查汇总。
- ruff.json / ruff-summary.json：91 个 Python 文件 Ruff，0 个诊断。
- focused-tests.log / focused-command.json：13 个相关测试模块，171 passed、8 failed。
- existing-failure-comparison.json / development-existing-failures.log：相同 8 项在开发源码复现。
- structural-checks.json / diff-check.log：边界、软链接和补丁路径映射检查。
- source-before.json：整理前开发运行源码 seal 及逐文件哈希。

## 纳入与排除

纳入 74 个修改文件和 17 个新增文件。原意见提及的 53 项未提交源码已在 026e829 提交，本候选全部包含；还有 38 项此前已提交的源码/测试增量。

全部排除 docs、experiments、实验结果、缓存和本机配置。保留开发树中用户恢复的 MERGE_REVIEW.md、bin/run-osworld.py，不把它们装进补丁。

1142019 的三个路径全部排除：生成 Order 107 参考表脚本、OSWorld evaluator 参考表 xlsx、任务 JSON。集成增量未更改 pinned OSWorld；开发分支的历史证据保持原位。集成历史从 b800fd9 派生，不包含 1142019 提交。

src/adapter_versions/v2_expanded/src 外部绝对链接当前不存在，未纳入。基线已有的相对 third_party 链接保持原样。

## 主仓库应用

保留本地 src/ 布局；在主仓库剥离该前缀，先预检查再应用：

    git apply --check -p2 /absolute/path/api-split.patch
    git apply -p2 /absolute/path/api-split.patch

-p2 同时剥离 Git diff 的 a/或 b/ 与本地 src/。已在模拟主仓库布局校验并实际应用，91 个结果文件与候选逐字节匹配。

不要将开发历史直接 git merge 到主仓库。若真实主仓库有自己的并行修改，应按清单检查冲突与语义兼容性。

## 验证范围

Ruff、diff --check 通过。相关测试存在 8 项开发基线已有失败，节点和原始输出已保留。本次仅整理集成材料，未修复这些失败、未改运行源码、未运行 benchmark 或全量测试，不作为正式验收或新的通过率结论。

开发目录 562 文件运行 seal 始终为 8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b。
集成候选有意不含生成参考表脚本，因此它不是原 562 文件运行快照的完整替代品。
