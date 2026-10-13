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

## 2026-10-11：0.6.5 公开前复核

对象是 0.6.5 r9 的实际载荷（Setup SHA-256 `16904292c22016ae9dfef823c2cff6c7b5083bb56c31cc505a5f4805e65eb4ab`）、发布提交 `a74c6d645858fa5cbacc80fda7c213f74267a198` 和 v0.6.5 未公开草稿的 15 个附件。结论：**安装包、renderer/app 组件包和 Source 附件仍不能公开分发**，v0.6.5 保持草稿。

**一、材料已经足够，只是状态没写（已更新）**
- 源码交付：`2ByteASR-Source-0.6.5.zip` 与 `2ByteASR-ThirdParty-Materials-0.6.5.zip` 合起来逐字节重现构建源码指纹 `88dd50773fcad681c6bf2c73c28a53aa6749b4424c40019165bad3d48f66fbfb`（1199 个输入，0 差异）；发布提交的干净检出也重现同一指纹。附件已上传到未公开草稿，尚未在线公开。
- `2ByteASR-0.5.0-ThirdParty-Sources.zip` 仍对应 0.6.5 实际随附的版本：gyan FFmpeg 9.0、mpv `7b8915bc1`（其 FFmpeg `N-126125-g1d7b14f61`）、Qt/PySide 6.9.2、Remotion 4.0.513 Rust 补充材料。沿用，不重新打包。

**二、可以直接补齐（本轮已补）**
- `ffmpeg.exe`、`ffprobe.exe`（gyan 9.0）、`node.exe` 24.13.0、mpv 3 个文件和 Remotion compositor 的 17 个可执行文件/DLL 已按 SHA-256 登记：[0.6.5-binary-register.json](materials/runtime/0.6.5-binary-register.json)。登记只标识文件，不代表许可义务已满足。

**三、确实未解决、阻挡公开分发**
1. **compositor 的 GPL+FDK 混合构建**：`renderer/node_modules/@remotion/compositor-win32-x64-msvc/` 里的 `ffmpeg.exe`、`ffprobe.exe`、`avcodec-61.dll` 等，实测 `-buildconf` 同时有 `--enable-gpl`、`--enable-libx264`、`--enable-libx265`、`--enable-libfdk-aac`、`--enable-encoder=libfdk_aac`，没有 `--enable-nonfree`。FFmpeg 把同时启用 GPL 与 FDK 的构建定为不可再分发，说明文字解决不了。需要同版本、不含 libfdk_aac 的构建（或权利人提供的相容构建），重新验收后重建 Setup 与 renderer 组件。
2. **Remotion 4.0.513 与 GSAP 3.15.0 同自有 GPL-3.0-only 代码组合**：Remotion 已拒绝所请求的 GPL 下游豁免，GSAP 标准许可有竞争用途限制。要么由所有者决定为自有代码加 GPL 第 7 节附加许可（须全部自有代码权利人同意），要么改走独立渲染路径（已有最小 CDP 验证，未迁移生产）。本轮不擅自决定。
3. **GPL 二进制的对应源码缺口**：gyan FFmpeg 9.0 的静态依赖、补丁与工具链；mpv 所用 libplacebo `v7.360.0-111-g22ee762-dirty` 的本地修改；PyAV 的 MSYS2 运行库；compositor 的原生构建输入；Chromium Headless Shell 中需要源码的子组件映射。
4. **素材**：`assets/theme-references/balatro-crt-mult.png` 是真实直播画面（第三方游戏画面、主播虚拟形象、观众弹幕），没有再分发授权记录，却随 app 组件、Setup 和 Source 附件分发。运行时不使用它，只有开发脚本 `scripts/author_balatro_candidates.py` 引用。

没有 Windows 代码签名证书是另一回事，不属于许可阻挡；发布说明如实标示即可。
