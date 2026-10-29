"""Explicit, undoable review of editorial tails in existing projects."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel,
                              QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..subtitle_rules.display_timing import project_display_tail_plan


def _cue_signature(project):
    return {c.id: (c.start_ms, c.end_ms, c.speaker_id, c.text, tuple(c.evidence_refs))
            for c in project.cues}


class DisplayHandoffPreview(QDialog):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.project = page.project
        self.project_id = self.project.project_id
        self.ends, self.audit = project_display_tail_plan(self.project)
        self.before = _cue_signature(self.project)
        self.setWindowTitle('预览说话人交接边界')
        self.resize(820, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('优先按实测字词时间收口说话结束后的拖尾；没有字词时间时参考句子来源。真正重叠或证据不足的字幕保留。\n'
                               '应用只改变表中列出的结束时间；字幕文字、说话人、位置和动效保持原样，可一次撤销。'))
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(['字幕', '文字', '原结束时间', '预览结束时间', '依据'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for cue in self.project.cues:
            if cue.id not in self.ends:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate((cue.id, cue.text, f'{cue.end_ms / 1000:.3f}s',
                                        f'{self.ends[cue.id] / 1000:.3f}s', '发音已分开；收口拖尾并保留末字')):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, col, item)
        layout.addWidget(self.table)
        counts = self.audit['counts']
        layout.addWidget(QLabel(f"可收口 {len(self.ends)} 条；来源重叠待检查 {counts['source_overlap_unverified']} 对；"
                               f"证据不足 {counts['uncertain']} 对；独立重叠保留 {counts['acoustic']} 对。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.apply_button = buttons.addButton('应用结束时间（可撤销）', QDialogButtonBox.AcceptRole)
        self.apply_button.setEnabled(bool(self.ends))
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self):
        current = self.page.project
        if (current is not self.project or current.project_id != self.project_id
                or _cue_signature(current) != self.before
                or project_display_tail_plan(current)[0] != self.ends):
            self.page._show_studio_hint('工程在预览期间已改变，请重新预览交接边界。')
            self.reject()
            return
        if self.ends:
            from ..timeline.studio_commands import RepairDisplayHandoffsCommand
            self.page.undo_stack.push(RepairDisplayHandoffsCommand(current, self.ends, self.audit, self.page._changed))
        self.accept()


def bridge_short_gaps(page):
    """Close every caption gap of 0.5 s or less in one undo step (2026-10-10)."""
    from ..subtitle_rules.display_timing import SHORT_GAP_BRIDGE_MS, short_gap_bridges
    from ..i18n import tr
    project = page.project
    if project is None:
        return 0
    ends = short_gap_bridges([(c.id, c.speaker_id or '', c.start_ms, c.end_ms) for c in project.cues],
                             SHORT_GAP_BRIDGE_MS)
    if not ends:
        page._show_studio_hint(tr('没有 0.5 秒以内的字幕间隙需要衔接'))
        return 0
    from ..timeline.studio_commands import BridgeShortGapsCommand
    page.undo_stack.push(BridgeShortGapsCommand(project, ends, page._changed))
    page._show_studio_hint(tr('已衔接 {count} 处 0.5 秒以内的字幕间隙（Ctrl+Z 可撤销）', count=len(ends)))
    return len(ends)


def open_handoff_preview(page):
    if page.project is None:
        return None
    dialog = DisplayHandoffPreview(page)
    page._display_handoff_preview = dialog  # Retain the modeless review object.
    dialog.open()
    return dialog
