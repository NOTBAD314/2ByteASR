# 第三方组件、许可与来源声明

本声明随 0.2.6-test.3 内部候选提供。自有代码按 [GPL-3.0-only](PROJECT_LICENSE.md) 授权；第三方保留原版权、许可及权利。基线组件证据来自品牌 test.2（SHA `0d2796a1…c88878c`）；当前构建保留既有运行依赖并精确排除四个冗余 Qt 文件，新候选身份与实际入包结果另见同版本交付回执。旧 Setup 原样保留，不自动包含新增材料。

[当前 GPL 路线及未解决项](licenses/GPL3_ROUTE.md)区分旧禁售冲突撤销、实际修正、对应源码缺口及组合许可问题。Remotion/GSAP、素材权利和第三方源码缺口仍开放，此声明不授予未取得权利，也不表示整个组合已可公开分发。

## 每个组件的详细声明

[完整组件目录](licenses/COMPONENTS.md)逐项提供604条分层记录的名称/准确版本、范围、实际路径、版权证据、官方与版本来源、本地原文位置、用途/集成、修改/补丁、对应源码义务、证据等级及缺口。记录含重复层级和未查明项，不代表604种软件均已获得法律核实。

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
| FFmpeg/ffprobe9.0-essentials_build-www.gyan.dev | B，独立CLI | 实际开启GPL/version3/static，不能称泛LGPL；原`ffmpeg-GPLv3.txt`、build-records保留，完整源码/静态依赖未齐；[FFmpeg](https://ffmpeg.org/legal.html)、[提供者](https://www.gyan.dev/ffmpeg/builds/) |
| mpv0.41.0-923-g7b8915bc1 | B，HWND嵌入/JSON IPC独立进程 | GPL功能开启，内部FFmpeg N-126125-g1d7b14f61/libplacebo dirty另列；原mpv-Copyright及build-records保留；[固定提交](https://github.com/mpv-player/mpv/tree/7b8915bc1d) |
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
