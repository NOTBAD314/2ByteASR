"""Widgets of the report window: timeline, step trail, step detail and log.

They only present a ``support_triage.Analysis``; collecting, exporting and the
window lifecycle stay in ``support_dialog``. Colours come from the active
theme's roles, so 葡萄夜幕 and 奶白 (and every other theme) follow.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QStyle,
                               QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget)

from ..i18n import tr
from .support_triage import ago_text, local_clock, seconds_text, step_chips, step_headline

MONO_FAMILIES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"]


def active_theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def tones(theme):
    """tone -> (strong, soft) colours of the active theme."""
    from ..design.ui_theme import blend_hex
    quiet = blend_hex(theme.panel, theme.text_muted, 0.55)
    return {"danger": (theme.danger, theme.danger_soft), "warn": (theme.warning, theme.warning_soft),
            "info": (theme.info, theme.info_soft), "muted": (quiet, theme.selected),
            "ok": (theme.border_strong, theme.selected), "accent": (theme.accent, theme.accent_soft)}


def tone_text(theme, tone):
    """Readable text colour for a tone (muted text never uses the dim dot colour)."""
    return theme.text_muted if tone in {"muted", "ok"} else tones(theme)[tone][0]


def support_qss(t):
    """Rules for the report window's own objects, layered over the dialog sheet."""
    from ..design.ui_theme import blend_hex
    hover = blend_hex(t.surface, t.selected, 0.6)
    return f"""
QWidget#supportBody {{ background: {t.app_background}; color: {t.text}; }}
QFrame#supportCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
QFrame#supportFooter {{ background: {t.panel}; border: 0; border-top: 1px solid {t.border}; }}
QFrame#supportBanner {{ background: {t.info_soft}; border: 0; border-radius: 10px; }}
QLabel {{ background: transparent; color: {t.text}; }}
QLabel#supportTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#supportMuted, QLabel#supportIdentity {{ color: {t.text_muted}; font-size: 12px; }}
QLabel#supportCardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#supportLegend {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
    padding: 2px 10px; color: {t.text_secondary}; font-size: 12px; }}
QLabel#supportStepName {{ font-size: 17px; font-weight: 700; }}
QLabel#supportHeadline {{ color: {t.text_secondary}; font-size: 13px; }}
QLabel#supportIssueTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#supportRelation {{ color: {t.text_secondary}; border: 1px solid {t.border_strong}; border-radius: 8px;
    padding: 1px 8px; font-size: 11px; }}
QLabel#supportAdvice {{ color: {t.text_secondary}; font-size: 13px; }}
QLabel#supportDev {{ color: {t.text_muted}; font-size: 11px; }}
QLabel#supportStartChip {{ background: {t.accent}; color: {t.text_on_accent}; border-radius: 8px;
    padding: 2px 8px; font-size: 12px; font-weight: 700; }}
QLabel#supportPill {{ border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 600; }}
QLabel#supportBannerText {{ color: {t.text}; font-size: 13px; }}
QLabel#supportKeyValues {{ color: {t.text_secondary}; font-size: 12px; }}
QFrame#supportSegment {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 9px; }}
QPushButton#supportViewButton, QPushButton#supportFilterButton {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 7px;
    min-height: 28px; max-height: 28px; padding: 0 14px; font-size: 13px; font-weight: 500; }}
QPushButton#supportViewButton:hover, QPushButton#supportFilterButton:hover {{ color: {t.text}; background: {hover}; }}
QPushButton#supportViewButton:checked, QPushButton#supportFilterButton:checked {{
    background: {t.surface_elevated}; color: {t.text}; font-weight: 700; }}
QPushButton#supportStepFilter {{ background: {t.accent_soft}; color: {t.text}; border: 1px solid {t.accent};
    border-radius: 14px; min-height: 28px; max-height: 28px; padding: 0 12px; font-size: 12px; }}
QToolButton#diagnosticMore {{ padding: 0 12px; }}
QToolButton#diagnosticMore::menu-indicator {{ image: none; width: 0px; }}
QListWidget#supportSteps {{ background: transparent; border: 0; padding: 0; outline: 0; }}
QListWidget#supportSteps::item, QListWidget#supportSteps::item:selected, QListWidget#supportSteps::item:hover {{
    background: transparent; border: 0; padding: 0; margin: 0; }}
QScrollArea#supportIssueScroll, QScrollArea#supportIssueScroll > QWidget > QWidget {{ background: transparent; border: 0; }}
QTableWidget#diagnosticEvents {{ background: {t.surface}; alternate-background-color: {t.surface};
    color: {t.text}; border: 0; gridline-color: transparent; selection-background-color: {t.selected};
    selection-color: {t.text}; }}
QTableWidget#diagnosticEvents::item {{ padding: 0 6px; border: 0; border-bottom: 1px solid {t.border}; border-radius: 0; }}
QTableWidget#diagnosticEvents::item:selected {{ background: {t.selected}; color: {t.text}; }}
QHeaderView::section {{ background: {t.app_background}; color: {t.text_muted}; border: 0;
    border-bottom: 1px solid {t.border}; padding: 4px 6px; font-size: 12px; }}
QPlainTextEdit#diagnosticsText {{ background: {t.input_surface}; color: {t.text_secondary}; border: 1px solid {t.border};
    border-radius: 10px; padding: 10px 12px; }}
"""


