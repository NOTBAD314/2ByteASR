# 兔白字幕使用指南

最后核对：2026-10-15，对应公开版本 **0.7.2**。这份指南取代以前写着“0.5.0”“目前尚无公开安装包”的旧版说明；那些内容已经不适用。

[返回首页](../README_ZH.md) · [界面一览](product-demo.zh-CN.md) · [申请与设置 API](api-setup/README.md) · [English](product-guide.en.md) · [日本語](product-guide.ja.md) · [한국어](product-guide.ko.md)

**目录**：[下载哪一个](#下载哪一个) · [Windows 安装](#windows-安装) · [Mac 安装（实验版）](#mac-安装实验版) · [第一次启动](#第一次启动) · [选择识别方式](#选择识别方式) · [费用与隐私](#费用与隐私) · [识别方案与模型](#识别方案与模型) · [字幕工作台常用操作](#字幕工作台常用操作) · [输入与输出](#输入与输出) · [更新](#更新) · [常见问题](#常见问题) · [从源码运行](#从源码运行) · [反馈问题](#反馈问题)

## 下载哪一个

| 你的电脑 | 下载这个文件 | 状态 |
| --- | --- | --- |
| Windows 10 22H2（19045）或更新，64 位 | [`2ByteASR-Setup-0.7.2.exe`](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.2/2ByteASR-Setup-0.7.2.exe)（约 1 GB） | 正式版 |
| Mac：Apple 芯片（M1 及以后），macOS 15 或更新 | [`2ByteASR-0.7.2-macos-arm64-Setup.dmg`](https://github.com/NOTBAD314/2ByteASR/releases/download/v0.7.2/2ByteASR-0.7.2-macos-arm64-Setup.dmg)（约 0.5 GB） | 实验版，不支持 Intel Mac |

[Release 页面](https://github.com/NOTBAD314/2ByteASR/releases/latest)里其他附件的用途：

| 附件 | 给谁用 |
| --- | --- |
| `2ByteASR-Source-0.7.2.zip` | 想看或重新构建安装包的人：与 Windows 安装包对应的完整构建输入 |
| `2ByteASR-ThirdParty-Materials-0.7.2.zip`、`mingw-w64-libiconv-…src.tar.zst`、`…GPL-Additional-Permission.txt` | 第三方许可条款、声明和上游源码 |
| `2ByteASR-update.json(.sig)`、`2ByteASR-0.7.2-<组件>-<哈希>.zip` | 程序内更新自动使用，不需要手动下载 |
| `SHA256SUMS.txt(.sig)` | 核对下载的文件是否完整、是否由本项目发布 |

## Windows 安装

1. 下载 `2ByteASR-Setup-0.7.2.exe`。想确认文件完整，可以在下载文件夹打开 PowerShell，运行 `certutil -hashfile 2ByteASR-Setup-0.7.2.exe SHA256`，和 Release 里 `SHA256SUMS.txt` 的值比对。
2. 运行安装程序。默认装在 `%LOCALAPPDATA%\Programs\2ByteASR`，不需要管理员权限，也可以换到别的磁盘。安装后约占 1.9 GB。
3. 安装程序**没有代码签名**，Windows 可能显示“未知发布者”，或出现“Windows 已保护你的电脑”。确认文件来自本仓库的 Releases、校验值一致后，点“更多信息”→“仍要运行”即可。**不需要、也不应该关闭 SmartScreen、杀毒软件或其他安全功能。**
4. 安装完成后从开始菜单或桌面快捷方式启动。

**已经装过旧版本：** 0.6.5、0.7.0、0.7.2 在程序右上角“检查更新”，只下载变化的部分（从 0.7.2 约 50 MB）。0.6.0 及更早版本：关闭兔白字幕，运行新的安装程序**直接覆盖安装，不要先卸载**。设置、词库、工程、已下载的模型和运行环境都会保留。

**文件放在哪里：** 设置、词库、工程和日志在 `%LOCALAPPDATA%\2ByteASR`。新安装时，模型默认下载到程序所在文件夹的 `models`（程序装在 D 盘，模型也在 D 盘）；以前下载过的模型原地沿用，不会搬动。

## Mac 安装（实验版）

**适用范围：** Apple 芯片（M 系列）、macOS 14 或更新（0.8.5 起；0.8.4 及更早要 macOS 15）。**不支持 Intel Mac**。建议 16 GB 以上内存，8 GB 的 Mac 没有测过。这个版本只在 GitHub 提供的虚拟 Mac（虚拟 M1、7 GB 内存）上检查过，没有在实体 Mac 上测过。

1. 下载 DMG，可以在“终端”运行 `shasum -a 256 2ByteASR-0.7.2-macos-arm64-Setup.dmg`，和 `SHA256SUMS.txt` 比对。
2. 打开 DMG，把 `2ByteASR` 拖进“应用程序”。
3. 安装包**没有 Developer ID 签名，也没有经过 Apple 公证**。第一次打开时，在 Finder 里按住 Control 点按 App，选“打开”，再在提示里选“打开”。如果仍被拦下，到“系统设置 → 隐私与安全性”，在下方点“仍要打开”。**不需要、也不应该关闭 Gatekeeper 等系统安全设置。**
4. 以后直接打开即可。

模型、运行环境、设置、工程和日志在 `~/Library/Application Support/2ByteASR`；API Key 存在 macOS 钥匙串。Mac 版的已知限制（速度、窄窗口时工具栏重叠、未开文字复核时显示“部分降级成功”等）见 [Mac 实验版说明](deployment/macos-experimental.zh-CN.md)。

## 第一次启动

全新安装第一次启动时，会先请你选一种识别方式（只出现一次；之后可以从首页提示或“说明”菜单重新打开）：

| 选项 | 用什么识别 | 第一次要下载 | 适合 |
| --- | --- | --- | --- |
| **本机识别**（Windows） | MOSS + FireRedASR2-AED + Qwen3-ASR | 模型约 11 GB，另加运行环境（含 CUDA 版 PyTorch） | 有 NVIDIA 显卡；要分说话人、逐字时间和多模型对照 |
| **云端识别** | MOSS Pro 云端（MOSI）、阿里云百炼、Qwen Cloud 等 | 不下载模型 | 没有显卡、想快速出字幕；需要 API Key，按用量付费 |
| **轻量本机** | SenseVoice（CPU） | 约 0.9 GB 加运行环境 | 没有显卡、不想上传；较慢，不分说话人 |
| **Mac 本机识别**（Apple 芯片） | MLX 版 Qwen3-ASR + 对齐模型 | 约 2.3 GB 加运行环境 | Mac 上不想上传的情况；社区实现，未在实体 Mac 验收 |

选好后，本机类选项会打开“模型工坊”开始下载；云端选项会打开“申请与设置 API”，按步骤申请并填写 Key。没有 NVIDIA 显卡时，“本机识别”这张卡会直接标出“这台电脑没有可用的 NVIDIA 显卡”，不能选。

想先熟悉界面：点右上角“说明 → 新手教学”。31 步带动画的教学用范例工程演示首页和字幕工作台，可以自己操作，也可以点“帮我做”；不需要模型，不上传、不花钱。

## 选择识别方式

| 你的电脑 | 推荐 | 说话人 | 逐字时间 | 多模型候选 |
| --- | --- | --- | --- | --- |
| Windows + NVIDIA 显卡 | 本机 MOSS + FireRedASR2-AED + Qwen3-ASR | 有（MOSS） | 有（FireRed 实测） | 三份 |
| Windows，没有 NVIDIA 显卡 | 云端识别 | MOSS Pro 云端、Qwen-Audio 3.1 有；其他服务没有 | 百炼 / Qwen Cloud 有；只回传句段时间的服务为“估算” | 没有 |
| Windows，没有 NVIDIA 显卡、不想上传 | 轻量本机（SenseVoice） | 没有 | 加装本机 Qwen3 对齐模型（可用 CPU）后有 | 没有 |
| 云端识别 + 本机对齐 | 云端出文字，本机 Qwen3 对齐模型补时间 | 取决于云端服务 | 有（本机对齐，不上传） | 没有 |
| Mac（Apple 芯片） | Mac 本机识别（MLX），或在模型工坊准备 MOSS + FireRed（Apple GPU），或云端 | MOSS 有 | 有 | MOSS + FireRed 两份 |

说明：

- **需要 NVIDIA 显卡的组件**（Windows）：MOSS、FireRedASR2-AED、Qwen3-ASR 1.7B 和 FireRedASR2-LLM。首页角色卡、首页提示和开始识别前都会说明，并给出“换成能用的方式”。
- **能用 CPU 的组件**：SenseVoice、Qwen3-ForcedAligner（对齐，较慢）；Whisper、Paraformer、Fun-ASR 也会在没有显卡时改用 CPU，但没有在 CPU 上做过完整测试。
- **云端服务的差别**（详见[申请与设置 API](api-setup/README.md)）：MOSS Pro 云端只要一把 Key、能分说话人，但只有句段时间；百炼 / Qwen Cloud 录音文件识别有字词时间，其中 Qwen-Audio 3.1 能分说话人，正式使用需要你自己的 OSS 私有存储空间。每次开始前，程序会列出用哪个引擎、时间从哪里来、音频上传到哪里和大概费用；不会悄悄改用付费服务。
- **Mac**：MOSS + FireRed 在虚拟 Mac 上约比实时慢 3–4 倍；只能在 NVIDIA 上运行的组件会标出“这台电脑不能运行”。

## 费用与隐私

- **软件本身免费**，没有付费功能、注册或订阅。
- **本机识别**：模型下载后可以离线使用，影音不离开电脑。
- **云端识别**：音频会上传到你选的服务商，按服务商的规则计费（价格以服务商页面为准）。程序不会替你开通或付费。
- **文字 AI**（DeepSeek、阿里云百炼、OpenAI、Gemini、xAI 或自定义兼容服务，都用你自己的 Key）：只发送字幕文字。用到它的功能有 AI 断句、AI 校对、“AI 词库校对”的 AI 模式、字幕翻译（中文、日语、英语字幕可译成简体中文、繁體中文、英语、日语或韩语）、AI 建词和联网更新词库、直播切片的 AI 排序、AI 字幕设计。没有配置时，这些功能不可用或改用本地规则，识别、编辑和导出照常。
- **外部 AI（MCP）**：默认关闭。开启后，你的 AI 客户端会读取当前工程的字幕文字，并发送给该客户端所用的 AI 服务。

## 识别方案与模型

一次识别最多有三种分工：

| 分工 | 做什么 | 常用方案 |
| --- | --- | --- |
| 主力转写 | 写出文字；MOSS 和部分云端服务还会区分说话人 | MOSS、SenseVoice、Whisper、Qwen3-ASR、云端服务 |
| 字幕时间轴 | 给每个字标上起止时间，断句和切分沿着字的边界 | FireRedASR2-AED、Qwen3-ForcedAligner、Paraformer |
| 文字复核 | 用另一个模型再听一遍，列出写法不同的地方，在工作台里对照采用 | Qwen3-ASR 等本地或在线方案 |

- 首页“识别方案”可以按目标（质量优先、快速轻量、在线、日语推荐、英语推荐等）选现成组合，也可以每个角色自己换。
- 模型在“模型工坊”下载，卡片上写着大小、运行方式和“参考指数”（1–100 的相对选择参考，**不是识别正确率**）。
- 下载来源依次是 ModelScope（固定版本）→ Hugging Face 官方 → hf-mirror.com，每个文件都要和锁定的 SHA-256 一致，支持断点续传。
- 本机模型清单：MOSS-Transcribe-Diarize、FireRedASR2-AED、Qwen3-ASR 1.7B、SenseVoice Small、Paraformer Large、Whisper large-v3-turbo、Fun-ASR Nano、FireRedASR2-LLM、GLM-ASR-Nano、Canary-Qwen-2.5B（英语）、Qwen3-ForcedAligner 0.6B、日语 CTC 对齐模型，以及 Mac 上的 MLX 版 Qwen3-ASR 与对齐模型。各模型的许可见[模型许可表](../licenses/MODELS.md)。

## 字幕工作台常用操作

| 想做的事 | 怎么做 |
| --- | --- |
| 切开一条字幕 | 剃刀工具（C），移动看预览，点击切开；开启吸附（S）时停在字与字之间 |
| 合并字幕 | 合并工具（B），或 Ctrl+Shift+M 与下一条合并 |
| 撤销 / 重做 | Ctrl+Z / Ctrl+Y |
| 对照候选、采用别的写法 | R 进入审核模式，1–4 采用并跳到下一条 |
| 改说话人名称、颜色、默认样式 | 说话人管理；或把字幕拖到另一条说话人轨 |
| 剪掉一段视频 | 选中视频片段后 Q / W 波纹剪除，或右键片段删除；“剪辑助手”可检测口播停顿 |
| 找直播切片 | “剪辑助手”里分析字幕和弹幕 XML，挑好候选后“生成剪辑” |
| 用词库校对 | 工作台左上“AI 校对”或完成页“AI 词库校对…” |
| 已有文稿对时间 | 工作台“匹配文稿”，先预览再替换 |
| 改快捷键 | 设置 → 快捷键 |

快捷键都可以自己改，这里写的是默认值。

**AI 字幕设计（进阶，需要 AI 服务）：** 工作台的“AI设计”页可以按描述生成三个可编辑的字幕视觉和动效候选，需要你配置的 AI 服务。普通的字体、描边、位置和入场退场动效预设不需要 AI。[界面一览](product-demo.zh-CN.md#ai-字幕设计范例)里的木刻和 CRT 两个效果是用 AI 字幕设计做出的范例作品，不是内置预设。

## 输入与输出

| 用途 | 格式 |
| --- | --- |
| 视频输入 | MP4、MOV、MKV、WebM、FLV、AVI |
| 音频输入 | MP3、WAV、M4A、FLAC、AAC |
| 工作台导入字幕 | SRT、ASS |
| 弹幕（直播切片用） | B 站格式的弹幕 XML（本地文件） |
| 字幕导出 | SRT、ASS、TXT、JSON；说话人合并、分别导出或两者都要；有翻译时可导出原文、译文或双语 SRT |
| 视频导出 | MP4、MKV、MOV，字幕压进画面；整段或入点到出点 |
| 其他 | 画面截图（PNG / JPG）、封面；工程文件 `.2byteproj` 保存全部编辑状态 |

## 更新

- **Windows 0.6.5 及以后**：程序右上角“检查更新”。只下载有变化的部分，下载后逐个校验，等你保存工程并同意退出后才替换；任何一步失败都会恢复原版本。
- **Windows 0.6.0 及更早**：下载新的安装程序直接覆盖安装，不要先卸载。
- **Mac**：下载新的 DMG，拖进“应用程序”覆盖旧版。

完整说明见 [UPDATING.md](../UPDATING.md)。

## 常见问题

**安装时提示“未知发布者”或“Windows 已保护你的电脑”。** 安装程序没有代码签名。确认是从本仓库 Releases 下载、校验值一致后，点“更多信息”→“仍要运行”。不要关闭杀毒软件或 SmartScreen。

**首页提示“需要 NVIDIA 显卡”。** 当前组合里有只能在 NVIDIA 显卡上运行的组件。点“换成能用的方式”，或参考[选择识别方式](#选择识别方式)换成云端识别或轻量本机。

**模型下载很慢或中断。** 下载支持断点续传，并会依次尝试 ModelScope、Hugging Face 和 hf-mirror.com；下载窗口会显示当前来源和换源原因。所有文件都要通过 SHA-256 校验才会使用。

**识别完显示“有需复核项”。** 识别执行完成，不代表每一处都确认无误。打开字幕工作台的审核模式（R），按“建议确认”逐条检查即可。

**字幕时间旁边写着“估算”。** 这条字幕没有实测的逐字时间（例如云端服务只回传句段时间），切分时文字分界按比例估算。加装本机 Qwen3 对齐模型，或换用有字词时间的服务，可以得到实测时间。

**卸载后我的资料还在吗？** 在。卸载只删除安装程序装进去的程序文件；之后下载的模型、工程、设置和词库都会保留，更新和覆盖安装也一样。需要彻底删除时，手动删除 `%LOCALAPPDATA%\2ByteASR` 和程序文件夹里的 `models`（Mac 为 `~/Library/Application Support/2ByteASR`）。

## 从源码运行

```powershell
git clone https://github.com/NOTBAD314/2ByteASR.git
cd 2ByteASR
.\setup_environment.bat
.\.venv-main\Scripts\python.exe quick_start.py
```

- `main` 分支是程序源码；与 0.7.2 安装包对应的构建来源是 tag `v0.7.2`，完整构建输入在 Release 的 `2ByteASR-Source-0.7.2.zip`，详见 [0.7.2 发布说明的“源码与校验”](releases/0.7.2.md#源码与校验)。
- 开发和测试约定见[贡献指南](../CONTRIBUTING.md)。
- [BUILD_FROM_SOURCE.md](../BUILD_FROM_SOURCE.md)、[SOURCE_ONLY_SCOPE.md](../SOURCE_ONLY_SCOPE.md) 和 [SOURCE_DELIVERY.md](../SOURCE_DELIVERY.md) 写于 0.5.0 阶段，是当时的源码范围与构建记录，尚未按 0.7.2 更新。

## 反馈问题

在 [Issues](https://github.com/NOTBAD314/2ByteASR/issues) 附上版本、操作系统、所用的识别方案、复现步骤和截图。识别结果有问题时，完成页的“运行日志”可以一并附上（注意先删去其中的本机路径等个人信息）。

[返回首页](../README_ZH.md) · [界面一览](product-demo.zh-CN.md) · [第三方组件](../THIRD_PARTY_NOTICES.md)
