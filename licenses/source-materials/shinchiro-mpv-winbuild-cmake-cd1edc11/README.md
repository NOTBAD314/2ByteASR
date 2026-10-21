# 随附 mpv（Windows）的构建配方：shinchiro/mpv-winbuild-cmake 提交 cd1edc11

适用对象：Windows 安装包里的 `tools/mpv/`（mpv `v0.41.0-923-g7b8915bc1`）。0.6.5 至 0.7.5 各版随附的是同一份。

## 二进制来自哪里

| 项目 | 值 |
| --- | --- |
| 构建项目 | https://github.com/shinchiro/mpv-winbuild-cmake |
| 构建运行 | [31755832255](https://github.com/shinchiro/mpv-winbuild-cmake/actions/runs/31755832255)（工作流 `mpv clang`，2026-08-14 00:00 UTC，结果 success） |
| 构建配方提交 | `cd1edc11dc6887a50f705717619d879f5a93a488`（2026-08-06，“libsrt: disable pthread_atfork”） |
| 原包 | `mpv-x86_64-20260814-git-7b8915bc1d.7z`，33,583,248 字节 |
| 原包 SHA-256 | `1bf3b029da2c98e605e00e85f21ee3142f22a1dcc4ceb5c827b5c51e36e390f9`（与上游发布时 GitHub 记录的摘要相同） |
| 上游发布 | 已被上游删除（只保留最近 30 个发布）。原包未改动，存档在本项目 [v0.6.5 发布](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.6.5)和 GitCode 同名发布 |
| `mpv.exe` | 119,761,408 字节，SHA-256 `09dc5c350a70b536cc91015e7a856f77c933fa9d7f4c41563666e51c998a0243` |

运行记录、日志摘录和 13 个文件的逐字节核对见 [`../build-records/mpv-upstream-run.txt`](../build-records/mpv-upstream-run.txt)。

## 本目录有什么

- `packages.json`：从配方的 `packages/*.cmake` 读出的 113 个包。每个包写明源码仓库或下载地址、怎样固定、配方里给它的补丁文件，以及 2026-08-14 那次运行是否下载了它（下载了 90 个，取自构建日志里的 `ninja download` 目标列表）。
- **配方源码包本身不放在这里**，原因见下面“许可问题”。它是 GitHub 对该提交生成的 `mpv-winbuild-cmake-cd1edc11dc6887a50f705717619d879f5a93a488.tar.gz`：81,599 字节，SHA-256 `d82f5f06336352d1ccde79d91d1ce48701aa422e6d72674befa607c3180c4c2c`，171 个文件，包头注释是该提交号。gzip 字节不保证每次下载都相同，身份以提交号为准。2026-10-17 下载，存在共享工作区的 `tmp/mpv-archive-20261017/recipe/`（不随包分发）。

## 对应源码由哪些部分组成

1. **mpv 和 FFmpeg 本体**：mpv `7b8915bc1`、FFmpeg `1d7b14f61` 的源码在 v0.6.5 发布附件 `2ByteASR-0.5.0-ThirdParty-Sources.zip` 里（`mpv-7b8915bc1.tar.gz`、`ffmpeg-1d7b14f61.tar.gz`）。
2. **构建配方与补丁**：上游仓库的公开提交 `cd1edc11`。配方自带 16 个补丁文件，其中 9 个属于这次运行用到的包：fontconfig 2 个，libbs2b、luajit、mujs、openssl、spirv-cross、vulkan、xvidcore 各 1 个。libplacebo 版本里的 `-dirty`，来自配方把 `3rdparty/glad`、`3rdparty/fast_float` 两个子模块目录换成单独取的 glad、fast_float，不是源码补丁。
3. **其余依赖库**：见 `packages.json`。这次运行用到的 90 个包里：
   - 52 个取默认分支，32 个取指定分支（多数是 `main`）。构建当天取到的是哪个提交，上游日志没有记录。
   - 5 个是带哈希的固定压缩包。
   - 1 个（`mpv-release`）只在打 mpv 正式版时使用，这次没有用到。
4. **依赖源码本体**：本项目没有另行打包。按 GPLv3 §6(d)，指向上游公开仓库。

## 许可问题（如实记录）

- 配方仓库**没有 LICENSE 文件**，GitHub 识别不出许可，README 里也没有许可说明。
- `licenses/` 整个目录会随安装包和程序内更新分发。把源码包放进这里，就等于由本项目再分发一份没有明确许可的代码。
- 本项目以前遇到类似情况时，只把它留作内部证据，不放进分发范围。那次是 Remotion `rust-ffmpeg-splitter` 的旧版文件，见 `../../SOURCES.md` 的“test.4定点更正”。
- 所以目前的做法是：
  - 本目录只放本项目自己写的说明和清单（事实、地址、哈希）。
  - 配方本身指向上游公开提交。
  - 2026-10-17 用户决定：源码包只作内部证据，留在共享工作区的 `tmp/`，不随包分发；本目录只放说明和 `packages.json`，配方指向上游公开提交。
- 配方里的 `cmake/CMake-v3.31.6-Modules-ExternalProject.zip` 是 CMake 自带的模块（BSD-3-Clause），与上面的问题无关。

## 已知限制

- **依赖库的提交没有记录**：见上面第 3 条。这是现有缺口，只有上游能补；即使拿到配方，也不能还原当天的依赖版本。
- **编译工具链没有按提交固定**：clang 工具链取 LLVM `release/22.x` 分支，mingw-w64 取默认分支，构建时还会用缓存里的旧工具链。通用编译器不属于 GPLv3 的“对应源码”，影响的是能否逐字节重建。
- 本项目没有执行重建，也没有逐字节复现官方二进制。
