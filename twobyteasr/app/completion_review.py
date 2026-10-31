"""Exactly the project-relative items counted on the completion page."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem, QPushButton, QLabel
from ..i18n import tr


def open_current_review(window):
    tasks = getattr(window, '_completion_tasks', ())
    index = window.result_task_selector.currentIndex()
    if not 0 <= index < len(tasks):
        return
    item, project = tasks[index]
    if project is None:
        return
    from ..recognition.processing_recovery import refresh_completion_evidence
    evidence = window._completion_task_evidence[window._completion_task_key(item)]
    refresh_completion_evidence(project, evidence)
    current = evidence['display_payload'].get('_current_review') or {}
    dialog = QDialog(window)
    dialog.setWindowTitle(tr('当前待检查内容'))
    dialog.resize(900, 580)
    layout = QVBoxLayout(dialog)
    note = QLabel(tr('按当前工程统计问题项；同一条字幕可以有多个问题。警告和可选词库建议另列。'))
    note.setWordWrap(True)
    layout.addWidget(note)
    tabs = QTabWidget(dialog)
    layout.addWidget(tabs)
    cues = {c.id: c for c in project.cues}
    for title, rows in ((tr('待检查'), current.get('items', ())),
                        (tr('可选词库建议'), current.get('suggestions', ())),
                        (tr('警告与历史'), [*current.get('warnings', ()), *current.get('history', ())])):
        tree = QTreeWidget(tabs)
        tree.setHeaderLabels([tr('位置'), tr('原因'), tr('当前字幕 / 说明')])
        tree.setColumnWidth(0, 110)
        tree.setColumnWidth(1, 160)
        for row in rows:
            ids = [key for key in row.get('cue_ids', ()) if key in cues]
            text = ' / '.join(cues[key].text for key in ids) or str(row.get('detail') or row.get('text') or '')
            at = cues[ids[0]].start_ms/1000 if ids else row.get('timestamp')
            position = f'{int(at)//60}:{int(at)%60:02d}' if at is not None else tr('说话人') if row.get('target') == 'speakers' else '—'
            entry = QTreeWidgetItem([position, str(row.get('category') or ''), text])
            entry.setData(0, Qt.ItemDataRole.UserRole, row)
            entry.setToolTip(2, str(row.get('detail') or text))
            tree.addTopLevelItem(entry)
        tabs.addTab(tree, f'{title} · {len(rows)}')
    button = QPushButton(tr('打开并定位所选内容'))
    layout.addWidget(button)

    def locate():
        selected = tabs.currentWidget().currentItem()
        row = selected.data(0, Qt.ItemDataRole.UserRole) if selected is not None else None
        if not row or not (row.get('cue_ids') or row.get('target') == 'speakers'):
            note.setText(tr('这条属于历史记录，没有对应的当前字幕；未计入待检查。'))
            return
        dialog.accept()
        open_review_row(window, item, row)
    button.clicked.connect(locate)
    dialog._review_tabs = tabs
    window._current_review_dialog = dialog
    dialog.exec()


def open_review_row(window, item, row):
    """Studio at one current review item: its first caption, or the speaker
    manager. A row without either opens the full list instead (2026-10-30)."""
    if not (row.get('cue_ids') or row.get('target') == 'speakers'):
        open_current_review(window)
        return

    def ready(studio):
        if row.get('target') == 'speakers':
            studio._open_speaker_manager()
        else:
            cue = next((c for c in studio.project.cues if c.id in row['cue_ids']), None)
            if cue is not None:
                studio.select_cue(cue.id)
                studio._seek(cue.start_ms/1000)
    window._open_completion_project(item.project_path, mode='edit', source='completion_current_review', on_ready=ready)
