"""Local edits share immutable receipts without weakening save/metadata checks."""
import copy
import marshal

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.projects.studio_revisions import StudioRevisionStore, thaw_json
from twobyteasr.rendering.caption_playback_cache import _reuse_caption_state
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand


def project():
    p = SubtitleProject(StudioMedia('', duration_ms=25000),
                        cues=[StudioCue(str(i), i*100, i*100+90, '字幕'+str(i)) for i in range(120)])
    p.validate()
    p.render_settings['_cue_domain'] = 'timeline'
    p.studio_state['caption_timeline'] = dict(version=1, source_archive=[dict(text='原始材料')],
        instances={c.id: dict(text=c.text, words=[dict(text=c.text, start_ms=c.start_ms, end_ms=c.end_ms)]) for c in p.cues})
    p.studio_state['term_word_overrides'] = {'0': {'text': '零'}, '80': {'text': '八十'}}
    return p


def content_edit(p, runtime, cue_id='0'):
    with runtime.transaction(p, action_id='edit', dirty=DirtyDomain.CUE_CONTENT|DirtyDomain.AUTOSAVE,
                             affected_cue_ids=(cue_id,)):
        p.cues[int(cue_id)].text += '修改'
        p.studio_state.setdefault('manual_caption_text', {})[cue_id] = p.cues[int(cue_id)].text


def test_local_content_edit_does_not_hash_the_archive_or_other_receipts(monkeypatch):
    p = project();store = StudioRevisionStore(p);runtime = state_for(p);runtime.subscribe(store.consume)
    before = store.render
    timeline = p.studio_state['caption_timeline']
    original = marshal.dumps
    forbidden = {id(p.studio_state), id(timeline), id(timeline['source_archive']), id(timeline['instances']['80'])}
    def bounded(value, *args):
        assert id(value) not in forbidden, 'local edit scanned unrelated caption data'
        return original(value, *args)
    monkeypatch.setattr(marshal, 'dumps', bounded)
    # Real text commands also remap inline marks and dirty CUE_STYLE.
    SetCueFieldsCommand(p, '0', {'text': '字幕0修改'}, '改字').redo()
    old = dict(dict(before.studio_state.items)['caption_timeline'].items)
    new = dict(dict(store.render.studio_state.items)['caption_timeline'].items)
    assert new['source_archive'] is old['source_archive']
    assert new['instances'] is old['instances']
    assert dict(new['instances'].items)['80'] is dict(old['instances'].items)['80']
    assert store.render.timeline_cues[0].text.endswith('修改')
    assert before.timeline_cues[0].text == '字幕0'
    assert store.render.generation_metadata is before.generation_metadata
    assert thaw_json(store.render.studio_state) == p.studio_state


def test_scoped_receipt_and_override_changes_are_detached_and_saved():
    p = project();store = StudioRevisionStore(p);runtime = state_for(p);runtime.subscribe(store.consume)
    before = store.render
    with runtime.transaction(p, action_id='local_words', dirty=DirtyDomain.CUE_CONTENT|DirtyDomain.AUTOSAVE,
                             affected_cue_ids=('0',)):
        p.cues[0].text = '新字'
        p.studio_state['caption_timeline']['instances']['0']['words'][0]['text'] = '新字'
        p.studio_state['term_word_overrides'].pop('0')
    actual = thaw_json(store.render.studio_state)
    assert actual == p.studio_state
    assert thaw_json(before.studio_state)['caption_timeline']['instances']['0']['words'][0]['text'] == '字幕0'
    assert thaw_json(store.persistence.studio_state) == p.studio_state
    p.studio_state['caption_timeline']['instances']['0']['words'][0]['text'] = '后来更改'
    assert actual['caption_timeline']['instances']['0']['words'][0]['text'] == '新字'


def test_metadata_and_formal_save_still_capture_unscoped_in_place_changes():
    p = project();store = StudioRevisionStore(p);runtime = state_for(p);runtime.subscribe(store.consume)
    with runtime.transaction(p, action_id='metadata', dirty=DirtyDomain.PROJECT_METADATA|DirtyDomain.AUTOSAVE):
        p.studio_state['caption_timeline']['source_archive'][0]['text'] = '更正档案'
    assert thaw_json(store.render.studio_state)['caption_timeline']['source_archive'][0]['text'] == '更正档案'
    p.studio_state['caption_timeline']['instances']['80']['words'][0]['text'] = '直接更正'
    snapshot = store.refresh_persistence(runtime.revision, deep=True)
    assert thaw_json(snapshot.studio_state) == p.studio_state


