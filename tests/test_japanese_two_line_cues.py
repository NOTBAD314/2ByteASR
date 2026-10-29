"""Japanese subtitles hold two lines; pieces of one sentence join back (日常 20, 2026-10-21).

User report: 「前はねみんなに隠してこっそり」「書いてたんだよ」 — grouping cut one sentence at
its 16-character line limit and left the last words on a line of their own.
Lines, speakers and times are the real final lines of that run (DeepSeek
grouping); tags are nagisa 0.2.11 output for the segment texts of that run.
"""
import copy

import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules import japanese_morphology as jm
from twobyteasr.subtitle_rules.cue_cleanup import merge_japanese_sentence_cues
from twobyteasr.subtitle_rules.language_rules import (
    JAPANESE_CUE_MAX_CHARS, finished_cue_limits, language_scope)
from twobyteasr.subtitle_rules.text_rules import content_exact


def tags(spec):
    return [item.rsplit("/", 1) for item in spec.split()]


TAGGED = {
    "前はねみんなに隠してこっそり書いてたんだよ":
        tags("前/名詞 は/助詞 ね/web誤脱 みんな/名詞 に/助詞 隠し/動詞 て/助詞 こっそり/副詞 書い/動詞 て/助動詞 "
             "た/助動詞 ん/助詞 だ/助動詞 よ/助詞"),
    "ちょっと見せてもらってもいいですか":
        tags("ちょっと/副詞 見せ/動詞 て/助詞 もらっ/動詞 て/助詞 も/助詞 いい/形容詞 です/助動詞 か/助詞"),
    "神のいたずらか悪魔の罠か":
        tags("神/名詞 の/助詞 いたずら/名詞 か/助詞 悪魔/名詞 の/助詞 罠/名詞 か/助詞"),
    "ここんとこ寒くなってきたなあ":
        tags("ここ/代名詞 ん/助詞 とこ/名詞 寒く/形容詞 なっ/動詞 て/助詞 き/動詞 た/助動詞 なあ/助詞"),
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


def test_a_sentence_cut_at_the_line_limit_joins_back_within_two_lines(japanese):
    cues = lines(
        (151.818, 154.279, "API_S05", "前はねみんなに隠してこっそり"),
        (154.279, 155.405, "API_S05", "書いてたんだよ"),
        (181.681, 182.891, "API_S06", "ちょっと見せてもらっても"),
        (182.891, 183.558, "API_S06", "いいですか"),
    )
    merged = merge_japanese_sentence_cues(copy.deepcopy(cues))
    assert texts(merged) == ["前はねみんなに隠してこっそり書いてたんだよ", "ちょっと見せてもらってもいいですか"]
    assert (merged[0].start, merged[0].end) == (151.818, 155.405)
    assert [cue.cue_id for cue in merged] == [1, 2]


def test_two_sentences_a_pause_another_speaker_or_three_lines_stay_apart(japanese):
    # A sentence end (final particle か) between two readable lines stays a cut.
    two_sentences = lines((1261.218, 1263.30, "API_S08", "神のいたずらか"), (1263.30, 1265.639, "API_S08", "悪魔の罠か"))
    assert texts(merge_japanese_sentence_cues(copy.deepcopy(two_sentences))) == ["神のいたずらか", "悪魔の罠か"]
    # A real pause (0.6 s) is longer than the display's own short-gap bridge.
    paused = lines((151.818, 154.279, "API_S05", "前はねみんなに隠してこっそり"),
                   (154.879, 156.005, "API_S05", "書いてたんだよ"))
    assert len(merge_japanese_sentence_cues(copy.deepcopy(paused))) == 2
    # Someone else's line is on screen across the seam.
    crossed = lines((151.818, 154.279, "API_S05", "前はねみんなに隠してこっそり"),
                    (153.900, 154.600, "API_S01", "えっ"),
                    (154.279, 155.405, "API_S05", "書いてたんだよ"))
    assert "前はねみんなに隠してこっそり" in texts(merge_japanese_sentence_cues(copy.deepcopy(crossed)))
    # A third line: 14 + 14 content characters exceed two lines.
    long = lines((10.0, 12.5, "S01", "ここんとこ寒くなってきたなあ"), (12.5, 15.0, "S01", "ここんとこ寒くなってきたなあ"))
    assert len(content_exact(long[0].text + long[1].text)) > JAPANESE_CUE_MAX_CHARS
    assert len(merge_japanese_sentence_cues(copy.deepcopy(long))) == 2


def test_chinese_lines_are_never_joined_this_way():
    cues = lines((1.0, 2.0, "S01", "我们先去"), (2.0, 3.0, "S01", "左边的房间"))
    with language_scope("zh"):
        assert texts(merge_japanese_sentence_cues(copy.deepcopy(cues))) == ["我们先去", "左边的房间"]
        assert finished_cue_limits(16, 5.0) == (16, 5.0)


def test_final_checks_keep_a_two_line_japanese_subtitle_and_chinese_limits_stay(japanese):
    from twobyteasr.subtitle_rules.output import validate_final_cues
    from twobyteasr.subtitle_rules.timing import repair_overlong_cues_from_source
    text = "前はねみんなに隠してこっそり書いてたんだよ"            # 21 characters, 6 seconds
    segment = SpeechSegment(13, 150.0, 156.0, text, 0.9, [], speaker="API_S05")
    cue = SubtitleCue(1, 150.0, 156.0, text, speaker="API_S05")
    assert finished_cue_limits(16, 5.0) == (26, 7.0)
    kept = repair_overlong_cues_from_source([copy.deepcopy(cue)], [segment])
    assert texts(kept) == [text]
    final = validate_final_cues([copy.deepcopy(cue)], [segment], 200.0)
    assert (final[0].start, final[0].end, final[0].text) == (150.0, 156.0, text)
    with language_scope("zh"):
        with pytest.raises(RuntimeError):
            validate_final_cues([copy.deepcopy(cue)], [segment], 200.0)
