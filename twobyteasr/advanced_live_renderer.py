"""Fast Qt raster fallback for canonical Advanced subtitle snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from math import ceil, cos, pi, sin

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QColorConstants, QFont, QFontMetricsF, QImage,
    QLinearGradient, QPainter, QPainterPath,
    QPainterPathStroker, QPen, QPolygonF, QRadialGradient,
)

from .studio_helpers import resolve_fill_brush
from .visual_design_graph import (
    COORDINATE_SPACE_VIDEO_CANVAS,
    CompiledLiveScene,
    VisualDesignGraph,
    layer_coordinate_space,
)
from .visual_snapshot import VisualCueSnapshot


LIVE_RENDERER_VERSION = "qt-live-v6-static-glyph-anchor"


class LiveLayerImages(dict[str, QImage]):
    """Aligned layer rasters with their position in the full render canvas."""

    def __init__(
        self,
        values: Mapping[str, QImage],
        *,
        canvas_size: QSize,
        origin: QPoint | None = None,
        snapshot: object = None,
    ) -> None:
        super().__init__(values)
        self.canvas_size = QSize(canvas_size)
        self.origin = QPoint(origin or QPoint())
        # The snapshot rides along so animated tracking can redraw the text
        # raster inside composite_live_scene_layers.
        self.snapshot = snapshot
        self.last_tracking: float | None = 0.0


def crop_live_layers(
    layers: Mapping[str, QImage], bounds: QRect
) -> LiveLayerImages:
    source = next((image for image in layers.values() if not image.isNull()), QImage())
    canvas_size = getattr(layers, "canvas_size", source.size())
    current_origin = getattr(layers, "origin", QPoint())
    clipped = QRect(bounds).intersected(source.rect())
    return LiveLayerImages(
        {
            layer_id: image.copy(clipped)
            for layer_id, image in layers.items()
            if not image.isNull()
        },
        canvas_size=canvas_size,
        origin=current_origin + clipped.topLeft(),
    )


def _color(value: object, fallback: str = "#FF000000", *, opacity: float = 1.0) -> QColor:
    if isinstance(value, Mapping):
        value = value.get("color", fallback)
    color = QColor(str(value or fallback))
    if not color.isValid():
        color = QColor(fallback)
    color.setAlphaF(max(0.0, min(1.0, color.alphaF() * float(opacity))))
    return color


def _number(payload: Mapping[str, object], *names: str, default: float = 0.0) -> float:
    for name in names:
        if payload.get(name) is not None:
            try:
                return float(payload[name])
            except (TypeError, ValueError):
                pass
    return float(default)


def _alpha_color(color: QColor, factor: float) -> QColor:
    result = QColor(color)
    result.setAlphaF(max(0.0, min(1.0, result.alphaF() * float(factor))))
    return result


def outside_stroke_ring(path: QPainterPath, radius: float) -> QPainterPath:
    """Return only the pixels added outside the original glyph geometry."""

    radius = max(0.0, float(radius))
    if radius <= 0.0 or path.isEmpty():
        return QPainterPath()
    stroker = QPainterPathStroker()
    stroker.setWidth(radius * 2.0)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    expanded = stroker.createStroke(path)
    expanded.setFillRule(Qt.FillRule.WindingFill)
    return expanded.subtracted(path)


def _draw_soft_path(
    painter: QPainter,
    path: QPainterPath,
    *,
    color: QColor,
    radius: float,
    spread: float = 0.0,
    fill_core: bool,
    intensity: float = 1.0,
) -> None:
    """Paint a bounded soft halo without a QWidget/scene blur round trip."""
    radius = max(0.0, float(radius))
    spread = max(0.0, float(spread))
    intensity = max(0.0, float(intensity))
    steps = max(1, min(8, int(ceil(radius))))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for step in range(steps, 0, -1):
        ratio = step / steps
        extent = spread + radius * ratio
        if extent <= 0:
            continue
        ring_alpha = min(1.0, intensity * (0.10 + 0.18 * (1.0 - ratio)) / steps * 4.0)
        painter.setPen(QPen(
            _alpha_color(color, ring_alpha),
            max(0.6, extent * 2.0),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        painter.drawPath(path)
    if fill_core:
        painter.setPen(QPen(
            _alpha_color(color, min(1.0, intensity)),
            max(0.0, spread * 2.0),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        painter.setBrush(_alpha_color(color, min(1.0, intensity)))
        painter.drawPath(path)


def _draw_shadow_path(painter, path, *, color, radius, spread=0.0, fill_core=True):
    """Blur one opaque glyph mask, then apply color alpha exactly once.

    Drawing translucent rings and the core onto the video compounds opacity.
    The single mask also matches CSS blur semantics in the export renderer.
    """
    if color.alpha() == 0 or path.isEmpty():
        return
    import numpy as np
    from PIL import Image, ImageFilter
    padding = max(0.0, radius) * 3 + max(0.0, spread) + 2
    bounds = path.boundingRect().adjusted(-padding, -padding, padding, padding).toAlignedRect()
    mask = QImage(bounds.size(), QImage.Format_ARGB32_Premultiplied)
    mask.fill(Qt.transparent)
    brush = QPainter(mask)
    brush.setRenderHint(QPainter.RenderHint.Antialiasing)
    brush.translate(-bounds.left(), -bounds.top())
    brush.setBrush(Qt.white)
    brush.setPen(QPen(Qt.white, spread * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) if spread > 0 else Qt.NoPen)
    brush.drawPath(path)
    brush.end()
    packed = np.ndarray((mask.height(), mask.width(), 4), dtype=np.uint8,
                       buffer=mask.constBits(), strides=(mask.bytesPerLine(), 4, 1))
    alpha = Image.fromarray(packed[:, :, 3].copy())
    if radius > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius))
    rgba = np.empty((mask.height(), mask.width(), 4), dtype=np.uint8)
    rgba[:, :, :3] = (color.red(), color.green(), color.blue())
    rgba[:, :, 3] = np.rint(np.asarray(alpha).astype(np.float32) * color.alphaF()).astype(np.uint8)
    image = QImage(rgba.data, mask.width(), mask.height(), mask.width()*4, QImage.Format_RGBA8888).copy()
    painter.drawImage(bounds.topLeft(), image)


def _graph_for_snapshot(snapshot: VisualCueSnapshot) -> VisualDesignGraph | None:
    recipe = snapshot.style_recipe if isinstance(snapshot.style_recipe, Mapping) else {}
    payload = recipe.get("visualGraph")
    if not isinstance(payload, Mapping) or not payload:
        return None
    return VisualDesignGraph.from_dict(payload)


def _param_number(payload: Mapping[str, object], *names: str, default: float = 0.0) -> float:
    return _number(payload, *names, default=default)


def _layer_overflow(params: Mapping[str, object], axis: str, default: float = 0.35) -> float:
    key = f"overflow{axis.upper()}"
    alt = f"overflow_{axis}"
    value = _param_number(params, key, alt, "overflow", default=default)
    return max(0.0, min(1.2, value if value <= 4.0 else default))


def composition_pivot_for_snapshot(
    snapshot: VisualCueSnapshot,
    width: int,
    height: int,
) -> QPointF:
    """Subtitle-local composition origin in the live raster."""

    scale_x = max(1, int(width)) / max(1.0, float(snapshot.playres_x))
    scale_y = max(1, int(height)) / max(1.0, float(snapshot.playres_y))
    return QPointF(float(snapshot.position_x) * scale_x, float(snapshot.position_y) * scale_y)


def _expanded_bounds(bounds: QRectF, params: Mapping[str, object], scale: float) -> QRectF:
    """Expand from the subtitle-local box. Never interpret sizes as video-frame %."""

    overflow_x = _layer_overflow(params, "x")
    overflow_y = _layer_overflow(params, "y")
    padding_x = min(
        bounds.width() * overflow_x,
        _param_number(params, "paddingX", "padding_x", "padding", default=20) * scale,
    )
    padding_y = min(
        bounds.height() * overflow_y,
        _param_number(params, "paddingY", "padding_y", "padding", default=12) * scale,
    )
    return bounds.adjusted(-padding_x, -padding_y, padding_x, padding_y)


def _draw_panel(
    painter: QPainter,
    bounds: QRectF,
    graph: VisualDesignGraph,
    type_scale: float,
) -> None:
    panel = graph.panel_layer
    if panel.primitive == "NONE":
        return
    if layer_coordinate_space(panel) == COORDINATE_SPACE_VIDEO_CANVAS:
        return
    params = panel.params
    rect = _expanded_bounds(bounds, params, type_scale)
    fill_value = params.get("gradient") or params.get("fill") or params.get("color", "#CC111111")
    outline = _color(
        params.get("outlineColor", params.get("borderColor", params.get("color"))),
        "#FF111111",
    )
    frame_panel = panel.primitive in {"BRACKET_FRAME", "TECH_FRAME"}
    outline_width = _param_number(
        params, "outlineWidth", "borderWidth", default=2 if frame_panel else 0
    ) * type_scale
    painter.setPen(
        QPen(outline, max(0.0, outline_width), Qt.PenStyle.SolidLine,
             Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if outline_width > 0 else Qt.PenStyle.NoPen
    )
    painter.setBrush(resolve_fill_brush(fill_value, rect))
    if panel.primitive == "COMIC_BURST":
        point_count = max(10, min(40, int(params.get("points", 18) or 18)))
        center = rect.center()
        radius_x = max(1.0, rect.width() * 0.5)
        radius_y = max(1.0, rect.height() * 0.5)
        polygon = QPolygonF()
        for index in range(point_count * 2):
            angle = -pi / 2 + index * pi / point_count
            jitter = 0.96 + 0.06 * sin((index + graph.seed) * 7.173)
            radius = (1.0 if index % 2 == 0 else 0.72) * jitter
            polygon.append(QPointF(
                center.x() + cos(angle) * radius_x * radius,
                center.y() + sin(angle) * radius_y * radius,
            ))
        painter.drawPolygon(polygon)
    elif panel.primitive == "ROUNDED_PANEL":
        radius = _param_number(params, "radius", "borderRadius", default=8) * type_scale
        painter.drawRoundedRect(rect, radius, radius)
    elif panel.primitive in {"CUT_CORNER", "ANGLED_PLATE"}:
        cut = min(rect.width() * 0.12, rect.height() * 0.42, 18 * type_scale)
        skew = cut * (1.7 if panel.primitive == "ANGLED_PLATE" else 1.0)
        painter.drawPolygon(QPolygonF([
            QPointF(rect.left() + skew, rect.top()), rect.topRight(),
            QPointF(rect.right() - cut, rect.bottom()), rect.bottomLeft(),
        ]))
    elif panel.primitive in {"BRACKET_FRAME", "TECH_FRAME"}:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        corner = min(rect.width() * 0.18, rect.height() * 0.42, 24 * type_scale)
        path = QPainterPath()
        path.moveTo(rect.left() + corner, rect.top()); path.lineTo(rect.left(), rect.top()); path.lineTo(rect.left(), rect.top() + corner)
        path.moveTo(rect.right() - corner, rect.top()); path.lineTo(rect.right(), rect.top()); path.lineTo(rect.right(), rect.top() + corner)
        path.moveTo(rect.left(), rect.bottom() - corner); path.lineTo(rect.left(), rect.bottom()); path.lineTo(rect.left() + corner, rect.bottom())
        path.moveTo(rect.right(), rect.bottom() - corner); path.lineTo(rect.right(), rect.bottom()); path.lineTo(rect.right() - corner, rect.bottom())
        if panel.primitive == "TECH_FRAME":
            tick = min(12 * type_scale, rect.width() * 0.08)
            path.moveTo(rect.left() + corner * 1.4, rect.top()); path.lineTo(rect.left() + corner * 1.4 + tick, rect.top())
            path.moveTo(rect.right() - corner * 1.4, rect.bottom()); path.lineTo(rect.right() - corner * 1.4 - tick, rect.bottom())
        painter.drawPath(path)
    elif panel.primitive == "COMIC_BUBBLE":
        radius = min(rect.height() * 0.28, 14 * type_scale)
        painter.drawRoundedRect(rect, radius, radius)
        tail = min(rect.height() * 0.34, 16 * type_scale)
        painter.drawPolygon(QPolygonF([
            QPointF(rect.center().x() - tail, rect.bottom()),
            QPointF(rect.center().x(), rect.bottom() + tail),
            QPointF(rect.center().x() + tail * 0.35, rect.bottom()),
        ]))
    elif panel.primitive == "UNDERLINE_SLAB":
        height = max(3 * type_scale, min(rect.height() * 0.22, 14 * type_scale))
        slab = QRectF(rect.left() + rect.width() * 0.04, rect.bottom() - height, rect.width() * 0.92, height)
        painter.drawRect(slab)
    elif panel.primitive == "MARKER":
        # Marker-pen highlight: skewed translucent block behind the glyphs.
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        center = rect.center()
        painter.translate(center.x(), center.y())
        painter.rotate(_param_number(params, "skew", default=-6.0))
        painter.translate(-center.x(), -center.y())
        painter.drawRect(rect)
        painter.restore()
    elif panel.primitive == "TAPE":
        # Washi tape strip laid across the top edge of the composition.
        tape_height = max(6 * type_scale, min(rect.height() * 0.30, 18 * type_scale))
        tape = QRectF(rect.left(), rect.top(), rect.width(), tape_height)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.translate(tape.center().x(), tape.center().y())
        painter.rotate(_param_number(params, "angle", default=-1.5))
        painter.translate(-tape.center().x(), -tape.center().y())
        painter.drawRect(tape)
        painter.restore()
    elif panel.primitive == "PIXEL_FRAME":
        # 8-bit staircase blocks in the four corners, hollow center.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        block = max(4.0, _param_number(params, "block", "blockSize", default=8) * type_scale)
        steps = 3
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            corner_x = rect.left() if dx == 0 else rect.right()
            corner_y = rect.top() if dy == 0 else rect.bottom()
            for step in range(steps):
                size = block * (steps - step)
                x = corner_x - size if dx else corner_x
                y = corner_y - size if dy else corner_y
                painter.drawRect(QRectF(x, y, size, size))
    elif panel.primitive == "PILL":
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    elif panel.primitive == "TORN_PAPER":
        # Ripped-paper edge: jagged top and bottom from the layer seed.
        painter.setPen(Qt.PenStyle.NoPen)
        teeth = max(6, min(22, int(params.get("teeth", 12) or 12)))
        polygon = QPolygonF()
        for index in range(teeth):
            ratio = index / (teeth - 1)
            jitter = sin((index + graph.seed) * 5.13) * 2.4 * type_scale
            polygon.append(QPointF(rect.left() + ratio * rect.width(), rect.top() + jitter))
        for index in range(teeth - 1, -1, -1):
            ratio = index / (teeth - 1)
            jitter = sin((index + graph.seed + 7) * 4.31) * 2.4 * type_scale
            polygon.append(QPointF(rect.left() + ratio * rect.width(), rect.bottom() + jitter))
        painter.drawPolygon(polygon)
    elif panel.primitive == "GLASS_PANEL":
        # Frosted glass: translucent plate, light rim, specular top strip.
        painter.save()
        radius = min(rect.height() * 0.28, 16 * type_scale)
        painter.setPen(QPen(
            _color(params.get("rimColor", "#66FFFFFF")), max(1.0, 1.2 * type_scale),
        ))
        painter.drawRoundedRect(rect, radius, radius)
        highlight = QRectF(
            rect.left() + radius * 0.4, rect.top() + 1.2 * type_scale,
            rect.width() * 0.55, max(2.0, 2.4 * type_scale),
        )
        painter.setBrush(_color(params.get("rimColor", "#66FFFFFF")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(highlight, highlight.height() / 2, highlight.height() / 2)
        painter.restore()
    elif panel.primitive in {"RIBBON", "BADGE"}:
        radius = min(rect.height() * 0.5, 12 * type_scale) if panel.primitive == "BADGE" else 4 * type_scale
        painter.drawRoundedRect(rect, radius, radius)
        if panel.primitive == "RIBBON":
            tail = min(rect.height() * 0.42, 18 * type_scale)
            left = QPolygonF([
                rect.topLeft(), QPointF(rect.left() - tail, rect.center().y()), rect.bottomLeft(),
            ])
            right = QPolygonF([
                rect.topRight(), QPointF(rect.right() + tail, rect.center().y()), rect.bottomRight(),
            ])
            painter.drawPolygon(left)
            painter.drawPolygon(right)
    elif panel.primitive == "MECHANICAL_PLATE":
        # Riveted iron plate: double outline, corner squares, inner hairline.
        radius = _param_number(params, "cornerRadius", "radius", default=6) * type_scale
        painter.drawRoundedRect(rect, radius, radius)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = max(2.5, min(rect.height() * 0.16, 7 * type_scale))
        inner = rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(QPen(outline, max(0.8, outline_width * 0.4)))
        painter.drawRoundedRect(inner, radius * 0.6, radius * 0.6)
        corner = max(3.0, min(rect.height() * 0.2, 9 * type_scale))
        painter.setPen(QPen(outline, max(0.8, outline_width * 0.5)))
        for corner_rect in (
            QRectF(rect.left(), rect.top(), corner, corner),
            QRectF(rect.right() - corner, rect.top(), corner, corner),
            QRectF(rect.left(), rect.bottom() - corner, corner, corner),
            QRectF(rect.right() - corner, rect.bottom() - corner, corner, corner),
        ):
            painter.drawRoundedRect(corner_rect, 2, 2)
        if bool(params.get("ornate")):
            painter.setPen(QPen(outline, max(0.7, outline_width * 0.3)))
            painter.drawLine(
                QPointF(inner.left(), inner.center().y()),
                QPointF(inner.left() + inner.width() * 0.12, inner.center().y()),
            )
            painter.drawLine(
                QPointF(inner.right() - inner.width() * 0.12, inner.center().y()),
                QPointF(inner.right(), inner.center().y()),
            )
        painter.restore()
    elif panel.primitive == "STICKER":
        # Die-cut sticker: white rim, rounded body, folded dog-ear corner.
        painter.save()
        rim = max(2.0, _param_number(params, "rimWidth", default=4) * type_scale)
        radius = min(rect.height() * 0.3, 14 * type_scale)
        rim_rect = rect.adjusted(-rim, -rim, rim, rim)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(params.get("rimColor", "#F2FFFFFF")))
        painter.drawRoundedRect(rim_rect, radius + rim, radius + rim)
        painter.setBrush(resolve_fill_brush(fill_value, rect))
        painter.setPen(QPen(outline, max(0.0, outline_width)))
        painter.drawRoundedRect(rect, radius, radius)
        ear = min(rect.width() * 0.16, rect.height() * 0.4, 16 * type_scale)
        painter.setBrush(_color(params.get("foldColor", "#B3000000")))
        painter.drawPolygon(QPolygonF([
            QPointF(rect.right() - ear, rect.top()),
            rect.topRight(),
            QPointF(rect.right(), rect.top() + ear),
        ]))
        painter.restore()
    elif panel.primitive == "LOWER_THIRD":
        # Broadcast lower-third slab with a parallel skew for direction.
        painter.save()
        skew = _param_number(params, "skew", default=-8.0) * type_scale
        painter.setPen(Qt.PenStyle.NoPen)
        height = rect.height()
        polygon = QPolygonF([
            QPointF(rect.left() - skew * 0.4, rect.top()),
            QPointF(rect.right() + skew, rect.top()),
            QPointF(rect.right() - skew, rect.bottom()),
            QPointF(rect.left() - skew * 0.4 + skew, rect.bottom()),
        ])
        painter.drawPolygon(polygon)
        if outline_width > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(outline, outline_width))
            painter.drawPolygon(polygon)
        painter.restore()
    else:
        painter.drawRect(rect)


def _draw_decoration(
    painter: QPainter,
    bounds: QRectF,
    primitive: str,
    params: Mapping[str, object],
    seed: int,
    type_scale: float,
) -> None:
    color = _color(params.get("color"), "#AA111111")
    # Width/overflow percentages are subtitle-local even if a graph asked
    # for video-canvas. Never promote a decoration to the full frame.
    rect = _expanded_bounds(bounds, params, type_scale)
    center = rect.center()
    painter.setBrush(color)
    painter.setPen(QPen(color, max(0.8, _param_number(params, "width", default=2) * type_scale)))
    if primitive == "IMPACT_RAYS":
        count = max(6, min(48, int(params.get("count", 16) or 16)))
        length = _param_number(params, "length", default=34) * type_scale
        for index in range(count):
            angle = index * 2 * pi / count + sin((index + seed) * 1.91) * 0.035
            inner_x = rect.width() * 0.54
            inner_y = rect.height() * 0.58
            painter.drawLine(
                QPointF(center.x() + cos(angle) * inner_x, center.y() + sin(angle) * inner_y),
                QPointF(center.x() + cos(angle) * (inner_x + length), center.y() + sin(angle) * (inner_y + length)),
            )
    elif primitive == "HALFTONE":
        max_radius = max(1.2, min(bounds.width(), bounds.height()) * 0.08)
        spacing = max(5.0, min(
            max(8.0, min(bounds.width(), bounds.height()) * 0.22),
            _param_number(params, "spacing", default=11) * type_scale,
        ))
        radius = max(0.6, min(max_radius, _param_number(params, "radius", default=2.0) * type_scale))
        y = rect.top()
        row = 0
        while y <= rect.bottom():
            x = rect.left() + (spacing * 0.5 if row % 2 else 0)
            while x <= rect.right():
                painter.drawEllipse(QPointF(x, y), radius, radius)
                x += spacing
            row += 1
            y += spacing
    elif primitive == "SCANLINES":
        spacing = max(2.0, _param_number(params, "spacing", default=5) * type_scale)
        y = rect.top()
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += spacing
    elif primitive == "SPEED_LINES":
        count = max(4, min(24, int(params.get("count", 9) or 9)))
        length = _param_number(params, "length", default=30) * type_scale
        for index in range(count):
            ratio = (index + 1) / (count + 1)
            y = rect.top() + ratio * rect.height()
            offset = (0.7 + 0.3 * sin((seed + index) * 2.3)) * length
            painter.drawLine(QPointF(rect.left() - offset, y), QPointF(rect.left() - 3, y))
            painter.drawLine(QPointF(rect.right() + 3, y), QPointF(rect.right() + offset, y))
    elif primitive == "SHARDS":
        count = max(3, min(18, int(params.get("count", 7) or 7)))
        for index in range(count):
            angle = (index + 0.5) * 2 * pi / count
            origin = QPointF(
                center.x() + cos(angle) * rect.width() * 0.62,
                center.y() + sin(angle) * rect.height() * 0.68,
            )
            size = (4 + abs(sin((seed + index) * 4.1)) * 8) * type_scale
            painter.drawPolygon(QPolygonF([
                origin,
                QPointF(origin.x() + cos(angle - 0.35) * size, origin.y() + sin(angle - 0.35) * size),
                QPointF(origin.x() + cos(angle + 0.35) * size, origin.y() + sin(angle + 0.35) * size),
            ]))
    elif primitive == "ACCENT_BARS":
        count = max(1, min(8, int(params.get("count", 3) or 3)))
        bar_width = _param_number(params, "barWidth", default=5) * type_scale
        for index in range(count):
            height = rect.height() * (0.22 + index * 0.1)
            x = rect.left() - (count - index) * bar_width * 1.8
            painter.drawRoundedRect(
                QRectF(x, center.y() - height / 2, bar_width, height),
                bar_width / 2, bar_width / 2,
            )
    elif primitive == "PIXEL_TILES":
        size = max(2.0, _param_number(params, "size", default=4) * type_scale)
        spacing = max(size * 1.6, _param_number(params, "spacing", default=16) * type_scale)
        y = rect.top()
        row = 0
        while y <= rect.bottom():
            x = rect.left() + (spacing * 0.5 if row % 2 else 0)
            while x <= rect.right():
                column = int((x - rect.left()) / spacing)
                if (row * 7 + column * 13 + seed) % 5 != 0:
                    painter.drawRect(QRectF(x, y, size, size))
                x += spacing
            row += 1
            y += spacing
    elif primitive == "CROSSHAIR":
        reach = _param_number(params, "reach", default=22) * type_scale
        gap = _param_number(params, "gap", default=10) * type_scale
        for cx, cy, sx, sy in (
            (rect.left(), rect.top(), 1, 1), (rect.right(), rect.top(), -1, 1),
            (rect.left(), rect.bottom(), 1, -1), (rect.right(), rect.bottom(), -1, -1),
        ):
            painter.drawLine(
                QPointF(cx + sx * gap, cy + sy * gap),
                QPointF(cx + sx * (gap + reach), cy + sy * gap),
            )
            painter.drawLine(
                QPointF(cx + sx * gap, cy + sy * gap),
                QPointF(cx + sx * gap, cy + sy * (gap + reach)),
            )
    elif primitive == "INK_SPLAT":
        count = max(3, min(12, int(params.get("count", 6) or 6)))
        for index in range(count):
            angle = (index + 0.5) * 2 * pi / count + sin((seed + index) * 3.7) * 0.4
            distance = (0.55 + 0.35 * abs(sin((seed + index) * 2.1))) * max(rect.width(), rect.height()) * 0.5
            origin = QPointF(center.x() + cos(angle) * distance, center.y() + sin(angle) * distance * 0.8)
            size = (3 + abs(sin((seed + index) * 5.3)) * 7) * type_scale
            painter.drawEllipse(origin, size, size * (0.7 + 0.3 * abs(sin((seed + index) * 1.9))))
    elif primitive == "FLOAT_GLYPHS":
        count = max(2, min(10, int(params.get("count", 5) or 5)))
        symbols = str(params.get("symbols") or "✦★●")
        font = painter.font()
        glyph_size = max(8.0, _param_number(params, "size", default=14) * type_scale)
        for index in range(count):
            glyph = symbols[index % len(symbols)] if symbols else "✦"
            angle = (seed + index * 2.399) % (2 * pi)
            distance = max(rect.width(), rect.height()) * (0.52 + 0.12 * sin((seed + index) * 1.3))
            position = QPointF(
                center.x() + cos(angle) * distance,
                center.y() + sin(angle) * distance * 0.7,
            )
            painter.save()
            painter.setFont(font)
            glyph_font = QFont(font)
            glyph_font.setPixelSize(max(1, round(glyph_size * (0.7 + 0.3 * ((seed + index) % 3) / 2))))
            painter.setFont(glyph_font)
            painter.drawText(position, glyph)
            painter.restore()
    elif primitive == "SCAN_SWEEP":
        # One vertical scan bar; animate its x (or opacity) from MotionGraph.
        width = max(6.0, _param_number(params, "width", default=26) * type_scale)
        bar = QRectF(center.x() - width / 2, rect.top(), width, rect.height())
        gradient = QLinearGradient(bar.topLeft(), bar.topRight())
        gradient.setColorAt(0.0, QColorConstants.Transparent)
        gradient.setColorAt(0.5, color)
        gradient.setColorAt(1.0, QColorConstants.Transparent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRect(bar)
    elif primitive == "PARTICLES":
        count = max(4, min(20, int(params.get("count", 9) or 9)))
        for index in range(count):
            ratio_x = ((seed * 13 + index * 37) % 97) / 97.0
            ratio_y = ((seed * 29 + index * 61) % 89) / 89.0
            size = (1.4 + abs(sin((seed + index) * 3.3)) * 2.6) * type_scale
            painter.drawEllipse(QPointF(
                rect.left() + ratio_x * rect.width(),
                rect.top() + ratio_y * rect.height(),
            ), size, size)
    elif primitive == "ARROWS":
        # Comic chevrons pointing toward the text from one side.
        count = max(2, min(6, int(params.get("count", 3) or 3)))
        size = max(8.0, _param_number(params, "size", default=18) * type_scale)
        from_left = str(params.get("side", "left")).lower() != "right"
        pen = QPen(color, max(1.2, _param_number(params, "width", default=3) * type_scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(count):
            offset = size * (0.8 + index * 0.9)
            if from_left:
                x = rect.left() - offset
                y = center.y() + sin((seed + index) * 2.7) * rect.height() * 0.22
                points = [
                    QPointF(x + size * 0.45, y - size * 0.5),
                    QPointF(x - size * 0.45, y),
                    QPointF(x + size * 0.45, y + size * 0.5),
                ]
            else:
                x = rect.right() + offset
                y = center.y() + sin((seed + index) * 2.7) * rect.height() * 0.22
                points = [
                    QPointF(x - size * 0.45, y - size * 0.5),
                    QPointF(x + size * 0.45, y),
                    QPointF(x - size * 0.45, y + size * 0.5),
                ]
            painter.drawPolyline(QPolygonF(points))
    elif primitive == "DATA_BARS":
        # Equalizer-style bar cluster anchored under one edge of the text.
        count = max(3, min(9, int(params.get("count", 5) or 5)))
        bar_width = max(2.0, _param_number(params, "barWidth", default=4) * type_scale)
        for index in range(count):
            height = rect.height() * (0.12 + abs(sin((seed + index) * 2.9)) * 0.3)
            painter.drawRect(QRectF(
                rect.right() + (index - count) * bar_width * 1.6 - bar_width,
                rect.bottom() - height,
                bar_width,
                height,
            ))
    elif primitive == "GEARS":
        # Gear cluster centered on the composition pivot: a toothed ring plus
        # satellite pinions. A rotation track spins the ring in place (the
        # composite pivot is this center) while satellites ride the ring.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        teeth = 10
        ring_radius = max(rect.width(), rect.height()) * 0.46
        tooth = max(2.0, ring_radius * 0.10)
        pen = QPen(color, max(1.4, _param_number(params, "width", default=3) * type_scale))
        painter.setPen(pen)
        polygon = QPolygonF()
        for index in range(teeth * 2):
            angle = index * pi / teeth
            radius = (ring_radius + tooth) if index % 2 == 0 else ring_radius
            polygon.append(QPointF(
                center.x() + cos(angle) * radius,
                center.y() + sin(angle) * radius,
            ))
        painter.drawPolygon(polygon)
        painter.drawEllipse(center, ring_radius * 0.62, ring_radius * 0.62)
        painter.drawEllipse(center, ring_radius * 0.16, ring_radius * 0.16)
        pinions = max(1, min(4, int(params.get("count", 2) or 2)))
        pinion_radius = ring_radius * 0.22
        for index in range(pinions):
            angle = (seed + index * 2.4) % (2 * pi)
            orbit = ring_radius * 0.84
            pinion_center = QPointF(
                center.x() + cos(angle) * orbit,
                center.y() + sin(angle) * orbit * 0.82,
            )
            pinion = QPolygonF()
            for tooth_index in range(14):
                pinion_angle = tooth_index * pi / 7
                factor = 1.18 if tooth_index % 2 == 0 else 1.0
                pinion.append(QPointF(
                    pinion_center.x() + cos(pinion_angle) * pinion_radius * factor,
                    pinion_center.y() + sin(pinion_angle) * pinion_radius * factor,
                ))
            painter.drawPolygon(pinion)
            painter.drawEllipse(pinion_center, pinion_radius * 0.3, pinion_radius * 0.3)
    elif primitive == "RIVETS":
        # Bolts marching along the composition border, like a riveted plate.
        count = max(4, min(16, int(params.get("count", 6) or 6)))
        size = max(1.6, _param_number(params, "size", default=5) * type_scale)
        painter.setPen(QPen(_color(params.get("outlineColor"), "#66FFFFFF"), max(0.7, size * 0.22)))
        per_side = max(1, count // 2)
        for index in range(per_side):
            ratio = (index + 1) / (per_side + 1)
            for x, y in (
                (rect.left() + ratio * rect.width(), rect.top()),
                (rect.left() + ratio * rect.width(), rect.bottom()),
            ):
                painter.drawEllipse(QPointF(x, y), size, size)
        for y in (rect.top(), rect.bottom()):
            painter.drawEllipse(QPointF(rect.left(), y), size, size)
            painter.drawEllipse(QPointF(rect.right(), y), size, size)
    elif primitive == "GAUGE":
        # Steam-pressure dial centered on the pivot: sweep arc, ticks, needle.
        dial_radius = max(10.0, _param_number(params, "size", default=64) * type_scale)
        painter.setPen(QPen(color, max(1.4, dial_radius * 0.05)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        start_angle, span = 225 * 16, -270 * 16
        painter.drawArc(
            QRectF(center.x() - dial_radius, center.y() - dial_radius,
                   dial_radius * 2, dial_radius * 2),
            start_angle, span,
        )
        if bool(params.get("ticks", True)):
            for index in range(9):
                angle = pi * (1.25 - index * 0.75 / 8)
                inner = dial_radius * 0.86
                outer = dial_radius * 0.97
                painter.drawLine(
                    QPointF(center.x() + cos(angle) * inner, center.y() - sin(angle) * inner),
                    QPointF(center.x() + cos(angle) * outer, center.y() - sin(angle) * outer),
                )
        needle = _color(params.get("needleColor"), "#FFFFF3D6")
        painter.setPen(QPen(needle, max(1.6, dial_radius * 0.06)))
        painter.drawLine(
            center,
            QPointF(center.x() + dial_radius * 0.8, center.y() - dial_radius * 0.8),
        )
        painter.setBrush(needle)
        painter.drawEllipse(center, dial_radius * 0.07, dial_radius * 0.07)
    elif primitive == "PIPES":
        # Industrial pipe rails with flange rings above/below the composition.
        count = max(1, min(3, int(params.get("count", 2) or 2)))
        thickness = max(2.5, _param_number(params, "thickness", default=6) * type_scale)
        pen = QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        for index in range(count):
            offset = thickness * (0.8 + index * 1.3)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(rect.left() - thickness, rect.top() - offset),
                QPointF(rect.right() + thickness, rect.top() - offset),
            )
        flange = QPen(_color(params.get("flangeColor") or params.get("color"), "#FFC9971F"),
                      thickness * 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        painter.setPen(flange)
        flange_x = rect.left() + rect.width() * 0.5
        painter.drawLine(QPointF(flange_x, rect.top() - thickness * 1.4),
                         QPointF(flange_x, rect.top() - thickness * 1.4))
    elif primitive == "STEAM":
        # Soft vapor puffs near the bottom edge; opacity/y tracks drift them.
        count = max(3, min(9, int(params.get("count", 5) or 5)))
        puff_size = max(8.0, _param_number(params, "size", default=26) * type_scale)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(count):
            ratio = ((seed * 17 + index * 31) % 89) / 89.0
            x = rect.left() + ratio * rect.width()
            y = rect.bottom() - abs(sin((seed + index) * 1.7)) * rect.height() * 0.5
            radius = puff_size * (0.7 + 0.5 * abs(sin((seed + index) * 2.3)))
            gradient = QRadialGradient(QPointF(x, y), radius)
            gradient.setColorAt(0.0, color)
            gradient.setColorAt(1.0, QColorConstants.Transparent)
            painter.setBrush(QBrush(gradient))
            painter.drawEllipse(QPointF(x, y), radius, radius)


_BACK_DECORATIONS = frozenset({"IMPACT_RAYS", "SPEED_LINES", "SHARDS", "ACCENT_BARS", "CROSSHAIR", "INK_SPLAT", "FLOAT_GLYPHS", "PARTICLES", "ARROWS", "DATA_BARS", "GEARS", "GAUGE", "PIPES"})
_FRONT_DECORATIONS = frozenset({"HALFTONE", "SCANLINES", "PIXEL_TILES", "SCAN_SWEEP", "RIVETS", "STEAM"})


def _draw_graph_backdrop(
    painter: QPainter,
    bounds: QRectF,
    graph: VisualDesignGraph,
    type_scale: float,
    layer_ids: frozenset[str] | None = None,
) -> None:
    for layer in graph.decoration_layers:
        if (
            (layer_ids is None or layer.id in layer_ids)
            and layer.primitive in _BACK_DECORATIONS
        ):
            _draw_decoration(
                painter, bounds, layer.primitive, layer.params, layer.seed, type_scale
            )
    if layer_ids is None or graph.panel_layer.id in layer_ids:
        _draw_panel(painter, bounds, graph, type_scale)
    for layer in graph.decoration_layers:
        if (
            (layer_ids is None or layer.id in layer_ids)
            and layer.primitive in _FRONT_DECORATIONS
        ):
            _draw_decoration(
                painter, bounds, layer.primitive, layer.params, layer.seed, type_scale
            )


def render_live_snapshot(
    snapshot: VisualCueSnapshot,
    *,
    width: int,
    height: int,
    device_pixel_ratio: float = 1.0,
    layers: frozenset[str] | None = None,
    graph_layer_ids: frozenset[str] | None = None,
) -> QImage:
    """Render an immediately correct gradient/layout approximation."""
    dpr = max(0.5, float(device_pixel_ratio))
    logical_width = max(1, int(width))
    logical_height = max(1, int(height))
    image = QImage(
        max(1, round(logical_width * dpr)),
        max(1, round(logical_height * dpr)),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)

    scale_x = logical_width / max(1.0, float(snapshot.playres_x))
    scale_y = logical_height / max(1.0, float(snapshot.playres_y))
    type_scale = scale_x
    font = QFont(snapshot.font_family)
    font.setPixelSize(max(1, round(float(snapshot.font_size) * type_scale)))
    font.setWeight(QFont.Weight(max(1, min(1000, int(snapshot.font_weight)))))
    face = getattr(snapshot,'resolved_caption',None)
    if face is not None:
        font.setStyleName(face.style.font_style_name)
    font.setItalic(bool(snapshot.italic))
    font.setLetterSpacing(
        QFont.SpacingType.AbsoluteSpacing,
        float(snapshot.letter_spacing) * type_scale,
    )
    metrics = QFontMetricsF(font)
    line_height = max(1.0, metrics.height())
    path = QPainterPath()
    lines=str(snapshot.text).split('\n') or ['']
    widths=[metrics.horizontalAdvance(line) for line in lines]
    widest=max(widths,default=0.)
    for index,line in enumerate(lines):
        offset=(widest-widths[index])*float(snapshot.anchor_x)
        path.addText(QPointF(offset, metrics.ascent() + index * line_height), font, line or ' ')
    bounds = path.boundingRect()
    local_x = -bounds.left() - bounds.width() * float(snapshot.anchor_x)
    local_y = -bounds.top() - bounds.height() * float(snapshot.anchor_y)
    path.translate(local_x, local_y)
    local_bounds = path.boundingRect()

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.translate(
        float(snapshot.position_x) * scale_x,
        float(snapshot.position_y) * scale_y,
    )
    painter.rotate(float(snapshot.rotation))
    painter.scale(float(snapshot.scale_x), float(snapshot.scale_y))

    graph = _graph_for_snapshot(snapshot)
    all_layers = layers is None
    backdrop_layer = all_layers or "backdrop" in layers
    effects_layer = all_layers or "effects" in layers
    text_layer = all_layers or "text" in layers
    if graph is not None and backdrop_layer:
        _draw_graph_backdrop(
            painter, local_bounds, graph, type_scale,
            layer_ids=graph_layer_ids,
        )
    background = snapshot.style_recipe.get("background", {}) if isinstance(snapshot.style_recipe, Mapping) else {}
    if graph is None and backdrop_layer and isinstance(background, Mapping) and bool(background.get("enabled", False)):
        padding = _number(background, "padding", default=8.0) * type_scale
        radius = _number(background, "radius", "borderRadius", default=6.0) * type_scale
        opacity = _number(background, "opacity", default=1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(background.get("color"), "#99000000", opacity=opacity))
        painter.drawRoundedRect(local_bounds.adjusted(-padding, -padding, padding, padding), radius, radius)

    glow = snapshot.glow if isinstance(snapshot.glow, Mapping) else {}
    if effects_layer and glow and bool(glow.get("enabled", _number(glow, "strength", default=0.0) > 0.0)):
        _draw_soft_path(
            painter,
            path,
            color=_color(
                glow.get("color"), "#FFFFFFFF",
                opacity=_number(glow, "opacity", default=0.45),
            ),
            radius=max(0.6, _number(glow, "radius", "blur", "strength", default=4.0) * type_scale * 2.2),
            spread=_number(glow, "spread", default=0.0) * type_scale,
            fill_core=False,
            intensity=max(1.0, _number(glow, "intensity", default=1.0)),
        )

    shadow = snapshot.shadow if isinstance(snapshot.shadow, Mapping) else {}
    if effects_layer and shadow and bool(shadow.get("enabled", _number(shadow, "strength", default=0.0) > 0.0)):
        opacity = _number(shadow, "opacity", default=min(0.78, _number(shadow, "strength", default=1.0) * 0.24))
        offset_x = _number(shadow, "offset_x", "offsetX", default=_number(shadow, "strength", default=1.0)) * type_scale
        offset_y = _number(shadow, "offset_y", "offsetY", default=_number(shadow, "strength", default=1.0)) * type_scale
        shadow_path = QPainterPath(path)
        shadow_path.translate(offset_x, offset_y)
        _draw_shadow_path(
            painter,
            shadow_path,
            color=_color(shadow.get("color"), "#FF000000", opacity=opacity),
            radius=max(
                0.0,
                _number(shadow, "blur_radius", "blur", default=0.0) * type_scale,
            ),
            spread=_number(shadow, "spread", default=0.0) * type_scale,
            fill_core=True,
        )

    if text_layer:
        strokes = [item for item in snapshot.strokes if isinstance(item, Mapping)]
        for stroke in reversed(strokes):
            alignment = str(stroke.get("alignment") or "OUTSIDE").upper()
            if alignment != "OUTSIDE":
                raise ValueError(f"unsupported LIVE stroke alignment: {alignment}")
            width_px = _number(stroke, "width", "size", default=0.0) * type_scale
            if width_px <= 0:
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color(
                stroke.get("color"),
                opacity=_number(stroke, "opacity", default=1.0),
            ))
            painter.drawPath(outside_stroke_ring(path, width_px))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(resolve_fill_brush(snapshot.fill, local_bounds))
        painter.drawPath(path)
    painter.end()
    return image


def render_live_layers(
    snapshot: VisualCueSnapshot,
    *,
    width: int,
    height: int,
    device_pixel_ratio: float = 1.0,
) -> dict[str, QImage]:
    """Compile graph pixels once into separately cacheable compositing layers."""
    graph = _graph_for_snapshot(snapshot)
    if graph is None:
        return {"composite": render_live_snapshot(
            snapshot,
            width=width,
            height=height,
            device_pixel_ratio=device_pixel_ratio,
        )}
    result: dict[str, QImage] = {}
    back_layers = [
        item for item in graph.decoration_layers
        if item.primitive in _BACK_DECORATIONS
    ]
    front_layers = [
        item for item in graph.decoration_layers
        if item.primitive in _FRONT_DECORATIONS
    ]
    for layer in back_layers:
        result[layer.id] = render_live_snapshot(
            snapshot, width=width, height=height, device_pixel_ratio=device_pixel_ratio,
            layers=frozenset({"backdrop"}), graph_layer_ids=frozenset({layer.id}),
        )
    result[graph.panel_layer.id] = render_live_snapshot(
        snapshot, width=width, height=height, device_pixel_ratio=device_pixel_ratio,
        layers=frozenset({"backdrop"}), graph_layer_ids=frozenset({graph.panel_layer.id}),
    )
    for layer in front_layers:
        result[layer.id] = render_live_snapshot(
            snapshot, width=width, height=height, device_pixel_ratio=device_pixel_ratio,
            layers=frozenset({"backdrop"}), graph_layer_ids=frozenset({layer.id}),
        )
    result["effects"] = render_live_snapshot(
            snapshot, width=width, height=height,
            device_pixel_ratio=device_pixel_ratio, layers=frozenset({"effects"}),
        )
    result[graph.text_layer.id] = render_live_snapshot(
            snapshot, width=width, height=height,
            device_pixel_ratio=device_pixel_ratio, layers=frozenset({"text"}),
        )
    source = next((image for image in result.values() if not image.isNull()), QImage())
    return LiveLayerImages(result, canvas_size=source.size(), snapshot=snapshot)


def _blurred_layer(image: QImage, radius_px: float) -> QImage:
    """Cheap continuous blur: bilinear down/up-scale around the radius."""
    if image.isNull() or radius_px <= 0.5:
        return image
    factor = max(2.0, min(8.0, radius_px))
    small = image.scaled(
        max(1, round(image.width() / factor)),
        max(1, round(image.height() / factor)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return small.scaled(
        image.width(), image.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def composite_live_scene_layers(
    layers: Mapping[str, QImage],
    scene: CompiledLiveScene,
    relative_ms: int,
    *,
    pivot: QPointF | None = None,
) -> tuple[QImage, object]:
    """Composite activation-time rasters using numeric layer samples only.

    Transforms pivot around the subtitle composition origin, never the
    video-frame center. Group tracks multiply onto each layer.
    """
    source = next((image for image in layers.values() if not image.isNull()), QImage())
    if source.isNull():
        return source, scene.sample(relative_ms)
    sample = scene.sample(relative_ms)
    result = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
    dpr = float(source.devicePixelRatio() or 1.0)
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    origin = getattr(layers, "origin", QPoint())
    if pivot is None:
        pivot = QPointF(
            (source.width() / 2.0 - origin.x()) / dpr,
            (source.height() / 2.0 - origin.y()) / dpr,
        )
    group = sample.values.get("group", {})
    group_scale = float(group.get("scale", 1.0) or 1.0)
    group_x = float(group.get("x", 0.0) or 0.0)
    group_y = float(group.get("y", 0.0) or 0.0)
    group_rotation = float(group.get("rotation", 0.0) or 0.0)
    group_opacity = float(group.get("opacity", 1.0))
    text_id = scene.graph.text_layer.id
    # Animated tracking (letter-spacing) redraws the text raster; a static
    # per-layer cache cannot express it. The snapshot rides on LiveLayerImages.
    snapshot = getattr(layers, "snapshot", None)
    last_tracking = getattr(layers, "last_tracking", None)
    tracking_value = float(sample.values.get(text_id, {}).get("tracking", 0.0) or 0.0)
    if (
        snapshot is not None
        and text_id in layers
        and (last_tracking is None or abs(last_tracking - tracking_value) > 0.75)
    ):
        try:
            from dataclasses import replace as _replace

            redraw = render_live_snapshot(
                _replace(snapshot, letter_spacing=float(snapshot.letter_spacing) + tracking_value),
                width=max(1, round(source.width() / dpr)),
                height=max(1, round(source.height() / dpr)),
                device_pixel_ratio=dpr,
                layers=frozenset({"text"}),
            )
            if not redraw.isNull():
                layers[text_id] = redraw
                # Glyph effects are part of the same text binding. Tracking
                # changes must move the shadow/glow with the new glyph paths.
                layers['effects'] = render_live_snapshot(
                    _replace(snapshot, letter_spacing=float(snapshot.letter_spacing) + tracking_value),
                    width=max(1,round(source.width()/dpr)),height=max(1,round(source.height()/dpr)),
                    device_pixel_ratio=dpr,layers=frozenset({'effects'}),
                )
            try:
                layers.last_tracking = tracking_value  # type: ignore[attr-defined]
            except AttributeError:
                pass
        except (RuntimeError, TypeError, ValueError):
            pass
    for layer_id, image in layers.items():
        if image.isNull():
            continue
        target = text_id if layer_id == "effects" else layer_id
        values = sample.values.get(target, {})
        scale = float(values.get(
            "scale",
            values.get("burst_scale", values.get("ray_scale", 1.0)),
        ))
        scale_x = float(values.get("scale_x", scale)) * group_scale
        scale_y = float(values.get("scale_y", scale)) * group_scale
        x = float(values.get("x", 0.0)) + group_x
        y = float(values.get("y", 0.0)) + group_y
        rotation = float(values.get("rotation", 0.0)) + group_rotation
        opacity = max(0.0, min(1.0, float(values.get("opacity", 1.0)) * group_opacity))
        blur_px = max(0.0, min(24.0, float(values.get("blur", 0.0))))
        if blur_px > 0.5:
            image = _blurred_layer(image, blur_px)
        # A sampled 0.0 is a designed value, not "missing": never coerce it
        # back to the default through a boolean `or` (the classic trap that
        # made char_reveal=0 show a fully revealed first frame).
        mask_reveal = max(0.0, min(1.0, float(values.get("mask_reveal", 1.0))))
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(pivot.x() + x, pivot.y() + y)
        if rotation:
            painter.rotate(rotation)
        painter.scale(scale_x, scale_y)
        painter.translate(-pivot)
        if mask_reveal < 0.999:
            # Directional wipe: clip any layer raster by the revealed width.
            painter.setClipRect(QRectF(
                0.0, 0.0,
                max(0.0, image.width() / dpr * mask_reveal),
                image.height() / dpr,
            ))
        if layer_id == text_id:
            # Per-character reveal: clip the text raster by the revealed
            # fraction so stagger entrances read as glyph-by-glyph.
            reveal = max(0.0, min(1.0, float(values.get("char_reveal", 1.0))))
            if reveal < 0.999:
                painter.setClipRect(QRectF(
                    0.0, 0.0,
                    max(0.0, image.width() / dpr * reveal),
                    image.height() / dpr,
                ), Qt.ClipOperation.IntersectClip)
        painter.drawImage(0, 0, image)
        painter.restore()
    painter.end()
    if any(
        effect.primitive in {"GLITCH", "RGB_SPLIT"}
        for effect in scene.graph.effect_layers
    ):
        result, _ = render_live_scene_frame(result, scene, relative_ms)
    return result, sample


def _tinted_source(source: QImage, color: QColor) -> QImage:
    tinted = source.copy()
    painter = QPainter(tinted)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted


def render_live_scene_frame(
    source: QImage,
    scene: CompiledLiveScene,
    relative_ms: int,
) -> tuple[QImage, object]:
    """Sample a compiled scene and composite effects without glyph layout."""
    sample = scene.sample(relative_ms)
    glitch = next(
        (
            item for item in scene.graph.effect_layers
            if item.primitive in {"GLITCH", "RGB_SPLIT"}
        ),
        None,
    )
    if glitch is None:
        return source, sample
    rgb_offset = sample.value(glitch.id, "rgb_offset", 0.0)
    slice_offset = sample.value(glitch.id, "slice_offset", 0.0)
    flicker = sample.value(glitch.id, "flicker", 0.0)
    if abs(rgb_offset) < 0.05 and abs(slice_offset) < 0.05 and flicker < 0.01:
        return source, sample
    dpr = float(source.devicePixelRatio() or 1.0)
    result = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    offset = round(rgb_offset * dpr)
    if offset:
        split_alpha = 0.48 if glitch.primitive == "GLITCH" else 0.34
        painter.setOpacity(split_alpha)
        painter.drawImage(offset, 0, _tinted_source(source, QColor("#FFFF365F")))
        painter.drawImage(-offset, 0, _tinted_source(source, QColor("#FF20E8FF")))
    painter.setOpacity(max(0.0, min(1.0, 1.0 - flicker)))
    painter.drawImage(0, 0, source)
    slice_count = max(1, min(16, int(glitch.params.get("sliceCount", 6) or 6)))
    band_height = max(1, source.height() // (slice_count * 2 + 1))
    displacement = round(slice_offset * dpr)
    if displacement:
        painter.setOpacity(0.92)
        for index in range(slice_count):
            y = int((index + 1) * source.height() / (slice_count + 1))
            source_rect = source.rect().adjusted(0, y, 0, -(source.height() - y - band_height))
            painter.drawImage(source_rect.translated(displacement if index % 2 == 0 else -displacement, 0), source, source_rect)
    painter.end()
    return result, sample


__all__ = [
    "LIVE_RENDERER_VERSION", "LiveLayerImages", "composite_live_scene_layers",
    "composition_pivot_for_snapshot", "crop_live_layers", "render_live_layers",
    "render_live_scene_frame", "render_live_snapshot",
]
