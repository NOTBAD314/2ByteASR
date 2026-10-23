"""Widgets of the model download window (2026-10-21): step track, activity graph, styles.

Painted from the active theme tokens so every theme (light and dark) gets the
same reading: green = done or moving, accent = current step, amber = slow or
waiting, red = stuck or failed. Nothing animates on its own: the only motion
is the activity graph, which plots measured bytes per second.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget


class WrapRow(QLayout):
    """Buttons left to right, continuing on the next line when the window is narrow.

    Items marked ``wrapRowEnd`` (property) go to the right end of their line.
    """

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)  # Qt's own value: ui_zoom scales it like any layout's

    @property
    def _gap(self) -> int:
        return max(0, self.spacing())

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self):
        width = sum(item.sizeHint().width() + self._gap for item in self._visible())
        return QSize(max(0, width - self._gap), self.minimumSize().height())

    def minimumSize(self):
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize().expandedTo(item.sizeHint()))
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def _visible(self):
        return [item for item in self._items if item.widget() is None or not item.widget().isHidden()]

    def _place(self, rect, *, apply):
        lines, current, used = [], [], 0
        for item in self._visible():
            width = item.sizeHint().width()
            if current and used + self._gap + width > rect.width():
                lines.append(current)
                current, used = [], 0
            used += (self._gap if current else 0) + width
            current.append(item)
        if current:
            lines.append(current)
        y = rect.y()
        for line in lines:
            height = max(item.sizeHint().height() for item in line)
            if apply:
                ends = [item for item in line if item.widget() is not None and item.widget().property('wrapRowEnd')]
                x = rect.x()
                for item in [item for item in line if item not in ends]:
                    hint = item.sizeHint()
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                    x += hint.width() + self._gap
                x = rect.right() + 1
                for item in reversed(ends):
                    hint = item.sizeHint()
                    x -= hint.width()
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                    x -= self._gap
            y += height + self._gap
        return max(0, y - self._gap - rect.y()) if lines else 0


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def tone_color(tone: str, theme=None) -> QColor:
    theme = theme or _theme()
    return QColor({'good': theme.success, 'warn': theme.warning, 'bad': theme.danger,
                   'accent': theme.accent}.get(tone, theme.text_muted))


def _zoom() -> float:
    try:
        from ..app.ui_zoom import zoom_factor
        return zoom_factor()
    except Exception:  # noqa: BLE001 - outside the app (tests) the zoom is 100%
        return 1.0


def _track_color(theme) -> QColor:
    from ..design.ui_theme import blend_hex
    return QColor(blend_hex(theme.surface, theme.border_strong, 0.45 if theme.is_light else 0.55))


class StepTrack(QWidget):
    """Segmented step bar: one segment per installer step, with label and time below.

    A finished step is a full green segment; the current step is filled by its
    measured fraction when there is one, otherwise hatched (no moving fake bar);
    its colour follows the health tone (amber when slow, red when stuck).
    """

    GAP = 8
    BAR = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('downloadStepTrack')
        self._rows: list = []
        self._tone = 'accent'
        self._factor = _zoom()
        # Painted in logical px times the interface zoom (Ctrl+wheel, 2026-10-10);
        # ui_zoom leaves this widget's sizes to apply_ui_zoom.
        self.setProperty('uiZoomOwnSize', True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._height())

    def _px(self, value: float) -> float:
        return value * self._factor

    def _height(self) -> int:
        return round(self._px(self.BAR + 44))

    def apply_ui_zoom(self, factor: float) -> None:
        self._factor = float(factor)
        self.setFixedHeight(self._height())
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(round(self._px(480)), self._height())

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self._px(200)), self._height())

    def set_rows(self, rows, tone: str = 'accent') -> None:
        rows = [tuple(row) for row in rows]
        if rows != self._rows or tone != self._tone:
            self._rows, self._tone = rows, tone
            names = [f'{label} {note}'.strip() for _key, label, _state, note, _fraction in rows]
            self.setAccessibleName(' / '.join(names))
            self.update()

    def rows(self):
        return list(self._rows)

    def paintEvent(self, _event):
        if not self._rows:
            return
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        count = len(self._rows)
        gap, bar_height = self._px(self.GAP), self._px(self.BAR)
        width = (self.width() - gap * (count - 1)) / count
        track = _track_color(theme)
        active = tone_color(self._tone, theme)
        done = QColor(theme.success)
        failed = QColor(theme.danger)
        text = QColor(theme.text)
        muted = QColor(theme.text_muted)
        label_font = QFont(self.font())
        label_font.setPixelSize(max(1, round(self._px(13))))
        note_font = QFont(self.font())
        note_font.setPixelSize(max(1, round(self._px(11))))
        radius = bar_height / 2
        for index, (_key, label, state, note, fraction) in enumerate(self._rows):
            left = index * (width + gap)
            bar = QRectF(left, 0, width, bar_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, radius, radius)
            color = {'done': done, 'failed': failed, 'active': active}.get(state)
            if color is not None:
                if state == 'active' and fraction is None:
                    painter.save()
                    clip = QPainterPath()
                    clip.addRoundedRect(bar, radius, radius)
                    painter.setClipPath(clip)
                    soft = QColor(color)
                    soft.setAlpha(90)
                    painter.setBrush(soft)
                    painter.drawRect(bar)
                    pattern = QBrush(color, Qt.BrushStyle.BDiagPattern)
                    painter.setBrush(pattern)
                    painter.drawRect(bar)
                    painter.restore()
                else:
                    share = 1.0 if state in {'done', 'failed'} else max(0.0, min(1.0, float(fraction or 0)))
                    if share > 0:
                        filled = QRectF(bar.left(), bar.top(), max(bar_height, bar.width() * share), bar.height())
                        painter.setBrush(color)
                        painter.drawRoundedRect(filled, radius, radius)
            # glyph + label
            top = bar_height + self._px(10)
            glyph = QRectF(left, top + self._px(2), self._px(14), self._px(14))
            self._paint_glyph(painter, glyph, state, done, active, failed, muted, self._factor)
            label_font.setWeight(QFont.Weight.DemiBold if state == 'active' else QFont.Weight.Normal)
            painter.setFont(label_font)
            painter.setPen(text if state in {'active', 'failed'} else (text if state == 'done' else muted))
            metrics = QFontMetrics(label_font)
            indent = self._px(20)
            label_rect = QRectF(left + indent, top, max(0.0, width - indent), self._px(18))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(str(label), Qt.TextElideMode.ElideRight, int(label_rect.width())))
            if note:
                painter.setFont(note_font)
                painter.setPen(failed if state == 'failed' else muted)
                note_rect = QRectF(left + indent, top + self._px(18), max(0.0, width - indent), self._px(16))
                painter.drawText(note_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 QFontMetrics(note_font).elidedText(str(note), Qt.TextElideMode.ElideRight,
                                                                    int(note_rect.width())))
        painter.end()

    @staticmethod
    def _paint_glyph(painter, rect, state, done, active, failed, muted, factor=1.0):
        painter.save()
        center = rect.center()
        radius = rect.width() / 2 - 1
        # The check and cross are drawn in 100% units around the centre.
        painter.translate(center)
        painter.scale(factor, factor)
        painter.translate(-center)
        radius = radius / factor
        if state == 'done':
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(done)
            painter.drawEllipse(center, radius, radius)
            pen = QPen(QColor('#ffffff'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath(QPointF(center.x() - 3.2, center.y() + 0.2))
            path.lineTo(center.x() - 0.8, center.y() + 2.6)
            path.lineTo(center.x() + 3.4, center.y() - 2.4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        elif state == 'failed':
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(failed)
            painter.drawEllipse(center, radius, radius)
            pen = QPen(QColor('#ffffff'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(center.x() - 2.6, center.y() - 2.6), QPointF(center.x() + 2.6, center.y() + 2.6))
            painter.drawLine(QPointF(center.x() + 2.6, center.y() - 2.6), QPointF(center.x() - 2.6, center.y() + 2.6))
        elif state == 'active':
            painter.setPen(QPen(active, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius - 0.5, radius - 0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(active)
            painter.drawEllipse(center, 2.6, 2.6)
        else:
            painter.setPen(QPen(muted, 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius - 0.5, radius - 0.5)
        painter.restore()


class ActivityGraph(QWidget):
    """Bars of the last ~90 seconds of measured bytes per second (newest on the right).

    A flat line means nothing arrived or was written: the eye sees "stopped"
    without reading any number.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('downloadActivityGraph')
        self._values: list[float] = []
        self._capacity = 90
        self._tone = 'good'
        self._factor = _zoom()
        self.setProperty('uiZoomOwnSize', True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(round(30 * self._factor))

    def apply_ui_zoom(self, factor: float) -> None:
        self._factor = float(factor)
        self.setFixedHeight(round(30 * self._factor))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(round(220 * self._factor), round(30 * self._factor))

    def set_values(self, values, tone: str = 'good', capacity: int = 90) -> None:
        self._values = [max(0.0, float(value or 0)) for value in values][-capacity:]
        self._capacity = capacity
        self._tone = tone
        self.update()

    def values(self):
        return list(self._values)

    def paintEvent(self, _event):
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        base = _track_color(theme)
        painter.setPen(QPen(base, 1))
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))
        if not self._values:
            painter.end()
            return
        peak = max(max(self._values), 512 * 1024)
        step = rect.width() / max(1, self._capacity)
        color = tone_color(self._tone, theme)
        painter.setPen(Qt.PenStyle.NoPen)
        count = len(self._values)
        for index, value in enumerate(self._values):
            x = rect.right() - (count - index) * step
            height = (rect.height() - 2) * (value / peak)
            if height <= 0:
                continue
            shade = QColor(color)
            shade.setAlpha(110 + int(145 * (index + 1) / count))
            painter.setBrush(shade)
            painter.drawRoundedRect(QRectF(x + step * 0.15, rect.bottom() - height, max(1.0, step * 0.7), height), 1, 1)
        painter.end()


