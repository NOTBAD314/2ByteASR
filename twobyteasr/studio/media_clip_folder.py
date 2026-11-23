"""Media clip look for the Studio timeline (2026-11-23).

Two rounds of drafts (``tmp/timeline-track-drafts-20261123``) and one round
in the real widget. The user's final mix:

* Video clips use draft D 「色點標記」: thumbnails fill the whole card (16:9,
  first frame pinned to the clip start, last frame to its end), a 4 px
  source-colour line along the bottom, and the file name in a frosted pill
  with a source-colour dot. The pill keeps the name readable on light
  themes; the earlier pale tab text on a pale tint was not.
* Audio clips use draft E's audio: a pale source tint with the waveform in
  the source colour (decoded part darker, outline overview lighter).
* Cuts: where one source is split (a razor cut inside continuous footage)
  draft B - both ends keep their rounded corners with a small gap and a
  nearly full-height colour bridge joins them, so it still reads as one
  strip. Where two different sources meet, draft D - the clips sit flush
  with square inner corners, a thin lane-coloured seam, and a two-colour
  knot between the video and its linked audio row (left half the previous
  source colour, right half the next).
* Audio cards carry a clearly visible tint and an ink hairline so a video
  clip and its audio read as one pair (the first pale tint did not).

Selection follows the same rounded outline (``clip_outline``), never a box.
"""
from __future__ import annotations

from dataclasses import dataclass
import zlib

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen

from ..design.timeline_theme import TimelinePalette, mix

CLIP_RADIUS = 8.0
JOIN_HALF_GAP = 2.5        # each side of a cut, so joined clips keep round ends
BRIDGE_REACH = 14.0        # how far a bridge runs under each neighbouring clip
INK_LINE = 4.0             # source-colour line under video thumbnails
CELL_GAP = 2.0
PILL_HEIGHT = 19.0
PILL_MIN_CLIP_HEIGHT = 34.0
SELECTION_WIDTH = 2.0

# Muted source hues; each theme mixes them toward its own ink and lane colour.
MEDIA_HUES = ("#5b93a8", "#b9875a", "#7b6db5", "#6f9a6a", "#b0707f", "#8f8a58")


@dataclass(frozen=True)
class MediaColors:
    ink: QColor        # bottom line, dot, waveform, bridges
    tint: QColor       # audio card fill
    base: QColor       # video card fill behind thumbnails
    pill: QColor       # frosted name pill
    text: QColor       # name text inside the pill


def media_colors(palette: TimelinePalette, key: str, *, offline: bool = False) -> MediaColors:
    """Stable colours for one source file (same file, same colour, every lane)."""
    if offline:
        hue = QColor(palette.playhead)
    else:
        hue = QColor(MEDIA_HUES[zlib.crc32(str(key or "").encode("utf-8")) % len(MEDIA_HUES)])
    lane = QColor(palette.track_background)
    text = QColor(palette.clip_text)
    if palette.dark:
        ink = mix(hue, "#ffffff", 0.28)
        tint = mix(lane, hue, 0.34)
        base = mix(lane, "#ffffff", 0.07)
        pill = QColor(palette.background)
        pill.setAlphaF(0.84)
    else:
        ink = mix(hue, text, 0.12)
        tint = mix(lane, hue, 0.32)
        base = mix(lane, text, 0.07)
        pill = QColor(255, 255, 255)
        pill.setAlphaF(0.9)
    return MediaColors(ink, tint, base, pill, text)


