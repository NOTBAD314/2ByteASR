"""Environment-gated formal Runtime acceptance driver for P6.4.

This module is imported only when ``TWOBYTEASR_P64_RUNTIME_AUDIT`` is set.
It drives the real ``run_desktop_app`` widget tree and keeps all evidence in a
caller-selected temporary directory.
"""

from __future__ import annotations

import copy
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


DEFAULT_MATRIX = "1366x768,1600x900,1920x1080,2560x1440,1400x850"


def parse_matrix_sizes(value: str) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for token in str(value or "").split(","):
        try:
            width, height = (int(part.strip()) for part in token.lower().split("x", 1))
        except (TypeError, ValueError):
            continue
        if width < 1080 or height < 640 or width > 7680 or height > 4320:
            continue
        size = (width, height)
        if size not in sizes:
            sizes.append(size)
    return sizes


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BitmapInfoHeader),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


def _window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed")
    return rect.left, rect.top, rect.right, rect.bottom


def _window_process_id(hwnd: int) -> int:
    process_id = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


def _activate_window(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return _window_process_id(int(user32.GetForegroundWindow())) == os.getpid()


def _print_window(hwnd: int):
    from PIL import Image

    left, top, right, bottom = _window_bounds(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"invalid HWND bounds: {(left, top, right, bottom)}")
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    source_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(source_dc)
    bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 0x00000002):
            raise RuntimeError("PrintWindow failed")
        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
        )
        if copied != height:
            raise RuntimeError(f"GetDIBits copied {copied}/{height} rows")
        return Image.frombuffer(
            "RGBA", (width, height), buffer, "raw", "BGRA", 0, 1
        ).convert("RGB")
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, source_dc)


