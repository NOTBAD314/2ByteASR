"""Save-only review data does not require full render/receipt preparation."""
from dataclasses import asdict
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
from twobyteasr.projects.studio_revisions import StudioRevisionStore,thaw_json,freeze_json
from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand

def project():
    p=SubtitleProject(StudioMedia('',duration_ms=10000),cues=[StudioCue(str(i),i*100, i*100+90,'字') for i in range(80)])
    p.validate();p.render_settings['_cue_domain']='timeline'
    p.studio_state['caption_timeline']={'version':1,'instances':{c.id:{'text':c.text,'words':[{'text':'字','start_ms':c.start_ms,'end_ms':c.end_ms}]} for c in p.cues}}
    return p

def test_save_only_retention_preserves_render_and_saves_current_metadata(monkeypatch):
    p=project();store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    before=store.render
    monkeypatch.setattr(store,'_capture_render',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('render recaptured')))
    with runtime.transaction(p,action_id='retain',dirty=DirtyDomain.AUTOSAVE,snapshot_cues=False):
        p.studio_state['glossary_proofread_review']={'version':1,'rows':{'40':{'retained':True}}}
    assert store.render.cues is before.cues and store.render.studio_state is before.studio_state
    assert thaw_json(store.persistence.studio_state)['glossary_proofread_review']['rows']['40']['retained']

def test_independent_cue_dtos_are_reused_and_receipts_roundtrip_exactly():
    p=project();store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    before=store.render.timeline_cues
    BatchReplaceTextCommand(p,{'40':'修改过'}).redo()
    after=store.render.timeline_cues
    assert len(after)==80 and after[40].text=='修改过'
    assert after[39] is before[39] and after[41] is before[41]
    assert thaw_json(store.persistence.studio_state)==thaw_json(freeze_json(p.studio_state))

def test_hidden_edit_keeps_save_current_and_publishes_latest_render_once(monkeypatch):
    p=project();store=StudioRevisionStore(p);runtime=state_for(p)
    runtime.subscribe(lambda delta:store.consume(delta,prepare_render=False))
    before=store.render
    BatchReplaceTextCommand(p,{'40':'第一次'}).redo()
    BatchReplaceTextCommand(p,{'40':'最后一次'}).redo()
    assert store.render is before
    assert store.persistence.cues[40].text=='最后一次'
    published=store.materialize_render()
    assert published.timeline_cues[40].text=='最后一次'
    assert store.materialize_render() is published
