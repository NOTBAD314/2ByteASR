"""Open the retained Studio acceptance project in a real Windows window."""

from __future__ import annotations

import json
import os
import sys
import ctypes
import copy
import time
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.studio_project import load_project, save_project


def main() -> int:
    project = ROOT / "tmp" / "p20-studio-e2e" / "studio.2byteproj"
    if not project.is_file():
        raise FileNotFoundError(project)
    low_track_project = project.with_name("studio-two-tracks.2byteproj")
    low_track = copy.deepcopy(load_project(project))
    speaker_ids = list(dict.fromkeys(cue.speaker_id for cue in low_track.cues))[:2]
    low_track.cues = [cue for cue in low_track.cues if cue.speaker_id in speaker_ids]
    low_track.speakers = [speaker for speaker in low_track.speakers if speaker.id in speaker_ids]
    low_track.studio_state = {}
    save_project(low_track, low_track_project)
    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.setWindowTitle("2ByteASR Subtitle Studio Acceptance")
    page.resize(1920, 1080)
    page.move(0, 0)
    page.open_project(project)
    page.show()
    QCursor.setPos(page.mapToGlobal(QPoint(100, 80)))
    report_path = ROOT / "tmp" / "p20-studio-e2e" / "visible-window-report.json"

    def start_playback() -> None:
        if page.video.controller:
            page.video.controller.seek(5.0, accurate=True)
            page.video.controller.set_paused(False)

    screenshots: dict[str, str] = {}
    reopened_context_tab: dict[str, int | None] = {"value": None}

    def capture(name: str) -> None:
        hwnd = int(page.winId())
        user32 = ctypes.windll.user32
        flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        user32.keybd_event(0x1B, 0, 0, 0)
        user32.keybd_event(0x1B, 0, 0x0002, 0)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)
        time.sleep(0.08)
        app.processEvents()
        screen = app.primaryScreen()
        target = ROOT / "tmp" / "p20-studio-e2e" / f"p20-2-final-{name}.png"
        frame = page.frameGeometry()
        pixmap = screen.grabWindow(0, frame.x(), frame.y(), frame.width(), frame.height())
        if pixmap.isNull() or not pixmap.save(str(target)):
            raise RuntimeError(f"could not capture visible Studio state: {name}")
        if pixmap.width() != 1920 or pixmap.height() != 1080:
            pixmap = pixmap.scaled(
                1920,
                1080,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not pixmap.save(str(target)):
                raise RuntimeError(f"could not normalize Studio screenshot: {name}")
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
        screenshots[name] = str(target)
        print(
            f"captured {name}: bilingual={page.bilingual_button.isChecked()} "
            f"tab={page.context_drawer.currentIndex()} context={page.context_panel.isVisible()} "
            f"workspace={page.workspace_splitter.sizes()} center={page.center_splitter.sizes()}",
            flush=True,
        )

    def capture_expanded() -> None:
        page._show_context_panel()
        page.context_drawer.setCurrentIndex(2)
        page._set_bilingual_mode(False)
        capture("context-expanded")

    def capture_collapsed() -> None:
        page._collapse_context_panel()
        capture("panel-collapsed")

    def capture_reopened() -> None:
        page._show_context_panel()
        reopened_context_tab["value"] = page.context_drawer.currentIndex()
        capture("panel-reopened-check-tab")

    def capture_resized() -> None:
        page.workspace_splitter.setSizes([650, 300])
        page.center_splitter.setSizes([465, 175])
        app.processEvents()
        capture("splitters-adjusted")

    def open_low_track() -> None:
        page.open_project(low_track_project)
        page._show_context_panel()
        page.context_drawer.setCurrentIndex(0)
        page._set_bilingual_mode(False)

    def capture_low_track_and_close() -> None:
        capture("two-track-default")
        controller = page.video.controller
        properties = {}
        if controller:
            for name in (
                "video-format",
                "width",
                "height",
                "time-pos",
                "pause",
                "sid",
                "sub-text",
            ):
                try:
                    properties[name] = controller.get_property(name)
                except RuntimeError as exc:
                    properties[name] = {"unavailable": str(exc)}
        report_path.write_text(
            json.dumps(
                {
                    "screenshots": screenshots,
                    "mpv": properties,
                    "preview_status": page.save_state.text(),
                    "preview_error": page.video.toolTip(),
                    "selected_cue": page.selected_cue_id,
                    "playhead_ms": page.timeline.playhead_ms,
                    "zoom": page.project.studio_state.get("zoom") if page.project else None,
                    "context_tab_after_reopen": reopened_context_tab["value"],
                    "workspace_sizes": page.workspace_splitter.sizes(),
                    "center_sizes": page.center_splitter.sizes(),
                    "track_count": len(page.timeline.speaker_ids()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        page.close()
        app.quit()

    QTimer.singleShot(1200, start_playback)
    QTimer.singleShot(2300, capture_expanded)
    QTimer.singleShot(3000, capture_collapsed)
    QTimer.singleShot(3700, capture_reopened)
    QTimer.singleShot(4400, capture_resized)
    QTimer.singleShot(5100, open_low_track)
    QTimer.singleShot(5900, capture_low_track_and_close)
    result = app.exec()
    page.close_page()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