def download_dialog_qss(theme=None) -> str:
    """Styles of the redesigned window; appended after the workshop sheet."""
    from ..design.ui_theme import blend_hex
    from ..design.typography import MONO_FONT_STACK
    theme = theme or _theme()
    good_soft = blend_hex(theme.surface_elevated, theme.success, 0.16)
    warn_soft = blend_hex(theme.surface_elevated, theme.warning, 0.18)
    bad_soft = blend_hex(theme.surface_elevated, theme.danger, 0.16)
    card = blend_hex(theme.surface_elevated, theme.surface_muted, 0.65)
    track = blend_hex(theme.surface, theme.border_strong, 0.45 if theme.is_light else 0.55)
    return f"""
QLabel#downloadSubtitle {{ color: {theme.text_secondary}; font-size: 12px; }}
QLabel#downloadHealthPill {{
    border-radius: 11px; padding: 3px 11px; font-size: 12px; font-weight: 600;
    background: {theme.surface_muted}; color: {theme.text_secondary}; border: 1px solid {theme.border};
}}
QLabel#downloadHealthPill[tone="good"] {{ background: {good_soft}; color: {theme.success}; border-color: {good_soft}; }}
QLabel#downloadHealthPill[tone="warn"] {{ background: {warn_soft}; color: {theme.warning}; border-color: {warn_soft}; }}
QLabel#downloadHealthPill[tone="bad"] {{ background: {bad_soft}; color: {theme.danger}; border-color: {bad_soft}; }}
QFrame#downloadTaskCard {{
    background: {card}; border: 1px solid {theme.border}; border-radius: 12px;
}}
QLabel#downloadTaskTitle {{ color: {theme.text}; font-size: 15px; font-weight: 600; }}
QLabel#downloadTaskFigures {{ color: {theme.text}; font-size: 13px; }}
QLabel#downloadTaskSource, QLabel#downloadActivityText {{ color: {theme.text_muted}; font-size: 12px; }}
QLabel#downloadTaskOutput {{ color: {theme.text_secondary}; font-size: 12px; }}
QLabel#downloadTaskMessage {{ color: {theme.text}; font-size: 13px; }}
QProgressBar#downloadTaskBar {{
    background: {track}; border: 0; border-radius: 4px; min-height: 8px; max-height: 8px;
}}
QProgressBar#downloadTaskBar::chunk {{ background: {theme.success}; border-radius: 4px; }}
QFrame#downloadNotice {{ border-radius: 12px; border: 1px solid {theme.border}; background: {theme.surface_muted}; }}
QFrame#downloadNotice[tone="warn"] {{ background: {warn_soft}; border-color: {blend_hex(warn_soft, theme.warning, 0.35)}; }}
QFrame#downloadNotice[tone="bad"] {{ background: {bad_soft}; border-color: {blend_hex(bad_soft, theme.danger, 0.35)}; }}
QFrame#downloadNotice[tone="good"] {{ background: {good_soft}; border-color: {blend_hex(good_soft, theme.success, 0.35)}; }}
QLabel#downloadNoticeTitle {{ color: {theme.text}; font-size: 14px; font-weight: 600; }}
QFrame#downloadNotice[tone="warn"] QLabel#downloadNoticeTitle {{ color: {theme.warning}; }}
QFrame#downloadNotice[tone="bad"] QLabel#downloadNoticeTitle {{ color: {theme.danger}; }}
QLabel#downloadNoticeWhere {{ color: {theme.text}; font-size: 12px; font-weight: 600; }}
QLabel#downloadNoticeBody {{ color: {theme.text}; font-size: 12px; }}
QLabel#downloadSectionLabel {{ color: {theme.text_muted}; font-size: 12px; font-weight: 600; }}
QLabel#downloadEventTime {{ color: {theme.text_muted}; font-size: 11px; font-family: {MONO_FONT_STACK}; }}
QLabel#downloadEventText {{ color: {theme.text_secondary}; font-size: 12px; }}
QLabel#downloadEventText[tone="good"] {{ color: {theme.text}; }}
QLabel#downloadEventText[tone="warn"] {{ color: {theme.warning}; }}
QLabel#downloadEventText[tone="bad"] {{ color: {theme.danger}; }}
QLabel#downloadEventDot {{ font-size: 10px; color: {theme.text_muted}; }}
QLabel#downloadEventDot[tone="good"] {{ color: {theme.success}; }}
QLabel#downloadEventDot[tone="warn"] {{ color: {theme.warning}; }}
QLabel#downloadEventDot[tone="bad"] {{ color: {theme.danger}; }}
QScrollArea#downloadBodyScroll, QWidget#downloadBody,
QScrollArea#downloadBodyScroll QWidget#qt_scrollarea_viewport {{ background: transparent; border: 0; }}
QFrame#downloadFooterRule {{ background: {theme.border}; max-height: 1px; min-height: 1px; border: 0; }}
"""
