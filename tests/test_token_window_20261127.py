"""Each segment looks only at FireRed tokens near the batch (2026-11-27, fast-anything scan).

segmentation_alignment.tokens_near_segments keeps every token any segment of
the batch keeps, so timelines and pause boundaries do not change.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import subtitle_core as core

from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules import segmentation_alignment as alignment

LUOKE = Path(__file__).parent / "fixtures/grouping_contract/luoke_cfeea.json"


def _window_kept(segment, tokens):
    pad = alignment.FIRERED_TEXT_ALIGNMENT_PAD_SECONDS
    return [token for token in tokens
            if float(token["end"]) >= segment.start - pad and float(token["start"]) <= segment.end + pad]


@pytest.fixture(scope="module")
def luoke():
    fixture = json.loads(LUOKE.read_text(encoding="utf-8"))
    shard = fixture["shards"][0]
    rows = core.deserialize_segments(shard["segments"])
    batch = shard["batches"][0]
    ids = set(batch["source_segment_ids"])
    return [row for row in rows if row.segment_id in ids], fixture["acoustic_tokens"]


def test_nearby_tokens_keep_every_token_a_segment_keeps(luoke):
    segments, tokens = luoke
    nearby = alignment.tokens_near_segments(segments, tokens)
    assert len(nearby) < len(tokens) / 4          # the point of it
    for segment in segments:
        assert _window_kept(segment, nearby) == _window_kept(segment, tokens)


def test_timelines_and_pauses_are_unchanged(luoke):
    segments, tokens = luoke
    nearby = alignment.tokens_near_segments(segments, tokens)
    with language_scope("zh"), activate_runtime_context(
            RuntimeContext(task_language="zh", enable_domain_terms=False), legacy=core):
        for segment in segments:
            full = alignment.segment_content_timeline(segment, tokens)
            near = alignment.segment_content_timeline(segment, nearby)
            assert [(u.start, u.end, u.text) for u in full] == [(u.start, u.end, u.text) for u in near]
        assert alignment.firered_pause_character_boundaries(segments, tokens) == \
            alignment.firered_pause_character_boundaries(segments, nearby)


def test_non_finite_segment_times_keep_the_full_list():
    tokens = [dict(start=1.0, end=1.2, text="好"), dict(start=50.0, end=50.2, text="的")]
    segments = [SimpleNamespace(start=float("nan"), end=2.0), SimpleNamespace(start=1.0, end=2.0)]
    assert alignment.tokens_near_segments(segments, tokens) is tokens
    assert alignment.tokens_near_segments([], tokens) is tokens
    assert alignment.tokens_near_segments(segments[1:], ()) == ()


def test_prefilter_preserves_timeline_handling_of_unordered_times():
    segments = [SimpleNamespace(start=1.0, end=2.0)]
    nearby = dict(start=1.0, end=float("nan"), text="好")
    distant = dict(start=50.0, end=50.2, text="的")
    assert alignment.tokens_near_segments(segments, [nearby, distant]) == [nearby]


def test_unreadable_time_defers_to_the_existing_reader():
    segments = [SimpleNamespace(start=1.0, end=2.0)]
    tokens = [{"start": None, "end": 1.5}]
    assert alignment.tokens_near_segments(segments, tokens) is tokens
