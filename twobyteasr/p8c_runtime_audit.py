"""P8C production integration evidence on real Qt widgets and media.

This is automated headed evidence. It never represents a person's acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

import psutil
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

from .main_ui_dialogs import SpringDialog
from .p8b_runtime_audit import P8BRuntimeAudit, _percentile
from .advanced_live_renderer import render_live_snapshot
from .studio_media_pool import (
    audio_master_mode,
    audio_master_track_id,
    effective_audio_master_track_id,
)
from .visual_design_graph import MotionGraph, clean_subtitle_graph, style_recipe_from_graph
from .style_recipe import route_recipe
from .window_audit import qt_top_level_widgets, win32_top_level_windows


def _pixels(image: QImage, path: Path | None = None) -> dict[str, object]:
    if image.isNull():
        return {
            "path": str(path or ""), "visible_pixels": 0,
            "dark_pixels": 0, "white_pixels": 0, "alpha_bounds": None,
        }
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(converted.constBits())[:converted.sizeInBytes()]
    line = converted.bytesPerLine()
    xs: list[int] = []
    ys: list[int] = []
    dark = 0
    white = 0
    for y in range(converted.height()):
        row = y * line
        for x in range(converted.width()):
            red, green, blue, alpha = data[row + x * 4:row + x * 4 + 4]
            if alpha > 8:
                xs.append(x)
                ys.append(y)
            if alpha > 64 and max(red, green, blue) < 90:
                dark += 1
            if alpha > 160 and min(red, green, blue) > 200:
                white += 1
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        converted.save(str(path))
    return {
        "path": str(path or ""),
        "sha256_pixels": hashlib.sha256(data).hexdigest(),
        "size": [converted.width(), converted.height()],
        "visible_pixels": len(xs),
        "dark_pixels": dark,
        "white_pixels": white,
        "alpha_bounds": None if not xs else [min(xs), min(ys), max(xs), max(ys)],
    }


def _file_pixels(path: Path) -> dict[str, object]:
    return _pixels(QImage(str(path)), path)


def _alpha_recovery(transparent: QImage, opaque: QImage) -> dict[str, object]:
    """Measure glyph body restored by opaque fill over the same outside ring."""

    clear = transparent.convertToFormat(QImage.Format.Format_RGBA8888)
    filled = opaque.convertToFormat(QImage.Format.Format_RGBA8888)
    if clear.size() != filled.size() or clear.isNull():
        return {"comparable": False, "recovered_pixels": 0, "recovered_ratio": 0.0}
    clear_data = bytes(clear.constBits())[:clear.sizeInBytes()]
    filled_data = bytes(filled.constBits())[:filled.sizeInBytes()]
    opaque_pixels = 0
    recovered = 0
    for index in range(3, min(len(clear_data), len(filled_data)), 4):
        if filled_data[index] > 160:
            opaque_pixels += 1
            if clear_data[index] <= 25:
                recovered += 1
    return {
        "comparable": True,
        "opaque_pixels": opaque_pixels,
        "recovered_pixels": recovered,
        "recovered_ratio": round(recovered / max(1, opaque_pixels), 4),
    }


def _near_color_pixels(image: QImage, rect: QRect, target: QColor, tolerance: int = 28) -> int:
    total = 0
    for y in range(max(0, rect.top()), min(image.height(), rect.bottom() + 1)):
        for x in range(max(0, rect.left()), min(image.width(), rect.right() + 1)):
            color = image.pixelColor(x, y)
            if max(
                abs(color.red() - target.red()),
                abs(color.green() - target.green()),
                abs(color.blue() - target.blue()),
            ) <= tolerance:
                total += 1
    return total


class P8CRuntimeAudit(P8BRuntimeAudit):
    def __init__(self, window, output_dir: str | os.PathLike[str], *, mode: str) -> None:
        super().__init__(window, output_dir, mode=mode)
        self.result["schema"] = "2byteasr.p8c-runtime-audit.v1"
        self.result["evidence_class"] = (
            "PACKAGED QT REAL-WIDGET AUTOMATION"
            if getattr(sys, "frozen", False)
            else "SOURCE QT REAL-WIDGET AUTOMATION"
        )

    def _stroke_checkpoint(self, label: str) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        snapshot = getattr(page, "_advanced_preview_snapshot", None)
        identity = getattr(page._advanced_preview_state, "identity", None)
        strokes = list(getattr(snapshot, "strokes", ()) or ())
        style_recipe = getattr(snapshot, "style_recipe", {}) or {}
        graph = style_recipe.get("visualGraph", {}) if isinstance(style_recipe, Mapping) else {}
        graph_strokes = (
            graph.get("textLayer", {}).get("strokes", [])
            if isinstance(graph, Mapping) else []
        )
        return {
            "label": label,
            "cue_id": cue.id,
            "generation": int(page._advanced_preview_state.generation),
            "identity": asdict(identity) if identity is not None else None,
            "snapshot_hash": snapshot.stable_hash() if snapshot is not None else "",
            "graph_hash": hashlib.sha256(
                json.dumps(graph, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest() if graph else "",
            "request_key": str(page._advanced_preview_expected_key),
            "project_ms": int(page.timeline.playhead_ms),
            "cue_local_ms": int(page.timeline.playhead_ms) - int(cue.start_ms),
            "owner_kind": str(getattr(page, "_advanced_canvas_source_kind", "")),
            "foreground_owner": page.subtitle_visibility_trace(
                reason=f"p8c-stroke-{label}"
            ).get("foreground_owner"),
            "canonical_stroke": float(strokes[0].get("width", -1)) if strokes else -1,
            "snapshot_strokes": strokes,
            "graph_strokes": graph_strokes,
            "pixels": _pixels(
                page.advanced_cue_overlay._source_image,
                self.screenshots / f"p8c-stroke20-{label}.png",
            ),
        }

    def _stroke_phase(self) -> dict[str, object]:
        result = super()._stroke_phase()
        page = self.page
        cue = page.project.cues[0]
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        page._seek((cue.start_ms + 700) / 1000.0)
        self._pump(250)
        self._wait(
            lambda: (
                page._advanced_preview_snapshot is not None
                and bool(page._advanced_preview_snapshot.strokes)
                and float(page._advanced_preview_snapshot.strokes[0]["width"]) == 20
                and page._advanced_canvas_source_kind in {"live", "fidelity"}
            ),
            4,
            "stroke 20 owner before 3s settled stability",
        )
        started = time.perf_counter()
        checkpoints = [self._stroke_checkpoint("0ms")]
        elapsed = 0
        for target, label in (
            (16, "16ms"), (50, "50ms"), (100, "100ms"),
            (250, "250ms"), (500, "500ms"), (1000, "1s"),
            (2000, "2s"), (3000, "3s"), (5000, "5s"), (10000, "10s"),
        ):
            self._pump(target - elapsed)
            elapsed = target
            checkpoints.append(self._stroke_checkpoint(label))
        result["ownership_checkpoints"] = checkpoints
        result["checkpoint_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result["stroke_20_stable_10s"] = all(
            item["canonical_stroke"] == 20
            and item["graph_strokes"]
            and float(item["graph_strokes"][0]["width"]) == 20
            and 0 <= item["cue_local_ms"] < cue.end_ms - cue.start_ms
            and item["pixels"]["visible_pixels"] > 0
            for item in checkpoints
        )
        result["stroke_20_stable_3s"] = result["stroke_20_stable_10s"]
        result["transparent_fill"] = self._transparent_stroke_phase()
        return result

    def _outside_fill_fixture(self, color: str, label: str) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        graph = clean_subtitle_graph()
        graph.text_layer.font.update({
            "family": "Source Han Sans Heavy", "size": 115, "weight": 900,
        })
        graph.text_layer.fill = {"type": "solid", "color": color}
        graph.text_layer.strokes = [
            {"color": "#FF000000", "width": 20, "opacity": 1, "alignment": "OUTSIDE"}
        ]
        graph.text_layer.shadow = {}
        graph.text_layer.glow = {}
        graph.motion_graph = MotionGraph(max(1, cue.end_ms - cue.start_ms), [])
        # The ring is an Advanced renderer contract. Keep the fixture on that
        # route even though the glyph has no motion/effect capability gaps.
        recipe = style_recipe_from_graph(graph)
        recipe.engine = "remotion"
        page._apply_style_recipe(cue.id, recipe)
        page._load_style_inspector()
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        page._seek((cue.start_ms + 700) / 1000.0)
        self._wait(
            lambda: (
                page._advanced_preview_snapshot is not None
                and bool(page._advanced_preview_snapshot.strokes)
                and float(page._advanced_preview_snapshot.strokes[0]["width"]) == 20
            ),
            8,
            f"{label} outside snapshot",
        )
        snapshot = page._advanced_preview_snapshot
        live = render_live_snapshot(
            snapshot,
            width=1280,
            height=720,
            layers=frozenset({"text"}),
        )
        live_path = self.screenshots / f"outside-{label}-live.png"
        live_metrics = _pixels(live, live_path)
        fidelity_path, wait_ms = self._wait_fidelity(20)
        fidelity_copy = self.screenshots / f"outside-{label}-fidelity.png"
        fidelity_copy.write_bytes(fidelity_path.read_bytes())
        return {
            "snapshot": snapshot,
            "live_image": live,
            "fidelity_image": QImage(str(fidelity_copy)),
            "live": live_metrics,
            "fidelity": _file_pixels(fidelity_copy),
            "fidelity_wait_ms": wait_ms,
            "foreground_owner": page.subtitle_visibility_trace(
                reason=f"outside-{label}"
            ).get("foreground_owner"),
        }

    def _transparent_stroke_phase(self) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        fixture_text = "0 8 B 中 口 回"
        original_text = cue.text
        page.cue_controller.set_text(
            cue.id,
            fixture_text,
            command_text="P8C transparent outside-stroke fixture",
        )
        self._wait(
            lambda: (
                page._advanced_preview_snapshot is not None
                and page._advanced_preview_snapshot.text == fixture_text
            ),
            8,
            "counter-glyph outside-stroke fixture",
        )
        try:
            opaque = self._outside_fill_fixture("#FFFFFFFF", "opaque")
            transparent = self._outside_fill_fixture("#00FFFFFF", "transparent")
            live_recovery = _alpha_recovery(
                transparent["live_image"], opaque["live_image"]
            )
            fidelity_recovery = _alpha_recovery(
                transparent["fidelity_image"], opaque["fidelity_image"]
            )
            return {
                "fixture": {
                    "font": "Source Han Sans Heavy",
                    "text": fixture_text,
                    "fill": "#00FFFFFF",
                    "stroke": "#FF000000",
                    "stroke_width": 20,
                    "alignment": "OUTSIDE",
                },
                "opaque": {key: value for key, value in opaque.items() if not key.endswith("_image") and key != "snapshot"},
                "transparent": {key: value for key, value in transparent.items() if not key.endswith("_image") and key != "snapshot"},
                "live_alpha_recovery": live_recovery,
                "fidelity_alpha_recovery": fidelity_recovery,
                "verified": bool(
                    transparent["live"]["visible_pixels"] > 0
                    and transparent["fidelity"]["visible_pixels"] > 0
                    and live_recovery["recovered_pixels"] > 100
                    and fidelity_recovery["recovered_pixels"] > 100
                    and live_recovery["recovered_ratio"] >= 0.20
                    and fidelity_recovery["recovered_ratio"] >= 0.20
                ),
            }
        finally:
            page.cue_controller.set_text(
                cue.id,
                original_text,
                command_text="Restore cue after P8C outside-stroke fixture",
            )
            self._wait(
                lambda: self._restore_text_route_ready(cue.id, original_text),
                8,
                "restore cue after counter-glyph fixture",
            )

    def _restore_text_route_ready(self, cue_id: str, original_text: str) -> bool:
        """Accept the route that owns the restored cue after a fixture.

        Outside-stroke fixtures deliberately use a native-compatible recipe
        after the final apply. In that state the Advanced snapshot is allowed
        to remain as a warm cache object, but it is not the active source of
        truth. Waiting for its text would report a false timeout even though
        ASS/native ownership has already been restored.
        """
        page = self.page
        cue = next(
            (item for item in getattr(page.project, "cues", ()) if item.id == cue_id),
            None,
        )
        if cue is None or cue.text != original_text:
            return False
        payload = page.project.style_recipes.get(cue.style_id, {})
        advanced = bool(
            isinstance(payload, Mapping)
            and payload
            and route_recipe(payload).engine == "remotion"
        )
        if advanced:
            snapshot = getattr(page, "_advanced_preview_snapshot", None)
            return bool(
                snapshot is not None
                and snapshot.cue_id == cue_id
                and snapshot.text == original_text
            )
        # Native ownership is complete once Advanced no longer suppresses the
        # cue and the owner has switched away from an Advanced layer. The
        # native track's observed property can lag the command by a frame, so
        # do not make that asynchronous observation a hard prerequisite here.
        owner = page.subtitle_visibility_trace(
            reason="p8c-restore-native-check"
        ).get("foreground_owner")
        return cue_id not in getattr(page, "_advanced_ass_hidden", set()) and owner in {
            "native", "none",
        }

    def _apply_shadow_graph(self, *, enabled: bool) -> dict[str, object]:
        page = self.page
        cue = page.project.cues[0]
        graph = clean_subtitle_graph()
        graph.text_layer.font.update({"family": "Arial", "size": 115, "weight": 700})
        graph.text_layer.fill = {"type": "solid", "color": "#FFFFFFFF"}
        graph.text_layer.strokes = [
            {"color": "#FF000000", "width": 10, "opacity": 1, "alignment": "OUTSIDE"}
        ]
        graph.text_layer.glow = {}
        graph.text_layer.shadow = (
            {
                "enabled": True,
                "color": "#FF000000",
                "opacity": 0.8,
                "offset_x": 12,
                "offset_y": 12,
                "blur_radius": 12,
                "blur": 12,
                "spread": 2,
            }
            if enabled else {}
        )
        graph.motion_graph = MotionGraph(2_400, [])
        recipe = style_recipe_from_graph(graph)
        # Shadow pixels are measured from the Advanced LIVE/Fidelity pair.
        # An empty motion graph is otherwise a valid native recipe, which
        # would leave this audit waiting for a snapshot that cannot exist.
        recipe.engine = "remotion"
        page._apply_style_recipe(cue.id, recipe)
        page._load_style_inspector()
        page._seek((cue.start_ms + 700) / 1000.0)
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: (
                page._advanced_preview_snapshot is not None
                and bool(page._advanced_preview_snapshot.strokes)
                and abs(float(page._advanced_preview_snapshot.strokes[0]["width"]) - 10) < 0.01
                and bool(page._advanced_preview_snapshot.shadow.get("enabled", False)) == enabled
            ),
            8,
            "shadow snapshot",
        )
        self._wait(
            lambda: page._advanced_canvas_source_kind == "live",
            8,
            "shadow LIVE",
        )
        live = _pixels(
            page.advanced_cue_overlay._source_image,
            self.screenshots / f"shadow-{'on' if enabled else 'off'}-live.png",
        )
        fidelity_path, wait_ms = self._wait_fidelity(10)
        fidelity_copy = self.screenshots / f"shadow-{'on' if enabled else 'off'}-fidelity.png"
        fidelity_copy.write_bytes(fidelity_path.read_bytes())
        snapshot = page._advanced_preview_snapshot
        graph_shadow = snapshot.style_recipe["visualGraph"]["textLayer"].get("shadow", {})
        return {
            "enabled": enabled,
            "canonical": dict(snapshot.shadow),
            "graph": dict(graph_shadow),
            "live": live,
            "fidelity": _file_pixels(fidelity_copy),
            "fidelity_wait_ms": wait_ms,
            "owner": page.subtitle_visibility_trace(
                reason=f"p8c-shadow-{'on' if enabled else 'off'}"
            ).get("foreground_owner"),
        }

    @staticmethod
    def _growth(on: Mapping[str, object], off: Mapping[str, object]) -> dict[str, object]:
        on_bounds = on.get("alpha_bounds")
        off_bounds = off.get("alpha_bounds")
        bounds_growth = [0, 0, 0, 0]
        if isinstance(on_bounds, list) and isinstance(off_bounds, list):
            bounds_growth = [
                off_bounds[0] - on_bounds[0], off_bounds[1] - on_bounds[1],
                on_bounds[2] - off_bounds[2], on_bounds[3] - off_bounds[3],
            ]
        return {
            "dark_pixel_growth": int(on.get("dark_pixels", 0)) - int(off.get("dark_pixels", 0)),
            "visible_pixel_growth": int(on.get("visible_pixels", 0)) - int(off.get("visible_pixels", 0)),
            "bounds_growth": bounds_growth,
        }

    def _shadow_phase(self) -> dict[str, object]:
        off = self._apply_shadow_graph(enabled=False)
        on = self._apply_shadow_graph(enabled=True)
        live_growth = self._growth(on["live"], off["live"])
        fidelity_growth = self._growth(on["fidelity"], off["fidelity"])
        return {
            "fixture": {
                "font_size": 115, "fill": "#FFFFFFFF", "stroke": 10,
                "shadow": {
                    "color": "#FF000000", "opacity": 0.8,
                    "offset_x": 12, "offset_y": 12,
                    "blur_radius": 12, "spread": 2,
                    "units": "reference-video px",
                },
                "draw_order": ["shadow", "outline", "fill"],
            },
            "off": off,
            "on": on,
            "live_growth": live_growth,
            "fidelity_growth": fidelity_growth,
            "visible": bool(
                live_growth["dark_pixel_growth"] > 0
                and fidelity_growth["dark_pixel_growth"] > 0
                and max(live_growth["bounds_growth"][2:]) > 0
                and max(fidelity_growth["bounds_growth"][2:]) > 0
            ),
        }

    def _select_combo_item(self, combo, data: str) -> None:
        index = combo.findData(data)
        if index < 0:
            raise ValueError(f"combo item is missing: {data}")
        combo.showPopup()
        self._pump(60)
        view = combo.view()
        model_index = combo.model().index(index, 0)
        view.scrollTo(model_index)
        view.setCurrentIndex(model_index)
        QTest.keyClick(view, Qt.Key.Key_Return)
        self._pump(80)

    def _audio_state(self, label: str) -> dict[str, object]:
        page = self.page
        decision = page._audio_playback_decision
        controller = page.video.controller
        desired = getattr(controller, "_desired_commands", {}).get("audio-output")
        players = {}
        for clip_id, runtime in page.video_compositor._players.items():
            players[str(clip_id)] = {
                "path": str(runtime.path),
                "state": str(runtime.state),
                "audio_output_attached": bool(runtime.audio_output_attached),
                "video_output_attached": bool(runtime.video_output_attached),
                "playback_state": str(runtime.playback_state),
            }
        return {
            "label": label,
            "project_ms": int(page.timeline.playhead_ms),
            "configured_master": audio_master_track_id(page.project),
            "master_mode": audio_master_mode(page.project),
            "effective_master": decision.master_track_id,
            "decision": asdict(decision),
            "audio_engine": page.audio_engine.telemetry_snapshot(),
            "mpv_audio_enabled": page._active_mpv_audio_enabled,
            "mpv_desired_command": desired,
            "secondary_players": players,
            "attached_secondary_outputs": sum(
                item["audio_output_attached"] for item in players.values()
            ),
            "video_visibility": {
                item.id: bool(item.enabled) for item in page.project.video_tracks
            },
        }

    def _resource_state(self, label: str) -> dict[str, object]:
        page = self.page
        process = psutil.Process(os.getpid())
        memory = process.memory_info()
        players = {}
        for clip_id, runtime in page.video_compositor._players.items():
            worker = runtime._worker
            players[str(clip_id)] = {
                "path": str(runtime.path or runtime._pending_path),
                "state": str(runtime.state),
                "audio_output_attached": bool(runtime.audio_output_attached),
                "video_output_attached": bool(runtime.video_output_attached),
                "playback_state": str(runtime.playback_state),
                "generation": int(runtime.generation),
                "delivered_frames": len(runtime.samples),
                "frame_delivery_pending": bool(worker._frame_delivery_pending),
                "latest_frame_pending": worker._latest_frame is not None,
            }
        with page._waveform_inflight_lock:
            waveform_threads = tuple(page._waveform_threads)
        return {
            "label": label,
            "elapsed_s": round(time.perf_counter() - self._memory_started, 3),
            "rss_bytes": int(memory.rss),
            "private_bytes": int(getattr(memory, "private", 0)),
            "process_threads": process.num_threads(),
            "python_threads": [item.name for item in threading.enumerate()],
            "waveform_threads_alive": sum(item.is_alive() for item in waveform_threads),
            "player_count": len(players),
            "players": players,
            "composition": page.video_compositor.performance_snapshot(),
            "audio_decision": asdict(page._audio_playback_decision),
            "mpv_path": str(page.video.controller.observed_property("path", "")),
            "mpv_audio_enabled": bool(page._active_mpv_audio_enabled),
        }

    @staticmethod
    def _memory_slope(samples: list[dict[str, object]], key: str) -> float:
        if len(samples) < 2:
            return 0.0
        xs = [float(item["elapsed_s"]) for item in samples]
        ys = [float(item[key]) for item in samples]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denominator = sum((value - x_mean) ** 2 for value in xs)
        if denominator <= 0:
            return 0.0
        return sum(
            (x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)
        ) / denominator

    def _memory_phase(self) -> None:
        page = self.page
        self.window.setGeometry(40, 30, 1680, 1020)
        self.window.showNormal()
        self._wait(lambda: page.project is not None and bool(page.project.cues), 30, "project")
        self._wait(
            lambda: page.video.controller is not None and page.video.controller.running,
            20,
            "mpv",
        )
        carryover = self._carryover_phase()
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: not page.video.playback_position_snapshot().paused,
            4,
            "carryover playback",
        )
        self._memory_started = time.perf_counter()
        samples = [self._resource_state("0s")]
        self.result["phases"]["memory"] = {
            "probe_state": "sampling",
            "carryover": carryover,
            "samples": samples,
        }
        self._write()
        for second in range(1, 61):
            self._pump(1_000)
            samples.append(self._resource_state(f"{second}s"))
            if second % 5 == 0:
                self._write()
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        tail = [item for item in samples if float(item["elapsed_s"]) >= 30.0]
        rss_slope = self._memory_slope(tail, "rss_bytes")
        private_slope = self._memory_slope(tail, "private_bytes")
        peak_rss = max(int(item["rss_bytes"]) for item in samples)
        peak_private = max(int(item["private_bytes"]) for item in samples)
        tail_rss_growth = int(tail[-1]["rss_bytes"]) - int(tail[0]["rss_bytes"])
        phase = self.result["phases"]["memory"]
        phase.update({
            "probe_state": "complete",
            "peak_rss_bytes": peak_rss,
            "peak_private_bytes": peak_private,
            "tail_rss_growth_bytes": tail_rss_growth,
            "tail_rss_slope_bytes_per_s": round(rss_slope, 3),
            "tail_private_slope_bytes_per_s": round(private_slope, 3),
        })
        final_players = samples[-1]["players"]
        audio_only = [
            item for item in final_players.values()
            if item["audio_output_attached"] and not item["video_output_attached"]
        ]
        self.result["checks"] = {
            "carryover_v2_base": carryover["chosen_base"]["track_id"] == "V2",
            "audio_master_v1": samples[-1]["audio_decision"]["audible_track_id"] == "V1",
            "one_audio_only_secondary": len(audio_only) == 1,
            "audio_only_delivers_no_video_frames": all(
                int(item["delivered_frames"]) == 0 for item in audio_only
            ),
            "peak_rss_under_3gb": 0 < peak_rss < 3 * 1024 ** 3,
            "tail_rss_growth_under_64mb": tail_rss_growth <= 64 * 1024 ** 2,
            "tail_rss_slope_under_1mb_s": rss_slope <= 1024 ** 2,
            "tail_private_slope_under_1mb_s": private_slope <= 1024 ** 2,
        }

    def _audio_probe(self, label: str) -> dict[str, object]:
        state = self._audio_state(label)
        phase = self.result["phases"].setdefault("audio", {})
        phase["probe_state"] = label
        phase.setdefault("states", {})[label] = state
        self._write()
        self._pump(1_800)
        state = self._audio_state(label)
        phase["states"][label] = state
        self._write()
        return state

    def _audio_phase(self) -> dict[str, object]:
        page = self.page
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        if not self._track(page.project, "V1").enabled:
            self._toggle_track("V1")
            self._wait(lambda: self._track(page.project, "V1").enabled, 5, "show V1")
        page._refresh_video_transform_panel()
        self._select_combo_item(page.video_audio_mode, "follow_active_video")
        self._wait(
            lambda: audio_master_mode(page.project) == "follow_active_video",
            4,
            "Follow Active Video mode",
        )
        page._seek(1.0)
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._pump(700)
        self._toggle_track("V1")
        self._wait(lambda: not self._track(page.project, "V1").enabled, 5, "V2-only hide V1")
        page._sync_multitrack_preview_at(int(page.timeline.playhead_ms))
        self._wait(
            lambda: (
                page._audio_playback_decision.audible_track_id == "V2"
                and page.audio_engine.telemetry_snapshot().get("windows_sink_count") == 1
                and int(page.audio_engine.telemetry_snapshot().get("sink_consumed_bytes", 0)) > 0
                and float(page.audio_engine.telemetry_snapshot().get("sink_consumed_rms", 0.0)) > 0.001
            ),
            15,
            "V2-only dedicated audio engine",
        )
        initial = self._audio_probe("V2_FOLLOW_ACTIVE")
        profile: list[float] = []
        samples = [initial]
        start_playhead = int(page.timeline.playhead_ms)
        start_underruns = int(initial["audio_engine"].get("underruns", 0))
        phase = self.result["phases"].setdefault("audio", {})
        phase.update({"probe_state": "V2_FOLLOW_60S", "states": {"V2_FOLLOW_ACTIVE": initial}})
        self._write()
        for second in range(1, 61):
            self._pump(1_000, profile)
            sample = self._audio_state(f"V2_{second}s")
            samples.append(sample)
            if second % 5 == 0:
                phase["samples"] = samples
                self._write()
        v2_end = samples[-1]

        self._select_combo_item(page.video_audio_mode, "manual")
        self._select_combo_item(page.video_audio_master, "V1")
        self._wait(
            lambda: (
                audio_master_mode(page.project) == "manual"
                and page._audio_playback_decision.audible_track_id == "V1"
            ),
            10,
            "Manual V1 audio master",
        )
        manual = self._audio_probe("MANUAL_V1")
        self._select_combo_item(page.video_audio_mode, "follow_active_video")
        self._wait(
            lambda: page._audio_playback_decision.audible_track_id == "V2",
            10,
            "Follow mode restores V2",
        )
        follow_restored = self._audio_probe("FOLLOW_RESTORED_V2")
        final_underruns = int(v2_end["audio_engine"].get("underruns", 0))
        v2_sources = {
            str(item["decision"].get("source_path") or "").casefold()
            for item in samples[1:]
        }
        return {
            "probe_state": "complete",
            "states": {
                "V2_FOLLOW_ACTIVE": initial,
                "V2_60S_END": v2_end,
                "MANUAL_V1": manual,
                "FOLLOW_RESTORED_V2": follow_restored,
            },
            "samples": samples,
            "playhead_advance_ms": int(v2_end["project_ms"]) - start_playhead,
            "event_loop_p95_ms": _percentile(profile, 0.95),
            "event_loop_max_ms": round(max(profile, default=0.0), 3),
            "underrun_growth": final_underruns - start_underruns,
            "v2_source_paths": sorted(v2_sources),
            "actual_pcm_consumed": all(
                int(item["audio_engine"].get("sink_consumed_bytes", 0)) > 0
                and float(item["audio_engine"].get("sink_consumed_rms", 0.0)) > 0.001
                and bool(item["audio_engine"].get("output_format"))
                for item in samples[1:]
            ),
            "one_dedicated_sink": all(
                item["decision"]["mpv_output_enabled"] is False
                and item["mpv_audio_enabled"] is False
                and item["attached_secondary_outputs"] == 0
                and int(item["audio_engine"].get("windows_sink_count", 0)) == 1
                for item in samples[1:]
            ),
            "follow_active_video": all(
                item["master_mode"] == "follow_active_video"
                and item["decision"]["audible_track_id"] == "V2"
                and item["video_visibility"] == {"V1": False, "V2": True}
                for item in samples
            ),
            "manual_mode": bool(
                manual["master_mode"] == "manual"
                and manual["decision"]["audible_track_id"] == "V1"
                and follow_restored["master_mode"] == "follow_active_video"
                and follow_restored["decision"]["audible_track_id"] == "V2"
            ),
            "v2_continuous_60s": bool(
                int(v2_end["project_ms"]) - start_playhead >= 55_000
                and final_underruns == start_underruns
                and len(v2_sources) == 1
                and all(item["decision"]["audible_track_id"] == "V2" for item in samples)
                and all(
                    int(item["audio_engine"].get("sink_consumed_bytes", 0)) > 0
                    and float(item["audio_engine"].get("sink_consumed_rms", 0.0)) > 0.001
                    for item in samples[1:]
                )
            ),
            "responsive_60s": bool(
                _percentile(profile, 0.95) < 16.7
                and max(profile, default=0.0) < 100.0
            ),
        }

    def _provider_phase(self) -> dict[str, object]:
        page = self.page
        page.context_drawer.setCurrentIndex(0)
        self._select_combo_item(page.ai_provider, "gemini")
        self._wait(
            lambda: page.runtime_settings.get("models", {}).get("polish_provider") == "gemini",
            4,
            "Gemini provider selection",
        )
        models = page.runtime_settings["models"]
        return {
            "event_path": "QComboBox popup + QTest Key_Return on provider item",
            "provider": page.ai_provider.currentData(),
            "model": page.ai_model.currentText(),
            "capabilities": page.ai_provider_capabilities.text(),
            "polish": {
                key: models.get(f"polish_{key}")
                for key in ("transport", "provider", "base_url", "model", "capabilities")
            },
            "group": {
                key: models.get(f"group_{key}")
                for key in ("transport", "provider", "base_url", "model", "capabilities")
            },
            "verified": bool(
                page.ai_provider.currentData() == "gemini"
                and page.ai_model.currentText() == "gemini-3.7-flash-high"
                and "Vision" in page.ai_provider_capabilities.text()
            ),
        }

    def _timeline_hover_phase(self) -> dict[str, object]:
        timeline = self.page.timeline
        timeline.show()
        self._pump(80)
        palette = timeline._timeline_palette()
        icon_color = QColor(palette.header_icon)
        video_rects = timeline._video_track_rects()
        audio_rects = timeline._audio_track_rects()
        speaker_id, speaker_rect = next(iter(timeline._track_layout()[0].items()))
        controls = [
            (f"video:{track_id}:{action}", left, track_rect, 14)
            for track_id, track_rect in video_rects.items()
            for action, left in (("enabled", 132), ("muted", 156), ("locked", 180), ("more", 204))
        ] + [
            (f"audio:{track_id}:{action}", left, track_rect, 18)
            for track_id, track_rect in audio_rects.items()
            for action, left in (("muted", 108), ("solo", 136), ("master", 164))
        ] + [
            (f"speaker:{speaker_id}:{action}", left, speaker_rect, 19)
            for action, left in (("visibility", 150), ("lock", 178), ("more", 206))
        ]
        rows = []
        for name, left, track_rect, y_offset in controls:
            QTest.mouseMove(
                timeline,
                QPoint(left + 10, round(track_rect.center().y())),
            )
            self._pump(30)
            initial_image = timeline.grab().toImage()
            # Hold each state for the full human-reported disappearance window.
            # Repeated paints/timers during this period must keep a non-null
            # cached icon rather than clearing while a variant is generated.
            self._pump(5_000)
            image = timeline.grab().toImage()
            ratio = max(1.0, float(image.devicePixelRatio()))
            logical = QRect(
                left + 3,
                round(track_rect.top()) + y_offset - 8,
                19,
                24,
            )
            physical = QRect(
                round(logical.x() * ratio),
                round(logical.y() * ratio),
                max(1, round(logical.width() * ratio)),
                max(1, round(logical.height() * ratio)),
            ).intersected(image.rect())
            rows.append({
                "control": name,
                "logical_rect": list(logical.getRect()),
                "physical_rect": list(physical.getRect()),
                "device_pixel_ratio": ratio,
                "hover_duration_ms": 5_000,
                "initial_icon_pixels": _near_color_pixels(initial_image, physical, icon_color),
                "icon_pixels": _near_color_pixels(image, physical, icon_color),
            })
        timeline.grab().save(str(self.screenshots / "timeline-hover-final.png"))
        return {
            "event_path": "QTest mouseMove over custom-painted timeline controls",
            "controls": rows,
            "verified": bool(rows and all(
                int(item["initial_icon_pixels"]) >= 2
                and int(item["icon_pixels"]) >= 2
                and int(item["hover_duration_ms"]) >= 5_000
                for item in rows
            )),
        }

    def _ai_motion_phase(self) -> dict[str, object]:
        provider = self._provider_phase()
        result = super()._ai_motion_phase()
        useful_widths = []
        for index, label in enumerate(self.page._ai_variant_preview_labels):
            pixmap = label.pixmap()
            if pixmap is None or pixmap.isNull():
                continue
            metrics = _pixels(
                pixmap.toImage(),
                self.screenshots / f"p8c-ai-card-{index + 1}.png",
            )
            bounds = metrics["alpha_bounds"]
            ratio = (
                (bounds[2] - bounds[0] + 1) / max(1, metrics["size"][0])
                if bounds else 0.0
            )
            useful_widths.append(round(ratio, 3))
        result["provider_selector"] = provider
        result["card_useful_width_ratios"] = useful_widths
        result["card_useful_width_verified"] = bool(
            useful_widths and all(0.40 <= value <= 0.70 for value in useful_widths)
        )
        return result

    def _workflow_phase(self) -> None:
        super()._workflow_phase()
        self.result["phases"]["shadow"] = self._shadow_phase()
        self.result["phases"]["timeline_hover"] = self._timeline_hover_phase()
        self.result["phases"]["audio"] = self._audio_phase()
        self.result["checks"].update({
            "true_outside_transparent_fill": bool(
                self.result["phases"]["stroke"]["transparent_fill"]["verified"]
            ),
            "stroke_stable_after_10s": bool(
                self.result["phases"]["stroke"]["stroke_20_stable_10s"]
            ),
            "shadow_pixel_visible": bool(self.result["phases"]["shadow"]["visible"]),
            "timeline_icons_hover_visible": bool(
                self.result["phases"]["timeline_hover"]["verified"]
            ),
            "one_dedicated_audio_sink": bool(
                self.result["phases"]["audio"]["one_dedicated_sink"]
            ),
            "audio_sink_consumed_non_silent_pcm": bool(
                self.result["phases"]["audio"]["actual_pcm_consumed"]
            ),
            "audio_follow_active_video": bool(
                self.result["phases"]["audio"]["follow_active_video"]
            ),
            "audio_manual_mode": bool(
                self.result["phases"]["audio"]["manual_mode"]
            ),
            "v2_only_audio_60s": bool(
                self.result["phases"]["audio"]["v2_continuous_60s"]
            ),
            "v2_playback_responsive": bool(
                self.result["phases"]["audio"]["responsive_60s"]
            ),
            "ai_provider_selector": bool(
                self.result["phases"]["ai_motion"]["provider_selector"]["verified"]
            ),
            "ai_card_useful_width": bool(
                self.result["phases"]["ai_motion"]["card_useful_width_verified"]
            ),
        })

    def _motion_profile(self) -> dict[str, object]:
        app = self.app
        first_open_samples: list[float] = []
        popup = self.window.language_combo

        # Keep native-window initialization visible as a separate diagnostic,
        # then gate the reusable surfaces on a second, steady-state opening.
        popup.showPopup()
        first_open_popup_motion = popup._popup._animation is not None
        self._pump(280, first_open_samples)
        popup.hidePopup()
        self._pump(24)

        dialog = SpringDialog(self.window)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("P8C motion audit"))
        dialog.resize(320, 140)
        dialog.show()
        first_open_dialog_motion = getattr(dialog, "_entrance_motion", None) is not None
        self._pump(220, first_open_samples)
        dialog.hide()
        self._pump(24)

        # Packaged startup can still be completing capability probes after the
        # first native popup/dialog creation. Keep that cost in the first-open
        # diagnostic, then measure reusable motion after the startup work has
        # had a bounded interval to settle.
        steady_state_settle_ms = 1_000
        self._pump(steady_state_settle_ms)

        popup_samples: list[float] = []
        popup.showPopup()
        popup_motion = popup._popup._animation is not None
        self._pump(280, popup_samples)
        popup.hidePopup()
        self._pump(24)

        dialog_samples: list[float] = []
        dialog.show()
        dialog_motion = getattr(dialog, "_entrance_motion", None) is not None
        self._pump(220, dialog_samples)
        dialog.hide()
        self._pump(24)
        samples = [*popup_samples, *dialog_samples]

        app.setProperty("reduceMotion", True)
        reduced_popup = self.window.language_combo
        reduced_popup.showPopup()
        self._pump(20)
        reduced_popup_immediate = reduced_popup._popup._animation is None
        reduced_popup.hidePopup()
        reduced_dialog = SpringDialog(self.window)
        reduced_dialog.show()
        self._pump(20)
        reduced_dialog_immediate = getattr(reduced_dialog, "_entrance_motion", None) is None
        reduced_dialog.close()
        dialog.close()
        app.setProperty("reduceMotion", False)
        return {
            "popup_motion": popup_motion,
            "dialog_motion": dialog_motion,
            "properties": ["opacity", "translate 6px"],
            "duration_ms": 180,
            "easing": "OutCubic",
            "first_open_popup_motion": first_open_popup_motion,
            "first_open_dialog_motion": first_open_dialog_motion,
            "first_open_event_loop_p95_ms": _percentile(first_open_samples, 0.95),
            "first_open_event_loop_max_ms": round(max(first_open_samples, default=0.0), 3),
            "steady_state_settle_ms": steady_state_settle_ms,
            "popup_event_loop_p95_ms": _percentile(popup_samples, 0.95),
            "popup_event_loop_max_ms": round(max(popup_samples, default=0.0), 3),
            "dialog_event_loop_p95_ms": _percentile(dialog_samples, 0.95),
            "dialog_event_loop_max_ms": round(max(dialog_samples, default=0.0), 3),
            "event_loop_p95_ms": _percentile(samples, 0.95),
            "event_loop_max_ms": round(max(samples, default=0.0), 3),
            "reduced_popup_immediate": reduced_popup_immediate,
            "reduced_dialog_immediate": reduced_dialog_immediate,
            "native_mpv_geometry_animated": False,
        }

    def _header_phase(self) -> None:
        window = self.window
        window.pages.setCurrentWidget(window.settings_scroll)
        window.setGeometry(40, 30, 1400, 880)
        window.showNormal()
        self._pump(250)
        mascot = window.header_mascot
        brand = window.brand
        mascot_rect = QRect(mascot.mapTo(window.app_header, QPoint()), mascot.size())
        brand_rect = QRect(brand.mapTo(window.app_header, QPoint()), brand.size())
        screenshot = self.screenshots / "p8c-header.png"
        window.grab().save(str(screenshot))
        screen = window.screen() or QApplication.primaryScreen()
        motion = self._motion_profile()
        mascot_pixmap = mascot.pixmap()
        pixmap_dpr = max(1.0, float(mascot_pixmap.devicePixelRatio()))
        pixmap_physical_size = [mascot_pixmap.width(), mascot_pixmap.height()]
        pixmap_logical_size = [
            round(mascot_pixmap.width() / pixmap_dpr, 3),
            round(mascot_pixmap.height() / pixmap_dpr, 3),
        ]
        pixmap_physical_capacity = [
            math.ceil(mascot.width() * pixmap_dpr),
            math.ceil(mascot.height() * pixmap_dpr),
        ]
        header = {
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", ""),
            "device_pixel_ratio": float(screen.devicePixelRatio()) if screen else 1.0,
            "header_rect": [
                window.app_header.x(), window.app_header.y(),
                window.app_header.width(), window.app_header.height(),
            ],
            "mascot_rect": [mascot_rect.x(), mascot_rect.y(), mascot_rect.width(), mascot_rect.height()],
            "brand_rect": [brand_rect.x(), brand_rect.y(), brand_rect.width(), brand_rect.height()],
            "pixmap_device_pixel_ratio": pixmap_dpr,
            "pixmap_physical_size": pixmap_physical_size,
            "pixmap_physical_capacity": pixmap_physical_capacity,
            "pixmap_logical_size": pixmap_logical_size,
            "mascot_inside_header": window.app_header.rect().contains(mascot_rect),
            "mascot_brand_overlap": mascot_rect.intersects(brand_rect),
            "mascot_brand_gap": brand_rect.left() - mascot_rect.right() - 1,
            "pixmap_inside_label": (
                pixmap_physical_size[0] <= pixmap_physical_capacity[0]
                and pixmap_physical_size[1] <= pixmap_physical_capacity[1]
            ),
            "screenshot": str(screenshot),
        }
        self.result["phases"]["header"] = header
        self.result["phases"]["ui_motion"] = motion
        self.result["checks"] = {
            "logo_complete_no_overlap": bool(
                header["mascot_inside_header"]
                and not header["mascot_brand_overlap"]
                and header["pixmap_inside_label"]
            ),
            "logo_human_scale_layout": bool(
                header["pixmap_logical_size"][1] >= 72
                and 8 <= header["mascot_brand_gap"] <= 16
            ),
            "ui_motion_performance": bool(
                motion["popup_motion"]
                and motion["dialog_motion"]
                and motion["event_loop_p95_ms"] < 16.7
                and motion["event_loop_max_ms"] < 50
            ),
            "reduced_motion": bool(
                motion["reduced_popup_immediate"]
                and motion["reduced_dialog_immediate"]
            ),
            "mpv_geometry_not_animated": motion["native_mpv_geometry_animated"] is False,
        }

    def _audio_runtime_sample(self, label: str) -> dict[str, object]:
        """Capture the single ProjectClock path for a real audio-only project."""
        page = self.page
        controller = getattr(page.video, "controller", None)
        try:
            observed = controller.observed_properties() if controller is not None else {}
        except Exception:
            observed = {}
        telemetry = page.audio_engine.telemetry_snapshot() if hasattr(page, "audio_engine") else {}
        playback = page.video.playback_position_snapshot()
        has_video = bool(getattr(page.video, "_media_has_video", True))
        external_clock = bool(getattr(page.video, "_external_clock_enabled", False))
        mpv_time_pos = observed.get("time-pos") if isinstance(observed, Mapping) else None
        mpv_pause = observed.get("pause") if isinstance(observed, Mapping) else None
        mpv_eof = observed.get("eof-reached") if isinstance(observed, Mapping) else None
        mpv_audio_playing = bool(
            not has_video
            and mpv_time_pos is not None
            and not bool(mpv_pause)
            and not bool(mpv_eof)
        )
        audio_engine_playing = bool(
            str(telemetry.get("state") or "").upper() in {"PLAYING", "SYNCED"}
            and not bool(telemetry.get("paused", True))
        )
        owner = (
            "audio_engine" if external_clock
            else "mpv" if not has_video
            else str(playback.source or "mpv")
        )
        audio_clock_position = telemetry.get("estimated_source_ms") if external_clock else (
            round(float(mpv_time_pos) * 1000.0, 3) if mpv_time_pos is not None else None
        )
        cue = page._renderer_cue_at_playhead() if page.project is not None else None
        visibility = page.subtitle_visibility_trace(reason=f"r6-audio-{label}")
        return {
            "label": str(label),
            "wall_time": time.time(),
            "audio_playing": audio_engine_playing if external_clock else mpv_audio_playing,
            "audio_output_state": str(telemetry.get("state") or ""),
            "project_clock_owner": owner,
            "project_clock_time": round(float(playback.presentation_media_ms), 3),
            "mpv_time_pos": mpv_time_pos,
            "mpv_pause": mpv_pause,
            "mpv_eof": mpv_eof,
            "audio_engine_time": telemetry.get("estimated_source_ms"),
            "audio_clock_position": audio_clock_position,
            "media_has_video": has_video,
            "external_clock_enabled": external_clock,
            "audio_engine_state": str(telemetry.get("state") or ""),
            "studio_playhead_time": int(getattr(page.timeline, "playhead_ms", 0) or 0),
            "timeline_cursor_time": int(getattr(page.timeline, "playhead_ms", 0) or 0),
            "active_cue_id": cue.id if cue is not None else "",
            "active_cue_start": int(cue.start_ms) if cue is not None else None,
            "active_cue_end": int(cue.end_ms) if cue is not None else None,
            "subtitle_visibility": bool(visibility.get("visible")),
            "subtitle_render_owner": str(visibility.get("foreground_owner") or "none"),
            "position_observer_alive": bool(
                callable(getattr(controller, "observed_position", None))
                and getattr(page.video, "_sync_timer", None) is not None
                and page.video._sync_timer.isActive()
            ),
            "clock_timer_alive": bool(telemetry.get("clock_timer_alive", False)),
            "subtitle_trace": visibility,
        }

    def _r6_audio_phase(self) -> None:
        """Run the requested 60-second trace against the currently opened project."""
        page = self.page
        self._wait(lambda: page.project is not None and len(page.project.cues) > 0, 45, "current project")
        self._wait(lambda: page.video.controller is not None and page.video.controller.running, 30, "mpv")
        duration_ms = int(getattr(page.timeline, "duration_ms", 0) or 0)
        if duration_ms <= 0 and page.project is not None:
            duration_ms = max((int(cue.end_ms) for cue in page.project.cues), default=0)
        page._apply_project_playhead(0)
        if page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: bool(
                getattr(page.video, "_external_clock_enabled", False)
                or (
                    not bool(getattr(page.video, "_media_has_video", True))
                    and page.video.controller.observed_property("time-pos", None) is not None
                )
            ),
            20,
            "audio-only clock owner",
        )
        self._pump(1_000)
        samples = [self._audio_runtime_sample("0s")]
        try:
            trace_seconds = max(1, min(600, int(os.environ.get("P8C_R6_AUDIO_TRACE_SECONDS", "60"))))
        except ValueError:
            trace_seconds = 60
        for index in range(1, trace_seconds * 10 + 1):
            self._pump(100)
            samples.append(self._audio_runtime_sample(f"{index / 10:.1f}s"))
            if index % 50 == 0:
                phase = self.result["phases"].setdefault("audio_r6", {})
                phase["samples"] = samples
                phase["probe_state"] = f"trace_{index / 10:.1f}s"
                self._write()
        if not page.video.playback_position_snapshot().paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        first = samples[0]
        last = samples[-1]
        clock_values = [float(item["project_clock_time"]) for item in samples]
        audio_values = [
            float(item["audio_clock_position"])
            for item in samples
            if item.get("audio_clock_position") is not None
        ]
        clock_deltas = [b - a for a, b in zip(clock_values, clock_values[1:])]
        audio_deltas = [b - a for a, b in zip(audio_values, audio_values[1:])]
        seek_results: list[dict[str, object]] = []
        for requested_ms in (300_000, 900_000, 60_000):
            page._seek(requested_ms / 1000.0)
            self._pump(1_200)
            observed = self._audio_runtime_sample(f"seek_{requested_ms}ms")
            target_ms = min(requested_ms, duration_ms) if duration_ms else requested_ms
            seek_results.append({
                "requested_ms": requested_ms,
                "target_ms": target_ms,
                "in_range": requested_ms <= duration_ms if duration_ms else False,
                "observed_project_clock_ms": observed["project_clock_time"],
                "observed_audio_engine_ms": observed["audio_engine_time"],
                "observed_audio_clock_ms": observed["audio_clock_position"],
                "subtitle_visible": observed["subtitle_visibility"],
                "owner": observed["subtitle_render_owner"],
                "within_tolerance": abs(float(observed["project_clock_time"]) - target_ms) <= 3_000,
            })
        review_rows: list[dict[str, object]] = []
        try:
            page._set_review_mode(True)
            for cue in list(page.project.cues)[:20]:
                page.select_cue(cue.id)
                page._seek(cue.start_ms / 1000.0)
                self._pump(350)
                row = self._audio_runtime_sample(f"review_{cue.id}")
                review_rows.append({
                    "cue_id": cue.id,
                    "visible": bool(row["subtitle_visibility"]),
                    "owner": row["subtitle_render_owner"],
                    "playhead_ms": row["project_clock_time"],
                })
        finally:
            if getattr(page, "_review_mode", False):
                page._set_review_mode(False)
        visible_samples = [item for item in samples if item.get("active_cue_id")]
        phase = self.result["phases"].setdefault("audio_r6", {})
        phase.update({
            "probe_state": "complete",
            "duration_ms": duration_ms,
            "trace_interval_ms": 100,
            "trace_duration_s": trace_seconds,
            "samples": samples,
            "first": first,
            "last": last,
            "clock_min_delta_ms": round(min(clock_deltas, default=0.0), 3),
            "clock_max_delta_ms": round(max(clock_deltas, default=0.0), 3),
            "audio_engine_min_delta_ms": round(min(audio_deltas, default=0.0), 3),
            "audio_engine_max_delta_ms": round(max(audio_deltas, default=0.0), 3),
            "seek_results": seek_results,
            "review_rows": review_rows,
            "subtitle_visible_sample_count": sum(bool(item["subtitle_visibility"]) for item in visible_samples),
            "subtitle_active_sample_count": len(visible_samples),
        })
        self.result["checks"] = {
            "audio_project_clock_owner": all(item["project_clock_owner"] == "mpv" for item in samples),
            "audio_playhead_60s_continuous": (
                float(last["project_clock_time"]) > float(first["project_clock_time"]) + 45_000
                and sum(delta > 0 for delta in clock_deltas) >= max(1, round(len(clock_deltas) * 0.90))
            ),
            "audio_clock_continuous": (
                len(audio_values) >= 2
                and float(audio_values[-1]) > float(audio_values[0]) + 45_000
                and sum(delta >= 0 for delta in audio_deltas) >= max(1, round(len(audio_deltas) * 0.90))
            ),
            # Retain the old key for consumers of the P8C report; it now means
            # the selected audio clock, which is mpv for primary audio-only media.
            "audio_engine_clock_continuous": (
                len(audio_values) >= 2
                and float(audio_values[-1]) > float(audio_values[0]) + 45_000
                and sum(delta >= 0 for delta in audio_deltas) >= max(1, round(len(audio_deltas) * 0.90))
            ),
            "audio_subtitles_visible": bool(visible_samples) and all(
                bool(item["subtitle_visibility"]) for item in visible_samples
            ),
            "audio_seek_5m": bool(seek_results[0]["in_range"] and seek_results[0]["within_tolerance"]),
            "audio_seek_15m": bool(seek_results[1]["in_range"] and seek_results[1]["within_tolerance"]),
            "audio_seek_1m": bool(seek_results[2]["in_range"] and seek_results[2]["within_tolerance"]),
            "audio_review_20_cues": len(review_rows) == min(20, len(page.project.cues)) and all(
                bool(item["visible"]) for item in review_rows
            ),
        }

    def _lifecycle_ready_phase(self) -> None:
        try:
            page = self.page
            self._wait(lambda: page.project is not None and bool(page.project.cues), 30, "project")
            self._wait(lambda: page.video.controller and page.video.controller.running, 20, "mpv")
            if len(page.project.video_tracks) < 2:
                page.timeline.set_visible_window(0, 60_000)
                tab_bar = page.context_drawer.tabBar()
                QTest.mouseClick(
                    tab_bar,
                    Qt.MouseButton.LeftButton,
                    pos=tab_bar.tabRect(page.media_pool_tab_index).center(),
                )
                self._wait(lambda: page.media_pool_panel.isVisible(), 4, "Media Pool")
                QTest.mouseClick(
                    page.media_pool_panel.add_track_button,
                    Qt.MouseButton.LeftButton,
                )
                self._wait(
                    lambda: [track.id for track in page.project.video_tracks] == ["V1", "V2"],
                    5,
                    "V2 track",
                )
                self._drop_v2(Path(os.environ["TWOBYTEASR_P8B_SECOND_MEDIA"]))
                self._wait(lambda: bool(self._track(page.project, "V2").clips), 45, "V2 media")
                page.save_button.click()
                self._wait(lambda: page.undo_stack.isClean(), 10, "lifecycle project save")
            self._wait(lambda: len(page.project.video_tracks) >= 2, 10, "V1+V2")
            for track_id in ("V1", "V2"):
                if not self._track(page.project, track_id).enabled:
                    self._toggle_track(track_id)
                    self._wait(lambda tid=track_id: self._track(page.project, tid).enabled, 5, f"show {track_id}")
            page._seek(1.0)
            if page.video.playback_position_snapshot().paused:
                QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(900)
            self.result["phases"]["lifecycle_ready"] = {
                "v1_v2": [item.id for item in page.project.video_tracks[:2]],
                "playing": not page.video.playback_position_snapshot().paused,
                "audio": asdict(page._audio_playback_decision),
            }
            self.result["checks"] = {
                "v1_v2_playing": bool(
                    self.result["phases"]["lifecycle_ready"]["playing"]
                )
            }
            self.result["accepted"] = all(self.result["checks"].values())
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        self.result["ready_for_external_close"] = True
        self._write()

    def _run(self) -> None:
        if self.mode == "lifecycle":
            self._lifecycle_ready_phase()
            return
        try:
            self.result["phases"]["startup"] = self._startup_phase()
            if self.mode == "workflow":
                self._workflow_phase()
            elif self.mode == "memory":
                self._memory_phase()
            elif self.mode == "reopen":
                self._reopen_phase()
            elif self.mode == "header":
                self._header_phase()
            elif self.mode == "r6_audio":
                self._r6_audio_phase()
            else:
                raise ValueError(f"unsupported P8C audit mode: {self.mode}")
            self.result["phases"]["windows"] = {
                "qt": qt_top_level_widgets(self.app),
                "win32": win32_top_level_windows(pids={os.getpid()}),
            }
            self.result["accepted"] = all(
                bool(value) for value in self.result["checks"].values()
            )
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        finally:
            self.result["elapsed_s"] = round(time.time() - self.result["started_at"], 3)
            self._write()
            code = 0 if self.result.get("accepted") else 1
            threading.Thread(
                target=lambda: (time.sleep(1.0), os._exit(code)),
                name="p8c-audit-exit", daemon=True,
            ).start()
            try:
                self.window.close()
            except Exception:
                pass
            self.app.quit()


__all__ = ["P8CRuntimeAudit"]
