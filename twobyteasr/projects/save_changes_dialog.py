"""「保存工程修改」 as three candies.

2026-11-15 first build (the user's pick B from the drafts): 兔白 on top, one question, three big
rounded tiles that cannot be mistaken for each other — 保存 (accent, 「推荐」, Enter), 不保存 (soft red),
取消 (plain, Esc), each saying in a few words what it does.

2026-11-15 evening (user: too much empty space, and the 「推荐」 tag was not a sticker like the rest):
the draft 「A 缩紧三糖」. 兔白 sits on a round tinted disc left of the question instead of on a row
of her own, each tile puts its icon and name on one line with the note below, and 「推荐」 is a
sticker in the editor card's 「编辑」 style — accent, white edge, tilted, over the tile's corner.
The window is about half as tall.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..app.candy_prompt import CandyPrompt
from ..i18n import tr


class _Sticker(QWidget):
    """A tilted label with a white edge and a small shadow, like the editor card's 「编辑」 tag."""

    TILT = -6.

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('candySticker')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = text
        self._font = QFont(self.font())
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.Black)
        metrics = QFontMetricsF(self._font)
        self._face = QRectF(0, 0, metrics.horizontalAdvance(text) + 20, metrics.height() + 9)
        # Room for the tilt and the shadow around the face.
        self.setFixedSize(int(self._face.width() + 12), int(self._face.height() + 14))

    def text(self) -> str:
        return self._text

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from ..design.theme_manager import theme_definition, theme_key
        t = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2 - 1)
        painter.rotate(self.TILT)
        face = self._face.translated(-self._face.width() / 2, -self._face.height() / 2)
        shadow = QPainterPath(); shadow.addRoundedRect(face.translated(0, 3), 9, 9)
        painter.fillPath(shadow, QColor(0, 0, 0, 70))
        path = QPainterPath(); path.addRoundedRect(face, 9, 9)
        painter.fillPath(path, QColor(t.accent))
        painter.setPen(QPen(QColor('#FFFFFF'), 2)); painter.drawPath(path)
        painter.setFont(self._font); painter.setPen(QColor('#FFFFFF'))
        painter.drawText(face, Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


class _BunnyDisc(QWidget):
    """兔白 on a soft round disc, so her purple hair stands out on a dark window."""

    def __init__(self, mascot: QWidget, size: int):
        super().__init__()
        self.setObjectName('candyBunnyDisc')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Taller than the disc when needed, so the keyring on her head is never cut.
        self.setFixedSize(size, max(size, mascot.height() + 6))
        mascot.setParent(self)
        mascot.move((size - mascot.width()) // 2, self.height() - mascot.height())
        self.mascot = mascot

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from ..design.theme_manager import theme_definition, theme_key
        from ..design.ui_theme import blend_hex
        t = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = self.width() * .86
        centre = QPointF(self.width() / 2, self.height() - diameter / 2 - 1)
        painter.setPen(QPen(QColor(blend_hex(t.surface, t.accent, .45)), 3))
        painter.setBrush(QColor(blend_hex(t.surface, t.accent, .28 if not t.is_light else .18)))
        painter.drawEllipse(centre, diameter / 2, diameter / 2)
        painter.end()


class _Tile(QPushButton):
    """A candy: icon and name on one line, a short note below; an optional sticker over its corner."""

    def __init__(self, tone: str, icon_label: QLabel, title: str, note: str, badge: str = ''):
        super().__init__()
        self.setObjectName('candyTile')
        self.setProperty('tone', tone)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f'{title}：{note}')
        from ..app.ui_zoom import px
        self.setMinimumHeight(px(64))
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 10, 8, 10)
        column.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(7)
        top.addStretch(1)
        top.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.title = CandyPrompt.label(title, 'candyTileTitle')
        top.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        column.addLayout(top)
        self.note = CandyPrompt.label(note, 'candyTileNote', wrap=True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.note)
        # The sticker hangs over the tile's edge, so it lives on the window, not inside the tile.
        self.badge = _Sticker(badge) if badge else None

    def place_badge(self):
        if self.badge is None or self.parentWidget() is None:
            return
        host = self.window()
        if self.badge.parentWidget() is not host:
            self.badge.setParent(host)
            self.badge.show()
        corner = self.mapTo(host, self.rect().topLeft())
        self.badge.move(corner.x() - 10, corner.y() - 13)
        self.badge.raise_()

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.place_badge()

    def moveEvent(self, event):  # noqa: N802 - Qt override
        super().moveEvent(event)
        self.place_badge()


