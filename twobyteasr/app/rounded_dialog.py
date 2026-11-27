"""A small dialog in the product's rounded shell instead of the Windows frame (2026-11-26).

User (2026-11-26): 「自动开关」 and 「随手贴快添词条」 must not use the Windows window; their
words must not be in the default font either. ``RoundedDialogShell`` puts a dialog's content in a
rounded, shadowed window (``rounded_window.RoundedWindow``) with its own header: the title in
猫啃什锦黑 (the playful accent), an optional chip in 思源黑体 Heavy, and a round ×. The header
moves the window; Esc and × close it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

RADIUS = 22


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


class RoundedDialogShell:
    """Wrap ``content`` in ``dialog`` (a fresh QDialog without a layout) as a rounded window."""

    def __init__(self, dialog: QDialog, content: QWidget, *, title: str, chip: str = '',
                 size: tuple[int, int] = (480, 360), margins=(22, 14, 16, 18)):
        from .rounded_window import SHADOW, RoundedWindow
        self.dialog = dialog
        dialog.setWindowTitle(f'{title} · {chip}' if chip else title)
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName('roundedDialogRoot')
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.root)
        body = QVBoxLayout(self.root)
        body.setContentsMargins(*margins)
        body.setSpacing(6)
        self.header = QFrame()
        self.header.setObjectName('roundedDialogHeader')
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.title_label = QLabel(title)
        self.title_label.setObjectName('roundedDialogTitle')
        top.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.chip = QLabel(chip)
        self.chip.setObjectName('roundedDialogChip')
        self.chip.setVisible(bool(chip))
        top.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        self.close_button = QPushButton('×')
        self.close_button.setObjectName('roundedDialogClose')
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(32, 32)
        self.close_button.setAutoDefault(False)
        try:
            from ..i18n import bind_text
            bind_text(self.close_button, '关闭', property='toolTip')
            bind_text(self.close_button, '关闭', property='accessibleName')
        except Exception:  # noqa: BLE001 - a missing translation never blocks the dialog
            self.close_button.setToolTip('关闭')
        self.close_button.clicked.connect(dialog.reject)
        top.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addWidget(self.header)
        body.addWidget(content, 1)
        self.refresh_theme()
        dialog.setMinimumSize(320 + 2 * SHADOW, 220 + 2 * SHADOW)
        dialog.resize(size[0] + 2 * SHADOW, size[1] + 2 * SHADOW)
        self.chrome = RoundedWindow(dialog, self.root, title_areas=[self.header], radius=RADIUS, maximizable=False)

    def refresh_theme(self) -> None:
        from ..design.typography import PLAYFUL_FONT_STACK, TITLE_FONT_STACK, UI_FONT_STACK
        from ..design.ui_theme import blend_hex
        t = _theme()
        chip_bg = blend_hex(t.surface, t.accent, 0.12 if t.is_light else 0.22)
        close_hover = blend_hex(t.surface, t.text, 0.08 if t.is_light else 0.14)
        self.root.setStyleSheet(f"""
            QWidget#roundedDialogRoot {{ background: {t.surface}; }}
            QFrame#roundedDialogHeader {{ background: transparent; border: 0; }}
            QLabel#roundedDialogTitle {{ background: transparent; color: {t.text}; font-family: {PLAYFUL_FONT_STACK};
                font-size: 22px; padding: 0; }}
            QLabel#roundedDialogChip {{ background: {chip_bg}; color: {t.accent_text}; border-radius: 11px;
                padding: 2px 10px; font-family: {TITLE_FONT_STACK}; font-size: 13px; font-weight: 800; }}
            QPushButton#roundedDialogClose {{ background: transparent; color: {t.text_muted}; border: 0;
                border-radius: 16px; font-family: {UI_FONT_STACK}; font-size: 20px; padding: 0 0 2px 0; }}
            QPushButton#roundedDialogClose:hover {{ background: {close_hover}; color: {t.text}; }}
        """)


__all__ = ['RoundedDialogShell']
