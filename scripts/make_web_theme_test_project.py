# -*- coding: utf-8 -*-
"""构建 web 主题 headed 验证用的合成工程（可重复、无用户数据依赖）。

产物：tmp/webtest/ 目录 ——
  testsrc.mp4        60s 合成视频（testsrc2 + 正弦音）
  webtest.2byteproj  干净工程：0-60s 每 3s 一条 cue、普通/web 交替、
                     末尾一对重叠 cue（模拟多说话人轨道重叠）

用法：.venv-main/Scripts/python.exe scripts/make_web_theme_test_project.py
（视频已存在时跳过生成；工程总是重建——headed 脚本会往里 autosave 污染。）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "webtest"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    video = OUT / "testsrc.mp4"
    if not video.is_file():
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(video),
        ]
        print("[webtest] generating testsrc.mp4 ...", flush=True)
        subprocess.run(cmd, check=True)
    print(f"[webtest] video: {video} ({video.stat().st_size // 1024} KB)", flush=True)

    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import (
        StudioCue, StudioMedia, StudioSpeaker, SubtitleStyle, SubtitleProject, save_project,
    )
    from twobyteasr.web_theme import builtin_web_themes
    from twobyteasr.style_recipe import StyleRecipe

    project = SubtitleProject(media=StudioMedia(path=str(video)))
    project.speakers.append(StudioSpeaker(id="S01", name="水墨"))
    project.speakers.append(StudioSpeaker(id="S02", name="北极熊"))

    theme = builtin_web_themes()["balatro-joker"].to_dict()
    web_recipe = StyleRecipe(
        name="WebTest", engine="remotion",
        typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 58, "bold": True},
        colors={"fill": "#FFE9B8", "outline": "#10181E"},
        web_theme=theme,
    )
    # 独立 web 样式（不要复用 default——那会把全部 cue 一起变成 web）。
    web_style = SubtitleStyle(
        id="webtest-web", name="WebTest 特效",
        font_family="Microsoft YaHei UI", font_size=56.0,
    )
    project.styles.append(web_style)
    project.style_recipes[web_style.id] = web_recipe.to_dict()

    texts = [
        "第一条普通字幕开场", "第二条套上小丑牌", "第三条普通文字测试",
        "第四条特效再次登场", "第五条普通收尾准备", "第六条特效压轴出场",
        "第七条普通字幕二号", "第八条特效二号说话", "第九条普通字幕重叠",
        "第十条特效重叠区段", "第十一条普通字幕", "第十二条特效最终",
        "第十三条普通字幕", "第十四条特效结束", "第十五条普通片尾",
        "第十六条普通收尾", "第十七条普通尾声", "第十八条普通最后",
    ]
    for index, text in enumerate(texts):
        start = 1200 + index * 3000
        cue = StudioCue(
            id=f"wt{index}",
            start_ms=start,
            end_ms=start + 2600,
            text=text,
            speaker_id="S01" if index % 2 == 0 else "S02",
        )
        if index % 2 == 1:
            cue.style_id = web_style.id
        project.cues.append(cue)

    # 重叠对：一条 web + 一条普通同窗（多说话人轨道重叠形态）
    project.cues.append(StudioCue(
        id="wt-overlap-web", start_ms=45_000, end_ms=48_000,
        text="重叠区特效字幕", speaker_id="S01", style_id=web_style.id,
    ))
    project.cues.append(StudioCue(
        id="wt-overlap-plain", start_ms=46_000, end_ms=49_000,
        text="重叠区普通字幕", speaker_id="S02",
    ))

    target = OUT / "webtest.2byteproj"
    save_project(project, target)
    print(f"[webtest] project: {target} cues={len(project.cues)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
