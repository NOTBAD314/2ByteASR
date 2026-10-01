"""P8B continuous real-widget Creative Engine runtime evidence.

This opt-in audit drives production Qt widgets and real media. It is automated
headed evidence and never represents a person's acceptance.
"""

from __future__ import annotations

import hashlib
import copy
import json
import math
import os
import statistics
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from .art_direction import fallback_art_directions, validate_and_repair_graph
from .model_registry import scan_model_registry
from .runtime_paths import get_runtime_paths
from .studio_ai import (
    AIDesignSuggestion,
    _fallback_graph_recipes,
    available_font_shortlist,
    style_recipe_for_prompt,
)
from .style_recipe import VisualStyleRecipe
from .studio_media_pool import active_video_clips, asset_by_id
from .visual_design_graph import (
    VisualDesignGraph,
    compile_live_scene,
    clean_subtitle_graph,
    style_recipe_from_graph,
)
from .window_audit import qt_top_level_widgets, win32_top_level_windows


MODEL_KEYS = ("moss", "firered_aed", "qwen_asr")


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _rgba_metrics(image: QImage, path: Path) -> dict[str, object]:
    if image.isNull():
        return {"path": str(path), "visible_pixels": 0, "alpha_bounds": None}
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(converted.constBits())[:converted.sizeInBytes()]
    line = converted.bytesPerLine()
    xs: list[int] = []
    ys: list[int] = []
    dark = 0
    for y in range(converted.height()):
        row = y * line
        for x in range(converted.width()):
            offset = row + x * 4
            red, green, blue, alpha = data[offset:offset + 4]
            if alpha > 8:
                xs.append(x)
                ys.append(y)
            if alpha > 64 and (red * 299 + green * 587 + blue * 114) / 1000 < 90:
                dark += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    converted.save(str(path))
    return {
        "path": str(path),
        "sha256_pixels": hashlib.sha256(data).hexdigest(),
        "size": [converted.width(), converted.height()],
        "visible_pixels": len(xs),
        "dark_outline_pixels": dark,
        "alpha_bounds": None if not xs else [min(xs), min(ys), max(xs), max(ys)],
    }


def _file_metrics(path: Path) -> dict[str, object]:
    image = QImage(str(path))
    if image.isNull():
        return {"path": str(path), "visible_pixels": 0, "alpha_bounds": None}
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(converted.constBits())[:converted.sizeInBytes()]
    line = converted.bytesPerLine()
    xs: list[int] = []
    ys: list[int] = []
    dark = 0
    for y in range(converted.height()):
        row = y * line
        for x in range(converted.width()):
            offset = row + x * 4
            red, green, blue, alpha = data[offset:offset + 4]
            if alpha > 8:
                xs.append(x)
                ys.append(y)
            if alpha > 64 and (red * 299 + green * 587 + blue * 114) / 1000 < 90:
                dark += 1
    return {
        "path": str(path),
        "sha256_pixels": hashlib.sha256(data).hexdigest(),
        "size": [converted.width(), converted.height()],
        "visible_pixels": len(xs),
        "dark_outline_pixels": dark,
        "alpha_bounds": None if not xs else [min(xs), min(ys), max(xs), max(ys)],
    }


def _image_has_visible_alpha(image: QImage) -> bool:
    """Use real LIVE canvas pixels as the post-edit readiness signal."""
    if image.isNull():
        return False
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(converted.constBits())[:converted.sizeInBytes()]
    return max(data[3::4], default=0) > 8


