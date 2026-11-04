# 2026-10-07：Remotion 4.0.513实际依赖与公开发布门

本页是新统一候选的依赖事实及未闭合条件；保留旧Setup、两独立候选和封存材料的原声明。自有代码仍是GPL-3.0-only，0.2.6-test.3历史分界不变。没有发送新邮件、接受合同、购买许可、修改旧产物或删除AI字幕功能。

作者提供的Remotion回复确认：**所请求的覆盖GPL下游的特殊豁免已拒绝**。Rust/FFmpeg按其各自许可。**原邮件要求的准确原生构建材料未提供，额外组合权利未提供，两项分别保持未解决**，不是它们均被拒绝，更不是均已许可。此前发送记录继续保留；免费个人资格、非商用声明、Company订阅、进程边界均不是本次下游豁免。

## 实际审计范围与证据

当前实际dirty源、MOSS `source-final`、可选模型 `build-final-r3/source`的package/lock均核对；两个最终onedir的实际package身份、compositor/浏览器/Node/FFmpeg原文件与版本命令核对，不用HEAD、文件名或版本号替代内容。机器证据保留在本轮`remotion-component-evidence.json`，包括每包依赖边、锁integrity、关键文件SHA、归档成员SHA和官方固定文档。

Remotion v4.0.513官方LICENSE通过GitHub API原字节核对，本地完整原文SHA256为`bd65083b940f61904f6ef298aade918a7cad72a3e35bc406e36fab365844b673`，与官方blob `d655e2df830bbe19285e55607aefff636ed93d7b`相同。[固定官方许可](https://github.com/remotion-dev/remotion/blob/v4.0.513/LICENSE.md)及[固定FFmpeg说明](https://github.com/remotion-dev/remotion/blob/v4.0.513/packages/docs/docs/miscellaneous/ffmpeg-license.mdx)均留原文。上游FFmpeg页面的概括性判断没有授予新的组合权利，也不能代替精确变体NOTICE及真实输入核验。

已有可选模型B源码ZIP内实际包含`@remotion`4196成员、`remotion`400成员、浏览器291成员、GSAP179成员；其第三方材料ZIP含Remotion专属原文2项、`remotion-4.0.513`原生材料62项。它是包含实际外部预编译输入的内部配对B，不能拿公开C排除项说它已经去掉Remotion。公开C的独立源码范围也不能代替整个B。

两个onedir均实际安装18个`@remotion`包及`remotion`，版本4.0.513；锁另含6个未部署的其他平台compositor。逐包license字段及实际原文分别核对；**MIT的子包不因名称含Remotion自动改成自定义许可，未写license字段的native包也不自动算MIT**。真实包身份与31个关键native文件SHA在机器证据中，后续最终统一载荷须再逐文件验证，不继承旧候选结论。

默认`%LOCALAPPDATA%/npm-cache/_cacache/index-v5`只读扫描，输出仅公开registry.npmjs.org的Remotion/GSAP URL、integrity和大小摘要，不输出私人URL/token或修改缓存。缓存命中不证明构建使用；实际构建依赖是固定node_modules及锁。载荷中未找到默认npm缓存目录；Chromium实际存在于node_modules/.remotion，是交付输入而非凭借缓存能隐去的组件。

## 组件→文件/版本→功能→许可→发布影响

| 组件 | 具体实际文件/版本 | 功能与调用事实 | 许可证据 | 公开发布影响 |
|---|---|---|---|---|
| Remotion核心 | `renderer/node_modules/remotion`4.0.513；`src/index.ts`、Root、SubtitleComposition、WebThemeSubtitle、TrustedSubtitle | registerRoot/Composition/useCurrentFrame/useVideoConfig、delay/continue/cancelRender、interpolate；组成高级字幕帧 | 完整Remotion Free/Company自定义许可 | 存在额外衍生品/主体资格条件；GPL下游特殊豁免拒绝，当前组合权利未解决 |
| Bundler | `@remotion/bundler`4.0.513；service.mjs、render-overlays.mjs | bundle、开发serveUrl与高级React帧 | 自定义Remotion许可 | 正常预览/透明导出实依赖；不能删npm后继续旧bundle |
| Renderer | `@remotion/renderer`4.0.513；service.mjs、export-browser.mjs、render-overlays.mjs、advanced_renderer.py | openBrowser、selectComposition、renderStill、renderMedia、makeCancelSignal；ProRes4444透明段生产 | 自定义Remotion许可 | 正常Studio HTML宿主、精确帧及透明输出仍依赖；最小纯CDP验证不等于已迁移生产 |
| CLI | `@remotion/cli`4.0.513；package.json render命令；advanced_renderer.py CLI分支 | render src/index.ts SubtitleOverlay、frame ranges、ProRes回退 | 自定义Remotion许可 | 是真实生产备用路径，去依赖时须同时替换；不能继续回退 |
| Player | `@remotion/player`4.0.513，经cli/studio传递，实际载荷存在 | 项目renderer/src未找到直接Player import/组件使用；bundler/CLI间接依赖 | 自定义Remotion许可原文 | 实际分发内容须按其许可处理，不能冒称项目单独使用Player API，也不能忽略传递包 |
| Media/parser与协议 | `@remotion/media-parser`、`studio-protocol`、`web-renderer`4.0.513 | 由bundler/studio等传递；web-renderer另带mediabunny编码器 | 各包自定义Remotion许可，按实际原文 | 都实际随包；去依赖须检查传递树及生成bundle，不是只删三个直接依赖 |
| MIT Remotion子包 | captions、licensing、media-utils、streaming、studio、studio-codemods、studio-server、studio-shared、timeline-utils、zod-types，均4.0.513 | 直接依赖的传递工具/UI/协议/编码辅助 | 各包MIT元数据/已附相应原文，独立于依赖库许可 | MIT本身不增加同样的自定义限制，但其依赖的核心/Player/协议仍按各自许可；不能整组误判 |
| Native compositor包 | `@remotion/compositor-win32-x64-msvc`4.0.513；remotion.exe、ffmpeg.exe、ffprobe.exe及媒体DLL | Renderer真实映射getExecutablePath(type=compositor/ffmpeg/ffprobe)，不调用系统同名代替 | 包json缺独立license字段；Rust/媒体各自许可与已有源记录 | 不能套父包MIT或进程隔离放行；JS豁免拒绝不代表所有Rust源也被拒绝，准确组合条件仍需闭合 |
| Rust helper与Cargo | `remotion-Cargo.toml/lock`；ffmpeg-next `4f47c491`、ffmpeg-sys `e20f3b7d`、mp4-rust `92ba3757`；93 crates | 原生像素/图像/媒体调用输入 | 各Cargo/原源许可；sys树只有WTFPL元数据的边界已记，不能编MIT | 完整helper源/锁原包在独立test4 Source-Addendum中已取得；可选模型B这62成员没有实际收入完整25 helper源和93 crates。新B需具体配套或记录缺口；准确原生链接/工具链/组合权利仍未闭合 |
| compositor媒体 | n7.1 FFmpeg及avcodec-61/format-61/util-59/device-61/filter-10/swresample-5/swscale-8；实际配置`enable-gpl`、`enable-libfdk-aac` | 高级透明ProRes4444、帧读写、音频codec等 | FFmpeg GPL路径；x264/x265 GPL-or-later；fdk-aac-free2.0.0完整Fraunhofer NOTICE | 原FDK混合构建继续阻塞；取消普通FDK检查的补丁不是授权；旧实验AAC不已进入本轮生产 |
| splitter构建材料 | 固定旧`39ddfbb2`；已授权20件来自`50b6a0c0`逐字节同旧；旧9件不同Cargo/compile-FFmpeg/x265/av1/clean/const/Docker/README | 现有native构建溯源，未用于本轮新编译 | licensed20件GPL-2.0-or-later；旧9件准确授权解释未得 | full内部B保留原记录；公开C继承逐件排除，不能删除旧声明掩盖旧B。20件权利关闭不等于完整组合放行 |
| 原生运行DLL | compositor目录libgcc_s_seh-1/libstdc++-6/libwinpthread-1/libssp-0/libvpx-1/msvcr100/zlib1 | native动态依赖 | 对应GCC例外/各库/Windows运行库的实际条款，不能统一MIT | 准确二进制来源、构建/必要材料或再分发资格按每库未闭合项提供；系统库例外不自动覆盖随包DLL |
| Chromium | Headless Shell149.0.7790.0；chrome-headless-shell.exe、EGL/GLESv2/SwiftShader/Vulkan与LICENSE.headless_shell；实际exeSHA ec76dc3e69ffab9daddf0bbe7bf0a9e0a034b2d086741a0ae2ef6358a597537b | Remotion宿主浏览器，亦可由原生CDP直接使用 | BSD风格主体及随附混合第三方通知/各库条款 | 单独CDP不是许可豁免；准确revision/DEPS/GNargs/patch及需源码子组件映射未完整闭合。普通系统Chrome依赖不能作为新接收者环境保证 |
| Node | `tools/node/node.exe`24.13.0，原文`materials/runtime/Node.js-24.13.0/node-LICENSE.txt` | Node服务及替代CDP WebSocket宿主 | MIT及捆绑组件原文 | 保留完整通知、来源/版本对应；不把MIT解释为浏览器或媒体组件授权 |
| 独立FFmpeg CLI | `tools/ffmpeg/bin/ffmpeg.exe`9.0-essentials gyan，GCC16.1.0，GPL/version3静态依赖 | 普通ASS/视频合成，替代PNG→ProRes4444 | GPLv3路径及真实静态库条款；本机配置没有FDK启用项 | 与Remotion n7.1不同。9.0基础源已附，精确gyan构建输入/静态库/补丁/工具链仍缺；去掉Remotion不会自动关闭此门 |
| GSAP | gsap3.15.0；gsap.min.js、webThemeMotion.js、MotionSpec runtime=gsap | 实体合板、压印、材质/字面动作、入退场；HTML档案内嵌 | 已保存完整standard-license.txt/原HTML，Webflow有限用途/竞品限制，非MIT | 即便纯HTML仍有独立GPL下游权利问题；发送请求未获相容授权，不把允许商用输出等同GPL下游无额外限制 |
| 作品字体 | SourceHanSansSC-Heavy.otf/Source Han Sans SC2.005，以及实际离线字体CSS/woff2 | 中文重字形/原作品字体，非普通替代字体 | 实际字体OFL原文，保留版权/RFN/修改字体边界 | 精确字体SHA、随作品嵌入/随软件分发分别保留原文；无需凭名称判违规，替代验证必须加载本字体不靠系统偶然可用 |
| bundler传递构建工具 | @rspack/core1.7.11及Windowsnative、esbuild0.28.1、webpack5.105.0、React19.x；全树版本/许可/锁integrity见JSON | JSX编译、bundle/服务；实际native调用及构建材料 | 每包实际原文，既有组件目录；与Remotion主体许可分开 | 固定lock不代表对应所有native已齐；不得仅扫描业务源码漏npm原生输入。替代CDP不需要这些工具不等于本轮onedir已移除 |

## 自动安装、AI提示与独立路径判断

当前package.json三个@remotion直接包和核心是`^4.0.0`范围，固定lock实际4.0.513；正常构建复制既存renderer/node_modules，spec实际保留`.remotion`浏览器。失败页`studio_export_ui._install_renderer_environment`用系统npm/npm.cmd运行`npm install`，会按package/lock重新安装相关树；系统工具缺失时提示失败。这是主动按钮，不误写成无条件静默安装，但未来去依赖候选必须同步替换/禁止再引入。Mac构建是`npm ci`后`@remotion/renderer.ensureBrowser`，未执行新Mac验收。服务通过localBrowserExecutable先配置路径、再已捆绑浏览器、再系统Chrome；正常缺浏览器抛错并禁自动下载，但Remotion包自己的ensureBrowser/CLI能力仍存在，调用链须逐一确认，不能只删一个install按钮。

AI adapter/Studio presets/StyleRecipe高级特性把engine设为remotion；HTML/VisualGraph/gradient也走该路由。MotionSpec文案明确GSAP单权威，不能只把AI提示改词就改变运行依赖。纯HTML档案`web_theme.build_live_html`确实能以本项目`webThemeClock/__2byteSeek`在普通浏览器求值而不import Remotion；MotionSpec时仍内嵌GSAP。正常LIVE HTML/CDP用service.mjs和export-browser.mjs的Remotion浏览器包装，因此**现有生产LIVE/透明输出不算独立非Remotion路径**。普通Qt/ASS字幕是另一条已存在的独立路由，但不能用它的淡入淡出代替认可作品设计。

本轮最小验证采用认可木刻作品的原字面/字体/HTML/CSS/MotionSpec，独立Node内置WebSocket直接CDP、同一通用Chrome和独立FFmpeg9.0，禁止import @remotion或加载其compositor/n7.1 DLL。它证明该作品设计可以保留并形成独立工程通路；具体帧/alpha/字体/seek/取消/合成结果由最小验证回执承担。**本轮保留生产AI字幕实现，没有迁移所有旧recipe、移除生产包、改用户工程或放行公开分发。** 后续完整替代须映射VisualGraph/TrustedSubtitle/gradient/无MotionSpecCSS动画、缓存/资源/时钟/播放/错误/取消与AI生成契约；无法迁移项按真实模板列举并由用户确认范围，不暗中删功能。

## 材料和权利关闭条件

材料：准确native输入/补丁/工具链，compositor Windows x265预编译来源与参数、其他静态依赖；新配对B实际收入完整helper及锁源或提供匹配可取得附件；Chromium源码义务组件映射；独立FFmpeg9/Qt/PyAV/mpv既存缺口分别关闭。

权利：所请求GPL下游Remotion豁免已经拒绝，不能等同未来仍在等待同一回复。保持现生产链时，当前组合权利仍未解决；改用完整独立实现也须单核GSAP/媒体/浏览器/字体及素材条件。不会擅加GPL链接例外。公开范围C有自己的文件决定而不完整替代B；旧声明/旧附件保持；工程测试通过不等于许可或声学质量通过。
