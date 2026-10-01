# macOS 原生开发构建

此页与[普通用户实验版说明](macos-experimental.zh-CN.md)分开。在 macOS 15 Apple Silicon arm64 使用完整可信源码，构建 Python 3.10.11；不是 Windows 交叉构建，不复制宿主 node_modules/EXE/DLL/wheel。

固定输入见 `packaging/macos/native-dependencies.lock.json`、GUI/CPU requirements 和 `bootstrap.lock.json`。关键 wheel 对实际 pip install report 校验版本/SHA；FFmpeg 9.0.2、mpv 0.41.0/revision 10、Node 22.16.0 及 Remotion lock 绑定准确原生输入，漂移即失败。实际 Qt、PyAV、模型运行库和 Chromium 的架构/动态库关系在回执中记录。

```bash
QA_ROOT="$PWD/tmp/macos-native-0.5.0"
python3.10 scripts/macos_prepare_runtime.py \
  --runtime "$QA_ROOT/runtime" --receipt "$QA_ROOT/runtime.json"
brew install ffmpeg mpv
"$QA_ROOT/runtime/bin/python" scripts/macos_doctor.py \
  --require-host --probe-torch --output "$QA_ROOT/doctor.json"
"$QA_ROOT/runtime/bin/python" scripts/macos_build.py \
  --source-sha "$(git rev-parse HEAD)" --runtime "$QA_ROOT/runtime" \
  --output "$QA_ROOT/build"
```

CI 要求干净40位源码 SHA；`--allow-dirty` 仅显式本地实验并保留固定输入。每次使用新输出目录，不覆盖旧包。PyInstaller 只生成 arm64 `.app`，记录 source identity、build_id、原文件、实际 Python/原生工具清单。

真实 `.app` 先归档，再从 ZIP 解压到另一中文/日文路径，核对内容、权限、符号链接、Mach-O、外部链接及 ad hoc 签名，并通过 LaunchServices 以最小 PATH 启动。后续模型/桌面失败不丢弃已生成的真实包，没有 `.app` 时不生成占位 ZIP/DMG。

`macos_desktop_smoke.py` 从普通 GUI 工坊准备单一 SenseVoice，再由首页真实 Start 识别中文，进入 Studio 编辑/剪切/撤销重做/保存重开/四格式及短视频验收。它需要有权使用的短中文输入，不注入识别结果。内部 CI 样本只进入专用私有构建分支，不自动纳入有限公开源码 C。

手动工作流只有 `workflow_dispatch`：一个标准 `macos-15` arm64 job、60分钟、完整 Action revision、`contents: read`、不留 Git 凭据，无生产 Secrets、云端LLM、Release 或缓存发布。只选安装 ZIP 和浅层回执上传，不上传模型/runtime/用户缓存；上限4GiB、保留1天。运行前实际核对现有免费额度和零付费预算，不调整预算、不购买 runner。新增提交、分支与运行登记在私有 HANDOFF，不能扩大公开范围。

MPS 可用性、小 tensor、具体模型、VideoToolbox实际硬件编码和预览后端分别记录。`macos_hardware_probe.py` 真正尝试25帧编码且禁用软件 fallback；失败表明当次 runner 未通过硬件检查，CPU与模型正确性另验。

Mac 材料按真实载荷增量记录。Windows 材料不自动证明 Mac 完整对应源码，内部构建不自动放行公开发行。官方参考：[PyInstaller macOS架构/签名](https://pyinstaller.org/en/stable/feature-notes.html)、[PyTorch MPS](https://docs.pytorch.org/docs/stable/notes/mps.html)、[Actions额度与存储](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。