@dataclass(frozen=True)
class ClipShape:
    true_left: float       # real project-time edges (thumbnail anchoring)
    true_right: float
    body: QRectF           # drawn card, gaps applied, artificial ends off-screen
    radius: float
    join_left: bool = False      # razor cut: half gap, rounded end
    join_right: bool = False
    flush_left: bool = False     # different source: no gap, square end
    flush_right: bool = False

    @property
    def content_left(self) -> float:
        return self.true_left + (JOIN_HALF_GAP if self.join_left else 0.0)

    @property
    def content_right(self) -> float:
        return self.true_right - (JOIN_HALF_GAP if self.join_right else 0.0)

    def path(self, grow: float = 0.0) -> QPainterPath:
        rect = self.body.adjusted(-grow, -grow, grow, grow)
        radius = max(0.0, self.radius + grow)
        left = 0.0 if self.flush_left else radius
        right = 0.0 if self.flush_right else radius
        return corner_path(rect, left, right, right, left)

    # Kept for callers written against the folder version.
    def body_path(self) -> QPainterPath:
        return self.path()


def corner_path(rect: QRectF, top_left: float, top_right: float,
                bottom_right: float, bottom_left: float) -> QPainterPath:
    """Rounded rectangle with an independent radius per corner."""
    x, y, w, h = rect.x(), rect.y(), max(0.0, rect.width()), max(0.0, rect.height())
    limit = min(w, h) / 2.0
    tl, tr, br, bl = (max(0.0, min(limit, r)) for r in (top_left, top_right, bottom_right, bottom_left))
    path = QPainterPath()
    path.moveTo(x + tl, y)
    path.lineTo(x + w - tr, y)
    if tr:
        path.arcTo(QRectF(x + w - 2 * tr, y, 2 * tr, 2 * tr), 90, -90)
    path.lineTo(x + w, y + h - br)
    if br:
        path.arcTo(QRectF(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br), 0, -90)
    path.lineTo(x + bl, y + h)
    if bl:
        path.arcTo(QRectF(x, y + h - 2 * bl, 2 * bl, 2 * bl), 270, -90)
    path.lineTo(x, y + tl)
    if tl:
        path.arcTo(QRectF(x, y, 2 * tl, 2 * tl), 180, -90)
    path.closeSubpath()
    return path


def clip_shape(left: float, right: float, top: float, height: float,
               view_left: float, view_right: float, *, join_left: bool = False,
               join_right: bool = False, flush_left: bool = False,
               flush_right: bool = False) -> ClipShape:
    """Card in real project-time x.

    ``join_*``: a razor cut inside one source, half a gap and a rounded end.
    ``flush_*``: a cut to a different source, no gap and a square end.
    """
    join_left = join_left and not flush_left
    join_right = join_right and not flush_right
    inner_left = left + (JOIN_HALF_GAP if join_left else 0.0)
    inner_right = right - (JOIN_HALF_GAP if join_right else 0.0)
    width = max(0.0, inner_right - inner_left)
    radius = min(CLIP_RADIUS, max(0.0, height) / 2.0, width / 2.0)
    x1 = max(inner_left, view_left - radius - 2.0)
    x2 = min(inner_right, view_right + radius + 2.0)
    body = QRectF(x1, top, max(0.0, x2 - x1), max(0.0, height))
    return ClipShape(left, right, body, radius, join_left, join_right, flush_left, flush_right)


def clip_outline(left: float, right: float, top: float, height: float,
                 view_left: float, view_right: float, *, join_left: bool = False,
                 join_right: bool = False, flush_left: bool = False,
                 flush_right: bool = False) -> QPainterPath:
    """The path a selection highlight strokes: the clip's own card outline."""
    return clip_shape(left, right, top, height, view_left, view_right,
                      join_left=join_left, join_right=join_right,
                      flush_left=flush_left, flush_right=flush_right).path()


def thumbnail_height(shape: ClipShape) -> float:
    return max(0.0, shape.body.height() - INK_LINE)


