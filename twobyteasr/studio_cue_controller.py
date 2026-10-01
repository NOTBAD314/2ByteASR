"""Cue selection and mutation orchestration for Subtitle Studio."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from time import perf_counter

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QSignalBlocker, Qt
from PySide6.QtWidgets import QAbstractItemView

from .studio_commands import (
    AssignSpeakerCommand,
    BatchTimingCommand,
    EditCueIntervalsCommand,
    MutationOrigin,
    SetCueFieldsCommand,
    SetCueTranslationCommand,
    add_cue_command,
    cue_by_id,
    delete_cues_command,
    merge_cues_command,
    set_cues_timing_offset_command,
    split_cue_command,
)
from .studio_edit_commands import delete_video_segments_command, ripple_trim_command
from .studio_edit_sequence import sequence_of
from .studio_project import StudioCue
from .studio_runtime_state import DirtyDomain, StateDelta, state_for
from .studio_theme import MIN_CUE_DURATION_MS
from .studio_timing import recommend_many, resolve_split
from .selection_scope import SelectionMode, SelectionScope
from .style_recipe import route_recipe

from .i18n import bind_text, tr


class StudioCueController:
    """Coordinate cue-domain actions against canonical ``StudioSession`` state."""

    __slots__ = ("page", "session")

    def __init__(self, page, session):
        self.page = page
        self.session = session

    def resolve_playhead_target(self, milliseconds: int):
        """Resolve timeline position, including gaps; never reuse a stale selection."""
        project, page = self.session.project, self.page
        if project is None:
            return None
        runtime = state_for(project)
        timeline = page.timeline
        hidden = getattr(timeline, 'hidden_speakers', set())
        locked = getattr(timeline, 'locked_speakers', set())
        visibility = getattr(page, '_subtitle_track_visibility', {})
        def eligible(cue):
            return (cue.id in runtime.cue_by_id and cue.end_ms > cue.start_ms
                    and cue.speaker_id not in hidden and cue.speaker_id not in locked
                    and visibility.get(cue.speaker_id, True))
        header = getattr(timeline, 'selected_track_header', None)
        speaker = (header[1] if header and header[0] == 'subtitle'
                   else self.session.preferred_subtitle_speaker)
        order = getattr(timeline, '_speaker_ids', ()) or [s.id for s in project.speakers]
        ranks = {key: i for i, key in enumerate(order)}
        def rank(cue):
            return (cue.speaker_id != speaker, ranks.get(cue.speaker_id, len(ranks)),
                    cue.speaker_id, -cue.start_ms, cue.id)
        candidates = [cue for cue in runtime.cues_at(milliseconds) if eligible(cue)]
        if not candidates:
            for cue in runtime.cues_before(milliseconds):
                if candidates and cue.end_ms < candidates[0].end_ms:
                    break
                if eligible(cue):
                    candidates.append(cue)
        return min(candidates, key=rank) if candidates else None

    def sync_playhead_target(self, milliseconds: int, *, force: bool = False):
        cue = self.resolve_playhead_target(milliseconds)
        cue_id = cue.id if cue else ''
        session = self.session
        if not force and cue_id == session.observed_playhead_target_id:
            return cue
        session.observed_playhead_target_id = cue_id
        session.playhead_target_id = cue_id
        self._mirror_clock_selection(cue_id)
        return cue

    def _mirror_clock_selection(self, cue_id: str) -> None:
        """Lightweight selection only: no editor hydration, focus, seek or dirty state."""
        page = self.page
        self.session.selected_cue_id = cue_id
        page._manual_selection_hold = False
        scope = SelectionScope.explicit((cue_id,), cue_id) if cue_id else SelectionScope.empty()
        page.selection_model.set_scope(scope)
        page.timeline.set_selection_scope(scope)
        model = page.cue_table.selectionModel()
        blocker = QSignalBlocker(model)
        model.clearSelection()
        row = page.cue_model.row_for_cue_id(cue_id) if cue_id else -1
        if row >= 0:
            model.select(page.cue_model.index(row, 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)
        del blocker
        page._selection_needs_hydration = bool(cue_id)
        refresh = getattr(page, '_refresh_ai_design_target', None)
        if callable(refresh):
            refresh()

    def cancel_selection(self) -> None:
        # Remember what the clock sees, but clear the retained target. Repeated
        # frames cannot undo cancellation; a new target or explicit E can.
        cue = self.resolve_playhead_target(self.page.timeline.playhead_ms)
        self.session.observed_playhead_target_id = cue.id if cue else ''
        self.session.playhead_target_id = ''
        self._mirror_clock_selection('')

    def selected_cue_ids(self) -> list[str]:
        if not self.session.project:
            return []
        page = self.page
        scope = page.selection_model.scope
        if scope.mode != SelectionMode.EMPTY:
            selected = scope.materialize(
                [cue.id for cue in self.session.project.cues]
            )
            if selected:
                return selected
        rows = page.cue_table.selectionModel().selectedRows()
        selected = [
            str(
                page.cue_model.data(
                    page.cue_model.index(index.row(), 0), Qt.ItemDataRole.UserRole
                )
                or ""
            )
            for index in rows
        ]
        selected_id = self.session.selected_cue_id
        return [item for item in selected if item] or ([selected_id] if selected_id else [])

    def timeline_selection_changed(self, cue_ids) -> None:
        selected_set = {str(item) for item in cue_ids if str(item)}
        if not selected_set:
            self.cancel_selection()
            return
        from .studio_edit_sequence import projected_cues
        selected = [cue.id for cue in projected_cues(self.session.project) if cue.id in selected_set] if self.session.project else []
        active = self.page.timeline.selected_id
        scope = SelectionScope.explicit(
            selected,
            active if active in selected else next(iter(selected), ''),
        )
        self.apply_selection_scope(scope, sync_timeline=False)

    def apply_selection_scope(
        self,
        scope: SelectionScope,
        *,
        sync_timeline: bool = True,
    ) -> None:
        page = self.page
        page.selection_model.set_scope(scope)
        self.session.selected_cue_id = scope.active_id or ''
        refresh_target = getattr(page, '_refresh_ai_design_target', None)
        if callable(refresh_target):
            refresh_target()
        if sync_timeline:
            page.timeline.set_selection_scope(scope)
            page._selection_latency.increment("timeline_selection_mirror")
        selection_model = page.cue_table.selectionModel()
        selection_model.blockSignals(True)
        try:
            selection_model.clearSelection()
            selection = QItemSelection()
            if scope.mode == SelectionMode.ALL and page.cue_model.rowCount() > 0:
                selection.select(
                    page.cue_model.index(0, 0),
                    page.cue_model.index(
                        page.cue_model.rowCount() - 1,
                        page.cue_model.columnCount() - 1,
                    ),
                )
                page._selection_latency.increment("QItemSelection_ranges")
            else:
                rows = sorted(
                    row
                    for cue_id in scope.explicit_ids
                    if (row := page.cue_model.row_for_cue_id(cue_id)) >= 0
                )
                if scope.mode == SelectionMode.ROW_RANGE:
                    rows = list(range(
                        max(0, scope.row_start),
                        min(page.cue_model.rowCount() - 1, scope.row_end) + 1,
                    ))
            if scope.mode != SelectionMode.ALL and rows:
                start = previous = rows[0]
                for row in (*rows[1:], -1):
                    if row == previous + 1:
                        previous = row
                        continue
                    selection.select(
                        page.cue_model.index(start, 0),
                        page.cue_model.index(
                            previous, page.cue_model.columnCount() - 1
                        ),
                    )
                    page._selection_latency.increment("QItemSelection_ranges")
                    start = previous = row
            if not selection.isEmpty():
                selection_model.select(
                    selection,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        finally:
            selection_model.blockSignals(False)
        page._selection_latency.mark("T2_qitemselection_applied")
        page._selection_latency.mark("T3_selection_model_correct")
        if hasattr(page, "style_scope"):
            selected_index = page.style_scope.findData("selected")
            if selected_index >= 0:
                page.style_scope.setItemText(
                    selected_index, tr("选中字幕（{count}）", count=scope.count())
                )
        page._selection_latency.mark("T5_timeline_mirror_correct")
        page._selection_latency.increment("inspector_reload")
        page._load_style_inspector(selection_scope=scope)

    def table_selection_changed(self) -> None:
        page = self.page
        rows = page.cue_table.selectionModel().selectedRows()
        selected = [
            str(page.cue_model.data(
                page.cue_model.index(index.row(), 0),
                Qt.ItemDataRole.UserRole,
            ) or "")
            for index in rows
        ]
        index = page.cue_table.currentIndex()
        active = str(page.cue_model.data(page.cue_model.index(index.row(), 0), Qt.ItemDataRole.UserRole) or '') if index.isValid() else ''
        if active not in selected:
            active = next((item for item in selected if item), '')
        scope = SelectionScope.explicit(selected, active)
        page._manual_selection_hold = bool(scope.active_id)
        cue = self.session._cue_lookup.get(scope.active_id)
        if cue:
            self.session.preferred_subtitle_speaker = cue.speaker_id
        elif not scope.active_id:
            self.cancel_selection()
            return
        if scope.active_id:
            page.timeline.selected_video_clip_id = ''
            page.timeline.selected_track_header = None
        self.session.selected_cue_id = scope.active_id or ''
        refresh_target = getattr(page, '_refresh_ai_design_target', None)
        if callable(refresh_target):
            refresh_target()
        page.selection_model.set_scope(scope)
        page.timeline.set_selection_scope(scope)
        page._load_style_inspector(selection_scope=scope)

    def smart_align_current(self) -> None:
        project = self.session.project
        cue_id = self.session.selected_cue_id
        if not project or not cue_id:
            return
        report = recommend_many(project, [cue_id])
        if not report.recommendations:
            self.page._show_studio_hint(tr('无法可靠修轴：当前字幕缺少明确字级时间或语音证据'))
            return
        values = {
            item.cue_id: (
                item.recommended_start
                if item.recommended_start is not None
                else item.current_start,
                item.recommended_end
                if item.recommended_end is not None
                else item.current_end,
            )
            for item in report.recommendations
        }
        self.session.undo_stack.push(
            BatchTimingCommand(project, values, "Smart Align", self.changed)
        )
        item = report.recommendations[0]
        delta = (
            values[item.cue_id][0] - item.current_start,
            values[item.cue_id][1] - item.current_end,
        )
        self.page._show_studio_hint(tr('已修正时间轴 {value0:+d}ms / {value1:+d}ms', value0=delta[0], value1=delta[1]))

    def smart_align_selected(self) -> None:
        project = self.session.project
        if not project:
            return
        cue_ids = self.selected_cue_ids()
        report = recommend_many(project, cue_ids)
        values = {
            item.cue_id: (
                item.recommended_start
                if item.recommended_start is not None
                else item.current_start,
                item.recommended_end
                if item.recommended_end is not None
                else item.current_end,
            )
            for item in report.recommendations
            if item.changed
        }
        if not values:
            self.page._show_studio_hint(tr('无法可靠修轴：已跳过 {value0} 条', value0=len(cue_ids)))
            return
        self.session.undo_stack.push(
            BatchTimingCommand(project, values, "Smart Align selected", self.changed)
        )
        self.page._show_studio_hint(tr('已修正 {value0} 条字幕，跳过 {value1} 条', value0=len(values), value1=len(report.skipped)))

    def speaker_structure_changed(self) -> None:
        self.page._populate_speakers()
        self.changed()

    def select_cue(
        self, cue_id: str, *, refresh_advanced: bool = False, hydrate: bool = True,
    ) -> None:
        self._select_cue_transaction(cue_id,refresh_advanced=refresh_advanced,hydrate=hydrate)
        updater=getattr(self.page,'_update_web_adjust_visibility',None)
        if callable(updater):updater()

    def _select_cue_transaction(
        self, cue_id: str, *, refresh_advanced: bool = False, hydrate: bool = True,
    ) -> None:
        project = self.session.project
        cue_id = str(cue_id or "")
        previous_id = self.session.selected_cue_id
        if project is None or previous_id == cue_id:
            self._select_cue_ui(cue_id, refresh_advanced=refresh_advanced, hydrate=hydrate)
            return
        runtime = state_for(project)
        with runtime.transaction(
            project,
            action_id="select_cue",
            dirty=(
                DirtyDomain.CUE_SELECTION
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.TRANSFORM
            ),
            affected_cue_ids=(previous_id, cue_id),
            selection_before=previous_id,
            selection_after=cue_id,
        ):
            self._select_cue_ui(cue_id, refresh_advanced=refresh_advanced, hydrate=hydrate)

    def _select_cue_ui(
        self, cue_id: str, *, refresh_advanced: bool = False, hydrate: bool = True,
    ) -> None:
        page = self.page
        project = self.session.project
        if getattr(page, '_canvas_editor', None) is not None:
            hydrate = False
        previous_id = self.session.selected_cue_id
        cue_id = str(cue_id or "")
        if not cue_id:
            page._manual_selection_hold = False
        if cue_id and hasattr(page, "timeline"):
            # Subtitle and video transforms are separate selection domains.
            # A subtitle selection must retire the video canvas handles.
            page.timeline.selected_video_clip_id = ""
            compositor = getattr(page, "video_compositor", None)
            if compositor is not None:
                compositor.set_selected_clip("")
        hydration_started = perf_counter()
        hydration_mark = hydration_started
        hydration_phases: dict[str, float] = {}

        def mark(phase: str) -> None:
            nonlocal hydration_mark
            now = perf_counter()
            hydration_phases[phase] = round((now - hydration_mark) * 1000.0, 3)
            hydration_mark = now

        if previous_id and previous_id != cue_id and hydrate:
            # Lightweight (playback-follow) selections never touch the
            # editor, so its content belongs to an older cue; committing it
            # here would attribute one cue's text to another.
            self.commit_manual_term_learning(previous_id)
        self.session.selected_cue_id = cue_id
        refresh_target = getattr(page, '_refresh_ai_design_target', None)
        if callable(refresh_target):
            refresh_target()
        timing=getattr(page,"_cue_timing_preview",None)
        if timing is not None and not getattr(page,'_review_fast_select',False):timing.request_warm()
        if cue_id:
            page.selection_model.active_id = cue_id
            if not page.selection_model.scope.contains(cue_id):
                page.selection_model.set_scope(
                    SelectionScope.explicit((cue_id,), cue_id)
                )
            else:
                page.selection_model.scope = (
                    page.selection_model.scope.with_active(cue_id)
                )
        else:
            page.selection_model.set_scope(SelectionScope.empty())
        if cue_id in page.timeline.selected_ids:
            page.timeline.selected_id = cue_id
            page.timeline.invalidate_cue(cue_id)
        else:
            page.timeline.set_selected(cue_id)
        if hasattr(page, "style_scope"):
            selected_index = page.style_scope.findData("selected")
            if selected_index >= 0:
                page.style_scope.setItemText(
                    selected_index,
                    tr("选中字幕（{count}）", count=page.selection_model.selected_count()),
                )
        mark("selection_scope_timeline")
        playing_follow = not hydrate or getattr(page,'_review_fast_select',False)
        page._selection_needs_hydration = playing_follow
        cursor_position = page.cue_text.textCursor().position() if not playing_follow else 0
        editor_had_focus = page.cue_text.hasFocus() if not playing_follow else False
        page._updating_editor = True
        try:
            if not project or not cue_id:
                if not playing_follow:
                    page.cue_text.clear()
                if hasattr(page, "position_overlay"):
                    page.position_overlay.hide()
                return
            cue = self.session._cue_lookup.get(cue_id)
            if cue is None:
                return
            if not playing_follow:
                # 2026-09-02（倍速顺滑）：播放期跟随选中只更新选择域/时间轴/
                # 表格行——编辑器与样式检查器水合（实测单次 280ms）推迟到暂停
                # 时补做（见 _playback_state_changed 的全量重选）。
                page._manual_text_baselines.setdefault(cue.id, cue.text)
                if page.cue_text.toPlainText() != cue.text:
                    page.cue_text.setPlainText(cue.text)
                if hasattr(page, "subtitle_edit_input") and getattr(page, "_canvas_editor", None) is not page.subtitle_edit_input:
                    if page.subtitle_edit_input.toPlainText() != cue.text:
                        page.subtitle_edit_input.blockSignals(True)
                        page.subtitle_edit_input.setPlainText(cue.text)
                        page.subtitle_edit_input.blockSignals(False)
                translations = project.generation_metadata.get("translations", {})
                translation = (
                    str(translations.get(cue.id, "") or "")
                    if isinstance(translations, dict)
                    else ""
                )
                if page.translation_text.toPlainText() != translation:
                    page.translation_text.setPlainText(translation)
                if editor_had_focus:
                    cursor = page.cue_text.textCursor()
                    cursor.setPosition(min(cursor_position, len(cue.text)))
                    page.cue_text.setTextCursor(cursor)
                page.start_ms.setValue(cue.start_ms)
                page.end_ms.setValue(cue.end_ms)
                page.duration_ms.setValue(cue.end_ms - cue.start_ms)
                speaker_index = page.speaker.findData(cue.speaker_id)
                page.speaker.setCurrentIndex(max(0, speaker_index))
                if hasattr(page, "style_preset"):
                    # Preset identity is explicit domain state. A derived style id
                    # created by an appearance/Transform transaction must never be
                    # parsed back into a preset choice.
                    preset_index = page.style_preset.findData(cue.base_preset_id)
                    if preset_index < 0:
                        preset_index = page.style_preset.findData(cue.style_id)
                    page.style_preset.blockSignals(True)
                    try:
                        if preset_index >= 0:
                            page.style_preset.setCurrentIndex(preset_index)
                    finally:
                        page.style_preset.blockSignals(False)
                    recipe_payload = (
                        project.style_recipes.get(cue.style_id, {})
                        if project is not None else {}
                    )
                    from .style_recipe import MOTION_SOURCE_VISUAL_GRAPH, motion_source

                    graph_payload = (
                        recipe_payload.get("visualGraph")
                        if isinstance(recipe_payload, Mapping) else {}
                    )
                    graph_motion = (
                        motion_source(
                            recipe_payload.get("motion") if isinstance(recipe_payload, Mapping) else {},
                            visual_graph=graph_payload if isinstance(graph_payload, Mapping) else {},
                        ) == MOTION_SOURCE_VISUAL_GRAPH
                    )
                    if not graph_motion:
                        effect_index = page.effect_preset.findData(cue.effect_id)
                        if effect_index >= 0:
                            page.effect_preset.blockSignals(True)
                            page.effect_preset.setCurrentIndex(effect_index)
                            page.effect_preset.blockSignals(False)
                            page._load_motion_controls(cue.effect_id)
                    mark("motion_controls")
                    page._load_style_inspector()
                    mark("style_inspector")
                page._refresh_selected_cue_properties(cue)
                mark("cue_properties")
                if hasattr(page, "position_overlay"):
                    page.position_overlay.set_text(cue.text)
                    page.position_overlay.sync_to_video(page.video)
                    if (
                        getattr(page, "position_edit_button", None) is not None
                        and page.position_edit_button.isChecked()
                        and page.isVisible()
                        and bool(getattr(page.video,'_paused',True))
                        and getattr(page, "export_workspace", None) is None
                    ):
                        page.position_overlay.show()
                        page.position_overlay.raise_()
                    page._overlay_cue_id = cue.id
                    page._sync_transform_visual_overlay()
                mark("transform_sync")
                if refresh_advanced:
                    page._sync_selected_cue_advanced(project.style_recipes.get(cue.style_id))
                page._refresh_current_review_context(cue)
                mark("review_context")
        finally:
            page._updating_editor = False
        recipe_payload = project.style_recipes.get(cue.style_id) if project and cue_id else None
        if getattr(page,'_review_fast_select',False):
            row=page.cue_model.row_for_cue_id(cue_id)
            if row>=0:
                blocker=QSignalBlocker(page.cue_table.selectionModel())
                page.cue_table.selectRow(row)
                del blocker
                page.cue_table.scrollTo(page.cue_model.index(row,0),QAbstractItemView.ScrollHint.EnsureVisible)
            return
        if (
            (isinstance(recipe_payload, Mapping)
             and recipe_payload
             and route_recipe(recipe_payload).engine == "remotion")
            or getattr(page, "_multitrack_composition_active", False)
            or getattr(page, "_audio_only_subtitle_active", False)
        ):
            # Native cues also have a LIVE raster above composed video. Their
            # text/style edits and undo must invalidate that same foreground.
            page._activate_selected_advanced_if_needed(force=refresh_advanced)
        if hasattr(page, "ensure_active_subtitle_renderer"):
            page.ensure_active_subtitle_renderer(reason="cue_selected")
        mark("renderer_commit")
        row = page.cue_model.row_for_cue_id(self.session.selected_cue_id)
        if row >= 0:
            index = page.cue_model.index(row, 0)
            if not page.cue_table.selectionModel().isRowSelected(row,index.parent()):
                # The canonical scope was already committed above. A mirrored
                # row must not re-enter table_selection_changed and hydrate
                # the inspector during lightweight playback-follow.
                blocker = QSignalBlocker(page.cue_table.selectionModel())
                page.cue_table.selectRow(row)
                del blocker
                page.cue_table.scrollTo(
                    index, QAbstractItemView.ScrollHint.PositionAtCenter
                )
        mark("table_selection")
        page._studio_trace(
            "CUE_HYDRATION",
            cue_id=cue_id,
            total_ms=round((perf_counter() - hydration_started) * 1000.0, 3),
            phases_ms=hydration_phases,
        )

    def consume_state_delta(self, delta: StateDelta) -> None:
        """Update only consumers interested in the committed dirty domains."""

        project = self.session.project
        if project is None:
            return
        page = self.page
        dirty = delta.dirty
        affected = set(delta.affected_cue_ids)
        if dirty & DirtyDomain.AUTOSAVE:
            bind_text(page.save_state, '未保存')
        if dirty & DirtyDomain.CUE_MODEL:
            runtime = state_for(project)
            self.session._cue_lookup = dict(runtime.cue_by_id)
            page._manual_text_baselines = {
                cue.id: page._manual_text_baselines.get(cue.id, cue.text)
                for cue in project.cues
            }
            page.cue_model.refresh()
            if delta.selection_after != self.session.selected_cue_id:
                self.session.selected_cue_id = delta.selection_after
        elif dirty & (
            DirtyDomain.CUE_CONTENT
            | DirtyDomain.CUE_TIMING
            | DirtyDomain.CUE_STYLE
        ):
            runtime = state_for(project)
            self.session._cue_lookup = dict(runtime.cue_by_id)
            for cue_id in affected:
                columns = None
                if dirty & DirtyDomain.CUE_CONTENT and not dirty & DirtyDomain.CUE_TIMING:
                    columns = (3, 4)
                page.cue_model.refresh_cue(cue_id, columns)

        sequence_handled = False
        if (
            dirty & DirtyDomain.SEQUENCE_STRUCTURE
            and delta.sequence_before is not None
            and delta.sequence_after is not None
        ):
            page._sequence_changed(
                delta.sequence_before,
                delta.sequence_after,
                _from_delta=True,
            )
            sequence_handled = True

        timing=getattr(page,"_cue_timing_preview",None)
        if timing is not None:timing.request_warm()

        if dirty & DirtyDomain.TIMELINE_INDEX and not sequence_handled:
            page.timeline.reindex_project(repaint=False)
            page.timeline.invalidate_ranges(delta.affected_ranges, affected)
        elif dirty & DirtyDomain.TIMELINE_PIXELS and not sequence_handled:
            if affected:
                timing = bool(dirty & DirtyDomain.CUE_TIMING)
                for cue_id in affected:
                    page.timeline.invalidate_cue(cue_id, timing=timing)
            else:
                page.timeline.update()

        if dirty & DirtyDomain.QC:
            # Interactive razor/merge/delete/add edits touch a handful of cues.
            # The full QC rescan measured ~0.8-1.3s of GUI-thread time on a
            # real 976-cue project, which is exactly the post-edit freeze.
            # analyze_incremental recomputes the +/-2 neighbour window per
            # affected cue, so route small structural edits there and keep
            # full scans for bulk operations and first-time analysis.
            small_structural_edit = (
                dirty & DirtyDomain.CUE_MODEL
                and not dirty & DirtyDomain.SEQUENCE_STRUCTURE
                and len(affected) <= 64
                and hasattr(project, "_qc_result")
            )
            if small_structural_edit:
                page._pending_qc_cue_ids.update(affected)
            elif dirty & (DirtyDomain.CUE_MODEL | DirtyDomain.SEQUENCE_STRUCTURE):
                page._qc_full_scan_pending = True
                page._pending_qc_cue_ids.clear()
            else:
                page._pending_qc_cue_ids.update(affected)

        visual_dirty = dirty & (
            DirtyDomain.NATIVE_SUBTITLE
            | DirtyDomain.ADVANCED_PREVIEW
        )
        if visual_dirty:
            page._initial_preview_timer.stop()
            page._visual_update_timer.start()
            targets = affected or {self.session.selected_cue_id}
            for cue_id in targets:
                if cue_id:
                    page._schedule_render_refresh(cue_id)

        selected_id = self.session.selected_cue_id
        selected_affected = bool(selected_id and selected_id in affected)
        if selected_affected and not getattr(page,'_review_fast_select',False) and dirty & (
            DirtyDomain.CUE_CONTENT
            | DirtyDomain.CUE_TIMING
            | DirtyDomain.CUE_STYLE
            | DirtyDomain.CUE_MODEL
        ):
            self._select_cue_ui(
                selected_id,
                refresh_advanced=bool(dirty & DirtyDomain.ADVANCED_PREVIEW),
            )

        if dirty & DirtyDomain.CLIP_STATUS and hasattr(page, "highlight_panel"):
            sequence = sequence_of(project)
            page.highlight_panel.set_project_status(project, sequence.danmaku_path)
        if dirty & DirtyDomain.AUTOSAVE:
            page._schedule_autosave()
        if os.environ.get("TWOBYTEASR_DEBUG_SUBTITLES") == "1":
            page._dump_selection_render_truth_probe()

    def changed(self, *, refresh_advanced: bool = True) -> None:
        """Compatibility commit for low-frequency callers not yet typed."""

        project = self.session.project
        if project is None:
            return
        dirty = (
            DirtyDomain.CUE_MODEL
            | DirtyDomain.CUE_CONTENT
            | DirtyDomain.CUE_TIMING
            | DirtyDomain.CUE_STYLE
            | DirtyDomain.TIMELINE_INDEX
            | DirtyDomain.TIMELINE_PIXELS
            | DirtyDomain.NATIVE_SUBTITLE
            | DirtyDomain.QC
            | DirtyDomain.CLIP_STATUS
            | DirtyDomain.AUTOSAVE
        )
        if refresh_advanced:
            dirty |= DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.TRANSFORM
        with state_for(project).transaction(
            project,
            action_id="legacy_project_changed",
            dirty=dirty,
            affected_cue_ids=(cue.id for cue in project.cues),
        ):
            pass

    def model_changed(self) -> None:
        """Refresh a structural edit without invoking Remotion/FFmpeg.

        Adding, deleting, splitting, locking, or reordering timeline model
        data does not change the selected cue's visual recipe.  Those actions
        must stay process-free; an explicit style edit or later cue selection
        remains responsible for requesting an advanced preview.
        """
        project = self.session.project
        if project is None:
            return
        with state_for(project).transaction(
            project,
            action_id="legacy_model_changed",
            dirty=(
                DirtyDomain.CUE_MODEL
                | DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX
                | DirtyDomain.TIMELINE_PIXELS
                | DirtyDomain.NATIVE_SUBTITLE
                | DirtyDomain.QC
                | DirtyDomain.AUTOSAVE
            ),
            affected_cue_ids=(cue.id for cue in project.cues),
        ):
            pass

    def cue_changed(
        self,
        cue_id: str,
        *,
        timing: bool = False,
        columns: tuple[int, ...] | None = None,
    ) -> None:
        """Compatibility commit for direct single-cue mutations."""

        project = self.session.project
        if project is None:
            return
        dirty = (
            DirtyDomain.CUE_TIMING if timing else DirtyDomain.CUE_CONTENT
        ) | (
            DirtyDomain.TIMELINE_INDEX if timing else DirtyDomain.TIMELINE_PIXELS
        ) | DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.QC | DirtyDomain.AUTOSAVE
        with state_for(project).transaction(
            project,
            action_id="legacy_cue_changed",
            dirty=dirty,
            affected_cue_ids=(cue_id,),
        ):
            pass
        self.page._sync_loop_region_after_cue_change(cue_id)

    def set_text(
        self,
        cue_id: str,
        value: str,
        *,
        command_text: str = "Edit subtitle",
        origin: MutationOrigin = MutationOrigin.USER_EDIT,
    ) -> bool:
        project = self.session.project
        cue = self.session._cue_lookup.get(str(cue_id))
        if not project or cue is None or str(value) == cue.text:
            return False
        from .studio_commands import LEARNABLE_TEXT_ORIGINS

        if origin in LEARNABLE_TEXT_ORIGINS:
            self.page._manual_text_baselines.setdefault(cue.id, cue.text)
        self.session.undo_stack.push(
            SetCueFieldsCommand(
                project,
                cue.id,
                {"text": str(value)},
                command_text,
                lambda cue_id=cue.id: self.cue_changed(cue_id, columns=(3, 4)),
                origin,
                learning_observer=self.observe_learnable_text,
            )
        )
        if origin not in LEARNABLE_TEXT_ORIGINS:
            # AI / SafeFix / import text must never be attributed to the user:
            # advance the learning baseline so the debounced commit sees no diff.
            self.page._manual_text_baselines[cue.id] = str(value)
            return True
        self.page._manual_learning_timer.start()
        # Text/line edits never change manually authored timing. Overflow is
        # handled by layout and the explicit split action only.
        return True

    # ------------------------- glossary learning hooks -------------------------

    def observe_learnable_text(self, command, undone: bool) -> None:
        """Follow undo/redo of human text edits with learning evidence.

        Typing chains debounce through the existing timer; discrete actions
        (search & replace) carry ``learning_meta`` with their own token and
        explicit (needle, replacement) pair, so undo reverts exactly that
        action's evidence and redo re-records it idempotently.
        """
        from .studio_commands import BatchReplaceTextCommand

        meta = getattr(command, "learning_meta", None)
        project = self.session.project
        if meta is not None:
            token = str(meta.get("token") or "")
            pair = meta.get("pair") or ()
            origin = str(meta.get("origin") or "search_replace")
            if not token or len(pair) != 2:
                return
            if undone:
                self.page._learning_store.revert_evidence([token])
                return
            context = ""
            if isinstance(command, BatchReplaceTextCommand):
                for cue_id in command.after:
                    cue = self.session._cue_lookup.get(str(cue_id))
                    if cue is not None and cue.text:
                        context = cue.text[:240]
                        break
            else:
                cue = self.session._cue_lookup.get(str(command.cue_id))
                if cue is not None:
                    context = cue.text[:240]
            self.page._learning_store.record_manual_edit(
                str(pair[0]),
                str(pair[1]),
                project=str(self.session.project_path or (project.project_id if project else "")),
                context=context,
                origin=origin,
                source="studio_search_replace",
                token=token,
            )
            return
        if undone:
            # Typing chain undone: revert evidence whose resulting text no
            # longer holds, and move the baseline back to the restored text.
            before = command.before if isinstance(command.before, dict) else {}
            restored = str(before.get("text") or "")
            cue_id = str(getattr(command, "cue_id", "") or "")
            if not cue_id:
                return
            tokens = list(self.page._learning_evidence_tokens.get(cue_id, ()))
            if tokens:
                self.page._learning_store.revert_evidence(
                    tokens, cue_after_text=restored
                )
            self.page._manual_text_baselines[cue_id] = restored
            return
        before = command.before if isinstance(command.before, dict) else {}
        old_text = before.get("text")
        cue_id = str(getattr(command, "cue_id", "") or "")
        if cue_id and isinstance(old_text, str):
            self.page._manual_text_baselines.setdefault(cue_id, old_text)
        self.page._manual_learning_timer.start()

    def set_translation(self, cue_id: str, value: str) -> bool:
        project = self.session.project
        if not project:
            return False
        translations = project.generation_metadata.get("translations", {})
        current = (
            str(translations.get(cue_id, "") or "")
            if isinstance(translations, dict)
            else ""
        )
        if str(value) == current:
            return False
        self.session.undo_stack.push(
            SetCueTranslationCommand(
                project,
                cue_id,
                str(value),
                lambda cue_id=cue_id: self.cue_changed(cue_id, columns=()),
            )
        )
        return True

    def set_speaker(self, cue_id: str, speaker_id: str) -> bool:
        project = self.session.project
        cue = self.session._cue_lookup.get(str(cue_id))
        if not project or cue is None or not speaker_id or speaker_id == cue.speaker_id:
            return False
        self.session.undo_stack.push(
            SetCueFieldsCommand(
                project,
                cue.id,
                {"speaker_id": str(speaker_id)},
                "Change speaker",
                lambda cue_id=cue.id: self.cue_changed(
                    cue_id, timing=True, columns=(2, 4)
                ),
            )
        )
        return True

    def set_timing(self, cue_id: str, start: int, end: int) -> bool:
        project = self.session.project
        start, end = int(start), int(end)
        if not project:
            return False
        if end <= start:
            self.select_cue(cue_id)
            return False
        cue = self.session._cue_lookup.get(str(cue_id))
        if cue is None or (start, end) == (cue.start_ms, cue.end_ms):
            return False
        self.session.undo_stack.push(
            SetCueFieldsCommand(
                project,
                cue.id,
                {"start_ms": start, "end_ms": end},
                "Adjust timing",
                lambda cue_id=cue.id: self.cue_changed(
                    cue_id, timing=True, columns=(1, 4)
                ),
            )
        )
        return True

    def text_changed(self) -> None:
        cue_id = self.session.selected_cue_id
        if self.page._updating_editor or not self.session.project or not cue_id:
            return
        self.set_text(cue_id, self.page.cue_text.toPlainText())

    def commit_manual_term_learning(self, cue_id: str | None = None) -> None:
        from .glossary_learning import new_evidence_token

        project = self.session.project
        cue_id = str(cue_id or self.session.selected_cue_id or "")
        if not project or not cue_id:
            return
        cue = self.session._cue_lookup.get(cue_id)
        if cue is None:
            return
        page = self.page
        before = page._manual_text_baselines.get(cue_id, cue.text)
        after = cue.text
        if before == after:
            return
        cue_index = next(
            (index for index, item in enumerate(project.cues) if item.id == cue_id), -1
        )
        nearby = []
        if cue_index >= 0:
            nearby = [
                item.text
                for item in project.cues[max(0, cue_index - 1) : cue_index + 2]
                if item.text
            ]
        token = new_evidence_token()
        page._learning_store.record_manual_edit(
            before,
            after,
            project=str(self.session.project_path or project.project_id),
            speaker=page._studio_speaker_name(cue.speaker_id),
            context=" / ".join(nearby)[:240],
            origin=MutationOrigin.USER_EDIT,
            source="studio_manual_edit",
            token=token,
        )
        recorded = page._learning_evidence_tokens.setdefault(cue_id, [])
        if token not in recorded:
            recorded.append(token)
            del recorded[:-24]
        page._manual_text_baselines[cue_id] = after

    def translation_changed(self) -> None:
        cue_id = self.session.selected_cue_id
        if self.page._updating_editor or not self.session.project or not cue_id:
            return
        self.set_translation(cue_id, self.page.translation_text.toPlainText())

    def speaker_changed(self, _index: int) -> None:
        cue_id = self.session.selected_cue_id
        value = str(self.page.speaker.currentData() or "")
        if self.page._updating_editor or not self.session.project or not cue_id:
            return
        self.set_speaker(cue_id, value)

    def timing_fields_changed(self) -> None:
        cue_id = self.session.selected_cue_id
        if self.page._updating_editor or not self.session.project or not cue_id:
            return
        start = self.page.start_ms.value()
        self.set_timing(cue_id, start, start + self.page.duration_ms.value())

    def timeline_timing_changed(self, cue_id: str, start: int, end: int) -> None:
        self.set_timing(cue_id, start, end)

    def commit_timeline_edit(self, values) -> None:
        if self.session.project and values:
            self.session.undo_stack.push(EditCueIntervalsCommand(
                self.session.project, values, self.model_changed))

    def add_subtitle_at_playhead(self) -> None:
        with self.page._interaction_runtime_audit.measure("T new subtitle"):
            return self._add_subtitle_at_playhead()

    def _add_subtitle_at_playhead(self) -> None:
        project = self.session.project
        if not project:
            return
        page = self.page
        start = max(0, int(page.timeline.playhead_ms))
        duration = 2_000
        project_duration = int(project.media.duration_ms or 0)
        if project_duration:
            start = min(start, max(0, project_duration - duration))
        header = getattr(page.timeline, 'selected_track_header', None)
        speaker_id = header[1] if header and header[0] == 'subtitle' else ""
        if speaker_id in page.timeline.locked_speakers:
            bind_text(page.save_state, '轨道已锁定，请先解锁')
            return
        selected_id = self.session.selected_cue_id
        if selected_id and not speaker_id:
            current = self.session._cue_lookup.get(selected_id)
            speaker_id = current.speaker_id if current else ""
        if not speaker_id:
            ordered = page.timeline.speaker_ids()
            speaker_id = (
                ordered[-1]
                if ordered
                else (project.speakers[0].id if project.speakers else "S00")
            )
        style_id = "default"
        if selected_id:
            current = self.session._cue_lookup.get(selected_id)
            style_id = current.style_id if current else style_id
        cue = StudioCue(
            id=f"cue-{uuid.uuid4().hex[:10]}",
            start_ms=start,
            end_ms=start + duration,
            text="",
            original_text="",
            speaker_id=speaker_id,
            style_id=style_id,
        )
        previous_id = self.session.selected_cue_id
        self.session.undo_stack.push(add_cue_command(project, cue, self.model_changed))
        self.select_cue(cue.id, refresh_advanced=False)
        created = self.session._cue_lookup.get(cue.id)
        if created is not None:
            page._pending_new_cue_id = cue.id
            page._pending_new_cue_previous_id = previous_id
            page._pending_new_cue_undo_index = self.session.undo_stack.index()
            page._begin_canvas_inline_edit()

    def timeline_speaker_changed(
        self, cue_id: str, _old_speaker: str, new_speaker: str
    ) -> None:
        project = self.session.project
        if not project or not new_speaker:
            return
        cue = self.session._cue_lookup.get(cue_id)
        if cue is None or cue.speaker_id == new_speaker:
            return
        try:
            self.session.undo_stack.push(
                AssignSpeakerCommand(
                    project,
                    [cue_id],
                    new_speaker,
                    self.speaker_structure_changed,
                )
            )
        except (KeyError, ValueError):
            self.page.timeline.update()

    def timeline_text_edited(
        self, cue_id: str, translation: bool, value: str
    ) -> None:
        if not self.session.project:
            return
        self.select_cue(cue_id)
        if translation:
            self.set_translation(cue_id, value)
        else:
            self.set_text(cue_id, value)

    def nudge(self, delta: int) -> None:
        project = self.session.project
        cue_id = self.session.selected_cue_id
        if not project or not cue_id:
            return
        cue = cue_by_id(project, cue_id)
        start = max(0, cue.start_ms + int(delta))
        self.set_timing(cue.id, start, start + (cue.end_ms - cue.start_ms))

    def trim_to_playhead(self, edge: str) -> None:
        project = self.session.project
        if not project:
            return
        cue = self.explicit_edit_target()
        if cue is None:
            self.page._ripple_video_to_playhead(edge)
            return
        if len(self.selected_cue_ids()) != 1:
            bind_text(self.page.save_state, 'Q/W 边界编辑请只选中一条字幕')
            return
        if cue.speaker_id in self.page.timeline.locked_speakers:
            bind_text(self.page.save_state, '轨道已锁定，请先解锁')
            return
        point = int(self.page.timeline.playhead_ms)
        start, end = (point, cue.end_ms) if edge == 'start' else (cue.start_ms, point)
        if start < 0 or end - start < MIN_CUE_DURATION_MS:
            bind_text(self.page.save_state, '字幕时长不能小于 {MIN_CUE_DURATION_MS} 毫秒', MIN_CUE_DURATION_MS=MIN_CUE_DURATION_MS)
            return
        from .studio_edit_sequence import map_timing_to_source
        if map_timing_to_source(project, cue_by_id(project, cue.id), start, end) is None:
            bind_text(self.page.save_state, '字幕跨剪辑边界，无法无损调整时间')
            return
        self.set_timing(cue.id, start, end)

    def explicit_edit_target(self):
        """Manual cue selection, independent of the playback highlight."""
        page = self.page
        header = getattr(page.timeline, 'selected_track_header', None)
        if (not getattr(page, '_manual_selection_hold', False)
                or getattr(page.timeline, 'selected_video_clip_id', '')
                or (header and header[0] != 'subtitle')):
            return None
        return self.session._cue_lookup.get(self.session.selected_cue_id)

    def split_at(self, cue_id: str, split_ms: int) -> None:
        project = self.session.project
        if not project:
            return
        cue = cue_by_id(project, cue_id)
        # The timeline razor preview snaps and resolves before emitting, so
        # this value is already exactly what the preview card showed. Do NOT
        # snap again here: a second snap pass can shift a few ms and flip the
        # character rounding, producing a cut that differs from the preview.
        from .studio_edit_sequence import map_timing_to_source
        view = self.session.runtime.cue_by_id.get(cue_id, cue)
        preview = resolve_split(view, int(split_ms), project=project)
        if preview is None:
            bind_text(self.page.save_state, '切点位于首个或末个词内，无法分成两段文字')
            return
        mapped = map_timing_to_source(project, cue, preview.split_ms, preview.split_ms + 1)
        if mapped is None:
            bind_text(self.page.save_state, '切点跨剪辑边界，无法无损映射到原字幕')
            return
        self.session.undo_stack.push(
            split_cue_command(
                project,
                cue.id,
                mapped[0],
                preview.left_text,
                preview.right_text,
                self.model_changed,
            )
        )
        gap = (preview.right_word_start_ms or preview.split_ms) - preview.split_ms
        note = f' · 后段首词证据在切点后 {gap}ms，请试听' if gap > 0 else ''
        (bind_text(self.page.save_state, '已按字词分配文字，保留手动切点{value0}', value0=note) if preview.timing_source == 'exact_token_text' else bind_text(self.page.save_state, '缺少可匹配字词时间：文字按比例分配，请试听检查切点'))
        self.page._studio_trace('RazorTiming', cue_id=cue_id, timeline_cut=preview.split_ms,
                                stored_cut=mapped[0], source=preview.timing_source,
                                reason=preview.timing_reason, right_word_start=preview.right_word_start_ms)

    def split_current(self) -> None:
        project = self.session.project
        cue_id = self.session.selected_cue_id
        if not project or not cue_id:
            return
        cue = cue_by_id(project, cue_id)
        if len(cue.text) < 2:
            return
        view = self.session.runtime.cue_by_id.get(cue_id, cue)
        self.split_at(cue_id, (view.start_ms + view.end_ms) // 2)

    def merge_next(self) -> None:
        project = self.session.project
        cue_id = self.session.selected_cue_id
        if not project or not cue_id:
            return
        self.merge_with_neighbor(1)

    def merge_with_neighbor(self, direction: int) -> None:
        """Ripple merge: selected cue absorbs its previous/next neighbour.

        The merged cue keeps the earlier cue's id, so the selection lands on
        the merge result and repeated presses keep absorbing in direction.
        """
        project = self.session.project
        cue_id = self.session.selected_cue_id
        if not project or not cue_id:
            return
        ordered = sorted(
            project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id)
        )
        index = next(
            (position for position, cue in enumerate(ordered) if cue.id == cue_id),
            -1,
        )
        if index < 0:
            return
        target = index + (1 if direction > 0 else -1)
        if not 0 <= target < len(ordered):
            return
        self.merge_pair(cue_id, ordered[target].id)

    def merge_pair(self, first_id: str, second_id: str) -> None:
        """Merge two explicitly chosen cues (merge tool two-click flow)."""
        project = self.session.project
        if not project:
            return
        if not any(cue.id == first_id for cue in project.cues) or not any(
            cue.id == second_id for cue in project.cues
        ):
            return
        self.session.undo_stack.push(
            merge_cues_command(project, [first_id, second_id], self.model_changed)
        )

    def merge_with_next(self, cue_id: str) -> None:
        """Merge the given cue with its next neighbour (merge tool entry)."""
        project = self.session.project
        if not project or not cue_id:
            return
        index = next((i for i, cue in enumerate(project.cues) if cue.id == cue_id), -1)
        if index < 0 or index + 1 >= len(project.cues):
            return
        self.session.undo_stack.push(
            merge_cues_command(
                project,
                [project.cues[index].id, project.cues[index + 1].id],
                self.model_changed,
            )
        )

    def delete_current(self) -> None:
        project = self.session.project
        if not project:
            return
        selected_segments = set(self.page.timeline.selected_segment_ids)
        if selected_segments:
            sequence = sequence_of(project)
            targets = [
                segment.id
                for segment in sequence.segments
                if segment.id in selected_segments
            ]
            if not sequence.video_track_locked and targets:
                from .studio_track_delete import delete_clips
                from .studio_media_pool import primary_video_track_id
                delete_clips(self.page, primary_video_track_id(project), targets)
            return
        selected = set(self.selected_cue_ids())
        targets = [
            cue.id
            for cue in project.cues
            if cue.id in selected and cue.speaker_id not in self.page.timeline.locked_speakers
        ]
        if not targets:
            return
        target_set = set(targets)
        index = min(
            (i for i, cue in enumerate(project.cues) if cue.id in target_set),
            default=-1,
        )
        remaining = [cue.id for cue in project.cues if cue.id not in target_set]
        fallback = remaining[min(max(0, index), len(remaining) - 1)] if remaining else ""
        self.session.selected_cue_id = fallback
        self.session.undo_stack.push(
            delete_cues_command(project, targets, self.model_changed)
        )
        self.select_cue(fallback, refresh_advanced=False)
        self.page.ensure_active_subtitle_renderer(reason="bulk_delete")

    def apply_timing_offset(self, cue_ids: list[str], offset_ms: int) -> None:
        project = self.session.project
        if not project or not cue_ids:
            return
        try:
            self.session.undo_stack.push(
                set_cues_timing_offset_command(
                    project, cue_ids, offset_ms, changed=self.changed
                )
            )
            self.page._show_studio_hint(tr('已整体偏移 {value0:+d}ms（{value1} 条）', value0=offset_ms, value1=len(cue_ids)))
        except ValueError as exc:
            self.page._show_studio_hint(str(exc))

    def table_activated(self, index) -> None:
        cue_id = self.page.cue_model.data(
            self.page.cue_model.index(index.row(), 0), Qt.ItemDataRole.UserRole
        )
        if cue_id and self.session.project:
            self.select_cue(cue_id)
            cue = cue_by_id(self.session.project, cue_id)
            self.page._seek(cue.start_ms / 1000.0)
