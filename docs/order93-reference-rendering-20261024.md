# Order 93：命令发现契约与参考字体兼容验证

Order 93 / `f7dfbef3-7697-431c-883a-db8583a4e4f9` 正式 `passed / reward=1.0`，候选 `45a455f`，16步、agent_done。使用昇腾 Qwen3.5-9B thinking，100步/1800秒预算；源码及配置完整性均true。`human_review=true`，93-human-v1/v2/v4获用户明确批准，另由用户明确要求按参考排版规范执行字体兼容条件。

直接argv不会展开通配符；模型最初将`*.doc`作为字面参数，退出码0但没有PDF。通用修复把这项既有契约投影到执行后的命令结果提示及执行前的工具发现说明，同时保留显式shell、程序原生模式和原参数校验，不自动改写命令或安排操作序列。

原始DOC相应段落使用Open Sans，而参考PDF使用DejaVu Sans。更新到OSWorld官方Open Sans3.003仍复现相同文本差异。受控诊断证明Open Sans不可用时自然回退DejaVu Sans，消除这组换行残差。本次根据用户明确要求，使用独立记录的字体兼容条件，不将其冒充默认字体环境的PASS。

## 复现

从干净提交检出源码，执行：

```bash
HF_ENDPOINT=https://hf-mirror.com python bin/run-osworld.py \
  --config configs/single-task-reference-fonts.json --orders 93 \
  --result-dir /absolute/path/to/new-output
```

仍须按repair_skill统一共享guest锁串行运行。本配置与正式PASS输入配置逐字节一致。

`vm.fontconfig`是通用可选环境配置：本配置的`reject_families`为`["Open Sans"]`，`expected_matches`核验`Open Sans`查询回退到`DejaVu Sans`。runner在office部署/模型执行前创建临时用户fontconfig文件，reset后重新应用，结束后核验并删除自己的文件。未配置时不改变字体环境。配置只改变字体可用性，不修改文档、参考文件或评估器，不把参考内容传给模型。

## 正式证据与实际行为

- 结果：`/home/liuxv/liteagent-local-runs/repair-93-20261024-human/run-reference-002/output/results/results.json`
- 完整性：同output目录`final-integrity.json`，两项均true。
- 源码seal：`8a0859e36a219907ff8dfb72834373e4e77e08eaa54f1ca77ff8653e9d9f365b`；集成运行源码与已验证候选完全一致。
- 原始evaluator的`result.txt`为`1.0`；完整轨迹和evaluator产物在output/results/raw/run-1/93-multi_apps-f7dfbef3-7697-431c-883a-db8583a4e4f9。
- 字体apply核验DejaVuSans，cleanup核验恢复OpenSans且临时文件不存在；无cleanup错误。
- 模型纠正了初次字面通配符错误，显式使用bash -c。多次命令超时后转换子进程仍完成了全部12PDF，模型通过filesystem.find读回12PDF，最终完成门通过。超时反馈和重复恢复仍有改进空间，本次没有修改超时、完成门或预算来掩盖这些行为。
- 19项focused测试、Ruff、diff-check、bin/check.sh通过。新发现回归检查实际tools_search摘要及后续调用schema均带通配符语义；临时fontconfig测试覆盖安装/重装/撤销、匹配失败、外部修改保护和reset顺序。

## 结果边界

默认字体环境下历史failed/0.9988200756924308及参考字体兼容条件首次failed/0.0均保留。本次PASS仅证明显式参考字体兼容条件下原始evaluator通过；未重跑全量，不宣称默认配置或历史批次总分变化。
