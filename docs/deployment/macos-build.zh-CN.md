# macOS 原生开发构建

2026-10-23：当前候选使用固定 Sonoma 媒体闭包、真正重编译的 Tesseract、兼容的完整 Remotion FFmpeg 7.1 媒体组和随包预编译 wheels。普通用户不需要 Homebrew / CMake / 编译器。构建命令沿用下方入口，必须查看新的 `binary-compatibility.json` 和候选执行回执；历史 run 记录不代表本轮完成。[相容性说明](macos-compatibility.zh-TW.md) · [输入来源](../../packaging/macos/MEDIA_INPUTS.md)。

此页与[普通用户实验版说明](macos-experimental.zh-CN.md)分开。在 macOS 14 Apple Silicon arm64 使用完整可信源码，构建 Python 3.10.11；不是 Windows 交叉构建，不复制宿主 node_modules/EXE/DLL/wheel。

历史私有run36893768101固定source/workflow `61ccea07e22ba8434030a2561779da801b4ad7c4`，真实arm64 `.app.zip` 已生成。媒体/架构/动态库/签名/Unicode解压搬移通过；搬移后二进制和LaunchServices均使用独立profile与 `/usr/bin:/bin:/usr/sbin:/sbin`，应用实际MainWindow/资源回执及退出0通过。GUI SenseVoice文件校验完成但加载worker失败，Home/Studio未执行，真实ZIP保持。

固定输入见 `packaging/macos/native-dependencies.lock.json`、GUI/CPU requirements 和 `bootstrap.lock.json`。关键 wheel 对实际 pip install report 校验版本/SHA；本轮 FFmpeg-full 9.0.1_1、mpv 0.41.0_9、Node 22.16.0、重编译的 Tesseract，以及 Remotion JS / Rust 4.0.513 与同 ABI 的 FFmpeg 7.1 兼容媒体组都绑定准确原生输入，漂移即失败。实际 Qt、PyAV、模型运行库和 Chromium 的架构/动态库关系在回执中记录。

```bash
QA_ROOT="$PWD/tmp/macos-native-sonoma"
export MACOSX_DEPLOYMENT_TARGET=14.0
export TWOBYTEASR_TEST_ROOT="$QA_ROOT"
python3.10 scripts/macos_install_media.py --output "$QA_ROOT/media"
python3.10 scripts/macos_prepare_runtime.py \
  --runtime "$QA_ROOT/runtime" --receipt "$QA_ROOT/runtime.json"
"$QA_ROOT/runtime/bin/python" scripts/macos_doctor.py \
  --require-host --probe-torch --output "$QA_ROOT/doctor.json"
"$QA_ROOT/runtime/bin/python" scripts/macos_build.py \
  --source-sha "$(git rev-parse HEAD)" --runtime "$QA_ROOT/runtime" \
  --output "$QA_ROOT/build" --media-receipt "$QA_ROOT/media/media-install.json"
```

CI 要求干净40位源码 SHA；`--allow-dirty` 仅显式本地实验并保留固定输入。每次使用新输出目录，不覆盖旧包。PyInstaller 只生成 arm64 `.app`，记录 source identity、build_id、原文件、实际 Python/原生工具清单。

真实 `.app` 先归档，再从 ZIP 解压到另一中文/日文路径，核对内容、权限、符号链接、Mach-O、外部链接及 ad hoc 签名，并通过搬移后二进制和 LaunchServices 以最小 PATH 启动。后续模型/桌面失败不丢弃已生成的真实包，没有 `.app` 时不生成占位 ZIP/DMG。

`macos_desktop_smoke.py` 从普通 GUI 工坊准备单一 SenseVoice，再由首页真实 Start 识别中文，进入 Studio 编辑/剪切/撤销重做/保存重开/四格式及短视频验收。它需要有权使用的短中文输入，不注入识别结果。内部 CI 样本只进入专用私有构建分支，不自动纳入有限公开源码 C。

手动工作流仅由 `workflow_dispatch` 启动。当前默认在标准 `macos-14` arm64 runner 建置，同一个 DMG 再交给标准 `macos-15` 验证；应用任务最多 100 分钟，较新系统回归 45 分钟，独立已安装模型任务 65 分钟。所有 Action 固定完整 revision，默认只读权限、不保存 Git 凭据、无生产 Secrets 或正式 Release 发布。`candidate_run_id` / `candidate_source_sha` 可复用已有 DMG；`candidate_mlx_only` 仅补测 MLX，结果明确记录请求范围。App 与外部验收器的提交分开记录。只上传有上限的必要回执及 DMG，保留 1 天；不上传模型、运行库与用户缓存。标准公开仓库 runner 与付费 xlarge 要分开，不能自动升级到付费 runner。

MPS 可用性、小 tensor、具体模型、VideoToolbox实际硬件编码和预览后端分别记录。`macos_hardware_probe.py` 真正尝试25帧编码且禁用软件 fallback；失败表明当次 runner 未通过硬件检查，CPU与模型正确性另验。

Mac 材料按真实载荷增量记录。Windows 材料不自动证明 Mac 完整对应源码，内部构建不自动放行公开发行。官方参考：[PyInstaller macOS架构/签名](https://pyinstaller.org/en/stable/feature-notes.html)、[PyTorch MPS](https://docs.pytorch.org/docs/stable/notes/mps.html)、[Actions额度与存储](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。

本轮真实run36882470527固定d41b3359在media阶段失败：runner core的rustup.rb/openssl@1.1.rb原有改动被过严的干净检查拒绝，未取得媒体或构建.app。后修订先在QA目录准备官方固定core，安装期间仅临时切换该配方目录；原目录完整保留，成功/失败均恢复，不改写它的Git状态、不删除无关预装工具。此后builder不查询已恢复的旧公式元数据，仅重验安装receipt、SHA及准确路径。24本机定向测试包含文件级恢复；该隔离修订已在随后五次新增原生运行通过，包含真实媒体身份、app构建与原tap恢复；此前d41失败仍封存。

首次CI36875057224实际倒入ffmpeg9.0.1_1/mpv0.41.0_9，旧流程未消费媒体锁，PyInstaller前失败。旧日志没有保存API缓存/完整Homebrew环境，缓存原因仅推测。第二轮仍保留原版本与归档SHA，新增官方[core固定快照](https://github.com/Homebrew/homebrew-core/tree/0211e9c2eeea26bc0f1b382446dc076321e9a871)和两份配方定义SHA；原bottle仍已实际下载验证可用。安装使用该core checkout，禁止滚动API与自动更新，由Homebrew处理依赖和重定位，只安装/重装这两个选定媒体公式，不全局升级。归档SHA、keg pkg_version（含revision）、INSTALL_RECEIPT的arm64/poured_from_bottle/core身份、PATH与真实工具路径、可执行文件SHA、lipo和运行输出分别校验。预装正确版本也重新取得安装证据。builder重查receipt与准确路径，不重新查PATH或最新仓库声明；归档摘要不等于解压/重定位后的工具摘要。最新分层结果见实际验证状态，不移植首次CI结论。
