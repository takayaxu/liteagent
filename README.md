# LiteAgent 开发与集成工作区

当前主活动源码位于 `/home/liuxv/liteagent` 的 `codex/v4` 分支。v4 运行源码
提交为 `a65c4ab`（标签 `v4`），基于本地 `131a465` 增量集成上游通用能力。
12 并发、189 题全量已完成：**138/189 PASS（73.02%）**，最终完整性检查通过。
结果摘要见 [v4 全量回执](docs/integration/v4-full189-result-20261026.json)。
范围、检查和原始 evaluator 说明见 [v4 集成回执](docs/integration/v4-20261026.md)。

本仓库保留 LiteAgent 的运行源码、测试和历史开发记录。当前开发分支为
`codex/v4`；原 `codex/api-split-liuxv` 保留为历史开发分支。
冻结 v3 源码基线提交为 `026e829`。
冻结 v3 是历史基线；后续复跑默认使用当前开发分支最新的 Git 提交（启动时的
`HEAD`），不包含未提交、已暂存但未提交或未跟踪的源码改动。需要验证修复时，
先完成源码提交，再从该提交创建独立运行工作树。只有明确指定历史版本时，
才使用对应历史提交。
当前 v4 运行范围为 614 个文件，SHA-256：

```text
e8cabb760b51c6aa5c1f8a56e5f3ba1d05106f9f64846deeba7ed3f64c8b0886
```

历史冻结 v3 的运行范围为 562 个文件，SHA-256：

```text
8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b
```

源码与包入口保持 `src/adapter_versions/v2_expanded/`；`v2_expanded` 是历史目录名。
v4 集成范围和原始评分条件见上方回执。

独立集成分支 `codex/integration-api-split-20261021` 从最初导入基线 `b800fd9`
派生，候选提交为 `1bcf3718d1b8ec65c31c792ef29c8d65fe303745`。其增量仅含
74 个修改和 17 个新增源码/测试文件，排除了 OSWorld/evaluator、任务/参考数据、
文档和实验产物。需要继续修复时使用开发分支；需要向主仓库交付增量时使用
[集成材料](docs/integration/api-split-20261021/README.md)。

## 已部署的共享资源

本机只部署一份 OSWorld guest 容器，并由两个源码目录共同使用：

```text
容器：liteagent-shared-osworld
镜像：happysixd/osworld-docker:latest
磁盘：/var/lib/liteagent-shared/Ubuntu.qcow2（共享硬链接，不占第二份空间）
Python：/var/lib/liteagent-shared/python-env（两个账号共用）
```

每份源码在运行器要求的标准路径
`src/third_party/OSWorld/docker_vm_data/Ubuntu.qcow2` 也有一个硬链接；这些路径
与上述共享磁盘是同一个 inode，不会重复占用 24 GB。`bin/run-liteagent.sh`
默认使用这个标准路径，也可通过 `--qcow2` 显式覆盖。

Ubuntu 磁盘以只读方式挂载，两个用户目录不会各自复制一份 12/24 GB 镜像。
共享 guest 同一时间只应运行一个任务；需要并行任务时，应另外启动 guest，
但仍可复用同一个 Docker image 和同一份只读基盘。

共享 guest 的实际端口写在 `docker/shared-endpoints.env`。启动后先执行：

```bash
./bin/guest-status.sh
```

## 目录结构

```text
README.md                               开发、运行和集成入口
MERGE_REVIEW.md                          合并意见及整理回执
docs/project-structure.md                目录职责和本机工作树位置
docs/integration/api-split-20261021/      补丁、清单与检查记录
src/adapter_versions/v2_expanded/        LiteAgent、Adapter、运行器和测试
src/third_party/OSWorld/                 pinned OSWorld、任务和 evaluator
bin/check.sh                            编译与关键导入检查
bin/run-liteagent.sh                     通用单题运行入口
bin/guest-status.sh                      共享 guest 健康检查
docker/                                 已有 Docker 配置和端口
requirements-liteagent.txt              运行依赖
```

完整目录职责、冻结源码身份及集成材料位置见
[项目结构与集成目录](docs/project-structure.md)。源码和包入口保持现有路径；
集成候选工作树及补丁放在仓库外的独立目录。

## 当前开发任务

`liuxv` 的主活动工作分支是 `codex/v4`。以下 API 拆分文档保留为历史背景；后续修复从该分支最新提交建立独立工作树。先读
[大粒度 API 拆分任务](API_SPLIT_TASK.md)，完整的 216 项公开面复查、P0/P1
清单和源码证据在 [API 粒度审计](docs/api-granularity-audit-20260920.md)。
API 拆分任务做 Adapter 契约拆分和针对性测试；后续完成判定修复及指定单题复跑
按下列修复记录执行，不启动全量评测。

## 检查

```bash
cd /home/liuxv/liteagent
git status --short --branch
git diff --check
./bin/check.sh
```

