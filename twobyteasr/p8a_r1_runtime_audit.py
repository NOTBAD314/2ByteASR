"""Packaged P8A-R1 real-widget workflow evidence.

This module is loaded only when TWOBYTEASR_P8A_R1_RUNTIME_AUDIT is set.
It drives production widgets and drop handlers with Qt events; it never claims
that a person completed the workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QElapsedTimer, QMimeData, QPoint, QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .build_identity import load_build_identity
from .model_registry import scan_model_registry
from .runtime_paths import get_runtime_paths


MODEL_KEYS = ("moss", "firered_aed", "qwen_asr")


def image_metrics(path: str | os.PathLike[str]) -> dict[str, object]:
    """Return deterministic proof that an mpv screenshot contains pixels."""

    target = Path(path)
    payload = target.read_bytes()
    with Image.open(target) as source:
        rgb = source.convert("RGB")
        gray = rgb.convert("L")
        histogram = gray.histogram()
        pixels = max(1, rgb.width * rgb.height)
        nonblack = pixels - sum(histogram[:9])
        weighted = sum(level * count for level, count in enumerate(histogram))
        return {
            "path": str(target.resolve()),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            "bytes": len(payload),
            "width": rgb.width,
            "height": rgb.height,
            "nonblack_ratio": round(nonblack / pixels, 6),
            "mean_luma": round(weighted / pixels, 3),
            "luma_extrema": list(gray.getextrema()),
        }


class P8AR1RuntimeAudit:
    """Run one model, workflow, or reopen phase inside the exact executable."""

    def __init__(self, window, output_dir: str | os.PathLike[str], *, mode: str) -> None:
        self.window = window
        self.page = window.studio_page
        self.app = QApplication.instance()
        self.output = Path(output_dir).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.screenshots = self.output / "screenshots"
        self.screenshots.mkdir(exist_ok=True)
        self.result_path = self.output / "runtime-result.json"
        self.progress_path = self.output / "runtime-progress.json"
        self.mode = str(mode or "model").strip().lower()
        self.result: dict[str, Any] = {
            "schema": "2byteasr.p8a-r1-runtime-audit.v1",
            "mode": self.mode,
            "evidence_class": "PACKAGED QT REAL-WIDGET AUTOMATION",
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

    def _checkpoint(self, name: str, **values: object) -> None:
        payload = {
            "name": str(name),
            "monotonic": time.monotonic(),
            "values": values,
        }
        self.result["checkpoint"] = payload
        self.progress_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _pump(self, milliseconds: int, *, profile: list[float] | None = None) -> None:
        deadline = time.perf_counter() + max(0, int(milliseconds)) / 1000.0
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            self.app.processEvents()
            if profile is not None:
                profile.append((time.perf_counter() - started) * 1000.0)
            remaining = max(1, round((deadline - time.perf_counter()) * 1000.0))
            QTest.qWait(min(16, remaining))

    def _wait(self, predicate, timeout: float, label: str) -> float:
        started = time.perf_counter()
        while time.perf_counter() - started < timeout:
            self.app.processEvents()
            if predicate():
                return round((time.perf_counter() - started) * 1000.0, 3)
            QTest.qWait(16)
        raise TimeoutError(f"{label} not ready after {timeout:.1f}s")

    @staticmethod
    def _track(project, track_id: str):
        return next(item for item in project.video_tracks if item.id == track_id)

    def _model_phase(self) -> None:
        paths = get_runtime_paths(refresh=True)
        registry = scan_model_registry(
            install_root=paths.install_root,
            model_root=paths.model_root,
        )

        button = self.window.model_workshop_button
        if not button.isVisible():
            raise RuntimeError("Model Workshop button is not visible")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: self.window.pages.currentWidget() is self.window.workshop_page,
            8.0,
            "model-workshop-page",
        )
        workshop = self.window.workshop_page
        self._wait(
            lambda: set(MODEL_KEYS) <= set(workshop._installed),
            12.0,
            "model-workshop-installed-state",
        )
        workshop_grab = workshop.grab()
        workshop_grab.save(str(self.screenshots / "model-workshop.png"))

        records = {
            key: {
                "health": registry.records[key].health.value,
                "path": str(registry.records[key].installation_path),
                "source": registry.records[key].source,
            }
            for key in MODEL_KEYS
            if key in registry.records
        }
        phase = {
            "model_root": str(paths.model_root.resolve()),
            "model_root_source": paths.model_root_source,
            "installed_count": registry.installed_count(),
            "installed_keys": sorted(registry.installed_keys()),
            "records": records,
            "workshop_installed_keys": sorted(workshop._installed),
            "workshop_health_summary": workshop.health_summary.text(),
            "workshop_combo_status": {
                key: label.text()
                for key, label in workshop.combo_status_labels.items()
            },
            "build_identity": load_build_identity().to_dict(),
        }
        self.result["phases"]["models"] = phase
        self.result["checks"] = {
            "exact_packaged_exe": bool(getattr(sys, "frozen", False))
            and Path(sys.executable).name.lower() == "2byteasr.exe",
            "three_required_models_installed": all(
                records.get(key, {}).get("health") == "INSTALLED"
                for key in MODEL_KEYS
            ),
            "workshop_ui_shows_three_models": set(MODEL_KEYS) <= set(workshop._installed),
            "no_download_was_started": not bool(workshop._download_dialogs),
        }

    def _click_ruler(self, target_ms: int, *, settle_ms: int = 900) -> dict[str, object]:
        timeline = self.page.timeline
        x = round(timeline._time_to_x(int(target_ms)))
        point = QPoint(x, max(5, timeline.RULER_HEIGHT // 2))
        self._checkpoint("ruler-click-before", target_ms=int(target_ms))
        QTest.mouseClick(
            timeline,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        self._checkpoint("ruler-click-after", target_ms=int(target_ms))
        self._wait(
            lambda: abs(int(timeline.playhead_ms) - int(target_ms)) <= 50,
            4.0,
            f"ruler-seek-{target_ms}",
        )
        self._checkpoint("ruler-wait-complete", target_ms=int(target_ms))
        self._pump(settle_ms)
        self._checkpoint("ruler-settle-complete", target_ms=int(target_ms))
        controller = self.page.video.controller
        observed = controller.observed_properties() if controller is not None else {}
        snapshot = self.page.video.playback_position_snapshot()
        return {
            "target_ms": int(target_ms),
            "timeline_ms": int(timeline.playhead_ms),
            "clock_ms": round(float(snapshot.presentation_media_ms), 3),
            "clock_source": snapshot.source,
            "mpv_time_pos_s": observed.get("time-pos"),
            "mpv_path": observed.get("path"),
            "video_frame_info": observed.get("video-frame-info"),
        }

    def _drop_media_on_timeline(self, media_path: Path, *, target_ms: int) -> dict[str, object]:
        page = self.page
        timeline = page.timeline
        v2_rect = timeline._video_track_rects()["V2"]
        local = QPoint(round(timeline._time_to_x(target_ms)), round(v2_rect.center().y()))
        page_point = timeline.mapTo(page, local)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(media_path.resolve()))])
        drag = QDragEnterEvent(
            page_point,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, drag)
        drop = QDropEvent(
            QPointF(page_point),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, drop)
        return {
            "path": str(media_path.resolve()),
            "page_point": [page_point.x(), page_point.y()],
            "drag_accepted": drag.isAccepted(),
            "drop_accepted": drop.isAccepted(),
        }

    def _drag_v2_to_zero(self) -> dict[str, object]:
        timeline = self.page.timeline
        project = self.page.project
        v2 = self._track(project, "V2")
        clip = v2.clips[0]
        source_before = [int(clip.source_in_ms), int(clip.source_out_ms)]
        timeline.set_visible_window(0, 60_000)
        self._pump(100)
        start_ms = int(clip.timeline_in_ms) + 3_000
        end_ms = 3_000
        start = QPoint(
            round(timeline._time_to_x(start_ms)),
            round(timeline._video_track_rects()["V2"].center().y()),
        )
        end = QPoint(
            round(timeline._time_to_x(end_ms)),
            start.y(),
        )
        left_x = timeline._time_to_x(int(clip.timeline_in_ms))
        QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(timeline, end, delay=120)
        QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)
        self._wait(
            lambda: int(self._track(project, "V2").clips[0].timeline_in_ms) == 0,
            5.0,
            "v2-drag-to-zero",
        )
        moved = self._track(project, "V2").clips[0]
        linked = next(
            item
            for track in project.audio_tracks
            for item in track.clips
            if item.linked_video_clip_id == moved.id
        )
        return {
            "start": [start.x(), start.y()],
            "end": [end.x(), end.y()],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "body_distance_from_left_px": round(abs(start.x() - left_x), 3),
            "trim_handle_px": timeline.VIDEO_CLIP_TRIM_HANDLE_PX,
            "timeline_in_ms": int(moved.timeline_in_ms),
            "source_before": source_before,
            "source_after": [int(moved.source_in_ms), int(moved.source_out_ms)],
            "linked_audio_timeline_in_ms": int(linked.timeline_in_ms),
        }

    def _toggle_track(self, track_id: str) -> None:
        timeline = self.page.timeline
        rect = timeline._video_track_rects()[track_id]
        QTest.mouseClick(
            timeline,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(143, round(rect.center().y())),
        )
        self._pump(120)

    def _capture_mpv(self, name: str) -> dict[str, object]:
        target = self.screenshots / f"{name}.png"
        controller = self.page.video.controller
        if controller is None or not controller.running:
            raise RuntimeError("mpv controller is not running")
        controller.screenshot_to_file(target, mode="video")
        self._wait(lambda: target.is_file() and target.stat().st_size > 0, 8.0, name)
        return image_metrics(target)

    def _stress(self, seconds: int) -> dict[str, object]:
        page = self.page
        timeline = page.timeline
        profile: list[float] = []
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(120)
        before_ms = int(timeline.playhead_ms)
        clock_before = asdict(page.video.playback_position_snapshot())
        controller = page.video.controller
        mpv_before_s = float(controller.observed_property("time-pos", 0.0) or 0.0)
        actor_before = controller.observed_position()
        applied_seek_before = controller.applied_seek_state()
        trace_start = len(page.video.playback_position_trace())
        scene = page.video_compositor
        scene.reset_performance_samples()
        playback_started = time.perf_counter()
        QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._pump(max(1, seconds) * 1000, profile=profile)
        playback_elapsed_s = time.perf_counter() - playback_started
        after_ms = int(timeline.playhead_ms)
        clock_after = asdict(page.video.playback_position_snapshot())
        mpv_after_s = float(controller.observed_property("time-pos", 0.0) or 0.0)
        actor_after = controller.observed_position()
        applied_seek_after = controller.applied_seek_state()
        playback_trace = page.video.playback_position_trace()[trace_start:]
        trace_reason_counts: dict[str, int] = {}
        for row in playback_trace:
            reason = str(row.get("reason") or "")
            trace_reason_counts[reason] = trace_reason_counts.get(reason, 0) + 1
        compositor = scene.performance_snapshot()
        compositor["visible_samples"] = sum(
            1 for row in scene.telemetry() if bool(row.get("visible"))
        )
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(120)

        seek_results = [
            self._click_ruler((5_000, 10_000, 17_000, 30_000)[index % 4], settle_ms=80)
            for index in range(20)
        ]
        for _index in range(20):
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(35, profile=profile)
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(35, profile=profile)
        for _index in range(5):
            self._toggle_track("V1")
            self._toggle_track("V1")
            self._toggle_track("V2")
            self._toggle_track("V2")

        ordered = sorted(profile)
        p95 = ordered[min(len(ordered) - 1, max(0, round(len(ordered) * 0.95) - 1))] if ordered else 0.0
        return {
            "requested_seconds": seconds,
            "playhead_before_ms": before_ms,
            "playhead_after_ms": after_ms,
            "advanced_ms": after_ms - before_ms,
            "timeline_advanced_ms": after_ms - before_ms,
            "clock_before": clock_before,
            "clock_after": clock_after,
            "clock_advanced_ms": round(
                float(clock_after["presentation_media_ms"])
                - float(clock_before["presentation_media_ms"]),
                3,
            ),
            "mpv_time_pos_before_s": round(mpv_before_s, 6),
            "mpv_time_pos_after_s": round(mpv_after_s, 6),
            "mpv_advanced_ms": round((mpv_after_s - mpv_before_s) * 1000.0, 3),
            "playback_elapsed_s": round(playback_elapsed_s, 3),
            "actor_before": actor_before,
            "actor_after": actor_after,
            "applied_seek_before": applied_seek_before,
            "applied_seek_after": applied_seek_after,
            "playback_trace_count": len(playback_trace),
            "playback_trace_reason_counts": trace_reason_counts,
            "playback_trace_tail": playback_trace[-12:],
            "compositor": compositor,
            "seek_count": len(seek_results),
            "pause_play_cycles": 20,
            "visibility_toggle_count": 20,
            "event_loop_samples": len(profile),
            "event_loop_max_ms": round(max(profile) if profile else 0.0, 3),
            "event_loop_p95_ms": round(p95, 3),
            "seek_results": seek_results,
        }

    def _workflow_phase(self) -> None:
        page = self.page
        self.window.setGeometry(40, 30, 1680, 1020)
        self.window.showNormal()
        self._wait(lambda: page.project is not None, 30.0, "studio-project")
        self._wait(
            lambda: page.video.controller is not None and page.video.controller.running,
            20.0,
            "mpv-controller",
        )
        project = page.project
        page.timeline.set_visible_window(0, 60_000)
        self._pump(250)

        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(150)
        baseline_seek = self._click_ruler(1_000, settle_ms=500)
        controller = page.video.controller
        self._wait(
            lambda: bool(controller.observed_property("video-frame-info", {})),
            12.0,
            "v1-video-frame-info",
        )
        QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        self._pump(1_200)
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(100)
        track_list = controller.observed_property("track-list", []) or []
        v1_baseline = {
            "seek": baseline_seek,
            "mpv_path": controller.observed_property("path", ""),
            "video_frame_info": controller.observed_property("video-frame-info", {}),
            "audio_pts": controller.observed_property("audio-pts", None),
            "sub_visibility": controller.observed_property("sub-visibility", None),
            "track_list": track_list,
            "pixels": self._capture_mpv("v1-baseline"),
        }

        initial_seek = self._click_ruler(9_000)
        tab_bar = page.context_drawer.tabBar()
        tab_point = tab_bar.tabRect(page.media_pool_tab_index).center()
        QTest.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_point)
        self._wait(lambda: page.media_pool_panel.isVisible(), 4.0, "media-pool-tab")
        add_button = page.media_pool_panel.add_track_button
        if not add_button.isVisible():
            raise RuntimeError("Media Pool Add Track button is not visible")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        self._wait(
            lambda: [track.id for track in project.video_tracks] == ["V1", "V2"],
            5.0,
            "add-v2-track",
        )
        add_track = {
            "command_path": "QTest.mouseClick(media_pool_panel.add_track_button)",
            "video_tracks": [track.id for track in project.video_tracks],
            "av_groups": [
                [group.video_track_id, group.audio_track_id]
                for group in project.av_track_groups
            ],
        }

        second = Path(os.environ["TWOBYTEASR_P8A_R1_SECOND_MEDIA"])
        drop = self._drop_media_on_timeline(second, target_ms=9_000)
        self._checkpoint("drop-events-complete", **drop)
        ingest_ms = self._wait(
            lambda: bool(self._track(project, "V2").clips),
            45.0,
            "v2-real-media-clip",
        )
        self._pump(500)
        self._checkpoint("v2-ingest-complete", ingest_ms=ingest_ms)
        v2_clip = self._track(project, "V2").clips[0]
        v2_asset_id = v2_clip.asset_id
        drop.update(
            ingest_wait_ms=ingest_ms,
            timeline_in_ms=int(v2_clip.timeline_in_ms),
            timeline_out_ms=int(v2_clip.timeline_out_ms),
            source_in_ms=int(v2_clip.source_in_ms),
            source_out_ms=int(v2_clip.source_out_ms),
        )

        waveform_wait_ms = None
        try:
            waveform_wait_ms = self._wait(
                lambda: v2_asset_id in page.timeline.waveform_caches,
                30.0,
                "a2-progressive-waveform",
            )
        except TimeoutError:
            pass
        drop["a2_waveform_wait_ms"] = waveform_wait_ms
        drop["a2_waveform_ready"] = v2_asset_id in page.timeline.waveform_caches

        clock_audit_start = len(page.video.project_clock_write_audit())
        seek_results = [self._click_ruler(value) for value in (5_000, 10_000, 17_000, 30_000)]
        self._checkpoint("seek-gate-complete")
        drag = self._drag_v2_to_zero()
        self._checkpoint("v2-drag-complete", **drag)

        if not self._track(project, "V1").enabled:
            self._toggle_track("V1")
        self._toggle_track("V1")
        self._wait(lambda: not self._track(project, "V1").enabled, 4.0, "hide-v1")
        v2_seek = self._click_ruler(10_000, settle_ms=1_200)
        expected_v2 = str(second.resolve()).casefold()
        self._wait(
            lambda: str(
                page.video.controller.observed_property("path", "")
                or page.video._media_path
            ).casefold() == expected_v2,
            12.0,
            "v2-mpv-path",
        )
        self._wait(
            lambda: bool(page.video.controller.observed_property("video-frame-info", {})),
            12.0,
            "v2-video-frame-info",
        )
        v2_pixels = self._capture_mpv("v2-only")
        self._checkpoint("v2-pixels-complete", **v2_pixels)
        v2_runtime = {
            "mpv_path": page.video.controller.observed_property("path", ""),
            "mpv_time_pos": page.video.controller.observed_property("time-pos", None),
            "video_frame_info": page.video.controller.observed_property("video-frame-info", {}),
            "seek": v2_seek,
            "pixels": v2_pixels,
        }
        self._toggle_track("V1")
        self._wait(lambda: self._track(project, "V1").enabled, 4.0, "show-v1")

        stress_seconds = int(os.environ.get("TWOBYTEASR_P8A_R1_STRESS_SECONDS", "60"))
        stress = self._stress(stress_seconds)
        self._checkpoint("stress-complete", **stress)
        writes = page.video.project_clock_write_audit()[clock_audit_start:]
        forbidden_writes = [
            row
            for row in writes
            if "qmediaplayer" in json.dumps(row, ensure_ascii=False).casefold()
            or "secondary" in str(row.get("source", "")).casefold()
        ]

        before_save = page.project_path.stat().st_mtime_ns
        QTest.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
        self._wait(lambda: page.undo_stack.isClean(), 8.0, "project-save")
        after_save = page.project_path.stat().st_mtime_ns
        page.grab().save(str(self.screenshots / "workflow-final.png"))

        self.result["phases"].update(
            v1_baseline=v1_baseline,
            initial_seek=initial_seek,
            add_track=add_track,
            drop=drop,
            seeks=seek_results,
            drag=drag,
            v2_only=v2_runtime,
            stress=stress,
            project_clock_writes=writes,
            forbidden_clock_writes=forbidden_writes,
            save={
                "project_path": str(page.project_path.resolve()),
                "mtime_before_ns": before_save,
                "mtime_after_ns": after_save,
                "undo_clean": page.undo_stack.isClean(),
            },
        )
        self.result["checks"] = {
            "exact_packaged_exe": bool(getattr(sys, "frozen", False)),
            "v1_real_video_pixels": v1_baseline["pixels"]["nonblack_ratio"] >= 0.05
            and v1_baseline["pixels"]["mean_luma"] >= 5.0,
            "v1_audio_observed": v1_baseline["audio_pts"] is not None
            and any(
                str(item.get("type") or "") == "audio" and bool(item.get("selected"))
                for item in track_list
                if isinstance(item, dict)
            ),
            "v1_subtitle_track_visible": bool(v1_baseline["sub_visibility"])
            and any(
                str(item.get("type") or "") == "sub" and bool(item.get("selected"))
                for item in track_list
                if isinstance(item, dict)
            ),
            "add_track_real_button": add_track["video_tracks"] == ["V1", "V2"]
            and ["V2", "A2"] in add_track["av_groups"],
            "drop_real_event_accepted": bool(drop["drag_accepted"] and drop["drop_accepted"]),
            "v2_imported_at_9s": abs(int(drop["timeline_in_ms"]) - 9_000) <= 50,
            "a2_progressive_waveform_ready": bool(drop["a2_waveform_ready"]),
            "seek_gate": all(
                abs(int(row["timeline_ms"]) - int(row["target_ms"])) <= 50
                and abs(float(row["clock_ms"]) - int(row["target_ms"])) <= 80
                for row in seek_results
            ),
            "seek_10s_not_17s": abs(int(seek_results[1]["timeline_ms"]) - 10_000) <= 50,
            "no_secondary_clock_writes": not forbidden_writes,
            "v2_drag_to_zero": drag["timeline_in_ms"] == 0
            and drag["source_before"] == drag["source_after"]
            and drag["linked_audio_timeline_in_ms"] == 0,
            "v2_only_real_pixels": v2_pixels["nonblack_ratio"] >= 0.05
            and v2_pixels["mean_luma"] >= 5.0,
            "multitrack_60s_playback": stress["requested_seconds"] >= 60
            and stress["playback_elapsed_s"] >= 59.0
            and stress["timeline_advanced_ms"] >= 55_000
            and stress["clock_advanced_ms"] >= 55_000
            and stress["mpv_advanced_ms"] >= 55_000
            and not stress["clock_after"]["exact_seek_pending"]
            and stress["compositor"]["frame_count"] >= 2
            and stress["compositor"]["visible_samples"] > 0
            and stress["event_loop_max_ms"] < 500.0,
            "stress_interactions_complete": stress["seek_count"] == 20
            and stress["pause_play_cycles"] == 20
            and stress["visibility_toggle_count"] == 20,
            "project_saved": page.undo_stack.isClean() and after_save >= before_save,
        }

    def _reopen_phase(self) -> None:
        page = self.page
        self.window.setGeometry(40, 30, 1680, 1020)
        self.window.showNormal()
        self._wait(lambda: page.project is not None, 30.0, "reopen-project")
        self._wait(
            lambda: page.video.controller is not None and page.video.controller.running,
            20.0,
            "reopen-mpv",
        )
        project = page.project
        page.timeline.set_visible_window(0, 60_000)
        self._pump(250)
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(150)
        v2 = self._track(project, "V2")
        clip = v2.clips[0]
        if not self._track(project, "V1").enabled:
            self._toggle_track("V1")
        self._toggle_track("V1")
        seek = self._click_ruler(10_000, settle_ms=1_000)
        expected = str(Path(os.environ["TWOBYTEASR_P8A_R1_SECOND_MEDIA"]).resolve()).casefold()
        self._wait(
            lambda: str(
                page.video.controller.observed_property("path", "")
                or page.video._media_path
            ).casefold() == expected,
            12.0,
            "reopen-v2-path",
        )
        if page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
        before = int(page.timeline.playhead_ms)
        self._pump(2_000)
        after = int(page.timeline.playhead_ms)
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.MouseButton.LeftButton)
            self._pump(100)
        pixels = self._capture_mpv("reopen-v2-playing")
        linked = next(
            item
            for track in project.audio_tracks
            for item in track.clips
            if item.linked_video_clip_id == clip.id
        )
        self.result["phases"]["reopen"] = {
            "project_path": str(page.project_path.resolve()),
            "v2_timeline_in_ms": int(clip.timeline_in_ms),
            "v2_source_in_ms": int(clip.source_in_ms),
            "linked_audio_timeline_in_ms": int(linked.timeline_in_ms),
            "seek": seek,
            "playhead_before_ms": before,
            "playhead_after_ms": after,
            "pixels": pixels,
        }
        self.result["checks"] = {
            "exact_packaged_exe": bool(getattr(sys, "frozen", False)),
            "v2_still_at_zero": int(clip.timeline_in_ms) == 0
            and int(linked.timeline_in_ms) == 0,
            "v2_reopen_played": after - before >= 1_200,
            "v2_reopen_pixels": pixels["nonblack_ratio"] >= 0.05
            and pixels["mean_luma"] >= 5.0,
            "reopen_seek_10s": abs(int(seek["timeline_ms"]) - 10_000) <= 50,
        }

    def _write(self) -> None:
        self.result_path.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _run(self) -> None:
        try:
            if self.mode == "model":
                self._model_phase()
            elif self.mode == "workflow":
                self._workflow_phase()
            elif self.mode == "reopen":
                self._reopen_phase()
            else:
                raise ValueError(f"Unsupported P8A-R1 audit mode: {self.mode}")
            self.result["accepted"] = all(bool(value) for value in self.result["checks"].values())
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        finally:
            self.result["elapsed_s"] = round(time.time() - self.result["started_at"], 3)
            self._write()
            code = 0 if self.result.get("accepted") else 1
            threading.Thread(
                target=lambda: (time.sleep(0.2), os._exit(code)),
                name="p8a-r1-exit",
                daemon=True,
            ).start()
            try:
                self.window.close()
            except Exception:
                pass
            self.app.quit()


__all__ = ["P8AR1RuntimeAudit", "image_metrics"]
