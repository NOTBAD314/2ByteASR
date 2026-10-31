"""Review starts at a stable active caption, or at the playhead."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.subtitle_rules.studio_qc import QCIssue, QCResult, QCSeverity, QCCategory
from twobyteasr.subtitle_rules.current_issues import invalidate
from tests.test_review_replay_and_window_bounds import _page

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('first',1000,2000,'第一条'),
        StudioCue('middle',8000,10000,'中间条'),StudioCue('last',14000,16000,'最后条')])
    page.project._qc_result=QCResult({'first':(QCIssue('invalid_time',QCSeverity.CRITICAL,
        QCCategory.TIMELINE,'first','时间检查','test'),)})
    invalidate(page.project)
    page.cue_model.refresh()
    page.seek_requests=[]
    monkeypatch.setattr(page,'_seek',lambda seconds:page.seek_requests.append(seconds))
    yield app,page
    page.close_page();page.deleteLater();app.processEvents()

def test_explicit_middle_outside_default_filter_is_preserved(workspace):
    app,page=workspace
    page.select_cue('middle');page._set_review_mode(True)
    assert page.selected_cue_id=='middle'
    assert page.cue_model.row_for_cue_id('middle')>=0
    assert page.seek_requests[-1]==8.0
    assert not page.project._qc_result.issues_by_cue.get('middle')

@pytest.mark.parametrize('milliseconds,expected',[(9000,'middle'),(12000,'last'),(19000,'last')])
def test_without_explicit_selection_uses_playhead_and_nearest_gap(workspace,milliseconds,expected):
    _,page=workspace
    page.timeline.explicit_subtitle_id=''
    page.timeline.set_playhead(milliseconds)
    page._set_review_mode(True)
    assert page.selected_cue_id==expected

def test_multiselect_uses_active_item_not_first(workspace):
    _,page=workspace
    page.timeline.set_selected_ids({'first','last'},'last')
    page.timeline.explicit_subtitle_id='first'  # a stale explicit item still in the set cannot override the active item
    page._set_review_mode(True)
    assert page.selected_cue_id=='last'

def test_overlap_prefers_current_track_header_over_historical_speaker(workspace):
    _,page=workspace
    page._cue_lookup['last'].start_ms=8000;page._cue_lookup['last'].end_ms=10000
    page._cue_lookup['last'].speaker_id='current-track'
    page.timeline.explicit_subtitle_id='';page.timeline.set_playhead(9000)
    page.session.preferred_subtitle_speaker=page._cue_lookup['middle'].speaker_id
    page.timeline.selected_track_header=('subtitle','current-track')
    assert page._review_entry_target()==('last','original')

def test_translation_layer_survives_review_entry_outside_pending_filter(workspace):
    _,page=workspace
    from twobyteasr.subtitle_rules.subtitle_translation import migrate
    page.project.generation_metadata['translations']={'middle':'翻译后的当前句子'}
    migrate(page.project)
    page.timeline.select_translation('middle');page._set_review_mode(True)
    assert page.selected_cue_id=='middle' and page.timeline.active_subtitle_layer=='translation'
    target=page._resolve_caption_edit_target()
    assert target.cue_id=='middle' and target.layer=='translation'

def test_deferred_qc_entry_captures_target_before_refresh(workspace):
    _,page=workspace
    result=page.project._qc_result
    del page.project._qc_result
    page.select_cue('middle');page._set_review_mode(True)
    assert not page._review_mode
    page.project._qc_result=result
    page.timeline.explicit_subtitle_id='first'
    page._pending_review_start=None
    page._set_review_mode(True)
    assert page.selected_cue_id=='middle'
