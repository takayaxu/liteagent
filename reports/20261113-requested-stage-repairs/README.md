# 指定23题单题阶段提示修复回执

按用户题号顺序执行，GUI轨迹先跳过；本地Qwen3.5-9B thinking，100步/1800秒，原始OSWorld评分。每题独立工作树、独立guest。候选从当时活动源码HEAD建立；期间其他对话改动均保留。

**7题通过，12题因GUI暂跳过，4题尚未解决。** 通过题：77、79、82、99、136、143、174。尚未解决：126、131、163、164。未将接近1的分数改为PASS。

|题号|应用|结果|合入提交 / 备注|
|---|---|---|---|
|77|libreoffice_writer|原始评分 PASS|93a42e1|
|79|libreoffice_writer|原始评分 PASS|ba3d068|
|82|libreoffice_writer|原始评分 PASS|5c1d659|
|87|multi_apps|原GUI轨迹暂跳过||
|93|multi_apps|复跑转GUI暂跳过|candidate used GUI typing; diagnostic stopped to honor GUI skip|
|97|multi_apps|复跑转GUI暂跳过|clicked View menu in candidate; diagnostic interrupted per GUI skip|
|98|multi_apps|原GUI轨迹暂跳过||
|99|multi_apps|PASS|协议根因修复后原始评分1.0，16步；见专项回执|
|103|multi_apps|原GUI轨迹暂跳过||
|116|multi_apps|复跑转GUI暂跳过||
|123|multi_apps|原GUI轨迹暂跳过||
|125|multi_apps|复跑转GUI暂跳过|latest-source baseline clicked GUI; deferred per GUI skip|
|126|multi_apps|取帧差异未解|reward=0.8042889575503187; prompt corrected second-page-only operation, original image score unchanged; not promoted|
|128|multi_apps|原GUI轨迹暂跳过||
|130|multi_apps|原GUI轨迹暂跳过||
|131|multi_apps|PDF内容差异未解|reward=0.9957239064716509; preserved chapter-one example; original score remains below PASS; not promoted|
|136|os|原始评分 PASS|b852322|
|143|os|原始评分 PASS|604859b|
|151|thunderbird|原GUI轨迹暂跳过||
|155|thunderbird|原GUI轨迹暂跳过||
|163|vlc|音频编码差异未解|reward=0.9897855178879925; exactly reproduced old score, correct input/output, media API has no editable codec params; no prompt answer hacking|
|164|vlc|当前画面捕获差异未解|reward=0.879553906659627; used actual fractional playback time; independent frame extraction still differs; no reference timestamp guessing|
|174|vs_code|原始评分 PASS|e22f941|

所有已合入提示均采用应用领域与原始指令完全相等的触发条件。对189条原始指令逐一检查，每个模块只触发对应1题；不改变工具路由、不读取参考答案、不改变评分、预算或原始任务。

77：末尾分割叠加空右段及原有空段；提示呈现剩余句界并阻止对已独立句子再次末尾分割。独立候选及集成复验均PASS。

79：追加后猜段索引，且旧轨迹重启重复编号。提示要求读回实际新文献、沿用既有原生列表并核对交叉引用。

82：原21处斜体只改15处便完成。提示列出每个尚未确认的范围并要求全文格式查询；21处全部改为14后PASS。

136：将API放大上限150%误作系统正常最大值。提示区分正常满量程与放大，100%后PASS。

143：把相对目标./fails错误放到home。提示要求源树与目标共同以当前终端目录为根，保留相对层级后PASS。

174：擅自增加整词限制，遗漏词内text。提示要求全部字面子串替换，10处替换后PASS。

99历史失败归因更正：attempt1三次普通文本JSON、未生成原生调用；attempt4三次均为真实原生调用，但旧提示要求kind=file，与当前schema仅允许any冲突。两轮正式model_protocol_failure和原始评分均保留；后续根因修复见[专项回执](../20261113-order99-protocol-rootcause/README.md)。其余诊断中止另记。126只改第二页后原图片分仍0.80428895755；131保留既有样例后仍0.99572390647；163正确抽取MP3仍0.98978551789；164按现场时间取帧仍0.87955390666。这些不能认定仅靠阶段提示已修复。

GUI暂跳过规则本轮按原始或新轨迹出现gui_action保守执行，并不证明这些题本质上必须GUI。复跑出现GUI而转跳过：93、97、116、125。原轨迹GUI：87、98、103、123、128、130、151、155。

完整运行、失败轨迹和逐题机器可读状态保留在 `/home/liuxv/liteagent-local-runs/stage-repairs-20261113`。

repair_skill.md 末尾同步维护通过题单；该文件存在会话前未提交修改，本轮未整体提交它。
