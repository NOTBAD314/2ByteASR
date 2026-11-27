"""Tests for Action-First Micro-Upgrade friction detectors & anti-Clippy guardrails."""
from __future__ import annotations

from pathlib import Path

from twobyteasr.app.micro_upgrade import MicroUpgradeTracker, QUIET_DURATION_S


def test_repeated_typo_offer_and_two_dismiss_seven_day_quiet(tmp_path: Path):
    prefs = tmp_path / "micro.json"
    tracker = MicroUpgradeTracker(prefs_path=prefs)

    # Needs >= 2 manual fixes AND remaining > 0
    assert tracker.check_repeated_typo([{"source": "元神", "target": "原神", "count": 1, "left": 5}], now=100.0) is None
    offer = tracker.check_repeated_typo([{"source": "元神", "target": "原神", "count": 2, "left": 11}], now=100.0)
    assert offer is not None
    assert offer.kind == "repeated_typo"
    assert "11" in offer.action_label and "Ctrl+H" in offer.insight_after

    # Dismiss twice -> silenced for 7 days across fresh sessions
    tracker.record_dismissed("repeated_typo", now=100.0)
    tracker.record_dismissed("repeated_typo", now=200.0)

    tracker2 = MicroUpgradeTracker(prefs_path=prefs)
    assert tracker2.check_repeated_typo([{"source": "杰风", "target": "捷风", "count": 3, "left": 7}], now=300.0) is None
    # After 7 days quiet window expires, eligible again
    assert tracker2.check_repeated_typo(
        [{"source": "杰风", "target": "捷风", "count": 3, "left": 7}],
        now=200.0 + QUIET_DURATION_S + 10.0,
    ) is not None


def test_pronoun_review_and_timing_detectors(tmp_path: Path):
    tracker = MicroUpgradeTracker(prefs_path=tmp_path / "micro.json")

    assert tracker.note_text_diff("他说好了", "她说好了", now=10.0) is None
    assert tracker.note_text_diff("他来了", "她来了", now=20.0) is None
    offer_p = tracker.note_text_diff("他走了", "它走了", now=30.0)
    assert offer_p is not None and "Shift+F" in offer_p.action_label

    # 4 consecutive timing shifts in same direction (after cooldown)
    for idx in range(3):
        assert tracker.note_manual_timing_shift(250, now=100.0 + idx) is None
    offer_t = tracker.note_manual_timing_shift(280, remaining_after=12, now=120.0)
    assert offer_t is not None and "Alt" in offer_t.action_label

    # 5 manual flagged edits without opening R review mode
    for idx in range(4):
        assert tracker.note_manual_flagged_edit(remaining_flagged=10, now=200.0 + idx) is None
    offer_r = tracker.note_manual_flagged_edit(remaining_flagged=10, now=210.0)
    assert offer_r is not None and "R" in offer_r.action_label
