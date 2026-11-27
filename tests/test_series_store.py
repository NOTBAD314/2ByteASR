"""Tests for formal Series Store, lossless migration, ECAPA cross-episode matching, and trust graduation."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from twobyteasr.projects.series_store import (
    CastMember,
    SeriesStore,
    VoiceprintObservation,
)


def _vec(angle_deg: float, dim: int = 8) -> list[float]:
    rad = math.radians(angle_deg)
    v = [0.0] * dim
    v[0] = math.cos(rad)
    v[1] = math.sin(rad)
    return v


def test_series_crud_and_lossless_migration(tmp_path: Path):
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text(json.dumps({
        "schema_version": 2,
        "profiles": [{
            "id": "prof_1",
            "name": "瓦罗兰特双排",
            "language": "zh",
            "primary_asr": "moss",
            "glossary_ids": ["valorant"],
            "subtitle_style_preset": "tactical_lock",
            "use_count": 4,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    bunny_file = tmp_path / "bunny" / "memory.json"
    bunny_file.parent.mkdir(parents=True, exist_ok=True)
    bunny_file.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "id": 1,
            "kind": "recipe",
            "text": "瓦罗兰特双排",
            "data": {
                "style": {"font_size": 42, "fill_color": "#FFFFFF"},
                "break_rule": "每条不超过12字",
                "language": "zh",
                "speakers": ["主播A", "队友B"],
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")

    store = SeriesStore(tmp_path / "series")
    receipt = store.migrate_legacy_sources(profiles_path=profiles_file, bunny_memory_path=bunny_file)
    assert receipt == {"profiles": 1, "recipes": 1}

    # Idempotent on second call & original files untouched
    assert store.migrate_legacy_sources(profiles_path=profiles_file, bunny_memory_path=bunny_file) == {"profiles": 0, "recipes": 0}
    assert profiles_file.is_file() and bunny_file.is_file()

    rec = store.find_by_name("瓦罗兰特双排")
    assert rec is not None
    assert rec.glossary_ids == ["valorant"]
    assert rec.break_rules["zh"] == "每条不超过12字"
    assert rec.visual["subtitle_style_preset"] == "tactical_lock"
    assert rec.visual["style_overrides"]["font_size"] == 42
    assert [c.name for c in rec.cast] == ["主播A", "队友B"]


def test_cross_episode_ecapa_voiceprint_three_tier_and_collision_guard(tmp_path: Path):
    store = SeriesStore(tmp_path / "series")
    series = store.create("双排系列", cast=[
        CastMember(cast_id="cast_a", name="主播A"),
        CastMember(cast_id="cast_b", name="队友B"),
    ])

    # Reject short or self-inconsistent audio (plain-Chinese errors, zero jargon)
    with pytest.raises(ValueError, match="不足"):
        store.enroll_voiceprint(series.id, "cast_a", VoiceprintObservation("S01", _vec(0), _vec(0), _vec(0), seconds=2.0))
    with pytest.raises(ValueError, match="不太一致"):
        store.enroll_voiceprint(series.id, "cast_a", VoiceprintObservation("S01", _vec(0), _vec(0), _vec(80), seconds=8.0))

    # Enroll A at 0 deg and B at 90 deg
    store.enroll_voiceprint(series.id, "cast_a", VoiceprintObservation("S01", _vec(0), _vec(2), _vec(-2), seconds=12.0), episode_id="ep1")
    store.enroll_voiceprint(series.id, "cast_b", VoiceprintObservation("S02", _vec(90), _vec(88), _vec(92), seconds=10.0), episode_id="ep1")

    # Episode 2: B speaks FIRST (S01 is B, S02 is A, S03 is mid-confidence ~0.55 to B in dim 2, S04 is new at 180 deg)
    mid_b = [0.0, 0.55, math.sqrt(1.0 - 0.55 * 0.55), 0.0, 0.0, 0.0, 0.0, 0.0]
    matches = store.match_episode_speakers(series.id, [
        VoiceprintObservation("S01", _vec(89), _vec(87), _vec(91), seconds=9.0),
        VoiceprintObservation("S02", _vec(3), _vec(1), _vec(5), seconds=11.0),
        VoiceprintObservation("S03", mid_b, mid_b, mid_b, seconds=8.0),
        VoiceprintObservation("S04", _vec(180), _vec(178), _vec(182), seconds=8.0),
    ])
    by_label = {m.label: m for m in matches}
    assert by_label["S01"].tier == "automatic" and by_label["S01"].cast_name == "队友B"
    assert by_label["S02"].tier == "automatic" and by_label["S02"].cast_name == "主播A"
    assert by_label["S03"].tier == "review"
    assert by_label["S04"].tier == "new"

    # Plain-Chinese check on all reasons (no invented jargon)
    for m in matches:
        for forbidden in ("沉淀", "质心", "置信区", "自洽度"):
            assert forbidden not in m.reason

    # Collision guard: two anonymous speakers both near A -> demote BOTH to review
    collided = store.match_episode_speakers(series.id, [
        VoiceprintObservation("S01", _vec(1), _vec(0), _vec(2), seconds=10.0),
        VoiceprintObservation("S02", _vec(4), _vec(3), _vec(5), seconds=10.0),
    ])
    assert all(m.tier == "review" for m in collided)

    # Clear voiceprint removes vector cleanly
    store.clear_voiceprint(series.id, "cast_a")
    assert "cast_a" not in store.load_voiceprints(series.id)


def test_delta_settlement_and_three_hit_trust_graduation(tmp_path: Path):
    store = SeriesStore(tmp_path / "series")
    series = store.create("原神实况", glossary_ids=["common"])

    # 3 clean adoptions across 3 distinct episodes unlock graduation candidate
    for ep in ("ep1", "ep2", "ep3"):
        store.record_rule_outcome(series.id, "alias:元神->原神", "元神 → 原神", episode_id=ep, clean_adopted=True)
    assert len(store.graduated_candidates(series.id)) == 1

    delta = store.compute_delta(
        series.id,
        glossary_ids=["common", "genshin"],
        speakers=[{"name": "主播A", "color": "#e06d97"}, {"name": "S01", "color": "#fff"}],
        break_rule=("zh", "每行最多12字"),
        visual={"preset": "candy"},
    )
    kinds = [d["kind"] for d in delta]
    assert "glossary_link" in kinds
    assert "cast_add" in kinds
    assert "break_rule" in kinds
    assert "visual" in kinds
    assert "trust_graduate" in kinds

    # User-facing labels must be plain Chinese without jargon
    for item in delta:
        for forbidden in ("沉淀", "质心", "置信区", "生成器", "信任分级"):
            assert forbidden not in item["label"]

    # Graduation item must be unchecked by default (explicit opt-in)
    grad_item = next(d for d in delta if d["kind"] == "trust_graduate")
    assert grad_item["checked"] is False
    grad_item["checked"] = True

    updated = store.settle(series.id, delta, episode_label="EP03")
    assert "genshin" in updated.glossary_ids
    assert [c.name for c in updated.cast] == ["主播A"]
    assert updated.trust_ledger["alias:元神->原神"].graduated is True

    # Any future undo/rejection revokes graduation immediately
    store.record_rule_outcome(series.id, "alias:元神->原神", "元神 → 原神", episode_id="ep4", clean_adopted=False)
    reloaded = store.get(series.id)
    assert reloaded.trust_ledger["alias:元神->原神"].graduated is False
    assert reloaded.trust_ledger["alias:元神->原神"].clean_streak == 0
