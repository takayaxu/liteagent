# LiteAgent · Computer Use

基于大语言模型的桌面任务执行与评测项目。LiteAgent 将自然语言目标转为可校验的工具调用，通过应用 Adapter 操作文档、表格、浏览器、文件系统等；需要视觉交互时使用 GUI 操作。项目以 OSWorld 任务验证执行结果，保存模型请求、工具调用、截图、轨迹和原始评分。

主活动分支为 **`codex/v4`**，运行代码位于 `src/adapter_versions/v2_expanded/`。`v2_expanded` 是保留的目录名，不代表当前发布版本。

## 当前状态

更新日期：**2026-11-19**。最近一轮评测于北京时间 **2026-11-14 14:40** 完成。

| 项目 | 当前记录 |
| --- | --- |
| 最近评测的冻结源码 | `c96e196d7741c247a11ba19ee496364af5d994b3` |
| 冻结标签 | `full189-c96e196-20261113`（本地标签） |
| 模型 | 本地 llama.cpp，Qwen3.5-9B F16 多模态，thinking |
| 任务范围 | 固定有序 189 题，原 evaluator；117 使用用户授权修订指令 |
| 合并结果 | **160/189 PASS，84.66%**；29 题未通过 |
| 最近108题续跑条件 | 6 并发，150 步，单题 2400 秒；79 PASS |
| 保留成绩 | 此前条件下通过的81题，没有重新测试 |
| 本轮状态 | 已完成，续跑最终完整性检查通过，本轮容器已释放 |

**160/189 是多轮续跑的合并成绩，不是统一条件下一次完整全量的成绩。** 前序批次包含不同并发，预算为100步/1800秒；最后108题改为150步/2400秒。部分修复使用精确任务ID限定的阶段提示，因此也不能将其描述成无任务提示的通用基准成绩。

| 最终状态 | 数量 |
| --- | ---: |
| PASS | 160 |
| 原始评分 FAIL | 19 |
| `agent_deadline_exhausted` | 9 |
| `model_protocol_failure` | 1 |

最近108题续跑没有环境失败或评分异常。接近1的连续分数仍记为FAIL；超时与协议失败的未评分结果不改成0分。

- [最新结果回执与条件](reports/20261114-c96e196-aggregate/result-summary.json)
- [全189题状态及成绩来源](reports/20261114-c96e196-aggregate/task-results.json)
- [29道未通过题单](reports/20261114-c96e196-aggregate/wrong-tasks.md)

## 执行架构

```text
自然语言指令 + 当前观察
          ↓
LiteAgent：规划、工具发现、运行状态与上下文
          ↓
OpenAI兼容模型服务：每轮生成一个原生工具调用
          ↓
调用解析与schema校验
          ↓
应用Adapter / GUI操作 → 执行回执、截图、事件轨迹
          ↓
保存与回读验证、完成检查 → 继续执行或结束
          ↓
回合结束后由OSWorld原evaluator独立评分
```

应用能力覆盖LibreOffice Calc、Writer、Impress、Chrome、GIMP、Thunderbird、VLC、VS Code、操作系统及多应用任务。Adapter提供可复用操作，GUI负责需要直接桌面交互的环节；模型自述不作为任务通过的依据。

并行评测由supervisor分片派发，每个任务使用独立Docker/KVM guest。模型推理槽位、虚拟机数量和磁盘吞吐共同决定实际容量；模型提供12个槽位不等于服务器能够稳定运行12台评测虚拟机。

## 仓库导航

| 路径 | 用途 |
| --- | --- |
| `src/adapter_versions/v2_expanded/integrations/lite_agent/` | Agent、工具面、协议、状态管理与完成检查 |
| `src/adapter_versions/v2_expanded/*_adapter/` | 各应用Adapter |
| `src/adapter_versions/v2_expanded/scripts/` | 单题运行器、并行supervisor、源码封存与审计 |
| `src/adapter_versions/v2_expanded/tests/` | 行为、契约、协议、隔离与部署测试 |
| `src/adapter_versions/v2_expanded/deployment/` | 模型和运行环境部署相关文件 |
| `src/third_party/OSWorld/` | OSWorld环境、任务与evaluator；包含本地集成内容 |
| `configs/` | 单题开发配置和历史实验配置 |
| `bin/` | 检查、模型环境加载、隔离运行与资源池入口 |
| `docker/` | 共享guest的compose和端口配置 |
| `reports/` | 评测汇总、错题单、逐题修复回执 |
| `docs/` | 设计、故障分析、历史集成材料 |
| `repair_skill.md` | 修复流程及累计修复记录 |

