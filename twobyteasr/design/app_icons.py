"""App-drawn line icons that the icon font does not have (2026-11-14).

User (2026-11-14, toolbar draft A): 「工程音量 / 响度」 and 「次要角色」 were text
buttons that looked out of place; each gets its own icon. Names start with
``app.`` and go through the same ``themed_icon`` / ``colored_icon`` calls as the
qtawesome names, so theme refreshes recolour them too.

Each icon is a 24×24 SVG body drawn with ``currentColor`` strokes; the colour is
substituted before rendering.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap

PREFIX = "app."

_STROKE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
           'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')

_PEOPLE = ('<circle cx="8.5" cy="8" r="3.2"/><path d="M2.8 19.5a5.7 5.7 0 0111.4 0"/>'
           '<circle cx="16.8" cy="9.2" r="2.2" opacity=".75"/><path d="M15 13.6a4.4 4.4 0 016.6 3.9" opacity=".75"/>')

BODIES = {
    # Speaker with three rising bars: the whole project's level.
    "project_volume": ('<path d="M3 10h2.6L9.5 7v10L5.6 14H3z" fill="{c}" fill-opacity=".15"/>'
                       '<path d="M13 16.5v-2M16.5 16.5v-5M20 16.5V7.5"/>'
                       '<path d="M12 19.5h9" stroke-width="1.6" opacity=".55"/>'),
    # One main speaker and two smaller ones behind: the secondary group.
    "secondary_roles": _PEOPLE,
    "secondary_roles_collapsed": _PEOPLE + '<path d="M16 19.5l2.2 2 2.2-2" stroke-width="1.8"/>',
    "secondary_roles_hidden": _PEOPLE + '<path d="M3 3l18 18" stroke-width="2.4"/>',
}


def is_app_icon(name: str) -> bool:
    return str(name).startswith(PREFIX) and str(name)[len(PREFIX):] in BODIES


def svg_bytes(name: str, color: str) -> bytes:
    body = BODIES[str(name)[len(PREFIX):]].replace("{c}", color)
    return _STROKE.format(c=color, body=body).encode("utf-8")


@lru_cache(maxsize=512)
def _raster(name: str, color: str, width: int, height: int) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_bytes(name, color)))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(width, height)
    renderer.render(painter, QRectF((width - side) / 2, (height - side) / 2, side, side))
    painter.end()
    return pixmap


def icon_pixmap(name: str, color: str, size: QSize, device_pixel_ratio: float = 1.0) -> QPixmap:
    ratio = max(1.0, float(device_pixel_ratio))
    pixmap = QPixmap(_raster(str(name), str(color), round(size.width() * ratio), round(size.height() * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class _SvgIconEngine(QIconEngine):
    def __init__(self, name: str, color: str, disabled: str):
        super().__init__()
        self._name, self._color, self._disabled = str(name), str(color), str(disabled or color)

    def _color_for(self, mode) -> str:
        return self._disabled if mode == QIcon.Mode.Disabled else self._color

    def pixmap(self, size, mode, state):  # noqa: D401 - Qt override
        return QPixmap(_raster(self._name, self._color_for(mode), size.width(), size.height()))

    def scaledPixmap(self, size, mode, state, scale):  # noqa: N802 - Qt override
        return icon_pixmap(self._name, self._color_for(mode), size, scale)

    def paint(self, painter, rect, mode, state):
        device = painter.device()
        ratio = float(device.devicePixelRatioF()) if device is not None else 1.0
        painter.drawPixmap(rect, icon_pixmap(self._name, self._color_for(mode), rect.size(), ratio))

    def actualSize(self, size, mode, state):  # noqa: N802 - Qt override
        return size

    def clone(self):
        return _SvgIconEngine(self._name, self._color, self._disabled)


def app_icon(name: str, color: str, disabled: str = "") -> QIcon:
    return QIcon(_SvgIconEngine(name, color, disabled))
