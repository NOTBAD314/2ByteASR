"""Synthetic timings and invented evidence, using only the user's quoted captions."""
from copy import deepcopy
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker
from twobyteasr.subtitle_rules.studio_qc import review_candidates,SubtitleQCEngine
from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses,annotate_suggestions
from twobyteasr.subtitle_rules.machine_text_policy import machine_text_allowed


def suggestions(p,cue):
    candidates=review_candidates(p,cue)
    return annotate_suggestions(p,cue,review_suggestions(cue.text,[(c.text,c.sources) for c in candidates[1:] if not c.context_only],pronouns=False))


def mixed(*,independent=False):
    blue='第一个连水友可以吧';source='合成前文'+blue
    p=SubtitleProject(StudioMedia('',duration_ms=20000),speakers=[StudioSpeaker('blue'),StudioSpeaker('green')],cues=[
        StudioCue('b',10000,14000,blue,speaker_id='blue',evidence_refs=['blue-ref']),
        StudioCue('g',11000,12000,'好好好',speaker_id='green',evidence_refs=['green-ref'])])
    p.asr_evidence={'blue-ref':dict(start_ms=10000,end_ms=14000,speaker_id='blue',primary_source='moss',moss_text=source,
        firered_text='合成前文第一个连好好可以吗',speaker_independent=independent),
        'green-ref':dict(start_ms=11000,end_ms=12000,speaker_id='green',primary_source='moss',moss_text='好好好')}
    return p


def test_synthetic_long_mixture_does_not_borrow_green_response():
    p=mixed();evidence=deepcopy(p.asr_evidence)
    assert not suggestions(p,p.cues[0])
    candidates=[r for r in cue_source_hypotheses(p,p.cues[0]) if r.get('candidate_partial')]
    assert candidates and all(r['context_only'] for r in candidates if '好好' in r['text'])
    assert p.asr_evidence==evidence


def test_explicit_independent_speaker_evidence_is_not_overruled_by_text_guess():
    p=mixed(independent=True)
    rows=cue_source_hypotheses(p,p.cues[0])
    assert any(r['model']=='firered' and not r['context_only'] and r['speaker_id']=='blue' for r in rows)


def clipped(text,reading,*,head=True):
    # The first or last token is outside the displayed cue in this synthetic clock.
    count=len(text);words=[]
    for i,char in enumerate(text):
        a=10000+i*200;b=a+100
        words.append(dict(text=char,start_ms=a,end_ms=b))
    start=10150 if head else 10000;end=10000+count*200 if head else 10000+(count-1)*200-10
    cue=StudioCue('c',start,end,text,speaker_id='s',evidence_refs=['ref'])
    p=SubtitleProject(StudioMedia('',duration_ms=20000),cues=[cue])
    p.asr_evidence={'ref':dict(start_ms=10000,end_ms=10000+count*200,speaker_id='s',primary_source='moss',text=text,moss_text=text,firered_text=reading,words=words)}
    return p,cue


def test_synthetic_time_crop_is_not_a_pronoun_deletion():
    p,cue=clipped('他这里会打打雪仗我们走吧','他这里会打打雪仗我们走吧')
    assert not suggestions(p,cue)
    assert p.asr_evidence['ref']['firered_text'].startswith('他')


def test_synthetic_time_crop_keeps_independent_spelling_fix():
    p,cue=clipped('这里他这个炮米花算是解掉了','这里他这个爆米花算是解掉了')
    rows=suggestions(p,cue)
    assert [(r.original,[o.text for o in r.options]) for r in rows]==[('炮',['爆'])]


@pytest.mark.parametrize('word',['好好好','行行行行','对对对','可以试试'])
def test_normal_response_shortening_is_not_a_machine_cleanup(word):
    assert not machine_text_allowed(word,word[1:])


def test_complete_reference_omission_is_not_an_explicit_delete_instruction():
    cue=StudioCue('c',10000,14000,'错误重复',speaker_id='s',evidence_refs=['ref'])
    p=SubtitleProject(StudioMedia('',duration_ms=20000),cues=[cue])
    p.asr_evidence={'ref':dict(start_ms=10000,end_ms=14000,speaker_id='s',primary_source='moss',moss_text=cue.text,firered_text='错误')}
    rows=suggestions(p,cue)
    assert not rows and cue.text=='错误重复'


def test_same_flow_boundary_is_not_shortened_to_another_speaker():
    from twobyteasr.subtitle_rules.display_timing import project_display_tail_plan
    p=SubtitleProject(StudioMedia('',duration_ms=20000),cues=[
        StudioCue('a',10000,12080,'这是蓝色连续前句',speaker_id='blue',evidence_refs=['a']),
        StudioCue('c',12000,13000,'绿色同时进入的完整插话',speaker_id='green',evidence_refs=['c']),
        StudioCue('b',12080,14000,'这是蓝色连续后句',speaker_id='blue',evidence_refs=['b'])])
    p.asr_evidence={'a':dict(acoustic_start_ms=10000,acoustic_end_ms=11950),
        'c':dict(acoustic_start_ms=12000,acoustic_end_ms=13000),
        'b':dict(acoustic_start_ms=12080,acoustic_end_ms=14000)}
    changes,_=project_display_tail_plan(p)
    assert 'a' not in changes and p.cues[1].end_ms==13000


def test_whole_issue_keep_suppresses_same_mark_until_evidence_changes():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.subtitle_rules.current_issues import pending_review_changes,unhandled_suggestion,invalidate,current_issue_view
    from twobyteasr.studio.caption_editor import IssueDecisionsCommand
    app=QApplication.instance() or QApplication([])
    cue=StudioCue('c',10000,14000,'我们在营第等一下',speaker_id='s',evidence_refs=['ref'])
    p=SubtitleProject(StudioMedia('',duration_ms=20000),cues=[cue])
    p.asr_evidence={'ref':dict(start_ms=10000,end_ms=14000,speaker_id='s',primary_source='moss',moss_text=cue.text,firered_text='我们在营地等一下')}
    p._qc_result=SubtitleQCEngine().analyze(p);invalidate(p)
    row=suggestions(p,cue)[0]
    changes,_,_=pending_review_changes(p);command=IssueDecisionsCommand(p,changes)
    command.redo()
    assert unhandled_suggestion(p,cue.id,'original',row) is None
    command.undo();assert unhandled_suggestion(p,cue.id,'original',row) is not None
    command.redo()
    p.asr_evidence['ref']['firered_text']='我们在营区等一下'
    p._qc_result=SubtitleQCEngine().analyze(p);invalidate(p)
    updated=suggestions(p,cue)[0]
    assert unhandled_suggestion(p,cue.id,'original',updated) is not None
