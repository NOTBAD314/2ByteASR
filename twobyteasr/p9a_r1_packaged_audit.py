"""P9A-R1 packaged-EXE human-truth audit.

Runs inside the real ``dist\\2ByteASR\\2ByteASR.exe`` process: verifies the
build identity file, the Style Inspector contracts (no X/Y offsets, angle
disc, non-white control fields, unclipped responsive tabs), the gradient
survival gates (stroke edit + save/reopen), real review evidence coverage,
a real AI-design generate attempt, the localized export dialog, and audio
seek/play latency samples on the loaded media.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import psutil

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from .build_identity import BUILD_ROUND_ID, load_build_identity, user_data_root
from .runtime_trace import GLOBAL_STUDIO_TRACE
from .studio_project import load_project, save_project
from .studio_review import review_evidence_coverage
from .style_recipe import FillSpec


def audio_sample_matches_target(
    sample: dict[str, Any],
    *,
    prior_generation: int,
    target_ms: int,
    tolerance_ms: int = 250,
) -> bool:
    """Require samples from the post-seek decoder, not an old buffered stream.

    A long FLV can take seconds to return its first PCM block.  During that
    wait the project clock (and therefore ``requested_source_ms``) continues
    to advance, so the decoder command start and source generation are the
    stable target identity; the live request is telemetry, not a target-frame
    acknowledgement.
    """
    return (
        int(sample.get("source_generation") or 0) > int(prior_generation)
        and abs(int(sample.get("decoder_command_start_ms") or 0) - int(target_ms))
        <= int(tolerance_ms)
    )


class P9AR1PackagedAudit:
    def __init__(self, window, output_dir: str | os.PathLike[str]) -> None:
        self.window = window
        self.page = window.studio_page
        self.app = QApplication.instance()
        self.output = Path(output_dir).resolve()
        self.shots = self.output / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.result_path = self.output / "runtime-result.json"
        self.result: dict[str, Any] = {
            "schema": "2byteasr.p9a-r1-packaged-audit.v1",
            "round_id": BUILD_ROUND_ID,
            "started_at": time.time(),
            "process": {
                "pid": os.getpid(),
                "executable": str(Path(sys.executable).resolve()),
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            "checks": {},
            "phases": {},
            "errors": [],
        }

    # ---------------------------------------------------------------- utils
    def start(self) -> None:
        QTimer.singleShot(0, self._run)

    def _pump(self, milliseconds: int) -> None:
        deadline = time.perf_counter() + max(0, int(milliseconds)) / 1000.0
        while time.perf_counter() < deadline:
            self.app.processEvents()
            QTest.qWait(10)

    def _wait(self, predicate: Callable[[], bool], timeout: float, label: str) -> float:
        started = time.perf_counter()
        while time.perf_counter() - started < timeout:
            self.app.processEvents()
            if predicate():
                return round((time.perf_counter() - started) * 1000.0, 1)
            QTest.qWait(20)
        raise TimeoutError(f"{label} not ready after {timeout:.1f}s")

    def _capture(self, widget, name: str) -> str:
        target = self.shots / name
        pixmap = widget.grab()
        if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
            raise RuntimeError(f"screenshot failed: {target}")
        return str(target)

    def _phase(self, name: str, run: Callable[[], dict[str, Any]]) -> None:
        started = time.perf_counter()
        try:
            (self.output / "runtime-progress.json").write_text(
                json.dumps({"phase": name, "state": "running", "t": started}),
                encoding="utf-8",
            )
            payload = run() or {}
            payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            self.result["phases"][name] = {"ok": True, **payload}
            (self.output / "runtime-progress.json").write_text(
                json.dumps({"phase": name, "state": "done"}),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - audit must survive and report
            self.result["phases"][name] = {
                "ok": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "error": f"{type(exc).__name__}: {exc}",
            }
            self.result["errors"].append(f"{name}: {exc}")
            (self.output / "runtime-progress.json").write_text(
                json.dumps({"phase": name, "state": "failed", "error": str(exc)}),
                encoding="utf-8",
            )

    # ---------------------------------------------------------------- phases
    def _phase_identity(self) -> dict[str, Any]:
        path = user_data_root() / "logs" / "build_identity.json"
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        identity = load_build_identity()
        checks = {
            "identity_file_written": path.is_file(),
            "round_id_matches": raw.get("round_id") == BUILD_ROUND_ID,
            "frozen_reported": bool(raw.get("sys_frozen")),
            "build_id_present": bool(raw.get("build_id")),
        }
        return {
            "identity_path": str(path),
            "payload": raw,
            "build_id": identity and raw.get("build_id", ""),
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_project(self) -> dict[str, Any]:
        wait_ms = self._wait(
            lambda: bool(self.page.project and self.page.project.cues),
            45.0,
            "project cues",
        )
        media = str(self.page.project.media.path)
        return {
            "wait_ms": wait_ms,
            "cue_count": len(self.page.project.cues),
            "media_path": media,
            "audio_only": bool(not self.page.project.media.width),
            "duration_ms": self.page.project.media.duration_ms,
        }

    def _visible_labels_contain(self, needle: str) -> bool:
        for label in self.page.findChildren(QLabel):
            if not label.isVisibleTo(self.page):
                continue
            if needle in label.text():
                return True
        return False

    def _phase_tabs(self) -> dict[str, Any]:
        page = self.page
        self.window.showMaximized()
        self._pump(320)
        page._update_context_tab_labels()
        self._pump(80)
        drawer = page.context_drawer
        full_labels = [drawer.tabText(i) for i in range(drawer.count())]
        # Icon mode uses empty text by design; the gates are: no ellipsis
        # truncation, every tab visible, and full names in tooltips.
        clipped_full = [t for t in full_labels if t.rstrip().endswith(("…", "..."))]
        shot_full = self._capture(drawer.tabBar(), "p9a_r1_packaged_tabs.png")

        self.window.showNormal()
        self.window.resize(860, 700)
        self._pump(320)
        page._update_context_tab_labels()
        self._pump(80)
        narrow_labels = [drawer.tabText(i) for i in range(drawer.count())]
        clipped_narrow = [t for t in narrow_labels if t.rstrip().endswith(("…", "..."))]
        tooltips = [drawer.tabToolTip(i) for i in range(drawer.count())]
        self.window.showMaximized()
        self._pump(150)
        checks = {
            "no_clipped_full": not clipped_full,
            "no_clipped_narrow": not clipped_narrow,
            "tooltips_complete": all(tooltips),
            "all_tabs_visible": all(
                drawer.tabBar().isTabVisible(index) for index in range(drawer.count())
            ),
        }
        return {
            "full_labels": full_labels,
            "narrow_labels": narrow_labels,
            "tooltips": tooltips,
            "screenshot": shot_full,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_style_shadow(self) -> dict[str, Any]:
        page = self.page
        page.context_drawer.setCurrentIndex(2)
        self._pump(220)
        rows = getattr(page, "_appearance_rows", {}) or {}
        shadow_row = rows.get("shadow")
        if shadow_row is None:
            raise RuntimeError("shadow property row missing")
        shadow_row.set_expanded(True)
        self._pump(120)
        offset_x_visible = page.style_shadow_offset_x.isVisibleTo(
            page.style_shadow_offset_x.parentWidget()
        )
        offset_y_visible = page.style_shadow_offset_y.isVisibleTo(
            page.style_shadow_offset_y.parentWidget()
        )
        angle_visible = bool(
            getattr(page, "style_shadow_angle", None)
            and page.style_shadow_angle.isVisibleTo(shadow_row)
        )
        xy_label_visible = self._visible_labels_contain("X偏移") or self._visible_labels_contain(
            "X 偏移"
        ) or self._visible_labels_contain("Y偏移") or self._visible_labels_contain("Y 偏移")
        shadow_shot = self._capture(shadow_row, "p9a_r1_packaged_shadow.png")

        button = getattr(page, "style_fill_button", None)
        white_field = None
        swatch_pixel = None
        if button is not None:
            image = button.grab().toImage()
            color = image.pixelColor(6, 6)
            swatch_pixel = (color.red(), color.green(), color.blue())
            white_field = all(value > 240 for value in swatch_pixel)
        style_shot = self._capture(page.context_panel, "p9a_r1_packaged_style.png")
        checks = {
            "offset_x_hidden": not offset_x_visible,
            "offset_y_hidden": not offset_y_visible,
            "angle_disc_visible": angle_visible,
            "xy_labels_absent": not xy_label_visible,
            "fill_button_not_white": white_field is False,
        }
        return {
            "fill_button_pixel_rgb": swatch_pixel,
            "shadow_screenshot": shadow_shot,
            "style_screenshot": style_shot,
            "checks": checks,
            "ok": all(checks.values()),
        }

    @staticmethod
    def _fill_of(project, style_id: str) -> dict[str, Any]:
        fill = project.style_recipes.get(style_id, {}).get("colors", {}).get("fill")
        if isinstance(fill, dict):
            return fill
        if isinstance(fill, str):
            return {"type": "solid", "color": fill}
        return {}

    def _phase_gradient(self) -> dict[str, Any]:
        page = self.page
        page.select_cue(page.project.cues[0].id)
        self._pump(400)
        gradient = FillSpec.linear(
            [
                {"color": "#FFFFAA00", "position": 0.0},
                {"color": "#FF00FF88", "position": 1.0},
            ],
            angle=90,
        )
        page._apply_fill_spec(gradient)
        self._pump(300)
        # Real user path: a numeric edit auto-commits through the debounced
        # _style_control_changed (180 ms). Do not stack a manual _apply_style
        # on top of that transaction.
        page.style_outline_width.setValue(10.0)
        self._pump(700)
        cue = page._cue_lookup[page.selected_cue_id]
        runtime_fill = self._fill_of(page.project, cue.style_id)
        stroke_kept = (
            runtime_fill.get("type") == "linear-gradient"
            and len(runtime_fill.get("stops") or []) == 2
            and runtime_fill.get("angle") == 90
        )

        reopen_path = self.output / "gradient-reopen.2byteproj"
        save_project(page.project, reopen_path)
        loaded = load_project(reopen_path)
        loaded_cue = next(item for item in loaded.cues if item.id == cue.id)
        reopen_fill = self._fill_of(loaded, loaded_cue.style_id)
        reopen_kept = reopen_fill.get("type") == "linear-gradient" and len(
            reopen_fill.get("stops") or []
        ) == 2
        checks = {
            "stroke_edit_preserves_gradient": stroke_kept,
            "save_reopen_preserves_gradient": reopen_kept,
        }
        return {
            "cue_style_id": cue.style_id,
            "reopen_style_id": loaded_cue.style_id,
            "runtime_fill": runtime_fill,
            "reopen_fill": reopen_fill,
            "reopen_project": str(reopen_path),
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_review(self) -> dict[str, Any]:
        page = self.page
        page.context_drawer.setCurrentIndex(1)
        self._pump(240)
        page.select_cue(page.project.cues[0].id)
        self._pump(240)
        coverage = review_evidence_coverage(page.project)
        shot = self._capture(page.context_panel, "p9a_r1_packaged_review.png")
        badge = getattr(page, "review_coverage_label", None)
        badge_text = badge.text() if badge is not None else ""
        single_source_wording = "单来源" in badge_text or coverage["FIRERED_COUNT"] + coverage[
            "QWEN_COUNT"
        ] == 0
        checks = {
            "coverage_computed": coverage["TOTAL"] > 0,
            "single_source_not_called_consensus": single_source_wording,
        }
        return {
            "coverage": coverage,
            "coverage_label": badge_text,
            "screenshot": shot,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_ai_design(self) -> dict[str, Any]:
        page = self.page
        page.context_drawer.setCurrentIndex(0)
        self._pump(260)
        shot = self._capture(page.context_panel, "p9a_r1_packaged_ai.png")
        provider_label = getattr(page, "ai_provider_health", None)
        status_text = provider_label.text() if provider_label is not None else ""
        generate: dict[str, Any] = {"attempted": False}
        try:
            import threading

            from .studio_ai import request_style_design

            cue_id = page.selected_cue_id or page.project.cues[0].id
            settings = dict(page.runtime_settings) if page.runtime_settings else {}
            outcome: dict[str, Any] = {}

            def _work() -> None:
                started = time.perf_counter()
                try:
                    suggestion = request_style_design(
                        page.project,
                        cue_id,
                        "清晰易读的对白字幕，轻微描边",
                        settings,
                        deadline_seconds=22.0,
                    )
                    outcome.update(
                        {
                            "provider_succeeded": bool(suggestion.provider_succeeded),
                            "failure_stage": suggestion.failure_stage,
                            "provider_error_category": suggestion.provider_error_category,
                            "pipeline_status": dict(suggestion.pipeline_status),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome["hard_error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    outcome["elapsed_s"] = round(time.perf_counter() - started, 1)

            worker = threading.Thread(target=_work, name="p9a-r1-ai-probe", daemon=True)
            worker.start()
            deadline = time.perf_counter() + 32.0
            while worker.is_alive() and time.perf_counter() < deadline:
                self._pump(60)
            generate = {"attempted": True, **outcome}
        except Exception as exc:  # noqa: BLE001
            generate = {"attempted": True, "hard_error": f"{type(exc).__name__}: {exc}"}
        checks = {
            "generate_attempted": bool(generate.get("attempted")),
            "stage_reported": bool(
                generate.get("failure_stage") or generate.get("provider_succeeded")
            ),
        }
        return {
            "provider_status_label": status_text,
            "generate": generate,
            "screenshot": shot,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_export_dialog(self) -> dict[str, Any]:
        from .studio_export_ui import SubtitleExportDialog

        dialog = SubtitleExportDialog(self.page.project, None, self.page)
        dialog.show()
        self._pump(260)
        shot = self._capture(dialog, "p9a_r1_packaged_export.png")
        texts = [b.text() for b in dialog.findChildren(QPushButton)]
        checks = {
            "chinese_primary": any("导出字幕" in t for t in texts),
            "chinese_cancel": any("取消" in t for t in texts),
            "no_english_save_cancel": not any(t.strip() in {"Save", "Cancel"} for t in texts),
        }
        dialog.close()
        dialog.deleteLater()
        return {"buttons": texts, "screenshot": shot, "checks": checks, "ok": all(checks.values())}

    def _phase_audio_latency(self) -> dict[str, Any]:
        page = self.page
        controller = getattr(page.video, "controller", None)
        if controller is None or not getattr(controller, "running", False):
            return {"skipped": "media controller not running", "ok": True}
        duration_s = max(1.0, page.project.media.duration_ms / 1000.0)
        page._seek(2.0)
        self._pump(900)
        for index in range(8):
            page._seek(min(duration_s - 5.0, 5.0 + index * (duration_s - 12.0) / 8.0))
            self._pump(420)

        canvas = getattr(page, "video", None)
        traces = canvas.seek_latency_traces() if hasattr(canvas, "seek_latency_traces") else []

        def _marker_ms(trace: dict[str, Any], name: str) -> float | None:
            elapsed = trace.get("elapsed_ms")
            if isinstance(elapsed, dict) and name in elapsed:
                return float(elapsed[name])
            markers = trace.get("markers")
            if not isinstance(markers, dict):
                return None
            base = markers.get("T0_user_input")
            stamp = markers.get(name)
            if isinstance(base, (int, float)) and isinstance(stamp, (int, float)):
                return (float(stamp) - float(base)) * 1000.0
            return None

        first_fb = [
            value
            for trace in traces
            if (value := _marker_ms(trace, "T2_optimistic_playhead_visible")) is not None
        ]
        settled = [
            value
            for trace in traces
            if (value := _marker_ms(trace, "T9_event_loop_settled")) is not None
        ]

        def _p(values: list[float]) -> dict[str, float]:
            if not values:
                return {}
            ordered = sorted(values)
            return {
                "n": len(values),
                "p50": round(statistics.median(ordered), 1),
                "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 1),
                "max": round(ordered[-1], 1),
            }

        try:
            play_duration_ms = max(
                500, int(os.environ.get("TWOBYTEASR_P9A_R4_PLAY_MS", "2600"))
            )
        except ValueError:
            play_duration_ms = 2600
        process = psutil.Process(os.getpid())
        position_samples: list[float] = []
        process_samples: list[dict[str, float | int]] = []
        play_started = time.perf_counter()
        if page.video.playback_position_snapshot().paused:
            page._toggle_playback()
        sample_deadline = time.perf_counter() + play_duration_ms / 1000.0
        while time.perf_counter() < sample_deadline:
            self._pump(min(250, max(1, round((sample_deadline - time.perf_counter()) * 1000))))
            position_samples.append(round(float(page.video.visual_position()), 4))
            try:
                children = process.children(recursive=True)
                process_samples.append({
                    "cpu_percent": float(process.cpu_percent(interval=None)),
                    "rss_bytes": int(process.memory_info().rss),
                    "thread_count": int(process.num_threads()),
                    "ffmpeg_count": sum(
                        child.is_running() and child.name().casefold() == "ffmpeg.exe"
                        for child in children
                    ),
                })
            except (psutil.Error, OSError):
                pass
        audio_telemetry = {}
        engine = getattr(page, "audio_engine", None)
        if engine is not None and hasattr(engine, "telemetry_snapshot"):
            snapshot = engine.telemetry_snapshot()
            audio_telemetry = {
                "state": snapshot.get("state"),
                "decode_lateness_ms": snapshot.get("decode_lateness_ms"),
                "buffer_bytes": snapshot.get("buffer_bytes"),
            }
        if not page.video.playback_position_snapshot().paused:
            page._toggle_playback()
        self._pump(300)
        play_feedback_ms = round((time.perf_counter() - play_started) * 1000.0, 1)
        position_regressions = sum(
            1 for left, right in zip(position_samples, position_samples[1:])
            if right < left - 0.12
        )
        loop_events = [
            dict(item) for item in GLOBAL_STUDIO_TRACE.recent()
            if item.get("event") == "PLAYBACK_LOOP_DETECTED"
        ]
        return {
            "seek_first_feedback": _p(first_fb),
            "seek_settled": _p(settled),
            "play_toggle_wall_ms": play_feedback_ms,
            "play_duration_ms": play_duration_ms,
            "position_samples": position_samples,
            "position_advance_s": round(
                max(position_samples) - min(position_samples), 4
            ) if position_samples else 0.0,
            "position_regressions": position_regressions,
            "loop_events": loop_events,
            "startup_milestones_ms": dict(
                getattr(page, "_studio_startup_milestones", {}) or {}
            ),
            "process_peaks": {
                "cpu_percent": max(
                    (float(item["cpu_percent"]) for item in process_samples), default=0.0
                ),
                "rss_bytes": max(
                    (int(item["rss_bytes"]) for item in process_samples), default=0
                ),
                "thread_count": max(
                    (int(item["thread_count"]) for item in process_samples), default=0
                ),
                "ffmpeg_count": max(
                    (int(item["ffmpeg_count"]) for item in process_samples), default=0
                ),
            },
            "audio_telemetry": audio_telemetry,
            "trace_sample_keys": sorted(traces[-1].keys()) if traces else [],
        }

    def _phase_target_audio_seek(self) -> dict[str, Any]:
        """Measure one user-style seek through the packaged QAudioSink path."""
        page = self.page
        target_s = max(
            0.0, float(os.environ.get("TWOBYTEASR_P9A_R5_AUDIO_TARGET_SECONDS", "3600"))
        )
        if not page.project or target_s >= page.project.media.duration_ms / 1000.0:
            raise RuntimeError(f"audio target {target_s:.3f}s is outside project media")
        if not page.video.playback_position_snapshot().paused:
            page._toggle_playback()
            self._pump(180)

        pre_seek = page.audio_engine.telemetry_snapshot()
        prior_generation = int(pre_seek.get("source_generation") or 0)
        started = time.perf_counter()
        page._seek(target_s)
        self._pump(40)
        if page.video.playback_position_snapshot().paused:
            page._toggle_playback()

        decoded_ms = None
        consumed_ms = None
        samples: list[dict[str, Any]] = []
        target_ms = round(target_s * 1000.0)
        deadline = started + 4.5
        while time.perf_counter() < deadline:
            self._pump(20)
            telemetry = page.audio_engine.telemetry_snapshot()
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            sample = {
                "elapsed_ms": elapsed_ms,
                "state": str(telemetry.get("state") or ""),
                "source_generation": int(telemetry.get("source_generation") or 0),
                "decoder_command_start_ms": int(
                    telemetry.get("decoder_command_start_ms") or 0
                ),
                "requested_source_ms": int(telemetry.get("requested_source_ms") or 0),
                "decoded_bytes": int(telemetry.get("decoded_bytes") or 0),
                "sink_consumed_bytes": int(telemetry.get("sink_consumed_bytes") or 0),
                "decode_lateness_ms": telemetry.get("decode_lateness_ms"),
            }
            samples.append(sample)
            is_target_decoder = audio_sample_matches_target(
                sample,
                prior_generation=prior_generation,
                target_ms=target_ms,
            )
            if is_target_decoder and decoded_ms is None and sample["decoded_bytes"] > 0:
                decoded_ms = elapsed_ms
            if is_target_decoder and sample["sink_consumed_bytes"] > 0:
                consumed_ms = elapsed_ms
                break
        final = page.audio_engine.telemetry_snapshot()
        if not page.video.playback_position_snapshot().paused:
            page._toggle_playback()
        self._pump(120)
        target_samples = [
            item for item in samples
            if audio_sample_matches_target(
                item,
                prior_generation=prior_generation,
                target_ms=target_ms,
            )
        ]
        generations = sorted({
            int(item["source_generation"]) for item in samples
            if item in target_samples and int(item["source_generation"]) > 0
        })
        checks = {
            "post_seek_decoder_started": bool(target_samples),
            "pcm_decoded": decoded_ms is not None,
            "sink_consumed": consumed_ms is not None,
            "hard_ceiling_4s": consumed_ms is not None and consumed_ms < 4000.0,
            "decoder_not_restarted_while_waiting": len(generations) <= 1,
        }
        return {
            "target_seconds": target_s,
            "first_decoded_ms": decoded_ms,
            "first_sink_consumed_ms": consumed_ms,
            "prior_source_generation": prior_generation,
            "source_generations": generations,
            "pre_seek_telemetry": pre_seek,
            "final_telemetry": final,
            "startup_state": page.video.startup_state_snapshot(),
            "hwdec": dict(getattr(page.video, "_last_hwdec_snapshot", {}) or {}),
            "samples": samples,
            "checks": checks,
            "ok": all(checks.values()),
        }

    def _phase_ai_config_persistence(self) -> dict[str, Any]:
        """Exercise the same UI save gate used immediately before recognition."""
        phase = os.environ.get("TWOBYTEASR_P9A_R5_CONFIG_PHASE", "").strip().lower()
        if phase not in {"save", "reopen"}:
            raise RuntimeError(f"unknown config audit phase: {phase}")
        editor = self.window.polish_editor
        if phase == "save":
            index = editor.service.findData("antigravity")
            if index < 0:
                raise RuntimeError("Antigravity service is missing from AI settings")
            editor.service.setCurrentIndex(index)
            editor.model.setCurrentText("gemini-3.7-flash-high")
        self.window.ai_grouping.setChecked(False)
        editor._model_discovery_timer.stop()
        self.window.group_editor._model_discovery_timer.stop()

        before = editor.values()
        saved = self.window._save_ai_configuration(
            show_feedback=False,
            require_ready=(phase == "reopen"),
        )
        from .llm_config import active_service_values

        persisted = active_service_values(self.window.legacy.RUNTIME_SETTINGS)
        checks = {
            "ui_save_returned_true": saved is True,
            "service_preserved": persisted.get("service") == "antigravity",
            "provider_preserved": persisted.get("provider") == "google_antigravity",
            "transport_preserved": persisted.get("transport") == "antigravity_cli",
            "model_preserved": persisted.get("model") == "gemini-3.7-flash-high",
            "recognition_start_config_gate": phase != "reopen" or saved is True,
        }
        return {
            "phase": phase,
            "editor_before": {
                key: before.get(key) for key in (
                    "service", "provider", "transport", "base_url", "model"
                )
            },
            "persisted": persisted,
            "status_text": self.window.ai_save_status.text(),
            "checks": checks,
            "ok": all(checks.values()),
        }

    # ---------------------------------------------------------------- driver
    def _run(self) -> None:
        skip = {
            item.strip()
            for item in os.environ.get("TWOBYTEASR_P9A_R1_SKIP", "").split(",")
            if item.strip()
        }
        try:
            self._phase("identity", self._phase_identity)
            config_phase = os.environ.get("TWOBYTEASR_P9A_R5_CONFIG_PHASE", "").strip()
            target_audio = os.environ.get(
                "TWOBYTEASR_P9A_R5_AUDIO_TARGET_SECONDS", ""
            ).strip()
            if config_phase:
                self._phase("ai_config_persistence", self._phase_ai_config_persistence)
            elif target_audio:
                self._phase("project", self._phase_project)
                self._phase("target_audio_seek", self._phase_target_audio_seek)
            elif "project" not in skip:
                self._phase("project", self._phase_project)
            if not config_phase and not target_audio and "tabs" not in skip:
                self._phase("tabs", self._phase_tabs)
            if not config_phase and not target_audio and "style_shadow" not in skip:
                self._phase("style_shadow", self._phase_style_shadow)
            if not config_phase and not target_audio and "gradient" not in skip:
                self._phase("gradient", self._phase_gradient)
            if not config_phase and not target_audio and "review" not in skip:
                self._phase("review", self._phase_review)
            if not config_phase and not target_audio and "ai_design" not in skip:
                self._phase("ai_design", self._phase_ai_design)
            if not config_phase and not target_audio and "export_dialog" not in skip:
                self._phase("export_dialog", self._phase_export_dialog)
            if not config_phase and not target_audio and "audio_latency" not in skip:
                self._phase("audio_latency", self._phase_audio_latency)
        finally:
            self.result["finished_at"] = time.time()
            phases = self.result["phases"]
            if os.environ.get("TWOBYTEASR_P9A_R5_CONFIG_PHASE", "").strip():
                gate_names = ("identity", "ai_config_persistence")
            elif os.environ.get("TWOBYTEASR_P9A_R5_AUDIO_TARGET_SECONDS", "").strip():
                gate_names = ("identity", "project", "target_audio_seek")
            else:
                gate_names = ("identity", "tabs", "style_shadow", "gradient", "review")
            self.result["checks"] = {
                name: bool(phases.get(name, {}).get("ok")) for name in gate_names
            }
            self.result["accepted"] = bool(
                self.result["checks"].values()
                and all(self.result["checks"].values())
                and not self.result["errors"]
            )
            try:
                self.result_path.write_text(
                    json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            # Teardown order matters: a queued Remotion preview that is still
            # spinning up when the window is destroyed trips Qt6Core's
            # fail-fast (0xC0000409). Revoke previews and close the page
            # cleanly before quitting the app.
            try:
                revoke = getattr(self.page, "_revoke_advanced_preview", None)
                if callable(revoke):
                    revoke(reason="p9a_r1_audit_shutdown")
            except Exception:  # noqa: BLE001
                pass
            self._pump(1200)
            try:
                self.page.close_page()
            except Exception:  # noqa: BLE001
                pass
            self._pump(800)
            try:
                self.window.close()
            except Exception:  # noqa: BLE001
                pass
            QTimer.singleShot(1500, self.app.quit)
