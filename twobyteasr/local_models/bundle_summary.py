"""「当前组合」, the download estimate and the model health card for the workspace sidebar.

2026-11-23 (user): only the model workshop showed the current bundle in its sidebar; the term
library and the recognition history did not, so the left column changed on every switch between
the three pages, which looked odd and felt jerky - it should always show and never change.

The workshop owns the real one (``source``: it computes the bundle and the model health) and
every other page shows a copy (``BundleSummaryPanel(source=False)``) that takes over its texts
whenever the workshop refreshes (``publish``). A copy made before the workshop has computed
anything shows the same starting texts the workshop shows while it checks.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

ROLES = (("primary", "主力转写", "MOSS"), ("timeline", "字幕时间轴", "FireRed"), ("review", "文字复核", "Qwen3-ASR"))

_COPIES: "weakref.WeakSet[BundleSummaryPanel]" = weakref.WeakSet()
_SOURCE = None                                          # weakref to the workshop's panel


class BundleSummaryPanel(QWidget):
    """The sidebar's lower part, the same on every workspace page."""

    storage_requested = Signal()

    def __init__(self, *, source: bool = False, parent=None):
        global _SOURCE
        super().__init__(parent)
        self.setObjectName("bundleSummaryPanel")
        self.source = bool(source)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addSpacing(12)
        label = QLabel("当前组合")
        label.setObjectName("workshopMuted")
        label.setWordWrap(True)
        layout.addWidget(label)
        combo = QFrame()
        combo.setObjectName("workshopComboCard")
        combo_layout = QVBoxLayout(combo)
        combo_layout.setContentsMargins(12, 10, 12, 12)
        combo_layout.setSpacing(6)
        title_row = QHBoxLayout()
        self.combo_title = QLabel("质量优先")
        self.combo_title.setObjectName("workshopComboHeading")
        self.combo_title.setWordWrap(True)
        title_row.addWidget(self.combo_title, 1)
        badge = QLabel("推荐")
        badge.setObjectName("workshopRecommendationBadge")
        title_row.addWidget(badge)
        combo_layout.addLayout(title_row)
        rule = QFrame()
        rule.setObjectName("workshopRule")
        rule.setFixedHeight(1)
        combo_layout.addWidget(rule)
        self.combo_model_labels: dict[str, QLabel] = {}
        self.combo_status_labels: dict[str, QLabel] = {}
        for key, role, model_name in ROLES:
            row = QHBoxLayout()
            row.setSpacing(8)
            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            role_label = QLabel(role)
            role_label.setObjectName("workshopComboRole")
            text_box.addWidget(role_label)
            model_label = QLabel(model_name)
            model_label.setObjectName("workshopComboModel")
            # The narrow column: an API bundle's "provider · model" may take two lines.
            model_label.setWordWrap(True)
            text_box.addWidget(model_label)
            row.addLayout(text_box, 1)
            status_label = QLabel()
            status_label.setObjectName("workshopComboStatus")
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(status_label, 0, Qt.AlignmentFlag.AlignBottom)
            combo_layout.addLayout(row)
            self.combo_model_labels[key] = model_label
            self.combo_status_labels[key] = status_label
            if key != "review":
                combo_layout.addSpacing(2)
        layout.addWidget(combo)
        layout.addStretch(1)
        self.download_estimate = QLabel()
        self.download_estimate.setObjectName("workshopTiny")
        self.download_estimate.setWordWrap(True)
        layout.addWidget(self.download_estimate)
        health = QFrame()
        health.setObjectName("workshopHealthCard")
        health_layout = QVBoxLayout(health)
        health_layout.setContentsMargins(12, 10, 12, 12)
        health_layout.setSpacing(6)
        health_title = QLabel("模型组合健康")
        health_title.setObjectName("workshopSection")
        health_title.setWordWrap(True)
        health_layout.addWidget(health_title)
        self.health_summary = QLabel("正在检查模型文件…")
        self.health_summary.setObjectName("workshopTiny")
        self.health_summary.setWordWrap(True)
        health_layout.addWidget(self.health_summary)
        self.health_bar = QProgressBar()
        self.health_bar.setObjectName("workshopHealthBar")
        self.health_bar.setTextVisible(False)
        self.health_bar.setFixedHeight(6)
        self.health_bar.setRange(0, 1)
        self.health_bar.setValue(0)
        health_layout.addWidget(self.health_bar)
        self.storage_button = QPushButton("存储管理")
        self.storage_button.setObjectName("workshopSecondary")
        self.storage_button.clicked.connect(self.storage_requested)
        health_layout.addWidget(self.storage_button)
        layout.addWidget(health)
        if self.source:
            _SOURCE = weakref.ref(self)
        else:
            # Outside the workshop page its style sheet is not inherited: the panel carries it.
            self.refresh_theme_palette()
            _COPIES.add(self)
            self.storage_requested.connect(self._open_storage)
            source_panel = _SOURCE() if _SOURCE is not None else None
            if source_panel is not None:
                self.take_from(source_panel)

    def refresh_theme_palette(self) -> None:
        if self.source:
            return
        from ..design.typography import emphasis_qss
        from .model_workshop import build_workshop_qss
        self.setStyleSheet(emphasis_qss(build_workshop_qss()))

    def take_from(self, other: "BundleSummaryPanel") -> None:
        """Show what ``other`` shows."""
        self.combo_title.setText(other.combo_title.text())
        for key in self.combo_model_labels:
            self.combo_model_labels[key].setText(other.combo_model_labels[key].text())
            mine, theirs = self.combo_status_labels[key], other.combo_status_labels[key]
            mine.setText(theirs.text())
            ready = theirs.property("ready")
            if mine.property("ready") != ready:
                mine.setProperty("ready", ready)
                mine.style().unpolish(mine)
                mine.style().polish(mine)
        self.download_estimate.setText(other.download_estimate.text())
        self.health_summary.setText(other.health_summary.text())
        self.health_summary.setToolTip(other.health_summary.toolTip())
        self.health_bar.setRange(other.health_bar.minimum(), other.health_bar.maximum())
        self.health_bar.setValue(other.health_bar.value())

    def _open_storage(self) -> None:
        """A copy's 存储管理: the workshop's storage manager (the workshop owns the files)."""
        from PySide6.QtCore import QTimer
        window = self.window()
        opener = getattr(window, '_open_model_workshop', None)
        if not callable(opener):
            return
        opener()
        built = getattr(window, 'built_page', None)
        workshop = built('workshop') if callable(built) else None
        if workshop is not None and hasattr(workshop, '_show_storage_manager'):
            def show():
                ensure = getattr(workshop, 'ensure_ui', None)
                if callable(ensure):
                    ensure()
                workshop._show_storage_manager()
            QTimer.singleShot(0, show)

    def publish(self) -> None:
        """The workshop's panel changed: every copy shows the same."""
        if not self.source:
            return
        for copy in list(_COPIES):
            try:
                copy.take_from(self)
            except RuntimeError:                         # its widget is gone
                _COPIES.discard(copy)


__all__ = ["BundleSummaryPanel"]
