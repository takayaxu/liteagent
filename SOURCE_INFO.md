# 当前运行源码身份

2026-10-21 恢复到原始冻结 v3，作为新单题修复起点。

- 当前运行源码：`/home/liuxv/liteagent/src/adapter_versions/v2_expanded`
- 原始冻结来源：`/home/liuxv/liteagent-fixed189-20261014-v1/adapter_versions/v2_expanded`
- 原始提交：`da003732c6836e86bc2c4a3df5100c3d11ea1782`
- 源码封存范围：14 个 Agent/Adapter/测试/部署目录，562 文件。
- SHA-256：`8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b`
- 当前单题配置：`configs/single-task-v3-thinking.json`

恢复的是运行文件；Git 工作区保留历史文档和未提交的非运行修改，因此不使用 `git reset --hard`。根目录的主机准备脚本、配置和说明是本次新增管理入口，不属于原始 v3 运行封存范围。

恢复清单、旧 Git 差异、旧运行源码、旧 README 和原始交付身份均保存在：
`/home/liuxv/liteagent-analysis/project-reorganization-20261021/`。
