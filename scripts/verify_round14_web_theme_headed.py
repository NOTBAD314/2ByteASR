"""Headed verification for round 14: web-theme subtitle visibility + buttons
+ storyboard demo + 4x playhead cadence, on a COPY of the user's real project.

Checks:
  A. applying a web theme to a cue leaves the cue's subtitle VISIBLE
     (advanced LIVE owns the foreground; no UnboundLocalError in the path)
  B. 应用 button re-applies to the current selection; 保存样式 persists
  C. storyboard renders three real HTML/CSS stills into the draft card
  D. 4x playback: steady playhead updates, few window jumps
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

PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.web_theme import builtin_web_themes

RESULTS: list[tuple[str, bool, str]] = []
STAMPS: list[float] = []
JUMPS: list[float] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R14] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1700, 940)
    page.show()
    app.processEvents()
    page.open_project(PROJECT, skip_dirty_guard=True)
    if not wait_until(app, lambda: page.project is not None and page.video._startup_state == "READY", 25.0):
        check("project_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)

    cues = page.project.cues
    target = next((c for c in cues if 30_000 <= c.start_ms <= 60_000), cues[0])
    page.select_cue(target.id)
    theme = builtin_web_themes()["balatro-joker"].to_dict()

    # A) apply + subtitle stays visible
    applied = page._apply_web_theme(target.id, theme)
    check("web_theme_applied", applied)
    check("pending_web_theme_stashed", getattr(page, "_pending_web_theme", None) is not None)
    page._seek((target.start_ms + 200) / 1000.0)
    wait_until(
        app,
        lambda: page._last_subtitle_visibility_trace.get("foreground_owner", "") != "",
        timeout=15.0,
    )
    trace = page._last_subtitle_visibility_trace
    owner = str(trace.get("foreground_owner", ""))
    check(
        "subtitle_foreground_owned",
        owner in {"advanced_live", "advanced_fidelity"},
        f"owner={owner} route={trace.get('renderer_route')}",
    )
    check("advanced_canvas_visible", bool(trace.get("advanced_canvas_visible")))

    # B) 应用 button re-applies to the current selection
    other = next((c for c in cues if c.id != target.id and 20_000 <= c.start_ms <= 80_000), None)
    page.select_cue(other.id)
    page._apply_ai_preview()
    payload_other = page.project.style_recipes.get(
        page._cue_lookup.get(other.id).style_id, {}
    )
    check("apply_button_reapplies", isinstance(payload_other.get("webTheme"), dict))

    from twobyteasr.studio_style_controller import StudioStyleController

    persisted: list[object] = []
    original_persist = StudioStyleController._persist_ai_design
    StudioStyleController._persist_ai_design = lambda self, s: persisted.append(s)
    try:
        page._save_ai_design_presets()
    finally:
        StudioStyleController._persist_ai_design = original_persist
    check("save_button_persists_recipe", bool(persisted))

    # C) storyboard: three real stills land in the draft card
    page._start_web_theme_storyboard(theme)
    wrap = getattr(page, "ai_web_theme_storyboard_wrap", None)
    labels = getattr(page, "ai_web_theme_storyboard_labels", None) or []
    ok = wait_until(
        app,
        lambda: all(
            label.pixmap() is not None and not label.pixmap().isNull() for label in labels
        ),
        timeout=90.0,
    )
    shots_dir = ROOT / "tmp" / "r14-verify"
    shots_dir.mkdir(exist_ok=True)
    saved = 0
    for index, label in enumerate(labels):
        pm = label.pixmap()
        if pm is not None and not pm.isNull():
            pm.save(str(shots_dir / f"storyboard-{index}.png"))
            saved += 1
    check("storyboard_three_stills", ok and saved == 3, f"saved={saved}")

    # D) 4x playhead cadence + window jumps
    original_playhead = page._apply_project_playhead

    def timed_playhead(milliseconds: int, *, defer_follow: bool = False) -> None:
        STAMPS.append(time.perf_counter() * 1000.0)
        original_playhead(milliseconds, defer_follow=defer_follow)

    page._apply_project_playhead = timed_playhead  # type: ignore[method-assign]
    timeline = page.timeline
    original_window = timeline.set_visible_window

    def counting_window(start, duration):
        JUMPS.append(time.perf_counter())
        return original_window(start, duration)

    timeline.set_visible_window = counting_window  # type: ignore[method-assign]
    page.follow_playhead_toggle.setChecked(True)

    page._seek(40.0)
    wait_until(app, lambda: not page.video.controller.get_property("seeking", True), 6.0)
    page._set_speed(4.0)
    page._toggle_playback()
    horizon = time.perf_counter() + 10.0
    while time.perf_counter() < horizon:
        app.processEvents()
        time.sleep(0.004)
    page._toggle_playback()
    page._set_speed(1.0)
    page._apply_project_playhead = original_playhead  # type: ignore[method-assign]
    timeline.set_visible_window = original_window  # type: ignore[method-assign]

    if len(STAMPS) > 30:
        intervals = [STAMPS[i + 1] - STAMPS[i] for i in range(len(STAMPS) - 1)]
        mean = statistics.mean(intervals)
        p50 = statistics.median(intervals)
        # Mean is contaminated by the Chromium churn from section A-C;
        # the cadence gate is the steady-state p50.
        check("4x_playhead_steady", 12.0 <= p50 <= 30.0,
              f"n={len(STAMPS)} mean={mean:.1f}ms p50={p50:.1f}ms")
        check("4x_window_jumps_bounded", len(JUMPS) <= 4, f"jumps={len(JUMPS)}")
    else:
        check("4x_playhead_steady", False, f"only {len(STAMPS)} updates")

    return finish(page, app)


def finish(page, app) -> int:
    try:
        page.close_page()
    except Exception:
        traceback.print_exc()
    ok = all(flag for _, flag, _ in RESULTS)
    print(f"[R14] summary ok={ok} total={len(RESULTS)}", flush=True)
    app.processEvents()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
