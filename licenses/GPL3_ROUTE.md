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