class PlainPage(QWidget):
    """A view page whose wrapped labels do not raise the window's minimum height.

    Qt turns any height-for-width child into the top-level window's minimum
    height at the current width; at 760 px that was 765 px, too tall for a
    150 % laptop screen. The page keeps its ordinary minimum size instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # A QWidget subclass paints its style-sheet background only with this.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def hasHeightForWidth(self):
        return False


def mono_font(size=11):
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size)
    return font


def pill_style(theme, tone):
    strong, soft = tones(theme)[tone]
    return f"background: {soft}; color: {tone_text(theme, tone)};"


def issue_icon(theme, kind, size=28, ratio=1.0):
    """Rounded tile with a drawn glyph; no icon font, so offscreen is exact too."""
    tone = {"act": "danger", "check": "warn", "stall": "warn", "slow": "warn", "auto": "info"}.get(kind, "muted")
    strong, soft = tones(theme)[tone]
    if tone == "muted":
        strong = theme.text_muted
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(soft))
    painter.drawRoundedRect(QRectF(0, 0, size, size), 8, 8)
    pen = QPen(QColor(strong), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    c = size / 2
    if kind in {"act", "check"}:
        painter.drawLine(QPointF(c, c - 6), QPointF(c, c + 2))
        painter.drawPoint(QPointF(c, c + 6))
    elif kind in {"stall", "slow"}:
        painter.drawEllipse(QPointF(c, c), 7, 7)
        painter.drawLine(QPointF(c, c - 4), QPointF(c, c))
        painter.drawLine(QPointF(c, c), QPointF(c + 3, c + 2))
    elif kind == "auto":
        path = QPainterPath(QPointF(c - 5.5, c + 0.5))
        path.lineTo(c - 1.5, c + 4.5)
        path.lineTo(c + 6, c - 4)
        painter.drawPath(path)
    else:
        painter.drawLine(QPointF(c - 5, c), QPointF(c + 5, c))
    painter.end()
    return pixmap


# ---------------------------------------------------------------------------
class TimelineStrip(QWidget):
    """Whole range on top, the selected step zoomed below; click picks a step."""

    stepSelected = Signal(str)
    LABEL_W = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("supportTimeline")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(236)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.analysis = None
        self.selected = None
        self.message = tr("正在读取记录…")
        self._hits = []
        self.setAccessibleName(tr("时间轴：上面是整段记录，下面放大选中的步骤"))

    def sizeHint(self):
        return QSize(760, 236)

    def set_analysis(self, analysis, selected=None):
        self.analysis, self.selected = analysis, selected
        self.update()

    def set_message(self, text):
        self.analysis, self.message = None, text
        self.update()

    def set_selected(self, step_id):
        self.selected = step_id
        self.update()

    # geometry ------------------------------------------------------------
    def _range(self):
        a = self.analysis
        start, end = a.start, a.end
        if a.anchor is not None:
            start, end = min(start, a.anchor), max(end, a.anchor)
        return start, max(end, start + 1.0)

    def _zoom(self):
        a = self.analysis
        step = a.step(self.selected) if self.selected else None
        if step is None:
            anchor = a.anchor if a.anchor is not None else a.end
            return anchor - 2.5, anchor + 0.5
        z0, z1 = step.start - 0.6, step.end + 0.9
        tail = [i.end or i.start for i in step.issues if (i.end or i.start) - step.end < 3]
        if tail:
            z1 = max(z1, max(tail) + 0.3)
        if a.anchor is not None and a.anchor > step.end and a.anchor - step.end < 1.5:
            z1 = max(z1, a.anchor + 0.3)
        if z1 - z0 < 2.2:
            middle = (z0 + z1) / 2
            z0, z1 = middle - 1.1, middle + 1.1
        return z0, z1

    def _steps_in_order(self):
        return sorted(self.analysis.steps, key=lambda s: s.start) if self.analysis else []

    # painting ------------------------------------------------------------
    def paintEvent(self, _event):
        theme = active_theme()
        palette = tones(theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        rect = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        if self.analysis is None or self.analysis.start is None:
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self.message or tr("这段时间没有记录")))
            return
        small = QFont(self.font())
        small.setPixelSize(11)
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        x0, x1 = rect.left() + self.LABEL_W, rect.right() - 2
        width = max(10.0, x1 - x0)
        start, end = self._range()
        span = end - start

        def ox(t):
            return x0 + (t - start) / span * width

        y = 2.0
        painter.setFont(small)
        painter.setPen(QColor(theme.text_muted))
        painter.drawText(QRectF(rect.left(), y, self.LABEL_W, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(tr("全部")))
        self._ticks(painter, x0, width, start, span, y, millis=False)
        y += 18
        lanes = [tr("问题"), tr("卡顿"), tr("操作")]
        lane_h, gap = 20.0, 4.0
        top = y
        step = self.analysis.step(self.selected) if self.selected else None
        for index, label in enumerate(lanes):
            ly = y + index * (lane_h + gap)
            painter.setFont(label_font)
            painter.setPen(QColor(theme.text_secondary))
            painter.drawText(QRectF(rect.left(), ly, self.LABEL_W, lane_h), Qt.AlignmentFlag.AlignVCenter, str(label))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.panel))
            painter.drawRoundedRect(QRectF(x0, ly, width, lane_h), 6, 6)
        bottom = y + 3 * lane_h + 2 * gap
        if step is not None:
            band = QColor(theme.accent)
            band.setAlpha(46)
            painter.setBrush(band)
            left = ox(step.start)
            painter.drawRoundedRect(QRectF(left, top, max(4.0, ox(step.end) - left), bottom - top), 3, 3)
        issues = [i for i in self.analysis.issues if i.lane == "problem"]
        order = {"ignore": 0, "auto": 1, "check": 2, "act": 3}
        for issue in sorted(issues, key=lambda i: order.get(i.kind, 0)):
            colour = QColor(palette[issue.tone][0])
            painter.setBrush(colour)
            painter.setPen(QPen(QColor(theme.panel), 2))
            cx, cy = ox(issue.start), top + lane_h / 2
            painter.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        painter.setPen(Qt.PenStyle.NoPen)
        for issue in self.analysis.issues:
            if issue.kind != "stall":
                continue
            painter.setBrush(QColor(palette["warn"][0]))
            left = ox(issue.start)
            painter.drawRoundedRect(QRectF(left, top + lane_h + gap + 6, max(3.0, ox(issue.end) - left), lane_h - 12), 3, 3)
        for item in self._steps_in_order():
            left = ox(item.start)
            box = QRectF(left, top + 2 * (lane_h + gap) + 5, max(3.0, ox(item.end) - left), lane_h - 10)
            if item.id == self.selected:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.accent))
            elif item.tone in {"danger", "warn", "info"}:
                painter.setPen(QPen(QColor(palette[item.tone][0]), 1))
                painter.setBrush(QColor(palette[item.tone][1]))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.border_strong))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            self._hits.append((box.adjusted(-2, -5, 2, 5), item.id, str(item.name)))
        self._marker(painter, theme, ox, top - 3, bottom + 3)
        z0, z1 = self._zoom()
        y = bottom + 4
        pen = QPen(QColor(theme.text_muted), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        left, right = max(x0, ox(z0)), min(x1, ox(z1))
        path = QPainterPath(QPointF(left, y))
        path.lineTo(left, y + 6)
        path.lineTo(right, y + 6)
        path.lineTo(right, y)
        painter.drawPath(path)
        y += 12
        painter.setFont(small)
        painter.setPen(QColor(theme.text_secondary))
        painter.drawText(QRectF(rect.left(), y, self.LABEL_W, 14), Qt.AlignmentFlag.AlignVCenter, str(tr("放大处")))
        self._ticks(painter, x0, width, z0, z1 - z0, y, millis=True)
        y += 18
        self._zoom_lanes(painter, theme, palette, x0, width, z0, z1, y, rect)

    def _ticks(self, painter, x0, width, start, span, y, *, millis):
        painter.setPen(QColor(active_theme().text_muted))
        metrics = QFontMetricsF(painter.font())
        for k in range(5):
            stamp = start + span * k / 4
            text = local_clock(stamp, millis=False) if not millis else local_clock(stamp, millis=True)[:-2]
            w = metrics.horizontalAdvance(text)
            x = x0 + width * k / 4
            left = x if k == 0 else (x - w if k == 4 else x - w / 2)
            painter.drawText(QRectF(left, y, w + 2, 14), Qt.AlignmentFlag.AlignVCenter, text)

    def _marker(self, painter, theme, ox, top, bottom):
        anchor = self.analysis.anchor
        if anchor is None:
            return
        painter.setPen(QPen(QColor(theme.accent), 2))
        x = ox(anchor)
        painter.drawLine(QPointF(x, top), QPointF(x, bottom))

    def _zoom_lanes(self, painter, theme, palette, x0, width, z0, z1, y, rect):
        span = z1 - z0
        lane_h, gap = 28.0, 4.0
        labels = [tr("问题"), tr("卡顿"), tr("操作")]
        font = QFont(self.font())
        font.setPixelSize(11)
        bold = QFont(font)
        bold.setBold(True)
        metrics = QFontMetricsF(font)

        def zx(t):
            return x0 + (min(max(t, z0), z1) - z0) / span * width

        def visible(a, b):
            return (b if b is not None else a) >= z0 and a <= z1

        step = self.analysis.step(self.selected) if self.selected else None
        top = y
        for index, label in enumerate(labels):
            ly = y + index * (lane_h + gap)
            painter.setFont(QFont(self.font()))
            label_font = QFont(self.font())
            label_font.setPixelSize(12)
            painter.setFont(label_font)
            painter.setPen(QColor(theme.text_secondary))
            painter.drawText(QRectF(rect.left(), ly, self.LABEL_W, lane_h), Qt.AlignmentFlag.AlignVCenter, str(label))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.panel))
            painter.drawRoundedRect(QRectF(x0, ly, width, lane_h), 6, 6)
        bottom = y + 3 * lane_h + 2 * gap
        painter.save()
        painter.setClipRect(QRectF(x0, top, width, bottom - top))
        if step is not None:
            band = QColor(theme.accent)
            band.setAlpha(36)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(band)
            painter.drawRect(QRectF(zx(step.start), top, max(4.0, zx(step.end) - zx(step.start)), bottom - top))
        # Problem pills; overlapping ones become one cluster.
        pills = []
        for issue in sorted((i for i in self.analysis.issues if i.lane == "problem" and visible(i.start, i.end)), key=lambda i: i.start):
            text = str(issue.short or "")
            x = zx(issue.start)
            w = max(22.0, metrics.horizontalAdvance(text) + 16) if text else 14.0
            right = max(x + w, zx(issue.end) if issue.end else 0)
            if pills and x < pills[-1]["right"] + 4:
                last = pills[-1]
                last["items"].append(issue)
                last["right"] = max(last["right"], right)
                continue
            pills.append(dict(x=x, right=right, items=[issue]))
        for pill in pills:
            items = pill["items"]
            worst = min(items, key=lambda i: i.rank)
            text = _cluster_label(items)
            w = max(pill["right"] - pill["x"], metrics.horizontalAdvance(text) + 16)
            box = QRectF(pill["x"], top + 5, w, lane_h - 10)
            if box.right() > x0 + width:
                box.moveRight(x0 + width - 1)
            self._pill(painter, theme, palette, box, worst.tone, text, font, selected=step is not None and worst.step is step)
            names = " · ".join(str(i.title) for i in items[:4])
            self._hits.append((box, worst.step.id if worst.step else None, names))
        bars = []
        for issue in sorted((i for i in self.analysis.issues if i.kind == "stall" and visible(i.start, i.end)), key=lambda i: i.start):
            if bars and issue.start < bars[-1][1]:
                bars[-1][1] = max(bars[-1][1], issue.end)
                bars[-1][2].append(issue)
            else:
                bars.append([issue.start, issue.end, [issue]])
        for begin, finish, members in bars:
            box = QRectF(zx(begin), top + lane_h + gap + 5, max(6.0, zx(finish) - zx(begin)), lane_h - 10)
            text = str(members[0].short) if len(members) == 1 else str(tr("卡住 {seconds} 秒", seconds=" + ".join(
                seconds_text(i.duration_ms / 1000) for i in members[:3])))
            owner = members[0].step
            self._pill(painter, theme, palette, box, "warn", text if metrics.horizontalAdvance(text) + 12 <= box.width() else "",
                       font, selected=owner is step, radius=5)
            self._hits.append((box, owner.id if owner else None, " · ".join(str(i.title) for i in members)))
        for item in self._steps_in_order():
            if not visible(item.start, item.end):
                continue
            box = QRectF(zx(item.start), top + 2 * (lane_h + gap) + 5, max(8.0, zx(item.end) - zx(item.start)), lane_h - 10)
            on = item is step
            painter.setPen(Qt.PenStyle.NoPen)
            if on:
                painter.setBrush(QColor(theme.accent))
            else:
                painter.setBrush(QColor(palette[item.tone][1] if item.tone != "ok" else theme.selected))
            painter.drawRoundedRect(box, 5, 5)
            if not on and item.tone in {"danger", "warn", "info"}:
                painter.setPen(QPen(QColor(palette[item.tone][0]), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
            name = str(item.name)
            painter.setFont(bold if on else font)
            painter.setPen(QColor(theme.text_on_accent if on else theme.text_secondary))
            fitted = QFontMetricsF(painter.font()).elidedText(name, Qt.TextElideMode.ElideRight, box.width() - 10)
            if box.width() > 28 and fitted not in {"…", ""}:
                painter.drawText(box.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, fitted)
            self._hits.append((box.adjusted(0, -4, 0, 4), item.id, name))
        painter.restore()
        anchor = self.analysis.anchor
        if anchor is not None and z0 <= anchor <= z1:
            x = zx(anchor)
            painter.setPen(QPen(QColor(theme.accent), 2))
            painter.drawLine(QPointF(x, top - 2), QPointF(x, bottom + 2))
            label = ("▲ " + str(tr("你按下回报")) if self.analysis.anchor_is_mark else "▲ " + str(tr("记录结束"))) + " " + local_clock(anchor, millis=True)
            painter.setFont(font)
            w = metrics.horizontalAdvance(label) + 4
            left = min(max(x0, x - w / 2), x0 + width - w)
            painter.setPen(QColor(theme.accent_text))
            painter.drawText(QRectF(left, bottom + 3, w, 16), Qt.AlignmentFlag.AlignVCenter, label)

    def _pill(self, painter, theme, palette, box, tone, text, font, *, selected=False, radius=None):
        strong, soft = palette[tone]
        painter.setPen(QPen(QColor(strong), 1))
        painter.setBrush(QColor(soft))
        r = box.height() / 2 if radius is None else radius
        painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        if selected:
            painter.setPen(QPen(QColor(theme.text), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5), r + 1.5, r + 1.5)
        if text:
            painter.setFont(font)
            painter.setPen(QColor(tone_text(theme, tone)))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # interaction ---------------------------------------------------------
    def _hit(self, pos):
        for box, step_id, text in reversed(self._hits):
            if box.contains(QPointF(pos)):
                return step_id, text
        return None, None

    def mousePressEvent(self, event):
        step_id, _text = self._hit(event.position())
        if step_id:
            self.stepSelected.emit(step_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        step_id, text = self._hit(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if step_id else Qt.CursorShape.ArrowCursor)
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        steps = self._steps_in_order()
        if steps and event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Right}:
            ids = [s.id for s in steps]
            index = ids.index(self.selected) if self.selected in ids else len(ids) - 1
            index = max(0, min(len(ids) - 1, index + (-1 if event.key() == Qt.Key.Key_Left else 1)))
            self.stepSelected.emit(ids[index])
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
STEP_ROLE = Qt.ItemDataRole.UserRole + 41


class StepDelegate(QStyledItemDelegate):
    """One row of the trail: time, rail and dot, name and detail, badges."""

    def sizeHint(self, option, index):
        data = index.data(STEP_ROLE) or {}
        return QSize(300, 36 if data.get("marker") else (52 if data.get("chips") or data.get("issues") else 44))

    def paint(self, painter, option, index):
        data = index.data(STEP_ROLE) or {}
        theme = active_theme()
        palette = tones(theme)
        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            from ..design.ui_theme import blend_hex
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.selected if selected else blend_hex(theme.surface, theme.selected, 0.5)))
            painter.drawRect(rect)
            if selected:
                painter.setBrush(QColor(theme.accent))
                painter.drawRect(QRectF(rect.left(), rect.top(), 3, rect.height()))
        base = QFont(option.font)
        small = QFont(base)
        small.setPixelSize(12)
        painter.setFont(small)
        ago_rect = QRectF(rect.left() + 8, rect.top(), 58, rect.height())
        painter.setPen(QColor(theme.accent_text if data.get("marker") else theme.text_muted))
        painter.drawText(ago_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, data.get("ago", ""))
        rail = rect.left() + 80
        painter.setPen(QPen(QColor(theme.border), 2))
        top = rect.center().y() if data.get("first") else rect.top()
        bottom = rect.center().y() if data.get("last") else rect.bottom() + 1
        painter.drawLine(QPointF(rail, top), QPointF(rail, bottom))
        centre = QPointF(rail, rect.center().y())
        if data.get("marker"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent))
            painter.drawEllipse(centre, 6, 6)
        elif data.get("tone", "ok") == "ok":
            painter.setPen(QPen(QColor(theme.border_strong), 2))
            painter.setBrush(QColor(theme.surface))
            painter.drawEllipse(centre, 4.5, 4.5)
        else:
            painter.setPen(QPen(QColor(theme.surface), 3))
            painter.setBrush(QColor(palette[data["tone"]][0]))
            painter.drawEllipse(centre, 6, 6)
        chips = data.get("chips") or []
        chip_font = QFont(base)
        chip_font.setPixelSize(11)
        chip_metrics = QFontMetricsF(chip_font)
        chip_w = max((chip_metrics.horizontalAdvance(label) + 16 for _tone, label in chips), default=0)
        text_left = rail + 16
        text_right = rect.right() - 10 - (chip_w + 8 if chips else 0)
        name_font = QFont(base)
        name_font.setPixelSize(14 if data.get("marker") else 13)
        name_font.setBold(bool(data.get("marker") or data.get("tone", "ok") != "ok"))
        painter.setFont(name_font)
        name_metrics = QFontMetricsF(name_font)
        sub = data.get("sub", "")
        if data.get("marker"):
            painter.setPen(QColor(theme.accent_text))
            painter.drawText(QRectF(text_left, rect.top(), text_right - text_left, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, data.get("name", ""))
        else:
            name_h = name_metrics.height()
            sub_h = QFontMetricsF(small).height() if sub else 0
            y = rect.center().y() - (name_h + sub_h) / 2
            painter.setPen(QColor(theme.text if data.get("tone", "ok") != "ok" else theme.text_secondary))
            painter.drawText(QRectF(text_left, y, text_right - text_left, name_h), Qt.AlignmentFlag.AlignVCenter,
                             name_metrics.elidedText(data.get("name", ""), Qt.TextElideMode.ElideRight, text_right - text_left))
            if sub:
                painter.setFont(small)
                painter.setPen(QColor(theme.text_muted))
                painter.drawText(QRectF(text_left, y + name_h, text_right - text_left, sub_h), Qt.AlignmentFlag.AlignVCenter,
                                 QFontMetricsF(small).elidedText(sub, Qt.TextElideMode.ElideRight, text_right - text_left))
        if chips:
            painter.setFont(chip_font)
            total = len(chips) * 18 + (len(chips) - 1) * 3
            y = rect.center().y() - total / 2
            for tone, label in chips:
                w = chip_metrics.horizontalAdvance(label) + 16
                box = QRectF(rect.right() - 10 - w, y, w, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(palette[tone][1]))
                painter.drawRoundedRect(box, 9, 9)
                painter.setPen(QColor(tone_text(theme, tone)))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
                y += 21
        painter.restore()


class StepTrail(QListWidget):
    """The person's steps, newest first, under a 'you pressed report' row."""

    stepSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("supportSteps")
        self.setItemDelegate(StepDelegate(self))
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAccessibleName(tr("操作轨迹"))
        self.currentItemChanged.connect(self._changed)
        self._quiet = False

    def set_analysis(self, analysis):
        self._quiet = True
        self.clear()
        steps = list(reversed(analysis.steps))
        marker = QListWidgetItem()
        marker.setFlags(Qt.ItemFlag.ItemIsEnabled)
        marker.setData(STEP_ROLE, dict(marker=True, first=True, last=not steps, ago=str(tr("0 秒")),
                                       name=str(tr("你按下回报") if analysis.anchor_is_mark else tr("记录结束"))))
        marker.setText(str(tr("你按下回报")))
        self.addItem(marker)
        for number, step in enumerate(steps):
            item = QListWidgetItem()
            chips = [(tone, str(label)) for tone, label in step_chips(step)]
            sub = step.detail or (step_headline(step) if step.issues else tr("没有发现问题"))
            item.setData(STEP_ROLE, dict(id=step.id, tone=step.tone, name=str(step.name), sub=str(sub), chips=chips,
                                         ago=str(ago_text(analysis, step.start)), issues=bool(step.issues),
                                         last=number == len(steps) - 1))
            item.setText(str(step.name))
            item.setToolTip(str(step_headline(step)))
            self.addItem(item)
        self._quiet = False

    def select(self, step_id):
        for row in range(self.count()):
            item = self.item(row)
            if (item.data(STEP_ROLE) or {}).get("id") == step_id:
                if self.currentItem() is not item:
                    self._quiet = True
                    self.setCurrentItem(item)
                    self._quiet = False
                self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
                return

    def _changed(self, current, _previous):
        if self._quiet or current is None:
            return
        step_id = (current.data(STEP_ROLE) or {}).get("id")
        if step_id:
            self.stepSelected.emit(step_id)


