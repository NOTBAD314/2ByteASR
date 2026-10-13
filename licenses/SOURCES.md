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
