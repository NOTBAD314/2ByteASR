"""「问问兔白」 on the workbench's subtitle list row (2026-11-16).

User (2026-11-16): 「在字幕工作台和编辑区里面也要增加问问兔白的按钮，让用户能随时随地调用兔白，可以放在字幕列表
那一行额外加个问问兔白，让她能真的操作和编辑工作台的内容」. The button sits left of 「AI 工具」 in the
title row of the subtitle list; it opens her chat over the main window, where her workbench tools
(jump, select, edit text, merge, styles, timing… under 「兔白权限」) act on this project.

The row is built by ``studio_workspace``; this module only adds to it once the workspace is ready
(``SubtitleStudioPage._finish_workspace_initialization``), so the list's own code stays as it is.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import QApplication, QToolButton

# The list is narrow by default (~320 px): there the button is her icon only, so 「AI 工具」 keeps its
# words; a wider list shows 「问问兔白」 in full (like 开始审核 → 审核 beside it).
WIDE_LIST = 420


class _ListWidth(QObject):
    def __init__(self, panel, button):
        super().__init__(button)
        self.button = button
        panel.installEventFilter(self)
        self.apply(panel.width())

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.Resize:
            self.apply(watched.width())
        return False

    def apply(self, width: int) -> None:
        compact = width < WIDE_LIST
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        if self.button.toolButtonStyle() != style:
            self.button.setToolButtonStyle(style)
            self.button.setProperty('compact', compact)
            self.button.refresh_theme_palette()


class BunnyEntryButton(QToolButton):
    """Styled from the current theme; ``refresh_theme_palette`` follows a theme switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('cueBunnyButton')
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(15, 15))
        self.refresh_theme_palette()

    def refresh_theme_palette(self):
        from ..design.theme_manager import theme_definition, theme_key
        from ..design.typography import UI_FONT_STACK
        t = theme_definition(theme_key())
        compact = bool(self.property('compact'))
        size = ' min-width: 30px; max-width: 30px; padding: 0;' if compact else ' padding: 0 12px;'
        self.setStyleSheet(
            f'QToolButton#cueBunnyButton {{ background: transparent; color: {t.accent_text};'
            f' border: 1px solid {t.border}; border-radius: 15px; min-height: 30px; max-height: 30px;'
            f'{size} font-family: {UI_FONT_STACK}; font-weight: 600; }}'
            f'QToolButton#cueBunnyButton:hover {{ border-color: {t.accent_text}; background: {t.accent_tint}; }}'
            f'QToolButton#cueBunnyButton:pressed {{ background: {t.accent_soft}; }}'
            f'QToolButton#cueBunnyButton:focus {{ border-color: {t.focus}; }}')


def main_window(page):
    """The main window her chat belongs to (the workbench may also be its own window)."""
    window = page.window()
    if hasattr(window, 'built_page') and hasattr(window, 'pages'):
        return window
    for top in QApplication.topLevelWidgets():
        if hasattr(top, 'built_page') and hasattr(top, 'pages'):
            return top
    return window


def open_from_studio(page):
    from ..app.bunny_chat import open_bunny_chat
    return open_bunny_chat(main_window(page))


def _layout_holding(widget):
    """The layout that has ``widget`` as a direct item (searched from its parent's layout down)."""
    parent = widget.parentWidget()
    pending = [parent.layout()] if parent is not None and parent.layout() is not None else []
    while pending:
        layout = pending.pop()
        if layout.indexOf(widget) >= 0:
            return layout
        for index in range(layout.count()):
            child = layout.itemAt(index).layout()
            if child is not None:
                pending.append(child)
    return None


def install(page):
    """Add the button left of 「AI 工具」; returns it (or None when the row is not there)."""
    anchor = getattr(page, 'cue_ai_button', None)
    if anchor is None or getattr(page, 'cue_bunny_button', None) is not None:
        return getattr(page, 'cue_bunny_button', None)
    layout = _layout_holding(anchor)
    if layout is None:
        return None
    from ..design.themed_icons import install_themed_icon
    from ..i18n import bind_text
    button = BunnyEntryButton()
    bind_text(button, '问问兔白')
    bind_text(button, '叫兔白来帮忙：问操作、查问题，也能让她替你跳转、选字幕、改字、合并、改样式（修改前会先问你）',
              property='toolTip')
    bind_text(button, '问问兔白', property='accessibleName')
    try:                                         # her own face, like the top bar's 「问问兔白」
        from PySide6.QtGui import QIcon
        from ..design.bunny_mascot import bunny_face_pixmap
        face = bunny_face_pixmap(20, button.devicePixelRatioF())
        face.setDevicePixelRatio(button.devicePixelRatioF())
        if face.isNull():
            raise ValueError('no face')
        button.setIcon(QIcon(face))
        button.setIconSize(QSize(20, 20))
    except Exception:  # noqa: BLE001 - no picture: the plain chat icon
        install_themed_icon(button, 'fa5s.comment-dots', 'accent')
    button.clicked.connect(lambda _checked=False: open_from_studio(page))
    layout.insertWidget(layout.indexOf(anchor), button)
    page.cue_bunny_button = button
    panel = getattr(page, 'cue_list_panel', None)
    if panel is not None:
        button._width_watch = _ListWidth(panel, button)
    return button


__all__ = ['BunnyEntryButton', 'install', 'main_window', 'open_from_studio']
