"""Nonmodal, reopenable Studio task details with throttled incremental updates.

2026-11-14 (user picked design A, 糖果计数): same order as before — task,
progress, counts, list, details, actions — made easier to read. The progress
bar is split by result, the counts are clickable chips that filter the list
(zero counts are left out), shared causes are small cards, each row carries
a status badge and a preview of its text or its reason, and the details show
原文 / 模型分段 / 实际写回 side by side with one line on what to do next.
The full record stays one click away.
"""

from __future__ import annotations

import html
import json
from collections import Counter

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QStyle, QStyledItemDelegate,
    QTableView, QToolButton, QVBoxLayout, QWidget, QDialog)

from .studio_task_progress import STATUS_TEXT, TERMINAL

TODO = frozenset({'failed', 'review', 'cancelled'})
SHORT_TEXT = {'applied': '已写回', 'unchanged': '无需调整', 'suggestion': '建议待采用', 'review': '需检查',
              'failed': '失败，保留原文', 'cancelled': '已取消', 'validated': '等待写回', 'pending': '排队中',
              'running': '处理中'}
CHIP_ORDER = ('applied', 'unchanged', 'suggestion', 'review', 'failed', 'cancelled')
NEXT_STEP = {
    'failed': ('没改动', '原文已保留。可定位原字幕试听核对；修正模型配置或手动编辑后，{retry}'),
    'review': ('先看看', '模型没给出可用结果，已按本地规则断句并写回。建议定位试听，确认断得对不对。'),
    'suggestion': ('等你决定', '建议已经准备好，在字幕表里采用或忽略。'),
    'cancelled': ('没处理', '任务取消时还没处理到这段，原文没动。{retry}'),
    'applied': ('搞定', '新的结果已经写回字幕表。'),
    'unchanged': ('搞定', '这段已经合适，没有改动。'),
    'validated': ('马上好', '结果已通过校验，正在写回。'),
    'running': ('处理中', '正在处理，第 {attempts} 次尝试。'),
    'pending': ('排队中', '还没轮到这段。'),
}


def time_text(value):
    value = max(0, int(value or 0))
    seconds, millis = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def short_time(value):
    full = time_text(value)
    return full[3:] if full.startswith('00:') else full


def elapsed_text(seconds):
    seconds = int(round(seconds))
    return f'{seconds} 秒' if seconds < 60 else f'{seconds // 60} 分 {seconds % 60:02d} 秒'


def row_status(row):
    status = str(row.get('status') or 'pending')
    return status if status in SHORT_TEXT else 'running'


def scaled(font, factor):
    from PySide6.QtGui import QFont
    font = QFont(font)
    if font.pixelSize() > 0:
        font.setPixelSize(max(9, round(font.pixelSize() * factor)))
    elif font.pointSizeF() > 0:
        font.setPointSizeF(max(7., font.pointSizeF() * factor))
    return font


def _theme():
    from ..design.themed_icons import _active_theme
    return _active_theme(None)


_TONES = {}


def tones():
    from ..design.task_panel_qss import status_tones
    theme = _theme()
    if theme.key not in _TONES:
        _TONES.clear()
        _TONES[theme.key] = (theme, {key: tuple(QColor(c) for c in value) for key, value in status_tones(theme).items()})
    return _TONES[theme.key]


