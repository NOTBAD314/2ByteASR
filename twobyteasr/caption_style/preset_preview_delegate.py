"""Visual thumbnail item delegate for the Subtitle Studio style preset picker.

Renders a cached 92x28 dark-canvas miniature preview of each style preset
(font family/weight, solid or gradient fill, single/double outline, optional
background bar, shadow and glow) alongside the preset name inside the expanded
combo popup without increasing the collapsed combo box height or touching
``QFontDatabase`` during paint.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
)

from ..design.theme_manager import theme_key
from ..design.typography import TITLE_FONT_FAMILIES, UI_FONT_FAMILIES, weighted_font
from ..design.ui_theme import blend_hex, contrast_ratio, theme_definition
from ..projects.studio_project import SubtitleStyle
from ..studio.studio_helpers import _preview_color, render_style_sample
from .style_presets import BUILTIN_PRESETS


PRESET_PREVIEW_ROLE = int(Qt.ItemDataRole.UserRole) + 31

ROW_HEIGHT = 42
CHIP_WIDTH = 92
CHIP_HEIGHT = 28
CHIP_RADIUS = 6.0
CHIP_BG_HEX = "#1e1d22"
SAMPLE_TEXT = "字幕 Abc"
DEFAULT_CACHE_LIMIT = 128

_CHIP_LEFT_PAD = 8
_CHIP_TEXT_GAP = 10
_ROW_RIGHT_PAD = 12
_STAR_SLOT_WIDTH = 18
_POPUP_CHROME_WIDTH = 28
_MIN_POPUP_WIDTH = 264
_MAX_POPUP_WIDTH = 460


@dataclass(frozen=True)
class PresetPreviewSpec:
    """Immutable snapshot of everything needed to paint one preset row."""

    preset_id: str
    name: str
    style: SubtitleStyle
    recipe: Mapping[str, Any] | None = None
    favorite: bool = False
    is_custom: bool = False
    is_ai: bool = False


class PresetPreviewCache:
    """Bounded LRU cache mapping ``(preset_id, style_digest, dpr)`` to ``QPixmap``."""

    def __init__(self, max_entries: int = DEFAULT_CACHE_LIMIT) -> None:
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple[str, str, float], QPixmap] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[str, str, float]) -> QPixmap | None:
        pixmap = self._entries.get(key)
        if pixmap is not None:
            self._entries.move_to_end(key)
            self.hits += 1
            return pixmap
        self.misses += 1
        return None

    def put(self, key: tuple[str, str, float], pixmap: QPixmap) -> None:
        self._entries[key] = pixmap
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)


def _extract_recipe_visuals(recipe: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(recipe, Mapping):
        return {}
    colors = recipe.get("colors") if isinstance(recipe.get("colors"), Mapping) else {}
    outline = recipe.get("outline") if isinstance(recipe.get("outline"), Mapping) else {}
    background = recipe.get("background") if isinstance(recipe.get("background"), Mapping) else {}
    effects = recipe.get("effects") if isinstance(recipe.get("effects"), Mapping) else {}
    result: dict[str, Any] = {}
    if "fill" in colors and colors.get("fill") is not None:
        result["fill"] = colors.get("fill")
    if "layers" in outline and isinstance(outline.get("layers"), list):
        result["layers"] = outline.get("layers")
    if "shadow" in outline and outline.get("shadow") is not None:
        result["shadow"] = outline.get("shadow")
    if background:
        result["background"] = {
            "enabled": bool(background.get("enabled", False)),
            "color": background.get("color"),
        }
    if isinstance(effects.get("glow"), Mapping):
        result["glow"] = dict(effects["glow"])
    return result


def style_preview_digest(
    style: SubtitleStyle,
    recipe: Mapping[str, Any] | None = None,
    *,
    sample_text: str = SAMPLE_TEXT,
    chip_size: tuple[int, int] = (CHIP_WIDTH, CHIP_HEIGHT),
) -> str:
    """Stable content digest for cache invalidation when a preset changes."""
    payload = {
        "font_family": str(getattr(style, "font_family", "") or ""),
        "font_size": round(float(getattr(style, "font_size", 52.0) or 52.0), 2),
        "font_weight": int(getattr(style, "font_weight", 0) or 0),
        "font_style_name": str(getattr(style, "font_style_name", "") or ""),
        "bold": bool(getattr(style, "bold", False)),
        "italic": bool(getattr(style, "italic", False)),
        "underline": bool(getattr(style, "underline", False)),
        "spacing": round(float(getattr(style, "spacing", 0.0) or 0.0), 2),
        "primary_color": str(getattr(style, "primary_color", "#FFFFFF") or "#FFFFFF"),
        "outline_color": str(getattr(style, "outline_color", "#000000") or "#000000"),
        "outline_width": round(float(getattr(style, "outline_width", 0.0) or 0.0), 2),
        "outline2_color": str(getattr(style, "outline2_color", "") or ""),
        "outline2_width": round(float(getattr(style, "outline2_width", 0.0) or 0.0), 2),
        "back_color": str(getattr(style, "back_color", "#000000") or "#000000"),
        "border_style": int(getattr(style, "border_style", 1) or 1),
        "shadow": round(float(getattr(style, "shadow", 0.0) or 0.0), 2),
        "recipe": _extract_recipe_visuals(recipe),
        "sample_text": str(sample_text),
        "chip_size": [int(chip_size[0]), int(chip_size[1])],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=10).hexdigest()


def build_preview_font(style: SubtitleStyle, pixel_size: float) -> QFont:
    """Build a safe preview ``QFont`` with ``UI_FONT_STACK`` fallback and zero GDI scans."""
    family = str(getattr(style, "font_family", "") or "").strip()
    weight_val = int(getattr(style, "font_weight", 0) or 0)
    is_heavy = (
        weight_val >= 800
        or "heavy" in family.casefold()
        or "black" in family.casefold()
    )
    is_bold = bool(getattr(style, "bold", False)) or weight_val >= 600 or is_heavy

    fallback_stack = TITLE_FONT_FAMILIES if is_heavy else UI_FONT_FAMILIES
    families: list[str] = []
    if family:
        families.append(family)
    for fallback in fallback_stack:
        if fallback not in families:
            families.append(fallback)
    for fallback in UI_FONT_FAMILIES:
        if fallback not in families:
            families.append(fallback)

    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(max(8, round(float(pixel_size))))
    if weight_val > 0:
        clamped = max(100, min(900, weight_val))
        font.setWeight(QFont.Weight(clamped))
    elif is_heavy:
        font.setWeight(QFont.Weight.ExtraBold)
    elif is_bold:
        font.setWeight(QFont.Weight.Bold)
    else:
        font.setWeight(QFont.Weight.Medium)
    font.setItalic(bool(getattr(style, "italic", False)))
    font.setUnderline(bool(getattr(style, "underline", False)))
    spacing = float(getattr(style, "spacing", 0.0) or 0.0)
    if spacing:
        scaled_spacing = max(-2.0, min(4.0, spacing * 0.22))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, scaled_spacing)
    return font


def _resolve_strokes(
    style: SubtitleStyle,
    recipe_visuals: Mapping[str, Any],
    scale_ratio: float,
) -> list[dict[str, Any]]:
    layers = recipe_visuals.get("layers")
    raw_strokes: list[Mapping[str, Any]]
    if isinstance(layers, list) and layers:
        raw_strokes = [item for item in layers if isinstance(item, Mapping)]
    else:
        raw_strokes = style.stroke_layers()

    stroke_factor = max(0.45, min(0.85, scale_ratio * 2.15))
    resolved: list[dict[str, Any]] = []
    for layer in raw_strokes:
        width = max(0.0, float(layer.get("width", 0.0) or 0.0))
        if width <= 0.0:
            continue
        color = _preview_color(layer.get("color", style.outline_color), "#FF000000")
        opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0))))
        color.setAlphaF(color.alphaF() * opacity)
        if color.alpha() <= 0:
            continue
        scaled_width = max(1.0, min(5.4, width * stroke_factor))
        resolved.append({
            "color": color.name(QColor.NameFormat.HexArgb),
            "width": scaled_width,
        })
    return resolved


def _resolve_shadow(
    style: SubtitleStyle,
    recipe_visuals: Mapping[str, Any],
) -> tuple[bool, QColor, float, float, float]:
    raw_shadow = recipe_visuals.get("shadow")
    if isinstance(raw_shadow, Mapping):
        opacity = raw_shadow.get("opacity")
        strength = max(0.0, float(raw_shadow.get("strength", raw_shadow.get("distance", 0.0)) or 0.0))
        offset_x = float(raw_shadow.get("offset_x", raw_shadow.get("offsetX", strength)) or 0.0)
        offset_y = float(raw_shadow.get("offset_y", raw_shadow.get("offsetY", strength)) or 0.0)
        blur = max(0.0, float(raw_shadow.get("blur_radius", raw_shadow.get("blur", 0.0)) or 0.0))
        if opacity is None:
            alpha = min(0.82, max(0.45, strength * 0.24)) if (strength > 0 or offset_x or offset_y or blur) else 0.0
        else:
            alpha = float(opacity or 0.0)
            if alpha > 1.0:
                alpha /= 100.0
        enabled = bool(raw_shadow.get("enabled", True)) and alpha > 0.0 and (
            offset_x != 0.0 or offset_y != 0.0 or blur > 0.0 or strength > 0.0
        )
        if not enabled:
            return False, QColor(0, 0, 0, 0), 0.0, 0.0, 0.0
        color = _preview_color(raw_shadow.get("color", "#FF000000"), "#FF000000")
        color.setAlphaF(max(0.18, min(0.9, color.alphaF() * alpha)))
        dx = max(-3.0, min(3.0, offset_x * 0.35 if abs(offset_x) > 0.01 else 0.0))
        dy = max(-3.0, min(3.0, offset_y * 0.35 if abs(offset_y) > 0.01 else 0.0))
        if dx == 0.0 and dy == 0.0 and blur > 0.0:
            dy = 1.0
        return True, color, dx, dy, min(3.0, blur * 0.2)

    scalar = max(0.0, float(getattr(style, "shadow", 0.0) or 0.0))
    if scalar <= 0.0:
        return False, QColor(0, 0, 0, 0), 0.0, 0.0, 0.0
    offset = max(1.0, min(2.6, 0.7 + scalar * 0.55))
    alpha = min(220, max(125, round(120 + scalar * 28)))
    return True, QColor(0, 0, 0, alpha), offset, offset, min(2.0, scalar * 0.35)


def _resolve_background(
    style: SubtitleStyle,
    recipe_visuals: Mapping[str, Any],
) -> tuple[bool, QColor]:
    recipe_bg = recipe_visuals.get("background")
    if isinstance(recipe_bg, Mapping) and recipe_bg.get("enabled"):
        color = _preview_color(recipe_bg.get("color", style.back_color), "#CC000000")
        if color.alpha() > 0:
            return True, color
    if int(getattr(style, "border_style", 1) or 1) == 3:
        color = _preview_color(getattr(style, "back_color", "#CC000000"), "#CC000000")
        if color.alpha() > 0:
            return True, color
    return False, QColor(0, 0, 0, 0)


def _resolve_glow(recipe_visuals: Mapping[str, Any]) -> dict[str, Any] | None:
    glow = recipe_visuals.get("glow")
    if not isinstance(glow, Mapping) or not glow.get("enabled"):
        return None
    raw_blur = max(0.0, float(glow.get("blur", glow.get("radius", glow.get("strength", 6.0))) or 0.0))
    if raw_blur <= 0.0:
        return None
    return {
        "enabled": True,
        "color": str(glow.get("color") or "#FFFF4040"),
        "blur": max(1.0, min(2.8, raw_blur * 0.24)),
        "opacity": max(0.2, min(1.0, float(glow.get("opacity", 0.85) or 0.85))),
    }


def render_preset_preview_pixmap(
    style: SubtitleStyle,
    *,
    recipe: Mapping[str, Any] | None = None,
    dpr: float = 1.0,
    width: int = CHIP_WIDTH,
    height: int = CHIP_HEIGHT,
    sample_text: str = SAMPLE_TEXT,
) -> QPixmap:
    """Render one ``92x28`` dark-video preview chip for a subtitle style preset."""
    safe_dpr = max(1.0, float(dpr or 1.0))
    logical_w = max(24, int(width))
    logical_h = max(16, int(height))
    pixmap = QPixmap(max(1, round(logical_w * safe_dpr)), max(1, round(logical_h * safe_dpr)))
    pixmap.setDevicePixelRatio(safe_dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        chip_rect = QRectF(0.5, 0.5, logical_w - 1.0, logical_h - 1.0)
        chip_path = QPainterPath()
        chip_path.addRoundedRect(chip_rect, CHIP_RADIUS, CHIP_RADIUS)
        painter.fillPath(chip_path, QColor(CHIP_BG_HEX))

        painter.save()
        painter.setClipPath(chip_path)

        recipe_visuals = _extract_recipe_visuals(recipe)
        source_size = max(8.0, float(getattr(style, "font_size", 52.0) or 52.0))
        target_px = max(10.0, min(16.5, source_size * 0.275))

        outline_pad = min(4.0, max(0.0, float(getattr(style, "outline_width", 0.0) or 0.0)) * 0.5)
        avail_w = max(12.0, logical_w - 12.0 - outline_pad)
        avail_h = max(10.0, logical_h - 6.0 - outline_pad * 0.6)

        font = build_preview_font(style, target_px)
        probe_path = QPainterPath()
        probe_path.addText(QPointF(0.0, 0.0), font, sample_text)
        bounds = probe_path.boundingRect()
        if not bounds.isEmpty() and (bounds.width() > avail_w or bounds.height() > avail_h):
            fit_scale = min(avail_w / max(1.0, bounds.width()), avail_h / max(1.0, bounds.height()))
            fitted_px = max(8.5, target_px * fit_scale * 0.96)
            font = build_preview_font(style, fitted_px)
            probe_path = QPainterPath()
            probe_path.addText(QPointF(0.0, 0.0), font, sample_text)
            bounds = probe_path.boundingRect()
            target_px = fitted_px

        if not bounds.isEmpty():
            baseline = QPointF(
                chip_rect.center().x() - bounds.center().x(),
                chip_rect.center().y() - bounds.center().y(),
            )
            text_rect = bounds.translated(baseline)
        else:
            metrics = QFontMetrics(font)
            baseline = QPointF(
                (logical_w - metrics.horizontalAdvance(sample_text)) / 2.0,
                (logical_h + metrics.ascent() - metrics.descent()) / 2.0,
            )
            text_rect = QRectF(8.0, 4.0, logical_w - 16.0, logical_h - 8.0)

        bg_enabled, bg_color = _resolve_background(style, recipe_visuals)
        if bg_enabled:
            bar_rect = text_rect.adjusted(-4.5, -2.5, 4.5, 2.5).intersected(
                chip_rect.adjusted(2.5, 2.5, -2.5, -2.5)
            )
            if not bar_rect.isEmpty():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg_color)
                painter.drawRoundedRect(bar_rect, 3.5, 3.5)

        shadow_on, shadow_color, shadow_dx, shadow_dy, shadow_blur = _resolve_shadow(style, recipe_visuals)
        if shadow_on:
            shadow_path = QPainterPath()
            shadow_path.addText(QPointF(baseline.x() + shadow_dx, baseline.y() + shadow_dy), font, sample_text)
            if shadow_blur > 0.35:
                soft = QColor(shadow_color)
                soft.setAlphaF(soft.alphaF() * 0.45)
                painter.strokePath(
                    shadow_path,
                    QPen(
                        soft,
                        max(1.2, shadow_blur * 1.4),
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin,
                    ),
                )
            painter.fillPath(shadow_path, QBrush(shadow_color))

        scale_ratio = target_px / source_size
        strokes = _resolve_strokes(style, recipe_visuals, scale_ratio)
        fill = recipe_visuals.get("fill")
        if fill is None:
            fill = getattr(style, "primary_color", "#FFFFFFFF") or "#FFFFFFFF"
        glow = _resolve_glow(recipe_visuals)

        render_style_sample(
            painter,
            text=sample_text,
            font=font,
            baseline=baseline,
            fill=fill,
            outline=getattr(style, "outline_color", "#FF000000"),
            outline_width=0.0 if strokes else 0.0,
            rect=text_rect,
            opacity=1.0,
            glow=glow,
            strokes=strokes,
        )

        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(chip_path)
    finally:
        painter.end()
    return pixmap


class PresetPreviewDelegate(QStyledItemDelegate):
    """Combo popup delegate rendering a real cached caption thumbnail per preset."""

    ROW_HEIGHT = ROW_HEIGHT
    CHIP_WIDTH = CHIP_WIDTH
    CHIP_HEIGHT = CHIP_HEIGHT
    SAMPLE_TEXT = SAMPLE_TEXT

    def __init__(
        self,
        parent=None,
        *,
        preset_resolver: Callable[[str], PresetPreviewSpec | SubtitleStyle | None] | None = None,
        cache_limit: int = DEFAULT_CACHE_LIMIT,
    ) -> None:
        super().__init__(parent)
        self._resolver = preset_resolver
        self._catalog: dict[str, PresetPreviewSpec] = {}
        self.cache = PresetPreviewCache(max_entries=cache_limit)

    def set_preset_resolver(
        self,
        resolver: Callable[[str], PresetPreviewSpec | SubtitleStyle | None] | None,
    ) -> None:
        self._resolver = resolver

    def set_preset_catalog(
        self,
        styles: Mapping[str, SubtitleStyle],
        recipes: Mapping[str, Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        recipe_map = recipes or {}
        meta_map = metadata or {}
        catalog: dict[str, PresetPreviewSpec] = {}
        for style_id, style in styles.items():
            meta = meta_map.get(style_id, {})
            source = str(meta.get("source") or "")
            is_ai = source == "ai" or str(style_id).startswith("ai-")
            is_custom = style_id not in BUILTIN_PRESETS and not is_ai
            catalog[str(style_id)] = PresetPreviewSpec(
                preset_id=str(style_id),
                name=str(getattr(style, "name", style_id) or style_id),
                style=style,
                recipe=recipe_map.get(style_id),
                favorite=bool(meta.get("favorite", False)),
                is_custom=is_custom,
                is_ai=is_ai,
            )
        self._catalog = catalog

    def clear_cache(self) -> None:
        self.cache.clear()

    def cache_size(self) -> int:
        return len(self.cache)

    def _resolve_spec(self, index) -> PresetPreviewSpec:
        stored = index.data(PRESET_PREVIEW_ROLE)
        if isinstance(stored, PresetPreviewSpec):
            return stored
        preset_id = str(index.data(Qt.ItemDataRole.UserRole) or "")
        label = str(index.data(Qt.ItemDataRole.DisplayRole) or preset_id or "默认样式")
        if preset_id and preset_id in self._catalog:
            return self._catalog[preset_id]
        if preset_id and callable(self._resolver):
            resolved = self._resolver(preset_id)
            if isinstance(resolved, PresetPreviewSpec):
                return resolved
            if isinstance(resolved, SubtitleStyle):
                return PresetPreviewSpec(preset_id=preset_id, name=label, style=resolved)
        if preset_id in BUILTIN_PRESETS:
            return PresetPreviewSpec(
                preset_id=preset_id,
                name=label,
                style=BUILTIN_PRESETS[preset_id],
            )
        fallback = BUILTIN_PRESETS["default"]
        return PresetPreviewSpec(
            preset_id=preset_id or fallback.id,
            name=label,
            style=fallback,
        )

    def pixmap_for_spec(self, spec: PresetPreviewSpec, dpr: float = 1.0) -> QPixmap:
        safe_dpr = round(max(1.0, float(dpr or 1.0)), 2)
        digest = style_preview_digest(
            spec.style,
            spec.recipe,
            sample_text=self.SAMPLE_TEXT,
            chip_size=(self.CHIP_WIDTH, self.CHIP_HEIGHT),
        )
        key = (str(spec.preset_id), digest, safe_dpr)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        pixmap = render_preset_preview_pixmap(
            spec.style,
            recipe=spec.recipe,
            dpr=safe_dpr,
            width=self.CHIP_WIDTH,
            height=self.CHIP_HEIGHT,
            sample_text=self.SAMPLE_TEXT,
        )
        self.cache.put(key, pixmap)
        return pixmap

    def popup_width_for_combo(
        self,
        combo: QComboBox,
        font_metrics: QFontMetrics | None = None,
    ) -> int:
        metrics = font_metrics or combo.view().fontMetrics()
        has_star = False
        longest = 0
        for row in range(combo.count()):
            label = str(combo.itemText(row) or "")
            longest = max(longest, metrics.horizontalAdvance(label))
            spec = combo.itemData(row, PRESET_PREVIEW_ROLE)
            if isinstance(spec, PresetPreviewSpec) and spec.favorite:
                has_star = True
        star_extra = _STAR_SLOT_WIDTH if has_star else 0
        needed = (
            _CHIP_LEFT_PAD
            + self.CHIP_WIDTH
            + _CHIP_TEXT_GAP
            + longest
            + star_extra
            + _ROW_RIGHT_PAD
            + _POPUP_CHROME_WIDTH
        )
        return max(_MIN_POPUP_WIDTH, min(_MAX_POPUP_WIDTH, round(needed)))

    def sizeHint(self, option, index) -> QSize:
        width = max(_MIN_POPUP_WIDTH, option.rect.width())
        return QSize(width, self.ROW_HEIGHT)

    @staticmethod
    def _selected_text_color(theme, chip_hex: str) -> QColor:
        candidate = theme.accent_text
        if contrast_ratio(candidate, chip_hex) >= 4.5:
            return QColor(candidate)
        blended = blend_hex(candidate, theme.text, 0.45)
        if contrast_ratio(blended, chip_hex) >= 4.5:
            return QColor(blended)
        return QColor(theme.text)

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if opt.rect.isEmpty():
            return

        theme = theme_definition(theme_key())
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        selected = enabled and bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = enabled and not selected and bool(opt.state & QStyle.StateFlag.State_MouseOver)

        hover_hex = blend_hex(theme.surface_elevated, theme.text, 0.07 if theme.is_light else 0.09)
        chip_hex = blend_hex(theme.surface_elevated, theme.accent, 0.15 if theme.is_light else 0.24)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        row_rect = QRectF(opt.rect).adjusted(2.0, 1.5, -2.0, -1.5)
        if selected:
            painter.setBrush(QColor(chip_hex))
            border = QColor(theme.accent)
            border.setAlpha(90 if theme.is_light else 120)
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(row_rect, 8.0, 8.0)
            text_color = self._selected_text_color(theme, chip_hex)
        elif hovered:
            painter.setBrush(QColor(hover_hex))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(row_rect, 8.0, 8.0)
            text_color = QColor(theme.text)
        else:
            text_color = QColor(theme.text if enabled else theme.disabled)

        spec = self._resolve_spec(index)
        dpr = 1.0
        if opt.widget is not None:
            try:
                dpr = max(1.0, float(opt.widget.devicePixelRatioF()))
            except (AttributeError, TypeError, ValueError):
                dpr = 1.0
        pixmap = self.pixmap_for_spec(spec, dpr=dpr)

        chip_x = opt.rect.left() + _CHIP_LEFT_PAD
        chip_y = opt.rect.top() + (opt.rect.height() - self.CHIP_HEIGHT) / 2.0
        if not enabled:
            painter.setOpacity(0.55)
        painter.drawPixmap(QPointF(chip_x, chip_y), pixmap)
        painter.setOpacity(1.0)

        label = str(index.data(Qt.ItemDataRole.DisplayRole) or spec.name)
        text_left = chip_x + self.CHIP_WIDTH + _CHIP_TEXT_GAP
        star_reserve = _STAR_SLOT_WIDTH if spec.favorite else 0
        text_right = opt.rect.right() - _ROW_RIGHT_PAD - star_reserve
        text_width = max(0, int(text_right - text_left))
        text_rect = QRectF(text_left, opt.rect.top(), text_width, opt.rect.height())

        label_font = QFont(opt.font)
        weighted_font(
            label_font,
            QFont.Weight.DemiBold if selected else QFont.Weight.Medium,
        )
        painter.setFont(label_font)
        painter.setPen(text_color)
        elided = QFontMetrics(label_font).elidedText(
            label,
            Qt.TextElideMode.ElideRight,
            max(1, text_width),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

        if spec.favorite:
            star_rect = QRectF(
                opt.rect.right() - _ROW_RIGHT_PAD - _STAR_SLOT_WIDTH + 2,
                opt.rect.top(),
                _STAR_SLOT_WIDTH - 2,
                opt.rect.height(),
            )
            star_font = QFont(opt.font)
            star_font.setPixelSize(12)
            painter.setFont(star_font)
            painter.setPen(QColor(theme.warning if enabled else theme.disabled))
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")

        painter.restore()


def install_preset_preview_delegate(
    combo: QComboBox,
    *,
    preset_resolver: Callable[[str], PresetPreviewSpec | SubtitleStyle | None] | None = None,
    cache_limit: int = DEFAULT_CACHE_LIMIT,
) -> PresetPreviewDelegate:
    """Attach a ``PresetPreviewDelegate`` to ``combo`` without altering collapsed geometry."""
    view = combo.view()
    delegate = PresetPreviewDelegate(view, preset_resolver=preset_resolver, cache_limit=cache_limit)
    combo.setItemDelegate(delegate)
    view.setItemDelegate(delegate)
    view.setUniformItemSizes(True)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    combo.popup_content_width = lambda metrics: delegate.popup_width_for_combo(combo, metrics)
    view.setMinimumWidth(delegate.popup_width_for_combo(combo))
    return delegate
