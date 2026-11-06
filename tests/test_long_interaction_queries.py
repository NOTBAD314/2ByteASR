from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, StudioSpeaker
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_cue_controller import StudioCueController

APP=QApplication.instance() or QApplication([])

def make():
    p=SubtitleProject(StudioMedia('missing.mp4',duration_ms=10000),
        speakers=[StudioSpeaker('S1','One')],cues=[StudioCue('a',0,5000,'a','S1'),StudioCue('b',2000,3000,'b','S1')])
    p.validate();r=state_for(p)
    s=StudioSession(project=p,runtime=r,_cue_lookup=r.cue_by_id)
    page=SimpleNamespace(timeline=SimpleNamespace(hidden_speakers=set(),locked_speakers=set(),selected_track_header=None,_speaker_ids=['S1']),_subtitle_track_visibility={})
    return p,s,page,StudioCueController(page,s)

def test_bound_clock_queries_do_not_revalidate_all_ids(monkeypatch):
    p,s,page,c=make()
    monkeypatch.setattr('twobyteasr.studio.studio_cue_controller.state_for',lambda *_:pytest.fail('full legacy scan'))
    assert c.resolve_playhead_target(2500).id=='b'
    assert c.resolve_playhead_target(3500).id=='a' # long overlapping caption
    page.timeline.hidden_speakers.add('S1')
    assert c.resolve_playhead_target(2500) is None

def test_bound_query_tracks_edits_undo_and_project_replacement():
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
    p,s,page,c=make();command=SetCueFieldsCommand(p,'b',{'start_ms':6000,'end_ms':7000},'move')
    command.redo();assert c.resolve_playhead_target(2500).id=='a'
    command.undo();assert c.resolve_playhead_target(2500).id=='b'
    other,_,_,_=make();other.cues[0].id='replacement';state_for(other)
    s.project=other # old session index must not authorize this project's query
    assert c.resolve_playhead_target(100).id=='replacement'

def test_many_selected_rectangles_use_visible_overlap_index():
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.timeline.studio_selection import ClipSelection
    p,s,page,c=make()
    p.cues.extend(StudioCue(str(i),10000+i*2000,11000+i*2000,'far','S1') for i in range(200))
    t=WaveformTimeline();t.resize(1400,350);t.set_project(p);t.set_visible_window(0,4000)
    try:
        items=t._selection_items(ClipSelection(cue_ids={x.id for x in p.cues}))
        assert {x[1] for x in items if x[0]=='subtitle'}=={'a','b'}
    finally:t._thumbnails.close();t._thumbnails.thread.join(2);t.close()

@pytest.mark.parametrize('language',['original','translation'])
def test_operation_local_bilingual_geometry_is_identical(language):
    from twobyteasr.caption_style.caption_layer_transform import displayed_layer,resolved_values
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    p,s,page,c=make();p.generation_metadata['translations']={'a':'Translated line'}
    p.studio_state['bilingual']={'mode':'bilingual','layout':'ink_v1'}
    cue=p.cues[0];shown=displayed_layer(p,cue,language)
    expected=resolved_values(p,cue,language)
    style=resolve_caption_style(p.styles,p.speakers,shown,p.style_recipes,1920).style
    assert resolved_values(p,cue,language,displayed=shown,resolved_style=style)==expected

def test_seek_revision_change_restarts_latest_target_before_reveal():
    from twobyteasr.studio.caption_seek_preparation import CaptionSeekPreparation
    calls=[];request=dict(scope='same',revision=1,target=12345,accurate=True,phase='reveal')
    obj=SimpleNamespace(pending=request,closed=False,page=SimpleNamespace(
        session=SimpleNamespace(runtime=SimpleNamespace(revision=2)),video=object()),
        _scope=lambda:'same',request=lambda *args:calls.append(args))
    CaptionSeekPreparation.tick(obj)
    assert calls==[(12.345,True)]

def test_delete_does_not_realign_or_copy_unchanged_word_receipts(monkeypatch):
    import copy
    from twobyteasr.timeline.studio_commands import delete_cues_command
    from twobyteasr.timeline import studio_caption_timeline as ct
    p,s,page,c=make();p.render_settings['_cue_domain']='timeline'
    p.studio_state[ct.KEY]={'version':1,'instances':{'a':{'text':'a','words':[{'text':'a','start_ms':0,'end_ms':10}]}}}
    before=copy.deepcopy((p.cues,p.studio_state))
    monkeypatch.setattr(ct,'_words',lambda *_:pytest.fail('deletion cannot need word alignment'))
    cmd=delete_cues_command(p,['a','b']);cmd.redo()
    assert p.cues==[] and p.studio_state[ct.KEY]==before[1][ct.KEY]
    cmd.undo();assert p.cues==before[0] and p.studio_state[ct.KEY]==before[1][ct.KEY]
    cmd.redo();assert p.cues==[]

