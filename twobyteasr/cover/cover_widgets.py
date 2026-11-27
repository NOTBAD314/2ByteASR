"""Rounded controls shared by the cover template picker and the cover editor (2026-11-27).

User (2026-11-27): the cover windows used the Windows frame and plain, undesigned buttons. From
three drafts each they picked picker B 「大圖預覽」 and editor A 「圓角工具箱」
(``tmp/cover-ui-drafts-20261127``). These are the small parts both windows share: a segmented
switch, a row of round colour dots, a labelled slider, a pill switch, the zoom pill and the
「在首頁看起來」 preview of how the cover looks in a phone's video feed.

Styling lives in ``design/cover_qss.py``; widgets here only set object names.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget)

from ..i18n import bind_text


def icon_button(icon: str, tip: str, *, role: str = 'secondary', size: int = 32, icon_size: int = 16,
                checkable: bool = False, name: str = 'coverIconButton') -> QToolButton:
    from ..design.themed_icons import install_themed_icon
    button = QToolButton()
    button.setObjectName(name)
    install_themed_icon(button, icon, role)
    button.setIconSize(QSize(icon_size, icon_size))
    button.setFixedSize(size, size)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoRaise(True)
    bind_text(button, tip, property='toolTip')
    bind_text(button, tip, property='accessibleName')
    return button


def text_button(text: str, *, icon: str = '', kind: str = 'normal', role: str = '') -> QPushButton:
    """A rounded push button; ``kind`` is normal / primary / soft / ghost (see cover_qss)."""
    from ..design.themed_icons import install_themed_icon
    button = QPushButton()
    button.setObjectName({'primary': 'coverPrimary', 'soft': 'coverSoft', 'ghost': 'coverGhost'}.get(kind, 'coverButton'))
    bind_text(button, text)
    if icon:
        install_themed_icon(button, icon, role or {'primary': 'on_accent', 'soft': 'accent'}.get(kind, 'secondary'))
        button.setIconSize(QSize(14, 14))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoDefault(False)
    return button


class Segmented(QFrame):
    """A row of exclusive choices in one rounded track; ``changed`` sends the item's data."""
    changed = Signal(object)

    def __init__(self, items, parent=None, *, icon_only: bool = False):
        super().__init__(parent)
        self.setObjectName('coverSegmented')
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for item in items:
            label, data = item[0], item[1]
            icon = item[2] if len(item) > 2 else ''
            button = QPushButton()
            button.setObjectName('coverSegment')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            button.setProperty('segment_data', data)
            if icon:
                from ..design.themed_icons import install_themed_icon
                install_themed_icon(button, icon, 'secondary')
                button.setIconSize(QSize(14, 14))
            if icon_only:
                bind_text(button, label, property='toolTip')
                button.setFixedWidth(34)
            else:
                bind_text(button, label)
            self.group.addButton(button)
            self.buttons.append(button)
            row.addWidget(button)
        self.group.buttonClicked.connect(lambda button: self.changed.emit(button.property('segment_data')))

    def value(self):
        button = self.group.checkedButton()
        return button.property('segment_data') if button else None

    def set_value(self, data) -> None:
        for button in self.buttons:
            if button.property('segment_data') == data:
                button.setChecked(True)
                return
        self.group.setExclusive(False)
        for button in self.buttons:
            button.setChecked(False)
        self.group.setExclusive(True)


