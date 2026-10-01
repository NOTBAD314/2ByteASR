# macOS Apple Silicon 桌面实验版（0.5.0）

当前没有公开 Mac 下载入口。此说明面向取得真实内部实验包的用户，源码脚本不是安装包。[实际验证状态](macos-validation.zh-CN.md)分别记录构建、移动启动、模型准备、Studio 与人工验证。

首轮环境为 macOS 15、Apple Silicon arm64。Intel、universal2、App Store 和更早系统均未验证。保留现有深葡萄紫界面、中文/English/日本語和工程库。

## 打开和首次使用

取得 `2ByteASR-0.5.0-macos-arm64-experimental.app.zip` 后，先核对随包 SHA256SUMS，再解压并把 `2ByteASR.app` 移到希望的位置，例如“应用程序”，通过 Finder 打开。内部包只有 ad hoc 签名，没有 Developer ID 或 Apple 公证；不需要全局关闭 Gatekeeper。

1. 打开“模型工坊”，选择 SenseVoice CPU，点击准备。首次准备需要网络与足够磁盘；界面提供下载阶段、日志、取消和重试。
2. 工坊自动准备应用管理的 Python/CPU 运行环境并下载固定版本模型，逐件校验后登记可用状态。普通用户无需输入 Homebrew、pip、Bash 或环境变量。
3. 返回首页，导入媒体，使用 SenseVoice 主识别；辅助识别与 AI 校对可以关闭，本地识别不要求云端密钥。
4. 识别完成后进入 Studio 编辑，保存工程，导出字幕或视频。已通过的层级以验证状态为准，不能凭启动成功推断全流程可用。

首轮支持路径是 SenseVoice CPU。未完成 Mac 适配的模型会显示原因并禁用 Windows 安装入口。MPS、模型算子和视频硬件加速分别探测；未验证的 MPS 不显示为正在使用 GPU。

## 文件、配置和预览

应用 bundle 内资源只读。模型、运行环境、配置、工程和日志使用 `~/Library/Application Support/2ByteASR` 的应用目录，移动或升级 `.app` 不应搬迁这些用户文件。云端密钥当前只保留在本次会话，退出后需要重新输入；不以明文写入工程、日志或源码，本地功能不依赖云端配置。

Mac 专用预览通过 Qt 解码真实视频帧显示在 Studio 内，音频由既有独立端点拥有。Windows 保留独立 mpv.exe、HWND 与 JSON 管道。单独真帧测试与完整 Studio 音画、字幕/特效同步的结论分别记录。

开发者参见[构建说明](macos-build.zh-CN.md)。真人输入法、听感与实机硬件见[简短实机检查单](macos-device-checklist.zh-CN.md)。内部包与新增私有 CI 对象未自动获准公开分发，已有第三方和素材发行条件仍单列。
