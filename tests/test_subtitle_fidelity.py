import copy
import pytest
import subtitle_core
from twobyteasr.subtitle_rules.number_fidelity import format_numbers, numeric_event_values, integer_value, format_segment
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit, SubtitleCue


@pytest.mark.parametrize('source,expected', [
    ('二十 二十','20 20'),('二十，二十','20，20'),('二十 三十','20 30'),
    ('二十到三十','20到30'),('二十加二十','20加20'),('二十加二十等于四十','20加20等于40'),
    ('五点三','5.3'),('六点六','6.6'),('零点一八','0.18'),('百分之十','10%'),
    ('两张卡','两张卡'),('第二局','第二局'),('一会儿 一点也不 死路一条','一会儿 一点也不 死路一条'),
    ('版本一点二点三','版本1.2.3'),('编号二零二零','编号2020'),('20 20','20 20'),
    ('二十二十','二十二十'),('三万三万','三万三万'),('40','40'),
    ('五点三十分','五点三十分'),('三点半','三点半'),
    ('1万','10000'),('1.5万','15000'),('百分之1万','10000%'),('三亿五千万','350000000'),
    ('只是一个周常本','只是一个周常本'),('只有一个','只有一个'),
])
def test_spelling_preserves_events_and_is_idempotent(source,expected):
    actual, events=format_numbers(source)
    assert actual==expected
    assert format_numbers(actual)[0]==actual
    assert numeric_event_values(source)==numeric_event_values(actual)


def test_parser_never_sums_two_spoken_events():
    assert integer_value('二十二十') is None
    assert integer_value('三万三万') is None
    assert integer_value('一百零二')=='102'


def test_word_spans_after_different_length_number_are_retained(monkeypatch):
    from twobyteasr.subtitle_rules import number_fidelity
    from twobyteasr.subtitle_rules.segmentation_alignment import segment_content_timeline
    monkeypatch.setattr(number_fidelity,'preference',lambda:True)
    words=[WordUnit(0,.1,'一',1),WordUnit(.1,.3,'百',1),WordUnit(.3,.4,'二',1),WordUnit(.4,.5,'十',1),
           WordUnit(.9,1.,'二',1),WordUnit(1.,1.1,'十',1),WordUnit(1.8,2.,'好',1)]
    s=SpeechSegment(1,0,2,'一百二十 二十好',1,words)
    format_segment(s)
    assert s.text=='120 20好'
    events=s.caption_arbitration['numeric_formatting'][0]['events']
    assert [(x['audio_start'],x['audio_end']) for x in events]==[(0,.5),(.9,1.1)]
    mapped=segment_content_timeline(s)
    assert [(w.start,w.end) for w in mapped]==[(0,.5)]*3+[(.9,1.1)]*2+[(1.8,2.)]
    before=copy.deepcopy(s);format_segment(s)
    assert s==before


def test_numeric_punctuation_survives_editorial_stage(monkeypatch):
    from twobyteasr.subtitle_rules import number_fidelity
    from twobyteasr.subtitle_rules.text_rules import apply_editorial_segment_rules
    monkeypatch.setattr(number_fidelity,'preference',lambda:True)
    s=SpeechSegment(1,0,2,'二十，二十',1,[])
    assert apply_editorial_segment_rules([s])[0].text=='20，20'


@pytest.mark.parametrize('text',['对 对','别打了 别打了','这个 这个','别打了别打了别打了'])
def test_repetition_is_not_editorial_noise(text):
    from twobyteasr.subtitle_rules.text_rules import normalize_output_text
    assert normalize_output_text(text)==text


@pytest.mark.parametrize('left,right',[('你真到时候开服玩的','时候他估计也就是'),('哎 别别能','不能停下来可以停下来吗？')])
def test_attached_breakpoints_use_word_anchors(left,right):
    from twobyteasr.subtitle_rules.segmentation import repair_mid_word_adjacent_cues
    from twobyteasr.subtitle_rules.text_rules import content_exact
    text=content_exact(left+right)
    words=[WordUnit(i*.12,(i+1)*.12,char,1) for i,char in enumerate(text)]
    s=SpeechSegment(1,0,len(text)*.12,text,1,words)
    cut=len(content_exact(left))
    cues=[SubtitleCue(1,0,cut*.12,left),SubtitleCue(2,cut*.12,s.end,right)]
    out=repair_mid_word_adjacent_cues(cues,[s])
    assert ''.join(content_exact(c.text) for c in out)==text
    assert not (out[0].text.endswith('的') and out[1].text.startswith('时候'))
    assert not (out[0].text.endswith('能') and out[1].text.startswith('不能'))
    assert out[0].end in [w.end for w in words]


def test_short_answer_and_interruption_are_not_merged():
    from twobyteasr.subtitle_rules.cue_cleanup import merge_same_speaker_dangling_cues,merge_isolated_two_character_cues
    rows=[SubtitleCue(1,0,.5,'对',speaker='a'),SubtitleCue(2,.5,1,'确实',speaker='b'),
          SubtitleCue(3,1,2,'他估计也就是',speaker='a')]
    assert len(merge_same_speaker_dangling_cues(copy.deepcopy(rows)))==3
    assert len(merge_isolated_two_character_cues(copy.deepcopy(rows)))==3


