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

class StudioEditAssemblyMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _save_current_frame(self):
        self.frame_capture.save()

    def _mark_in(self) -> None:
        project = self.project
        if project is None:
            return
        from .project_range import set_range, range_points, text_input_focused
        if text_input_focused(): return
        set_range(project, int(self.timeline.playhead_ms), range_points(project)[1], self.undo_stack)

    def _mark_out(self) -> None:
        project = self.project
        if project is None:
            return
        from .project_range import set_range, range_points, text_input_focused
        if text_input_focused(): return
        set_range(project, range_points(project)[0], int(self.timeline.playhead_ms), self.undo_stack)

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
        self.undo_stack.push(generate_edit_command(project, changed=self._sequence_changed))
        self._reload_edit_playback()

    def _restore_full_sequence(self) -> None:
        project = self.project
        if project is None:
            return
        self.undo_stack.push(restore_full_sequence_command(project, self._sequence_changed))
        self._reload_edit_playback()

    def _import_danmaku_xml(self, path: str) -> None:
        project = self.project
        if project is None:
            return
        from .studio_runtime_state import DirtyDomain, state_for

        resolved = str(Path(path).resolve())
        with state_for(project).transaction(
            project,
            action_id="bind_danmaku_xml",
            dirty=DirtyDomain.CLIP_STATUS | DirtyDomain.AUTOSAVE,
        ):
            sequence_of(project).danmaku_path = str(path)
        self.highlight_panel.set_xml_discovery(
            (resolved,), resolved, automatic=False
        )

    def _unbind_danmaku_xml(self) -> None:
        project = self.project
        if project is None:
            return
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
            sequence_of(project).danmaku_path = ""
            project.studio_state["media_xml_match"] = "none"
        self.highlight_panel.set_xml_discovery(
            tuple(project.studio_state.get("media_xml_candidates", ())),
            "",
            automatic=False,
        )

    def _analyze_highlights(self, options: dict) -> None:
        project = self.project
        if project is None:
            self.highlight_panel.analysis_finished()
            return
        sequence = sequence_of(project)
        payload = {
            "danmaku_path": sequence.danmaku_path,
            "mode": options.get("mode") or "subtitles_xml",
            "target_count": int(options.get("target_count") or 20),
            "min_seconds": int(options.get("min_seconds") or 30),
            "max_seconds": int(options.get("max_seconds") or 180),
            "ai_service": str(options.get("ai_service") or ""),
            "model": str(options.get("model") or ""),
            "runtime_settings": self.runtime_settings,
        }
        request = begin_request(self, "highlight")
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
        self.undo_stack.push(replace_candidates_command(project, candidates, "AI 剪辑候选", self._sequence_changed))
        sequence = sequence_of(project)
        self.highlight_panel.set_project_status(project, sequence.danmaku_path)
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
