# Docker 启动超时修复与复测

## 已确认的问题

最新全量 0670889 的中止批次 `latest-full189-12workers-20261029T155258Z` 记录5次Docker create ReadTimeout及4次公共端口锁等待超时。配置声明Docker API超时180秒，原provider却以`docker.from_env()`默认60秒创建客户端；端口锁覆盖create/start，慢调用进一步造成后续排队失败。Docker事件还证明客户端已退出后，daemon仍可创建出迟到的Created容器。主机在故障窗口出现高负载，但低层阻塞具体位于存储、调度或daemon内部仍缺乏系统日志证明，不能声称仅为CPU不足。

历史失败、原始任务、evaluator、模型及全量分数保持原样。中止批次不作为完整189题分数。

## 修复范围

- 仅在本地Adapter provider中初始化具有实际API timeout的Docker客户端，不修改pinned OSWorld。runner传入冻结protocol，并在元数据及逐题记录保存有效设置和启动耗时。
- 将create和start分开，创建前生成唯一容器名及`openapa.start_attempt`标签。create遇到响应超时/连接丢失时，只按该名字和标签查回原容器，在有界期限内核对归属；不重复提交未知结果的create。start前已保存对象句柄，start响应丢失时核验真实running状态，失败仅清理自身容器。
- 保留共同端口FileLock。默认等待预算按并发数乘以每个排队worker的create、查回、start预算计算，避免沿用固定180秒而消耗后面的题目；显式既有端口锁环境配置仍优先。
- 最终无法启动guest时记录DockerStartupError及startup证据，worker停止取下一题，supervisor在启动和轮询阶段停止整批，不重跑失败题或继续消耗后续题目。原题失败/评分失败不触发该基础设施门。

若daemon在查回期限之后才完成请求，仍属于未知的迟到创建；必须按记录的唯一attempt/本轮owner核对清理，不能无界等待、盲目重试或全局prune。源码修改不声称消除了宿主机所有性能抖动。

## 验证方案

候选运行提交`dd013936b7b61a0c4473ce9c75fef32ef8d3fba9`，独立运行目录：

`/home/liuxv/liteagent-local-runs/docker-startup-rerun-20261029T162338Z`

113项相关测试、Ruff、diff check及关键导入检查通过。测试覆盖实际timeout参数传入、无效参数拒绝、迟到create查回且只提交一次、身份不匹配拒绝、未解决创建停止、start响应超时清理、supervisor仅对Docker启动故障停止派发，并保留已有模型/网络边界检查。

先执行12个真实guest环境测试，保持12个同时在线，验证截图、egress、168个不同主机端口、12份独立可写卷及各guest同路径文件标记互不覆盖；环境测试不调用模型、不计OSWorld PASS。环境成功后，在同一干净候选源码上复跑中止批次的9道环境失败题：5、6、7、8、9、10、11、17、18。仍为原始任务/evaluator、昇腾Qwen3.5-9B thinking、100步/1800秒、原启动间隔；每题新目录一次，无resume/best-of，不回写原失败。九题配置的并发上限为12，实际非空任务分片为9，不将其称作12题同时推理。

本次不自动恢复189题全量。最终回执以本次`native/result.json`、`test-result.json`和原始results/manifest为准。

## 已完成的环境验证

12/12真实guest同时就绪并通过文件隔离回读，168个主机端口唯一、12份可写卷独立；所有客户端记录有效API timeout为180秒。最长create为25.884秒，最长guest就绪为76.219秒，最长端口锁等待2.020秒，环境超时为0。该测试的12个guest已清理。

另在真实Docker上注入“daemon已完成create、客户端丢失响应”：只提交1次create，按唯一名字和attempt标签查回同一容器，启动`/bin/true`退出0；没有启动guest，探针容器及卷已清理。证据`native/real-response-loss-probe.json`。这证明了查回分支可用，不能把注入故障当作复现了原始daemon内部阻塞。

## 正式复跑结果

北京时间2026-10-30 00:33至00:47，9/9题由原始evaluator正式判定passed、reward=1.0（Order5、6、7、8、9、10、11、17、18），环境失败为0。每题记录实际Docker API timeout=180秒，正式复跑最大create耗时12.858秒。最终source/config/repository integrity为ok，运行源码摘要`796cc6ccaf7c2f8989649d7016033b904a466ed4389345e21a23892b81c4eb9d`。所有本次owner对应容器已清理，修复池仍为默认5并发且已释放。

这确认了本次12-guest环境测试与9题复跑可行，不等于已经完成新的189题全量，也不证明宿主机的原始瞬时阻塞原因已消除。历史失败记录保留。最终数据摘要及原始results文件SHA256见[docker启动复跑回执](docker-startup-recovery-20261030-result.json)。

选择口径说明：九题按上一轮环境失败筛选，因此selection_uses_prior_outcome应为true；复制的冻结配置继承了旧全量的false字段，该字段在本次诊断中不准确。原始冻结文件和结果保持不变，本回执明确更正选择口径；9/9只报告这组定向复跑，不能外推为全量成绩。
