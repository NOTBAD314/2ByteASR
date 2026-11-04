"""Read-only API usage view. Reads SQLite in a worker, never on an edit event."""
from __future__ import annotations

import json
import threading
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QPushButton, QTableWidget, QTableWidgetItem, QPlainTextEdit,
                              QHeaderView, QAbstractItemView)
from ..providers.api_usage import UsageTotals, call_payload, usage_text
from ..i18n import tr


def stage_group(stage):
    stage = str(stage).lower()
    if 'translat' in stage:
        return '翻译'
    if 'group' in stage or 'segment' in stage or 'sentence' in stage:
        return '断句'
    if 'polish' in stage or 'proof' in stage:
        return '校对'
    if 'test' in stage or 'probe' in stage:
        return '连接测试'
    return '其他'


def totals_for(rows):
    totals = UsageTotals()
    for row in rows:
        totals.add(call_payload(stage=row['stage'], usage=row.get('raw_usage'),
                                request_id=row['request_id'], estimated_cost=row.get('cost', {'known': False})))
    return totals


class _Signals(QObject):
    loaded = Signal(object, str)


class UsageDialog(QDialog):
    def __init__(self, parent=None, *, project=None, task_id=''):
        super().__init__(parent)
        self.setWindowTitle(tr('API 用量与估算费用'))
        self.setObjectName('apiUsageDialog')
        self.resize(1020, 640)
        self.project_id = str(getattr(project, 'project_id', '') or '')
        self.recognition_ref = (getattr(project, 'generation_metadata', {}) or {}).get('recognition_result', {})
        self.task_id = task_id
        self.rows = []
        self._loading = False
        self._signals = _Signals(self)
        self._signals.loaded.connect(self._loaded)
        layout = QVBoxLayout(self)
        note = QLabel(tr('Token 来自 API 实际回传；费用按每次请求保存的费率估算，不是最终账单。未知用量不会算作零。本机翻译缓存不会产生 API 请求。'))
        note.setWordWrap(True); layout.addWidget(note)
        controls = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem(tr('本软件已记录'), 'all')
        if self.project_id:
            self.scope.addItem(tr('目前工程累计'), 'project')
        if task_id:
            self.scope.addItem(tr('本次任务'), 'task')
        self.scope.setCurrentIndex(self.scope.count()-1)
        self.stage = QComboBox(); self.stage.addItems([tr(x) for x in ('全部步骤', '断句', '校对', '翻译', '连接测试', '其他')])
        self.stage.setItemData(0, '')
        for index, name in enumerate(('断句','校对','翻译','连接测试','其他'),1):
            self.stage.setItemData(index,name)
        controls.addWidget(self.scope); controls.addWidget(self.stage); controls.addStretch()
        refresh = QPushButton(tr('刷新')); refresh.clicked.connect(self.refresh); controls.addWidget(refresh)
        layout.addLayout(controls)
        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([tr(x) for x in ('请求时间 UTC', '步骤', '模型', '输入 / 输出', '缓存命中 / 未命中', '估算费用', '状态')])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(150)
        layout.addWidget(self.details)
        self.scope.currentIndexChanged.connect(self.render)
        self.stage.currentIndexChanged.connect(self.render)
        self.table.itemSelectionChanged.connect(self._selection)
        self.refresh()

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        signals = self._signals
        def load():
            from ..providers.usage_ledger import read_rows, flush, write_error
            try:
                flush()
                rows, error = read_rows(), write_error()
            except Exception as exc:
                rows, error = [], str(exc)
            from shiboken6 import isValid
            if isValid(signals):
                signals.loaded.emit(rows, error)
        threading.Thread(target=load, name='usage-view-reader', daemon=True).start()

    def _loaded(self, rows, error):
        self._loading = False
        self.rows, self.error = rows, error
        self.render()

    def render(self, *_):
        scope, stage = self.scope.currentData(), self.stage.currentData()
        rows = [row for row in self.rows if
                (scope != 'project' or row.get('project_id') == self.project_id or
                    (self.recognition_ref.get('job_id') and row.get('task_id') == self.recognition_ref['job_id']
                     and row.get('media_fingerprint') == self.recognition_ref.get('media_fingerprint'))) and
                (scope != 'task' or row.get('task_id') == self.task_id) and
                (not stage or stage_group(row['stage']) == stage)]
        summary = usage_text(totals_for(rows)) or tr('此范围尚无已记录请求。')
        if len(rows)>500:
            summary += tr(' · 总计 {count} 次请求，表格显示最近 500 次。',count=len(rows))
        rows=rows[:500]
        self.visible_rows = rows
        error = getattr(self, 'error', '')
        self.summary.setText(summary + (tr(' · 记账失败：{error}', error=error) if error else ''))
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            usage, cost = row.get('usage') or {}, row.get('cost') or {}
            fee = (f"{cost['currency']} {cost['low']}" + (f"–{cost['high']}" if cost['high'] != cost['low'] else '')) if cost.get('known') else tr('未知')
            values = (row['at'][:19], tr(stage_group(row['stage'])), row['model'],
                      f"{usage.get('input_tokens', '?')} / {usage.get('output_tokens', '?')}",
                      f"{usage.get('cached_input_tokens', '?')} / {usage.get('uncached_input_tokens', '?')}", fee,
                      tr({'received':'已返回用量','usage_unknown':'用量未知','pending':'请求中／尚未取得用量',
                          'cancelled':'已取消','total_timeout':'请求超时','rate_limited':'限流',
                          'auth_error':'凭据被拒绝','quota_exhausted':'余额或额度不足'}.get(row['status'],'请求异常；详情可查看')))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def _selection(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.visible_rows):
            self.details.setPlainText(json.dumps(self.visible_rows[row], ensure_ascii=False, indent=2))


def open_usage(parent, *, project=None, task_id=''):
    from shiboken6 import isValid
    dialog = getattr(parent, '_usage_dialog', None)
    if dialog is not None and isValid(dialog):
        dialog.refresh(); dialog.show(); dialog.raise_(); dialog.activateWindow()
        return dialog
    dialog = UsageDialog(parent, project=project, task_id=task_id)
    parent._usage_dialog = dialog
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog
