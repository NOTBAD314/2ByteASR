"""Save sharing detects unversioned writes and GC deferral is finite."""
import copy
import gc
from types import SimpleNamespace
from twobyteasr.acceptance.studio_search_fixture import make_project
from twobyteasr.projects.studio_revisions import StudioRevisionStore,thaw_json
from twobyteasr.projects.studio_save import capture_manual_save


def test_formal_cue_sharing_preserves_direct_edits_and_snapshot_ownership():
    p=make_project(100,3,2)
    store=StudioRevisionStore(p);page=SimpleNamespace(_revision_store=store)
    a=capture_manual_save(page,p,1)
    p.cues[0].appearance_override['direct']={'nested':['before']}
    p.cues[1].text='unversioned new text'
    p.asr_evidence['segment:0']['words'][0]['text']='direct evidence'
    p.generation_metadata['translation_terminology']['enabled']=False
    b=capture_manual_save(page,p,2)
    assert a.cues[10] is b.cues[10]
    assert a.cues[0] is not b.cues[0]
    assert b.to_payload()['cues'][1]['text']=='unversioned new text'
    p.cues[0].appearance_override['direct']['nested'].append('later')
    assert b.to_payload()['cues'][0]['appearance_override']['direct']['nested']==['before']
    assert b.to_payload()['asr_evidence']['segment:0']['words'][0]['text']=='direct evidence'
    assert a.to_payload()['generation_metadata']['translation_terminology']['enabled'] is True
    assert b.to_payload()['generation_metadata']['translation_terminology']['enabled'] is False


def test_freeze_state_shares_words_and_detects_in_place_receipt_changes():
    p=make_project(25,0,0)
    p.studio_state['caption_timeline']={'instances':{c.id:{'words':[{'text':c.text,'start_ms':c.start_ms}]} for c in p.cues},
        'source_archive':[{'id':c.id,'text':c.text} for c in p.cues]}
    store=StudioRevisionStore(p);a=store._frozen_studio_state()
    assert store._frozen_studio_state() is a
    p.studio_state['playhead_ms']=100
    b=store._frozen_studio_state()
    def instances(v):return dict(dict(dict(v.items)['caption_timeline'].items)['instances'].items)
    assert instances(a)['3'] is instances(b)['3']
    p.studio_state['caption_timeline']['instances']['3']['words'][0]['text']='direct'
    c=store._frozen_studio_state()
    assert instances(c)['3'] is not instances(b)['3']
    assert thaw_json(c)==p.studio_state


def test_gc_window_deadline_pressure_and_exception_release(monkeypatch):
    from twobyteasr.playback import playback_gc_budget as b
    from twobyteasr.system import memory_budget
    now=[100.];private=[1000]
    monkeypatch.setattr(b.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(b,'private_bytes',lambda:private[0])
    monkeypatch.setattr(memory_budget,'memory_status',lambda:{'available':2*1024**3})
    enabled=gc.isenabled()
    with b.gui_collection_window('test',max_seconds=3):
        assert b._interaction_window_busy()
        private[0]+=129*1024**2
        assert not b._interaction_window_busy()
        private[0]=1000;now[0]+=4
        assert not b._interaction_window_busy()
    assert not b._interaction_windows and gc.isenabled()==enabled
    try:
        with b.gui_collection_window('failed'):raise RuntimeError('simulate write failure')
    except RuntimeError:pass
    assert not b._interaction_windows


def test_closed_canvas_rejects_late_pause_seek_and_navigation():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=SimpleNamespace(_closing=True)
    # These return before any controller, clock or Qt object is consulted.
    MpvCanvas.set_paused(canvas,True)
    MpvCanvas._apply_requested_pause(canvas,True)
    MpvCanvas.set_navigation_visible(canvas,False)
    MpvCanvas.seek(canvas,1.)
    MpvCanvas._seek_now(canvas,1.)


def test_explicit_source_preview_reload_is_allowed_but_closing_page_is_not():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    page=SimpleNamespace(_close_requested=False);visibility=[]
    canvas=SimpleNamespace(_closing=True,_studio_page=lambda:page,
        isVisible=lambda:True,set_navigation_visible=visibility.append)
    assert MpvCanvas._accept_new_media_load(canvas) is True
    assert not canvas._closing and visibility==[True]
    page._close_requested=True;canvas._closing=True
    assert MpvCanvas._accept_new_media_load(canvas) is False
    assert canvas._closing and visibility==[True]
