"""Detached AI generation progress window.

A small always-visible non-modal window while a web theme generates: progress
bar, elapsed / ETA, the live output tail, and (on finish) the persisted trace
JSON path so runs can be audited and improved after the fact.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .i18n import bind_text


class AIGenerationProgressWindow(QDialog):
    """Non-modal; one instance per studio page, shown during generation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        bind_text(self, 'AI 生成进度', property='windowTitle')
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(480, 300)
        self._started_at: float | None = None
        self._estimated_total: float | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.stage_label = QLabel("正在连接 Provider…")
        self.stage_label.setObjectName("contextMeta")
        self.stage_label.setWordWrap(True)
        header.addWidget(self.stage_label, 1)
        self.close_button = QPushButton("隐藏")
        self.close_button.setObjectName("studioButton")
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.time_label = QLabel("已耗时 0:00 · 等待真实进展")
        self.time_label.setObjectName("contextMeta")
        layout.addWidget(self.time_label)

        self.tail = QPlainTextEdit()
        self.tail.setReadOnly(True)
        self.tail.setMaximumBlockCount(400)
        bind_text(self.tail, '模型实时输出…', property='placeholderText')
        layout.addWidget(self.tail, 1)

        self.trace_label = QLabel("")
        self.trace_label.setObjectName("contextMeta")
        self.trace_label.setWordWrap(True)
        layout.addWidget(self.trace_label)

        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)

    # -- lifecycle ---------------------------------------------------------
    def begin(self) -> None:
        self._started_at = time.monotonic()
        self._estimated_total = None
        self.progress.setValue(0)
        self.tail.clear()
        self.trace_label.setText("")
        bind_text(self.stage_label, '正在连接 Provider…')
        self._ticker.start()
        self.show()
        self.raise_()

    def finish(self, ok: bool, summary: str, trace_path: str = "") -> None:
        self._ticker.stop()
        self.progress.setValue(100 if ok else self.progress.value())
        self.stage_label.setText(summary)
        if trace_path:
            bind_text(self.trace_label, '运行 JSON 已记录：{trace_path}', trace_path=trace_path)
        # Leave the window open so the user can read the result / trace path.

    # -- updates -----------------------------------------------------------
    def update_stage(self, stage: str) -> None:
        self.stage_label.setText(str(stage or ""))

    def update_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, int(value))))

    def append_tail(self, chunk: str) -> None:
        self.tail.appendPlainText(str(chunk or "").strip()[-2000:])

    def _tick(self) -> None:
        if self._started_at is None:
            return
        elapsed = max(0, time.monotonic() - self._started_at)
        minutes, seconds = divmod(int(elapsed), 60)
        if self._estimated_total is not None:
            remaining = max(0, self._estimated_total - elapsed)
            r_minutes, r_seconds = divmod(int(remaining), 60)
            bind_text(self.time_label, '已耗时 {minutes}:{seconds:02d} · 预计剩余 {r_minutes}:{r_seconds:02d}', minutes=minutes, seconds=seconds, r_minutes=r_minutes, r_seconds=r_seconds)
        else:
            bind_text(self.time_label, '已耗时 {minutes}:{seconds:02d} · 以实际阶段和候选结果为准', minutes=minutes, seconds=seconds)
