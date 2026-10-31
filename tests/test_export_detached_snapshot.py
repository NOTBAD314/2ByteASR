"""An export snapshot must not traverse a live page's callback graph."""
from copy import deepcopy
import pytest
from twobyteasr.exports.export_timeline import export_project_snapshot
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_runtime_state import state_for

class LiveOwner:
    def __deepcopy__(self,memo):
        raise AssertionError('export traversed a live GUI/runtime owner')

def test_snapshot_owns_only_document_data_and_keeps_pending_edits():
    p=SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('cue',0,1000,'已保存的编辑')])
    p.validate()
    p._runtime_owner=LiveOwner()
    p._analysis_cache={'callback_owner':LiveOwner()}
    state_for(p)._subscribers.append(LiveOwner())
    frozen=export_project_snapshot(p)
    assert frozen.cues[0].text=='已保存的编辑'
    assert not any(k in frozen.__dict__ for k in ('_runtime_owner','_analysis_cache','_studio_state_runtime'))
    frozen.cues[0].text='worker changed'
    frozen.studio_state['only_worker']=True
    assert p.cues[0].text=='已保存的编辑' and 'only_worker' not in p.studio_state

def test_export_rejects_snapshot_of_half_committed_transaction():
    p=SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('cue',0,1000,'字幕')])
    p.validate()
    from twobyteasr.projects.studio_runtime_state import DirtyDomain
    with state_for(p).transaction(p,action_id='test',dirty=DirtyDomain.CUE_CONTENT,affected_cue_ids=('cue',)):
        with pytest.raises(RuntimeError,match='事务'):
            export_project_snapshot(p)

def test_export_entry_waits_for_the_last_style_request_before_borrowing_canvas():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    calls=[]
    page=SimpleNamespace(project=object(),_preview_path='owned-test.mp4',
        style_controller=SimpleNamespace(flush_pending_application=lambda:(calls.append('flush') or False)))
    SubtitleStudioPage._open_render_dialog(page)
    assert calls==['flush']