def test_translation_splice_does_not_copy_unaffected_history():
    from twobyteasr.timeline.caption_translation_splice import TranslationSplice
    class Unrelated(dict):
        def __deepcopy__(self,memo):pytest.fail('unaffected translation history copied')
    p,s,page,c=make()
    # A valid existing container lets the splice keep unrelated records in
    # place; only the edited cue's private undo values are copied.
    p.generation_metadata['translation_records']={'version':1,'records':{'z':Unrelated(text='untouched')},'extra':{'x':1}}
    splice=TranslationSplice(p,[p.cues[0]],[])
    assert splice.template['records']=={} and splice.template['extra']=={'x':1}
    p.generation_metadata['translation_records']['extra']['x']=2
    assert splice.template['extra']['x']==1

def test_input_gc_deferral_expires_and_private_growth_is_bounded():
    from twobyteasr.playback.playback_gc_budget import GuiThreadCollector
    now=[10.];memory=[1024**3]
    collector=GuiThreadCollector(memory_reader=lambda:memory[0],clock=lambda:now[0])
    collector.note_interaction();assert collector._input_is_busy()
    memory[0]+=collector.INPUT_MAX_GROWTH
    assert not collector._input_is_busy()
    now[0]=12.;collector.note_interaction();assert collector._input_is_busy()
    now[0]+=collector.INPUT_IDLE_S+.01
    assert not collector._input_is_busy()
    collector.deleteLater()

def test_input_gc_unknown_memory_cannot_defer_indefinitely():
    from twobyteasr.playback.playback_gc_budget import GuiThreadCollector
    now=[10.];collector=GuiThreadCollector(memory_reader=lambda:None,clock=lambda:now[0])
    collector.note_interaction();assert collector._input_is_busy()
    for _ in range(6):now[0]+=.4;collector.note_interaction()
    assert not collector._input_is_busy()
    collector.deleteLater()

def test_media_health_refresh_ignores_retired_controls():
    from twobyteasr.studio.studio_media_availability import StudioMediaAvailability
    StudioMediaAvailability.refresh(SimpleNamespace(page=SimpleNamespace(_close_requested=False)))

def test_project_settle_recognizes_recent_input(monkeypatch):
    from twobyteasr.playback import playback_gc_budget as budget
    calls=[]
    monkeypatch.setattr(budget,'_holders',set())
    monkeypatch.setattr(budget,'input_collection_deferred',lambda:True)
    monkeypatch.setattr(budget,'_collect_observed',lambda *a,**k:calls.append(k))
    policy=budget.ProjectHeapPolicy()
    policy.settle()
    assert not calls and policy.settle_timer.isActive()
    monkeypatch.setattr(budget,'input_collection_deferred',lambda:False)
    policy.settle()
    assert len(calls)==1 and not policy.settle_timer.isActive()
    policy.close();policy.deleteLater()

def test_table_activation_keeps_only_latest_and_flushes_before_edit():
    from PySide6.QtWidgets import QWidget
    from PySide6.QtTest import QTest
    p,s,_,_=make();page=QWidget();page._close_requested=False
    page.cue_model=SimpleNamespace(index=lambda row,col:['a','b'][row],data=lambda value,role:value)
    selected=[];seeks=[];page._seek=seeks.append
    class Controller(StudioCueController):
        def select_cue(self,cue_id,**kwargs):
            self._table_refresh_serial+=1;self._pending_table_activation=None;selected.append(cue_id)
    c=Controller(page,s)
    s.selected_cue_id='a';c.table_activated(SimpleNamespace(row=lambda:0))
    s.selected_cue_id='b';c.table_activated(SimpleNamespace(row=lambda:1))
    c._mirror_clock_selection('a') # stale decoded frame before deferred activation
    assert s.selected_cue_id=='b' and not selected
    c.flush_table_activation() # focus/typing must see the clicked binding now
    QTest.qWait(35)
    assert selected==['b'] and seeks==[2.]
    page.close();page.deleteLater()

def test_table_activation_rejects_closed_project():
    from PySide6.QtWidgets import QWidget
    from PySide6.QtTest import QTest
    p,s,_,_=make();page=QWidget();page._close_requested=False
    page.cue_model=SimpleNamespace(index=lambda *a:'a',data=lambda value,role:value)
    page._seek=lambda *_:pytest.fail('old seek after project replacement')
    c=StudioCueController(page,s);s.selected_cue_id='a'
    c.table_activated(SimpleNamespace(row=lambda:0));s.close('switch')
    QTest.qWait(35)
    assert c._pending_table_activation is None
    page.close();page.deleteLater()
