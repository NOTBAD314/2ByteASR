"""R31 probe: FLV native subtitle invisibility (user shot 4).

Opens a synthetic project pointing at the real Bilibili FLV with one cue at
15:55.138-15:57.138, seeks inside it, and samples the app-level visual
ownership + mpv sub state to catch the gate flip-flop.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA = Path("H:/record/Bilibili/Bilibili/企鹅带带北极熊/2026-09-04 20-05-04 异环新版本！拍卖！.flv")
PROJECT_DIR = ROOT / "tmp" / "round31-flv"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage


def prop(page, name, default=None):
    try:
        return page.video.controller.get_property(name, default)
    except (RuntimeError, TypeError):
        return default


def wait_until(predicate, timeout: float = 8.0, *, app=None) -> bool:
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


def main() -> int:
    app = QApplication.instance() or QApplication([])
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    project_path = PROJECT_DIR / "flv-sub-probe.2byteproj"

    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), duration_ms=1_756_570, width=2560, height=1440,
        ),
        cues=[],
    )
    project.validate()
    save_project(project, project_path)

    page = SubtitleStudioPage()
    page.resize(1500, 900)
    page.show()
    app.processEvents()
    page.open_project(str(project_path), skip_dirty_guard=True)
    if not wait_until(
        lambda: page.project is not None and page.video._startup_state == "READY",
        timeout=40.0, app=app,
    ):
        print(f"[R31] FAIL open startup={page.video._startup_state}")
        return finish(app, page)

    def owner_name() -> str:
        ownership = getattr(page, "_visual_ownership", None)
        try:
            current = ownership.current
        except Exception:
            return "?"
        return getattr(current, "value", str(current))

    def sample(label: str, seconds: float = 3.0) -> None:
        rows = []
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            app.processEvents()
            rows.append((prop(page, "sub-visibility"), repr(prop(page, "sub-text"))[:20], owner_name()[:40]))
            time.sleep(0.1)
        flips = sum(1 for a, b in zip(rows, rows[1:]) if a[0] != b[0])
        with_text = sum(1 for row in rows if row[1].strip("'"))
        print(f"[R31] {label}: flips={flips} with_text={with_text}/{len(rows)} "
              f"last={rows[-1] if rows else None}")

    # --- 用户路径复现：T 键在播放头新建字幕 → 画布编辑器 → 输入 → 提交 ---
    page._seek(955.7)
    wait_until(lambda: not prop(page, "seeking", True), timeout=10.0, app=app)
    page.cue_controller.add_subtitle_at_playhead()
    app.processEvents()
    editor = getattr(page, "_canvas_editor", None)
    print("[R31] canvas editor open:", editor is not None)
    if editor is not None:
        editor.setPlainText("这个道具给它展示了")
        app.processEvents()
        sample("during-edit", 1.5)
        page._commit_canvas_inline_edit()
        app.processEvents()
    time.sleep(1.0)
    app.processEvents()
    print("[R31] cue after commit:", [(c.start_ms, c.end_ms, c.text) for c in page.project.cues])
    print("[R31] selected:", page.selected_cue_id, "playhead:", page.timeline.playhead_ms)
    sample("after-commit", 4.0)

    # 位置编辑（变换框）激活时
    if getattr(page, "position_edit_button", None) is not None:
        page.position_edit_button.setChecked(True)
        page._toggle_position_edit(True)
        app.processEvents()
        time.sleep(0.5)
        sample("position-edit-on", 3.0)
        page.position_edit_button.setChecked(False)
        page._toggle_position_edit(False)
        app.processEvents()
        time.sleep(0.5)
        sample("position-edit-off", 2.0)
    return finish(app, page)


def finish(app, page) -> int:
    try:
        page.close_page()
    except Exception:
        traceback.print_exc()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
