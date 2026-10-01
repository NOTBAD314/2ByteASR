"""P6.1 real-window screenshots: timeline order, live find, blank project, home."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))

from PySide6.QtWidgets import QApplication, QSplitter

import subtitle_core as legacy

from twobyteasr.studio_find_replace import FindReplaceDialog
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.theme_manager import apply_application_theme
from twobyteasr.ui import MainWindow

SHOTS = ROOT / "tmp" / "p61-accept"
SHOTS.mkdir(parents=True, exist_ok=True)
CLIP = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.mp4"


def pump(app, ms=200):
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(widget, name: str) -> Path:
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(name)
    print("shot", target)
    return target


def demo_project() -> SubtitleProject:
    media_path = str(CLIP) if CLIP.is_file() else "D:/rec.mp4"
    return SubtitleProject(
        media=StudioMedia(path=media_path, display_name="p61.mp4", duration_ms=30_000, width=1280, height=720),
        speakers=[StudioSpeaker("S01", "主播"), StudioSpeaker("S02", "队友")],
        cues=[
            StudioCue("c1", 800, 2800, "尼奈今天这把有点悬", "S01"),
            StudioCue("c2", 4200, 6800, "尼奈也好笑死", "S01"),
            StudioCue("c3", 11000, 15000, "等一下我还能反杀", "S02"),
        ],
    )


def main() -> int:
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, "plum")
    evidence: dict[str, object] = {}

    window = MainWindow([], legacy, object(), None)
    window.show()
    pump(app, 250)
    evidence["home"] = str(grab(window, "home.png"))
    evidence["home-cta-heights"] = {
        "studio": window.studio_footer_button.height(),
        "start": window.start_button.height(),
        "min_window": [window.minimumWidth(), window.minimumHeight()],
        "header_status_hidden": window.header_status.isHidden(),
    }
    for width, height, name in ((1366, 768, "home-1366"), (1600, 900, "home-1600"), (1920, 1080, "home-1920")):
        window.resize(width, height)
        pump(app, 180)
        evidence[name] = str(grab(window, f"{name}.png"))
        right = window.home_task_settings_button
        geo = right.rect()
        mapped = right.mapTo(window, geo.topLeft())
        evidence[f"{name}-advanced-settings"] = {
            "x": mapped.x(),
            "y": mapped.y(),
            "w": right.width(),
            "h": right.height(),
            "clipped": mapped.x() + right.width() > window.width() - 8,
        }

    page = window.studio_page
    page.video.load = lambda *_a, **_k: None
    page._generate_waveform = lambda *_a, **_k: None
    window.pages.setCurrentWidget(page)
    page.show_project_hub()
    pump(app, 220)
    evidence["hub"] = str(grab(page, "hub.png"))
    evidence["hub-clip-assistant-visible"] = page.studio_clip_assistant_button.isVisible()

    page._create_blank_studio()
    pump(app, 250)
    evidence["blank-studio"] = str(grab(page, "blank-studio.png"))
    evidence["blank"] = {
        "media_path": page.project.media.path if page.project else None,
        "cues": len(page.project.cues) if page.project else None,
        "empty_visible": not page.video_empty_hint.isHidden(),
        "view": getattr(page, "_project_view_state", ""),
    }

    page.show_project_hub()
    pump(app, 120)
    page.studio_clip_assistant_button.click()
    pump(app, 250)
    evidence["hub-clip-assistant"] = str(grab(page, "hub-clip-assistant.png"))
    evidence["clip-assistant-tab"] = page.context_drawer.tabText(page.context_drawer.currentIndex())

    path = save_project(demo_project(), SHOTS / "p61-demo.2byteproj")
    page.open_project(path)
    page.resize(1440, 900)
    pump(app, 300)
    evidence["studio"] = str(grab(page, "studio.png"))
    evidence["timeline"] = str(grab(page.timeline, "timeline.png"))
    video = page.timeline._video_track_rect()
    speakers, _translation, waveform = page.timeline._track_layout()
    last = list(speakers.values())[-1]
    evidence["track-order"] = {
        "last_speaker_bottom": round(last.bottom(), 1),
        "video_top": round(video.top(), 1),
        "video_bottom": round(video.bottom(), 1),
        "waveform_top": round(waveform.top(), 1),
        "v1_above_waveform": video.bottom() <= waveform.top() + 2,
        "speakers_above_v1": last.bottom() <= video.top() + 2,
        "opaque_resize": page.workspace_splitter.opaqueResize(),
    }
    evidence["studio-1366"] = str(_shot_resized(page, 1366, 768, "studio-1366.png"))
    evidence["studio-1600"] = str(_shot_resized(page, 1600, 900, "studio-1600.png"))
    evidence["context-width"] = page.context_panel.width()
    evidence["context-min"] = page.context_panel.minimumWidth()

    dialog = FindReplaceDialog(page, page)
    dialog.show()
    pump(app, 180)
    evidence["find-empty"] = str(grab(dialog, "find-empty.png"))
    dialog.find_edit.setText("尼奈")
    dialog.replace_edit.setText("她")
    pump(app, 280)
    evidence["find-nynay"] = str(grab(dialog, "find-nynay.png"))
    evidence["find"] = {
        "count": dialog.preview.count(),
        "status": dialog.status_label.text(),
        "object_name": dialog.objectName(),
        "min_size": [dialog.minimumWidth(), dialog.minimumHeight()],
    }
    dialog.close()

    splitter: QSplitter = page.workspace_splitter
    evidence["splitter-opaque"] = splitter.opaqueResize() is False
    page.close_page()
    window.close()
    (SHOTS / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


def _shot_resized(widget, width: int, height: int, name: str) -> Path:
    widget.resize(width, height)
    app = QApplication.instance()
    pump(app, 180)
    return grab(widget, name)


if __name__ == "__main__":
    raise SystemExit(main())
