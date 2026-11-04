# GitHub README 展示素材复现

2026-10-14 起，`main` 分支 README 的主图、截图和两段操作动图（剃刀、候选对照）都来自真实桌面窗口，由这里的脚本在隔离环境里截取；直播切片动图仍是 2026-10-09 的 HyperFrames 示意动画（`animations/`）。下次界面变化后按同样步骤更新即可。

## 边界

- 截图应对应**公开版本**：先在仓库外或 `tmp/` 下用 `git worktree add --detach <目录> v<版本>` 检出发布 tag，再在那个目录里运行脚本；`models`、`tools` 用目录联接指向开发仓库已有的文件夹。
- 工作目录默认 `<检出目录>/tmp/readme-showcase`，可用环境变量 `README_SHOWCASE_DIR` 指定。
- 用户数据、缓存、报告、工程、QSettings 全部写到工作目录里的 profile；只**读取**已登记的本地运行环境（`%LOCALAPPDATA%\2ByteASR\runtimes\registry.json` 的 main / moss / firered_llm 条目，复制一份到 profile）和 `models/`。不复制 `secrets.dat`、不带 API Key，阻止对外网络连接。
- 正常 `MainWindow` 跑在私有 Windows 桌面上，不打扰当前屏幕；截图用窗口原生捕获。设 `TWOBYTEASR_ONBOARDING=1` 时首页显示新手步骤卡（与新安装用户看到的一致），但不弹出首次选择窗口。
- 示例素材是测试卡画面 + Windows OneCore 中文语音（Kangkang／Yaoyao），不使用游戏实录、直播或私人媒体。

## 步骤

```powershell
$env:README_SHOWCASE_DIR = "$PWD\tmp\readme-showcase"
$env:TWOBYTEASR_ONBOARDING = "1"
# 1. 示例素材：两种合成语音 + 测试卡画面（需要 ffmpeg 在 PATH；加参数 forest 可生成 2026-10-09 的小游戏画面）
powershell -ExecutionPolicy Bypass -File scripts\readme_showcase\tts.ps1 -Dialogue scripts\readme_showcase\dialogue.json -OutDir "$env:README_SHOWCASE_DIR\media\tts"
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_demo_media.py testcard
# 2. 真实识别（点“开始生成字幕”，拍首页、进度页与完成页，记录全部事件）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_run.py --name run-071 --size 1320x880 --scale 2 --media-name 双人实况示例.mp4
# 3. 在 run-071 工程副本上操作字幕工作台
#    zh-01：剃刀、候选对照录制，术语库、模型工坊、五套主题（1320×880）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name zh-01 --source run-071 --size 1320x880 --scale 2 --scenes speakers,razor,review,fixups,hero,home,pages,export,themes
#    zh-02：主图与导出完成页（1440×900，标题栏按钮不重叠）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name zh-02 --source run-071 --size 1440x900 --scale 2 --scenes speakers,review,fixups,hero,export
#    en-02 / ja-02：英日界面（标签较长，用 1600×1000）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name en-02 --source run-071 --lang en --size 1600x1000 --scale 2 --scenes speakers,razor,review,fixups,hero,home,pages
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name ja-02 --source run-071 --lang ja --size 1600x1000 --scale 2 --scenes speakers,razor,review,fixups,hero,home,pages
#    ko-02：韩语界面（2026-10-15 起，需 0.7.2 及以后的源码；run-071 复制过来时要把 result.json 里的工程路径改成新位置）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name ko-02 --source run-071 --lang ko --size 1600x1000 --scale 2 --scenes speakers,razor,review,fixups,hero,home,pages
# 4. 生成 README 图片（输出到 $env:README_SHOWCASE_DIR\assets）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_assets.py
# 5. 复制到 main 的工作树，重写清单，并用 GitHub 渲染接口检查链接、图片与锚点（需要 gh 登录）
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_manifest.py <main 工作树> <日期>
<开发仓库>\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\check_links.py <main 工作树> README.md README_EN.md README_JA.md docs/product-guide.zh-CN.md docs/product-guide.en.md docs/product-guide.ja.md docs/product-demo.zh-CN.md docs/product-demo.en.md docs/product-demo.ja.md
```

`build_assets.py` 按上面的运行名读取截图（`run-071`、`zh-01`、`zh-02`、`en-02`、`ja-02`）；裁切框写在脚本顶部和各调用处，界面布局变化后要重新核对。`build_banner2.py` 是 2026-10-09 版页首图的脚本，现在的 README 不再使用。

“导出”场景按中文按钮文字“开始导出”找按钮，只在中文界面运行。审核场景点选候选后会自动跳到下一条，录制间隔不同时可能只录到跳转后的画面，必要时单独重录这一场景（`--scenes review`）。

## 直播切片示意动画

`animations/index.html` 是 2026-10-09 的 45 秒、五个场景的 HyperFrames 合成（1600×800，GSAP 单一时间轴）。现在 README 只保留其中的直播切片一段（`clips*.webp`，35–45 s），并在界面一览里标明是示意动画。重新渲染的方法：

```powershell
New-Item -ItemType Directory -Force tmp\readme-anim\assets\fonts | Out-Null
Copy-Item scripts\readme_showcase\animations\* tmp\readme-anim\
Copy-Item assets\fonts\SourceHanSansSC-Heavy.otf, assets\fonts\SourceHanSansSC-Medium.otf tmp\readme-anim\assets\fonts\
cd tmp\readme-anim
npx hyperframes@0.8.143 check .
npx hyperframes@0.8.143 render . -q high -o renders\video.mp4
ffmpeg -ss 35 -t 10 -i renders\video.mp4 -vf "fps=25,scale=1100:-1:flags=lanczos" -c:v libwebp_anim -q:v 82 -compression_level 6 -loop 0 clips.webp
```

英文、日文、韩文版用 `build_anim_variant.py <目录> en|ja|ko <输出目录>` 生成后同样渲染、切片（韩文版 2026-10-15 加入）。

## 取景时避开的已知问题（2026-10-14）

英文界面标题栏按钮重叠、英日界面残留中文、采用候选后预览字幕暂时消失等，记在 `docs/assets/readme/README.md` 的“录制时看到、尚未修复的界面问题”一节。