class SaveChangesDialog(CandyPrompt):
    WIDTH = 500

    def __init__(self, parent, action: str, project_name: str = ''):
        super().__init__(parent, object_name='saveChangesDialog', title=str(tr('保存工程修改')), icon='fa5s.save')
        from ..design.theme_manager import theme_definition, theme_key
        t = theme_definition(theme_key())
        self.choice = 'cancel'
        self.body.setContentsMargins(18, 0, 18, 16)
        head = QHBoxLayout()
        head.setSpacing(12)
        mascot = self.bunny(66)
        self.bunny_disc = None
        if mascot is not None:
            from ..app.ui_zoom import px
            self.bunny_disc = _BunnyDisc(mascot, max(px(76), mascot.width()))
            head.addWidget(self.bunny_disc, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(3)
        heading = self.label(str(tr('{action}前，要把修改存起来吗？', action=tr(action))), 'candyHeading', wrap=True)
        words.addWidget(heading)
        sub = self.label(str(tr('{name} · 有没保存的修改', name=project_name) if project_name
                             else tr('这个工程有没保存的修改')), 'candyMuted', wrap=True)
        words.addWidget(sub)
        head.addLayout(words, 1)
        self.body.addLayout(head)
        self.body.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.save_button = _Tile('save', self.icon_label('fa5s.save', t.text_on_accent, 18), str(tr('保存')),
                                 str(tr('留下这次的修改')), str(tr('推荐')))
        self.discard_button = _Tile('drop', self.icon_label('fa5s.trash-alt', t.danger, 18), str(tr('不保存')),
                                    str(tr('这次的修改不要了')))
        self.cancel_button = _Tile('back', self.icon_label('fa5s.undo-alt', t.text_secondary, 18), str(tr('取消')),
                                   str(tr('回去继续编辑')))
        for button, value in ((self.save_button, 'save'), (self.discard_button, 'discard'), (self.cancel_button, 'cancel')):
            button.setObjectName('candyTile')
            button.clicked.connect(lambda _=False, v=value: self._choose(v))
            row.addWidget(button, 1)
        self.body.addLayout(row)
        self.save_button.setDefault(True)
        self.save_button.setFocus()
        self._text, self._informative = heading.text(), sub.text()
        self.finish_layout()

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        self.save_button.place_badge()

    # The old message box's surface, so callers and audits can still answer it by standard button.
    def _standard(self):
        from PySide6.QtWidgets import QMessageBox
        button = QMessageBox.StandardButton
        return {button.Save: self.save_button, button.Discard: self.discard_button, button.Cancel: self.cancel_button}

    def button(self, which):
        return self._standard().get(which)

    def standardButtons(self):  # noqa: N802 - kept from QMessageBox
        from PySide6.QtWidgets import QMessageBox
        button = QMessageBox.StandardButton
        return button.Save | button.Discard | button.Cancel

    def buttons(self):
        return [self.save_button, self.discard_button, self.cancel_button]

    def text(self) -> str:
        return self._text

    def informativeText(self) -> str:  # noqa: N802 - kept from QMessageBox
        return self._informative

    def _choose(self, value: str):
        self.choice = value
        if value == 'cancel':
            self.reject()
        else:
            self.accept()

    def reject(self):                 # Esc, the round ✕, or 取消
        self.choice = 'cancel'
        super().reject()


def ask_save_changes(parent, action: str, project_name: str = '') -> str:
    """'save' / 'discard' / 'cancel'."""
    dialog = SaveChangesDialog(parent, action, project_name)
    try:
        dialog.exec()
        return dialog.choice
    finally:
        dialog.deleteLater()


__all__ = ['SaveChangesDialog', 'ask_save_changes']
