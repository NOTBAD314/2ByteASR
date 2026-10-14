# GitHub README 展示素材复现

2026-10-09 起，`main` 分支 README 的功能演示是 `animations/` 里的 HyperFrames HTML 动画，截图部分由这里的脚本从真实桌面窗口截取。下次界面变化后按同样步骤更新即可。

## 边界

- 工作目录默认 `tmp/readme-showcase`，可用环境变量 `README_SHOWCASE_DIR` 指定（必须在仓库 `tmp/` 下）。
- 用户数据、缓存、报告、工程、QSettings 全部写到工作目录里的 profile；只**读取**已登记的本地运行环境（`%LOCALAPPDATA%\2ByteASR\runtimes\registry.json` 的 main / moss / firered_llm 条目，复制一份到 profile）和仓库 `models/`。不复制 `secrets.dat`、不带 API Key，阻止对外网络连接。
- 正常 `MainWindow` 跑在私有 Windows 桌面上，不打扰当前屏幕；截图用窗口原生捕获。
- 示例素材是自制画面 + Windows OneCore 中文语音（Kangkang／Yaoyao），不使用游戏实录、直播或私人媒体。

## 步骤

```powershell
$env:README_SHOWCASE_DIR = "$PWD\tmp\readme-showcase"
# 1. 示例素材：两种合成语音 + 自绘画面（需要 ffmpeg 在 PATH）
powershell -ExecutionPolicy Bypass -File scripts\readme_showcase\tts.ps1 -Dialogue scripts\readme_showcase\dialogue.json -OutDir "$env:README_SHOWCASE_DIR\media\tts"
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_demo_media.py
# 2. 真实识别（点“开始生成字幕”，拍进度页与完成页，记录全部事件）
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_run.py --name run-01
# 3. 在 run-01 工程副本上操作字幕工作台（中文 1320×880@2x；英日 1600×1000@1.5x）
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name final-02 --size 1320x880 --scale 2 --scenes speakers,razor,review,fixups,style2,playback,hero,export,home,themes,pages
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name final-04 --size 1320x880 --scale 2 --scenes speakers,razor,review,fixups,style-size,hero
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name wide-en2 --lang en --size 1600x1000 --scale 1.5 --scenes speakers,razor,review,fixups,style2,hero,home,pages
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\showcase_studio.py --name wide-ja2 --lang ja --size 1600x1000 --scale 1.5 --scenes speakers,razor,review,fixups,style2,hero,home,pages
# 4. 生成 README 图片与页首
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_assets.py
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_banner2.py
# 5. 在 main 的工作树里检查链接、图片与锚点（使用 GitHub 渲染接口，需要 gh 登录）
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\check_links.py <main 工作树> README.md README_EN.md README_JA.md
```

`build_assets.py` 与 `build_banner2.py` 按上面的运行名读取截图（`run-01`、`final-02`、`final-04`、`wide-en2`、`wide-ja2`）。换了运行名就改脚本顶部对应的路径。

## 功能动画（README 前五段）

`animations/index.html` 是一个 45 秒、五个场景的 HyperFrames 合成（1600×800，GSAP 单一时间轴，可逐帧定位）。字体用仓库 `assets/fonts` 的思源黑体，先复制到工程里：

```powershell
New-Item -ItemType Directory -Force tmp\readme-anim\assets\fonts | Out-Null
Copy-Item scripts\readme_showcase\animations\* tmp\readme-anim\
Copy-Item assets\fonts\SourceHanSansSC-Heavy.otf, assets\fonts\SourceHanSansSC-Medium.otf tmp\readme-anim\assets\fonts\
cd tmp\readme-anim
npx hyperframes@0.8.143 check .
npx hyperframes@0.8.143 render . -q high -o renders\video.mp4
```

再按场景切成 WebP 动图（25 fps、宽 1100）：roles 0–10 s、razor 10–19 s、review 19–27 s、terms 27–35 s、clips 35–45 s，例如

```powershell
ffmpeg -ss 10 -t 9 -i renders\video.mp4 -vf "fps=25,scale=1100:-1:flags=lanczos" -c:v libwebp_anim -q:v 82 -compression_level 6 -loop 0 razor.webp
```

### 英文、日文版

同一个 `index.html` 带三套文字，由 `<html lang>` 选择：中文是页面里写好的内容，英日两套在脚本的 `I18N` 表里，界面用语按软件英日界面（Undo、Add to edit、元に戻す、クリップへ追加等），示例字幕也译成对应语言（英文按词标时间和切分，日文按字）。直播弹幕保持中文原文，因为弹幕分析目前按中文弹幕调校。日文界面文字用 Windows 自带的游ゴシック（`local("Yu Gothic Medium")`／`Bold`，日文字形），中文内容仍用思源黑体。

```powershell
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_anim_variant.py tmp\readme-anim en tmp\readme-anim-en
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_anim_variant.py tmp\readme-anim ja tmp\readme-anim-ja
```

分别在两个目录里 `check`、`render`，再按同样的时间切片，文件名加 `-en`／`-ja`（`roles-en.webp` 等）。

换好 `main` 工作树里的图片后，用下面的命令重写 `docs/assets/readme/manifest.json`：

```powershell
.\.venv-main\Scripts\python.exe -X utf8 scripts\readme_showcase\build_manifest.py <main 工作树> 2026-10-09
```

## 取景时避开的已知问题

时间轴放大后视频轨压住字幕轨、剃刀预览卡与选中字幕重叠、样式预览播放一次动效后变空白——都记在 [已知问题](../../docs/KNOWN_ISSUES.md) 2026-10-09 一节。所以剃刀场景把时间轴分栏拉到 56%，主图在应用动效之前拍。