# ---------------------------------------------------------------------------
class IssueRow(QFrame):
    def __init__(self, issue, first, parent=None):
        super().__init__(parent)
        self.setObjectName("supportIssueRow")
        theme = active_theme()
        if not first:
            self.setStyleSheet(f"QFrame#supportIssueRow {{ border: 0; border-top: 1px solid {theme.border}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setObjectName("supportIssueIcon")
        ratio = self.devicePixelRatioF() if self.devicePixelRatioF() > 0 else 1.0
        icon.setPixmap(issue_icon(theme, issue.kind, 28, ratio))
        icon.setFixedSize(28, 28)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(str(issue.title))
        self.title.setObjectName("supportIssueTitle")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        if issue.relation is not None:
            relation = QLabel(str(issue.relation))
            relation.setObjectName("supportRelation")
            relation.setToolTip(str(tr("“同一操作／同一任务”表示记录里有相同的编号；“时间接近”只表示先后，不代表因果。")))
            head.addWidget(relation, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(head)
        advice = QLabel(f"<span style='color:{theme.text_muted}'>{tr('可以先试：')}</span>{_escape(str(issue.advice))}")
        advice.setObjectName("supportAdvice")
        advice.setWordWrap(True)
        body.addWidget(advice)
        dev = QLabel(issue.dev)
        dev.setObjectName("supportDev")
        dev.setFont(mono_font(11))
        dev.setWordWrap(True)
        dev.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dev.setToolTip(str(tr("给开发者：用 #序号 或操作 ID 在详细记录或 events.jsonl 里找到这一笔")))
        body.addWidget(dev)
        layout.addLayout(body, 1)


def _cluster_label(items):
    """'错误 ×2 · AI ×12': what a crowded spot holds, most severe first."""
    labels = {}
    for issue in sorted(items, key=lambda i: i.rank):
        text = str(issue.short or "")
        labels[text] = labels.get(text, 0) + 1
    parts = [label if count == 1 else f"{label} ×{count}" for label, count in labels.items() if label]
    return " · ".join(parts[:2]) + (" …" if len(parts) > 2 else "")


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class StepDetail(QFrame):
    """The selected step: what happened, what to try, where in the code."""

    showStepLog = Signal(str)
    copyStep = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("supportCard")
        self.step_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        head = QVBoxLayout(header)
        head.setContentsMargins(16, 12, 16, 10)
        head.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.start_chip = QLabel("从这里开始")
        self.start_chip.setObjectName("supportStartChip")
        self.start_chip.hide()
        row.addWidget(self.start_chip)
        self.name = QLabel()
        self.name.setObjectName("supportStepName")
        row.addWidget(self.name, 1)
        self.when = QLabel()
        self.when.setObjectName("supportMuted")
        row.addWidget(self.when)
        head.addLayout(row)
        self.headline = QLabel()
        self.headline.setObjectName("supportHeadline")
        self.headline.setWordWrap(True)
        head.addWidget(self.headline)
        layout.addWidget(header)
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setObjectName("supportRule")
        rule.setStyleSheet(f"background: {active_theme().border};")
        self._rule = rule
        layout.addWidget(rule)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("supportIssueScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(48)
        self.container = QWidget()
        self.rows = QVBoxLayout(self.container)
        self.rows.setContentsMargins(16, 0, 16, 0)
        self.rows.setSpacing(0)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 8, 16, 10)
        footer.setSpacing(8)
        from ..design.presentation import button_role
        self.only = QPushButton()
        self.only.setObjectName("supportOnlyStep")
        button_role(self.only, "secondary", size="compact")
        self.only.clicked.connect(lambda: self.step_id and self.showStepLog.emit(self.step_id))
        footer.addWidget(self.only)
        self.copy = QPushButton("复制这一步")
        self.copy.setObjectName("supportCopyStep")
        button_role(self.copy, "ghost", size="compact")
        self.copy.clicked.connect(lambda: self.step_id and self.copyStep.emit(self.step_id))
        footer.addWidget(self.copy)
        footer.addStretch(1)
        layout.addLayout(footer)

    def show_step(self, analysis, step, log_count):
        from ..i18n_widgets import bind_text
        self.step_id = step.id if step else None
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if step is None:
            self.name.setText(str(tr("还没有选中步骤")))
            self.when.clear()
            self.headline.clear()
            self.start_chip.hide()
            self.only.setEnabled(False)
            self.copy.setEnabled(False)
            return
        self.start_chip.setVisible(step is analysis.start_step)
        self.name.setText(str(step.name))
        self.when.setText(f"{local_clock(step.start, millis=True)} · {ago_text(analysis, step.start)}")
        self.headline.setText(str(step_headline(step)))
        visible = [i for i in step.issues]
        if not visible:
            empty = QLabel(str(tr("这一步没有记录到错误、卡顿或资料异常。")))
            empty.setObjectName("supportHeadline")
            empty.setContentsMargins(0, 16, 0, 16)
            self.rows.addWidget(empty)
        for number, issue in enumerate(visible):
            self.rows.addWidget(IssueRow(issue, number == 0))
        self.rows.addStretch(1)
        bind_text(self.only, tr("只看这一步的记录（{count} 笔）", count=log_count))
        self.only.setEnabled(log_count > 0)
        self.copy.setEnabled(True)
        self.scroll.verticalScrollBar().setValue(0)


def step_text(analysis, step):
    """Plain text of one step for the clipboard."""
    lines = [f"{step.name} · {local_clock(step.start, millis=True)} · {ago_text(analysis, step.start)}", str(step_headline(step))]
    for issue in step.issues:
        lines += [f"- {issue.title}（{issue.relation or ''}）", f"  {tr('可以先试：')}{issue.advice}", f"  {issue.dev}"]
    return "\n".join(lines)


def key_values_html(theme, pairs):
    rows = "".join(f"<tr><td style='color:{theme.text_muted};padding:1px 14px 1px 0;white-space:nowrap'>{_escape(str(k))}</td>"
                   f"<td style='color:{theme.text_secondary};padding:1px 0'>{_escape(str(v))}</td></tr>" for k, v in pairs if v not in (None, ""))
    return f"<table cellspacing='0' cellpadding='0'>{rows}</table>"


def row_json(row):
    return json.dumps(row, ensure_ascii=False, indent=2, default=str)
