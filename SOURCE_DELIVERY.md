# 0.5.0 对应源码与材料交付 / Source delivery

项目自有代码延续 GPL-3.0-only；最初从0.2.6-test.3生效的历史分界保持。0.5.0是本轮实际版本选择，本地构建不代表已经公开发布或许可缺口全部关闭。

本轮附件：
- 2ByteASR-Setup-0.5.0.exe：从当前完整开发工作区的固定快照重新冻结并构建的安装器。
- 2ByteASR-Source-0.5.0.zip：与实际构建对应的可编辑应用代码、全部构建/安装脚本、必要C#源、锁文件、资源、vendored修改和所需预编译输入；不携带私人Git历史、配置或原始私人任务记录。
- 2ByteASR-ThirdParty-Materials-0.5.0.zip：本轮所选许可、准确第三方源归档/补丁/构建事实，按licenses/展开；仍不是全部原生依赖已完整对应源码的保证。
- SOURCE_SNAPSHOT.json / release-artifacts.json / SHA256SUMS.txt / BUILD_VALIDATION.md：准确输入、dirty基础提交、构建身份、哈希与本轮通过/失败/阻塞/未执行范围。

将主源包和材料包展开到同一新目录；SOURCE_SNAPSHOT.json列出实际输入。按[构建说明](BUILD_FROM_SOURCE.md)验证重建。预编译Node/Chromium/Remotion媒体工具/npm原生组件/离线wheels是运行或构建输入，不是它们的对应源码。许可/准确材料剩余条件见[第三方源码](licenses/SOURCES.md)和[当前路线](licenses/GPL3_ROUTE.md)。

明确区分：A为固定的完整内部构建输入；B为配对源码与必要材料；C为从同一最新快照增量选择的[独立公开源码范围](SOURCE_ONLY_SCOPE.md)。C延续r2排除理由，但不是永远固定的2431路径白名单，也不能替代B。旧test.4/r2附件原件保留，不改名充当0.5.0。

当前尚无公开安装包。0.5.0 源码与文档已进入原私有仓库 main 的更新准备，专用 Release 保持 draft 和 prerelease；私有草稿附件用于作者受控的发布准备，不是公众下载，也不表示第三方授予额外权利。正式提供完整附件时须同处、同等便利提供准确对应源码和必要材料；main 最新树或自动 GitHub 源码 ZIP 不能代替 Windows Setup 或 Mac 应用的完整对应源码。

Third-party combination permissions and exact native build-source gaps remain separately documented. This local 0.5.0 build is not a public release or a complete source offer; consult the validation and source manifest for the actual scope.

## 本轮桌面增量

已封存的 Windows Setup 及其 A/B、旧 C 原件保持。新 C 来自最新桌面源码和既有 r2 允许范围，记录与旧 C 的逐件差异，排除内部归档、任务、VM、私人 QA 样本、原品牌素材及已退场的 13 件 Docker 专用输入；不把旧 C 改名覆盖。

macOS 原生桌面实验的可编辑代码、依赖锁与构建入口纳入源码增量。实际 .app、安装 ZIP、准确原生输入和分层验收状态须由本轮真实 Mac 回执证明；没有真实产物时明确没有产物，不用空目录或脚本通过替代。普通使用与开发能力边界见 [Mac 桌面说明](docs/deployment/macos-experimental.zh-CN.md)。macOS 对应第三方材料也须按实际输入单独记录，既有 Windows 材料不自动成为完整 Mac 对应材料。

Docker 专用部署内容转为内部历史归档；此前通过的 CPU 实验仍是历史成功，不作为本轮桌面交付或当前下载入口。桌面共用代码与必要第三方声明继续保留。
