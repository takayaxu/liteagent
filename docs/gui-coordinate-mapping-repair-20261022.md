# GUI 截图坐标换算

119 题失败轨迹确认：桌面截图为 1920×1080，模型请求里的 JPEG 被缩小到
1280×720，但 GUI 执行器将模型坐标原样传入 PyAutoGUI，未声明或转换坐标系。
原始证据保留在 `/home/liuxv/liteagent-local-runs/119-root-cause-20261022/evidence.json`。

模型请求现在声明坐标以实际编码的截图像素为单位，原点在左上角；模型无需
自行换算桌面分辨率。每个直接 `gui_action` 提案绑定生成时的截图尺寸与桌面尺寸。
执行器校验该尺寸与当前截图一致后，按横纵比例分别转换 `x/y/to_x/to_y`，
再生成 PyAutoGUI 命令。越界坐标拒绝执行；小截图不放大；拖拽起终点均转换。
委托 Holo 的 `gui_request` 继续使用其自身坐标协议。

轨迹中的 `arguments_raw` 和 `arguments` 保留模型原值，`gui_arguments` 保存
实际桌面坐标，`gui_coordinate_frame` 保存两种分辨率，`command` 保存执行命令。
重复操作检查使用实际桌面坐标。

验证：坐标换算、数字参数、GUI 完成、Holo 协议及协议恢复测试共 122 项通过，
另两项协议测试失败已用改动前版本核对；`bin/check.sh` 通过。
隔离 Xvfb 桌面的实际 Tk/PyAutoGUI 点击验证：模型 `(818,230)` 换算为
`(1227,345)` 后命中该位置的目标，未经换算则未命中。验证结果位于
`/home/liuxv/liteagent-local-runs/gui-coordinate-validation-20261022/live-click-result.json`。

本次保证坐标转换与执行一致，不代表模型一定选对视觉目标；未重跑 119 的
完整 OSWorld 任务，不更新其既有评分。
