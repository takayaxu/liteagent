# Order99 协议根因与修复

本次工作从活动源码 `60f6de4` 建立独立工作树 `codex/repair99-protocol-root`。原始模型为本地 Qwen3.5-9B thinking，100 步/1800 秒，原始 OSWorld 评分不变。

## 经原始请求证实的根因

1. 历史 `order99-attempt1` 三次返回普通 assistant JSON，`tool_calls=[]`，属于未生成原生函数调用。不能把它与后一次失败混为一类。
2. 历史 `order99-attempt4` 三次均生成真实 `atomic__os_filesystem_find_8a29b208` 函数调用；严格 schema 仅允许 `kind=any`，单题提示却要求 `kind=file`。三次唯一校验错误均为 `kind: must be one of ['any']`。原回执把该轮也归入普通 JSON 伪调用是错误记录，已在本回执更正。
3. `atomic_tool_surface` 把发现路由投影成原生工具时，只取底层 params 描述，丢掉 wrapper 上追加的当前库存扫描说明。搜索结果仍展示通用 wrapper 名称和旧参数范围，进一步使模型混淆历史发现结果与当前调用契约。
4. 当前源码完整复跑发现新的确定性代码错误：精确目录搜索返回六条相关路由，通用恢复重建宽泛工具面，覆盖整理阶段已限定的单一路由。随后整理阶段访问无 properties 的 params，抛出 `KeyError: 'properties'`。真实新失败前缀已复现；修复后相同前缀恢复为单一、完整类型的文件发现工具。
5. 第二轮在完成全部发票比较后出现阶段退行：模型面对最后一张应保留发票的 skip 工具，却反复纠结已经移动成功的第一张。新增仅99且仅skip阶段生效的紧凑提示，保留真实执行事实。真实旧前缀重放一次生成正确当前对象的 skip 调用。
6. 第三轮在第二张发票核验时，模型对桌面上已移动文件的缺席陷入重复推理，9步后诊断中止。仅99核验阶段使用已有structured_observation模式省略不相关桌面截图，完整保留对账单/当前PDF文本与真实执行回执，不注入分类答案；相同原失败前缀重放生成合法retain核验调用。

## 变更

- 原生工具投影保留当前操作说明，并把当前公开 enum/const 约束明示；不替模型补参，不改变允许值，不解析普通文本伪调用，不放宽校验。
- 通用目录恢复后再次限制到整理状态已确定的当前路由，避免后续追加约束遇到无类型 params。
- 只为99启用初始库存扫描、已验证保留三段提示。当前阶段 schema 优先，使用实际原生函数名；不编码发票答案、不修改 evaluator、不增加任务专用 API。

## 验证

- 直接相关测试59通过。
- 扩展文件整理/读取测试194通过、1项基线已有失败；该失败 `test_exhaustive_organization_cannot_retain_unplaced_source_even_if_checker_agrees` 在未修改活动源码上独立复现。
- 历史3次 kind 拒绝均精确重放，唯一违例为 kind 枚举；合法 any 满足原 schema。
- 189题检查：新增阶段配置只激活99。
- 三次真实本地9B原失败前缀重放：文件发现合法原生调用；最后一张发票合法 skip 调用；第二张发票合法核验调用。三次均不执行 Adapter，仅验证模型协议。
- 运行证据：`/home/liuxv/liteagent-local-runs/repair99-rootcause-evidence`。

## 完整OSWorld复跑

- attempt1：当前源码新暴露的 KeyError，原始结果 agent_failure，完整性 source/config/osworld 均true。
- attempt2：已成功执行文件发现、全部对账单/发票读取、首张异常发票移动、两张匹配发票独立验证，前13步无协议错误。最后skip阶段推理退行，诊断中止，不记完整评分PASS/FAIL。
- attempt3：候选51595ac，9步均合法；核验阶段重复推理，诊断中止，完整性三项true，不计正式PASS/FAIL。
- attempt4：候选518244d，原始 OSWorld **PASS 1.0**，agent_done，16步/670.898秒，模型请求错误0，source/config/osworld完整性均true。自有服务已退出、容器已释放。

局限：第15步完成说明仍声称接下来读取，被门禁拒绝；第16步模型完成说明同样与已执行事实不一致，现有门禁接受后原始文件夹evaluator评分1.0。本补丁未改变完成门禁，不宣称修复所有完成说明的语义准确性。原始PASS来自实际文件整理结果，不以模型自述作为正确性证据。

结果目录：`/home/liuxv/liteagent-local-runs/repair99-rootcause-20261113-attempt{1,2,3,4}`。
