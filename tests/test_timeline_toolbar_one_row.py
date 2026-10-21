"""Timeline toolbar on one row, transport under the video, full tooltips (2026-10-21)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from twobyteasr.studio.studio_toolbar_layout import fold_plan, install_command_groups


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _bar(app, width, *, fold=("display", "view")):
    """editing 300 | transport 560 | view 120 | display 200 | output 160 (fixed widths)."""
    host = QWidget()
    outer = QVBoxLayout(host)
    old = QHBoxLayout()
    outer.addLayout(old)
    starts = {}
    for role, sizes in (("editing", [300]), ("transport", [560]), ("view", [120]),
                        ("display", [200]), ("output", [160])):
        for size in sizes:
            widget = QPushButton(role)
            widget.setFixedSize(QSize(size, 32))
            old.addWidget(widget)
            starts.setdefault(role, widget)
    page = type("Page", (), {})()
    install_command_groups(page, outer, old, starts["transport"], starts["view"],
                           toggles_start=starts["display"], output_start=starts["output"], fold=fold)
    host.resize(width, 200)
    host.show()
    app.processEvents()
    return host, page


def _roles(page):
    return {group.property("commandGroup"): group for group in page._timeline_group_widgets}


def test_transport_aims_at_the_anchor_and_folds_display_then_view(app):
    host, page = _bar(app, 1700)
    flow, bar, groups = page._timeline_command_layout, page._timeline_command_bar, _roles(page)
    foldable = {role: groups[role] for role in ("display", "view")}
    flow.center_anchor = lambda: 700
    # Everything fits with the transport centred on x=700.
    assert fold_plan(flow, 1700, foldable) == set()
    # Narrower: the right side cannot hold display and still centre -> fold it.
    assert fold_plan(flow, 1450, foldable) == {"display"}
    # Narrower still: fold the zoom group too.
    assert fold_plan(flow, 1300, foldable) == {"display", "view"}
    bar.refit()
    flow.invalidate()
    flow.activate()
    app.processEvents()
    transport = groups["transport"]
    centre = transport.mapTo(bar, transport.rect().topLeft()).x() + transport.width() / 2
    assert abs(centre - 700) <= 1
    assert not groups["display"].isHidden() and not groups["view"].isHidden()
    # The plan depends only on width and anchor: repeated refits agree.
    host.resize(1450, 200)
    app.processEvents()
    assert groups["display"].isHidden() and not groups["view"].isHidden()
    bar.refit()
    assert groups["display"].isHidden()
    host.resize(1700, 200)
    app.processEvents()
    assert not groups["display"].isHidden()
    host.close()


def test_bars_that_do_not_opt_in_still_wrap_and_keep_every_group(app):
    host, page = _bar(app, 900, fold=())
    groups = _roles(page)
    assert not any(group.isHidden() for group in groups.values())
    tops = {group.mapTo(page._timeline_command_bar, group.rect().topLeft()).y() for group in groups.values()}
    assert len(tops) > 1
    host.close()


def test_tooltip_grows_to_the_font_the_window_sheet_gave_it(app):
    from twobyteasr.design.theme_manager import _fit_tooltip
    tip = QLabel("添加字幕 (T) · 在播放头创建字幕块")
    font = QFont(tip.font())
    font.setPixelSize(12)
    tip.setFont(font)
    tip.resize(tip.sizeHint())
    small = tip.width()
    font.setPixelSize(14)  # the zoomed window sheet, applied on Show
    tip.setFont(font)
    _fit_tooltip(tip)
    assert tip.width() >= tip.sizeHint().width() > small
    screen = tip.screen().availableGeometry()
    assert screen.contains(tip.geometry()) or tip.width() > screen.width()


def test_studio_bar_moves_tracks_media_and_transitions_into_more_and_adds_plus(app):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page = SubtitleStudioPage()
    app.processEvents()
    try:
        assert page.add_subtitle_button.text() == ""
        for button in (page.media_pool_button, page.add_video_track_button, page.add_subtitle_track_button,
                       page.transition_button):
            assert button.isHidden() and button.parentWidget() is page
        more = page.cue_more_button.menu()
        more.aboutToShow.emit()
        texts = [action.text() for action in more.actions()]
        assert texts[:4] == ["打开媒体池", "新建字幕轨", "新建视频轨", page.transition_button.toolTip()]
        assert more.actions()[3].menu() is page.transition_button.menu()
        # A second opening keeps the shared transition submenu alive.
        more.aboutToShow.emit()
        assert more.actions()[3].menu() is page.transition_button.menu()
        plus = page.timeline_add_track_button
        assert plus.parentWidget() is page.timeline
        plus.menu().aboutToShow.emit()
        assert [action.text() for action in plus.menu().actions()] == ["新建字幕轨", "新建视频轨"]
        for toggle, name in ((page.waveform_toggle, "波形"), (page.filmstrip_toggle, "缩略图"),
                             (page.follow_playhead_toggle, "跟随播放头"), (page.snap_toggle, "自动吸附")):
            assert toggle.text() == "" and toggle.accessibleName() == name and toggle.toolTip()
        options = page.timeline_options_button.menu()
        options.aboutToShow.emit()
        names = [action.text() for action in options.actions()]
        assert names[:4] == ["波形", "缩略图", "跟随播放头", "自动吸附"]
        assert any("缩小时间轴" in name for name in names) and any("适应窗口" in name for name in names)
        # Unchecking in the menu unchecks the switch.
        options.actions()[3].setChecked(False)
        assert not page.snap_toggle.isChecked()
        assert set(page._timeline_command_bar._fold_groups) == {"display", "view"}
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()
