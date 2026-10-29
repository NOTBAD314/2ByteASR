import copy

import pytest

from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.subtitle_rules.number_fidelity import format_numbers, format_segment


@pytest.mark.parametrize('source,expected', [
    ('一个 两个办法 一会儿 一起 一技能 二技能', '一个 两个办法 一会儿 一起 一技能 二技能'),
    ('只有一个 一共九个 三抽 第二局', '只有一个 一共九个 三抽 第二局'),
    ('十个 二十 二十 十二秒', '10个 20 20 12秒'),
    ('零点五秒 零点八九 百分之二 二比三', '0.5秒 0.89 2% 2比3'),
    ('十有八九 一心一意 十全十美 三十六计', '十有八九 一心一意 十全十美 三十六计'),
    ('十几个 二三十个 一百来个 两三个 十来分钟', '十几个 二三十个 一百来个 两三个 十来分钟'),
    ('1个 2个 v1.0.5 S0PP 编号001', '1个 2个 v1.0.5 S0PP 编号001'),
])
def test_default_conservative_policy(source, expected):
    actual, _ = format_numbers(source)
    assert actual == expected
    assert format_numbers(actual)[0] == actual


# 2026-10-16: a lone 十 before 分 is the adverb unless a scoring word, 钟/制/以上/
# 以下/左右 or clause edges make it ten points or minutes (十分感谢 was 10分感谢).
@pytest.mark.parametrize('source,expected', [
    ('十分感谢 十分重要 十分好', '十分感谢 十分重要 十分好'),
    ('他十分厉害 感到十分高兴 打得十分精彩 伤害十分高 十分十分感谢', '他十分厉害 感到十分高兴 打得十分精彩 伤害十分高 十分十分感谢'),
    ('打了十分 得了十分 扣十分 领先十分 满分十分', '打了10分 得了10分 扣10分 领先10分 满分10分'),
    ('这把十分！', '这把十分！'),  # no scoring word: kept as written, reads the same
    ('十分！', '10分！'),
    ('十分钟 等了十分钟 十分左右 十分以上', '10分钟 等了10分钟 10分左右 10分以上'),
    ('三十分 九十分 五点三十分 十点十分', '30分 90分 五点三十分 十点十分'),
])
def test_adverb_shifen_keeps_source_while_scores_and_minutes_convert(source, expected):
    actual, _ = format_numbers(source)
    assert actual == expected
    assert format_numbers(actual)[0] == actual


def test_adverb_shifen_is_one_judgement_for_restore_cuts_and_check():
    import subtitle_core as legacy  # noqa: F401  (loads the core before the timing helpers)
    from twobyteasr.subtitle_rules.number_fidelity import numeric_event_values, numeric_unsafe_cut_offsets
    # An AI edit that wrote the adverb as 10分 is restored; a score is not.
    result, receipts = format_numbers('10分感谢 打了10分', source_text='十分感谢 打了十分')
    assert result == '十分感谢 打了10分'
    assert [r['reason'] for r in receipts] == ['protected_source_spelling']
    assert numeric_event_values('十分感谢 十分重要') == ()
    assert numeric_event_values('打了十分 十分钟') == ('10', '10')
    # 打了｜十分 would leave 十分 an adverb on its own line, so it is not a safe cut.
    assert 3 in numeric_unsafe_cut_offsets('他打了十分很厉害')
    assert not numeric_unsafe_cut_offsets('我十分感谢大家')


def test_adverb_shifen_survives_grouping_and_final_check():
    import subtitle_core as legacy
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    source = '十分感谢大家 这把打了十分 等了十分钟 五点三十分'
    words = [WordUnit(i * .12, (i + 1) * .12, c, .9) for i, c in enumerate(source) if c != ' ']
    segment = SpeechSegment(1, 0, len(source) * .12, source, .9, words, speaker='S01')
    context = RuntimeContext(asr_settings_snapshot={'switches': {
        'prefer_arabic_numbers': True, 'enable_ai_polish': False, 'use_ai_grouping': False}})
    with activate_runtime_context(context, legacy=legacy):
        segments = legacy.apply_editorial_segment_rules([segment])
        cues = legacy.group_subtitles(segments, use_ai=False)
        cues = finalize_cues(cues, segments, [], [], segment.end, 30, legacy)
    assert ''.join(c.text.replace(' ', '') for c in cues) == '十分感谢大家这把打了10分等了10分钟五点三十分'


