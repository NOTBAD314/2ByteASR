# 对应源码、补丁与取得方式

**GPL迁移更新：** 自有代码已采用 GPL-3.0-only，旧禁售目标退出。0.2.6-test.3本地附件名称、版本关系与GPLv3 §6(d)交付见 [SOURCE_DELIVERY.md](../SOURCE_DELIVERY.md)，构建方法见 [BUILD_FROM_SOURCE.md](../BUILD_FROM_SOURCE.md)。第三方ZIP按本目录原路径展开，尚未在线提供。预编译输入不是对应源码，以下缺口保留。当前分类见 [GPL3_ROUTE.md](GPL3_ROUTE.md)。

本页只记录已经提供的材料和仍然缺失的对应关系。新增材料位于源码树，旧Setup未更新。原URL、归档成员、SHA256及组件映射见[机器索引](component-index.json)；下列本地归档可直接取得，不依赖私人账号。源码义务依具体许可判断，MIT/Apache并不一律要求全部源码。没有长期人工邮寄或无限期托管承诺。

## 已提供的源码与版本材料

| 对象 | 实际文件 | 对应关系与限制 |
|---|---|---|
| PyAV17.1.0 | [官方源码](source-materials/pyav-17.1.0/pyav-source.tar.gz) | 来自v17.1.0；原审计确认当前wheel与官方wheel、25个DLL匹配。未作可复现重建 |
| pyav-ffmpeg8.1.1-2 | [完整构建工程](source-materials/pyav-17.1.0/pyav-ffmpeg-build-source.tar.gz) | 由PyAV17.1.0的ffmpeg-latest.json指向，含脚本、配方、补丁和原始许可；本轮未执行 |
| FFmpeg8.1.1 | [源码](source-materials/pyav-17.1.0/ffmpeg-source.tar.xz) | SHA `b6863adde98898f42602017462871b5f6333e65aec803fdd7a6308639c52edf3`匹配构建脚本；需结合实际补丁/配置 |
| x264构建脚本输入 | [源码](source-materials/pyav-17.1.0/x264-source.tar.bz2) | 脚本固定`b35605ace3ddf7c1a5d67a2eb553f034aef41d55`，SHA `6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224`已核对；同版本README的`32c3b801…`已由固定Windows构建DLL逐SHA对应排除：实际配方b35605a与wheel的x264 DLL匹配，见2026-10-01增量证据 |
| x2654.2+1-e444744 | [源码](source-materials/pyav-17.1.0/x265-source.tar.gz) | SHA `40b1ea0453e0309f0eba934e0ddf533f8f6295966679e8894e8f1c1c8d5e1210`匹配脚本；COPYING从此归档提取，补足GitHub路径404的缺口；原归档x265Version.txt实际为4.2+1-e444744，与完整commit e444744c03978c1fb4e037168967020cf2648427代码对应；GPLv3路径不要求另买商业授权 |
| FireRedASR2S | 安装树/开发目录`third_party/FireRedASR2S/`及[补丁](source-materials/build-records/firered-local.patch) | 基础`4e7d9aaf4482a47cec1724807026b9b151926eb5`，5处实质修改、49处换行差异、53个上游文件未纳入；上游原版不是实际修改版 |
| MOSS代码 | 安装树/开发目录`third_party/MOSS-Transcribe-Diarize/`及LICENSE | 对应`eda4b9f13f1574765a80438c9797780a9bd48112`，原审计确认vendor干净；权重revision另列 |
| GPL GIMP桥接插件 | `assets/gimp/2byte-cover-bridge.py`及COPYING-GIMP.txt | 已提供可编辑源；完整GIMP不在Setup中，插件既有GPL不能被统一禁止销售条款覆盖 |

归档保留上游版权/许可。PyAV的BSD不替代编码库许可；本项目已撤销禁止出售目标，取得部分源码仍不等于全部对应源码和补丁已齐。

## FireRed修改声明

实质修改文件为：

- `fireredasr2s/fireredasr2/asr.py`
- `fireredasr2s/fireredlid/lid.py`
- `fireredasr2s/fireredpunc/punc.py`
- `fireredasr2s/fireredasr2/models/fireredasr_aed.py`
- `fireredasr2s/fireredvad/core/detect_model.py`

