"""Real PySide6 screenshots and responsive checks for P22.11 Studio polish."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--scale", default="1")
parser.add_argument("--screenshots", action="store_true")
parser.add_argument("--quiet", action="store_true")
args = parser.parse_args()
os.environ["QT_SCALE_FACTOR"] = args.scale

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p22.11-acceptance"
SHOTS = ROOT / "screenshots" / "p22.11"
SOURCE = Path(
    Path.home() / "Desktop" / r"2ByteASR Projects\大饭包 开挖土机\大饭包 开挖土机.2byteproj"
)
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"local-scale-{args.scale.replace('.', '-')}")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + milliseconds / 1000
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        time.sleep(0.01)


def capture(page: SubtitleStudioPage, name: str, width: int, height: int) -> str:
    target = SHOTS / name
    pixmap = page.grab()
    if pixmap.width() != width or pixmap.height() != height:
        pixmap = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"could not capture {target}")
    return str(target)


def geometry_snapshot(page: SubtitleStudioPage, width: int, height: int, app: QApplication) -> dict:
    page.resize(width, height)
    pump(app, 120)
    upper = page.upper_splitter.sizes()
    workspace = page.workspace_splitter.sizes()
    return {
        "requested": [width, height],
        "actual": [page.width(), page.height()],
        "header_height": page.findChild(type(page.context_panel), "studioToolbar").height(),
        "upper_splitter": upper,
        "workspace_splitter": workspace,
        "cue_list_width": page.cue_list_panel.width(),
        "video_width": page.center_splitter.width(),
        "tool_panel_width": page.context_panel.width(),
        "timeline_height": page.timeline.height(),
        "style_horizontal_scroll": page.context_drawer.widget(2).horizontalScrollBar().maximum(),
        "guards": {
            "all_major_regions_visible": all(value > 0 for value in (*upper, *workspace)),
            "tool_panel_not_clipped": page.context_panel.width() >= page.context_panel.minimumWidth(),
            "style_no_horizontal_scroll": page.context_drawer.widget(2).horizontalScrollBar().maximum() == 0,
            "timeline_tracks_visible": page.timeline.height() >= 120,
            "waveform_height_52": page.timeline.WAVEFORM_TRACK_HEIGHT == 52,
        },
    }


def main() -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    copy_dir = OUTPUT / f"scale-{args.scale.replace('.', '-')}" / SOURCE.stem
    copy_dir.mkdir(parents=True, exist_ok=True)
    project_copy = copy_dir / SOURCE.name
    shutil.copy2(SOURCE, project_copy)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    page = SubtitleStudioPage()
    page.setWindowTitle(f"2ByteASR P22.11 Visual Acceptance {args.scale}x")
    page.resize(1920, 1080)
    page.show()
    pump(app, 120)
    opened = time.perf_counter()
    page.open_project(project_copy)
    studio_open_ms = (time.perf_counter() - opened) * 1000
    pump(app, 1200)
    page.select_cue(page.project.cues[0].id)
    page._show_context_panel()
    page._refresh_checks()

    report = {
        "scale": args.scale,
        "source_project": str(SOURCE),
        "working_copy": str(project_copy),
        "cue_count": len(page.project.cues),
        "studio_open_ms": round(studio_open_ms, 3),
        "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
        "available_screen": [
            app.primaryScreen().availableGeometry().width(),
            app.primaryScreen().availableGeometry().height(),
        ],
        "layouts": {},
        "screenshots": {},
    }

    for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
        report["layouts"][f"{width}x{height}"] = geometry_snapshot(
            page, width, height, app
        )

    if args.screenshots:
        page.resize(1920, 1080)
        page.context_drawer.setCurrentIndex(0)
        page.ai_empty_state.hide()
        page.ai_suggestion_title.setText("发现 1 项建议")
        page.ai_preview.setPlainText(
            "原文：\n那维来特的技能已经准备好了。\n\n"
            "建议：\n那维莱特的技能已经准备好了。\n\n"
            "依据：项目词库中的角色名与上下文一致。"
        )
        page.ai_confidence.setText("术语建议 · 请核对后采用")
        pump(app, 120)
        report["screenshots"]["ai_1920x1080"] = capture(
            page, "studio-ai-1920x1080.png", 1920, 1080
        )

        page.context_drawer.setCurrentIndex(2)
        pump(app, 120)
        report["screenshots"]["style_1920x1080"] = capture(
            page, "studio-style-1920x1080.png", 1920, 1080
        )

        page.context_drawer.setCurrentIndex(1)
        pump(app, 120)
        report["screenshots"]["check_1920x1080"] = capture(
            page, "studio-check-1920x1080.png", 1920, 1080
        )

        page.resize(2560, 1440)
        page.context_drawer.setCurrentIndex(2)
        pump(app, 160)
        report["screenshots"]["studio_2560x1440"] = capture(
            page, "studio-max-2560x1440.png", 2560, 1440
        )

    page.close_page()
    page.close()
    pump(app, 80)
    target = OUTPUT / f"visual-scale-{args.scale.replace('.', '-')}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
