# 0.2.6-test.4：GPL 路线与第三方分发状态

自有代码已采用 GPL-3.0-only，允许商用及收费分发。第三方原文、原有 or-later、版权、NOTICE 和例外保持原样。完整材料入口为 [COMPONENTS.md](COMPONENTS.md)、[SOURCES.md](SOURCES.md)、[MODELS.md](MODELS.md)。本地内部候选尚不能作为已完成许可义务的公开发行物。

| 分类 | 当前结果 |
|---|---|
| A：旧理由撤销 | 不再存在主项目禁售与GPL的冲突；为禁售而去GPL/去x264/x265或购买商业许可的方案暂停。CPU H.264/HEVC、播放和特效保留。仅表示这个冲突原因撤销 |
| B：已处理 | 标准GPL原文与only声明；安装器读取载荷原文；共享离线许可/声明/源码入口；FireRed五文件修改标记；组件权利人误抽取纠正。四项Qt排除保留，实际候选检验以同版本回执为准 |
| C：缺源码/构建材料 | PyAV MSYS2运行库准确版本/所需材料；FFmpeg9.0静态依赖；mpv/libplacebo dirty修改；Qt wheel与媒体FFmpeg构建对应；compositor预编译输入及Rust helper；Chromium内需源码部分。Qt/PySide完整基础源码、mpv/FFmpeg固定源码及fdk-aac-free2.0.0原文/源码已补，仍不是全部材料 |
| D：组合/权利问题 | Remotion/GSAP实际运行时代码与GPL组合后的下游权利；compositor GPL+FDK实际混合构建；贡献权属；部分模型条款归属。两组无授权图像在test.4源码已替换，旧test.3不变。主项目GPL不能代替这些授权 |

x264 b35605ace3ddf7c1a5d67a2eb553f034aef41d55及x2654.2、419182243fb2e2dfbe91dfc45a51778cf704f849的实际代码头写明GPL第2版或以后版本。见 [x264头文件](materials/gpl-route/x264-b356-x264.h)、[x2654.2](materials/gpl-route/x265-4.2-x265.h)、[x265固定提交](materials/gpl-route/x265-419182243-x265.h)；完整源包/来源映射见SOURCES和component-index。可以选择GPLv3不等于所有DLL已对应：PyAV的x264固定构建DLL与wheel同SHA，配方b35605a对应；x2654.2源包版本文件明确4.2+1-e444744，两项版本疑点已关闭；其余依赖需逐项对应。

Remotion4.0.513的[原许可](materials/remotion/4.0.513/LICENSE.md)包含实体/员工数资格及衍生品销售/出租/许可限制。`renderer/service.mjs`、`render-overlays.mjs`与应用组件实际使用其渲染API，不能按仅分发输出处理。现有许可不是对整个GPL覆盖组合所有下游均无额外限制的授权（GPL §5(c)、§10）；具体组合的法律范围仍待审阅。个人免费资格或Company订阅不自动解决。compositor的媒体GPL/FDK-free材料是另一问题，不能用JS许可替代。

GSAP3.15.0的[条款](materials/gsap/3.15.0/standard-license.txt)允许AI产码、商用及不直接竞争的垂直工具，但保留特定竞争用途和相关逆向限制。应用字幕JS实际import GSAP，因此当前用途可能允许与GPL下游能行使全部必要权利必须分开。作为GPL覆盖组合分发时，额外限制不能靠第三方声明消除。需要相容授权或另行审阅批准的实现边界方案；不擅加GPL链接例外。

Qt各模块按真实许可路径履行，LGPL替换/调试条件保留。GIMP桥接仍为GPL3-or-later。素材授权须覆盖原文件随商业软件/修改版再分发，不能仅凭演示合作许可。未查明部分保持未查明。

补充源码与校验：[supplement-20261001.json](source-materials/supplement-20261001.json)。fdk-aac-free实读原NOTICE仍有Fraunhofer限制，不能因构建脚本绕过nonfree检查就按GPL放行。
## 2026-10-07授权回复与实际依赖更新

Remotion4.0.513已回复：**所请求覆盖GPL下游的特殊豁免已拒绝**；Rust/FFmpeg按各自许可。原请求的准确原生构建材料未提供，额外组合权利未提供，两项**分别未解决**；没有将所有项写成拒绝或已获许可。个人免费资格、非商用声明、Company订阅及独立进程不能代替这些权利。

当前生产高级字幕仍保留；直接/传递npm包、真实API、compositor/Rust/媒体DLL、Chromium、自动npm安装/备用CLI、两个独立onedir及配对B内部材料已分别核对。现有HTML档案可独立求值，正常Studio宿主仍调用Remotion；最小纯CDP验证不会偷偷替换全部AI功能。原封存Setup/候选/A/B/C声明与自有GPL-3.0-only、0.2.6-test.3分界保持。

[组件、实际材料及发布门](REMOTION_DEPENDENCY_AUDIT.md)。新统一候选保留既有实现并继续标公开发布阻塞；纯源码C不代替内部B及原生对应材料。

## 2026-10-11：0.6.5 公开前复核与结论

