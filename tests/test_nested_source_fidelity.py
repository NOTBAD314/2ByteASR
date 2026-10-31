"""Contained same-speaker utterances must not truncate or reorder a turn."""
import copy
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.number_fidelity import numeric_event_values
from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content, _spread_on_source
from twobyteasr.subtitle_rules.text_rules import content_exact


def segment(i, start, end, text, speaker="S01"):
    return SpeechSegment(i, start, end, text, .9, [], speaker=speaker)


def cue(i, start, end, text, speaker="S01"):
    return SubtitleCue(i, start, end, text, speaker=speaker)


def chronological_text(rows):
    return "".join(content_exact(c.text) for c in sorted(rows, key=lambda c: (c.start, c.end)))


def assert_delivery(rows, source):
    ordered = sorted(rows, key=lambda c: (c.start, c.end))
    assert chronological_text(ordered) == "".join(content_exact(s.text) for s in source)
    assert tuple(v for c in ordered for v in numeric_event_values(c.text)) == tuple(
        v for s in source for v in numeric_event_values(s.text))
    assert all(0 < c.end - c.start <= 5.05 and core.display_length(c.text) <= 16 for c in ordered)
    assert all(b.start >= a.end - .001 for a, b in zip(ordered, ordered[1:]))


def test_nested_short_source_does_not_truncate_a_correct_turn(monkeypatch):
    source = [segment(1, 0, 8, "我们讲五个专题然后先讲前三个"),
              segment(2, .03, .49, "好"), segment(3, 8.23, 9.5, "继续下一句")]
    final = [cue(1, 0, 3, "我们讲五个专题"), cue(2, 3, 7.5, "然后先讲前三个"),
             cue(3, 7.5, 8, "好"), cue(4, 8.23, 9.5, "继续下一句")]
    def unexpected(*args):
        pytest.fail("Already conserved captions should not require reconstruction")
    monkeypatch.setattr(core, "build_local_source_cues", unexpected)
    with language_scope("zh"):
        result = recover_final_content(final, copy.deepcopy(final), source, [], core)
    assert result is final
    assert_delivery(result, source)


@pytest.mark.parametrize("tail_start,tail_end", [(661.65, 662.11), (661.62, 662.11), (666, 668)])
def test_recovery_preserves_contained_utterance_and_both_numbers(tail_start, tail_end):
    # Same containment shape and times as the lecture; independent text keeps this fixture public.
    source = [segment(1, 661.62, 670.22, "然后我们讲五个专题今天先讲前三个"),
              segment(2, tail_start, tail_end, "好"), segment(3, 670.45, 672.0, "接着往下看")]
    source.sort(key=lambda s: (s.start, s.end, s.segment_id))
    before = copy.deepcopy(source)
    with language_scope("zh"):
        result = recover_final_content([], [], source, [], core)
    assert_delivery(result, source)
    assert [(s.start, s.end, s.text, s.words) for s in source] == [
        (s.start, s.end, s.text, s.words) for s in before]


def test_chained_overlaps_keep_source_order_and_leave_distant_speaker_untouched():
    source = [segment(1, 0, 6, "这次讲五个专题"), segment(2, 1, 1.5, "好"),
              segment(3, 4, 8, "今天先讲前三个"), segment(4, 8.2, 9, "继续")]
    other = segment(5, 20, 22, "另一位说话人", "S02")
    untouched = cue(99, 20, 22, other.text, "S02")
    with language_scope("zh"):
        result = recover_final_content([untouched], [untouched], [*source, other], [], core)
    assert next(c for c in result if c.speaker == "S02") is untouched
    assert_delivery([c for c in result if c.speaker == "S01"], source)
    assert max(c.end for c in result if c.speaker == "S01") <= 9.05


def test_unsuccessful_spread_does_not_partially_retime_captions():
    source = [segment(1, 0, 2, "第一句"), segment(2, 3, 4, "第二句")]
    pieces = [cue(1, 10, 11, "第一句"), cue(2, 20, 21, "缺字")]
    before = copy.deepcopy(pieces)
    assert _spread_on_source(pieces, source) is None
    assert pieces == before


def test_normal_finalization_recovers_nested_local_grouping_fallback():
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    source = [segment(1, 661.62, 670.22, "然后我们讲五个专题今天先讲前三个"),
              segment(2, 661.65, 662.11, "好"), segment(3, 670.45, 672, "接着往下看")]
    grouped = [cue(s.segment_id, s.start, s.end, s.text) for s in source]
    with language_scope("zh"):
        result = finalize_cues(grouped, source, [], [], 680, 27, core)
    assert chronological_text(result) == "".join(s.text for s in source)
    assert all(b.start >= a.end-.001 for a, b in zip(result, result[1:]))
    assert tuple(v for c in result for v in numeric_event_values(c.text)) == ("5", "3")


def test_timing_policy_invalidates_only_final_timing_cache(monkeypatch):
    from twobyteasr.recognition import cache
    stages = ("audio", "firered_vad", "moss", "qwen", "grouped_local", "final_timing")
    before = {stage: cache.cache_stage_signature(stage) for stage in stages}
    monkeypatch.setattr(cache, "TIMING_LOGIC_VERSION", "previous-timing-policy")
    changed = [stage for stage in stages if before[stage] != cache.cache_stage_signature(stage)]
    assert changed == ["final_timing"]


@pytest.mark.parametrize("text", ["漏字", "我们讲六个专题然后先讲前三个好", "我们讲五个专题好然后先讲前三个"])
def test_nested_overlap_does_not_relax_text_or_number_validation(text):
    source = [segment(1, 0, 8, "我们讲五个专题然后先讲前三个"), segment(2, .03, .49, "好")]
    bad = [cue(1, 0, 5, text)]
    legacy = SimpleNamespace(MAX_SUBTITLE_SECONDS=5, COMPLETE_PHRASE_SOFT_MAX_CHARS=16,
                             display_length=core.display_length,
                             build_local_source_cues=lambda *_: copy.deepcopy(bad),
                             record_run_event=lambda *_a, **_kw: None)
    with language_scope("zh"), pytest.raises(ValueError, match="字幕保真检查未通过"):
        recover_final_content(bad, copy.deepcopy(bad), source, [], legacy)