运行快照、模型权重、qcow2、缓存、虚拟环境和大体积原始结果放在仓库外或已有忽略目录中。不要把新评测输出写入已完成的历史目录。

## 环境与模型

完整运行需要Linux、Docker、可用的`/dev/kvm`、Ubuntu guest基盘、Python依赖，以及支持工具调用和图像输入的OpenAI兼容模型服务。只安装Python包并不能代替guest环境部署。

以下是已有服务器的资源位置；换机器时需配置等价资源。

| 资源 | 本机位置 |
| --- | --- |
| 主活动工作区 | `/home/liuxv/liteagent` |
| Python | `/var/lib/liteagent-shared/python-env/bin/python` |
| 默认共享基盘 | `/var/lib/liteagent-shared/Ubuntu.qcow2` |
| 本地模型endpoint | `http://127.0.0.1:18009/v1` |
| 模型配置 | `~/.config/liteagent/model.env`，不纳入Git |
| 原始运行记录 | `/home/liuxv/liteagent-local-runs/` |

启动器优先使用已部署Python，也支持通过`PYTHON`指定解释器。新环境可先安装主机侧依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-liteagent.txt
```

当前测试使用本地9B，显式设置环境以覆盖机器上可能保留的云端配置：

```bash
export QWEN_BASE_URL='http://127.0.0.1:18009/v1'
export QWEN_MODEL='Qwen3.5-9B'
export QWEN_API_KEY='EMPTY'
curl --fail --silent --show-error "$QWEN_BASE_URL/models"
```

`EMPTY`适用于本地无鉴权服务；其他服务的真实密钥通过环境提供。`bin/run-osworld.py`和`bin/run-liteagent.sh`会加载机器配置，显式环境优先；后者还支持命令行覆盖。历史昇腾/SSH隧道部署不是最近评测使用的后端。

本地服务使用`configs/single-task-local9b-thinking.json`，其中`tool_call_stop_sequence=null`。不要复用云端XML结束stop：本地llama.cpp可能先截去结束标记，使原生解析器无法返回`tool_calls`。客户端仍要求单个调用并按原schema严格校验。协议与部署要求见[本地工具协议](docs/local9b-tool-protocol-20261112.md)和[模型服务修复](docs/local9b-delivery-20261112.md)。

## 运行与检查

### 源码检查

在仓库根目录运行：

```bash
git status --short --branch
git diff --check
./bin/check.sh
```

`check.sh`检查编译与关键导入，不启动评测，不代表OSWorld通过。修改行为时按影响范围运行相关测试，例如：

```bash
PYTHONPATH=src/adapter_versions/v2_expanded \
  /var/lib/liteagent-shared/python-env/bin/python -m pytest -q \
  src/adapter_versions/v2_expanded/tests/test_atomic_provider_surface.py \
  src/adapter_versions/v2_expanded/tests/test_task_stage_prompts.py
```

### 隔离单题复跑

先提交待验证的运行源码，再从指定提交创建独立工作树。`source_mode=active`表示复制启动目录源码，运行器本身不会剔除未提交改动，因此不要从有源码改动的开发目录直接启动正式复跑。

```bash
cd /home/liuxv/liteagent
rerun_commit=$(git rev-parse HEAD)
rerun_root=$(mktemp -d /home/liuxv/liteagent-local-runs/committed-rerun-XXXXXXXX)
git worktree add --detach "$rerun_root/source" "$rerun_commit"
cd "$rerun_root/source"

QWEN_BASE_URL=http://127.0.0.1:18009/v1 \
QWEN_MODEL=Qwen3.5-9B QWEN_API_KEY=EMPTY HF_ENDPOINT=https://hf-mirror.com \
  /var/lib/liteagent-shared/python-env/bin/python bin/run-osworld.py \
  --config configs/single-task-local9b-thinking.json \
  --orders 2 3 --result-dir "$rerun_root/output" \
  --qcow2 /var/lib/liteagent-shared/Ubuntu.qcow2
