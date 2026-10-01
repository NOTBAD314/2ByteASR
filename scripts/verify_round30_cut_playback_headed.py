"""Headed verification: 剪辑对位与播放流畅性（第三十轮，2026-09-04）。

Reproduces the user report chain with a real mpv child and a synthetic 60s
clip (testsrc2 + 440Hz tone). Ripple-trim the first 30s, then prove:

  1. mpv lands on the retained source head (~30s), never source 0
  2. playback advances with the UI playhead on the trimmed timeline
  3. source position never ping-pongs into the deleted head
  4. timeline seeks map into the retained source range
  5. timeline end pauses cleanly (no deleted-tail playback / EOF freeze)
  6. pressing play after end restarts at the retained head
  7. a deleted middle range is bridged: source jumps 40→45 while the
     timeline playhead stays continuous
  8. save + reopen restores the mapped source position
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

PROJECT_DIR = ROOT / "tmp" / "round30-verify"
MEDIA = PROJECT_DIR / "recording-60s.mp4"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_edit_commands import (
    delete_video_segments_command,
    razor_video_command,
    ripple_trim_command,
    set_video_lock_command,
)
from twobyteasr.studio_edit_sequence import segment_at, sequence_of
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R30] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


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


def prop(page, name, default=None):
    try:
        return page.video.controller.get_property(name, default)
    except (RuntimeError, TypeError):
        return default


def time_pos(page) -> float:
    value = prop(page, "time-pos", -1.0)
    return float(value) if value is not None else -1.0


def build_project(project_path: Path) -> None:
    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), duration_ms=60_000, width=640, height=360,
        ),
        cues=[
            StudioCue("c1", 30_500, 32_000, "保留段第一句"),
            StudioCue("c2", 40_000, 41_500, "后段字幕"),
        ],
    )
    project.validate()
    save_project(project, project_path)


def open_ready(app, project_path) -> SubtitleStudioPage | None:
    page = SubtitleStudioPage()
    page.resize(1400, 860)
    page.show()
    app.processEvents()
    page.open_project(str(project_path), skip_dirty_guard=True)
    if not wait_until(
        lambda: page.project is not None and page.video._startup_state == "READY",
        timeout=25.0, app=app,
    ):
        check("project_open_ready", False, f"startup={page.video._startup_state}")
        page.close_page()
        page.deleteLater()
        return None
    check("project_open_ready", True, "mpv READY")
    return page


def main() -> int:
    app = QApplication.instance() or QApplication([])
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    if not MEDIA.is_file():
        print(f"[R30] FAIL missing media {MEDIA}", flush=True)
        return 2
    project_path = PROJECT_DIR / "cut-playback.2byteproj"
    build_project(project_path)

    page = open_ready(app, project_path)
    if page is None:
        return finish(app, None)
    try:
        run_scenario(app, page, project_path)
    except Exception:
        traceback.print_exc()
        check("scenario_no_exception", False, "see traceback")
    return finish(app, page)


def run_scenario(app, page: SubtitleStudioPage, project_path: Path) -> None:
    # --- linear sanity -----------------------------------------------------
    page._refresh_edit_playback_state()
    check("linear_mode_source", page._playback_mode == "source",
          f"mode={page._playback_mode}")
    check("linear_duration_override", abs(page.video._duration_override - 60.0) < 0.01,
          f"override={page.video._duration_override}")

    # --- ripple-trim the first 30s (the user's Q flow) ---------------------
    project = page.project
    page.undo_stack.push(set_video_lock_command(project, False))
    page.undo_stack.push(ripple_trim_command(project, "start", 30_000, page._sequence_changed))

    sequence = sequence_of(project)
    check("mapped_mode", page._playback_mode == "mapped", f"mode={page._playback_mode}")
    check("mapped_override_cleared", page.video._duration_override == 0.0,
          f"override={page.video._duration_override}")
    check("mapped_canvas_duration_is_source", abs(page.video._duration - 60.0) < 0.01,
          f"duration={page.video._duration}")
    check("timeline_total_trimmed", sequence.timeline_duration_ms == 30_000,
          f"total={sequence.timeline_duration_ms}")

    landed = wait_until(lambda: abs(time_pos(page) - 30.0) <= 0.8, timeout=8.0, app=app)
    check("retained_head_lands", landed, f"time_pos={time_pos(page):.2f}")
    check("playhead_at_zero", abs(page.timeline.playhead_ms) < 1_200,
          f"playhead={page.timeline.playhead_ms}")

    # --- play: source stays in the retained range, UI playhead runs 1x -----
    page._toggle_playback()
    wait_until(lambda: not prop(page, "seeking", True), timeout=5.0, app=app)
    samples: list[tuple[float, float, int]] = []
    started = time.monotonic()
    while time.monotonic() - started < 3.0:
        app.processEvents()
        samples.append((time.monotonic() - started, time_pos(page), page.timeline.playhead_ms))
        time.sleep(0.05)
    source_values = [item[1] for item in samples if item[1] >= 0]
    check("source_never_enters_deleted_head", min(source_values) >= 29.0,
          f"min_source={min(source_values):.2f}")
    playhead_values = [item[2] for item in samples]
    backward = max(
        (b - a for a, b in zip(playhead_values, playhead_values[1:])), default=0.0
    )
    check("playhead_monotonic", backward <= 250.0, f"max_backward_ms={backward:.0f}")
    advance_ms_per_s = (playhead_values[-1] - playhead_values[0]) / max(0.1, samples[-1][0] - samples[0][0])
    check("playhead_realtime_rate", 700.0 <= advance_ms_per_s <= 1300.0,
          f"advance={advance_ms_per_s:.0f}ms/s")

    # --- timeline seek maps into retained range ----------------------------
    page._toggle_playback()  # pause
    page._seek(15.0)
    mapped_seek = wait_until(lambda: abs(time_pos(page) - 45.0) <= 0.8, timeout=8.0, app=app)
    check("timeline_seek_maps_to_source", mapped_seek, f"time_pos={time_pos(page):.2f}")

    # --- timeline end pauses cleanly ----------------------------------------
    page._seek(28.5)
    wait_until(lambda: not prop(page, "seeking", True), timeout=5.0, app=app)
    page._toggle_playback()
    ended = wait_until(
        lambda: bool(prop(page, "eof-reached", False)) or bool(prop(page, "pause", False)),
        timeout=10.0, app=app,
    )
    check("timeline_end_stops", ended,
          f"eof={prop(page, 'eof-reached')} pause={prop(page, 'pause')}")
    a, b = time_pos(page), time_pos(page)
    time.sleep(1.0)
    app.processEvents()
    b = time_pos(page)
    check("position_frozen_at_end", abs(b - a) <= 0.3, f"{a:.2f} -> {b:.2f}")
    check("playhead_parked_at_timeline_end", abs(page.timeline.playhead_ms - 30_000) <= 1_200,
          f"playhead={page.timeline.playhead_ms}")

    # --- restart after end returns to the retained head ---------------------
    page._toggle_playback()
    restarted = wait_until(
        lambda: abs(time_pos(page) - 30.0) <= 0.8 and not bool(prop(page, "pause", True)),
        timeout=8.0, app=app,
    )
    check("eof_restart_at_retained_head", restarted,
          f"time_pos={time_pos(page):.2f} pause={prop(page, 'pause')}")
    check("eof_restart_playhead_zero", page.timeline.playhead_ms < 2_000,
          f"playhead={page.timeline.playhead_ms}")
    page._toggle_playback()  # pause

    # --- delete a middle range: boundary must bridge 40 -> 45 ----------------
    project = page.project
    page.undo_stack.push(razor_video_command(project, 10_000, page._sequence_changed))
    page.undo_stack.push(razor_video_command(project, 15_000, page._sequence_changed))
    middle = segment_at(sequence_of(project), 12_500)
    page.undo_stack.push(delete_video_segments_command(project, [middle.id], page._sequence_changed))
    segments = sequence_of(project).segments
    check("two_segments_after_middle_delete", len(segments) == 2,
          f"segments={[(s.source_in_ms, s.source_out_ms) for s in segments]}")

    page._seek(0.0)
    wait_until(lambda: abs(time_pos(page) - 30.0) <= 0.8, timeout=8.0, app=app)
    page._toggle_playback()
    crossing: list[tuple[float, int]] = []
    started = time.monotonic()
    bridged = False
    while time.monotonic() - started < 14.0:
        app.processEvents()
        crossing.append((time_pos(page), page.timeline.playhead_ms))
        positions = [item[0] for item in crossing[-8:] if item[0] >= 0]
        if positions and min(positions) >= 44.5 and max(positions) >= 44.5:
            bridged = True
            break
        time.sleep(0.05)
    check("boundary_bridge_to_next_segment", bridged,
          f"last_positions={[round(p, 1) for p in positions[-4:]] if crossing else '[]'}")
    timeline_values = [item[1] for item in crossing]
    backward = max(
        (b2 - a2 for a2, b2 in zip(timeline_values, timeline_values[1:])), default=0.0
    )
    check("boundary_playhead_continuous", backward <= 300.0,
          f"max_backward_ms={backward:.0f}")
    source_jump = any(
        b2 - a2 >= 4.0
        for (a1, _), (b1, _) in zip(crossing, crossing[1:])
        for a2, b2 in [(a1, b1)]
    )
    check("boundary_source_jump_observed", source_jump, "")
    page._toggle_playback()  # pause

    # --- save + reopen restores mapped source position ----------------------
    page._seek(5.0)
    wait_until(lambda: abs(time_pos(page) - 35.0) <= 0.8, timeout=8.0, app=app)
    save_project(project, project_path)
    page.close_page()
    page.deleteLater()

    reopened = open_ready(app, project_path)
    if reopened is None:
        return
    restored = wait_until(lambda: abs(time_pos(reopened) - 35.0) <= 1.0, timeout=10.0, app=app)
    check("reopen_restores_mapped_source", restored,
          f"time_pos={time_pos(reopened):.2f} playhead={reopened.timeline.playhead_ms}")
    reopened.close_page()
    reopened.deleteLater()


def finish(app, page) -> int:
    if page is not None:
        try:
            page.close_page()
        except Exception:
            traceback.print_exc()
    ok = all(flag for _, flag, _ in RESULTS)
    print(f"[R30] summary ok={ok} total={len(RESULTS)}", flush=True)
    app.processEvents()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
