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
Docker 镜像已实测且在本机运行。镜像代码提交 76e9bdb7，公开源码标签 v0.8.1-docker.1 指向 a2a7e2b4。分支与标签已推送，PR #7 已创建，Release 草稿正在上传五个附件；尚未公开发布。远端 main 在原 0.8.1 之后只有公开 README/发行说明更新，当前登录账号有 ADMIN 权限。

## Tasks
- [x] 核对远端、权限、版本和 GitHub 附件限制。
- [x] 合并远端已公开文档，补源码构建与分片加载说明。
- [ ] 分片与源码归档检查，上传草稿并核对远端资产。
- [ ] 发布 Release 与主分支入口，匿名检查后归档计划。

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
