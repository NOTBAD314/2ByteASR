"""Project lifecycle orchestration for Subtitle Studio."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox, QToolTip

from .i18n import current_language, translate, tr, user_text
from .project_display_name import display_project_name
from .studio_fonts import missing_project_fonts
from .processes import run_hidden_subprocess
from .studio_helpers import media_relink_warning, probe_media_identity
from .media_availability import media_available
from .studio_project import (
    PROJECT_SUFFIX,
    ProjectValidationError,
    StudioMedia,
    SubtitleProject,
    hydrate_media_contract,
    load_project,
    project_content_fingerprint,
    project_library_root,
    recoverable_autosave,
    save_project,
    studio_settings_path,
)
from .studio_qc import terminology_from_project
from .studio_session import StudioSession
from .studio_theme import apply_secondary_surface_theme, studio_message_box
from .project_dirty_guard import ProjectDirtyGuard
from .runtime_trace import GLOBAL_STUDIO_TRACE

from .i18n import bind_text


class StudioProjectController:
    """Coordinate project persistence and page population without owning UI state."""

    __slots__ = ("page", "session")

    def __init__(self, page, session: StudioSession):
        self.page = page
        self.session = session

    @contextmanager
    def _studio_operation(
        self,
        name: str,
        *,
        project_id: str = "",
        media_path: str = "",
        blocking_ui_thread: bool = True,
    ):
        """Record a Studio-open operation with packaged-runtime timing fields."""
        with GLOBAL_STUDIO_TRACE.operation(
            name,
            project_id=project_id,
            media_path=media_path,
            blocking_ui_thread=blocking_ui_thread,
        ):
            yield

    @property
    def dirty_guard(self) -> ProjectDirtyGuard:
        return ProjectDirtyGuard(self.page)

    def import_media_dialog(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self.page,
            tr('导入媒体'),
            "",
            "媒体文件 (*.mp4 *.mkv *.mov *.webm *.flv *.avi *.wav *.mp3 *.m4a *.flac *.aac);;所有文件 (*)",
        )
        if path:
            self.page._open_or_create_media_project(Path(path))

    def create_blank_project(self, *, focus_clip_assistant: bool = False, on_ready=None) -> None:
        """Open an empty Studio: no media, no cues, no XML."""
        page = self.page
        if not self.dirty_guard.confirm("新建工程"):
            return
        library = project_library_root()
        base = "未命名工程"
        name = base
        index = 2
        while (library / name / f"{name}{PROJECT_SUFFIX}").is_file():
            name = f"{base} {index}"
            index += 1
        project_dir = library / name
        for child in ("source", "autosave", "cache", "preview", "backup", "exports"):
            (project_dir / child).mkdir(parents=True, exist_ok=True)
        project = SubtitleProject(
            media=StudioMedia(path="", display_name=name, duration_ms=0),
        )
        project.studio_state["project_name_origin"] = {"kind": "unnamed", "number": index - 1 if name != base else None}
        target = save_project(project, project_dir / f"{name}{PROJECT_SUFFIX}")
        page.open_project(target, skip_dirty_guard=True, on_ready=on_ready)
        if focus_clip_assistant and page.project is not None:
            page._open_clip_assistant()

    def show_project_hub(self, *, skip_dirty_guard: bool = False) -> bool:
        """Show the Studio entry surface without implicitly opening a project."""
        page = self.page
        if not skip_dirty_guard and not self.dirty_guard.confirm("关闭当前工程"):
            return False
        page._cancel_media_ingest()
        if hasattr(page, "_close_export_workspace"):
            page._close_export_workspace()
        page._project_view_state = "hub"
        page._project_opening_path = ""
        page._close_project_session("project_hub")
        bind_text(page.filename, tr('2ByteASR  兔白字幕'))
        bind_text(page.save_state, translate('未打开项目', current_language()))
        page._recovered_autosave_pending = False
        page._review_mode = False
        page.review_summary_strip.hide()
        page.cue_model.set_project(None)
        page.timeline.set_project(None)
        if hasattr(page, "_widget_alive") and page._widget_alive(getattr(page, "position_overlay", None)):
            page.position_overlay.hide()
        elif hasattr(page, "position_overlay"):
            try:
                page.position_overlay.hide()
            except RuntimeError:
                pass
        page._set_hub_toolbar_mode(True)
        page.hub_loading_label.hide()
        page.studio_empty.show()
        page.studio_empty.raise_()
        page._refresh_studio_empty_state()
        return True

    def open_project_dialog(self) -> None:
        page = self.page
        path, _selected = QFileDialog.getOpenFileName(
            page, tr('打开 Subtitle Project'), "", "2ByteASR Project (*.2byteproj)"
        )
        if path:
            host = page.window()
            if host is not page and hasattr(host, "open_studio_project"):
                host.open_studio_project(path, mode="edit", source="open_dialog")
            else:
                page.open_project(path)

    def most_recent_project(self, *, settings_path_fn=studio_settings_path) -> str:
        try:
            payload = json.loads(settings_path_fn().read_text(encoding="utf-8"))
            recent = payload.get("recent_projects", []) if isinstance(payload, dict) else []
        except (OSError, ValueError, TypeError):
            recent = []
        for item in recent:
            path = item.get("path", "") if isinstance(item, dict) else item
            if Path(str(path)).is_file():
                return str(path)
        return ""

    def recent_project_records(self, *, settings_path_fn=studio_settings_path) -> list[dict[str, object]]:
        try:
            payload = json.loads(settings_path_fn().read_text(encoding="utf-8"))
            recent = payload.get("recent_projects", []) if isinstance(payload, dict) else []
        except (OSError, ValueError, TypeError):
            recent = []
        records: list[dict[str, object]] = []
        for item in recent:
            record = dict(item) if isinstance(item, dict) else {"path": str(item)}
            path = Path(str(record.get("path", "")))
            record.setdefault("name", path.stem)
            record.setdefault("source_media", "")
            record.setdefault("modified", "")
            record.setdefault("cue_count", 0)
            record.setdefault("cover_path", "")
            if not path.is_file():
                record["status"] = "工程文件已移动"
            else:
                record.setdefault("status", "可打开")
            record.setdefault("pinned", False)
            records.append(record)
        return records

    def _remember_recent_project(self, path: Path, *, settings_path_fn=studio_settings_path) -> None:
        settings_path = settings_path_fn()
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        resolved = str(path.resolve())
        existing = payload.get("recent_projects", []) if isinstance(payload, dict) else []
        previous = next(
            (
                dict(item)
                for item in existing
                if isinstance(item, dict) and str(item.get("path", "")) == resolved
            ),
            {},
        )
        project = self.session.project
        existing_cover = previous.get("cover_path", "")
        canonical_cover = path.resolve().parent / "preview" / "project-cover.jpg"
        cover_path = str(canonical_cover) if canonical_cover.is_file() else existing_cover
        current = {
            "path": resolved,
            "name": str(project.studio_state.get("project_name") or path.stem) if project else path.stem,
            "name_origin": dict(project.studio_state.get("project_name_origin") or {}) if project else {},
            "name_custom": bool(project and project.studio_state.get("project_name") and not project.studio_state.get("project_name_automatic")),
            "source_media": project.media.path if project else "",
            "modified": project.updated_at if project else "",
            "last_opened": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "created_at": project.created_at if project else "",
            "updated_at": project.updated_at if project else "",
            "duration_ms": project.media.duration_ms if project else 0,
            "cue_count": len(project.cues) if project else 0,
            "cover_path": str(cover_path or ""),
            "status": "已保存",
            "pinned": bool(previous.get("pinned", False)),
        }
        retained = []
        for item in existing:
            item_path = item.get("path", "") if isinstance(item, dict) else item
            if str(item_path) != resolved:
                retained.append(item)
        retained.sort(key=lambda item: not bool(item.get("pinned", False)) if isinstance(item, dict) else True)
        payload["recent_projects"] = [current] + retained[:9]
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._touch_library_index_entry(path, current)

    def _touch_library_index_entry(self, path: Path, recent_record: dict) -> None:
        """Keep the persisted Library index fresh for one project (save/open).

        2026-09-19：索引是工程库首屏的数据源；保存或打开工程时把摘要与
        (mtime_ns, size) 指纹一起写回，重启后首屏即可显示最新数据，
        后台扫描也无需再全量解析这个工程。
        """
        from .studio_project import load_library_index, save_library_index

        try:
            stat = path.resolve().stat()
        except OSError:
            return
        index = load_library_index()
        resolved = str(path.resolve())
        entry = {
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            "needs_metadata_repair": False,
            "project_id": (self.session.project.project_id if self.session.project else ""),
            "name": str(recent_record.get("name") or path.stem),
            "cue_count": int(recent_record.get("cue_count") or 0),
            "duration_ms": int(recent_record.get("duration_ms") or 0),
            "source_media": str(recent_record.get("source_media") or ""),
            "created_at": str(recent_record.get("created_at") or ""),
            "updated_at": str(recent_record.get("updated_at") or ""),
            "width": 0,
            "height": 0,
            "cover_path": str(recent_record.get("cover_path") or ""),
        }
        if index.get(resolved) and int(index[resolved].get("mtime_ns", -1)) == entry["mtime_ns"]:
            previous = index[resolved]
            for dimension in ("width", "height"):
                entry[dimension] = int(previous.get(dimension) or 0)
            entry["project_id"] = entry["project_id"] or str(previous.get("project_id") or "")
        index[resolved] = entry
        save_library_index(index)

    def _ensure_project_cover(self, project_path: Path, project: SubtitleProject) -> Path | None:
        preview_dir = project_path.resolve().parent / "preview"
        cover = preview_dir / "project-cover.jpg"
        if cover.is_file() and cover.stat().st_size > 1024:
            return cover
        media = Path(project.media.path)
        ffmpeg = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if not media.is_file() or not ffmpeg.is_file():
            return cover if cover.is_file() else None
        preview_dir.mkdir(parents=True, exist_ok=True)
        seek_seconds = min(90.0, max(1.0, float(project.media.duration_ms or 0) / 100_000.0))
        result = run_hidden_subprocess(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{seek_seconds:.3f}", "-i", str(media), "-frames:v", "1",
                "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "3", str(cover),
            ],
            purpose="ffmpeg project cover",
            capture_output=True,
            timeout=20,
        )
        return cover if result.returncode == 0 and cover.is_file() else None

    def _relink_media(
        self,
        *,
        probe_media_identity_fn=probe_media_identity,
        message_box_fn=studio_message_box,
    ) -> None:
        page = self.page
        project = self.session.project
        if not project:
            return
        asset = next((a for a in project.media_pool if a.canonical_source == project.media.path), None)
        if asset is None:
            page.media_availability.show_media()
            return
        page.media_availability.choose_relink(asset.asset_id)

    def _attach_media_to_current(
        self,
        media_path: Path,
        *,
        add_to_timeline: bool = False,
        target_track_id: str = "",
    ) -> None:
        project = self.session.project
        if project is not None:
            primary = not str(project.media.path or "").strip() and not project.media_pool
            self.page._begin_media_ingest(
                media_path,
                add_to_pool=not primary,
                add_to_timeline=bool(add_to_timeline and not primary),
                **({"target_track_id": target_track_id} if target_track_id else {}),
            )

    def _open_or_create_media_project(
        self,
        media_path: Path,
        *,
        project_library_root_fn=project_library_root,
        probe_media_identity_fn=probe_media_identity,
        save_project_fn=save_project,
        message_box_fn=studio_message_box,
    ) -> None:
        current = self.session.project
        if current is not None:
            self._attach_media_to_current(media_path)
            return
        project_dir = project_library_root_fn() / media_path.stem
        candidate = project_dir / f"{media_path.stem}{PROJECT_SUFFIX}"
        for child in ("source", "autosave", "cache", "preview", "backup", "exports"):
            (project_dir / child).mkdir(parents=True, exist_ok=True)
        legacy = Path.home() / "Desktop" / "2ByteASR Projects" / media_path.stem / f"{media_path.stem}{PROJECT_SUFFIX}"
        if not candidate.is_file() and legacy.is_file():
            answer = message_box_fn(
                self.page,
                QMessageBox.Icon.Question,
                "检测到旧版字幕工程",
                f"是否将旧工程复制到新的工程库？\n{project_library_root_fn()}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                shutil.copy2(legacy, candidate)
            else:
                candidate = legacy
        if candidate.is_file():
            self.page.open_project(candidate)
            return
        media = StudioMedia(path="", display_name=media_path.name)
        project = SubtitleProject(media=media)
        self.session.project_path = save_project_fn(project, candidate)
        self.page.open_project(self.session.project_path)
        self.page._begin_media_ingest(media_path)

    def open_project_entry(self,path,*,single_shot_fn,skip_dirty_guard=False,on_ready=None,expected_result_ref=None):
        from PySide6.QtWidgets import QApplication
        page=self.page
        if page.isVisible() and QApplication.platformName()!='offscreen':
            from .studio_readiness import StudioReadiness
            gate=getattr(page,'_readiness',None)
            if gate is None:gate=page._readiness=StudioReadiness(page)
            gate.on_ready=on_ready
            return gate.begin(path,skip_dirty_guard=skip_dirty_guard,expected_result_ref=expected_result_ref)
        result=self.open_project(path,single_shot_fn=single_shot_fn,skip_dirty_guard=skip_dirty_guard,expected_result_ref=expected_result_ref)
        loaded_path = self.session.project_path
        if (on_ready is not None and page.project is not None and page._project_view_state == 'open'
                and loaded_path is not None and Path(loaded_path).resolve() == Path(path).resolve()):
            if expected_result_ref:
                from .recognition_result import verify_result_reference
                verify_result_reference(expected_result_ref, project=page.project, project_path=loaded_path)
            on_ready()
        return result

    def open_project(
        self, path: str | os.PathLike[str], *, single_shot_fn,
        skip_dirty_guard: bool = False,
        expected_result_ref=None,
    ) -> None:
        from .ui_motion import reveal_cue
        page = self.page
        # Contents already settle the visible splitters once. A second full
        # widget-tree pass here used to delay every project transition.
        result = self._open_project_contents(
            path, single_shot_fn=single_shot_fn, skip_dirty_guard=skip_dirty_guard,expected_result_ref=expected_result_ref
        )
        if page.project is not None and page._project_view_state == "open":
            page._studio_trace("UI_READY", upper_sizes=page.upper_splitter.sizes(),
                               workspace_sizes=page.workspace_splitter.sizes())
            reveal_cue(page.studio_toolbar)
        return result

    def _open_project_contents(self, path, *, single_shot_fn, skip_dirty_guard=False,expected_result_ref=None):
        # Synchronous compatibility API for non-visible tools/tests. User
        # navigation consumes these same steps through StudioReadiness.
        for _ in self._open_project_steps(path, single_shot_fn=single_shot_fn,
                                          skip_dirty_guard=skip_dirty_guard,expected_result_ref=expected_result_ref):
            pass

    def _open_project_steps(
        self,
        path: str | os.PathLike[str],
        *,
        single_shot_fn,
        skip_dirty_guard: bool = False,
        loaded_project=None,
        expected_result_ref=None,
    ) -> None:
        page = self.page
        profile_started = perf_counter()
        profile_mark = profile_started
        profile: dict[str, float] = {}
        open_stage = "REQUEST"
        requested_path = Path(path).expanduser()
        previous_view_state = page._project_view_state
        current_path = self.session.project_path
        replacing = self.session.project is not None and (
            current_path is None
            or requested_path.resolve() != Path(current_path).resolve()
        )
        if replacing and not skip_dirty_guard and not self.dirty_guard.confirm("打开其它工程"):
            return
        page._cancel_media_ingest()
        page._studio_trace("OPEN_REQUEST", project_path=str(requested_path))
        page._studio_trace("OPEN_VALIDATE", exists=requested_path.is_file(), readable=os.access(requested_path, os.R_OK))
        if hasattr(page, "_close_export_workspace"):
            page._close_export_workspace()
        page._project_view_state = "loading"
        page._project_opening_path = str(requested_path.resolve())
        project_id = str(requested_path.resolve())
        if hasattr(page, "_studio_startup_begin"):
            page._studio_startup_begin(project_id=project_id)
            page._studio_mark_startup_milestone("PROJECT_LOAD_START", project_path=str(requested_path))
        page._studio_trace("VIEW_TRANSITION", source="hub", target="loading")
        try:
            open_stage = "DESERIALIZE"
            page._studio_trace("PROJECT_LOAD_BEGIN", official_path=str(requested_path))
            with self._studio_operation("project_deserialize", project_id=project_id):
                project = loaded_project if loaded_project is not None else load_project(requested_path)
            if expected_result_ref:
                from .recognition_result import verify_result_reference
                verify_result_reference(expected_result_ref, project=project, project_path=requested_path)
            page._studio_trace("P74C_T0_PROJECT_SELECTED", project_path=str(requested_path.resolve()))
            page._studio_trace("PROJECT_DESERIALIZED", cue_count=len(project.cues), media_path=project.media.path)
            if hasattr(page, "_studio_mark_startup_milestone"):
                page._studio_mark_startup_milestone("MEDIA_METADATA_READY", media_path=str(project.media.path or ""))
            open_stage = "RECOVERY"
            with self._studio_operation(
                "project_recovery",
                project_id=project_id,
                media_path=str(project.media.path or ""),
            ):
                if expected_result_ref:
                    # Recognition completion names an exact committed revision.
                    # Autosave recovery belongs to explicit normal project open.
                    recovered_autosave = False
                else:
                    project, recovered_autosave = page._resolve_project_recovery(requested_path, project)
            if hasattr(page, "_studio_startup_media_path"):
                page._studio_startup_media_path = str(project.media.path or "")
            primary_asset = project.media_pool[0] if project.media_pool else None
            needs_contract_probe = media_available(project, project.media.path) and bool(
                primary_asset is None
                or int(primary_asset.duration_ms or 0) <= 0
                or "has_video" not in primary_asset.video_metadata
                or "has_audio" not in primary_asset.audio_metadata
            )
            if needs_contract_probe:
                # A cold ffprobe can take seconds on long FLV recordings. It
                # is useful metadata, but it is not required to show the first
                # playable frame; defer it until after the workspace is open.
                page._studio_trace(
                    "MEDIA_CONTRACT_PROBE_DEFERRED",
                    project_id=project_id,
                    media_path=str(project.media.path),
                    suffix=Path(str(project.media.path)).suffix.lower(),
                )
            from .studio_edit_sequence import sequence_of
            from .studio_media_pool import media_graph_duration_ms, sync_primary_video_track_from_sequence

            if media_graph_duration_ms(project) <= 0:
                sequence = sequence_of(project)
                if int(sequence.source_duration_ms or 0) > 0 or sequence.segments:
                    sync_primary_video_track_from_sequence(project, sequence)
                    primary_asset = project.media_pool[0] if project.media_pool else primary_asset
            page._studio_trace(
                "P74C_T1_MEDIA_POOL",
                asset_id=primary_asset.asset_id if primary_asset is not None else "",
                source=primary_asset.canonical_source if primary_asset is not None else project.media.path,
                container_suffix=Path(str(project.media.path or "")).suffix.lower(),
                duration_ms=int(primary_asset.duration_ms if primary_asset is not None else project.media.duration_ms),
                clip_out_ms=int(
                    project.video_tracks[0].clips[0].timeline_out_ms
                    if project.video_tracks and project.video_tracks[0].clips
                    else 0
                ),
                has_audio=bool(primary_asset and primary_asset.audio_metadata.get("has_audio", True)),
                contract_probe=needs_contract_probe,
                video_metadata=dict(primary_asset.video_metadata) if primary_asset is not None else {},
                audio_metadata=dict(primary_asset.audio_metadata) if primary_asset is not None else {},
                video_codec=str((primary_asset.video_metadata if primary_asset is not None else {}).get("codec") or ""),
                audio_codec=str((primary_asset.audio_metadata if primary_asset is not None else {}).get("codec") or ""),
                video_stream_index=int((primary_asset.video_metadata if primary_asset is not None else {}).get("stream_index", 0) or 0),
                audio_stream_index=int((primary_asset.audio_metadata if primary_asset is not None else {}).get("stream_index", 0) or 0),
                sample_rate=int((primary_asset.audio_metadata if primary_asset is not None else {}).get("sample_rate", 0) or 0),
                channels=int((primary_asset.audio_metadata if primary_asset is not None else {}).get("channels", 0) or 0),
                video_timebase=str((primary_asset.video_metadata if primary_asset is not None else {}).get("timebase") or ""),
                audio_timebase=str((primary_asset.audio_metadata if primary_asset is not None else {}).get("timebase") or ""),
            )
        except Exception as exc:
            page._project_view_state = previous_view_state if self.session.project is not None else "hub"
            page._project_opening_path = ""
            page._set_hub_toolbar_mode(self.session.project is None)
            page.studio_empty.setEnabled(True)
            page.hub_loading_label.hide()
            page._studio_trace("OPEN_FAILED", stage=open_stage, exception_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
            studio_message_box(page, QMessageBox.Icon.Critical, tr('无法打开项目'), str(exc))
            return
        profile["工程反序列化"] = perf_counter() - profile_mark
        profile_mark = perf_counter()
        yield '建立时间轴'
        if self.session.project is not None:
            page._close_project_session("project_switch")
        # Never carry a generated ASS across project boundaries.
        stale_preview = page._preview_path
        page._preview_path = None
        page._ass_generation += 1
        page._pending_motion_replay_cue_id = ""
        page._overlay_cue_id = ""
        # Read-only migration of older projects: keep all raw MOSS labels in
        # the next explicit save/autosave, even if Stage 5 excluded them.
        if not project.generation_metadata.get("speaker_recovery") and project.report_path:
            from .speaker_recovery import load_candidate_snapshot
            try:
                project.generation_metadata["speaker_recovery"] = load_candidate_snapshot(project)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                project.generation_metadata["speaker_recovery_error"] = str(exc)
        # Freeze legacy visible captions before models, cue lookups and render
        # revisions capture them. A later timeline hydration is too late.
        from .studio_caption_timeline import ensure_independent_captions
        ensure_independent_captions(project)
        from .caption_source_receipts import recover_caption_sources
        recover_caption_sources(project)
        from .studio_caption_timeline import recover_caption_words
        recovered_words = recover_caption_words(project)
        if recovered_words:
            page._studio_trace("CAPTION_WORDS_RECOVERED", count=recovered_words)
        page.project = project
        page._manual_selection_hold = False
        visibility = project.studio_state.get("subtitle_track_visibility", {})
        page._subtitle_track_visibility = {
            str(key): bool(value)
            for key, value in visibility.items()
            if str(key).strip()
        } if isinstance(visibility, dict) else {}
        if hasattr(page, "timeline"):
            page.timeline.hidden_speakers = {
                speaker_id for speaker_id, visible in page._subtitle_track_visibility.items()
                if not visible
            }
        hydration_started = perf_counter()
        hydration_mark = hydration_started
        hydration_phases: dict[str, float] = {}

        def mark_hydration(phase: str) -> None:
            nonlocal hydration_mark
            now = perf_counter()
            hydration_phases[phase] = round((now - hydration_mark) * 1000.0, 3)
            hydration_mark = now

        page._studio_trace("PROJECT_ASSIGN", project_path=str(requested_path), cue_count=len(project.cues))
        self.session.project_path = requested_path.resolve()
        self.session._cue_lookup = {cue.id: cue for cue in project.cues}
        page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
        page._project_view_state = "open"
        page._studio_trace("VIEW_TRANSITION", source="loading", target="open")
        page._project_opening_path = ""
        page._set_hub_toolbar_mode(False)
        page.studio_empty.setEnabled(True)
        page.hub_loading_label.hide()
        page.studio_empty.hide()
        play_res_x = max(1, int(project.render_settings.get("play_res_x", 1920)))
        play_res_y = max(1, int(project.render_settings.get("play_res_y", 1080)))
        page.position_overlay.set_video_size(
            project.media.width,
            project.media.height,
        )
        mark_hydration("project_assignment")
        page._remember_recent_project(self.session.project_path)
        owner = page.window().parentWidget() if page.window() is not None else None
        if owner is not None and hasattr(owner, "_refresh_studio_entry_card"):
            owner._refresh_studio_entry_card()
        self.session.undo_stack.clear()
        self.session.undo_stack.setClean()
        page._recovered_autosave_pending = recovered_autosave
        user_text(page.filename).setText(display_project_name(path=self.session.project_path, project=project))
        _language = current_language()
        (bind_text(page.save_state, translate('已恢复自动保存（尚未保存）', _language)) if recovered_autosave else bind_text(page.save_state, translate('已保存', _language)))
        mark_hydration("recent_undo_state")
        with self._studio_operation(
            "timeline_model_hydration",
            project_id=project_id,
            media_path=str(project.media.path or ""),
        ):
            page.cue_model.set_project(project)
            page.timeline.set_project(project)
        if hasattr(page, "media_pool_panel"):
            page.media_pool_panel.refresh(project)
        # Project open may consume an existing disk thumbnail, but it must not
        # launch FFmpeg merely because the timeline paints for the first time.
        page.timeline.thumbnail_requests_enabled = False
        if hasattr(page, 'filmstrip_toggle'):
            page.filmstrip_toggle.blockSignals(True)
            page.filmstrip_toggle.setChecked(page.timeline.filmstrip_visible)
            page.filmstrip_toggle.blockSignals(False)
        with self._studio_operation(
            "subtitle_list_population",
            project_id=project_id,
            media_path=str(project.media.path or ""),
        ):
            page._populate_speakers()
            page._qc_terminology = terminology_from_project(project)
        page._pending_qc_cue_ids.clear()
        page._qc_full_scan_pending = False
        mark_hydration("models_timeline_speakers")
        yield '恢复工作区'
        studio_state = project.studio_state if page._studio_preferences().get("restore_layout", True) is not False else {}
        # Opening a project only reflects its saved display; no undo entry.
        from .studio_bilingual import sync_controls
        from .bilingual_layout import settings_from_state
        sync_controls(page, settings_from_state(project.studio_state))
        from .studio_punctuation import sync_controls as sync_punctuation
        sync_punctuation(page)
        page.continuous_review_toggle.blockSignals(True)
        page.continuous_review_toggle.setChecked(bool(studio_state.get("continuous_review", False)))
        page.continuous_review_toggle.blockSignals(False)
        page.follow_playhead_toggle.setChecked(bool(studio_state.get("follow_playhead", True)))
        page.snap_toggle.setChecked(bool(studio_state.get("timeline_snap_enabled", True)))
        page._set_timeline_tool(str(studio_state.get("timeline_tool", "selection")))
        saved_track_heights = studio_state.get("timeline_track_heights")
        if isinstance(saved_track_heights, dict):
            # 2026-09-18 VIII：恢复三类轨高（空值=回落默认档位/常量）。
            page.timeline.set_track_heights({
                str(kind): int(value)
                for kind, value in saved_track_heights.items()
                if kind in ("video", "audio", "subtitle") and value
            })
        layout_state = studio_state.get("layout", {})
        restored_workspace_sizes = False
        if isinstance(layout_state, dict):
            upper_sizes = layout_state.get("upper_sizes")
            workspace_sizes = layout_state.get("workspace_sizes")
            center_sizes = layout_state.get("center_sizes")
            if isinstance(upper_sizes, list) and len(upper_sizes) == 3:
                page.upper_splitter.setSizes([max(0, int(value)) for value in upper_sizes])
            if isinstance(workspace_sizes, list) and len(workspace_sizes) == 2:
                page.workspace_splitter.setSizes([max(0, int(value)) for value in workspace_sizes])
                restored_workspace_sizes = True
            if isinstance(center_sizes, list) and len(center_sizes) == 2:
                page.center_splitter.setSizes([max(0, int(value)) for value in center_sizes])
            from .studio_context_tabs import restored_context_tab
            page._last_context_tab = restored_context_tab(layout_state)
            page.context_drawer.setCurrentIndex(page._last_context_tab)
            if bool(layout_state.get("context_collapsed", False)):
                page._collapse_context_panel()
            else:
                page._show_context_panel()
            page._set_major_panel_visible(
                "cue_list", bool(layout_state.get("cue_list_visible", True))
            )
            # Compatibility: deprecated editor_visible state is deliberately ignored.
            page._set_major_panel_visible(
                "context",
                bool(
                    layout_state.get(
                        "context_visible",
                        not bool(layout_state.get("context_collapsed", False)),
                    )
                ),
            )
            editor_fields = layout_state.get("editor_fields", {})
            if isinstance(editor_fields, dict):
                for field in page._editor_field_visibility:
                    page._set_editor_field_visible(
                        field,
                        bool(editor_fields.get(field, page._editor_field_visibility[field])),
                    )
        # QSplitter defers hide/show geometry. Commit visibility first, then
        # restore ratios against the final available rectangle before media IO.
        from .ui_motion import settle_layout
        page._show_teach_hint("studio")
        settle_layout(page)
        if isinstance(layout_state, dict):
            for splitter, key, count in ((page.upper_splitter, 'upper_sizes', 3),
                                         (page.workspace_splitter, 'workspace_sizes', 2),
                                         (page.center_splitter, 'center_sizes', 2)):
                sizes = layout_state.get(key)
                if isinstance(sizes, list) and len(sizes) == count:
                    splitter.setSizes([max(0, int(value)) for value in sizes])
                    splitter.refresh()
        if not restored_workspace_sizes:
            page._apply_default_workspace_layout()
        mark_hydration("layout_restore")
        # 2026-09-19 进工程提速轮：布局恢复是单块最大的主线程阶段（实测 ~700ms），
        # 在其后插入 yield 让就绪门有机会重绘进度/阶段，避免"只剩一个不动的转圈"。
        yield '恢复界面布局'
        yield '准备字幕'
        saved_cue_id = str(studio_state.get("last_selected_cue") or "")
        from .studio_edit_sequence import projected_cues
        view_cues = projected_cues(project)
        valid_cue_ids = {cue.id for cue in view_cues}
        page.select_cue(
            saved_cue_id
            if saved_cue_id in valid_cue_ids
                else (view_cues[0].id if view_cues else "")
        )
        mark_hydration("cue_selection")
        # 选中/可见窗/播放头恢复是第二大的单块主线程阶段（实测 ~450ms），同样切块。
        yield '恢复播放位置'
        from .studio_edit_sequence import timeline_duration_ms
        duration = timeline_duration_ms(project)
        saved_zoom = studio_state.get("zoom")
        if saved_zoom is None:
            visible_duration = min(60_000, max(1000, duration))
        else:
            try:
                zoom = max(1.0, float(saved_zoom))
            except (TypeError, ValueError):
                zoom = 1.0
            # Legacy zoom=1 must not turn a multi-hour project into a
            # 10,000-cue paint operation on every selection.
            visible_duration = min(
                300_000,
                max(1000, round(duration / zoom)),
                max(1000, duration),
            )
        maximum_scroll = max(0, duration - visible_duration)
        page.timeline.set_visible_window(
            min(maximum_scroll, max(0, int(studio_state.get("scroll_ms", 0) or 0))),
            visible_duration,
        )
        playhead_ms = min(
            duration, max(0, int(studio_state.get("playhead_ms", 0) or 0))
        )
        active_v1 = next(
            (
                clip
                for track in project.video_tracks
                if track.id == "V1" and track.enabled
                for clip in track.clips
                if clip.enabled and clip.timeline_in_ms <= playhead_ms < clip.timeline_out_ms
            ),
            None,
        )
        page._studio_trace(
            "P74C_T2_ACTIVE_V1",
            playhead_ms=playhead_ms,
            clip_id=active_v1.id if active_v1 is not None else "",
            source_out_ms=int(active_v1.source_out_ms if active_v1 is not None else 0),
        )
        page.timeline.set_playhead(playhead_ms)
        mark_hydration("timeline_window")
        if project.generation_metadata.get('display_overlap_audit',{}).get('status') != 'user_undone':
            from .display_timing import project_display_tail_plan
            ends,audit=project_display_tail_plan(project)
            page._pending_display_handoffs_preview = {"project_id": project.project_id, "ends": ends, "audit": audit}
            if ends:
                bind_text(page.save_state, '发现{value0}条可预览的显示边界修复，确认后应用；原始工程保持。', property='toolTip', value0=len(ends))
        missing_fonts = missing_project_fonts(project)
        if missing_fonts:
            message = "缺失字体: " + "、".join(missing_fonts)
            page.save_state.setText(message)
            bind_text(page.save_state, '压制前请安装字体或在样式中选择已安装字体。', property='toolTip')
        if hasattr(page, "_set_subtitle_editor_visible"):
            page._set_subtitle_editor_visible(False)
        page._studio_trace("WORKSPACE_READY", project_path=str(self.session.project_path), cue_count=len(project.cues))
        if hasattr(page, "_studio_mark_startup_milestone"):
            page._studio_mark_startup_milestone("TIMELINE_INTERACTIVE")
        mark_hydration("timeline_interactive")
        yield '准备播放器'
        page._studio_trace(
            "PROJECT_UI_HYDRATION",
            project_path=str(self.session.project_path),
            cue_count=len(project.cues),
            total_ms=round((perf_counter() - hydration_started) * 1000.0, 3),
            phases_ms=hydration_phases,
        )
        profile["界面与时间轴构建"] = perf_counter() - profile_mark
        profile_mark = perf_counter()
        page._initial_preview_timer.stop()
        profile["ASS 后台调度"] = perf_counter() - profile_mark
        profile_mark = perf_counter()
        untitled = not str(project.media.path or "").strip()
        media_exists = media_available(project, project.media.path)
        page.relink_button.setVisible(not media_exists and not untitled)
        playable_source = project.media.path if media_exists else next(
            (asset.canonical_source for asset in project.media_pool if not asset.offline), '')
        if playable_source:
            page._set_media_ingest_state("READY")
            page._studio_trace("MEDIA_LOAD", media_path=project.media.path)
            page._studio_trace("P74C_T3_MPV_LOAD_REQUEST", media_path=project.media.path)
            open_stage = "MEDIA_LOAD"
            try:
                with self._studio_operation(
                    "mpv_loadfile",
                    project_id=project_id,
                    media_path=str(project.media.path),
                ):
                    page._studio_mark_startup_milestone("MPV_LOADFILE_SENT", media_path=str(project.media.path))
                    # Establish the new project's primary source clock BEFORE
                    # load() publishes its initial position. A previous V2
                    # mapping would interpret a deep source offset as project
                    # time and jump beyond the new project's end.
                    page._refresh_edit_playback_state()
                    page.video.set_project_time_mapping(enabled=False)
                    restore_seconds = None
                    if playhead_ms >= 0:
                        # The saved playhead is TIMELINE time. A trimmed
                        # (mapped) sequence must restore mpv at the mapped
                        # SOURCE position, or the opening frame shows the
                        # deleted head.
                        from .studio_edit_sequence import sequence_of
                        from .studio_sequence_mapper import restore_source_seconds

                        restore_seconds = restore_source_seconds(
                            sequence_of(project), playhead_ms
                        )
                    # Restore the actual clip instance and the same content-clock
                    # artifact used by the compositor/audio/task renderer. Opening
                    # the original FLV first seeks in its discontinuous PTS domain
                    # and can time out before the deferred proxy rebind is allowed.
                    target_resolver = getattr(page, "_multitrack_preview_target", None)
                    target = target_resolver(playhead_ms) if callable(target_resolver) else None
                    if target:
                        playable_source = str(target["source_path"])
                        restore_seconds = int(target["source_ms"]) / 1000.0
                    elif hasattr(page, "_preview_media_path"):
                        playable_source = page._preview_media_path(playable_source)
                    page._studio_trace(
                        "MEDIA_RESTORE_SEEK",
                        playhead_ms=playhead_ms,
                        restore_seconds=restore_seconds,
                        sequence=sequence_of(project).id if hasattr(sequence_of(project), "id") else "",
                        media_path=str(playable_source),
                    )
                    page._loading_project_media = True
                    try:
                        page.video.load(playable_source, "", start_seconds=restore_seconds)
                    finally:
                        page._loading_project_media = False
                page._studio_mark_startup_milestone("MPV_FILE_LOADED", media_path=str(getattr(page.video, "_media_path", "") or project.media.path))
                page._studio_trace("P74C_T4_MPV_PATH", media_path=str(getattr(page.video, "_media_path", "") or project.media.path))
                page._preview_timer.start(0)
                if hasattr(page, "_reload_edit_playback"):
                    with self._studio_operation(
                        "post_open_reload_edit_playback",
                        project_id=project_id,
                        media_path=str(project.media.path or ""),
                    ):
                        page._reload_edit_playback()
                # Bind the actual project media graph immediately.  This is
                # especially important for audio-only projects: without the
                # first target resolution MpvCanvas keeps its video startup
                # gate and the timeline never adopts mpv's audio time-pos.
                if hasattr(page, "_sync_multitrack_preview_at"):
                    with self._studio_operation(
                        "post_open_multitrack_sync",
                        project_id=project_id,
                        media_path=str(project.media.path or ""),
                    ):
                        page._sync_multitrack_preview_at(playhead_ms)
            except Exception as exc:
                page.relink_button.setVisible(True)
                bind_text(page.save_state, translate('媒体加载失败 · 工程仍已打开', current_language()))
                page._studio_trace("MEDIA_LOAD_FAILED", stage=open_stage, exception_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
            profile["mpv 初始化与媒体解析"] = perf_counter() - profile_mark
            profile_mark = perf_counter()
            open_stage = "WAVEFORM"
            try:
                with self._studio_operation(
                    "waveform_scheduling",
                    project_id=project_id,
                    media_path=str(project.media.path),
                    blocking_ui_thread=True,
                ):
                    page._studio_mark_startup_milestone("WAVEFORM_REQUESTED", media_path=str(project.media.path))
                    page._generate_project_waveforms()
            except Exception as exc:
                page._studio_trace("OPEN_FAILED", stage=open_stage, exception_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
            profile["波形缓存调度"] = perf_counter() - profile_mark
        else:
            page._set_media_ingest_state("EMPTY")
            if untitled:
                bind_text(page.save_state, translate('空白工程 · 拖入视频或音频', current_language()))
                bind_text(page.save_state, '把媒体拖到预览区即可开始剪辑。', property='toolTip')
            else:
                _offline_language = current_language()
                (bind_text(page.save_state, translate('素材离线 · 自动保存已恢复', _offline_language)) if recovered_autosave else bind_text(page.save_state, translate('素材离线', _offline_language)))
                bind_text(page.save_state, translate('使用链条按钮重新定位源媒体，工程字幕仍可编辑。', _offline_language), property='toolTip')
            page._preview_timer.start(0)
            if not untitled:
                page._set_media_ingest_state("READY")
                page._sync_multitrack_preview_at(playhead_ms)
        if hasattr(page, "_sync_video_empty_state"):
            page._sync_video_empty_state()
        if hasattr(page, 'media_availability'):
            page.media_availability.refresh()
        if hasattr(page, "highlight_panel"):
            # Bind the clip assistant to THIS project now, then find/validate
            # the same-name XML beside the original source in the background.
            page._schedule_danmaku_discovery()
        if stale_preview:
            single_shot_fn(1_000, lambda stale=stale_preview: stale.unlink(missing_ok=True))
        profile["窗口打开总计"] = perf_counter() - profile_started
        page.last_open_profile = profile
        page._studio_trace("OPEN_FINISHED", project_path=str(self.session.project_path), cue_count=len(project.cues), media_exists=media_exists)
        # A successful open settles any pending recognition reload; failures
        # keep it so the next Studio entry retries automatically.
        page._pending_recognition_reload = ""
        if needs_contract_probe and media_exists and hasattr(page, "_schedule_project_media_probe"):
            page._schedule_project_media_probe(project, project_id)
        def deferred_open_analysis() -> None:
            if page.project is not project or page._project_view_state != "open":
                return
            media_value = str(project.media.path or "")
            with self._studio_operation(
                "review_model_build",
                project_id=project_id,
                media_path=media_value,
                blocking_ui_thread=True,
            ):
                page._refresh_review_risks()
            with self._studio_operation(
                "cue_summary_build",
                project_id=project_id,
                media_path=media_value,
                blocking_ui_thread=True,
            ):
                page._refresh_cue_list_summary()
            page._studio_trace("STUDIO_BACKGROUND_ANALYSIS_READY", project_id=project_id)
        # Let the first playable state reach the event loop before full QC and
        # counters run. Review filters still invoke the same analysis eagerly.
        # Run first-screen summaries before readiness is released. This used
        # to be an untracked zero-timer AFTER UI_READY, blocking first play.
        yield '建立首屏索引'
        deferred_open_analysis()

        def _rearm_timeline_thumbnails() -> None:
            # 2026-09-18 III：打开路径在首绘前禁用了缩略图请求（防 ffmpeg
            # 风暴），但此前没有任何恢复点——整个会话轨道缩略图零请求（用户
            # "FLV 视频轨道没有预览缩略图"，全天日志 0 缩略图事件）。首屏
            # 已绘制定格，此处恢复请求并重绘一次让可见段开始生成。
            timeline = getattr(page, "timeline", None)
            if timeline is not None and page.project is not None:
                timeline.thumbnail_requests_enabled = True
                timeline.update()

        single_shot_fn(0, _rearm_timeline_thumbnails)
        # Project cover generation belongs to media ingest/project library,
        # never the Studio open path.
        single_shot_fn(
            0,
            lambda: page.ensure_active_subtitle_renderer(reason="project_open"),
        )

    def _recovery_choice(self, candidate: Path) -> str:
        box = QMessageBox(self.page)
        box.setIcon(QMessageBox.Icon.Warning)
        bind_text(box, '发现未保存的自动恢复版本', property='windowTitle')
        bind_text(box, '自动恢复包含正式保存之后的实际修改。')
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            project_path_value = payload.get("autosave", {}).get("project_path", "")
            project_path = Path(str(project_path_value)) if project_path_value else None
            saved_time = datetime.fromtimestamp(project_path.stat().st_mtime).strftime("%H:%M") if project_path else "--:--"
            recovery_time = datetime.fromtimestamp(candidate.stat().st_mtime).strftime("%H:%M")
            bind_text(box, '正式保存  {value0}\n自动恢复  {value1}\n\n请选择要打开的版本。', property='informativeText', value0=saved_time, value1=recovery_time)
        except OSError:
            bind_text(box, '请选择恢复自动保存、打开正式保存，或删除恢复点。', property='informativeText')
        restore = box.addButton("恢复自动保存", QMessageBox.ButtonRole.AcceptRole)
        saved = box.addButton("打开正式保存", QMessageBox.ButtonRole.ActionRole)
        ignore = box.addButton("删除恢复点", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(restore)
        apply_secondary_surface_theme(box)
        box.exec()
        clicked = box.clickedButton()
        if clicked is restore:
            return "recover"
        if clicked is ignore:
            return "ignore"
        return "saved" if clicked is saved else "saved"

    def _resolve_project_recovery(
        self, project_path: Path, official: SubtitleProject, *, single_shot_fn
    ) -> tuple[SubtitleProject, bool]:
        page = self.page
        candidate = recoverable_autosave(project_path, official=official)
        page._studio_trace(
            "RECOVERY",
            official_path=str(project_path),
            autosave_path=str(candidate) if candidate else "",
            decision="none" if candidate is None else "inspect",
        )
        if candidate is None:
            return official, False
        # 快路径：新鲜指纹边车与官方内容一致 → 无需解析候选即可断定
        # "自动保存不比正式新"（重复进入实测省 438-710ms/次）。
        from .studio_project import autosave_fingerprint_sidecar, project_content_fingerprint
        sidecar = autosave_fingerprint_sidecar(candidate)
        if sidecar and str(sidecar.get("content_fingerprint") or "") == project_content_fingerprint(official):
            page._studio_trace(
                "RECOVERY",
                official_path=str(project_path),
                autosave_path=str(candidate),
                chosen_path=str(project_path),
                decision="official_unchanged_fast",
            )
            return official, False
        try:
            if project_content_fingerprint(load_project(candidate)) == project_content_fingerprint(official):
                page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(project_path), decision="official_unchanged")
                return official, False
        except (OSError, ProjectValidationError):
            page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(project_path), decision="official_invalid_autosave")
            return official, False
        policy = str(page._studio_preferences().get("recovery_policy", "ask"))
        if policy == "auto":
            recovered = load_project(candidate)
            page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(candidate), decision="auto_recover")
            single_shot_fn(100, lambda: QToolTip.showText(QCursor.pos(), "已自动恢复较新的自动保存版本", page))
            return recovered, True
        if policy == "official":
            page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(project_path), decision="policy_official")
            single_shot_fn(100, lambda: QToolTip.showText(QCursor.pos(), "已按偏好打开正式保存版本", page))
            return official, False
        choice = page._recovery_choice(candidate)
        if choice == "recover":
            page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(candidate), decision="recover")
            return load_project(candidate), True
        if choice == "ignore":
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        page._studio_trace("RECOVERY", official_path=str(project_path), autosave_path=str(candidate), chosen_path=str(project_path), decision="official")
        return official, False

    def _populate_speakers(self) -> None:
        page = self.page
        project = self.session.project
        pending = bool(project and project.generation_metadata.get("speaker_recovery", {}).get("needs_confirmation"))
        unapplied = bool(getattr(page, "_speaker_roles_pending", False))
        if hasattr(page, "speaker_manager_button"):
            (bind_text(page.speaker_manager_button, '说话人管理 · 待应用') if unapplied else (bind_text(page.speaker_manager_button, '说话人管理 · 待确认') if pending else bind_text(page.speaker_manager_button, '说话人管理')))
            (bind_text(page.speaker_manager_button, '检测到多个持续说话人，需要确认。打开全部 MOSS 标签试听并恢复轨道。', property='toolTip') if pending else bind_text(page.speaker_manager_button, '说话人管理与 MOSS 缓存恢复', property='toolTip'))
        page.speaker.blockSignals(True)
        page.speaker.clear()
        if project:
            values = list(dict.fromkeys(
                [speaker.id for speaker in project.speakers]
                + [cue.speaker_id for cue in project.cues]
            ))
            for speaker_id in values or ["S00"]:
                name = next(
                    (
                        speaker.name or speaker.id
                        for speaker in project.speakers
                        if speaker.id == speaker_id
                    ),
                    speaker_id,
                )
                page.speaker.addItem(name, speaker_id)
        page.speaker.blockSignals(False)

    def save(self, *, save_project_fn=save_project, message_box_fn=studio_message_box) -> None:
        page = self.page
        project = self.session.project
        if not project:
            return
        page._capture_studio_state()
        if self.session.project_path is None:
            path, _selected = QFileDialog.getSaveFileName(
                page, tr('保存 Subtitle Project'), "", "2ByteASR Project (*.2byteproj)"
            )
            if not path:
                return
            self.session.project_path = Path(path)
        page._autosave_timer.stop()
        try:
            page._wait_for_autosave_worker()
            self.session.project_path = save_project_fn(project, self.session.project_path)
            self.session.undo_stack.setClean()
            page._recovered_autosave_pending = False
            page._autosave_deadline.mark_succeeded()
            bind_text(page.save_state, '已保存')
        except Exception as exc:
            page._schedule_autosave()
            message_box_fn(page, QMessageBox.Icon.Critical, "保存失败", str(exc))
