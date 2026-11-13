# SPDX-License-Identifier: GPL-3.0-only
"""Pieces of the question-style Application Settings window (2026-11-12, design C).

The values still live in the combo boxes and check boxes that saving,
audits and older callers read (``dialog.interval.currentData()``...); the
chips and cards here only show and change them. A combo box shown as chips
or cards is kept hidden inside the widget that shows it, so the dialog's
"what changed?" comparison still sees it.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QWidget)

from ..i18n import bind_text
from ..design.typography import weighted_font


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _px(value: float) -> int:
    from .ui_zoom import px
    return px(value)


def _blend(base: str, color: str, amount: float) -> str:
    from ..design.ui_theme import blend_hex
    return blend_hex(base, color, amount)


# Sidebar tiles: icon and colour per category (the first follows the theme accent).
SECTION_ICONS = {
    '工程与保存': ('fa5s.folder-open', None),
    'Studio 与维护': ('fa5s.film', '#7a58a0'),
    '存储与缓存': ('fa5s.database', '#3f7686'),
    '外观': ('fa5s.palette', '#a06f12'),
    '高级设置': ('fa5s.sliders-h', '#3f7a44'),
    '快捷键': ('fa5s.keyboard', '#9a5444'),
    '外部 AI（MCP）': ('fa5s.plug', '#5560a8'),
    '关于': ('fa5s.info-circle', '#7a6c5e'),
}


def section_icon(label: str, theme=None) -> QIcon:
    """A rounded colour tile with a white-ish glyph; solid when the row is selected."""
    from ..design.themed_icons import cached_icon_pixmap
    t = theme or _theme()
    name, hue = SECTION_ICONS.get(label, ('fa5s.circle', None))
    hue = hue or t.accent
    side = 32
    icon = QIcon()
    for mode, solid in ((QIcon.Mode.Normal, False), (QIcon.Mode.Selected, True), (QIcon.Mode.Active, False)):
        for ratio in (1.0, 1.5, 2.0):
            size = round(side * ratio)
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            if solid:
                fill, glyph = hue, '#ffffff'
            elif t.is_light:
                fill, glyph = _blend(t.surface, hue, 0.2), hue
            else:
                fill, glyph = _blend(t.surface, hue, 0.35), _blend(hue, '#ffffff', 0.55)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.34, size * 0.34)
            mark = cached_icon_pixmap(name, glyph, QSize(round(size * 0.5), round(size * 0.5)))
            mark.setDevicePixelRatio(1.0)
            painter.drawPixmap(QRectF(size * 0.25, size * 0.25, size * 0.5, size * 0.5), mark,
                               QRectF(mark.rect()))
            painter.end()
            pixmap.setDevicePixelRatio(ratio)
            icon.addPixmap(pixmap, mode)
    return icon


class PillSwitch(QCheckBox):
    """A check box painted as a rounded on/off switch (same API, same signals)."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(_px(46), _px(26))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        t = _theme()
        on = self.isChecked()
        enabled = self.isEnabled()
        w, h = _px(46), _px(26)
        rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        if on:
            track = t.accent if enabled else _blend(t.surface, t.accent, 0.35)
        else:
            track = _blend(t.surface, t.text, 0.22 if t.is_light else 0.3)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.hasFocus():
            painter.setPen(QPen(QColor(t.focus), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), h / 2 + 2, h / 2 + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        knob = h - _px(6)
        x = rect.right() - _px(3) - knob if on else rect.left() + _px(3)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(x, rect.top() + _px(3) + 1, knob, knob))
        painter.setBrush(QColor('#ffffff' if enabled else _blend(t.surface, '#ffffff', 0.6)))
        painter.drawEllipse(QRectF(x, rect.top() + _px(3), knob, knob))
        painter.end()


class _ComboMirror(QWidget):
    """Shows a combo box's items as buttons; the hidden combo keeps the value."""

    def __init__(self, combo: QComboBox, parent=None):
        super().__init__(parent)
        self.combo = combo
        combo.setParent(self)
        combo.hide()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QAbstractButton] = []
        combo.installEventFilter(self)
        combo.currentIndexChanged.connect(self._sync)

    def _add(self, button: QAbstractButton, index: int):
        button.setCheckable(True)
        if isinstance(button, QPushButton):
            button.setAutoDefault(False)
        self.group.addButton(button, index)
        self.buttons.append(button)
        button.clicked.connect(lambda _checked=False, i=index: self.combo.setCurrentIndex(i))

    def _sync(self, *_args):
        index = self.combo.currentIndex()
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)

    def eventFilter(self, watched, event):
        if watched is self.combo and event.type() == QEvent.Type.EnabledChange:
            for button in self.buttons:
                button.setEnabled(self.combo.isEnabled())
        return False


class ChoiceChips(_ComboMirror):
    """``每隔 [30 秒] [1 分钟] … 存一次``: one pill per combo item."""

    def __init__(self, combo: QComboBox, *, prefix: str = '', suffix: str = '', parent=None):
        super().__init__(combo, parent)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        if prefix:
            caption = bind_text(QLabel(), prefix)
            caption.setObjectName('settingsChipCaption')
            line.addWidget(caption)
        for index in range(combo.count()):
            chip = QPushButton(combo.itemText(index))
            chip.setObjectName('settingsChip')
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            self._add(chip, index)
            line.addWidget(chip)
        if suffix:
            caption = bind_text(QLabel(), suffix)
            caption.setObjectName('settingsChipCaption')
            line.addWidget(caption)
        line.addStretch(1)
        self._sync()


