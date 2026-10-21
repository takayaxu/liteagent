# 本地项目结构盘点（2026-10-21）

## 当前使用的目录

|路径（相对 `/home/liuxv/liteagent`）|用途|
|---|---|
|`src/adapter_versions/v2_expanded/`|当前运行源码，已恢复冻结 v3；目录名是历史名称|
|`configs/single-task-v3-thinking.json`|统一单题配置|
|`configs/current-single-task.json`|最近准备的任务与快照身份|
|`bin/prepare-single.py`|从当前源码准备独立快照，默认不启动测试|
|`bin/run-liteagent.sh`|运行入口，由快照命令调用|
|`src/third_party/OSWorld/`|原始评测器与共享资源|
|`src/adapter_versions/v2_expanded/docs/`|历史分析和修复证据，按日期阅读|

运行源码与冻结 v3 完全一致：562 文件、82,214,256 字节；原始提交
`da003732c6836e86bc2c4a3df5100c3d11ea1782`，摘要
`8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b`。
还原了 47 个改动文件，67 个新增运行文件已移入备份。Git 工作区仍保留历史文档等非运行修改；未执行 reset/clean。

## 冗余与体积

以下为本次整理前的磁盘实占，GiB 按 1024³ 字节计算；不同目录的硬链接空间不能直接相加。

|位置|大小|处理|
|---|---:|---|
|主项目|49.77 GiB|历史实验移出后约 23.39 GiB|
|主项目内 `experiments/`|26.39 GiB|529 条历史实验归档，原路径保留链接；已跟踪 configs 保留|
|OSWorld `docker_vm_data/`|22.78 GiB|共享镜像，保留|
|`/home/liuxv/liteagent-reproduction-jobs/`|24.73 GiB|独立快照和原始轨迹，保留|
|`/home/liuxv/liteagent-repair-workspaces/`|3.09 GiB|26 个旧开发副本，保留作参考|
|`/home/liuxv/liteagent-probes/`|0.10 GiB|历史最小探针，保留|
|冻结来源 `liteagent-fixed189-20261014-v1/`|5.97 GiB|基线证据，保持不变|

盘点时 114 份源码压缩快照合计 8.76 GiB，其中 20 组包含相同源码、共 35 份重复快照；另有 20 个仅准备、未启动的 job。这些是后续去重候选，**本次未删除**。相同源码不意味着模型请求、产物、评分等实验记录相同。盘点后新准备的 job 不计入这些历史统计。

镜像 `src/third_party/OSWorld/docker_vm_data/Ubuntu.qcow2` 与
`/var/lib/liteagent-shared/Ubuntu.qcow2` 指向同一 inode，并非两份独立大文件。
旧目录中的兼容符号链接也不另占一份内容。缓存已归档。实验归档属于移动，**没有释放整机磁盘空间**。

## 备份与历史证据

统一归档根：`/home/liuxv/liteagent-analysis/project-reorganization-20261021/`。

|归档内路径|内容|
|---|---|
|`runtime-before/`|回滚前运行源码，包含旧修复与新增文件|
|`legacy-experiments/`|移出主树的历史实验，旧路径通过链接继续可访问|
|`nested-history/`|原误嵌套到源码下的历史目录|
|`generated-caches/`|移出的生成缓存|
|`previous-management-entrypoints/`|统一入口前的旧脚本和进度记录|
|`inventory-before.json`|体积、重复源码组和未启动 job 清单|
|`restoration.json`|逐项恢复与归档清单|
|`git-diff-before.patch`|回滚前 Git 差异；另保留状态和源码 manifest|

旧修复 workspaces 不再作为新入口。087–108 批次的 `launch.py`、`configure_frozen_v3.py` 已委托主目录准备脚本；默认只准备，显式 `--run` 才启动。
其他对话使用的 `/home/liuxv/liteagent1021` 及其他用户的批次保持原状。

## 下一轮配置

Qwen3.5-9B，thinking，全局、初始、局部均 100 步，单题 Agent 时间预算 1800 秒；保留 8 步无进展停止和 1 次软重启。局部从 25 改为 100，是为了避免在全局预算用完前被两段局部 25 步上限提前终止；100 步仍是上限，并非保证走满。

每次从主目录准备新快照，冻结后运行；已启动快照不可原地修改。仍用原始 OSWorld evaluator 和 fresh VM，不继承上次 VM 状态。当前 88 仅准备了快照，未启动新测试。旧条件下的 PASS 不视为新条件下的 PASS。
