# LiteAgent 开发与集成工作区

本仓库保留 LiteAgent 的运行源码、测试和历史开发记录。当前开发分支为
`codex/api-split-liuxv`，冻结 v3 源码基线提交为 `026e829`。
运行范围为 562 个文件，SHA-256：

```text
8ed6671fb2928c99e379880007d60638d9768d321ba2dde94cf61b4bafea780b
```

源码与包入口保持 `src/adapter_versions/v2_expanded/`；`v2_expanded` 是历史目录名。
本次目录与文档整理没有修改运行源码。

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

`liuxv` 的工作分支是 `codex/api-split-liuxv`。先读
[大粒度 API 拆分任务](API_SPLIT_TASK.md)，完整的 216 项公开面复查、P0/P1
清单和源码证据在 [API 粒度审计](docs/api-granularity-audit-20260920.md)。
本任务只做 Adapter 契约拆分和针对性测试，不新增门禁，也不启动全量评测。

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

默认的本地串行配置位于 `configs/single-task-v3-thinking.json`：它固定冻结
v3 源码、Qwen3.5-9B thinking、每题 100 步和 1800 秒，并配置完整的工具调用
结束标记。`parallel_tool_calls=false` 请求每轮单个工具调用；完整结束标记让模型
在调用结束处停止生成，客户端仍检查恰好一个完整工具调用并执行参数 schema 校验。

依次运行指定 OSWorld 题目：

```bash
HF_ENDPOINT=https://hf-mirror.com python bin/run-osworld.py --orders 13 15 27 47 76
```

运行器会核对当前 LiteAgent 源码与配置中的冻结 v3 摘要，按顺序运行题目，并将
独立源码快照、配置、命令、日志和结果写入 `../liteagent-local-runs/`。可使用
`--config /path/to/config.json` 指定另一份配置。

直接调用单题或自定义任务配置时，仍可使用通用形式：

```bash
./bin/run-liteagent.sh \
  --config /path/to/config.json \
  --orders 1 \
  --result-dir /tmp/liteagent-run-1 \
  --base-url "$QWEN_BASE_URL" \
  --model "$QWEN_MODEL" \
  --api-key "$QWEN_API_KEY"
```

运行结果应写到 `/home/liuxv/liteagent-local-runs/` 或其他仓库外目录。
`src/adapter_versions/v2_expanded/experiments/` 已有历史配置只作证据保留；
新结果、模型权重和虚拟环境不纳入源码提交。磁盘和缓存继续使用已有忽略路径。

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
