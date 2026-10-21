# LiteAgent 本地 OSWorld 工作手册

更新日期：2026-10-21。本手册是当前本地单题配置、运行、日志和修复的统一入口。历史手册中的模型、步数和旧开发目录以本文件及当前配置为准。

## 1. 当前版本和运行条件

主项目：`/home/liuxv/liteagent`。运行源码已恢复到冻结 v3，后续在主目录修改，再生成独立快照复跑。`v2_expanded` 是历史目录名。

|项目|当前值|
|---|---|
|模型|Qwen3.5-9B|
|推理模式|thinking|
|全局 / 初始 / 局部步数上限|100 / 100 / 100|
|单题 Agent 时间预算|1800 秒|
|无进展停止 / 软重启|8 步 / 最多 1 次同 VM 软重启|
|模型请求超时 / 重试配置|240 秒 / 3|
|输出 tokens / temperature / top_k|8192 / 0 / 7|
|模型端点|`https://qwen.jinmaoapi.cc.cd/v1`|
|单题执行|本机 Docker fresh VM，使用原始 OSWorld evaluator|
|默认行为|只准备；运行必须另外执行 job 的 `run.sh`|

100 步是上限，仍可能因完成、无进展、模型异常或时间耗尽提前结束。1800 秒是 Agent 预算，排队、VM 启动、任务初始化和评测可能增加总耗时。

配置唯一入口：[configs/single-task-v3-thinking.json](/home/liuxv/liteagent/configs/single-task-v3-thinking.json)。准备时会把条件写进 job；修改主配置不会改变已经准备的 job，必须重新准备。

冻结 v3 身份：

- 原始提交：`da003732c6836e86bc2c4a3df5100c3d11ea1782`
- 运行封存范围：562 文件，82,214,256 字节。
- SHA-256：`8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b`
- 冻结来源：`/home/liuxv/liteagent-fixed189-20261014-v1/adapter_versions/v2_expanded`

这是本轮修复起点的身份；后续源码修改后以每次快照的实际摘要为准。Git 工作区保留历史文档和未提交修改，不能只用 Git HEAD 判断运行版本。

## 2. 本地目录

|绝对路径|用途|
|---|---|
|`/home/liuxv/liteagent/src/adapter_versions/v2_expanded/`|当前 Agent、Adapter、运行器和测试源码|
|`/home/liuxv/liteagent/bin/prepare-single.py`|统一单题准备入口|
|`/home/liuxv/liteagent/configs/current-single-task.json`|最近一次准备的题号、job 路径和源码身份；不是运行状态监控|
|`/home/liuxv/liteagent-reproduction-jobs/`|单题快照、日志、产物和评分|
|`/home/liuxv/liteagent/src/third_party/OSWorld/`|本机 OSWorld 和原始 evaluator|
|`/home/liuxv/liteagent/src/third_party/OSWorld/cache/`|共享任务资源缓存|
|`/var/lib/liteagent-shared/Ubuntu.qcow2`|共享 VM 基础镜像|
|`/var/lib/liteagent-shared/python-env/`|共享 Python 环境|
|`/home/liuxv/liteagent-analysis/project-reorganization-20261021/`|回滚前源码、历史实验与整理清单|

完整盘点见 [项目结构与重复内容](/home/liuxv/liteagent/docs/project-structure-20261021.md)。旧 repair-workspaces、probes 和 experiments 保留作证据，新尝试从主目录准备。镜像存在硬链接，不要当成多份大文件；不必向新 job 复制 VM 镜像或 Python 环境。

## 3. 开始前检查

下面检查不启动测试：

```bash
cd /home/liuxv/liteagent
./bin/check.sh
docker info >/dev/null
df -h /home/liuxv /var/lib/liteagent-shared
ps -eo pid,etime,args | rg 'run_lite_agent_pilot|supervise_lite_agent_parallel|host_driver.py'
```

`check.sh` 检查源码编译和关键导入，不代表 Docker、模型服务或题目一定可用。Docker 不可访问时先检查当前用户权限、daemon 和现有容器；不要直接重启 Docker 或停止其他批次。

单题修复共用 VM 锁：`/home/liuxv/liteagent-reproduction-jobs/v3-repair-vm.lock`。锁只协调使用该入口的运行；其他批次可能使用独立入口，启动前仍需查看现有进程。`/home/liuxv/liteagent1021` 等其他对话的批次不属于本轮清理范围。

## 4. 准备单题快照

例如准备 Order 88，替换题号即可：

```bash
cd /home/liuxv/liteagent
/var/lib/liteagent-shared/python-env/bin/python bin/prepare-single.py --order 88
```

先按第 9 节建立该题检查点；若已修改源码，先保存修复提交。准备入口要求管理范围内没有未提交修改，防止测试条件无法回到 Git 版本。