def paint_mark(painter, rect, status, angle=0.):
    """A round status mark drawn as shapes, so it never depends on a font."""
    theme, palette = tones()
    solid = palette.get(status, palette['pending'])[0]
    glyph = QColor(theme.surface_elevated)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    d = min(rect.width(), rect.height())
    box = QRectF(rect.center().x() - d / 2, rect.center().y() - d / 2, d, d)
    line = max(1.6, d * .13)
    if status in {'running', 'pending'}:
        pen = QPen(solid, line, Qt.PenStyle.SolidLine if status == 'running' else Qt.PenStyle.DotLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inner = box.adjusted(line, line, -line, -line)
        if status == 'running':
            painter.drawArc(inner, int(-angle * 16), int(270 * 16))
        else:
            painter.drawEllipse(inner)
        painter.restore()
        return
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(solid)
    painter.drawEllipse(box)
    pen = QPen(glyph, line, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    c, u = box.center(), d / 2
    p = lambda x, y: QPointF(c.x() + x * u, c.y() + y * u)
    if status == 'applied':
        path = QPainterPath(p(-.42, .02))
        path.lineTo(p(-.12, .32))
        path.lineTo(p(.42, -.28))
        painter.drawPath(path)
    elif status == 'unchanged':
        painter.drawLine(p(-.36, -.16), p(.36, -.16))
        painter.drawLine(p(-.36, .18), p(.36, .18))
    elif status == 'failed':
        painter.drawLine(p(-.3, -.3), p(.3, .3))
        painter.drawLine(p(.3, -.3), p(-.3, .3))
    elif status == 'cancelled':
        painter.drawLine(p(-.36, 0), p(.36, 0))
    elif status == 'review':
        painter.drawLine(p(0, -.42), p(0, .1))
        painter.drawPoint(p(0, .38))
    elif status == 'validated':
        for x in (-.34, 0, .34):
            painter.drawPoint(p(x, 0))
    else:  # suggestion: a small four-point sparkle
        path = QPainterPath(p(0, -.5))
        for x, y in ((.13, -.13), (.5, 0), (.13, .13), (0, .5), (-.13, .13), (-.5, 0), (-.13, -.13), (0, -.5)):
            path.lineTo(p(x, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glyph)
        painter.drawPath(path)
    painter.restore()


_ICONS = {}


def mark_icon(status, size=18):
    theme, _palette = tones()
    key = (theme.key, status, size)
    if key not in _ICONS:
        from PySide6.QtWidgets import QApplication
        ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.
        pixmap = QPixmap(int(size * ratio), int(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_mark(painter, QRectF(0, 0, size, size), status, 45)
        painter.end()
        _ICONS[key] = QIcon(pixmap)
    return _ICONS[key]


class TaskTableModel(QAbstractTableModel):
    headers = ['字幕', '素材时间', '状态', '尝试', '原文 / 原因']
    StatusRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.keys = []
        self.indexes = {}
        self.rendered = {}

    def set_task(self, task):
        self.beginResetModel()
        self.task = task
        self.keys = list(task.rows) if task else []
        self.indexes = {key: index for index, key in enumerate(self.keys)}
        self.rendered = dict(task.rows) if task else {}
        self.endResetModel()

    def sync(self):
        if self.task is None:
            return
        added = [key for key in self.task.rows if key not in self.indexes]
        if added:
            self.beginInsertRows(QModelIndex(), len(self.keys), len(self.keys)+len(added)-1)
            for key in added:
                self.indexes[key] = len(self.keys)
                self.keys.append(key)
            self.endInsertRows()
        for key, row in self.task.rows.items():
            if self.rendered.get(key) is not row:
                index = self.indexes[key]
                self.rendered[key] = row
                self.dataChanged.emit(self.index(index, 0), self.index(index, 4))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.keys)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal and section == 1 and self.task is not None:
                return getattr(self.task,'time_label',self.headers[section])
            return self.headers[section] if orientation == Qt.Orientation.Horizontal else str(section+1)
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            align = Qt.AlignmentFlag.AlignCenter if section == 3 else Qt.AlignmentFlag.AlignLeft
            return int(align | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.task.rows[self.keys[index.row()]]
        if role == self.StatusRole:
            return row_status(row)
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        column = index.column()
        if column == 0:
            ids = row.get('cue_ids', ())
            if row.get('range_label') and role == Qt.ItemDataRole.DisplayRole:
                return row['range_label']
            source_rows = row.get('source_rows')
            if source_rows and role == Qt.ItemDataRole.DisplayRole:
                return f'第 {source_rows[0]} 条' if len(source_rows) == 1 else f'第 {source_rows[0]}–{source_rows[-1]} 条（{len(ids)} 条）'
            return ', '.join(ids) if len(ids) <= 3 else f'{ids[0]}…{ids[-1]}（{len(ids)} 条）'
        if column == 1:
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"{time_text(row.get('start_ms'))}–{time_text(row.get('end_ms'))}"
            return f"{short_time(row.get('start_ms'))} – {short_time(row.get('end_ms'))}"
        if column == 2:
            status = row.get('status', 'pending')
            if role == Qt.ItemDataRole.ToolTipRole:
                return STATUS_TEXT.get(status, row.get('phase', ''))
            if status in TERMINAL:
                return SHORT_TEXT.get(status, status)
            if status == 'running' or status not in SHORT_TEXT:
                return row.get('phase') or SHORT_TEXT['running']
            return SHORT_TEXT[status]
        if column == 3:
            return str(row.get('attempts', 0))
        error = str(row.get('error', ''))
        if error and (row.get('status') in TODO or role == Qt.ItemDataRole.ToolTipRole):
            return error
        text = str(row.get('input_text', '')).strip().replace('\n', ' / ')
        return text or error or ''


class TaskTable(QTableView):
    """Rows highlight as a whole while hovered; status marks spin while running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1
        self.spin = 0.
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


class TaskRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width(), 38)

    def paint(self, painter, option, index):
        view = self.parent()
        theme, palette = tones()
        status = index.data(TaskTableModel.StatusRole)
        column = index.column()
        cell = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == getattr(view, 'hover_row', -1)
        if selected or hovered:
            from ..design.ui_theme import blend_hex
            fill = theme.accent_soft if selected else blend_hex(theme.surface_elevated, theme.text, .05 if theme.is_light else .08)
            width = view.viewport().width()
            band = QRectF(6, cell.top() + 1, width - 12, cell.height() - 2)
            painter.setClipRect(cell)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(band, 12, 12)
            if selected and column == 0:
                painter.setBrush(QColor(theme.accent))
                painter.drawRoundedRect(QRectF(7, cell.top() + 8, 4, cell.height() - 16), 2, 2)
            painter.setClipping(False)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        font = option.font
        if column == 2:
            solid, soft, ink = palette.get(status, palette['pending'])
            painter.setFont(scaled(font, .93))
            metrics = painter.fontMetrics()
            label = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(cell.width() - 52))
            pill = QRectF(cell.left() + 6, cell.center().y() - 12, metrics.horizontalAdvance(label) + 40, 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(soft)
            painter.drawRoundedRect(pill, 12, 12)
            paint_mark(painter, QRectF(pill.left() + 3, pill.top() + 3, 18, 18), status, getattr(view, 'spin', 0.))
            painter.setPen(ink)
            painter.drawText(pill.adjusted(27, 0, -6, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
            painter.restore()
            return
        color = QColor(theme.text)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        left = 16 if column == 0 else 12
        if column == 1:
            color = QColor(theme.text_muted)
            font = scaled(font, .93)
        elif column == 3:
            attempts = int(text or 0)
            align = Qt.AlignmentFlag.AlignCenter
            left = 0
            text = '–' if attempts == 0 else (f'×{attempts}' if attempts > 1 else '1')
            color = palette['review'][2] if attempts > 1 else QColor(theme.text_muted)
            font = scaled(font, 1.)
            font.setBold(attempts > 1)
        elif column == 4:
            row = index.model().task.rows[index.model().keys[index.row()]]
            error = row.get('error') and status in TODO
            color = palette[status][2] if error and status in {'failed', 'review'} else (
                QColor(theme.text_muted) if error else QColor(theme.text_secondary))
        painter.setFont(font)
        painter.setPen(color)
        rect = cell.adjusted(left, 0, -12 if column != 3 else 0, 0)
        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
        painter.drawText(rect, int(align), text)
        painter.restore()


class SegmentBar(QWidget):
    """The progress bar, split by result; work in flight is striped."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parts = []
        self.active = 0
        self.total = 1
        self.offset = 0
        self.setFixedHeight(14)

    def set_parts(self, parts, active, total):
        state = (tuple(parts), active, total)
        if state != (tuple(self.parts), self.active, self.total):
            self.parts, self.active, self.total = list(parts), active, max(1, total)
            self.update()

    def tick(self):
        if self.active:
            self.offset = (self.offset + 3) % 14
            self.update()

    def paintEvent(self, _event):
        theme, palette = tones()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(theme.input_surface))
        x = rect.left()
        for status, count in self.parts:
            width = rect.width() * count / self.total
            painter.fillRect(QRectF(x, rect.top(), width, rect.height()), palette[status][0])
            x += width
        if self.active:
            width = rect.width() * self.active / self.total
            band = QRectF(x, rect.top(), width, rect.height())
            painter.fillRect(band, palette['running'][1])
            painter.save()
            painter.setClipRect(band)
            pen = QPen(palette['running'][0], 5)
            painter.setPen(pen)
            start = int(band.left()) - 20 + self.offset
            while start < band.right() + 20:
                painter.drawLine(QPointF(start, rect.bottom() + 2), QPointF(start + 16, rect.top() - 2))
                start += 14
            painter.restore()
        painter.setClipping(False)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.end()


def _button(text, name, slot=None):
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        button.clicked.connect(slot)
    return button


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


class SegmentCard(QFrame):
    """One detail card: a title and its lines as rounded chips."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName('taskDetailCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName('taskDetailTitle')
        layout.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('taskSegments')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName('taskSegmentsBody')
        self.lines = QVBoxLayout(body)
        self.lines.setContentsMargins(0, 0, 0, 0)
        self.lines.setSpacing(5)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        self._shown = None

    def set_lines(self, title, lines, empty):
        self.title.setText(title)
        state = (tuple(lines), empty)
        if state == self._shown:
            return
        self._shown = state
        _clear(self.lines)
        for text in lines or [empty]:
            label = QLabel(text)
            label.setObjectName('taskSegment' if lines else 'taskDetailEmpty')
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.lines.addWidget(label)
        self.lines.addStretch(1)


class VoiceComparison(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.peaks = (), ()
        self.hide()

    def set_peaks(self, original=(), enhanced=()):
        peaks = tuple(original), tuple(enhanced)
        self.setVisible(bool(peaks[0] and peaks[1]))
        if self.peaks != peaks:
            self.peaks = peaks
            self.update()

    def paintEvent(self, _event):
        from ..i18n import tr

        painter = QPainter(self)
        label_width = max(painter.fontMetrics().horizontalAdvance(str(tr(label)))
                          for label in ('原音', '增强人声')) + 12
        width = max(1, self.width() - label_width)
        for y, label, color, peaks in (
            (10, '原音', self.palette().mid().color(), self.peaks[0]),
            (31, '增强人声', self.palette().highlight().color(), self.peaks[1]),
        ):
            painter.setPen(self.palette().windowText().color())
            painter.drawText(QRectF(0, y - 10, label_width, 20), Qt.AlignmentFlag.AlignVCenter, str(tr(label)))
            painter.setPen(QPen(color, 1))
            n = max(1, len(peaks))
            for index, peak in enumerate(peaks):
                x = label_width + (index + .5) * width / n
                height = min(1., max(0., float(peak))) * 8
                painter.drawLine(QPointF(x, y - height), QPointF(x, y + height))
        painter.end()


class SubtitleTaskPanel(QDialog):
    locate = Signal(object)
    retry = Signal(object)
    adopt = Signal(object)
    audition = Signal(object)
    preview_dismissed = Signal()
    cancel = Signal(str)
    PILLS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('subtitleTaskPanel')
        self.setModal(False)
        # 2026-11-15 (user): our own round frame instead of the Windows title bar.
        from ..app.candy_chrome import CandyChrome
        self.chrome = CandyChrome(self, "字幕任务进度与结果", "fa5s.tasks")
        self.resize(*CandyChrome.outer_size(1000, 740))
        self.setMinimumSize(*CandyChrome.outer_size(760, 560))
        layout = self.chrome.layout
        layout.setContentsMargins(16, 8, 16, 14)
        layout.setSpacing(10)

        head = QFrame()
        head.setObjectName('taskHead')
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(14, 12, 14, 12)
        head_layout.setSpacing(9)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        top.addLayout(self.pills)
        self.more_tasks = QToolButton()
        self.more_tasks.setObjectName('taskMore')
        self.more_tasks.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_tasks.hide()
        top.addWidget(self.more_tasks)
        top.addStretch(1)
        self.elapsed = QLabel()
        self.elapsed.setObjectName('taskElapsed')
        top.addWidget(self.elapsed)
        head_layout.addLayout(top)
        middle = QHBoxLayout()
        self.phase = QLabel()
        self.phase.setObjectName('taskPhase')
        self.phase.setTextFormat(Qt.TextFormat.RichText)
        middle.addWidget(self.phase, 1)
        self.fraction = QLabel()
        self.fraction.setObjectName('taskFraction')
        middle.addWidget(self.fraction)
        head_layout.addLayout(middle)
        self.bar = SegmentBar()
        head_layout.addWidget(self.bar)
        layout.addWidget(head)
        # Tests and callers read the task line from here.
        self.summary = self.fraction

        from ..design.soft_widgets import WrapLayout
        self.chips = WrapLayout(spacing=7, fill=False)
        layout.addLayout(self.chips)
        self.causes = QHBoxLayout()
        self.causes.setSpacing(8)
        layout.addLayout(self.causes)

        table_card = QFrame()
        table_card.setObjectName('taskTableCard')
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 2, 0, 4)
        self.table = TaskTable()
        self.table.setObjectName('taskTable')
        self.table_model = TaskTableModel(self.table)
        self.table.setModel(self.table_model)
        self.table.setItemDelegate(TaskRowDelegate(self.table))
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
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((176, 196, 176, 52)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().selectionChanged.connect(self._show_details)
        self.table.doubleClicked.connect(lambda *_: self._locate())
        table_layout.addWidget(self.table)
        layout.addWidget(table_card, 1)

        self.detail = QStackedWidget()
        self.detail.setFixedHeight(172)
        placeholder = QLabel('点上面的一行，这里会并排显示原文、模型分段和实际写回')
        placeholder.setObjectName('taskPlaceholder')
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.addWidget(placeholder)
        compare = QWidget()
        grid = QGridLayout(compare)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.input_card = SegmentCard('原文')
        self.validated_card = SegmentCard('模型分段（已校验）')
        self.final_card = SegmentCard('实际写回')
        self.raw_toggle = _button('完整处理记录（含模型原始响应）›', 'taskRawToggle', lambda: self.detail.setCurrentIndex(2))
        self.final_card.layout().addWidget(self.raw_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        for column, card in enumerate((self.input_card, self.validated_card, self.final_card)):
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)
        self.next_strip = QFrame()
        self.next_strip.setObjectName('taskNext')
        next_layout = QHBoxLayout(self.next_strip)
        next_layout.setContentsMargins(12, 7, 12, 7)
        next_layout.setSpacing(10)
        self.next_lead = QLabel()
        self.next_lead.setObjectName('taskNextLead')
        self.next_text = QLabel()
        self.next_text.setObjectName('taskNextText')
        self.next_text.setWordWrap(True)
        next_layout.addWidget(self.next_lead)
        next_layout.addWidget(self.next_text, 1)
        grid.addWidget(self.next_strip, 1, 0, 1, 3)
        grid.setRowStretch(0, 1)
        self.detail.addWidget(compare)
        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        raw_layout.setSpacing(4)
        raw_layout.addWidget(_button('‹ 返回对照', 'taskRawToggle', lambda: self.detail.setCurrentIndex(1)),
                             0, Qt.AlignmentFlag.AlignLeft)
        self.details = QPlainTextEdit()
        self.details.setObjectName('taskRaw')
        self.details.setReadOnly(True)
        raw_layout.addWidget(self.details, 1)
        self.detail.addWidget(raw_page)
        layout.addWidget(self.detail)
        self.voice_comparison = VoiceComparison(self)
        layout.addWidget(self.voice_comparison)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.locate_button = _button('定位试听', 'taskAction', self._locate)
        self.locate_button.setToolTip('选中原字幕并把播放头移到这段开头')
        actions.addWidget(self.locate_button)
        self.retry_button = _button('重试这一段', 'taskAction', self._retry)
        actions.addWidget(self.retry_button)
        self.adopt_button = _button('采用建议', 'taskAction', self._adopt)
        self.adopt_button.hide()
        actions.addWidget(self.adopt_button)
        self.listen_original = _button('听原音', 'taskAction', lambda: self._audition(False))
        self.listen_enhanced = _button('听增强人声', 'taskAction', lambda: self._audition(True))
        for button in (self.listen_original, self.listen_enhanced):
            button.hide()
            actions.addWidget(button)
        self.retry_why = QLabel()
        self.retry_why.setObjectName('taskWhy')
        actions.addWidget(self.retry_why)
        actions.addStretch(1)
        self.cancel_button = _button('取消任务', 'taskDanger',
                                     lambda: self.cancel.emit(self.current.task_id) if self.current else None)
        actions.addWidget(self.cancel_button)
        self.collapse_button = _button('收起，继续运行', 'taskPrimary', self.hide)
        actions.addWidget(self.collapse_button)
        layout.addLayout(actions)

        self._models = {}
        self._order = []
        self.current = None
        self.filter = None
        self._row_keys = []
        self._row_indexes = {}
        self._painted_revision = -1
        self._pill_state = self._chip_state = self._cause_state = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._spinner = QTimer(self)
        self._spinner.setInterval(90)
        self._spinner.timeout.connect(self._spin)

    # ── tasks ──
    def add_task(self, task):
        self._models[task.task_id] = task
        self._order.append(task.task_id)
        self._pick(task.task_id)

    def _pick(self, task_id):
        if self.current is not None and self.current.task_id == task_id:
            self._pill_state = None
            self._paint_pills()
            return
        self.current = self._models.get(task_id)
        self.filter = None
        self.table_model.set_task(self.current)
        self._row_keys = self.table_model.keys
        self._row_indexes = self.table_model.indexes
        self._painted_revision = -1
        self._pill_state = self._chip_state = self._cause_state = None
        self.details.clear()
        self.detail.setCurrentIndex(0)
        self.refresh()

    def _task_state(self, task):
        if task.ended is None:
            return 'running'
        counts = task.counts()
        if counts['failed']:
            return 'failed'
        if counts['review']:
            return 'review'
        return 'cancelled' if task.cancelled else 'applied'

    def _task_label(self, task):
        same = [key for key in self._order if self._models[key].kind == task.kind]
        return task.kind if len(same) < 2 else f'{task.kind} · {same.index(task.task_id) + 1}'

    def _paint_pills(self):
        theme = _theme()
        recent = self._order[-self.PILLS:]
        if self.current is not None and self.current.task_id not in recent:
            recent = recent[1:] + [self.current.task_id]
        state = (theme.key, tuple((key, self._task_state(self._models[key]), self.current is self._models[key])
                                  for key in self._order))
        if state == self._pill_state:
            return
        self._pill_state = state
        _clear(self.pills)
        for key in recent:
            task = self._models[key]
            status = self._task_state(task)
            pill = _button(self._task_label(task), 'taskPill', lambda _=False, key=key: self._pick(key))
            pill.setCheckable(True)
            pill.setChecked(task is self.current)
            pill.setProperty('status', status)
            pill.setIcon(mark_icon(status, 16))
            pill.setIconSize(QSize(16, 16))
            self.pills.addWidget(pill)
        older = [key for key in self._order if key not in recent]
        self.more_tasks.setVisible(bool(older))
        if older:
            self.more_tasks.setText(f'更早 {len(older)} 项')
            menu = QMenu(self.more_tasks)
            for key in reversed(older):
                task = self._models[key]
                action = menu.addAction(mark_icon(self._task_state(task), 16), self._task_label(task))
                action.triggered.connect(lambda _=False, key=key: self._pick(key))
            self.more_tasks.setMenu(menu)

    # ── counts and filters ──
    def _counts(self, task):
        counts = task.counts()
        counts['active'] = max(0, counts['total'] - sum(counts[key] for key in TERMINAL))
        counts['todo'] = sum(counts[key] for key in TODO)
        return counts

    def _set_filter(self, value):
        self.filter = None if value == self.filter else value
        self._chip_state = self._cause_state = None
        self.refresh(force=True)

    def _paint_chips(self, task, counts):
        theme = _theme()
        state = (theme.key, self.filter, task.ended is None, tuple(counts[key] for key in CHIP_ORDER + ('active', 'todo', 'total')))
        if state == self._chip_state:
            return
        self._chip_state = state
        _clear(self.chips)

        def chip(text, value, status, icon=True):
            button = _button(text, 'taskChip', lambda _=False: self._set_filter(value))
            button.setCheckable(True)
            button.setChecked(self.filter == value)
            button.setProperty('status', status)
            if icon:
                button.setIcon(mark_icon(status, 20))
                button.setIconSize(QSize(20, 20))
            else:
                button.setProperty('plain', True)
            self.chips.addWidget(button)
            return button

        chip(f"全部 {counts['total']}", None, 'all', icon=False).setChecked(self.filter is None)
        if task.ended is None and counts['active']:
            chip(f"进行中 {counts['active']}", 'active', 'running')
        for key in CHIP_ORDER:
            if counts[key]:
                chip(f'{SHORT_TEXT[key]} {counts[key]}', key, key).setToolTip(STATUS_TEXT[key])
        if counts['todo']:
            todo = chip(f"只看要处理的 {counts['todo']}", 'todo', 'failed', icon=False)
            todo.setToolTip('失败、需检查和取消的范围')

    def _paint_causes(self, task):
        causes = Counter()
        kinds = {}
        for row in task.rows.values():
            if row.get('status') in {'failed', 'review'} and row.get('error'):
                reason = str(row['error'])
                causes[reason] += len(row.get('cue_ids', ()))
                kinds.setdefault(reason, row['status'])
        top = causes.most_common(2)
        state = (_theme().key, self.filter, tuple(top))
        if state == self._cause_state:
            return
        self._cause_state = state
        _clear(self.causes)
        from ..design.elided_label import ElidedLabel
        for reason, count in top:
            card = QFrame()
            card.setObjectName('taskCause')
            card.setProperty('status', kinds[reason])
            row = QHBoxLayout(card)
            row.setContentsMargins(10, 5, 6, 5)
            row.setSpacing(8)
            mark = QLabel()
            mark.setPixmap(mark_icon(kinds[reason], 18).pixmap(18, 18))
            row.addWidget(mark)
            number = QLabel(f'{count} 条')
            number.setObjectName('taskCauseCount')
            row.addWidget(number)
            text = ElidedLabel(reason, mode=Qt.TextElideMode.ElideRight)
            text.setObjectName('taskCauseText')
            row.addWidget(text, 1)
            value = ('cause', reason)
            button = _button('看全部' if self.filter == value else '只看这些', 'taskCauseFilter',
                             lambda _=False, value=value: self._set_filter(value))
            row.addWidget(button)
            self.causes.addWidget(card, 1)

    def _matches(self, row):
        value = self.filter
        status = row.get('status')
        if value is None:
            return True
        if value == 'active':
            return status not in TERMINAL
        if value == 'todo':
            return status in TODO
        if isinstance(value, tuple):
            return status in {'failed', 'review'} and str(row.get('error', '')) == value[1]
        return status == value

    # ── refresh ──
    def selected_record(self):
        index = self.table.currentIndex().row()
        if self.current and 0 <= index < len(self._row_keys) and not self.table.isRowHidden(index):
            return self.current.rows[self._row_keys[index]]
        return None

    def refresh(self, force=False):
        task = self.current
        if not task or not self.isVisible():
            return
        counts = self._counts(task)
        theme = _theme()
        self._paint_pills()
        elapsed = ('用时 ' if task.ended else '已用 ') + elapsed_text(task.elapsed)
        if self.elapsed.text() != elapsed:
            self.elapsed.setText(elapsed)
        phase = (f'<span style="color:{theme.accent_text}">{html.escape(task.kind)}</span>'
                 f'&nbsp;·&nbsp;{html.escape(task.headline(counts))}')
        if self.phase.text() != phase:
            self.phase.setText(phase)
        fraction = f"{counts['processed']}/{counts['total']} {task.unit_label}"
        if self.fraction.text() != fraction:
            self.fraction.setText(fraction)
            self.fraction.setToolTip(task.summary())
        active = sum(len(row.get('cue_ids', ())) for row in task.rows.values()
                     if row.get('status') not in TERMINAL) if task.ended is None else 0
        self.bar.set_parts([(key, counts[key]) for key in CHIP_ORDER if counts[key]],
                           min(active, counts['active']), counts['total'])
        self._paint_chips(task, counts)
        self._paint_causes(task)
        running = task.ended is None
        self.cancel_button.setEnabled(running and not task.cancelled)
        self.cancel_button.setText('取消任务' if running else ('已取消' if task.cancelled else '已结束'))
        self.collapse_button.setText('收起，继续运行' if running else '关闭')
        if running and not self._spinner.isActive():
            self._spinner.start()
        elif not running and self._spinner.isActive():
            self._spinner.stop()
        if self._painted_revision == task.revision and not force:
            self._update_actions()
            return
        self._painted_revision = task.revision
        self.table_model.sync()
        self._filter_rows()
        self._show_details()

    def _spin(self):
        self.table.spin = (self.table.spin + 30) % 360
        self.bar.tick()
        self.table.viewport().update()

    def _filter_rows(self):
        if self.current:
            for key, index in self._row_indexes.items():
                hidden = not self._matches(self.current.rows[key])
                if hidden != self.table.isRowHidden(index):
                    self.table.setRowHidden(index, hidden)

    def _retry_reason(self, row):
        if row is None:
            return ''
        status = row.get('status')
        if status not in TODO:
            if status == 'suggestion':
                return '这段有建议待采用，不用重试'
            return '这段已经好了，不用重试' if status in TERMINAL else '这段还在处理'
        if self.current.ended is None:
            return '任务结束后才能重试'
        return ''

    def _update_actions(self):
        row = self.selected_record()
        reason = self._retry_reason(row)
        self.locate_button.setEnabled(row is not None)
        self.retry_button.setEnabled(row is not None and not reason)
        self.adopt_button.setVisible(bool(self.current and self.current.kind == '批量重新识别'
                                          and row and row.get('status') == 'suggestion'))
        compare_audio = bool(row and row.get('audio_preview'))
        self.listen_original.setVisible(compare_audio)
        self.listen_enhanced.setVisible(compare_audio)
        if self.retry_why.text() != reason:
            self.retry_why.setText(reason)

    def _show_details(self, *_):
        row = self.selected_record()
        self._update_actions()
        if row is None:
            self.voice_comparison.set_peaks()
            self.detail.setCurrentIndex(0)
            return
        if self.detail.currentIndex() == 0:
            self.detail.setCurrentIndex(1)
        status = row_status(row)
        label = self.table_model.data(self.table_model.index(self.table.currentIndex().row(), 0))
        inputs = [line for line in str(row.get('input_text', '')).split('\n') if line.strip()]
        validated = [str(text) for text in row.get('validated_texts', ()) if str(text).strip()]
        final = [str(text) for text in row.get('final_texts', ()) if str(text).strip()]
        kept = status in {'failed', 'cancelled'}
        self.input_card.set_lines(f'原文 · {label}', inputs, '没有记录原文')
        label = ('重新识别 · 增强人声' if row.get('audio_source') == 'htdemucs'
                 else '重新识别 · 原音' if row.get('audio_source') == 'original' else '模型分段（已校验）')
        if row.get('separation_backend') in {'cpu', 'cuda'}:
            label += ' · ' + row['separation_backend'].upper()
        self.validated_card.set_lines(label, validated,
                                      '没有通过校验的分段' if status in TERMINAL else '还没有结果')
        self.voice_comparison.set_peaks(row.get('original_peaks', ()), row.get('enhanced_peaks', ()))
        self.final_card.set_lines('实际写回 · 保留原文' if kept else '实际写回', final or (inputs if kept else []),
                                  '还没写回' if status not in TERMINAL else '没有写回内容')
        lead, text = NEXT_STEP.get(status, NEXT_STEP['pending'])
        retry = '可以单独重试这段。' if self.current.ended else '等任务结束后可以单独重试这段。'
        text = text.format(retry=retry, attempts=row.get('attempts', 1) or 1)
        error = str(row.get('error') or '')
        if error and status in TODO:
            text = f'{error}。{text}'
        for stage, activity in (row.get('activity') or {}).items():
            if not stage.startswith('escalation:') or activity.get('state') != 'completed':
                continue
            label = '校对' if activity.get('stage') == 'polished' else '断句'
            text += (f" {label}提高思考等级重试（{activity.get('thinking', '')}）："
                     f"救回 {int(activity.get('succeeded_cues') or 0)} 条，"
                     f"仍失败 {int(activity.get('failed_cues') or 0)} 条。")
        self.next_lead.setText(lead)
        self.next_text.setText(text)
        if self.next_strip.property('status') != status:
            self.next_strip.setProperty('status', status)
            _repolish(self.next_strip)
            for child in self.next_strip.findChildren(QLabel):
                _repolish(child)
        raw = json.dumps(row, ensure_ascii=False, indent=2, default=str)
        if raw != self.details.toPlainText():
            self.details.setPlainText(raw)

    def _locate(self):
        row = self.selected_record()
        if row:
            self.locate.emit(dict(task_id=self.current.task_id, record=row))

    def _retry(self):
        row = self.selected_record()
        if row and row.get('status') in TODO and self.current.ended:
            self.retry.emit(dict(task_id=self.current.task_id, record=row))

    def _adopt(self):
        row = self.selected_record()
        if row and self.current.kind == '批量重新识别' and row.get('status') == 'suggestion':
            self.adopt.emit(dict(task_id=self.current.task_id, record=row))

    def _audition(self, enhanced):
        row = self.selected_record()
        if self.current and row and row.get('audio_preview'):
            self.audition.emit(dict(task_id=self.current.task_id, record=row, enhanced=enhanced))

    def hideEvent(self, event):
        self.preview_dismissed.emit()
        super().hideEvent(event)