源码检查只编译并检查关键导入，不会下载模型或启动任务；它不代表任务评分通过。
启动和检查脚本默认使用已部署的
`/var/lib/liteagent-shared/python-env`。如需使用自己的 Python 环境，可设置
`PYTHON`；虚拟环境不要提交进源码包：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-liteagent.txt
```

完整 OSWorld 任务还需要 Docker、`/dev/kvm`、共享 guest 和一个 OpenAI
兼容模型 endpoint。模型地址和密钥通过环境变量提供，不能写进 README 或源码：

```bash
export QWEN_BASE_URL='http://MODEL_HOST:8001/v1'
export QWEN_MODEL='Qwen3.5-9B'
export QWEN_API_KEY='EMPTY'
```

本机后续模型测试默认调用华为云昇腾上的 Qwen3.5-9B。V100 通过用户级服务
`qwen-modelarts-tunnel.service` 建立 SSH 隧道，断线后自动重连，并已设置登录外
持续运行和开机启动。模型仍在华为云执行推理。

机器配置位于仓库外的 `~/.config/liteagent/model.env`，保存上述三个环境变量；
私钥位于 `~/.ssh/liuxv-modelarts.pem`，不要提交到仓库。`bin/run-osworld.py` 和
`bin/run-liteagent.sh` 会自动读取机器配置，独立运行工作树也使用同一份配置。
显式环境变量优先于机器配置；`run-liteagent.sh` 的命令行参数仍可覆盖环境变量。
`run-osworld.py` 会把实际使用的模型名和地址写入本次结果的配置快照，历史配置和
结果不回写。其他需要调用模型的程序，可先执行 `set -a; . ~/.config/liteagent/model.env; set +a`。

检查隧道及模型连通性：

```bash
systemctl --user status qwen-modelarts-tunnel.service
set -a
. ~/.config/liteagent/model.env
set +a
curl --fail --silent --show-error "$QWEN_BASE_URL/models"
```

隧道日志通过 `journalctl --user -u qwen-modelarts-tunnel.service` 查看；需要重新
连接时执行 `systemctl --user restart qwen-modelarts-tunnel.service`。华为云实例及
模型服务须保持运行；实例重建或 SSH 端口变更后，更新本机 systemd 服务再重启隧道。

本地串行配置位于 `configs/single-task-active-thinking.json`，保持 Qwen3.5-9B thinking、每题
100 步和 1800 秒，并配置完整的工具调用
结束标记。`parallel_tool_calls=false` 请求每轮单个工具调用；完整结束标记让模型
在调用结束处停止生成，客户端仍检查恰好一个完整工具调用并执行参数 schema 校验。

复跑前，从开发分支最新提交创建独立 Git worktree，并在该目录依次运行指定题目：

```bash
cd /home/liuxv/liteagent
rerun_commit=$(git rev-parse HEAD)
mkdir -p /home/liuxv/liteagent-local-runs
rerun_root=$(mktemp -d /home/liuxv/liteagent-local-runs/committed-rerun-XXXXXXXX)
git worktree add --detach "$rerun_root/source" "$rerun_commit"
cd "$rerun_root/source"
HF_ENDPOINT=https://hf-mirror.com python bin/run-osworld.py --orders 13 15 27 47 76
```

`git worktree add` 从指定提交检出文件，不会带入开发工作区的未提交改动。
运行工作树中的源码、运行脚本和默认配置均来自该提交，启动前不要在其中修改源码。
复跑记录必须保留所用提交 SHA、源码摘要和配置；每次新复跑重新解析开发分支的
`HEAD` 并创建工作树，不复用旧快照来代表最新版本。

现有配置的 `sources.source_mode=active` 仍表示“复制启动目录的源码”，运行器本身
不会自动过滤未提交改动。因此必须从上述独立提交工作树启动，不能直接从有待提交
源码的开发目录启动。运行器再复制独立快照并记录源码摘要、Git 提交和工作区状态，
在快照准备后及运行结束时校验完整性。默认结果位于运行工作树父目录下的
`liteagent-local-runs/`，可用 `--result-dir` 指定其他仓库外目录。
可用 `--config /path/to/config.json` 指定测试配置，但不得借此混入未提交源码；
使用最新提交复跑时，不沿用历史配置中不匹配的固定源码摘要。

默认配置也收录了 4、102、119、147、183，在上述提交工作树内可按需复跑，例如：

```bash
HF_ENDPOINT=https://hf-mirror.com python bin/run-osworld.py \
  --orders 102 119 147 183
