import pytest
import subtitle_core as core
from twobyteasr.subtitle_rules import grouping
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result

TEXT = 'I have the idea because flash cards are like bad steam content'
PROPOSED = ['I have the idea', 'because flash cards are like', 'bad steam content']


def segment(text=TEXT, start=0, end=5, speaker='S00', index=1):
    return core.SpeechSegment(index, start, end, text, .9, [], speaker=speaker)


def test_production_repair_keeps_like_comparison_and_exact_steam():
    source = [segment()]
    with language_scope('en'):
        cues = grouping.cues_from_resegmented_texts(source, PROPOSED)
    assert [c.text for c in cues] == ['I have the idea', 'because flash cards are like bad steam content']
    assert validate_grouping_result(source, cues)
    assert 'stream' not in ''.join(c.text for c in cues)


def test_local_fallback_keeps_readable_block_and_contract():
    with language_scope('en'):
        cues = grouping.fallback_group([segment()])
    assert [c.text for c in cues] == [TEXT]
    assert cues.data_validated


def test_real_pause_can_override_like_preference():
    tokens = TEXT.split()
    aligned=[]
    for index, word in enumerate(tokens):
        start = index*.35 + (1.4 if index >= 9 else 0)
        aligned.append(dict(text=word,start=start,end=start+.3,confidence=.99))
    source = [segment(end=aligned[-1]['end'])]
    with language_scope('en'):
        cues = grouping.cues_from_resegmented_texts(source, PROPOSED, aligned)
    assert any(c.text.endswith('like') for c in cues)
    assert validate_grouping_result(source, cues)


def test_speaker_handoff_never_merged_and_long_text_bounded():
    source=[segment('We have to go now. ',end=2,speaker='S00'),
            segment('But I do not want to leave.',start=2,end=5,speaker='S01',index=2)]
    with language_scope('en'):
        cues=grouping.cues_from_resegmented_texts(source,[s.text for s in source])
    assert {c.speaker for c in cues} == {'S00','S01'}
    assert validate_grouping_result(source,cues)
    text = 'We need to find the main bridge before we can go back to the castle and finish this mission. '*3
    source=[segment(text,end=20)]
    with language_scope('en'):
        cues=grouping.fallback_group(source)
    assert len(cues) >= 3 and all(len(c.text)<=84 for c in cues)
    assert validate_grouping_result(source,cues)


def test_chinese_and_japanese_do_not_enter_english_branch(monkeypatch):
    monkeypatch.setattr('twobyteasr.subtitle_rules.english_cue_quality.assemble',
                        lambda *_:pytest.fail('English quality used for another language'))
    for language,text in [('zh','我们先往这边走'),('ja','それではこちらへ行こう')]:
        with language_scope(language):
            cues=grouping.fallback_group([segment(text)])
            assert validate_grouping_result([segment(text)],cues)
