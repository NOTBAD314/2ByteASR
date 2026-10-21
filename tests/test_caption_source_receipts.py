import copy
from pathlib import Path
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.caption_source_receipts import initialize_recognition_receipts, recover_caption_sources
from twobyteasr.timeline.studio_caption_timeline import caption_replacement_receipts
from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses


def result():
    p = SubtitleProject(media=StudioMedia(path='task.wav', duration_ms=3000),
        cues=[StudioCue('job-cue-1', 100, 900, '正确转写', evidence_refs=['segment:1'])])
    p.asr_evidence = {'segment:1': dict(start_ms=100, end_ms=900, primary_source='moss',
        moss_text='原始甲', firered_text='原始乙', qwen_text='原始丙')}
    return p


def test_new_result_replaces_stale_empty_receipts_without_faking_transcripts():
    p = result(); raw=copy.deepcopy(p.asr_evidence)
    source=copy.deepcopy(p)
    p.render_settings['_cue_domain']='timeline'
    p.studio_state['caption_timeline']={'instances':{},'source_archive':[]}
    initialize_recognition_receipts(p,source)
    cue=p.cues[0];cue.start_ms=5000;cue.end_ms=6000;cue.text='人工改过'
    hypotheses=cue_source_hypotheses(p,cue)
    assert {h['text'] for h in hypotheses}=={'原始甲','原始乙','原始丙'}
    assert all(h['coverage_unknown'] for h in hypotheses)
    assert p.asr_evidence==raw
    reopened=SubtitleProject.from_dict(p.to_dict())
    assert cue_source_hypotheses(reopened,reopened.cues[0])==hypotheses


def test_source_spans_survive_split_and_merge_even_without_word_alignment():
    p=result();initialize_recognition_receipts(p,copy.deepcopy(p))
    left=copy.deepcopy(p.cues[0]);right=copy.deepcopy(left);right.id='split-2'
    left.text='正确';right.text='转写';left.end_ms=500;right.start_ms=500
    _,after=caption_replacement_receipts(p,p.cues,[left,right])
    assert after[left.id]['source_spans']==after[right.id]['source_spans']
    assert after[right.id]['source_cue_ids']==['job-cue-1']


def test_recovery_rejects_wrong_task_and_preserves_manual_edit(monkeypatch):
    import twobyteasr.recognition.recognition_result as module
    p=result();source=copy.deepcopy(p);source.project_id='wrong-task'
    p.render_settings['_cue_domain']='timeline'
    p.generation_metadata['recognition_result']={'path':'foreign','job_id':'wrong'}
    monkeypatch.setattr(module,'verify_result_reference',lambda _:source)
    before=copy.deepcopy(p.cues)
    assert recover_caption_sources(p)==0
    assert p.cues==before and p.studio_state['caption_timeline']['source_recovery']['status']=='unavailable'


def test_mixed_local_and_neighbor_context_cannot_be_adopted(monkeypatch):
    import twobyteasr.recognition.asr_source_evidence as evidence
    from twobyteasr.subtitle_rules.studio_qc import model_evidence, review_candidates
    p = result()
    monkeypatch.setattr(evidence, 'cue_source_hypotheses', lambda *_args, **_kwargs: [
        dict(model='moss', text='本条纠正', context_only=False),
        dict(model='moss', text='下一位说话人', context_only=True),
    ])
    assert model_evidence(p, p.cues[0])[0].context_only
    candidates = review_candidates(p, p.cues[0])
    assert candidates[0].sources == ('Current',) and not candidates[0].context_only
    assert candidates[1].context_only
