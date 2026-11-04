"""Review a scoped subtitle layout before one existing presentation undo edit."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHeaderView,
                              QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..caption_style.subtitle_stacking import manual_position, rearrange_subtitles_command


def _has_keyframes(value):
    if isinstance(value, Mapping):
        return any((str(key).replace('_', '').lower() == 'keyframes' and bool(item))
                   or _has_keyframes(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_keyframes(item) for item in value)
    return False


def _snapshot(project):
    # to_dict() is a persistence/validation boundary and may mutate a legacy
    # project. This inspection must not initialize or normalize its model.
    state = project.__dict__.get('_studio_state_runtime')
    sequence = project.__dict__.get('_edit_sequence_runtime')
    model = asdict(project)
    # The normal Studio timer saves these view preferences while a modeless
    # preview is open. They cannot alter caption layout, and must not reject
    # the reviewed edit. Content, media, styles and layout policy stay guarded.
    for key in ('playhead_ms', 'last_selected_cue', 'zoom', 'scroll_ms', 'layout'):
        model['studio_state'].pop(key, None)
    return (model, tuple((cue.id, id(cue)) for cue in project.cues),
            (id(state), getattr(state, 'revision', None)),
            (id(sequence), getattr(sequence, 'revision', None)))


def _base_position(project, cue):
    from ..caption_style.style_resolution import resolve_cue_visual
    from ..caption_style.visual_snapshot import _anchor
    style = resolve_cue_visual(project, cue).style
    width = int(project.render_settings.get('play_res_x', 1920))
    height = int(project.render_settings.get('play_res_y', 1080))
    x, y, _, _ = _anchor(style, width, height)
    return f'({x:.1f}, {y:.1f})'


class SubtitleLayoutPreview(QDialog):
    def __init__(self, page, cue_ids):
        super().__init__(page)
        self.page, self.project = page, page.project
        self.before = _snapshot(self.project)
        self.frozen_project = deepcopy(self.project)
        from ..timeline.studio_edit_sequence import source_cue_id_of
        known = {cue.id for cue in self.project.cues}
        self.selected_ids = {str(key) if str(key) in known else source_cue_id_of(str(key))
                             for key in cue_ids} & known
        self.selected_cues = [cue for cue in self.frozen_project.cues if cue.id in self.selected_ids]
        self.protected_ids = {cue.id for cue in self.selected_cues
                              if manual_position(cue) or _has_keyframes(cue.transform)}
        self.command = None
        self.setWindowTitle('预览字幕重新排版')
        self.resize(1060, 520)
        layout = QVBoxLayout(self)
        description = QLabel('预览按实际重叠范围重新分配所选字幕的基础位置；未选字幕作为固定障碍。\n'
                             '默认保留手动位置和关键帧。确认应用后可一次撤销，文字、时间、说话人和关键帧保持原样。', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        self.reset_manual = QCheckBox('允许重置所选手动基础位置（关键帧保留）', self)
        self.reset_manual.setEnabled(bool(self.protected_ids))
        layout.addWidget(self.reset_manual)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(['字幕', '文字', '原基础位置', '预览基础位置', '手动状态', '提示'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.warning_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.apply_button = buttons.addButton('应用重新排版（可撤销）', QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reset_manual.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        eligible = self.selected_ids if self.reset_manual.isChecked() else self.selected_ids-self.protected_ids
        command, layout = rearrange_subtitles_command(self.frozen_project, eligible)
        # The reviewed command contains the frozen before/after presentation.
        # Bind it to the live owner only for a guarded, explicit stack push.
        if command is not None:
            command.project = self.project
            command.changed = self.page._changed
        self.command = command
        preview = deepcopy(self.frozen_project)
        for cue in preview.cues:
            if command is not None and cue.id in command.after:
                cue.transform = deepcopy(command.after[cue.id][4])
        after_cues = {cue.id:cue for cue in preview.cues}
        self.table.setRowCount(0)
        for cue in self.selected_cues:
            row = self.table.rowCount()
            self.table.insertRow(row)
            states = []
            if manual_position(cue):states.append('手动位置')
            if _has_keyframes(cue.transform):states.append('关键帧')
            status = '、'.join(states) or '自动位置'
            notes = [warning.split(':', 1)[-1] for warning in layout.warnings
                     if warning.startswith(cue.id+':')]
            if cue.id not in eligible:
                notes.insert(0, '已保护；本次不重排')
            elif cue.id in self.protected_ids:
                notes.insert(0, '仅重置基础位置；关键帧保留')
            elif command is None or cue.id not in command.after:
                notes.insert(0, '位置无需改变')
            for column, value in enumerate((cue.id, cue.text, _base_position(self.frozen_project, cue),
                    _base_position(preview, after_cues[cue.id]), status, '；'.join(notes))):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.warning_label.setText('\n'.join(layout.warnings) or
            f'所选 {len(self.selected_ids)} 条；本次可重排 {len(eligible)} 条；保留 {len(self.selected_ids-eligible)} 条手动或关键帧字幕。')
        self.apply_button.setEnabled(command is not None)

    def apply(self):
        current = self.page.project
        if current is not self.project or _snapshot(current) != self.before:
            self.page._show_studio_hint('工程在预览期间已改变，请重新预览字幕排版。')
            self.reject()
            return False
        if self.command is not None:
            self.page.undo_stack.push(self.command)
            self.command = None
        self.accept()
        return True


def rearrange_now(page, cue_ids):
    """One-click re-layout from the timeline 调整 menu (2026-10-18, user).

    Same command the preview applies, without the table: the scope's captions
    that have no manual position or keyframes, one undo step. Returns how many
    captions moved."""
    from ..i18n import tr
    from ..timeline.studio_edit_sequence import source_cue_id_of
    project = page.project
    if project is None:
        return 0
    cues = {cue.id: cue for cue in project.cues}
    ids = {str(key) if str(key) in cues else source_cue_id_of(str(key)) for key in cue_ids} & set(cues)
    if not ids:
        page._show_studio_hint(tr('先选中要重新排版的字幕'))
        return 0
    kept = {key for key in ids if manual_position(cues[key]) or _has_keyframes(cues[key].transform)}
    command, layout = rearrange_subtitles_command(project, ids - kept, changed=page._changed)
    moved = 0 if command is None else sum(1 for key, after in command.after.items()
                                          if after != command.before.get(key))
    if command is None or not moved:
        text = tr('字幕位置已经不重叠，无需重新排版')
    else:
        page.undo_stack.push(command)
        text = tr('已重新排版 {count} 条字幕的位置（可撤销）', count=moved)
    if kept:
        text = f"{text}{tr('；{count} 条手动摆放或带关键帧的保持不动', count=len(kept))}"
    if layout.warnings:
        text = f"{text}{tr('；{count} 处放不下仍会重叠', count=len(layout.warnings))}"
    page._show_studio_hint(text)
    return moved


def open_layout_preview(page, cue_ids):
    """Modeless explicit review; opening/cancelling never changes the project."""
    if page.project is None:
        return None
    dialog = SubtitleLayoutPreview(page, cue_ids)
    page._subtitle_layout_preview = dialog
    dialog.open()
    return dialog