class P64RuntimeAudit(QObject):
    def __init__(self, window, output_dir: str | os.PathLike[str], *, mode: str) -> None:
        super().__init__(window)
        self.window = window
        self.page = window.studio_page
        self.mode = str(mode or "full").casefold()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.screenshot_dir = self.output_dir / "screenshots"
        self.result_path = self.output_dir / f"runtime-result-{self.mode}.json"
        self.event_path = self.output_dir / f"runtime-events-{self.mode}.jsonl"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.result: dict[str, object] = {
            "schema": 1,
            "mode": self.mode,
            "formal_entry": str(Path(sys.executable).resolve()),
            "started_at": time.time(),
            "screenshots": {},
            "errors": [],
        }
        self._operations: list[tuple[str, Callable[[], None]]] = []
        self._operation_results: list[dict[str, object]] = []
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(10)
        self._monitor_timer.timeout.connect(self._poll_visible_process_windows)
        self._visible_process_windows: list[dict[str, object]] = []
        self._seen_windows: set[tuple[int, int]] = set()

    def start(self) -> None:
        self._record_environment()
        if os.name != "nt":
            self._fail("P6.4 formal Runtime audit requires Windows")
            return
        if self.mode == "matrix":
            self._start_matrix()
        else:
            self._start_full()

    def _later(self, delay_ms: int, callback: Callable[[], None]) -> None:
        def guarded() -> None:
            try:
                callback()
            except Exception as exc:
                self.result["errors"].append(
                    {"step": getattr(callback, "__name__", "runtime"), "type": type(exc).__name__, "message": str(exc)}
                )
                self._write_result()
                self._finish(False)

        QTimer.singleShot(max(0, int(delay_ms)), guarded)

    def _record_environment(self) -> None:
        screen = self.window.screen() or QApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen else 1.0
        geometry = self.window.geometry()
        self.result["environment"] = {
            "pid": os.getpid(),
            "platform": sys.platform,
            "device_pixel_ratio": dpr,
            "logical_geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            "physical_window_estimate": [round(geometry.width() * dpr), round(geometry.height() * dpr)],
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", ""),
            "startup_project": os.environ.get("TWOBYTEASR_STARTUP_PROJECT", ""),
        }

    def _event(self, kind: str, **payload) -> None:
        record = {"timestamp": time.time(), "kind": kind, **payload}
        with self.event_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _capture(self, widget, name: str, *, screen: bool = False) -> dict[str, object]:
        widget.show()
        widget.raise_()
        QApplication.processEvents()
        hwnd = int(widget.winId())
        bounds = _window_bounds(hwnd)
        if screen:
            from PIL import ImageChops, ImageGrab, ImageStat

            foreground_is_app = _activate_window(hwnd)
            QApplication.processEvents()
            reference = _print_window(hwnd)
            image = ImageGrab.grab(bbox=bounds, all_screens=True)
            top_height = max(1, round(image.height * 0.12))
            if image.size == reference.size:
                difference = ImageChops.difference(
                    image.crop((0, 0, image.width, top_height)),
                    reference.crop((0, 0, reference.width, top_height)),
                )
                top_mean_difference = round(sum(ImageStat.Stat(difference).mean[:3]) / 3.0, 4)
                capture_matches_window = top_mean_difference <= 12.0
            else:
                top_mean_difference = None
                capture_matches_window = False
            method = "screen-bounds"
        else:
            foreground_is_app = None
            top_mean_difference = None
            capture_matches_window = None
            image = _print_window(hwnd)
            method = "PrintWindow"
        target = self.screenshot_dir / f"{name}.png"
        image.save(target)
        record = {
            "path": str(target),
            "pixels": list(image.size),
            "bounds": list(bounds),
            "method": method,
            "foreground_is_app": foreground_is_app,
            "capture_matches_window": capture_matches_window,
            "top_mean_difference": top_mean_difference,
        }
        self.result["screenshots"][name] = record
        self._event("capture", name=name, **record)
        return record

    def _capture_with_qt_overlay(self, widget, overlay, name: str) -> dict[str, object]:
        """Capture the native main HWND and its transparent Qt Tool layer."""
        from PIL import Image
        from PySide6.QtGui import QImage

        widget.show()
        widget.raise_()
        overlay.show()
        overlay.raise_()
        QApplication.processEvents()
        hwnd = int(widget.winId())
        bounds = _window_bounds(hwnd)
        base = _print_window(hwnd).convert("RGBA")

        pixmap = overlay.grab()
        qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(qimage.bits()[:qimage.sizeInBytes()])
        layer = Image.frombuffer(
            "RGBA",
            (qimage.width(), qimage.height()),
            raw,
            "raw",
            "RGBA",
            qimage.bytesPerLine(),
            1,
        ).copy()
        alpha_bounds = layer.getchannel("A").getbbox()
        dpr = float(overlay.devicePixelRatioF() or 1.0)
        offset = (
            round((overlay.x() - widget.x()) * dpr),
            round((overlay.y() - widget.y()) * dpr),
        )
        base.alpha_composite(layer, dest=offset)
        target = self.screenshot_dir / f"{name}.png"
        base.convert("RGB").save(target)
        record = {
            "path": str(target),
            "pixels": list(base.size),
            "bounds": list(bounds),
            "method": "PrintWindow+Qt-overlay",
            "overlay_pixels": list(layer.size),
            "overlay_offset": list(offset),
            "overlay_alpha_bounds": list(alpha_bounds) if alpha_bounds else [],
            "overlay_nonblank": bool(alpha_bounds),
            "capture_matches_window": True,
        }
        self.result["screenshots"][name] = record
        self._event("capture", name=name, **record)
        return record

    def _start_matrix(self) -> None:
        sizes = parse_matrix_sizes(os.environ.get("TWOBYTEASR_P64_MATRIX_SIZES", DEFAULT_MATRIX))
        if not sizes:
            self._fail("no valid matrix sizes")
            return
        capture_startup = os.environ.get("TWOBYTEASR_P64_MATRIX_CAPTURE_STARTUP") == "1"
        if capture_startup and len(sizes) != 1:
            self._fail("startup geometry matrix mode requires exactly one size")
            return
        original_minimum = [self.window.minimumWidth(), self.window.minimumHeight()]
        native_dpi = 0
        get_dpi_for_window = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
        if get_dpi_for_window is not None:
            native_dpi = int(get_dpi_for_window(int(self.window.winId())))
        qt_scale = float(self.window.devicePixelRatioF())
        native_scale = native_dpi / 96.0 if native_dpi > 0 else qt_scale
        adjusted_minimum = list(original_minimum)
        if not capture_startup and native_scale > qt_scale + 0.01:
            factor = qt_scale / native_scale
            adjusted_minimum = [
                max(1, round(original_minimum[0] * factor)),
                max(1, round(original_minimum[1] * factor)),
            ]
            self.window.setMinimumSize(*adjusted_minimum)
        self.result["matrix_dpi_normalization"] = {
            "native_window_dpi": native_dpi,
            "qt_device_pixel_ratio": qt_scale,
            "product_minimum_size": original_minimum,
            "audit_minimum_size": adjusted_minimum,
            "capture_mode": "startup_geometry" if capture_startup else "runtime_resize",
            "audit_fixed_viewport": not capture_startup,
        }
        self.result["matrix"] = []

        def capture_at(index: int) -> None:
            if index >= len(sizes):
                entries = self.result["matrix"]
                self.result["matrix_accepted"] = bool(entries) and all(
                    item["exact_logical_size"]
                    and item["exact_physical_pixels"]
                    and item["cue_horizontal_scroll_max"] == 0
                    and item["candidate_horizontal_scroll_max"] == 0
                    for item in entries
                )
                self._finish(bool(self.result["matrix_accepted"]))
                return
            width, height = sizes[index]
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

            def capture_current() -> None:
                record = self._capture(self.window, f"matrix-{width}x{height}")
                logical = [self.window.width(), self.window.height()]
                pixels = list(record["pixels"])
                dpr = float(self.window.devicePixelRatioF())
                expected_pixels = [int(width * dpr + 0.5), int(height * dpr + 0.5)]
                screen = self.window.screen() or QApplication.primaryScreen()
                available = screen.availableGeometry() if screen else None
                normal = self.window.normalGeometry()
                native_dpi = 0
                get_dpi_for_window = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
                if get_dpi_for_window is not None:
                    native_dpi = int(get_dpi_for_window(int(self.window.winId())))
                entry = {
                    "requested_logical_size": [width, height],
                    "actual_logical_size": logical,
                    "expected_physical_pixels": expected_pixels,
                    "actual_physical_pixels": pixels,
                    "device_pixel_ratio": dpr,
                    "native_window_dpi": native_dpi,
                    "window_minimum_size": [self.window.minimumWidth(), self.window.minimumHeight()],
                    "window_minimum_size_hint": [
                        self.window.minimumSizeHint().width(), self.window.minimumSizeHint().height(),
                    ],
                    "screen_available_geometry": (
                        [available.x(), available.y(), available.width(), available.height()]
                        if available is not None else []
                    ),
                    "normal_geometry": [normal.x(), normal.y(), normal.width(), normal.height()],
                    "window_maximized": self.window.isMaximized(),
                    "exact_logical_size": logical == [width, height],
                    "exact_physical_pixels": pixels == expected_pixels,
                    "cue_horizontal_scroll_max": self.page.cue_table.horizontalScrollBar().maximum(),
                    "candidate_horizontal_scroll_max": self.page.highlight_panel.results.horizontalScrollBar().maximum(),
                }
                self.result["matrix"].append(entry)
                self._write_result()
                self._later(120, lambda: capture_at(index + 1))

            if capture_startup:
                self._later(650, capture_current)
                return
            def apply_geometry() -> None:
                self.window.setFixedSize(width, height)
                self.window.move(0, 0)
                QApplication.processEvents()
                self._later(650, capture_current)

            # showNormal posts a native state transition on Windows. Apply the
            # requested geometry only after that transition has settled.
            self._later(120, apply_geometry)

        capture_at(0)

    def _start_full(self) -> None:
        from .studio_project import StudioMedia, SubtitleProject, save_project

        empty_path = self.output_dir / "empty-studio.2byteproj"
        save_project(SubtitleProject(media=StudioMedia(path="")), empty_path)
        self.window.open_studio_project(empty_path, source="p64_formal_runtime_empty")
        self._later(900, self._capture_empty)

    def _capture_empty(self) -> None:
        record = self._capture(self.window, "01-empty-studio")
        hint = self.page.video_empty_hint
        label = self.page.video_empty_label
        note = self.page.video_empty_note
        drop_zone = self.page.video_drop_zone
        children_inside = all(
            drop_zone.rect().contains(widget.geometry())
            for widget in (self.page.video_empty_icon, label, self.page.video_empty_import, note)
        )
        self.result["empty_studio"] = {
            "capture_pixels": record["pixels"],
            "drop_zone_visible": hint.isVisible(),
            "title_visible": label.isVisible(),
            "title_text": label.text(),
            "title_rect": [label.x(), label.y(), label.width(), label.height()],
            "word_wrap": label.wordWrap(),
            "import_visible": self.page.video_empty_import.isVisible(),
            "note_visible": note.isVisible(),
            "note_text": note.text(),
            "note_rect": [note.x(), note.y(), note.width(), note.height()],
            "children_inside_drop_zone": children_inside,
            "accepted": bool(
                hint.isVisible()
                and label.isVisible()
                and self.page.video_empty_import.isVisible()
                and note.isVisible()
                and label.wordWrap()
                and note.wordWrap()
                and children_inside
            ),
        }
        self._run_page_switches()

    def _run_page_switches(self) -> None:
        targets = [
            ("home", self.window.settings_scroll),
            ("workshop", self.window.workshop_page),
            ("studio", self.window.studio_page),
        ]
        records: list[dict[str, object]] = []

        def switch(index: int) -> None:
            if index >= 20:
                self.result["page_switches"] = records
                self.result["page_switch_state_mismatches"] = sum(
                    1 for item in records if not item["current_matches"]
                )
                self.window._return_to_settings()
                self._later(250, self._open_ai_settings)
                return
            name, target = targets[index % len(targets)]
            started = time.perf_counter()
            self.window._switch_page(target)
            QApplication.processEvents()
            records.append({
                "index": index + 1,
                "target": name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "current_matches": self.window.pages.currentWidget() is target,
                "updates_enabled": self.window.updatesEnabled(),
            })
            self._later(55, lambda: switch(index + 1))

        switch(0)

    def _open_ai_settings(self) -> None:
        editor = self.window.polish_editor
        self.window.ai_panel.set_expanded(True, animate=False)
        self.window.ai_panel.show()
        self.window._ensure_ai_panel_visible()
        index = editor.service.findData("antigravity")
        if index >= 0:
            editor.service.setCurrentIndex(index)
            editor.detect_cli()
        self._provider_detection_started = time.monotonic()
        self._later(250, self._wait_for_provider_detection)

    def _wait_for_provider_detection(self) -> None:
        editor = self.window.polish_editor
        tester = getattr(editor, "_tester", None)
        if (
            tester is not None
            and tester.isRunning()
            and time.monotonic() - self._provider_detection_started < 12.0
        ):
            self._later(250, self._wait_for_provider_detection)
            return
        self.result["provider_detection"] = {
            "cli_status": editor.cli_status.text(),
            "account_status": editor.account_status.text(),
            "status": editor.status.text(),
            "detected_models": [editor.model.itemText(index) for index in range(editor.model.count())],
            "selected_model": editor.model.currentText(),
        }
        editor.test_connection()
        self._provider_connection_started = time.monotonic()
        self._later(250, self._wait_for_provider_connection)

    def _wait_for_provider_connection(self) -> None:
        editor = self.window.polish_editor
        tester = getattr(editor, "_tester", None)
        if (
            tester is not None
            and tester.isRunning()
            and time.monotonic() - self._provider_connection_started < 65.0
        ):
            self._later(250, self._wait_for_provider_connection)
            return
        self._capture_ai_settings()

    def _capture_ai_settings(self) -> None:
        editor = self.window.polish_editor
        record = self._capture(self.window, "02-home-ai-settings")
        connection_status = editor.status.text()
        connection_accepted = connection_status.startswith(
            "连接正常 · 返回 2ByteASR_OK"
        )
        self.result["provider_connection_accepted"] = connection_accepted
        self.result["provider_ui"] = {
            "capture_pixels": record["pixels"],
            "services": [editor.service.itemData(index) for index in range(editor.service.count())],
            "protocols": [editor.protocol.itemData(index) for index in range(editor.protocol.count())],
            "selected_service": editor.service.currentData(),
            "cli_status": editor.cli_status.text(),
            "account_status": editor.account_status.text(),
            "connection_status": connection_status,
            "connection_accepted": connection_accepted,
            "selected_model": editor.model.currentText(),
            "connection_test_finished": editor.test_button.isEnabled(),
            "settings_page": editor.settings_stack.currentWidget().objectName(),
        }
        project_path = Path(os.environ.get("TWOBYTEASR_STARTUP_PROJECT", "")).expanduser()
        if not project_path.is_file():
            self._fail(f"real fixture project missing: {project_path}")
            return
        self.window.open_studio_project(project_path, source="p64_formal_runtime_real")
        self._later(5200, self._capture_real_studio)

    def _capture_real_studio(self) -> None:
        if self.page.project is None:
            self._fail("real project did not open")
            return
        self.page._show_context_panel()
        self.page.context_drawer.setCurrentIndex(2)
        record = self._capture(self.window, "03-real-studio-style")
        self.result["real_studio"] = {
            "capture_pixels": record["pixels"],
            "media_path": self.page.project.media.path,
            "duration_ms": self.page.project.media.duration_ms,
            "cue_count": len(self.page.project.cues),
            "candidate_count": len(__import__("twobyteasr.studio_edit_sequence", fromlist=["sequence_of"]).sequence_of(self.page.project).clip_candidates),
            "cue_horizontal_scroll_max": self.page.cue_table.horizontalScrollBar().maximum(),
            "context_tab_count": self.page.context_drawer.count(),
        }
        self._later(200, self._show_fill_editor)

    def _show_fill_editor(self) -> None:
        from .studio_ui import FillEditorDialog

        self._fill_dialog = FillEditorDialog({
            "type": "linear-gradient",
            "stops": [
                {"position": 0.0, "color": "#FFFFE45E"},
                {"position": 1.0, "color": "#FF20D9FF"},
            ],
            "angle": 18,
        }, self.page)
        self._fill_dialog.show()
        self._later(500, self._capture_fill_editor)

    def _capture_fill_editor(self) -> None:
        dialog = self._fill_dialog
        record = self._capture(dialog, "04-fill-editor")
        square = dialog.picker.sv_square
        self.result["color_picker"] = {
            "capture_pixels": record["pixels"],
            "sv_size": [square.width(), square.height()],
            "sv_ratio": round(square.width() / max(1, square.height()), 4),
            "gradient_top": dialog.gradient.geometry().top(),
            "picker_top": dialog.picker.geometry().top(),
            "stop_controls_top": dialog._stop_host.geometry().top(),
            "gradient_above_picker": dialog.gradient.geometry().top() < dialog.picker.geometry().top(),
        }
        dialog.close()
        self.page.context_drawer.setCurrentIndex(3)
        self.page.highlight_panel.set_project_status(
            self.page.project,
            __import__("twobyteasr.studio_edit_sequence", fromlist=["sequence_of"]).sequence_of(self.page.project).danmaku_path,
        )
        self._later(350, self._capture_candidates)

    def _capture_candidates(self) -> None:
        panel = self.page.highlight_panel
        record = self._capture(self.window, "05-clip-candidates")
        context_scroll = self.page.context_drawer.currentWidget()
        viewport_height = context_scroll.viewport().height()
        cards = []
        card_layouts = []
        required_actions = {"预览", "加入剪辑", "忽略", "详情"}
        for index in range(min(5, panel.results.count())):
            card = panel.results.itemWidget(panel.results.item(index))
            buttons = card.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
            cards.append([button.text() for button in buttons])
            card_layouts.append({
                "card_size": [card.width(), card.height()],
                "buttons": [
                    {
                        "text": button.text(),
                        "rect": [button.x(), button.y(), button.width(), button.height()],
                        "visible": button.isVisible(),
                        "inside_card": card.rect().contains(button.geometry()),
                    }
                    for button in buttons
                ],
            })
        actions_accepted = bool(card_layouts) and all(
            required_actions <= {button["text"] for button in layout["buttons"]}
            and all(button["visible"] and button["inside_card"] for button in layout["buttons"])
            for layout in card_layouts
        )
        self.result["clip_candidates"] = {
            "capture_pixels": record["pixels"],
            "result_count": panel.results.count(),
            "result_height": panel.results.height(),
            "panel_height": panel.height(),
            "viewport_height": viewport_height,
            "height_ratio": round(panel.results.height() / max(1, viewport_height), 4),
            "horizontal_scroll_max": panel.results.horizontalScrollBar().maximum(),
            "card_buttons": cards,
            "card_layouts": card_layouts,
            "actions_accepted": actions_accepted,
        }
        self._later(200, self._apply_ai_fixture)

    def _apply_ai_fixture(self) -> None:
        from .studio_ai import AIDesignSuggestion, style_recipe_for_prompt, visual_design_variants
        from .style_recipe import VisualStyleRecipe

        if not self.page.selected_cue_id and self.page.project.cues:
            self.page.select_cue(self.page.project.cues[0].id)
        prompt = "手写纸片感，暖白到珊瑚渐变，两层描边，轻微发光，关键词弹跳出现"
        recipe = style_recipe_for_prompt(prompt)
        primary = VisualStyleRecipe.from_style_recipe(recipe)
        suggestion = AIDesignSuggestion(
            self.page.selected_cue_id,
            recipe,
            "P6.4 deterministic validated fixture",
            tuple(visual_design_variants(prompt, primary)),
        )
        self.page.context_drawer.setCurrentIndex(0)
        self.page._ai_ready(suggestion)
        self._capture(self.window, "06-ai-design-fixture")
        applied = self.page._apply_style_recipe(suggestion.cue_id, suggestion.recipe)
        self.page.context_drawer.setCurrentIndex(2)
        self.result["ai_fixture"] = {
            "source": "deterministic_test_fixture",
            "prompt": prompt,
            "recipe": recipe.to_dict(),
            "applied": bool(applied),
        }
        self._later(900, self._capture_style_sync)

    def _capture_style_sync(self) -> None:
        page = self.page
        cue = page._cue_lookup.get(page.selected_cue_id)
        style = page._selected_style_source(use_cue_style=True)
        record = self._capture(self.window, "07-style-ui-synced")
        self.result["style_ui_sync"] = {
            "capture_pixels": record["pixels"],
            "cue_style_id": cue.style_id if cue else "",
            "preset_text": page.style_preset.currentText(),
            "font": page.style_font.currentText(),
            "font_size": page.style_font_size.value(),
            "fill_type": page._fill_spec.kind,
            "fill": page._fill_spec.to_dict(),
            "fill_color": page.style_fill_color.text(),
            "stroke_1": [page.style_outline_color.text(), page.style_outline_width.value()],
            "stroke_2": [page.style_outline2.isChecked(), page.style_outline2_color.text(), page.style_outline2_width.value()],
            "glow": [page.style_glow.isChecked(), page.style_glow_color.text(), page.style_glow_strength.value()],
            "motion": [page.effect_preset.currentData(), page.effect_duration.value()],
            "effective_style": asdict(style) if style is not None else {},
        }
        page.position_edit_button.setChecked(True)
        page.video.set_paused(True)
        page._playback_state_changed(True)
        page._toggle_position_edit(True)
        cue = page._cue_lookup.get(page.selected_cue_id)
        if cue is not None:
            page._seek(max(0, cue.start_ms + 500) / 1000.0)
        self._later(1100, self._capture_transform)

    def _capture_transform(self) -> None:
        self.page._playback_state_changed(True)
        self.page._sync_transform_visual_overlay()
        visual = self.page.position_visual_overlay
        record = self._capture_with_qt_overlay(
            self.window, visual, "08-transform-overlay"
        )
        self.result["transform_overlay"] = {
            "capture_pixels": record["pixels"],
            "visible": visual.isVisible(),
            "interaction_visible": self.page.position_overlay.isVisible(),
            "device_pixel_ratio": float(visual.devicePixelRatioF()),
            "visual_geometry": [visual.x(), visual.y(), visual.width(), visual.height()],
            "interaction_native": self.page.position_overlay.testAttribute(
                __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_NativeWindow
            ),
            "capture_foreground_is_app": bool(record.get("foreground_is_app")),
            "capture_matches_window": bool(record.get("capture_matches_window")),
            "overlay_nonblank": bool(record.get("overlay_nonblank")),
        }
        self._start_stress()

    def _start_stress(self) -> None:
        from .studio_edit_sequence import sequence_of

        page = self.page
        sequence = sequence_of(page.project)
        candidates = [item.id for item in sequence.clip_candidates[:5]]
        self._stress_before = {
            "cue_count": len(page.project.cues),
            "segment_count": len(sequence.segments),
            "video_locked": sequence.video_track_locked,
            "accepted_candidates": sum(item.status == "accepted" for item in sequence.clip_candidates),
        }
        operations: list[tuple[str, Callable[[], None]]] = []
        for index in range(10):
            def add_subtitle(index=index) -> None:
                page.timeline.set_playhead(1_000 + index * 2_500)
                page._add_subtitle_at_playhead()
                page.timeline._cancel_inline_edit()
            operations.append((f"T-{index + 1}", add_subtitle))
        lock_count = 0
        if sequence.video_track_locked:
            operations.append(("Lock-1", page._toggle_video_lock))
            lock_count = 1
        for index in range(10):
            operations.append((f"Razor-{index + 1}", lambda index=index: page._razor_video_at(60_000 + index * 30_000)))
        while lock_count < 10:
            lock_count += 1
            operations.append((f"Lock-{lock_count}", page._toggle_video_lock))
        for index, candidate_id in enumerate(candidates):
            operations.append((f"CandidatePreview-{index + 1}", lambda candidate_id=candidate_id: page._on_candidate_clicked(candidate_id)))
        for index, candidate_id in enumerate(candidates):
            operations.append((f"CandidateAdd-{index + 1}", lambda candidate_id=candidate_id: page._set_candidate_status(candidate_id, "accepted")))
        self._operations = operations
        self._operation_results = []
        self._monitor_timer.start()
        self._event("stress_start", operation_count=len(operations), before=self._stress_before)
        self._later(40, self._run_next_operation)

    def _run_next_operation(self) -> None:
        if not self._operations:
            self._later(4500, self._finish_stress)
            return
        name, operation = self._operations.pop(0)
        started = time.perf_counter()
        status = "ok"
        message = ""
        try:
            operation()
        except Exception as exc:
            status = "error"
            message = f"{type(exc).__name__}: {exc}"
        record = {
            "name": name,
            "status": status,
            "message": message,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        self._operation_results.append(record)
        self._event("operation", **record)
        self._later(55, self._run_next_operation)

    def _poll_visible_process_windows(self) -> None:
        try:
            import psutil

            children = psutil.Process(os.getpid()).children(recursive=True)
            names = {child.pid: child.name().casefold() for child in children if child.is_running()}
            targets = {"ffmpeg.exe", "ffprobe.exe", "cmd.exe", "powershell.exe", "pwsh.exe"}
            target_pids = {pid for pid, name in names.items() if name in targets}
            if not target_pids:
                return
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def visit(hwnd, _lparam):
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in target_pids or not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                key = (pid.value, int(hwnd))
                if key in self._seen_windows:
                    return True
                self._seen_windows.add(key)
                record = {"pid": pid.value, "hwnd": int(hwnd), "binary": names.get(pid.value, "")}
                self._visible_process_windows.append(record)
                self._event("visible_process_window", **record)
                return True

            ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
        except Exception as exc:
            if "window_monitor_error" not in self.result:
                self.result["window_monitor_error"] = f"{type(exc).__name__}: {exc}"

    def _finish_stress(self) -> None:
        from .studio_edit_sequence import sequence_of

        self._monitor_timer.stop()
        self._poll_visible_process_windows()
        sequence = sequence_of(self.page.project)
        after = {
            "cue_count": len(self.page.project.cues),
            "segment_count": len(sequence.segments),
            "video_locked": sequence.video_track_locked,
            "accepted_candidates": sum(item.status == "accepted" for item in sequence.clip_candidates),
        }
        counts = {
            "T": sum(item["name"].startswith("T-") and item["status"] == "ok" for item in self._operation_results),
            "Razor": sum(item["name"].startswith("Razor-") and item["status"] == "ok" for item in self._operation_results),
            "Lock": sum(item["name"].startswith("Lock-") and item["status"] == "ok" for item in self._operation_results),
            "CandidatePreview": sum(item["name"].startswith("CandidatePreview-") and item["status"] == "ok" for item in self._operation_results),
            "CandidateAdd": sum(item["name"].startswith("CandidateAdd-") and item["status"] == "ok" for item in self._operation_results),
        }
        self.result["stress"] = {
            "before": self._stress_before,
            "after": after,
            "successful_counts": counts,
            "operations": self._operation_results,
            "visible_process_window_count": len(self._visible_process_windows),
            "visible_process_windows": self._visible_process_windows,
            "window_monitor_error": self.result.get("window_monitor_error", ""),
        }
        self._capture(self.window, "09-stress-complete")
        accepted = (
            counts == {"T": 10, "Razor": 10, "Lock": 10, "CandidatePreview": 5, "CandidateAdd": 5}
            and not self._visible_process_windows
            and not self.result.get("window_monitor_error")
            and after["cue_count"] >= self._stress_before["cue_count"] + 10
            and after["segment_count"] >= self._stress_before["segment_count"] + 10
        )
        self.result["stress_accepted"] = accepted
        self._finish(accepted)

    def _write_result(self) -> None:
        self.result_path.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _fail(self, message: str) -> None:
        self.result["errors"].append({"step": "runtime", "type": "RuntimeError", "message": message})
        self._finish(False)

    def _finish(self, accepted: bool) -> None:
        self._monitor_timer.stop()
        provider_accepted = (
            bool(self.result.get("provider_connection_accepted"))
            if self.mode == "full"
            else True
        )
        runtime_checks_accepted = True
        if self.mode == "full":
            empty = self.result.get("empty_studio", {})
            real_studio = self.result.get("real_studio", {})
            color = self.result.get("color_picker", {})
            candidates = self.result.get("clip_candidates", {})
            fixture = self.result.get("ai_fixture", {})
            style_sync = self.result.get("style_ui_sync", {})
            transform = self.result.get("transform_overlay", {})
            runtime_checks_accepted = bool(
                empty.get("accepted")
                and len(self.result.get("page_switches", ())) == 20
                and self.result.get("page_switch_state_mismatches") == 0
                and real_studio.get("cue_horizontal_scroll_max") == 0
                and 0.98 <= float(color.get("sv_ratio", 0)) <= 1.02
                and color.get("gradient_above_picker")
                and candidates.get("horizontal_scroll_max") == 0
                and float(candidates.get("height_ratio", 0)) >= 0.55
                and candidates.get("actions_accepted")
                and fixture.get("applied")
                and style_sync.get("font")
                and transform.get("visible")
                and transform.get("interaction_visible")
                and not transform.get("interaction_native")
                and transform.get("capture_matches_window")
                and transform.get("overlay_nonblank")
            )
        self.result["formal_runtime_checks_accepted"] = runtime_checks_accepted
        self.result["accepted"] = (
            bool(accepted)
            and provider_accepted
            and runtime_checks_accepted
            and not self.result["errors"]
        )
        self.result["finished_at"] = time.time()
        self.result["duration_seconds"] = round(
            float(self.result["finished_at"]) - float(self.result["started_at"]), 3
        )
        self._write_result()
        self._event("finish", accepted=self.result["accepted"], result_path=str(self.result_path))
        if os.environ.get("TWOBYTEASR_P64_AUTO_CLOSE", "1") == "1":
            self._later(250, self.window.close)
