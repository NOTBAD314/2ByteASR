"""Read-only API usage view. Reads SQLite in a worker, never on an edit event.

2026-11-14 (user picked design 3, 日历糖果, same look as the 字幕任务 window):
a top card with the chosen range, the estimated total, a spend bar split by
step and a 45-day calendar to drag a date range on; a task list on the left;
step chips, a 有问题 filter and the request table on the right; one line of
detail for the selected row. Unknown usage is never counted as zero.
"""
from __future__ import annotations

import csv
import json
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
                               QStyle, QStyledItemDelegate, QTableView, QToolTip, QVBoxLayout, QWidget)

from ..providers.api_usage import UsageTotals, call_payload
from ..i18n import tr
from .studio_task_panel import paint_mark, scaled, tones

STEPS = ('断句', '校对', '翻译', '连接测试', '其他')
STEP_KEYS = {'断句': 'seg', '校对': 'proof', '翻译': 'tr', '连接测试': 'test', '其他': 'other'}
STATUS_TEXT = {'received': '已返回用量', 'usage_unknown': '用量未知', 'pending': '请求中', 'cancelled': '已取消',
               'total_timeout': '请求超时', 'rate_limited': '限流', 'auth_error': '凭据被拒绝',
               'quota_exhausted': '余额或额度不足'}
DAYS = 45
NOTE = '费用按每次请求当时的费率估算，不是最终账单；没拿到用量的请求不会算作零。本机翻译缓存不会产生 API 请求。'
RANGES = (('today', '今天'), ('7', '7天'), ('30', '30天'), ('all', '全部'))


def stage_group(stage):
    stage = str(stage).lower()
    if 'translat' in stage:
        return '翻译'
    if 'group' in stage or 'segment' in stage or 'sentence' in stage:
        return '断句'
    if 'polish' in stage or 'proof' in stage:
        return '校对'
    if 'test' in stage or 'probe' in stage:
        return '连接测试'
    return '其他'


def totals_for(rows):
    totals = UsageTotals()
    for row in rows:
        totals.add(call_payload(stage=row['stage'], usage=row.get('raw_usage'),
                                request_id=row['request_id'], estimated_cost=row.get('cost', {'known': False})))
    return totals


def status_label(status):
    return STATUS_TEXT.get(status, '请求异常')


def status_mark(status):
    """The 字幕任务 window's mark for a ledger status."""
    if status == 'received':
        return 'applied'
    if status in {'usage_unknown', 'pending'}:
        return 'review'
    if status == 'cancelled':
        return 'cancelled'
    return 'failed'


def money(value):
    value = Decimal(value)
    if value == 0:
        return '0'
    if value >= 1:
        return f'{value:.2f}'
    if value >= Decimal('0.0001'):
        return f'{value:.4f}'
    return f'{value:.{-value.adjusted() + 1}f}'


def row_money(value):
    value = Decimal(value)
    if value == 0 or value >= Decimal('0.00001'):
        return f'{value:.5f}'
    return f'{value:.{-value.adjusted() + 1}f}'


def cost_text(low, high, fmt=money):
    return fmt(low) if low == high else f'{fmt(low)}–{fmt(high)}'


def compact(value):
    value = int(value or 0)
    if value >= 100_000:
        return f'{value / 1000:.0f}k'
    return f'{value / 1000:.1f}k' if value >= 1000 else str(value)


def local_time(at):
    try:
        value = datetime.fromisoformat(str(at))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()


class Record:
    """One ledger row with the values the window shows, worked out once."""
    __slots__ = ('row', 'at', 'step', 'key', 'low', 'high', 'currency', 'inp', 'out', 'cached', 'ok')

    def __init__(self, row):
        self.row = row
        self.at = local_time(row.get('at'))
        self.step = stage_group(row.get('stage', ''))
        self.key = str(row.get('task_id') or '') or 'loose'
        cost = row.get('cost') or {}
        self.low = self.high = None
        self.currency = str(cost.get('currency') or 'USD')
        if cost.get('known'):
            try:
                self.low, self.high = Decimal(str(cost['low'])), Decimal(str(cost.get('high', cost['low'])))
            except (KeyError, InvalidOperation):
                self.low = self.high = None
        usage = row.get('usage') or {}
        self.inp, self.out = usage.get('input_tokens'), usage.get('output_tokens')
        self.cached = usage.get('cached_input_tokens')
        self.ok = row.get('status') == 'received'


class Sum:
    def __init__(self, records=()):
        self.n = self.unknown = self.bad = self.inp = self.out = self.cached = 0
        self.costs = {}
        self.by_step = {}
        for record in records:
            self.add(record)

    def add(self, record):
        self.n += 1
        self.bad += not record.ok
        self.inp += record.inp or 0
        self.out += record.out or 0
        self.cached += record.cached or 0
        step = self.by_step.setdefault(record.step, [0, 0., 0])
        step[0] += 1
        if record.low is None:
            self.unknown += 1
            step[2] += 1
        else:
            pair = self.costs.setdefault(record.currency, [Decimal(0), Decimal(0)])
            pair[0] += record.low
            pair[1] += record.high
            step[1] += float(record.low)

    @property
    def weight(self):
        return sum(float(low) for low, _high in self.costs.values())

    def money_parts(self):
        """``[(currency, text)]``, USD first."""
        order = sorted(self.costs, key=lambda key: (key != 'USD', key))
        return [(key, cost_text(*self.costs[key])) for key in order]


