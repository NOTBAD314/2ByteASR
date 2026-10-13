"""Japanese tasks: language decision, text rules and per-cue aligned word evidence."""
from types import SimpleNamespace

import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr import language_rules as lr
from twobyteasr.cue_forced_alignment import (CUE_ALIGNMENT_PREFIX, attach_project_evidence, evidence_row,
                                             remap_whitespace_only)
from twobyteasr.cue_word_alignment import cue_words
from twobyteasr.runtime import get_runtime_context
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio_timing import resolve_split


def test_kanji_alone_do_not_make_japanese_but_kana_do():
    assert lr.resolve_task_language("auto", ["今天天气很好", "我们走吧"])[0] == lr.ZH
    language, evidence = lr.resolve_task_language("auto", ["恐ろしいわ、すえ恐ろしいわ", "天気いいを買いに行く"])
    assert language == lr.JA and evidence["decided_by"] == "transcript_scripts"
    # A Japanese line written only in kanji is still Japanese inside a Japanese task.
    assert lr.resolve_task_language("auto", ["期待", "反省", "もしかして今のままのレベルで"])[0] == lr.JA
    manual, evidence = lr.resolve_task_language("ja", ["今天天气很好"])
    assert manual == lr.JA and evidence["decided_by"] == "manual" and evidence["disagrees_with_transcript"] == lr.ZH
    assert lr.resolve_task_language("auto", ["OK OK"], asr_detected="Japanese")[0] == lr.JA
    assert lr.resolve_task_language("auto", [""])[0] == lr.ZH


def test_model_roles_are_recorded_per_language():
    assert lr.supports("moss", "transcribe", lr.JA) and lr.supports("moss", "speakers", lr.JA)
    assert lr.supports("qwen_aligner", "align", lr.JA)
    assert not lr.supports("firered_aed", "align", lr.JA) and not lr.supports("paraformer", "transcribe", lr.JA)
    assert not lr.supports("moss", "align", lr.JA)


@pytest.fixture
def japanese_task():
    context = get_runtime_context()
    previous = context.task_language
    context.task_language = lr.JA
    yield context
    context.task_language = previous


def test_japanese_output_text_keeps_kanji_and_skips_chinese_rewrites(japanese_task):
    from twobyteasr import text_rules
    assert text_rules.normalize_output_text("天気いいを買いに行くって、思ってるんじゃ") == "天気いいを買いに行くって思ってるんじゃ"
    assert text_rules.content_only("ねえねえ、聞こえなかった？") == "ねえねえ聞こえなかった"
    japanese_task.task_language = ""
    assert text_rules.normalize_output_text("天氣很好呃") == "天气很好"


def test_kana_count_as_content_for_lengths_and_offsets():
    from twobyteasr.text_rules import content_only, display_length
    assert display_length("恐ろしいわすえ恐ろしいわこの子らもしかして") == 21
    assert content_only("没事 开一把就知道了，OK！") == "没事开一把就知道了ok"   # Chinese unchanged


def test_japanese_phrase_protection_blocks_cuts_inside_words():
    import subtitle_core  # noqa: F401  (segmentation is loaded through the legacy core)
    from twobyteasr import segmentation
    with lr.language_scope("ja"):
        assert segmentation.snap_boundaries_away_from_word_interiors("私が本当に天才だって", [6, 10]) == [5, 10]
    spans = [w for *_unused, w in lr.japanese_phrase_spans("もしかして私が本当に天才だって思ってるんじゃ")]
    assert spans == ["もしかして", "私が", "本当に", "天才だって", "思ってるんじゃ"]


def _alignment(text, pieces):
    return {"text": text, "segments": [dict(char_start=a, char_end=b, start_ms=s, end_ms=e, granularity=g,
                                            start_basis="model", end_basis="model") for a, b, s, e, g in pieces],
            "model": "Qwen/Qwen3-ForcedAligner-0.6B", "language": "Japanese", "status": "aligned",
            "units_word": [], "units_char": [], "unit_fields": []}


def test_cue_alignment_row_drives_studio_words_and_razor():
    text = "私が本当に 天才だって"
    alignment = _alignment(text, [(0, 2, 1000, 1240, "word"), (2, 5, 1240, 1600, "word"),
                                  (6, 8, 1800, 2160, "char_slot"), (8, 11, 2160, 2600, "char_slot")])
    cue = StudioCue("1", 950, 2700, text, speaker_id="S01", evidence_refs=["segment:1"])
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=5000), cues=[cue], asr_evidence={
        # The overlapping segment row carries another text's (MOSS) timing.
        "segment:1": {"words": [{"text": "私が本当に天才だって", "start_ms": 900, "end_ms": 2700}],
                      "caption_arbitration": {"acoustic_words": [{"text": "私が本当", "start_ms": 900, "end_ms": 1500}]}}})
    assert attach_project_evidence(project, [SimpleNamespace(forced_alignment=alignment)]) == 1
    assert cue.evidence_refs[0] == CUE_ALIGNMENT_PREFIX + "1"
    words, reason = cue_words(project, cue)
    assert reason == "exact_token_text"
    assert [(text[w.char_start:w.char_end], w.start_ms) for w in words] == [
        ("私が", 1000), ("本当に", 1240), ("天才", 1800), ("だって", 2160)]
    cut = resolve_split(cue, 1700, project=project)
    assert (cut.left_text, cut.right_text) == ("私が本当に", "天才だって")
    assert cut.timing_source == "exact_token_text"


def test_whitespace_only_delivery_changes_keep_alignment_and_other_changes_drop_it():
    alignment = _alignment("恐ろしいわ すえ ", [(0, 5, 0, 700, "word"), (6, 8, 900, 1200, "word")])
    moved = remap_whitespace_only(alignment, "恐ろしいわ すえ")
    assert moved["segments"][1]["char_start"] == 6 and moved["segments"][1]["char_end"] == 8
    assert remap_whitespace_only(alignment, "恐ろしいわ すえね") is None
    row = evidence_row("1", 0, 1300, "S01", moved)
    assert [w["text"] for w in row["caption_arbitration"]["acoustic_words"]] == ["恐ろしいわ", "すえ"]
    assert row["final_timing_owner"] == "Qwen3-ForcedAligner"


def test_aligner_tokens_keep_original_substrings_and_job_keys():
    from twobyteasr.asr import aligner_tokens
    payload = {"results": [{"id": "S01@1000-2000", "text": "ＡＢＣを2024年に",
                            "segments": [dict(char_start=0, char_end=4, start_ms=1000, end_ms=1300, granularity="word",
                                              start_basis="model", end_basis="model"),
                                         dict(char_start=4, char_end=10, start_ms=1300, end_ms=1300, granularity="word",
                                              start_basis="model", end_basis="model")]}]}
    tokens = aligner_tokens(payload)
    assert [t["text"] for t in tokens] == ["ＡＢＣを"]          # zero-length pieces are never tokens
    assert tokens[0]["alignment_key"] == "S01@1000-2000" and tokens[0]["source"] == "qwen-forced-aligner"
