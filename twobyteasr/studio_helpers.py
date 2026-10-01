"""Pure Studio formatting, media identity, and style preview helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)

from .processes import run_hidden_subprocess

if TYPE_CHECKING:
    from .studio_project import StudioMedia

def _library_duration(milliseconds: int) -> str:
    minutes, seconds = divmod(max(0, int(milliseconds)) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def probe_media_identity(path: str | os.PathLike[str]) -> dict[str, object]:
    """Return the process-wide single-probe metadata snapshot as a mapping."""
    from .media_service import GLOBAL_MEDIA_SERVICE

    return GLOBAL_MEDIA_SERVICE.metadata(path).to_dict()


def media_relink_warning(media: StudioMedia, candidate: dict[str, object]) -> str:
    problems: list[str] = []
    expected_duration = int(media.duration_ms or 0)
    actual_duration = int(candidate.get("duration_ms") or 0)
    tolerance = max(3_000, round(expected_duration * 0.02))
    if expected_duration and actual_duration and abs(expected_duration - actual_duration) > tolerance:
        problems.append(
            f"时长不一致：工程记录 {_format_ms(expected_duration)}，所选媒体 {_format_ms(actual_duration)}"
        )
    expected_fingerprint = str(media.fingerprint or "")
    actual_fingerprint = str(candidate.get("fingerprint") or "")
    if expected_fingerprint and actual_fingerprint and expected_fingerprint != actual_fingerprint:
        problems.append("基础媒体指纹不一致")
    return "\n".join(problems)


def _format_ms(milliseconds: int) -> str:
    total = max(0, int(milliseconds))
    minutes, remainder = divmod(total, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_timeline_timecode(milliseconds: int) -> str:
    """Format the Studio transport clock with an explicit hours field."""
    total = max(0, int(milliseconds))
    hours, remainder = divmod(total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_timeline_timecode(value: str) -> int | None:
    """Parse hh:mm:ss.ms or mm:ss.ms transport input."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        seconds_part = parts[-1].replace(",", ".")
        seconds = float(seconds_part)
        if not 0 <= seconds < 60:
            return None
        minutes = int(parts[-2])
        hours = int(parts[-3]) if len(parts) == 3 else 0
        if minutes < 0 or hours < 0 or (len(parts) == 3 and minutes >= 60):
            return None
    except (TypeError, ValueError):
        return None
    return round((hours * 3600 + minutes * 60 + seconds) * 1000)



def _preview_color(value: object, fallback: str = "#FFFFFFFF") -> QColor:
    """Resolve legacy #RRGGBB, Qt #AARRGGBB, and recipe color values."""
    if isinstance(value, Mapping):
        value = value.get("color", fallback)
    color = QColor(str(value or fallback))
    return color if color.isValid() else QColor(fallback)


def resolve_fill_brush(fill: object, rect: QRectF) -> QBrush:
    """Shared fill resolver for StylePreview and motion/AI samples."""
    if not isinstance(fill, Mapping):
        return QBrush(_preview_color(fill))
    kind = str(fill.get("type", "solid")).lower()
    if kind == "solid":
        return QBrush(_preview_color(fill.get("color")))
    stops = [item for item in fill.get("stops", []) if isinstance(item, Mapping)]
    if kind in {"linear", "linear-gradient"}:
        angle = float(fill.get("angle", 0.0) or 0.0)
        import math
        radians = math.radians(angle)
        dx, dy = math.cos(radians), -math.sin(radians)
        center = rect.center()
        # Project the whole glyph block onto the gradient axis: both endpoint
        # stops reach its edges, including a tall/short block at 90 degrees.
        # Existing UI convention is 0=right, 90=up (CSS angle=90-angle).
        radius = max(.001,(abs(dx)*rect.width()+abs(dy)*rect.height())/2)
        gradient = QLinearGradient(center.x() - dx * radius, center.y() - dy * radius, center.x() + dx * radius, center.y() + dy * radius)
    elif kind in {"radial", "radial-gradient"}:
        gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) / 2)
    else:
        return QBrush(_preview_color(fill.get("color")))
    for stop in stops:
        try:
            position = max(0.0, min(1.0, float(stop.get("position", stop.get("pos", 0.0)))))
        except (TypeError, ValueError):
            continue
        gradient.setColorAt(position, _preview_color(stop.get("color")))
    return QBrush(gradient)


