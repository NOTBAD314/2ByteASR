# macOS Apple Silicon 实验版（0.7.1）

0.7.1 起 GitHub Release 提供 Mac 安装包 `2ByteASR-0.7.1-macos-arm64-Setup.dmg`。它和 Windows 安装包出自同一个发布提交（tag `v0.7.1`）。**这是实验版**：只在 GitHub 提供的 macOS 15 虚拟 Mac 上用安装版检查过，没有在实体 Mac 上测过。

## 适用范围

- **只支持 Apple 芯片（M 系列）、macOS 14 及以上**（0.8.5 起；0.8.4 及更早要 macOS 15）。 不支持 Intel Mac：没有 Intel 版程序包，PyTorch 与 MLX 也没有可用的 Intel 版本。
- 云端识别（自备服务商账号与 API Key）不需要本地模型，也不需要 NVIDIA 显卡。
- 本地识别：模型工坊可准备 MOSS（文字 + 说话人）与 FireRedASR2-AED（字级时间），在这台 Mac 的 Apple GPU 上用自带样本实际跑一次，通过才启用；也可用 SenseVoice（CPU）与社区实现的 MLX 方案。只能在 NVIDIA CUDA 上运行的组件，在开始前就会标出“这台电脑不能运行”并说明原因，不会当成 Mac 已支持。
- 内存建议 16 GB 以上；8 GB 的 Mac 没有实测。

## 安装与第一次打开

1. 下载 DMG，用 Release 里的 `SHA256SUMS.txt` 核对：在“终端”运行 `shasum -a 256 2ByteASR-0.7.1-macos-arm64-Setup.dmg`。
2. 打开 DMG，把 `2ByteASR` 拖进“应用程序”。
3. **安装包没有 Developer ID 签名，也没有经过 Apple 公证。** 第一次打开时，在 Finder 里按住 Control 点按 App，选“打开”，再在提示里选“打开”。如果仍被拦下，到“系统设置 → 隐私与安全性”，在下方点“仍要打开”。**不需要、也不应该关闭系统安全设置（Gatekeeper）。**
4. 以后直接打开即可。新版本照同样方式拖进“应用程序”覆盖旧版。

## 发布前检查过什么

在 GitHub 的 macOS 15 虚拟 Mac（虚拟 M1、3 核、7 GB 内存）上，用从 DMG 拖装的程序：

- 启动、新建空工程、保存与重新打开；视频真实帧与硬件探测。
- 模型工坊准备 MOSS + FireRed（含语音段检测与说话人模型，在 Apple GPU 实跑样本）；首页识别 → 工作台改字、剪切、保存、重开 → 导出四种字幕与视频并解码核对；重启后再识别，运行环境与模型不变。
- 云端识别整条流程（安装版的云端组件，连本机模拟服务器，不上传、不计费）；macOS 钥匙串真实存取删（API Key 只存在钥匙串，数据目录没有明文）；MLX 准备、识别与对齐。

每次的具体结果见 Release 说明。

## 已知限制

- 虚拟 Mac 上 MOSS + FireRed 约慢于实时 3–4 倍，FireRed 每次载入 2–3 分钟；实体 M 系列 Mac 一般更快，但没有实测。
- 没开文字复核时，这条方案的识别状态显示“部分降级成功”（每条字幕只有一个来源，文字与字时间都正常）。
- 窗口很窄时，工作台顶部工具栏会重叠。
- Mac 的国内备用下载来源只在离线测试里验证过，没有在大陆网络的 Mac 上跑过。
- MOSS Pro 云端（MOSI）与 Qwen Cloud 没有用真实付费调用验证。

## 文件放在哪里

程序包内的资源只读。模型、运行环境、设置、工程和日志在 `~/Library/Application Support/2ByteASR`；移动或升级 App 不会动这些文件。API Key 存在 macOS 钥匙串；钥匙串不可用时只保留到程序关闭，不写明文。

Mac 版的视频预览由 Qt 解码真实视频帧显示在工作台内；Windows 版用独立的 mpv。

开发者参见[构建说明](macos-build.zh-CN.md)；实机检查项见[实机检查单](macos-device-checklist.zh-CN.md)。第三方组件的分发状态见 `licenses/DISTRIBUTION-STATUS.md` 的 0.7.1 节。
