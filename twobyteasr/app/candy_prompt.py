"""A small question window in the candy style (2026-11-15).

User (2026-11-15): the 「保存工程修改」 and 「发现未保存的自动恢复版本」 questions were plain Windows
message boxes; redraw them cute and rounded, with buttons that stand apart. From the drafts they
picked 「三颗糖」 for saving and 「两张卡片」 for recovery. Both share this base: the candy windows'
own round frame (``CandyChrome``, no maximize), 兔白 when her pictures are there, modal, Esc
cancels, and a style sheet of its own so it looks the same wherever it opens.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QLabel, QWidget

from .candy_chrome import CandyChrome


class CandyPrompt(QDialog):
    WIDTH = 520

    def __init__(self, parent, *, object_name: str, title: str, icon: str):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setModal(True)
        self.chrome = CandyChrome(self, title, icon, maximizable=False)
        self.body = self.chrome.layout
        self.body.setContentsMargins(24, 2, 24, 20)
        self.body.setSpacing(8)
        self.restyle()

    def restyle(self):
        from ..design.candy_prompt_qss import build_candy_prompt_qss
        from ..design.theme_manager import theme_definition, theme_key
        self.setStyleSheet(build_candy_prompt_qss('QDialog#' + self.objectName(), theme_definition(theme_key())))

    def finish_layout(self):
        """Fix the width (plus the frame's shadow) and let the height follow the content."""
        from .ui_zoom import px
        self.chrome.root.setFixedWidth(px(self.WIDTH))
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def bunny(self, height: int, mood: str = '') -> QWidget | None:
        """兔白 (swinging gently), or None when her pictures are missing."""
        from . import ui_zoom
        try:
            from ..design.bunny_mascot import BunnyMascot
            mascot = BunnyMascot(self, height=ui_zoom.px(height), motion='swing')
        except Exception:  # noqa: BLE001 - no pictures: no bunny
            return None
        if not mascot.available:
            mascot.deleteLater()
            return None
        mascot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if mood:
            mascot.set_mood(mood)
        return mascot

    @staticmethod
    def label(text: str, name: str, *, wrap: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(wrap)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return label

    def icon_label(self, icon: str, color: str, size: int, name: str = 'candyIcon') -> QLabel:
        from ..design.themed_icons import cached_icon_pixmap
        label = QLabel()
        label.setObjectName(name)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ratio = self.devicePixelRatioF() or 1.0
        pixmap = cached_icon_pixmap(icon, color, QSize(size, size), device_pixel_ratio=ratio)
        label.setPixmap(pixmap)
        label.setFixedSize(size, size)
        return label

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


__all__ = ['CandyPrompt']