class _ChoiceCard(QAbstractButton):
    """A card with a small picture, a title, a note and a radio mark."""

    def __init__(self, title: str, note: str, picture: str, parent=None):
        super().__init__(parent)
        self.title, self.note, self.picture = title, note, picture
        self.setText(title)
        self.setAccessibleName(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        return QSize(_px(240), _px(74))

    def minimumSizeHint(self):
        return QSize(_px(200), _px(74))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            self.update()
        super().changeEvent(event)

    def paintEvent(self, event):
        from ..i18n import tr
        t = _theme()
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        border = t.accent if on else (t.focus if self.hasFocus() else t.border)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(border), 2))
        fill = _blend(t.surface_elevated, t.accent, 0.08 if t.is_light else 0.16) if on else t.surface_elevated
        if self.underMouse() and not on:
            fill = _blend(t.surface_elevated, t.text, 0.03)
        painter.setBrush(QColor(fill))
        radius = _px(18)
        painter.drawRoundedRect(rect, radius, radius)
        # Picture
        pad = _px(12)
        pic = QRectF(rect.left() + pad, rect.center().y() - _px(23), _px(64), _px(46))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.surface if on else t.input_surface))
        painter.drawRoundedRect(pic, _px(10), _px(10))
        inner = pic.adjusted(_px(7), _px(7), -_px(7), -_px(7))
        soft = _blend(t.surface, t.text, 0.18)
        if self.picture == 'lines':
            painter.setBrush(QColor(_blend(t.surface, t.accent, 0.45)))
            painter.drawRoundedRect(QRectF(inner.left(), inner.top(), inner.width() * 0.7, _px(8)), _px(4), _px(4))
            painter.setBrush(QColor(soft))
            for row, share in ((1, 1.0), (2, 0.85)):
                y = inner.top() + _px(8) + row * _px(7) - _px(3)
                painter.drawRoundedRect(QRectF(inner.left(), y, inner.width() * share, _px(5)), _px(2.5), _px(2.5))
        else:
            painter.setBrush(QColor(soft))
            gap = _px(4)
            cell_w = (inner.width() - 2 * gap) / 3
            cell_h = (inner.height() - gap) / 2
            for r in range(2):
                for c in range(3):
                    painter.drawRoundedRect(QRectF(inner.left() + c * (cell_w + gap), inner.top() + r * (cell_h + gap),
                                                   cell_w, cell_h), _px(3), _px(3))
        # Radio mark
        dot = _px(18)
        mark = QRectF(rect.right() - pad - dot, rect.center().y() - dot / 2, dot, dot)
        painter.setPen(QPen(QColor(t.accent if on else t.border_strong), 2))
        painter.setBrush(QColor(t.surface_elevated))
        painter.drawEllipse(mark)
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
            painter.drawEllipse(mark.adjusted(_px(4), _px(4), -_px(4), -_px(4)))
        # Words
        left = pic.right() + _px(12)
        words = QRectF(left, rect.top(), mark.left() - left - _px(8), rect.height())
        title_font = self.font()
        title_font.setPixelSize(_px(14))
        weighted_font(title_font, 700)
        note_font = self.font()
        note_font.setPixelSize(_px(12))
        painter.setPen(QColor(t.text))
        painter.setFont(title_font)
        title_box = QRectF(words.left(), words.center().y() - _px(19), words.width(), _px(20))
        painter.drawText(title_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(str(tr(self.title)), Qt.TextElideMode.ElideRight,
                                                          int(title_box.width())))
        painter.setPen(QColor(t.text_muted))
        painter.setFont(note_font)
        note_box = QRectF(words.left(), words.center().y() + _px(2), words.width(), _px(18))
        painter.drawText(note_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(str(tr(self.note)), Qt.TextElideMode.ElideRight,
                                                          int(note_box.width())))
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class ChoiceCards(_ComboMirror):
    """Two or three picture cards side by side; ``options`` = [(note, picture)] per combo item."""

    def __init__(self, combo: QComboBox, options, parent=None):
        super().__init__(combo, parent)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        for index in range(combo.count()):
            note, picture = options[index]
            card = _ChoiceCard(combo.itemText(index), note, picture)
            self._add(card, index)
            line.addWidget(card, 1)
        self._sync()


class Bunny(QLabel):
    """The bunny's round face, sized for the interface zoom."""

    def __init__(self, size: int = 44, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(_px(size), _px(size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._refresh()

    def _refresh(self):
        from ..design.bunny_mascot import bunny_face_pixmap
        self.setPixmap(bunny_face_pixmap(_px(self._size), self.devicePixelRatioF() or 1.0))

    def apply_ui_zoom(self, _factor):
        self.setFixedSize(_px(self._size), _px(self._size))
        self._refresh()


def question(text: str) -> QLabel:
    label = bind_text(QLabel(), text)
    label.setObjectName('settingsQuestion')
    label.setWordWrap(True)
    return label


__all__ = ['Bunny', 'ChoiceCards', 'ChoiceChips', 'PillSwitch', 'SECTION_ICONS', 'question', 'section_icon']
