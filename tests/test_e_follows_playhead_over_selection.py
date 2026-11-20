"""2026-11-18 (user): E edits the caption under the playhead, not an older selection."""
from twobyteasr.projects.studio_project import StudioCue


def _cues():
    return [StudioCue('a', 1000, 2000, '第一条'), StudioCue('b', 2200, 5000, '第二条')]


def test_e_after_playback_edits_caption_under_playhead(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, _cues())
    try:
        page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'
        page._remember_canvas_edit_target('a', 'original')
        page.timeline.set_playhead(3000)
        assert page._shortcut_edit_at_playhead()
        app.processEvents()
        assert page._caption_draft is not None
        assert page._caption_draft.target.cue_id == 'b'
        assert page.subtitle_edit_input.toPlainText() == '第二条'
        page._cancel_canvas_inline_edit()
    finally:
        page.close_page(); page.deleteLater()


def test_selection_made_at_the_current_clock_keeps_e(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, _cues())
    try:
        page.timeline.set_playhead(3000)
        page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'
        assert not page._playhead_overrides_selection('a')
        page.timeline.set_playhead(3100)  # played/seeked on: the clock wins
        assert page._playhead_overrides_selection('a')
    finally:
        page.close_page(); page.deleteLater()


def test_selection_keeps_e_inside_itself_and_in_a_gap(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, _cues())
    try:
        for position in (1500, 2100):
            page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'
            page.timeline.set_playhead(position)
            assert not page._playhead_overrides_selection('a')
            assert page._shortcut_edit_at_playhead()
            app.processEvents()
            assert page._caption_draft.target.cue_id == 'a'
            page._cancel_canvas_inline_edit()
        page.timeline.set_playhead(3000)
        assert page._playhead_overrides_selection('a')
        assert not page._playhead_overrides_selection('b')
    finally:
        page.close_page(); page.deleteLater()
