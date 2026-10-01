"""Retained P21.1 geometry, timeline, and Render dialog acceptance."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "screenshots" / "p21.1-stabilization"
LOCAL_DATA = ROOT / "tmp" / "p21.1-localappdata"
sys.path.insert(0, str(ROOT))


def _probe_header() -> int:
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    import moss_firered_pipeline
    import subtitle_core
    from twobyteasr.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    cjk_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow([], subtitle_core, moss_firered_pipeline, None)
    results = []
    for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
        window.resize(width, height)
        window.show()
        app.processEvents()
        results.append(
            {
                "window": [width, height],
                "header_logical_height": window.app_header.height(),
                "mascot_logical_size": [window.header_mascot.width(), window.header_mascot.height()],
                "mascot_pixmap_logical_size": [
                    window.header_mascot.pixmap().deviceIndependentSize().width(),
                    window.header_mascot.pixmap().deviceIndependentSize().height(),
                ],
                "device_pixel_ratio": window.header_mascot.pixmap().devicePixelRatio(),
            }
        )
    print(json.dumps(results))
    window.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-header", action="store_true")
    args = parser.parse_args()
    if args.probe_header:
        return _probe_header()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(LOCAL_DATA)

    header_dpi = {}
    for scale in ("1", "1.25", "1.5", "2"):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale)
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--probe-header"],
            cwd=str(ROOT), env=env, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", shell=False,
        )
        header_dpi[scale] = json.loads(completed.stdout.strip().splitlines()[-1])

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    import moss_firered_pipeline
    import subtitle_core
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from twobyteasr.studio_render import scan_encoder_capabilities
    from twobyteasr.studio_render_ui import StudioRenderDialog
    from twobyteasr.studio_ui import MpvCanvas, SubtitleStudioPage
    from twobyteasr.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    cjk_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    project = SubtitleProject(
        media=StudioMedia(str(ROOT / "tmp" / "p21-studio-e2e" / "p21-source.mp4"), "P21.1", 120_000),
        cues=[
            StudioCue("a", 1000, 4800, "播放头会连续移动"),
            StudioCue("b", 12_000, 18_000, "底部滚动条可拖动"),
            StudioCue("c", 36_000, 42_000, "手动滚动不会改变播放时间"),
        ],
    )
    page = SubtitleStudioPage()
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.resize(1440, 900)
    page.show()
    project_path = ROOT / "tmp" / "p21.1-acceptance.2byteproj"
    save_project(project, project_path)
    page.open_project(project_path)
    page.timeline.set_visible_window(8_000, 20_000)
    app.processEvents()
    timeline_shot = OUTPUT / "timeline-horizontal-scrollbar.png"
    if not page.grab().save(str(timeline_shot)):
        raise RuntimeError("could not capture timeline screenshot")

    ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    capabilities = scan_encoder_capabilities(ffmpeg)
    ass = ROOT / "tmp" / "p21-studio-e2e" / "2ByteASR Projects" / "p21-source" / "preview" / "p21-preview.ass"
    render = StudioRenderDialog(project, str(ass), 12.0)
    render.resize(720, 900)
    render.show()
    app.processEvents()
    render_shot = OUTPUT / "render-dialog.png"
    if not render.grab().save(str(render_shot)):
        raise RuntimeError("could not capture Render dialog screenshot")

    shell = MainWindow([], subtitle_core, moss_firered_pipeline, None)
    shell.resize(1440, 900)
    shell.show()
    app.processEvents()
    header_shots = []
    for name, target in (
        ("home", shell.settings_scroll),
        ("workshop", shell.workshop_page),
        ("studio", shell.studio_page),
    ):
        shell.pages.setCurrentWidget(target)
        app.processEvents()
        shot = OUTPUT / f"header-{name}.png"
        shell.grab().save(str(shot))
        header_shots.append(str(shot))

    timer_canvas = MpvCanvas()
    timer_canvas._set_interpolation_base(0.0, paused=False)
    timer_canvas._timer.start()
    loop = QEventLoop()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    timer_canvas._timer.stop()
    playback = timer_canvas.playback_metrics()

    report = {
        "header_dpi_and_resolution": header_dpi,
        "timeline": {
            "scrollbar_visible": page.timeline.horizontal_scrollbar.isVisible(),
            "minimum": page.timeline.horizontal_scrollbar.minimum(),
            "maximum": page.timeline.horizontal_scrollbar.maximum(),
            "page_step": page.timeline.horizontal_scrollbar.pageStep(),
            "value": page.timeline.horizontal_scrollbar.value(),
            "playback_tick": playback,
        },
        "encoder_capabilities": {
            "ffmpeg_version": capabilities["ffmpeg_version"],
            "available_by_codec": capabilities["available_by_codec"],
            "probe_failures": capabilities["probe_failures"],
        },
        "screenshots": {
            "timeline": str(timeline_shot),
            "render": str(render_shot),
            "headers": header_shots,
        },
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    timer_canvas.close()
    render.close()
    page.close_page()
    page.close()
    shell.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
