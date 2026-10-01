"""Shared management navigation for the desktop workbench.

The recognition home remains the primary work area.  Deep-management screens
reuse this compact navigation so the same destination is never represented by
different labels or different callbacks.
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from twobyteasr.ui_theme import GREEN, INK, MUTED


class WorkspaceNavigation(QWidget):
    recognition_requested = Signal()
    workshop_requested = Signal()
    terms_requested = Signal()
    history_requested = Signal()

    ITEMS = (
        ("recognition", "返回字幕识别", "fa5s.arrow-left"),
        ("workshop", "模型工坊", "fa5s.cubes"),
        ("terms", "术语库", "fa5s.book-open"),
        ("history", "识别记录", "fa5s.history"),
    )

    def __init__(self, active: str, parent=None):
        super().__init__(parent)
        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for key, label, icon_name in self.ITEMS:
            button = QPushButton(label)
            button.setObjectName("workspaceNav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _checked=False, value=key: self._activate(value))
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        self.set_active(active)

    def set_active(self, key: str):
        for item_key, _label, icon_name in self.ITEMS:
            checked = item_key == key
            button = self.buttons[item_key]
            button.setChecked(checked)
            button.setIcon(
                qta.icon(
                    icon_name,
                    color=GREEN if checked else MUTED,
                    color_active=GREEN,
                )
            )

    def _activate(self, key: str):
        signal = {
            "recognition": self.recognition_requested,
            "workshop": self.workshop_requested,
            "terms": self.terms_requested,
            "history": self.history_requested,
        }[key]
        signal.emit()


NAVIGATION_QSS = f"""
QPushButton#workspaceNav {{
    background: transparent;
    color: {INK};
    border: 0;
    border-radius: 10px;
    padding: 10px 12px;
    min-height: 22px;
    text-align: left;
    font-weight: 600;
}}
QPushButton#workspaceNav:hover {{
    background: #eeeae2;
}}
QPushButton#workspaceNav:checked {{
    background: #e6efe2;
    color: {GREEN};
    font-weight: 700;
}}
"""
