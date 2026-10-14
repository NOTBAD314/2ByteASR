"""Draggable subtitle position overlay over the video canvas."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QWidget

from .studio_geometry import SubtitleCoordinateMapper
from .ui_theme import theme_definition

class SubtitlePositionOverlay(QWidget):
    """Drag a subtitle proxy in video space without touching mpv rendering."""

    HANDLE_VISUAL_SIZE = 11.0
    HANDLE_HOVER_SIZE = 13.0
    HANDLE_HIT_SIZE = 16.0
    SELECTION_PADDING = 7.0
    # libass/FreeType's visible glyph em is smaller than the ASS line-size
    # value. This keeps Qt's proxy bounds close without introducing a position
    # offset; the ASS anchor remains exact and only the conservative glyph
    # envelope is normalized.
    # Measure the same nominal pixel size used by the ASS/FreeType contract;
    # the box represents content bounds, while visual effects are separate.
    ASS_VISIBLE_EM_FACTOR = 1.0

    position_moved = Signal(int, int)
    position_committed = Signal(int, int)
    position_cancelled = Signal()
    font_size_preview = Signal(float)
    font_size_committed = Signal(float)
    doubleClickRequested = Signal()
    interaction_started = Signal()

    def __init__(self, parent=None, *, top_level: bool = False):
        super().__init__(parent)
        self._top_level_canvas = bool(top_level)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # Keep the editor as a regular Qt child. Making this full-size overlay
        # native creates a second HWND over mpv's native rendering surface on
        # Windows, which can hide the video and libass output entirely.
        self.setAutoFillBackground(False)
        if self._top_level_canvas:
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        palette = self.palette()
        palette.setColor(palette.ColorRole.Window, QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.play_res_x = 1920
        self.play_res_y = 1080
        self.video_width = 1920
        self.video_height = 1080
        self._video_size_explicit = False
        self.position_x = 960
        self.position_y = 960
        self.text = "当前字幕"
        self.font_family = "Microsoft YaHei UI"
        self.letter_spacing = 0.0
        self.font_size = 52.0
        self.alignment = 2
        self.scale_x = 100.0
        self.scale_y = 100.0
        self.outline_width = 3.0
        self.strokes: list[dict] | None = None
        self.shadow = 1.0
        self.margin_l = 40
        self.margin_r = 40
        self.bold = False
        self.italic = False
        self.underline = False
        self._dragging = False
        self._resize_handle = ""
        self._hover_handle = ""
        self._composition_overflow = 0.0
        self._drag_origin = QPoint()
        self._origin_position = (self.position_x, self.position_y)
        self._origin_font_size = self.font_size
        self._origin_bounds = None
        self._snap_enabled = True
        self._inline_editing = False
        self._requires_measured_bounds = False
        self._measured_bounds = None
        self.geometry_diagnostics = {}
        self._compositor_publish_pending = False
        self._compositor_last_attempt: tuple[object, ...] | None = None
        self.hide()

    def sync_to_video(self, video: QWidget) -> None:
        """Keep the interaction surface aligned with the Qt video surface.

        IMPORTANT: The overlay canvas must ALWAYS cover the *full* video widget
        (the actual interactive viewport), not the current subtitle bbox and
        not only the letterboxed content rect. Drawing the subtitle handles
        inside a smaller rect causes the box to be clipped when the subtitle
        is dragged outside that sub-rect.
        """
        if self._top_level_canvas:
            origin = video.mapToGlobal(QPoint(0, 0))
            self.setGeometry(QRect(origin, video.size()))
        else:
            # Restore pre-P25.2.7 behavior for native mpv compatibility.
            # The overlay is sized to the video widget rect (the interactive viewport).
            # Internal drawing still uses _content_rect() + _subtitle_rect() so the box
            # follows the cue while the canvas itself covers the viewport.
            self.setGeometry(video.rect())
        self.raise_()

    def set_video_position(self, x: int, y: int, play_res_x: int, play_res_y: int) -> None:
        self.play_res_x = max(1, int(play_res_x))
        self.play_res_y = max(1, int(play_res_y))
        if not self._video_size_explicit:
            self.video_width = self.play_res_x
            self.video_height = self.play_res_y
        self.position_x = min(self.play_res_x, max(0, int(x)))
        self.position_y = min(self.play_res_y, max(0, int(y)))
        self.update()

    def set_video_size(self, width: int, height: int) -> None:
        """Set mpv's displayed video aspect; zero keeps the PlayRes fallback."""
        self._video_size_explicit = int(width or 0) > 0 and int(height or 0) > 0
        self.video_width = max(1, int(width or self.play_res_x))
        self.video_height = max(1, int(height or self.play_res_y))
        self.update()

    def set_text(self, value: str) -> None:
        self.text = str(value or "当前字幕")
        self.update()

    def set_font_size(self, value: float) -> None:
        self.font_size = max(1.0, float(value))
        self.update()

    def set_font_spec(
        self,
        family: str,
        size: float,
        spacing: float = 0.0,
        alignment: int = 2,
        *,
        scale_x: float = 100.0,
        scale_y: float = 100.0,
        outline_width: float = 3.0,
        shadow: float = 1.0,
        margin_l: int = 40,
        margin_r: int = 40,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        strokes: list[dict] | None = None,
    ) -> None:
        self.font_family = str(family or "Microsoft YaHei UI")
        self.font_size = max(1.0, float(size))
        self.letter_spacing = float(spacing or 0.0)
        self.alignment = min(9, max(1, int(alignment)))
        self.scale_x = max(1.0, float(scale_x))
        self.scale_y = max(1.0, float(scale_y))
        self.outline_width = max(0.0, float(outline_width))
        self.strokes = [dict(item) for item in strokes] if isinstance(strokes, list) else None
        self.shadow = max(0.0, float(shadow))
        self.margin_l = max(0, int(margin_l))
        self.margin_r = max(0, int(margin_r))
        self.bold = bool(bold)
        self.italic = bool(italic)
        self.underline = bool(underline)
        self.update()

    def _max_stroke_width(self) -> float:
        if self.strokes:
            return max((max(0.0, float(item.get("width", 0) or 0)) for item in self.strokes), default=0.0)
        return self.outline_width

    def _mapper(self) -> SubtitleCoordinateMapper:
        return SubtitleCoordinateMapper(
            QRectF(self.rect()),
            self.play_res_x,
            self.play_res_y,
            self.video_width,
            self.video_height,
        )

    def _content_rect(self) -> QRectF:
        return self._mapper().video_content_rect

    def _screen_point(self) -> QPoint:
        return self._mapper().subtitle_to_preview(
            QPointF(self.position_x, self.position_y)
        ).toPoint()

    def _video_point(self, point: QPoint) -> tuple[int, int]:
        mapper = self._mapper()
        subtitle = mapper.preview_to_subtitle(QPointF(point))
        x = round(subtitle.x())
        y = round(subtitle.y())
        snap_x = self.play_res_x // 2
        snap_y = round(self.play_res_y * 0.9)
        threshold_x = round(14 / max(mapper.scale_x, 1e-12))
        threshold_y = round(14 / max(mapper.scale_y, 1e-12))
        if self._snap_enabled and abs(x - snap_x) <= threshold_x:
            x = snap_x
        if self._snap_enabled and abs(y - snap_y) <= threshold_y:
            y = snap_y
        return min(self.play_res_x, max(0, x)), min(self.play_res_y, max(0, y))

    def _draw_transform_visual(self, painter: QPainter) -> None:
        from .theme_manager import theme_key

        theme = theme_definition(theme_key())
        accent = QColor(theme.media_accent)  # readable over the video in every theme
        accent_dark = QColor(theme.accent_hover)
        if self._inline_editing or (self._requires_measured_bounds and self._measured_bounds is None):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._subtitle_rect()

        shadow = QColor(theme.app_background)
        shadow.setAlpha(190)
        # The full rectangle remains the interaction/hit-test region, but the
        # visual interior must not tint or obscure the authoritative glyphs.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(shadow, 4.0))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(accent, 2.0))
        painter.drawRoundedRect(rect, 4, 4)

        painter.setPen(QPen(accent_dark, 1.2))
        for name, center in self._handle_centers(rect).items():
            hovered = name == self._hover_handle
            size = self.HANDLE_HOVER_SIZE if hovered else self.HANDLE_VISUAL_SIZE
            handle = QRectF(
                center.x() - size / 2,
                center.y() - size / 2,
                size,
                size,
            )
            painter.setBrush(
                QColor(theme.accent_soft)
                if hovered
                else accent
            )
            painter.drawRoundedRect(handle, 2.0, 2.0)

        anchor = QPointF(self._screen_point())
        painter.setBrush(QColor(theme.accent_soft))
        painter.setPen(QPen(accent_dark, 1.4))
        painter.drawEllipse(anchor, 4.0, 4.0)
        painter.drawLine(
            QPointF(anchor.x() - 6, anchor.y()),
            QPointF(anchor.x() + 6, anchor.y()),
        )
        painter.drawLine(
            QPointF(anchor.x(), anchor.y() - 6),
            QPointF(anchor.x(), anchor.y() + 6),
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        owner = self.parentWidget()
        controller = getattr(owner, 'controller', None)
        if getattr(controller, 'backend', '') != 'qt-video-sink':
            # Windows mpv draws outside Qt's backing store. Its overlay
            # keeps the existing transparent replacement contract.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        # Mac video is a lower Qt child in the SAME backing store. Source
        # transparency here erases its real pixels; draw only the handles.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self._draw_transform_visual(painter)
        painter.end()
        self._schedule_compositor_publish()

    def _compositor_signature(self) -> tuple[object, ...]:
        return (
            self.position_x,
            self.position_y,
            round(self.font_size, 2),
            self._hover_handle,
            self._inline_editing,
            tuple(self._measured_bounds.getRect()) if self._measured_bounds is not None else None,
            tuple(self.geometry().getRect()),
        )

    def _schedule_compositor_publish(self, *, force: bool = False) -> None:
        if self._compositor_publish_pending or not self.isVisible():
            return
        signature = self._compositor_signature()
        if not force and signature == self._compositor_last_attempt:
            return
        self._compositor_last_attempt = signature
        self._compositor_publish_pending = True
        QTimer.singleShot(0, self, self._publish_to_mpv)

    def _publish_to_mpv(self) -> None:
        self._compositor_publish_pending = False
        owner = self.parentWidget()
        publisher = getattr(owner, "publish_compositor_overlay", None)
        if not callable(publisher) or not self.isVisible() or self._inline_editing:
            return
        bounds = self._subtitle_rect().adjusted(-12, -12, 12, 12).toAlignedRect()
        bounds = bounds.intersected(self.rect())
        if bounds.isEmpty():
            return
        image = QImage(bounds.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.translate(-bounds.x(), -bounds.y())
        self._draw_transform_visual(painter)
        painter.end()
        publisher(owner.TRANSFORM_OVERLAY_ID, image, bounds, context={
            "renderer_path": "TRANSFORM", "caller": "SubtitlePositionOverlay._publish_to_mpv",
            "reason": "transform_update", "cue_active": False, "scene_alive": True, "opacity": 1.0,
        })

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_compositor_publish(force=True)

    def hideEvent(self, event) -> None:
        owner = self.parentWidget()
        remover = getattr(owner, "remove_compositor_overlay", None)
        if callable(remover):
            remover(owner.TRANSFORM_OVERLAY_ID, context={
                "renderer_path": "TRANSFORM", "caller": "SubtitlePositionOverlay.hideEvent",
                "reason": "transform_hide", "cue_active": False,
            })
        self._compositor_publish_pending = False
        self._compositor_last_attempt = None
        super().hideEvent(event)

    def _rendered_text_rect(self) -> QRectF:
        """Conservative Qt approximation of the libass-rendered text block."""
        if self._measured_bounds is not None:
            return QRectF(self._measured_bounds)
        mapper = self._mapper()
        font = QFont(self.font_family)
        font.setPixelSize(max(1, round(
            self.font_size
            * mapper.scale_y
            * self.scale_y
            / 100.0
            * self.ASS_VISIBLE_EM_FACTOR
        )))
        font.setBold(self.bold)
        font.setItalic(self.italic)
        font.setUnderline(self.underline)
        font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing,
            self.letter_spacing * mapper.scale_x,
        )
        metrics = QFontMetricsF(font)
        available_width = max(
            1.0,
            self._content_rect().width()
            - (self.margin_l + self.margin_r) * mapper.scale_x,
        )
        horizontal_stretch = self.scale_x / max(self.scale_y, 1e-12)
        layout_width = max(1.0, available_width / max(horizontal_stretch, 1e-12))
        text = self.text.replace(r"\N", "\n")
        width = 1.0
        height = 0.0
        for paragraph in text.split("\n"):
            layout = QTextLayout(paragraph or " ", font)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            paragraph_height = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(layout_width)
                width = max(width, line.naturalTextWidth() * horizontal_stretch)
                paragraph_height += line.height()
            layout.endLayout()
            height += paragraph_height or metrics.height()
        # Transform handles are CONTENT BOUNDS: glyphs plus stroke only. A
        # large/soft shadow must not make the drag box jump or grow.
        visual_outset = self._max_stroke_width() * max(mapper.scale_x, mapper.scale_y)
        width += visual_outset * 2
        height += visual_outset * 2
        point = self._screen_point()
        column = (self.alignment - 1) % 3
        row = (self.alignment - 1) // 3
        left = (point.x(), point.x() - width / 2, point.x() - width)[column]
        top = (point.y() - height, point.y() - height / 2, point.y())[row]
        return QRectF(left, top, width, height)

    def _visual_overflow_rect(self) -> QRectF:
        """Return effects-inclusive bounds for diagnostics/compositing only."""
        content = self._rendered_text_rect()
        mapper = self._mapper()
        scale = max(mapper.scale_x, mapper.scale_y)
        blur = max(0.0, float(self.shadow or 0.0)) * scale
        return content.adjusted(-blur, -blur, blur + blur, blur + blur)

    def set_composition_overflow(self, overflow: float) -> None:
        """Expand Transform handles to VisualCompositionBounds, not text-only."""

        value = max(0.0, min(1.2, float(overflow or 0.0)))
        if abs(value - self._composition_overflow) < 0.01:
            return
        self._composition_overflow = value
        self.update()

    def _subtitle_rect(self) -> QRectF:
        rect = self._rendered_text_rect()
        if self._requires_measured_bounds:
            return rect.adjusted(-4,-4,4,4) if self._measured_bounds is not None else QRectF()
        extra_x = rect.width() * self._composition_overflow
        extra_y = rect.height() * self._composition_overflow
        pad = self.SELECTION_PADDING
        return rect.adjusted(
            -pad - extra_x,
            -pad - extra_y,
            pad + extra_x,
            pad + extra_y,
        )

    def set_measured_bounds(self,rect):
        self._measured_bounds=QRectF(rect) if rect is not None else None
        if rect is None:
            owner=self.parentWidget()
            remover=getattr(owner,'remove_compositor_overlay',None)
            if callable(remover):remover(owner.TRANSFORM_OVERLAY_ID)
        self.update()
        self._schedule_compositor_publish(force=True)

    @staticmethod
    def _handle_centers(rect: QRectF) -> dict[str, QPointF]:
        return {
            "tl": rect.topLeft(),
            "t": QPointF(rect.center().x(), rect.top()),
            "tr": rect.topRight(),
            "r": QPointF(rect.right(), rect.center().y()),
            "br": rect.bottomRight(),
            "b": QPointF(rect.center().x(), rect.bottom()),
            "bl": rect.bottomLeft(),
            "l": QPointF(rect.left(), rect.center().y()),
        }

    def _handle_at(self, point: QPoint) -> str:
        rect = self._subtitle_rect()
        if rect.isEmpty():return ""
        half = self.HANDLE_HIT_SIZE / 2.0
        for name, center in self._handle_centers(rect).items():
            if QRectF(center.x() - half, center.y() - half, half * 2, half * 2).contains(point):
                return name
        return ""

    @staticmethod
    def _cursor_for_handle(handle: str) -> Qt.CursorShape:
        if handle in {"tl", "br"}:
            return Qt.CursorShape.SizeFDiagCursor
        if handle in {"tr", "bl"}:
            return Qt.CursorShape.SizeBDiagCursor
        if handle in {"l", "r"}:
            return Qt.CursorShape.SizeHorCursor
        if handle in {"t", "b"}:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeAllCursor

    def _dragged_video_position(self, point: QPoint) -> tuple[int, int]:
        content = self._content_rect()
        origin_x, origin_y = self._origin_position
        anchor = QPoint(
            round(content.left() + origin_x * content.width() / self.play_res_x),
            round(content.top() + origin_y * content.height() / self.play_res_y),
        )
        return self._video_point(anchor + point - self._drag_origin)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore(); return
        point = event.position().toPoint()
        rect = self._subtitle_rect()
        resize_handle = self._handle_at(point)
        if not resize_handle and not rect.contains(point):
            event.ignore(); return
        self._dragging = True
        self.interaction_started.emit()
        self._resize_handle = resize_handle
        self._drag_origin = point
        self._origin_position = (self.position_x, self.position_y)
        self._origin_font_size = self.font_size
        self._origin_bounds = QRectF(self._measured_bounds) if self._measured_bounds is not None else None
        self._snap_enabled = not bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._resize_handle:
            self.setCursor(self._cursor_for_handle(self._resize_handle))
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            point = event.position().toPoint()
            previous = self._hover_handle
            self._hover_handle = self._handle_at(point)
            if self._hover_handle:
                self.setCursor(self._cursor_for_handle(self._hover_handle))
            elif self._subtitle_rect().contains(point):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            if previous != self._hover_handle:
                self.update()
            return
        point = event.position().toPoint()
        if self._resize_handle:
            delta_x = point.x() - self._drag_origin.x()
            delta_y = point.y() - self._drag_origin.y()
            outward_x = delta_x if "r" in self._resize_handle else -delta_x
            outward_y = delta_y if "b" in self._resize_handle else -delta_y
            if self._resize_handle in {"l", "r"}:
                delta = outward_x
            elif self._resize_handle in {"t", "b"}:
                delta = outward_y
            else:
                delta = (outward_x + outward_y) / 2
            if getattr(self,'_web_theme_transform',False) and self._origin_bounds is not None:
                # Whole-object scale: movement is proportional to the actual
                # visible artwork, independent of its CSS font-size policy.
                bounds=self._origin_bounds
                rx=1+outward_x*2/max(1,bounds.width())
                ry=1+outward_y*2/max(1,bounds.height())
                ratio=rx if self._resize_handle in {'l','r'} else ry if self._resize_handle in {'t','b'} else (
                    1+2*(outward_x*bounds.width()+outward_y*bounds.height())/max(1,bounds.width()**2+bounds.height()**2))
                ratio=max(.1,min(4,ratio))
                self.font_size=self._origin_font_size*ratio
                self._measured_bounds=QRectF(bounds.center().x()-bounds.width()*ratio/2,
                    bounds.center().y()-bounds.height()*ratio/2,bounds.width()*ratio,bounds.height()*ratio)
            else:
                self.font_size = max(8.0, min(500.0, self._origin_font_size + delta * 0.7))
            self.font_size_preview.emit(self.font_size)
        else:
            self._snap_enabled = not bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self.position_x, self.position_y = self._dragged_video_position(point)
            if self._origin_bounds is not None:
                self._measured_bounds=self._origin_bounds.translated(point-self._drag_origin)
            self.position_moved.emit(self.position_x, self.position_y)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._hover_handle = self._handle_at(event.position().toPoint())
        self.setCursor(
            self._cursor_for_handle(self._hover_handle)
            if self._hover_handle
            else Qt.CursorShape.SizeAllCursor
        )
        if self._resize_handle:
            self.font_size_committed.emit(self.font_size)
        else:
            self.position_x, self.position_y = self._dragged_video_position(
                event.position().toPoint()
            )
            self.position_moved.emit(self.position_x, self.position_y)
            self.position_committed.emit(self.position_x, self.position_y)
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._subtitle_rect().contains(event.position().toPoint()):
            self.doubleClickRequested.emit()
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._dragging:
            self._dragging = False
            self.position_x, self.position_y = self._origin_position
            self.font_size = self._origin_font_size
            self._measured_bounds = self._origin_bounds
            self.position_cancelled.emit()
            self.update(); event.accept(); return
        super().keyPressEvent(event)