def _video_metrics(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    with Image.open(path) as source:
        gray = source.convert("L")
        histogram = gray.histogram()
        pixels = max(1, gray.width * gray.height)
        nonblack = pixels - sum(histogram[:9])
        return {
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            "bytes": len(payload),
            "size": [gray.width, gray.height],
            "nonblack_ratio": round(nonblack / pixels, 6),
            "mean_luma": round(sum(i * n for i, n in enumerate(histogram)) / pixels, 3),
        }


def _radius(bounds: list[int] | None, base: list[int] | None) -> float:
    if not bounds or not base:
        return 0.0
    return round(statistics.mean((
        max(0, base[0] - bounds[0]),
        max(0, base[1] - bounds[1]),
        max(0, bounds[2] - base[2]),
        max(0, bounds[3] - base[3]),
    )), 3)


def _reference_radius(
    radius: float,
    size: list[int] | tuple[int, int] | None,
    *,
    reference: tuple[int, int] = (1280, 720),
) -> float:
    """Normalize raster growth before comparing LIVE and Fidelity owners."""

    if not size or len(size) < 2:
        return round(float(radius), 3)
    scale_x = max(1.0, float(size[0])) / max(1.0, float(reference[0]))
    scale_y = max(1.0, float(size[1])) / max(1.0, float(reference[1]))
    return round(float(radius) / statistics.mean((scale_x, scale_y)), 3)


class P8BRuntimeAudit:
    def __init__(self, window, output_dir: str | os.PathLike[str], *, mode: str) -> None:
        self.window = window
        self.page = window.studio_page
        self.app = QApplication.instance()
        self.output = Path(output_dir).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.screenshots = self.output / "screenshots"
        self.screenshots.mkdir(exist_ok=True)
        self.result_path = self.output / "runtime-result.json"
        self.mode = str(mode or "workflow").strip().lower()
        self.result: dict[str, Any] = {
            "schema": "2byteasr.p8b-runtime-audit.v1",
            "mode": self.mode,
            "evidence_class": "PACKAGED QT REAL-WIDGET AUTOMATION" if getattr(sys, "frozen", False) else "SOURCE QT REAL-WIDGET AUTOMATION",
            "real_user_click": False,
            "ui_event_path": True,
            "started_at": time.time(),
            "process": {
                "pid": os.getpid(),
                "executable": sys.executable,
                "frozen": bool(getattr(sys, "frozen", False)),
                "image_name": Path(sys.executable).name,
            },
            "phases": {},
            "checks": {},
            "errors": [],
        }

    def start(self) -> None:
        QTimer.singleShot(0, self._run)

    def _pump(self, milliseconds: int, profile: list[float] | None = None) -> None:
        deadline = time.perf_counter() + max(0, int(milliseconds)) / 1000.0
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            self.app.processEvents()
            if profile is not None:
                profile.append((time.perf_counter() - started) * 1000.0)
            QTest.qWait(min(16, max(1, round((deadline - time.perf_counter()) * 1000))))

    def _wait(self, predicate, timeout: float, label: str) -> float:
        started = time.perf_counter()
        while time.perf_counter() - started < timeout:
            self.app.processEvents()
            try:
                if predicate():
                    return round((time.perf_counter() - started) * 1000.0, 3)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            QTest.qWait(16)
        raise TimeoutError(f"{label} not ready after {timeout:.1f}s")

    @staticmethod
    def _track(project, track_id: str):
        return next(item for item in project.video_tracks if item.id == track_id)

    def _startup_phase(self) -> dict[str, object]:
        trace_path = Path(os.environ.get("TWOBYTEASR_STARTUP_TRACE", ""))
        rows = []
        if trace_path.is_file():
            rows = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        preflight = next((row for row in rows if row.get("stage") == "MODEL_PREFLIGHT"), {})
        registry = scan_model_registry(
            install_root=get_runtime_paths().install_root,
            model_root=get_runtime_paths().model_root,
        )
        records = {
            key: registry.records[key].health.value
            for key in MODEL_KEYS if key in registry.records
        }
        top_levels = qt_top_level_widgets(self.app)
        return {
            "trace_path": str(trace_path),
            "trace": rows,
            "preflight": preflight,
            "registry_installed_count": registry.installed_count(),
            "registry_records": records,
            "visible_qt_top_levels": [item for item in top_levels if item.get("visible")],
            "guided_setup_visible": any(
                item.get("visible") and item.get("class") == "GuidedSetupDialog"
                for item in top_levels
            ),
        }

    def _drop_v2(self, media: Path, target_ms: int = 9_000) -> dict[str, object]:
        page = self.page
        timeline = page.timeline
        rect = timeline._video_track_rects()["V2"]
        local = QPoint(round(timeline._time_to_x(target_ms)), round(rect.center().y()))
        point = timeline.mapTo(page, local)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(media.resolve()))])
        drag = QDragEnterEvent(
            point, Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, drag)
        drop = QDropEvent(
            QPointF(point), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, drop)
        return {"point": [point.x(), point.y()], "drag": drag.isAccepted(), "drop": drop.isAccepted()}

    def _drag_v2_to_zero(self) -> dict[str, object]:
        page = self.page
        timeline = page.timeline
        project = page.project
        clip = self._track(project, "V2").clips[0]
        generation_before = int(page._video_composition_generation)
        timeline.set_visible_window(0, 60_000)
        self._pump(100)
        start_ms = int(clip.timeline_in_ms) + 3_000
        start = QPoint(round(timeline._time_to_x(start_ms)), round(timeline._video_track_rects()["V2"].center().y()))
        content_width = max(1, timeline._content_right() - timeline.TRACK_HEADER_WIDTH)
        pixels_to_zero = math.ceil(
            int(clip.timeline_in_ms) * content_width / max(1, timeline.visible_duration_ms)
        )
        # Cross the zero boundary by one logical pixel so coordinate rounding
        # cannot leave a nominal 0 ms drag committed at 1-40 ms.
        end = QPoint(start.x() - pixels_to_zero - 1, start.y())
        left_x = timeline._time_to_x(int(clip.timeline_in_ms))
        probe = {
            "timeline_size": [timeline.width(), timeline.height()],
            "timeline_visible": timeline.isVisible(),
            "visible_window": [timeline.visible_start_ms, timeline.visible_duration_ms],
            "v2_rect": [
                round(timeline._video_track_rects()["V2"].x()),
                round(timeline._video_track_rects()["V2"].y()),
                round(timeline._video_track_rects()["V2"].width()),
                round(timeline._video_track_rects()["V2"].height()),
            ],
            "clip_before": [int(clip.timeline_in_ms), int(clip.timeline_out_ms)],
            "start": [start.x(), start.y()],
            "end": [end.x(), end.y()],
            "start_track": timeline._video_track_at(start),
            "start_clip": getattr(timeline._video_clip_at("V2", timeline._x_to_time(start.x())), "id", ""),
        }
        self.result["phases"]["carryover_drag_probe"] = probe
        self._write()
        QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
        probe["after_press"] = dict(timeline._clip_drag or {})
        QTest.mouseMove(timeline, end, delay=120)
        probe["after_move"] = dict(timeline._clip_drag or {})
        QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)
        probe["timeline_in_after_release"] = int(self._track(project, "V2").clips[0].timeline_in_ms)
        self._write()
        self._wait(lambda: int(self._track(project, "V2").clips[0].timeline_in_ms) == 0, 5, "V2 drag to zero")
        moved = self._track(project, "V2").clips[0]
        linked = next(
            item for track in project.audio_tracks for item in track.clips
            if item.linked_video_clip_id == moved.id
        )
        return {
            "event_path": "QTest mousePress/mouseMove/mouseRelease",
            "start": [start.x(), start.y()], "end": [end.x(), end.y()],
            "body_distance_from_left_px": round(abs(start.x() - left_x), 3),
            "trim_handle_px": timeline.VIDEO_CLIP_TRIM_HANDLE_PX,
            "timeline_in_ms": int(moved.timeline_in_ms),
            "source_in_ms": int(moved.source_in_ms),
            "linked_audio_timeline_in_ms": int(linked.timeline_in_ms),
            "composition_generation_before": generation_before,
            "composition_generation_after": int(page._video_composition_generation),
        }

    def _toggle_track(self, track_id: str) -> None:
        timeline = self.page.timeline
        rect = timeline._video_track_rects()[track_id]
        QTest.mouseClick(
            timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(143, round(rect.center().y())),
        )

    def _capture_video(self, name: str) -> dict[str, object]:
        target = self.screenshots / f"{name}.png"
        controller = self.page.video.controller
        controller.screenshot_to_file(target, mode="video")
        self._wait(lambda: target.is_file() and target.stat().st_size > 0, 10, name)
        return _video_metrics(target)

    def _carryover_phase(self) -> dict[str, object]:
        page = self.page
        project = page.project
        page.timeline.set_visible_window(0, 60_000)
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        page._seek(1.0)
        self._pump(700)
        tab_bar = page.context_drawer.tabBar()
        QTest.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar.tabRect(page.media_pool_tab_index).center())
        self._wait(lambda: page.media_pool_panel.isVisible(), 4, "Media Pool")
        QTest.mouseClick(page.media_pool_panel.add_track_button, Qt.MouseButton.LeftButton)
        self._wait(lambda: [track.id for track in project.video_tracks] == ["V1", "V2"], 5, "V2 track")
        media = Path(os.environ["TWOBYTEASR_P8B_SECOND_MEDIA"])
        drop = self._drop_v2(media)
        self._wait(lambda: bool(self._track(project, "V2").clips), 45, "V2 media")
        self._pump(400)
        drag = self._drag_v2_to_zero()

        layers_before = page._multitrack_preview_layers(int(page.timeline.playhead_ms))
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._pump(500)
        project_time = int(page.timeline.playhead_ms)
        before_hide_generation = int(page._video_composition_generation)
        self._toggle_track("V1")
        self._wait(lambda: not self._track(project, "V1").enabled, 4, "hide V1")
        # Deliberately no seek here. This is the stateful production regression.
        expected = str(media.resolve()).casefold()
        rebind_ms = self._wait(
            lambda: str(page.video.controller.observed_property("path", "") or page.video._media_path).casefold() == expected,
            15, "V2 dynamic base rebind",
        )
        frame_ms = self._wait(
            lambda: bool(page.video.controller.observed_property("video-frame-info", {})),
            15, "V2 first video frame",
        )
        self._pump(250)
        project_time = int(page.timeline.playhead_ms)
        active = []
        for track, clip in active_video_clips(project, project_time):
            asset = asset_by_id(project, clip.asset_id)
            mapped = page._multitrack_preview_layers(project_time)
            layer = next((item for item in mapped if item["clip_id"] == clip.id), {})
            active.append({
                "track_id": track.id, "clip_id": clip.id,
                "timeline_in_ms": int(clip.timeline_in_ms),
                "source_time_ms": int(layer.get("source_ms", clip.source_in_ms)),
                "source_path": str(asset.canonical_source),
            })
        controller = page.video.controller
        pixels = self._capture_video("v2-after-drag-hide-no-seek")
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(120)
        return {
            "drop": drop,
            "drag": drag,
            "project_time_ms": project_time,
            "layers_before_hide": [item["track_id"] for item in layers_before],
            "active_visible_clips": active,
            "visible_layer_set": [item["track_id"] for item in page._multitrack_preview_layers(project_time)],
            "chosen_base": {
                "track_id": page._active_video_preview_track_id,
                "clip_id": page._active_video_preview_clip_id,
                "source_path": page._active_video_preview_source_path,
                "timeline_in_ms": page._active_video_preview_timeline_in_ms,
                "source_in_ms": page._active_video_preview_source_in_ms,
            },
            "composition_generation_before_hide": before_hide_generation,
            "composition_generation_after_hide": int(page._video_composition_generation),
            "rebind_wait_ms": rebind_ms,
            "first_frame_wait_ms": frame_ms,
            "mpv": {
                "path": controller.observed_property("path", ""),
                "time_pos": controller.observed_property("time-pos", None),
                "video_frame_info": controller.observed_property("video-frame-info", {}),
                "observed_position": controller.observed_position(),
                "applied_seek_state": controller.applied_seek_state(),
                "playback_clock": asdict(page.video.playback_position_snapshot()),
            },
            "pixels": pixels,
            "extra_seek_after_hide": False,
        }

    def _spin_value(self, value: float) -> float:
        control = self.page.style_outline_width
        editor = control.lineEdit()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        started = time.perf_counter()
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, f"{value:g}")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self._wait(lambda: abs(float(control.value()) - value) < 0.01, 2, f"stroke {value:g} control")
        self._wait(
            lambda: (
                getattr(self.page, "_advanced_preview_snapshot", None) is not None
                and bool(self.page._advanced_preview_snapshot.strokes)
                and abs(float(self.page._advanced_preview_snapshot.strokes[0].get("width", -1)) - value) < 0.01
            ),
            5,
            f"stroke {value:g} LIVE snapshot",
        )
        def current_pixels_ready() -> bool:
            page = self.page
            snapshot = getattr(page, "_advanced_preview_snapshot", None)
            state = getattr(page, "_advanced_preview_state", None)
            identity = getattr(state, "identity", None)
            owner = str(getattr(page, "_advanced_canvas_source_kind", ""))
            return bool(
                owner in {"live", "fidelity"}
                and snapshot is not None
                and identity is not None
                and identity.cue_id == snapshot.cue_id
                and identity.snapshot_hash == snapshot.stable_hash()
                and int(getattr(identity, "appearance_generation", -1))
                == int(getattr(snapshot, "appearance_generation", -2))
                and _image_has_visible_alpha(page.advanced_cue_overlay._source_image)
            )

        try:
            self._wait(
                current_pixels_ready,
                5,
                f"stroke {value:g} current foreground pixels",
            )
        except TimeoutError as exc:
            canvas = self.page.advanced_cue_overlay
            image = canvas._source_image
            target = self.screenshots / f"stroke-{value:g}-live-timeout.png"
            if not image.isNull():
                image.save(str(target), "PNG")
            converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
            data = (
                bytes(converted.constBits())[:converted.sizeInBytes()]
                if not converted.isNull() else b""
            )
            snapshot = getattr(self.page, "_advanced_preview_snapshot", None)
            raise TimeoutError(
                f"{exc}; owner={self.page._advanced_canvas_source_kind}; "
                f"image={image.width()}x{image.height()}; "
                f"max_alpha={max(data[3::4], default=0)}; "
                f"appearance_generation={getattr(snapshot, 'appearance_generation', -1)}; "
                f"snapshot_hash={snapshot.stable_hash() if snapshot is not None else ''}; "
                f"capture={target}"
            ) from exc
        return round((time.perf_counter() - started) * 1000, 3)

    def _wait_fidelity(self, width: float, timeout: float = 150.0) -> tuple[Path, float]:
        started = time.perf_counter()
        self._wait(
            lambda: (
                self.page._advanced_canvas_source_kind == "fidelity"
                and bool(self.page._advanced_preview_state.frame_path)
                and getattr(self.page, "_advanced_preview_snapshot", None) is not None
                and bool(self.page._advanced_preview_snapshot.strokes)
                and abs(float(self.page._advanced_preview_snapshot.strokes[0].get("width", -1)) - width) < 0.01
            ),
            timeout,
            f"stroke {width:g} Fidelity",
        )
        return Path(self.page._advanced_preview_state.frame_path), round((time.perf_counter() - started) * 1000, 3)

    def _stroke_phase(self) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        page.context_drawer.setCurrentIndex(2)
        page._seek((cue.start_ms + 700) / 1000.0)
        self._pump(500)
        graph = clean_subtitle_graph()
        graph.text_layer.font.update({"family": "Arial", "size": 115, "weight": 700})
        graph.text_layer.fill = {"type": "solid", "color": "#FFFFFFFF"}
        graph.text_layer.shadow = {}
        graph.text_layer.glow = {}
        graph.text_layer.strokes = [{"color": "#FF000000", "width": 0, "opacity": 1}]
        recipe = style_recipe_from_graph(graph)
        page._apply_style_recipe(cue.id, recipe)
        page._load_style_inspector()
        # Applying an animated graph intentionally replays its entrance. End
        # that user-visible replay through the real transport before measuring
        # paused LIVE -> Fidelity parity.
        self._wait(
            lambda: not page.video.playback_position_snapshot().paused,
            8,
            "initial VisualGraph replay",
        )
        QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: page.video.playback_position_snapshot().paused,
            4,
            "pause after initial VisualGraph replay",
        )
        page._seek((cue.start_ms + 700) / 1000.0)
        self._pump(400)

        records: dict[str, object] = {}
        for width in (0.0, 1.0, 5.0, 10.0, 20.0):
            control_ms = self._spin_value(width)

            def current_live_image() -> QImage:
                memory = getattr(page, "_advanced_live_memory", {})
                pixmap = next(reversed(memory.values()), None) if memory else None
                return pixmap.toImage() if pixmap is not None and not pixmap.isNull() else QImage()

            immediate = _rgba_metrics(
                current_live_image(),
                self.screenshots / f"stroke-{width:g}-live-immediate.png",
            )
            immediate_owner = page._advanced_canvas_source_kind
            self._pump(50)
            after_50 = _rgba_metrics(
                current_live_image(),
                self.screenshots / f"stroke-{width:g}-live-50ms.png",
            )
            after_50_owner = page._advanced_canvas_source_kind
            fidelity_path, fidelity_wait_ms = self._wait_fidelity(width)
            fidelity = _file_metrics(fidelity_path)
            records[f"{width:g}"] = {
                "control_event_path": "QTest key input on ScrubDoubleSpinBox.lineEdit",
                "control_to_live_ms": control_ms,
                "fidelity_wait_ms": fidelity_wait_ms,
                "canonical_width": float(page._advanced_preview_snapshot.strokes[0]["width"]),
                "graph_width": float(page._advanced_preview_snapshot.style_recipe["visualGraph"]["textLayer"]["strokes"][0]["width"]),
                "live_immediate": immediate,
                "live_immediate_owner": immediate_owner,
                "live_after_50ms": after_50,
                "after_50ms_owner": after_50_owner,
                "fidelity": fidelity,
                "fidelity_owner": page._advanced_canvas_source_kind,
                "owner": page.subtitle_visibility_trace(reason=f"stroke-{width:g}"),
            }

        base_live = records["0"]["live_immediate"]
        base_fidelity = records["0"]["fidelity"]
        for key in ("1", "5", "10", "20"):
            records[key]["live_radius_px"] = _radius(records[key]["live_immediate"]["alpha_bounds"], base_live["alpha_bounds"])
            records[key]["fidelity_radius_px"] = _radius(records[key]["fidelity"]["alpha_bounds"], base_fidelity["alpha_bounds"])
            records[key]["after_50ms_radius_px"] = _radius(
                records[key]["live_after_50ms"]["alpha_bounds"],
                base_live["alpha_bounds"],
            )
            records[key]["live_radius_reference_px"] = _reference_radius(
                records[key]["live_radius_px"],
                records[key]["live_immediate"].get("size"),
            )
            records[key]["fidelity_radius_reference_px"] = _reference_radius(
                records[key]["fidelity_radius_px"],
                records[key]["fidelity"].get("size"),
            )
            records[key]["after_50ms_radius_reference_px"] = _reference_radius(
                records[key]["after_50ms_radius_px"],
                records[key]["live_after_50ms"].get("size"),
            )

        # Playback must immediately reclaim foreground ownership, then a pause
        # requests Fidelity at the current cue-local frame.
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(lambda: page._advanced_canvas_source_kind == "live", 4, "LIVE owner on playback")
        profile: list[float] = []
        hashes = []
        owners = []
        for _ in range(8):
            self._pump(90, profile)
            image = page.advanced_cue_overlay._source_image
            converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
            hashes.append(hashlib.sha256(bytes(converted.constBits())[:converted.sizeInBytes()]).hexdigest())
            owners.append(page.subtitle_visibility_trace(reason="stroke-playing")["foreground_owner"])
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        paused_local_ms = max(0, int(page.timeline.playhead_ms) - int(cue.start_ms))
        paused_path, paused_wait_ms = self._wait_fidelity(20)
        pause_identity = page._advanced_preview_state.identity
        paused_fidelity = _file_metrics(paused_path)

        page._seek((cue.end_ms + 250) / 1000.0)
        self._pump(250)
        page._seek((cue.start_ms + 700) / 1000.0)
        self._pump(250)
        reentry_path, _ = self._wait_fidelity(20)
        reentry = _file_metrics(reentry_path)
        return {
            "levels": records,
            "playing": {
                "owners": owners,
                "distinct_frames": len(set(hashes)),
                "composite_p95_ms": _percentile([
                    float(page.advanced_cue_overlay._last_sync_profile.get("total_ms", 0))
                    for _item in hashes
                ], 0.95),
                "event_loop_p95_ms": _percentile(profile, 0.95),
            },
            "paused": {
                "cue_local_ms": paused_local_ms,
                "fidelity_identity_motion_ms": int(pause_identity.motion_time_ms if pause_identity else -1),
                "wait_ms": paused_wait_ms,
                "owner": page.subtitle_visibility_trace(reason="stroke-paused")["foreground_owner"],
                "pixels": paused_fidelity,
            },
            "seek_reentry": {
                "canonical_width": float(page._advanced_preview_snapshot.strokes[0]["width"]),
                "pixels": reentry,
                "owner": page.subtitle_visibility_trace(reason="stroke-reentry")["foreground_owner"],
            },
        }

    def _fixture_suggestion(self, cue_id: str) -> AIDesignSuggestion:
        prompt = "漫画冲击字幕，克制、有层级、稳定可读"
        directions = fallback_art_directions(prompt)
        base_recipe = style_recipe_for_prompt(prompt)
        planned = _fallback_graph_recipes(
            prompt, base_recipe, available_font_shortlist(), directions,
        )
        variants = tuple(
            VisualStyleRecipe.from_style_recipe(recipe) for recipe in planned
        )
        scores = []
        for visual, direction in zip(variants, directions):
            graph = VisualDesignGraph.from_dict(visual.visual_graph)
            _graph, score = validate_and_repair_graph(graph, direction, deadline_ms=40)
            scores.append(score)
        return AIDesignSuggestion(
            cue_id,
            variants[0].to_style_recipe(),
            "P8B formal headed curated fixture; real Provider is verified separately.",
            variants,
            "Three materially distinct art directions",
            tuple(direction.visual_language for direction in directions),
            "Layered family motion with readable hold",
            {"headed_fixture": True},
            False,
            "headed_fixture",
            {},
            tuple(directions),
            tuple(scores),
        )

    def _ai_motion_phase(self) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        cue_id = cue.id
        page.select_cue(cue.id)
        page.context_drawer.setCurrentIndex(0)
        suggestion = self._fixture_suggestion(cue.id)
        page._ai_ready(suggestion)
        self._pump(100)
        cards = [
            item.widget() for index in range(page.ai_variant_row.count())
            if (item := page.ai_variant_row.itemAt(index)) is not None and item.widget() is not None
        ]
        titles = [
            next((label.text() for label in card.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel) if label.objectName() == "cardMeta"), "")
            for card in cards
        ]
        play = next(button for button in cards[0].findChildren(QPushButton) if button.text() == "播放动效")
        label = page._ai_variant_preview_labels[0]
        before_key = label.pixmap().cacheKey() if label.pixmap() and not label.pixmap().isNull() else 0
        started = time.perf_counter()
        QTest.mouseClick(play, Qt.MouseButton.LeftButton)
        first_frame_ms = self._wait(
            lambda: label.pixmap() is not None and not label.pixmap().isNull() and label.pixmap().cacheKey() != before_key,
            3,
            "AI card LIVE first frame",
        )
        self._pump(350)
        motion_running = 0 in page._ai_variant_motion_timers
        apply = next(button for button in cards[0].findChildren(QPushButton) if button.text() == "应用")
        card_graph = page._pending_suggestion.variants[0].visual_graph
        # Applying a graph canonicalizes it for the actual cue duration. The
        # persisted graph is therefore compared with that normalized graph,
        # not with the shorter card preview graph before clamping.
        card_scene = compile_live_scene(card_graph)
        # P9A-R3: apply stores the design-intent graph unchanged; the cue
        # span binding happens inside compile_live_scene(cue_duration_ms=...)
        # at render time, so the persisted graph equals the card graph.
        card_hash = card_scene.graph_hash
        pre_apply_style_id = str(page._cue_lookup[cue_id].style_id)
        pre_apply_payload = page.project.style_recipes.get(pre_apply_style_id, {})
        pre_apply_graph = (
            pre_apply_payload.get("visualGraph", {})
            if isinstance(pre_apply_payload, Mapping) else {}
        )
        pre_apply_graph_hash = (
            compile_live_scene(pre_apply_graph).graph_hash if pre_apply_graph else ""
        )
        click_observed: list[bool] = []
        apply.clicked.connect(lambda: click_observed.append(True))
        QTest.mouseClick(apply, Qt.MouseButton.LeftButton)
        self._pump(100)

        def current_apply_state() -> dict[str, object]:
            current = page._cue_lookup[cue_id]
            payload = page.project.style_recipes.get(current.style_id, {})
            graph = payload.get("visualGraph", {}) if isinstance(payload, Mapping) else {}
            return {
                "button_visible": apply.isVisible(),
                "button_enabled": apply.isEnabled(),
                "button_geometry": list(apply.geometry().getRect()),
                "clicked_signal": bool(click_observed),
                "selected_cue_id": str(page.selected_cue_id),
                "pending_cue_id": str(getattr(page._pending_suggestion, "cue_id", "")),
                "style_id": str(current.style_id),
                "graph_hash": compile_live_scene(graph).graph_hash if graph else "",
                "expected_graph_hash": card_hash,
                # Keep the complete graph payload in the audit artifact so a
                # hash mismatch identifies the exact ownership mutation.
                "graph": copy.deepcopy(graph) if isinstance(graph, Mapping) else {},
                "expected_graph": copy.deepcopy(card_graph) if isinstance(card_graph, Mapping) else {},
            }

        self.result["phases"]["ai_apply_probe"] = current_apply_state()
        self._wait(
            lambda: (
                str(page._cue_lookup[cue_id].style_id) != pre_apply_style_id
                and page._cue_lookup[cue_id].style_id in page.project.style_recipes
                and self._applied_graph_matches_card(
                    page.project.style_recipes[page._cue_lookup[cue_id].style_id],
                    card_graph,
                    pre_apply_graph_hash,
                )
            ),
            5,
            "AI apply style/graph transition",
        )
        cue = page._cue_lookup[cue_id]
        self.result["phases"]["ai_apply_probe"] = current_apply_state()
        persisted = page.project.style_recipes[cue.style_id]
        applied_scene = compile_live_scene(persisted["visualGraph"])
        applied_hash = applied_scene.graph_hash
        applied_stroke_width = float(
            persisted["visualGraph"]["textLayer"]["strokes"][0]["width"]
        )
        # Keep a real transport sample for owner/visibility, and separately
        # sample the production LIVE compositor at cue-local entrance times.
        # An asynchronous mpv seek can settle into HOLD before a headed probe
        # observes it; that must not make a valid entrance graph look static.
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: (
                int(cue.start_ms) <= int(page.timeline.playhead_ms) < int(cue.end_ms)
                and page._advanced_canvas_source_kind == "live"
                and not page.video.playback_position_snapshot().paused
                and bool(page.advanced_cue_overlay._source_image)
                and any(
                    page.advanced_cue_overlay._source_image.pixelColor(x, y).alpha() > 8
                    for y in range(page.advanced_cue_overlay._source_image.height())
                    for x in range(page.advanced_cue_overlay._source_image.width())
                )
            ),
            5,
            "applied motion playing owner",
        )
        playback_samples = []
        for _ in range(12):
            self._pump(100)
            image = page.advanced_cue_overlay._source_image.convertToFormat(QImage.Format.Format_RGBA8888)
            payload = bytes(image.constBits())[:image.sizeInBytes()]
            playback_samples.append({
                "project_ms": int(page.timeline.playhead_ms),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "visible": any(payload[index + 3] > 8 for index in range(0, len(payload) - 3, 4)),
                "owner": page.subtitle_visibility_trace(reason="applied-playing")["foreground_owner"],
                "total_ms": float(page.advanced_cue_overlay._last_sync_profile.get("total_ms", 0)),
            })
        motion_samples = []
        saved_playhead = int(page.timeline.playhead_ms)
        for local_ms in (20, 70, 150, 260, 500, 1_000, 2_000, 3_000):
            absolute_ms = min(int(cue.end_ms) - 1, int(cue.start_ms) + local_ms)
            page.advanced_cue_overlay.sync_time(absolute_ms, paused=False)
            image = page.advanced_cue_overlay._source_image.convertToFormat(QImage.Format.Format_RGBA8888)
            payload = bytes(image.constBits())[:image.sizeInBytes()]
            motion_samples.append({
                "project_ms": absolute_ms,
                "cue_local_ms": absolute_ms - int(cue.start_ms),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "visible": any(payload[index + 3] > 8 for index in range(0, len(payload) - 3, 4)),
                "owner": page.subtitle_visibility_trace(reason="applied-motion-sample")["foreground_owner"],
                "total_ms": float(page.advanced_cue_overlay._last_sync_profile.get("total_ms", 0)),
            })
        page.advanced_cue_overlay.sync_time(
            saved_playhead,
            paused=page.video.playback_position_snapshot().paused,
        )
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._wait(
                lambda: page.video.playback_position_snapshot().paused,
                4,
                "pause before applied Fidelity",
            )
        fidelity_path, _ = self._wait_fidelity(
            float(page._advanced_preview_snapshot.strokes[0]["width"])
        )
        fidelity_identity = page._advanced_preview_state.identity
        page.save_button.click()
        self._wait(lambda: page.undo_stack.isClean(), 10, "P8B project save")
        page.grab().save(str(self.screenshots / "p8b-workflow-final.png"))
        return {
            "direction_titles": titles,
            "direction_families": [item.primary_family for item in suggestion.art_directions],
            "quality": [item.to_dict() for item in suggestion.quality_scores],
            "card_count": len(cards),
            "card_first_frame_ms": first_frame_ms,
            "card_click_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "play_motion_running_after_350ms": motion_running,
            "card_graph_hash": card_hash,
            "pre_apply_style_id": pre_apply_style_id,
            "pre_apply_graph_hash": pre_apply_graph_hash,
            "applied_graph_hash": applied_hash,
            "card_motion_duration_ms": int(canonical_card_graph.motion_graph.duration_ms),
            "applied_motion_duration_ms": int(applied_scene.graph.motion_graph.duration_ms),
            "applied_stroke_width": applied_stroke_width,
            "cue_duration_ms": int(cue.end_ms - cue.start_ms),
            "persisted_style_id": cue.style_id,
            "samples": motion_samples,
            "playback_samples": playback_samples,
            "sampling_mode": "production LIVE sync_time cue-local entrance plus real playback owner samples",
            "distinct_applied_frames": len({item["sha256"] for item in motion_samples}),
            "applied_p95_ms": _percentile([item["total_ms"] for item in playback_samples], 0.95),
            "paused_fidelity": {
                "path": str(fidelity_path),
                "motion_time_ms": int(fidelity_identity.motion_time_ms if fidelity_identity else -1),
                "cue_local_ms": max(0, int(page.timeline.playhead_ms) - int(cue.start_ms)),
                "owner": page.subtitle_visibility_trace(reason="applied-paused")["foreground_owner"],
                "pixels": _file_metrics(fidelity_path),
            },
            "saved": page.undo_stack.isClean(),
            "fixture_provider_succeeded": suggestion.provider_succeeded,
        }

    def _reopen_phase(self) -> None:
        page = self.page
        self._wait(lambda: page.project is not None and bool(page.project.cues), 30, "reopen project")
        project = page.project
        cue = project.cues[0]
        v2 = self._track(project, "V2")
        page.select_cue(cue.id)
        page._seek((cue.start_ms + 700) / 1000.0)
        self._pump(700)
        recipe = project.style_recipes.get(cue.style_id, {})
        graph = recipe.get("visualGraph", {}) if isinstance(recipe, Mapping) else {}
        self._wait(lambda: page._advanced_preview_snapshot is not None, 10, "reopen LIVE")
        stroke = float(page._advanced_preview_snapshot.strokes[0]["width"])
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: page.video.playback_position_snapshot().paused,
            3,
            "reopen pause before Fidelity",
        )
        fidelity_path, _ = self._wait_fidelity(stroke)
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: page._advanced_canvas_source_kind == "live",
            4,
            "reopen LIVE owner on playback",
        )
        before = int(page.timeline.playhead_ms)
        self._pump(800)
        after = int(page.timeline.playhead_ms)
        owner = page.subtitle_visibility_trace(reason="reopen-playing")["foreground_owner"]
        self.result["phases"]["reopen"] = {
            "v2_timeline_in_ms": int(v2.clips[0].timeline_in_ms),
            "v1_enabled": self._track(project, "V1").enabled,
            "stroke_width": stroke,
            "graph_hash": compile_live_scene(graph).graph_hash if graph else "",
            "motion_duration_ms": int(graph.get("motionGraph", {}).get("durationMs", 0)) if isinstance(graph, Mapping) else 0,
            "motion_tracks": len(graph.get("motionGraph", {}).get("tracks", [])) if isinstance(graph, Mapping) else 0,
            "play_advance_ms": after - before,
            "playing_owner": owner,
            "fidelity_pixels": _file_metrics(fidelity_path),
        }
        self.result["checks"] = {
            "startup_prompt_absent": bool(self.result["phases"]["startup"]["preflight"])
            and not bool(self.result["phases"]["startup"]["preflight"].get("prompt")),
            "v2_move_persisted": int(v2.clips[0].timeline_in_ms) == 0,
            "v1_hidden_persisted": not self._track(project, "V1").enabled,
            "applied_stroke_loaded": bool(graph)
            and abs(
                stroke
                - float(graph["textLayer"]["strokes"][0]["width"])
            ) < 0.01,
            "graph_motion_persisted": bool(graph and self.result["phases"]["reopen"]["motion_tracks"]),
            "reopen_playback_live": after - before >= 400 and owner == "advanced_live",
            "reopen_fidelity_nonblank": self.result["phases"]["reopen"]["fidelity_pixels"]["visible_pixels"] > 0,
        }

    def _workflow_phase(self) -> None:
        page = self.page
        self.window.setGeometry(40, 30, 1680, 1020)
        self.window.showNormal()
        self._wait(lambda: page.project is not None and bool(page.project.cues), 30, "project")
        self._wait(lambda: page.video.controller is not None and page.video.controller.running, 20, "mpv")
        self.result["phases"]["carryover"] = self._carryover_phase()
        self.result["phases"]["stroke"] = self._stroke_phase()
        self.result["phases"]["ai_motion"] = self._ai_motion_phase()
        carry = self.result["phases"]["carryover"]
        stroke = self.result["phases"]["stroke"]
        ai = self.result["phases"]["ai_motion"]
        levels = stroke["levels"]
        live_radii = [levels[key]["live_radius_reference_px"] for key in ("1", "5", "10", "20")]
        fidelity_radii = [levels[key]["fidelity_radius_reference_px"] for key in ("1", "5", "10", "20")]
        applied_state = carry["mpv"]["applied_seek_state"]
        self.result["checks"] = {
            "startup_prompt_absent": bool(self.result["phases"]["startup"]["preflight"])
            and not bool(self.result["phases"]["startup"]["preflight"].get("prompt")),
            "registry_models_healthy": all(self.result["phases"]["startup"]["registry_records"].get(key) == "INSTALLED" for key in MODEL_KEYS),
            "v2_real_drag_to_zero": carry["drag"]["timeline_in_ms"] == 0 and carry["drag"]["linked_audio_timeline_in_ms"] == 0,
            "move_invalidated_composition": carry["drag"]["composition_generation_after"] > carry["drag"]["composition_generation_before"],
            "hide_invalidated_composition": carry["composition_generation_after_hide"] > carry["composition_generation_before_hide"],
            "v2_only_after_move_without_seek": carry["extra_seek_after_hide"] is False and carry["visible_layer_set"] == ["V2"] and carry["chosen_base"]["track_id"] == "V2",
            "v2_mpv_loadfile_start": applied_state.get("command") == "loadfile-start" and int(applied_state.get("generation", -1)) == int(carry["mpv"]["observed_position"].get("source_generation", -2)),
            "v2_first_frame_and_pixels": bool(carry["mpv"]["video_frame_info"]) and carry["pixels"]["nonblack_ratio"] >= 0.05 and carry["pixels"]["mean_luma"] >= 5,
            "stroke_control_canonical_levels": [levels[key]["canonical_width"] for key in ("1", "5", "10", "20")] == [1, 5, 10, 20],
            "stroke_live_strict_order": all(a < b for a, b in zip(live_radii, live_radii[1:])),
            "stroke_fidelity_strict_order": all(a < b for a, b in zip(fidelity_radii, fidelity_radii[1:])),
            "stroke20_not_thin": live_radii[-1] >= 7 and fidelity_radii[-1] >= 7 and abs(live_radii[-1] - fidelity_radii[-1]) <= 3,
            "stroke_no_50ms_thinning": (
                levels["20"]["after_50ms_radius_reference_px"] >= 7
                and abs(
                    levels["20"]["live_radius_reference_px"]
                    - levels["20"]["after_50ms_radius_reference_px"]
                ) <= 3
            ),
            "playing_live_owner": bool(stroke["playing"]["owners"]) and set(stroke["playing"]["owners"]) == {"advanced_live"},
            "paused_fidelity_current_time": stroke["paused"]["owner"] == "advanced_fidelity" and abs(stroke["paused"]["cue_local_ms"] - stroke["paused"]["fidelity_identity_motion_ms"]) <= 40,
            "stroke_seek_reentry_stable": stroke["seek_reentry"]["canonical_width"] == 20 and stroke["seek_reentry"]["pixels"]["visible_pixels"] > 0,
            "three_distinct_art_direction_cards": ai["card_count"] == 3 and len(set(ai["direction_families"])) == 3,
            "card_live_first_frame_budget": ai["card_first_frame_ms"] < 150,
            "play_motion_restarts": ai["play_motion_running_after_350ms"],
            "card_applied_same_graph": (
                ai["applied_graph_hash"] != ai["pre_apply_graph_hash"]
                and ai["card_motion_duration_ms"]
                == ai["applied_motion_duration_ms"]
                == ai["cue_duration_ms"]
            ),
            "applied_motion_visible_through_hold": all(item["visible"] for item in ai["samples"]) and ai["distinct_applied_frames"] >= 2,
            "applied_playback_live_owner": set(item["owner"] for item in ai["playback_samples"]) == {"advanced_live"},
            "applied_live_p95_budget": ai["applied_p95_ms"] < 40,
            "applied_paused_fidelity": ai["paused_fidelity"]["owner"] == "advanced_fidelity" and ai["paused_fidelity"]["pixels"]["visible_pixels"] > 0,
            "project_saved": ai["saved"],
        }

    @staticmethod
    def _applied_graph_matches_card(
        payload: Mapping[str, object],
        card_graph: Mapping[str, object],
        pre_apply_graph_hash: str,
    ) -> bool:
        """Validate semantic graph ownership across the apply transaction."""
        graph = payload.get("visualGraph") if isinstance(payload, Mapping) else {}
        if not isinstance(graph, Mapping) or not isinstance(card_graph, Mapping):
            return False
        try:
            applied_scene = compile_live_scene(graph)
            card_text = card_graph.get("textLayer", {})
            applied_text = graph.get("textLayer", {})
            card_strokes = card_text.get("strokes", []) if isinstance(card_text, Mapping) else []
            applied_strokes = applied_text.get("strokes", []) if isinstance(applied_text, Mapping) else []
            card_motion = card_graph.get("motionGraph", {})
            applied_motion = graph.get("motionGraph", {})
            card_tracks = card_motion.get("tracks", []) if isinstance(card_motion, Mapping) else []
            applied_tracks = applied_motion.get("tracks", []) if isinstance(applied_motion, Mapping) else []
            return bool(
                applied_scene.graph_hash != pre_apply_graph_hash
                and str(graph.get("name", "")) == str(card_graph.get("name", ""))
                and applied_strokes
                and len(applied_strokes) == len(card_strokes)
                and applied_tracks
                and len(applied_tracks) == len(card_tracks)
            )
        except (TypeError, ValueError):
            return False

    def _write(self) -> None:
        self.result_path.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _run(self) -> None:
        try:
            self.result["phases"]["startup"] = self._startup_phase()
            if self.mode == "workflow":
                self._workflow_phase()
            elif self.mode == "reopen":
                self._reopen_phase()
            else:
                raise ValueError(f"unsupported P8B audit mode: {self.mode}")
            self.result["phases"]["windows"] = {
                "qt": qt_top_level_widgets(self.app),
                "win32": win32_top_level_windows(pids={os.getpid()}),
            }
            self.result["accepted"] = all(bool(value) for value in self.result["checks"].values())
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        finally:
            self.result["elapsed_s"] = round(time.time() - self.result["started_at"], 3)
            self._write()
            code = 0 if self.result.get("accepted") else 1
            threading.Thread(
                target=lambda: (time.sleep(1.0), os._exit(code)),
                name="p8b-audit-exit", daemon=True,
            ).start()
            try:
                self.window.close()
            except Exception:
                pass
            self.app.quit()


__all__ = ["P8BRuntimeAudit"]
