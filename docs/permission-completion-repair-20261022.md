# 第 147 题：完整目标核验与修复工具保留

开发分支：`codex/api-split-liuxv`。本次在活动源码上修复，不改原始任务、evaluator 或 golden。
任务 `order: 147` / `source_order: 287`，UUID `4d117223-a354-47fb-8b45-62ab1390a95f`。
指令要求将当前目录树下所有普通文件的权限改为 644。

## 根因与修改

旧完成门只核对动作名称是否出现，最后一次单文件修改的 verifier 就能满足回读条件；
没有将“所有文件”绑定到完整目标集。该误判还会触发完成审查，将普通工具收缩为
`propose_done`、`fail_task` 和 `completion_revise`。实际轨迹中模型知道还有目标没处理，
但无法直接调用权限修改；其待办声明又落在有限正则之外，于是完成门错误接受。

本次为可解析的“所有文件 + 八进制权限 + 当前/显式绝对目录”建立目标范围核验：

- 从完整的原生 `filesystem.find` 清单逐个核对文件实际权限，不累计调用次数。
- 目录范围、全名通配、递归方式必须覆盖要求；截断、隐藏条目被跳过、深度限制、扫描
  错误或上下文裁剪都不能证明全部目标已覆盖。
- 最终完整清单必须晚于最后一次可能修改文件的调用。单文件成功只更新该文件的证据，
  不能替代其他目标的状态和完整最终清单。已经是正确权限的文件无须重复修改。
- 缺项使用统一 `outcome_issues` 接口，包含目标、要求、观察值、证据步及修复动作。
  无需模型先提交一次失败完成声明或调用 `completion_revise`。
- 完成审查通过后仍保留检查、已有修改动作和搜索；终态审计同样可选择实际修复动作，
  通过现有的撤销 pending terminal 路径继续执行。提示不再断言“无需后续操作”。
- 待办声明检查补充“remaining files still need to be processed”等表述；即使模型不承认
  遗漏，实际目标核验也独立阻止完成。
- 工作流进度改为根据未满足的权限结果报告，避免一次修改就标记 `mutation_complete`。

`filesystem.find` 增加每个条目的 Unix mode、符号链接标记和覆盖情况；明确报告隐藏项、
未访问子目录和扫描异常。链接路径与其目标保持不同记录，避免覆盖真正的普通文件条目。
接口仍只读；修改仍由模型逐文件选择公开 `filesystem.set_permissions` 参数执行。
新检查不执行脚本、不读宿主机目标文件，也不自动修改任何模型参数。

本版不声称支持任意自然语言权限表达式；符号权限、多根组合、大于单次工具容量的目标集
仍需进一步证据接口。遇到容量或覆盖限制会报告证据不足，不能按不完整清单放行。

## 验证

原失败活动源码运行：
`/home/liuxv/liteagent-local-runs/active-thinking-serial-20261022T040631618920Z/`。
用其前两步回放，新完成门拒绝完成，并保留 `filesystem.find`、
`filesystem.set_permissions` 和 `tools_search`。报告：
`/home/liuxv/liteagent-local-runs/permission-completion-repair-20261022/old-failure-replay.json`。

定向测试：

```bash
PYTHONPATH=$PWD/src/adapter_versions/v2_expanded:$PWD/src/third_party/OSWorld \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  src/adapter_versions/v2_expanded/tests/test_permission_completion_outcomes.py \
  src/adapter_versions/v2_expanded/tests/test_filesystem_permission_contract.py \
  src/adapter_versions/v2_expanded/tests/test_completion_outcomes.py \
  src/adapter_versions/v2_expanded/tests/test_completion_observed_mismatch_recovery.py \
  src/adapter_versions/v2_expanded/tests/test_hybrid_gui_completion.py
```

上述 99 项通过。额外检查 episode control 和文件组织工具面，77 通过、2 失败；
这两项在修复前独立快照同样失败，分别是恢复摘要条目数断言和 retain 分类 schema
断言，未夹带无关修改。修改 Python 文件 Ruff 和 `git diff --check` 通过。

## 单题复跑

```bash
HF_ENDPOINT=https://hf-mirror.com python3 bin/run-osworld.py --orders 147 \
  --result-dir /home/liuxv/liteagent-local-runs/permission-completion-repair-20261022/run-147
```

使用 README 中 `sources.source_mode=active` 的默认配置，保存启动时源码快照，包含
尚未提交的本次修复。结果与源码完整性在运行结束后记录。

正式结果：`passed`，原始 evaluator `reward=1.0`，`generic_api_only`，5 个执行步，
耗时 295.613 秒。完整扫描返回三个文件的原生 mode，模型只修改两个原来不符合的文件；
第三轮工具面同时保留权限修改与读取，并报告未满足目标的路径、当前权限和要求。
第二个文件原本已经是 644，无须重复写入。

1. `filesystem.find`：完整扫描当前目录树，包含隐藏项。
2. `filesystem.set_permissions`：第一个文件由 755 改为 644。
3. `filesystem.set_permissions`：第三个文件由 777 改为 644。
4. `filesystem.find`：最终完整清单确认三个文件都是 644。
5. `propose_done`：完成门通过；随后终态审计确认，修复与搜索工具仍可用。

评测输出：`All files have the correct permissions.`。源码与配置完整性均为 true。
本次源码 SHA-256：`357f53dbb3d661929cffa72ae67d7d48a70759c60ff7d6f78a6c36e4d197d837`。
运行目录下的 `config.json`、`source-seal.json`、`final-integrity.json` 记录条件与完整性；
评分见 `results/results.json`，完整事件见
`results/raw/run-1/147-os-4d117223-a354-47fb-8b45-62ab1390a95f/lite_agent_events.jsonl`。

真实运行在尝试结束前已利用缺项报告完成修正，没有触发一次错误完成声明；拒绝旧失败
声明及拒绝后继续修复的路径另由旧轨迹回放和定向执行测试验证。

运行结束核对：本次修复的全部源码与运行快照一致。运行期间工作区另外出现
`model_client.py`、`test_protocol_recovery.py` 及空工具响应测试的其他修改，本次没有
纳入这些改动；正式评分始终对应上述隔离快照，不代表那些后续修改也经过单题验证。
