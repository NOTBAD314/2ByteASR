<div align="center">
<img src="assets/2byteasr-icon-transparent.png" width="100" alt="兔白字幕原角色图标" />

# 2ByteASR · 兔白字幕

**准确识别字幕，轻松剪辑视频。**

免费的字幕识别与视频编辑工具，支持本地部署。<br/>
从识别、校对到特效字幕与视频输出，一站完成。

[源码范围](SOURCE_ONLY_SCOPE.md) · [完整演示](docs/product-demo.zh-CN.md) · [快速开始](#下载与快速开始)

[中文](README.md) · [English](README_EN.md) · [日本語](README_JA.md)
</div>

![兔白字幕主页：素材、字幕工作台与三种识别角色](docs/assets/readme/overview.png)

*从主页开始：准备素材与识别方案，或进入字幕工作台继续编辑。*

## 一份字幕，三种分工

平台状态：Windows 提供桌面工作流，当前尚无公开安装包；[macOS 原生桌面实验版](docs/deployment/macos-experimental.zh-CN.md)开发中，首轮目标为 Apple Silicon arm64。实际构建与验收状态见对应文档。

转写先把话写出来，时间轴把字词落到对应位置，复核让同一句的不同结果可以放在一起比较。按素材和设备选择组合，再按需开启 AI 断句。

| 角色 | 帮你做什么 | 代表方案 |
| --- | --- | --- |
| 主力转写 | 得到文本；支持说话人区分的方案还可提供分轨线索 | MOSS、SenseVoice、Whisper |
| 字词时间轴 | 定位边界，让字幕切分与画面更合拍 | FireRedASR2-AED、Paraformer；已有文本可用独立对齐器 |
| 文字复核 | 对照另一份文本，处理听不清或有分歧的词 | Qwen3-ASR 等本地／在线方案 |

![说话人 A 的两句话与 B 的回应分别进入对应字幕轨](docs/assets/readme/speaker-tracks.gif)

*A → B → A，逐句识别，分轨呈现。*

## 切到字词边界，调整字幕节奏

沿着长句选择切点，剃刀切开后，时间轴立即变成对应的字幕片段。切得不合适，就撤销或合并，继续调整。

![在自然长句上选点、切成三段，时间轴同步分开，再逐次撤销](docs/assets/readme/word-split.gif)

## 同一句，对照候选再采用

“人物”“任务”还是“战术”？在同一条字幕下看清差异与来源，选中后采用，当前字幕随之更新。

![比较同句候选，采用任务后当前字幕更新](docs/assets/readme/candidate-review.gif)

## 游戏术语库：整理一次，反复使用

角色名、别名和常见错词，按游戏归档。核对参考词与来源，确认后再用于识别；换一段素材，不必从头整理。

![术语库的游戏分类、来源、确认状态与批量维护界面](docs/assets/readme/glossary.png)

## 直播切片与特效字幕

**先找到值得剪的片段。** 结合直播弹幕 XML 和字幕，找到“残血反杀”“翻车爆笑”“弹幕集中”等候选。选择左侧片段，右侧理由和时间轴选区一起更新，选好后加入剪辑。

![切换直播候选、查看理由与时间轴选区，再加入剪辑](docs/assets/readme/live-clips.gif)

**再让一句话有自己的表情。** 字体、材质、入场与退场一起构成字幕作品。已有样式可以复用，也可以配置 AI 设计服务生成并修改。字幕设计和直播切片可以分别使用。

![木刻压印与 CRT 计分屏完整入场、停留和退场](docs/assets/readme/caption-effects.gif)

*木刻压印：木板扣合、刻印显字、收拢退场。CRT 计分屏：通电、磷光显字、关屏退场。*

## 下载与快速开始

面向 **Windows x64**。本仓库提供独立源码范围，**当前尚无公开安装包**；内部测试候选不作为公开下载版本。此范围不是现有完整 Setup 的全部对应源码，也未验证可直接完整打包。详见[源码范围与构建条件](SOURCE_ONLY_SCOPE.md)。

1. **准备源码。** 先阅读[源码范围与构建条件](SOURCE_ONLY_SCOPE.md)，在独立开发环境中准备有权使用的外部依赖；以下为依赖准备后的产品使用流程。
2. **准备识别方案。** 在模型工坊准备本地模型，或配置自己的在线服务。
3. **导入并识别。** 选择素材、内容与词库，检查转写、字词时间和说话人结果。
4. **进入兔白字幕 Studio。** 校对、拆分或合并，调整字幕与画面，再导出字幕、文稿或压制成片。

默认采用**深葡萄紫**主题，也可以在外观设置中选择喜欢的配色。

### 必要条件

- **系统：** Windows 10 22H2（19045）及以上的 x64 系统。
- **本地识别：** 模型权重在模型工坊按需下载。SenseVoice 支持 CPU；MOSS 等方案使用 NVIDIA CUDA，配置要求可在模型工坊查看。
- **在线服务：** 使用自己的账号或 API 密钥，按服务提供方的规则计费。
- **输出：** SRT、ASS、TXT、JSON、说话人分轨，以及 MP4、MKV、MOV 视频。

[安装与首次使用](docs/product-guide.zh-CN.md#安装与准备) · [模型、格式与高级使用](docs/product-guide.zh-CN.md) · [源码范围与构建条件](SOURCE_ONLY_SCOPE.md)

## 更多文档与反馈

[界面与功能展示](docs/product-demo.zh-CN.md) · [从源码运行与构建](docs/product-guide.zh-CN.md#从源码运行与构建) · [架构](ARCHITECTURE.md) · [反馈问题](https://github.com/NOTBAD314/2ByteASR/issues)

反馈时附上版本、模型、复现步骤和截图，方便定位问题。

项目自有代码采用 **GPL-3.0-only**（[标准英文全文](LICENSE) / [适用范围](PROJECT_LICENSE.md)）。官方版本免费提供；允许依 GPL 商用、修改和收费分发，分发时须履行对应源码等条件。私人修改无需公开，普通字幕、视频和图片不会仅因使用本软件生成而自动适用 GPL。第三方内容见 [第三方说明](THIRD_PARTY_NOTICES.md)，对应版本源码见 [交付说明](SOURCE_DELIVERY.md)。