def test_worker_reuses_only_shared_frozen_branches_and_detaches_changes():
    p = project();store = StudioRevisionStore(p);runtime = state_for(p);runtime.subscribe(store.consume)
    before = store.render.studio_state;plain = thaw_json(before);saved = copy.deepcopy(plain)
    content_edit(p, runtime)
    after = _reuse_caption_state(store.render.studio_state, before, plain)
    assert after == p.studio_state and plain == saved
    assert after['caption_timeline']['source_archive'] is plain['caption_timeline']['source_archive']
    assert after['caption_timeline']['instances']['80'] is plain['caption_timeline']['instances']['80']
    assert after['manual_caption_text'] is not plain.get('manual_caption_text')


def test_qc_after_real_text_edit_uses_current_detached_inputs_without_save_capture(monkeypatch):
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.subtitle_rules.qc_process import evaluate
    p=project();store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    SetCueFieldsCommand(p,'0',{'text':'修改后的字幕'},'改字').redo()
    monkeypatch.setattr(store,'_capture_persistence',lambda *a,**k:(_ for _ in ()).throw(AssertionError('QC recaptured save')))
    snapshot=store.qc_snapshot()
    assert snapshot.cues[0].text=='修改后的字幕'
    assert thaw_json(snapshot.studio_state)==p.studio_state
    engine=SubtitleQCEngine()
    assert evaluate(snapshot,engine.config,())['result'].issues_by_cue==engine.analyze(p).issues_by_cue
    p.cues[0].text='更晚的编辑'
    assert snapshot.cues[0].text=='修改后的字幕'


def test_qc_metadata_change_recaptures_current_model_and_evidence_inputs():
    p=project();store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    with runtime.transaction(p,action_id='evidence',dirty=DirtyDomain.PROJECT_METADATA|DirtyDomain.QC):
        p.generation_metadata['models']={'moss':'current'}
        p.asr_evidence['fresh']={'text':'新证据'}
    snapshot=store.qc_snapshot()
    assert thaw_json(snapshot.generation_metadata)['models']=={'moss':'current'}
    assert thaw_json(snapshot.asr_evidence)['fresh']=={'text':'新证据'}


def test_selection_does_not_retire_qc_but_content_style_and_metadata_do():
    p=project();runtime=state_for(p)
    with runtime.transaction(p,action_id='select',dirty=DirtyDomain.CUE_SELECTION|DirtyDomain.TRANSFORM,
                             affected_cue_ids=('0','1')):pass
    assert runtime.playback_revision>0 and runtime.qc_revision==0
    for number,dirty in enumerate((DirtyDomain.CUE_CONTENT,DirtyDomain.CUE_STYLE,DirtyDomain.PROJECT_METADATA),1):
        with runtime.transaction(p,action_id='edit',dirty=dirty,affected_cue_ids=('0',)):pass
        assert runtime.qc_revision==number
    assert copy.deepcopy(runtime).qc_revision==runtime.qc_revision


def test_inflight_qc_result_survives_selection_but_not_a_real_edit():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_review_ui import StudioReviewMixin
    p=project();runtime=state_for(p);applied=[];restarted=[]
    page=SimpleNamespace(project=p,session=SimpleNamespace(generation=1),_qc_scan_token=3,_qc_worker_snapshot_ms=0,
        _finish_chunked_qc_scan=lambda *a:applied.append(a),_start_chunked_qc_scan=lambda:restarted.append(True))
    page._background_qc_current=lambda identity:StudioReviewMixin._background_qc_current(page,identity)
    token=(id(p),1,runtime.qc_revision,3)
    with runtime.transaction(p,action_id='select',dirty=DirtyDomain.CUE_SELECTION|DirtyDomain.TRANSFORM):pass
    StudioReviewMixin._background_qc_ready(page,token,'current',{})
    assert applied==[(p,'current')] and not restarted
    with runtime.transaction(p,action_id='edit',dirty=DirtyDomain.CUE_CONTENT,affected_cue_ids=('0',)):
        p.cues[0].text='后来改字'
    StudioReviewMixin._background_qc_ready(page,token,'stale',{})
    assert applied==[(p,'current')] and restarted==[True]


def test_autosave_shares_committed_words_and_captures_current_view_decisions(monkeypatch):
    p=project();store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    SetCueFieldsCommand(p,'0',{'text':'修改正文'},'改字').redo()
    p.studio_state['playhead_ms']=3000
    p.studio_state['current_issue_decisions']={'reviewed:0':{'status':'reviewed'}}
    forbidden={id(p.studio_state),id(p.studio_state['caption_timeline']),id(p.studio_state['caption_timeline']['source_archive'])}
    original=marshal.dumps
    def bounded(value,*args):
        assert id(value) not in forbidden,'autosave rehashed committed word archive'
        return original(value,*args)
    monkeypatch.setattr(marshal,'dumps',bounded)
    snapshot=store.refresh_persistence(runtime.revision)
    assert thaw_json(snapshot.studio_state)==p.studio_state
    assert snapshot.cues[0].text=='修改正文'
