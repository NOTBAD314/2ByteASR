"""Headed Windows P6.7 interaction, HWND, process, and renderer acceptance."""

from __future__ import annotations

import copy
import faulthandler
import json
import os
import shutil
import statistics
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p67-runtime"
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"
PROJECT_COPY = OUTPUT / "p67-real-hour-copy.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
STACK_LOG = (OUTPUT / "runtime-stacks.log").open("w", encoding="utf-8")
faulthandler.enable(STACK_LOG)
faulthandler.dump_traceback_later(20.0, repeat=True, file=STACK_LOG)
shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
os.environ["TWOBYTEASR_INTERACTION_LATENCY_PATH"] = str(OUTPUT / "interaction-latency.json")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.advanced_renderer import normalized_visual_snapshot
from twobyteasr.ass_compiler import compile_ass
from twobyteasr.processes import child_process_start_count
from twobyteasr.studio_ai import AIDesignSuggestion, style_recipe_for_prompt, visual_design_variants
from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_project import StudioCue, SubtitleStyle
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_presets import BUILTIN_PRESETS
from twobyteasr.style_recipe import FillSpec
from twobyteasr.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.window_audit import TopLevelWindowAudit, qt_top_level_widgets, win32_top_level_windows


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        time.sleep(0.005)


def progress(message: str) -> None:
    print(f"[p67] {message}", flush=True)


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return round((time.perf_counter() - started) * 1000.0, 1)
        time.sleep(0.01)
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


