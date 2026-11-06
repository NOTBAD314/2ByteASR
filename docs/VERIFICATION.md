# 本轮反馈修复的针对性验证

2026-11-06。所有测试使用独立TWOBYTEASR_TEST_ROOT；Qt语义检查为offscreen，真实窗口为正常MainWindow和私有Windows桌面。真实窗口的输入是Qt事件与原生WM重复消息，不等于实体键盘/输入法验收。

```powershell
python scripts/run_isolated_tests.py tests/test_issue_environment_delivery.py tests/test_issue_placeholder_sources.py tests/test_issue_frame_step.py -q
python scripts/verify_issue_frame_step_headed.py --output tmp/frame25 --fps 25
python scripts/verify_issue_frame_step_headed.py --output tmp/frame-ntsc --fps 30000/1001
python scripts/verify_issue_frame_step_headed.py --output tmp/frame-trim --fps 25 --trim-head
python scripts/verify_issue_frame_step_headed.py --output tmp/frame-cut --fps 25 --cut-middle
python scripts/verify_issue_frame_step_headed.py --output tmp/frame-cut-ntsc --fps 30000/1001 --cut-middle
```

输出必须为新的tmp目录。需准备项目的FFmpeg/FFprobe和mpv工具；本机隔离源码只读复用原工具目录，不能用媒体探测失败的salvage预览替代完整媒体图。

Pillow安装不能由开发机已有包证明：本轮完整setup在全新venv执行，实际repair另建staging，分别运行依赖一致性、布局、保存重开及导出检查。真实Qwen使用仓库诊断音频与已注册CUDA运行时，以源模式只读显式选择验证，不代表模型下载/安装已重新验收。

CI和扩大回归均单列：旧CI轻量清单缺依赖导致收集失败；26条既有回归在未改7c44b93d复现，不作为通过。其它平台、打包、外部云API和长时间场景的未验原因见[计划](exec-plans/completed/2026-11-06-github-issues-11-15.md)。