class Swatch(QAbstractButton):
    """One round colour dot; the current colour gets an accent ring."""

    def __init__(self, color: str, parent=None, *, custom: bool = False):
        super().__init__(parent)
        self.color = color
        self.custom = custom
        self.current = False
        self.ring = QColor('#b34470')
        self.edge = QColor('#574c60')
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '自选颜色' if custom else color, property='toolTip')

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, 16, 16)
        if self.custom:
            from PySide6.QtGui import QConicalGradient
            gradient = QConicalGradient(rect.center(), 0)
            for stop, value in ((0, '#ff6b6b'), (.2, '#ffd84a'), (.4, '#6ee07a'), (.6, '#5cc8ff'), (.8, '#a77bff'), (1, '#ff6b6b')):
                gradient.setColorAt(stop, QColor(value))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(self.color))
        painter.setPen(QPen(self.edge, 1))
        painter.drawEllipse(rect)
        if self.current or self.underMouse():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.ring if self.current else self.edge, 2))
            painter.drawEllipse(QRectF(1, 1, 22, 22))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class SwatchRow(QWidget):
    """Common cover colours plus a rainbow dot that opens the app's own colour picker."""
    picked = Signal(str)
    COLORS = ('#ffffff', '#ffd84a', '#ff6b5a', '#f49ac1', '#7fd1a4', '#86b4f7', '#1d1d1d')

    def __init__(self, parent=None, *, colors=COLORS, title: str = '选择颜色'):
        super().__init__(parent)
        self.title = title
        self.value = '#ffffff'
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.swatches = []
        for color in colors:
            swatch = Swatch(color)
            swatch.clicked.connect(lambda _checked=False, value=color: self.picked.emit(value))
            self.swatches.append(swatch)
            row.addWidget(swatch)
        self.custom = Swatch('', custom=True)
        self.custom.clicked.connect(self._choose)
        row.addWidget(self.custom)
        row.addStretch(1)

    def set_theme(self, ring: str, edge: str) -> None:
        for swatch in self.swatches + [self.custom]:
            swatch.ring, swatch.edge = QColor(ring), QColor(edge)
            swatch.update()

    def set_current(self, value: str) -> None:
        self.value = value or '#ffffff'
        wanted = QColor(self.value).name().lower()
        for swatch in self.swatches:
            swatch.current = QColor(swatch.color).name().lower() == wanted
            swatch.update()
        self.custom.current = not any(swatch.current for swatch in self.swatches)
        self.custom.update()

    def _choose(self):
        from ..design.color_picker import SimpleColorDialog
        from ..design.studio_theme import apply_secondary_surface_theme
        from ..i18n import tr
        from PySide6.QtWidgets import QDialog
        dialog = SimpleColorDialog(QColor(self.value), self.window(), title=tr(self.title), common_colors=self.COLORS)
        apply_secondary_surface_theme(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_color().isValid():
            color = dialog.selected_color()
            self.picked.emit(color.name(QColor.NameFormat.HexArgb) if color.alpha() < 255 else color.name())


class SliderRow(QWidget):
    """A slider with its value written beside it. ``moved`` fires live while dragging (one undo
    step through a merge key), ``committed`` when the drag ends or a key changes the value."""
    moved = Signal(float)
    committed = Signal(float)

    def __init__(self, low: float, high: float, *, suffix: str = ' px', zero_text: str = '', step: float = 1, parent=None):
        super().__init__(parent)
        self.step = step
        self.suffix = suffix
        self.zero_text = zero_text
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName('coverSlider')
        self.slider.setRange(int(low / step), int(high / step))
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.slider, 1)
        self.label = QLabel()
        self.label.setObjectName('coverSliderValue')
        self.label.setMinimumWidth(46)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label)
        self._setting = False
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(lambda: self.committed.emit(self.value()))

    def value(self) -> float:
        return self.slider.value() * self.step

    def set_value(self, value: float) -> None:
        self._setting = True
        self.slider.setValue(round(float(value) / self.step))
        self._setting = False
        self._write()

    def setValue(self, value: float) -> None:  # noqa: N802 - the spin-box name the editor's refresh uses
        self.set_value(value)

    def _write(self):
        value = self.value()
        text = self.zero_text if (self.zero_text and not value) else f'{value:g}{self.suffix}'
        self.label.setText(text)

    def _changed(self, _value):
        self._write()
        if self._setting:
            return
        if self.slider.isSliderDown():
            self.moved.emit(self.value())
        else:
            self.committed.emit(self.value())


class PillSwitch(QAbstractButton):
    """An on/off pill drawn in the theme's accent; ``toggled`` like a check box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.on_color = QColor('#b34470')
        self.off_color = QColor('#574c60')

    def set_theme(self, on: str, off: str) -> None:
        self.on_color, self.off_color = QColor(on), QColor(off)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = self.on_color if self.isChecked() else self.off_color
        if not self.isEnabled():
            track.setAlphaF(.45)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(1, 2, 38, 20), 10, 10)
        painter.setBrush(QColor('#ffffff'))
        x = 21 if self.isChecked() else 5
        painter.drawEllipse(QRectF(x, 5, 14, 14))


class ZoomPill(QFrame):
    """「−  45%  +  │ 適應  100% │ 吸附  時長角」 floating over the canvas."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setObjectName('coverZoomPill')
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(2)
        minus = icon_button('fa5s.minus', '缩小', size=28, icon_size=11)
        minus.clicked.connect(lambda: self._step(1 / 1.25))
        row.addWidget(minus)
        self.value = QLabel()
        self.value.setObjectName('coverZoomValue')
        self.value.setMinimumWidth(46)
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.value)
        plus = icon_button('fa5s.plus', '放大', size=28, icon_size=11)
        plus.clicked.connect(lambda: self._step(1.25))
        row.addWidget(plus)
        row.addWidget(self._separator())
        self.fit_button = icon_button('fa5s.expand', '适应窗口', size=28, icon_size=12)
        self.fit_button.clicked.connect(view.fit_canvas)
        row.addWidget(self.fit_button)
        self.actual_button = QPushButton('100%')
        self.actual_button.setObjectName('coverPillText')
        self.actual_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actual_button.clicked.connect(lambda: view.set_zoom(1))
        row.addWidget(self.actual_button)
        self.tail = QHBoxLayout()
        self.tail.setContentsMargins(0, 0, 0, 0)
        self.tail.setSpacing(2)
        self.tail_separator = self._separator()
        row.addWidget(self.tail_separator)
        row.addLayout(self.tail)
        self.corner_button = icon_button('fa5s.clock', '标出影片时长会盖住的角落', size=28, icon_size=12, checkable=True)
        self.corner_button.toggled.connect(self._corner)
        self.tail.addWidget(self.corner_button)
        view.zoom_changed.connect(self._zoom)
        self._zoom(view.transform().m11())

    def _separator(self):
        line = QFrame()
        line.setObjectName('coverPillSeparator')
        line.setFixedSize(1, 18)
        return line

    def _step(self, factor):
        self.view.set_zoom(self.view.transform().m11() * factor)

    def _zoom(self, value):
        self.value.setText(f'{value * 100:.0f}%')

    def _corner(self, on):
        self.view.duration_corner = bool(on)
        self.view.viewport().update()


