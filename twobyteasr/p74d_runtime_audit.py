"""Headed P7.4D: applied graph motion + real Add Track UI.

Automated evidence only. Never claims a person completed the workflow.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .runtime_trace import GLOBAL_STUDIO_TRACE
from .visual_design_graph import (
    compile_live_scene,
    glitch_graph,
    style_recipe_from_graph,
)


def lifecycle_events_since(
    records: Iterable[Mapping[str, object]],
    *,
    overlay_id: int,
    started_monotonic: float,
) -> list[dict[str, object]]:
    """Select one overlay's lifecycle without treating ID zero as missing."""
    return [
        dict(item)
        for item in records
        if item.get("event") == "COMPOSITOR_OVERLAY_LIFECYCLE"
        and int(item.get("overlay_id", -1)) == int(overlay_id)
        and float(item.get("time_monotonic") or 0.0) >= float(started_monotonic)
    ]


def _image_stats(image: Image.Image) -> dict[str, Any]:
    rgb = image.convert("RGB")
    extrema = [list(item) for item in rgb.getextrema()]
    pixels = list(rgb.getdata())
    total = max(1, len(pixels))
    mean = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels) / total
    return {
        "pixels": list(rgb.size),
        "mean_luminance": round(mean, 3),
        "extrema": extrema,
        "hash": hash(rgb.tobytes()) & 0xFFFFFFFF,
    }


def _qimage_to_pil(image: QImage) -> Image.Image | None:
    if image is None or image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = converted.constBits()
    return Image.frombuffer(
        "RGBA",
        (converted.width(), converted.height()),
        bytes(ptr),
        "raw",
        "RGBA",
        0,
        1,
    ).copy()


