# 0.8.1 Docker 公开发布

日期：2026-10-19。用户明确要求发布到 NOTBAD314/2ByteASR，方便他人构建与使用。

## Goal
将已验 Docker 版源码、构建入口、部署说明和镜像公开发布到原仓库；其他人可从固定标签构建，也可下载镜像导入使用。

## Non-goals
不改变 0.8.1 的识别和工程契约；不添加 GPU 支持，不上传模型/凭据/用户素材，不覆盖 Windows/macOS 的现有 Release。

## Acceptance criteria
- 原仓库可以看到 Dockerfile、Compose、完整源码和显著使用入口。
- 发布独立 v0.8.1-docker.1，现有 v0.8.1 保持桌面版 Latest。
- 镜像分片、部署包、对应源码及校验清单上传完整；匿名访问和远端摘要核对通过。
- 分片重组与原镜像 SHA-256 一致，源码与镜像 821 项源码清单一致。
- 更新状态与文档目录，分块提交并记录真实发布链接。

## Current state

已完成公开发布。PR #7 已合入 main（d892ffe8），固定标签 v0.8.1-docker.1 指向 a2a7e2b4，镜像运行代码为 76e9bdb7。[v0.8.1-docker.1](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.8.1-docker.1) 包含五个完整附件，大小与远端 SHA-256 匹配，匿名访问通过；原桌面版 v0.8.1 保持 Latest。

## Tasks
- [x] 核对远端、权限、版本和 GitHub 附件限制。
- [x] 合并远端已公开文档，补源码构建与分片加载说明。
- [x] 分片与源码归档检查，上传草稿并核对远端资产。
- [x] 发布 Release 与主分支入口，匿名检查后归档计划。

## Verification strategy
沿用已验镜像，二进制字节不修改。GitHub 每附件小于 2 GiB；分为 1.5 GB 与余量，逐片与重组摘要验证。仅源码/部署辅助文件和匿名化验收结论进入仓库，公开下载从固定标签定位。

## Findings
GitHub 官方说明每个 Release 附件须小于 2 GiB：https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases 。现有归档 2,663,312,896 字节且层已经 gzip 压缩。已验对应源码 821 项零差异。

## Decisions
独立 Docker Release，latest=false；main 保留既有桌面下载入口并新增 Docker。优先发布现有验证过的镜像字节，不为分发而修改运行依赖。

## Blockers
无。

## Progress
- 开始发布准备，未向远端写入。

- 镜像分成 1,500,000,000 与 1,163,312,896 字节两段；Windows PowerShell 与 Linux sh 导入器都已实际校验成功，重组摘要与原镜像一致。公开主分支最新 1ecf1ea7 的既有 Windows CI 已失败，发布记录不把其当作本轮通过证据；补充新增凭据测试需要的 cryptography 依赖。

- 已推送 codex/docker-0.8.1 和 v0.8.1-docker.1，创建 [PR #7](https://github.com/NOTBAD314/2ByteASR/pull/7) 与独立 Release 草稿。上传仅五个预定附件。最终源码 ZIP 对应 a2a7e2b4，与镜像 821 项源码摘要一致。原 main 的 CI 日志确认在测试收集阶段缺少 PIL、jsonschema 及原有文件；不把修复这批历史问题混进本次发布。

- GitHub 分支 CI 已结束：原 main 收集错误 40 项，本分支 39 项，新增失败名单为空（补 cryptography 后原 test_r5_tls 收集错误消失）。仍未进入全量用例执行；本轮实测以 Docker 定向测试和运行时证据为准。源码包、启动包及 SHA256SUMS 已上传，GitHub 返回摘要与本地一致；两个大镜像分片仍在上传。

- Windows 与 Linux 两个导入器用独立损坏分片做反向检查，均以非零状态拒绝，未创建合并归档，也未调用 Docker 导入。

- 主分支发布：PR #7 于 2026-10-19 合并（d892ffe8），匿名读取 main 的 Dockerfile、Compose、README.docker.md 与本地一致。首次大文件并发上传报 EOF，未留下同名远端附件；保留三个成功附件，改为单分片顺序上传。

- 首个镜像分片已由 GitHub 标记 uploaded，1,500,000,000 字节且摘要 f98df15a…02bd71f 与本地一致。CLI 在服务器已接受后重试，最终报同名 422；通过远端大小与摘要确认成功，没有使用 clobber 重传。第二分片改为独立上传。

- 公开验收：五个 Release 附件均为 uploaded，大小和 SHA-256 与本地一致。匿名完整下载启动 ZIP 与校验清单并核对摘要；两个镜像分片和源码 ZIP 用匿名范围请求核对开头字节，整文件摘要以 GitHub 返回值核对。匿名读取 tag 与 main 的 Dockerfile / Compose / README.docker.md 六项均一致。公开时间 2026-10-19T11:13:42Z；桌面 Latest 仍为 v0.8.1。

## Acceptance review

- 主分支：首页入口、Dockerfile、Compose 与源码已公开；PR #7 已合并。
- 独立 Release：v0.8.1-docker.1 已公开，桌面 Latest 保留。
- 五个附件：远端摘要、大小和匿名下载核对通过。
- 字节一致：Windows / Linux 重组完整归档 SHA-256 为 1c2dcb24f5d74f6dd7cd6d469c78209165b10bb754f13895c58abd81256561c5；源码 821 项零差异。
- 文档：已更新状态、近期变化与打包架构；目录检查在包含完整资料的共享主工作区执行。

- 文档检查：完整共享主工作区 document_library build/check 通过，1,349 份文档，errors=[]；公开旧快照缺目录配置的历史边界保留。共享工作区的其他任务代码不提交。
