"""Japanese cue line breaks follow bunsetsu boundaries (nagisa tags recorded from 0.2.11)."""
import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr import japanese_morphology as jm
from twobyteasr.runtime import get_runtime_context


def tags(spec):
    return [item.rsplit("/", 1) for item in spec.split()]


TAGGED = {
    "高すぎたかもっとみんなにわかるように伝えないとね":
        tags("高/形容詞 すぎ/動詞 た/助動詞 か/助詞 もっと/副詞 みんな/名詞 に/助詞 わかる/動詞 よう/形状詞 "
             "に/助動詞 伝え/動詞 ない/助動詞 と/助詞 ね/助詞"),
    "言ってたのにねいやーこんな天気のいい日はさ":
        tags("言っ/動詞 て/助動詞 た/助動詞 の/助詞 に/助詞 ねい/名詞 やー/助詞 こんな/連体詞 天気/名詞 の/助詞 "
             "いい/形容詞 日/名詞 は/助詞 さ/助詞"),
    "ねえ　ムカデに襲われた人がなんて言ったか知ってる？":
        tags("ねえ/感動詞 　/空白 ムカデ/名詞 に/助詞 襲わ/動詞 れ/助動詞 た/助動詞 人/名詞 が/助詞 なん/代名詞 "
             "て/助詞 言っ/動詞 た/助動詞 か/助詞 知っ/動詞 てる/助動詞 ?/補助記号"),
    "もしかして今のままのレベルで収まるなっていう":
        tags("もし/副詞 か/助詞 し/動詞 て/助詞 今/名詞 の/助詞 まま/名詞 の/助詞 レベル/名詞 で/助詞 収まる/動詞 "
             "な/助詞 って/助詞 いう/動詞"),
}


def phrases(text):
    spans = jm.word_spans(text, TAGGED[text])
    allowed, _strong = jm.bunsetsu_breaks(text, spans)
    cuts = [0] + sorted(allowed) + [len(text)]
    return [text[a:b].strip() for a, b in zip(cuts, cuts[1:])]


def test_bunsetsu_keep_auxiliaries_compounds_and_modified_nouns():
    assert phrases("高すぎたかもっとみんなにわかるように伝えないとね") == [
        "高すぎたか", "もっと", "みんなに", "わかるように", "伝えないとね"]
    assert phrases("もしかして今のままのレベルで収まるなっていう") == [
        "もしかして", "今のままのレベルで", "収まるなっていう"]
    assert phrases("ねえ　ムカデに襲われた人がなんて言ったか知ってる？") == [
        "ねえ", "ムカデに", "襲われた人が", "なんて", "言ったか", "知ってる？"]


def test_interjection_after_a_finished_clause_is_a_strong_break_despite_tagger_error():
    text = "言ってたのにねいやーこんな天気のいい日はさ"
    allowed, strong = jm.bunsetsu_breaks(text, jm.word_spans(text, TAGGED[text]))
    assert text.index("いやー") in strong and text.index("こんな") in strong
    assert text.index("やー") not in allowed            # never inside いやー


def test_word_spans_keep_pauses_and_tolerate_width_normalisation():
    text = "ねえ　ムカデに襲われた人がなんて言ったか知ってる？"
    spans = jm.word_spans(text, TAGGED[text])
    assert spans[1][3] == "空白" and spans[-1][2] == "?" and spans[-1][1] == len(text)
    assert jm.word_spans("違う文", [["別", "名詞"]]) is None


@pytest.fixture
def japanese_document():
    context = get_runtime_context()
    previous = context.task_language, context.japanese_phrases
    context.task_language = "ja"
    texts = list(TAGGED)
    payload = {"tagger_version": "0.2.11", "results": [
        {"text": text, "words": words} for text, words in TAGGED.items()]}
    document = jm.build_document(texts, payload)
    jm.install(document)
    yield document
    context.task_language, context.japanese_phrases = previous


def test_segmentation_uses_task_phrases_for_substrings(japanese_document):
    from twobyteasr.segmentation import chinese_word_spans, segmenter_forbidden_boundary_offsets
    assert japanese_document.measured_segments == 4 and japanese_document.heuristic_segments == 0
    # A cue that starts mid-segment still finds its phrases in the task document.
    words = [word for _start, _end, word in chinese_word_spans("みんなにわかるように伝えないとね")]
    assert words == ["みんなに", "わかるように", "伝えないとね"]
    forbidden = segmenter_forbidden_boundary_offsets("もっとみんなにわかるように伝えないとね")
    assert 7 not in forbidden and 9 in forbidden            # みんなに|わかる…, never わかるよ|うに


def test_local_repair_cuts_long_japanese_line_only_between_phrases(japanese_document):
    from twobyteasr.segmentation import locally_repair_resegmented_cue
    text = "高すぎたかもっとみんなにわかるように伝えないとね"
    units = [subtitle_core.WordUnit(i * 0.2, i * 0.2 + 0.18, char, 0.9) for i, char in enumerate(text)]
    cues = locally_repair_resegmented_cue(text, units, comfort_max_chars=12)
    pieces = [cue.text for cue in cues]
    assert "".join(pieces) == text
    allowed = {0, len(text)} | {text.index(p) for p in ("もっと", "みんなに", "わかるように", "伝えないとね")}
    cursor = 0
    for piece in pieces:
        assert cursor in allowed
        cursor += len(piece)


def test_heuristic_fallback_splits_interjections_inside_hiragana_runs():
    from twobyteasr.language_rules import heuristic_japanese_phrase_spans
    words = [word for _s, _e, word in heuristic_japanese_phrase_spans("言ってたのにねいやーこんな")]
    assert "いやー" in words


def test_two_character_opener_joins_the_next_japanese_line():
    from twobyteasr.cue_cleanup import merge_isolated_two_character_cues
    context = get_runtime_context()
    previous = context.task_language
    context.task_language = "ja"
    try:
        cues = [subtitle_core.SubtitleCue(1, 0.0, 1.2, "これほどの猛さとは", speaker="S01"),
                subtitle_core.SubtitleCue(2, 1.3, 1.6, "いや", speaker="S01"),
                subtitle_core.SubtitleCue(3, 1.7, 2.6, "もはやこれは", speaker="S01")]
        merged = merge_isolated_two_character_cues(cues)
    finally:
        context.task_language = previous
    assert [cue.text for cue in merged] == ["これほどの猛さとは", "いやもはやこれは"]


def test_studio_refine_checks_breaks_against_the_projects_tagged_texts():
    from twobyteasr.language_rules import language_scope
    from twobyteasr.sentence_refine import _japanese_boundaries
    payload = {"tagger_version": "0.2.11", "results": [
        {"text": text, "words": words} for text, words in TAGGED.items()]}
    document = jm.build_document(list(TAGGED), payload)
    text = "もっとみんなにわかるように伝えないとね"
    with language_scope("ja"):
        coarse = _japanese_boundaries(text)
        with jm.phrase_scope(document):
            measured = _japanese_boundaries(text)
    # The coarse rule cannot split the hiragana stretch; the tagged document can.
    assert 7 not in coarse and 7 in measured and 9 not in measured