修改涉及checkpoint安全读取、CTC dtype与诊断，以完整补丁为准，并非本轮新改功能。2026-09-30阻断处理轮已在这五个文件自身加入醒目的修改说明、基础commit及非官方集成标识，保留原版权；注释前后AST一致。旧包补丁保留为原证据，当前版本另见[含标记补丁](source-materials/build-records/firered-current-with-notices.patch)。test.3配对源码和实际安装载荷已包含这些标记，原brand/test.2旧Setup不自动更新。

## Remotion compositor 的二进制对应链（本轮新增）

当前载荷与Remotion v4.0.513官方对应目录21项逐Git blob匹配。该版本的[Cargo.lock](source-materials/remotion-4.0.513/remotion-Cargo.lock)固定`rust-ffmpeg-sys@e20f3b7d15db0386e1ab62cb107ca6bab0cd79ae`；Windows归档SHA256 `5ce7b6e6d6fa49aac970d9121368cf7942f43bd6dfacb13e2bb98a8f01e88489`内16个媒体二进制与当前载荷逐字节相同（README为不同用途的文档，不相同）。该提交的[来源记录](source-materials/remotion-4.0.513/sys-SOURCE.md)将构建锁到`39ddfbb2283857327c5f31635059c399eaab7b4c`及具体CI运行。

已保存该版本的[FFmpeg构建配方](source-materials/remotion-4.0.513/splitter/compile-ffmpeg.mjs)、[fdk-aac-free配方](source-materials/remotion-4.0.513/splitter/compile-fdkaac.mjs)、原补丁/工具链描述，以及[FFmpeg7.1完整源码](source-materials/remotion-4.0.513/ffmpeg-7.1.tar.xz)。其余已保存文件及原始归档成员/SHA在机器索引中。来源原始归档含额外视频和二进制，保留于内部取证目录；配套材料只取原字节的构建源码，不把那些演示素材误当作必要源码随包。

实际avcodec DLL的字串进一步给出x264 `r3222 b35605a`、x265 `3.4+28-419182243`。前者复用[已附基础源码](source-materials/pyav-17.1.0/x264-source.tar.bz2)；后者解析到VideoLAN镜像完整提交`419182243fb2e2dfbe91dfc45a51778cf704f849`，补入[对应基础源码](source-materials/remotion-4.0.513/x265-419182243-source.tar.gz)及[原COPYING](source-materials/remotion-4.0.513/x265-419182243-COPYING.txt)。源码SHA256为`d82fccba4c302b9873ba09d021f9e71bfb85996d90ff4d6a8ba69bcf13dd90b9`。此版本结论只针对compositor，不能移用于PyAV的另一份x264/x265 DLL。

**尚缺而非推定已满足：** x264配方使用可变stable分支并pull；Windows x265配方直接复制预编译libx265.a。虽基础revision已定位，二者实际构建参数/本地补丁仍须确认；fdk-aac-free2.0.0现已从Fedora f33固定SHA512档案取得，原NOTICE附在materials/remotion/4.0.513；归档来源与许可判断见REVIEW，仍有GPL混合构建冲突；其余静态库和运行库完整对应、Rust helper组合适用授权仍须闭合；源文件及锁定Cargo输入已由下述test.4增补补齐。`fdk-aac-free.patch`改检查名单不是额外许可。此处匹配的是来源链与上述媒体文件，不声称全部对应源码已交付。

## 尚未完整闭合的对应源码

