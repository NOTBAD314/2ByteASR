"""Japanese lines too short to read join the same speaker's neighbour (日常 19, 2026-10-18).

Lines, speakers and times are the real ones of job 11c64375809845418ad5db35e22ad5da
at the point final timing merges them (on the frame grid, before reading
tails); tags are nagisa 0.2.11 output for the segment texts of that run.
"""
import copy

import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr.recognition.transcript_data import SubtitleCue
from twobyteasr.subtitle_rules import japanese_morphology as jm
from twobyteasr.subtitle_rules.cue_cleanup import merge_short_japanese_cues
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.text_rules import content_exact


def tags(spec):
    return [item.rsplit("/", 1) for item in spec.split()]


TAGGED = {
    "今度はちょっとバーを落とすからゆっくりでいいから次は教えた通りに飛びなよ":
        tags("今度/名詞 は/助詞 ちょっと/副詞 バー/名詞 を/助詞 落とす/動詞 から/助詞 ゆっくり/副詞 で/助詞 "
             "いい/形容詞 から/助詞 次/名詞 は/助詞 教え/動詞 た/助動詞 通り/名詞 に/助詞 飛びなよ/名詞"),
    "そうだねそれに随分遠くにいるからよく見えないし":
        tags("そう/副詞 だ/助動詞 ね/助詞 それ/代名詞 に/助詞 随分/副詞 遠く/名詞 に/助詞 いる/動詞 から/助詞 "
             "よく/副詞 見え/動詞 ない/助動詞 し/助詞"),
    "本当だよ本当に坂本が入れろって言ったから":
        tags("本当/名詞 だ/助動詞 よ/助詞 本当/名詞 に/助詞 坂本/名詞 が/助詞 入れろ/動詞 って/助詞 言っ/動詞 "
             "た/助動詞 から/助詞"),
    "えーとじゃあままあとりあえず今日は食べちゃいましょう":
        tags("えーと/感動詞 じゃ/助詞 あまま/名詞 あとりあえず/名詞 今日/名詞 は/助詞 食べ/動詞 ちゃい/助動詞 "
             "ましょう/助動詞"),
    "やりますよ俺": tags("やり/動詞 ます/助動詞 よ/助詞 俺/代名詞"),
    "でもどうやってやればいいの？":
        tags("で/助詞 も/助詞 どう/副詞 やっ/動詞 て/助詞 やれ/動詞 ば/助詞 いい/形容詞 の/助詞 ?/補助記号"),
}


@pytest.fixture
def japanese():
    payload = {"tagger_version": "0.2.11", "results": [
        {"text": text, "words": words} for text, words in TAGGED.items()]}
    document = jm.build_document(list(TAGGED), payload)
    with language_scope("ja"), jm.phrase_scope(document):
        yield document


def lines(*rows):
    return [SubtitleCue(index, start, end, text, speaker=speaker)
            for index, (start, end, speaker, text) in enumerate(rows, 1)]


def texts(cues):
    return [cue.text for cue in cues]


def spoken(cues):
    by_speaker = {}
    for cue in sorted(cues, key=lambda cue: (cue.start, cue.end)):
        by_speaker.setdefault(cue.speaker, []).append(content_exact(cue.text))
    return {speaker: "".join(parts) for speaker, parts in by_speaker.items()}


def test_flashing_pieces_join_inside_one_breath_but_not_across_a_pause(japanese):
    cues = lines(
        (370.245, 372.622, "API_S08", "今度はちょっとバーを落とすから"),
        (372.622, 373.039, "API_S08", "ゆっくりで"),
        (373.540, 373.915, "API_S08", "いいから"),
        (374.249, 375.458, "API_S08", "次は教えた通りに"),
        (376.001, 376.376, "API_S08", "飛びなよ"),
        (376.418, 378.336, "API_S07", "わかったとりあえず"),
    )
    before = spoken(cues)
    merged = merge_short_japanese_cues(copy.deepcopy(cues))
    # 「飛びなよ」 follows a 0.54 s pause and the next line is someone else's;
    # 「ゆっくりで」 would make a 17-character line.
    assert texts(merged) == ["今度はちょっとバーを落とすから", "ゆっくりで", "いいから次は教えた通りに",
                             "飛びなよ", "わかったとりあえず"]
    joined = merged[2]
    assert (joined.start, joined.end) == (373.540, 375.458)
    assert [cue.cue_id for cue in merged] == [1, 2, 3, 4, 5]
    assert spoken(merged) == before


