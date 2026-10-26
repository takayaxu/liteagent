# 项目结构与集成目录

更新日期：2026-10-26。用户指定 v4 为主活动源码；保持现有模块、包入口、Docker 和部署路径。2026-10-21 的集成材料作为历史记录保留。

## 开发目录

当前主活动目录为 `/home/liuxv/liteagent`，开发分支为 `codex/v4`。
运行源码提交 `a65c4ab44f29926a6070483006065fb1f0a08e3d`，标签 `v4`；后续修复从该分支最新提交建立独立工作树。
原 `codex/api-split-liuxv` 和 `026e829` 基线保留为历史记录。

```text
/home/liuxv/liteagent/
├── README.md                         # 启动说明与入口索引
├── MERGE_REVIEW.md                   # 原合并意见及本次整理回执
├── API_SPLIT_TASK.md / task.md       # 历史开发任务与记录
├── SOURCE_INFO.md                   # 最初导入信息
├── bin/                             # 本机检查、启动脚本
├── docker/                          # 已有共享 guest 配置
├── docs/
│   ├── api-granularity-audit-20260920.md
│   ├── integration/api-split-20261021/ # 可从 GitHub 获取的补丁、清单和检查记录
│   └── project-structure.md          # 本文件
└── src/
    ├── adapter_versions/v2_expanded/
    │   ├── integrations/            # Agent 与工具编排
    │   ├── *_adapter/               # 各应用 Adapter
    │   ├── scripts/                 # 运行器与公共辅助脚本
    │   ├── tests/                   # 已有测试
    │   ├── deployment/              # 已有部署文件
    │   ├── assets/                  # 源码自带静态资源
    │   ├── docs/                    # 历史开发文档；不纳入集成增量
    │   └── experiments/             # 历史实验配置；不纳入集成增量
    └── third_party/OSWorld/          # pinned 上游；不纳入集成增量
```

运行结果和完整源码快照继续使用 `/home/liuxv/liteagent-local-runs/`、`/home/liuxv/liteagent-reproduction-jobs/` 等仓库外目录。`OSWorld/cache/`、`OSWorld/docker_vm_data/` 是本机被忽略的资源目录，继续使用已有路径。

## 源码身份

当前 v4 运行范围为 614 个文件，SHA-256：

```text
e8cabb760b51c6aa5c1f8a56e5f3ba1d05106f9f64846deeba7ed3f64c8b0886
```

12 并发全量完成 138/189 PASS（73.02%），最终完整性通过。
详见 [v4 集成回执](integration/v4-20261026.md) 和 [全量结果摘要](integration/v4-full189-result-20261026.json)。

下文为 2026-10-21 历史整理记录。历史 v3 的运行范围为 562 个文件，SHA-256：

```text
8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b
```

本次整理没有更改这些运行源码。原意见中的 53 个未提交源码/测试文件已全部保存于 `026e829`，并全部纳入集成候选；当前恢复的 `MERGE_REVIEW.md` 和 `bin/run-osworld.py` 不属于这 53 个文件，未纳入集成候选。

## 集成候选与交付材料

| 用途 | 位置 |
| --- | --- |
| 独立集成工作树 | `/home/liuxv/liteagent-integration-worktrees/api-split-20261021/` |
| 集成分支 | `codex/integration-api-split-20261021` |
| 最初导入基线 | `b800fd9c8861528bc5dc0c204c88a84163835769` |
| 集成候选提交 | `1bcf371`；完整 SHA 记录在交付目录的 `scope-manifest.json` |
| 补丁、清单与检查日志 | `/home/liuxv/liteagent-integration-deliveries/api-split-20261021/` |
| GitHub 可获取的交付副本 | [integration/api-split-20261021/](integration/api-split-20261021/README.md)，保存在开发分支 |

集成候选直接从最初导入基线创建，仅纳入 74 个修改文件和 17 个新增文件，均为源码或测试。保留原开发分支历史，不把包含 evaluator 改动的历史提交直接合并到主仓库。

交付目录包含 `api-split.patch`（完整二进制补丁）、`name-status.tsv`、`scope-manifest.json`、`README.md` 和检查日志。开发分支保存一份文档交付副本供 GitHub 查看，独立集成分支仍只有源码/测试增量。补丁排除历史文档、实验配置/结果、缓存、本机启动器及所有 `1142019` 相关路径，包括生成参考表的脚本和两项 OSWorld 数据改动。外部绝对软链接 `src/adapter_versions/v2_expanded/src` 当前不存在，也不在补丁中。导入基线已有的相对链接 `third_party -> ../../third_party` 保持不变。

主仓库使用 `adapter_versions/`，本仓库使用 `src/adapter_versions/`，补丁应用时去掉一层 `src/`，不要据此搬动本仓库的源码：

```bash
cd /absolute/path/to/main-repository
git apply --check -p2 /home/liuxv/liteagent-integration-deliveries/api-split-20261021/api-split.patch
git apply -p2 /home/liuxv/liteagent-integration-deliveries/api-split-20261021/api-split.patch
```

`-p2` 还会去掉 Git diff 自带的 `a/` 或 `b/` 前缀。补丁已在模拟主仓库布局中校验并实际应用，91 项结果与候选源码一致；这不代表已在真实主仓库完成集成或兼容性验收。

## 检查结果

- `git diff --check` 通过；91 个变更 Python 文件的 Ruff 通过。
- 13 个相关测试模块：171 通过、8 失败。
- 同一组 8 项失败在原开发工作区全部复现，属于本次整理前已有失败，未改写源码或测试来规避。
- 集成增量不含 OSWorld/evaluator、任务/参考数据和绝对软链接。

候选已经保存为独立提交；8 项既有失败仍需后续处理，不能将本次整理称为正式验收通过。具体节点与原始输出见交付目录中的 `focused-tests.log`、`existing-failure-comparison.json`。
