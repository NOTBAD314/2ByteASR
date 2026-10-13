"""Edit assembly flow: mark in/out, IO candidates, timeline markers,
highlight generation, and danmaku binding for Subtitle Studio."""

from __future__ import annotations

import copy
from pathlib import Path
from PySide6.QtWidgets import (QMessageBox)
from .studio_edit_commands import (add_marker_command, generate_edit_command, replace_candidates_command, restore_full_sequence_command)
from .studio_edit_sequence import (HighlightCandidate, TimelineMarker, sequence_of)
from .studio_highlight_ui import HighlightAnalyzeWorker
from .studio_sequence_mapper import (source_to_timeline, timeline_to_source)
from .studio_theme import studio_message_box
from .studio_analysis_request import begin_request, current_request, cancel_request, retain_worker

from .i18n import bind_text

from .i18n import tr

def _clock(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class StudioEditAssemblyMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _save_current_frame(self):
        self.frame_capture.save()

    def _mark_in(self) -> None:
        self._mark_range_point(0)

    def _mark_out(self) -> None:
        self._mark_range_point(1)

    def _mark_range_point(self, index: int) -> None:
        """I / O at the playhead; the same key again at the same place clears
        that point (2026-10-09, M16, user). One undo step either way."""
        project = self.project
        if project is None:
            return
        from .project_range import set_range, range_points, text_input_focused, clock_text, RANGE_TOGGLE_MS
        if text_input_focused(): return
        points = list(range_points(project))
        here = int(self.timeline.playhead_ms)
        cleared = points[index] is not None and abs(points[index] - here) <= RANGE_TOGGLE_MS
        points[index] = None if cleared else here
        set_range(project, points[0], points[1], self.undo_stack)
        name = '入点' if index == 0 else '出点'
        key = 'I' if index == 0 else 'O'
        if cleared:
            bind_text(self.save_state, '已取消{name}', name=tr(name))
        else:
            bind_text(self.save_state, '{name} {time} · 同一位置再按 {key} 取消', name=tr(name), time=clock_text(here), key=key)
        self.timeline.update()

    def _clear_range(self) -> None:
        project = self.project
        if project is None:
            return
        from .project_range import set_range
        set_range(project, None, None, self.undo_stack)
        bind_text(self.save_state, '已清除入出点范围')
        self.timeline.update()

    def _add_io_candidate(self) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        start = sequence.in_point_ms
        end = sequence.out_point_ms
        if start is None or end is None or end - start < 40:
            return
        mapped_in = timeline_to_source(sequence, start)
        mapped_out = timeline_to_source(sequence, max(start + 1, end - 1))
        if mapped_in is None or mapped_out is None:
            return
        candidate = HighlightCandidate(
            id=f"manual-{start}-{end}",
            title="手动候选",
            source_in_ms=mapped_in.source_ms,
            source_out_ms=mapped_out.source_ms,
            score=1.0,
            reason="I / O",
            status="accepted",
            origin="manual",
        )
        candidates = list(sequence.clip_candidates) + [candidate]
        self.undo_stack.push(replace_candidates_command(project, candidates, "加入剪辑候选", self._sequence_changed))
        if hasattr(self, "highlight_panel"):
            self.highlight_panel.set_project_status(project, sequence.danmaku_path)

    def _add_timeline_marker(self) -> None:
        project = self.project
        if project is None:
            return
        marker = TimelineMarker(
            id=f"mk-{self.timeline.playhead_ms}",
            time_ms=int(self.timeline.playhead_ms),
            label="标记",
            kind="note",
        )
        self.undo_stack.push(add_marker_command(project, marker, self._sequence_changed))

    def _on_candidate_clicked(self, candidate_id: str) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        candidate = next((item for item in sequence.clip_candidates if item.id == candidate_id), None)
        if candidate is None:
            return
        mapped = source_to_timeline(sequence, candidate.source_in_ms)
        if mapped is None:
            # Candidate is in source time of the original recording.
            self._seek(candidate.source_in_ms / 1000.0)
            return
        self._seek(mapped.timeline_ms / 1000.0)

    def _set_candidate_status(self, candidate_id: str, status: str) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        candidates = []
        for item in sequence.clip_candidates:
            clone = copy.deepcopy(item)
            if item.id == candidate_id:
                clone.status = status
            candidates.append(clone)
        self.undo_stack.push(replace_candidates_command(project, candidates, "更新剪辑候选", self._sequence_changed))
        self.highlight_panel.set_project_status(project, sequence.danmaku_path)
        self.timeline.update()

    def _remove_candidate_from_bin(self, candidate_id: str) -> None:
        self._set_candidate_status(candidate_id, "suggested")

    def _clear_candidate_bin(self) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        candidates = []
        for item in sequence.clip_candidates:
            clone = copy.deepcopy(item)
            if clone.status == "accepted":
                clone.status = "suggested"
            candidates.append(clone)
        self.undo_stack.push(
            replace_candidates_command(
                project,
                candidates,
                "清空剪辑候选",
                self._sequence_changed,
            )
        )

    def _move_candidate_in_bin(self, candidate_id: str, direction: int) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        candidates = [copy.deepcopy(item) for item in sequence.clip_candidates]
        accepted_positions = [
            index for index, item in enumerate(candidates) if item.status == "accepted"
        ]
        current = next(
            (index for index, position in enumerate(accepted_positions) if candidates[position].id == candidate_id),
            -1,
        )
        target = current + (-1 if int(direction) < 0 else 1)
        if current < 0 or not 0 <= target < len(accepted_positions):
            return
        left = accepted_positions[current]
        right = accepted_positions[target]
        candidates[left], candidates[right] = candidates[right], candidates[left]
        self.undo_stack.push(
            replace_candidates_command(
                project,
                candidates,
                "调整剪辑候选顺序",
                self._sequence_changed,
            )
        )

    def _generate_highlight_edit(self) -> None:
        project = self.project
        if project is None:
            return
        from .studio_edit_sequence import timeline_duration_ms
        panel = self.highlight_panel
        full_ms = int(project.media.duration_ms or 0)
        try:
            command = generate_edit_command(project, changed=self._sequence_changed, page=self,
                                            locked_speakers=self.timeline.locked_speakers)
        except ValueError as exc:
            panel.show_edit_result(tr(str(exc)), ok=False)
            self.save_state.setText(tr(str(exc)))
            return
        if command is not None:
            self.undo_stack.push(command)
            self._reload_edit_playback()
        # The result is the whole new timeline: show it from its first frame.
        self._present_whole_timeline(0)
        sequence = sequence_of(project)
        duration = timeline_duration_ms(project)
        left_out = getattr(command, 'left_out_captions', 0) if command is not None else 0
        panel.show_edit_result(tr(
            '已生成剪辑：{count} 段，共 {duration}（完整录播 {full}）。Ctrl+Z 撤销，「返回完整录播」可恢复。'
            if command is not None else '时间轴已是候选箱的剪辑结果：{count} 段，共 {duration}（完整录播 {full}）。',
            count=len(sequence.segments), duration=_clock(duration), full=_clock(full_ms))
            + (tr('{count} 条字幕不在保留区间，返回完整录播可恢复。', count=left_out) if left_out else ''), ok=True)
        bind_text(self.save_state, '已生成剪辑 · {count} 段 · {duration}', count=len(sequence.segments),
                  duration=_clock(duration))

    def _restore_full_sequence(self) -> None:
        project = self.project
        if project is None:
            return
        panel = self.highlight_panel
        try:
            command = restore_full_sequence_command(project, self._sequence_changed, page=self,
                                                    locked_speakers=self.timeline.locked_speakers)
        except ValueError as exc:
            panel.show_edit_result(tr(str(exc)), ok=False)
            self.save_state.setText(tr(str(exc)))
            return
        if command is not None:
            self.undo_stack.push(command)
            self._reload_edit_playback()
        self._present_whole_timeline(None)
        from .studio_edit_sequence import timeline_duration_ms
        panel.show_edit_result(tr('已返回完整录播（{duration}）。', duration=_clock(timeline_duration_ms(project))), ok=True)

    def _present_whole_timeline(self, playhead_ms) -> None:
        """Fit the edited timeline in view and hold the player on one frame."""
        try:
            if self.video.controller and not bool(self.video.playback_position_snapshot().paused):
                self.video.set_paused(True)
                self._sync_play_button(True)
        except (RuntimeError, AttributeError):
            pass
        self._fit_timeline()
        if playhead_ms is not None:
            self.timeline.set_playhead(int(playhead_ms))
            self._seek(int(playhead_ms) / 1000.0)

    def _refresh_danmaku_status(self) -> None:
        if hasattr(self, "highlight_panel"):
            from .danmaku_binding import effective_path
            self.highlight_panel.set_project_status(self.project, effective_path(self.project) if self.project else "")

    def _schedule_danmaku_discovery(self, manual_path: str = "") -> None:
        """Find/validate the same-name XML beside the ORIGINAL source, off the GUI thread.

        ``manual_path`` validates a file the user chose (or dropped) instead.
        Results are applied only to the project and source they were made for.
        """
        import threading
        from .danmaku_binding import (
            DanmakuDiscovery, binding_of, discover_for_source, inspect_xml,
            needs_discovery, normalized_source, primary_source)
        project = self.project
        if project is None:
            self._refresh_danmaku_status()
            return
        legacy = "" if binding_of(project) else str(sequence_of(project).danmaku_path or "")
        manual = str(manual_path or legacy)
        if not manual and not needs_discovery(project):
            self._refresh_danmaku_status()
            return
        project_id, source = project.project_id, primary_source(project)
        explicit = bool(manual_path)

        def work() -> None:
            if manual:
                count, duration, error = inspect_xml(manual)
                result = DanmakuDiscovery(normalized_source(source), "manual" if explicit else "legacy_manual",
                                          path=str(Path(manual).resolve()), count=count,
                                          duration_ms=duration, error=error)
            else:
                result = discover_for_source(source)
            try:
                self.danmaku_discovery_signal.emit(project_id, result)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="studio-danmaku-discovery").start()
        if not manual:
            self._refresh_danmaku_status()

    def _danmaku_discovery_ready(self, project_id: str, discovery) -> None:
        project = self.project
        if project is None or project.project_id != project_id:
            return  # a late result for another project is discarded
        from .danmaku_binding import apply_discovery, bind_manual, normalized_source, primary_source
        from .studio_runtime_state import DirtyDomain, state_for
        if discovery.source_path != normalized_source(primary_source(project)):
            return  # the source changed while searching
        manual = discovery.status in {"manual", "legacy_manual"}
        # A user choice is an edit (saved); an automatic match is re-found on
        # open and saved with the next edit, without forcing an autosave.
        dirty = DirtyDomain.CLIP_STATUS | DirtyDomain.PROJECT_METADATA
        if discovery.status == "manual":
            dirty |= DirtyDomain.AUTOSAVE
        with state_for(project).transaction(project, action_id="danmaku_binding", dirty=dirty):
            if manual:
                bind_manual(project, discovery.path, discovery.count, discovery.duration_ms, discovery.error)
            else:
                apply_discovery(project, discovery)
        self._refresh_danmaku_status()

    def _import_danmaku_xml(self, path: str) -> None:
        if self.project is None or not path:
            return
        self._schedule_danmaku_discovery(manual_path=str(path))

    def _unbind_danmaku_xml(self) -> None:
        project = self.project
        if project is None:
            return
        from .danmaku_binding import unbind
        from .studio_runtime_state import DirtyDomain, state_for

        with state_for(project).transaction(
            project,
            action_id="unbind_danmaku_xml",
            dirty=(
                DirtyDomain.PROJECT_METADATA
                | DirtyDomain.CLIP_STATUS
                | DirtyDomain.AUTOSAVE
            ),
        ):
            unbind(project)
        self._refresh_danmaku_status()

    def _analyze_highlights(self, options: dict) -> None:
        project = self.project
        if project is None:
            self.highlight_panel.analysis_finished()
            return
        from .danmaku_binding import effective_path
        payload = {
            "danmaku_path": effective_path(project),
            "mode": options.get("mode") or "subtitles_xml",
            "target_count": int(options.get("target_count") or 20),
            "min_seconds": int(options.get("min_seconds") or 30),
            "max_seconds": int(options.get("max_seconds") or 180),
            "ai_service": str(options.get("ai_service") or ""),
            "model": str(options.get("model") or ""),
            "runtime_settings": self.runtime_settings,
        }
        request = begin_request(self, "highlight")
        request.analysis_input = {"danmaku_path": payload["danmaku_path"], "mode": payload["mode"]}
        self._highlight_worker = HighlightAnalyzeWorker(copy.deepcopy(project), copy.deepcopy(payload))
        self._highlight_worker.finished_ok.connect(lambda result: self._highlights_ready(result, request))
        self._highlight_worker.failed.connect(lambda message: self._highlights_failed(message, request))
        retain_worker(self, self._highlight_worker)
        self._highlight_worker.start()

    def _cancel_highlight_analysis(self) -> None:
        cancel_request(self, "highlight")
        self.highlight_panel.analysis_finished()
        bind_text(self.highlight_panel.status, '分析已取消')

    def _highlights_ready(self, result: dict, request=None) -> None:
        if not current_request(self, "highlight", request):
            self._finish_stale_highlights(request)
            return
        self._highlight_request = None
        self.highlight_panel.analysis_finished()
        project = self.project
        if project is None:
            return
        candidates = list(result.get("candidates") or [])
        self.highlight_panel.set_analysis_note(
            str(result.get("llm_status") or ""),
            str(result.get("llm_error") or ""),
        )
        from .studio_runtime_state import DirtyDomain, state_for
        # Provenance of these candidates: which XML (and how many comments)
        # really went into the analysis.
        provenance = {key: result.get(key) for key in (
            "danmaku_count", "danmaku_duration_ms", "local_count", "llm_status", "ai_service", "model")}
        provenance.update(getattr(request, "analysis_input", {}) or {}, candidates=len(candidates))
        with state_for(project).transaction(project, action_id="highlight_provenance",
                                            dirty=DirtyDomain.PROJECT_METADATA):
            project.studio_state["highlight_analysis"] = provenance
        self.undo_stack.push(replace_candidates_command(project, candidates, "AI 剪辑候选", self._sequence_changed))
        self._refresh_danmaku_status()
        if candidates:
            self.highlight_panel.show_candidates_stage()
        self.timeline.update()

    def _highlights_failed(self, message: str, request=None) -> None:
        if not current_request(self, "highlight", request):
            self._finish_stale_highlights(request)
            return
        self._highlight_request = None
        self.highlight_panel.analysis_finished()
        studio_message_box(self, QMessageBox.Icon.Warning, tr('剪辑助手'), str(message))

    def _finish_stale_highlights(self, request) -> None:
        if request is not None and getattr(self, "_highlight_request", None) is request:
            self._highlight_request = None
            if self.project is request.project and not getattr(self, "_close_requested", False):
                self.highlight_panel.analysis_finished()
                bind_text(self.highlight_panel.status, '工程已修改，已丢弃过期分析，请重新分析。')
