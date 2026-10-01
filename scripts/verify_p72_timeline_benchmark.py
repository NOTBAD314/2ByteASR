"""Headed production Timeline benchmark for P7.2 long projects.

Automated MainWindow evidence is not a real-user click session.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P72_TIMELINE_OUTPUT",
    str(ROOT / "tmp" / "p72" / "timeline-benchmark"),
)).resolve()
MEDIA = ROOT / "tmp" / "p72" / "media" / "p72-6h.mp4"
PROJECT = OUTPUT / "p72-6h-10k-1k-mixed.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"]).unlink(missing_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.studio_edit_sequence import (
    EditSequence,
    HighlightCandidate,
    TimelineMarker,
    VideoSegment,
    runtime_of,
    store_sequence,
)
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.window_audit import qt_top_level_widgets, win32_top_level_windows


DURATION_MS = 6 * 60 * 60 * 1000
CUE_COUNT = 10_000
SEGMENT_COUNT = 334
CANDIDATE_COUNT = 333
MARKER_COUNT = 333


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return round(ordered[index], 3)


def stats(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else 0.0,
        "mean_ms": round(statistics.fmean(values), 3) if values else 0.0,
    }


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        QTest.qWait(5)


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def fixture_project() -> Path:
    if PROJECT.is_file():
        return PROJECT
    if not MEDIA.is_file():
        raise FileNotFoundError(MEDIA)
    step = DURATION_MS / CUE_COUNT
    cues = [
        StudioCue(
            id=f"cue-{index:05d}",
            start_ms=round(index * step),
            end_ms=min(DURATION_MS, round(index * step) + 1_200),
            text=f"P7.2 long cue {index:05d}",
            speaker_id=f"S{index % 3:02d}",
        )
        for index in range(CUE_COUNT)
    ]
    boundaries = [round(index * DURATION_MS / SEGMENT_COUNT) for index in range(SEGMENT_COUNT + 1)]
    segments = [
        VideoSegment(
            id=f"segment-{index:04d}", source_path=str(MEDIA),
            source_in_ms=boundaries[index], source_out_ms=boundaries[index + 1],
            timeline_in_ms=boundaries[index], timeline_out_ms=boundaries[index + 1],
        )
        for index in range(SEGMENT_COUNT)
    ]
    candidates = []
    for index in range(CANDIDATE_COUNT):
        start = round(index * (DURATION_MS - 30_000) / max(1, CANDIDATE_COUNT - 1))
        candidates.append(HighlightCandidate(
            id=f"candidate-{index:04d}", title=f"Candidate {index:04d}",
            source_in_ms=start, source_out_ms=min(DURATION_MS, start + 30_000),
            score=0.75,
        ))
    markers = [
        TimelineMarker(
            id=f"marker-{index:04d}",
            time_ms=round(index * (DURATION_MS - 1) / max(1, MARKER_COUNT - 1)),
            label=f"Marker {index:04d}",
        )
        for index in range(MARKER_COUNT)
    ]
    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), display_name=MEDIA.name, duration_ms=DURATION_MS,
            width=320, height=180,
        ),
        cues=cues,
        speakers=[
            StudioSpeaker("S00", "Speaker A"),
            StudioSpeaker("S01", "Speaker B"),
            StudioSpeaker("S02", "Speaker C"),
        ],
    )
    sequence = EditSequence(
        source_path=str(MEDIA), source_duration_ms=DURATION_MS,
        video_track_locked=False, segments=segments,
        clip_candidates=candidates, markers=markers,
    )
    store_sequence(project, sequence)
    return save_project(project, PROJECT)


def measure_paints(app: QApplication, timeline, start_ms: int, duration_ms: int) -> list[float]:
    timeline.set_visible_window(start_ms, duration_ms)
    pump(app, 120)
    rows: list[float] = []
    for index in range(30):
        timeline.set_playhead(min(DURATION_MS - 1, start_ms + (index + 1) * duration_ms // 31))
        started = time.perf_counter()
        timeline.repaint()
        rows.append((time.perf_counter() - started) * 1000.0)
        pump(app, 8)
    return rows


def measure_seek_feedback(app: QApplication, page, start_ms: int, duration_ms: int) -> list[float]:
    rows: list[float] = []
    for index in range(20):
        target = start_ms + (index + 1) * duration_ms // 21
        started = time.perf_counter()
        page._seek(target / 1000.0)
        page.timeline.repaint()
        rows.append((time.perf_counter() - started) * 1000.0)
        pump(app, 8)
    return rows


def main() -> int:
    project_path = fixture_project()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P7.2 Timeline Benchmark")
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    ui.apply_application_theme(app)
    result: dict[str, object] = {
        "schema": "2byteasr.p72-timeline-benchmark.v1",
        "evidence_class": "FORMAL HEADED PRODUCTION MAINWINDOW",
        "real_user_click": False,
        "project": str(project_path),
        "media": str(MEDIA),
        "counts": {
            "cues": CUE_COUNT,
            "segments": SEGMENT_COUNT,
            "candidates": CANDIDATE_COUNT,
            "markers": MARKER_COUNT,
            "mixed_overlays": SEGMENT_COUNT + CANDIDATE_COUNT + MARKER_COUNT,
        },
    }
    window = None
    before_pids = descendants()
    try:
        shell_started = time.perf_counter()
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        result["shell_construct_ms"] = round((time.perf_counter() - shell_started) * 1000.0, 3)
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 350)
        page = window.studio_page
        page._generate_waveform = lambda *_args, **_kwargs: None
        open_started = time.perf_counter()
        window.open_studio_project(project_path, source="p72-timeline-benchmark")
        pump(app, 250)
        result["project_open_usable_ms"] = round((time.perf_counter() - open_started) * 1000.0, 3)
        page.video.set_paused(True)
        page.select_cue("cue-05000")
        timeline = page.timeline
        runtime = runtime_of(page.project)

        overview_paints = measure_paints(app, timeline, 0, DURATION_MS)
        overview_seek = measure_seek_feedback(app, page, 0, DURATION_MS)
        zoom_start = DURATION_MS // 2 - 15_000
        zoom_paints = measure_paints(app, timeline, zoom_start, 30_000)
        zoom_seek = measure_seek_feedback(app, page, zoom_start, 30_000)
        query_started = time.perf_counter()
        visible = {
            "segments": len(runtime.visible_segments(zoom_start, zoom_start + 30_000)),
            "candidates": len(runtime.visible_candidates(zoom_start, zoom_start + 30_000)),
            "markers": len(runtime.visible_markers(zoom_start, zoom_start + 30_000)),
        }
        query_ms = (time.perf_counter() - query_started) * 1000.0
        result["overview"] = {
            "visible_duration_ms": DURATION_MS,
            "paint": stats(overview_paints),
            "seek_feedback": stats(overview_seek),
            "visible_cues": len(timeline.visible_cues()),
        }
        result["zoom30"] = {
            "visible_duration_ms": 30_000,
            "paint": stats(zoom_paints),
            "seek_feedback": stats(zoom_seek),
            "visible_cues": len(timeline.visible_cues()),
            "visible_mixed": visible,
            "visible_index_query_ms": round(query_ms, 3),
        }
        screen = QGuiApplication.primaryScreen()
        screenshot = OUTPUT / "timeline-6h-10k-1k-headed.png"
        captured = screen.grabWindow(int(window.winId())) if screen else window.grab()
        result["screenshot"] = str(screenshot)
        result["screenshot_saved"] = bool(not captured.isNull() and captured.save(str(screenshot), "PNG"))
        pids = descendants()
        result["window_audit"] = {
            "visible_win32": [item for item in win32_top_level_windows(pids=pids) if item.get("visible")],
            "visible_qt": [item for item in qt_top_level_widgets(app) if item.get("visible")],
        }
        child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
        result["child_process_records"] = (
            [
                record
                for line in child_log.read_text(encoding="utf-8").splitlines()
                if (record := json.loads(line)).get("root_pid") == os.getpid()
            ]
            if child_log.is_file() else []
        )
        result["checks"] = {
            "overview_paint_p95_lt_33": result["overview"]["paint"]["p95_ms"] < 33.0,
            "zoom30_paint_p95_lt_33": result["zoom30"]["paint"]["p95_ms"] < 33.0,
            "overview_seek_p95_lt_50": result["overview"]["seek_feedback"]["p95_ms"] < 50.0,
            "zoom30_seek_p95_lt_50": result["zoom30"]["seek_feedback"]["p95_ms"] < 50.0,
            "mixed_overlay_count": sum(visible.values()) < 20,
            "screenshot_saved": result["screenshot_saved"],
        }
        result["pass"] = all(result["checks"].values())
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump(app, 500)
        remaining = descendants() - before_pids - {os.getpid()}
        result["remaining_child_pids"] = sorted(remaining)
        result["no_remaining_children"] = not remaining
        result["pass"] = bool(result.get("pass") and result["no_remaining_children"])
    target = OUTPUT / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target, flush=True)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
