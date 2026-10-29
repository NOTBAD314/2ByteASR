"""The "+" above the track names: add a subtitle or video track (2026-10-21).

The user asked for it after 新建字幕轨 / 新建视频轨 left the timeline bar for
「…」. It sits in the empty corner left of the ruler and reuses the same
(hidden) bar buttons, so shortcuts, undo and track naming stay as before.
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton

from ..design.studio_theme import create_studio_menu
from ..design.themed_icons import install_themed_icon
from ..i18n import tr
from ..i18n_widgets import bind_text


def install_add_track_button(page) -> QToolButton:
    timeline = page.timeline
    button = QToolButton(timeline)
    button.setObjectName("timelineAddTrackButton")
    install_themed_icon(button, "fa5s.plus", "secondary")
    button.setIconSize(QSize(12, 12))
    button.setFixedSize(QSize(26, 24))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    bind_text(button, '新建轨道：字幕轨或视频轨', property='toolTip')
    menu = create_studio_menu(button)

    def fill():
        from .studio_widgets import _icon
        menu.clear()
        subtitle = menu.addAction(_icon('fa5s.closed-captioning'), tr('新建字幕轨'), page.add_subtitle_track_button.click)
        video = menu.addAction(_icon('fa5s.layer-group'), tr('新建视频轨'), page.add_video_track_button.click)
        for action in (subtitle, video):
            action.setEnabled(page.project is not None)

    menu.aboutToShow.connect(fill)
    button.setMenu(menu)
    button.move(10, (timeline.RULER_HEIGHT - button.height()) // 2)
    button.show()
    page.timeline_add_track_button = button
    return button
