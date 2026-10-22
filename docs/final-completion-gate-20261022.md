# 最终完成审查与条件修复

分支：`codex/api-split-liuxv`。这次调整完成判定的优先级，不改任务、evaluator 或 golden。

## 协议

执行和读取结果 → 对照全部用户要求自审 → `propose_done` 的完整证据门禁。

- 原生检查发现缺少证据或实际结果不符：报告具体目标、要求、观察值及修复动作，
  开放检查、修改、搜索工具。无需模型先承认错误。
- 原生证据已满足：提供最终声明和具体偏差报告 `completion_revise`，不再普通读取。
  模型使用已有最终观察逐条自审；发现偏差时先报告观察、要求与纠正方案，再进入修复。
- `propose_done` 检查模型声明格式、未完成声明、必要动作、保存、最终回读、原生对象及
  可解析的对象定义和输出值。全部通过直接 `done=True`，不创建成功后的审计轮。
- 审查失败才进入修复；修复由模型选择公开工具及参数，执行后重新收集证据并审查。
  `completion_revise` 报告的偏差不会被读取、保存或重复声明直接抹掉。
- 完成后的工具面为空，执行器也拒绝继续调用；Runner 优先处理成功终态，避免被当轮
  时间或停滞判定覆盖。失败控制的旧确认机制继续保留，不影响成功完成路径。

工作流上下文在证据齐备时显示 `completion_review`，完成时显示 `complete`，避免通用
源读取阶段的 `target_action_discovery` 与最终审查相矛盾。

## 修复原因

此前第 4 题在第 11 步已经通过门禁，但 `pending_terminal` 要求再请求模型一轮。
保留普通检查工具后，任何不同工具都会无条件取消待完成状态；模型没有报告具体差异，
仍可通过 `workbook.inspect` 开启新执行。五次通过的声明分别被下一轮检查撤销。
这些检查与第 8 步的原生结果完全相同。一次软重启后仍循环，最终 `stalled_no_progress`；
原始 evaluator 因文件本来已正确而给出 1.0。现在成功门禁本身就是最后一个状态转换。

## 验证

完成结果、权限、已观察偏差修复、GUI、声明契约及剪贴板工具面：133 项通过。
权限工具契约、episode control 与 Qwen 空参数工具约束：24 项通过，1 项失败。
失败为恢复摘要条目数断言，修复前独立运行快照同样失败。
`test_recovery_surface.py` 本来无法收集，引用了已退役的 `build_repair_contract`；未修改该文件。
本次修改 Python 文件 Ruff 和 `git diff --check` 通过。

回放证据位于运行目录的 `gate-replay.json`：

- 旧第 4 题第 10 步的完整证据：直接完成，没有待审计标记或后续工具。
- 旧第 147 题只修改一个文件的失败轨迹：拒绝，报告未核验模式和不完整扫描，保留修复工具。
- 第 147 题完整最终清单：直接完成，不再请求模型确认。

## 活动源码实跑

```bash
HF_ENDPOINT=https://hf-mirror.com python3 bin/run-osworld.py --orders 4 147 \
  --result-dir /home/liuxv/liteagent-local-runs/final-completion-gate-20261022
```

使用启动时的活动源码快照，包含先前尚未提交的 Qwen XML 分隔符修复；这些其他改动
不属于本次完成门修改。正式评分以该隔离快照和 `final-integrity.json` 为准。
结果文件为 `results/results.json`，每题原始事件和请求位于 `results/raw/run-1/`。

第 4 题 `passed`，reward=1.0，14 步，`termination_reason=agent_done`。
第 9 步因缺少最终保存被门禁拒绝；第 10 步保存，第 11 步检查，第 12、13 步分别回读
两张透视表，第 14 步审查通过并结束。只有 14 次模型请求，没有成功后的第 15 次审计。

第 147 题 `passed`，reward=1.0，5 步，`termination_reason=agent_done`。
完整扫描 → 修改两个权限不符文件 → 完整扫描确认所有普通文件为 0644 → 完成。
只有 5 次模型请求，没有成功后的第 6 次审计。

两题都以 `propose_done` 为最后一条事件，`audit_required=false`，没有 `terminal_audit`。
源码与配置完整性均为 true；本次修改源码与实跑快照逐文件一致。
快照 SHA-256：`81c71075e1ef1d66d8212bdc1c164b545a22fcfa89db4a315a3bc10efe3a4ef1`。
运行目录的 `verification-summary.json` 汇总评分、步数、请求次数和最后事件。

## 能力边界

这次修复确定的是状态转换和修复优先级，不声称现有规则已覆盖任意自然语言任务。
原生结果语义核验目前仍以已有 Calc 对象定义/结果及明确数值权限要求等检查为限；
其他任务仍依赖已有语义检查和模型提交完成声明前的逐条自审。不能把 evaluator 的
评分或 golden 当作运行时门禁证据，也不能把工具内部 `verification.passed` 等同于整题完成。
