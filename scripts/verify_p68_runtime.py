"""Formal headed Windows acceptance for P6.8 Studio recovery work.

This is an automated harness, not a real-user click test.  It deliberately
uses the production MainWindow, real PySide6/Win32 widgets, the retained long
FLV project, mpv, libass, and the trusted Remotion compositor.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P68_OUTPUT",
    str(ROOT / "tmp" / "p68-runtime"),
)).resolve()
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"
PROJECT_COPY = OUTPUT / "p68-real-hour-copy.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.studio_ai import AIDesignSuggestion, style_recipe_for_prompt, visual_design_variants
from twobyteasr.studio_edit_sequence import HighlightCandidate
from twobyteasr.style_presets import StylePresetStore
from twobyteasr.style_recipe import FillSpec
from twobyteasr.window_audit import TopLevelWindowAudit, qt_top_level_widgets, win32_top_level_windows


def progress(message: str) -> None:
    print(f"[p68] {message}", flush=True)


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        time.sleep(0.005)


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return round((time.perf_counter() - started) * 1000.0, 1)
        time.sleep(0.01)
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")


def pause_video(app: QApplication, page) -> None:
    page.video.set_paused(True)
    wait_until(
        app,
        lambda: (
            page.video.playback_position_snapshot().paused is True
            and page.video.controller.observed_property("pause", None) is True
        ),
        5.0,
        "local and mpv actor pause",
    )
    page.ensure_active_subtitle_renderer(reason="p68_pause_settled")


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


class RuntimeMonitor:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.action = "startup"
        self.baseline_hwnds: set[int] = set()
        self.new_windows: list[dict[str, object]] = []
        self.children: dict[int, dict[str, object]] = {}
        self._seen: set[tuple[str, int]] = set()
        self.thread = threading.Thread(target=self._work, daemon=True, name="p68-runtime-monitor")

    def start(self) -> None:
        self.thread.start()

    def set_baseline(self) -> None:
        self.baseline_hwnds = {
            int(item["hwnd"])
            for item in win32_top_level_windows(pids=descendants())
            if item.get("visible")
        }

    def set_action(self, action: str) -> None:
        self.action = str(action)

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.0)

    def _work(self) -> None:
        while not self.stop_event.is_set():
            pids = descendants()
            for pid in pids - {os.getpid()}:
                try:
                    process = psutil.Process(pid)
                    self.children.setdefault(pid, {
                        "pid": pid,
                        "name": process.name(),
                        "exe": process.exe(),
                        "cmdline": process.cmdline(),
                        "parent_pid": process.ppid(),
                        "first_action": self.action,
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


def screenshot(widget, name: str) -> str:
    target = OUTPUT / name
    screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(int(widget.window().winId())) if screen else widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"failed to save screenshot: {target}")
    return str(target)


def widget_screenshot(widget, name: str) -> str:
    target = OUTPUT / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"failed to save widget screenshot: {target}")
    return str(target)


def mpv_screenshot(app: QApplication, page, name: str) -> str:
    target = OUTPUT / name
    if target.exists():
        target.unlink()
    page.video.controller.screenshot_to_file(target, mode="window")
    wait_until(app, target.is_file, 5.0, f"mpv screenshot {name}")
    return str(target)


def button_by_text(root, text: str) -> QPushButton:
    for button in root.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise LookupError(text)


def child_log_records() -> list[dict[str, object]]:
    path = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    rows: list[dict[str, object]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def main() -> int:
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    if child_log.exists():
        child_log.unlink()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P6.8 Formal Headed Acceptance")
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    ui.apply_application_theme(app)

    result: dict[str, object] = {
        "schema": "2byteasr.p68-runtime.v1",
        "evidence_class": "FORMAL HEADED VERIFIED",
        "real_user_click": False,
        "project": str(PROJECT_COPY),
        "pid": os.getpid(),
        "phases": {},
    }
    window = None
    page = None
    monitor = RuntimeMonitor()
    qt_audit = TopLevelWindowAudit(app, capture_win32=False)
    try:
        progress("constructing production MainWindow")
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        window.setWindowTitle("2ByteASR P6.8 Formal Headed Acceptance")
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 800)
        monitor.start()
        monitor.set_baseline()
        monitor.set_action("A project open")
        before_children = descendants()
        opened = time.perf_counter()
        window.open_studio_project(PROJECT_COPY, source="p68-headed")
        open_return_ms = round((time.perf_counter() - opened) * 1000.0, 1)
        page = window.studio_page
        mpv_wait_ms = wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            25.0,
            "mpv",
        )
        # P2 asks for the complete open-to-ready+5s observation window.
        pump(app, 5000)
        open_windows = [item for item in monitor.new_windows if item.get("action") == "A project open"]
        open_children = descendants() - before_children
        result["phases"]["A_project_open"] = {
            "open_return_ms": open_return_ms,
            "mpv_ready_ms": mpv_wait_ms,
            "studio_visible_after_return": page.isVisible(),
            "screenshot": screenshot(window, "01-project-open.png"),
            "new_visible_windows": open_windows,
            "new_child_pids": sorted(open_children),
            "qt_top_levels": qt_top_level_widgets(app),
        }

        progress("checking existing cue visibility and Transform mouse interaction")
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        page.timeline.set_playhead(cue.start_ms + 700)
        page._seek((cue.start_ms + 700) / 1000.0)
        pause_video(app, page)
        page.position_edit_button.setChecked(True)
        pump(app, 350)
        visibility = page.ensure_active_subtitle_renderer(reason="p68_existing_cue")
        overlay = page.position_overlay
        before_position = [overlay.position_x, overlay.position_y]
        before_font_size = float(overlay.font_size)
        center = overlay._subtitle_rect().center().toPoint()
        monitor.set_action("B Transform drag")
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
        QTest.mouseMove(overlay, center + QPoint(0, -300), 40)
        QTest.mouseRelease(
            overlay,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            center + QPoint(0, -300),
            40,
        )
        pump(app, 300)
        after_position = [overlay.position_x, overlay.position_y]
        handle = overlay._handle_centers(overlay._subtitle_rect())["br"].toPoint()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, handle)
        QTest.mouseMove(overlay, handle + QPoint(80, 60), 40)
        QTest.mouseRelease(
            overlay,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            handle + QPoint(80, 60),
            40,
        )
        pump(app, 300)
        transform_overlay_wait_ms = wait_until(
            app,
            lambda: page.video.TRANSFORM_OVERLAY_ID
            in page.video.active_compositor_overlay_ids(),
            5.0,
            "mpv Transform overlay",
        )
        result["phases"]["B_subtitle_transform"] = {
            "visibility_trace": page.subtitle_visibility_trace(
                reason="p68_transform_after_interaction"
            ),
            "transform_visible": overlay.isVisible(),
            "transform_is_window": overlay.isWindow(),
            "transform_native": overlay.testAttribute(Qt.WidgetAttribute.WA_NativeWindow),
            "handle_count": len(overlay._handle_centers(overlay._subtitle_rect())),
            "position_before": before_position,
            "position_after_300px_up_drag": after_position,
            "subtitle_position_changed": before_position != after_position,
            "font_size_before": before_font_size,
            "font_size_after_resize": float(overlay.font_size),
            "subtitle_size_changed": abs(float(overlay.font_size) - before_font_size) > 0.1,
            "compositor_wait_ms": transform_overlay_wait_ms,
            "mpv_composite_screenshot": mpv_screenshot(
                app, page, "02-transform-mpv-composite.png"
            ),
            "screenshot": screenshot(window, "02-transform-after-drag-resize.png"),
        }

        progress("applying yellow-to-cyan gradient in the real Studio canvas")
        recipe = style_recipe_for_prompt("黄色到青色渐变游戏字幕")
        recipe.engine = "remotion"
        recipe.colors["fill"] = FillSpec.linear([
            {"color": "#FFFFE45E", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]).to_dict()
        # Keep the acceptance sample legible enough to judge the fill itself;
        # a 52 px glyph under a thick black game outline mostly measures the
        # outline, not whether the yellow/cyan renderer chain reached Studio.
        recipe.typography["fontSize"] = 84
        recipe.outline = {"color": "#FF101317", "width": 1.5, "shadow": 0}
        recipe.motion = {"mode": "none"}
        recipe.visual_graph = {}
        recipe.validate()
        if not page._apply_style_recipe(cue.id, recipe):
            raise RuntimeError("gradient recipe did not apply")
        page.select_cue(cue.id)
        page.timeline.set_playhead(cue.start_ms + 700)
        page._seek((cue.start_ms + 700) / 1000.0)
        pause_video(app, page)
        page.position_edit_button.setChecked(True)
        window.activateWindow()
        page._queue_advanced_preview(recipe.to_dict(), force=True, delay_ms=0)
        gradient_wait_ms = wait_until(
            app,
            lambda: (
                not getattr(page.advanced_cue_overlay, "_source").isNull()
                and getattr(page.advanced_cue_overlay, "_snapshot", None) is not None
            ),
            180.0,
            "Studio gradient canvas",
        )
        pause_video(app, page)
        page.position_edit_button.setChecked(True)
        page.ensure_active_subtitle_renderer(reason="p68_gradient_ready")
        pump(app, 300)
        gradient_compositor_wait_ms = wait_until(
            app,
            lambda: {
                page.video.ADVANCED_OVERLAY_ID,
                page.video.TRANSFORM_OVERLAY_ID,
            }.issubset(set(page.video.active_compositor_overlay_ids())),
            5.0,
            "mpv advanced + Transform overlays",
        )
        gradient_frame = OUTPUT / "03-gradient-frame.png"
        page.advanced_cue_overlay._source.save(str(gradient_frame), "PNG")
        gradient_trace = page.subtitle_visibility_trace(reason="p68_gradient_acceptance")
        gradient_with_transform = mpv_screenshot(
            app, page, "03-gradient-mpv-composite.png"
        )
        page.position_edit_button.setChecked(False)
        page.ensure_active_subtitle_renderer(reason="p68_gradient_clean_capture")
        wait_until(
            app,
            lambda: page.video.TRANSFORM_OVERLAY_ID
            not in page.video.active_compositor_overlay_ids(),
            5.0,
            "Transform overlay removal",
        )
        gradient_clean = mpv_screenshot(app, page, "03-gradient-mpv-clean.png")
        page.position_edit_button.setChecked(True)
        page.ensure_active_subtitle_renderer(reason="p68_gradient_restore_transform")
        result["phases"]["C_gradient_studio"] = {
            "wait_ms": gradient_wait_ms,
            "compositor_wait_ms": gradient_compositor_wait_ms,
            "frame": str(gradient_frame),
            "frame_size": [
                page.advanced_cue_overlay._source.width(),
                page.advanced_cue_overlay._source.height(),
            ],
            "canvas_visible": page.advanced_cue_overlay.isVisible(),
            "canvas_is_window": page.advanced_cue_overlay.isWindow(),
            "canvas_mouse_transparent": page.advanced_cue_overlay.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            ),
            "transform_above_canvas": page.position_overlay.isVisible(),
            "visibility_trace": gradient_trace,
            "mpv_composite_screenshot": gradient_with_transform,
            "mpv_clean_screenshot": gradient_clean,
            "screenshot": screenshot(window, "03-gradient-in-studio.png"),
        }

        progress("checking Clip Assistant stages")
        page._show_context_panel()
        clip_index = next(
            index for index in range(page.context_drawer.count())
            if page.context_drawer.tabText(index) == "剪辑助手"
        )
        page.context_drawer.setCurrentIndex(clip_index)
        page.highlight_panel.reload_candidates([])
        pump(app, 150)
        settings_stage = page.highlight_panel.active_stage()
        settings_shot = screenshot(window, "04-clip-settings.png")
        sample = HighlightCandidate(
            "p68-highlight",
            "搞笑反应高峰",
            4_855_000,
            4_945_000,
            score=0.96,
            grade="强烈推荐",
            hook="主播突然发现关键机制，弹幕从疑惑转为集中爆发。",
            reason="从误判铺垫到反转 payoff 完整，前后语义边界自然。",
            signal_in_ms=4_885_000,
            signal_out_ms=4_903_000,
            context_in_ms=4_855_000,
            context_out_ms=4_945_000,
        )
        page.highlight_panel.reload_candidates([sample])
        pump(app, 180)
        result["phases"]["D_clip_assistant"] = {
            "empty_stage": settings_stage,
            "candidate_stage": page.highlight_panel.active_stage(),
            "candidate_count": page.highlight_panel.results.count(),
            "settings_button_cursor": page.highlight_panel.settings_tab.cursor().shape().value,
            "candidate_button_cursor": page.highlight_panel.candidates_tab.cursor().shape().value,
            "settings_screenshot": settings_shot,
            "candidates_screenshot": screenshot(window, "05-clip-candidates.png"),
        }

        progress("checking themed Studio recognition sheet")
        page._open_recognition_sheet()
        pump(app, 250)
        controls = page._recognition_controls
        result["phases"]["E_recognition_sheet"] = {
            "modal_visible": window._modal_host.isVisible(),
            "sheet_object": page._recognition_sheet.objectName(),
            "analysis": controls["analysis"].text(),
            "final": controls["final"].text(),
            "plans": [controls["plan"].itemText(i) for i in range(controls["plan"].count())],
            "primary_models": [controls["primary"].itemText(i) for i in range(controls["primary"].count())],
            "timeline_models": [controls["timeline"].itemText(i) for i in range(controls["timeline"].count())],
            "review_models": [controls["review"].itemText(i) for i in range(controls["review"].count())],
            "glossary_count": len(controls["glossaries"]),
            "screenshot": widget_screenshot(
                window._modal_host.card, "06-recognition-sheet.png"
            ),
        }
        window._modal_host.hide_content()
        wait_until(app, lambda: not window._modal_host.isVisible(), 2.0, "recognition sheet close")
        recognition_closed_before_ai = not window._modal_host.isVisible()

        progress("checking real renderer AI cards and entrance/hold/exit frames")
        page._show_context_panel()
        page.context_drawer.setCurrentIndex(0)
        variants = tuple(visual_design_variants("1930s 橡皮管胶片动画风"))
        suggestion = AIDesignSuggestion(
            cue.id,
            variants[0].to_style_recipe(),
            rationale="三套真实渲染视觉方向",
            variants=variants,
            design_intent="1930s 橡皮管胶片动画风",
            visual_changes=("胶片卡片", "颗粒纹理", "不规则描边", "橡皮管动效"),
            motion_reason="squash stretch 与 film gate 共同建立年代感",
        )
        page._ai_ready(suggestion)
        ai_wait_ms = wait_until(
            app,
            lambda: len(page._ai_variant_preview_labels) == 3 and all(
                label.pixmap() is not None and not label.pixmap().isNull()
                for label in page._ai_variant_preview_labels
            ),
            180.0,
            "AI renderer cards",
        )
        page._play_ai_variant_motion(0, variants[0])
        motion_wait_ms = wait_until(
            app,
            lambda: 0 in page._ai_variant_motion_timers,
            180.0,
            "AI motion frames",
        )
        pump(app, 250)
        motion_shot = widget_screenshot(page.context_drawer, "07-ai-abc-motion.png")
        motion_completed_ms = wait_until(
            app,
            lambda: 0 not in page._ai_variant_motion_timers,
            5.0,
            "AI motion completion",
        )
        snapshots = [page._ai_variant_snapshot(item, i) for i, item in enumerate(variants)]
        result["phases"]["F_ai_design"] = {
            "variant_count": len(variants),
            "renderer_wait_ms": ai_wait_ms,
            "motion_wait_ms": motion_wait_ms,
            "motion_completed_ms": motion_completed_ms,
            "recognition_closed_before_ai": recognition_closed_before_ai,
            "all_have_renderer_pixels": all(
                label.pixmap() is not None and not label.pixmap().isNull()
                for label in page._ai_variant_preview_labels
            ),
            "preview_min_heights": [label.minimumHeight() for label in page._ai_variant_preview_labels],
            "snapshot_sizes": [list(item.resolution) for item in snapshots if item is not None],
            "sample_texts": [item.text for item in snapshots if item is not None],
            "sample_positions": [
                [item.position_x, item.position_y, item.font_size]
                for item in snapshots if item is not None
            ],
            "background_types": [item.background.get("type") for item in variants],
            "motion": [item.motion.to_dict() for item in variants],
            "screenshot": motion_shot,
        }

        progress("checking Style Preset Manager flat-library row selection")
        store = StylePresetStore()
        ai_style_a = copy.deepcopy(page.project.styles[0])
        ai_style_a.id, ai_style_a.name = "ai-p68-a", "AI P6.8 A"
        ai_style_b = copy.deepcopy(page.project.styles[0])
        ai_style_b.id, ai_style_b.name = "ai-p68-b", "AI P6.8 B"
        store.upsert(ai_style_a, recipe.to_dict(), source="ai")
        store.upsert(ai_style_b, recipe.to_dict(), source="ai")
        page._open_style_preset_manager()
        pump(app, 220)
        tree = page._style_preset_manager_tree
        selected_ids: list[str] = []
        tree.clearSelection()
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            style_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if style_id in {"ai-p68-a", "ai-p68-b"}:
                item.setSelected(True)
                selected_ids.append(style_id)
        manager_shot = widget_screenshot(window._modal_host.card, "08-style-preset-manager.png")
        button_by_text(page._style_preset_manager, "删除所选").click()
        pump(app, 180)
        remaining = StylePresetStore().load_user()
        result["phases"]["G_preset_manager"] = {
            "flat_library": tree.rootIsDecorated() is False,
            "search_placeholder": page._style_preset_manager_search.placeholderText(),
            "filters": sorted(page._style_preset_manager_filters),
            "selected_ids": selected_ids,
            "bulk_deleted": all(style_id not in remaining for style_id in selected_ids),
            "screenshot": manager_shot,
        }
        window._modal_host.hide_content()

        progress("checking P6.7 Razor/Undo regression without new helper window")
        page.timeline.set_playhead(120_000)
        monitor.set_action("H Razor Undo")
        before_razor = page.timeline.playhead_ms
        razor_result = page._razor_video_at(120_000)
        page._undo_interactive()
        pump(app, 250)
        result["phases"]["H_p67_regression"] = {
            "razor_result": razor_result,
            "playhead_before": before_razor,
            "playhead_after": page.timeline.playhead_ms,
            "new_visible_windows": [
                item for item in monitor.new_windows if item.get("action") == "H Razor Undo"
            ],
        }
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        monitor.set_action("shutdown")
        if window is not None:
            original_dirty_prompt = ProjectDirtyGuard._prompt
            ProjectDirtyGuard._prompt = lambda _guard, _action: DirtyGuardChoice.DISCARD
            result["shutdown_dirty_disposition"] = DirtyGuardChoice.DISCARD.value
            try:
                window.close()
            finally:
                ProjectDirtyGuard._prompt = original_dirty_prompt
            if page is not None:
                try:
                    result["shutdown_cleanup_ms"] = wait_until(
                        app,
                        lambda: bool(page._close_complete),
                        12.0,
                        "Studio asynchronous cleanup",
                    )
                    result["shutdown_close_profile"] = dict(page.last_close_profile)
                except Exception as close_exc:
                    result.setdefault(
                        "error", f"shutdown: {type(close_exc).__name__}: {close_exc}"
                    )
            pump(app, 150)
            window.deleteLater()
        monitor.stop()
        qt_audit.close()

    records = child_log_records()
    result["process_window_evidence"] = {
        "child_records": records,
        "observed_children": list(monitor.children.values()),
        "new_visible_windows": monitor.new_windows,
        "qt_window_events": qt_audit.records,
        "open_waveform_ffmpeg_starts": sum(
            1 for item in records
            if item.get("phase") == "start"
            if "ffmpeg" in " ".join(str(part) for part in item.get("cmd", item.get("command", []))).lower()
            and "waveform" in json.dumps(item, ensure_ascii=False).lower()
        ),
        "open_thumbnail_starts": sum(
            1 for item in records
            if item.get("phase") == "start"
            if "thumbnail" in json.dumps(item, ensure_ascii=False).lower()
            or "project-cover" in json.dumps(item, ensure_ascii=False).lower()
        ),
    }
    result_path = OUTPUT / "runtime-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result_path)
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
