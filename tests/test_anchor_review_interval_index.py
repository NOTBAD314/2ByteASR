"""The fast token window preserves the exhaustive review result and ordering."""
import copy
import random

import subtitle_core
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import timing


def test_index_matches_exhaustive_coverage_for_unsorted_and_long_overlapping_tokens(monkeypatch):
    rng = random.Random(2810)
    tokens = [{"start": i*.3, "end": i*.3+.22, "text": "古龙"} for i in range(2000)]
    # Long intervals and reversed/touching timestamps must retain the original
    # exhaustive predicate; a starts-only bisection would incorrectly lose them.
    tokens += [{"start": 0, "end": 600, "text": "骨龙"},
               {"start": 100, "end": 99, "text": "龙"}]
    rng.shuffle(tokens)
    segments = [SpeechSegment(i, t, t+1.5, "古龙", .99, []) for i,t in enumerate((0, 5, 99.5, 310, 599))]
    original = copy.deepcopy(tokens)
    helper = timing.firered_anchor_coverage
    expected = {s.segment_id: helper(s, tokens) for s in segments}
    counts = []
    def checked(segment, subset):
        result = helper(segment, subset)
        assert result == expected[segment.segment_id]
        counts.append(len(subset))
        return result
    monkeypatch.setattr(timing, "firered_anchor_coverage", checked)
    monkeypatch.setattr(timing, "add_review_item", lambda *a, **k: None)
    monkeypatch.setattr(timing, "record_run_event", lambda *a, **k: None)
    timing.collect_review_items(segments, [], [], tokens)
    assert len(counts) == len(segments)
    assert tokens == original


def test_short_regular_tokens_do_not_rescan_the_whole_hour(monkeypatch):
    tokens = [{"start": i, "end": i+.5, "text": "字幕"} for i in range(3600)]
    segments = [SpeechSegment(i, i, i+.5, "字幕", .99, []) for i in range(10)]
    counts = []
    helper = timing.firered_anchor_coverage
    def checked(segment, subset):
        counts.append(len(subset))
        return helper(segment, subset)
    monkeypatch.setattr(timing, "firered_anchor_coverage", checked)
    monkeypatch.setattr(timing, "add_review_item", lambda *a, **k: None)
    monkeypatch.setattr(timing, "record_run_event", lambda *a, **k: None)
    timing.collect_review_items(segments, [], [], tokens)
    assert max(counts) < 10
