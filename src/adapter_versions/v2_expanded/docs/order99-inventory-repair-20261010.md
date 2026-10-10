# Order 99：清单发现与跨文件对照修复

> 2026-10-10 入口核对：Order 99 本轮批次为 FAIL；最新已核对运行为 PASS。[最新结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json) / [最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[完整批次与后续记录](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/docs/osworld-task-results-index-20261010.md#order-99)。下文是本文件所述运行的记录，历史路径不作为最新入口。

## 原始失败证据

题目 ID：`337d318b-aa07-4f4f-b763-89d9a2dd013f`。人工完整查看原始任务定义、用户指令、45 步事件、45 份模型请求、调用日志、verification 与 evaluator 产物；题目要求对照发票和银行流水，把不匹配的发票移入用户指定目录。

原始目录：`experiments/osworld-api-split-test-only-20261010-resume1/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/`。运行时间为北京时间 2026-10-10 15:12:44–15:20:40；正式 evaluator `reward=0.0`，45 步，475.856 秒。manifest 终止原因为 `max_steps`；批次 results.json 未填写 termination_reason，保留原记录。

前 6 步反复搜索 `pdf.extract_text_batch`，命中正确 reader；其余 39 步搜索未注册的 `filesystem.list_directory`，结果为空。所有模型请求只提供 `tools_search/propose_done/fail_task`，实际 Adapter 调用为 0，协议与传输错误为 0。整理状态要求先建立来源清单，却没有向模型说明该前置条件，搜索到 reader 后也未暴露可执行入口。evaluator 无法获取目标 PDF，result artifact 为 null。

## 本题增量

- 清单未建立时，搜索工具明确指引发现公共 `os.filesystem.find`；发现后直接提供该调用，避免继续搜索和过早结束。
- 整理的初始清单使用 `kind=any`、`name_patterns=["*"]`、`recursive=false`。schema 与运行时拒绝过滤或递归的初始清单；根目录仍由模型根据用户指令和当前桌面证据选择。补充桌面可见源文件对应 `~/Desktop` 的通用位置指引。
- 对照类指令下，planner 与独立分类 checker 保留其他已实际读取对象的内容观察。未读对象和瞬时 launcher 截图不会作为对照证据；剔除历史 organization_progress，防止旧对象状态覆盖当前标记；不填写任何预期答案。
- checker 的 retain/insufficient_evidence 必须提供当前父目录，禁止空字符串；提示明确要求 disposition、目录和理由一致。
- 当前对象的 rename 被语义校验拒绝时，提供重新分类入口，保留对象且禁止继续重复已拒绝的移动；checker 可看到该对象最近的实际 mutation validation error。

- retain 工具的 path enum 与当前对象绑定；既有 runtime validation 继续拒绝旧对象路径。

P1 复核：保留 `os.pdf.extract_text_batch`，它仍是有界只读观察，不决定分类、不移动文件。保留 `filesystem.find` 与单文件 `filesystem.rename`；只收窄整理流程的初始清单调用契约，没有新增大粒度 API、题目 ID 路由、答案、golden 或固定坐标。

## 定向检查

- 原失败 45 个搜索回合离线重放：每个回合都明确提示清单前置条件；发现清单工具后仅提供对应的 correlated Adapter route。
- `PYTHONPATH=src/adapter_versions/v2_expanded /var/lib/liteagent-shared/python-env/bin/python -m pytest -q src/adapter_versions/v2_expanded/tests/test_filesystem_move_discovery.py`：70 passed。
- 临时 focused contract 检查：有效初始清单可调用；过滤、kind=file、recursive=true 被 schema 拒绝；实际观察的参考内容在 retain 转换后保留，未读对象排除；真实流水摘录的有效 retain 通过，空目标目录拒绝；实际失败移动回合重新提供分类入口且不推进源对象。
- 四个改动 Python 文件 Ruff 通过，whitespace 检查通过。没有新增回归测试或跨题评测。

## 单题运行

所有目录均以 `experiments/osworld-order99-qwen-20261010-inventory-handoff` 为前缀；每次都保留原始轨迹，未覆盖旧失败。模型为 `https://qwen.jinmaoapi.cc.cd/v1` 的 `Qwen3.5-9B`，non_thinking，temperature=0，45 全局步、25 本地步、一次 soft restart、1200 秒 Agent 预算、8192 输出 tokens。

| 后缀 | 状态 | 诊断 |
|---|---|---|
| 无 | interrupted，8 步，无评分 | 搜索循环修复有效，但小写过滤模式仅找到一张发票，漏掉流水和其余文件；Codex 主动 SIGINT 保存诊断证据 |
| retry1 | interrupted，6 步，无评分 | 完整枚举了 home，将 Desktop 容器当作当前对象；Codex 主动停止，补充来源目录指引 |
| retry2 | interrupted，6 步，无评分 | 正确枚举 4 个文件并读取流水，checker 的 retain 返回空目录，不能推进；Codex 主动停止并修复契约 |
| retry3 | PASS，reward=1.0，25 步，stalled_no_progress，778.290 秒 | 不匹配发票已移动且验证通过；匹配发票的错误移动被既有运行时校验阻止，但旧工具面不能重新分类 |
| retry4 | PASS，reward=1.0，45 步，manifest=max_steps，702.154 秒 | 分类 checker 成功纠正匹配发票的错误判定，但无 enum 的 retain 工具反复收到旧发票路径；既有 validation 拒绝，未改动匹配文件 |
| retry5 | PASS，reward=1.0，45 步，manifest=max_steps，1386.762 秒 | 全部增量：流水和三张发票均真实读取；唯一不匹配发票移动且验证通过，第二张匹配发票显式保留；第三张匹配发票保留在原位，但 checker 的 disposition 与理由反复矛盾，未正常 agent_done |

retry3 的部署前两次因 PackageKit 索引锁/apt 缓存问题失败，第三次部署恢复。在尚未有任务动作时，经属于该进程的 guest control endpoint 调用已有 `CommandRunner.sudo` 执行 `apt-get -o DPkg::Lock::Timeout=90 install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng`；返回 0，包已就绪。未改任务文件或 evaluator，也未改部署脚本。

实际单题命令（result-dir 按上表增加后缀）：

```bash
HF_ENDPOINT=https://hf-mirror.com PYTHONPATH=src/adapter_versions/v2_expanded \
/opt/anaconda3/bin/python3.13 -u src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py \
--config src/adapter_versions/v2_expanded/experiments/configs/osworld-order99-qwen-20261010-inventory-handoff.json \
--result-dir src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5 \
--orders 99 --base-url https://qwen.jinmaoapi.cc.cd/v1 --model Qwen3.5-9B \
--reasoning-mode non_thinking --max-steps 45 --max-local-steps 25 --max-soft-restarts 1 \
--max-no-progress-steps 8 --max-agent-seconds 1200 --max-output-tokens 8192 \
--request-timeout 240 --model-retries 3 --top-k 7 --temperature 0
```

## 提交边界

当前工作区已有多个题目的未提交共享源码增量，且 `organization_validation.py` 是本轮开始前就存在的未跟踪文件；不能把其全部内容或其他题目的代码混入 Order 99 提交。活动源码已应用本题修改，另提供仅包含本次增量的 `order99-inventory-repair-20261010.patch` 及修复前后文件 SHA-256 清单，供集成人员在当前共享基线上复核/应用。交付提交只包含本题补丁、记录、配置与审计更新，不宣称该文档提交的裸 HEAD 已包含全部工作区运行依赖；正式分数来自记录的工作区。

## 最终回执与限制

最终工作区验证结果：`experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json` 为 `status=passed`、`reward=1.0`、45 步，耗时 1386.762 秒（含环境部署）；manifest 终止原因为 `max_steps`，results.json 沿用未填 termination_reason 的原始字段。完整轨迹位于该目录 `raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/`。正式 evaluator 获取结果 PDF 与 expected PDF，比较通过。

第 3、6、9、14 步分别读取流水与全部三张发票。第 8 步只移动唯一金额不匹配的发票，Adapter verification=true；第 12 步显式保留第二张匹配发票。第 13 步过期 reader 路径被拒绝，第 14 步恢复为当前对象并读取成功。第三张发票的 planner 正确请求 retain，但 checker 在理由中确认金额/商户匹配，字段却持续输出 move；两者不同导致 check 不通过，原文件没有移动。该问题仍是 **模型 verdict 自相矛盾造成的收尾限制**；不能将本次 evaluator PASS 记为完整分类状态机正常结束。没有通过解析理由强制改写 verdict，也没有加入题目答案。

原始 FAIL、三次主动中断、两次中间 PASS 与最终 PASS 都保留，各轮结果互不覆盖。最终活动源码与增量补丁 SHA-256 一致，未运行其他题目。

交付提交：`f0afcaa`（`fix(order99): package inventory and reconciliation workflow repair`），包含本题独立增量补丁、修复前后 SHA-256、正式验证配置、开发日志与审计。后续证据提交 `37202a6`（`docs(order99): record repair delivery and final evaluator evidence`）修正补丁的空白上下文表示，不改变活动源码行为。

轨迹 manifest 的 adapter_verifier_passed_calls 汇总为 0，但原始第 8 步 rename 返回嵌套 verification_passed=true，且 evaluator result/expected 的 SHA-256 相同；沿用原始文件，不修改汇总计数。

## 本次四处写回的证据入口

[正式结果](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/results.json)；[最新事件轨迹](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/lite_agent_events.jsonl)；[轨迹 manifest](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/trajectory_manifest.json)；[原始评分](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/result.txt)；[evaluator 产物索引](/home/liuxv/liteagent/src/adapter_versions/v2_expanded/experiments/osworld-order99-qwen-20261010-inventory-handoff-retry5/raw/run-1/99-multi_apps-337d318b-aa07-4f4f-b763-89d9a2dd013f/evaluator_artifacts/manifest.json)。

工具事件共 45 条，北京时间 2026-10-10T21:40:31.439163+08:00 至 2026-10-10T21:59:22.006738+08:00；完整运行于北京时间 2026-10-10 21:36:44–21:59:51，含部署。6 个实际 Adapter 调用为 1 次 find、4 次 PDF 读取、1 次 rename。

evaluator result/expected 均为 15655 字节，SHA-256：`39c23a5792795583184c3694de5b0187d895e6ef75d2e2cbfbdd16b23f1c3594`。完整证据 SHA-256 与终止字段同步写入 [批次审计 JSON](osworld-passing-submission-20261010.json) 和 [统一结果 JSON](osworld-task-results-index-20261010.json)。

本次同步 API 审计、正式开发日志、本单题日志、最新结果入口及配套机器可读回执；只校验文档链接、原始证据和 JSON，不新增复跑。原批次仍为 23/28。