这一步只复制源码、生成配置和命令、校验完整性，**不会启动 VM**。末行输出新 job 的绝对路径；每次调用产生独立目录，并更新 `configs/current-single-task.json`。每个新 job 的 `repair-version.json` 记录 Git 提交和修复前检查点，外部版本台账同时记录 job 路径。

题号使用原始固定 189 题的 Order，不是应用内编号。任务指令与旧失败入口：

- [全部 189 题索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/v3-repair-20261017/all-189-index.md)
- [原始 83 道未通过题索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/v3-repair-20261017/failed-83-index.md)
- 任务卡：`/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/v3-repair-20261017/tasks/order-NNN.md`

任务索引是历史记录，不自动收录新尝试。统一准备脚本内部复用历史 preparation 工具；日常使用主目录 `bin/prepare-single.py`，以确保新配置进入命令。

## 5. 启动和查看单题

将上一步输出的绝对路径填入 `job_path`，再启动：

```bash
job_path=/home/liuxv/liteagent-reproduction-jobs/替换为刚准备的job目录名
bash "$job_path/run.sh"
```

`run.sh` 先等待共享 VM 锁，取得锁后校验源码、配置和命令，再运行本机 OSWorld 单题。已有 `runner.log` 的 job 会拒绝重复执行；复跑必须重新 prepare。等待锁时可能还没有 `runner.log`。

在另一个终端把 `job_path` 设为同一个目录，查看日志：

```bash
tail -f "$job_path/runner.log"
```

前台运行时，命令返回后查看结果和完整性：

```bash
cat "$job_path/run-status.json"
cat "$job_path/final-source-integrity.json"
/var/lib/liteagent-shared/python-env/bin/python -m json.tool "$job_path/results/results.json"
```

只校验准备快照、不运行 VM：

```bash
/var/lib/liteagent-shared/python-env/bin/python \
  /home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/v3-repair-20261017/prepare_single.py \
  --verify-job "$job_path"
```

运行使用本机资源缓存，准备记录中的 `HF_ENDPOINT` 默认为 `https://hf-mirror.com`。模型请求和 Hugging Face 资源下载是两条链路，本地运行仍可能需要网络。

## 6. 日志和证据位置

```text
/home/liuxv/liteagent-reproduction-jobs/<job>/
├── source/                         # 该次实际运行的源码
├── source-manifest.json             # 每个源码文件的摘要
├── source-snapshot.tar.gz           # 源码压缩备份
├── config.json                     # 单题配置
├── command.json                    # 实际启动参数
├── selected-profile.json           # 使用的统一配置副本
├── baseline-comparison.json        # 与冻结 v3 的运行摘要比较
├── repair-version.json             # 该次提交、分支和修复前检查点
├── preparation.json                # 题号、来源、资源镜像等准备信息
├── runner.log                      # 运行输出和异常
├── run-status.json                  # 主机驱动状态
├── initial-source-integrity.json    # 运行前校验
├── final-source-integrity.json      # 运行后校验
└── results/
    ├── results.json                # 最终任务状态、reward 和终止原因
    └── raw/run-1/<Order-domain-task_id>/
        ├── lite_agent_events.jsonl # 执行轨迹和工具结果
        ├── adapter_calls.jsonl     # Adapter 调用与返回
        ├── llm_call_log.jsonl      # 模型调用记录
        ├── llm_request_index.jsonl # 模型请求索引
        ├── llm_requests/           # 实际送给模型的消息和工具 schema
        └── model_audits.jsonl      # 模型审查记录
```

文件随运行阶段生成；初始化失败或中断时可能不完整。截图、评测附件和异常文件也在该次 `results/` 内，实际位置可用下面命令定位：

```bash
rg --files -uu "$job_path/results" | rg 'lite_agent_events|adapter_calls|llm_requests|model_audits|exception|trajectory_manifest|evaluator_artifacts|screenshot'
```

分析“为什么没有编辑、选错工具或生成错误参数”时，应定位到当步 `llm_requests/` 的真实消息、工具说明和 schema，并对照模型输出与 Adapter 返回，不能只看压缩后的轨迹摘要。

## 7. 单题修复流程

1. 阅读完整题意、原始失败与最新有效轨迹，找到首次偏离；区分环境、传输、协议、模型决策和工具实现问题。
2. 先验证根因，再在主目录做最小、可复用修改。阶段提示先从通用信息开始，失败后逐步收紧；不要加入题号、参考答案或整题固定操作序列。
3. 运行与改动相关的定向检查和 `./bin/check.sh`，不因单题修复自动启动全量。
4. 重新 prepare，检查该次 `config.json`、`command.json` 和源码摘要，再执行新 job 的 `run.sh`。
5. 等待真实终态，核对 evaluator 结果、保存后的实际产物和最后完整性记录。
6. 记录原因、改动文件、检查结果、job 目录、评分与剩余问题；失败和中断尝试也保留。

