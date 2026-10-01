"""Packaged R6 evidence for long-FLV timestamp mapping and seeks.

This is real Qt-widget automation against the frozen executable. It records
demux/projection evidence and intentionally leaves human acceptance separate.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .build_identity import load_build_identity, runtime_fingerprint_payload
from .media_time import MediaTimeMapping


class P9AR6PackagedAudit:
    def __init__(self, window, output_dir: str | os.PathLike[str]) -> None:
        self.window = window
        self.page = window.studio_page
        self.app = QApplication.instance()
        self.output = Path(output_dir).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.result_path = self.output / "runtime-result.json"
        self.progress_path = self.output / "runtime-progress.json"
        self.result: dict[str, Any] = {
            "schema": "2byteasr.p9a-r6-packaged-audit.v1",
            "evidence_class": "PACKAGED QT REAL-WIDGET AUTOMATION",
            "real_user_click": False,
            "process": {
                "pid": os.getpid(),
                "executable": str(Path(sys.executable).resolve()),
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            "build_identity": load_build_identity().to_dict(),
            "runtime_fingerprint": runtime_fingerprint_payload(load_build_identity()),
            "phases": {},
            "checks": {},
            "errors": [],
            "started_at": time.time(),
        }

    def start(self) -> None:
        QTimer.singleShot(0, self._run)

    def _pump(self, milliseconds: int) -> None:
        deadline = time.perf_counter() + max(0, int(milliseconds)) / 1000.0
        while time.perf_counter() < deadline:
            self.app.processEvents()
            QTest.qWait(min(16, max(1, round((deadline - time.perf_counter()) * 1000.0))))

    def _wait(self, predicate, timeout: float, label: str) -> None:
        deadline = time.perf_counter() + float(timeout)
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(20)
        raise TimeoutError(f"{label} not ready after {timeout:.1f}s")

    def _write(self) -> None:
        self.result_path.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _metadata(self) -> dict[str, Any]:
        project = self.page.project
        media = dict(getattr(project, "studio_state", {}).get("media_time_mapping", {}) or {})
        path = str(getattr(getattr(project, "media", None), "path", "") or "")
        for asset in getattr(project, "media_pool", ()):
            if str(getattr(asset, "canonical_source", "") or "") == path:
                video = dict(getattr(asset, "video_metadata", {}) or {})
                audio = dict(getattr(asset, "audio_metadata", {}) or {})
                media.update(video)
                media.update(audio)
                media["video_start_ms"] = video.get("start_time_ms", media.get("video_start_ms", 0.0))
                media["audio_start_ms"] = audio.get("start_time_ms", media.get("audio_start_ms", 0.0))
                media["video_timebase"] = video.get("timebase", media.get("video_timebase", ""))
                media["audio_timebase"] = audio.get("timebase", media.get("audio_timebase", ""))
                media["sample_rate"] = audio.get("sample_rate", media.get("sample_rate", 0))
                media["sample_timeline_origin_ms"] = audio.get(
                    "sample_timeline_origin_ms", media.get("sample_timeline_origin_ms", media.get("audio_start_ms", 0.0))
                )
                break
        media.setdefault("source_path", path)
        return media

    def _seek_one(self, target_s: float) -> dict[str, Any]:
        page = self.page
        controller = page.video.controller
        mapping = MediaTimeMapping.from_metadata(self._metadata())
        started = time.perf_counter()
        page._seek(float(target_s))
        target_ms = round(float(target_s) * 1000.0)
        settled = None
        deadline = time.perf_counter() + 20.0
        while time.perf_counter() < deadline:
            self._pump(40)
            observed = controller.observed_properties() if controller is not None else {}
            value = observed.get("time-pos") if isinstance(observed, Mapping) else None
            if value is not None and abs(float(value) - float(target_s)) <= 0.15:
                settled = observed
                break
        paused_observed = settled or (controller.observed_properties() if controller is not None else {})
        timeline_at_settle_ms = int(getattr(page.timeline, "playhead_ms", 0) or 0)

        # A paused seek can expose the target time without producing a fresh
        # decoded frame/audio observation. Resume briefly so the evidence is
        # tied to live demux/decode, then pause before recording the result.
        live_observed: Mapping[str, Any] = {}
        if settled is not None:
            page.video.set_paused(False)
            live_deadline = time.perf_counter() + 4.0
            while time.perf_counter() < live_deadline:
                self._pump(40)
                candidate = controller.observed_properties() if controller is not None else {}
                if isinstance(candidate, Mapping):
                    frame_candidate = candidate.get("video-frame-info")
                    frame_ready = isinstance(frame_candidate, Mapping) and (
                        frame_candidate.get("pts") is not None
                        or frame_candidate.get("estimated-frame-number") is not None
                        or frame_candidate.get("picture-type")
                    )
                    audio_ready = candidate.get("audio-pts") is not None
                    if frame_ready and audio_ready:
                        live_observed = dict(candidate)
                        break
                    if not live_observed and (frame_ready or audio_ready):
                        live_observed = dict(candidate)
            page.video.set_paused(True)
            self._pump(120)
        observed = dict(live_observed or paused_observed)
        if live_observed:
            post_pause = controller.observed_properties() if controller is not None else {}
            if isinstance(post_pause, Mapping):
                # Keep the decoded frame/audio fields from the live sample,
                # while recording pause/seeking as observed after the audit
                # has returned the player to its stable state.
                observed.update(post_pause)
        frame = observed.get("video-frame-info") if isinstance(observed, Mapping) else {}
        audio_pts = observed.get("audio-pts") if isinstance(observed, Mapping) else None
        video_pts = frame.get("pts") if isinstance(frame, Mapping) else None
        frame_signal = bool(isinstance(frame, Mapping) and any(
            frame.get(key) is not None
            for key in ("pts", "estimated-frame-number", "picture-type", "estimated-smpte-timecode")
        ))
        trace = next(
            (
                item for item in reversed(page.video.seek_latency_traces())
                if abs(float(item.get("target_seconds", -1.0)) - float(target_s)) < 0.001
            ),
            {},
        )
        source_ms = float(observed.get("time-pos") or target_s) * 1000.0
        expected = mapping.describe_seek(target_ms)
        normalized_offset = None
        if video_pts is not None and audio_pts is not None:
            normalized_offset = (
                (float(video_pts) * 1000.0 - mapping.video_start_ms)
                - (float(audio_pts) * 1000.0 - mapping.audio_start_ms)
            )
        elif frame_signal and audio_pts is not None:
            # mpv's media clock is the normalized video presentation domain
            # when the backend omits a numeric frame PTS.
            normalized_offset = source_ms - (
                float(audio_pts) * 1000.0 - mapping.audio_start_ms
            )
        screenshot = self.output / "screenshots" / f"seek-{int(target_s)}s.png"
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        try:
            controller.screenshot_to_file(screenshot, mode="video")
        except Exception as exc:
            screenshot_error = f"{type(exc).__name__}: {exc}"
        else:
            screenshot_error = ""
        waveform = page.timeline.waveform_cache_for_source(str(getattr(project.media, "path", ""))) if (project := page.project) else None
        waveform_meta = waveform.metadata.to_dict() if waveform is not None else {}
        result = {
            "target_seconds": float(target_s),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "settled": settled is not None,
            "project_timeline_at_seek_settle_ms": timeline_at_settle_ms,
            "project_timeline_ms": int(getattr(page.timeline, "playhead_ms", 0) or 0),
            "visual_position_ms": round(float(page.video.visual_position()) * 1000.0, 3),
            "mpv_time_pos_ms": round(source_ms, 3),
            "mpv_pause": observed.get("pause") if isinstance(observed, Mapping) else None,
            "mpv_seeking": observed.get("seeking") if isinstance(observed, Mapping) else None,
            "live_decode_observed": bool(live_observed),
            "video_frame_info": dict(frame) if isinstance(frame, Mapping) else {},
            "video_frame_signal": "pts" if video_pts is not None else "frame-info+mpv-time-pos" if frame_signal else "",
            "video_frame_observed_media_ms": round(source_ms, 3) if frame_signal else None,
            "video_frame_pts_ms": round(float(video_pts) * 1000.0, 3) if video_pts is not None else None,
            "audio_observed_pts_ms": round(float(audio_pts) * 1000.0, 3) if audio_pts is not None else None,
            "normalized_av_offset_ms": round(normalized_offset, 3) if normalized_offset is not None else None,
            "mapping": expected,
            "seek_trace": trace,
            "waveform_metadata": waveform_meta,
            "screenshot": str(screenshot) if screenshot.is_file() else "",
            "screenshot_error": screenshot_error,
        }
        result["checks"] = {
            "settled": result["settled"],
            "timeline_target_within_150ms": abs(result["project_timeline_at_seek_settle_ms"] - target_ms) <= 150,
            "mpv_target_within_150ms": abs(result["mpv_time_pos_ms"] - target_ms) <= 150,
            "video_frame_observed": result["video_frame_observed_media_ms"] is not None,
            "audio_pts_observed": result["audio_observed_pts_ms"] is not None,
            "live_decode_observed": result["live_decode_observed"],
            "av_hard_gate_if_observed": normalized_offset is not None and abs(normalized_offset) < 150,
        }
        return result

    def _run(self) -> None:
        try:
            self._wait(lambda: self.page.project is not None, 45.0, "project")
            self._wait(
                lambda: self.page.video.controller is not None and self.page.video.controller.running,
                30.0,
                "mpv",
            )
            targets = (60.0, 600.0, 1800.0, 3600.0)
            rows = [self._seek_one(target) for target in targets]
            metadata = self._metadata()
            self.result["phases"]["real_flv"] = {
                "media_path": str(getattr(self.page.project.media, "path", "")),
                "metadata": metadata,
                "seeks": rows,
            }
            self.result["checks"] = {
                "exact_packaged_exe": bool(getattr(sys, "frozen", False)),
                "real_flv_path": bool(metadata.get("source_path") or getattr(self.page.project.media, "path", "")),
                "all_seeks_settled": all(row["checks"]["settled"] for row in rows),
                "all_timeline_targets": all(row["checks"]["timeline_target_within_150ms"] for row in rows),
                "all_mpv_targets": all(row["checks"]["mpv_target_within_150ms"] for row in rows),
                "all_av_offsets_under_150ms_when_observed": all(
                    row["checks"]["av_hard_gate_if_observed"] for row in rows
                ),
                "all_live_decode_observed": all(
                    row["checks"]["live_decode_observed"] for row in rows
                ),
                "all_video_frames_observed": all(
                    row["checks"]["video_frame_observed"] for row in rows
                ),
                "all_audio_pts_observed": all(
                    row["checks"]["audio_pts_observed"] for row in rows
                ),
            }
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            self.result["accepted"] = bool(
                not self.result["errors"] and all(self.result["checks"].values())
            )
            self.result["elapsed_s"] = round(time.time() - self.result["started_at"], 3)
            self._write()
            QTimer.singleShot(500, self.window.close)
            QTimer.singleShot(900, self.app.quit)


__all__ = ["P9AR6PackagedAudit"]
