"""Our own round window frame for the Studio's candy windows (2026-11-15).

User (2026-11-15): 「字幕任务进度与结果」 and 「API 用量与估算费用」 still wore the Windows title bar,
which did not look like the rest; they should have their own, rounder frame. Both now sit in a
``RoundedWindow`` (the link download and AI cleanup windows' frame: soft shadow, rounded corners,
resizable edges, double-click to maximize) with a title bar of their own — a round accent badge,
the title, and round window buttons.

Usage: ``chrome = CandyChrome(dialog, '标题', 'fa5s.tasks')``, then build the content into
``chrome.layout``. The dialog keeps its object name, so its ``QDialog#name …`` style rules still
reach every widget inside; ``design/candy_chrome_qss.py`` styles the frame itself.
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .rounded_window import SHADOW

RADIUS = 22


class CandyChrome:
    def __init__(self, dialog, title: str, icon: str, *, maximizable: bool = True):
        from ..i18n import bind_text
        from .link_download_widgets import icon_label
        from .rounded_window import RoundedWindow, WindowButtons
        from .ui_zoom import set_size
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.root = QFrame(dialog)
        self.root.setObjectName('candyRoot')
        outer.addWidget(self.root)
        column = QVBoxLayout(self.root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.title_bar = QFrame()
        self.title_bar.setObjectName('candyTitleBar')
        row = QHBoxLayout(self.title_bar)
        row.setContentsMargins(14, 10, 10, 2)
        row.setSpacing(10)
        self.mark = icon_label(icon, 13, 'on_accent', 'candyMark')
        set_size(self.mark, fixed_w=28, fixed_h=28)
        row.addWidget(self.mark)
        self.title = QLabel()
        self.title.setObjectName('candyTitle')
        bind_text(self.title, title)
        bind_text(dialog, title, property='windowTitle')     # the taskbar and Alt+Tab still name it
        row.addWidget(self.title, 1)
        self.buttons = WindowButtons(dialog)
        for button in (self.buttons.maximize_button, self.buttons.close_button):
            set_size(button, fixed_w=30, fixed_h=30)
        self.buttons.layout().setSpacing(6)
        if not maximizable:
            self.buttons.maximize_button.hide()
        row.addWidget(self.buttons)
        column.addWidget(self.title_bar)

        self.body = QWidget()
        self.body.setObjectName('candyBody')
        self.layout = QVBoxLayout(self.body)
        column.addWidget(self.body, 1)
        self.window = RoundedWindow(dialog, self.root, title_areas=[self.title_bar], buttons=self.buttons,
                                    radius=RADIUS, maximizable=maximizable)

    @staticmethod
    def outer_size(width: int, height: int) -> tuple[int, int]:
        """The window size that leaves ``width`` x ``height`` for the frame's content (the shadow is extra)."""
        return width + 2 * SHADOW, height + 2 * SHADOW


__all__ = ['CandyChrome', 'RADIUS']
