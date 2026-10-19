# 0.8.1 Docker 版当前状态

2026-10-19：本分支将公开 v0.8.1 做成 Linux amd64 / CPU 的浏览器桌面版，镜像已在本机构建并通过真实识别与导出检查。默认推荐 MOSS Pro 云端转写 + Qwen3 本地字级对齐；设置、工程和模型分卷保存。此分支仍使用 0.8.1 发布时的平铺模块，不包含之后的日常版功能。

镜像代码提交为 `76e9bdb7ebeab83cc4b940d315ad0d06de7ca764`，原版基线为 `83f928c1aa445fd17312ffbfb30c88cf5d5027b1`。镜像标签 `2byteasr:0.8.1-docker.1`，本地交付位于主工作区 `releases/0.8.1-docker/`；已公开发布至 [v0.8.1-docker.1](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.8.1-docker.1)，构建与分片导入见使用说明。

实际检查：最终镜像重建后的正常 GUI 流程 38 项通过（SenseVoice 真识别、Qwen3 字级时间、视频画面和声音、编辑剪切、保存重开、四种字幕和 MP4）；首次引导 6 项通过，模型工坊 9 项通过；跨容器设置、工程和测试密钥恢复 4 项通过。定向测试合计 31 passed、1 skipped。云端上传/轮询用本机模拟服务验证，39 项通过，未使用真实 API Key 或产生付费调用。

字级时间轴保留 Qwen3、Whisper、Paraformer 和日语 CTC。CTC 已跑 CPU 推理冒烟，未判断日语准确率；Whisper、Paraformer、Fun-ASR Nano 的真实样本未逐一验证。FireRed / NVIDIA 专属模型、Apple MLX，以及 0.8.1 之后的 MFA 不在此 CPU 包内。

发布核验：源码和构建入口已合入 main（PR #7）；Release 五个附件的大小与 GitHub SHA-256 全部匹配，匿名下载检查通过。Windows / Linux 导入器均通过真实分片校验和损坏分片拒绝检查，原桌面版 v0.8.1 保持 Latest。仓库全量 CI 仍在已有测试收集问题处失败，原 main 40 项、本分支 39 项，没有新增失败；不将此写成全量通过。

说明入口：[启动与使用](../README.docker.md) · [打包架构](architecture/packaging.md) · [本轮计划](exec-plans/completed/2026-10-19-docker-081.md) · [公开发布计划](exec-plans/completed/2026-10-19-docker-github-release.md) · [近期变化](RECENT_CHANGES.md)。

文档检查边界：v0.8.1 发布快照自带 document_library.py，但缺少其必需的 document-library-overrides.json 等目录资料；原样运行 build/check 会失败。本轮目录检查在有完整资料的主工作区运行，不把这一历史缺项冒称通过。
