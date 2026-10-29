"""2026-10-15: click-to-fix marks on review card 1, 他/她/它 helpers and the
AI correction rule that lets a context-only pronoun fix through."""
from __future__ import annotations

from types import SimpleNamespace

import subtitle_core  # noqa: F401  (production import order: the facade first)
from twobyteasr.subtitle_rules.pronouns import (flip_pronouns, is_pronoun_swap, pronoun_options,
                                                pronoun_positions, pronoun_swap_in_context)
from twobyteasr.subtitle_rules.review_suggestions import (GLOSSARY, MODEL, PRONOUN, model_suggestions,
                                                          review_suggestions)


# pronouns -------------------------------------------------------------------
def test_pronoun_positions_skip_words_that_only_contain_ta():
    text = '其他人说他会弹吉他，它也来了'
    assert [text[i] for i in pronoun_positions(text)] == ['他', '它']
    assert pronoun_positions(text) == [4, 10]


def test_flip_turns_the_leading_gender_of_a_caption():
    assert flip_pronouns('他说他们要走了') == '她说她们要走了'
    assert flip_pronouns('她和它') == '他和它'
    assert flip_pronouns('它跑了') == '他跑了'
    assert flip_pronouns('其他都可以') == '其他都可以'
    assert pronoun_options('他') == ('她', '它')
    assert pronoun_options('它') == ('他', '她')


def test_pronoun_swap_detection():
    assert is_pronoun_swap('所以他', '所以她')
    assert is_pronoun_swap('他们', '她们')
    assert not is_pronoun_swap('他', '她们')
    assert not is_pronoun_swap('他说', '她讲')
    assert pronoun_swap_in_context('我看他', 2, 3, '她')
    assert not pronoun_swap_in_context('其他人', 1, 2, '她')


# marks ------------------------------------------------------------------------
def test_other_recognizers_become_local_marks_on_the_current_caption():
    current = '好我们这边来到他的视角'
    rows = review_suggestions(current, [('好，我们这边来到她的视角', ('FireRed',)),
                                        ('好我们这边来到她的世界', ('Qwen3-ASR',))])
    assert [(row.kind, row.original, [option.text for option in row.options]) for row in rows] == [
        (MODEL, '他', ['她']), (MODEL, '视角', ['世界'])]
    # The punctuation-only difference (好，) is not a mark; agreeing sources merge.
    assert rows[0].options[0].sources == ('FireRed', 'Qwen3-ASR')
    assert rows[0].apply(current) == '好我们这边来到她的视角'
    assert rows[1].apply(current) == '好我们这边来到他的世界'


def test_overlapping_differences_become_one_mark_with_ranked_options():
    current = '那维来特很强'
    rows = model_suggestions(current, [('那维莱特很强', ('FireRed',)), ('那维莱特很强', ('Qwen3-ASR',)),
                                       ('那为来特很强', ('MOSS',))])
    assert len(rows) == 1
    row = rows[0]
    assert row.original == '维来'
    assert [option.text for option in row.options] == ['维莱', '为来']
    assert row.options[0].sources == ('FireRed', 'Qwen3-ASR')


def test_a_rewrite_is_left_to_the_whole_candidate_card():
    assert model_suggestions('今天天气不错', [('我们出发去打副本吧', ('Qwen3-ASR',))]) == []


def test_glossary_aliases_and_pronouns_fill_the_remaining_spans():
    hit = SimpleNamespace(start=0, end=3, source='福宁娜', canonical='芙宁娜')
    resolver = SimpleNamespace(resolve=lambda text, scene=None: SimpleNamespace(hits=(hit,)))
    rows = review_suggestions('福宁娜说他累了', [], resolver=resolver)
    assert [(row.kind, row.original, row.options[0].text) for row in rows] == [
        (GLOSSARY, '福宁娜', '芙宁娜'), (PRONOUN, '他', '她')]
    # A recognizer difference on the pronoun wins over the plain toggle.
    rows = review_suggestions('福宁娜说他累了', [('福宁娜说她累了', ('FireRed',))])
    assert [(row.kind, row.original, row.options[0].text) for row in rows] == [(MODEL, '他', '她')]
    assert review_suggestions('他累了', [], pronouns=False) == []


