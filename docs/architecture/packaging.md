# 0.8.1 Docker 浏览器桌面打包

2026-10-19：此分支在 v0.8.1 上增加独立 Docker 分发。用户通过浏览器使用原桌面，视频与声音由 Selkies 传输；字幕和视频导出仍由原流水线执行。Windows/macOS 的现有入口不启用容器专属逻辑。

## 构建与入口

Dockerfile 使用固定摘要的 LinuxServer Debian Trixie Selkies、Python 3.10 和 Node 22，Python 依赖按已验证 constraints 固定。主运行环境是 /opt/venv，CPU PyTorch/torchaudio 2.11；ffmpeg、mpv、Chromium 和中文字体位于镜像。Python 3.10 遵循 0.8.1 的主环境预检，不跳过契约。

桌面启动运行 `python -m twobyteasr.container.launch`，然后进入原 quick_start.main。`TWOBYTEASR_CONTAINER=1` 只启用容器适配：首次设置、Linux 下载进程、Fernet 密钥保存、mpv 的 X11 嵌入窗口。原 Unix socket IPC 保留，mpv 使用软件解码，浏览器桌面固定 1600×900。

构建时写入 /app/build/2byteasr_build.json，包含原版提交、代码提交及源码文件摘要。`.dockerignore` 使用允许清单，不复制用户配置、工程、模型、私有环境、Git 和验收输出。发布归档由独立工作树生成。

## 数据与模型

| 路径 | 所有权与用途 |
| --- | --- |
| /app、/opt/venv | 镜像程序和依赖 |
| /config | 配置、工程库、缓存；持久命名卷 |
| /models | 固定版本并通过 SHA-256 的权重；持久命名卷 |
| /media | 用户明确挂载的素材和导出目录 |

新配置默认 MOSS Pro API 主力 + Qwen3 本地字级对齐；已有设置文件逐字保留。API Key 密文和 container-secrets.key 同放配置卷，密钥权限 0600；备份必须包含两者。它避免明文写入设置，保护边界仍是宿主机和卷权限。Windows DPAPI 文件不能直接迁移。

Linux 模型工坊的下载对话框启动 QProcess，执行 container.models，复用 0.8.1 原锁文件、来源切换、断点下载与哈希校验。允许模型：sensevoice、paraformer、funasr_nano、qwen_aligner、ja_ctc_aligner、whisper_turbo。模型加载沿用主 CPU 环境；GPU/MLX 不列入此镜像支持范围。

## 验收边界

最终镜像 38 项正常 GUI 检查涵盖真实识别、字级时间、X11 变化画面、实际 PulseAudio 声音、编辑剪切、保存重开、字幕与视频导出。9 项工坊检查实际点击标签和下载按钮；4 项跨容器检查核对文件摘要、工程加载与测试密钥解密。云端协议使用明确标记的本机模拟服务，不能当作真实云端准确率测试。

源入口验证通过专用容器、专用卷、独立临时 profile 完成。所有素材均为本轮合成短音视频，不读取用户工程或日常配置。持久化与启动方式见 [使用说明](../../README.docker.md)，长期边界见 [ADR 0136](../adr/0136-docker-browser-desktop-and-container-data.md)。

## GitHub 分发

固定标签 [v0.8.1-docker.1](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.8.1-docker.1) 提供源码构建入口；main 首页链接同一使用说明。预构建镜像归档分为 1,500,000,000 与 1,163,312,896 字节两段，每段低于 GitHub 单附件限制。启动包导入器先验证两段与合并归档 SHA-256，再执行 docker load；损坏分片不会被导入。另附对应源码 ZIP、启动 ZIP 和 SHA256SUMS。公开源码 a2a7e2b4 与镜像 76e9bdb7 的 821 项运行源码逐项一致。

这个 Release 不改变桌面版 v0.8.1 的 Latest 标记；不依赖 GHCR / Docker Hub，也没有把模型权重写进镜像。Windows / Linux 重组验证与五个远端附件摘要、匿名下载已通过；仓库原有全量 CI 收集失败仍单列保留。
