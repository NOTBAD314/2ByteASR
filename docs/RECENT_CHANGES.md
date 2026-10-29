# 公开仓库近期变化

## 2026-10-29：项目首页改版并公开发布

首页从面向游戏实况的介绍改为字幕剪辑翻译工作台，默认英文，另有中文、日文、韩文。主图和功能展示换为公开 0.8.7 的真实窗口与操作动图，并保留样例授权、人工补译和录制帧率的说明。160 处本地引用与 44 处锚点检查通过；GitHub main 的四份文档与 29 个图片资源核对一致。应用、安装包和仓库简介未改。[本轮计划](exec-plans/completed/2026-10-29-readme-workbench-redesign.md)。

## 2026-10-19：Docker 源码和镜像公开发布

源码、Dockerfile / Compose 与四语言首页入口已合入主分支，[Docker Release](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.8.1-docker.1) 提供启动包、两个镜像分片、对应源码与 SHA-256 清单。可以从固定标签自行构建，也可下载后校验导入；原桌面版 v0.8.1 仍是 Latest。五个附件的远端摘要和匿名下载均已核对，详细过程见 [发布计划](exec-plans/completed/2026-10-19-docker-github-release.md)。全量 CI 的既有缺失依赖与文件问题仍在，Docker 本轮定向及运行验收另列。

## 2026-10-19：浏览器桌面与云端默认组合

以前仅有桌面分发，Linux 的模型准备和密钥存储缺少可运行入口。现在用 Selkies 提供原 Qt 界面、视频和声音，Compose 启动后可在本机 3000 端口操作。应用配置、模型与输入输出各自持久化，重建容器不会清掉已保存的内容。

用户要求接入字级时间戳模型并推荐云端：新配置默认 MOSS Pro API + Qwen3 对齐；已有配置不改写。工坊能下载 CPU 支持的 Qwen3、日语 CTC、Whisper、Paraformer、SenseVoice、Fun-ASR Nano，未适配的 GPU 模型隐藏。

最终镜像实际完成 38 项识别到导出的 GUI 检查、6 项首次引导、9 项工坊检查和 4 项持久化检查；本机模拟云端流程 39 项通过。CTC 仅推理冒烟，其余未验模型与硬件详见 [计划](exec-plans/completed/2026-10-19-docker-081.md)。未调用真实付费 API；本机交付阶段尚未上传，后续公开发布见上条。