class P74DRuntimeAudit:
    def __init__(self, window, output_dir: str | os.PathLike[str]) -> None:
        self.window = window
        self.page = window.studio_page
        self.app = QApplication.instance()
        self.output = Path(output_dir).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.screenshots = self.output / "screenshots"
        self.screenshots.mkdir(exist_ok=True)
        self.result_path = self.output / "runtime-result.json"
        self.result: dict[str, Any] = {
            "schema": "2byteasr.p74d-runtime-audit.v1",
            "evidence_class": "FORMAL HEADED QUICK_START RUNTIME",
            "real_user_click": False,
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

    def _pump(self, milliseconds: int) -> None:
        deadline = time.perf_counter() + max(0, int(milliseconds)) / 1000.0
        while time.perf_counter() < deadline:
            self.app.processEvents()
            QTest.qWait(min(16, max(1, round((deadline - time.perf_counter()) * 1000))))

    def _wait(self, predicate, timeout: float, label: str) -> float:
        started = time.perf_counter()
        while time.perf_counter() - started < timeout:
            self.app.processEvents()
            if predicate():
                return round((time.perf_counter() - started) * 1000.0, 3)
            QTest.qWait(16)
        raise TimeoutError(f"{label} not ready after {timeout:.1f}s")

    def _write(self) -> None:
        self.result_path.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _grab(self, widget, name: str) -> None:
        if widget is None:
            return
        pixmap = widget.grab()
        path = self.screenshots / f"{name}.png"
        pixmap.save(str(path))

    def _run(self) -> None:
        try:
            self.window.setGeometry(80, 40, 1600, 980)
            self.window.showNormal()
            self._pump(250)
            page = self.page
            self._wait(lambda: page.project is not None and page.project.cues, 20.0, "project")
            project = page.project
            cue = project.cues[0]
            graph = glitch_graph()
            recipe = style_recipe_from_graph(graph)
            card_hash = compile_live_scene(graph).graph_hash
            apply_input_hash = compile_live_scene(recipe.visual_graph).graph_hash
            page.selected_cue_id = cue.id
            applied = page._apply_style_recipe(cue.id, recipe)
            first_motion_ms = 0.0
            persisted = project.style_recipes.get(project.cues[0].style_id, {})
            persisted_graph = persisted.get("visualGraph") if isinstance(persisted, Mapping) else {}
            persisted_hash = (
                compile_live_scene(
                    persisted_graph,
                    cue_duration_ms=max(1, cue.end_ms - cue.start_ms),
                ).graph_hash
                if isinstance(persisted_graph, Mapping) and persisted_graph
                else ""
            )
            page._load_style_inspector()
            self._pump(400)
            overlay = page.advanced_cue_overlay
            if overlay._compiled_scene is None or overlay._snapshot is None:
                from PySide6.QtCore import QRect
                from PySide6.QtGui import QPixmap

                from .advanced_live_renderer import render_live_snapshot
                from .visual_snapshot import build_visual_cue_snapshot

                snapshot = build_visual_cue_snapshot(
                    project, project.cues[0].id, width=960, height=540
                )
                image = render_live_snapshot(snapshot, width=960, height=540)
                overlay.set_base_geometry(QRect(0, 0, 960, 540))
                overlay.set_visual(QPixmap.fromImage(image), snapshot, animate_graph=True)
                self._pump(80)
            try:
                self._wait(lambda: bool(overlay._layer_images), 5.0, "live-layers")
            except TimeoutError:
                self._pump(120)
            if not page.video.playback_position_snapshot().paused:
                page._toggle_playback()
                self._pump(120)
            snapshot_graph = (
                overlay._snapshot.style_recipe.get("visualGraph", {})
                if overlay._snapshot is not None
                and isinstance(overlay._snapshot.style_recipe, Mapping)
                else {}
            )
            snapshot_graph_hash = (
                compile_live_scene(
                    snapshot_graph,
                    cue_duration_ms=max(1, cue.end_ms - cue.start_ms),
                ).graph_hash
                if isinstance(snapshot_graph, Mapping) and snapshot_graph
                else ""
            )
            hold_samples: dict[str, dict[str, Any]] = {}
            for offset_ms in (500, 1000, 2000, 3000):
                page._seek((cue.start_ms + offset_ms) / 1000.0)
                self._pump(120)
                page.ensure_active_subtitle_renderer(reason="p9a_r4_hold_sample")
                self._pump(45)
                overlay.sync_time(cue.start_ms + offset_ms, paused=True)
                self._pump(30)
                sample = _qimage_to_pil(overlay._source_image)
                alpha = sample.getchannel("A") if sample is not None else None
                alpha_bbox = alpha.getbbox() if alpha is not None else None
                hold_samples[str(offset_ms)] = {
                    "alpha_bbox": list(alpha_bbox) if alpha_bbox is not None else [],
                    "alpha_nonzero": bool(alpha_bbox),
                    "overlay_present": page.video.ADVANCED_OVERLAY_ID
                    in page.video.active_compositor_overlay_ids(),
                }
                if sample is not None:
                    sample.save(self.screenshots / f"applied-glitch-hold-{offset_ms}.png")
            motion_started = time.perf_counter()
            overlay.sync_time(cue.start_ms + 80, paused=False)
            first_motion_ms = round((time.perf_counter() - motion_started) * 1000.0, 3)
            self._pump(30)
            first_pil = _qimage_to_pil(overlay._source_image)
            if first_pil is not None:
                first_pil.save(self.screenshots / "applied-glitch-t80.png")
            overlay.sync_time(cue.start_ms + 200, paused=False)
            self._pump(30)
            second_pil = _qimage_to_pil(overlay._source_image)
            if second_pil is not None:
                second_pil.save(self.screenshots / "applied-glitch-t900.png")
            first_hash = first_pil.tobytes() if first_pil is not None else b""
            second_hash = second_pil.tobytes() if second_pil is not None else b""
            motion_changed = bool(first_hash and second_hash and first_hash != second_hash)
            overlay.sync_time(cue.start_ms + 900, paused=True)
            paused_bytes = _qimage_to_pil(overlay._source_image)
            paused_payload = paused_bytes.tobytes() if paused_bytes is not None else b""
            self._pump(80)
            still_paused = _qimage_to_pil(overlay._source_image)
            still_payload = still_paused.tobytes() if still_paused is not None else b""
            overlay.sync_time(cue.start_ms + 400, paused=False)
            seek_mid = _qimage_to_pil(overlay._source_image)
            overlay.sync_time(cue.start_ms + 400, paused=False)
            seek_repeat = _qimage_to_pil(overlay._source_image)
            seek_stable = bool(
                seek_mid is not None
                and seek_repeat is not None
                and seek_mid.tobytes() == seek_repeat.tobytes()
            )

            # P9A-R5: exercise the real playback/visibility owners instead of
            # treating direct sync_time() samples as a full-cue runtime pass.
            page._seek((cue.start_ms + 60) / 1000.0)
            self._pump(240)
            page.ensure_active_subtitle_renderer(reason="p9a_r5_playthrough_prepare")
            self._pump(160)
            # Filter the production trace by monotonic time. The trace writer
            # already records the exact structured fields emitted to
            # studio-open.log, so the audit must not replace a live Qt class
            # method merely to duplicate those records.
            trace_started_monotonic = time.monotonic()
            # Read the effect selector while the audited cue is still at the
            # playhead. The playthrough intentionally crosses into cue 2,
            # whose native effect is "none".
            preset_text = (
                page.effect_preset.currentText()
                if hasattr(page, "effect_preset") else ""
            )
            if page.video.playback_position_snapshot().paused:
                page._toggle_playback()
            playthrough_samples: list[dict[str, Any]] = []
            paused_sample: dict[str, Any] = {}
            resumed_sample: dict[str, Any] = {}
            pause_done = False
            deadline = time.perf_counter() + (cue.end_ms - cue.start_ms) / 1000.0 + 2.5
            while time.perf_counter() < deadline:
                self._pump(80)
                position_ms = round(float(page.video.visual_position()) * 1000.0)
                sample = {
                    "position_ms": position_ms,
                    "paused": bool(page.video.playback_position_snapshot().paused),
                    "overlay_present": page.video.ADVANCED_OVERLAY_ID
                    in page.video.active_compositor_overlay_ids(),
                    "canvas_visible": overlay.isVisibleTo(page),
                    "scene_alive": not overlay._display_source.isNull(),
                    "opacity": round(float(overlay._display_opacity), 3),
                }
                playthrough_samples.append(sample)
                if not pause_done and position_ms >= cue.start_ms + 1_100:
                    page._toggle_playback()
                    self._pump(320)
                    paused_sample = {
                        "position_ms": round(float(page.video.visual_position()) * 1000.0),
                        "overlay_present": page.video.ADVANCED_OVERLAY_ID
                        in page.video.active_compositor_overlay_ids(),
                        "canvas_visible": overlay.isVisibleTo(page),
                    }
                    page._toggle_playback()
                    self._pump(160)
                    resumed_sample = {
                        "position_ms": round(float(page.video.visual_position()) * 1000.0),
                        "overlay_present": page.video.ADVANCED_OVERLAY_ID
                        in page.video.active_compositor_overlay_ids(),
                        "canvas_visible": overlay.isVisibleTo(page),
                    }
                    pause_done = True
                if position_ms >= cue.end_ms + 180:
                    break
            if not page.video.playback_position_snapshot().paused:
                page._toggle_playback()
            self._pump(180)
            GLOBAL_STUDIO_TRACE.flush(0.5)
            lifecycle = lifecycle_events_since(
                GLOBAL_STUDIO_TRACE.recent(),
                overlay_id=page.video.ADVANCED_OVERLAY_ID,
                started_monotonic=trace_started_monotonic,
            )
            inside_samples = [
                item for item in playthrough_samples
                if cue.start_ms + 250 <= int(item["position_ms"]) <= cue.end_ms - 150
            ]
            after_cue_samples = [
                item for item in playthrough_samples
                if int(item["position_ms"]) >= cue.end_ms + 100
            ]
            active_removals = [
                item for item in lifecycle
                if item.get("action") == "REMOVE" and bool(item.get("cue_active"))
            ]
            removal_events = [item for item in lifecycle if item.get("action") == "REMOVE"]
            rejected_removals = [
                item for item in lifecycle if item.get("action") == "REMOVE_REJECTED"
            ]
            summary = getattr(page, "graph_motion_summary", None)
            inspector = summary.isVisible() if summary is not None else False
            inspector_text = summary.text() if summary is not None else ""
            compiled_hash = (
                overlay._compiled_scene.graph_hash
                if overlay._compiled_scene is not None else ""
            )
            compiled_scene_ready = overlay._compiled_scene is not None
            sync_profile = dict(getattr(overlay, "_last_sync_profile", {}) or {})

            self._grab(page, "studio-after-apply")
            self._grab(page.timeline, "timeline-before-add-track")

            before_tracks = [track.id for track in project.video_tracks]
            v1_path_before = str(getattr(page.video, "_media_path", "") or "")
            button = getattr(page, "add_video_track_button", None)
            if button is not None:
                button.click()
            else:
                page._add_video_track()
            self._pump(180)
            after_tracks = [track.id for track in page.project.video_tracks]
            groups = {
                group.video_track_id: group.audio_track_id
                for group in page.project.av_track_groups
            }
            rects = page.timeline._video_track_rects()
            audio = page.timeline._audio_track_rects()
            composition = bool(getattr(page, "_multitrack_composition_active", False))
            v1_path = str(getattr(page.video, "_media_path", "") or "")
            self._grab(page.timeline, "timeline-after-add-track")
            empty_hint = getattr(page, "video_empty_hint", None)
            video_hidden = bool(
                empty_hint is not None and empty_hint.isVisible()
            )
            second_media = Path(os.environ.get("TWOBYTEASR_P74D_SECOND_MEDIA", "") or "")
            second_clip = False
            composition_after_second = False
            if second_media.is_file():
                page._video_track_action("V2", "select")
                page._begin_media_ingest(str(second_media), add_to_timeline=True)
                try:
                    self._wait(
                        lambda: any(
                            track.id == "V2" and track.clips
                            for track in page.project.video_tracks
                        ),
                        20.0,
                        "v2-clip",
                    )
                    second_clip = True
                except TimeoutError:
                    second_clip = False
                self._pump(200)
                composition_after_second = bool(
                    getattr(page, "_multitrack_composition_active", False)
                )
                v1_path = str(getattr(page.video, "_media_path", "") or "")
                video_hidden = bool(
                    empty_hint is not None and empty_hint.isVisible()
                )
                self._grab(page.timeline, "timeline-after-second-media")

            self.result["phases"] = {
                "graph": {
                    "card_hash": card_hash,
                    "apply_input_hash": apply_input_hash,
                    "persisted_hash": persisted_hash,
                    "renderer_snapshot_hash": snapshot_graph_hash,
                    "compiled_live_hash": compiled_hash,
                    "applied": applied,
                    "first_apply_ms": first_motion_ms,
                },
                "motion": {
                    "inspector_visible": inspector,
                    "inspector_text": inspector_text,
                    "preset_text": preset_text,
                    "pixels_changed": motion_changed,
                    "compiled_scene": compiled_scene_ready,
                    "pause_freezes": paused_payload == still_payload,
                    "seek_stable": seek_stable,
                    "sync_profile": sync_profile,
                    "hold_samples": hold_samples,
                    "playthrough_samples": playthrough_samples,
                    "pause_sample": paused_sample,
                    "resume_sample": resumed_sample,
                    "after_cue_samples": after_cue_samples,
                    "overlay_lifecycle": lifecycle,
                    "overlay_removers": removal_events,
                    "rejected_active_removals": rejected_removals,
                    "first_stats": _image_stats(first_pil) if first_pil is not None else {},
                    "second_stats": _image_stats(second_pil) if second_pil is not None else {},
                },
                "tracks": {
                    "before": before_tracks,
                    "after": after_tracks,
                    "groups": groups,
                    "v2_rect": not rects.get("V2").isEmpty() if "V2" in rects else False,
                    "a2_rect": not audio.get("A2").isEmpty() if "A2" in audio else False,
                    "v2_below_v1": (
                        "V1" in rects
                        and "V2" in rects
                        and rects["V2"].top() >= rects["V1"].bottom() - 1
                    ),
                    "composition_active": composition,
                    "v1_path_before": v1_path_before,
                    "v1_path": v1_path,
                    "video_hidden_after_add": video_hidden,
                    "command_path": "add_video_track_button.click",
                    "second_media": str(second_media) if second_media.is_file() else "",
                    "second_clip_on_v2": second_clip,
                    "composition_after_second": composition_after_second,
                },
            }
            self.result["checks"] = {
                "apply_hash_matches_card": card_hash == apply_input_hash,
                "persisted_graph_complete": bool(
                    isinstance(persisted, Mapping)
                    and persisted.get("visualGraph", {}).get("motionGraph", {}).get("tracks")
                    and persisted.get("visualGraph", {}).get("effectLayers")
                ),
                "compiled_hash_matches_renderer_snapshot": (
                    compiled_hash == snapshot_graph_hash and bool(compiled_hash)
                ),
                "graph_motion_not_flattened": bool(
                    isinstance(persisted, Mapping)
                    and persisted.get("visualGraph", {}).get("motionGraph", {}).get("tracks")
                ),
                "compiled_scene_on_overlay": compiled_scene_ready,
                "inspector_shows_graph_motion": inspector and "Graph Motion" in inspector_text,
                "inspector_not_none_preset": "无" not in str(preset_text),
                "applied_pixels_change_over_cue": motion_changed,
                "hold_pixels_present": all(
                    bool(item.get("alpha_nonzero")) for item in hold_samples.values()
                ),
                "hold_overlay_present": all(
                    bool(item.get("overlay_present")) for item in hold_samples.values()
                ),
                "pause_freezes_animation": paused_payload == still_payload,
                "seek_is_cue_local_stable": seek_stable,
                "full_cue_overlay_visible": bool(inside_samples) and all(
                    bool(item["overlay_present"])
                    and bool(item["canvas_visible"])
                    and bool(item["scene_alive"])
                    and float(item["opacity"]) > 0.0
                    for item in inside_samples
                ),
                "pause_keeps_overlay": bool(paused_sample.get("overlay_present"))
                and bool(paused_sample.get("canvas_visible")),
                "resume_keeps_overlay": bool(resumed_sample.get("overlay_present"))
                and bool(resumed_sample.get("canvas_visible")),
                "cue_end_removes_overlay": bool(after_cue_samples)
                and not bool(after_cue_samples[-1].get("overlay_present")),
                "cue_end_remove_traced": any(
                    not bool(item.get("cue_active")) for item in removal_events
                ),
                "no_active_overlay_remove": bool(lifecycle) and not active_removals,
                "add_track_created_v2": "V2" in after_tracks,
                "add_track_created_a2": groups.get("V2") == "A2",
                "v2_lane_visible": bool(self.result["phases"]["tracks"]["v2_rect"]),
                "a2_lane_visible": bool(self.result["phases"]["tracks"]["a2_rect"]),
                "v2_not_stacked_on_v1": bool(self.result["phases"]["tracks"]["v2_below_v1"]),
                "empty_v2_skips_compositor": composition is False,
                "v1_source_kept": bool(v1_path) and v1_path == v1_path_before,
                "add_track_did_not_hide_video": video_hidden is False,
                "first_motion_budget_ms": first_motion_ms < 150.0,
                "live_composite_budget": (
                    not sync_profile
                    or float(sync_profile.get("total_ms") or 0) < 40.0
                    or float(sync_profile.get("composite_ms") or 0) < 40.0
                ),
                "process_is_packaged_when_frozen": (
                    not bool(getattr(sys, "frozen", False))
                    or Path(sys.executable).name.lower() == "2byteasr.exe"
                ),
                "second_media_lands_on_v2": (
                    not second_media.is_file() or second_clip
                ),
                "second_media_keeps_v1": (
                    not second_media.is_file() or (bool(v1_path) and video_hidden is False)
                ),
            }
            self.result["accepted"] = all(self.result["checks"].values())
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        finally:
            self.result["finished_at"] = time.time()
            self.result["duration_seconds"] = round(
                self.result["finished_at"] - self.result["started_at"], 3
            )
            self._write()
            try:
                self.page.close_page()
            except Exception as exc:
                self.result["errors"].append(f"close_page: {type(exc).__name__}: {exc}")
                self.result["accepted"] = False
                self._write()
            self._pump(500)
            QTimer.singleShot(0, self.window.close)
            QTimer.singleShot(1200, self.app.quit)


__all__ = ["P74DRuntimeAudit"]