class FeedPreview(QFrame):
    """「在首頁看起來」: the cover at the size a phone's video feed shows it, with a duration badge
    and two grey title lines. Re-rendered at most every 350 ms while the document changes."""

    WIDTH = 156

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setObjectName('coverFeedCard')
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(5)
        caption = QHBoxLayout()
        caption.setSpacing(5)
        from ..design.themed_icons import install_themed_icon
        phone = QToolButton()
        phone.setObjectName('coverFeedIcon')
        install_themed_icon(phone, 'fa5s.mobile-alt', 'muted')
        phone.setIconSize(QSize(11, 11))
        phone.setFixedSize(14, 14)
        phone.setEnabled(False)
        caption.addWidget(phone)
        self.caption = QLabel()
        self.caption.setObjectName('coverFeedCaption')
        bind_text(self.caption, '在首页看起来')
        caption.addWidget(self.caption, 1)
        column.addLayout(caption)
        self.picture = QLabel()
        self.picture.setObjectName('coverFeedPicture')
        self.picture.setFixedSize(self.WIDTH, round(self.WIDTH * 9 / 16))
        column.addWidget(self.picture)
        self.lines = QWidget()
        self.lines.setFixedHeight(22)
        column.addWidget(self.lines)
        self.line_color = QColor('#3a3240')
        self.lines.paintEvent = self._paint_lines
        bind_text(self, '手机首页的封面大约只有这么大：标题要一眼读得出来，右下角会被时长盖住。', property='toolTip')
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.render_now)
        session.changed.connect(self._timer.start)
        self.render_now()

    def set_line_color(self, value: str) -> None:
        self.line_color = QColor(value)
        self.lines.update()

    def _paint_lines(self, _event):
        painter = QPainter(self.lines)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.line_color)
        painter.drawEllipse(QRectF(0, 1, 18, 18))
        painter.drawRoundedRect(QRectF(26, 3, self.WIDTH - 34, 6), 3, 3)
        painter.drawRoundedRect(QRectF(26, 14, (self.WIDTH - 34) * .6, 6), 3, 3)

    def render_now(self):
        from .cover_render import CoverRenderer
        width, height = self.picture.width(), self.picture.height()
        ratio = self.devicePixelRatioF() or 1
        canvas = QPixmap(round(width * ratio), round(height * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, width, height), 7, 7)
        painter.setClipPath(clip)
        painter.fillRect(QRectF(0, 0, width, height), QColor('#1d1920'))
        try:
            image = CoverRenderer().render(self.session.document.snapshot())
        except Exception:  # noqa: BLE001 - a preview never blocks editing
            image = QImage()
        if not image.isNull():
            scaled = image.scaled(round(width * ratio), round(height * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            w, h = scaled.width() / ratio, scaled.height() / ratio
            painter.drawImage(QRectF((width - w) / 2, (height - h) / 2, w, h), scaled)
        badge = QRectF(width - 34, height - 17, 30, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 210))
        painter.drawRoundedRect(badge, 3, 3)
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QColor('#ffffff'))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, '12:34')
        painter.end()
        self.picture.setPixmap(canvas)


def section_label(text: str, name: str = 'coverSectionTitle') -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    bind_text(label, text)
    return label


def form_row(label: str, widget: QWidget, *, label_width: int = 46) -> QWidget:
    """「標籤  控件」 on one line, the label muted and fixed-width like the drafts."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    title = QLabel()
    title.setObjectName('coverRowLabel')
    bind_text(title, label)
    title.setFixedWidth(label_width)
    row.addWidget(title)
    row.addWidget(widget, 1)
    host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return host


__all__ = ['FeedPreview', 'PillSwitch', 'Segmented', 'SliderRow', 'Swatch', 'SwatchRow', 'ZoomPill',
           'form_row', 'icon_button', 'section_label', 'text_button']