class RuntimeMonitor:
    """Poll real EnumWindows and descendants while each interaction is active."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.action = "startup"
        self.baseline_hwnds: set[int] = set()
        self.new_windows: list[dict[str, object]] = []
        self.observed_children: dict[int, dict[str, object]] = {}
        self._seen: set[tuple[str, int]] = set()
        self.thread = threading.Thread(target=self._work, daemon=True, name="p67-runtime-monitor")

    def start(self) -> None:
        self.thread.start()

    def set_baseline(self) -> None:
        self.baseline_hwnds = {
            int(item["hwnd"])
            for item in win32_top_level_windows(pids=descendants())
            if item.get("visible")
        }

    def set_action(self, value: str) -> None:
        self.action = str(value)

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.0)

    def _work(self) -> None:
        while not self.stop_event.is_set():
            pids = descendants()
            for pid in pids - {os.getpid()}:
                try:
                    process = psutil.Process(pid)
                    self.observed_children.setdefault(pid, {
                        "pid": pid,
                        "name": process.name(),
                        "exe": process.exe(),
                        "cmdline": process.cmdline(),
                        "parent_pid": process.ppid(),
                    })
                except (psutil.Error, OSError):
                    pass
            if self.baseline_hwnds:
                for item in win32_top_level_windows(pids=pids):
                    hwnd = int(item["hwnd"])
                    if not item.get("visible") or hwnd in self.baseline_hwnds:
                        continue
                    key = (self.action, hwnd)
                    if key not in self._seen:
                        self._seen.add(key)
                        self.new_windows.append({"action": self.action, **item})
            self.stop_event.wait(0.02)


def mpv_pid(page: SubtitleStudioPage) -> int:
    controller = page.video.controller
    process = getattr(controller, "_process", None) if controller else None
    return int(process.pid) if process is not None else 0


def safe_mpv_property(page: SubtitleStudioPage, name: str):
    controller = page.video.controller
    if controller is None:
        return None
    try:
        return controller.get_property(name, None)
    except RuntimeError as exc:
        return {"unavailable": str(exc)}


def screenshot(page: SubtitleStudioPage, name: str, *, entire_screen: bool = False) -> str:
    target = OUTPUT / name
    screen = QGuiApplication.primaryScreen()
    pixmap = (
        screen.grabWindow(0 if entire_screen else int(page.window().winId()))
        if screen else page.grab()
    )
    if not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"failed to save screenshot: {target}")
    return str(target)


def widget_screenshot(widget, name: str) -> str:
    target = OUTPUT / name
    if not widget.grab().save(str(target), "PNG"):
        raise RuntimeError(f"failed to save widget screenshot: {target}")
    return str(target)


def add_runtime_cue(page: SubtitleStudioPage, cue_id: str = "p67-cue") -> StudioCue:
    cue = StudioCue(cue_id, 6_817_000, 6_821_000, "真正移动的字幕：黄色到青色", style_id="default")
    page.project.cues = [cue]
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.select_cue(cue.id)
    page.timeline.set_playhead(cue.start_ms)
    page._seek(cue.start_ms / 1000.0)
    return cue


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, round((len(ordered) - 1) * ratio))], 3)


def main() -> int:
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    latency_path = Path(os.environ["TWOBYTEASR_INTERACTION_LATENCY_PATH"])
    for path in (child_log, latency_path, OUTPUT / "window-events.jsonl"):
        if path.exists():
            path.unlink()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P6.7 Runtime Acceptance")
    qt_audit: TopLevelWindowAudit | None = None
    monitor: RuntimeMonitor | None = None
    progress("constructing page")
    page = SubtitleStudioPage()
    page.setWindowTitle("2ByteASR P6.7 Runtime Acceptance")
    page.resize(1800, 1050)
    progress("showing page")
    page.show()
    pump(app, 200)
    progress("page shown")
    result: dict[str, object] = {
        "schema": "2byteasr.p67-runtime.v1",
        "project": str(PROJECT_COPY),
        "pid": os.getpid(),
        "phases": {},
    }

    def phase(name: str, callback, *, loops: int = 1, settle_ms: int = 12):
        if monitor is not None:
            monitor.set_action(name)
        values: list[float] = []
        children_before = child_process_start_count()
        for _index in range(loops):
            started = time.perf_counter()
            callback()
            values.append((time.perf_counter() - started) * 1000.0)
            pump(app, settle_ms)
        children_after = child_process_start_count()
        return {
            "iterations": loops,
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3),
            "child_process_starts": children_after - children_before,
        }

    try:
        progress("opening real project copy")
        page.open_project(PROJECT_COPY)
        progress("open_project returned")
        wait_until(app, lambda: page.video.controller is not None and page.video.controller.running, 20.0, "mpv")
        pump(app, 1200)
        progress("mpv ready; adding runtime cue")
        original_mpv_pid = mpv_pid(page)
        add_runtime_cue(page)
        pump(app, 400)
        progress("runtime cue ready; capturing baseline")
        # The independent RuntimeMonitor supplies full Win32 process/window
        # fields.  Keep the synchronous Qt event hook lightweight so the
        # diagnostic probe does not inflate popup/interaction latency.
        qt_audit = TopLevelWindowAudit(app, capture_win32=False)
        monitor = RuntimeMonitor()
        monitor.start()
        monitor.set_baseline()
        baseline_windows = win32_top_level_windows(pids=descendants())
        result["startup"] = {
            "mpv_pid": original_mpv_pid,
            "child_start_count": child_process_start_count(),
            "qt_top_levels": qt_top_level_widgets(app),
            "win32_top_levels": baseline_windows,
            "screenshot": screenshot(page, "01-headed-baseline.png"),
        }
        progress("baseline captured; running phase A")

        # A: sustained ordinary edit interactions.
        razor_points = iter(range(120_000, 220_000, 5_000))
        a = {
            "razor": phase("A Razor", lambda: page._razor_video_at(next(razor_points)), loops=20),
            "undo": phase("A Undo", page._undo_interactive, loops=10),
            "redo": phase("A Redo", page._redo_interactive, loops=10),
            "lock": phase("A Lock", page._toggle_video_lock, loops=20),
        }

        def delete_then_undo() -> None:
            sequence = sequence_of(page.project)
            if not sequence.segments:
                return
            target = sequence.segments[min(1, len(sequence.segments) - 1)].id
            page.timeline.selected_segment_id = target
            page.timeline.selected_segment_ids = {target}
            page._delete_selected_timeline_segments()
            page._undo_interactive()

        a["delete_undo"] = phase("A Delete", delete_then_undo, loops=10)

        def t_escape() -> None:
            before = len(page.project.cues)
            page._add_subtitle_at_playhead()
            pump(app, 5)
            page._cancel_canvas_inline_edit()
            if len(page.project.cues) != before:
                raise AssertionError("Esc left a temporary T cue behind")

        a["t_escape"] = phase("A T Esc", t_escape, loops=10)
        preset_ids = iter(("game", "clean-white") * 5)

        def switch_preset() -> None:
            preset_id = next(preset_ids)
            index = page.style_preset.findData(preset_id)
            page.style_preset.setCurrentIndex(index)
            page._preset_activated(index)

        a["preset"] = phase("A Preset", switch_preset, loops=10, settle_ms=5)

        def font_popup() -> None:
            page.style_font.showPopup()
            pump(app, 25)
            page.style_font.hidePopup()

        a["font_popup"] = phase("A Font popup", font_popup, loops=10, settle_ms=5)
        # Let the native QComboBox popup surface finish hiding before the next
        # acceptance action so the monitor cannot attribute the same expected
        # popup HWND to B/E because of its polling boundary.
        monitor.set_action("A Font popup settle")
        pump(app, 150)
        result["phases"]["A"] = a
        progress("phase A complete; running B-F")

        # B: only-segment deletion must idle the existing mpv process; Undo restores it.
        monitor.set_action("B reload")
        page.open_project(PROJECT_COPY)
        wait_until(app, lambda: page.video.controller is not None and page.video.controller.running, 20.0, "reloaded mpv")
        pump(app, 1000)
        before_empty_pid = mpv_pid(page)
        sequence = sequence_of(page.project)
        only = sequence.segments[0].id
        page.timeline.selected_segment_id = only
        page.timeline.selected_segment_ids = {only}
        empty_metrics = phase("B Delete only segment", page._delete_selected_timeline_segments)
        controller = page.video.controller
        empty_path = safe_mpv_property(page, "path")
        empty_state = {
            "sequence_empty": sequence_of(page.project).empty_timeline,
            "play_enabled": page.play_button.isEnabled(),
            "media_attached": page.video._media_attached,
            "mpv_pid": mpv_pid(page),
            "mpv_path": empty_path,
            "metrics": empty_metrics,
        }
        page._toggle_playback()
        page._seek(10.0)
        empty_state["after_play_seek_path"] = safe_mpv_property(page, "path")
        undo_metrics = phase("B Undo empty", page._undo_interactive)
        pump(app, 300)
        result["phases"]["B"] = {
            "before_mpv_pid": before_empty_pid,
            "empty": empty_state,
            "undo": {
                "metrics": undo_metrics,
                "sequence_empty": sequence_of(page.project).empty_timeline,
                "media_attached": page.video._media_attached,
                "mpv_pid": mpv_pid(page),
                "path": safe_mpv_property(page, "path"),
                "empty_hint_visible": page.video_empty_hint.isVisible(),
                "video_visible": page.video.isVisible(),
            },
        }

        # C: T hides Transform until commit; Esc removes a new temporary cue.
        page.project.cues = []
        page.cue_controller.model_changed()
        page.position_edit_button.setChecked(True)
        t_metrics = phase("C T", page._add_subtitle_at_playhead)
        pump(app, 80)
        transform_hidden_during_edit = page.position_overlay.isHidden()
        page.subtitle_edit_input.setPlainText("提交后才出现 Transform")
        commit_metrics = phase("C Commit T", page._commit_canvas_inline_edit)
        pump(app, 80)
        transform_visible_after_commit = page.position_overlay.isVisible()
        committed_count = len(page.project.cues)
        page._add_subtitle_at_playhead()
        pump(app, 40)
        page._cancel_canvas_inline_edit()
        result["phases"]["C"] = {
            "t_metrics": t_metrics,
            "commit_metrics": commit_metrics,
            "transform_hidden_during_edit": transform_hidden_during_edit,
            "transform_visible_after_commit": transform_visible_after_commit,
            "temporary_cue_removed_by_escape": len(page.project.cues) == committed_count,
        }

        # D: live Transform snapshot and committed project/ASS use one coordinate.
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        moved = phase("D Transform live", lambda: page._position_overlay_moved(706, 812))
        live_project = page._ass_preview_snapshot(page.project)
        live_cue = next(item for item in live_project.cues if item.id == cue.id)
        live_style = next(item for item in live_project.styles if item.id == live_cue.style_id)
        committed = phase("D Transform commit", lambda: page._position_overlay_committed(706, 812))
        cue = page._cue_lookup[cue.id]
        style = next(item for item in page.project.styles if item.id == cue.style_id)
        result["phases"]["D"] = {
            "live_metrics": moved,
            "commit_metrics": committed,
            "live_position": [live_style.position_x, live_style.position_y],
            "project_position": [style.position_x, style.position_y],
            "controls_position": [page.style_position_x.value(), page.style_position_y.value()],
            "ass_has_position": r"\pos(706,812)" in compile_ass(page.project),
            "transform_top_level": page.position_overlay.isWindow(),
        }

        # E: replacing a modified style with a preset materializes the preset fully.
        page.project.style_recipes[cue.style_id] = style_recipe_for_prompt("赛博渐变 glitch").to_dict()
        game_index = page.style_preset.findData("game")
        page.style_preset.setCurrentIndex(game_index)
        preset_metrics = phase("E Preset replacement", lambda: page._preset_activated(game_index))
        cue = page._cue_lookup[cue.id]
        style = next(item for item in page.project.styles if item.id == cue.style_id)
        preset = BUILTIN_PRESETS["game"]
        result["phases"]["E"] = {
            "metrics": preset_metrics,
            "cue_style_id": cue.style_id,
            "effect_id": cue.effect_id,
            "recipe_inherited": cue.style_id in page.project.style_recipes,
            "matches": {
                "font": style.font_family == preset.font_family,
                "size": style.font_size == preset.font_size,
                "bold": style.bold == preset.bold,
                "outline": style.outline_width == preset.outline_width,
            },
        }

        # F: the real Windows font inventory is available in the popup model.
        page.style_font._load_full_font_list()
        installed_fonts = set(QFontDatabase.families())
        page.style_font.showPopup()
        pump(app, 80)
        combo_fonts = {page.style_font.itemText(i) for i in range(page.style_font.count())}
        font_shot = widget_screenshot(page.style_font.view().window(), "02-font-dropdown.png")
        page.style_font.hidePopup()
        result["phases"]["F"] = {
            "installed_count": len(installed_fonts),
            "combo_count": len(combo_fonts),
            "missing_count": len(installed_fonts - combo_fonts),
            "missing_sample": sorted(installed_fonts - combo_fonts)[:10],
            "screenshot": font_shot,
        }
        progress("phase F complete; rendering gradient")

        # G: render a yellow-to-cyan gradient through the trusted final compositor.
        recipe = style_recipe_for_prompt("黄色到青色渐变游戏字幕")
        recipe.engine = "remotion"
        recipe.colors["fill"] = FillSpec.linear([
            {"color": "#FFFFE45E", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]).to_dict()
        recipe.validate()
        gradient_project = copy.deepcopy(page.project)
        gradient_cue = gradient_project.cues[0]
        gradient_style = copy.deepcopy(next(item for item in gradient_project.styles if item.id == gradient_cue.style_id))
        gradient_style.id = "p67-gradient"
        gradient_style.primary_color = "#FFFFE45E"
        gradient_project.styles.append(gradient_style)
        gradient_project.style_recipes[gradient_style.id] = recipe.to_dict()
        gradient_cue.style_id = gradient_style.id
        snapshot = build_visual_cue_snapshot(gradient_project, gradient_cue.id, width=960, height=540, fps=30.0)
        gradient_started = time.perf_counter()
        _key, gradient_path, cache_hit = page._advanced_preview_cache.render_snapshot(
            snapshot, relative_ms=300, width=960, height=540, force=True,
        )
        gradient_elapsed = round((time.perf_counter() - gradient_started) * 1000.0, 1)
        gradient_target = OUTPUT / "03-gradient-yellow-cyan.png"
        shutil.copy2(gradient_path, gradient_target)
        visual = normalized_visual_snapshot(snapshot)
        result["phases"]["G"] = {
            "render_ms": gradient_elapsed,
            "cache_hit": cache_hit,
            "path": str(gradient_target),
            "renderer_colors": [item["color"] for item in visual["fill"]["stops"]],
            "route": "trusted-remotion-final-compositor",
            "exists": gradient_target.is_file() and gradient_target.stat().st_size > 0,
        }
        progress("gradient complete; rendering AI A/B/C")

        # H: A/B/C cards each receive rendered pixels and expose motion playback.
        page.project.cues[0].text = "示例字幕 Aa 123"
        page.cue_controller.model_changed()
        ai_requirement = "1930s 橡皮管胶片卡片"
        variants = tuple(visual_design_variants(ai_requirement))
        suggestion = AIDesignSuggestion(
            gradient_cue.id,
            variants[0].to_style_recipe(),
            rationale="三套可落地视觉方向",
            variants=variants,
            design_intent="1930s 橡皮管胶片卡片字幕",
            visual_changes=("复古字体", "胶片色彩", "多层描边", "橡皮管动效"),
            motion_reason="用橡皮管式弹跳和胶片抖动呈现年代感",
        )
        page._ai_ready(suggestion)
        ai_wait_ms = wait_until(
            app,
            lambda: len(page._ai_variant_preview_labels) == 3 and all(
                label.pixmap() is not None and not label.pixmap().isNull()
                for label in page._ai_variant_preview_labels
            ),
            180.0,
            "AI card renders",
        )
        page._play_ai_variant_motion(0, variants[0])
        pump(app, 100)
        animation_running = 0 in page._ai_variant_animations
        page._select_ai_variant(variants[0], suggestion)
        applied = page._apply_ai_preview()
        pump(app, 100)
        page._show_context_panel()
        page.context_drawer.setCurrentIndex(0)
        page.upper_splitter.setSizes([360, 760, 680])
        pump(app, 120)
        ai_cue = page._cue_lookup[gradient_cue.id]
        ai_style = next(item for item in page.project.styles if item.id == ai_cue.style_id)
        ai_frame_paths: list[str] = []
        for index, source in enumerate(page._ai_variant_preview_paths):
            target = OUTPUT / f"04-ai-card-{chr(65 + index)}.png"
            shutil.copy2(source, target)
            ai_frame_paths.append(str(target))
        result["phases"]["H"] = {
            "variant_count": len(page._ai_variant_preview_labels),
            "all_have_renderer_pixels": all(
                label.pixmap() is not None and not label.pixmap().isNull()
                for label in page._ai_variant_preview_labels
            ),
            "render_wait_ms": ai_wait_ms,
            "motion_animation_created": animation_running,
            "apply_result": applied,
            "renderer_frames": ai_frame_paths,
            "style_ui_sync": {
                "font": page.style_font.currentText() == ai_style.font_family,
                "size": page.style_font_size.value() == round(ai_style.font_size),
            },
            "screenshot": screenshot(page, "04-ai-abc-renderer-cards.png"),
        }
        progress("AI cards complete; running debounce and summary")

        # I: many rapid preview requests only enqueue; the latest request wins after debounce.
        queue_values: list[float] = []
        queue_children_before = child_process_start_count()
        monitor.set_action("I Preview debounce")
        for _index in range(30):
            started = time.perf_counter()
            page._queue_advanced_preview(recipe.to_dict())
            queue_values.append((time.perf_counter() - started) * 1000.0)
        timer_active_after_burst = page._advanced_preview_timer.isActive()
        pump(app, 260)
        result["phases"]["I"] = {
            "requests": len(queue_values),
            "queue_p95_ms": percentile(queue_values, 0.95),
            "queue_max_ms": round(max(queue_values), 3),
            "timer_active_after_burst": timer_active_after_burst,
            "debounce_ms": page._advanced_preview_timer.interval(),
            "child_starts_during_queue_and_flush": child_process_start_count() - queue_children_before,
            "state_generation": page._advanced_preview_state.generation,
        }
        pump(app, 2500)

        # J: consolidate process/window/latency facts.
        page._interaction_runtime_audit.flush(latency_path)
        interaction_records = list(page._interaction_runtime_audit.records)
        totals = [float(item["total_ms"]) for item in interaction_records]
        result["phases"]["J"] = {
            "interaction_records": len(interaction_records),
            "median_ms": round(statistics.median(totals), 3) if totals else 0.0,
            "p95_ms": percentile(totals, 0.95),
            "max_ms": round(max(totals), 3) if totals else 0.0,
            "over_50ms": sum(value >= 50.0 for value in totals),
            "over_100ms": sum(value >= 100.0 for value in totals),
            "child_spawns_in_ordinary_records": sum(int(item["child_process_starts"]) for item in interaction_records),
            "new_qt_top_levels_in_ordinary_records": [
                item
                for record in interaction_records
                if not record.get("expected_qt_popup", False)
                for item in record["new_qt_top_levels"]
            ],
            "expected_qt_popups": [
                item
                for record in interaction_records
                if record.get("expected_qt_popup", False)
                for item in record["new_qt_top_levels"]
            ],
            "latency_path": str(latency_path),
            "final_screenshot": screenshot(page, "05-final-headed.png"),
        }
        progress("phase J complete")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if monitor is not None:
            monitor.set_action("shutdown")
        try:
            page._interaction_runtime_audit.flush(latency_path)
        except Exception:
            pass
        page.close_page()
        page.close()
        page.deleteLater()
        pump(app, 100)
        if monitor is not None:
            monitor.stop()
        if qt_audit is not None:
            qt_audit.close()

    child_records: list[dict[str, object]] = []
    if child_log.is_file():
        for line in child_log.read_text(encoding="utf-8").splitlines():
            try:
                child_records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    monitor_windows = list(monitor.new_windows) if monitor is not None else []
    qt_records = list(qt_audit.records) if qt_audit is not None else []
    helper_windows = [
        item for item in monitor_windows
        if str(item.get("title") or "").strip() in {"2ByteASR", "2ByteASR P6.7 Runtime Acceptance"}
        and item.get("action") not in {"startup", "shutdown"}
        and "Popup" not in str(item.get("class") or "")
        and item.get("action") != "A Font popup"
    ]
    result["process_window_evidence"] = {
        "child_records": child_records,
        "observed_children": list(monitor.observed_children.values()) if monitor is not None else [],
        "new_visible_windows": monitor_windows,
        "titled_helper_windows": helper_windows,
        "qt_window_events": qt_records,
        "unexpected_transform_or_advanced_top_levels": [
            item for item in qt_records
            if item.get("class") in {"SubtitlePositionOverlay", "AdvancedLiveCanvas"}
        ],
    }
    event_path = OUTPUT / "window-events.jsonl"
    event_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in qt_records),
        encoding="utf-8",
    )
    result_path = OUTPUT / "runtime-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result_path)
    faulthandler.cancel_dump_traceback_later()
    STACK_LOG.flush()
    STACK_LOG.close()
    if result.get("error") or helper_windows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