| 组件 | 现有证据 | 仍需取得或验证 |
|---|---|---|
| FFmpeg9.0 gyan CLI | [buildconf](source-materials/build-records/ffmpeg-buildconf.txt)、[版本](source-materials/build-records/ffmpeg-version.txt)、GPLv3全文 | 提供者精确来源包、全部静态库版本/补丁/构建脚本和工具链。上面的8.1.1不适用于9.0 |
| mpv0.41.0-923-g7b8915bc1 | [版本](source-materials/build-records/mpv-version.txt)、[构建](source-materials/build-records/mpv-build.txt)、Copyright | mpv7b8915bc1与FFmpeg1d7b14f61精确commit源码已补；libplacebo dirty补丁、其余链接依赖及实际构建配方仍缺 |
| Qt/PySide/Shiboken6.9.2及Qt Multimedia FFmpeg | 对应全文/例外/部分头文件与[库探针](source-materials/build-records/dll-probes.json) | Qt完整6.9.2、PySide/Shiboken6.9.2官方源码已补且SHA匹配；实际wheel/Qt媒体构建配置与源码对应、必要替换说明仍需补，未进行替换测试不单独等同违规 |
| PyAV其余编解码依赖 | 官方wheel对应、构建工程及上述主要源码包 | 11项Windows配方输入已按原SHA补齐；x264/x265版本疑虑已关闭。尚缺实际MSYS2运行库的精确包身份与所需源码/例外，不称全部对应源码已齐 |
| Remotion compositor4.0.513 / FFmpeg n7.1 | [真实configuration](source-materials/build-records/remotion-ffmpeg.exe-version.txt)、上节锁定来源链与基础源码 | x264/x265实际预编译构建参数/补丁、其他静态库及Rust helper相容授权；FDK原文/源码和Rust源文件已补，不能替代组合权利；JS许可不是媒体库授权书 |
| Chromium149.0.7790.0 / QtPdf/PDFium | 真实长通知和版本身份 | 准确构建来源及各自适用的源码/通知、补丁与版本映射尚未全部闭合 |
| Microsoft及其他原生DLL | PE版本/版权/路径在组件目录 | 精确工具链、来源与可再分发依据未逐项核实；不能套父包MIT或最新EULA |
| C范围下载环境 | 直接版本、下载约束及部分许可 | 每台机器实际传递组件及条件尚未锁全；本机venv不是接收者环境的证明 |

GSAP条款纳入了Webflow服务条款，已保留原文中的官方链接；具体版本适用关系和产品边界仍待确认，链接不是额外授权书。

LGPL路径还应提供修改库替换/重链接方法、必要安装信息及修改调试逆向例外，并验证受影响入口。本轮不把DLL可见写成替换试验通过。

2026-10-01新增归档见 [精确来源与哈希](source-materials/supplement-20261001.json)，实际文件在独立源码补充目录；安装包无需嵌入1GB的Qt源码，但选择GPL §6(d)时须与二进制在同一发行位置提供接收者可取得的对应源码。不要求重建哈希相同，不将未修改通用编译工具一概列入对应源码。

正式分发时，应把完整匹配的必要源码随包/发行附件提供，或选择适用许可允许且可实际履行的方式。失效链接、私人权限仓库和泛项目首页不列作完成；未选择的长期履约安排不预先承诺。


## 2026-10-01 test.4 后续源码增补（旧载荷不变）

独立文件 `releases/2ByteASR-test4-Source-Addendum-20261001.zip`，SHA256 `24ba2ff4ffea3d10d6e77ceefedbf2494eab834dcd2cb2801f9cb3e2c53776da`。源码树 `releases/test4-source-addendum-20261001/` 内 source-receipts.json 记录每个原始URL/Git blob/SHA和排除项。compositor v4.0.513 的 Rust helper、Cargo及构建/工具链文件已补；锁中rust-ffmpeg@4f47c491、rust-ffmpeg-sys@e20f3b7d、mp4-rust@92ba3757源和93个原crate已逐checksum提供，不再将这些源文件列缺。原始版权/许可保留；sys固定树缺独立LICENSE仅有WTFPL元数据的证据边界已写入增补README，未统一推定MIT。此附件仍不是完整原生组合对应源码或组合授权。

PyAV MSYS2缺口已定位到PyAV-Org/pyav-ffmpeg 8.1.1-2、commit b84838a003b1626152ef530750d5c3e0022c3db9、run26719662502/Windows job78744345635；日志API已410过期。待构建者提供pacman包身份/.PKGINFO/对应源码补丁，不再猜当日依赖版本。其余准确请求见内部REVIEW C节接续请求表，未自动发送。

### 接收者修改LGPL库的安装信息（未作替换实测）

