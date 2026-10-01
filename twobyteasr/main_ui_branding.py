"""Application icon and header branding widgets."""

from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy

from .main_ui_helpers import APP_ICON_FALLBACK_PATH, APP_ICON_PATH, APP_ICON_SOURCE_PATH
from .themed_icons import _prime_platform_font_fallback
from .ui_theme import GREEN, INK


def _icon(name: str, color: str = INK) -> QIcon:
    _prime_platform_font_fallback()
    return qta.icon(name, color=color)


def _app_icon() -> QIcon:
    # Qt/Windows 对多尺寸 ICO 的窗口图标解析在部分显卡驱动上会退回空白
    # 文档图标；透明 PNG 用于窗口最稳定。app_icon.ico（脸部特写）保留给
    # EXE / 快捷方式 / 任务栏注册使用。
    if APP_ICON_SOURCE_PATH.is_file():
        return QIcon(str(APP_ICON_SOURCE_PATH))
    if APP_ICON_PATH.is_file():
        return QIcon(str(APP_ICON_PATH))
    if APP_ICON_FALLBACK_PATH.is_file():
        return QIcon(str(APP_ICON_FALLBACK_PATH))
    return _icon("fa5s.closed-captioning", GREEN)


_BRAND_PIXMAP_CACHE: dict[tuple[str, int, float, tuple | None], QPixmap] = {}


def _brand_pixmap(
    path: Path,
    logical_size: int,
    *,
    focus_crop: tuple[float, float, float, float] | None = None,
) -> QPixmap:
    """Render a crisp logical-size mascot on high-DPI Windows displays."""
    screen = QApplication.primaryScreen()
    ratio = max(1.0, float(screen.devicePixelRatio()) if screen else 1.0)
    cache_key = (str(path), int(logical_size), round(ratio, 3), focus_crop)
    cached = _BRAND_PIXMAP_CACHE.get(cache_key)
    if cached is not None:
        return QPixmap(cached)
    physical_size = max(logical_size, round(logical_size * ratio))
    source = QPixmap(str(path))
    if focus_crop and not source.isNull():
        left, top, right, bottom = focus_crop
        x = round(source.width() * left)
        y = round(source.height() * top)
        width = max(1, round(source.width() * (right - left)))
        height = max(1, round(source.height() * (bottom - top)))
        source = source.copy(x, y, width, height)
    pixmap = source.scaled(
        QSize(physical_size, physical_size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(ratio)
    _BRAND_PIXMAP_CACHE[cache_key] = QPixmap(pixmap)
    return QPixmap(pixmap)


class HeaderMascot(QLabel):
    """Fixed logical-size header artwork, refreshed only when DPR changes."""

    LOGICAL_WIDTH = 76
    LOGICAL_HEIGHT = 76
    ARTWORK_SIZE = 76
    LIBRARY_SIZE = 64
    # Header variant: the artwork bleeds below the label and is cropped at
    # the header divider, so the physical artwork is taller than the label.
    HEADER_WIDTH = 72
    HEADER_HEIGHT = 58
    HEADER_ARTWORK = 70
    HEADER_FOCUS_CROP = (0.12, 0.22, 0.88, 0.98)

    def __init__(
        self,
        parent=None,
        *,
        full_artwork: bool = False,
        header_crop: bool = False,
        logical_size: int | None = None,
    ):
        super().__init__(parent)
        self._full_artwork = bool(full_artwork)
        self._header_crop = bool(header_crop)
        self._logical_size = max(32, int(logical_size)) if logical_size is not None else None
        if self._header_crop:
            self.setFixedSize(self.HEADER_WIDTH, self.HEADER_HEIGHT)
            self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        else:
            size = self._logical_size or (
                self.LIBRARY_SIZE if self._full_artwork else self.LOGICAL_HEIGHT
            )
            self.setFixedSize(size, size)
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("border: 0; background: transparent;")
        self.setToolTip("2ByteASR")
        self.setScaledContents(False)
        self._rendered_dpr = -1.0
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        ratio = max(1.0, float(screen.devicePixelRatio()) if screen else 1.0)
        if abs(ratio - self._rendered_dpr) < 0.001:
            return
        self._rendered_dpr = ratio
        if self._header_crop:
            artwork_size = self.HEADER_ARTWORK
        else:
            artwork_size = self._logical_size or (
                self.LIBRARY_SIZE if self._full_artwork else self.ARTWORK_SIZE
            )
        crop = self.HEADER_FOCUS_CROP if self._header_crop else None
        if APP_ICON_SOURCE_PATH.is_file():
            pixmap = _brand_pixmap(
                APP_ICON_SOURCE_PATH,
                artwork_size,
                focus_crop=crop,
            )
        elif APP_ICON_FALLBACK_PATH.is_file():
            pixmap = _brand_pixmap(APP_ICON_FALLBACK_PATH, artwork_size)
        else:
            pixmap = _app_icon().pixmap(QSize(artwork_size, artwork_size))
        self.setPixmap(pixmap)

    def event(self, event):
        dpr_change = getattr(QEvent.Type, "DevicePixelRatioChange", None)
        screen_change = getattr(QEvent.Type, "ScreenChangeInternal", None)
        watched = {value for value in (dpr_change, screen_change) if value is not None}
        if event.type() in watched:
            self._rendered_dpr = -1.0
            self._refresh_pixmap()
        return super().event(event)
