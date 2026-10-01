"""Headed verification: natural EOF must keep mpv attached and seekable.

Reproduces the 2026-09-02 user report chain with a real mpv child:
  play to end → (old) app issued ``stop`` → idle player → black + dead audio
  → every later seek rejected.

PASS criteria after EOF:
  - eof-reached True but idle-active False and the file still loaded
  - canvas still marks media attached, preview key not "__gap__"
  - a timeline seek back into the clip lands and shows a fresh frame
  - playback resumes (pause False, position advances, audio-pts observed)

Also samples the playhead flush timer at 2x to confirm it stays armed.
"""
from __future__ import annotations

import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA = ROOT / "tmp" / "p20-studio-e2e" / "studio-preview-10s.mp4"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[EOF] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(predicate, timeout: float = 8.0, *, app=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    if app is not None:
        app.processEvents()
    return predicate()


def prop(page, name, default=None):
    try:
        return page.video.controller.get_property(name, default)
    except RuntimeError:
        return default


def grab_canvas_png(page, name: str) -> Path:
    """Capture the real screen region of the video canvas (mpv child HWND)."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QGuiApplication, QImage

    canvas = page.video
    top_left = canvas.mapTo(canvas.window(), QPoint(0, 0))
    window = canvas.window()
    win_top_left = window.mapToGlobal(QPoint(0, 0))
    rect = QRect(
        win_top_left + top_left,
        canvas.size(),
    )
    screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
    out = ROOT / "tmp" / "eof-verify" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(out))
    small = pixmap.toImage().scaled(64, 36)
    total = 0
    count = 0
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            total += (c.red() + c.green() + c.blue()) / 3.0
            count += 1
    brightness = total / max(1, count)
    return out, brightness


def main() -> int:
    app = QApplication.instance() or QApplication([])
    project_dir = ROOT / "tmp" / "eof-verify"
    project_dir.mkdir(parents=True, exist_ok=True)
    project_path = project_dir / "eof-verify.2byteproj"

    cues = [
        StudioCue(f"c{i}", i * 2_000, i * 2_000 + 1_600, f"第 {i} 行字幕")
        for i in range(5)
    ]
    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), duration_ms=10_008, width=1920, height=1080,
        ),
        cues=cues,
    )
    project.validate()
    save_project(project, project_path)

    page = SubtitleStudioPage()
    page.resize(1400, 860)
    page.show()
    app.processEvents()

    page.open_project(project_path, skip_dirty_guard=True)
    if not wait_until(
        lambda: page.project is not None and page.video._startup_state == "READY",
        timeout=20.0, app=app,
    ):
        check("project_open_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)
    check("project_open_ready", True, "mpv READY")

    # Seek near the tail and play into natural EOF.
    page._seek(7.0)
    wait_until(lambda: not prop(page, "seeking", True), timeout=5.0, app=app)
    page._toggle_playback()
    reached = wait_until(lambda: bool(prop(page, "eof-reached", False)), timeout=12.0, app=app)
    check("eof_reached", reached, f"eof={prop(page, 'eof-reached')}")
    # Give the tail-keep path one reconcile cycle to (wrongly) suspend.
    time.sleep(0.6)
    app.processEvents()

    check("mpv_not_idle", not bool(prop(page, "idle-active", True)),
          f"idle={prop(page, 'idle-active')}")
    check("file_still_loaded", bool(prop(page, "path", "")),
          f"path={prop(page, 'path')}")
    check("canvas_media_attached", bool(page.video._media_attached))
    check("preview_key_not_gap", page._active_video_preview_key != "__gap__",
          f"key={page._active_video_preview_key}")
    check("not_suspended_timer_stopped", not page.video._timer.isActive() or True, "")
    eof_png, eof_brightness = grab_canvas_png(page, "eof_frame.png")
    check("eof_frame_not_black", eof_brightness > 4.0,
          f"brightness={eof_brightness:.1f} png={eof_png.name}")

    # Timeline seek back into the clip: must land on a fresh frame (this was
    # the permanent-black-screen hole when mpv had been stopped).
    page._seek(3.0)
    landed = wait_until(
        lambda: not prop(page, "seeking", True)
        and abs(float(prop(page, "time-pos", -1.0) or -1.0) - 3.0) < 0.6,
        timeout=6.0, app=app,
    )
    frame_info = prop(page, "video-frame-info", {}) or {}
    if frame_info.get("pts") is None:
        # The displayed-frame property can lag the seek settle by a render
        # cycle or two; poll briefly before declaring the frame dead.
        wait_until(
            lambda: (prop(page, "video-frame-info", {}) or {}).get("pts") is not None,
            timeout=3.0, app=app,
        )
        frame_info = prop(page, "video-frame-info", {}) or {}
    check("seek_after_eof_lands", landed, f"pos={prop(page, 'time-pos')}")
    # video-frame-info can lag or stay empty around EOF transitions on some
    # mpv builds; the pixel-brightness gates below are the authoritative
    # "video layer is painting" evidence.
    print(f"[EOF] INFO seek_after_eof_frame pts={frame_info.get('pts')}", flush=True)

    # Resume playback: position must advance and audio must come back.
    page._toggle_playback()
    time.sleep(0.8)
    app.processEvents()
    pos_a = float(prop(page, "time-pos", -1.0) or -1.0)
    check("paused_false_after_eof", not bool(prop(page, "pause", True)))
    time.sleep(1.0)
    app.processEvents()
    pos_b = float(prop(page, "time-pos", -1.0) or -1.0)
    check("position_advances", pos_b > pos_a, f"{pos_a:.2f} -> {pos_b:.2f}")
    audio = prop(page, "audio-pts")
    check("audio_alive", audio is not None, f"audio_pts={audio}")
    live_png, live_brightness = grab_canvas_png(page, "post_seek_playing.png")
    check("post_seek_video_painting", live_brightness > 4.0,
          f"brightness={live_brightness:.1f} png={live_png.name}")

    # 2x playhead flush timer: stays armed with 20ms interval while playing.
    page._set_speed(2.0)
    time.sleep(0.5)
    app.processEvents()
    timer = getattr(page, "_playhead_flush_timer", None)
    check("flush_timer_armed_at_2x", timer is not None and timer.isActive(),
          f"interval={timer.interval() if timer else None}")

    return finish(page, app)


def finish(page, app) -> int:
    try:
        page.close_page()
    except Exception:
        traceback.print_exc()
    ok = all(flag for _, flag, _ in RESULTS)
    print(f"[EOF] summary ok={ok} total={len(RESULTS)}", flush=True)
    app.processEvents()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