test.4实际平铺安装树中：PySide6/Qt6Core.dll、Qt6Gui.dll、Qt6Widgets.dll及*.pyd，PySide6/plugins/platforms/qwindows.dll等插件；Shiboken在shiboken6/Shiboken.pyd、shiboken6.abi3.dll；Qt媒体DLL在PySide6/avcodec-61.dll、avformat-61.dll、avutil-59.dll、swresample-5.dll、swscale-8.dll。这与renderer或PyAV的媒体库是不同集合，不能混换。

在用户可写的独立安装副本中保留原文件，关闭该副本进程后，以适用于Windows x64、当前Python3.10 ABI及Qt/PySide/Shiboken6.9.2接口的修改库完整一致集合替换相应文件；插件须匹配Qt构建。对应基础源码及构建说明依前表取得；若改ABI，须同时重建相应绑定/调用者，不能承诺任意版本DLL直接可换。重新从该副本启动并检查载入模块路径、中文输入/媒体播放/受影响导出，失败恢复原副本。无需作者私钥/签名证书；GPL项目声明没有添加禁止为调试库修改而逆向的条件。官方安装器修复/升级可能覆盖修改库，应另存副本。

这些是按实际文件给出的替换位置与操作边界，不是已经完成替换验证或所有LGPL义务的法律确认；实际wheel/Qt媒体构建对应仍待材料。新增说明没有写入封存Setup，下一次经批准的新候选应将正式采用的相关说明实际入包并验证。


## test.4定点更正：mpv与splitter材料范围

test.4实际播放器是独立mpv.exe，通过HWND及JSON命名管道通信；封存EXE代码/配对源/既有导出进程回执一致。没有libmpv/Python-mpv加载证据；libmpv=true只是构建能力，不是应用调用。mpv内部精确构建和dirty来源缺口仍保留。

splitter准确构建39ddfbb2283857327c5f31635059c399eaab7b4c无LICENSE/COPYING，README未声明GPL；不能用主仓库或新版README替它授权。新增[splitter-licensed/PROVENANCE.json](source-materials/remotion-4.0.513/splitter-licensed/PROVENANCE.json)为明确GPL的固定50b6a0c0e7e3076e33044254b560f466b67cd245原样20件，逐字节等于39旧输入，原LICENSE/README和GPL全文齐全。此20件来源/许可交付关闭；不是给旧版整个commit追溯授权。

旧版Cargo.toml、clean.mjs、compile-av1.mjs、compile-ffmpeg.mjs、compile-x265.mjs、const.mjs、Dockerfile、Dockerfile-aws、README.md与该GPL版不同且缺旧版明确授权，原内部证据保留，独立源码范围不提供。只有此9件需要新文件级授权解释；脚本许可与产出FDK混合媒体库的权利分别判断。自有API源码无需等待此完整媒体CS缺口。独立源码r2不是完整Setup的Corresponding Source；既有外部构建材料请求没有重复改写、仍未发送。
## 2026-10-07授权回复与实际依赖更新

Remotion4.0.513已回复：**所请求覆盖GPL下游的特殊豁免已拒绝**；Rust/FFmpeg按各自许可。原请求的准确原生构建材料未提供，额外组合权利未提供，两项**分别未解决**；没有将所有项写成拒绝或已获许可。个人免费资格、非商用声明、Company订阅及独立进程不能代替这些权利。

当前生产高级字幕仍保留；直接/传递npm包、真实API、compositor/Rust/媒体DLL、Chromium、自动npm安装/备用CLI、两个独立onedir及配对B内部材料已分别核对。现有HTML档案可独立求值，正常Studio宿主仍调用Remotion；最小纯CDP验证不会偷偷替换全部AI功能。原封存Setup/候选/A/B/C声明与自有GPL-3.0-only、0.2.6-test.3分界保持。

[组件、实际材料及发布门](REMOTION_DEPENDENCY_AUDIT.md)。新统一候选保留既有实现并继续标公开发布阻塞；纯源码C不代替内部B及原生对应材料。

## 2026-10-11：0.6.5 对应源码指引（GPLv3 §6(d)）

0.6.5 的 Release 附件提供下列基础源码。只放在第三方服务器上的部分写明位置；确实没有的材料写明“未提供”，不推定已满足。

