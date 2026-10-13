"""Merge-tool preview on the subtitle timeline (replaces the 2026-09 card).

The result is drawn where it will be: one dashed "after merge" block over
both cues and the gap between them, the joined text centred with a join mark,
a span bar on the ruler and a fixed status in the ruler's header cell. Like
the razor preview it never covers the waveform, never edits the project and
only repaints its own region.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QRegion

from .i18n import tr
from .timeline_razor import PILL_HEIGHT, PILL_TOP, _block_rect, _clock, razor_colors, paint_split_text, split_text_layout


@dataclass(frozen=True)
class MergeState:
    kind: str                 # 'anchor' | 'drag' | 'pair'
    anchor: object            # StudioCue
    other: object | None      # StudioCue the anchor merges with
    direction: int = 0        # -1 / +1 while dragging

    @property
    def ordered(self):
        if self.other is None:
            return self.anchor, None
        a, b = self.anchor, self.other
        return (a, b) if (a.start_ms, a.end_ms, a.id) <= (b.start_ms, b.end_ms, b.id) else (b, a)

    @property
    def span(self) -> tuple[int, int]:
        cues = [c for c in (self.anchor, self.other) if c is not None]
        return min(c.start_ms for c in cues), max(c.end_ms for c in cues)


def _rows(timeline, state) -> list[QRectF]:
    speakers = timeline._track_layout()[0]
    ids = {c.speaker_id for c in (state.anchor, state.other) if c is not None}
    return [speakers[s] for s in ids if s in speakers]


def region(timeline, state) -> QRegion:
    if state is None:
        return QRegion()
    left = timeline.TRACK_HEADER_WIDTH
    width = timeline._content_right() - left
    result = QRegion(QRect(0, 0, timeline.TRACK_HEADER_WIDTH, timeline.RULER_HEIGHT))
    result |= QRegion(QRect(left, 0, width, timeline.RULER_HEIGHT))
    for row in _rows(timeline, state):
        result |= QRegion(QRectF(left, row.top(), width, row.height()).toAlignedRect())
    return result.intersected(QRegion(timeline.rect()))


def _ghost_rect(timeline, state) -> QRectF | None:
    first, _second = state.ordered
    track = timeline._track_layout()[0].get(first.speaker_id)
    if track is None:
        return None
    track = timeline._cue_band(first, track)
    start, end = state.span
    left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(start))
    right = min(timeline._content_right(), timeline._time_to_x(end))
    if right - left < 2:
        return None
    return QRectF(left, track.top() + 5, right - left, track.height() - 10)


def status_lines(state) -> tuple[str, str, str]:
    first, second = state.ordered
    if state.other is None:
        if state.kind == 'drag':
            return tr('该方向没有可以合并的字幕'), '', ''
        return tr('已选锚点：拖动或点另一条字幕'), '', ''
    if state.kind == 'drag':
        line = tr('向后合并（与下一条）· 松开执行') if state.direction > 0 else tr('向前合并（与上一条）· 松开执行')
    else:
        line = tr('点击即与锚点合并')
    if first.speaker_id != second.speaker_id:
        line = tr('跨轨合并：结果放在前一条的轨道') + ' · ' + line
    return line, first.text.rstrip(), second.text.lstrip()


def paint(timeline, painter: QPainter, palette, state) -> None:
    if state is None:
        return
    colors = razor_colors(palette)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    content = QRectF(timeline.TRACK_HEADER_WIDTH, 0,
                     timeline._content_right() - timeline.TRACK_HEADER_WIDTH, timeline._canvas_bottom())
    painter.setClipRect(content)
    if state.other is None:
        block = _block_rect(timeline, state.anchor)
        if block is not None:
            painter.setPen(QPen(colors['muted' if state.kind == 'drag' else 'cut'], 2.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(block.adjusted(-2, -2, 2, 2), 6, 6)
    else:
        _paint_ghost(timeline, painter, palette, colors, state)
        _paint_ruler(timeline, painter, colors, state)
    painter.restore()
    _paint_header(timeline, painter, palette, colors, state)


def _paint_ghost(timeline, painter, palette, colors, state) -> None:
    from .studio_cue_table import _speaker_color
    first, second = state.ordered
    ghost = _ghost_rect(timeline, state)
    if ghost is None:
        return
    if first.speaker_id != second.speaker_id:
        other = _block_rect(timeline, second)
        if other is not None:
            painter.setPen(QPen(colors['cut'], 2.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(other.adjusted(-2, -2, 2, 2), 6, 6)
    speaker = _speaker_color(timeline.project, first.speaker_id, palette)
    fill = QColor(palette.clip_fill(speaker, True))
    fill.setAlpha(255)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(ghost, 6, 6)
    gap_start, gap_end = (first.end_ms, second.start_ms) if first.speaker_id == second.speaker_id else (0, 0)
    if gap_end > gap_start:
        # The silence between them becomes part of the merged caption.
        left = max(ghost.left(), timeline._time_to_x(gap_start))
        right = min(ghost.right(), timeline._time_to_x(gap_end))
        if right > left:
            hatch = QColor(colors['cut'])
            hatch.setAlpha(70)
            painter.setBrush(QBrush(hatch, Qt.BrushStyle.BDiagPattern))
            painter.drawRect(QRectF(left, ghost.top() + 2, right - left, ghost.height() - 4))
    painter.setPen(QPen(colors['cut'], 2.2, Qt.PenStyle.DashLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(ghost, 6, 6)
    font = timeline._timeline_text_font(round(ghost.height() + 10), ghost.width())
    paint_split_text(painter, ghost.adjusted(10, 2, -10, -2), font, first.text.rstrip(), second.text.lstrip(),
                     QColor(palette.clip_text), colors['left'], colors['right'], colors['cut'], marker='join')


def _paint_ruler(timeline, painter, colors, state) -> None:
    start, end = state.span
    left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(start))
    right = min(timeline._content_right(), timeline._time_to_x(end))
    if right <= left:
        return
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colors['cut'])
    painter.drawRoundedRect(QRectF(left, timeline.RULER_HEIGHT - 5, right - left, 4), 2, 2)
    label = tr('合并后 {seconds}s', seconds=f'{(end - start) / 1000:.1f}')
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    width = QFontMetrics(font).horizontalAdvance(label) + 18
    lo = timeline.TRACK_HEADER_WIDTH + 2
    hi = max(lo, timeline._content_right() - width - 2)
    pill_left = min(hi, max(lo, (left + right) / 2 - width / 2))
    playhead = timeline._time_to_x(timeline.playhead_ms)
    if pill_left < playhead + 43 and pill_left + width > playhead - 43:
        pill_left = min(hi, max(lo, playhead + 45 if (left + right) / 2 >= playhead else playhead - 45 - width))
    pill = QRectF(pill_left, PILL_TOP, width, PILL_HEIGHT)
    painter.drawRoundedRect(pill, 4, 4)
    painter.setFont(font)
    painter.setPen(colors['ink'])
    painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)


def _paint_header(timeline, painter, palette, colors, state) -> None:
    cell = QRectF(0, 0, timeline.TRACK_HEADER_WIDTH, timeline.RULER_HEIGHT)
    line, left_text, right_text = status_lines(state)
    blocked = state.other is None and state.kind == 'drag'
    painter.save()
    painter.setClipRect(cell)
    painter.fillRect(cell, QColor(palette.header))
    painter.setPen(QPen(colors['muted' if blocked else 'cut'], 2))
    painter.drawLine(QPointF(cell.left() + 4, cell.bottom() - 1), QPointF(cell.right() - 4, cell.bottom() - 1))
    font = QFont()
    font.setPointSize(9)
    metrics = QFontMetrics(font)
    painter.setFont(font)
    height = max(12.0, (cell.height() - 3) / 2)
    first = QRectF(cell.left() + 8, cell.top() + 1, cell.width() - 14, height)
    painter.setPen(colors['warn'] if blocked else QColor(palette.time_label))
    flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
    painter.drawText(first, flags, metrics.elidedText(line, Qt.TextElideMode.ElideRight, int(first.width())))
    if left_text or right_text:
        second = QRectF(first.left(), first.bottom(), first.width(), height)
        paint_split_text(painter, second, font, left_text, right_text, QColor(palette.clip_text),
                         colors['left'], colors['right'], colors['cut'], marker='join', underline=False)
    elif state.anchor is not None:
        second = QRectF(first.left(), first.bottom(), first.width(), height)
        painter.setPen(QColor(palette.clip_text))
        painter.drawText(second, flags, metrics.elidedText(state.anchor.text, Qt.TextElideMode.ElideRight,
                                                         int(second.width())))
    painter.restore()
