# 第三方组件、许可与来源声明

## 2026-10-26 链接下载开发功能

- 参考并移植 [imsyy/yt-dlp-gui](https://github.com/imsyy/yt-dlp-gui/tree/e3cd1df342c1dd0f543b309cf305210a588a461c) 的字幕来源分组、排除 live_chat、独立工具管理与阶段通知模式。固定 commit：e3cd1df342c1dd0f543b309cf305210a588a461c。实际改写位置：twobyteasr/media/link_catalog.py、link_download.py、link_tools.py 与 app/link_download_dialog.py；未引入 Vue/Tauri 运行时。版权与 [MIT 全文](licenses/yt-dlp-gui-MIT.txt) 保留。
- 已阅读的参考文件：src/components/home/SubtitleCard.vue、src/pages/toolbox/Subtitles.vue、src/utils/subtitle.ts、src-tauri/src/commands/toolbox/subtitles.rs、commands/download/arguments.rs、commands/external_tools/ytdlp.rs。主要差异：原语/自动翻译分开；同语言人工/自动用实际端点选择；不聚合列表轨道；不按行号合并双语；不把回退格式改扩展名；原稿、标准化和工程编辑三层分开。
- 下载引擎为 [yt-dlp 2026.10.21](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.21)，EJS 0.8.0（官方可执行文件内置）。源码 [Unlicense](licenses/yt-dlp-Unlicense.txt)，官方 PyInstaller 可执行文件整体为 GPL-3.0-or-later，内含组件分别保留 [上游完整第三方声明](licenses/yt-dlp-THIRD_PARTY_LICENSES.txt)；不可把独立 EXE 只标成 Unlicense。EJS 的 [许可](licenses/yt-dlp-ejs-Unlicense.txt) 另存，内含 astring/Meriyah 的 MIT/ISC 原文也在上游第三方声明内。
- Windows/macOS 文件 URL、大小、SHA-256 固定在 dependencies.lock.json 的 tools.yt_dlp；原文件不修改，通过参数数组作为独立进程使用。Node 与 FFmpeg 复用应用受管版本及既有声明。工具随应用锁表更新；首次缺失时从官方地址安装到私有运行库，可校验/修复。没有发布或替换日常包，本次源码验证不能替代新的安装包验收。

> 2026-10-14：0.7.1 的 Windows 安装包随附第三方组件与 0.7.0 相同；第一次附带的 macOS DMG（Apple Silicon）媒体工具来自固定 Homebrew 提交，现状与仍缺的材料见 [分发状态](licenses/DISTRIBUTION-STATUS.md) 的 0.7.1 节。
>
> 2026-10-13：0.7.0 新增随安装包附带的组件与可下载模型见文末“0.7.0 新增”一节；下方原有记录与证据等级不变。

本声明随 0.2.6-test.3 内部候选提供。自有代码按 [GPL-3.0-only](PROJECT_LICENSE.md) 授权；第三方保留原版权、许可及权利。基线组件证据来自品牌 test.2（SHA `0d2796a1…c88878c`）；当前构建保留既有运行依赖并精确排除四个冗余 Qt 文件，新候选身份与实际入包结果另见同版本交付回执。旧 Setup 原样保留，不自动包含新增材料。

[当前 GPL 路线及未解决项](licenses/GPL3_ROUTE.md)区分旧禁售冲突撤销、实际修正、对应源码缺口及组合许可问题。Remotion/GSAP、素材权利和第三方源码缺口仍开放，此声明不授予未取得权利，也不表示整个组合已可公开分发。

## 每个组件的详细声明

[完整组件目录](licenses/COMPONENTS.md)逐项提供623条分层记录的名称/准确版本、范围、实际路径、版权证据、官方与版本来源、本地原文位置、用途/集成、修改/补丁、对应源码义务、证据等级及缺口。记录含重复层级和未查明项，不代表604种软件均已获得法律核实。

[机器索引](licenses/component-index.json)提供原文、NOTICE、例外和源码材料的逐文件SHA/来源；[模型表](licenses/MODELS.md)区分代码、权重、配置/词表；[源码说明](licenses/SOURCES.md)说明实际可取得内容与未完成范围；[分发状态](licenses/DISTRIBUTION-STATUS.md)保留开放事项。

- **A**：随拟公开源码分发的代码/资源。开发树与远端main不是同一源码发行树。
- **B**：选定Setup实际附带，包括离线wheel和实际入包的开发依赖。
- **C**：安装或模型首次准备时下载。
- **D**：用户另行配置的外部工具/服务。
- **E**：仅开发使用，未实际分发；被复制进产品的产出另列。

原文位于`licenses/materials/`，已取得的源码/补丁位于`licenses/source-materials/`。版权归各原文和源文件列明的权利人，完整版权/NOTICE未用通用许可证摘要替代；没有原文的项明确列“未取得”，不放空文件。

## 重点组件导航

下表是导航，逐项完整版本证据、版权和具体全文路径见组件目录。

| 组件及版本 | 范围与用途 | 实际许可/条件和材料 |
|---|---|---|
| CPython3.10.11 | B，嵌入`python310.dll` | PSF及历史许可；`materials/python/3.10.11/`；[官方版本](https://github.com/python/cpython/tree/v3.10.11) |
| PyInstaller bootloader6.22.2 | B的EXE引导器，构建工具为E | 原COPYING及bootloader例外已保留，不能删例外只称GPL；`materials/pyinstaller/6.22.2/`；[对应版本](https://github.com/pyinstaller/pyinstaller/tree/v6.22.2) |
| PySide6/Shiboken/Qt6.9.2 | B，Python绑定/动态DLL | 各模块分别判断LGPL/GPL/商业路径；商业占位文本不证明已购买。`materials/qt/6.9.2/`保留全文及例外；[PySide](https://github.com/pyside/pyside-setup/tree/v6.9.2)、[QtBase](https://github.com/qt/qtbase/tree/v6.9.2) |
| QtDataVisualization、QtVirtualKeyboard6.9.2 | B，旧Setup仍有；0.2.6-test.3打包规则保留四项排除，实际新包另验 | GPL3-only或商业许可，**不能任选LGPL**。已查明可选qtpy兼容导入与QtGui插件收集路径；原Setup的分发义务不因此消失。对应头文件/全文在Qt目录；[DataVisualization](https://github.com/qt/qtdatavis3d/tree/v6.9.2)、[VirtualKeyboard](https://github.com/qt/qtvirtualkeyboard/tree/v6.9.2) |
| QtPdf6.9.2 | B | PDFium等第三方不能用QtBase主许可概括；精确第三方版本/版权映射仍待补 |
| FFmpeg/ffprobe n9.0.2-17-g2a571b6068（BtbN FFmpeg-Builds `autobuild-2026-09-30-13-08`，win64-gpl-9.0，2026-10-14起） | B，独立CLI | 实际开启GPL/version3/static，不能称泛LGPL；`ffmpeg-GPLv3.txt`与包内LICENSE逐字节相同。构建仓库快照、补丁与105个依赖的固定仓库/提交见[对应源码材料](licenses/source-materials/btbn-ffmpeg-builds-6c9aec5f/README.md)，依赖源码按§6(d)指向上游；静态库含libdvdcss（GPL-2.0+）等，各库许可原文逐项收集未完成；[FFmpeg](https://ffmpeg.org/legal.html)、[构建项目固定提交](https://github.com/BtbN/FFmpeg-Builds/tree/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b)。截至0.7.1的已发布安装包随附gyan 9.0-essentials，其缺口见[SOURCES.md](licenses/SOURCES.md) |
| mpv0.41.0-923-g7b8915bc1 | B，HWND嵌入/JSON IPC独立进程 | GPL功能开启，内部FFmpeg N-126125-g1d7b14f61/libplacebo dirty另列；原mpv-Copyright及build-records保留；[固定提交](https://github.com/mpv-player/mpv/tree/7b8915bc1d) |
| Khronos Vulkan-Loader 1.4.363.0（LunarG Vulkan Runtime 官方签名的 `vulkan-1.dll`，2026-10-17 起，下一版安装包随附） | B，`third_party/vulkan-loader/`；mpv 的兜底运行库，只在系统没有显卡驱动带的 `vulkan-1.dll` 时才被用到 | Apache-2.0、MIT（cJSON 等）、HPND-Kevlin-Henney；未修改，上游没有 NOTICE 文件。原文在 `materials/vulkan-loader/1.4.363.0/`；[LunarG 组件包](https://sdk.lunarg.com/sdk/download/1.4.363.0/windows/VulkanRT-X64-1.4.363.0-Components.zip)、[上游固定标签](https://github.com/KhronosGroup/Vulkan-Loader/tree/v1.4.363)；组件目录第 624 条 |
| OpenCC 1.4.2 词典数据（2026-10-19 起，下一版安装包随附） | B，`twobyteasr/locales/zh-Hant-subtitles.json`：开发脚本 `scripts/make_zh_hant_subtitles.py` 从 OpenCC 的 s2tw 词典生成，用于把识别出的字幕转成繁体；繁體中文界面的 `zh-Hant*.json` 同样由 OpenCC 生成。程序不随附、不调用 OpenCC 本身 | Apache-2.0，版权人见 AUTHORS（取自 PyPI 1.4.2 发行包，包内没有 NOTICE）。原文在 `materials/opencc/1.4.2/`；[上游](https://github.com/BYVoid/OpenCC)、[PyPI 1.4.2](https://pypi.org/project/OpenCC/1.4.2/) |
| PyAV17.1.0 / FFmpeg8.1.1 | B，同进程扩展与离线wheel | PyAV BSD不覆盖编码库。FFmpeg自报LGPLv3却链接x264/x265，构建补丁移动GPL检查；GPL路线仍需闭合实际版本/源码/补丁，不凭自报LGPL放行。原文/部分源码见pyav-codecs及SOURCES；[PyAV](https://github.com/PyAV-Org/PyAV/tree/v17.1.0)、[构建工程](https://github.com/PyAV-Org/pyav-ffmpeg/tree/8.1.1-2) |
| Qt Multimedia FFmpeg | B，avcodec61.19.101/format61.7.100/util59.39.100 | 此套自报LGPL2.1+，与CLI和PyAV不同；原文及库探针已附，源码补丁对应仍待闭合 |
| Remotion4.0.513 / compositor FFmpeg n7.1 | B，实际渲染运行时及ProRes4444透明层生产导出辅助进程 | JS自定义Free/Company License不授予全部GPL下游权利，具体组合范围见当前审阅。媒体库的fdk-aac-free2.0.0原NOTICE现已取得，保留Fraunhofer版权及限制，不能凭移除configure检查按GPL放行。[完整FDK原文](licenses/materials/remotion/4.0.513/fdk-aac-free-2.0.0-NOTICE.txt)、[对应源码及缺口](licenses/SOURCES.md)、[Remotion固定原文](https://github.com/remotion-dev/remotion/blob/v4.0.513/LICENSE.md) |
| GSAP3.15.0 | A/B，renderer/示例/网站代码 | 标准GSAP/Webflow条款，竞争工具用途及纳入的Webflow服务条款待确认，非MIT。`materials/gsap/3.15.0/`含完整可见文本及原始HTML文本；[官方条款](https://gsap.com/standard-license/) |
| React/ReactDOM19.2.8 | B，前端运行时 | MIT，保留Meta及原文列明权利人；npm逐版本来源和全文见目录 |
| Node24.13.0 | B，独立JS运行时 | 现有node-LICENSE.txt包含Node及内置第三方完整通知；[固定全文](https://github.com/nodejs/node/blob/v24.13.0/LICENSE) |
| Chromium Headless149.0.7790.0 | B，浏览器渲染 | 实际约2MB LICENSE.headless_shell保留；传递源码交付未全部核实。runtime条目含精确本地文本 |
| Torch/Torchaudio2.11.0+cpu | B，cp310/cp312离线wheel | 各wheel原许可/NOTICE保留，Torch主BSD不覆盖全部传递组件；[Torch v2.11.0](https://github.com/pytorch/pytorch/tree/v2.11.0) |
| Torch2.11.0 CPU/cu126/cu128、uv0.11.7、私有Python3.10.19/3.12.13 | C，按设备准备环境 | 直接约束已列但传递项未全锁。构建venv中的CUDA许可不证明CUDA二进制在B；uv Apache/MIT和各Python原文已补；[uv0.11.7](https://github.com/astral-sh/uv/tree/0.11.7) |
| MOSS代码eda4b9f13f1574765a80438c9797780a9bd48112 | B，vendor源码 | Apache2.0，本地对应干净提交；权重单列C；source条目保留全文；[固定源码](https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/tree/eda4b9f13f1574765a80438c9797780a9bd48112) |
| FireRed代码4e7d9aaf4482a47cec1724807026b9b151926eb5 | B，vendor源码 | Apache2.0，5处实质修改；当前源码五文件已加修改标记，原版权保留。旧包补丁与当前含声明补丁分别保留，见[SOURCES](licenses/SOURCES.md)；旧Setup尚未更新，不能写未修改；[固定源码](https://github.com/FireRedTeam/FireRedASR2S/tree/4e7d9aaf4482a47cec1724807026b9b151926eb5) |
| 16项工坊模型/词表 | C | Apache/MIT/CC-BY4/OpenMDW1.1/FunASR自定义条款分列；模型卡不是基础资源全核实证明。完整ID/revision/原文见MODELS |
| Cubic11 1.451、SourceHan2.005、ZCOOL2.001/1.000、SmileySans2.0.1 | A/B，字体原件及副本 | OFL全文和具体版权保留；WOFF2本地转换及保留字体名条件另列；font逐项含来源 |
| QtAwesome1.4.0与12个TTF | B | 代码MIT不覆盖字体：FA5.15.4/6.7.2字体OFL/图标CC-BY/代码MIT；Codicon0.0.36 CC-BY4；MDI5.9.55/6.9.96字体Apache2；Phosphor1.3.0 MIT；Remixicon2.5.0 Apache2。Elusive2.0精确原文仍缺。`materials/fonts/`及逐项官方版本来源 |
| GIMP bridge本地快照 | A/B，插件源码 | 插件GPL3+及全文保留；完整GIMP为D/E，未在Setup。保留GPL3-or-later，不能统一改为only |
| ag-psd31.0.2、pako/base64-js bundle | A/B，PSD处理 | 原许可保留，后两者精确版本/构建锁仍未查明；vendored逐项记录 |
| 参考图与封面模板、商标、技能文本 | A/B，实际资源/模板 | 2026-10-01源码替换：原游戏/CBR拼图和录播背景退出新资源，改为随附可编辑SVG的原创几何示意/山谷，适用项目GPL-3.0-only；保留OFL字体原文。旧test.3发行物仍含旧图，不能追溯重标。其他商标和技能文本保持各自权利范围，源码替换不自动证明新Setup已更新 |
| 用户另配ASR/LLM/OSS及CLI服务 | D；客户SDK另列B | 各服务独立条款，未提供用户密钥。软件许可不豁免服务、模型或素材条件 |

当前B未发现QtWebEngine、ONNX Runtime、libmpv/Python-mpv或HyperFrames运行时，不把整个开发环境当作安装包。QtPdf/PDFium与独立Chromium仍需单列；名为HyperFrames的作品目录、直接分发的技能文本和渲染输出也是不同范围。

部分原生DLL（含Microsoft运行组件）、下载运行环境及资产的精确来源/再分发依据仍未闭合，见“未取得独立原文”的项。不能由父包许可、免费发布或能够下载推定许可已确认。


## test.4独立源码范围补充：splitter构建资料

以下是新增源码材料的声明，不表示旧Setup自动含新增文件。rust-ffmpeg-splitter的实际媒体构建来源为39ddfbb2283857327c5f31635059c399eaab7b4c，该版未找到LICENSE/README整体授权；不得把Remotion主项目许可覆盖到它。

本次从明确GPL-2.0-or-later的50b6a0c0e7e3076e33044254b560f466b67cd245取得20件未修改构建脚本/补丁，逐字节等于旧构建输入。版权©2026 Jonny Burger；对应[上游LICENSE](https://github.com/remotion-dev/rust-ffmpeg-splitter/blob/50b6a0c0e7e3076e33044254b560f466b67cd245/LICENSE)、[原文](licenses/source-materials/remotion-4.0.513/splitter-licensed/LICENSE)、[完整GPLv2](licenses/source-materials/remotion-4.0.513/splitter-licensed/COPYING.GPLv2.txt)、[原README](licenses/source-materials/remotion-4.0.513/splitter-licensed/README.md)及[逐文件来源/校验](licenses/source-materials/remotion-4.0.513/splitter-licensed/PROVENANCE.json)配套提供，GPL or-later不覆盖各补丁上下文中独立FFmpeg/x265等版权。

用途是**原样第三方构建/许可材料**，不用于修改本轮运行载荷；没有本地代码补丁。旧版9件不同文件没有按此冒认授权，公开范围不含它们。完整媒体库仍缺其准确构建输入和组合权利，提供此20件不等于已交付完整对应源码，也不解决FDK混合分发。本项目4件自有Remotion/GSAP接口按GPL-3.0-only独立提供，不把调用的库实现计入自有代码。
## Optional models added in the 2026-10-06 source increment

Microsoft VibeVoice code `1541f590c7099820f10ea012f48d2399282df69f` and both official VibeVoice-ASR-Streaming checkpoints are marked MIT. BUTSpeechFIT DiariZen code `844f5555b0a98acd0931511fc641a8c5b8ba92c7` is MIT; its specific WavLM large s80 md v2 weights are CC-BY-NC-4.0, with complete upstream research/compatibility wording retained. The WeSpeaker auxiliary weights and PLDA materials retain independent CC-BY-4.0 terms. Exact checkpoint revisions, filenames, hashes, original notices and modifications are in [the shared optional-model manifest and local originals](licenses/optional-models/README.md).

No optional weights are bundled by default; model acquisition and consent do not settle formal redistribution compatibility. Original application adapters remain GPL-3.0-only under the existing historical grant. Existing components and unresolved permission/source conditions retain their status. This addition does not include pyannote Community-1 or restore a Docker product.
## 2026-10-07授权回复与实际依赖更新

Remotion4.0.513已回复：**所请求覆盖GPL下游的特殊豁免已拒绝**；Rust/FFmpeg按各自许可。原请求的准确原生构建材料未提供，额外组合权利未提供，两项**分别未解决**；没有将所有项写成拒绝或已获许可。个人免费资格、非商用声明、Company订阅及独立进程不能代替这些权利。

当前生产高级字幕仍保留；直接/传递npm包、真实API、compositor/Rust/媒体DLL、Chromium、自动npm安装/备用CLI、两个独立onedir及配对B内部材料已分别核对。现有HTML档案可独立求值，正常Studio宿主仍调用Remotion；最小纯CDP验证不会偷偷替换全部AI功能。原封存Setup/候选/A/B/C声明与自有GPL-3.0-only、0.2.6-test.3分界保持。

[组件、实际材料及发布门](licenses/REMOTION_DEPENDENCY_AUDIT.md)。新统一候选保留既有实现并继续标公开发布阻塞；纯源码C不代替内部B及原生对应材料。

## 0.7.0 新增（2026-10-13）

0.7.0 相对 0.6.5 安装包，主程序新增本机 MCP 服务（官方 Python SDK `mcp` 2.3.0），因此 PyInstaller 把它的依赖链一并收入主程序。按 0.6.5 与 0.7.0 两个主程序的 PYZ 模块与载荷文件逐项比较，新增的第三方组件如下（B＝随安装包附带）。每项的原许可文件从构建环境的发行包元数据原样复制到 `licenses/materials/frozen/`，安装后也在程序目录的 `licenses/python/`；逐文件 SHA-256 见 [机器索引](licenses/component-index.json)，逐项记录见[组件目录](licenses/COMPONENTS.md)第 605 条起。

| 组件及版本 | 范围与用途 | 许可与原文 |
|---|---|---|
| mcp 2.3.0 | B，PYZ | MIT；原文 `licenses/materials/frozen/mcp-2.3.0/` |
| mcp-types 2.3.0 | B，PYZ | MIT；原文 `licenses/materials/frozen/mcp-types-2.3.0/` |
| pydantic 2.13.4 | B，PYZ | MIT；原文 `licenses/materials/frozen/pydantic-2.13.4/` |
| pydantic_core 2.46.4 | B，PYZ＋_pydantic_core.cp310-win_amd64.pyd | MIT；原文 `licenses/materials/frozen/pydantic_core-2.46.4/` |
| starlette 1.3.1 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/starlette-1.3.1/` |
| uvicorn 0.52.0 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/uvicorn-0.52.0/` |
| sse-starlette 3.5.0 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/sse-starlette-3.5.0/` |
| anyio 4.14.2 | B，PYZ | MIT；原文 `licenses/materials/frozen/anyio-4.14.2/` |
| httpx2 2.13.1 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/httpx2-2.13.1/` |
| httpcore2 2.13.1 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/httpcore2-2.13.1/` |
| click 8.4.2 | B，PYZ | BSD-3-Clause；原文 `licenses/materials/frozen/click-8.4.2/` |
| opentelemetry-api 1.45.1 | B，PYZ | Apache-2.0；原文 `licenses/materials/frozen/opentelemetry-api-1.45.1/` |
| truststore 0.10.4 | B，PYZ | MIT；原文 `licenses/materials/frozen/truststore-0.10.4/` |
| typing-inspection 0.4.2 | B，PYZ | MIT；原文 `licenses/materials/frozen/typing-inspection-0.4.2/` |
| tzdata 2026.3 | B，PYZ | Apache-2.0；原文 `licenses/materials/frozen/tzdata-2026.3/` |
| pywin32 312 | B，PYZ＋pywintypes310.dll、_win32sysloader.pyd、win32api.pyd、win32evtlog.pyd、win32job.pyd、win32pdh.pyd | PSF；原文 `licenses/materials/frozen/pywin32-312/` |
| pytest 9.1.1 | B，PYZ | MIT；原文 `licenses/materials/frozen/pytest-9.1.1/` |

另有 8 个组件原来就作为离线 wheel 随包（h11 0.16.0、rich 15.0.0、itsdangerous 2.2.0、markdown-it-py 4.2.0、mdurl 0.1.2、python-multipart 0.0.32、annotated-types 0.8.0、exceptiongroup 1.3.1），0.7.0 起同一版本也进入主程序 PYZ；许可与原文不变，组件目录已补路径。

说明：
- `pytest` 只因依赖链被收入 `_pytest` 模块，程序不运行测试；之后应在打包规则里排除。
- `pywin32` 的发行包含多份子项目许可原文（全部保留）；实际随包的只是 win32 核心扩展与 `pywintypes310.dll`。
- `tzdata` 的 Python 包是 Apache-2.0，IANA 时区数据本身另有公共领域声明。
- 模型（C，首次下载）：日语 CTC 对齐模型 `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`（Apache-2.0，固定版本 `cf031e02…`；国内来源 ModelScope 固定提交 `18a6b597…`），模型卡原文见 `licenses/materials/models/ja_ctc_aligner/`，[模型表](licenses/MODELS.md)记录其基础模型与训练数据条款待核。

这一节只登记新增组件及其原文；0.7.0 的公开分发结论与仍缺的对应源码材料见[分发状态](licenses/DISTRIBUTION-STATUS.md)。PR #2 贡献者已对其贡献的代码给予与作者相同的 Remotion/GSAP 附加许可（见 `PROJECT_LICENSE.md`）。这不表示组合已获法律核实。
