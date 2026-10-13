"""Video tool panel: motion first, transition defaults last; honest empty state."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QGroupBox, QScrollArea, QWidget

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.studio_video_flow import StudioVideoFlowMixin


def _app():
    return QApplication.instance() or QApplication([])


def _panel(page) -> QWidget:
    area = page.context_drawer.widget(page.video_transform_tab_index)
    return area.widget() if isinstance(area, QScrollArea) else area


def _order(panel):
    layout = panel.layout()
    names = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None:
            continue
        names.append(widget.title() if isinstance(widget, QGroupBox) else widget.objectName())
    return names


def test_motion_controls_come_first_and_defaults_are_collapsed_last():
    _app()
    page = SubtitleStudioPage()
    try:
        names = _order(_panel(page))
        motion, blend, chroma = names.index("运动"), names.index("透明度与叠加"), names.index("绿幕抠像")
        defaults = names.index("videoDefaultsSection")
        assert motion < blend < chroma < defaults
        assert "默认转场时长" not in names  # no longer a group above 运动
        assert page.default_transition_content.isHidden()
        assert "500 ms" in page.default_transition_toggle.text() and "300 ms" in page.default_transition_toggle.text()
        page.default_transition_toggle.setChecked(True)
        assert not page.default_transition_content.isHidden()
    finally:
        page.close_page()
        page.deleteLater()


def test_no_selected_clip_shows_blank_fields_not_one_or_zero_percent():
    _app()
    page = SubtitleStudioPage()
    try:
        page._refresh_video_transform_panel()
        for control in (page.video_scale_x, page.video_scale_y, page.video_opacity, page.video_position_x):
            assert control.specialValueText() == "—"
            assert control.value() == control.minimum()
            assert not control.isEnabled()
        assert page.video_fit_mode.currentIndex() == -1
        # Leaving the empty state restores ordinary numbers.
        page._show_video_transform_placeholders(False)
        page._set_video_transform_controls({"scale_x": 1.0, "scale_y": 1.0, "opacity": 1.0})
        assert page.video_scale_x.specialValueText() == "" and page.video_scale_x.value() == 100.0
        assert page.video_opacity.value() == 100.0
    finally:
        page.close_page()
        page.deleteLater()


def test_focus_out_without_edit_pushes_no_undo_step():
    transform = SimpleNamespace(position_x=.5, position_y=.5, scale_x=1.234567, scale_y=1.234567,
                                rotation=0.0, opacity=1.0, anchor_x=.5, anchor_y=.5, fit_mode="contain")
    clip = SimpleNamespace(id="clip-1", transform=transform)
    committed, synced = [], []
    fake = SimpleNamespace(
        _updating_video_transform_ui=False,
        _selected_video_clip=lambda: (SimpleNamespace(id="V1", locked=False), clip),
        # The fields show two decimals of percent: 123.46 %.
        _video_transform_values_from_controls=lambda: {
            "position_x": .5, "position_y": .5, "scale_x": 1.2346, "scale_y": 1.2346, "rotation": 0.0,
            "opacity": 1.0, "anchor_x": .5, "anchor_y": .5, "fit_mode": "contain"},
        _video_transform_preview_overrides={"clip-1": {"scale_x": 1.2346}},
        _video_transform_committed=lambda *args: committed.append(args),
        _sync_video_compositor=lambda ms: synced.append(ms),
        timeline=SimpleNamespace(playhead_ms=1234),
    )
    StudioVideoFlowMixin._video_transform_control_committed(fake)
    assert committed == [] and synced == [1234] and fake._video_transform_preview_overrides == {}
    # A real edit is committed.
    fake._video_transform_values_from_controls = lambda: {
        "position_x": .5, "position_y": .5, "scale_x": 1.5, "scale_y": 1.5, "rotation": 0.0,
        "opacity": 1.0, "anchor_x": .5, "anchor_y": .5, "fit_mode": "contain"}
    StudioVideoFlowMixin._video_transform_control_committed(fake)
    assert len(committed) == 1 and committed[0][2]["scale_x"] == 1.5


def test_narrow_drawer_stacks_y_under_x():
    app = _app()
    page = SubtitleStudioPage()
    try:
        page.resize(1600, 900)
        page.show()
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        for _ in range(5):
            app.processEvents()
        panel = _panel(page)
        fields, group_x, group_y = page._video_axis_pairs[1]  # scale X/Y (+ link)
        assert fields.getItemPosition(fields.indexOf(group_y))[:2] == (0, 1)
        panel.setFixedWidth(240)
        for _ in range(5):
            app.processEvents()
        assert fields.getItemPosition(fields.indexOf(group_y))[:2] == (1, 0)
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(16777215)
        panel.setFixedWidth(600)
        for _ in range(5):
            app.processEvents()
        assert fields.getItemPosition(fields.indexOf(group_y))[:2] == (0, 1)
    finally:
        page.close_page()
        page.deleteLater()
