"""2026-11-12 (user, draft B split in two): the 当前字幕 pill left of the
transport, locate / start / end icons on its right."""
from PySide6.QtWidgets import QLabel
from twobyteasr.projects.studio_project import StudioCue
from tests.test_review_replay_and_window_bounds import _page


def _groups(page):
    return {group.property('commandGroup'): widgets
            for group, widgets in zip(page._timeline_group_widgets, page._timeline_command_groups)}


def test_pill_sits_between_editing_and_transport_and_keeps_frame_and_cover(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 10000, 13000, '甲'), StudioCue('b', 14000, 16000, '乙')])
    try:
        roles = [group.property('commandGroup') for group in page._timeline_group_widgets]
        groups = _groups(page)
        assert roles.index('editing') + 1 == roles.index('cue') == roles.index('transport') - 1
        cue = groups['cue']
        assert cue[0] is page.cue_capsule_badge
        assert [w.property('commandSource') for w in cue[1:]] == [
            '波纹向前合并 ({key})', '波纹向后合并 ({key})', '删除当前字幕 ({key})']
        assert groups['navigation'][:3] == [page.selection_center_toggle, page.cue_start_button, page.cue_end_button]
        assert all(widget.isVisible() for widget in (*cue, *groups['navigation']))
        assert page.selection_center_toggle.accessibleName() == '选中定位并居中'
        assert roles.index('navigation') > roles.index('transport')
        assert not page.cue_boundary_button.isVisible()
        assert not any(label.text() == '时间轴' for label in page._timeline_command_bar.findChildren(QLabel))
        assert 'Alt+J' in page.cue_start_button.toolTip() and 'Alt+J' in page.cue_end_button.toolTip()
        assert page.save_frame_button in groups['output'] and page.make_cover_button in groups['output']
        assert page.save_frame_button.isVisible() and page.make_cover_button.isVisible()
    finally:
        page.close_page(); page.deleteLater(); app.processEvents()


def test_pill_names_the_selection_and_jumps_to_start_and_end(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 10000, 13000, '甲'), StudioCue('b', 14000, 16000, '乙')])
    calls = []

    def seek(seconds, **kwargs):
        calls.append(seconds); page.timeline.set_playhead(round(seconds * 1000))

    monkeypatch.setattr(page, '_seek', seek)
    try:
        page.cue_controller.cancel_selection(); app.processEvents()
        assert page.cue_capsule_badge.text() == '#—'
        assert not any(button.isEnabled() for button in page._cue_capsule_buttons)
        page.select_cue('b'); app.processEvents()
        assert page.cue_capsule_badge.text() == '#2'
        assert all(button.isEnabled() for button in page._cue_capsule_buttons)
        # An older pinned E target must not disagree with the pill's selected
        # subtitle. The toggle command itself retains its editor ownership.
        monkeypatch.setattr(page,'_subtitle_navigation_cue',lambda:(page.timeline._timeline_cue_by_id['a'],'original'))
        page.cue_end_button.click(); page.cue_end_button.click()
        page.cue_start_button.click()
        assert calls == [16.0, 16.0, 14.0] and page.selected_cue_id == 'b'
        page.selection_center_toggle.click()
        assert calls[-1] == 14.0 and page.timeline.visible_duration_ms == 15000
        page.timeline.set_playhead(10000)
        page.cue_boundary_button.click()
        assert calls[-1]==13.0  # clicked(bool) still executes the Alt+J toggle
        page.select_cue('b')
        page._cue_capsule_buttons[-1].click(); app.processEvents()  # delete
        assert [cue.id for cue in page.project.cues] == ['a']
    finally:
        page.close_page(); page.deleteLater(); app.processEvents()