def test_only_source_traced_new_arabic_spelling_is_restored():
    source = '一个 一个 两个办法 十几个 一心一意 版本1.0.5'
    proposed = '1个 1个 2个办法 10几个 1心1意 版本1.0.5'
    result, receipts = format_numbers(proposed, source_text=source)
    assert result == source
    assert receipts
    assert format_numbers('原本1个 1.0.5', source_text='原本1个 1.0.5')[0] == '原本1个 1.0.5'


def test_restoration_and_formatting_receipts_reference_the_same_final_text():
    original = '一百二十 一个 一百来个'
    proposed = '一百二十 1个 100来个'
    result, receipts = format_numbers(proposed, source_text=original)
    assert result == '120 一个 一百来个'
    assert all(result[r['output_start']:r['output_end']] == r['value'] for r in receipts)
    assert all(proposed[r['start']:r['end']] == r.get('input',r['source']) for r in receipts)


def test_confirmed_term_numeric_spelling_has_priority_over_threshold():
    actual, _ = format_numbers('用了二十里香 十个', protected_terms=('二十里香',))
    assert actual == '用了二十里香 10个'
    actual, _ = format_numbers('用了20里香', source_text='用了二十里香', protected_terms=('二十里香',))
    assert actual == '用了二十里香'


def test_disabled_switch_keeps_existing_and_source_styles_unchanged():
    text = '1个 二十 零点五秒'
    assert format_numbers(text, enabled=False, source_text='一个 二十 零点五秒') == (text, [])


def test_format_segment_updates_final_fields_and_keeps_whole_word_spans(monkeypatch):
    from twobyteasr.subtitle_rules import number_fidelity
    monkeypatch.setattr(number_fidelity, 'preference', lambda: True)
    s = SpeechSegment(7, 0, 2, '一个 一百二十 二十', 1,
        [WordUnit(0, .3, '一个', 1), WordUnit(.5, 1, '一百二十', 1), WordUnit(1.3, 2, '二十', 1)],
        speaker='S03', final_text='旧的最终字段')
    bounds = (s.start, s.end, s.speaker)
    format_segment(s)
    assert s.text == s.final_text == '一个 120 20'
    assert ''.join(w.text for w in s.words) == s.text.replace(' ', '')
    assert (s.start, s.end, s.speaker) == bounds
    assert [(w.start, w.end) for w in s.words] == [(0, .3), (.5, 1), (1.3, 2)]
    assert s.caption_arbitration['numeric_formatting'][-1]['requires_acoustic_alignment']
    before = copy.deepcopy(s)
    format_segment(s)
    assert s == before


def test_production_editorial_grouping_final_and_outputs_follow_new_policy():
    import subtitle_core as legacy
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.subtitle_rules.output import render_txt, render_srt
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    source = '一个 两个办法 二十 二十 零点五秒 百分之二 二十里香'
    words = [WordUnit(i * .12, (i + 1) * .12, c, .9) for i, c in enumerate(source) if c != ' ']
    segment = SpeechSegment(1, 0, len(source) * .12, source, .9, words, speaker='S03')
    snapshot = snapshot_from_pairs([('二十里香', '二十里香'), ('BerLIN', 'BerLIN'), ('S0PP', 'S0PP')])
    context = RuntimeContext(enable_domain_terms=True, glossary_snapshot=snapshot,
        asr_settings_snapshot={'switches': {'prefer_arabic_numbers': True, 'enable_ai_polish': False, 'use_ai_grouping': False}})
    with activate_runtime_context(context, legacy=legacy):
        segments = legacy.apply_editorial_segment_rules([segment])
        cues = legacy.group_subtitles(segments, use_ai=False)
        cues = finalize_cues(cues, segments, [], [], segment.end, 30, legacy)
    compact = ''.join(c.text.replace(' ', '') for c in cues)
    assert compact == '一个两个办法20200.5秒2%二十里香'
    assert {c.speaker for c in cues} == {'S03'}
    assert '1个' not in render_txt(cues)
    assert '一个' in render_srt(cues)


