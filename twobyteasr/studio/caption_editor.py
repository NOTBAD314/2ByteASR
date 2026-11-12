"""One bound text transaction for original, associated and imported captions."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import ChainMap
from time import perf_counter
import json
import uuid
from PySide6.QtCore import QEvent, Qt, Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QTextCursor, QUndoCommand
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QHBoxLayout, QWidget, QVBoxLayout

from .review_marked_text import ReviewMarkedText, MORE, BASE
from ..subtitle_rules.current_issues import (DECISIONS, current_issue_view, digest, invalidate,
    suggestion_identity, patch_identity, suggestion_handled)
from ..subtitle_rules.review_suggestions import review_suggestions, PRONOUN
from ..subtitle_rules.pronouns import pronoun_positions, toggle_pronoun
from .caption_split_editor import CaptionSplitEditorMixin


def py_position(text, qt_position):
    return len(text.encode("utf-16-le")[:max(0, qt_position)*2].decode("utf-16-le", errors="ignore"))


def qt_position(text, position):
    return len(text[:position].encode("utf-16-le")) // 2


@dataclass(frozen=True)
class CaptionEditTarget:
    project_id: str
    cue_id: str
    track_id: str
    layer: str
    language: str
    role: str

    def resolve(self, project):
        if project is None or project.project_id != self.project_id:
            return None
        from ..projects.studio_runtime_state import state_for
        return state_for(project).cue_by_id.get(self.cue_id)

    def read(self, project):
        cue = self.resolve(project)
        if cue is None:
            return None
        if self.layer == "translation":
            from ..subtitle_rules.subtitle_translation import container_target, records_of
            if container_target(project) != self.language:
                return None
            record = records_of(project).get(cue.id, {})
            rendered = project.generation_metadata.get("translations", {}).get(cue.id, "")
            # The compatibility writer can update the render entry before
            # records are reconciled. Match the existing migration contract.
            return str(rendered if str(rendered or '').strip() else record.get('text') or '')
        return cue.text

    @property
    def render_id(self):
        if self.layer == "translation":
            from ..caption_style.bilingual_layout import companion_id
            return companion_id(self.cue_id)
        return self.cue_id


@dataclass
class CaptionDraft:
    project: object
    target: CaptionEditTarget
    before: str
    suggestions: tuple = ()
    suggestion_text: str = ""
    ignored: dict = field(default_factory=dict)
    actions: list = field(default_factory=list)
    session_generation: int | None = None
    edit_session_id: str = field(default_factory=lambda: 'edit-' + uuid.uuid4().hex[:16])
    opened_revision: int = 0
    entity_epoch: int = 0
    state: str = 'editing'
    revision: int = 0
    text: str = ''

    def owns(self, project, generation):
        return (self.state in {'editing', 'rejected'}
                and project is not None and project.project_id == self.target.project_id
                and (generation == self.session_generation if self.session_generation is not None
                     else project is self.project))

    def suggestion_key(self, row):
        return suggestion_identity(self.target.__dict__, row)


class IssueDecisionsCommand(QUndoCommand):
    def __init__(self, project, changes, changed=None, *, prepared_issue_views=None):
        super().__init__("处理当前建议")
        self.project, self.after, self.changed = project, dict(changes), changed
        decisions = project.studio_state.get(DECISIONS, {})
        self._container_present = DECISIONS in project.studio_state
        self.before = {key: decisions.get(key) for key in changes}
        self.prepared_issue_views = prepared_issue_views

    def _apply(self, values):
        from ..projects.studio_runtime_state import state_for, DirtyDomain
        with state_for(self.project).transaction(self.project, action_id=self.text(),
                dirty=DirtyDomain.AUTOSAVE, affected_cue_ids=(), snapshot_cues=False):
            decisions = dict(self.project.studio_state.get(DECISIONS, {}))
            for key, value in values.items():
                if value is None:
                    decisions.pop(key, None)
                else:
                    decisions[key] = dict(value)
            if decisions or self._container_present:
                self.project.studio_state[DECISIONS] = decisions
            else:
                self.project.studio_state.pop(DECISIONS, None)
            invalidate(self.project)
        if self.prepared_issue_views is not None:
            from ..subtitle_rules.current_issues import adopt_acknowledged_view
            adopt_acknowledged_view(self.project, self.prepared_issue_views, undo=values is self.before)
        if self.changed:
            self.changed()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


# Compatibility name for integrations that access the editor suggestion view.
from .caption_editor_panel import CaptionSuggestionView as SuggestionText


class CaptionEditorMixin(CaptionSplitEditorMixin):
    def _remember_canvas_edit_target(self, cue_id, layer):
        if layer not in {'original','translation'}:
            return
        target=self._resolve_caption_edit_target(cue_id,layer)
        if target is not None:
            # Text targeting does not narrow the transform/clip multi-selection.
            if self.timeline.active_subtitle_layer != layer:
                self.timeline.set_subtitle_layer(layer)
            self._caption_canvas_edit_target=(id(self.project),self.session.generation,target)

    def _edit_caption_from_canvas(self):
        panel=getattr(self,'caption_transform_panel',None)
        if panel is not None:
            self._remember_canvas_edit_target(self.selected_cue_id,panel.language.currentData())
        self._begin_canvas_inline_edit()

    def _install_caption_editor_tools(self):
        if getattr(self, '_caption_tools_installed', False):
            return
        panel = self.subtitle_edit_card
        self.caption_suggestion_text = panel.suggestions
        self.caption_reference = panel.reference
        self.caption_reference_button = panel.reference_button
        self.caption_pronoun_button = panel.pronoun_button
        self.caption_ignore_button = panel.ignore_button
        self.caption_editor_hint = panel.hint
        self.caption_editor_error = panel.error_label
        self.caption_cancel_button = panel.cancel_button
        self.caption_confirm_button = panel.confirm_button
        self.caption_editor_tools = panel
        panel.suggestions.activated.connect(self._apply_editor_suggestion)
        panel.suggestions.location_requested.connect(self._locate_caption_suggestion)
        panel.pronoun_button.clicked.connect(self._flip_editor_pronoun)
        panel.ignore_button.clicked.connect(self._ignore_editor_suggestion)
        panel.cancel_button.clicked.connect(self._cancel_canvas_inline_edit)
        panel.confirm_button.clicked.connect(lambda: self._caption_trigger_commit('button'))
        panel.copy_draft_button.clicked.connect(lambda: QApplication.clipboard().setText(self.subtitle_edit_input.toPlainText()))
        panel.reload_current_button.clicked.connect(self._reload_current_caption_text)
        panel.split_button.clicked.connect(self._split_caption_at_cursor)
        panel.split_mode.toggled.connect(lambda checked: self._lock_caption_editor())
        panel.split_previous.clicked.connect(lambda: self._navigate_split_part(-1))
        panel.split_next.clicked.connect(lambda: self._navigate_split_part(1))
        panel.split_undo.clicked.connect(lambda: self._undo_caption_split())
        panel.split_redo.clicked.connect(lambda: self._undo_caption_split(redo=True))
        self._caption_tools_installed = True

    def _locate_caption_suggestion(self, start, end):
        self._lock_caption_editor()
        text = self.subtitle_edit_input.toPlainText()
        cursor = self.subtitle_edit_input.textCursor()
        cursor.setPosition(qt_position(text, start))
        cursor.setPosition(qt_position(text, end), QTextCursor.MoveMode.KeepAnchor)
        self.subtitle_edit_input.setTextCursor(cursor)

    def _resolve_caption_edit_target(self, cue_id=None, layer=None):
        if not self.project:
            return None
        remembered=getattr(self,'_caption_canvas_edit_target',None)
        if (cue_id is None and layer is None and remembered is not None
                and remembered[:2]==(id(self.project),self.session.generation)
                and remembered[2].cue_id == (self.timeline.explicit_subtitle_id or self.timeline.selected_id or self.selected_cue_id)
                and remembered[2].layer == self.timeline.active_subtitle_layer
                and remembered[2].read(self.project) is not None):
            return remembered[2]
        timeline = self.timeline
        layer = layer or timeline.active_subtitle_layer
        cue_id = cue_id or timeline.explicit_subtitle_id or timeline.selected_id or self.selected_cue_id
        from ..timeline.studio_commands import cue_by_id
        try:cue=cue_by_id(self.project,str(cue_id))
        except KeyError:return None
        from ..projects.subtitle_import import imported_track
        from ..subtitle_rules.current_issues import _language
        track = imported_track(self.project, cue.speaker_id)
        role = "translation" if layer == "translation" else track.get("role", "original")
        return CaptionEditTarget(self.project.project_id, cue.id, cue.speaker_id, layer,
                                 _language(self.project, cue, layer), role)

    def _open_caption_editor(self, cue_id=None, layer=None):
        if getattr(self, '_caption_submitting', False) or getattr(self, '_caption_ending', False):
            return False
        if getattr(self, '_caption_following', False) and cue_id is None and layer is None:
            return
        target = self._resolve_caption_edit_target(cue_id, layer)
        if target is None:
            return
        previous = getattr(self, '_caption_draft', None)
        if self._caption_owns_draft(previous):
            if previous.target == target: return
            if (target.track_id in self.timeline.locked_speakers or
                    target.layer == 'translation' and 'translation' in self.timeline.locked_speakers):
                self.save_state.setText('轨道已锁定，请先解锁')
                return
            if getattr(self.subtitle_edit_input, '_preediting', False):
                self.caption_editor_hint.setText('请先完成输入法选字，再切换字幕')
                return
            if (self.subtitle_edit_input.toPlainText() != previous.before or previous.actions):
                if not self._submit_caption_draft(): return
        self._caption_following = True
        self.subtitle_edit_card.split_mode.setChecked(False)
        self.subtitle_edit_card.split_playhead.setChecked(False)
        self.subtitle_edit_card.split_status.clear()
        self._caption_edit_locked = False
        self._caption_disk_pending = None
        self._caption_follow_track = target.track_id
        self._caption_follow_layer = target.layer
        self._caption_follow_fallback_original = False
        if not self._bind_caption_editor(target):
            self._caption_following = False
            return
        self.subtitle_edit_card.title.setText('跟随 · 译文' if target.role == 'translation' else '跟随 · 原文')
        self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _bind_caption_editor(self, target, *, edit_session_id=None):
        # Keep the reused native tool atomic while its target, marks and final
        # geometry are prepared. No hide/show, focus grab or event pumping.
        dock = self.subtitle_edit_dock
        dock.setUpdatesEnabled(False)
        try:
            return self._bind_caption_editor_content(target, edit_session_id=edit_session_id)
        finally:
            dock.setUpdatesEnabled(True)
            dock.update()

    def _bind_caption_editor_content(self, target, *, edit_session_id=None):
        started = perf_counter()
        if target is None:
            self.save_state.setText("当前没有可编辑字幕")
            return False
        cue = target.resolve(self.project)
        if cue is None:
            return False
        target = replace(target, track_id=cue.speaker_id)
        if cue.speaker_id in self.timeline.locked_speakers or (target.layer == "translation" and "translation" in self.timeline.locked_speakers):
            self.save_state.setText("轨道已锁定，请先解锁")
            return False
        text = target.read(self.project)
        if text is None:
            return False
        self._install_caption_editor_tools()
        previous = getattr(self, '_caption_draft', None)
        if previous is not None:
            previous.state = 'retired'
        timer = getattr(self, '_caption_suggestion_timer', None)
        if timer is not None:
            timer.stop()
        self._edit_preview_timer.stop()
        if previous is not None:
            self._live_edit_text_overrides.pop(previous.target.render_id, None)
        draft = CaptionDraft(self.project, target, text, text=text)
        from ..projects.studio_runtime_state import state_for
        runtime = state_for(self.project)
        draft.session_generation = self.session.generation
        draft.opened_revision = runtime.revision
        draft.entity_epoch = runtime.entity_epochs.get(target.cue_id, 0)
        if edit_session_id:
            draft.edit_session_id = edit_session_id
        self._caption_draft = draft
        self._caption_follow_bind_ms = int(self.timeline.playhead_ms)
        self._caption_follow_clock_generation = getattr(getattr(self.video, '_playback_clock', None), 'generation', None)
        self._review_edit_lock = None
        self._canvas_editor = self.subtitle_edit_input
        editor = self._canvas_editor
        self._reset_caption_input_method()
        self.subtitle_edit_card.reset()
        editor._diagnostic_context = dict(edit_session_id=draft.edit_session_id, project_id=target.project_id, cue_id=target.cue_id,
                                          track_id=target.track_id, layer=target.layer, language=target.language)
        self._caption_editor_opening = True
        editor.setEnabled(True)
        editor.setPlaceholderText('')
        self.caption_confirm_button.setEnabled(True)
        editor.setPlainText(text)
        editor.moveCursor(QTextCursor.MoveOperation.End)
        from ..projects.subtitle_import import language_label
        from .studio_cue_table import _speaker_name
        from .studio_helpers import _format_ms
        self.subtitle_edit_title.setText("编辑译文" if target.role == 'translation' else "编辑原文")
        self.subtitle_edit_card.role.setText(language_label(target.language))
        self.subtitle_edit_card.role.show()
        from ..projects.subtitle_import import imported_track
        imported = bool(imported_track(self.project, cue.speaker_id))
        origin = ' · 独立导入' if imported else ''
        self.subtitle_edit_card.meta.setText(
            f"{_speaker_name(self.project, cue.speaker_id)}{origin} · {_format_ms(cue.start_ms)}–{_format_ms(cue.end_ms)}")
        self.caption_reference.setText("同条原文（只读）：" + cue.text if target.layer == "translation" else "")
        self.caption_reference.setToolTip(cue.text if target.layer == "translation" else "")
        self.caption_reference.hide()
        self.caption_reference_button.setVisible(target.layer == "translation")
        self.position_overlay._inline_editing = True
        self.position_overlay.hide()
        self.caption_suggestion_text.hide()
        self.caption_ignore_button.hide()
        self.caption_pronoun_button.setEnabled(True)
        self._caption_editor_opening = False
        self._update_split_controls()
        self._set_subtitle_editor_visible(True)
        self._schedule_caption_suggestions(delay=0)
        self._studio_trace('EDIT_CARD_OPEN', cue_id=target.cue_id, layer=target.layer,
                           editor_show_ms=(perf_counter()-started)*1000)
        from ..diagnostics.event_log import emit
        emit('caption.edit_open', **self._caption_edit_context(draft), result='opened')
        return True

    def _caption_owns_draft(self, draft):
        return draft is not None and draft.owns(self.project, self.session.generation)

    def _caption_trigger_commit(self, trigger):
        previous = getattr(self, '_caption_submit_trigger', None)
        self._caption_submit_trigger = trigger
        try:
            return self._commit_canvas_inline_edit()
        finally:
            self._caption_submit_trigger = previous

    def _caption_edit_context(self, draft, value=None):
        from ..diagnostics.studio_events import revision
        project = self.project
        cue = draft.target.resolve(project)
        current = draft.target.read(project)
        runtime = getattr(project, '_studio_state_runtime', None)
        scene=getattr(self,'_caption_scene',None)
        locks = self.timeline.locked_speakers
        lock_sources = [key for key in (cue.speaker_id if cue else draft.target.track_id,
                       'translation' if draft.target.layer == 'translation' else None) if key in locks]
        def text_summary(text):
            return dict(length=len(text), digest=digest(text)) if text is not None else None
        return dict(edit_session_id=draft.edit_session_id, **draft.target.__dict__,
                    project_format_version=getattr(project,'schema_version',None),
                    session_generation=self.session.generation, opened_generation=draft.session_generation,
                    opened_revision=draft.opened_revision, revision_current=revision(project),
                    render_revision=getattr(runtime, 'playback_revision', None),
                    opened_entity_epoch=draft.entity_epoch,
                    entity_epoch=getattr(runtime, 'entity_epochs', {}).get(draft.target.cue_id, 0),
                    target_resolved=cue is not None, current_track_id=cue.speaker_id if cue else None,
                    track_locked=bool(lock_sources), lock_sources=lock_sources,
                    baseline_summary=text_summary(draft.before), current_summary=text_summary(current),
                    submitted_summary=text_summary(value),
                    trigger=getattr(self, '_caption_submit_trigger', None) or 'project_save',
                    autosave_generation=getattr(self, '_autosave_generation', None),
                    scene_generation=scene.token[3] if scene is not None and scene.token is not None else None,
                    playback_generation=getattr(getattr(self.video,'_playback_clock',None),'generation',None))

    def _reload_current_caption_text(self):
        draft = getattr(self, '_caption_draft', None)
        if not self._caption_owns_draft(draft) or draft.target.read(self.project) is None:
            return
        # This explicit action gives the user a recoverable copy before rebase.
        QApplication.clipboard().setText(self.subtitle_edit_input.toPlainText())
        self._bind_caption_editor(draft.target, edit_session_id=draft.edit_session_id)
        self._lock_caption_editor()
        self.save_state.setText('草稿已复制；已载入当前文本，可继续编辑。')

    def _lock_caption_editor(self):
        draft = getattr(self, '_caption_draft', None)
        if draft is not None and not getattr(self, '_caption_editor_opening', False):
            self._caption_edit_locked = True
            self._review_edit_lock = dict(cue_id=draft.target.cue_id, project=self.project, layer=draft.target.layer)
            self.subtitle_edit_card.title.setText('编辑译文' if draft.target.role == 'translation' else '编辑原文')

    def _follow_caption_editor(self, milliseconds, *, force=False, clock_sample=False):
        if self._subtitle_navigation_holds_editor():
            return
        if (not getattr(self, '_caption_following', False) or not self.project
                or getattr(self, '_caption_edit_locked', False) or getattr(self, '_caption_submitting', False)):
            return
        draft = getattr(self, '_caption_draft', None)
        if (not force and self._caption_owns_draft(draft)
                and int(milliseconds) == getattr(self, '_caption_follow_bind_ms', None)):
            return  # an unchanged clock sample cannot erase a just-bound target
        from ..projects.studio_runtime_state import state_for
        hidden, locked = self.timeline.hidden_speakers, self.timeline.locked_speakers
        draft = getattr(self, '_caption_draft', None)
        if clock_sample and not force and self._caption_owns_draft(draft):
            cue = draft.target.resolve(self.project)
            generation = getattr(getattr(self.video, '_playback_clock', None), 'generation', None)
            if (cue is not None and getattr(self.video, '_paused', True)
                    and generation == getattr(self, '_caption_follow_clock_generation', None)
                    and not cue.start_ms <= int(milliseconds) < cue.end_ms
                    and cue.speaker_id not in hidden and cue.speaker_id not in locked):
                # A passive sample from before the just-bound paused target
                # cannot clear/rebind it. A real seek has a new generation;
                # direct navigation and normal running playback still follow.
                return
        layer = getattr(self, '_caption_follow_layer', 'original')
        candidates = [c for c in state_for(self.project).cues_at(int(milliseconds))
                      if c.speaker_id not in hidden and c.speaker_id not in locked
                      and getattr(self, '_subtitle_track_visibility', {}).get(c.speaker_id, True)]
        fallback = getattr(self, '_caption_follow_fallback_original', False)
        if layer == 'translation' and 'translation' in locked and not fallback:
            candidates = []
        order = {key: i for i, key in enumerate(self.timeline._speaker_ids)}
        preferred = getattr(self, '_caption_follow_track', '')
        cue = min(candidates, key=lambda c: (c.speaker_id != preferred, order.get(c.speaker_id, len(order)),
                                            c.speaker_id, -c.start_ms, c.id)) if candidates else None
        draft = getattr(self, '_caption_draft', None)
        target = self._resolve_caption_edit_target(cue.id, layer) if cue is not None else None
        if target is not None and layer == 'translation' and fallback and (
                'translation' in locked or 'translation' in hidden
                or not getattr(self, '_subtitle_track_visibility', {}).get('translation', True)
                or not str(target.read(self.project) or '').strip()):
            target = self._resolve_caption_edit_target(cue.id, 'original')
        draft = getattr(self, '_caption_draft', None)
        if not force and ((draft is None and target is None) or
                          (self._caption_owns_draft(draft) and draft.target == target)):
            return
        self._clear_caption_binding()
        if target is not None:
            self._bind_caption_editor(target)
            self.subtitle_edit_card.title.setText('跟随 · 译文' if target.role == 'translation' else '跟随 · 原文')
        else:
            self._install_caption_editor_tools()
            self.subtitle_edit_card.reset()
            self.subtitle_edit_title.setText('当前位置无字幕')
            self.subtitle_edit_card.meta.clear()
            self.subtitle_edit_card.role.clear()
            self.subtitle_edit_card.role.hide()
            self.subtitle_edit_input.setPlaceholderText('当前位置无字幕')
            self.caption_reference.clear()
            self.subtitle_edit_input.setEnabled(False)
            self.caption_confirm_button.setEnabled(False)
            self.caption_pronoun_button.setEnabled(False)
            self.caption_reference_button.hide()
            self.caption_ignore_button.hide()

    def _caption_window_owns(self, widget):
        window = getattr(self, 'subtitle_edit_dock', None)
        while widget is not None:
            if widget is window:
                return True
            widget = widget.parentWidget()
        return False

    def _caption_float_event(self, watched, event):
        """Observe before dispatch; never swallow or replay an external click."""
        if not getattr(self, '_caption_following', False):
            return
        from PySide6.QtWidgets import QWidget
        if not isinstance(watched, QWidget):
            return
        kind = event.type()
        editor = self.subtitle_edit_input
        inside = self._caption_window_owns(watched)
        if inside:
            if kind == QEvent.Type.FocusOut and (watched is editor or editor.isAncestorOf(watched)):
                draft = getattr(self, '_caption_draft', None)
                QTimer.singleShot(0, lambda: self._caption_focus_out(draft))
            if ((watched is editor or editor.isAncestorOf(watched)) and kind in
                    {QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress, QEvent.Type.InputMethod}):
                self._lock_caption_editor()
            elif kind == QEvent.Type.MouseButtonPress and (watched is self.caption_suggestion_text or
                    self.caption_suggestion_text.isAncestorOf(watched) or watched in
                    {self.caption_pronoun_button, self.caption_ignore_button}):
                self._lock_caption_editor()
        elif kind == QEvent.Type.MouseButtonPress and self.isVisible():
            if getattr(self, '_save_capture_in_progress', False):
                return
            popup = QApplication.activePopupWidget()
            if popup is not None and self._caption_window_owns(popup):
                return
            # Native IME candidate windows never reach this QWidget branch.
            self._end_caption_editor(keep_open=False, restore_focus=False)

    def _caption_focus_out(self, draft):
        from ..diagnostics.event_log import emit
        emit('caption.focus_transfer', module=__name__,
             focused_widget=type(QApplication.focusWidget()).__name__,
             draft_current=getattr(self, '_caption_draft', None) is draft,
             capture_running=getattr(self, '_save_capture_in_progress', False),
             ending=getattr(self, '_caption_ending', False),
             popup_widget=type(QApplication.activePopupWidget()).__name__,
             preediting=getattr(self.subtitle_edit_input, '_preediting', False))
        if (draft is None or getattr(self, '_caption_draft', None) is not draft
                or getattr(self, '_caption_ending', False) or getattr(self, '_save_capture_in_progress', False)):
            return
        focus = QApplication.focusWidget()
        if focus is None or self._caption_window_owns(focus):
            return
        popup = QApplication.activePopupWidget()
        if popup is not None or getattr(self.subtitle_edit_input, '_preediting', False):
            return
        self._end_caption_editor(keep_open=False, restore_focus=False)

    def _clear_caption_binding(self, *, terminal_state='retired'):
        draft = getattr(self, '_caption_draft', None)
        if draft is not None:
            draft.state = terminal_state
        self._edit_preview_timer.stop()
        timer = getattr(self, '_caption_suggestion_timer', None)
        if timer is not None: timer.stop()
        self._draft_recovery.discard()
        if draft is not None:
            had_preview = draft.target.render_id in self._live_edit_text_overrides
            self._live_edit_text_overrides.pop(draft.target.render_id, None)
            if had_preview:
                self._caption_transform_preview_serial = getattr(self, '_caption_transform_preview_serial', 0) + 1
        self._caption_draft = None
        self._canvas_editor = None
        self._review_edit_lock = None
        self._caption_edit_locked = False
        self._reset_caption_input_method()
        self._caption_editor_opening = True
        blocker = QSignalBlocker(self.subtitle_edit_input)
        try:
            self.subtitle_edit_input.clear()
        finally:
            del blocker
            self._caption_editor_opening = False

    def _cancel_bound_caption_editor(self, *, trigger='cancel'):
        """Retire the draft before hiding/resetting widgets can dispatch events."""
        draft = getattr(self, '_caption_draft', None)
        if draft is None and not getattr(self, '_caption_following', False):
            return False
        context = self._caption_edit_context(draft, self.subtitle_edit_input.toPlainText()) if draft else {}
        undo_index, undo_count = self.undo_stack.index(), self.undo_stack.count()
        self._caption_following = False
        self._caption_disk_pending = None
        self._cancel_split_session()
        self._clear_caption_binding(terminal_state='cancelled')
        self.position_overlay._inline_editing = False
        self._set_subtitle_editor_visible(False)
        if not self._present_caption_scene():self._refresh_ass_preview()
        self.timeline.setFocus(Qt.FocusReason.OtherFocusReason)
        from ..diagnostics.event_log import emit
        context['trigger'] = trigger
        emit('caption.edit_cancelled', **context, result='discarded', stage='closed',
             undo_index_before=undo_index, undo_index_after=self.undo_stack.index(),
             undo_count_before=undo_count, undo_count_after=self.undo_stack.count())
        return True

    def _end_caption_editor(self, *, keep_open, restore_focus=True):
        if getattr(self, '_caption_ending', False):
            return False
        self._caption_ending = True
        try:
            if getattr(self.subtitle_edit_input, '_preediting', False):
                QApplication.inputMethod().commit()
                if getattr(self.subtitle_edit_input, '_preediting', False):
                    self._caption_editor_failed('请先完成输入法选字，再重试保存')
                    return False
            if getattr(self, '_caption_draft', None) is not None:
                self._caption_edit_locked = True
                if not self._submit_caption_draft():
                    return False
            if keep_open:
                self._caption_following = True
                self._caption_edit_locked = False
                self._follow_caption_editor(self.timeline.playhead_ms, force=True)
                self._set_subtitle_editor_visible(True)
            else:
                self._caption_following = False
                self._clear_caption_binding()
                self.position_overlay._inline_editing = False
                self._set_subtitle_editor_visible(False)
            if restore_focus:
                self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return True
        finally:
            self._caption_ending = False

    def _schedule_caption_suggestions(self, *, delay=80):
        draft = getattr(self, '_caption_draft', None)
        if not self._caption_owns_draft(draft): return
        timer = getattr(self, '_caption_suggestion_timer', None)
        if timer is None:
            timer = self._caption_suggestion_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._deliver_caption_suggestions)
        self._caption_suggestion_request = (draft, draft.revision)
        timer.start(delay)

    def _deliver_caption_suggestions(self):
        draft, revision = self._caption_suggestion_request
        self._refresh_editor_suggestions(expected_draft=draft, expected_revision=revision)

    def _refresh_editor_suggestions(self, *, expected_draft=None, expected_revision=None):
        draft = getattr(self, "_caption_draft", None)
        if (expected_draft is not None and draft is not expected_draft
                or expected_revision is not None and (draft is None or draft.revision != expected_revision)):
            return
        if not self._caption_owns_draft(draft):
            return
        text = self.subtitle_edit_input.toPlainText()
        if draft.suggestion_text and text!=draft.suggestion_text:
            # A manual change is a new input. Do not carry old model offsets
            # or decisions across it. Local glossary checks are rerun below.
            draft.actions.clear();draft.ignored.clear();draft.suggestions=()
        rows = []
        if text==draft.suggestion_text:
            rows.extend(draft.suggestions)
        # Stored candidates are valid only for the complete text they describe.
        if text == draft.target.read(self.project):
            for issue in current_issue_view(self.project).for_cue(draft.target.cue_id, layer=draft.target.layer):
                rows.extend(issue.suggestions)
            if draft.target.layer=='original':
                from ..subtitle_rules.studio_qc import review_candidates
                cue=draft.target.resolve(self.project)
                if cue is not None:
                    rows.extend(r for r in self._review_suggestions_for(cue,review_candidates(self.project,cue)) if r.kind!=PRONOUN)
        if draft.target.layer!='original' or text!=draft.target.read(self.project):
            rows.extend(review_suggestions(text, resolver=self._review_term_resolver(), pronouns=False))
        decisions = self.project.studio_state.get(DECISIONS, {})
        combined_decisions=ChainMap(draft.ignored,decisions)
        unique = {}
        from ..subtitle_rules.review_suggestions import validated_suggestion
        from ..subtitle_rules.current_issues import unhandled_suggestion
        for row in rows:
            row = validated_suggestion(text, row)
            if row is not None and text == draft.target.read(self.project):
                row=unhandled_suggestion(self.project,draft.target.cue_id,draft.target.layer,row)
            if row is None: continue
            key = draft.suggestion_key(row)
            if suggestion_handled(draft.target.__dict__,row,text,combined_decisions):
                continue
            unique[key] = row
        draft.suggestions = tuple(sorted(unique.values(), key=lambda r: (r.start, r.end)))
        draft.suggestion_text = text
        self.caption_suggestion_text.update_rows(text, draft.suggestions)
        self.caption_suggestion_text.setVisible(self.caption_suggestion_text.has_rows())
        self.caption_ignore_button.setVisible(bool(draft.suggestions))
        self.caption_pronoun_button.setEnabled(True)
        self.subtitle_edit_card.update_hint()

    def _apply_editor_suggestion(self, mark=None, option=None):
        draft = getattr(self, "_caption_draft", None)
        if not self._caption_owns_draft(draft) or getattr(self.subtitle_edit_input, '_preediting', False):
            return False
        text = self.subtitle_edit_input.toPlainText()
        if text != draft.suggestion_text:
            self._schedule_caption_suggestions(delay=0)
            return False
        if mark is None:
            mark, option = self.caption_suggestion_text.selected
        if not 0 <= int(mark) < len(draft.suggestions):
            return False
        row = draft.suggestions[int(mark)]
        from ..recognition.asr_source_evidence import current_suggestion_option
        if not current_suggestion_option(self.project,draft.target.resolve(self.project),row,int(option or 0)):return False
        value = row.apply(text, int(option or 0))
        if value == text:
            return False
        return self._stage_caption_patch(row.start,row.end,row.options[int(option or 0)].text,
            kind=row.kind,options={row.original,*(o.text for o in row.options)})

    def _stage_caption_patch(self,start,end,replacement,*,kind='model',options=()):
        self._lock_caption_editor()
        draft=getattr(self,'_caption_draft',None)
        if not self._caption_owns_draft(draft):
            return False
        editor=self.subtitle_edit_input;text=editor.toPlainText()
        if text != draft.suggestion_text:
            # A cold first click must not synchronously build the project QC
            # view. Retire stale offsets; the command edits this draft now.
            draft.actions.clear(); draft.ignored.clear(); draft.suggestions = ()
            draft.suggestion_text = text
            self.caption_suggestion_text.update_rows(text, ())
        value=text[:start]+replacement+text[end:]
        if value==text:return False
        from ..subtitle_rules.machine_text_policy import machine_text_allowed
        if kind != 'pronoun' and not machine_text_allowed(text,value):return False
        self.caption_suggestion_text.stage_patch(start, end, replacement, value)
        delta=len(replacement)-(end-start)
        def shifted(a,b):
            if a==b and a in {start,end}:return None
            if b<=start:return a,b
            if a>=end:return a+delta,b+delta
            return None
        remaining=[]
        for row in draft.suggestions:
            location=shifted(row.start,row.end)
            if location is not None and value[location[0]:location[1]]==row.original:
                remaining.append(replace(row,start=location[0],end=location[1]))
        actions=[]
        for action in draft.actions:
            location=shifted(action['start'],action['end'])
            if action['input_text']==text and location is not None and value[location[0]:location[1]]==action['expected']:
                actions.append(dict(action,start=location[0],end=location[1],input_text=value))
        actions.append(dict(start=start,end=start+len(replacement),expected=replacement,
            kind='model' if kind=='pronoun' else kind,options=tuple(sorted(set(options))),status='resolved',input_text=value))
        draft.actions=actions
        draft.suggestions=tuple(remaining);draft.suggestion_text=value
        draft.ignored=self._draft_patch_decisions(draft,value,only_ignored=True)
        cursor=editor.textCursor();cursor.setPosition(qt_position(text,start))
        cursor.setPosition(qt_position(text,end),QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement);editor.setTextCursor(cursor)
        return True

    @staticmethod
    def _draft_patch_decisions(draft,text,*,only_ignored=False):
        changes={}
        for action in draft.actions:
            if (action['input_text']!=text or text[action['start']:action['end']]!=action['expected']
                    or only_ignored and action['status']!='ignored'):
                continue
            key=patch_identity(draft.target.__dict__,action['start'],action['end'],action['expected'],action['kind'])
            changes[key]=dict(input_version=digest(text),status=action['status'],options=list(action['options']))
        return changes

    def _ignore_editor_suggestion(self):
        self._lock_caption_editor()
        draft = getattr(self, "_caption_draft", None)
        if draft is None:
            return
        mark, _ = self.caption_suggestion_text.selected
        if 0 <= mark < len(draft.suggestions):
            row = draft.suggestions[mark]
            self.caption_suggestion_text.stage_ignore()
            draft.actions.append(dict(start=row.start,end=row.end,expected=row.original,kind=row.kind,
                options=tuple(o.text for o in row.options),status='ignored',input_text=draft.suggestion_text))
            draft.ignored=self._draft_patch_decisions(draft,draft.suggestion_text,only_ignored=True)
            self._refresh_editor_suggestions()

    def _flip_editor_pronoun(self, checked=False, *, event=None):
        draft = getattr(self, '_caption_draft', None)
        editor = self.subtitle_edit_input
        if not self._caption_owns_draft(draft) or getattr(editor, '_preediting', False):
            return False
        text, cursor = editor.toPlainText(), editor.textCursor()
        positions = pronoun_positions(text)
        if not positions:
            self.caption_editor_hint.setText('当前这一层没有可切换的 他 / 她 / 他们 / 她们')
            return False
        self._lock_caption_editor()
        item = editor._begin_input('pronoun', event)
        anchor, position = cursor.anchor(), cursor.position()
        vertical, horizontal = editor.verticalScrollBar().value(), editor.horizontalScrollBar().value()
        blocker = QSignalBlocker(editor)
        cursor.beginEditBlock()
        try:
            # One existing whole-draft toggle, one document undo block and one
            # notification. Do not rebuild candidates or serialize per word.
            for at in reversed(positions):
                self._stage_caption_patch(at, at+1, toggle_pronoun(text[at]),
                    kind='pronoun', options=('他','她','它'))
        finally:
            cursor.endEditBlock()
            cursor = editor.textCursor()
            cursor.setPosition(anchor)
            cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)
            editor.verticalScrollBar().setValue(vertical)
            editor.horizontalScrollBar().setValue(horizontal)
            del blocker
            editor._input_active = None
        editor.textChanged.emit()
        item['expected_text'] = editor.toPlainText()
        editor.viewport().update()
        return True

    def _caption_editor_key(self, event, *, text_focus=False):
        editor = self.subtitle_edit_input
        mods = event.modifiers()
        shifted = mods == Qt.KeyboardModifier.ShiftModifier
        key = event.key()
        if key == Qt.Key.Key_S and mods == Qt.KeyboardModifier.ControlModifier:
            self.save()
            return True
        # While composing text, Shift+R observes the same IME guard as Enter.
        # Let the IME finish its candidate first, exactly like Enter.
        ime_key = Qt.Key.Key_Return if text_focus and shifted and key == Qt.Key.Key_R else key
        if editor.consume_ime_exit_key(ime_key):
            self._studio_ime_composing = False
            return True
        plain_c = (key == Qt.Key.Key_C and mods in {
            Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier})
        composing = getattr(editor, '_preediting', False) or getattr(editor, '_ime_commit_key_pending', False)
        if plain_c:
            if composing:
                return not text_focus
            # 2026-11-10 (user): Shift+C always cuts at the caret, like the
            # other Shift letter keys of this editor; plain c cuts only in C mode.
            if shifted or self.subtitle_edit_card.split_mode.isChecked():
                self._caption_consumed_commit_key = key
                if not event.isAutoRepeat():
                    self._split_caption_at_cursor()
                return True
            if not text_focus:
                QApplication.setActiveWindow(self.subtitle_edit_dock)
                editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
                editor.insertPlainText(event.text() or ('C' if shifted else 'c'))
                return True
        if shifted and key == Qt.Key.Key_P and (composing or event.isAutoRepeat()):
            return True  # reserve this command without inserting P or ending IME
        if getattr(editor, '_preediting', False):
            return False
        if (getattr(self, '_caption_split_session', None) is not None
                and mods in {Qt.KeyboardModifier.ControlModifier,
                             Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier}
                and key in {Qt.Key.Key_Z, Qt.Key.Key_Y}):
            redo = key == Qt.Key.Key_Y or bool(mods & Qt.KeyboardModifier.ShiftModifier)
            available = editor.document().isRedoAvailable() if redo else editor.document().isUndoAvailable()
            if text_focus and available:
                (editor.redo if redo else editor.undo)()
            else:
                self._undo_caption_split(redo=redo)
            return True
        suggestions = self.caption_suggestion_text
        candidate_focus = suggestions.owns_focus()
        if shifted and key == Qt.Key.Key_R:
            self._caption_consumed_commit_key = key
            self._caption_trigger_commit('shift_r')
            return True
        if getattr(self, '_caption_draft', None) is None:
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and not shifted:
                self._caption_consumed_commit_key = key
                self._end_caption_editor(keep_open=False)
                return True
            return False
        if shifted and key in {Qt.Key.Key_A, Qt.Key.Key_D}:
            right = key == Qt.Key.Key_D
            if suggestions.has_rows():
                if not suggestions.cycle(1 if right else -1, from_body=not candidate_focus):
                    cursor = editor.textCursor(); cursor.clearSelection(); editor.setTextCursor(cursor)
                    editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    self.subtitle_edit_card.update_hint()
            else:
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    cursor.setPosition(cursor.selectionEnd() if right else cursor.selectionStart())
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter if right else QTextCursor.MoveOperation.PreviousCharacter)
                editor.setTextCursor(cursor)
                editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return True
        if shifted and key == Qt.Key.Key_W:
            if candidate_focus:
                suggestions.navigate(vertical=-1)
            else:
                suggestions.select_first()
            return True
        if shifted and key == Qt.Key.Key_P:
            self._flip_editor_pronoun(event=event)
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape}:
            if text_focus and key != Qt.Key.Key_Escape and mods & Qt.KeyboardModifier.ShiftModifier:
                return False
            self._caption_consumed_commit_key = key
            if key == Qt.Key.Key_Escape:
                self._cancel_canvas_inline_edit()
            else:
                self._caption_trigger_commit('keypad_enter' if key == Qt.Key.Key_Enter else 'enter')
            return True
        return False

    def _flush_caption_editor_preview(self):
        draft = getattr(self, "_caption_draft", None)
        if not self._caption_owns_draft(draft):
            return
        self._live_edit_text_overrides[draft.target.render_id] = self.subtitle_edit_input.toPlainText()
        self._caption_transform_preview_serial = getattr(self, '_caption_transform_preview_serial', 0) + 1
        # The current scene already knows the bounded visible cue set, fonts
        # and immutable revision. Its prepare() applies draft text locally.
        if self._present_caption_scene():
            return
        self._refresh_ass_preview()

    def _finish_caption_draft(self):
        if getattr(self, '_caption_following', False):
            self._clear_caption_binding(terminal_state='applied')
            return
        draft = getattr(self, "_caption_draft", None)
        if draft:
            draft.state = 'applied'
        self._edit_preview_timer.stop()
        self._draft_recovery.discard()
        if draft:
            self._live_edit_text_overrides.pop(draft.target.render_id, None)
        self._caption_draft = None
        self._canvas_editor = None
        self._review_edit_lock = None
        self._reset_caption_input_method()
        self.position_overlay._inline_editing = False
        self._set_subtitle_editor_visible(False)
        self.subtitle_edit_input.clear()
        self.timeline.setFocus(Qt.FocusReason.OtherFocusReason)

    def _commit_caption_for_manual_save(self):
        """Apply memory once; retain the same target until disk save resolves."""
        draft = getattr(self, '_caption_draft', None)
        if draft is None:
            return None
        position = self.subtitle_edit_input.textCursor().position()
        if not self._submit_caption_draft():
            return False
        if not self._bind_caption_editor(draft.target, edit_session_id=draft.edit_session_id):
            return False
        cursor = self.subtitle_edit_input.textCursor()
        cursor.setPosition(min(position, self.subtitle_edit_input.document().characterCount()-1))
        self.subtitle_edit_input.setTextCursor(cursor)
        self._caption_edit_locked = False
        return (self.project, self._caption_draft.target, self.session.generation, self._caption_draft)

    def _finish_caption_manual_save(self, token, *, error=None):
        if (not token or self.project is not token[0] or self.session.generation != token[2]
                or getattr(self, '_caption_draft', None) is not token[3]
                or not getattr(self, '_caption_following', False)):
            return
        if error is not None:
            self._caption_disk_pending = token[1]
            self.subtitle_edit_card.set_error('工程尚未写入磁盘，修改和编辑对象已保留，可重试保存。',str(error))
            from ..diagnostics.event_log import emit, exception_info
            emit('caption.persistence', **self._caption_edit_context(token[3]), result='failed',
                 stage='persist', reason_code='disk_write_failed', exception=exception_info(error))
            return
        from ..diagnostics.event_log import emit
        emit('caption.persistence', **self._caption_edit_context(token[3]), result='completed', stage='persist')
        self._caption_disk_pending = None
        # Completion acknowledges this committed version. The user may have
        # typed a new draft or moved focus while the writer was running.

    def _reset_caption_input_method(self):
        editor = self.subtitle_edit_input
        if getattr(editor, '_preediting', False) and editor.hasFocus():
            method = QApplication.inputMethod()
            if method is not None:
                method.reset()
        editor._preediting = False
        editor._ime_commit_key_pending = False
        editor._ime_commit_token = None
        self._studio_ime_composing = False

    def _submit_caption_draft(self):
        if getattr(self, '_caption_submitting', False):
            return False
        self._caption_submitting = True
        started=perf_counter()
        from ..diagnostics.event_log import operation, emit, exception_info
        from ..diagnostics.studio_events import revision
        draft=getattr(self,'_caption_draft',None)
        before_revision=revision(self.project)
        context=self._caption_edit_context(draft, self.subtitle_edit_input.toPlainText()) if draft else {}
        context.update(revision_before=before_revision,source='caption_editor')
        if draft:
            value=self.subtitle_edit_input.toPlainText()
            context['text_summary']=dict(before_length=len(draft.before),draft_length=len(value),
                before_digest=digest(draft.before),draft_digest=digest(value))
        try:
            with operation('cue.editor_commit',**context):
                result=self._submit_caption_draft_impl()
                emit('caption.edit_result',result='applied' if result else 'retained',
                    edit_session_id=draft.edit_session_id if draft else None,
                    revision_before=before_revision,revision_after=revision(self.project),
                    duration_ms=(perf_counter()-started)*1000,
                    text_digest=digest(self.subtitle_edit_input.toPlainText()) if not result else None,
                    stage='memory_applied' if result else 'draft_retained')
                return result
        except Exception as exc:
            emit('caption.edit_failed',level='ERROR',result='failed',**context,
                revision_after=revision(self.project),duration_ms=(perf_counter()-started)*1000,
                exception=exception_info(exc),stage='edit_command')
            self._caption_editor_failed(f'字幕未提交：{exc}')
            return False
        finally:
            self._caption_submitting = False

    def _caption_editor_failed(self, message, *, reason_code=None):
        self._lock_caption_editor()
        summary = '本次修改未提交，输入内容已保留。可直接重试，或取消。'
        if '输入法候选' in message:
            summary = '请先确认输入法候选；当前输入已保留。'
            reason_code = reason_code or 'ime_unconfirmed'
        if reason_code:
            summary = message
        draft = getattr(self, '_caption_draft', None)
        details = str(message)
        if draft:
            draft.state = 'rejected'
            from ..diagnostics.event_log import emit
            context = self._caption_edit_context(draft, self.subtitle_edit_input.toPlainText())
            context.update(reason_code=reason_code or 'edit_command_failed', stage='validate')
            emit('caption.edit_rejected', **context, result='retained', level='WARN')
            details += '\n' + json.dumps(context, ensure_ascii=False, indent=2)
        self.save_state.setText(summary)
        self.subtitle_edit_card.set_error(summary, details)
        self.subtitle_edit_card.reload_current_button.setVisible(reason_code == 'text_conflict')
        if reason_code == 'text_conflict' and draft:
            current=draft.target.read(self.project)
            self.subtitle_edit_card.reference.setText('当前文本（只读）：'+str(current or ''))
            self.subtitle_edit_card.reference.show()
        self.subtitle_edit_card.updateGeometry()

    def _submit_caption_draft_impl(self):
        draft = getattr(self, "_caption_draft", None)
        if draft is None:
            return False
        if getattr(self.subtitle_edit_input,'_preediting',False):
            method=QApplication.inputMethod()
            if method is not None:method.commit()
            if getattr(self.subtitle_edit_input,'_preediting',False):
                self._caption_editor_failed('输入法候选尚未确认，请先确认候选再提交')
                return False
        value = self.subtitle_edit_input.toPlainText()
        def reject(code, message):
            self._caption_editor_failed(message, reason_code=code)
            return False
        if not self._caption_owns_draft(draft):
            return reject('session_changed', '工程会话已切换，输入已保留；可复制草稿到当前工程。')
        cue = draft.target.resolve(self.project)
        if cue is None:
            return reject('target_deleted', '这条字幕已删除或被合并，输入已保留；可复制草稿。')
        from ..projects.studio_runtime_state import state_for
        if state_for(self.project).entity_epochs.get(cue.id, 0) != draft.entity_epoch:
            return reject('entity_restructured', '这条字幕已拆分、合并或重新建立，输入已保留；可复制草稿。')
        current = draft.target.read(self.project)
        if current is None:
            return reject('translation_language_changed', '译文目标语言已变化，输入已保留；可复制草稿。')
        if draft.target.layer == 'translation':
            from ..subtitle_rules.subtitle_translation import clean_translation
            value = clean_translation(value)
        if (cue.speaker_id in self.timeline.locked_speakers or draft.target.layer == 'translation'
                and 'translation' in self.timeline.locked_speakers):
            return reject('track_locked', '当前字幕轨道已锁定，输入已保留；解锁后可直接重试。')
        if current != draft.before and current != value:
            return reject('text_conflict', '同一文本已有其他修改，草稿已保留；请比较当前文本后再保存。')
        changes = self._draft_patch_decisions(draft,value)
        if getattr(self, '_caption_split_session', None) is not None:
            if changes:
                from .caption_split_editor import SplitStep
                self._caption_split_session.stage(SplitStep(
                    IssueDecisionsCommand(self.project, changes), draft.target, value,
                    self.subtitle_edit_input.textCursor().position()))
            return self._finish_split_session()
        changed = value != current
        if not changed and not changes:
            self._finish_caption_draft()
            self._refresh_ass_preview()
            return True
        cue_id = draft.target.cue_id
        applied = True
        if changed or changes:
            self.undo_stack.beginMacro("编辑译文" if draft.target.layer == "translation" else "编辑原文")
            try:
                if changed:
                    if draft.target.layer == "translation":
                        applied = self.cue_controller.set_translation(cue_id, value, target=draft.target.language)
                    else:
                        applied = self.cue_controller.set_text(cue_id, value)
                if changes and applied:
                    self.undo_stack.push(IssueDecisionsCommand(self.project, changes,
                        lambda: self._caption_issue_decisions_changed(cue_id)))
            finally:
                self.undo_stack.endMacro()
        if not applied or draft.target.read(self.project) != value:
            self._caption_editor_failed('字幕写入未成功，草稿已保留')
            return False
        self._finish_caption_draft()
        invalidate(self.project)
        self._refresh_ass_preview()
        return True

    def _caption_issue_decisions_changed(self, cue_id):
        self.cue_model.refresh_cues((cue_id,), (4,), recheck_filter=True)
        self._refresh_cue_list_summary()
        self._schedule_autosave()
        if self._review_mode:
            self._refresh_review_summary_strip()

    def _commit_target_text_patch(self,target,start,end,replacement,*,kind='model',options=(),label='采用局部建议'):
        if getattr(self,'_caption_draft',None) is not None or not self.project:
            return False
        text=target.read(self.project)
        if text is None or target.track_id in self.timeline.locked_speakers:
            return False
        value=text[:start]+replacement+text[end:]
        if value==text:return False
        self.undo_stack.beginMacro(label)
        try:
            if target.layer=='translation':
                changed=self.cue_controller.set_translation(target.cue_id,value,target=target.language)
            else:
                changed=self.cue_controller.set_text(target.cue_id,value,command_text=label)
            if changed and target.read(self.project)==value:
                key=patch_identity(target.__dict__,start,start+len(replacement),replacement,
                                   'model' if kind=='pronoun' else kind)
                self.undo_stack.push(IssueDecisionsCommand(self.project,{key:dict(status='resolved',
                    input_version=digest(value),options=sorted(set(options)))},
                    lambda:self._caption_issue_decisions_changed(target.cue_id)))
        finally:
            self.undo_stack.endMacro()
        return changed
