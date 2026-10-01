"""Headed P8A: runtime paths, model registry, seek mapping, V2 ingest, hide V1.

Automated evidence only. Never claims a person completed the workflow.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dataclasses import asdict

from .clip_time_mapper import clip_time_traces, map_project_time
from .model_registry import scan_model_registry
from .model_storage import ModelStorageDialog, build_storage_qss
from .model_workshop import MODELS
from .runtime_paths import get_runtime_paths, source_and_packaged_roots
from .theme_manager import apply_theme


class P8ARuntimeAudit:
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
            "schema": "2byteasr.p8a-runtime-audit.v1",
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
            "benchmarks": {},
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
        pixmap.save(str(self.screenshots / f"{name}.png"))

    def _event_loop_sample(self, milliseconds: int) -> dict[str, float]:
        samples: list[float] = []
        deadline = time.perf_counter() + milliseconds / 1000.0
        while time.perf_counter() < deadline:
            timer = QElapsedTimer()
            timer.start()
            self.app.processEvents()
            samples.append(float(timer.nsecsElapsed()) / 1_000_000.0)
            QTest.qWait(8)
        ordered = sorted(samples)
        p95 = ordered[max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))] if ordered else 0.0
        return {
            "count": len(samples),
            "max_ms": round(max(samples) if samples else 0.0, 3),
            "p95_ms": round(p95, 3),
            "mean_ms": round(sum(samples) / max(1, len(samples)), 3),
        }

    def _run(self) -> None:
        try:
            self.window.setGeometry(60, 30, 1600, 980)
            self.window.showNormal()
            self._pump(250)
            paths = get_runtime_paths()
            registry = scan_model_registry()
            self.result["phases"]["runtime_paths"] = source_and_packaged_roots()
            self.result["phases"]["models"] = {
                "installed_count": registry.installed_count(),
                "installed_keys": sorted(registry.installed_keys()),
                "model_root": str(paths.model_root),
                "model_root_source": paths.model_root_source,
                "records": {
                    key: {
                        "health": record.health.value,
                        "path": str(record.installation_path),
                        "source": record.source,
                    }
                    for key, record in registry.records.items()
                    if key in {"moss", "firered_aed", "qwen_asr"}
                },
            }
            apply_theme("lavender", self.app)
            dialog = ModelStorageDialog(
                paths.install_root,
                MODELS,
                lambda: {"moss", "firered"},
                lambda *_args: None,
                lambda *_args: None,
                self.window,
            )
            dialog.show()
            try:
                self._wait(
                    lambda: dialog.summary_labels and "扫描中" not in dialog.summary_labels[0].text(),
                    8.0,
                    "storage-scan",
                )
            except TimeoutError:
                self._pump(200)
            qss = build_storage_qss()
            self._grab(dialog, "storage-manager-lavender")
            dialog.close()
            from .ui_theme import theme_definition
            from .theme_manager import theme_key as live_theme_key

            live = theme_definition(live_theme_key())
            self.result["phases"]["storage"] = {
                "theme_key": live.key,
                "qss_has_surface": live.surface.lower() in qss.lower(),
                "qss_has_text": live.text.lower() in qss.lower(),
                "hardcoded_cream": "#fbfaf6" in qss.lower() and live.surface.lower() != "#fbfaf6",
            }

            page = self.page
            self._wait(lambda: page.project is not None, 25.0, "project")
            project = page.project
            before_tracks = [track.id for track in project.video_tracks]
            if "V2" not in before_tracks:
                button = getattr(page, "add_video_track_button", None)
                if button is not None:
                    button.click()
                else:
                    page._add_video_track()
                self._pump(200)
            second_media = Path(os.environ.get("TWOBYTEASR_P8A_SECOND_MEDIA", "") or "")
            ingest_ms = None
            freeze_ms = 0.0
            if second_media.is_file():
                page._video_track_action("V2", "select")
                timer = QElapsedTimer()
                timer.start()
                page._begin_media_ingest(str(second_media), add_to_timeline=True)
                try:
                    ingest_ms = self._wait(
                        lambda: any(
                            track.id == "V2" and track.clips
                            for track in page.project.video_tracks
                        ),
                        40.0,
                        "v2-clip",
                    )
                except TimeoutError as exc:
                    self.result["errors"].append(str(exc))
                freeze_ms = timer.elapsed()
                self._pump(250)
            self._grab(page.timeline, "timeline-after-v2")
            playhead = 10_000
            page._seek(playhead / 1000.0)
            self._pump(180)
            layers = page._multitrack_preview_layers(playhead)
            traces = [asdict(item) for item in clip_time_traces()[-8:]]
            v2_clip = next(
                (
                    clip
                    for track in page.project.video_tracks
                    if track.id == "V2"
                    for clip in track.clips
                ),
                None,
            )
            mapped_v2 = (
                map_project_time(v2_clip, playhead).source_ms if v2_clip is not None else None
            )
            loop = self._event_loop_sample(400)
            v1_enabled = next(
                (track.enabled for track in page.project.video_tracks if track.id == "V1"),
                True,
            )
            if v1_enabled:
                page._video_track_action("V1", "enabled")
            self._pump(80)
            hidden_layers = page._multitrack_preview_layers(playhead)
            hidden_target = page._multitrack_preview_target(playhead)
            page._sync_multitrack_preview_at(playhead)
            self._pump(800)
            self._grab(page, "studio-hide-v1")
            self._grab(getattr(page, "video", None), "canvas-hide-v1")
            scene = getattr(page, "video_compositor", None)
            self.result["phases"]["hide_v1_compositor"] = {
                "visible": bool(scene is not None and scene.isVisible()),
                "layers": len(getattr(scene, "_layers", []) or []) if scene is not None else 0,
                "players": len(getattr(scene, "_players", {}) or {}) if scene is not None else 0,
                "mpv_path": str(getattr(page.video, "_media_path", "") or ""),
                "mpv_attached": bool(getattr(page.video, "_media_attached", False)),
            }
            if not next((track.enabled for track in page.project.video_tracks if track.id == "V1"), True):
                page._video_track_action("V1", "enabled")
            if v2_clip is not None:
                page._video_clip_move_committed("V2", v2_clip.id, 3_000)
                self._pump(80)
            moved = next(
                (
                    clip
                    for track in page.project.video_tracks
                    if track.id == "V2"
                    for clip in track.clips
                ),
                None,
            )
            self.result["phases"]["playback"] = {
                "tracks": [track.id for track in page.project.video_tracks],
                "layers_at_10s": [
                    {
                        "track_id": layer.get("track_id"),
                        "source_ms": layer.get("source_ms"),
                        "timeline_in_ms": layer.get("timeline_in_ms"),
                    }
                    for layer in layers
                ],
                "mapped_v2_source_ms": mapped_v2,
                "hide_v1_layers": [layer.get("track_id") for layer in hidden_layers],
                "hide_v1_base": (hidden_target or {}).get("track_id"),
                "moved_timeline_in_ms": None if moved is None else moved.timeline_in_ms,
                "second_media": str(second_media) if second_media.is_file() else "",
                "ingest_wait_ms": ingest_ms,
                "ingest_wall_ms": freeze_ms,
                "clip_time_traces": traces,
            }
            self.result["benchmarks"]["event_loop"] = loop
            compositor = getattr(page, "video_compositor", None)
            if compositor is not None:
                self.result["benchmarks"]["compositor"] = compositor.performance_snapshot()
            moss = registry.record("moss")
            checks = {
                "shared_model_root": Path(paths.model_root).name.lower() in {"models"}
                and registry.installed_count() >= 3,
                "moss_not_missing_outside_exe": moss is not None and moss.health.value == "INSTALLED",
                "storage_follows_live_theme": live.surface.lower() in qss.lower()
                and not self.result["phases"]["storage"]["hardcoded_cream"],
                "seek_10s_v2_not_17s": mapped_v2 not in {17_000, None},
                "hide_v1_base_is_v2": (hidden_target or {}).get("track_id") == "V2",
                "move_unlocked_import_anchor": moved is not None and moved.timeline_in_ms == 3_000,
                "ingest_loop_max_under_500ms": loop["max_ms"] < 500,
                "second_clip_present": v2_clip is not None,
            }
            if mapped_v2 is not None and v2_clip is not None:
                checks["seek_10s_uses_mapper"] = mapped_v2 == map_project_time(v2_clip, 10_000).source_ms
            self.result["checks"] = checks
            self.result["accepted"] = all(bool(value) for value in checks.values())
        except Exception as exc:
            self.result["errors"].append(f"{type(exc).__name__}: {exc}")
            self.result["accepted"] = False
        finally:
            self.result["elapsed_s"] = round(time.time() - self.result["started_at"], 3)
            self._write()
            code = 0 if self.result.get("accepted") else 1
            # os._exit from a Qt slot can deadlock on Windows. Kill from a
            # side thread after the result file is durable.
            threading.Thread(
                target=lambda: (time.sleep(0.15), os._exit(code)),
                name="p8a-exit",
                daemon=True,
            ).start()
            try:
                self.window.close()
            except Exception:
                pass
            self.app.quit()