| 随附程序 | 本项目附件里已有 | 第三方服务器上的对应材料 | 未提供 |
| --- | --- | --- | --- |
| `tools/ffmpeg/bin/ffmpeg.exe`、`ffprobe.exe`（gyan.dev 9.0 essentials，GCC 16.1.0/MSYS2） | `2ByteASR-0.5.0-ThirdParty-Sources.zip` 的 `Fixed-Upstream-Archives/ffmpeg-9.0.tar.xz`；库版本见 `ffmpeg -version` 和 [二进制登记](materials/runtime/0.6.5-binary-register.json) | https://www.gyan.dev/ffmpeg/builds/ | gyan 的构建脚本与可能的补丁；13 个未标版本的链接库与 openal-soft 的确切版本（见下方来源索引） |
| `tools/mpv/`（mpv-winbuild-cmake） | 同一附件的 `mpv-7b8915bc1.tar.gz`、`ffmpeg-1d7b14f61.tar.gz` | 构建系统 https://github.com/shinchiro/mpv-winbuild-cmake （`packages/libplacebo.cmake` 无补丁，2025-09-01 起未变）；libplacebo 上游提交 `22ee762` | 无：libplacebo 的 `-dirty` 来自配方替换 glad、fast_float 两个子模块目录，不是源码改动 |
| `renderer/node_modules/@remotion/compositor-win32-x64-msvc/`（Remotion 4.0.513，FFmpeg n7.1） | `source-materials/remotion-4.0.513/` 的 `ffmpeg-7.1.tar.xz`、`x265-419182243-source.tar.gz`、GPL 版 rust-ffmpeg-splitter 构建脚本；`source-materials/pyav-17.1.0/x264-source.tar.bz2`（b35605a）；0.5.0 附件里的 `fdk-aac-free-2.0.0.tar.gz`、opus、lame、dav1d、vpx | 实际构建提交的完整脚本：https://github.com/remotion-dev/rust-ffmpeg-splitter/tree/39ddfbb2283857327c5f31635059c399eaab7b4c | 无（x265 见下方来源索引：默认 8 位配置，源码与相关补丁已附） |
| PyAV 17.1.0 随附的 FFmpeg 动态库与 MinGW 运行库 | Source 与第三方附件里的对应源码包；本版 Release 另附 `mingw-w64-libiconv-1.19-1.src.tar.zst`（libiconv 1.19，LGPL） | 构建配方 https://github.com/PyAV-Org/pyav-ffmpeg/tree/b84838a003b1626152ef530750d5c3e0022c3db9 | 无：`libgcc_s_seh-1`、`libstdc++-6` 适用 GCC 运行库例外，`libwinpthread-1`、`zlib1` 是宽松许可 |
| Chromium Headless Shell 149.0.7790.0 | 随附 `LICENSE.headless_shell` | https://chromium.googlesource.com/chromium/src/+/refs/tags/149.0.7790.0 | 需源码子组件的逐项映射 |

## 2026-10-11：随附 FFmpeg 命令行（gyan 9.0）与 compositor x265 的来源索引

**gyan FFmpeg 9.0 essentials（`tools/ffmpeg/bin/ffmpeg.exe`、`ffprobe.exe`）**

- 出处已核对：GitHub `GyanD/codexffmpeg` 的 Release `9.0`（2026-08-04 发布）里的 `ffmpeg-9.0-essentials_build.zip`。
  - 压缩包 SHA-256 `e6b54767a6065919048f1a098eb27211ca4e12b4348a05d88777a5855d0b6e71`，与 GitHub 服务端摘要一致。
  - 包内 `bin/ffmpeg.exe`（`227af0691433b703…`）、`bin/ffprobe.exe`（`901f0efe4793cbb0…`）与本项目随附的逐字节相同；`ffplay.exe` 未随附。
- 包内 README 原文：[gyan-ffmpeg-9.0-essentials/README.txt](source-materials/gyan-ffmpeg-9.0-essentials/README.txt)。
- FFmpeg 本体：README 写明源码是提交 `d32b387f2b`，即 tag `n9.0`。本项目附件里的 `ffmpeg-9.0.tar.xz` 就是这一版本。

README 列出的外部库确切版本（`git describe` 形式即上游提交）：

