"""Studio: choose the project's punctuation style, preview it, or write it into the manuscript (2026-10-13).

Switching the style is one undoable visual edit (``studio_state['punctuation']``);
preview, ASS/SRT/TXT/JSON export, bilingual layers and burn-in all follow it,
while the manuscript (``cue.text``), timings, speakers, cue ids and clip
mapping stay exactly as they are. Writing the style into the manuscript is a
separate, previewed, one-step-undoable command that keeps word receipts.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

from PySide6.QtGui import QUndoCommand

from .i18n import tr
from .punctuation_style import (MODE_ADD, MODE_HINTS, MODE_LABELS, MODE_NONE, MODE_ORIGINAL, MODES, mode_from_state,
                                project_mode, protected_terms_of, state_value, style_text)


class SetPunctuationStyleCommand(QUndoCommand):
    def __init__(self, project, mode: str, changed=None):
        super().__init__(tr('标点：{value0}', value0=tr(MODE_LABELS.get(mode, mode))))
        self.project = project
        self.before = copy.deepcopy(project.studio_state.get('punctuation'))
        self.after = state_value(mode)
        self.changed = changed

    def _apply(self, value):
        from .studio_commands import _commit_mutation
        from .studio_runtime_state import DirtyDomain

        def mutate():
            if value is None:
                self.project.studio_state.pop('punctuation', None)
            else:
                self.project.studio_state['punctuation'] = copy.deepcopy(value)

        _commit_mutation(self.project, action_id=self.text(),
                         dirty=(DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW
                                | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE),
                         cue_ids=(), mutate=mutate, changed=self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def apply_style(page, mode: str) -> bool:
    """User choice in the workbench: one undoable step; the manuscript is untouched."""
    if not getattr(page, 'project', None) or mode not in MODES:
        return False
    if project_mode(page.project) == mode and 'punctuation' in page.project.studio_state:
        sync_controls(page)
        return False
    page.undo_stack.push(SetPunctuationStyleCommand(page.project, mode, None))
    sync_controls(page)
    refresh = getattr(page, '_refresh_ass_preview', None)
    if callable(refresh):
        refresh()
    return True


def build_menu(page, menu) -> None:
    from PySide6.QtGui import QAction, QActionGroup
    group = QActionGroup(menu)
    group.setExclusive(True)
    page.punctuation_mode_actions = {}
    for mode in (MODE_ADD, MODE_NONE, MODE_ORIGINAL):
        label = tr(MODE_LABELS[mode]) + ('（' + tr('进阶') + '）' if mode == MODE_ORIGINAL else '')
        action = QAction(label, menu)
        action.setCheckable(True)
        action.setToolTip(tr(MODE_HINTS[mode]))
        action.triggered.connect(lambda _checked=False, value=mode: apply_style(page, value))
        group.addAction(action)
        menu.addAction(action)
        page.punctuation_mode_actions[mode] = action
    menu.addSeparator()
    preview = QAction(tr('预览三种效果…'), menu)
    preview.triggered.connect(lambda: open_style_dialog(page))
    menu.addAction(preview)
    permanent = QAction(tr('把当前效果写进文稿…（可撤销）'), menu)
    permanent.triggered.connect(lambda: open_permanent_dialog(page))
    menu.addAction(permanent)
    page.punctuation_permanent_action = permanent
    stack = getattr(page, 'undo_stack', None)
    if stack is not None:
        # Undo/redo of a style switch (and project reloads) keep the checks right.
        stack.indexChanged.connect(lambda _index: sync_controls(page))
    sync_controls(page)


def sync_controls(page) -> None:
    mode = project_mode(page.project) if getattr(page, 'project', None) else MODE_ORIGINAL
    for value, action in (getattr(page, 'punctuation_mode_actions', None) or {}).items():
        action.setChecked(value == mode)
    button = getattr(page, 'punctuation_button', None)
    if button is not None:
        button.setText(tr('标点：{value0}', value0=tr(MODE_LABELS[mode])))
        button.setToolTip(tr('{value0}：{value1}（文稿不变）', value0=tr(MODE_LABELS[mode]), value1=tr(MODE_HINTS[mode])))
    permanent = getattr(page, 'punctuation_permanent_action', None)
    if permanent is not None:
        permanent.setEnabled(mode != MODE_ORIGINAL)


def open_style_dialog(page) -> None:
    """Three choices with the project's own subtitles as the preview."""
    from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QRadioButton,
                                   QVBoxLayout)
    from .punctuation_style import preview_rows
    project = getattr(page, 'project', None)
    dialog = QDialog(page.window() or page)
    dialog.setObjectName('punctuationStyleDialog')
    dialog.setWindowTitle(tr('字幕标点'))
    dialog.resize(640, 480)
    layout = QVBoxLayout(dialog)
    note = QLabel(tr('画面和所有导出都照这个来；文稿不变，随时能换回'))
    note.setWordWrap(True)
    layout.addWidget(note)
    group = QButtonGroup(dialog)
    current = project_mode(project) if project else MODE_ORIGINAL
    buttons = {}
    for mode in (MODE_ADD, MODE_NONE, MODE_ORIGINAL):
        radio = QRadioButton(f"{tr(MODE_LABELS[mode])} — {tr(MODE_HINTS[mode])}", dialog)
        radio.setObjectName('punctuationMode_' + mode)
        radio.setChecked(mode == current)
        group.addButton(radio)
        layout.addWidget(radio)
        buttons[mode] = radio
    preview = QPlainTextEdit(dialog)
    preview.setObjectName('punctuationPreview')
    preview.setReadOnly(True)
    layout.addWidget(preview, 1)
    honesty = QLabel(tr('“添加标点”按停顿推断；要更准的标点，用“批量替换 → AI 整理”（可能收费）'))
    honesty.setObjectName('muted')
    honesty.setWordWrap(True)
    layout.addWidget(honesty)

    def chosen():
        return next(mode for mode, radio in buttons.items() if radio.isChecked())

    def refresh():
        mode = chosen()
        lines = []
        for original, styled in preview_rows(project, mode, limit=4):
            lines.append(tr('文稿：') + original)
            lines.append(tr('输出：') + styled)
            lines.append('')
        preview.setPlainText('\n'.join(lines).strip())

    for radio in buttons.values():
        radio.toggled.connect(lambda _on: refresh())
    refresh()
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    dialog._chosen = chosen  # for automated checks
    if dialog.exec() == QDialog.Accepted and project is not None:
        apply_style(page, chosen())


