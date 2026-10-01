"""Reproducible GUI performance audit for the production PySide6 widgets.

The script does not run ASR or mutate settings. It exercises the real
MainWindow routes and writes a JSON snapshot suitable for before/after runs.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget  # noqa: E402

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_render_ui import StudioRenderDialog  # noqa: E402


class EventCounter(QObject):
    def __init__(self):
        super().__init__()
        self.counts = Counter()

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.Type.Paint:
            self.counts["paint"] += 1
        elif event_type == QEvent.Type.Resize:
            self.counts["resize"] += 1
        elif event_type == QEvent.Type.LayoutRequest:
            self.counts["layout_request"] += 1
        return False

    def delta(self, before):
        return {key: self.counts[key] - before.get(key, 0) for key in self.counts}


def _rss_mb() -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return round(counters.WorkingSetSize / 1024 / 1024, 2) if ok else None
    except Exception:
        return None


def _pump(app: QApplication, rounds: int = 2):
    for _ in range(rounds):
        app.processEvents()


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    if not ordered:
        return {"count": 0}
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "count": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(ordered), 3),
        "over_50ms": sum(value > 50 for value in ordered),
        "over_100ms": sum(value > 100 for value in ordered),
        "over_250ms": sum(value > 250 for value in ordered),
    }


def _measure(app, action, cycles: int) -> list[float]:
    values = []
    for index in range(cycles):
        started = time.perf_counter()
        action(index)
        _pump(app)
        values.append((time.perf_counter() - started) * 1000)
    return values


def _select_term_game(window, name: str):
    library = window.term_library_page.library
    if library is None:
        return
    for index in range(library.game_list.count()):
        item = library.game_list.item(index)
        if str(item.data(Qt.ItemDataRole.UserRole)) == name:
            library.game_list.setCurrentItem(item)
            return


def _object_snapshot(window) -> dict:
    return {
        "widgets": len(QApplication.allWidgets()),
        "timers": len(window.findChildren(QTimer)),
        "python_threads": threading.active_count(),
        "rss_mb": _rss_mb(),
    }


def _synthetic_studio_project(cue_count: int = 10_000) -> SubtitleProject:
    """Build a deterministic five-hour project without touching media runtimes."""
    cues = []
    for index in range(cue_count):
        start_ms = index * 1_800
        cues.append(
            StudioCue(
                id=f"perf-{index:05d}",
                start_ms=start_ms,
                end_ms=start_ms + 1_300,
                text=f"性能基线字幕 {index + 1}，用于验证长时间轴可视区域绘制。",
                original_text=f"性能基线字幕 {index + 1}，用于验证长时间轴可视区域绘制。",
                speaker_id=f"S{index % 4 + 1:02d}",
            )
        )
    return SubtitleProject(
        media=StudioMedia(
            path=str(ROOT / "tmp" / "performance-profile" / "synthetic-5h.mp4"),
            display_name="synthetic-5h.mp4",
            duration_ms=18_000_000,
        ),
        cues=cues,
        speakers=[StudioSpeaker(id=f"S{index:02d}", name=f"Speaker {index}") for index in range(1, 5)],
    )


def _profile_studio(app, window, counter) -> dict:
    profile_root = ROOT / "tmp" / "performance-profile"
    profile_root.mkdir(parents=True, exist_ok=True)
    project_path = save_project(
        _synthetic_studio_project(), profile_root / "synthetic-5h.2byteproj"
    )
    studio = window.studio_page
    studio.video.load = lambda *_args, **_kwargs: None
    studio._restore_playhead = lambda *_args, **_kwargs: None
    studio._generate_waveform = lambda *_args, **_kwargs: None

    results = {}
    results["home_to_studio"] = _summary(
        _measure(app, lambda _index: window._open_subtitle_studio(str(project_path)), 1)
    )
    results["project_open"] = _summary(
        _measure(app, lambda _index: studio.open_project(project_path), 3)
    )

    cue_ids = [studio.project.cues[index].id for index in range(0, 400, 20)]
    results["cue_selection"] = _summary(
        _measure(app, lambda index: studio.select_cue(cue_ids[index % len(cue_ids)]), 40)
    )

    edit_values = [f"性能编辑 {index}" for index in range(20)]
    results["subtitle_text_edit"] = _summary(
        _measure(app, lambda index: studio.cue_text.setPlainText(edit_values[index]), 20)
    )

    list_scrollbar = studio.cue_table.verticalScrollBar()
    results["subtitle_list_scroll"] = _summary(
        _measure(
            app,
            lambda index: list_scrollbar.setValue(
                round(list_scrollbar.maximum() * ((index % 20) / 19))
            ),
            100,
        )
    )

    timeline_scrollbar = studio.timeline.horizontal_scrollbar
    results["timeline_horizontal_scroll"] = _summary(
        _measure(
            app,
            lambda index: timeline_scrollbar.setValue(
                round(timeline_scrollbar.maximum() * ((index % 20) / 19))
            ),
            100,
        )
    )
    zoom_levels = (10_000, 20_000, 60_000, 120_000, 300_000)
    results["timeline_zoom"] = _summary(
        _measure(
            app,
            lambda index: studio.timeline.set_visible_window(
                studio.timeline.visible_start_ms, zoom_levels[index % len(zoom_levels)]
            ),
            50,
        )
    )
    results["timeline_resize"] = _summary(
        _measure(
            app,
            lambda index: studio.timeline.resize(900 + index % 7 * 30, 210 + index % 5 * 12),
            50,
        )
    )
    results["timeline_playhead_follow"] = _summary(
        _measure(
            app,
            lambda index: (
                studio.timeline.set_playhead(index * 180_000),
                studio.timeline.reveal_playhead(index * 180_000),
            ),
            50,
        )
    )

    def inline_edit(index):
        cue = studio.project.cues[index % 20]
        # Exercise the public mutation path.  The old harness reached through
        # the private overlay editor and crashed whenever geometry correctly
        # declined to create ``_inline_editor`` (for example offscreen).
        studio.cue_controller.set_text(
            cue.id,
            f"时间轴编辑 {index}",
            command_text="Performance inline edit",
        )

    results["inline_edit"] = _summary(_measure(app, inline_edit, 20))

    studio._load_style_inspector()
    style_values = (48, 54, 64, 72, 96)
    results["style_change"] = _summary(
        _measure(
            app,
            lambda index: studio.style_font_size.setValue(style_values[index % len(style_values)]),
            20,
        )
    )
    results["context_panel_open"] = _summary(
        _measure(
            app,
            lambda index: studio._set_major_panel_visible("context", bool(index % 2)),
            20,
        )
    )

    def combo_cycle(_index):
        # P22.11 renders style scope as radio buttons. The remaining expensive
        # Style popup is the lazy system-font chooser, so profile that directly.
        studio.style_font.showPopup()
        app.processEvents()
        studio.style_font.hidePopup()

    results["combobox_open"] = _summary(_measure(app, combo_cycle, 20))
    results["ass_preview_update"] = _summary(
        _measure(app, lambda _index: studio._refresh_ass_preview(), 10)
    )
    results["waveform_paint"] = _summary(
        _measure(app, lambda _index: studio.timeline.grab(), 30)
    )
    results["project_save"] = _summary(
        _measure(app, lambda _index: save_project(studio.project, project_path), 5)
    )
    results["project_autosave"] = _summary(
        _measure(app, lambda _index: studio._autosave(), 5)
    )

    render_dialogs = []

    def render_dialog_open(_index):
        dialog = StudioRenderDialog(
            studio.project,
            str(studio._preview_path),
            studio.timeline.playhead_ms / 1000.0,
            studio,
        )
        dialog.show()
        app.processEvents()
        dialog.close()
        render_dialogs.append(dialog)

    results["render_dialog_open"] = _summary(_measure(app, render_dialog_open, 5))
    results["project_close"] = _summary(
        _measure(app, lambda _index: studio.close_page(), 1)
    )
    results["event_counts"] = dict(counter.counts)
    summaries = [value for value in results.values() if isinstance(value, dict) and "max_ms" in value]
    results["main_thread_max_block_ms"] = max(
        (float(summary["max_ms"]) for summary in summaries), default=0.0
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--studio-only", action="store_true")
    args = parser.parse_args()

    # Keep profiling reproducible and isolated from the user's real recent
    # projects, autosaves and Studio settings.
    profile_local_data = ROOT / "tmp" / "performance-profile" / "local-app-data"
    profile_local_data.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(profile_local_data)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    counter = EventCounter()
    app.installEventFilter(counter)

    cold_started = time.perf_counter()
    window = ui.MainWindow(
        [], subtitle_core, moss_firered_pipeline, {"id": "p10-profile", "checks": 0}
    )
    window.resize(1366, 768)
    window.show()
    _pump(app, 3)
    cold_ms = (time.perf_counter() - cold_started) * 1000
    window._background_preload()
    _pump(app)

    result = {
        "schema_version": 3,
        "platform": os.environ.get("QT_QPA_PLATFORM", "desktop"),
        "cold_start_visible_ms": round(cold_ms, 3),
        "rss_start_mb": _rss_mb(),
    }

    # Measure Studio before opening repeated modal surfaces. Keeping this near
    # cold start prevents retained top-level widgets from distorting editor,
    # timeline, save and render-dialog latency.
    before_studio_events = dict(counter.counts)
    result["studio"] = _profile_studio(app, window, counter)
    result["studio"]["event_counts"] = counter.delta(before_studio_events)
    if args.studio_only:
        result["rss_end_mb"] = _rss_mb()
        window.close()
        _pump(app)
        app.removeEventFilter(counter)
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        print(payload)
        if args.output:
            target = args.output if args.output.is_absolute() else ROOT / args.output
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload + "\n", encoding="utf-8")
        return 0

    first_routes = {}
    routes = (
        ("workshop", window._open_model_workshop),
        ("terms", window._manage_terms),
        ("history", window._open_recognition_history),
        ("home", lambda: window.pages.setCurrentWidget(window.settings_scroll)),
    )
    for name, route in routes:
        first_routes[name] = _summary(_measure(app, lambda _i, fn=route: fn(), 1))
    result["first_routes"] = first_routes

    route_samples = {name: [] for name, _route in routes}
    route_times = []
    for index in range(100):
        name, route = routes[index % len(routes)]
        sample = _measure(app, lambda _i, fn=route: fn(), 1)[0]
        route_samples[name].append(sample)
        route_times.append(sample)
    result["page_switch_100"] = _summary(route_times)
    result["warm_routes_100"] = {
        name: _summary(samples) for name, samples in route_samples.items()
    }

    window._manage_terms()
    _pump(app, 4)
    term_names = ("原神", "异环", "我的世界", "洛克王国：世界")
    term_times = _measure(
        app, lambda i: _select_term_game(window, term_names[i % len(term_names)]), 20
    )
    result["term_switch_20"] = _summary(term_times)
    library = window.term_library_page.library
    if library is not None:
        result["term_table_rows"] = library._term_model.rowCount()
        row_counts = {}
        for name in ("原神", "异环", "我的世界"):
            _select_term_game(window, name)
            _pump(app, 2)
            row_counts[name] = library._term_model.rowCount()
        result["term_row_counts"] = row_counts

    window.pages.setCurrentWidget(window.settings_scroll)
    _pump(app)
    before_events = dict(counter.counts)
    resize_times = _measure(
        app,
        lambda i: window.resize(
            1366 + (i % 9) * 54,
            768 + (i % 7) * 34,
        ),
        100,
    )
    result["resize_100"] = _summary(resize_times)
    result["resize_event_counts"] = counter.delta(before_events)

    window._open_model_workshop()
    _pump(app)
    scroll = window.workshop_page.findChild(QScrollArea, "workshopScroll")
    before_events = dict(counter.counts)
    scroll_times = _measure(
        app,
        lambda i: scroll.verticalScrollBar().setValue(
            int(scroll.verticalScrollBar().maximum() * ((i % 20) / 19))
        ),
        100,
    )
    result["scroll_100"] = _summary(scroll_times)
    result["scroll_event_counts"] = counter.delta(before_events)
    result["objects_before_modals"] = _object_snapshot(window)

    def picker_cycle(_index):
        window._open_model_picker("primary")
        window._modal_host._request_close()

    result["model_picker_20"] = _summary(_measure(app, picker_cycle, 20))

    def technical_cycle(_index):
        window.workshop_page._selected_key = "moss"
        window.workshop_page._show_technical_details()
        window._modal_host._request_close()

    result["technical_20"] = _summary(_measure(app, technical_cycle, 20))
    result["objects_after_modal_40"] = _object_snapshot(window)

    # External-AI Smart Builder flow: real production widgets, preview only.
    clipboard = app.clipboard()
    previous_clipboard = clipboard.text()
    smart = ui.SmartGlossaryDialog(window, "原神", window._modal_host.body)
    window._modal_host.show_content(
        smart,
        title="智能建词｜原神",
        size=(980, 720),
        min_size=(760, 560),
    )
    _pump(app, 2)
    smart.copy_ai_prompt_button.click()
    copied_prompt = clipboard.text()
    smart.pasted_editor.setPlainText(
        "标准词\t分类\t别名或常见错写\n"
        "芙宁娜\t角色\t芙宁那|水神\n"
        "仆人\t怪物/Boss\t阿蕾奇诺\n"
    )
    smart.start_extraction()
    deadline = time.perf_counter() + 3.0
    while smart._worker is not None and smart._worker.isRunning() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    _pump(app, 2)
    result["smart_builder_tsv"] = {
        "prompt_copied": "原神" in copied_prompt and "TSV" in copied_prompt,
        "candidate_count": len(smart._candidates),
        "review_visible": not smart.review_panel.isHidden(),
        "statuses": sorted({candidate.status for candidate in smart._candidates}),
    }
    clipboard.setText(previous_clipboard)
    window._modal_host._request_close()
    _pump(app)

    before_events = dict(counter.counts)
    stability_times = []
    for index in range(30):
        stability_times.extend(_measure(app, picker_cycle, 1))
        stability_times.extend(_measure(app, technical_cycle, 1))
    result["modal_stability_60"] = _summary(stability_times)
    result["modal_stability_event_counts"] = counter.delta(before_events)
    result["objects_after_modal_100"] = _object_snapshot(window)

    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    while time.perf_counter() - wall_started < 0.5:
        app.processEvents()
        time.sleep(0.005)
    cpu_elapsed = time.process_time() - cpu_started
    wall_elapsed = time.perf_counter() - wall_started
    result["idle_cpu_percent"] = round(cpu_elapsed / wall_elapsed * 100, 2)
    result["objects"] = _object_snapshot(window)
    result["events_total"] = dict(counter.counts)
    result["rss_end_mb"] = _rss_mb()

    window.close()
    _pump(app)
    app.removeEventFilter(counter)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        target = args.output if args.output.is_absolute() else ROOT / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