def test_repeated_responses_never_cross_other_speaker():
    from twobyteasr.subtitle_rules.cue_cleanup import merge_consecutive_short_repeated_cues
    rows=[SubtitleCue(3,0,.5,'确实',speaker='a'),SubtitleCue(1,.5,.7,'对',speaker='b'),
          SubtitleCue(2,.7,1.,'确实',speaker='a')]
    assert len(merge_consecutive_short_repeated_cues(rows))==3


def test_short_response_survives_minimum_length_refinement():
    from twobyteasr.subtitle_rules.segmentation import refine_resegmented_texts
    source=[SpeechSegment(1,0,2,'确实他估计也就是',1,[])]
    assert refine_resegmented_texts(source,['确实','他估计也就是'])==['确实','他估计也就是']


def test_unaligned_boundary_cannot_claim_word_precision():
    from twobyteasr.subtitle_rules.subtitle_fidelity import aligned_boundary_time
    rows=[SpeechSegment(1,0,6,'面对对你必须',1,[])]
    cues=[SubtitleCue(1,0,2,'面'),SubtitleCue(2,3,6,'对对你必须')]
    assert aligned_boundary_time(*cues,2,rows,[{'start':0,'end':6,'text':'不匹配'}]) is None


def test_overlap_dedup_requires_matching_source_and_time():
    from twobyteasr.subtitle_rules.text_rules import remove_overlapping_duplicate_segments
    def row(n,start,end,source):
        return SpeechSegment(n,start,end,'别打了别打了别打了',1,[],primary_source=source)
    assert len(remove_overlapping_duplicate_segments([row(1,0,2,'a'),row(2,2,4,'a')]))==2
    assert len(remove_overlapping_duplicate_segments([row(1,0,2,'a'),row(2,0,2,'b')]))==2
    assert len(remove_overlapping_duplicate_segments([row(1,0,2,'a'),row(2,0,2,'a')]))==1


def test_final_numeric_recovery_is_bounded_and_preserves_other_turns():
    from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
    segments=[SpeechSegment(1,0,2,'20 20',1,[],speaker='a'),SpeechSegment(2,5,6,'没错',1,[],speaker='b')]
    good=[SubtitleCue(1,0,2,'20 20',speaker='a'),SubtitleCue(2,5,6,'没错',speaker='b')]
    bad=copy.deepcopy(good);bad[0].text='40'
    out=recover_final_content(bad,good,segments,[],subtitle_core)
    assert sorted(c.text for c in out)==['20 20','没错']
    assert out[0] is bad[1]


def test_drifted_cue_stays_with_its_turn_and_is_not_rebuilt_twice():
    # 2026-10-18 (日常 19): a cue that drifted past its turn's end was left out, the
    # turn was rebuilt and the drifted cue kept too: the same words stacked twice.
    from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
    segments=[SpeechSegment(1,10,14,'眼镜眼镜眼镜眼镜',1,[],speaker='a'),SpeechSegment(2,20,22,'下一句话',1,[],speaker='a')]
    final=[SubtitleCue(1,10,12,'眼镜眼镜',speaker='a'),SubtitleCue(2,14.2,16,'眼镜眼镜',speaker='a'),
           SubtitleCue(3,20,22,'下一句话',speaker='a')]
    out=recover_final_content(final,copy.deepcopy(final),segments,[],subtitle_core)
    assert out==final


def test_collapsed_character_times_are_spread_over_the_segment():
    from twobyteasr.subtitle_rules.subtitle_fidelity import _spread_on_source
    text='眼镜眼镜眼镜眼镜眼镜眼镜眼镜眼镜眼镜眼镜'
    row=SpeechSegment(1,10,18,text,1,[WordUnit(10.,10.,c,1) for c in text],speaker='a')
    cues=subtitle_core.build_local_source_cues([row],[])
    assert ''.join(c.text for c in cues)==text and len(cues)>1
    assert all(b.start>=a.end-.001 for a,b in zip(cues,cues[1:])) and cues[-1].end>17
    pieces=[SubtitleCue(1,10,10,text[:5],speaker='a'),SubtitleCue(2,10,10,text[5:],speaker='a')]
    assert _spread_on_source(pieces,[row]) is pieces
    assert [(c.start,c.end) for c in pieces]==[(10,12),(12,18)]
    assert _spread_on_source([SubtitleCue(1,10,10,text[:5],speaker='a')],[row]) is None


def test_local_overlength_repair_preserves_compact_structures():
    from twobyteasr.subtitle_rules.text_rules import content_exact
    text='你真到时候开服玩的时候他估计也就是一个只是一个周长本'
    words=[WordUnit(i*.2,(i+1)*.2,c,1) for i,c in enumerate(text)]
    row=SpeechSegment(1,0,len(text)*.2,text,1,words)
    cues=subtitle_core.build_local_source_cues([row])
    assert ''.join(content_exact(c.text) for c in cues)==text
    assert not any(a.text.endswith('的') and b.text.startswith('时候') for a,b in zip(cues,cues[1:]))
    assert not any(c.text.endswith('估计') for c in cues[:-1])
    assert all(c.end-c.start<=5.05 for c in cues)


def test_missing_alignment_has_explicit_segment_precision():
    from twobyteasr.subtitle_rules.segmentation_alignment import segment_content_timeline
    row=SpeechSegment(1,0,2,'只有字幕没有字戳',1,[])
    segment_content_timeline(row)
    assert row.caption_arbitration['timing_degradation']['precision']=='segment-only'