def test_stale_mark_never_rewrites_changed_text():
    row = review_suggestions('他累了')[0]
    assert row.apply('她累了') == '她累了'


# AI correction ------------------------------------------------------------------
def test_context_pronoun_fix_passes_the_safety_gate():
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    text, applied = apply_correction_edits('然后他就去打副本了', [], [
        {'from': '他', 'to': '她', 'start': 2, 'end': 3, 'type': 'pronoun_gender', 'evidence': '上句说姐姐'}],
        independent_sources=[])
    assert text == '然后她就去打副本了'
    assert applied[0]['type'] == 'pronoun_gender' and applied[0]['rule_id'] == 'pronoun_gender_context'


def test_pronoun_rule_never_touches_words_or_other_single_characters():
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    decisions = []
    text, applied = apply_correction_edits('其他人先走', [], [{'from': '他', 'to': '她'}],
                                           independent_sources=[], decisions=decisions)
    assert text == '其他人先走' and applied == []
    decisions = []
    text, applied = apply_correction_edits('我在这里', [], [{'from': '在', 'to': '再'}],
                                           independent_sources=[], decisions=decisions)
    assert applied == [] and decisions[0]['rule_id'] == 'ambiguous_single_character'


def test_prompt_and_schema_carry_the_pronoun_rule():
    from twobyteasr.subtitle_rules import polishing
    from twobyteasr.providers.asr_provider_snapshot import POLISH_PROMPT_VERSION
    enum = polishing.POLISH_SCHEMA['properties']['cues']['items']['properties']['edits']['items']['properties']['type']['enum']
    assert 'pronoun_gender' in enum
    assert '他/她/它' in polishing.PRONOUN_GENDER_RULE and 'pronoun_gender' in polishing.PRONOUN_GENDER_RULE
    assert POLISH_PROMPT_VERSION == 'correction-edits-v14-pronoun-gender'


# script matching in other languages ------------------------------------------
def _chars(text, start, step=200):
    from twobyteasr.recognition.script_match import Token
    tokens, at = [], start
    for char in text:
        tokens.append(Token(at, at + step - 20, char, 'segment:0', 'S00'))
        at += step
    return tokens


def test_japanese_script_matches_across_kana_and_width():
    from twobyteasr.recognition.script_match import match_script
    tokens = _chars('きょうはげーむをやります', 0) + _chars('アリガトウ', 4000)
    result = match_script(['今日はゲームをやります', 'ｱﾘｶﾞﾄｳ'], tokens, language='ja')
    first, second = result.lines
    assert second.matched_chars == 5 and second.start_ms == 4000
    assert first.matched_chars >= 8 and first.start_ms <= 400


def test_japanese_kanji_do_not_match_by_chinese_reading():
    from twobyteasr.recognition.script_match import _key
    # 市 and 是 share the Chinese reading shi.
    assert _key('市') == _key('是')
    assert _key('市', 'ja') != _key('是', 'ja')


def test_english_script_matches_case_and_full_width_letters():
    from twobyteasr.recognition.script_match import Token, match_script
    words = [('Hello', 0, 400), ('everyone', 450, 1000), ('welcome', 2000, 2500), ('back', 2550, 2900)]
    tokens = [Token(start, end, text, 'segment:0', 'S00') for text, start, end in words]
    result = match_script(['ＨＥＬＬＯ everyone!', 'Welcome back.'], tokens, language='en')
    first, second = result.lines
    assert (first.start_ms, first.end_ms) == (0, 1000) and first.coverage == 1.0
    assert (second.start_ms, second.end_ms) == (2000, 2900) and second.coverage == 1.0


def test_home_route_picks_models_by_language():
    from twobyteasr.app.home_script_match import script_language, uses_qwen
    assert script_language(['今日はゲームをやります、ありがとう']) == 'ja'
    assert script_language(['Hello everyone, welcome back to the stream today']) == 'en'
    assert script_language(['大家好欢迎回来']) == 'zh'
    assert script_language(['大家好'], 'en') == 'en'
    assert not uses_qwen('zh') and uses_qwen('ja') and uses_qwen('en')
