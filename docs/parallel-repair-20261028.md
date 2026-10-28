# 多对话并行修复

## 原因与实现

旧 `run-osworld.py` 持整轮公共排他锁，不同题目的独立 guest 也被串行；锁路径还依赖工作树父目录，无法可靠跨工作树协调。Docker provider 实际已为每题创建新容器、匿名可写卷和动态端口，只读挂载基盘。保留其启动阶段公共端口锁，不修改 provider、模型、任务或 evaluator。

新入口使用同账号固定资源目录 `~/.local/state/liteagent/repair-resources`：短时 registry 锁保护分配，默认 3 个整轮名额，按 task_id 加认领锁。不同题目可重叠，同题排队；冲突时释放所有部分认领，不占着名额等待其他题目。`repair-resources.py status` 根据实际 flock 而非残留 JSON 判断占用，`configure --slots N` 仅允许空闲时调整到 1–12。

旧公共锁固定为 `~/liteagent-reproduction-jobs/v3-repair-vm.lock`。新独立运行持共享锁，旧排他持有者结束后才能进入；`--exclusive` 取得排他锁并占全部名额。为保留历史互斥，兼容锁的范围覆盖整个运行；新入口外不得再套整轮公共排他锁。等待调度不保证严格先进先出。历史脚本若使用其他路径的锁，需要另行确认所有权和资源隔离，不能视作已纳入池。

## 启动与证据

遵循 README，从已提交源码创建每个对话自己的工作树。每次新建尚不存在的结果目录：

```bash
HF_ENDPOINT=https://hf-mirror.com python bin/run-osworld.py \
  --orders 13 --result-dir /home/liuxv/liteagent-local-runs/my-repair/run-001/output
python bin/repair-resources.py status
```

题目必须存在于配置；可用 `--config` 指向保留原始条件、补齐题目身份的配置。不同对话运行不同题目，沿用原审核/最小通用修复/单题复跑流程。多题 `--orders` 在一个名额内串行执行，题目锁覆盖整批；需要跨对话并行时分别启动。

每轮快照包含独立 OSWorld 源码和仅所选题目的 cache；准备前后及运行结束校验 evaluator/source/config 摘要。`resource-request.json`、`resource-lease.json`、`run-status.json` 记录 owner、源码身份、题目、名额、等待原因及结果位置，`final-integrity.json` 包含 OSWorld 校验。

owner 每轮随机生成，通过 `openapa.run_owner` Docker label 标识。SIGTERM/SIGINT 终止自己的 runner 进程组，再按精确 owner label 清理遗留容器及其匿名卷，完成后释放名额；不清理其他任务。租约文件描述符传入 runner，单独 SIGKILL 包装器时，尚存 runner 仍保有租约。SIGKILL 无法执行 finally 清理；若 runner 也被强杀但容器残留，先按回执核对 owner，仅清理该轮容器。禁止全局 kill/prune。

## 验证与边界

`tests/test_parallel_repair_resources.py` 用真实子进程/flock 和合成 runner 验证：跨项目共享池且重叠执行、同题互斥、容量及重配限制、独占名额、部分认领释放、进程退出释放、子进程继承租约、旧排他锁兼容、SIGTERM、精确 owner 清理、私有 cache 及 evaluator 摘要。合成 runner 不执行模型推理，不计为 OSWorld PASS。

实施时只读核验了并行中的 Order100/30/103：三个不同 owner 的独立容器、不同主机端口、同一只读基盘和不同匿名可写卷。它们使用历史入口，不计入新池，未修改或重启。未以本次基础设施改动发起新的正式题目评测，也未改写历史分数。

资源池限同机同账号；其他账号、历史入口或直接运行 `run-liteagent.sh` 不自动占名额。共享模型的吞吐和排队可能影响每题耗时，默认 3 是并发上限而非性能保证。不要更改公共模型配置或为迁移改写运行中的快照。已有旧排队控制器应由所属对话确认状态后迁移下一轮，不能用新入口外加排他锁继续排队。Git 集成仍只在短时间更新活动分支时串行，不能占整轮推理。