```

`configs/single-task-v3-thinking.json` 和 `configs/single-task-completion-repair.json`
保留为各次历史条件记录，不作为后续复跑默认配置。未设置 `source_mode` 的历史
配置仍校验固定源码摘要；运行器不会自动回滚或切换到历史源码。

当前完成门检查原生对象是否存在，并对可解析的独立分类求和透视表核对源范围、
分组、聚合、输出范围和最终回读值。缺少证据或发现不符时会报告具体目标与差异，
直接开放检查和修复工具，无需模型先调用 `completion_revise`。
适用范围、验证与限制见 [完成判定修复记录](docs/completion-outcomes-repair-20261021.md)。
完成声明通过完整门禁后立即结束，不再追加终态审计；审查不通过才进入修复。
最终完成门及第 4、147 题复跑证据见
[最终完成审查记录](docs/final-completion-gate-20261022.md)，Qwen 空参数工具和
分隔符修复见 [工具调用修复记录](docs/empty-tool-whitespace-repair-20261022.md)。
明确指定源列和目标单位列的缩放显示任务，还会核验目标原生值与实际显示结果，
允许复制、公式或写值实现；缺项持续到保存并回读验证消除，详见
[单元格结果核验修复](docs/scaled-display-outcomes-repair-20261022.md)。
公共指令明确列出独立分类百分比时，还会约束同分类分组和 COUNT，并核对保存后
最终表头、原生比例、百分比显示、分类集合、总计及分隔空行；原生检查也保留
同字段分组与计数的重复维度，详见
[分类百分比结果核验](docs/percentage-pivot-outcomes-repair-20261023.md)。
堆叠透视表还会按指令核对精确空行数，并核验保存后的分隔单元格；相对定位可用
平铺的 `below_range`、`blank_rows`，避免字符串/对象混合参数歧义，详见
[透视表空行与定位修复](docs/pivot-spacing-repair-20261023.md)。
Qwen 的透视表生成 schema 会将公共必填项、分类约束和条件定位约束展开为完整分支，
避免 XGrammar 编译组合 schema 时丢失公共参数；返回参数仍按原始 schema 严格校验，
不会自动补参。实现及编译器、模型端验证见
[透视表生成契约修复](docs/qwen-pivot-schema-contract-repair-20261023.md)。

直接调用单题或自定义任务配置时，也必须在上述提交工作树内运行：

```bash
./bin/run-liteagent.sh \
  --config /path/to/config.json \
  --orders 1 \
  --result-dir /tmp/liteagent-run-1 \
  --qcow2 /var/lib/liteagent-shared/Ubuntu.qcow2 \
  --base-url "$QWEN_BASE_URL" \
  --model "$QWEN_MODEL" \
  --api-key "$QWEN_API_KEY"
```

运行结果应写到 `/home/liuxv/liteagent-local-runs/` 或其他仓库外目录。
`src/adapter_versions/v2_expanded/experiments/` 已有历史配置只作证据保留；
新结果、模型权重和虚拟环境不纳入源码提交。磁盘和缓存继续使用已有忽略路径。

年度百分比变化汇总的计算列现要求模型提交源单元格引用和 Calc 公式，拒绝把心算常量
当作派生结果写入；完成检查核对原生公式、求值、显示和保存后的回读证据。Adapter 的两种
公开公式写入方式均可使用；这类任务暴露给模型的 `range.write` 只接受普通标签值，公式
统一经 `cells.set_formulas` 的单元格/表达式记录提交，避免 Qwen XML 对嵌套 typed 矩阵的
不可靠约束。公式工具在表头及全部所需年份标签已建立后开放，缺失年份持续投影到模型
上下文；读取和标签修复工具继续可用。这是已有计算证据依赖的工具面约束，没有增加模型
审查阶段。当前适用范围与测试见
[计算公式与回读核验](docs/calc-formula-evidence-repair-20261023.md)，本次尚未复跑 OSWorld。

## 集成与补丁

本机独立集成工作树位于
`/home/liuxv/liteagent-integration-worktrees/api-split-20261021/`。
已发布材料位于本分支的
[docs/integration/api-split-20261021/](docs/integration/api-split-20261021/README.md)，
包含 `api-split.patch`、相对导入基线的 `name-status.tsv`、纳入/排除清单和检查日志。

主仓库使用 `adapter_versions/`，本仓库使用 `src/adapter_versions/`；不要为了合并移动模块。
在主仓库根目录先预检查，再应用补丁：

```bash
git apply --check -p2 /absolute/path/to/api-split.patch
git apply -p2 /absolute/path/to/api-split.patch
```

`-p2` 去掉 Git diff 的 `a/` 或 `b/` 以及本地 `src/` 前缀。
开发历史中包含 `1142019` 的 evaluator 改动，不直接把开发分支合并进主仓库；
集成候选已排除该提交的全部三个路径。

本次最小检查：91 个变更 Python 文件 Ruff 通过，`git diff --check` 通过，
相关测试为 **171 通过、8 失败**；同一组 8 项失败已在原开发源码复现，详见
[检查汇总](docs/integration/api-split-20261021/verification.json)。
这些检查没有启动 benchmark，也不表示集成候选已通过正式验收。

## Docker 配置

`docker/shared-osworld.compose.yml` 只引用已有的
`happysixd/osworld-docker:latest`，并通过 `${OSWORLD_QCOW2}` 挂载基盘；
它不会把镜像或 qcow2 复制到用户目录。若共享容器被停止，可在任一目录执行：

```bash
docker-compose -p liteagent-shared --env-file docker/shared-endpoints.env \
  -f docker/shared-osworld.compose.yml up -d
```

部署后使用 `./bin/guest-status.sh` 检查截图接口和 Adapter。容器由管理员
统一维护，两个用户不需要重复 `docker pull` 或保存大镜像。

## 边界

这是开发运行环境和集成候选，不是新的 benchmark 结果。历史记录按各次实际条件解释；
任何正式评测仍需单独冻结源码、配置和结果目录。