def _active_theme():
    from ..design.themed_icons import _active_theme as active
    return active(None)


_STEP_COLORS = {}


def step_colors():
    from ..design.usage_dialog_qss import step_tones
    theme = _active_theme()
    if theme.key not in _STEP_COLORS:
        _STEP_COLORS.clear()
        _STEP_COLORS[theme.key] = {step: tuple(QColor(c) for c in value) for step, value in step_tones(theme).items()}
    return _STEP_COLORS[theme.key]


_ICONS = {}


def step_icon(step, size=18):
    """A solid step-coloured circle with the step's first character."""
    theme = _active_theme()
    key = (theme.key, step, size)
    if key not in _ICONS:
        from PySide6.QtWidgets import QApplication
        ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.
        pixmap = QPixmap(int(size * ratio), int(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(step_colors()[step][0])
        painter.drawEllipse(QRectF(0, 0, size, size))
        from ..design.typography import heavy_font
        font = heavy_font(QFont(QGuiApplication.font()))
        font.setPixelSize(int(size * .58))
        painter.setFont(font)
        painter.setPen(QColor(theme.surface_elevated))
        painter.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), tr(step)[:1])
        painter.end()
        _ICONS[key] = QIcon(pixmap)
    return _ICONS[key]


def mark_icon(mark, size=18):
    from .studio_task_panel import mark_icon as icon
    return icon(mark, size)


def _soft(color, amount=.1):
    from ..design.ui_theme import blend_hex
    theme = _active_theme()
    return QColor(blend_hex(theme.surface_elevated, QColor(color).name(), amount))


def paint_pill(painter, rect, soft, ink, text, *, mark=None, dot=None):
    """A rounded badge: optional status mark or coloured dot, then text."""
    metrics = painter.fontMetrics()
    lead = 27 if mark else (20 if dot is not None else 10)
    label = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - lead - 10))
    pill = QRectF(rect.left(), rect.center().y() - 12, min(rect.width(), metrics.horizontalAdvance(label) + lead + 10), 24)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(soft)
    painter.drawRoundedRect(pill, 12, 12)
    if mark:
        paint_mark(painter, QRectF(pill.left() + 3, pill.top() + 3, 18, 18), mark)
    elif dot is not None:
        painter.setBrush(dot)
        painter.drawEllipse(QRectF(pill.left() + 9, pill.center().y() - 4, 8, 8))
    painter.setPen(ink)
    painter.drawText(pill.adjusted(lead, 0, -6, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)


class StepBar(QWidget):
    """The spend bar of the top card, split by step; a click picks that step."""
    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parts = []
        self.setFixedHeight(13)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_parts(self, parts):
        parts = [(step, value) for step, value in parts if value > 0]
        if parts != self.parts:
            self.parts = parts
            self.update()

    def _segments(self):
        total = sum(value for _step, value in self.parts) or 1.
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        x, gap = rect.left(), 2 if len(self.parts) > 1 else 0
        usable = rect.width() - gap * (len(self.parts) - 1)
        for step, value in self.parts:
            width = usable * value / total
            yield step, value / total, QRectF(x, rect.top(), width, rect.height())
            x += width + gap

    def paintEvent(self, _event):
        theme = _active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(theme.input_surface))
        colors = step_colors()
        for step, _share, box in self._segments():
            painter.fillRect(box, colors[step][0])
        painter.end()

    def _at(self, x):
        for step, share, box in self._segments():
            if box.left() <= x <= box.right() + 2:
                return step, share
        return None, 0

    def mouseMoveEvent(self, event):
        step, share = self._at(event.position().x())
        if step:
            QToolTip.showText(event.globalPosition().toPoint(), tr('{step} · 占 {share}%，点一下只看这一步', step=tr(step),
                                                                 share=round(share * 100)), self)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        step, _share = self._at(event.position().x())
        if step and event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(step)
        super().mouseReleaseEvent(event)


