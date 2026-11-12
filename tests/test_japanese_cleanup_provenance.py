import subtitle_core
from copy import deepcopy
from types import SimpleNamespace as NS
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.cue_cleanup import merge_japanese_sentence_cues


def cue(i,text,start,source):
    return NS(cue_id=i,text=text,start=start,end=start+.5,speaker='A',timing_locked=False,
              source_spans=[dict(source_id=source,char_start=0,char_end=len(text),raw_text=text)])


def test_legal_short_join_keeps_both_parent_character_spans():
    a,b=cue(1,'ナノちゃん',0,'source-a'),cue(2,'はい',.55,'source-b')
    with language_scope('ja'):result=merge_japanese_sentence_cues([a,b])
    assert len(result)==1
    assert [p['source_id'] for p in result[0].source_spans]==['source-a','source-b']
    assert result[0].grouping_boundary_receipt['parent_cue_ids']==[1,2]


def test_valid_ai_boundary_is_not_locally_joined_again():
    a,b=cue(1,'ナノちゃん',0,'source-a'),cue(2,'はい',.55,'source-b')
    for c in (a,b):c.grouping_origin='ai_accepted';c.grouping_boundary_receipt={'origin':'ai_accepted'}
    before=deepcopy([a,b])
    with language_scope('ja'):result=merge_japanese_sentence_cues([a,b])
    assert [(c.text,c.start,c.end,c.source_spans) for c in result]==[(c.text,c.start,c.end,c.source_spans) for c in before]


def test_japanese_ai_freeze_requires_measured_phrase_and_hard_boundary_evidence(monkeypatch):
    import twobyteasr.subtitle_rules.grouping as grouping
    from twobyteasr.subtitle_rules import japanese_morphology as morphology
    segments=[NS(segment_id=11,text='ナノちゃんはい',start=0.,end=2.,speaker='A',words=[])]
    monkeypatch.setattr(morphology,'document_phrase_spans',lambda text:[(0,5,'ナノちゃん'),(5,7,'はい')])
    monkeypatch.setattr(grouping,'texts_from_boundary_offsets',lambda *a:['ナノちゃん','はい'])
    monkeypatch.setattr(grouping,'cues_from_resegmented_texts',lambda *a:[cue(1,'ナノちゃん',0,11),cue(2,'はい',.55,11)])
    result=grouping.accepted_japanese_boundaries(segments,[5,7])
    assert result and all(c.grouping_origin=='ai_accepted' for c in result)
    assert grouping.accepted_japanese_boundaries(segments,[4,7]) is None
    assert grouping.accepted_japanese_boundaries(segments,[5,7],required={3}) is None


def test_editorial_filter_does_not_reuse_source_ids_after_empty_row():
    from twobyteasr.recognition.transcript_data import SpeechSegment
    from twobyteasr.subtitle_rules.text_rules import apply_editorial_segment_rules
    for language,words in [('en',('hello','world')),('ja',('ナノちゃん','はい'))]:
        rows=[SpeechSegment(41,0,1,words[0],.8,[]),SpeechSegment(42,2,3,'!!!',.8,[]),SpeechSegment(43,4,5,words[1],.8,[])]
        with language_scope(language):result=apply_editorial_segment_rules(rows)
        assert [r.segment_id for r in result]==[41,43]


def test_overlong_local_split_preserves_complete_parent_offsets():
    import twobyteasr.subtitle_rules.timing as timing
    from twobyteasr.recognition.transcript_data import SubtitleCue
    text='ざそっかそっかでもほらこういう事件もブログに書いてネタとして消費すれば'
    parent=SubtitleCue(199,0,8,text,speaker='A')
    parent.source_spans=[dict(source_id=199,char_start=0,char_end=len(text),raw_text=text,source_time=[0,8])]
    with language_scope('ja'):pieces=timing._repair_cue_on_own_timeline(parent)
    assert len(pieces)>1 and ''.join(c.text.replace(' ','') for c in pieces)==text
    assert all(c.source_spans and c.source_spans[0]['source_id']==199 for c in pieces)
    assert pieces[0].source_spans[0]['char_start']==0
    assert pieces[-1].source_spans[-1]['char_end']==len(text)
