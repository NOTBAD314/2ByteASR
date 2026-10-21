# 随附 FFmpeg（Windows）的对应源码材料：BtbN/FFmpeg-Builds autobuild-2026-09-30-13-08

适用对象：Windows 安装包里的 `tools/ffmpeg/bin/ffmpeg.exe` 与 `tools/ffmpeg/bin/ffprobe.exe`（2026-10-14 起在开发树中替换 gyan.dev 9.0-essentials；首个随附它的正式版本待定）。

## 二进制来自哪里

| 项目 | 值 |
| --- | --- |
| 构建项目 | https://github.com/BtbN/FFmpeg-Builds （MIT，见 `BtbN-FFmpeg-Builds-LICENSE.txt`） |
| Release 标签 | `autobuild-2026-09-30-13-08`（月末构建；BtbN 说明月末构建保留两年） |
| 构建仓库提交 | `6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b` |
| 压缩包 | `ffmpeg-n9.0.2-17-g2a571b6068-win64-gpl-9.0.zip`，194,034,585 字节 |
| 压缩包 SHA-256 | `a0e45723c72141975f51d8666302e614711745f3102b704ca3f82c897a58d278`（与 GitHub 服务端摘要、该 Release 的 `checksums.sha256` 一致） |
| `bin/ffmpeg.exe` | 165,155,840 字节，SHA-256 `513368c81583572ce1d09d5c7ff827feed1a63db352412a5001f4da3a1583d98` |
| `bin/ffprobe.exe` | 164,954,624 字节，SHA-256 `0fd8f3bae96cc707993bcd8c56c13f8cd73962d37dbcaac0dad4fe3a0ce1f68f` |
| 构建目标 | `win64` + `gpl` + 附加 `9.0`（静态，单个 exe） |

压缩包里的 `ffplay.exe`、`doc/`、`presets/` 不随附。包内 `LICENSE.txt` 与 `licenses/ffmpeg-GPLv3.txt` 逐字节相同。

## 对应源码由哪些部分组成

1. **FFmpeg 本体**：https://github.com/FFmpeg/FFmpeg 分支 `release/9.0` 的提交 `2a571b606854520cf89804d8030c8b328e621689`（`n9.0.2-17-g2a571b6068`）。BtbN 不给 FFmpeg 打补丁（见仓库 `build.sh`：克隆分支后直接 configure）。实际 configure 参数见 `../build-records/btbn-ffmpeg-buildconf.txt`。
2. **构建脚本与补丁**：本目录 `FFmpeg-Builds-6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b.tar.gz`（GitHub 对该提交生成的源码包，107,893 字节，SHA-256 `81da4f7c878dc0f60e6b8d0049a112e32178e20f025d468fe4e99e77b2dfe0ec`；gzip 字节不保证每次下载都相同，身份以提交号为准）。其中 `scripts.d/` 为每个依赖库的下载与构建步骤，`patches/aom`、`patches/aribb24` 为仅有的补丁文件，`images/` 为构建镜像定义。
3. **每个依赖库的固定来源**：`dependencies.json`。逐项给出仓库、固定方式（99 个完整 git 提交、4 个 git 标签已解析为提交、2 个 SVN 修订号）、是否进入 ffmpeg.exe，以及 2026-10-14 的公开可取检查（105/105 可取）。子模块、shaderc 的 `git-sync-deps`、glib 的 meson subprojects、opus 模型下载、Rust crate（`Cargo.lock` / `cargo vendor`）都由各上游仓库在该提交里的锁定文件决定。
4. **依赖源码本体**：按 GPLv3 §6(d)，指向上表所列上游仓库的固定提交，本项目未另行打包这些源码（2026-10-14 用户决定）。

`50-libcurl/` 下的 libpsl、nghttp2、nghttp3、ngtcp2 会在镜像里构建，但 FFmpeg 9.0 关闭了 libcurl，它们不进入 ffmpeg.exe（二进制中也找不到它们的字串）；清单中 `linked_into_ffmpeg_exe=false`。

## 怎样重建

在有 Docker 的 Linux 机器上，于解压后的构建仓库目录执行：

```
./makeimage.sh win64 gpl 9.0
./build.sh win64 gpl 9.0
```

`build.sh` 用 `git clone --branch` 克隆 `release/9.0` 分支当时的最新提交，不能直接写提交号。要得到与上面相同的 FFmpeg，可准备一个构建容器能访问的 FFmpeg 仓库，在其中建一个指向 `2a571b606854520cf89804d8030c8b328e621689` 的分支，再用环境变量 `FFMPEG_REPO_OVERRIDE`（该仓库地址）和 `GIT_BRANCH_OVERRIDE`（该分支名）运行 `build.sh`。

## 已知限制（如实记录）

- **编译工具链没有按提交固定**：`images/base-win64` 在构建镜像时克隆当时最新的 crosstool-NG，Rust 取当时的 stable。二进制自报 `gcc 16.2.0 (crosstool-NG 1.29.0.7_b1a94f6)`。通用编译器不属于 GPLv3 的“对应源码”；静态链接的 libgcc、libstdc++、libgomp 适用 GCC 运行库例外。影响的是能否逐字节重建，不是源码是否齐全。
- 本项目没有执行重建，也没有逐字节复现官方二进制。
- 该构建静态链接 **libdvdcss**（DVD CSS 解扰，GPL-2.0-or-later），供 FFmpeg 的 dvdvideo 解封装使用；2ByteASR 不读取 DVD。2026-10-14 用户确认可以随附。
- 各依赖库自身的许可原文（BSD/MIT 等要求在二进制分发中保留的版权声明）尚未逐项收集进 `licenses/`，见 `licenses/DISTRIBUTION-STATUS.md`。
