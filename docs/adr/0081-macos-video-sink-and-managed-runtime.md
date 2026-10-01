# ADR 0081：Mac 内嵌视频与界面管理的原生运行环境

状态：采用；原生运行结果单独记录。日期：2026-10-01。

## 背景
Windows Studio 实际由独立 mpv.exe、HWND 和 JSON 命名管道播放，原 repair 已完成关闭项。Mac 的跨进程 Cocoa 窗口不能作为 Qt 内嵌完成证据；普通创作者也不应手动搭建 Homebrew/Python 来准备本地模型。

## 决定
Mac factory 选择已有 PySide6 的 QMediaPlayer/QVideoSink 真帧后端，在生产 canvas 内绘制真实视频与既有栅格字幕/叠加层；不添加 QAudioOutput，既有 PlaybackClock 和独立 PCM/QAudioSink 仍拥有主时钟与音频。Windows 保留原 mpv actor。Qt操作限制在GUI线程，跨线程叠加层/transport经队列传递。Qt沿用准确6.9.2版本与对应现有许可材料，未增加Python-libmpv。

Mac 工坊使用 SHA 固定的官方 uv/Python/pip 自举与固定 CPU requirements，实际 pip report 的关键 wheel 逐SHA校验、pip check与生产probe通过后才登记用户级 runtime。模型复用下载源、锁定revision、逐件校验、取消与重试。资源根_MEIPASS只读，用户数据使用Application Support；冻结入口先分流子命令与freeze_support，避免递归开GUI。尚无Keychain时密钥仅会话内存保留，无明文持久化。

## 影响与验证边界
原Mac外部窗口改为Qt内嵌视频，mpv IPC工具仍可独立诊断。普通字幕走既有raster publisher；高保真Remotion输出仍沿用原抽象。完整音画/特效同步需真实工程验证，单独视频帧/无QAudioOutput测试不足以证明PCM听感。MPS availability、tensor、模型算子与VideoToolbox分别记录。当前Windows真帧探针和回归不充当Mac原生验收，见部署验证状态及私有构建HANDOFF。

Docker产品退场是当前发行输入选择改变；专用文件内部逐SHA归档，共用下载/进程/日志/路径与第三方媒体配方保留，不抹除历史测试成功或旧Git对象。
