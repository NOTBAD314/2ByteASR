"""Optional, bounded view over the existing task's public event journal."""
import json
import time
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QPlainTextEdit, QApplication, QCheckBox, QLabel

from .i18n import bind_text, tr, current_language


class ExecutionProcessView(QWidget):
    def __init__(self, event_supplier, parent=None):
        super().__init__(parent)
        self.supplier=event_supplier
        self.signature=None
        self.settings=QSettings()
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.toggle=QPushButton('查看执行过程')
        self.toggle.setCheckable(True)
        layout.addWidget(self.toggle)
        self.body=QWidget()
        inner=QVBoxLayout(self.body)
        inner.setContentsMargins(0,0,0,0)
        hint=QLabel('仅显示应用观察到的事件与公开摘要。当前服务未提供摘要时，不展示内部思考；无中间事件时无法判断内部进度。')
        hint.setWordWrap(True)
        inner.addWidget(hint)
        row=QHBoxLayout()
        self.search=QLineEdit()
        bind_text(self.search, '搜索过程、查询词或来源', property='placeholderText')
        row.addWidget(self.search,1)
        self.follow=QCheckBox('跟随最新')
        self.follow.setChecked(True)
        row.addWidget(self.follow)
        copy=QPushButton('复制脱敏过程')
        copy.clicked.connect(lambda:QApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(copy)
        inner.addLayout(row)
        self.text=QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        self.text.setMinimumHeight(150)
        self.text.setMaximumHeight(280)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        inner.addWidget(self.text)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self._toggle)
        self.search.textChanged.connect(lambda:self.refresh(force=True))
        self.text.verticalScrollBar().actionTriggered.connect(lambda _a:self.follow.setChecked(False))
        self.follow.toggled.connect(lambda checked:self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum()) if checked else None)
        self.toggle.setChecked(self.settings.value('execution/show_details',False,type=bool))
        self.body.setVisible(self.toggle.isChecked())
        self.timer=QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def _toggle(self, checked):
        self.body.setVisible(checked)
        self.settings.setValue('execution/show_details',checked)
        self.refresh(force=True)

    def refresh(self, force=False):
        if not self.toggle.isChecked():return
        events=list(self.supplier() or [])[-1500:]
        signature=(current_language(),len(events),events[-1].get('seq',events[-1].get('request_seq')) if events else 0,self.search.text())
        if signature==self.signature and not force:return
        self.signature=signature
        query=self.search.text().casefold()
        lines=[]
        for event in events:
            payload=event.get('payload','')
            payload=payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False)
            source=tr({'application':'应用','provider':'服务端','cli_stderr':'CLI错误输出','http':'页面响应'}.get(event.get('source'),event.get('source','')))
            stamp=time.strftime('%H:%M:%S',time.localtime(event.get('timestamp',0)))
            line=f"{stamp} #{event.get('seq',event.get('request_seq',0))} [{source}/{event.get('kind','')}] {payload[:3000]}"
            if not query or query in line.casefold():lines.append(line)
        bar=self.text.verticalScrollBar()
        old=bar.value()
        self.text.setPlainText('\n'.join(lines) or tr('尚无符合条件的真实事件。'))
        bar.setValue(bar.maximum() if self.follow.isChecked() else old)
        self.text.horizontalScrollBar().setValue(0)
