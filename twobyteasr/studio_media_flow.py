"""Media ingest, media probe, subtitle import, recognition sheet runtime,
waveform generation, and local re-ASR flow for Subtitle Studio."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from PySide6.QtCore import (QTimer, Qt)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget)
from .media_ingest import (MediaIngestResult, ingest_media, result_matches_request)
from .recognition_plans import matching_plan, plan_options, recognition_plan
from .resource_governor import ResourceKind
from .studio_ai import StudioSuggestion
from .studio_commands import MutationOrigin
from .studio_helpers import probe_media_identity
from .studio_project import (StudioCue, SubtitleProject, library_project_snapshot, load_project, parse_ass_dialogue_line, parse_subtitle_timecode_ms, project_library_root, repair_project_library_metadata, save_project, studio_settings_path)
from .studio_reasr import (LocalReASRResult, run_local_reasr)
from .studio_theme import studio_message_box
from .waveform_cache import (WaveformCache, generate_progressive_waveform_cache)

from .i18n import bind_text

from .i18n import tr

class StudioMediaFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _choose_media_drop_target(self):
        """Choose before ingest; cancellation must not mutate the project."""
        from PySide6.QtWidgets import QInputDialog
        from .studio_media_pool import primary_video_track_id
        project = self.project
        if project is None:
            return None
        choices = [("新建视频轨道", "new")]
        primary_id = primary_video_track_id(project)
        choices.extend((f"{track.id} · {track.name}", track.id)
                       for track in project.video_tracks
                       if track.id != primary_id and not track.locked)
        choices.append(("只加入素材库", "pool"))
        label, accepted = QInputDialog.getItem(
            self, "添加视频", "将视频放到播放头位置", [label for label, _ in choices], 0, False,
        )
        return dict(choices).get(label) if accepted else None

    def import_media_dialog(self) -> None:
        return self.project_controller.import_media_dialog()

    def _queue_project_cover_backfill(self, record: dict[str, object]) -> None:
        path_text = str(record.get("path", ""))
        if not path_text:
            return
        inflight = getattr(self, "_cover_backfill_inflight", set())
        self._cover_backfill_inflight = inflight
        if path_text in inflight or len(inflight) >= 2:
            return
        inflight.add(path_text)

        def work() -> None:
            cover = ""
            try:
                project_path = Path(path_text)
                project = load_project(project_path)
                result = self._ensure_project_cover(project_path, project)
                cover = str(result or "")
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                cover = ""
            self.cover_ready_signal.emit(path_text, cover)

        threading.Thread(target=work, daemon=True, name="studio-cover-backfill").start()

    def _queue_project_metadata_repair(self, record: dict[str, object]) -> None:
        path_text = str(record.get("path", ""))
        if not path_text:
            return
        inflight = getattr(self, "_metadata_repair_inflight", set())
        self._metadata_repair_inflight = inflight
        if path_text in inflight:
            return
        inflight.add(path_text)
        recent = copy.deepcopy(record)

        def work() -> None:
            cover = ""
            try:
                project_path = Path(path_text)
                snapshot, _summary, _needs_repair = library_project_snapshot(project_path, recent)
                metadata = None
                if (
                    snapshot.media.path
                    and Path(snapshot.media.path).is_file()
                    and (not snapshot.media.duration_ms or not snapshot.media.width or not snapshot.media.height)
                ):
                    metadata = probe_media_identity(snapshot.media.path)
                project, _summary, _changed = repair_project_library_metadata(
                    project_path,
                    recent,
                    media_metadata=metadata,
                )
                result = self._ensure_project_cover(project_path, project)
                cover = str(result or "")
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                cover = ""
            finally:
                inflight.discard(path_text)
            self.cover_ready_signal.emit(path_text, cover)

        threading.Thread(target=work, daemon=True, name="studio-library-repair").start()

    def _cover_backfill_ready(self, path_text: str, cover: str) -> None:
        inflight = getattr(self, "_cover_backfill_inflight", None)
        if inflight is not None:
            inflight.discard(path_text)
        if cover:
            settings_path = studio_settings_path()
            try:
                payload = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                payload = {}
            records = payload.get("recent_projects", []) if isinstance(payload, dict) else []
            for record in records:
                if isinstance(record, dict) and str(record.get("path", "")) == path_text:
                    record["cover_path"] = cover
            payload["recent_projects"] = records
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            # Update only the matching card surface; never rebuild or navigate
            # the Hub while a project may already be opening.
            cover_path = Path(cover)
            if cover_path.is_file():
                fresh = QPixmap(str(cover_path))
                for card in getattr(self, "_hub_card_widgets", []):
                    tooltip_lines = str(card.toolTip()).splitlines()
                    if not tooltip_lines or tooltip_lines[-1] != path_text:
                        continue
                    cover_label = card.findChild(QLabel, "projectCardCover")
                    if cover_label is not None and not fresh.isNull():
                        cover_label.setPixmap(fresh)
                    break

    def _open_or_create_media_project(self, media_path: Path) -> None:
        return self.project_controller._open_or_create_media_project(
            media_path,
            project_library_root_fn=project_library_root,
            probe_media_identity_fn=probe_media_identity,
            save_project_fn=save_project,
            message_box_fn=studio_message_box,
        )

    def _cancel_media_ingest(self) -> None:
        self._media_ingest_generation += 1
        self._media_ingest_project_token = ""
        self._pending_media_path = ""
        self._pending_media_mode = "primary"
        self._waveform_generation += 1
        self._waveform_cancel_event.set()
        self._waveform_cancel_event = threading.Event()
        self._waveform_pending_media.clear()
        with self._waveform_inflight_lock:
            self._waveform_inflight.clear()
        self._reset_av_sync_map()
        if hasattr(self, "timeline"):
            self.timeline.set_cache(None)

    def _schedule_project_media_probe(self, project: SubtitleProject, project_id: str) -> None:
        """Probe legacy project media off the GUI thread after first paint."""
        source = str(project.media.path or "").strip()
        if not source or not Path(source).is_file():
            return
        self._project_probe_generation += 1
        generation = self._project_probe_generation
        self._studio_trace(
            "MEDIA_CONTRACT_PROBE_START",
            project_id=str(project_id),
            media_path=source,
            suffix=Path(source).suffix.lower(),
            thread="pending",
        )

        def start_worker() -> None:
            def work() -> None:
                started = perf_counter()
                try:
                    from .runtime_trace import GLOBAL_STUDIO_TRACE

                    with GLOBAL_STUDIO_TRACE.operation(
                        "media_probe",
                        project_id=str(project_id),
                        media_path=source,
                        blocking_ui_thread=False,
                    ):
                        identity = probe_media_identity(source)
                    payload = {
                        "identity": dict(identity),
                        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
                    }
                except Exception as exc:
                    payload = {
                        "error": str(exc) or type(exc).__name__,
                        "exception_type": type(exc).__name__,
                        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
                    }
                try:
                    self.project_media_probe_ready_signal.emit(
                        generation, str(project_id), payload
                    )
                except RuntimeError:
                    return

            worker = threading.Thread(
                target=work,
                daemon=True,
                name="studio-media-probe",
            )
            self._project_probe_thread = worker
            worker.start()

        QTimer.singleShot(0, start_worker)

    def _project_media_probe_ready(
        self, generation: int, project_id: str, payload: object
    ) -> None:
        if generation != self._project_probe_generation or self.project is None:
            return
        if str(self.project_path or "") != str(project_id):
            return
        data = dict(payload) if isinstance(payload, Mapping) else {}
        identity = data.get("identity")
        media_path = str(self.project.media.path or "")
        if not isinstance(identity, Mapping):
            self._studio_trace(
                "P74C_MEDIA_CONTRACT_PROBE_FAILED",
                project_id=str(project_id),
                media_path=media_path,
                suffix=Path(media_path).suffix.lower(),
                exception_type=str(data.get("exception_type") or "RuntimeError"),
                message=str(data.get("error") or "unable to probe media"),
                elapsed_ms=data.get("elapsed_ms"),
            )
            return
        try:
            from .studio_project import hydrate_media_contract

            started = perf_counter()
            asset = hydrate_media_contract(
                self.project,
                identity,
                source_path=media_path,
            )
            self.timeline.refresh_media_graph()
            self._refresh_edit_playback_state()
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
            self._studio_trace(
                "MEDIA_CONTRACT_PROBE_READY",
                project_id=str(project_id),
                media_path=media_path,
                suffix=Path(media_path).suffix.lower(),
                elapsed_ms=data.get("elapsed_ms"),
                hydration_ms=round((perf_counter() - started) * 1000.0, 3),
                asset_id=asset.asset_id,
                duration_ms=int(asset.duration_ms or 0),
                video_codec=str((asset.video_metadata or {}).get("codec") or ""),
                audio_codec=str((asset.audio_metadata or {}).get("codec") or ""),
                video_stream_index=int((asset.video_metadata or {}).get("stream_index", 0) or 0),
                audio_stream_index=int((asset.audio_metadata or {}).get("stream_index", 0) or 0),
                sample_rate=int((asset.audio_metadata or {}).get("sample_rate", 0) or 0),
                channels=int((asset.audio_metadata or {}).get("channels", 0) or 0),
                video_timebase=str((asset.video_metadata or {}).get("timebase") or ""),
                audio_timebase=str((asset.audio_metadata or {}).get("timebase") or ""),
                video_metadata=dict(asset.video_metadata),
                audio_metadata=dict(asset.audio_metadata),
            )
        except Exception as exc:
            self._studio_trace(
                "P74C_MEDIA_CONTRACT_PROBE_FAILED",
                project_id=str(project_id),
                media_path=media_path,
                suffix=Path(media_path).suffix.lower(),
                exception_type=type(exc).__name__,
                message=str(exc),
                elapsed_ms=data.get("elapsed_ms"),
            )

    def _begin_media_drop(self, paths, position_ms, track_id=""):
        project = self.project
        if project is None:
            return
        self._media_ingest_generation += 1
        generation = self._media_ingest_generation
        project_id = project.project_id
        self._set_media_ingest_state("LOADING")
        bind_text(self.save_state, '正在读取媒体信息…')

        def work():
            results = [ingest_media(path, generation=generation, project_token=project_id) for path in paths]
            try:
                self.media_ingest_ready_signal.emit({"kind":"media_drop", "generation":generation,
                    "project_id":project_id, "results":results, "position_ms":position_ms, "track_id":track_id})
            except RuntimeError:
                pass
        self._media_ingest_thread = threading.Thread(target=work, daemon=True, name="studio-media-drop")
        self._media_ingest_thread.start()

    def _finish_media_drop(self, payload):
        project = self.project
        if (project is None or project.project_id != payload["project_id"]
                or self._media_ingest_generation != payload["generation"]):
            return
        from .studio_media_drop import MediaDropCommand
        first_media = not getattr(project, "media_pool", None) and not any(
            getattr(track, "clips", None) for track in getattr(project, "video_tracks", ())
        )
        try:
            # Resolve locks against the current project after probing finishes.
            command = MediaDropCommand(project, payload["results"], payload["position_ms"], payload["track_id"])
            self.undo_stack.push(command)
        except Exception as exc:
            self._set_media_ingest_state("ERROR", str(exc))
            self.save_state.setText(str(exc))
            return
        self._set_media_ingest_state("READY")
        self._sync_video_empty_state()
        self.timeline.refresh_media_graph()
        self._refresh_edit_playback_state()
        if first_media:
            # 空工程首媒体：播放头/视口归零，预览从第一帧开始。
            self._reset_playhead_for_first_media(
                reason="drop_first_media", position_ms=int(payload.get("position_ms") or 0)
            )
        self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
        self._generate_project_waveforms()
        bind_text(self.save_state, '素材已加入时间线')
        dropped_xml = getattr(self, "_pending_drop_xml", "")
        self._pending_drop_xml = ""
        if first_media or dropped_xml:
            # The first recording of a project: look for its same-name XML
            # (a dropped XML counts as the user's explicit choice).
            self._schedule_danmaku_discovery(manual_path=dropped_xml)

    def _reset_playhead_for_first_media(self, *, reason: str, position_ms: int = 0) -> None:
        """首次主媒体的确定起点：播放头=0、视口最左，并留结构化取证日志。"""
        try:
            self._studio_trace(
                "MEDIA_FIRST_LOAD",
                project_id=str(getattr(self.project, "project_id", "") or ""),
                source=str(getattr(getattr(self.project, "media", None), "path", "") or ""),
                initial_position=0,
                reason=reason,
                drop_position_ms=int(position_ms),
            )
        except Exception:
            pass
        if self.timeline.playhead_ms != 0:
            self.timeline.set_playhead(0)
        try:
            if self.timeline.visible_start_ms != 0:
                self.timeline.set_visible_window(0, self.timeline.visible_duration_ms)
        except Exception:
            pass
        self._studio_trace("PLAYER_INITIAL_SEEK", target=0, reason=reason)

    def _begin_media_ingest(
        self,
        media_path: str | os.PathLike[str],
        *,
        add_to_pool: bool = False,
        add_to_timeline: bool = False,
        target_track_id: str = "",
    ) -> None:
        project = self.project
        if project is None:
            return
        source = Path(media_path).resolve()
        self._media_ingest_generation += 1
        generation = self._media_ingest_generation
        project_token = str(project.project_id)
        self._media_ingest_project_token = project_token
        self._pending_media_path = str(source)
        self._pending_media_mode = (
            "timeline" if add_to_timeline else "pool" if add_to_pool else "primary"
        )
        self._pending_media_track_id = str(target_track_id)
        self._pending_media_timeline_ms = int(self.timeline.playhead_ms)
        self._studio_trace("FFPROBE_START", media_path=str(source), generation=generation)
        self._waveform_generation += 1
        self._set_media_ingest_state("LOADING")
        bind_text(self.save_state, '正在读取媒体信息…')
        self.save_state.setToolTip(str(source))
        if self._pending_media_mode == "primary":
            self.timeline.set_cache(None)
            self.timeline.set_waveform_state("EMPTY")
            self._sync_video_empty_state()

        def start_worker() -> None:
            if not (
                self.project is project
                and generation == self._media_ingest_generation
                and self._pending_media_path == str(source)
            ):
                return

            def work() -> None:
                result = ingest_media(
                    source,
                    generation=generation,
                    project_token=project_token,
                )
                try:
                    self.media_ingest_ready_signal.emit(result)
                except RuntimeError:
                    return

            worker = threading.Thread(
                target=work,
                daemon=True,
                name="studio-media-ingest",
            )
            self._media_ingest_thread = worker
            worker.start()

        # Give Qt one event-loop turn to paint LOADING before ffprobe starts.
        QTimer.singleShot(0, start_worker)

    def _media_ingest_ready(self, result: MediaIngestResult) -> None:
        if isinstance(result, dict) and result.get("kind") == "media_drop":
            return self._finish_media_drop(result)
        project = self.project
        if project is None or not result_matches_request(
            result,
            self._media_ingest_generation,
            self._media_ingest_project_token,
            self._pending_media_path,
        ) or result.project_token != project.project_id:
            return
        if result.error:
            self._studio_trace("FFPROBE_END", media_path=str(result.source_path), elapsed_ms=result.elapsed_ms, error=result.error)
            self._set_media_ingest_state("ERROR", result.error)
            bind_text(self.save_state, '无法读取媒体')
            self.save_state.setToolTip(result.error)
            self._sync_video_empty_state()
            return

        self._studio_trace("FFPROBE_END", media_path=str(result.source_path), elapsed_ms=result.elapsed_ms, error="")
        self._studio_mark_startup_milestone("MEDIA_METADATA_READY", media_path=str(result.source_path), elapsed_ms=result.elapsed_ms)
        media = project.media
        pending_mode = self._pending_media_mode
        from .studio_edit_sequence import identity_sequence, replace_runtime_sequence
        from .studio_media_pool import add_media_asset, add_video_clip, create_video_track
        from .studio_project import hydrate_media_contract
        from .studio_runtime_state import DirtyDomain, state_for

        ingest_metadata = {
            "fps": result.fps,
            "has_video": result.has_video,
            "has_audio": result.has_audio,
            "size": result.size,
            "mtime_ns": result.mtime_ns,
            "metadata_ms": result.elapsed_ms,
            "media_time_mapping": {
                "container_start_ms": result.container_start_ms,
                "source_start_ms": result.source_start_ms,
                "video_start_ms": result.video_start_ms,
                "audio_start_ms": result.audio_start_ms,
                "video_timebase": result.video_timebase,
                "audio_timebase": result.audio_timebase,
                "sample_rate": result.sample_rate,
                "sample_timeline_origin_ms": result.sample_timeline_origin_ms,
            },
        }
        project.studio_state["media_ingest"] = ingest_metadata
        if pending_mode == "primary":
            first_media = not getattr(project, "media_pool", None) and not any(
                getattr(track, "clips", None) for track in getattr(project, "video_tracks", ())
            )
            with state_for(project).transaction(
                project,
                action_id="media_ingest_ready",
                dirty=(
                    DirtyDomain.PROJECT_METADATA
                    | DirtyDomain.SEQUENCE_STRUCTURE
                    | DirtyDomain.TIMELINE_INDEX
                    | DirtyDomain.TIMELINE_PIXELS
                    | DirtyDomain.MEDIA_POOL
                    | DirtyDomain.VIDEO_TRACKS
                    | DirtyDomain.AUDIO_TRACKS
                    | DirtyDomain.CLIP_STATUS
                    | DirtyDomain.AUTOSAVE
                ),
            ):
                media.path = result.source_path
                media.display_name = Path(result.source_path).name
                media.duration_ms = result.duration_ms
                media.fingerprint = result.fingerprint
                media.width = result.width
                media.height = result.height
                project.media_pool = []
                project.video_tracks = []
                project.audio_tracks = []
                project.av_track_groups = []
                hydrate_media_contract(
                    project,
                    {
                        "source_path": result.source_path,
                        "duration_ms": result.duration_ms,
                        "width": result.width,
                        "height": result.height,
                        "fps": result.fps,
                        "has_video": result.has_video,
                        "has_audio": result.has_audio,
                        "video_codec": result.video_codec,
                        "audio_codec": result.audio_codec,
                        "video_timebase": result.video_timebase,
                        "audio_timebase": result.audio_timebase,
                        "sample_rate": result.sample_rate,
                        "channels": result.channels,
                        "rotation": result.rotation,
                        "fingerprint": result.fingerprint,
                        "container_start_ms": result.container_start_ms,
                        "source_start_ms": result.source_start_ms,
                        "video_start_ms": result.video_start_ms,
                        "audio_start_ms": result.audio_start_ms,
                        "video_first_pts_ms": result.video_first_pts_ms,
                        "audio_first_pts_ms": result.audio_first_pts_ms,
                        "video_best_effort_timestamp_ms": result.video_best_effort_timestamp_ms,
                        "audio_best_effort_timestamp_ms": result.audio_best_effort_timestamp_ms,
                        "sample_timeline_origin_ms": result.sample_timeline_origin_ms,
                    },
                    source_path=result.source_path,
                )
                sequence = identity_sequence(media)
                replace_runtime_sequence(project, sequence, validate=False)
                project.validate()
        else:
            from .studio_media_commands import media_graph_command

            def add_ingested_media(working) -> None:
                asset = add_media_asset(
                    working,
                    result.source_path,
                    fingerprint=result.fingerprint,
                    duration_ms=result.duration_ms,
                    video_metadata={
                        "width": result.width,
                        "height": result.height,
                        "fps": result.fps,
                        "has_video": result.has_video,
                        "codec": result.video_codec,
                        "timebase": result.video_timebase,
                        "rotation": result.rotation,
                        "start_time_ms": result.video_start_ms,
                        "first_pts_ms": result.video_first_pts_ms,
                        "best_effort_timestamp_ms": result.video_best_effort_timestamp_ms,
                        "source_start_ms": result.source_start_ms,
                    },
                    audio_metadata={
                        "has_audio": result.has_audio,
                        "codec": result.audio_codec,
                        "timebase": result.audio_timebase,
                        "sample_rate": result.sample_rate,
                        "channels": result.channels,
                        "stream_index": 0,
                        "start_time_ms": result.audio_start_ms,
                        "first_pts_ms": result.audio_first_pts_ms,
                        "best_effort_timestamp_ms": result.audio_best_effort_timestamp_ms,
                        "sample_timeline_origin_ms": result.sample_timeline_origin_ms,
                        "source_start_ms": result.source_start_ms,
                    },
                )
                if pending_mode == "timeline":
                    from .studio_media_pool import primary_video_track_id

                    requested_track_id = getattr(self, "_pending_media_track_id", "")
                    selected_track_id = requested_track_id or str(
                        working.studio_state.get("selected_video_track_id") or ""
                    )
                    primary_id = primary_video_track_id(working)
                    track = create_video_track(working) if requested_track_id == "new" else next(
                        (
                            item
                            for item in working.video_tracks
                            if item.id == selected_track_id
                            and item.id != primary_id
                            and not item.locked
                        ),
                        None,
                    ) or next(
                        (
                            item
                            for item in working.video_tracks
                            if item.id != primary_id and not item.locked
                        ),
                        None,
                    ) or create_video_track(working)
                    add_video_clip(
                        working,
                        track.id,
                        asset.asset_id,
                        timeline_in_ms=int(getattr(self, "_pending_media_timeline_ms", self.timeline.playhead_ms)),
                    )
                    working.studio_state["selected_video_track_id"] = track.id

            self.undo_stack.push(
                media_graph_command(
                    project,
                    "添加媒体到时间线"
                    if pending_mode == "timeline"
                    else "添加媒体到媒体池",
                    add_ingested_media,
                )
            )
        if pending_mode != "primary":
            self._set_media_ingest_state("READY")
            self._sync_video_empty_state()
            (bind_text(self.save_state, '素材已加入时间线') if pending_mode == 'timeline' else bind_text(self.save_state, '素材已加入媒体池'))
            if hasattr(self, "timeline"):
                self.timeline.refresh_media_graph()
            self._refresh_edit_playback_state()
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
            self._generate_project_waveforms()
            return
        self.position_overlay.set_video_size(media.width or 1920, media.height or 1080)
        self.timeline.waveform_caches.clear()
        self.timeline.waveform_clip_keys.clear()
        self.timeline.set_project(project)
        self._set_media_ingest_state("READY")
        self._sync_video_empty_state()
        try:
            if first_media:
                # 首媒体：播放头归零 + 原子 loadfile(start=0)。裸 load 后再补 seek
                # 会撞 mpv 异步初始化（seek 可能被静默吞掉），start 选项一次到位。
                self._reset_playhead_for_first_media(reason="primary_first_media")
                self.video.load(media.path, "", start_seconds=0.0)
            else:
                self.video.load(media.path, "")
            # Resolve the media graph now so an audio-only source selects the
            # mpv audio clock before the first play request.
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
            self._preview_timer.start(0)
        except Exception as exc:
            self._set_media_ingest_state("ERROR", str(exc))
            bind_text(self.save_state, '媒体预览加载失败')
            self.save_state.setToolTip(str(exc))
            self._sync_video_empty_state()
            return
        if hasattr(self, "highlight_panel"):
            # Same discovery as drag-drop and reopening: beside the original file.
            self._schedule_danmaku_discovery()
        bind_text(self.save_state, '媒体可用 · 元数据 {value0:.0f} ms', value0=result.elapsed_ms)
        if result.has_audio:
            self._generate_project_waveforms()
        else:
            self.timeline.set_waveform_state("ERROR", "媒体没有可分析的音轨")

    def _retry_media_ingest(self) -> None:
        if self._pending_media_path:
            self._begin_media_ingest(self._pending_media_path)

    def _set_media_ingest_state(self, state: str, message: str = "") -> None:
        state = state if state in {"EMPTY", "LOADING", "READY", "ERROR"} else "ERROR"
        self._media_ingest_state = state
        label = getattr(self, "video_empty_label", None)
        import_button = getattr(self, "video_empty_import", None)
        retry = getattr(self, "video_empty_retry", None)
        reselect = getattr(self, "video_empty_reselect", None)
        note = getattr(self, "video_empty_note", None)
        if label is not None:
            bind_text(label, {'EMPTY': '拖入视频 / 音频到这里开始剪辑', 'LOADING': '正在载入媒体…\n正在读取媒体信息…', 'READY': '', 'ERROR': '无法读取媒体'}[state])
            label.setToolTip(message if state == "ERROR" else "")
        if import_button is not None:
            import_button.setVisible(state == "EMPTY")
        if retry is not None:
            retry.setVisible(state == "ERROR")
        if reselect is not None:
            reselect.setVisible(state == "ERROR")
        if note is not None:
            bind_text(note, {'EMPTY': '支持 MP4 / FLV / MKV / MOV / MP3 / WAV 等常用格式', 'LOADING': '分析在后台进行，界面仍可操作。', 'READY': '', 'ERROR': message or '请重试，或重新选择另一个媒体文件。'}[state])

    def _read_subtitle_cues(self, path: Path) -> list[StudioCue]:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        cues: list[StudioCue] = []

        def _time_ms(value: str) -> int:
            parsed = parse_subtitle_timecode_ms(value)
            if parsed is None:
                raise ValueError(f"无效字幕时间：{value}")
            return parsed

        if path.suffix.lower() == ".srt":
            blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
            for index, block in enumerate(blocks, 1):
                lines = block.splitlines()
                timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
                if timing_index < 0:
                    continue
                start, end = (part.strip() for part in lines[timing_index].split("-->", 1))
                cue_text = " ".join(line.strip() for line in lines[timing_index + 1 :] if line.strip())
                cues.append(StudioCue(f"import-{index}", _time_ms(start), _time_ms(end), cue_text, original_text=cue_text))
        else:
            for index, line in enumerate(text.splitlines(), 1):
                if not line.startswith("Dialogue:"):
                    continue
                parsed_line = parse_ass_dialogue_line(line)
                if parsed_line is None:
                    continue
                start_ms, end_ms, _style, actor, cue_text = parsed_line
                cues.append(StudioCue(f"import-{index}", start_ms, end_ms, cue_text, speaker_id=actor or "S00", original_text=cue_text))
        return cues

    def _open_subtitle_import_dialog(self) -> None:
        if not self.project:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            tr('导入字幕'),
            str(self.project_path.parent if self.project_path else Path.home()),
            "字幕文件 (*.srt *.ass)",
        )
        if path:
            self._import_subtitle_file(Path(path))

    def _open_recognition_sheet(self) -> None:
        project = self.project
        media_path = str(project.media.path or "") if project else ""
        if not project or not media_path or not Path(media_path).is_file():
            studio_message_box(
                self,
                QMessageBox.Icon.Information,
                tr('先导入媒体'),
                tr('识别字幕需要当前工程中的视频或音频。请先导入媒体。'),
            )
            return
        project_path = str(self.project_path or "")
        if not project_path:
            studio_message_box(
                self,
                QMessageBox.Icon.Warning,
                tr('请先保存工程'),
                tr('保存工程后才能把识别结果写回同一个工程。'),
            )
            return

        host = self.window()
        sheet = QWidget()
        sheet.setObjectName("studioRecognitionSheet")
        layout = QVBoxLayout(sheet)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)
        title = QLabel("识别当前工程")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        media = bind_text(QLabel(), '媒体 · {value0}', value0=Path(media_path).name)
        media.setObjectName("contextValue")
        media.setWordWrap(True)
        layout.addWidget(media)

        plan_row = QHBoxLayout()
        plan_row.addWidget(QLabel("识别方案"))
        plan = QComboBox()
        # 四十二轮：方案与主页 plan_options() 对齐（补 省显存/仅转写/API 转写），
        # 另保留"当前主页方案"快捷项。此前硬编码 4 项，API 识别根本选不到。
        for entry in plan_options():
            plan.addItem(entry.label, entry.key)
        plan.addItem("当前主页方案", "home")
        plan.setCurrentIndex(plan.findData("home"))
        plan_row.addWidget(plan, 1)
        layout.addLayout(plan_row)

        advanced_toggle = QPushButton("▸ 高级配置 · 模型")
        advanced_toggle.setObjectName("studioButton")
        advanced_toggle.setCheckable(True)
        advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(advanced_toggle)
        advanced = QFrame()
        advanced.setObjectName("contextCard")
        advanced_grid = QGridLayout(advanced)
        advanced_grid.setContentsMargins(12, 10, 12, 10)
        advanced_grid.setHorizontalSpacing(10)
        advanced_grid.setVerticalSpacing(7)

        def copy_model_choices(target: QComboBox, source_name: str, fallback) -> None:
            source = getattr(host, source_name, None)
            if isinstance(source, QComboBox):
                for index in range(source.count()):
                    value = source.itemData(index)
                    if value is not None and target.findData(value) < 0:
                        target.addItem(source.itemText(index), value)
            if not target.count():
                for label, value in fallback:
                    target.addItem(label, value)

        primary_model = QComboBox()
        timeline_model = QComboBox()
        review_model = QComboBox()
        copy_model_choices(
            primary_model,
            "primary_asr_backend",
            (
                ("SenseVoice", "sensevoice"),
                ("MOSS", "moss"),
                ("Qwen3-ASR", "qwen_local"),
                ("FireRed", "firered"),
                ("在线 ASR API", "api"),
            ),
        )
        copy_model_choices(
            timeline_model,
            "firered_asr_backend",
            (("不使用", "off"), ("FireRed", "local"), ("Paraformer", "paraformer")),
        )
        copy_model_choices(
            review_model,
            "qwen_asr_backend",
            (
                ("不使用", "off"),
                ("Qwen3-ASR", "local"),
                ("FireRed LLM", "firered_llm"),
                ("在线 ASR API", "api"),
            ),
        )

        # 四十三轮：API 项显示完整服务与模型 id（用户怀疑调用错模型——
        # 笼统「API」无法核查；17:36 实录实为 OpenRouter·mai-transcribe-2）。
        def _api_entry_labels() -> tuple[str, str]:
            try:
                models_cfg = dict(
                    getattr(getattr(host, "legacy", None), "RUNTIME_SETTINGS", {}) or {}
                ).get("models", {}) or {}
            except Exception:
                models_cfg = {}
            from .ui import ASR_API_PRESETS

            provider = str(models_cfg.get("qwen_asr_api_provider") or "qwen31_filetrans")
            preset = ASR_API_PRESETS.get(provider) or {}
            model_id = str(models_cfg.get("qwen_asr_api_model") or preset.get("model") or "")
            short = str(preset.get("short") or provider)
            full = f"在线 ASR API（{short} · {model_id}）" if model_id else f"在线 ASR API（{short}）"
            return full, short

        api_full_label, api_short = _api_entry_labels()
        for combo in (primary_model, review_model):
            index = combo.findData("api")
            if index >= 0:
                combo.setItemText(index, api_full_label)
        plan_api_index = plan.findData("api")
        if plan_api_index >= 0:
            plan.setItemText(plan_api_index, f"API 转写（{api_short}）")
        for row, (label, combo, role) in enumerate(
            (
                ("主力转写", primary_model, "primary"),
                ("字幕时间轴", timeline_model, "timeline"),
                ("文字复核", review_model, "review"),
            )
        ):
            advanced_grid.addWidget(QLabel(label), row, 0)
            advanced_grid.addWidget(combo, row, 1)
            # 四十二轮：接入主页同款模型选择弹窗作为二级弹窗——本地下载、
            # 在线 API 服务商选择与"配置"（Key/地址/转写风格）都能在这里完成。
            picker_button = QPushButton("选择…")
            picker_button.setObjectName("studioButton")
            bind_text(picker_button, '打开与主页相同的模型选择弹窗（本地模型下载、在线 API 服务与配置）', property='toolTip')
            picker_button.setCursor(Qt.CursorShape.PointingHandCursor)
            picker_button.clicked.connect(lambda _checked=False, r=role: open_role_picker(r))
            advanced_grid.addWidget(picker_button, row, 2)
        advanced.hide()
        layout.addWidget(advanced)

        speaker_source = QComboBox()
        speaker_source.addItem("统一字幕轨（默认，不额外运行说话人分离）", "single")
        speaker_source.addItem("Filetrans 原生分轨（使用所选 Filetrans 版本）", "filetrans")
        speaker_source.addItem("说话人：ECAPA 快速分离 · 不重复转写（身份需复核）", "ecapa")
        speaker_source.addItem("高级：按接口原始标签整理说话人", "native")
        speaker_source.addItem("说话人：MOSS · 保留模型身份（主稿为其它模型时额外运行 MOSS）", "moss")
        from .speaker_strategy import resolve
        speaker_settings=getattr(getattr(host,'legacy',None),'RUNTIME_SETTINGS',{})
        speaker_source.setCurrentIndex(max(0, speaker_source.findData(resolve(speaker_settings))))
        bind_text(speaker_source, '默认只组织为统一字幕轨，不代表已确认同一个人。原标签保留；旧版本自动分轨设置不沿用。其余方式需要在这里明确选择。', property='toolTip')
        layout.addWidget(speaker_source)
        local_analysis = QCheckBox('仅本地识别与分轨（跳过云端校对和 AI 断句）')
        local_analysis.setObjectName('localSpeakerRecognition')
        bind_text(local_analysis, '仍使用所选主转写与时间轴模型；需选择本地模型。说话人按上方选择运行，身份需试听确认。', property='toolTip')
        layout.addWidget(local_analysis)
        speaker_scope=QLabel('默认来自当前方案；此处选择仅影响本次识别，不修改其他方案或已有字幕。')
        speaker_scope.setWordWrap(True)
        layout.addWidget(speaker_scope)

        glossary_card = QFrame()
        glossary_card.setObjectName("contextCard")
        glossary_layout = QVBoxLayout(glossary_card)
        glossary_layout.setContentsMargins(12, 10, 12, 10)
        glossary_layout.setSpacing(5)
        glossary_layout.addWidget(QLabel("本次识别词库"))
        # 四十三轮：词库改常驻勾选 chips。下拉方案两轮翻车——三十一轮前复选行
        # 被 ModalHost 钳制压成切片；四十二轮 activated 已修但用户实录"点开后
        # 又马上退出"（不同 DPI/屏幕下 popup 存活不稳，headed 无法复现）。
        # chips 没有 popup 可关，勾选状态直接可见；空 identity 条目（工程
        # glossary_ids 历史污染出的空串，用户截图 6 项 4 空白）直接过滤。
        glossary_entries: dict[str, str] = {}
        profiles = getattr(getattr(host, "legacy", None), "load_game_profiles", lambda: {})() or {}
        identity_fn = getattr(getattr(host, "legacy", None), "runtime_game_identity", str)
        for name in profiles:
            display = str(name or "").strip()
            identity = str(identity_fn(name) or "").strip()
            if display and identity:
                glossary_entries[identity] = display
        for identity in dict.fromkeys(project.glossary_ids or []):
            key = str(identity or "").strip()
            if key:
                glossary_entries.setdefault(key, key)
        if not glossary_entries:
            empty_glossary = QLabel("未关联词库；可继续识别。")
            empty_glossary.setObjectName("studioSaveState")
            glossary_layout.addWidget(empty_glossary)

        glossary_checks: list[tuple[QCheckBox, str]] = []

        def _glossary_checked_ids(*_args) -> list[str]:
            return [identity for box, identity in glossary_checks if box.isChecked()]

        def _sync_glossary_summary(*_args) -> None:
            names = [box.text() for box, _identity in glossary_checks if box.isChecked()]
            if not names:
                bind_text(glossary_summary, '未选择词库')
            else:
                joined = "、".join(names)
                (bind_text(glossary_summary, '已选 {value0} 个词库：{value1}…', value0=len(names), value1=joined[:38]) if len(joined) > 40 else bind_text(glossary_summary, '已选 {value0} 个词库：{value1}', value0=len(names), value1=joined))

        chips_host = QWidget()
        chips_grid = QGridLayout(chips_host)
        chips_grid.setContentsMargins(0, 0, 0, 0)
        chips_grid.setHorizontalSpacing(8)
        chips_grid.setVerticalSpacing(4)
        for index, (identity, display_name) in enumerate(glossary_entries.items()):
            box = QCheckBox(display_name)
            bind_text(box, '识别时启用词库：{display_name}', property='toolTip', display_name=display_name)
            box.stateChanged.connect(_sync_glossary_summary)
            glossary_checks.append((box, identity))
            chips_grid.addWidget(box, index // 2, index % 2)
        glossary_summary = QLabel("未选择词库")
        glossary_summary.setObjectName("studioSaveState")
        glossary_summary.setWordWrap(True)
        if glossary_entries:
            glossary_layout.addWidget(chips_host)
            glossary_layout.addWidget(glossary_summary)
        layout.addWidget(glossary_card)

        scope_note = QLabel("")
        scope_note.setObjectName("studioSaveState")
        scope_note.setWordWrap(True)
        layout.addWidget(scope_note)
        start = QPushButton("识别字幕")
        start.setObjectName("studioPrimary")
        start.setMinimumHeight(42)
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(start)
        confirm_row = QFrame()
        confirm_layout = QHBoxLayout(confirm_row)
        confirm_layout.setContentsMargins(0, 0, 0, 0)
        confirm_layout.addWidget(QLabel("仅替换正式字幕稿；保留样式、剪辑和候选。"), 1)
        confirm_replace = QPushButton("确认替换")
        confirm_replace.setObjectName("studioPrimary")
        confirm_replace.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_layout.addWidget(confirm_replace)
        confirm_row.hide()
        layout.addWidget(confirm_row)

        configure = QPushButton("在主页管理全部识别设置")
        configure.setObjectName("studioButton")
        configure.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(configure)

        def set_combo_value(combo: QComboBox, value: str) -> None:
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

        home_models = {
            "primary": getattr(getattr(host, "primary_asr_backend", None), "currentData", lambda: "moss")(),
            "timeline": getattr(getattr(host, "firered_asr_backend", None), "currentData", lambda: "local")(),
            "review": getattr(getattr(host, "qwen_asr_backend", None), "currentData", lambda: "local")(),
        }

        applying_plan = {"value": False}

        def apply_plan() -> None:
            key = str(plan.currentData() or "custom")
            if key == "home":
                values = (home_models["primary"], home_models["timeline"], home_models["review"])
            else:
                entry = recognition_plan(key)
                values = (entry.primary, entry.timeline, entry.review)
            if values and any(values):
                applying_plan["value"] = True
                try:
                    for combo, value in zip((primary_model, timeline_model, review_model), values):
                        set_combo_value(combo, str(value or ""))
                finally:
                    applying_plan["value"] = False

        def refresh_models_from_host() -> None:
            # 二级模型选择弹窗关闭后：同步主页当前选择回弹窗下拉。
            sources = (
                (primary_model, "primary_asr_backend"),
                (timeline_model, "firered_asr_backend"),
                (review_model, "qwen_asr_backend"),
            )
            for target, source_name in sources:
                copy_model_choices(target, source_name, ())
                source = getattr(host, source_name, None)
                data = source.currentData() if isinstance(source, QComboBox) else None
                if data:
                    set_combo_value(target, str(data))
            matched = matching_plan(
                str(primary_model.currentData() or ""),
                str(timeline_model.currentData() or ""),
                str(review_model.currentData() or ""),
            )
            if matched != "custom" or plan.findData("custom") < 0:
                plan.setCurrentIndex(max(0, plan.findData(matched)))

        def open_role_picker(role: str) -> None:
            open_fn = getattr(host, "_open_model_picker", None)
            if not callable(open_fn):
                return

            def _restore() -> None:
                refresh_models_from_host()
                host_modal = getattr(host, "_modal_host", None)
                if host_modal is not None:
                    sheet_height = min(760, max(520, host.height() - 120))
                    host_modal.show_content(
                        sheet,
                        title="识别字幕",
                        size=(620, sheet_height),
                        min_size=(500, 520),
                        retain_content=True,
                    )

            open_fn(role, on_closed=_restore)

        (bind_text(scope_note, '当前字幕 {value0} 条；识别结果将替换字幕，保留样式和剪辑。', value0=len(project.cues)) if project.cues else bind_text(scope_note, '使用所选方案生成工程字幕。'))
        (bind_text(start, '识别并替换当前字幕') if project.cues else bind_text(start, '识别字幕'))

        def request_options() -> dict:
            return {
                "purpose": "analysis" if local_analysis.isChecked() else "final",
                "recognition_plan": str(plan.currentData() or "custom"),
                "models": {
                    "primary": str(primary_model.currentData() or ""),
                    "timeline": str(timeline_model.currentData() or ""),
                    "review": str(review_model.currentData() or ""),
                },
                "enabled_glossary_ids": (
                    _glossary_checked_ids() if glossary_entries else []
                ),
                "replace_policy": "replace_cues",
                "speaker_source": str(speaker_source.currentData()),
            }

        def dispatch(action: str) -> None:
            modal = getattr(host, "_modal_host", None)
            if action == "configure":
                if modal is not None:
                    modal.hide_content()
                self.recognition_requested.emit(action, media_path, project_path)
                return
            if local_analysis.isChecked():
                if (str(primary_model.currentData()) not in {'moss','firered','qwen_local','whisper_turbo','paraformer'}
                        or str(timeline_model.currentData()) == 'api' or speaker_source.currentData()=='filetrans'):
                    bind_text(scope_note, '仅本地识别需要本地主转写、时间轴及说话人方案，请展开高级配置。')
                    return
                action='start_analysis'
            self._recognition_request_options = request_options()
            self._recognition_started_at = perf_counter()
            # 四十二轮：识别转后台。①弹窗立即关闭（状态进左侧字幕列表芯片），
            # 否则 _start_run 预检分支的 QMessageBox 会被 ModalHost 盖住形成
            # "隐形模态卡死"（用户实录"在线API识别一直卡住"）；②记录替换基线
            # 与 autosave 代次，供完成后"保留编辑/重新加载"裁决。
            if action == "start_final":
                self._recognition_replace_baseline_ids = {cue.id for cue in project.cues}
            else:
                self._recognition_replace_baseline_ids = None
            self._recognition_autosave_generation = int(getattr(self, "_autosave_generation", 0) or 0)
            # 2026-09-17：真实编辑判定基准——undo 栈只在真实编辑时增长；
            # autosave 代次会被无编辑的周期保存顶掉。
            self._recognition_undo_count = int(
                self.undo_stack.count() if getattr(self, "undo_stack", None) is not None else 0
            )
            if modal is not None:
                modal.hide_content()
            self._recognition_running = True
            self._recognition_cancelling = False
            self._recognition_status_sticky = ""
            self._recognition_show_status("准备模型", "")
            if getattr(self, "_recognition_runtime_timer", None) is not None:
                self._recognition_runtime_timer.stop()
            self._recognition_runtime_timer = QTimer(self)
            self._recognition_runtime_timer.timeout.connect(self._update_recognition_elapsed)
            self._recognition_runtime_timer.start(250)
            self.recognition_requested.emit(action, media_path, project_path)

        def start_clicked() -> None:
            if project.cues:
                confirm_row.show()
                return
            dispatch("start_final")

        advanced_toggle.toggled.connect(
            lambda checked: (
                advanced.setVisible(checked),
                bind_text(advanced_toggle, '{value0} 高级配置 · 模型', value0='▾' if checked else '▸'),
            )
        )
        plan.currentIndexChanged.connect(lambda _index: apply_plan())
        for combo in (primary_model, timeline_model, review_model):
            combo.currentIndexChanged.connect(
                lambda _index: plan.setCurrentIndex(plan.findData("custom"))
                if not applying_plan["value"] and str(plan.currentData()) not in {"custom", "home"}
                else None
            )
        start.clicked.connect(start_clicked)
        confirm_replace.clicked.connect(lambda: dispatch("start_final"))
        configure.clicked.connect(lambda: dispatch("configure"))
        apply_plan()
        # 四处引用旧 sheet 状态对象的地方都已改走左侧芯片；重建弹窗前清理
        # 上一张 retain 的 sheet，避免反复开关累积孤儿控件。
        previous_sheet = getattr(self, "_recognition_sheet", None)
        if previous_sheet is not None and previous_sheet is not sheet:
            previous_sheet.setParent(None)
            previous_sheet.deleteLater()
        self._recognition_sheet = sheet
        self._recognition_controls = {
            "plan": plan,
            "primary": primary_model,
            "timeline": timeline_model,
            "review": review_model,
            "advanced": advanced,
            "glossaries": chips_host,
            "start": start,
            "confirm": confirm_row,
        }

        modal = getattr(host, "_modal_host", None)
        if modal is not None:
            # 四十三轮：768 高的屏幕放不下 760 的弹窗（词库区会被压出视野）。
            sheet_height = min(760, max(520, host.height() - 120))
            modal.show_content(
                sheet,
                title="识别字幕",
                size=(620, sheet_height),
                min_size=(500, 520),
                retain_content=True,
            )
        else:
            self.recognition_requested.emit("configure", media_path, project_path)

    def recognition_request_options(self) -> dict:
        return copy.deepcopy(getattr(self, "_recognition_request_options", {}))

    def _recognition_chip_parts(self):
        frame = getattr(self, "recognition_chip", None)
        label = getattr(self, "recognition_chip_label", None)
        if frame is None or label is None:
            return None
        return frame, label

    def _recognition_status_text(self) -> str:
        running = bool(getattr(self, "_recognition_running", False))
        started = float(getattr(self, "_recognition_started_at", 0.0) or 0.0)
        label = getattr(self, "recognition_chip_label", None)
        stage = getattr(self, "_recognition_stage_message", None) or ((label.property("recognitionStage") if label is not None else "") or "识别中")
        if running and started:
            elapsed = max(0, int(perf_counter() - started))
            return tr('识别中 · {stage} · {minutes:02d}:{seconds:02d}', stage=stage if hasattr(stage, "source") else tr(stage), minutes=elapsed//60, seconds=elapsed%60)
        return stage if hasattr(stage, "source") else tr(stage)

    def _sync_recognition_zero_state(self) -> None:
        """四十三轮：识别状态同步到"暂无字幕"卡（用户点名的主视觉位）。"""
        card = getattr(self, "recognition_zero_card", None)
        label = getattr(self, "recognition_zero_label", None)
        if card is None or label is None:
            return
        active = bool(
            getattr(self, "_recognition_running", False)
            or getattr(self, "_recognition_status_sticky", "")
        )
        zero = getattr(self, "cue_zero_state", None)
        if zero is not None and zero.isVisibleTo(zero.parentWidget()) and active:
            bind_text(label, self._recognition_status_text())
            card.show()
            card.raise_()
        else:
            card.hide()
        recognize = getattr(self, "cue_recognize_button", None)
        if recognize is not None:
            recognize.setVisible(not getattr(self, "_recognition_running", False))

    def _recognition_show_status(self, stage: str, detail: str = "") -> None:
        self._recognition_stage_message = stage
        parts = self._recognition_chip_parts()
        if parts is not None:
            frame, label = parts
            label.setProperty("recognitionStage", str(stage or "识别中"))
            if detail:
                bind_text(label, detail, property='toolTip')
            frame.show()
            frame.raise_()
        self._update_recognition_elapsed(force=True)
        self._sync_recognition_zero_state()
        cancel_visible = bool(getattr(self, "_recognition_running", False)) and not bool(
            getattr(self, "_recognition_cancelling", False)
        )
        for name in ("recognition_cancel_button", "recognition_zero_cancel"):
            button = getattr(self, name, None)
            if button is not None:
                button.setVisible(cancel_visible)
        if cancel_visible:
            detail_button = getattr(self, "recognition_zero_detail", None)
            if detail_button is not None:
                detail_button.show()

    def _update_recognition_elapsed(self, force: bool = False) -> None:
        parts = self._recognition_chip_parts()
        if parts is None:
            return
        _frame, label = parts
        running = bool(getattr(self, "_recognition_running", False))
        if not running and not force:
            return
        bind_text(label, self._recognition_status_text())
        zero_label = getattr(self, "recognition_zero_label", None)
        if zero_label is not None and getattr(self, "_recognition_running", False):
            bind_text(zero_label, self._recognition_status_text())

    def set_recognition_cancelling(self) -> None:
        """四十三轮：取消请求已发出——Studio 内立即可见（防"点了没反应"）。"""
        self._recognition_cancelling = True
        self._recognition_show_status(
            "正在安全取消", "将在当前可安全停止的阶段边界退出"
        )

    def set_recognition_runtime_stage(self, stage: str, detail: str = "") -> None:
        self._recognition_show_status(stage or "识别中", detail)

    def apply_recognition_cue_delta(self, payload: Mapping[str, object]) -> None:
        """Apply immutable worker output on the Qt GUI thread."""
        project = self.project
        if project is None:
            return
        try:
            source = str(Path(str(payload.get("source_path") or "")).resolve())
            project_source = str(Path(project.media.path).resolve())
        except (OSError, ValueError):
            return
        if os.path.normcase(source) != os.path.normcase(project_source):
            self._runtime_cache.record_cancel(
                f"cue-delta:{payload.get('manifest_key', '')}", stale=True,
            )
            return
        raw_cues = [
            item for item in payload.get("cues", ()) if isinstance(item, Mapping)
        ]
        state_name = str(payload.get("state") or "provisional")
        if not raw_cues and state_name != "final":
            return
        incoming_ids = {
            str(item.get("id") or "") for item in raw_cues
            if str(item.get("id") or "")
        }
        states = project.generation_metadata.setdefault("asr_cue_states", {})
        if not isinstance(states, dict):
            states = {}
            project.generation_metadata["asr_cue_states"] = states
        provisional_ids = (
            {cue_id for cue_id, value in states.items() if value == "provisional"}
            if state_name == "final" else set()
        )
        affected = provisional_ids | incoming_ids
        from .studio_runtime_state import DirtyDomain, state_for

        with state_for(project).transaction(
            project,
            action_id=f"asr_cue_delta_{state_name}",
            dirty=(
                DirtyDomain.CUE_MODEL
                | DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.AUTOSAVE
            ),
            affected_cue_ids=affected,
        ):
            if state_name == "final":
                replacement = payload.get("replacement_mapping", {})
                replacement = dict(replacement) if isinstance(replacement, Mapping) else {}
                project.generation_metadata["asr_replacement_mapping"] = replacement
                project.cues = [cue for cue in project.cues if cue.id not in provisional_ids]
                for cue_id in provisional_ids:
                    states[cue_id] = "invalidated"
                # 四十二轮：final/replace 语义——识别前的旧正式字幕整组让位
                # （dispatch(start_final) 记录的基线）。识别期间用户新建的 cue
                # 不在基线集，保留；后台模式下不重载工程也能得到正确的替换结果。
                baseline = getattr(self, "_recognition_replace_baseline_ids", None)
                if baseline:
                    project.cues = [cue for cue in project.cues if cue.id not in baseline]
                    for cue_id in baseline:
                        states[cue_id] = "invalidated"
                    self._recognition_replace_baseline_ids = None
            existing = {cue.id: cue for cue in project.cues}
            for item in raw_cues:
                cue_id = str(item.get("id") or "")
                if not cue_id:
                    continue
                start_ms = max(0, int(item.get("start_ms") or 0))
                end_ms = max(start_ms + 20, int(item.get("end_ms") or start_ms + 20))
                cue = existing.get(cue_id)
                if cue is None:
                    cue = StudioCue(
                        id=cue_id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        text=str(item.get("text") or ""),
                        speaker_id=str(item.get("speaker_id") or "S00"),
                        style_id=str(item.get("style_id") or "default"),
                    )
                    project.cues.append(cue)
                    existing[cue_id] = cue
                else:
                    cue.start_ms = start_ms
                    cue.end_ms = end_ms
                    cue.text = str(item.get("text") or cue.text)
                states[cue_id] = state_name
            project.cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
        if not self.selected_cue_id and project.cues:
            self.select_cue(project.cues[0].id)

    def finish_recognition_runtime(self, elapsed_seconds: float = 0.0) -> None:
        self._recognition_running = False
        self._recognition_cancelling = False
        timer = getattr(self, "_recognition_runtime_timer", None)
        if timer is not None:
            timer.stop()
        parts = self._recognition_chip_parts()
        if parts is None:
            return
        _frame, label = parts
        duration = float(getattr(getattr(self.project, "media", None), "duration_ms", 0) or 0) / 1000.0
        rate = duration / float(elapsed_seconds) if elapsed_seconds > 0 and duration > 0 else 0.0
        suffix = f" · {rate:.1f}× realtime" if rate else ""
        label.setProperty("recognitionStage", "")
        label.setToolTip("")
        final_text = f"识别完成 · {float(elapsed_seconds):.1f} 秒{suffix}"
        label.setText(final_text)
        self._recognition_status_sticky = final_text
        self._sync_recognition_zero_state()
        for name in ("recognition_cancel_button", "recognition_zero_cancel"):
            button = getattr(self, name, None)
            if button is not None:
                button.hide()

    def note_recognition_kept_in_memory(self) -> None:
        """完成时用户选择"保留编辑"：新字幕已写入工程文件，当前窗口不动。"""
        parts = self._recognition_chip_parts()
        if parts is None:
            return
        _frame, label = parts
        text = (
            "识别完成 · 新字幕已写入工程文件；当前窗口保留你的编辑，"
            "重新打开工程即可加载新字幕"
        )
        label.setText(text)
        self._recognition_status_sticky = text
        self._sync_recognition_zero_state()

    def fail_recognition_runtime(self, message: str) -> None:
        self._recognition_running = False
        self._recognition_cancelling = False
        self._recognition_replace_baseline_ids = None
        timer = getattr(self, "_recognition_runtime_timer", None)
        if timer is not None:
            timer.stop()
        parts = self._recognition_chip_parts()
        if parts is None:
            return
        frame, label = parts
        label.setProperty("recognitionStage", "")
        text = f"识别未完成 · {str(message or '请查看运行日志')}"
        label.setText(text)
        self._recognition_status_sticky = text
        frame.show()
        frame.raise_()
        self._sync_recognition_zero_state()
        for name in ("recognition_cancel_button", "recognition_zero_cancel"):
            button = getattr(self, name, None)
            if button is not None:
                button.hide()

    def _import_subtitle_file(self, path: Path) -> None:
        if not self.project:
            studio_message_box(
                self,
                QMessageBox.Icon.Information,
                tr('先加载媒体'),
                tr('请先拖入媒体或 .2byteproj，再导入字幕。'),
            )
            return
        try:
            cues = self._read_subtitle_cues(path)
            if not cues:
                raise ValueError("没有读取到有效字幕")
            from .studio_commands import ReplaceCuesCommand
            self.undo_stack.push(
                ReplaceCuesCommand(
                    self.project,
                    cues,
                    f"Import {path.suffix.upper()}",
                    self._changed,
                    MutationOrigin.IMPORT,
                )
            )
            self.cue_model.set_project(self.project)
            self.timeline.set_project(self.project)
            self._populate_speakers()
            self.select_cue(cues[0].id)
        except (OSError, ValueError) as exc:
            studio_message_box(self, QMessageBox.Icon.Critical, tr('导入字幕失败'), str(exc))

    def _generate_waveform(self, media_path: str) -> None:
        media_key = str(Path(media_path).resolve())
        self._studio_mark_startup_milestone("WAVEFORM_REQUESTED", media_path=media_key)
        self._studio_mark_startup_milestone("WAVEFORM_CACHE_LOOKUP", media_path=media_key)
        cache = self.timeline.waveform_cache_for_source(media_key)
        if (
            cache is not None
            and str(Path(cache.metadata.source_path).resolve()) == media_key
        ):
            self._waveform_last_ready_media = media_key
            self.timeline.set_waveform_state("READY")
            self._studio_mark_startup_milestone("WAVEFORM_CACHE_REUSE", media_path=media_key)
            self._studio_mark_startup_milestone("WAVEFORM_FIRST_TILE_READY", media_path=media_key, stage="cached")
            self._studio_mark_startup_milestone("WAVEFORM_VISIBLE", media_path=media_key, stage="cached")
            self._studio_mark_startup_milestone("WAVEFORM_COMPLETE", media_path=media_key)
            return
        with self._waveform_inflight_lock:
            if media_key in self._waveform_inflight:
                self.timeline.set_waveform_state("LOADING", "分析音频…")
                self._studio_trace("WAVEFORM_JOB_REUSE", media_path=media_key)
                return
            self._waveform_inflight.add(media_key)
            self._waveform_cancel_event.set()
            cancel_event = threading.Event()
            self._waveform_cancel_event = cancel_event
        root = Path(__file__).resolve().parents[1]
        ffmpeg = root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        self._waveform_generation += 1
        generation = self._waveform_generation
        self.timeline.set_waveform_state("LOADING", "正在生成音频波形…")

        from .runtime_trace import GLOBAL_STUDIO_TRACE

        def trace_log(event: str, fields: dict) -> None:
            GLOBAL_STUDIO_TRACE.emit(event, {"media_path": media_key, **fields})

        def resolve_duration_ms() -> int:
            duration = 0
            if self.project is not None:
                if str(Path(self.project.media.path).resolve()) == media_key:
                    duration = int(self.project.media.duration_ms or 0)
                for asset in self.project.media_pool:
                    if str(Path(asset.canonical_source).resolve()) == media_key:
                        duration = max(duration, int(asset.duration_ms or 0))
            if not duration and self.project is not None:
                mapping = getattr(self.project, "studio_state", {}).get("media_time_mapping", {})
                duration = int(dict(mapping).get("duration_ms", 0) or 0)
            return duration

        def decode_source_resolver():
            # ffmpeg decodes the selected audio directly from FLV; making an
            # entire MP4 is unrelated to waveform/audio extraction. Keeping
            # the original also preserves its audio offset and track identity.
            return None

        def work():
            try:
                self._queue_startup_milestone("WAVEFORM_DECODE_START", media_path=media_key)
                def publish(stage: str, cache_dir: Path) -> None:
                    if cancel_event.is_set():
                        return
                    self._studio_trace(
                        "WAVEFORM_PROGRESSIVE_READY",
                        media_path=media_key,
                        stage=stage,
                    )
                    if stage == "coarse":
                        self._queue_startup_milestone("WAVEFORM_FIRST_TILE_READY", media_path=media_key, stage=stage)
                    self.waveform_ready_signal.emit(
                        generation,
                        media_key,
                        stage,
                        WaveformCache(cache_dir),
                    )

                generate_progressive_waveform_cache(
                    media_path,
                    ffmpeg,
                    cancelled=cancel_event.is_set,
                    time_mapping=(
                        dict(getattr(self.project, "studio_state", {}).get("media_time_mapping", {}))
                        if self.project is not None else None
                    ),
                    on_ready=publish,
                    before_refine=lambda: self._resource_governor.wait_until_allowed(
                        ResourceKind.WAVEFORM,
                        cancelled=cancel_event.is_set,
                    ),
                    decode_source_resolver=decode_source_resolver,
                    duration_ms=resolve_duration_ms(),
                    log=trace_log,
                )
            except InterruptedError:
                self._runtime_cache.telemetry.record(
                    "cancel", key=f"waveform:{media_key}",
                )
            except Exception as exc:
                self.waveform_failed_signal.emit(generation, media_key, str(exc))
            finally:
                with self._waveform_inflight_lock:
                    self._waveform_inflight.discard(media_key)
                    self._waveform_threads.discard(threading.current_thread())

        worker = threading.Thread(target=work, daemon=True, name="studio-waveform")
        with self._waveform_inflight_lock:
            self._waveform_threads.add(worker)
        worker.start()

    def _waveform_progress(self, generation: int, media_key: str, text: str) -> None:
        if generation != self._waveform_generation:
            return
        if self._waveform_last_progress_text == text:
            return
        self._waveform_last_progress_text = text
        label = getattr(self, "save_state", None)
        if label is not None:
            label.setText(text)
        timeline = getattr(self, "timeline", None)
        if timeline is not None and timeline.waveform_state in {"EMPTY", "LOADING"}:
            timeline.set_waveform_state("LOADING", text)

    def _waveform_ready(
        self,
        generation: int,
        media_key: str,
        stage: str,
        cache: WaveformCache,
    ) -> None:
        if generation == self._waveform_generation:
            self.timeline.set_cache(cache)
            self.timeline.set_waveform_state("READY")
            self._waveform_last_ready_media = media_key
            self._studio_mark_startup_milestone("WAVEFORM_VISIBLE", media_path=media_key, stage=stage)
            if stage == "partial":
                duration = 0
                if self.project is not None:
                    if str(Path(self.project.media.path).resolve()) == media_key:
                        duration = int(self.project.media.duration_ms or 0)
                    for asset in self.project.media_pool:
                        if str(Path(asset.canonical_source).resolve()) == media_key:
                            duration = max(duration, int(asset.duration_ms or 0))
                coverage = int(cache.metadata.coverage_end_ms or 0)
                if duration > 0 and coverage < duration:
                    self._waveform_progress(
                        generation, media_key,
                        f"正在生成音频波形… {min(99, int(coverage * 100 / duration))}%",
                    )
            if stage == "full":
                self._studio_mark_startup_milestone("WAVEFORM_COMPLETE", media_path=media_key)
                self._start_next_project_waveform(media_key)

    def _waveform_failed(self, generation: int, media_key: str, message: str) -> None:
        if generation == self._waveform_generation:
            bind_text(self.save_state, '波形不可用')
            self.timeline.setToolTip(message)
            self.timeline.set_waveform_state("ERROR", message)
            self._start_next_project_waveform(media_key)

    def _start_next_project_waveform(self, completed_media: str = "") -> None:
        completed = str(completed_media or "")
        if completed:
            self._waveform_pending_media = [
                item for item in self._waveform_pending_media if item != completed
            ]
        while self._waveform_pending_media:
            media_path = self._waveform_pending_media[0]
            if self.timeline.waveform_cache_for_source(media_path) is not None:
                self._waveform_pending_media.pop(0)
                continue
            self._generate_waveform(media_path)
            return

    def _generate_project_waveforms(self) -> None:
        if not self.project:
            return
        from .studio_project import _asset_has_audio

        pending: list[str] = []
        for asset in self.project.media_pool:
            if not _asset_has_audio(asset):
                continue
            source = str(asset.canonical_source or "").strip()
            if source and Path(source).is_file():
                resolved = str(Path(source).resolve())
                if resolved not in pending:
                    pending.append(resolved)
        self._waveform_pending_media = pending
        for source in pending:
            self._studio_mark_startup_milestone("WAVEFORM_REQUESTED", media_path=source)
        self._start_next_project_waveform()

    def _reasr_current(self) -> None:
        if not self.project or not self.selected_cue_id:
            return
        cue_id = self.selected_cue_id
        self._toggle_drawer(0)
        self.ai_preview.setPlainText("正在提取当前字幕附近音频并重新识别...")
        ffmpeg = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"

        def work():
            try:
                result = run_local_reasr(
                    self.project, cue_id, self.runtime_settings, ffmpeg
                )
                self.reasr_ready_signal.emit(result)
            except Exception as exc:
                self.reasr_failed_signal.emit(str(exc))

        threading.Thread(target=work, daemon=True, name="studio-local-reasr").start()

    def _reasr_ready(self, result: LocalReASRResult) -> None:
        if not self.project or result.cue_id != self.selected_cue_id:
            return
        glossary = "、".join(result.glossary_evidence) or "无"
        review = result.review_text or f"未获得结果（后端: {result.backend}）"
        bind_text(self.ai_preview, tr('当前文本:\n{value0}\n\nPrimary result:\n{value1}\n\nReview result:\n{value2}\n\nGlossary evidence:\n{value3}\n\n建议:\n{value4}', value0=result.current_text, value1=result.primary_text, value2=review, value3=glossary, value4=result.recommendation), property='plainText')
        self._pending_suggestion = StudioSuggestion(
            cue_id=result.cue_id,
            before_text=result.current_text,
            after_text=result.recommendation,
            effect=None,
            rationale=f"局部重识别: {result.backend}",
        )

    def _reasr_failed(self, message: str) -> None:
        self._pending_suggestion = None
        self.ai_preview.setPlainText(message)
