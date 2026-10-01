"""Project open/navigation flow for Subtitle Studio."""

from __future__ import annotations
from .i18n import bind_text, tr, current_language

import os
from pathlib import Path
from PySide6.QtCore import (QTimer)
from .audio_playback_graph import AudioPlaybackGraph
from .studio_helpers import probe_media_identity
from .studio_project import (PROJECT_SUFFIX, SubtitleProject, studio_settings_path)
from .studio_theme import (STUDIO_MEDIA_SUFFIXES, studio_message_box)

class StudioProjectFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def open_project_dialog(self) -> None:
        return self.project_controller.open_project_dialog()

    def most_recent_project(self) -> str:
        return self.project_controller.most_recent_project(settings_path_fn=studio_settings_path)

    def recent_project_records(self) -> list[dict[str, object]]:
        return self.project_controller.recent_project_records(settings_path_fn=studio_settings_path)

    def _remember_recent_project(self, path: Path) -> None:
        return self.project_controller._remember_recent_project(path, settings_path_fn=studio_settings_path)

    def _ensure_project_cover(self, project_path: Path, project: SubtitleProject) -> Path | None:
        return self.project_controller._ensure_project_cover(project_path, project)

    def _relink_media(self) -> None:
        return self.project_controller._relink_media(
            probe_media_identity_fn=probe_media_identity, message_box_fn=studio_message_box
        )

    def _confirm_leave_project(self, message: str) -> bool:
        return self.project_controller.dirty_guard.confirm(message.rstrip("？?"))

    def _request_back(self) -> None:
        export = getattr(self, "export_workspace", None)
        if export is not None and export.isVisible():
            self._close_export_workspace()
            return
        if self.project is not None and getattr(self, "_project_view_state", "") == "open":
            self._request_return_library()
            return
        self._request_return_home()

    def _request_return_library(self) -> None:
        if not self._confirm_leave_project("返回工程库前是否保存当前兔白字幕修改？"):
            return
        self.show_project_hub(skip_dirty_guard=True)

    def _request_return_home(self) -> None:
        if not self._confirm_leave_project("返回字幕识别前是否保存当前兔白字幕修改？"):
            return
        self._close_export_workspace()
        self.show_project_hub(skip_dirty_guard=True)
        self.return_requested.emit()

    def _close_project_session(self, reason: str = "") -> int:
        """Unified A→Home/B boundary; services persist, project work does not."""
        from time import perf_counter

        from .runtime_trace import GLOBAL_STUDIO_TRACE

        close_t0 = perf_counter()
        previous_path = str(self.project_path or "")
        if getattr(self, '_canvas_editor', None) is not None:
            self._cancel_canvas_inline_edit()
        self._review_edit_lock = None
        self._qc_scan_token = getattr(self, '_qc_scan_token', 0) + 1
        scan = getattr(self, '_qc_scan_timer', None)
        if scan is not None:
            scan.stop()
        from .studio_analysis_request import cancel_analysis
        cancel_analysis(self)
        self._composition_keep_resynced = False
        self._cancel_media_ingest()
        self._resource_governor.set_dragging(False)
        self._resource_governor.set_playback(False)
        ai_cancel = getattr(self, "_ai_cancel_event", None)
        if ai_cancel is not None:
            ai_cancel.set()
        self._ai_request_generation += 1
        self._ai_provider_probe_generation += 1
        self._ai_variant_preview_generation += 1
        self._advanced_preview_generation += 1
        self._ass_generation += 1
        self._autosave_generation += 1
        # Closing a project revokes all pixel producers, including the ones
        # that bypass QWidget visibility and the GUI overlay registry.
        scene = getattr(self, "_caption_scene", None)
        if scene is not None:
            scene.close()
            self._caption_scene = None
        cache = getattr(self, "_caption_playback_cache", None)
        if cache is not None:
            cache.close()
            self._caption_playback_cache = None
        self._revoke_advanced_preview(reason="project_close")
        actor = getattr(self, "_ass_actor", None)
        if actor is not None:
            actor.invalidate_cache()
        for timer_name in (
            "_initial_preview_timer", "_preview_timer", "_edit_preview_timer",
            "_transform_preview_timer", "_advanced_preview_timer",
            "_advanced_preview_publish_timer", "_advanced_seek_timer",
            "_autosave_timer", "_visual_update_timer", "_recognition_runtime_timer",
            "_reverse_timer", "_style_debounce_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        for timer in tuple(getattr(self, "_ai_variant_motion_timers", {}).values()):
            timer.stop()
        self._ai_variant_motion_timers.clear()
        self._advanced_prefetch_queue.clear()
        self._advanced_prefetch_running = False
        self._pending_suggestion = None
        self._ai_request_active = False
        self._ai_cancel_event = None
        self._loop_enabled = False
        self._loop_region_ms = None
        self._audio_playback_graph = AudioPlaybackGraph()
        self._audio_playback_decision = self._audio_playback_graph.last_decision
        t_timers = perf_counter()
        if hasattr(self, "video_compositor"):
            # 关闭链分段计时：返回主页楔死类问题（2026-09-07 用户实录）从
            # trace 直接看到卡在哪一段，不再靠复现猜。
            players = len(getattr(self.video_compositor, "_players", {}) or {})
            self.video_compositor.clear()
            self.video_compositor.suspend()
            GLOBAL_STUDIO_TRACE.emit(
                "PROJECT_CLOSE_STEP",
                {
                    "step": "compositor_clear",
                    "players": players,
                    "duration_ms": round((perf_counter() - t_timers) * 1000, 1),
                },
            )
        t_compositor = perf_counter()
        if hasattr(self, "video"):
            self.video.unload_project_media()
            GLOBAL_STUDIO_TRACE.emit(
                "PROJECT_CLOSE_STEP",
                {
                    "step": "video_unload",
                    "duration_ms": round((perf_counter() - t_compositor) * 1000, 1),
                },
            )
        # 四十三轮：Qt 侧高级字幕画布也要清——只卸 mpv overlay 的话，画布
        # QLabel 里旧工程的最后一帧像素会浮在新工程视频上方（用户实录
        # "上一个工程的字幕卡在上面但字幕没显示"）。
        advanced = getattr(self, "advanced_cue_overlay", None)
        if advanced is not None:
            try:
                advanced.hide()
                advanced.clear()
            except RuntimeError:
                pass
        self._preview_path = None
        self.project = None
        # Unload can emit synchronous callbacks while the old project is still
        # assigned. Fence LIVE jobs after those callbacks too.
        self._advanced_live_render_generation = getattr(self, "_advanced_live_render_generation", 0) + 1
        self._advanced_live_inflight_key = ""
        # Video unload emits advisory playback-state changes. Fence audio only
        # after those callbacks and after project ownership is cleared, so no
        # late old-project synchronize call can overwrite the SILENT request.
        if hasattr(self, "audio_engine"):
            self.audio_engine.unload()
        # 2026-09-06：mix_all 混音池（第 2+ 叠加层音频引擎）随工程一起关停。
        if hasattr(self, "_silence_mix_audio_engines"):
            self._silence_mix_audio_engines()
        generation = self.session.close(reason)
        GLOBAL_STUDIO_TRACE.emit(
            "PROJECT_CLOSE_STEP",
            {
                "step": "done",
                "reason": str(reason or ""),
                "duration_ms": round((perf_counter() - close_t0) * 1000, 1),
            },
        )
        self._studio_trace(
            "PROJECT_SESSION_CLOSED",
            reason=str(reason or ""),
            project_path=previous_path,
            session_generation=generation,
            audio_generation=(
                int(self.audio_engine.telemetry_snapshot().get("session_generation") or 0)
                if hasattr(self, "audio_engine") else 0
            ),
        )
        return generation

    def _sync_navigation_chrome(self) -> None:
        hub = getattr(self, "_project_view_state", "hub") == "hub" or self.project is None
        export = getattr(self, "export_workspace", None)
        export_open = export is not None and export.isVisible()
        if hasattr(self, "studio_back_button"):
            if export_open:
                self.studio_back_button.setVisible(True)
                bind_text(self.studio_back_button, "返回兔白字幕", property="toolTip")
            elif hub:
                self.studio_back_button.setVisible(False)
            else:
                self.studio_back_button.setVisible(True)
                bind_text(self.studio_back_button, "返回工程库", property="toolTip")
        if hasattr(self, "studio_home_button"):
            bind_text(self.studio_home_button, "返回字幕识别", property="toolTip")
        if hasattr(self, "studio_library_button"):
            bind_text(self.studio_library_button, "兔白字幕工程库", property="toolTip")
            self.studio_library_button.setChecked(
                bool(hub and not export_open)
            ) if hasattr(self.studio_library_button, "setChecked") else None
        # 2026-09-06（用户四图反馈·图一）：双语/剪辑助手只在工程打开后的编辑态显示，
        # 主页（hub）右上角不再出现这两个按钮。双语按钮若已被收进 overflow 菜单
        # （_studio_toolbar_overflow_widgets，常驻隐藏），此处不得把它重新显示回工具栏。
        editing = bool(not hub and not export_open)
        overflow = set(
            id(widget) for widget in getattr(self, "_studio_toolbar_overflow_widgets", ())
        )
        if hasattr(self, "studio_clip_assistant_button"):
            self.studio_clip_assistant_button.setVisible(editing and id(self.studio_clip_assistant_button) not in overflow)
        toggle = getattr(self, "bilingual_toggle_button", None)
        if toggle is not None and id(toggle) not in overflow:
            toggle.setVisible(editing)
        for button in getattr(self, "_studio_compact_commands", ()):
            button.setVisible(editing and self.width() >= (1800 if current_language() != "zh" else 1480))

    def dragEnterEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if any(path.suffix.lower() in STUDIO_MEDIA_SUFFIXES | {PROJECT_SUFFIX, ".srt", ".ass"} for path in paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        projects = [path for path in paths if path.suffix.lower() == PROJECT_SUFFIX]
        media = [path for path in paths if path.suffix.lower() in STUDIO_MEDIA_SUFFIXES]
        subtitles = [path for path in paths if path.suffix.lower() in {".srt", ".ass"}]
        if projects:
            self.open_project(projects[0])
        elif media:
            if self.project is not None:
                if self._timeline_is_blank_for_first_media():
                    # 空工程的第一次主媒体：无论拖到窗口哪里都从 0 开始（用户
                    # 只是"把文件丢进来"，落点 x 换算成 4.4s/8.6s 起点是误伤，
                    # 2026-09-20 未命名工程17 实录 REBIND project_ms=4457）。
                    self._begin_media_drop(media, 0)
                else:
                    point = self.timeline.mapFrom(self, event.position().toPoint())
                    inside = self.timeline.rect().contains(point) and point.x() >= self.timeline.TRACK_HEADER_WIDTH
                    position = self.timeline._x_to_time(point.x()) if inside else self.timeline.playhead_ms
                    track = self.timeline._video_track_at(point) if inside else ""
                    self._begin_media_drop(media, max(0, position), track or "")
            else:
                self.project_controller.create_blank_project(on_ready=lambda: self._begin_media_drop(media, 0))
        if subtitles:
            self._import_subtitle_file(subtitles[0])
        event.acceptProposedAction()

    def _timeline_is_blank_for_first_media(self) -> bool:
        """True 当工程还没有任何媒体池资产与视频片段（首条主媒体判定）。"""
        project = self.project
        if project is None:
            return False
        return not getattr(project, "media_pool", None) and not any(
            getattr(track, "clips", None) for track in getattr(project, "video_tracks", ())
        )

    def open_project(
        self,
        path: str | os.PathLike[str],
        *,
        skip_dirty_guard: bool = False,
        on_ready=None,
    ) -> None:
        return self.project_controller.open_project_entry(path,single_shot_fn=QTimer.singleShot,
            skip_dirty_guard=skip_dirty_guard,on_ready=on_ready)

    def _recovery_choice(self, candidate: Path) -> str:
        return self.project_controller._recovery_choice(candidate)

    def _resolve_project_recovery(
        self, project_path: Path, official: SubtitleProject
    ) -> tuple[SubtitleProject, bool]:
        return self.project_controller._resolve_project_recovery(
            project_path, official, single_shot_fn=QTimer.singleShot
        )
