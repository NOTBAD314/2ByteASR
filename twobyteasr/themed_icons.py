"""Theme-aware icon generation and refresh registry.

qtawesome rasterizes icons at creation time, so a dark icon stays dark when
the app switches to a dark theme. Every themed icon is generated from a
semantic role mapped to the active theme's text tokens, and buttons/tabs
register themselves through dynamic properties so ``refresh_themed_icons``
can re-rasterize just the theme-sensitive icons on theme switch.
"""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QAction, QFontDatabase, QFontMetricsF, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QAbstractButton, QTabWidget, QWidget

import qtawesome as qta

from .ui_theme import ThemeDefinition, theme_definition

ICON_ROLES = (
    "primary", "secondary", "muted", "disabled", "on_accent", "accent",
    "window_control", "toolbar_primary", "toolbar_secondary", "toolbar_disabled",
)

_BUTTON_PROPERTY = "_themed_icon"          # (name, role) on QAbstractButton
_TABS_PROPERTY = "_themed_tab_icons"       # [(name, role)] on QTabWidget
_FONT_FALLBACK_PRIMED = False
_PIXMAP_CACHE: dict[tuple[str, str, int, int, int, str], QPixmap] = {}
_NORMAL_PIXMAP_CACHE: dict[tuple[str, int, int, int], QPixmap] = {}


def _prime_platform_font_fallback() -> None:
    global _FONT_FALLBACK_PRIMED
    if _FONT_FALLBACK_PRIMED:
        return
    app = QApplication.instance()
    if app is None:
        return
    if sys.platform == "win32":
        families = {str(item).casefold() for item in QFontDatabase.families()}
        if "microsoft yahei ui" not in families:
            fallback = Path("C:/Windows/Fonts/msyh.ttc")
            if fallback.is_file():
                QFontDatabase.addApplicationFont(str(fallback))
    QFontMetricsF(app.font()).horizontalAdvance("字幕")
    _FONT_FALLBACK_PRIMED = True


def _active_theme(theme: ThemeDefinition | None) -> ThemeDefinition:
    """Resolve the persisted theme when the caller did not pin one."""
    if theme is not None:
        return theme
    from .theme_manager import theme_key

    return theme_definition(theme_key())


def icon_role_color(role: str, theme: ThemeDefinition | None = None) -> str:
    active = _active_theme(theme)
    return {
        "primary": active.text,
        "secondary": active.text_secondary,
        "muted": active.text_muted,
        "disabled": active.disabled,
        "on_accent": active.text_on_accent,
        "accent": active.accent,
        "window_control": active.text,
        "toolbar_primary": active.text,
        "toolbar_secondary": active.text_secondary,
        "toolbar_disabled": active.disabled,
    }.get(str(role), active.text)


def themed_icon(name: str, role: str = "primary", theme: ThemeDefinition | None = None) -> QIcon:
    _prime_platform_font_fallback()
    active = _active_theme(theme)
    color = icon_role_color(role, active)
    return qta.icon(name, color=color, color_active=color, color_disabled=active.disabled)


def cached_icon_pixmap(
    name: str,
    color: str,
    size: QSize,
    *,
    device_pixel_ratio: float = 1.0,
    state: str = "normal",
) -> QPixmap:
    """Synchronously rasterize an icon with a guaranteed normal fallback."""

    _prime_platform_font_fallback()
    width, height = max(1, int(size.width())), max(1, int(size.height()))
    dpr_key = max(100, round(max(1.0, float(device_pixel_ratio)) * 100))
    state_key = str(state or "normal")
    key = (str(name), str(color), width, height, dpr_key, state_key)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None and not cached.isNull():
        return QPixmap(cached)

    dpr = dpr_key / 100.0
    icon = qta.icon(str(name), color=str(color))
    try:
        pixmap = icon.pixmap(QSize(width, height), dpr)
    except TypeError:
        pixmap = icon.pixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
        pixmap.setDevicePixelRatio(dpr)
    normal_key = (str(name), width, height, dpr_key)
    if pixmap.isNull():
        fallback = _NORMAL_PIXMAP_CACHE.get(normal_key)
        if fallback is not None and not fallback.isNull():
            pixmap = QPixmap(fallback)
    if pixmap.isNull():
        # qtawesome is synchronous, so this means its font/icon source is not
        # usable. Fail in development instead of silently painting a blank.
        raise RuntimeError(f"timeline icon rasterization returned null: {name}")
    _PIXMAP_CACHE[key] = QPixmap(pixmap)
    if state_key == "normal" or normal_key not in _NORMAL_PIXMAP_CACHE:
        _NORMAL_PIXMAP_CACHE[normal_key] = QPixmap(pixmap)
    return pixmap


def paint_cached_icon(
    painter: QPainter,
    name: str,
    color: str,
    rect: QRect,
    *,
    state: str = "normal",
) -> QPixmap:
    device = painter.device()
    dpr = float(getattr(device, "devicePixelRatioF", lambda: 1.0)() or 1.0)
    pixmap = cached_icon_pixmap(
        name,
        color,
        rect.size(),
        device_pixel_ratio=dpr,
        state=state,
    )
    painter.drawPixmap(rect, pixmap)
    return pixmap


def clear_icon_pixmap_cache() -> None:
    _PIXMAP_CACHE.clear()
    _NORMAL_PIXMAP_CACHE.clear()


def install_themed_icon(button: QAbstractButton | QAction, name: str, role: str = "primary") -> None:
    """Set a role-driven icon and remember it for theme refreshes."""
    button.setProperty(_BUTTON_PROPERTY, (str(name), str(role)))
    button.setIcon(themed_icon(name, role))


def install_themed_tabs(tabs: QTabWidget, entries: list[tuple[str, str]]) -> None:
    """Remember [(icon_name, role)] so tab icons can be re-rasterized."""
    payload = [(str(name), str(role)) for name, role in entries]
    tabs.setProperty(_TABS_PROPERTY, payload)
    for index, (name, role) in enumerate(payload):
        tabs.setTabIcon(index, themed_icon(name, role))


def refresh_themed_icons(app: QApplication | None = None) -> int:
    """Re-rasterize registered icons for the active theme. Returns count."""
    app = app or QApplication.instance()
    if app is None:
        return 0
    clear_icon_pixmap_cache()
    refreshed = 0
    seen_actions = set()
    for widget in app.allWidgets():
        for action in widget.actions():
            if action in seen_actions:
                continue
            seen_actions.add(action)
            spec = action.property(_BUTTON_PROPERTY)
            if isinstance(spec, tuple) and len(spec) == 2:
                action.setIcon(themed_icon(spec[0], spec[1]))
                refreshed += 1
        if isinstance(widget, QAbstractButton):
            spec = widget.property(_BUTTON_PROPERTY)
            if isinstance(spec, tuple) and len(spec) == 2:
                widget.setIcon(themed_icon(spec[0], spec[1]))
                refreshed += 1
        elif isinstance(widget, QTabWidget):
            specs = widget.property(_TABS_PROPERTY)
            if isinstance(specs, list):
                for index, spec in enumerate(specs):
                    if isinstance(spec, tuple) and len(spec) == 2 and index < widget.count():
                        widget.setTabIcon(index, themed_icon(spec[0], spec[1]))
                        refreshed += 1
    return refreshed


def widget_has_themed_icons(widget: QWidget) -> bool:
    return widget.property(_BUTTON_PROPERTY) is not None or widget.property(_TABS_PROPERTY) is not None
