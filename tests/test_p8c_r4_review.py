from __future__ import annotations

from types import SimpleNamespace

from twobyteasr.subtitle_rules.studio_review import (
    ReviewEvidenceAggregator,
    ReviewRiskType,
    ReviewTriageAI,
    ReviewTriageDecision,
)
from twobyteasr.rendering.renderer_service import RendererJob


def _cue(text="你瞅他还能换衣服的", speaker="S02"):
    return SimpleNamespace(id="cue-1", text=text, speaker_id=speaker, start_ms=0, end_ms=1000)


def test_boundary_only_stream_is_not_lexical_review():
    evidence = [
        {"model": "MOSS", "text": "你", "start_ms": 0, "end_ms": 300, "speaker_id": "S02"},
        {"model": "MOSS", "text": "瞅他还能换衣服的", "start_ms": 300, "end_ms": 1000, "speaker_id": "S02"},
        {"model": "Qwen", "text": "你瞅他还能换衣服的", "start_ms": 0, "end_ms": 1000, "speaker_id": "S02"},
    ]
    aggregate = ReviewEvidenceAggregator().aggregate(_cue(), evidence)
    assert aggregate.models_agree_text
    assert aggregate.boundary_only
    assert not aggregate.requires_review
    assert ReviewRiskType.LEXICAL.value not in aggregate.risk_types


def test_speaker_only_and_small_timing_difference_are_separate():
    evidence = [
        {"model": "MOSS", "text": "同一句", "start_ms": 0, "end_ms": 1000, "speaker_id": "S02"},
        {"model": "Qwen", "text": "同一句", "start_ms": 80, "end_ms": 1080, "speaker_id": "S03"},
    ]
    aggregate = ReviewEvidenceAggregator().aggregate(_cue("同一句", "S02"), evidence)
    assert aggregate.models_agree_text
    assert aggregate.speaker_only
    assert ReviewRiskType.SPEAKER.value in aggregate.risk_types
    assert ReviewRiskType.TIMING.value not in aggregate.risk_types


def test_lexical_conflict_requires_human():
    evidence = [
        {"model": "MOSS", "text": "天平", "start_ms": 0, "end_ms": 1000},
        {"model": "Qwen", "text": "甜品", "start_ms": 0, "end_ms": 1000},
    ]
    aggregate = ReviewEvidenceAggregator().aggregate(_cue("天平"), evidence)
    assert not aggregate.models_agree_text
    assert aggregate.requires_review
    assert ReviewRiskType.LEXICAL.value in aggregate.risk_types


def test_single_model_disagreement_with_current_text_is_lexical_risk():
    aggregate = ReviewEvidenceAggregator().aggregate(
        _cue("天平"),
        [{"model": "MOSS", "text": "甜品", "start_ms": 0, "end_ms": 1000}],
    )
    assert not aggregate.models_agree_text
    assert aggregate.requires_review
    assert ReviewRiskType.LEXICAL.value in aggregate.risk_types


def test_triage_is_batched_and_cannot_hide_lexical_conflict():
    calls = []

    class Provider:
        def structured_complete(self, messages, schema, **kwargs):
            calls.append((messages, schema, kwargs))
            return {"results": [{"candidate_id": "cue-1:review", "decision": "KEEP_AUTO", "confidence": 1.0}]}

    aggregate = ReviewEvidenceAggregator().aggregate(
        _cue("天平"),
        [{"model": "MOSS", "text": "天平"}, {"model": "Qwen", "text": "甜品"}],
    )
    result = ReviewTriageAI(Provider()).triage([aggregate])
    assert len(calls) == 1
    assert result[0].decision == ReviewTriageDecision.NEEDS_HUMAN.value
    assert result[0].provider_succeeded


def test_renderer_job_identity_is_stable_and_job_kind_is_closed():
    job = RendererJob("frame.png", {}, 0)
    first = job.to_dict()
    second = job.to_dict()
    assert first["job_id"] == second["job_id"]
    assert first["requested_at"] == second["requested_at"]

    try:
        RendererJob("frame.png", {}, 0, job_kind="unknown")
    except ValueError as exc:
        assert "unsupported renderer job kind" in str(exc)
    else:
        raise AssertionError("unknown renderer job kinds must be rejected")