| 库 | 版本 | 上游 |
| --- | --- | --- |
| AMF | v1.5.2-2-gc35f613 | github.com/GPUOpen-LibrariesAndSDKs/AMF `c35f613` |
| aom | v3.14.1-138-g4f8be91496 | aomedia.googlesource.com/aom `4f8be91496` |
| AviSynthPlus | v3.7.5-342-gcfdaf8eb | github.com/AviSynth/AviSynthPlus `cfdaf8eb` |
| cairo | 1.18.5 | cairographics.org 发布包 1.18.5 |
| ffnvcodec | n13.1.15.0-1-geddcea9 | github.com/FFmpeg/nv-codec-headers `eddcea9` |
| gsm | 1.0.24 | quut.com gsm-1.0.24 |
| lame | 3.100 | 已附（0.5.0 第三方源码包 `lame_3.100.orig.tar.gz`） |
| libgme | 0.6.6 | github.com/libgme/game-music-emu 0.6.6 |
| opencore-amrnb/amrwb | 0.1.6 | 已附（`opencore-amr-0.1.6.tar.gz`） |
| libssh | 0.12.0 | libssh.org 0.12.0 |
| libtheora | v1.2.0 | github.com/xiph/theora `v1.2.0` |
| libwebp | v1.6.0-195-g733c91e | chromium.googlesource.com/webm/libwebp `733c91e` |
| openal-soft | “latest” | **未标版本** |
| libopenmpt | 0.6.28-38-g879fd166 | github.com/OpenMPT/openmpt `879fd166` |
| opus | v1.6.1-50-g3da9f7a6 | github.com/xiph/opus `3da9f7a6` |
| rubberband | v4.0.0 | breakfastquay.com rubberband 4.0.0 |
| SDL | release-2.32.0-228-ga2e7c76bd | github.com/libsdl-org/SDL `a2e7c76bd` |
| speex | Speex-1.2.1-51-g0589522 | github.com/xiph/speex `0589522` |
| srt | v1.5.6-1-ga13859e | github.com/Haivision/srt `a13859e` |
| libva（VAAPI） | 2.25.0 | github.com/intel/libva 2.25.0 |
| vid.stab | v1.1.2-23-g8f5ce58 | github.com/georgmartius/vid.stab `8f5ce58` |
| vmaf | v3.2.0-9-g4991d2b5 | github.com/Netflix/vmaf `4991d2b5` |
| vo-amrwbenc | 0.1.3 | opencore-amr 项目 vo-amrwbenc-0.1.3 |
| vorbis | v1.3.7-36-ge3c9861f | github.com/xiph/vorbis `e3c9861f` |
| libvpl | 2.17 | github.com/intel/libvpl 2.17 |
| libvpx | v1.16.0-181-g3e25f224f | chromium.googlesource.com/webm/libvpx `3e25f224f` |
| x264 | v0.165.3223 | code.videolan.org/videolan/x264（只给出修订号 r3223） |
| x265 | 4.3-2-g5ab552e | bitbucket.org/multicoreware/x265_git `5ab552e` |
| xvid | v1.3.7 | xvidcore-1.3.7 |
| zeromq | 4.3.5 | github.com/zeromq/libzmq v4.3.5 |
| zimg | release-3.0.6-252-g1ad1895 | github.com/sekrit-twc/zimg `1ad1895` |

**仍缺（只有构建者 gyan 能补，或换成脚本公开的构建）**：
1. gyan 编译这些外部库和链接 FFmpeg 所用的构建脚本，以及可能的补丁。gyan.dev 与 `GyanD/codexffmpeg` 只公开 FFmpeg 源码提交，仓库里只有 README。
2. 链接进来但 README 没写版本的库：bzip2、gmp、gnutls（及其依赖）、libiconv、libass、fontconfig、freetype、fribidi、harfbuzz、libxml2、xz/lzma、zlib、openjpeg；openal-soft 只写了“latest”。

**compositor 的 x265（Remotion 预编译 `libx265.a`）：已满足，不缺必要材料。**

