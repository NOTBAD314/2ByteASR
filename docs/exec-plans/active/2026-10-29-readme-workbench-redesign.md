# 2026-10-29 GitHub README 改版：字幕剪辑翻译工作台

## Goal

GitHub 首页（四种语言 README、仓库简介）换成新定位「字幕剪辑翻译工作台」，图片全部换成 0.8.7 的真实应用内截图。用户 10-29 选定：草稿 A（一屏看懂）为底，加上草稿 C 的「你要做的是…」四格表；主图不要编号标注；不要自己画的演示图。

## Non-goals

- 不改程序代码、不发新版、不动 Release 附件。
- 不改使用指南、界面一览的正文（只修因图片删除而失效的链接）。
- 不动开发分支 `feature/subtitle-studio` 的工作区。

## Acceptance criteria

1. `README.md`、`README_EN.md`、`README_JA.md`、`README_KO.md` 开头是「字幕剪辑翻译工作台」（及对应译文），不再写“为游戏实况……而做”。
2. 结构：页首 → 主图（真实工作台截图，无标注）→ 五步表 → 下载 → 你要做的是…（四格表）→ 能做什么（六格，每格一张真实截图）→ 选择识别方式 → 进阶与文档 → 支持作者 → 反馈与许可。
3. 所有新图来自 tag `v0.8.7` 源码的真实窗口（隔离桌面、项目自制素材、真实识别），只做裁切缩放；四种语言各一套。
4. `docs/assets/readme/README.md` 与 `manifest.json` 更新；不再引用的旧图删除。
5. GitHub 渲染接口检查链接、图片、锚点通过。
6. 推送 `main` 和改仓库简介 / Topics 前给用户看 diff 并得到确认。

## Current state

- 10-29：三版草稿已发给用户（artifact），用户选 A + C 表格。
- 工作树：`tmp/readme-087/source`（detached `v0.8.7`，截图用），`tmp/readme-087/main`（分支 `claude/readme-workbench-20261029`，底 `origin/main` `04a2fa70`）。

## Tasks

- [x] 生成示例素材（合成语音 + 自绘小游戏画面 `forest`）
- [x] 真实识别一次，得到工程（`run-087`，176.8 秒，14 条字幕、两位说话人）
- [x] 适配 `showcase_studio.py` 到 0.8.7 界面：说话人卡片改名、手动补译、双语显示、链接下载窗口、控件位置记录
- [x] 四种语言各截一套（`zh-05` 1440×900，`en/ja/ko-05` 1600×1000），`build_assets_087.py` 裁切
- [x] 改四种语言 README、素材说明、脚本说明；界面一览里指向旧 README 小节的链接改指使用指南
- [ ] 清单、链接检查、提交
- [ ] 用户确认后推送并改简介

## Findings

- 0.8.x 只认应用运行环境目录里的解释器，旧截图脚本的隔离 profile 找不到运行环境（“main 解释器缺失”）。源码运行可设 `TWOBYTEASR_DEVELOPER_RUNTIMES=1`，配合 `TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY=1` 只读使用。
- 手动补译的目标语言必须等于工程译文容器的语言（默认简体中文），否则 `set_manual` 拒绝；脚本改用时间轴自己的 `subtitle_target_language`，与双击输入一致。
- 界面问题（未修，已记入 `docs/assets/readme/README.md`）：时间轴较高时译文轨字幕块被视频轨挡住下半截；1440×900 下“动效”页两行文字重叠；英日韩界面残留中文；链接下载窗口无韩语。

## Decisions

- 截图对应公开版本 0.8.7（`scripts/readme_showcase/README.md` 的既有约定）。
- 双语截图的译文用应用里的手动补译（`cue_controller.set_translation`，与双击输入同一路径）写入，不接 AI、不带 API Key。
- 五步说明和场景表用 Markdown 表格，不做图片，四种语言都能直接改字。
- 示例画面改用自绘小游戏画面（用户嫌旧测试卡难看）。
- 六张功能图统一 16:10：从同一窗口按控件位置裁出，不加底板、不重绘。
- 旧 `hero*.png` 删除；“界面一览”仍引用的 0.7.1 素材保留，不在本次重拍范围。

## Blockers

## Progress

- 10-29：建计划与工作树；草稿 A + C 表格定稿；四种语言真实截图完成。