def test_a_piece_joins_the_phrase_it_belongs_to_and_a_sentence_end_gets_a_space(japanese):
    cues = lines(
        (738.112, 739.656, "API_S11", "本当だよ"),
        (739.656, 739.989, "API_S11", "本当に"),
        (739.989, 740.490, "API_S11", "坂本が"),
        (740.490, 741.115, "API_S11", "入れろって"),
        (741.115, 742.325, "API_S11", "言ったから"),
    )
    before = spoken(cues)
    merged = merge_short_japanese_cues(copy.deepcopy(cues))
    # 本当に|坂本が first (no break between them), then 本当だよ after its final particle.
    assert texts(merged) == ["本当だよ 本当に坂本が", "入れろって", "言ったから"]
    assert (merged[0].start, merged[0].end) == (738.112, 740.490)
    assert spoken(merged) == before


def test_reply_and_inverted_subject_join_with_a_space(japanese):
    cues = lines(
        (627.126, 627.919, "API_S13", "そうだね"),
        (628.336, 630.004, "API_S13", "それに随分遠くにいるから"),
        (1110.067, 1110.693, "API_S18", "やりますよ"),
        (1111.193, 1111.527, "API_S18", "俺"),          # 12 frames later: 0.5005 s at 23.976 fps
        (1112.028, 1113.696, "API_S18", "でもどうやってやればいいの？"),
        (1113.988, 1115.406, "API_S17", "大丈夫です前に"),
    )
    merged = merge_short_japanese_cues(copy.deepcopy(cues))
    assert texts(merged) == ["そうだね それに随分遠くにいるから", "やりますよ 俺",
                             "でもどうやってやればいいの？", "大丈夫です前に"]


def test_never_across_speakers(japanese):
    cues = lines(
        (760.343, 760.802, "API_S14", "落とせとは"),
        (760.802, 761.678, "API_S14", "言ってねえよ"),
        (761.803, 762.220, "API_S11", "言った"),
        (762.553, 763.388, "API_S14", "言ってねえよ"),
        (763.429, 763.763, "API_S11", "言った"),
        (764.055, 764.931, "API_S14", "言ってねえよ"),
        (765.515, 765.848, "API_S11", "言った"),
        (765.807, 766.808, "API_S14", "言ってねえよ"),
        (766.808, 767.183, "API_S11", "言った"),
    )
    merged = merge_short_japanese_cues(copy.deepcopy(cues))
    assert texts(merged) == ["落とせとは言ってねえよ"] + texts(cues)[2:]
    assert [cue.speaker for cue in merged] == ["API_S14"] + [cue.speaker for cue in cues[2:]]


def test_not_while_another_line_is_on_screen_across_the_seam(japanese):
    cues = lines(
        (626.900, 628.500, "API_S12", "よかったじゃん"),
        (627.126, 627.919, "API_S13", "そうだね"),
        (628.336, 630.004, "API_S13", "それに随分遠くにいるから"),
    )
    assert texts(merge_short_japanese_cues(copy.deepcopy(cues))) == texts(cues)


def test_joined_line_keeps_the_character_and_second_limits(japanese):
    over_16 = lines(
        (838.921, 839.338, "API_S13", "えー"),
        (839.338, 842.550, "API_S13", "とじゃあままあとりあえず今日は"),
        (842.550, 844.427, "API_S13", "食べちゃいましょう"),
    )
    assert texts(merge_short_japanese_cues(copy.deepcopy(over_16))) == texts(over_16)
    over_5s = lines(
        (627.126, 627.919, "API_S13", "そうだね"),
        (628.336, 632.200, "API_S13", "それに随分遠くにいるから"),
    )
    assert texts(merge_short_japanese_cues(copy.deepcopy(over_5s))) == texts(over_5s)


def test_timing_locked_lines_stay(japanese):
    cues = lines(
        (373.540, 373.915, "API_S08", "いいから"),
        (374.249, 375.458, "API_S08", "次は教えた通りに"),
    )
    cues[1].timing_locked = True
    assert texts(merge_short_japanese_cues(copy.deepcopy(cues))) == texts(cues)


def test_chinese_tasks_are_untouched():
    cues = lines(
        (0.0, 0.4, "S01", "然后"),
        (0.5, 1.6, "S01", "我们去下一个点"),
    )
    with language_scope("zh"):
        assert merge_short_japanese_cues(cues) is cues
    assert texts(cues) == ["然后", "我们去下一个点"]