对象：0.6.5 r9 实际载荷（Setup SHA-256 `16904292c22016ae9dfef823c2cff6c7b5083bb56c31cc505a5f4805e65eb4ab`）、构建来源提交 `a74c6d645858fa5cbacc80fda7c213f74267a198`（tag `v0.6.5`）和 Release 的 15 个附件。结论：**这些安装包与附件可以公开分发**。处理方式和仍未提供的材料如下。

1. **compositor 的 FDK：保留现有构建，取消更换计划。**
   - 实测 `renderer/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe` 可以用 `libfdk_aac` 编 LC-AAC，但 HE-AAC（AOT 5）和 HE-AACv2（AOT 29）被拒（`Unable to set the AOT`），与去掉 SBR/PS 的 fdk-aac-free 一致。Remotion 构建脚本 `compile-fdkaac.mjs` 取的是 `fdk-aac-free-2.0.0`，`fdk-aac-free.patch` 只把 `libfdk_aac` 移出 nonfree 名单；fdk-aac-free 2.0.0 源码与 NOTICE 已附。
   - Fedora 官方 `ffmpeg` 包（`License: GPL-3.0-or-later`，`--enable-gpl --enable-version3 … --enable-libfdk-aac`，`Patch2: ffmpeg-allow-fdk-aac-free.patch`）以同样组合公开分发。依据是 Fedora Legal 在 Red Hat Bugzilla 1501522 comment 112（2019-06-11）的判断：FSF 认为 FDK AAC 许可因第 3 条与 GPL 不相容；fdk-aac-free 已不受 AAC 专利约束，第 3 条不起作用，所以这一特定实现与 GPL 相容。FSF 的相反看法同样记录在此。
2. **Remotion / GSAP：用作者自有代码的 GPL 第 7 节附加许可解决**（见 [PROJECT_LICENSE.md](../PROJECT_LICENSE.md)）。
   - renderer 实际随附的 257 个 npm 包里没有 GPL 系许可，git 历史只有作者一人提交，所以这个组合里的 GPL 代码只有作者自有的部分，附加许可覆盖它。
   - Remotion 4.0.513 与 GSAP 3.15.0 的原条件对下游继续有效：Remotion 免费许可只给个人、3 人以内公司等，其他组织需要 Company License；GSAP 标准许可允许网站、网页应用和数字界面使用，不许用于与 Webflow 可视化动画构建竞争的无代码工具。附加许可不代表 Remotion 或 Webflow 的授权。
3. **对应源码：逐项核对后，只剩两处确实缺少的构建材料。** 详见 [SOURCES.md 的 2026-10-11 节](SOURCES.md)。
   - **libplacebo 没有本地源码改动。** mpv-winbuild-cmake 的 `packages/libplacebo.cmake` 没有补丁步骤，该文件自 2025-09-01 起未变，覆盖 2026-08-14 的构建。它删掉 `3rdparty/glad` 和 `3rdparty/fast_float` 两个子模块目录，改为链接另行取得的 glad（`glad2`）与 fast_float（`main`），`git describe --dirty` 因此显示 `-dirty`。对应源码是上游 libplacebo 提交 `22ee762` 加该配方，均公开。
   - **PyAV 的 MSYS2 运行库只有 `libiconv-2.dll` 需要提供源码。** 这个文件是 libiconv 1.19，LGPL。本版 Release 已附 MSYS2 官方源码包 `mingw-w64-libiconv-1.19-1.src.tar.zst` 及其签名。其余几个不需要提供源码：`libgcc_s_seh-1`、`libstdc++-6` 适用 GCC 运行库例外，`libwinpthread-1` 是 MIT 类许可，`zlib1` 是 zlib 许可。
   - **compositor 的 x264 已满足**：GPL 版 `compile-x264.mjs` 加实际编入的 x264 `b35605a` 源码。
   - **仍缺（唯一一处）**：gyan FFmpeg 9.0 essentials（`ffmpeg.exe`、`ffprobe.exe`）。已确认与 gyan 官方 9.0 压缩包逐字节相同，FFmpeg 本体 `n9.0` 已附，包内 README 列出的外部库版本已全部列入来源索引（openal-soft 只写了“latest”）。仍缺 gyan 的构建脚本与可能的补丁，以及 13 个未标版本的链接库与 openal-soft 的确切版本。
   - **compositor 的 x265 已满足**：随附库是 x265 默认 8 位配置（`[Windows][GCC 12.2.0][64 bit] 8bit`），源码 `419182243` 含 CMake 构建系统，相关补丁 `x265-api.patch` 改的是 FFmpeg 且已附；只缺 Remotion 当年的命令行记录，不是必要材料。
4. **素材**：`assets/theme-references/balatro-crt-mult.png` 已在 `SOURCE_FILE_DECISIONS.json` 里按“inherited approved source/material role”纳入公开源码，运行时不使用；`docs/release-0.2.6-test.2-zh` 分支的截图是当时按需求做的产品概览。两者都不含密钥或口令，本轮不改写历史。
5. 已登记：随附第三方程序按 SHA-256 记在 [0.6.5-binary-register.json](materials/runtime/0.6.5-binary-register.json)。

没有 Windows 代码签名是另一回事，不属于许可问题，发布说明已如实标示。