```

基盘必须可读且满足隔离运行器创建硬链接的权限要求；权限不符时，用`--qcow2`指向本账号已准备的基盘。不要修改共享基盘。一次传入多个`--orders`会在一个修复名额内串行运行。

仓库中的本地单题配置仍是**100步/1800秒**。最近续跑的**150步/2400秒**来自独立冻结配置，不是本仓库默认预算。改变条件时，启动前生成并保存新配置，不在运行中改模型、源码或预算。

### 并行修复与全量

不同修复各自使用工作树、快照、缓存及guest；同一task ID跨工作树互斥。默认修复资源池为5个名额，支持1–12个：

```bash
python bin/repair-resources.py status
python bin/repair-resources.py configure --slots 5
```

资源池容量不会自动改变已启动批次的并发。全量入口是`src/adapter_versions/v2_expanded/scripts/supervise_lite_agent_parallel.py`，需要准备新的冻结配置、源码摘要、独立仓库身份和结果目录，再执行`--plan-only`校验。普通单题配置不能直接作为全量冻结条件使用。参数以该脚本`--help`为准。

运行前检查CPU、内存、磁盘I/O、Docker与模型槽位，分批启动虚拟机。此前12并发发生过guest就绪超时和高I/O等待；最近完成的108题使用6并发。无法恢复的Docker启动故障会终止后续派发并保留已有结果。详见[并行隔离](docs/parallel-repair-20261028.md)、[Docker启动恢复](docs/docker-startup-recovery-20261030.md)。

### 最近一轮结果与进度入口

以下是本机已完成运行的路径，供复核使用；源码快照不再修改，也不会自动启动新任务。

```text
冻结源码仓库：
/home/liuxv/liteagent-local-runs/resume108-c96e196-6workers-150steps-2400s-20261114T021642Z/source

本轮目录（配置、控制器、汇总及原始结果入口）：
/home/liuxv/liteagent-local-runs/resume108-c96e196-6workers-150steps-2400s-20261114T021642Z
```

```bash
python /home/liuxv/liteagent-local-runs/resume108-c96e196-6workers-150steps-2400s-20261114T021642Z/progress.py
# 添加 --watch 每5秒刷新；添加 --json 输出机器可读状态。
```

源码SHA-256：`faeef74794866bfb78e54f5072f5d93203290fdd90fdd3cbd2d9825b1c4f9ee2`。OSWorld原始基点为`091f5ef1d5544bc74953c77875d5feb5bed30108`，本轮任务仓库提交为`4976d975c069e77522854a8ec6ad2594dc390731`，仅在此基点上加入用户批准的117指令修订，evaluator不变。详情以本轮回执为准。

## 修复流程与结果解释

先读失败轨迹并确认运行版本；旧轨迹用目标活动源码复现。无需补丁即通过则按新回执记录；仍失败则定位根因，制定最小可行方案，按当前审核模式评审。在独立工作树修改、测试，再以带补丁的提交复跑原题。只有原评分确认通过才纳入已修复题单；FAIL、诊断中止和未评分异常都保留。完整流程与审核选项见[repair_skill.md](repair_skill.md)。

阶段提示按精确任务和执行阶段限制范围，不把单题通过扩大为其他任务已验证。任务指令修订、预算变化、服务端协议补丁和混合续跑均需说明。近期修复记录：

- [99协议根因与原始评分PASS](reports/20261113-order99-protocol-rootcause/README.md)
- [16题超时相关修复与13题通过记录](reports/20261113-deadline16/README.md)
- [指定题阶段修复台账](reports/20261113-requested-stage-repairs/README.md)
- [十一题协议与阶段提示修复](reports/20261113-protocol11/README.md)

这些是对应版本和条件的单题证据，不能相加成全量成绩。最新汇总中的29题仍未通过，即使部分题在历史单题运行中曾通过。

## 历史版本与文档

| 历史记录 | 结果及入口 |
| --- | --- |
| 2026-10-26，初始v4集成 | `a65c4ab`，138/189；[集成回执](docs/integration/v4-20261026.md) |
| 2026-10-30，Docker修复后全量 | `c8349c4`，139/189；[结果回执](reports/20261030-dockerfix-full189/result-summary.json) |
| 2026-11-14，当前冻结版续跑汇总 | `c96e196`，160/189，混合条件；[结果回执](reports/20261114-c96e196-aggregate/result-summary.json) |

`v4`标签对应初次集成，不随`codex/v4`分支移动；历史v3 `026e829`也不作为后续默认基线。新一轮运行应明确指定提交并重新封存条件。

更早的API拆分补丁、路径映射及纳入/排除清单见[历史集成材料](docs/integration/api-split-20261021/README.md)。[原项目结构说明](docs/project-structure.md)和源码子目录README含早期基线，按各自日期解释；本页是当前项目入口。旧根README完整保存在[历史快照](docs/archive/root-readme-before-20261119.md)，其中的服务、任务和分数只代表当时记录。
