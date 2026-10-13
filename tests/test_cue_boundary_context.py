from types import SimpleNamespace
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.studio_cue_controller import StudioCueController
from twobyteasr.studio_runtime_state import state_for
from twobyteasr.selection_scope import SelectionScope


@pytest.fixture
def controller():
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia('missing.mp4',duration_ms=30000),
        cues=[StudioCue('a',10000,12000,'原文20','S01'),StudioCue('b',15000,17000,'下一条','S02')])
    p.validate(); messages=[]; ripple=[]
    session=SimpleNamespace(project=p,selected_cue_id='a',_cue_lookup=state_for(p).cue_by_id,undo_stack=QUndoStack())
    page=SimpleNamespace(_manual_selection_hold=True, timeline=SimpleNamespace(playhead_ms=11000,
        selected_track_header=None,selected_video_clip_id='',locked_speakers=set()),
        save_state=SimpleNamespace(setText=messages.append),
        selection_model=SimpleNamespace(scope=SelectionScope.explicit(['a'],'a')),
        _ripple_video_to_playhead=ripple.append)
    class Controller(StudioCueController):
        def cue_changed(self,*a,**k): pass
    c=Controller(page,session)
    return c,p,messages,ripple


@pytest.mark.parametrize('edge,point,expected', [('start',11000,(11000,12000)),('end',11000,(10000,11000)),
    ('start',9000,(9000,12000)),('end',12300,(10000,12300))])
def test_qw_one_undoable_boundary_no_other_mutations(controller,edge,point,expected):
    c,p,messages,ripple=controller; before=p.to_dict()['cues']; c.page.timeline.playhead_ms=point
    c.trim_to_playhead(edge)
    assert (p.cues[0].start_ms,p.cues[0].end_ms)==expected
    assert p.cues[0].text=='原文20' and p.to_dict()['cues'][1]==before[1] and not ripple
    assert c.session.undo_stack.count()==1
    c.session.undo_stack.undo(); assert p.to_dict()['cues']==before
    c.session.undo_stack.redo(); assert (p.cues[0].start_ms,p.cues[0].end_ms)==expected


@pytest.mark.parametrize('edge,point',[('start',12000),('start',13000),('end',9999),('end',10049)])
def test_invalid_boundaries_do_not_mutate(controller,edge,point):
    c,p,messages,ripple=controller;c.page.timeline.playhead_ms=point
    c.trim_to_playhead(edge)
    assert c.session.undo_stack.count()==0 and messages and not ripple


@pytest.mark.parametrize('context',['video','audio'])
def test_video_context_is_not_hijacked_by_cue_highlight(controller,context):
    c,p,messages,ripple=controller
    c.page.timeline.selected_track_header=(context,'V1')
    c.trim_to_playhead('start'); assert ripple==['start'] and c.session.undo_stack.count()==0


def test_clock_highlight_inside_a_caption_is_the_qw_target(controller):
    # ADR 0104 (2026-10-11): without an explicit click, Q/W edit the caption
    # under the playhead in one press (it supersedes ADR 0077's video default).
    c,p,messages,ripple=controller
    c.page._manual_selection_hold=False
    type(c)._mirror_clock_selection=lambda self,cue_id:None
    c.trim_to_playhead('start')
    assert not ripple and c.session.undo_stack.count()==1 and p.cues[0].start_ms==11000


def test_locked_and_multi_selection_refused(controller):
    c,p,messages,ripple=controller;c.page.timeline.locked_speakers={'S01'}
    c.trim_to_playhead('start');assert messages and c.session.undo_stack.count()==0
    c.page.timeline.locked_speakers.clear();c.page.selection_model.scope=SelectionScope.explicit(['a','b'],'a')
    c.trim_to_playhead('end');assert c.session.undo_stack.count()==0 and not ripple
