"""A stale view object cannot turn a real entity edit into a false no-op."""
import copy
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.projects.studio_runtime_state import state_for

def test_replaced_model_with_stale_view_text_still_writes_authoritative_cue(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',0,5000,'Authoritative before')])
    try:
        stale=page.session._cue_lookup['a']
        page.project.cues=copy.deepcopy(page.project.cues)
        stale.text='Requested new value'
        state_for(page.project).reindex_cues(page.project)
        assert page.cue_controller.set_text('a','Requested new value')
        assert page.project.cues[0].text=='Requested new value'
        page.undo_stack.undo()
        assert page.project.cues[0].text=='Authoritative before'
    finally:page.close_page();page.deleteLater();app.processEvents()