def thumbnail_cells(shape: ClipShape, source_in: float, source_out: float,
                    view_left: float, view_right: float, lod_ms: int) -> list[tuple[QRectF, int]]:
    """Full-height 16:9 cells: first frame at the clip start, last at its end.

    Sample times sit on the filmstrip's LOD grid so a trim or zoom step
    reuses decoded frames instead of asking for new ones each pixel.
    """
    cell_height = thumbnail_height(shape)
    if cell_height < 8 or source_out <= source_in:
        return []
    cell_width = cell_height * 16.0 / 9.0
    x0 = shape.content_left
    span = shape.content_right - x0
    if span <= 2:
        return []
    count = max(2, int((span + CELL_GAP) // (cell_width + CELL_GAP))) if span > cell_width * 1.2 else 1
    step = (span - cell_width) / (count - 1) if count > 1 else 0.0
    if count > 1 and step - cell_width > CELL_GAP + 4:
        # Spread whole cells left light bars up to a cell wide between frames
        # on short clips; one more cell, with the earlier ones centre-cropped
        # narrower (never stretched), keeps every gap at CELL_GAP.
        count += 1
        step = (span - cell_width) / (count - 1)
    lod = max(1, int(lod_ms))
    first_ms = min(int(source_out) - 1, -(-int(source_in) // lod) * lod)
    last_ms = max(first_ms, ((int(source_out) - 1) // lod) * lod)
    top = shape.body.top()
    cells = []
    start = 0 if count == 1 else max(0, int((view_left - x0 - cell_width) // step))
    for index in range(start, count):
        x = x0 + index * step
        if x > view_right:
            break
        if x + cell_width < view_left:
            continue
        if count == 1:
            ms = first_ms
        else:
            fraction = index / (count - 1)
            ms = int(round((first_ms + (last_ms - first_ms) * fraction) / lod)) * lod
            ms = min(last_ms, max(first_ms, ms))
        width = cell_width if index == count - 1 else min(cell_width, step - CELL_GAP)
        cells.append((QRectF(x, top, width, cell_height), int(ms)))
    return cells


def paint_video_card(painter: QPainter, shape: ClipShape, colors: MediaColors) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colors.base)
    painter.drawPath(shape.path())


def paint_video_card_finish(painter: QPainter, shape: ClipShape, colors: MediaColors,
                            palette: TimelinePalette, selected: bool) -> None:
    """Bottom source line, hairline border and (if selected) the outline."""
    painter.save()
    painter.setClipPath(shape.path(), Qt.ClipOperation.IntersectClip)
    painter.fillRect(QRectF(shape.body.left(), shape.body.bottom() - INK_LINE,
                            shape.body.width(), INK_LINE), colors.ink)
    painter.restore()
    hairline = QColor(palette.clip_text)
    hairline.setAlphaF(0.14)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(hairline, 1.0))
    painter.drawPath(shape.path(-0.5))
    if selected:
        paint_selection_outline(painter, palette, shape.path())


def paint_selection_outline(painter: QPainter, palette: TimelinePalette, path: QPainterPath) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(palette.clip_selected_border), SELECTION_WIDTH))
    painter.drawPath(path)
    painter.restore()


def _pill_font(painter: QPainter, point_size: float) -> QFont:
    font = QFont(painter.font())
    font.setPointSizeF(point_size)
    font.setWeight(QFont.Weight.Bold)
    font.setItalic(False)
    return font


def paint_name_pill(painter: QPainter, shape: ClipShape, colors: MediaColors, label: str,
                    detail: str, view_left: float, view_right: float, point_size: float = 8.0) -> None:
    """Frosted pill with a source dot; sticks to the viewport's left edge."""
    if shape.body.height() < PILL_MIN_CLIP_HEIGHT:
        return
    font = _pill_font(painter, point_size)
    metrics = QFontMetricsF(font)
    left = max(shape.body.left(), view_left) + 6.0
    right = min(shape.body.right(), view_right) - 6.0
    room = right - left
    if room < 34.0:
        return
    label_width = metrics.horizontalAdvance(label)
    detail_width = metrics.horizontalAdvance(detail) if detail else 0.0
    full = 18.0 + label_width + (detail_width + 8.0 if detail else 0.0) + 9.0
    width = min(full, room)
    pill = QRectF(left, shape.body.top() + 5.0, width, PILL_HEIGHT)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colors.pill)
    painter.drawRoundedRect(pill, PILL_HEIGHT / 2.0, PILL_HEIGHT / 2.0)
    painter.setBrush(colors.ink)
    painter.drawEllipse(QRectF(pill.left() + 7.0, pill.center().y() - 3.0, 6.0, 6.0))
    painter.setFont(font)
    painter.setPen(colors.text)
    show_detail = bool(detail) and width >= full
    text_left = pill.left() + 18.0
    text_width = pill.right() - 9.0 - text_left - (detail_width + 8.0 if show_detail else 0.0)
    painter.drawText(
        QRectF(text_left, pill.top(), max(4.0, text_width), pill.height()),
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(max(4.0, text_width))),
    )
    if show_detail:
        faded = QColor(colors.text)
        faded.setAlphaF(0.55)
        painter.setPen(faded)
        painter.drawText(
            QRectF(text_left + label_width + 8.0, pill.top(), detail_width + 2.0, pill.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            detail,
        )
    painter.restore()


def paint_cut_bridge(painter: QPainter, x: float, top: float, height: float,
                     before: QColor, after: QColor, *, continuous: bool) -> None:
    """Draft B cut: a gradient bridge under the two rounded ends.

    Draw it before the clips: they cover its ends, so only the notch
    between their rounded corners shows. A razor cut inside one source gets
    a nearly full-height bridge and reads as one strip.
    """
    bridge_height = max(4.0, height - 6.0) if continuous else max(4.0, height * 0.42)
    rect = QRectF(x - BRIDGE_REACH, top + (height - bridge_height) / 2.0, BRIDGE_REACH * 2, bridge_height)
    gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
    gradient.setColorAt(0.0, before)
    gradient.setColorAt(1.0, after)
    radius = 4.0 if continuous else bridge_height / 2.0
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def paint_cut_seam(painter: QPainter, palette: TimelinePalette, x: float, top: float, height: float) -> None:
    """Draft D cut between two sources: a thin lane-coloured line."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QPen(QColor(palette.track_background), 1.5))
    painter.drawLine(round(x), round(top), round(x), round(top + height))
    painter.restore()


def paint_cut_knot(painter: QPainter, palette: TimelinePalette, x: float, y: float,
                   before: QColor, after: QColor) -> None:
    """Draft D two-colour knot: left half the previous source, right the next."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ring = QColor(palette.clip_text)
    ring.setAlphaF(0.18)
    painter.setPen(QPen(ring, 1.0))
    painter.setBrush(QColor(palette.track_background))
    painter.drawEllipse(QRectF(x - 5.5, y - 5.5, 11.0, 11.0))
    painter.setPen(Qt.PenStyle.NoPen)
    dot = QRectF(x - 3.4, y - 3.4, 6.8, 6.8)
    painter.setBrush(before)
    painter.drawPie(dot, 90 * 16, 180 * 16)
    painter.setBrush(after)
    painter.drawPie(dot, -90 * 16, 180 * 16)
    painter.restore()


def paint_audio_card(painter: QPainter, shape: ClipShape, colors: MediaColors) -> None:
    """Tinted audio card with an ink hairline, the pair of its video clip."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colors.tint)
    painter.drawPath(shape.path())
    edge = QColor(colors.ink)
    edge.setAlphaF(0.45)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(edge, 1.0))
    painter.drawPath(shape.path(-0.5))
    painter.restore()


def audio_bridge_colors(palette: TimelinePalette, before: MediaColors, after: MediaColors) -> tuple[QColor, QColor]:
    lane = QColor(palette.track_background)
    return mix(before.ink, lane, 0.45), mix(after.ink, lane, 0.45)


def format_clip_duration(ms: int) -> str:
    seconds = max(0, int(ms)) / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}:{rest:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}"