- 随附库自报 `3.4+28-419182243` 和 `[Windows][GCC 12.2.0][64 bit] 8bit`。这是 x265 默认的 8 位 CMake 配置，用 MinGW-w64 GCC 12.2.0 编译，`X265_BUILD 198`（见 Remotion 仓库 `39ddfbb` 的 `x265-windows/include/x265_config.h` 和 `x265.pc`）。
- 源码 `x265-419182243-source.tar.gz` 含 x265 自带的 CMake 构建系统，已附。
- Remotion 仓库里唯一相关的补丁 `x265-api.patch` 改的是 FFmpeg 的 `libavcodec/libx265.c`，不是 x265，也已附（`splitter-licensed/`）。
- 只缺 Remotion 当年的命令行记录。那是操作记录，不是缺源码、补丁或构建脚本。

## 2026-10-14：随附 FFmpeg 命令行换为 BtbN 固定构建（下一版安装包起）

以前：Windows 安装包随附 gyan.dev 9.0-essentials，gyan 只公开 FFmpeg 提交和 README，构建脚本、可能的补丁与部分库版本无从取得（上一节）。现在：开发树的 `tools/ffmpeg/bin/ffmpeg.exe`、`ffprobe.exe` 换成 BtbN/FFmpeg-Builds 的月末构建，构建脚本和每个依赖的提交都公开固定。已发布的 0.7.1 及更早安装包不受影响，仍按上一节说明。

- 出处：Release `autobuild-2026-09-30-13-08` 的 `ffmpeg-n9.0.2-17-g2a571b6068-win64-gpl-9.0.zip`，SHA-256 `a0e45723c72141975f51d8666302e614711745f3102b704ca3f82c897a58d278`（与 GitHub 服务端摘要、该 Release 的 `checksums.sha256` 一致）。包内 `ffmpeg.exe`（`513368c8…583d98`）、`ffprobe.exe`（`0fd8f3ba…1f68f`）与随附文件逐字节相同；`ffplay.exe` 未随附。BtbN 说明月末构建保留两年。
- FFmpeg 本体：`release/9.0` 提交 `2a571b606854520cf89804d8030c8b328e621689`，无补丁。
- 构建脚本与补丁：构建仓库提交 `6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b` 的源码包已附，[说明](source-materials/btbn-ffmpeg-builds-6c9aec5f/README.md)。
- 依赖：[`dependencies.json`](source-materials/btbn-ffmpeg-builds-6c9aec5f/dependencies.json) 列出 105 个固定来源（99 个 git 提交、4 个已解析为提交的标签、2 个 SVN 修订号），2026-10-14 逐项确认公开可取。依赖源码按 GPLv3 §6(d) 指向这些上游固定提交，本项目没有另行打包（2026-10-14 用户决定）。
- 仍如实保留的限制：编译工具链（crosstool-NG、Rust）没有按提交固定，二进制自报 `gcc 16.2.0 (crosstool-NG 1.29.0.7_b1a94f6)`，不属于对应源码，但影响逐字节重建；本项目没有重建验证；各依赖库许可原文尚未逐项收集；该构建静态链接 libdvdcss（GPL-2.0-or-later），用户已确认可随附。

## 2026-10-17：mpv 的 Vulkan 运行库兜底（下一版安装包起）

随包 `mpv.exe` 需要 `vulkan-1.dll` 才能启动，没有显卡驱动的电脑没有这个文件。下一版安装包在 `third_party/vulkan-loader/` 随附 LunarG 官方签名的 Khronos Vulkan-Loader 1.4.363.0，原样未改：

- 来源：`VulkanRT-X64-1.4.363.0-Components.zip`（SHA-256 `a25a927aa8b9f0371048f1861cf88ac3b9bc9b1fb332c42d897c8ab32695769a`），只取 `x64/vulkan-1.dll`（SHA-256 `e1fcfc9489beefa6a6d9d11d6c7517f6a2b7f16e0d3fb8f4103bee0210f314a3`）。
- 源码：上游 [Vulkan-Loader v1.4.363](https://github.com/KhronosGroup/Vulkan-Loader/tree/v1.4.363)（`9e9518d2cf00054a220ae1a40f4406804b420ef5`）。Apache-2.0、MIT、HPND 都不要求提供源码，这里只记录出处；本项目没有自行重建核对二进制与标签逐字节对应。
- 许可原文与版权：见[组件目录](COMPONENTS.md)第 624 条和 `materials/vulkan-loader/1.4.363.0/`。