def test_policy_and_switch_participate_in_runtime_cache_signature():
    import subtitle_core as legacy
    from twobyteasr.subtitle_rules.number_fidelity import RULE_VERSION
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    signatures = []
    for enabled in (False, True):
        with activate_runtime_context(RuntimeContext(asr_settings_snapshot={'switches': {'prefer_arabic_numbers': enabled}}), legacy=legacy):
            signatures.append(legacy.runtime_content_profile_signature())
    assert signatures[0]['numeric_policy']['version'] == RULE_VERSION
    assert signatures[0] != signatures[1]


def test_ai_small_integer_proposal_is_restored_before_final_pipeline(monkeypatch):
    import subtitle_core as legacy
    from twobyteasr.subtitle_rules.number_fidelity import restore_source_number_style
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    source = '一个 一个 1个编号 二十 二十'
    ai_returned = '1个 1个 1个编号 二十 二十'
    restored, receipts = restore_source_number_style(source, ai_returned)
    assert restored == source and len(receipts) == 2
    segment = SpeechSegment(3, 0, 3, ai_returned, .9,
        [WordUnit(0, 3, source, .9)], speaker='S01')
    context = RuntimeContext(asr_settings_snapshot={'switches': {'prefer_arabic_numbers': True}})
    with activate_runtime_context(context, legacy=legacy):
        format_segment(segment, source_text=source)
        segments = legacy.apply_editorial_segment_rules([segment])
        cues = legacy.group_subtitles(segments, use_ai=False)
        cues = finalize_cues(cues, segments, [], [], 3, 30, legacy)
    assert ''.join(c.text.replace(' ', '') for c in cues) == '一个一个1个编号2020'
    assert segment.final_text == segment.text


@pytest.mark.parametrize('enabled,expected', [(True, '2:3 0.5:2'), (False, '二:三 零点五:二')])
def test_explicit_ratios_survive_actual_editorial_grouping_and_finalization(enabled, expected):
    import subtitle_core as legacy
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    source = '二:三 零点五:二'
    segment = SpeechSegment(1, 0, 2, source, .9, [], speaker='S01')
    context = RuntimeContext(asr_settings_snapshot={'switches': {'prefer_arabic_numbers': enabled}})
    with activate_runtime_context(context, legacy=legacy):
        segments = legacy.apply_editorial_segment_rules([segment])
        cues = legacy.group_subtitles(segments, use_ai=False)
        cues = finalize_cues(cues, segments, [], [], 2, 30, legacy)
    assert ''.join(c.text for c in cues).replace(' ', '') == expected.replace(' ', '')


def test_saved_numeric_mapping_never_becomes_acoustic_word_evidence(tmp_path, monkeypatch):
    from twobyteasr.subtitle_rules import number_fidelity
    from twobyteasr.recognition.transcript_data import SubtitleCue
    from twobyteasr.projects.studio_project import create_studio_outputs, load_project
    from twobyteasr.recognition.cue_word_alignment import cue_words
    monkeypatch.setattr(number_fidelity, 'preference', lambda: True)
    segment = SpeechSegment(1, 0, 2, '二十 二十', .9,
        [WordUnit(0, .5, '二十', .9), WordUnit(1.5, 2, '二十', .9)], speaker='S01')
    format_segment(segment)
    assert [(w.text,w.start,w.end) for w in segment.words] == [('20',0,.5),('20',1.5,2)]
    outputs = create_studio_outputs(tmp_path/'missing.mp4',
        [SubtitleCue(1,0,2,segment.text,speaker='S01')], txt_path='', segments=[segment],
        target_project_path=tmp_path/'copy'/'n.2byteproj')
    project = load_project(outputs['project'])
    assert project.cues[0].text == '20 20'
    assert cue_words(project,project.cues[0])[0] == ()