修改只发生在开发源码，已准备的快照保持不变；修复后重新生成。OSWorld evaluator、冻结来源、原始轨迹和历史成绩保持不变。旧补丁在备份中可查，按根因逐项决定是否重做，不整体恢复到新基线上。

## 8. 结果与异常怎么判断

|现象|检查与判定|
|---|---|
|prepare 成功但没有日志|可能尚未执行 `run.sh`，或正在等锁；不是任务失败|
|Docker 连接失败、VM 未启动|查看 `runner.log`、主机服务与权限，先作为环境问题定位|
|模型连接重置、超时|查看原始请求、重试和响应证据；不能仅凭错误名认定协议有问题|
|模型报完成或进程退出 0|仍须看原始 evaluator，不能直接记 PASS|
|没有 `results.json`|查 `runner.log`、`run-status.json` 和异常，不能自行填成 0 分|
|`runner_exited` 或完整性 `ok`|分别只说明进程返回、源码未变化，不等于任务通过|
|reward 为部分分数|按结果中的实际状态保留，不能记作二元通过|
|旧条件通过、新条件失败|分别保留，旧 PASS 不能替代本次结果|

原始 v3 全量为 106/189（56.08%），属于旧条件历史成绩。新配置下的单题通过只代表这一次尝试；达到 80% 以上须由后续统一版本的新 189 题全量证明，至少需要 152 题通过，不能拼接各题最佳结果。

## 9. Git 保存、检查点和回滚

修复分支：`codex/v3-thinking-repair-20261021`。
基线标签：`baseline/frozen-v3-thinking-100-1800-20261021`。
基线封存当前 v3 运行源码、新配置、运行入口和本手册。原分支与旧未提交文档仍保留。

每道题开始前，在源码尚未修改时保存检查点。例如 Order 88：

```bash
cd /home/liuxv/liteagent
python bin/repair-version.py checkpoint --order 88
```

它为当前提交创建唯一的 `checkpoint/order088/<时间>` 标签，记录本题修复起点。若源码已有修改，会要求先处理，避免把修改后的状态误记成修复前状态。

每个可独立验证的改动做一次提交，然后准备单题：

```bash
python bin/repair-version.py save --order 88 --message '填写本次修改的原因与行为'
python bin/prepare-single.py --order 88
```

`save` 只提交 [版本管理范围](/home/liuxv/liteagent/configs/repair-versioning.json) 中的源码、配置和入口，不会将其他历史文档或实验目录一并加入。已有暂存内容时会拒绝操作，防止混入其他工作。新增范围外的运行依赖时，先显式更新管理范围。先做定向检查，再保存提交；不要把多次无关修改合并成一个修复。

测试失败、需要撤销本次修改时，先从该 job 的 `repair-version.json` 取得 `commit`，填入下面命令：

```bash
python bin/repair-version.py rollback --order 88 --commit 填写失败版本的提交哈希
```

该操作使用 `git revert` 新建撤销提交，保留失败版本和历史；只允许撤销当前 HEAD 对应的本题修复提交，并要求源码干净。存在后续修改、多提交或跨题依赖时，先分析依赖，再逐项撤销，不能用 `reset --hard` 或 `clean` 批量清除。回滚不删除 job，也不改已经准备或运行的快照。回滚后若要测试，重新 prepare。

测试通过则保留该提交。下一题重新建立检查点，沿当前成功版本继续。版本台账位于：

```text
/home/liuxv/liteagent-analysis/repair-version-ledger/
```

台账逐条保存 checkpoint、save、prepare 和 rollback；prepare 记录包含具体 job 路径。评分仍以对应 job 原始结果为准，Git 提交不代表测试通过。当前任务指针 `configs/current-single-task.json` 不纳入提交，避免每次准备改变源码版本。

基线标签永久保留。整轮修复如需重新回到基线，应先保存当前工作，再建立新分支或工作目录；不要直接覆盖现有未提交文件。

## 10. 当前交接状态

2026-10-21：主目录已恢复冻结 v3，新配置及单题准备入口校验通过。第 88 题已准备新快照，尚未启动；修复任务保持暂停。本次编写手册没有启动测试。

- [最近准备记录](/home/liuxv/liteagent/configs/current-single-task.json)
- [源码身份说明](/home/liuxv/liteagent/SOURCE_INFO.md)
- [目录整理与归档清单](/home/liuxv/liteagent/docs/project-structure-20261021.md)
- [本轮恢复验证记录](/home/liuxv/liteagent-analysis/project-reorganization-20261021/validation.json)

历史手册 [v3 修复记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/v3-repair-handbook-20261017.md) 可用于查旧证据，其中旧预算、旧补丁状态和旧开发流程不代表当前配置。
