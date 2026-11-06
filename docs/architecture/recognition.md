# 识别环境、有效来源与结果交付

2026-11-06，说明 #12–#15 本轮改变的边界，不改识别结果、工程或 settings schema。

`subtitle_core.check_runtime` 只验证 GUI/队列使用的依赖；Pillow 字体模块在耗时识别前验证。模型包由 `asr.check_selected_worker_dependencies` 调用真实 worker 解释器选择器，复用 `environment_probe.py` 的有界子进程启动与依赖探测；预检不加载模型。真实 worker 保留导入、启动和执行失败检测，错误指出解释器和模型工坊。源码 MOSS 的部分 ECAPA 仍在队列进程，speechbrain 检查保留。

`cue_cleanup.prepare_effective_sources` 只用于识别来源；严格的纯控制标记在校对/分组快照与缓存前排除，原 ASR 响应、审计和保留行的ID不变。旧派生字幕的清理必须先通过完整来源契约并确认source_spans，不能按文字/时间相似猜归属。真正文字恢复按规范化正文偏移回到原文行和标点边界；完整来源、说话人、时间和protected_boundary校验保留。

污染的终态/分片缓存逐项拒绝，不清除原 ASR 或正常缓存。全静默需要无语音证据；unk不是静音。原工程加载/保存/导出不调用识别来源过滤。

布局与工程写盘共同进入保存异常边界；失败保留旧工程、恢复副本和delivery检查点，交付状态为needs_recovery。没有成功提交的工程不得成为成功引用。

[执行与验收](../exec-plans/completed/2026-11-06-github-issues-11-15.md)
