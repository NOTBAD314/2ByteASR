"""Modeless diagnostics available before the export workspace exists."""
from __future__ import annotations

import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QPlainTextEdit, QApplication)

from .export_issues import (EMPTY_CONFIRMATIONS, empty_version, export_issues, clock, owner_for,
                            issues_from_error)
from ..i18n import tr


class ConfirmEmptySourceCommand(QUndoCommand):
    def __init__(self, project, cue_id, changed=None):
        super().__init__(tr('确认这条原文有意清空'))
        import copy
        self.project, self.cue_id, self.changed = project, cue_id, changed
        self.before = copy.deepcopy(project.studio_state.get(EMPTY_CONFIRMATIONS, {}).get(cue_id))
        cue = owner_for(project, cue_id)
        if cue is None or cue.text.strip() or not cue.original_text.strip():
            raise ValueError(tr('字幕已变化，请重新检查'))
        self.after = dict(input_version=empty_version(project, cue), disposition='intentional_empty')

    def _apply(self, value):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        def mutate():
            decisions = self.project.studio_state.setdefault(EMPTY_CONFIRMATIONS, {})
            if value is None: decisions.pop(self.cue_id, None)
            else: decisions[self.cue_id] = dict(value)
        _commit_mutation(self.project, action_id=self.text(), dirty=DirtyDomain.QC | DirtyDomain.AUTOSAVE,
                         cue_ids=(self.cue_id,), mutate=mutate, changed=self.changed)

    def redo(self): self._apply(self.after)
    def undo(self): self._apply(self.before)


def locate_issue(page, issue, *, edit=False):
    """Clear presentation filters; preserve the real cue/clip owner."""
    project = page.session.project
    cue = owner_for(project, issue.cue_id)
    if cue is None:
        return False
    if getattr(page, 'export_workspace', None) is not None:
        page._close_export_workspace()
    page.video.set_paused(True)
    page.cue_search.clear()
    page.cue_model.set_query('')
    page._activate_filter('all')
    page.timeline.set_group_expanded(True)
    page.timeline.set_subtitle_layer('original')
    page.cue_model.set_text_layer('original')
    page.cue_model.refresh()
    from ..timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    views = projected_cues(project, domain='timeline')
    view = next((v for v in views if v.id == issue.view_id), None)
    if view is None:
        view = next((v for v in views if v.id == cue.id or source_cue_id_of(v.id) == cue.id), None)
    if view is None:
        return False
    page.select_cue(view.id)
    milliseconds = max(0, view.start_ms)
    page._seek(milliseconds / 1000.0)
    page.timeline.reveal_playhead(milliseconds, force=True)
    page.timeline.set_playhead(milliseconds)
    # Move the selected track into the viewport after its group expanded.
    tracks, _, _ = page.timeline._track_layout()
    rect = tracks.get(view.speaker_id)
    if rect is not None:
        viewport = page.timeline._track_viewport()
        offset = round(rect.center().y() - viewport.center().y())
        page.timeline.vertical_scrollbar.setValue(page.timeline.vertical_scrollbar.value() + offset)
    row = page.cue_model.row_for_cue_id(view.id)
    if row >= 0:
        page.cue_table.selectRow(row)
        page.cue_table.scrollTo(page.cue_model.index(row, 3), QAbstractItemView.ScrollHint.PositionAtCenter)
    page.timeline.update()
    page._show_studio_hint(tr('已定位：{time} · {speaker} · 原文', time=clock(milliseconds), speaker=issue.speaker))
    if edit:
        page._open_caption_editor(view.id, 'original')
    return row >= 0


