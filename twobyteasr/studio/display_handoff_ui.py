"""Explicit, undoable review of editorial tails in existing projects."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel,
                              QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..subtitle_rules.display_timing import project_display_tail_plan


def _cue_signature(project):
    instances=project.studio_state.get('caption_timeline',{}).get('instances',{})
    return {c.id: (c.start_ms, c.end_ms, c.speaker_id, c.text, tuple(c.evidence_refs),repr(c.transform),
                   tuple(instances.get(c.id,{}).get(key) for key in
                         ('protected_start','protected_end','manual_timing','source_start_ms','source_end_ms','source_path')))
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
        layout.addWidget(QLabel('在阅读预算内优先顺接短交接，显示决定与声学事实分别记录；可靠字时的显示补偿单独处理。\n'
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
            decisions=[p for p in self.audit['pairs_before'] if p['left']==cue.id]
            editorial=any(p['classification']=='editorial_handoff' for p in decisions)
            reason='编辑显示顺接；原始发声证据不变' if editorial else '按可用字时或来源收口显示拖尾'
            for col, value in enumerate((cue.id, cue.text, f'{cue.end_ms / 1000:.3f}s',
                                        f'{self.ends[cue.id] / 1000:.3f}s', reason)):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, col, item)
        layout.addWidget(self.table)
        counts = self.audit['counts']
        layout.addWidget(QLabel(f"可收口 {len(self.ends)} 条；来源重叠说明 {counts['source_overlap_unverified']} 对；"
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
    from ..subtitle_rules.display_continuity import project_handoff_plan
    from ..i18n import tr
    project = page.project
    if project is None:
        return 0
    selected = getattr(page,'selected_cue_ids',lambda:[])()
    # One selected row is the editor focus. An explicit multi-selection owns
    # a range; ordinary focused playback retains the whole-project action.
    if len(selected)<2:
        selected=[]
    before = _cue_signature(project)
    audit=[]
    progress_dialog = None
    from PySide6.QtWidgets import QWidget, QProgressDialog, QApplication
    if isinstance(page,QWidget) and len(project.cues)>1000:
        progress_dialog=QProgressDialog('正在计算字幕显示衔接','取消',0,len(project.cues),page)
        progress_dialog.setMinimumDuration(200)
    def progress(done,total):
        if progress_dialog is not None:
            progress_dialog.setValue(done)
            QApplication.processEvents()
            return not progress_dialog.wasCanceled()
        return True
    try:
        ends = project_handoff_plan(project,selected,progress=progress,audit=audit)
    finally:
        if progress_dialog is not None:
            progress_dialog.close()
    if ends is None or project is not page.project or _cue_signature(project)!=before:
        page._show_studio_hint('字幕衔接已取消，或工程在计算期间发生变化')
        return 0
    page._last_display_handoff_audit=audit
    if not ends:
        protected={row['cue_id'] for row in audit if row['reason']=='manual_or_source_boundary'}
        limited={row['cue_id'] for row in audit if row['reason']=='maximum_display_duration'}
        page._show_studio_hint(f'没有可自动衔接的微缝。保留 {len(protected)} 处人工或来源边界，'
                              f'{len(limited)} 处最长显示时长约束。')
        return 0
    from ..timeline.studio_commands import BridgeShortGapsCommand
    page.undo_stack.push(BridgeShortGapsCommand(project, ends, page._changed,audit=audit))
    page._show_studio_hint(tr('已衔接 {count} 处字幕显示间隙（Ctrl+Z 可撤销）', count=len(ends)))
    return len(ends)


def open_handoff_preview(page):
    if page.project is None:
        return None
    dialog = DisplayHandoffPreview(page)
    page._display_handoff_preview = dialog  # Retain the modeless review object.
    dialog.open()
    return dialog
