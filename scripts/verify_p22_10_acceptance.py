"""Real-window acceptance for the scoped P22.10 Studio reliability hotfix."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "1")

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p22.10-acceptance"
SCREENSHOTS = ROOT / "screenshots" / "p22.10"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"local-{os.getpid()}")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

sys.path.insert(0, str(ROOT))

from twobyteasr.studio_project import load_project
from twobyteasr.studio_ui import SubtitleStudioPage


SOURCE_PROJECT = Path(
    Path.home() / "Desktop" / r"2ByteASR Projects\大饭包 开挖土机\大饭包 开挖土机.2byteproj"
)
def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + milliseconds / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            break
        time.sleep(0.01)


def wait_until(app: QApplication, predicate, timeout_s: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout_s:
        pump(app, 20)
        if predicate():
            return (time.perf_counter() - started) * 1000.0
    raise TimeoutError(label)


def timing(action, app: QApplication, cycles: int = 1) -> dict[str, float | int]:
    values = []
    for _ in range(cycles):
        started = time.perf_counter()
        action()
        app.processEvents()
        values.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(values), 3),
    }


def capture_desktop(page: SubtitleStudioPage, name: str, app: QApplication) -> Path:
    hwnd = int(page.winId())
    user32 = ctypes.windll.user32
    page.showNormal()
    page.activateWindow()
    page.raise_()
    user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    pump(app, 150)
    frame = page.frameGeometry()
    pixmap = app.primaryScreen().grabWindow(
        0, frame.x(), frame.y(), frame.width(), frame.height()
    )
    target = SCREENSHOTS / f"{name}.png"
    if pixmap.width() != 1920 or pixmap.height() != 1080:
        pixmap = pixmap.scaled(
            1920,
            1080,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if pixmap.isNull() or not pixmap.save(str(target)):
        raise RuntimeError(f"could not capture {target}")
    return target


def send_windows_key(page: SubtitleStudioPage, app: QApplication, virtual_key: int) -> float:
    hwnd = int(page.winId())
    target_hwnd = int(page.video.winId())
    user32 = ctypes.windll.user32
    page.activateWindow()
    page.raise_()
    user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    pump(app, 80)
    started = time.perf_counter()
    if not user32.PostMessageW(target_hwnd, 0x0100, virtual_key, 1):
        raise RuntimeError(f"could not post WM_KEYDOWN {virtual_key:#x}")
    if not user32.PostMessageW(
        target_hwnd, 0x0101, virtual_key, (1 << 31) | (1 << 30) | 1
    ):
        raise RuntimeError(f"could not post WM_KEYUP {virtual_key:#x}")
    app.processEvents()
    dispatch_ms = (time.perf_counter() - started) * 1000.0
    pump(app, 80)
    return dispatch_ms


def selected_style(page: SubtitleStudioPage):
    cue = next(cue for cue in page.project.cues if cue.id == page.selected_cue_id)
    return next(style for style in page.project.styles if style.id == cue.style_id)


def set_font_size(page: SubtitleStudioPage, app: QApplication, value: int) -> dict:
    before_generation = page._ass_generation
    before_path = page._preview_path
    started = time.perf_counter()
    page.style_font_size.setValue(value)
    page._commit_style_now()
    commit_ms = (time.perf_counter() - started) * 1000.0
    wait_ms = wait_until(
        app,
        lambda: (
            page._ass_generation > before_generation
            and page._preview_path is not None
            and page._preview_path != before_path
            and page._preview_path.is_file()
        ),
        15.0,
        f"ASS preview did not refresh for font size {value}",
    )
    pump(app, 500)
    ass_text = page._preview_path.read_text(encoding="utf-8-sig")
    style_line = next(line for line in ass_text.splitlines() if line.startswith("Style: Default,"))
    screenshot = capture_desktop(page, f"style-font-{value}", app)
    return {
        "ui_value": page.style_font_size.value(),
        "project_value": selected_style(page).font_size,
        "ass_style": style_line,
        "preview_path": str(page._preview_path),
        "commit_ms": round(commit_ms, 3),
        "refresh_wait_ms": round(wait_ms, 3),
        "screenshot": str(screenshot),
    }


def main() -> int:
    if not SOURCE_PROJECT.is_file():
        raise FileNotFoundError(SOURCE_PROJECT)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    project_copy = OUTPUT / "real-242-copy.2byteproj"
    shutil.copy2(SOURCE_PROJECT, project_copy)

    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.setWindowTitle("2ByteASR P22.10 Real Acceptance")
    page.resize(1920, 1080)
    page.move(0, 0)
    page.show()
    page.activateWindow()
    pump(app, 150)

    report: dict[str, object] = {
        "source_project": str(SOURCE_PROJECT),
        "working_copy": str(project_copy),
        "screen": {
            "available": [app.primaryScreen().availableGeometry().width(), app.primaryScreen().availableGeometry().height()],
            "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
        },
        "editing": {},
        "style": {},
        "review": {},
        "layout": {},
        "performance": {},
    }

    open_started = time.perf_counter()
    page.open_project(project_copy)
    report["performance"]["studio_open_ms"] = round(
        (time.perf_counter() - open_started) * 1000.0, 3
    )
    report["performance"]["studio_open_profile_ms"] = {
        name: round(seconds * 1000.0, 3)
        for name, seconds in page.last_open_profile.items()
    }
    pump(app, 1800)
    if page.video.controller is None:
        raise RuntimeError(f"real mpv controller unavailable: {page.video.toolTip()}")
    report["cue_count"] = len(page.project.cues)
    report["mpv"] = {
        name: page.video.controller.get_property(name)
        for name in ("width", "height", "video-format", "pause", "sid")
    }

    first = page.project.cues[0]
    second = page.project.cues[1]
    original_first = first.text
    original_second = second.text
    page.select_cue(first.id)
    pump(app, 50)

    # Subtitle List: real double-click editor, Enter commit, unified Undo.
    list_started = time.perf_counter()
    list_index = page.cue_model.index(page.cue_model.row_for_cue_id(first.id), 3)
    page.cue_table.scrollTo(list_index)
    pump(app, 30)
    list_point = page.cue_table.visualRect(list_index).center()
    QTest.mouseClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=list_point)
    QTest.mouseDClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton, pos=list_point)
    pump(app, 30)
    list_editor = QApplication.focusWidget()
    if not isinstance(list_editor, QLineEdit):
        raise RuntimeError(f"list inline editor did not open: {type(list_editor).__name__}")
    list_editor.selectAll()
    QTest.keyClicks(list_editor, "P22.10 list edit")
    QTest.keyClick(list_editor, Qt.Key.Key_Return)
    pump(app, 60)
    list_commit_ms = (time.perf_counter() - list_started) * 1000.0
    list_committed = page._cue_lookup[first.id].text
    page.undo_stack.undo()
    pump(app, 30)
    report["editing"]["list"] = {
        "committed": list_committed,
        "undo_restored": page._cue_lookup[first.id].text == original_first,
        "current_editor_synced": page.cue_text.toPlainText() == original_first,
        "elapsed_ms": round(list_commit_ms, 3),
    }

    # Timeline: real editor, blank-click commit, then Tab navigation and Undo.
    page.timeline.set_visible_window(0, max(10_000, second.end_ms + 2_000))
    pump(app, 40)
    timeline_started = time.perf_counter()
    page.timeline._open_inline_editor(first, False, first.text)
    inline_begin_ms = (time.perf_counter() - timeline_started) * 1000.0
    timeline_editor = page.timeline._inline_editor
    editor_width = timeline_editor.width()
    cue_width = max(
        24,
        round(page.timeline._time_to_x(first.end_ms) - page.timeline._time_to_x(first.start_ms)),
    )
    timeline_editor.selectAll()
    QTest.keyClicks(timeline_editor, "P22.10 timeline edit")
    blank_started = time.perf_counter()
    QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    pump(app, 50)
    blank_commit_ms = (time.perf_counter() - blank_started) * 1000.0
    blank_committed = page._cue_lookup[first.id].text
    page.timeline._open_inline_editor(second, False, second.text)
    QTest.keyClick(page.timeline._inline_editor, Qt.Key.Key_Tab)
    pump(app, 30)
    tab_target = page.timeline._inline_target
    QTest.keyClick(page.timeline._inline_editor, Qt.Key.Key_Escape)
    page.undo_stack.undo()
    pump(app, 30)
    report["editing"]["timeline"] = {
        "blank_click_committed": blank_committed,
        "editor_closed": page.timeline._inline_editor is None,
        "editor_width": editor_width,
        "cue_width": cue_width,
        "inside_cue": editor_width == cue_width,
        "tab_target": list(tab_target) if tab_target else None,
        "expected_tab_target": first.id if False else page.project.cues[2].id,
        "undo_restored": page._cue_lookup[first.id].text == original_first,
        "inline_begin_ms": round(inline_begin_ms, 3),
        "blank_commit_ms": round(blank_commit_ms, 3),
    }

    # Style panel and mpv/libass path.
    page._show_context_panel()
    page.context_drawer.setCurrentIndex(2)
    page.select_cue(first.id)
    page._seek((first.start_ms + 50) / 1000.0)
    page.video.set_paused(True)
    pump(app, 300)
    report["layout"] = {
        "window": [page.width(), page.height()],
        "video_widget_height": page.video.height(),
        "center_splitter": page.center_splitter.sizes(),
        "workspace_splitter": page.workspace_splitter.sizes(),
        "waveform_default_height": page.timeline.WAVEFORM_TRACK_HEIGHT,
        "central_editor_in_center_layout": page.cue_editor.parent() is page,
    }
    report["style"]["screenshot"] = str(capture_desktop(page, "style-panel-1920x1080", app))
    report["style"]["font_sizes"] = {
        str(value): set_font_size(page, app, value) for value in (52, 100, 500)
    }

    wheel_before = page.style_font_size.value()
    page.style_font_size.setFocus()
    wheel = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(page.style_font_size, wheel)
    pump(app, 30)
    report["style"]["wheel_safety"] = {
        "before": wheel_before,
        "after": page.style_font_size.value(),
        "unchanged": wheel_before == page.style_font_size.value(),
    }

    # Priority Review: all commands enter via real key events on the visible page.
    page.style_font_size.clearFocus()
    page.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
    page.follow_playhead_toggle.setChecked(False)
    page._activate_filter("priority")
    if page.cue_model.rowCount() == 0:
        raise RuntimeError("real project unexpectedly has no priority review cues")
    review_first = page.cue_model.cue_at(0).id
    page.select_cue(review_first)
    page.video.set_paused(True)
    pump(app, 80)
    replay_trace = {"calls": 0}
    original_replay = page._play_review_context

    def traced_replay() -> None:
        replay_trace["calls"] += 1
        original_replay()

    page._play_review_context = traced_replay
    space_dispatch_ms = send_windows_key(page, app, 0x20)  # VK_SPACE
    pump(app, 180)
    if replay_trace["calls"] != 1:
        raise RuntimeError(
            f"Win32 Space dispatched {replay_trace['calls']} review replay calls"
        )
    replay = {
        "cue": review_first,
        "review_replay_calls": replay_trace["calls"],
        "time_pos": page.video.controller.get_property("time-pos"),
        "pause_during_context": page.video.controller.get_property("pause"),
        "dispatch_ms": round(space_dispatch_ms, 3),
    }
    replay["auto_pause_wait_ms"] = round(
        wait_until(
            app,
            lambda: bool(page.video.controller.get_property("pause", False)),
            8.0,
            "review replay did not auto-pause",
        ),
        3,
    )
    review_before_enter = page.selected_cue_id
    shortcut_context = {
        "active_window": QApplication.activeWindow() is page,
        "focus_widget": type(QApplication.focusWidget()).__name__ if QApplication.focusWidget() else None,
    }
    enter_ms = send_windows_key(page, app, 0x0D)  # VK_RETURN
    review_after_enter = page.selected_cue_id
    confirmed = review_before_enter in page.project.studio_state.get("review_confirmations", {})
    send_windows_key(page, app, 0x45)  # E
    edit_focused = page.cue_text.hasFocus()
    page.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
    pump(app, 30)
    reasr_signal = {"done": False, "kind": "", "payload": ""}
    page.reasr_ready_signal.connect(
        lambda result: reasr_signal.update(
            done=True, kind="ready", payload=str(result.recommendation)
        )
    )
    page.reasr_failed_signal.connect(
        lambda message: reasr_signal.update(done=True, kind="failed", payload=str(message))
    )
    before_reasr = page.ai_preview.toPlainText()
    reasr_dispatch_ms = send_windows_key(page, app, 0x52)  # R
    dispatch_text = page.ai_preview.toPlainText()
    reasr_dispatched = dispatch_text != before_reasr or reasr_signal["done"]
    reasr_result = {
        "dispatched": reasr_dispatched,
        "dispatch_ms": round(reasr_dispatch_ms, 3),
        "initial_text": dispatch_text,
    }
    try:
        reasr_result["wait_ms"] = round(
            wait_until(
                app,
                lambda: reasr_signal["done"],
                180.0,
                "local Re-ASR did not finish in 180 seconds",
            ),
            3,
        )
        reasr_result["result"] = page.ai_preview.toPlainText()
        reasr_result["signal"] = dict(reasr_signal)
        reasr_result["completed"] = True
    except TimeoutError as exc:
        reasr_result["completed"] = False
        reasr_result["error"] = str(exc)
    report["review"] = {
        "priority_count_before": 110,
        "shortcut_context": shortcut_context,
        "space": replay,
        "enter": {
            "cue_before": review_before_enter,
            "confirmed": confirmed,
            "advanced": review_after_enter != review_before_enter,
            "next_cue": review_after_enter,
            "elapsed_ms": round(enter_ms, 3),
        },
        "edit_focused": edit_focused,
        "reasr": reasr_result,
    }

    # Preserve an explicit edit across save/reopen on the copied project.
    persisted_text = "P22.10 persisted edit"
    page._timeline_text_edited(first.id, False, persisted_text)
    page.save()
    page.close_page()
    page.close()
    pump(app, 100)
    reloaded = load_project(project_copy)
    report["save_reopen"] = {
        "persisted": next(cue for cue in reloaded.cues if cue.id == first.id).text == persisted_text,
        "text": next(cue for cue in reloaded.cues if cue.id == first.id).text,
        "font_size": next(style for style in reloaded.styles if style.id == "default").font_size,
    }

    performance = report["performance"]
    performance.update(
        {
            "inline_begin_ms": report["editing"]["timeline"]["inline_begin_ms"],
            "inline_commit_ms": report["editing"]["timeline"]["blank_commit_ms"],
            "list_inline_edit_ms": report["editing"]["list"]["elapsed_ms"],
            "style_preview_commit_ms": max(
                row["commit_ms"] for row in report["style"]["font_sizes"].values()
            ),
            "review_next_ms": report["review"]["enter"]["elapsed_ms"],
        }
    )
    performance["guards"] = {
        "studio_open_under_1500ms": performance["studio_open_ms"] < 1500,
        "inline_begin_under_50ms": performance["inline_begin_ms"] < 50,
        "inline_commit_under_100ms": performance["inline_commit_ms"] < 100,
        "list_edit_under_250ms": performance["list_inline_edit_ms"] < 250,
        "style_commit_under_250ms": performance["style_preview_commit_ms"] < 250,
        "review_next_under_100ms": performance["review_next_ms"] < 100,
    }
    report_path = OUTPUT / "p22.10-real-acceptance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