class ExportIssuesDialog(QDialog):
    def __init__(self, page, *, issues=None, scope=None, continue_callback=None):
        super().__init__(page)
        self.page, self.project = page, page.session.project
        self.scope = dict(scope or {})
        self.initial = tuple(issues) if issues is not None else None
        self.task_issues = tuple(issue for issue in (issues or ()) if issue.code == 'task_failure')
        self.continue_callback = continue_callback
        self.setWindowTitle(tr('导出问题 · 定位与处理'))
        self.setObjectName('exportIssuesDialog')
        self.resize(1040, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel(); layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr(s) for s in ('问题／是否阻断', '时间码', '轨道／说话人／类型', '当前文本', '保留原稿摘要')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(190)
        layout.addWidget(self.detail)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        navigation = QHBoxLayout()
        self.previous = QPushButton(tr('上一条')); self.previous.clicked.connect(lambda: self.move(-1))
        self.next = QPushButton(tr('下一条')); self.next.clicked.connect(lambda: self.move(1))
        self.locate = QPushButton(tr('定位字幕')); self.locate.clicked.connect(self.locate_current)
        self.edit = QPushButton(tr('编辑这条字幕')); self.edit.clicked.connect(lambda: self.locate_current(edit=True))
        self.restore = QPushButton(tr('恢复这条原文')); self.restore.clicked.connect(self.restore_current)
        self.confirm = QPushButton(tr('确认有意清空')); self.confirm.clicked.connect(self.confirm_current)
        for button in (self.previous, self.next, self.locate, self.edit, self.restore, self.confirm): navigation.addWidget(button)
        layout.addLayout(navigation)
        actions = QHBoxLayout()
        self.recheck = QPushButton(tr('重新检查')); self.recheck.clicked.connect(self.refresh)
        copy = QPushButton(tr('复制详情')); copy.clicked.connect(lambda: QApplication.clipboard().setText(
            json.dumps([i.to_dict() for i in self.issues], ensure_ascii=False, indent=2)))
        self.proceed = QPushButton(tr('返回导出设置…')); self.proceed.clicked.connect(self.proceed_to_export)
        close = QPushButton(tr('关闭')); close.clicked.connect(self.close)
        for button in (self.recheck, copy, self.proceed, close): actions.addWidget(button)
        layout.addLayout(actions)
        from ..design.studio_theme import apply_secondary_surface_theme
        apply_secondary_surface_theme(self)
        self.refresh(initial=True)

    def current(self):
        index = self.table.currentRow()
        return self.issues[index] if 0 <= index < len(self.issues) else None

    def refresh(self, _checked=False, *, initial=False):
        if self.page.session.project is not self.project:
            self.status.setText(tr('工程已切换，请关闭后在当前工程重新检查'))
            for button in (self.restore, self.confirm, self.edit, self.proceed, self.locate): button.setEnabled(False)
            return
        previous = self.table.currentRow()
        try:
            self.issues = self.initial if initial and self.initial is not None else self.task_issues + export_issues(self.project, **self.scope)
        except Exception as exc:
            self.issues = issues_from_error(self.project, exc)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.issues))
        for i, issue in enumerate(self.issues):
            values = (('阻断 · ' if issue.blocking else '警告 · ') + issue.label, clock(issue.start_ms),
                f"{issue.speaker or issue.track_id} · {'译文' if issue.layer == 'translation' else '原文'}",
                issue.text or tr('空文本'), issue.manuscript[:90])
            for j, value in enumerate(values): self.table.setItem(i, j, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.summary.setText(tr('当前导出范围：{count} 项问题，{blocking} 项阻断。处理后请重新检查。',
            count=len(self.issues), blocking=sum(i.blocking for i in self.issues)))
        if self.issues: self.table.selectRow(max(0, min(previous, len(self.issues)-1)))
        self.selection_changed()
        if not self.issues: self.status.setText(tr('本次范围预检已通过，可以返回导出设置。'))

    def selection_changed(self):
        issue = self.current()
        can_locate = bool(issue and issue.cue_id)
        for button in (self.locate, self.edit): button.setEnabled(can_locate)
        for button in (self.restore, self.confirm): button.setEnabled(bool(issue and issue.code == 'empty_source'))
        self.previous.setEnabled(len(self.issues) > 1); self.next.setEnabled(len(self.issues) > 1)
        self.proceed.setEnabled(self.continue_callback is not None)
        self.detail.setPlainText('' if issue is None else '\n'.join((
            f'{issue.stage} · {issue.label}', issue.reason, issue.provenance,
            f'当前文本：{issue.text or "（空）"}', f'保留原稿：{issue.manuscript or "（无）"}',
            f'对应译文：{issue.translation or "（无）"}',
            f'详情ID：{issue.cue_id}\n剪辑实例ID：{issue.view_id}')))

    def move(self, step):
        if self.issues:
            self.table.selectRow((self.table.currentRow() + step) % len(self.issues))
            self.locate_current()

    def locate_current(self, _checked=False, *, edit=False):
        issue = self.current()
        if self.page.session.project is not self.project or issue is None: return
        ok = locate_issue(self.page, issue, edit=edit)
        self.status.setText(tr('已选中对应字幕和轨道；可在工作台查看，处理后点重新检查。') if ok else tr('当前范围找不到该字幕，请重新检查。'))
        if ok:
            self.page.window().raise_()
            if edit: self.hide()

    def _fresh(self):
        issue = self.current()
        if issue is None or self.page.session.project is not self.project: return None
        cue = owner_for(self.project, issue.cue_id)
        if cue is None or issue.input_version != empty_version(self.project, cue):
            self.status.setText(tr('这条字幕已变化，尚未修改。请重新检查。')); return None
        return cue

    def restore_current(self):
        cue = self._fresh()
        if cue is None: return
        from ..timeline.studio_commands import SetCueFieldsCommand
        self.page.session.undo_stack.push(SetCueFieldsCommand(self.project, cue.id,
            {'text': cue.original_text}, tr('恢复这条保留原稿'), self.page._changed))
        self.refresh()

    def confirm_current(self):
        cue = self._fresh()
        if cue is None: return
        self.page.session.undo_stack.push(ConfirmEmptySourceCommand(self.project, cue.id, self.page._changed))
        self.refresh()

    def proceed_to_export(self):
        if self.page.session.project is not self.project or self.continue_callback is None: return
        self.close(); QTimer.singleShot(0, self.continue_callback)


def show_export_issues(page, *, error=None, scope=None, continue_callback=None):
    old = getattr(page, '_export_issues_dialog', None)
    if old is not None: old.close(); old.deleteLater()
    issues = issues_from_error(page.session.project, error) if error is not None else None
    dialog = ExportIssuesDialog(page, issues=issues, scope=scope, continue_callback=continue_callback)
    page._export_issues_dialog = dialog
    dialog.show(); dialog.raise_(); dialog.activateWindow()
    return dialog
