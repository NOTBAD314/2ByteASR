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
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from ..media.media_ingest import (MediaIngestResult, ingest_media, result_matches_request)
from ..recognition.recognition_plans import matching_plan, plan_options, recognition_plan
from ..system.resource_governor import ResourceKind
from ..caption_design.studio_ai import StudioSuggestion
from ..timeline.studio_commands import MutationOrigin
from .studio_helpers import probe_media_identity
from ..projects.studio_project import (StudioCue, SubtitleProject, library_project_snapshot, load_project, parse_ass_dialogue_line, parse_subtitle_timecode_ms, project_library_root, repair_project_library_metadata, save_project, studio_settings_path)
from .studio_reasr import (LocalReASRResult, run_local_reasr)
from ..design.presentation import field_width
from ..design.studio_theme import studio_message_box
from ..playback.waveform_cache import (WaveformCache, generate_progressive_waveform_cache)
from ..timeline.audio_stream_lanes import (split_waveform_job, stream_time_mapping, waveform_job, waveform_streams_for)

from ..i18n import bind_text

from ..i18n import tr, user_text

class StudioMediaFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _choose_media_drop_target(self):
        """Choose before ingest; cancellation must not mutate the project."""
        from PySide6.QtWidgets import QInputDialog
        from ..timeline.studio_media_pool import primary_video_track_id
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
                    from ..diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE

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
            # Kept apart from "no audio": recognition says which one it is.
            self._media_probe_error = str(data.get("error") or "unable to probe media")
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
            from ..projects.studio_project import hydrate_media_contract

            started = perf_counter()
            lanes_before = {track.id for track in self.project.audio_tracks}
            asset = hydrate_media_contract(
                self.project,
                identity,
                source_path=media_path,
            )
            self._media_probe_error = ""
            self.timeline.refresh_media_graph()
            self._refresh_edit_playback_state()
            if {track.id for track in self.project.audio_tracks} - lanes_before:
                # A project saved before multi-track import gained the
                # source's further audio streams: draw their waveforms too.
                self.timeline._sync_track_minimum_height()
                self._generate_project_waveforms()
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

    def _begin_media_drop(self, paths, position_ms, track_id="", *, subtitle_paths=()):
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
                    "project_id":project_id, "results":results, "position_ms":position_ms, "track_id":track_id,
                    "subtitle_paths":list(subtitle_paths)})
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
            from ..projects.link_import import MediaCompanionCommand
            has_subtitles = any(r.subtitle_bundle for r in payload["results"])
            command_type = MediaCompanionCommand if has_subtitles else MediaDropCommand
            command = command_type(project, payload["results"], payload["position_ms"], payload["track_id"])
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
        if getattr(command, "result", {}).get("cue_count"):
            self.save_state.setText(tr("已导入 {count} 条配套字幕", count=command.result["cue_count"]))
        self.video.set_paused(True)
        from .studio_link_import import offer_companion_choices
        offer_companion_choices(self, payload["results"])
        dropped_xml = getattr(self, "_pending_drop_xml", "")
        self._pending_drop_xml = ""
        if first_media or dropped_xml:
            # The first recording of a project: look for its same-name XML
            # (a dropped XML counts as the user's explicit choice).
            self._schedule_danmaku_discovery(manual_path=dropped_xml)
        if payload.get("subtitle_paths"):
            self._import_subtitle_files(payload["subtitle_paths"])

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
        if result.subtitle_bundle and pending_mode == "primary" and not project.media.path:
            return self._finish_media_drop(dict(project_id=project.project_id, generation=result.generation,
                results=[result], position_ms=0, track_id=""))
        from ..timeline.studio_edit_sequence import identity_sequence, replace_runtime_sequence
        from ..timeline.studio_media_pool import add_media_asset, add_video_clip, create_video_track
        from ..projects.studio_project import hydrate_media_contract
        from ..projects.studio_runtime_state import DirtyDomain, state_for

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
                        "audio_streams": result.audio_streams,
                    },
                    source_path=result.source_path,
                )
                sequence = identity_sequence(media)
                replace_runtime_sequence(project, sequence, validate=False)
                project.validate()
        else:
            from ..timeline.studio_media_commands import media_graph_command

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
                        "streams": [dict(row) for row in result.audio_streams],
                    },
                )
                if pending_mode == "timeline":
                    from ..timeline.studio_media_pool import primary_video_track_id

                    requested_track_id = getattr(self, "_pending_media_track_id", "")
                    selected_track_id = requested_track_id or str(
                        working.studio_state.get("selected_video_track_id") or ""
                    )
                    primary_id = primary_video_track_id(working)
                    track = create_video_track(working, synchronize=result.has_audio) if requested_track_id == "new" else next(
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
                    ) or create_video_track(working, synchronize=result.has_audio)
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
        # Compatibility reader; the importer uses the full prepared plan.
        from ..projects.subtitle_import import read_subtitles
        from uuid import uuid4
        parsed = read_subtitles(path)
        return [StudioCue("subtitle-cue-" + uuid4().hex, row.start_ms, row.end_ms,
                          row.text, speaker_id=row.speaker or "unassigned-" + uuid4().hex,
                          original_text=row.text) for row in parsed.rows]

    def _open_subtitle_import_dialog(self, *, replace_track_id: str = "") -> None:
        if not self.project:
            return
        title = tr('导入字幕并替换此轨道…') if replace_track_id else tr('导入字幕')
        directory = str(self.project_path.parent if self.project_path else Path.home())
        if replace_track_id:
            path, _selected = QFileDialog.getOpenFileName(self, title, directory, "字幕文件 (*.srt *.ass)")
            paths = [path] if path else []
        else:
            paths, _selected = QFileDialog.getOpenFileNames(self, title, directory, "字幕文件 (*.srt *.ass)")
        if paths:
            self._import_subtitle_files([Path(path) for path in paths], replace_track_id=replace_track_id)

    def _open_recognition_sheet(self, range_ms=None, language_recovery=None) -> None:
        """The 识别字幕 sheet; ``range_ms`` = (in, out) opens it for that stretch only
        (2026-10-25, studio_range_recognition)."""
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
        audio_problem = self._recognition_audio_problem(project)
        if audio_problem is not None:
            title, message = audio_problem
            studio_message_box(self, QMessageBox.Icon.Information, title, message)
            return
        range_info = None
        if range_ms is not None:
            # Only this stretch: captions a point cuts are recognized whole.
            from ..recognition.range_recognition import edited_cue_ids, recognition_window, translated_cue_ids
            requested = (int(range_ms[0]), int(range_ms[1]))
            window_start, window_end, replaced_ids = recognition_window(project, *requested)
            range_info = {"requested": requested, "window": (window_start, window_end),
                          "replaced": replaced_ids, "edited": edited_cue_ids(project, replaced_ids),
                          "translated": translated_cue_ids(project, replaced_ids)}
        sheet_title = "只重新识别这一段字幕" if range_info else "识别字幕"

        host = self.window()
        sheet = QWidget()
        sheet.setObjectName("studioRecognitionSheet")
        # 2026-10-22：ModalHost 给卡片定高且不设尺寸约束；内容超出时 Qt 把
        # 各行压到最小值以下互相叠住（展开「高级配置」后三行模型被压成一条）。
        # 内容放进滚动区，放不下就滚动。
        sheet_layout = QVBoxLayout(sheet)
        sheet_layout.setContentsMargins(0, 0, 0, 0)
        sheet_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("studioRecognitionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea#studioRecognitionScroll, "
            "QScrollArea#studioRecognitionScroll > QWidget#qt_scrollarea_viewport, "
            "QWidget#studioRecognitionBody { background: transparent; border: 0; }"
        )
        sheet_layout.addWidget(scroll)
        body = QWidget()
        body.setObjectName("studioRecognitionBody")
        scroll.setWidget(body)
        # 2026-10-23（用户选方案 C）：阅读次序 = ①顶部一行识别方案 → ②左栏三个
        # 模型角色（主页同款 logo、模型名、支持语言与状态，点一行换模型）→
        # ③右栏「这次识别」（唯一强调色：媒体与会替换多少条、术语词库、翻译、
        # 还缺什么、唯一主按钮）。左右两栏上下对齐。说话人跟随主力转写，不再单选；
        # 原来说话人的位置换成翻译（要先连上 AI）。
        from ..design.presentation import button_role
        from ..design.theme_manager import theme_key
        from ..design.tokens import RADIUS_SCALE, TYPE_SCALE
        from ..design.ui_theme import blend_hex, hex_luminance, theme_definition
        from .recognition_role_rows import RecognitionCardHeader, RecognitionRoleRow, catalog_facts, role_row_rules
        palette = theme_definition(theme_key())
        light = hex_luminance(palette.surface) > 0.5
        sheet.setStyleSheet(
            f"QWidget#studioRecognitionSheet QLabel#recognitionStepTitle {{ color: {palette.text};"
            f" font-size: {TYPE_SCALE['heading2']}px; font-weight: 700; background: transparent; }}"
            f"QWidget#studioRecognitionSheet QFrame#recognitionSummary {{"
            f" background: {blend_hex(palette.surface, palette.accent, 0.12 if light else 0.11)};"
            f" border: 1px solid {blend_hex(palette.surface, palette.accent, 0.45 if light else 0.55)};"
            f" border-radius: {RADIUS_SCALE['surface']}px; }}"
            f"QWidget#studioRecognitionSheet QFrame#recognitionSummary QLabel {{ background: transparent; }}"
            f"QWidget#studioRecognitionSheet QFrame#recognitionPlanCard {{"
            f" background: {blend_hex(palette.surface, palette.text, 0.035 if light else 0.03)};"
            f" border: 1px solid {palette.border}; border-radius: {RADIUS_SCALE['surface']}px; }}"
            f"QWidget#studioRecognitionSheet QWidget#recognitionCardHeader {{ background: transparent; }}"
            f"QWidget#studioRecognitionSheet QLabel#recognitionContext {{ color: {palette.text_secondary};"
            f" font-size: {TYPE_SCALE['small']}px; }}"
            f"QWidget#studioRecognitionSheet QLabel#recognitionImpact {{ color: {palette.accent_text};"
            f" font-size: {TYPE_SCALE['small']}px; font-weight: 600; }}"
            f"QWidget#studioRecognitionSheet QLabel#recognitionFieldLabel {{ color: {palette.text_secondary};"
            f" font-size: {TYPE_SCALE['small']}px; font-weight: 700; }}"
            f"QWidget#studioRecognitionSheet QCheckBox#localSpeakerRecognition {{ color: {palette.text_secondary};"
            f" font-size: {TYPE_SCALE['small']}px; background: transparent; }}"
            f"QWidget#studioRecognitionSheet QLabel#recognitionStepHint {{ color: {palette.text_muted};"
            f" font-size: {TYPE_SCALE['caption']}px; }}"
            f"QWidget#studioRecognitionSheet QLabel#recognitionProblem {{ color: {palette.warning};"
            f" font-size: {TYPE_SCALE['small']}px; font-weight: 600; }}"
            + role_row_rules(palette, light, RADIUS_SCALE['surface'], TYPE_SCALE)
        )

        # 2026-10-23（用户：比例臃肿、右边不对称）：两张对称的卡片，等高、同样的内边距、
        # 同样一行标题栏——左「识别方案」+ 方案下拉，下面三行薄模型行；右「这次识别」
        # + 文件名 + 右上角「AI 设置」，下面词库、翻译、仅本地识别和唯一的主按钮。
        outer = QVBoxLayout(body)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(0)
        layout = QHBoxLayout()
        layout.setSpacing(14)
        outer.addLayout(layout)
        outer.addStretch(1)  # room left over stays below; the rows keep their height

        def card(name: str):
            frame = QFrame()
            frame.setObjectName(name)
            frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            box = QVBoxLayout(frame)
            box.setContentsMargins(16, 14, 16, 14)
            box.setSpacing(8)
            header = RecognitionCardHeader()
            header_row = QHBoxLayout(header)
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(10)
            box.addWidget(header)
            return frame, box, header_row

        left_column, left, plan_row = card("recognitionPlanCard")

        # ① 识别方案：最先看到。
        plan_title = QLabel("识别方案")
        plan_title.setObjectName("recognitionStepTitle")
        plan_row.addWidget(plan_title, 0, Qt.AlignmentFlag.AlignVCenter)
        plan = QComboBox()
        # 四十二轮：方案与主页 plan_options() 对齐，另保留"当前主页方案"快捷项。
        # 2026-10-23：本地识别 / API 转写 / 日语 / 外语；「自定义」只在换过模型时出现。
        for entry in plan_options():
            plan.addItem(entry.label, entry.key)
        plan.addItem("当前主页方案", "home")
        plan.setCurrentIndex(plan.findData("home"))
        for index in range(plan.count()):
            plan.setItemData(index, plan.itemText(index), Qt.ItemDataRole.ToolTipRole)
        plan.currentTextChanged.connect(plan.setToolTip)
        plan.setToolTip(plan.currentText())
        field_width(plan, "expanding")
        plan_row.addWidget(plan, 1, Qt.AlignmentFlag.AlignVCenter)

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

        # The three selectors hold the choice; the rows below show it (and the
        # model picker changes it), so the selectors themselves stay hidden.
        primary_model = QComboBox(body)
        timeline_model = QComboBox(body)
        review_model = QComboBox(body)
        for combo in (primary_model, timeline_model, review_model):
            combo.hide()
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
            from ..app.ui import ASR_API_PRESETS

            provider = str(models_cfg.get("qwen_asr_api_provider") or "qwen31_filetrans")
            preset = ASR_API_PRESETS.get(provider) or {}
            model_id = str(models_cfg.get("qwen_asr_api_model") or preset.get("model") or "")
            short = str(preset.get("short") or provider)
            full = f"在线 ASR API（{short} · {model_id}）" if model_id else f"在线 ASR API（{short}）"
            return full, short

        api_full_label, _api_short = _api_entry_labels()
        for combo in (primary_model, review_model):
            index = combo.findData("api")
            if index >= 0:
                combo.setItemText(index, api_full_label)

        # ② 三个模型角色：薄薄一行（logo、角色、模型名 + 支持语言、状态），点一行换模型。
        advanced = QFrame()
        advanced.setObjectName("recognitionRoles")
        advanced.setStyleSheet("QFrame#recognitionRoles { background: transparent; border: 0; }")
        roles_column = QVBoxLayout(advanced)
        roles_column.setContentsMargins(0, 0, 0, 0)
        roles_column.setSpacing(8)
        role_rows: dict[str, RecognitionRoleRow] = {}
        for role in ("primary", "timeline", "review"):
            row = RecognitionRoleRow(role)
            row.clicked.connect(lambda r: open_role_picker(r))
            roles_column.addWidget(row, 1)
            role_rows[role] = row
        left.addWidget(advanced, 1)
        layout.addWidget(left_column, 3)

        # ③「这次识别」：文件、词库、翻译、仅本地识别，最后是唯一的主按钮。
        summary_card, summary, title_row = card("recognitionSummary")
        summary_title = QLabel("这次识别")
        summary_title.setObjectName("recognitionStepTitle")
        title_row.addWidget(summary_title, 0, Qt.AlignmentFlag.AlignVCenter)
        from .recognition_role_rows import ElidedLabel
        # A range run names its stretch in the note above the start button.
        context = user_text(ElidedLabel(Path(media_path).name)) if project.cues or range_info \
            else bind_text(ElidedLabel(), '{name} · 还没有字幕', name=Path(media_path).name)
        context.setObjectName("recognitionContext")
        context.setToolTip(media_path)
        title_row.addWidget(context, 1, Qt.AlignmentFlag.AlignVCenter)
        # The AI text service (translation needs it) is one button in the corner.
        import qtawesome as qta
        ai_button = QPushButton("AI 设置")
        ai_button.setObjectName("recognitionTranslationUnlock")
        button_role(ai_button, "secondary", size="compact")
        ai_button.setIcon(qta.icon("fa5s.magic", color=palette.accent_text))
        ai_button.setCursor(Qt.CursorShape.PointingHandCursor)
        title_row.addWidget(ai_button, 0, Qt.AlignmentFlag.AlignVCenter)

        def field_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("recognitionFieldLabel")
            return label

        # 词库：一个下拉，弹出勾选列表。四十三轮：词库曾改常驻勾选 chips
        # （下拉复选在 ModalHost 里被压扁 / 点开就退出）。2026-10-22（用户：多按钮
        # 没必要，下拉能显示更多）：菜单里嵌一列勾选框（QWidgetAction）——点勾选框
        # 菜单不关、不经 QComboBox 视图；空 identity 条目照旧过滤。
        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)
        options.setColumnStretch(1, 1)
        options.addWidget(field_label("词库"), 0, 0, Qt.AlignmentFlag.AlignVCenter)
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

        glossary_checks: list[tuple[QCheckBox, str]] = []

        def _glossary_checked_ids(*_args) -> list[str]:
            return [identity for box, identity in glossary_checks if box.isChecked()]

        from .recognition_role_rows import MenuComboBox
        glossary_button = MenuComboBox(lambda: show_glossary_menu())
        glossary_button.setObjectName("recognitionGlossaryButton")
        field_width(glossary_button, "expanding")

        def _sync_glossary_summary(*_args) -> None:
            names = [box.text() for box, _identity in glossary_checks if box.isChecked()]
            if not names:
                glossary_button.set_text(str(tr('选择词库（{count} 个可选）', count=len(glossary_checks))))
                glossary_button.setToolTip("")
            else:
                joined = "、".join(names)
                glossary_button.set_text(str(tr('已选 {count} 个：{names}', count=len(names), names=joined)))
                glossary_button.setToolTip(joined)

        from PySide6.QtWidgets import QMenu, QWidgetAction
        glossary_menu = QMenu(glossary_button)
        glossary_menu.setObjectName("recognitionGlossaryMenu")
        chips_host = QWidget()
        chips_host.setObjectName("recognitionGlossaryList")
        chips_grid = QVBoxLayout(chips_host)
        chips_grid.setContentsMargins(12, 8, 12, 8)
        chips_grid.setSpacing(6)
        for identity, display_name in glossary_entries.items():
            box = QCheckBox(display_name)
            bind_text(box, '识别时启用词库：{display_name}', property='toolTip', display_name=display_name)
            box.stateChanged.connect(_sync_glossary_summary)
            glossary_checks.append((box, identity))
            chips_grid.addWidget(box)
        list_action = QWidgetAction(glossary_menu)
        if len(glossary_entries) > 10:
            # A long library scrolls inside the dropdown instead of growing off screen.
            list_scroll = QScrollArea()
            list_scroll.setWidgetResizable(True)
            list_scroll.setFrameShape(QFrame.Shape.NoFrame)
            list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            list_scroll.setMaximumHeight(360)
            list_scroll.setWidget(chips_host)
            list_action.setDefaultWidget(list_scroll)
        else:
            list_action.setDefaultWidget(chips_host)
        glossary_menu.addAction(list_action)

        def show_glossary_menu() -> None:
            list_action.defaultWidget().setMinimumWidth(glossary_button.width())
            glossary_menu.popup(glossary_button.mapToGlobal(glossary_button.rect().bottomLeft()))

        if glossary_entries:
            options.addWidget(glossary_button, 0, 1)
            _sync_glossary_summary()
        else:
            empty_glossary = QLabel("未关联词库；可继续识别。")
            empty_glossary.setObjectName("recognitionStepHint")
            options.addWidget(empty_glossary, 0, 1)

        # 翻译（原来说话人的位置）：和主页同一组选择，只管这一次识别；要先连上 AI。
        translation_label = field_label("翻译")
        options.addWidget(translation_label, 1, 0, Qt.AlignmentFlag.AlignVCenter)
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, TARGETS, targets_for
        output_labels = (("只显示原文", "original"), ("原文 + 翻译（双语）", "bilingual"), ("只显示翻译", "translation"))
        translation_output = QComboBox()
        translation_output.setObjectName("recognitionTranslationOutput")
        for text, value in output_labels:
            translation_output.addItem(tr(text), value)
        translation_target = user_text(QComboBox())
        translation_target.setObjectName("recognitionTranslationTarget")
        language_options = {}
        language_fn = getattr(host, "_subtitle_language_options", None)
        if callable(language_fn):
            try:
                language_options = dict(language_fn() or {})
            except Exception:  # noqa: BLE001 - home not built: originals only
                language_options = {}
        spoken = str(language_options.get("recognition_language") or "auto")
        if language_recovery:
            spoken = str(language_recovery['requested_language'])
            language_options['recognition_language'] = spoken
        for value in (TARGETS if spoken == "auto" else targets_for(spoken)):
            translation_target.addItem(TARGET_LABELS[value], value)
        translation_target.setCurrentIndex(max(0, translation_target.findData(
            str(language_options.get("translation_script") or "zh-Hans"))))
        for combo in (translation_output, translation_target):
            field_width(combo, "expanding")
        translation_row = QHBoxLayout()
        translation_row.setSpacing(8)
        translation_row.addWidget(translation_output, 3)
        translation_row.addWidget(translation_target, 2)
        options.addLayout(translation_row, 1, 1)
        summary.addSpacing(2)
        summary.addLayout(options)
        translation_state = {"ready": False}

        def ai_gate() -> str:
            try:
                from ..providers.ai_connection_record import service_gate
                return str(service_gate(getattr(getattr(host, "legacy", None), "RUNTIME_SETTINGS", {}) or {}))
            except Exception:  # noqa: BLE001 - unknown: never lock anyone out
                return "ready"

        def refresh_translation_lock(initial: bool = False) -> None:
            gate = ai_gate() if callable(language_fn) else "no_key"
            ready = gate == "ready"
            translation_state["ready"] = ready
            model = translation_output.model()
            for index in range(translation_output.count()):
                value = str(translation_output.itemData(index) or "")
                item = model.item(index) if hasattr(model, "item") else None
                if value == "original" or item is None:
                    continue
                item.setEnabled(ready)
                label = dict((v, t) for t, v in output_labels)[value]
                translation_output.setItemText(index, str(tr(label)) if ready else str(tr("{value0}（文字服务未就绪）", value0=tr(label))))
            wanted = str(translation_output.currentData() or "original")
            if initial:
                wanted = str(language_options.get("subtitle_output") or "original")
            if not ready:
                wanted = "original"
            translation_output.setCurrentIndex(max(0, translation_output.findData(wanted)))
            lines = getattr(host, "AI_LOCK_LINES", {}) or {}
            note = (tr("翻译由 AI 完成，只发送字幕文字（可能产生少量费用）。") if ready
                    else tr(lines.get(gate) or lines.get("no_key") or "需要先填 API Key 并测试连接才能用"))
            translation_output.setToolTip(str(note))
            ai_button.setToolTip(str(note))
            # A range run recognizes original text only (no translation this time).
            ai_button.setVisible((not range_info or bool(language_recovery)) and callable(getattr(host, "_open_ai_settings_dialog", None)))
            translation_target.setVisible((not range_info or bool(language_recovery)) and ready and translation_output.currentData() != "original")
            QTimer.singleShot(0, fit_card)

        def open_ai_settings() -> None:
            opener = getattr(host, "_open_ai_settings_dialog", None)
            if callable(opener):
                opener(on_finished=refresh_translation_lock)

        ai_button.clicked.connect(open_ai_settings)
        translation_output.currentIndexChanged.connect(lambda _index: refresh_translation_lock())

        local_analysis = QCheckBox('仅本地识别与分轨')
        local_analysis.setObjectName('localSpeakerRecognition')
        bind_text(local_analysis, '跳过云端校对和 AI 断句；仍使用所选主转写与时间轴模型（需选本地模型）。说话人跟随主力转写，身份需试听确认。', property='toolTip')
        summary.addSpacing(2)
        summary.addWidget(local_analysis)
        range_notes = []
        if range_info:
            from ..projects.project_range import clock_text
            for widget in (translation_label, translation_output, translation_target, local_analysis):
                widget.hide()
            window_start, window_end = range_info["window"]
            range_notes.append(bind_text(QLabel(), '只识别 {start} – {end}（{duration}），替换这一段的 {count} 条字幕；其他字幕不动，可一步撤销。',
                                         start=clock_text(window_start), end=clock_text(window_end),
                                         duration=clock_text(window_end - window_start),
                                         count=len(range_info["replaced"])))
            if range_info["window"] != range_info["requested"]:
                range_notes.append(bind_text(QLabel(), '入点或出点切在字幕中间，这几条整条一起重新识别。'))
            if range_info["translated"]:
                range_notes.append(bind_text(QLabel(),
                    '旧译文会归档；新原文只采用本次生成的对应译文，未翻译时明确保留待翻译状态。'
                    if language_recovery else '这一段的译文会清空，之后可以重新翻译。'))
            for index, note in enumerate(range_notes):
                note.setObjectName("recognitionImpact" if index == 0 else "recognitionStepHint")
                note.setWordWrap(True)
                summary.addWidget(note)
        # Only for a start that cannot go ahead; what each model still needs is on its row.
        problem = QLabel("")
        problem.setObjectName("recognitionProblem")
        problem.setWordWrap(True)
        problem.hide()
        summary.addWidget(problem)
        summary.addStretch(1)
        start = QPushButton("识别字幕")
        start.setObjectName("studioPrimary")
        button_role(start, "primary", size="large")
        field_width(start, "expanding", size="large")
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        summary.addWidget(start)
        confirm_row = QFrame()
        confirm_layout = QVBoxLayout(confirm_row)
        confirm_layout.setContentsMargins(0, 0, 0, 0)
        confirm_layout.setSpacing(6)
        if range_info:
            confirm_text = bind_text(QLabel(), '这一段有 {count} 条字幕你改过，会被新识别结果替换。',
                                     count=len(range_info["edited"]))
        else:
            confirm_text = bind_text(QLabel(), '将替换当前 {count} 条字幕；保留样式、剪辑和候选。', count=len(project.cues))
        confirm_text.setObjectName("recognitionImpact")
        confirm_text.setWordWrap(True)
        confirm_layout.addWidget(confirm_text)
        confirm_replace = QPushButton("确认替换")
        confirm_replace.setObjectName("studioPrimary")
        button_role(confirm_replace, "primary", size="large")
        field_width(confirm_replace, "expanding", size="large")
        confirm_replace.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_layout.addWidget(confirm_replace)
        confirm_row.hide()
        summary.addWidget(confirm_row)
        layout.addWidget(summary_card, 2)

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

        def plan_provider() -> str | None:
            key = str(plan.currentData() or "custom")
            if key in {"home", "custom"}:
                return None
            return recognition_plan(key).api_provider or None

        def refresh_role_rows() -> None:
            backends = {role: str(combo.currentData() or "") for role, combo in
                        (("primary", primary_model), ("timeline", timeline_model), ("review", review_model))}
            state_fn = getattr(host, "recognition_role_state", None)
            facts = None
            if callable(state_fn):
                try:
                    facts = state_fn(backends, plan_provider())["roles"]
                except Exception:  # noqa: BLE001 - the rows fall back to the catalog
                    facts = None
            if facts is None:
                facts = {role: catalog_facts(role, backends[role], combo.currentText(), plan_provider() or "")
                         for role, combo in (("primary", primary_model), ("timeline", timeline_model),
                                             ("review", review_model))}
            missing = []
            for role, row in role_rows.items():
                if backends[role] in {"", "none"}:
                    facts[role] = dict(facts[role], status=tr("未选择"), tone="warn", model=None, line=None)
                row.set_facts(facts[role])
                if facts[role].get("tone") == "warn" and facts[role].get("status"):
                    missing.append(str(tr("{role} {status}", role=row.role_label.text(), status=facts[role]["status"])))
            # The rows' chips say it; the start button repeats it on hover.
            start.setToolTip(str(tr("还需处理：{items}", items="、".join(missing))) if missing else "")

        def update_plan_summary() -> None:
            key = str(plan.currentData() or "custom")
            if key == "home":
                lead = tr('沿用主页当前的设置')
            elif key == "custom":
                lead = tr('按左边选的模型')
            else:
                lead = tr(recognition_plan(key).description)
            # What the plan does stays one hover away; the rows show what it uses.
            plan.setToolTip(str(lead))
            refresh_role_rows()

        def apply_plan() -> None:
            key = str(plan.currentData() or "custom")
            if key == "home":
                values = (home_models["primary"], home_models["timeline"], home_models["review"])
            else:
                values = recognition_plan(key).backends(spoken, plan_host())
            if values and any(values):
                applying_plan["value"] = True
                try:
                    for combo, value in zip((primary_model, timeline_model, review_model), values):
                        if value and combo.findData(str(value)) < 0:
                            # A plan model not installed yet: shown as itself with 需要下载
                            # (home applies the plan the same way when recognition starts).
                            combo.addItem(str(value), str(value))
                        set_combo_value(combo, str(value or ""))
                finally:
                    applying_plan["value"] = False
            if key != "custom":
                select_plan(key)  # a real choice takes 自定义 out of the list again
            else:
                update_plan_summary()

        role_sources = {
            "primary": (primary_model, "primary_asr_backend"),
            "timeline": (timeline_model, "firered_asr_backend"),
            "review": (review_model, "qwen_asr_backend"),
        }

        def plan_host():
            """The computer's profile (FireRedASR2 needs an NVIDIA GPU); None without the main window."""
            profile = getattr(host, "_home_host_profile", None)
            if profile is None and callable(getattr(host, "recognition_role_state", None)):
                from ..recognition.recognition_choices import host_profile
                profile = host._home_host_profile = host_profile()
            return profile

        def select_plan(key: str) -> None:
            # Show ``key`` without applying it; 自定义 is in the list only while it is current.
            plan.blockSignals(True)
            try:
                custom = plan.findData("custom")
                if key == "custom" and custom < 0:
                    plan.addItem(recognition_plan("custom").label, "custom")
                elif key != "custom" and custom >= 0:
                    plan.removeItem(custom)
                plan.setCurrentIndex(max(0, plan.findData(key)))
            finally:
                plan.blockSignals(False)
            update_plan_summary()

        def host_value(role: str) -> str:
            source = getattr(host, role_sources[role][1], None)
            return str(source.currentData() or "") if isinstance(source, QComboBox) else ""

        def refresh_models_from_host(role: str, before: str) -> None:
            # 二级模型选择弹窗关闭后：只把在弹窗里换了的那个角色同步回来；
            # 没换（直接关掉）就保留这里选的方案和模型（2026-10-23）。
            for target, source_name in role_sources.values():
                copy_model_choices(target, source_name, ())
            chosen = host_value(role)
            if chosen and chosen != before:
                set_combo_value(role_sources[role][0], chosen)
                provider_combo = getattr(host, "qwen_asr_api_provider", None)
                matched = matching_plan(
                    str(primary_model.currentData() or ""),
                    str(timeline_model.currentData() or ""),
                    str(review_model.currentData() or ""),
                    spoken,
                    provider=str(provider_combo.currentData() or "") if isinstance(provider_combo, QComboBox) else None,
                )
                select_plan(matched)
            update_plan_summary()

        def sheet_size() -> tuple[int, int]:
            # Wide enough for the two columns; the height is fitted to the content.
            return min(1060, max(760, host.width() - 48)), min(760, max(520, host.height() - 48))

        def fit_card() -> None:
            modal_host = getattr(host, "_modal_host", None)
            parent = modal_host.parentWidget() if modal_host is not None else None
            if parent is None or not modal_host.isVisible() or not sheet.isVisible():
                return
            card = modal_host.card
            viewport = scroll.viewport()
            chrome = card.height() - viewport.height()
            grid = body.layout()
            need = grid.totalHeightForWidth(viewport.width()) if grid.hasHeightForWidth() else -1
            need = need if need > 0 else body.sizeHint().height()
            area = parent.rect()
            width = min(card.width(), max(1, area.width() - 24))
            height = max(320, min(area.height() - 24, need + chrome + 2))
            card.setGeometry((area.width() - width) // 2, max(12, (area.height() - height) // 2), width, height)

        def open_role_picker(role: str) -> None:
            open_fn = getattr(host, "_open_model_picker", None)
            if not callable(open_fn):
                return

            before = host_value(role)

            def _restore() -> None:
                refresh_models_from_host(role, before)
                host_modal = getattr(host, "_modal_host", None)
                if host_modal is not None:
                    host_modal.show_content(
                        sheet,
                        title=sheet_title,
                        size=sheet_size(),
                        min_size=(760, 420),
                        retain_content=True,
                    )
                    QTimer.singleShot(0, fit_card)

            open_fn(role, on_closed=_restore)

        if range_info:
            bind_text(start, '识别这一段')
        else:
            (bind_text(start, '识别并替换当前字幕') if project.cues else bind_text(start, '识别字幕'))

        def current_range() -> dict | None:
            """The stretch at the start (captions may have changed since the sheet opened)."""
            if not range_info:
                return None
            from ..recognition.range_recognition import recognition_window
            window_start, window_end, replaced_ids = recognition_window(project, *range_info["requested"])
            return {"requested": list(range_info["requested"]), "window": [window_start, window_end],
                    "replaced": list(replaced_ids)}

        def request_options() -> dict:
            from ..recognition.speaker_strategy import resolve
            settings = getattr(getattr(host, "legacy", None), "RUNTIME_SETTINGS", {}) or {}
            output = str(translation_output.currentData() or "original") if translation_state["ready"] else "original"
            stretch = current_range()
            if stretch is not None and not language_recovery:
                output = "original"
            options = {
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
                # Speakers follow the primary model (speaker_strategy.resolve); not chosen here.
                "speaker_source": resolve(settings),
                "subtitle_output": output,
                "translation_script": str(translation_target.currentData() or "zh-Hans"),
            }
            if stretch is not None:
                # 2026-10-25: only this stretch is heard; its captions are replaced.
                options.update(replace_policy="replace_range", purpose="final",
                               recognition_range_ms=stretch["window"],
                               requested_range_ms=stretch["requested"],
                               range_replaced_cue_ids=stretch["replaced"])
            if language_recovery:
                options['language_recovery_policy'] = dict(language_recovery,
                    explicit_range=True, explicit_local_range=str(primary_model.currentData())=='qwen_local')
                options['recognition_language'] = spoken
            return options

        def dispatch(action: str, lanes=None) -> None:
            modal = getattr(host, "_modal_host", None)
            if action == "configure":
                if modal is not None:
                    modal.hide_content()
                self.recognition_requested.emit(action, media_path, project_path)
                return
            if getattr(self, "_recognition_running", False):
                bind_text(problem, '已有识别任务正在运行，请等待完成或取消后再试。')
                problem.show()
                return
            if language_recovery and str(primary_model.currentData())=='qwen_local':
                from ..recognition.asr import resolve_qwen_asr_local_source, resolve_qwen_aligner_local_source
                from ..system.runtime_registry import resolve_runtime_python
                ready = bool(resolve_qwen_asr_local_source() and resolve_runtime_python('main',register=False))
                if not ready or (str(timeline_model.currentData())=='qwen_aligner' and not resolve_qwen_aligner_local_source()):
                    bind_text(problem,'本地模型或运行环境未就绪。正常结果已保留；请选择已有可用方案，本次不会自动下载或上传音频。')
                    problem.show()
                    return
            if (self.project is not project or str(self.project_path or '') != project_path
                    or str(project.media.path or '') != media_path):
                bind_text(problem, '工程或媒体已变化，请关闭窗口后重新开始识别。')
                problem.show()
                return
            if local_analysis.isChecked():
                if (str(primary_model.currentData()) not in {'moss','firered','qwen_local','whisper_turbo','paraformer'}
                        or str(timeline_model.currentData()) == 'api'):
                    bind_text(problem, '仅本地识别需要本地的主力转写和时间轴模型；请点左边那一行换成本地模型。')
                    problem.show()
                    return
                action='start_analysis'
            self._recognition_request_options = request_options()
            if lanes:
                # 2026-10-24: the picked audio tracks, each recognized on its own.
                self._recognition_request_options["audio_lanes"] = [dict(row) for row in lanes]
            self._recognition_started_at = perf_counter()
            # 四十二轮：识别转后台。①弹窗立即关闭（状态进左侧字幕列表芯片），
            # 否则 _start_run 预检分支的 QMessageBox 会被 ModalHost 盖住形成
            # "隐形模态卡死"（用户实录"在线API识别一直卡住"）；②记录替换基线
            # 与 autosave 代次，供完成后"保留编辑/重新加载"裁决。
            stretch = self._recognition_request_options.get("recognition_range_ms")
            if action == "start_final" and not stretch:
                self._recognition_replace_baseline_ids = {cue.id for cue in project.cues}
            else:
                self._recognition_replace_baseline_ids = None
            # A range run's live rows are window-local; the result is spliced at the end.
            self._recognition_range = list(stretch) if stretch else None
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
            self._recognition_lane_note = None
            self._recognition_status_sticky = ""
            self._recognition_show_status("准备模型", "")
            if getattr(self, "_recognition_runtime_timer", None) is not None:
                self._recognition_runtime_timer.stop()
            self._recognition_runtime_timer = QTimer(self)
            self._recognition_runtime_timer.timeout.connect(self._update_recognition_elapsed)
            self._recognition_runtime_timer.start(250)
            self.recognition_requested.emit(action, media_path, project_path)

        def open_track_picker() -> None:
            analysis = local_analysis.isChecked()

            def restore_sheet() -> None:
                host_modal = getattr(host, "_modal_host", None)
                if host_modal is not None:
                    host_modal.show_content(sheet, title=sheet_title, size=sheet_size(),
                                            min_size=(760, 420), retain_content=True)
                    QTimer.singleShot(0, fit_card)

            def start_with(lanes) -> None:
                self._finish_track_picker(picker)
                self._remember_track_choice(lanes)
                dispatch("start_final", lanes=lanes)

            def cancel() -> None:
                self._finish_track_picker(picker)
                restore_sheet()

            picker = self._open_audio_track_picker(on_closed=lambda: self._finish_track_picker(picker),
                                                    single=analysis)
            if picker is None:
                dispatch("start_final")
                return
            picker.accepted.connect(start_with)
            picker.cancelled.connect(cancel)

        def start_clicked() -> None:
            if range_info:
                # Captions edited by hand in this stretch are confirmed first.
                from ..recognition.range_recognition import edited_cue_ids
                stretch = current_range()
                edited = edited_cue_ids(project, stretch["replaced"])
                if edited:
                    bind_text(confirm_text, '这一段有 {count} 条字幕你改过，会被新识别结果替换。', count=len(edited))
                    start.hide()
                    confirm_row.show()
                    QTimer.singleShot(0, fit_card)
                    return
                dispatch("start_final")
                return
            if self._recognition_needs_track_picker(project):
                # Several audio tracks: which ones is the user's call. The
                # picker also shows what happens to existing captions.
                open_track_picker()
                return
            if project.cues:
                # The second press confirms; the button's place keeps the panel's height.
                start.hide()
                confirm_row.show()
                QTimer.singleShot(0, fit_card)
                return
            dispatch("start_final")

        plan.currentIndexChanged.connect(lambda _index: apply_plan())
        for combo in (primary_model, timeline_model, review_model):
            combo.currentIndexChanged.connect(
                lambda _index: select_plan("custom")
                if not applying_plan["value"] and str(plan.currentData()) not in {"custom", "home"}
                else None
            )
            combo.currentIndexChanged.connect(lambda _index: None if applying_plan["value"] else update_plan_summary())
        start.clicked.connect(start_clicked)
        confirm_replace.clicked.connect(lambda: dispatch("start_final"))
        apply_plan()
        if language_recovery:
            select_plan('custom')
            for combo, value in ((primary_model,'qwen_local'),(timeline_model,'qwen_aligner'),(review_model,'off')):
                index = combo.findData(value)
                if index < 0:
                    combo.addItem({'qwen_local':tr('Qwen3-ASR 本地'),'qwen_aligner':tr('Qwen3-ForcedAligner'),'off':tr('关闭')}[value],value)
                    index=combo.findData(value)
                combo.setCurrentIndex(index)
            bind_text(start, '用所选方案恢复这一段')
            range_notes.append(bind_text(QLabel(), '只处理异常范围；本地方案不会上传音频，模型未就绪时不会自动下载。旧文字与设置保留在可恢复记录中。'))
            range_notes[-1].setWordWrap(True)
            summary.insertWidget(max(0,summary.count()-1),range_notes[-1])
        refresh_translation_lock(initial=True)
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
            "left": left_column,
            "rows": role_rows,
            "summary": summary_card,
            "glossaries": chips_host,
            "translation": translation_output,
            "translation_target": translation_target,
            "start": start,
            "confirm": confirm_row,
            "confirm_text": confirm_text,
            "confirm_replace": confirm_replace,
            "local_analysis": local_analysis,
            "range": range_info,
            "range_notes": range_notes,
        }

        modal = getattr(host, "_modal_host", None)
        if modal is not None:
            # 四十三轮：768 高的屏幕放不下 760 的弹窗（词库区会被压出视野）；
            # 2026-10-22：宽卡片，显示后按内容定高（放不下才滚动）。
            modal.show_content(
                sheet,
                title=sheet_title,
                size=sheet_size(),
                min_size=(760, 420),
                retain_content=True,
            )
            QTimer.singleShot(0, fit_card)
        else:
            self.recognition_requested.emit("configure", media_path, project_path)

    def _recognition_audio_problem(self, project):
        """(title, message) when there is nothing to recognize, else None.

        2026-10-24: a source probed without any audio stream says so, and a
        source whose probe failed says that instead; both used to start a
        run on silence.
        """
        from ..timeline.audio_stream_lanes import recognizable_lanes
        if recognizable_lanes(project):
            return None
        used = {clip.asset_id for track in (*project.video_tracks, *project.audio_tracks) for clip in track.clips}
        assets = [asset for asset in project.media_pool if asset.asset_id in used]
        probe_error = str(getattr(self, "_media_probe_error", "") or "")
        if probe_error:
            return tr('无法读取音轨信息'), tr('读取素材的音轨信息失败：{error}', error=probe_error)
        if assets and all((asset.audio_metadata or {}).get("has_audio") is False for asset in assets):
            return tr('没有可识别的音轨'), tr('此素材没有可识别的音轨。请导入带声音的视频或音频。')
        return None

    def _recognition_needs_track_picker(self, project) -> bool:
        """A multi-track source on the timeline and more than one audio lane."""
        from ..timeline.audio_stream_lanes import has_multitrack_source, recognizable_lanes
        return has_multitrack_source(project) and len(recognizable_lanes(project)) >= 2

    def _open_audio_track_picker(self, *, on_closed=None, single=False):
        project = self.project
        host = self.window()
        modal = getattr(host, "_modal_host", None)
        if project is None or modal is None:
            return None
        from ..recognition.audio_lane_results import CHOICE_KEY, SUMMARY_KEY
        from ..timeline.audio_stream_lanes import recognizable_lanes
        from .audio_track_picker import AudioTrackPicker, default_choice
        rows = recognizable_lanes(project)
        timeline = getattr(self, "timeline", None)
        selected = []
        if timeline is not None:
            explicit = {str(getattr(timeline, "selected_audio_track_id", "") or "")}
            clip_ids = set(getattr(timeline, "selected_audio_clip_ids", ()) or ())
            explicit |= {track.id for track in project.audio_tracks if any(c.id in clip_ids for c in track.clips)}
            selected = [lane for lane in explicit if lane]
        checked = default_choice(rows, selected_lanes=selected,
                                 remembered=project.studio_state.get(CHOICE_KEY) or ())
        if single:
            checked = checked[:1]
        picker = AudioTrackPicker(project, rows, checked, start_ms=int(timeline.playhead_ms) if timeline else 0,
                                  previous=project.generation_metadata.get(SUMMARY_KEY) or {}, single=single)
        picker.preview_started.connect(self._pause_for_track_preview)
        self._studio_trace("AUDIO_TRACK_PICKER_OPEN", lanes=[row["lane_id"] for row in rows], checked=checked,
                           streams=[[row["ordinal"], row["stream_index"]] for row in rows])
        # Intro, source header, a ~70 px row per track, count, note, impact, buttons.
        height = min(max(420, host.height() - 48), 380 + 72 * len(rows))
        modal.show_content(picker, title="选择要识别的音轨", size=(660, height), min_size=(520, 360),
                           on_closed=on_closed)
        return picker

    def _pause_for_track_preview(self) -> None:
        """A preview never plays over the timeline; resume when the picker closes."""
        video = getattr(self, "video", None)
        try:
            playing = bool(video is not None and video.controller
                           and not video.playback_position_snapshot().paused)
        except (RuntimeError, AttributeError):
            playing = False
        self._track_preview_resume = playing
        if playing:
            video.set_paused(True)
            self._sync_play_button(True)

    def _finish_track_picker(self, picker) -> None:
        if picker is not None:
            picker.shutdown()
        if getattr(self, "_track_preview_resume", False):
            self._track_preview_resume = False
            try:
                self.video.set_paused(False)
                self._sync_play_button(False)
            except (RuntimeError, AttributeError):
                pass

    def _remember_track_choice(self, lanes) -> None:
        """This project's track choice, bound to the source file and stream."""
        from ..recognition.audio_lane_results import CHOICE_KEY
        from ..timeline.audio_stream_lanes import source_key
        if self.project is not None:
            self.project.studio_state[CHOICE_KEY] = [source_key(row) for row in lanes]
            self._studio_trace("AUDIO_TRACK_PICKER_START", lanes=[row["lane_id"] for row in lanes],
                               streams=[[row["ordinal"], row["stream_index"]] for row in lanes])

    def recognition_request_options(self) -> dict:
        return copy.deepcopy(getattr(self, "_recognition_request_options", {}))

    def _recognition_chip_parts(self):
        frame = getattr(self, "recognition_chip", None)
        label = getattr(self, "recognition_chip_label", None)
        if frame is None or label is None:
            return None
        return frame, label

    def set_recognition_lane_note(self, note) -> None:
        """'音轨 1/2 · 中文配音': which picked track is being recognized."""
        self._recognition_lane_note = note
        self._update_recognition_elapsed(force=True)

    def _recognition_status_text(self) -> str:
        running = bool(getattr(self, "_recognition_running", False))
        started = float(getattr(self, "_recognition_started_at", 0.0) or 0.0)
        label = getattr(self, "recognition_chip_label", None)
        stage = getattr(self, "_recognition_stage_message", None) or ((label.property("recognitionStage") if label is not None else "") or "识别中")
        lane = getattr(self, "_recognition_lane_note", None) if running else None
        if running and started:
            elapsed = max(0, int(perf_counter() - started))
            text = tr('识别中 · {stage} · {minutes:02d}:{seconds:02d}', stage=stage if hasattr(stage, "source") else tr(stage), minutes=elapsed//60, seconds=elapsed%60)
            return tr('{lane} · {status}', lane=lane, status=text) if lane else text
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
        from .language_recovery_ui import sync_action
        sync_action(self)

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
        if project is None or getattr(self, "_recognition_range", None):
            # A range run's live rows are window-local: the finished result is
            # spliced in by ``studio_range_recognition.apply_range_result``.
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
        from ..projects.studio_runtime_state import DirtyDomain, state_for

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
        request=getattr(self,'_recognition_request_options',{}) or {}
        span=request.get('recognition_range_ms')
        if isinstance(span,(list,tuple)) and len(span)==2:
            duration=max(0.,(float(span[1])-float(span[0]))/1000)
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

    def apply_range_recognition_result(self, project_path: str, snapshot) -> bool:
        """A finished 只重新识别这一段 run: splice it in as one undo step (2026-10-25)."""
        from .studio_range_recognition import apply_range_result
        return apply_range_result(self, project_path, snapshot)

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
        self._recognition_range = None
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
        return self._import_subtitle_files([path])

    def _import_subtitle_files(self, paths, *, replace_track_id: str = ""):
        if not self.project:
            studio_message_box(self, QMessageBox.Icon.Information, tr('先加载媒体'),
                               tr('请先拖入媒体或 .2byteproj，再导入字幕。'))
            return
        from ..projects.subtitle_import import prepare_import
        from ..timeline.subtitle_import_command import ImportSubtitlesCommand
        try:
            if replace_track_id in self.timeline.locked_speakers:
                raise ValueError("指定字幕轨道已锁定，请先解锁")
            plan = prepare_import(self.project, paths, replace_track_id=replace_track_id)
            self._last_subtitle_import = plan
            if not plan.cues:
                raise ValueError("\n".join(plan.failures) or "没有读取到有效字幕")
            self.undo_stack.push(ImportSubtitlesCommand(self.project, plan, self._changed, self._populate_speakers))
            self.select_cue(plan.cues[0].id)
            message = tr('已导入 {count} 条字幕', count=len(plan.cues))
            details = "\n".join(dict.fromkeys(plan.failures + plan.warnings))
            if details:
                message += " · " + details
            self._show_studio_hint(message)
            self.save_state.setToolTip(details)
            return plan
        except (OSError, ValueError) as exc:
            studio_message_box(self, QMessageBox.Icon.Critical, tr('导入字幕失败'), str(exc))

    def _generate_waveform(self, media_path: str) -> None:
        # ``media_path`` is a waveform job: a path, or ``path|aN`` for audio
        # stream N of a multi-track source (2026-10-24).
        media_path, audio_stream = split_waveform_job(media_path)
        media_key = waveform_job(str(Path(media_path).resolve()), audio_stream)
        source_key = str(Path(media_path).resolve())
        self._studio_mark_startup_milestone("WAVEFORM_REQUESTED", media_path=media_key)
        self._studio_mark_startup_milestone("WAVEFORM_CACHE_LOOKUP", media_path=media_key)
        cache = self.timeline.waveform_cache_for_source(source_key, audio_stream)
        if (
            cache is not None
            and str(Path(cache.metadata.source_path).resolve()) == source_key
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
        root = Path(__file__).resolve().parents[2]
        ffmpeg = root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        self._waveform_generation += 1
        generation = self._waveform_generation
        self.timeline.set_waveform_state("LOADING", "正在生成音频波形…")

        from ..diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE

        def trace_log(event: str, fields: dict) -> None:
            GLOBAL_STUDIO_TRACE.emit(event, {"media_path": media_key, **fields})

        def resolve_duration_ms() -> int:
            duration = 0
            if self.project is not None:
                if str(Path(self.project.media.path).resolve()) == source_key:
                    duration = int(self.project.media.duration_ms or 0)
                for asset in self.project.media_pool:
                    if str(Path(asset.canonical_source).resolve()) == source_key:
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
                    time_mapping=stream_time_mapping(self.project, source_key, audio_stream),
                    audio_stream=audio_stream,
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
        if getattr(self, '_completed_waveform_progress', None) == (generation, media_key):
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
                source_key = split_waveform_job(media_key)[0]
                if self.project is not None:
                    if str(Path(self.project.media.path).resolve()) == source_key:
                        duration = int(self.project.media.duration_ms or 0)
                    for asset in self.project.media_pool:
                        if str(Path(asset.canonical_source).resolve()) == source_key:
                            duration = max(duration, int(asset.duration_ms or 0))
                coverage = int(cache.metadata.coverage_end_ms or 0)
                if duration > 0 and coverage < duration:
                    self._waveform_progress(
                        generation, media_key,
                        f"正在生成音频波形… {min(99, int(coverage * 100 / duration))}%",
                    )
            if stage == "full":
                self._completed_waveform_progress = (generation, media_key)
                label = getattr(self, 'save_state', None)
                if label is not None and label.text() == self._waveform_last_progress_text:
                    # This says only that waveform work completed; never claim
                    # that a concurrent manual/automatic project save succeeded.
                    bind_text(label, '波形已就绪')
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
            if self.timeline.waveform_cache_for_source(*split_waveform_job(media_path)) is not None:
                self._waveform_pending_media.pop(0)
                continue
            self._generate_waveform(media_path)
            return

    def _generate_project_waveforms(self) -> None:
        if not self.project:
            return
        from ..projects.studio_project import _asset_has_audio

        pending: list[str] = []
        later: list[str] = []
        for asset in self.project.media_pool:
            if not _asset_has_audio(asset):
                continue
            source = str(asset.canonical_source or "").strip()
            if source and Path(source).is_file():
                resolved = str(Path(source).resolve())
                # The audible lanes' streams first; further streams of a
                # multi-track source follow in the background.
                lead, rest = waveform_streams_for(self.project, asset.asset_id)
                for stream in lead:
                    if waveform_job(resolved, stream) not in pending:
                        pending.append(waveform_job(resolved, stream))
                for stream in rest:
                    if waveform_job(resolved, stream) not in later:
                        later.append(waveform_job(resolved, stream))
        pending += [job for job in later if job not in pending]
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
        ffmpeg = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"

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