def render_style_sample(
    painter: QPainter,
    *,
    text: str,
    font: QFont,
    baseline: QPointF,
    fill: object,
    outline: object,
    outline_width: float = 0.0,
    rect: QRectF | None = None,
    opacity: float = 1.0,
    glow: Mapping[str, object] | None = None,
    strokes: list[Mapping[str, object]] | None = None,
) -> None:
    """Render one subtitle sample with the same glyph order as ASS.

    QPainter.drawText consumes the pen only; passing a QBrush through QPen
    therefore loses gradient/ARGB fill semantics. A path lets us explicitly
    stroke the outline and fill the glyph interior with the resolved brush.
    Both StylePreview and MotionPreview call this function.

    ``strokes`` (when given) paints multiple outline layers in list order —
    outermost first — enabling two-layer strokes (e.g. black outer + white
    inner) that a single ASS Outline cannot express.
    """
    path = QPainterPath()
    path.addText(baseline, font, str(text))
    bounds = path.boundingRect()
    fill_rect = QRectF(rect) if rect is not None else bounds
    fill_brush = resolve_fill_brush(fill, fill_rect)
    outline_color = _preview_color(outline, "#FF000000")
    width = max(0.0, float(outline_width or 0.0))
    if os.environ.get("TWOBYTEASR_DEBUG_STYLE_PREVIEW") == "1":
        print(
            "[STYLE_PREVIEW] draw_path"
            f" fill={fill_brush.color().name(QColor.NameFormat.HexArgb) if fill_brush.style() == Qt.BrushStyle.SolidPattern else 'gradient'}"
            f" outline={outline_color.name(QColor.NameFormat.HexArgb)} width={width:g}",
            flush=True,
        )
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, float(opacity))))
    if isinstance(glow, Mapping) and glow.get("enabled"):
        glow_color = _preview_color(glow.get("color", "#FFFF0000"), "#FFFF0000")
        base_opacity = max(0.15, min(0.95, float(glow.get("opacity", 1.0)) * 0.8))
        blur = max(0.0, float(glow.get("blur", glow.get("radius", 8.0)) or 0.0))
        # Two halo rings: a wide faint outer bloom plus a brighter inner ring.
        # Half of a single centered stroke hides under the outline/fill, which
        # made glow visually disappear on typical white-text/black-outline
        # styles — hence the wider radii and the second pass.
        outer_color = QColor(glow_color)
        outer_color.setAlphaF(base_opacity * 0.28)
        painter.strokePath(path, QPen(
            outer_color, max(5.0, min(60.0, blur * 4.4)),
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
        ))
        mid_color = QColor(glow_color)
        mid_color.setAlphaF(base_opacity * 0.5)
        painter.strokePath(path, QPen(
            mid_color, max(4.0, min(48.0, blur * 3.2)),
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
        ))
        inner_color = QColor(glow_color)
        inner_color.setAlphaF(base_opacity)
        painter.strokePath(path, QPen(
            inner_color, max(2.5, min(28.0, blur * 1.7)),
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
        ))
    if strokes:
        for stroke in strokes:
            stroke_color = _preview_color(stroke.get("color"), "#FF000000")
            stroke_width = max(0.0, float(stroke.get("width", 0) or 0.0))
            if stroke_width > 0.0 and stroke_color.alpha() > 0:
                painter.strokePath(path, QPen(stroke_color, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    elif width > 0.0 and outline_color.alpha() > 0:
        painter.strokePath(path, QPen(outline_color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.fillPath(path, fill_brush)
    painter.restore()