# ---------------------------------------------------------------- permanent

def permanent_changes(project, mode: str | None = None) -> list[tuple[str, str, str]]:
    """(cue_id, manuscript, styled) for every cue the current style would change."""
    from .language_rules import project_language
    mode = project_mode(project) if mode is None else mode
    if mode == MODE_ORIGINAL:
        return []
    hint = project_language(project) or ''
    terms = protected_terms_of(project)
    changes = []
    for cue in project.cues:
        styled = style_text(cue.text, mode, language=hint, protected_terms=terms)
        if styled.changed and styled.text.strip():
            changes.append((cue.id, cue.text, styled.text))
    return changes


class WritePunctuationCommand(QUndoCommand):
    """The chosen style written into the manuscript: one undo step.

    Built on the QC safe-fix command so caption receipts and term word
    overrides follow a punctuation-only change instead of falling back to
    re-alignment; timings, speakers, ids and clip mapping are untouched.
    """

    def __new__(cls, project, changes, changed=None):
        from .studio_commands import ApplySafeFixesCommand
        values = {cue_id: styled for cue_id, _old, styled in changes}
        cues = []
        for cue in project.cues:
            if cue.id in values:
                cue = copy.deepcopy(cue)
                cue.text = values[cue.id]
            cues.append(cue)
        plan = SimpleNamespace(cues=tuple(cues), total=len(values), counts={'punctuation': len(values)})
        command = ApplySafeFixesCommand(project, plan, changed)
        command.setText(tr('标点写进文稿（{count} 条）', count=len(values)))
        return command


def open_permanent_dialog(page) -> bool:
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
    project = getattr(page, 'project', None)
    if project is None:
        return False
    mode = project_mode(project)
    changes = permanent_changes(project, mode)
    dialog = QDialog(page.window() or page)
    dialog.setObjectName('punctuationPermanentDialog')
    dialog.setWindowTitle(tr('把标点写进文稿'))
    dialog.resize(680, 520)
    layout = QVBoxLayout(dialog)
    if not changes:
        layout.addWidget(QLabel(tr('当前设置不会改变任何字幕的文字。')))
        box = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        box.rejected.connect(dialog.reject)
        box.accepted.connect(dialog.accept)
        layout.addWidget(box)
        dialog.exec()
        return False
    summary = QLabel(tr('改写 {count} 条字幕的文字，时间和说话人不变；Ctrl+Z 一步恢复', count=len(changes)))
    summary.setWordWrap(True)
    layout.addWidget(summary)
    listing = QPlainTextEdit(dialog)
    listing.setObjectName('punctuationPermanentPreview')
    listing.setReadOnly(True)
    rows = []
    for _cue_id, old, new in changes[:300]:
        rows.append(f'{old}\n→ {new}\n')
    if len(changes) > 300:
        rows.append(tr('……另有 {count} 条', count=len(changes) - 300))
    listing.setPlainText('\n'.join(rows))
    layout.addWidget(listing, 1)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
    box.button(QDialogButtonBox.Ok).setText(tr('写进文稿'))
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    if dialog.exec() != QDialog.Accepted:
        return False
    # The project may have changed while the dialog was open: recompute.
    fresh = permanent_changes(project, mode)
    if not fresh:
        return False
    page.undo_stack.push(WritePunctuationCommand(project, fresh))
    refresh = getattr(page, '_refresh_ass_preview', None)
    if callable(refresh):
        refresh()
    return True


def initial_state_for_new_project(settings: dict) -> dict | None:
    """The new-task default as a project state (None keeps 保留原文 implicit)."""
    from .punctuation_style import default_mode_for_new_tasks
    mode = default_mode_for_new_tasks(settings)
    return state_value(mode) if mode != MODE_ORIGINAL else None


__all__ = ['SetPunctuationStyleCommand', 'WritePunctuationCommand', 'apply_style', 'build_menu',
           'open_permanent_dialog', 'open_style_dialog', 'permanent_changes', 'sync_controls', 'mode_from_state']