class Badge(QWidget):
    """A status badge outside a table (the top card's 用量 line)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mark, self.text = 'applied', ''
        self.setFixedHeight(26)

    def set(self, mark, text):
        self.mark, self.text = mark, str(text)
        self.setVisible(bool(text))
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        font = scaled(self.font(), .93)
        from PySide6.QtGui import QFontMetrics
        return QSize(QFontMetrics(font).horizontalAdvance(self.text) + 40, 26)

    def paintEvent(self, _event):
        _theme, palette = tones()
        _solid, soft, ink = palette[self.mark]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(scaled(self.font(), .93))
        paint_pill(painter, QRectF(self.rect()), soft, ink, self.text, mark=self.mark)
        painter.end()


class DayColumns(QWidget):
    """Daily spend for the last ``DAYS`` days; drag across it to pick dates."""
    picked = Signal(int, int)   # days ago: oldest, newest

    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = [({}, 0, 0) for _ in range(DAYS)]   # oldest first: ({step: weight}, requests, unknown)
        self.span = (DAYS - 1, 0)
        self.today = date.today()
        self.drag = None
        self.setMinimumHeight(88)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_days(self, days, span, today):
        self.days, self.span, self.today = days, span, today
        self.update()

    def _plot(self):
        return QRectF(self.rect()).adjusted(.5, .5, -.5, -17.5)

    def _column(self, index):
        plot = self._plot().adjusted(4, 4, -4, -4)
        width = (plot.width() - 2 * (DAYS - 1)) / DAYS
        return QRectF(plot.left() + index * (width + 2), plot.top(), width, plot.height())

    def _index(self, x):
        plot = self._plot().adjusted(4, 4, -4, -4)
        step = plot.width() / DAYS
        return max(0, min(DAYS - 1, int((x - plot.left()) / step)))

    def _label(self, ago):
        day = self.today - timedelta(days=ago)
        return tr('今天') if ago == 0 else (tr('昨天') if ago == 1 else f'{day.month}/{day.day}')

    def paintEvent(self, _event):
        theme = _active_theme()
        _t, palette = tones()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.input_surface))
        painter.drawRoundedRect(plot, 14, 14)
        peak = max((sum(parts.values()) for parts, _n, _u in self.days), default=0.) or 1.
        colors = step_colors()
        oldest, newest = self.span
        for index, (parts, requests, unknown) in enumerate(self.days):
            ago = DAYS - 1 - index
            box = self._column(index)
            painter.setOpacity(1. if newest <= ago <= oldest else .28)
            if not requests:
                painter.setBrush(QColor(theme.border))
                painter.drawRoundedRect(QRectF(box.left() + box.width() * .2, box.bottom() - 3, box.width() * .6, 3), 1.5, 1.5)
                continue
            stack = [(step, parts[step]) for step in STEPS if parts.get(step)]
            if not stack:   # requests, all without usage
                painter.setBrush(palette['review'][0])
                painter.drawRoundedRect(QRectF(box.left(), box.bottom() - 5, box.width(), 5), 2, 2)
                continue
            height = box.height() * sum(value for _s, value in stack) / peak
            column = QRectF(box.left(), box.bottom() - max(4., height), box.width(), max(4., height))
            clip = QPainterPath()
            clip.addRoundedRect(column, min(4., box.width() / 2), min(4., box.width() / 2))
            painter.save()
            painter.setClipPath(clip)
            y = column.bottom()
            total = sum(value for _s, value in stack)
            for step, value in stack:
                part = column.height() * value / total
                painter.fillRect(QRectF(column.left(), y - part, column.width(), part), colors[step][0])
                y -= part
            painter.restore()
        painter.setOpacity(1.)
        if self.drag:
            low, high = sorted(self.drag)
            left, right = self._column(low), self._column(high)
            painter.setPen(QPen(QColor(theme.accent), 2))
            painter.setBrush(_soft(theme.accent, .12))
            painter.drawRoundedRect(QRectF(left.left() - 3, plot.top() + 1, right.right() - left.left() + 6, plot.height() - 2), 11, 11)
        painter.setPen(QColor(theme.text_muted))
        painter.setFont(scaled(self.font(), .8))
        labels = ((DAYS - 1, Qt.AlignmentFlag.AlignLeft), (30, Qt.AlignmentFlag.AlignHCenter),
                  (15, Qt.AlignmentFlag.AlignHCenter), (0, Qt.AlignmentFlag.AlignRight))
        for ago, align in labels:
            box = self._column(DAYS - 1 - ago)
            area = QRectF(box.center().x() - 40, plot.bottom() + 2, 80, 15)
            if align == Qt.AlignmentFlag.AlignLeft:
                area.moveLeft(plot.left() + 2)
            elif align == Qt.AlignmentFlag.AlignRight:
                area.moveRight(plot.right() - 2)
            painter.drawText(area, int(align | Qt.AlignmentFlag.AlignVCenter), self._label(ago))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index(event.position().x())
            self.drag = [index, index]
            self.update()

    def mouseMoveEvent(self, event):
        index = self._index(event.position().x())
        if self.drag:
            self.drag[1] = index
            self.update()
        parts, requests, unknown = self.days[index]
        ago = DAYS - 1 - index
        if requests:
            text = tr('{day} · 约 {cost} · {count} 次', day=self._label(ago), cost=money(Decimal(str(sum(parts.values())))),
                      count=requests)
            if unknown:
                text = tr('{text} · {unknown} 次用量未知', text=text, unknown=unknown)
        else:
            text = tr('{day} · 没有请求', day=self._label(ago))
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mouseReleaseEvent(self, event):
        if self.drag:
            low, high = sorted(self.drag)
            self.drag = None
            self.update()
            self.picked.emit(DAYS - 1 - low, DAYS - 1 - high)


class TaskDelegate(QStyledItemDelegate):
    """Task cards of the left list: name, amount, a line, a step bar."""
    Role = Qt.ItemDataRole.UserRole + 1

    def sizeHint(self, option, index):
        data = index.data(self.Role) or {}
        return QSize(option.rect.width(), 26 if data.get('header') else 60)

    def paint(self, painter, option, index):
        data = index.data(self.Role) or {}
        theme = _active_theme()
        _t, palette = tones()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        font = option.font
        if data.get('header'):
            painter.setPen(QColor(theme.text_muted))
            painter.setFont(scaled(font, .86))
            painter.drawText(rect.adjusted(8, 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), data['title'])
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setPen(QPen(QColor(theme.accent), 2))
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 14, 14)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.panel))
            painter.drawRoundedRect(rect, 14, 14)
        inner = rect.adjusted(10, 6, -10, -6)
        title_font = scaled(font, .98)
        title_font.setBold(True)
        painter.setFont(title_font)
        cost = data.get('cost', '—')
        cost_width = painter.fontMetrics().horizontalAdvance(cost)
        painter.setPen(QColor(theme.accent_text))
        top = QRectF(inner.left(), inner.top(), inner.width(), 20)
        painter.drawText(top, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), cost)
        painter.setPen(QColor(theme.text))
        title = painter.fontMetrics().elidedText(data.get('title', ''), Qt.TextElideMode.ElideRight, int(inner.width() - cost_width - 8))
        painter.drawText(top, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), title)
        painter.setFont(scaled(font, .82))
        line = QRectF(inner.left(), top.bottom() + 1, inner.width(), 16)
        x = line.left()
        if data.get('unknown'):
            warn = tr('⚠{count} · ', count=data['unknown'])
            painter.setPen(palette['review'][2])
            painter.drawText(line, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), warn)
            x += painter.fontMetrics().horizontalAdvance(warn)
        painter.setPen(QColor(theme.text_muted))
        sub = painter.fontMetrics().elidedText(data.get('sub', ''), Qt.TextElideMode.ElideRight, int(line.right() - x))
        painter.drawText(QRectF(x, line.top(), line.right() - x, line.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), sub)
        bar = QRectF(inner.left(), inner.bottom() - 5, inner.width(), 5)
        clip = QPainterPath()
        clip.addRoundedRect(bar, 2.5, 2.5)
        painter.setClipPath(clip)
        painter.fillRect(bar, QColor(theme.input_surface))
        parts = data.get('parts', [])
        total = sum(value for _s, value in parts) or 1.
        width = bar.width() * data.get('fraction', 1.)
        colors = step_colors()
        x = bar.left()
        for step, value in parts:
            part = width * value / total
            painter.fillRect(QRectF(x, bar.top(), max(0., part - 1), bar.height()), colors[step][0])
            x += part
        painter.restore()


class UsageTableModel(QAbstractTableModel):
    headers = ('时间', '步骤', '输入 → 输出', '缓存命中', '费用', '状态')
    RecordRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []
        self.today = date.today()
        self.titles = {}
        self.currency = ''

    def set_records(self, records, today, titles, currency):
        self.beginResetModel()
        self.records, self.today, self.titles, self.currency = list(records), today, titles, currency
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if section == 4:
                return tr('费用 {currency}', currency=self.currency) if self.currency else tr('费用')
            return tr(self.headers[section])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = Qt.AlignmentFlag.AlignRight if section in (2, 3, 4) else Qt.AlignmentFlag.AlignLeft
            return int(align | Qt.AlignmentFlag.AlignVCenter)
        return None

    def when(self, at):
        if at is None:
            return '?'
        ago = (self.today - at.date()).days
        day = tr('今天') if ago == 0 else (tr('昨天') if ago == 1 else f'{at.month}/{at.day}')
        return f'{day} {at:%H:%M:%S}'

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        record = self.records[index.row()]
        if role == self.RecordRole:
            return record
        column = index.column()
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 0 and record.at is not None:
                utc = record.at.astimezone(timezone.utc)
                return tr('{task}\n{local}（本机时间）· UTC {utc}', task=self.titles.get(record.key, ''),
                          local=f'{record.at:%Y-%m-%d %H:%M:%S}', utc=f'{utc:%H:%M:%S}')
            if column == 4 and record.low is not None:
                return f'{record.currency} {record.low}' + (f'–{record.high}' if record.high != record.low else '')
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == 0:
            return self.when(record.at)
        if column == 1:
            return tr(record.step)
        if column == 2:
            return '—' if record.inp is None else f'{record.inp:,} → {record.out or 0:,}'
        if column == 3:
            return '—' if not record.inp or record.cached is None else f'{round(record.cached / record.inp * 100)}%'
        if column == 4:
            return tr('未知') if record.low is None else cost_text(record.low, record.high, row_money)
        return tr(status_label(record.row.get('status')))


class UsageTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        row = self.rowAt(event.position().toPoint().y())
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_row = -1
        self.viewport().update()
        super().leaveEvent(event)


class UsageRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width(), 38)

    def paint(self, painter, option, index):
        view = self.parent()
        theme, palette = tones()
        record = index.data(UsageTableModel.RecordRole)
        column = index.column()
        cell = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected or index.row() == getattr(view, 'hover_row', -1):
            from ..design.ui_theme import blend_hex
            fill = theme.accent_soft if selected else blend_hex(theme.surface_elevated, theme.text, .05 if theme.is_light else .08)
            painter.setClipRect(cell)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(QRectF(6, cell.top() + 1, view.viewport().width() - 12, cell.height() - 2), 12, 12)
            if selected and column == 0:
                painter.setBrush(QColor(theme.accent))
                painter.drawRoundedRect(QRectF(7, cell.top() + 8, 4, cell.height() - 16), 2, 2)
            painter.setClipping(False)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        font = option.font
        if column in (1, 5):
            painter.setFont(scaled(font, .93))
            if column == 1:
                solid, soft, ink = step_colors()[record.step]
                paint_pill(painter, cell.adjusted(8, 0, -6, 0), soft, ink, text, dot=solid)
            else:
                mark = status_mark(record.row.get('status'))
                _solid, soft, ink = palette[mark]
                paint_pill(painter, cell.adjusted(8, 0, -6, 0), soft, ink, text, mark=mark)
            painter.restore()
            return
        color = QColor(theme.text)
        align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column in (2, 3, 4) else Qt.AlignmentFlag.AlignLeft)
        if column == 3 or (column == 2 and record.inp is None):
            color = QColor(theme.text_muted)
        if column == 4 and record.low is None:
            color = palette['review'][2]
            font = QFont(font)
            font.setBold(True)
        painter.setFont(font)
        painter.setPen(color)
        rect = cell.adjusted(16 if column == 0 else 12, 0, -12, 0)
        painter.drawText(rect, int(align), painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width())))
        painter.restore()


def _button(text, name, slot=None, *, checkable=False):
    button = QPushButton(tr(text) if text else '')
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setCheckable(checkable)
    if slot is not None:
        button.clicked.connect(slot)
    return button


def _label(name, text=''):
    label = QLabel(text)
    label.setObjectName(name)
    return label


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _Signals(QObject):
    loaded = Signal(object, str)


class UsageDialog(QDialog):
    def __init__(self, parent=None, *, project=None, task_id=''):
        super().__init__(parent)
        self.setObjectName('apiUsageDialog')
        # 2026-11-15 (user): our own round frame instead of the Windows title bar.
        from ..app.candy_chrome import CandyChrome
        self.chrome = CandyChrome(self, 'API 用量与估算费用', 'fa5s.coins')
        self.resize(*CandyChrome.outer_size(1040, 690))
        self.setMinimumSize(*CandyChrome.outer_size(960, 620))
        self.project_id = str(getattr(project, 'project_id', '') or '')
        media = getattr(project, 'media', None)
        self.project_name = str(getattr(media, 'display_name', '') or '')
        self.recognition_ref = (getattr(project, 'generation_metadata', {}) or {}).get('recognition_result', {})
        self.task_id = str(task_id or '')
        self.rows, self.records, self.visible_rows = [], [], []
        self.error = ''
        self._loading = False
        self._loaded_once = False
        self.titles, self.subtitles = {}, {}
        self.range_mode, self.span = 'all', (10 ** 6, 0)
        self.step, self.only_problems = '', False
        self.scopes = ['all'] + (['project'] if self.project_id or self.recognition_ref.get('job_id') else []) + (['task'] if self.task_id else [])
        self.scope = self.scopes[-1]
        self._rail_state = None
        self._signals = _Signals(self)
        self._signals.loaded.connect(self._loaded)
        self._build()
        self.refresh()

    # ---------- layout ----------
    def _build(self):
        layout = self.chrome.layout
        layout.setContentsMargins(14, 6, 14, 12)
        layout.setSpacing(9)

        head = QFrame()
        head.setObjectName('usageHead')
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(14, 11, 14, 10)
        head_layout.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(7)
        titles = QHBoxLayout()
        titles.setSpacing(10)
        self.scope_label = _label('usageScopeTitle')
        self.range_label = _label('usageRangeTitle')
        titles.addWidget(self.scope_label)
        titles.addWidget(self.range_label)
        titles.addStretch(1)
        left.addLayout(titles)
        self.money = _label('usageMoney')
        self.money.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(self.money)
        self.bar = StepBar()
        self.bar.picked.connect(self._pick_step)
        left.addWidget(self.bar)
        badges = QHBoxLayout()
        badges.setSpacing(10)
        self.badge = Badge()
        self.facts = _label('usageFacts')
        badges.addWidget(self.badge)
        badges.addStretch(1)
        badges.addWidget(self.facts)
        left.addLayout(badges)
        left.addStretch(1)
        head_layout.addLayout(left, 10)
        right = QVBoxLayout()
        right.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(3)
        top.addWidget(_label('usageHint', tr('每天花了多少 · 在柱子上拖动选日期')))
        top.addStretch(1)
        self.range_group = QButtonGroup(self)
        self.range_buttons = {}
        for key, text in RANGES:
            button = _button(text, 'usageRangeSeg', checkable=True)
            button.clicked.connect(lambda _checked=False, key=key: self._set_range(key))
            self.range_group.addButton(button)
            self.range_buttons[key] = button
            top.addWidget(button)
        right.addLayout(top)
        self.calendar = DayColumns()
        self.calendar.picked.connect(self._pick_days)
        right.addWidget(self.calendar, 1)
        head_layout.addLayout(right, 11)
        layout.addWidget(head)

        split = QHBoxLayout()
        split.setSpacing(9)
        rail = QFrame()
        rail.setObjectName('usageRail')
        rail.setFixedWidth(240)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(6, 6, 6, 6)
        self.tasks = QListWidget()
        self.tasks.setObjectName('usageTasks')
        self.tasks.setItemDelegate(TaskDelegate(self.tasks))
        self.tasks.setMouseTracking(True)
        self.tasks.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tasks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tasks.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tasks.currentItemChanged.connect(self._pick_task_item)
        rail_layout.addWidget(self.tasks)
        split.addWidget(rail)

        body = QVBoxLayout()
        body.setSpacing(8)
        chips = QHBoxLayout()
        chips.setSpacing(7)
        from ..design.soft_widgets import WrapLayout
        self.chips = WrapLayout(spacing=7, fill=False)
        chips.addLayout(self.chips)
        chips.addStretch(1)
        self.todo = _button('', 'usageTodo', self._toggle_problems, checkable=True)
        chips.addWidget(self.todo)
        body.addLayout(chips)
        card = QFrame()
        card.setObjectName('usageTableCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 2, 0, 4)
        self.pages = QStackedWidget()
        self.table = UsageTable()
        self.table.setObjectName('usageTable')
        self.model = UsageTableModel(self.table)
        self.table.setModel(self.model)
        self.table.setItemDelegate(UsageRowDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((130, 94, 132, 78, 108)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().selectionChanged.connect(self._selection)
        self.pages.addWidget(self.table)
        self.empty = _label('usageHint', tr('这段时间没有用到 API～换个时间或任务看看'))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pages.addWidget(self.empty)
        card_layout.addWidget(self.pages)
        body.addWidget(card, 1)
        self.strip = QFrame()
        self.strip.setObjectName('usageNext')
        strip_layout = QHBoxLayout(self.strip)
        strip_layout.setContentsMargins(12, 7, 12, 7)
        strip_layout.setSpacing(10)
        self.strip_lead = _label('usageNextLead')
        self.strip_text = _label('usageNextText')
        self.strip_text.setWordWrap(True)
        self.strip_link = _button('复制原始记录 ›', 'usageLink', self.copy_row)
        strip_layout.addWidget(self.strip_lead, 0, Qt.AlignmentFlag.AlignTop)
        strip_layout.addWidget(self.strip_text, 1)
        strip_layout.addWidget(self.strip_link, 0, Qt.AlignmentFlag.AlignTop)
        body.addWidget(self.strip)
        split.addLayout(body, 1)
        layout.addLayout(split, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.copy_button = _button('复制这一行', 'usageAction', self.copy_row)
        self.export_button = _button('导出 CSV', 'usageAction', self.export_csv)
        self.refresh_button = _button('刷新', 'usageAction', self.refresh)
        for button in (self.copy_button, self.export_button, self.refresh_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(_button('关闭', 'usagePrimary', self.close))
        layout.addLayout(actions)

    # ---------- data ----------
    def refresh(self):
        if self._loading:
            return
        self._loading = True
        signals = self._signals

        def load():
            from ..providers.usage_ledger import read_rows, flush, write_error
            try:
                flush()
                rows, error = read_rows(), write_error()
            except Exception as exc:
                rows, error = [], str(exc)
            from shiboken6 import isValid
            if isValid(signals):
                signals.loaded.emit(rows, error)
        threading.Thread(target=load, name='usage-view-reader', daemon=True).start()

    def _loaded(self, rows, error):
        self._loading = False
        self._loaded_once = True
        self.rows, self.error = list(rows), error
        self.records = [Record(row) for row in self.rows]
        self.records.sort(key=lambda record: record.at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        self._name_tasks()
        self._rail_state = None
        self.render()

    def _today(self):
        return datetime.now().astimezone().date()

    def _in_project(self, row):
        if self.project_id and row.get('project_id') == self.project_id:
            return True
        ref = self.recognition_ref
        return bool(ref.get('job_id') and row.get('task_id') == ref['job_id']
                    and row.get('media_fingerprint') == ref.get('media_fingerprint'))

    def _in_scope(self, record, scope=None):
        scope = self.scope if scope is None else scope
        if scope == 'all':
            return True
        if scope == 'task':
            return record.row.get('task_id') == self.task_id
        if scope == 'project':
            return self._in_project(record.row)
        return record.key == scope[5:]

    def _in_span(self, record):
        if self.range_mode == 'all':
            return True
        if record.at is None:
            return False
        ago = (self._today() - record.at.date()).days
        return self.span[1] <= ago <= self.span[0]

    def _name_tasks(self):
        groups = {}
        self.model.today = self._today()
        for record in self.records:
            groups.setdefault(record.key, []).append(record)
        today = self._today()
        self.titles, self.subtitles, self.task_order = {}, {}, []
        for key, records in groups.items():
            first = min(records, key=lambda record: record.at or datetime.max.replace(tzinfo=timezone.utc))
            label = next((str(r.row.get('task_label')) for r in records if r.row.get('task_label')), '')
            if not label and self.project_name and any(self._in_project(r.row) for r in records):
                label = self.project_name
            when = self.model.when(first.at).rsplit(':', 1)[0] if first.at else ''
            if key == 'loose':
                self.titles[key] = tr('其他请求')
                self.subtitles[key] = tr('没有归入任务，例如连接测试')
            else:
                self.titles[key] = label or tr('任务 {when}', when=when)
                steps = [step for step in STEPS if any(r.step == step for r in records)]
                self.subtitles[key] = '＋'.join(tr(step) for step in steps) + (f' · {when}' if when else '')
            self.task_order.append((max(r.at or first.at or datetime.min.replace(tzinfo=timezone.utc) for r in records), key))
        self.task_order = [key for _at, key in sorted(self.task_order, key=lambda item: item[0], reverse=True)]
        self.model.today = today

    def scope_title(self, scope=None):
        scope = self.scope if scope is None else scope
        if scope == 'task':
            return tr('本次任务')
        if scope == 'project':
            return tr('这个工程')
        if scope == 'all':
            return tr('全部记录')
        return self.titles.get(scope[5:], tr('任务'))

    def range_title(self):
        if self.range_mode == 'custom':
            today = self._today()
            first, last = (today - timedelta(days=self.span[0]), today - timedelta(days=self.span[1]))
            return f'{first.month}/{first.day}' if first == last else f'{first.month}/{first.day}–{last.month}/{last.day}'
        return tr({'today': '今天', '7': '近 7 天', '30': '近 30 天', 'all': '全部时间'}[self.range_mode])

    # ---------- filters ----------
    def _set_range(self, key):
        self.range_mode = key
        self.span = {'today': (0, 0), '7': (6, 0), '30': (29, 0), 'all': (10 ** 6, 0)}[key]
        self.render()

    def _pick_days(self, oldest, newest):
        if oldest == newest == 0:
            return self._set_range('today')
        self.range_mode, self.span = 'custom', (oldest, newest)
        self.render()

    def _pick_step(self, step):
        self.step = '' if self.step == step else step
        self.render()

    def _toggle_problems(self):
        self.only_problems = self.todo.isChecked()
        self.render()

    def _pick_task_item(self, item, _previous=None):
        if self._rail_state is None or item is None:
            return
        scope = item.data(Qt.ItemDataRole.UserRole)
        if scope and scope != self.scope:
            self.scope, self.step, self.only_problems = scope, '', False
            self.render()

    # ---------- render ----------
    def render(self, *_):
        today = self._today()
        ranged = [record for record in self.records if self._in_span(record)]
        scoped = [record for record in ranged if self._in_scope(record)]
        total = Sum(scoped)
        if self.step and self.step not in total.by_step:
            self.step = ''
        if self.only_problems and not total.bad:
            self.only_problems = False
        visible = [record for record in scoped if (not self.step or record.step == self.step)
                   and (not self.only_problems or not record.ok)]
        self.visible_records = visible
        self.visible_rows = [record.row for record in visible]
        self._render_head(visible, Sum(visible), today)
        self._render_rail(ranged)
        self._render_chips(total)
        currencies = {record.currency for record in visible if record.low is not None}
        self.model.set_records(visible, today, self.titles, next(iter(currencies)) if len(currencies) == 1 else '')
        self.pages.setCurrentIndex(0 if visible or not self._loaded_once else 1)
        self._selection()

    def _render_head(self, scoped, total, today):
        self.scope_label.setText(self.scope_title())
        self.range_label.setText(self.range_title())
        if not self._loaded_once:
            self.money.setText(tr('正在读取…'))
        else:
            parts = total.money_parts() or [('USD', tr('未知') if total.unknown else '0')]
            self.money.setText(' + '.join(f'<span style="font-size:14px">{currency}</span>&nbsp;{text}' for currency, text in parts))
        self.facts.setText(tr('{count} 次 · {input} → {output} tokens', count=total.n, input=compact(total.inp),
                              output=compact(total.out)))
        self.bar.set_parts([(step, total.by_step[step][1]) for step in STEPS if step in total.by_step])
        if total.unknown:
            self.badge.set('review', tr('{count} 次用量未知，不算作零', count=total.unknown))
        elif total.n:
            self.badge.set('applied', tr('每次都拿到了用量'))
        else:
            self.badge.set('applied', '')
        for key, button in self.range_buttons.items():
            button.setChecked(key == self.range_mode)
        if self.range_mode == 'custom':
            self.range_group.setExclusive(False)
            for button in self.range_buttons.values():
                button.setChecked(False)
            self.range_group.setExclusive(True)
        in_scope = [record for record in self.records if self._in_scope(record) and record.at is not None]
        days = [[{}, 0, 0] for _ in range(DAYS)]
        for record in in_scope:
            ago = (today - record.at.date()).days
            if 0 <= ago < DAYS:
                slot = days[DAYS - 1 - ago]
                slot[1] += 1
                if record.low is None:
                    slot[2] += 1
                else:
                    slot[0][record.step] = slot[0].get(record.step, 0.) + float(record.low)
        span = self.span if self.range_mode != 'all' else (DAYS - 1, 0)
        self.calendar.set_days([tuple(slot) for slot in days], span, today)

    def _render_rail(self, ranged):
        sums = {}
        for record in ranged:
            sums.setdefault(record.key, Sum()).add(record)
        keys = [key for key in self.task_order if key in sums]
        if self.scope.startswith('task:') and self.scope[5:] not in keys:
            keys.insert(0, self.scope[5:])
        keys = keys[:300]
        fixed = [scope for scope in ('task', 'project', 'all') if scope in self.scopes]
        fixed_sums = {scope: Sum(record for record in ranged if self._in_scope(record, scope)) for scope in fixed}
        peak = max([sums[key].weight for key in keys if key in sums] or [0.]) or 1.

        def card(scope, title, sub, total, fraction):
            parts = [(step, total.by_step[step][1]) for step in STEPS if step in total.by_step and total.by_step[step][1]]
            money_parts = total.money_parts()
            return dict(scope=scope, title=title, sub=sub, unknown=total.unknown, parts=parts, fraction=fraction,
                        cost=' + '.join(text for _c, text in money_parts) if money_parts else (tr('未知') if total.unknown else ('0' if total.n else '—')))
        cards = []
        subs = {'task': self.titles.get(self.task_id, self.project_name), 'project': self.project_name or tr('当前工程'),
                'all': tr('本软件记过的所有请求')}
        icons = {'task': '📌 ', 'project': '📁 ', 'all': '🌐 '}
        for scope in fixed:
            cards.append(card(scope, icons[scope] + self.scope_title(scope), subs[scope], fixed_sums[scope], 1.))
        cards.append(dict(header=True, title=tr('按任务')))
        for key in keys:
            total = sums.get(key, Sum())
            cards.append(card('task:' + key, self.titles.get(key, key), self.subtitles.get(key, ''), total,
                              max(.04, total.weight / peak) if total.weight else .04))
        state = (json.dumps(cards, ensure_ascii=False, sort_keys=True, default=str), self.scope)
        if state == self._rail_state:
            return
        self._rail_state = None
        self.tasks.clear()
        current = None
        for data in cards:
            item = QListWidgetItem()
            item.setData(TaskDelegate.Role, data)
            if data.get('header'):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setData(Qt.ItemDataRole.UserRole, data['scope'])
                item.setToolTip(f"{data['title']}\n{data['sub']}")
                if data['scope'] == self.scope:
                    current = item
            self.tasks.addItem(item)
        if current is not None:
            self.tasks.setCurrentItem(current)
        self._rail_state = state

    def _render_chips(self, total):
        _clear(self.chips)
        chip = _button('', 'usageChip', lambda: self._pick_step(''), checkable=True)
        chip.setText(tr('全部 {count}', count=total.n))
        chip.setProperty('tone', 'all')
        chip.setChecked(not self.step)
        self.chips.addWidget(chip)
        for step in STEPS:
            if step not in total.by_step:
                continue
            chip = _button('', 'usageChip', lambda _checked=False, step=step: self._pick_step(step), checkable=True)
            chip.setText(tr('{step} {count}', step=tr(step), count=total.by_step[step][0]))
            chip.setIcon(step_icon(step))
            chip.setIconSize(QSize(18, 18))
            chip.setProperty('tone', STEP_KEYS[step])
            chip.setChecked(self.step == step)
            self.chips.addWidget(chip)
        if total.unknown:
            chip = _button('', 'usageChip')
            chip.setText(tr('未知 {count}', count=total.unknown))
            chip.setIcon(mark_icon('review'))
            chip.setIconSize(QSize(18, 18))
            chip.setProperty('tone', 'warn')
            chip.setCursor(Qt.CursorShape.ArrowCursor)
            chip.setToolTip(tr('这些请求没拿到用量，费用不算作零'))
            self.chips.addWidget(chip)
        self.todo.setVisible(bool(total.bad))
        self.todo.setText(tr('有问题 {count}', count=total.bad))
        self.todo.setChecked(self.only_problems)

    def selected_record(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.model.records[rows[0].row()] if rows and rows[0].row() < len(self.model.records) else None

    def _selection(self, *_):
        record = self.selected_record()
        self.copy_button.setEnabled(record is not None)
        self.strip_link.setVisible(record is not None)
        if record is None:
            tone, lead = ('warn', tr('记账失败')) if self.error else ('note', tr('说明'))
            text = self.error if self.error else tr(NOTE)
        elif record.ok:
            tone, lead = 'row', tr('这一行')
            cost = tr('未知') if record.low is None else f'{record.currency} {cost_text(record.low, record.high, row_money)}'
            text = tr('{task} · {model} · 输入 {input}（命中 {cached}）→ 输出 {output} · {cost}',
                      task=self.titles.get(record.key, ''), model=record.row.get('model', ''), input=f'{record.inp or 0:,}',
                      cached=f'{record.cached or 0:,}', output=f'{record.out or 0:,}', cost=cost)
        else:
            tone, lead = 'warn', tr('先看看')
            text = tr('{status}：这次没拿到用量，费用不算作零，实际账单可能比这里多一点。',
                      status=tr(status_label(record.row.get('status'))))
        self.strip.setProperty('tone', tone)
        _repolish(self.strip)
        _repolish(self.strip_lead)
        self.strip_lead.setText(lead)
        self.strip_text.setText(text)

    # ---------- actions ----------
    def copy_row(self):
        record = self.selected_record()
        if record is not None:
            QGuiApplication.clipboard().setText(json.dumps(record.row, ensure_ascii=False, indent=2))

    def export_csv(self, path=None):
        if not path:
            path, _filter = QFileDialog.getSaveFileName(self, tr('导出 CSV'), 'api-usage.csv', 'CSV (*.csv)')
        if not path:
            return ''
        with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['本机时间', 'UTC 时间', '任务', '步骤', '模型', '输入', '缓存命中', '输出',
                             '费用（低）', '费用（高）', '币种', '状态', '请求 ID'])
            for record in self.visible_records:
                row = record.row
                writer.writerow([f'{record.at:%Y-%m-%d %H:%M:%S}' if record.at else '', row.get('at', ''),
                                 self.titles.get(record.key, ''), record.step, row.get('model', ''),
                                 '' if record.inp is None else record.inp, '' if record.cached is None else record.cached,
                                 '' if record.out is None else record.out, '' if record.low is None else record.low,
                                 '' if record.high is None else record.high, record.currency if record.low is not None else '',
                                 status_label(row.get('status')), row.get('request_id', '')])
        return path


def open_usage(parent, *, project=None, task_id=''):
    from shiboken6 import isValid
    dialog = getattr(parent, '_usage_dialog', None)
    if dialog is not None and isValid(dialog):
        dialog.refresh(); dialog.show(); dialog.raise_(); dialog.activateWindow()
        return dialog
    dialog = UsageDialog(parent, project=project, task_id=task_id)
    parent._usage_dialog = dialog
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog
