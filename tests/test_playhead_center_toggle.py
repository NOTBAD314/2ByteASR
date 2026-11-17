"""Viewport follow stays separate from seek, zoom and editing selection."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import pytest
from twobyteasr.projects.studio_project import StudioCue, studio_settings_path
from tests.test_review_replay_and_window_bounds import _page


def test_switch_defaults_on_and_needs_no_selected_caption(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',10000,13000,'甲')])
    try:
        page.cue_controller.cancel_selection();app.processEvents()
        button=page.selection_center_toggle
        assert button.isCheckable() and button.isChecked() and button.isEnabled()
        assert page.timeline.center_playhead_mode
        assert page.timeline._time_to_x(page.timeline.playhead_ms)==pytest.approx(
            (page.timeline.TRACK_HEADER_WIDTH+page.timeline._content_right())/2,abs=1)
        calls=[];monkeypatch.setattr(page,'_seek',lambda *a,**k:calls.append(a))
        page.timeline.set_playhead(12000);page.timeline.set_visible_window(0,9000)
        before=page.timeline.visible_duration_ms
        button.click();button.click()
        assert not calls and not page.selected_cue_id
        assert page.timeline.visible_duration_ms==before
        assert page.timeline.visible_start_ms==7500
        payload=json.loads(studio_settings_path().read_text('utf8'))
        assert payload['studio_preferences']['playhead_centered'] is True
    finally:
        page.close_page();page.deleteLater();app.processEvents()


def test_disabled_preference_restores_without_enabling_old_selection_mode(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',10000,13000,'甲')])
    try:
        page.selection_center_toggle.setChecked(False)
        path=studio_settings_path();payload=json.loads(path.read_text('utf8'))
        payload['studio_preferences']['selection_centered']=True
        path.write_text(json.dumps(payload),'utf8')
        from twobyteasr.studio.studio_ui import SubtitleStudioPage
        reopened=SubtitleStudioPage()
        try:
            assert not reopened.selection_center_toggle.isChecked()
            assert not reopened.timeline.center_playhead_mode
        finally:
            reopened.close_page();reopened.deleteLater();app.processEvents()
    finally:
        page.close_page();page.deleteLater();app.processEvents()


def test_centering_does_not_turn_selection_into_seek(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',10000,13000,'甲'),StudioCue('b',14000,16000,'乙')])
    try:
        calls=[];monkeypatch.setattr(page,'_seek',lambda *a,**k:calls.append(a))
        page.select_cue('b');app.processEvents()
        assert page.selected_cue_id=='b' and not calls
        page._go_to_listed_cue(page._cue_lookup['b'])
        assert calls==[(14.0,)]
    finally:
        page.close_page();page.deleteLater();app.processEvents()
