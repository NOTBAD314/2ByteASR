"""Window-owned reversible previews, promoted to one ordinary project command."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QApplication


@contextmanager
def preview_changes(project):
    project._caption_preview_active = True
    try:
        yield
    finally:
        project._caption_preview_active = False


@dataclass
class SplitStep:
    command: object
    target: object
    text: str
    cursor: int
    split: bool = False


class CaptionSplitSession(QUndoCommand):
    def __init__(self, project, target):
        super().__init__('编辑并按文字光标切割字幕')
        self.project = project
        self.root = target
        self.steps = []
        self.future = []
        self.ids = {target.cue_id}
        self.first_redo = True
        from ..subtitle_rules.current_issues import LEGACY_INPUTS, legacy_review_inputs
        self.legacy_absent = LEGACY_INPUTS not in project.studio_state
        self.legacy_input = {key: list(value) for key, value in legacy_review_inputs(project).items()}

    def _restore_legacy_container(self):
        from ..subtitle_rules.current_issues import LEGACY_INPUTS
        if self.legacy_absent and self.project.studio_state.get(LEGACY_INPUTS) == self.legacy_input:
            self.project.studio_state.pop(LEGACY_INPUTS, None)

    def stage(self, step):
        with preview_changes(self.project):
            step.command.redo()
        self.steps.append(step)
        self.future.clear()
        self.ids.update(c.id for c in getattr(step.command, '_after_cues', ()))

    def _replay(self, forward):
        from ..projects.studio_runtime_state import state_for, DirtyDomain
        runtime = state_for(self.project)
        with runtime.transaction(self.project, action_id='caption_editor_commit',
                dirty=DirtyDomain.AUTOSAVE, affected_cue_ids=self.ids, snapshot_cues=False):
            for step in (self.steps if forward else reversed(self.steps)):
                (step.command.redo if forward else step.command.undo)()
            if not forward:
                self._restore_legacy_container()

    def redo(self):
        if self.first_redo:
            self.first_redo = False
            from ..projects.studio_runtime_state import state_for, DirtyDomain
            with state_for(self.project).transaction(self.project, action_id='caption_editor_commit',
                    dirty=DirtyDomain.AUTOSAVE, affected_cue_ids=self.ids, snapshot_cues=False):
                pass
        else:
            self._replay(True)

    def undo(self):
        self._replay(False)

    def cancel(self):
        from ..projects.studio_runtime_state import state_for, DirtyDomain
        with preview_changes(self.project), state_for(self.project).transaction(self.project,
                action_id='caption_editor_preview', dirty=DirtyDomain.NONE,
                affected_cue_ids=self.ids, snapshot_cues=False):
            for step in reversed(self.steps):
                step.command.undo()
            self._restore_legacy_container()


class CaptionSplitEditorMixin:
    def _caption_split_notice(self, message):
        self.subtitle_edit_card.split_status.setText(message)
        self.subtitle_edit_card.updateGeometry()
        self.subtitle_edit_dock.schedule_fit()

    def _stage_split_editor_text(self):
        session = getattr(self, '_caption_split_session', None)
        draft = self._caption_draft
        if session is None or draft is None:
            return
        value = self.subtitle_edit_input.toPlainText()
        cue = draft.target.resolve(self.project)
        if cue is None or value == cue.text:
            return
        if not value.strip():
            raise ValueError('字幕需要保留文字')
        from ..timeline.studio_commands import SetCueFieldsCommand, MutationOrigin
        command = SetCueFieldsCommand(self.project, cue.id, {'text': value}, '编辑切割草稿', origin=MutationOrigin.USER_EDIT)
        session.stage(SplitStep(command, draft.target, value, self.subtitle_edit_input.textCursor().position()))

    def _split_caption_at_cursor(self):
        editor = self.subtitle_edit_input
        draft = getattr(self, '_caption_draft', None)
        if not self._caption_owns_draft(draft):
            self._caption_split_notice('当前位置没有可切割字幕')
            return False
        # Button clicks must neither finish a preedit nor steal the insertion cursor.
        if getattr(editor, '_preediting', False) or getattr(editor, '_ime_commit_key_pending', False):
            self._caption_split_notice('请先完成输入法选字')
            return False
        cursor = editor.textCursor()
        if cursor.hasSelection():
            self._caption_split_notice('请先点击一个文字插入位置，取消选区')
            return False
        if draft.target.layer == 'translation':
            self._caption_split_notice('关联译文缺少原文位置映射，请在原文层切割；完整译文会保留待校对')
            return False
        cue = draft.target.resolve(self.project)
        from ..projects.studio_runtime_state import state_for
        if (cue is None or cue.speaker_id in self.timeline.locked_speakers
                or state_for(self.project).entity_epochs.get(cue.id, 0) != draft.entity_epoch
                or draft.target.read(self.project) != draft.before):
            self._caption_split_notice('字幕或轨道已变化，请重新打开后切割')
            return False
        from .caption_editor import py_position, qt_position
        from ..timeline.caret_split import plan_caret_cut, caret_split_command
        from ..timeline.studio_edit_sequence import map_timing_to_source
        text = editor.toPlainText()
        try:
            position = py_position(text, cursor.position())
            if qt_position(text, position) != cursor.position():
                raise ValueError('请把光标移到完整字符之间')
            view = self.session.runtime.cue_by_id.get(cue.id, cue)
            playhead = self.timeline.playhead_ms if self.subtitle_edit_card.split_playhead.isChecked() else None
            cut = plan_caret_cut(self.project, view, text, position, playhead_ms=playhead)
            mapped = map_timing_to_source(self.project, cue, cut.split_ms, cut.split_ms + 1)
            if mapped is None:
                raise ValueError('切点跨剪辑边界，无法映射到原字幕')
            command = caret_split_command(self.project, cue, text, replace(cut, split_ms=mapped[0]))
        except ValueError as error:
            self._caption_split_notice(str(error))
            return False
        self._lock_caption_editor()
        session = getattr(self, '_caption_split_session', None)
        if session is None:
            session = self._caption_split_session = CaptionSplitSession(self.project, draft.target)
        decisions = self._draft_patch_decisions(draft, text)
        if decisions:
            from .caption_editor import IssueDecisionsCommand
            session.stage(SplitStep(IssueDecisionsCommand(self.project, decisions),
                                   draft.target, text, cursor.position()))
        step = SplitStep(command, draft.target, text, cursor.position(), True)
        self._live_edit_text_overrides.pop(draft.target.render_id, None)
        session.stage(step)
        target = replace(draft.target, cue_id=command._after_cues[-1].id)
        self._bind_split_part(target)
        from .studio_helpers import _format_ms
        label = '字词对齐切点' if cut.measured else '播放头校准' if playhead is not None else '估算切点 · 可勾选播放头校准后切割'
        translation = ' · 完整译文保留在首段，分段待校对' if command._translations.active else ''
        self._caption_split_notice(f'{label} {_format_ms(cut.split_ms)}{translation}')
        return True

    def _bind_split_part(self, target, text=None, cursor=0):
        previous = getattr(self, '_caption_draft', None)
        if previous is not None:
            self._live_edit_text_overrides.pop(previous.target.render_id, None)
        self._caption_split_restoring = True
        try:
            self._bind_caption_editor(target)
            self._lock_caption_editor()
            if text is not None:
                self.subtitle_edit_input.setPlainText(text)
        finally:
            self._caption_split_restoring = False
        insertion = self.subtitle_edit_input.textCursor()
        insertion.setPosition(min(cursor, self.subtitle_edit_input.document().characterCount() - 1))
        self.subtitle_edit_input.setTextCursor(insertion)
        self.select_cue(target.cue_id)
        QApplication.setActiveWindow(self.subtitle_edit_dock)
        self.subtitle_edit_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_split_controls()

    def _update_split_controls(self):
        panel = self.subtitle_edit_card
        session = getattr(self, '_caption_split_session', None)
        parts = [c for c in self.project.cues if c.id in session.ids] if session and self.project is session.project else []
        target = getattr(self, '_caption_draft', None)
        index = next((i for i, c in enumerate(parts) if target and c.id == target.target.cue_id), -1)
        panel.split_previous.setEnabled(index > 0)
        panel.split_next.setEnabled(0 <= index < len(parts) - 1)
        panel.split_undo.setEnabled(bool(session and any(s.split for s in session.steps)))
        panel.split_redo.setEnabled(bool(session and session.future))
        panel.split_part.setText(f'第 {index + 1}/{len(parts)} 段' if parts else '')
        host = getattr(panel, 'parts_host', None)
        if host is not None and host.isHidden() == bool(parts or session):
            host.setVisible(bool(parts or session))  # 2026-11-09: only while splitting
            if hasattr(panel.window(), 'schedule_fit'):
                panel.window().schedule_fit()

    def _navigate_split_part(self, direction):
        session = getattr(self, '_caption_split_session', None)
        if session is None or getattr(self.subtitle_edit_input, '_preediting', False):
            return
        try:
            self._stage_split_editor_text()
        except ValueError as error:
            self._caption_split_notice(str(error))
            return
        parts = [c for c in self.project.cues if c.id in session.ids]
        target = self._caption_draft.target
        index = next(i for i, c in enumerate(parts) if c.id == target.cue_id) + direction
        if 0 <= index < len(parts):
            self._bind_split_part(replace(target, cue_id=parts[index].id))

    def _undo_caption_split(self, redo=False):
        session = getattr(self, '_caption_split_session', None)
        if session is None or getattr(self.subtitle_edit_input, '_preediting', False):
            return False
        if redo:
            if not session.future:
                return True
            with preview_changes(self.project):
                step = session.future.pop()
                step.command.redo()
                session.steps.append(step)
                while session.future and not session.future[-1].split:
                    step = session.future.pop()
                    step.command.redo()
                    session.steps.append(step)
            cue_id = step.command._after_cues[-1].id if step.split else step.target.cue_id
            self._bind_split_part(replace(step.target, cue_id=cue_id))
        else:
            if not any(s.split for s in session.steps):
                return True
            # Retain edits made after the cut in the redo branch, including
            # edits to earlier parts reached with the navigation buttons.
            try:
                self._stage_split_editor_text()
            except ValueError as error:
                self._caption_split_notice(str(error))
                return True
            with preview_changes(self.project):
                while session.steps:
                    step = session.steps.pop()
                    step.command.undo()
                    session.future.append(step)
                    if step.split:
                        break
            self._bind_split_part(step.target, step.text, step.cursor)
        self._caption_split_notice('已重做切割' if redo else '已撤销切割，切割前的最新文字已保留')
        return True

    def _finish_split_session(self):
        session = self._caption_split_session
        self._stage_split_editor_text()
        self._caption_split_session = None
        if session.steps:
            self.undo_stack.push(session)
        self._finish_caption_draft()
        self._refresh_ass_preview()
        return True

    def _cancel_split_session(self):
        session = getattr(self, '_caption_split_session', None)
        if session is not None:
            self._caption_split_session = None
            if self.project is session.project:
                session.cancel()
                self.select_cue(session.root.cue_id)
