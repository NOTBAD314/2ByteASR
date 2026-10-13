"""Razor preview on the subtitle timeline: resolve, invalidate and paint.

The preview is drawn where the result will be: inside the target cue block
(the text that stays left of the cut, the text that starts after it, and a
lane of measured words), a thin cut line through the ruler, tracks and
waveform, a cut-time pill on the ruler and a fixed two-line status in the
ruler's header cell. Nothing covers the waveform, and nothing here edits the
project: the timeline only repaints the previous and current preview region.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRegion

from .studio_project import StudioCue
from .studio_timing import SplitBlocked, SplitPreview, describe_split, word_boundary_times
from .i18n import tr

PILL_HEIGHT = 23
PILL_TOP = 4
LANE_HEIGHT = 16


@dataclass(frozen=True)
class RazorResolution:
    cue: StudioCue
    pointer_ms: int
    split_ms: int
    snap: str          # '' | 'word' | 'playhead' | 'edge'
    result: object     # SplitPreview | SplitBlocked
    words: tuple
    reason: str
    locked: bool = False

    @property
    def preview(self) -> SplitPreview | None:
        return self.result if isinstance(self.result, SplitPreview) and not self.locked else None


def razor_colors(palette) -> dict[str, QColor]:
    """Cut / side colours that differ from every playhead and clip hue."""
    if palette.dark:
        values = dict(cut='#FFD04D', left='#F3EFE7', right='#4FD3E6', ink='#141118',
                      warn='#FFB35C', muted='#9C96A3')
    else:
        values = dict(cut='#1D5FD1', left='#3B3631', right='#0D8797', ink='#FFFFFF',
                      warn='#A9500A', muted='#8B847B')
    return {key: QColor(value) for key, value in values.items()}


def resolve(timeline, cue: StudioCue, pointer_ms: int, *, bypass_snap: bool = False) -> RazorResolution:
    words, reason = timeline._razor_alignment(cue)
    split, snap = int(pointer_ms), ''
    if timeline.snap_enabled and not bypass_snap:
        content_width = max(1, timeline._content_right() - timeline.TRACK_HEADER_WIDTH)
        threshold = 8.0 * timeline.visible_duration_ms / content_width
        best = None
        standard = timeline._snap_time(split, cue.id)
        if standard != split:
            best = (abs(standard - split), 1, standard,
                    'playhead' if standard == int(timeline.playhead_ms) else 'edge')
        for value, _index in word_boundary_times(words):
            distance = abs(value - split)
            if cue.start_ms < value < cue.end_ms and distance <= threshold:
                candidate = (distance, 0, value, 'word')
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
        if best is not None:
            split, snap = best[2], best[3]
    result = describe_split(cue, split, project=timeline.project, alignment=(words, reason))
    return RazorResolution(cue, int(pointer_ms), int(result.split_ms), snap, result, tuple(words), reason,
                           cue.speaker_id in timeline.locked_speakers)


def _block_rect(timeline, cue) -> QRectF | None:
    track = timeline._track_layout()[0].get(cue.speaker_id)
    if track is None:
        return None
    track = timeline._cue_band(cue, track)  # its sub-lane on the shared secondary row
    left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(cue.start_ms))
    right = min(timeline._content_right(), timeline._time_to_x(cue.end_ms))
    if right - left < 2:
        return None
    return QRectF(left, track.top() + 7, max(4.0, right - left), track.height() - 14)


ICON = 14


def _pill(timeline, resolution) -> tuple[QRectF, str]:
    label = _clock(resolution.split_ms)
    if resolution.snap == 'word':
        label += ' · ' + tr('吸附字界')
    elif resolution.snap:
        label += ' · ' + tr('吸附')
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    width = QFontMetrics(font).horizontalAdvance(label) + 24 + ICON
    x = timeline._time_to_x(resolution.split_ms)
    lo = timeline.TRACK_HEADER_WIDTH + 2
    hi = max(lo, timeline._content_right() - width - 2)
    left = min(hi, max(lo, x - width / 2))
    playhead = timeline._time_to_x(timeline.playhead_ms)
    # The playhead pill (82px, centred) is painted above: sit beside it.
    if left < playhead + 43 and left + width > playhead - 43:
        left = playhead + 45 if x >= playhead else playhead - 45 - width
        left = min(hi, max(lo, left))
    return QRectF(left, PILL_TOP, width, PILL_HEIGHT), label


def _clock(milliseconds: int) -> str:
    from .studio_helpers import _format_ms
    return _format_ms(int(milliseconds))


def region(timeline, resolution) -> QRegion:
    if resolution is None:
        return QRegion()
    x = round(timeline._time_to_x(resolution.split_ms))
    result = QRegion(QRect(x - 5, 0, 11, round(timeline._canvas_bottom()) + 2))
    result |= QRegion(_pill(timeline, resolution)[0].adjusted(-2, -2, 2, 2).toAlignedRect())
    result |= QRegion(QRect(0, 0, timeline.TRACK_HEADER_WIDTH, timeline.RULER_HEIGHT))
    block = _block_rect(timeline, resolution.cue)
    if block is not None:
        result |= QRegion(block.adjusted(-4, -4, 4, 4).toAlignedRect())
    return result.intersected(QRegion(timeline.rect()))


def status_lines(resolution) -> tuple[str, str, str]:
    """(state, left context, right context) for the fixed header cell."""
    result = resolution.result
    if resolution.locked:
        return tr('轨道已锁定，不能切分'), '', ''
    if isinstance(result, SplitBlocked):
        state = {
            'before_first_word': tr('首字发音之前：前段没有文字'),
            'after_last_word_onset': tr('末字已开始发音：后段没有文字'),
        }.get(result.reason, tr('这条字幕太短，不能在此切分'))
        return state, '', ''
    if not result.measured:
        state = tr('缺少字级对齐 · 文字分界为估算')
    elif result.straddled is not None:
        heard = resolution.cue.text[result.straddled.char_start:result.straddled.char_end]
        state = tr('切在「{word}」发音中，该字归前段', word=heard)
    elif result.timing_source == 'derived_term_source_span':
        state = tr('字级时间 · 替换词按原读音整体')
    else:
        state = tr('字级时间')
    return state, result.left_text.rstrip(), result.right_text.lstrip()


def paint(timeline, painter: QPainter, palette, resolution) -> None:
    if resolution is None:
        return
    colors = razor_colors(palette)
    blocked = resolution.preview is None
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_block(timeline, painter, palette, colors, resolution)
    _paint_cut(timeline, painter, palette, colors, resolution, blocked)
    _paint_header(timeline, painter, palette, colors, resolution, blocked)
    painter.restore()


def _paint_block(timeline, painter, palette, colors, resolution) -> None:
    from .studio_cue_table import _speaker_color
    cue = resolution.cue
    block = _block_rect(timeline, cue)
    if block is None:
        return
    content = QRectF(timeline.TRACK_HEADER_WIDTH, 0,
                     timeline._content_right() - timeline.TRACK_HEADER_WIDTH, timeline._canvas_bottom())
    painter.save()
    painter.setClipRect(block.adjusted(-3, -3, 3, 3).intersected(content))
    speaker = _speaker_color(timeline.project, cue.speaker_id, palette)
    selected = cue.id == timeline.selected_id
    painter.setPen(QPen(QColor(palette.clip_selected_border) if selected else palette.clip_border(speaker),
                        2.0 if selected else 1.2))
    painter.setBrush(palette.clip_fill(speaker, selected))
    painter.drawRoundedRect(block, 5, 5)
    lane_height = LANE_HEIGHT if block.height() >= 46 else 0
    text_rect = block.adjusted(10, 3, -8, -(lane_height + 4))
    font = timeline._timeline_text_font(round(block.height() + 14), block.width())
    metrics = QFontMetrics(font)
    painter.setFont(font)
    result = resolution.result
    if isinstance(result, SplitPreview) and not resolution.locked:
        # The big text stays centred and readable wherever the pointer is;
        # only the marker between the two parts moves (by character). The
        # lane below carries the real word times.
        paint_split_text(painter, text_rect, font, result.left_text.rstrip(), result.right_text.lstrip(),
                         QColor(palette.clip_text), colors['left'], colors['right'],
                         colors['cut'] if result.measured else colors['warn'], dashed=not result.measured)
    else:
        muted = QColor(palette.clip_text)
        muted.setAlpha(150)
        painter.setPen(muted)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
                         metrics.elidedText(cue.text, Qt.TextElideMode.ElideRight, int(max(8, text_rect.width()))))
    if lane_height:
        lane = QRectF(block.left() + 4, block.bottom() - lane_height - 3, block.width() - 8, lane_height)
        _paint_lane(timeline, painter, palette, colors, resolution, lane)
    painter.restore()


MARKER_GAP = 14


def split_text_layout(metrics, left_text, right_text, width):
    """Centred labels for two text parts around one marker gap.

    Far ends are elided first; the characters next to the marker stay.
    Returns ``(left_label, right_label, total_width)``.
    """
    room = max(0.0, width - MARKER_GAP)
    left_w, right_w = metrics.horizontalAdvance(left_text), metrics.horizontalAdvance(right_text)
    if left_w + right_w > room:
        half = room / 2
        if left_w <= half:
            right_room, left_room = room - left_w, left_w
        elif right_w <= half:
            left_room, right_room = room - right_w, right_w
        else:
            left_room = right_room = half
        left_text = _fit(metrics, left_text, left_room, Qt.TextElideMode.ElideLeft)
        right_text = _fit(metrics, right_text, right_room, Qt.TextElideMode.ElideRight)
    total = metrics.horizontalAdvance(left_text) + MARKER_GAP + metrics.horizontalAdvance(right_text)
    return left_text, right_text, total


def paint_split_text(painter, rect, font, left_text, right_text, ink, left_color, right_color,
                     marker_color, *, dashed=False, marker='bar', underline=True):
    """One centred line: left part, a marker, right part.

    ``marker='bar'`` is the razor's text boundary; ``'join'`` is the merge
    tool's join mark. Underlines tell the two parts apart without relying on
    two similar fill colours.
    """
    metrics = QFontMetrics(font)
    left_label, right_label, total = split_text_layout(metrics, left_text, right_text, rect.width())
    x = rect.center().x() - total / 2
    flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
    painter.save()
    painter.setFont(font)
    painter.setPen(ink)
    left_w = metrics.horizontalAdvance(left_label)
    left_area = QRectF(x, rect.top(), left_w + 1, rect.height())
    painter.drawText(left_area, flags | Qt.AlignmentFlag.AlignLeft, left_label)
    right_area = QRectF(x + left_w + MARKER_GAP, rect.top(), metrics.horizontalAdvance(right_label) + 1, rect.height())
    painter.setPen(ink)
    painter.drawText(right_area, flags | Qt.AlignmentFlag.AlignLeft, right_label)
    if underline:
        _underline(painter, left_area, metrics, left_label, left_color, right=False)
        _underline(painter, right_area, metrics, right_label, right_color, right=False)
    mx = round(x + left_w + MARKER_GAP / 2) + 0.5
    cy = rect.center().y()
    if marker == 'join':
        radius = max(4.0, min(7.0, metrics.ascent() / 3))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(marker_color)
        painter.drawEllipse(QPointF(mx, cy), radius, radius)
        painter.setPen(QPen(QColor('#141118'), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arm = radius * 0.55
        painter.drawLine(QPointF(mx - arm, cy), QPointF(mx + arm, cy))
        painter.drawLine(QPointF(mx, cy - arm), QPointF(mx, cy + arm))
    else:
        top = cy - metrics.ascent() / 2 - 3
        bottom = cy + metrics.ascent() / 2 + 6
        painter.setPen(QPen(marker_color, 2.5, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(mx, top), QPointF(mx, bottom))
    painter.restore()
    return QRectF(x, rect.top(), total, rect.height())


def _fit(metrics, text, room, mode):
    """Elide away from the cut; a bare ellipsis gives way to the boundary character."""
    label = metrics.elidedText(text, mode, int(room))
    if label.strip('…') or not text:
        return label
    edge = text[-1] if mode == Qt.TextElideMode.ElideLeft else text[0]
    return edge if metrics.horizontalAdvance(edge) <= room else ''


def _underline(painter, area, metrics, label, color, *, right):
    if not label:
        return
    width = min(area.width(), metrics.horizontalAdvance(label))
    left = area.right() - width if right else area.left()
    y = area.center().y() + metrics.ascent() / 2 + 4
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(left, y, width, 2.5), 1.2, 1.2)
    painter.restore()


def _paint_lane(timeline, painter, palette, colors, resolution, lane) -> None:
    painter.save()
    painter.setClipRect(lane.adjusted(0, -6, 0, 0), Qt.ClipOperation.IntersectClip)
    small = QFont()
    small.setPointSize(8)
    painter.setFont(small)
    metrics = QFontMetrics(small)
    cue = resolution.cue
    result = resolution.result
    if not resolution.words:
        painter.setPen(colors['warn'])
        painter.drawText(lane, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(tr('此段缺少有效字级对齐 · 文字分界为估算，切后请试听'),
                                            Qt.TextElideMode.ElideRight, int(lane.width())))
        painter.restore()
        return
    measured = isinstance(result, SplitPreview) and not resolution.locked
    split = resolution.split_ms
    last_left = max((i for i, w in enumerate(resolution.words) if w.start_ms < split), default=-1)
    for index, word in enumerate(resolution.words):
        x0, x1 = timeline._time_to_x(word.start_ms), timeline._time_to_x(word.end_ms)
        if x1 < lane.left() or x0 > lane.right():
            continue
        chip = QRectF(x0 + 0.5, lane.top(), max(1.5, x1 - x0 - 1.0), lane.height())
        on_right = word.start_ms >= split
        boundary = measured and index in (last_left, last_left + 1)
        color = QColor(colors['muted'] if not measured else colors['right'] if on_right else colors['left'])
        color.setAlpha(255 if boundary else 92)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(chip, 3, 3)
        text = cue.text[word.char_start:word.char_end]
        if chip.width() >= metrics.horizontalAdvance(text) + 2:
            painter.setPen(colors['ink'] if boundary else QColor(palette.clip_text))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
    if measured and result.right_word_start_ms is not None:
        # The measured text boundary: where the first word of the right part
        # starts. It coincides with the cut line when snapped to it.
        bx = round(timeline._time_to_x(result.right_word_start_ms))
        painter.setPen(QPen(colors['right'], 2.0))
        painter.drawLine(bx, round(lane.top() - 5), bx, round(lane.bottom()))
    painter.restore()


def _paint_cut(timeline, painter, palette, colors, resolution, blocked) -> None:
    x = timeline._time_to_x(resolution.split_ms)
    left, right = timeline.TRACK_HEADER_WIDTH, timeline._content_right()
    if not left <= x <= right:
        return
    bottom = timeline._canvas_bottom()
    painter.save()
    painter.setClipRect(QRectF(left, 0, right - left, bottom))
    color = QColor(colors['muted'] if blocked else colors['cut'])
    thin = QColor(color)
    thin.setAlpha(210)
    pen = QPen(thin, 1.2, Qt.PenStyle.DashLine if blocked else Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    xx = round(x) + 0.5
    painter.drawLine(QPointF(xx, timeline.RULER_HEIGHT - 8), QPointF(xx, bottom))
    track = timeline._track_layout()[0].get(resolution.cue.speaker_id)
    if track is not None:
        track = timeline._cue_band(resolution.cue, track)
        painter.setPen(QPen(color, 2.2, pen.style()))
        painter.drawLine(QPointF(xx, track.top() + 3), QPointF(xx, track.bottom() - 3))
    marker = QPainterPath(QPointF(xx - 6, timeline.RULER_HEIGHT - 9))
    marker.lineTo(QPointF(xx + 6, timeline.RULER_HEIGHT - 9))
    marker.lineTo(QPointF(xx, timeline.RULER_HEIGHT - 1))
    marker.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(marker)
    rect, label = _pill(timeline, resolution)
    painter.setBrush(color)
    painter.drawRoundedRect(rect, 4, 4)
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)
    ink = colors['ink'] if not blocked else QColor('#141118')
    from .themed_icons import paint_cached_icon
    icon = QRect(round(rect.left() + 8), round(rect.center().y() - ICON / 2), ICON, ICON)
    paint_cached_icon(painter, 'fa5s.cut', ink.name(), icon)
    painter.setPen(ink)
    painter.drawText(rect.adjusted(ICON + 12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
    painter.restore()


def _paint_header(timeline, painter, palette, colors, resolution, blocked) -> None:
    cell = QRectF(0, 0, timeline.TRACK_HEADER_WIDTH, timeline.RULER_HEIGHT)
    state, left_text, right_text = status_lines(resolution)
    painter.save()
    painter.setClipRect(cell)
    painter.fillRect(cell, QColor(palette.header))
    painter.setPen(QPen(QColor(colors['muted' if blocked else 'cut']), 2))
    painter.drawLine(QPointF(cell.left() + 4, cell.bottom() - 1), QPointF(cell.right() - 4, cell.bottom() - 1))
    font = QFont()
    font.setPointSize(9)
    metrics = QFontMetrics(font)
    painter.setFont(font)
    line_height = max(12.0, (cell.height() - 3) / 2)
    first = QRectF(cell.left() + 8, cell.top() + 1, cell.width() - 14, line_height)
    second = QRectF(first.left(), first.bottom(), first.width(), line_height)
    warn = blocked or not resolution.result.measured if isinstance(resolution.result, SplitPreview) else True
    painter.setPen(colors['warn'] if warn else QColor(palette.time_label))
    flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
    painter.drawText(first, flags, metrics.elidedText(state, Qt.TextElideMode.ElideRight, int(first.width())))
    if left_text or right_text:
        bar = ' ┃ '
        room = (second.width() - metrics.horizontalAdvance(bar)) / 2
        left_label = metrics.elidedText(left_text, Qt.TextElideMode.ElideLeft, int(room))
        right_label = metrics.elidedText(right_text, Qt.TextElideMode.ElideRight, int(room))
        middle = second.center().x()
        left_area = QRectF(second.left(), second.top(), middle - second.left() - metrics.horizontalAdvance(bar) / 2,
                           second.height())
        painter.setPen(QColor(palette.clip_text))
        painter.drawText(left_area, flags | Qt.AlignmentFlag.AlignRight, left_label)
        bar_area = QRectF(left_area.right(), second.top(), metrics.horizontalAdvance(bar), second.height())
        painter.setPen(colors['muted' if blocked else 'cut'])
        painter.drawText(bar_area, flags | Qt.AlignmentFlag.AlignHCenter, bar)
        painter.setPen(colors['right'])
        painter.drawText(QRectF(bar_area.right(), second.top(), second.right() - bar_area.right(), second.height()),
                         flags | Qt.AlignmentFlag.AlignLeft, right_label)
    painter.restore()
