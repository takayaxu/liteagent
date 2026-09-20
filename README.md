# LiteAgent 可运行源码包

这是当前 `adapter_versions/v2_expanded` LiteAgent 的可运行源码快照，面向
`liuxv` 和 `pengzhe` 两个用户目录。两份目录包含同一份源代码和启动配置，
不包含 Python 虚拟环境、实验结果、缓存、模型权重或 Ubuntu qcow2 镜像。
上游 OSWorld 的其他 Agent 示例和账号 settings 也被剔除；交付包只保留
LiteAgent 使用的 Docker controller、公开任务定义和 evaluator 源码。

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
src/adapter_versions/v2_expanded/  LiteAgent、Adapter 和运行脚本
src/third_party/OSWorld/          OSWorld Python 源码和任务定义
bin/check.sh                       源码编译和关键导入检查
bin/run-liteagent.sh               LiteAgent 运行入口
bin/guest-status.sh                检查共享 guest 和 Adapter 健康状态
docker/shared-osworld.compose.yml  共享 guest 的 Docker 配置
docker/shared-endpoints.env        共享 guest 的本机端口
requirements-liteagent.txt        运行时 Python 依赖清单
```

## 当前开发任务

`liuxv` 的工作分支是 `codex/api-split-liuxv`。先读
[大粒度 API 拆分任务](API_SPLIT_TASK.md)，完整的 216 项公开面复查、P0/P1
清单和源码证据在 [API 粒度审计](docs/api-granularity-audit-20260920.md)。
本任务只做 Adapter 契约拆分和针对性测试，不新增门禁，也不启动全量评测。

## 首次检查

```bash
cd /home/liuxv/liteagent       # pengzhe 目录同理
./bin/check.sh
```

检查只读源码，不会下载模型或启动任务。启动和检查脚本默认使用已部署的
`/var/lib/liteagent-shared/python-env`。如需使用自己的 Python 环境，可设置
`PYTHON`；虚拟环境不要提交进源码包：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-liteagent.txt
```

完整 OSWorld 任务还需要 Docker、`/dev/kvm`、共享 guest、一个 OpenAI
兼容模型 endpoint，以及任务配置。模型地址和密钥通过环境变量提供，不能
写进 README 或源码：

```bash
export QWEN_BASE_URL='http://MODEL_HOST:8001/v1'
export QWEN_MODEL='qwen3.5-4b'
export QWEN_API_KEY='EMPTY'
```

运行单个任务的通用形式：

```bash
./bin/run-liteagent.sh \
  --config /path/to/config.json \
  --orders 1 \
  --result-dir /tmp/liteagent-run-1 \
  --base-url "$QWEN_BASE_URL" \
  --model "$QWEN_MODEL" \
  --api-key "$QWEN_API_KEY"
```

不要把 `Ubuntu.qcow2`、模型权重、`experiments/` 或 `.venv/` 放进这两个
源码目录。运行结果应写到用户自己的临时或结果目录。

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

这是源码交付和单 guest 开发运行环境，不是新的 benchmark 基线。历史实验
证据、任务结果和模型权重都没有复制；任何正式评测仍需单独冻结源码、配置和
结果目录。
