"""2026-10-24: caption 位置与变换 moved from the 样式 tab to the 视频 tab;
样式 starts with 应用到; motion previews take their stage from the theme."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from tests.test_motion_workflow_ui import make_page, close
from tests.test_studio_transform_controls import video_graph
from twobyteasr.caption_style.caption_layer_transform import resolved_values
from twobyteasr.caption_style.caption_transform_panel import CaptionTransformPanel


def test_style_tab_starts_with_scope_and_has_no_transform_card(tmp_path):
    app, page = make_page(tmp_path)
    try:
        style = page.context_drawer.widget(1).widget()
        assert not style.findChildren(CaptionTransformPanel)
        first = style.layout().itemAt(0).widget()
        assert first.objectName() == 'styleScopeBar'
        assert first.isAncestorOf(page.style_scope) and first.isAncestorOf(page.style_apply_geometry)
        video = page.context_drawer.widget(page.video_transform_tab_index)
        assert video.isAncestorOf(page.caption_transform_panel)
    finally:
        close(page)


def test_video_tab_swaps_between_caption_and_clip_cards(tmp_path):
    app, page = make_page(tmp_path)
    try:
        track, clip = video_graph(page)
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        page.select_cue('b')
        # Picking a caption keeps the 视频 tab and shows the caption card.
        assert page.context_drawer.currentIndex() == page.video_transform_tab_index
        assert not page.caption_transform_panel.isHidden() and page.video_clip_controls.isHidden()
        assert '第二句' in page.video_transform_selection_label.text()
        assert page.caption_transform_panel.controls['position_x'].isEnabled()
        page._video_clip_selected(track.id, clip.id)
        assert page.caption_transform_panel.isHidden() and not page.video_clip_controls.isHidden()
        assert page.video_position_x.isEnabled()
        page.select_cue('a')
        assert not page.caption_transform_panel.isHidden() and page.video_clip_controls.isHidden()
        assert '你好世界' in page.video_transform_selection_label.text()
        page.select_cue('')
        assert page.caption_transform_panel.isHidden() and not page.video_clip_controls.isHidden()
        assert page.video_transform_selection_label.text() == '在时间线选择视频片段或字幕'
    finally:
        close(page)


def test_several_captions_are_named_by_count_and_edited_together(tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    app, page = make_page(tmp_path)
    try:
        model = page.cue_table.selectionModel()
        model.clearSelection()
        for row in (0, 2):
            model.select(page.cue_model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        panel = page.caption_transform_panel
        panel.refresh()
        assert not panel.isHidden()
        assert page.video_transform_selection_label.text() == '原文 · 2 条字幕'
        panel.controls['rotation'].setValue(9)
        assert [resolved_values(page.project, page.project.cues[i], 'original')['rotation'] for i in (0, 1, 2)] == [9., 0., 9.]
    finally:
        close(page)


def _mouse(widget, kind, point, buttons):
    event = QMouseEvent(kind, QPointF(point), QPointF(widget.mapToGlobal(point)), Qt.LeftButton,
                        buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def test_caption_pad_drag_is_one_undo_step(tmp_path):
    app, page = make_page(tmp_path)
    try:
        panel = page.caption_transform_panel
        panel.refresh()
        before = resolved_values(page.project, page.project.cues[0], 'original')
        pad = panel.pad
        pad.resize(320, 100)
        frame = pad._frame()
        count = page.undo_stack.count()
        start = QPoint(round(frame.center().x()), round(frame.center().y()))
        end = QPoint(round(frame.left() + frame.width() * .25), round(frame.top() + frame.height() * .75))
        _mouse(pad, QEvent.MouseButtonPress, start, Qt.LeftButton)
        _mouse(pad, QEvent.MouseMove, end, Qt.LeftButton)
        _mouse(pad, QEvent.MouseButtonRelease, end, Qt.NoButton)
        after = resolved_values(page.project, page.project.cues[0], 'original')
        assert after['position_x'] == pytest.approx(480, abs=12)
        assert after['position_y'] == pytest.approx(810, abs=12)
        assert page.undo_stack.count() == count + 1
        assert panel.gesture is None
        page.undo_stack.undo()
        undone = resolved_values(page.project, page.project.cues[0], 'original')
        assert (undone['position_x'], undone['position_y']) == (before['position_x'], before['position_y'])
    finally:
        close(page)


def test_locked_caption_track_is_read_only_on_video_tab(tmp_path):
    app, page = make_page(tmp_path)
    try:
        page.timeline.locked_speakers = {'S01'}
        page.select_cue('a')
        panel = page.caption_transform_panel
        assert not panel.controls['position_x'].isEnabled() and not panel.pad.isEnabled()
        assert not panel.target.isHidden() and panel.target.text() == '所选字幕轨已锁定，请在时间轴解锁'
        count = page.undo_stack.count()
        panel.apply({'position_x': 100.})
        assert page.undo_stack.count() == count
    finally:
        page.timeline.locked_speakers = set()
        close(page)


def test_preview_stage_follows_theme_with_white_text_contrast():
    from twobyteasr.design.soft_qss import preview_stage
    from twobyteasr.design.ui_theme import THEMES, contrast_ratio, hex_luminance
    old_navy = hex_luminance('#283A4F')
    for theme in THEMES.values():
        top, bottom = preview_stage(theme)
        assert contrast_ratio('#ffffff', top) >= 4.5 and contrast_ratio('#ffffff', bottom) >= 4.5, theme.key
        if theme.is_light:
            assert hex_luminance(top) > old_navy * 2, theme.key  # a mid tone, not a dark navy
        else:
            assert hex_luminance(top) < old_navy * 1.5, theme.key  # dark themes stay dark
    assert preview_stage(THEMES['sand']) != preview_stage(THEMES['grape'])


def test_motion_previews_refresh_their_stage_with_the_theme(tmp_path, monkeypatch):
    from twobyteasr.design import theme_manager
    from twobyteasr.design.soft_qss import preview_stage
    from twobyteasr.design.ui_theme import THEMES
    from twobyteasr.caption_style.motion_inspector_ui import MotionEffectTile
    app, page = make_page(tmp_path)
    tile = MotionEffectTile('entry', 'fade', '淡入', None)
    try:
        samples = [page.motion_sample, tile.preview]
        for key in ('sand', 'grape'):
            monkeypatch.setattr(theme_manager, 'theme_key', lambda key=key: key)
            top, bottom = preview_stage(THEMES[key])
            for sample in samples:
                sample.refresh_theme_palette()
                assert top in sample.styleSheet() and bottom in sample.styleSheet()
                assert '#283A4F' not in sample.styleSheet()
        assert 'border-radius: 12px' in page.motion_sample.styleSheet()
        assert 'border-radius: 9px' in tile.preview.styleSheet()
    finally:
        tile.deleteLater()
        close(page)
