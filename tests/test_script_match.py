"""匹配文稿 core: a user's line-broken script timed by word timestamps only."""
from __future__ import annotations

import time

import pytest

from twobyteasr.recognition.script_match import (ScriptMatchError, Token, match_script, parse_script)


def _chars(text, start, step=200, speaker='S00', ref='segment:0'):
    """One measured token per character, back to back from ``start``."""
    tokens, at = [], start
    for char in text:
        tokens.append(Token(at, at + step - 20, char, ref, speaker))
        at += step
    return tokens


def test_parse_script_keeps_each_line_as_typed():
    text = '  第一句，你好。 \r\n\r\n第二句  有空格\n\n\nHello, World!\r'
    assert parse_script(text) == ['第一句，你好。', '第二句  有空格', 'Hello, World!']
    assert parse_script('\n \n') == []


def test_identical_text_takes_measured_times_and_words():
    tokens = _chars('今天天气不错', 1000) + _chars('我们出发吧', 3000)
    result = match_script(['今天天气不错。', '我们出发吧！'], tokens)
    first, second = result.lines
    assert (first.start_ms, first.end_ms) == (1000, 1000 + 5 * 200 + 180)
    assert (second.start_ms, second.end_ms) == (3000, 3000 + 4 * 200 + 180)
    assert first.text == '今天天气不错。' and second.text == '我们出发吧！'
    assert first.coverage == 1.0 and not first.needs_review
    assert first.word_reason == 'exact_token_text'
    assert [w.text for w in first.words] == list('今天天气不错')
    assert result.coverage == 1.0


def test_heard_homophone_still_anchors_the_line():
    # The recogniser heard 至东; the script says 至冬.
    tokens = _chars('我们去至东国', 0) + _chars('派蒙在哪里', 2000)
    result = match_script(['我们去至冬国', '派蒙在哪里'], tokens)
    line = result.lines[0]
    assert line.matched_chars == 6 and line.text == '我们去至冬国'
    assert (line.start_ms, line.end_ms) == (0, 5 * 200 + 180)
    assert line.words, line.word_reason


def test_line_never_heard_is_placed_between_neighbours_for_review():
    tokens = _chars('第一句话', 0) + _chars('第三句话', 5000)
    result = match_script(['第一句话', '完全没说出口的台词', '第三句话'], tokens)
    first, missing, third = result.lines
    assert missing.placed_by == 'estimated_between_neighbours' and missing.needs_review
    assert first.end_ms <= missing.start_ms < missing.end_ms <= third.start_ms
    assert not missing.words
    assert not first.needs_review and not third.needs_review


def test_extra_speech_not_in_script_is_skipped():
    tokens = _chars('大家好', 0) + _chars('嗯嗯那个就是说', 1000) + _chars('开始游戏', 3000)
    result = match_script(['大家好', '开始游戏'], tokens)
    assert result.lines[0].end_ms <= 1000
    assert result.lines[1].start_ms == 3000
    assert result.unmatched_token_chars == 7


def test_repeated_lines_take_successive_occurrences():
    tokens = _chars('好的', 0) + _chars('继续', 1000) + _chars('好的', 2000)
    result = match_script(['好的', '继续', '好的'], tokens)
    starts = [line.start_ms for line in result.lines]
    assert starts == [0, 1000, 2000]
    assert all(not line.needs_review for line in result.lines)


def test_unheard_first_character_extends_start_by_reading_pace():
    tokens = _chars('们出发吧', 1000)
    line = match_script(['我们出发吧'], tokens).lines[0]
    assert line.edges_estimated
    assert 700 <= line.start_ms < 1000


def test_lines_never_overlap_and_keep_order():
    tokens = _chars('一二三四五六七八九十', 0, step=100)
    result = match_script(['一二三', '四五六七', '八九十'], tokens)
    for left, right in zip(result.lines, result.lines[1:]):
        assert left.end_ms <= right.start_ms


def test_speaker_comes_from_heard_tokens():
    tokens = _chars('你好呀', 0, speaker='S01') + _chars('收到', 1000, speaker='S02')
    result = match_script(['你好呀', '收到'], tokens)
    assert [line.speaker for line in result.lines] == ['S01', 'S02']


def test_estimated_tokens_place_lines_but_never_become_words():
    tokens = [Token(0, 300, '这', 'cue-estimate:c1', 'S00', True), Token(300, 600, '是', 'cue-estimate:c1', 'S00', True)]
    line = match_script(['这是'], tokens).lines[0]
    assert (line.start_ms, line.end_ms) == (0, 600)
    assert line.placed_by == 'estimated_tokens' and not line.words and line.needs_review


def test_english_words_match_case_insensitively():
    tokens = [Token(0, 400, 'hello', 'r', 'S00'), Token(450, 900, 'world', 'r', 'S00'),
              Token(1500, 1900, 'next', 'r', 'S00'), Token(1950, 2300, 'line', 'r', 'S00')]
    result = match_script(['Hello, World!', 'Next line.'], tokens)
    assert [(line.start_ms, line.end_ms) for line in result.lines] == [(0, 900), (1500, 2300)]
    line = result.lines[0]
    assert [line.text[w.char_start:w.char_end] for w in line.words] == ['Hello', 'World']


def test_nothing_to_match_is_an_error():
    with pytest.raises(ScriptMatchError):
        match_script([], _chars('你好', 0))
    with pytest.raises(ScriptMatchError):
        match_script(['你好'], [])


def test_hour_long_script_matches_quickly():
    import random
    rng = random.Random(7)
    alphabet = '的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处理府研质'
    script = [''.join(rng.choice(alphabet) for _ in range(rng.randint(6, 14))) for _ in range(1200)]
    tokens, at = [], 0
    for line in script:
        heard = line if rng.random() > 0.05 else line[1:]     # some first characters unheard
        tokens.extend(_chars(heard, at, step=180))
        at += 180 * len(line) + 400
    started = time.perf_counter()
    result = match_script(script, tokens)
    elapsed = time.perf_counter() - started
    assert result.coverage > 0.98
    assert elapsed < 20, elapsed


def test_speech_regions_trim_edges_that_absorbed_a_pause():
    # FireRed-style contiguous characters: 间 runs into the pause, 今 starts in it.
    tokens = [Token(0, 300, '你', 'r'), Token(300, 900, '好', 'r'),       # speech ends ~500
              Token(900, 1600, '再', 'r'), Token(1600, 1800, '见', 'r')]   # speech starts ~1400
    plain = match_script(['你好', '再见'], tokens)
    assert (plain.lines[0].end_ms, plain.lines[1].start_ms) == (900, 900)
    snapped = match_script(['你好', '再见'], tokens, speech_regions_ms=[(0, 520), (1380, 1800)])
    assert snapped.lines[0].end_ms == 520
    assert snapped.lines[1].start_ms == 1380
    # Never past the line's own first/last character.
    kept = match_script(['你好', '再见'], tokens, speech_regions_ms=[(0, 200), (1700, 1800)])
    assert kept.lines[0].end_ms == 900 and kept.lines[1].start_ms == 900
