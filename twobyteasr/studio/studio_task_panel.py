"""Nonmodal, reopenable Studio task details with throttled incremental updates."""

from __future__ import annotations

import json
from collections import Counter

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QTimer, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableView, QVBoxLayout)

from .studio_task_progress import STATUS_TEXT, TERMINAL


def time_text(value):
    value = max(0, int(value or 0))
    seconds, millis = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


class TaskTableModel(QAbstractTableModel):
    headers = ['原字幕范围', '素材时间', '阶段 / 结果', '尝试', '原因']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.keys = []
        self.indexes = {}
        self.rendered = {}

    def set_task(self, task):
        self.beginResetModel()
        self.task = task
        self.keys = list(task.rows) if task else []
        self.indexes = {key: index for index, key in enumerate(self.keys)}
        self.rendered = dict(task.rows) if task else {}
        self.endResetModel()

    def sync(self):
        if self.task is None:
            return
        added = [key for key in self.task.rows if key not in self.indexes]
        if added:
            self.beginInsertRows(QModelIndex(), len(self.keys), len(self.keys)+len(added)-1)
            for key in added:
                self.indexes[key] = len(self.keys)
                self.keys.append(key)
            self.endInsertRows()
        for key, row in self.task.rows.items():
            if self.rendered.get(key) is not row:
                index = self.indexes[key]
                self.rendered[key] = row
                self.dataChanged.emit(self.index(index, 0), self.index(index, 4))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.keys)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section] if orientation == Qt.Orientation.Horizontal else str(section+1)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self.task.rows[self.keys[index.row()]]
        column = index.column()
        if column == 0:
            ids = row.get('cue_ids', ())
            if row.get('range_label') and role == Qt.ItemDataRole.DisplayRole:
                return row['range_label']
            source_rows = row.get('source_rows')
            if source_rows and role == Qt.ItemDataRole.DisplayRole:
                return f'第 {source_rows[0]} 条' if len(source_rows) == 1 else f'第 {source_rows[0]}–{source_rows[-1]} 条（{len(ids)} 条）'
            return ', '.join(ids) if len(ids) <= 3 else f'{ids[0]}…{ids[-1]}（{len(ids)} 条）'
        if column == 1:
            return f"{time_text(row.get('start_ms'))}–{time_text(row.get('end_ms'))}"
        if column == 2:
            status = row.get('status', 'pending')
            return STATUS_TEXT.get(status, status) if status in TERMINAL else row.get('phase', '')
        if column == 3:
            return str(row.get('attempts', 0))
        return str(row.get('error', ''))


class SubtitleTaskPanel(QDialog):
    locate = Signal(object)
    retry = Signal(object)
    cancel = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字幕任务进度与结果")
        self.resize(940, 640)
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.tasks = QComboBox()
        self.tasks.currentIndexChanged.connect(self._select_task)
        layout.addWidget(self.tasks)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.counts_label = QLabel()
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)
        self.only_failures = QCheckBox('只看失败、需检查和取消范围')
        self.only_failures.toggled.connect(self._filter_rows)
        layout.addWidget(self.only_failures)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableView()
        self.table_model = TaskTableModel(self.table)
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 45)
        self.table.selectionModel().selectionChanged.connect(self._show_details)
        splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        splitter.setSizes([340, 180])
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.locate_button = QPushButton("定位所选范围")
        self.locate_button.clicked.connect(self._locate)
        actions.addWidget(self.locate_button)
        self.retry_button = QPushButton("仅重试所选失败范围")
        self.retry_button.clicked.connect(self._retry)
        actions.addWidget(self.retry_button)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.clicked.connect(lambda: self.cancel.emit(self.current.task_id) if self.current else None)
        actions.addWidget(self.cancel_button)
        collapse = QPushButton("收起，继续运行")
        collapse.clicked.connect(self.hide)
        actions.addWidget(collapse)
        layout.addLayout(actions)
        self._models = {}
        self.current = None
        self._row_keys = []
        self._row_indexes = {}
        self._rendered_rows = {}
        self._painted_revision = -1
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def add_task(self, task):
        self._models[task.task_id] = task
        self.tasks.addItem(task.kind, task.task_id)
        self.tasks.setCurrentIndex(self.tasks.count() - 1)
        self._select_task()

    def _select_task(self, *_):
        self.current = self._models.get(self.tasks.currentData())
        self._row_keys = []
        self._row_indexes = {}
        self._rendered_rows = {}
        self.table_model.set_task(self.current)
        self._row_keys = self.table_model.keys
        self._row_indexes = self.table_model.indexes
        self._painted_revision = -1
        self.details.clear()
        self.refresh()

    def selected_record(self):
        index = self.table.currentIndex().row()
        if self.current and 0 <= index < len(self._row_keys):
            return self.current.rows[self._row_keys[index]]
        return None

    def refresh(self):
        task = self.current
        if not task or not self.isVisible():
            return
        self.summary.setText(task.summary())
        counts = task.counts()
        self.progress.setRange(0, max(1, counts['total']))
        self.progress.setValue(counts['processed'])
        self.counts_label.setText(" · ".join(f"{STATUS_TEXT[key]} {counts[key]}" for key in
            ("applied", "unchanged", "suggestion", "review", "failed", "cancelled")))
        causes = Counter()
        for row in task.rows.values():
            if row.get('status') in {'failed', 'review'} and row.get('error'):
                causes[str(row['error'])] += len(row.get('cue_ids', ()))
        if causes:
            self.counts_label.setText(self.counts_label.text() + '\n共同原因及受影响字幕\n' +
                '\n'.join(f'{count} 条 · {reason}' for reason, count in causes.most_common(3)))
        self.cancel_button.setEnabled(task.ended is None and not task.cancelled)
        self.retry_button.setEnabled(task.ended is not None)
        if self._painted_revision == task.revision:
            return
        self._painted_revision = task.revision
        self.table_model.sync()
        self._show_details()
        self._filter_rows()

    def _filter_rows(self):
        if self.current:
            for key, index in self._row_indexes.items():
                row = self.current.rows[key]
                hidden = self.only_failures.isChecked() and row.get('status') not in {'failed', 'review', 'cancelled'}
                if hidden != self.table.isRowHidden(index):
                    self.table.setRowHidden(index, hidden)

    def _show_details(self, *_):
        row = self.selected_record()
        if row is None:
            return
        text = '\n'.join(['输入原文', row.get('input_text', ''), '', '当前结果',
            STATUS_TEXT.get(row.get('status'), row.get('phase', '')),
            row.get('error') or row.get('phase', ''), '',
            '校验后的分段', '\n'.join(row.get('validated_texts', ())), '',
            '最终实际写回', '\n'.join(row.get('final_texts', ())), '',
            '下一步', '可定位原字幕并试听核对。修正模型配置或手动编辑后，可仅重试所选失败范围。', '',
            '完整处理记录（含模型原始响应）', json.dumps(row, ensure_ascii=False, indent=2, default=str)])
        if text != self.details.toPlainText():
            self.details.setPlainText(text)
        self.retry_button.setEnabled(self.current.ended is not None and row.get('status') in {'failed', 'review', 'cancelled'})

    def _locate(self):
        row = self.selected_record()
        if row:
            self.locate.emit(dict(task_id=self.current.task_id, record=row))

    def _retry(self):
        row = self.selected_record()
        if row and row.get('status') in {'failed', 'review', 'cancelled'} and self.current.ended:
            self.retry.emit(dict(task_id=self.current.task_id, record=row))
