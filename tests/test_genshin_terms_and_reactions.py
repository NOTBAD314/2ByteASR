# -*- coding: utf-8 -*-
import json
from pathlib import Path

import subtitle_core
from subtitle_core import (
    SpeechSegment,
    collect_global_term_disputes,
    format_subtitle_display_text,
)


ROOT = Path(__file__).resolve().parents[1]


def _segment(segment_id, text, confidence=0.9, overlap=False):
    return SpeechSegment(
        segment_id,
        float(segment_id),
        float(segment_id) + 1.0,
        text,
        confidence,
        [],
        speaker="S01",
        moss_text=text,
        overlapping_speaker_conflict=overlap,
    )


def test_ohyo_reaction_word_is_never_split_in_the_middle():
    assert format_subtitle_display_text("哦哟这什么玩意") == "哦哟 这什么玩意"
    assert format_subtitle_display_text("哦呦这什么玩意") == "哦呦 这什么玩意"
    assert "哦 哟" not in format_subtitle_display_text("哦哟这什么玩意")
    assert "哦 呦" not in format_subtitle_display_text("哦呦这什么玩意")


def test_hao_lai_display_pause_does_not_split_hao_lai_le():
    assert format_subtitle_display_text("好来就看第一个") == "好 来 就看第一个"
    assert format_subtitle_display_text("好来了来了") == "好来了来了"


def test_genshin_profile_contains_current_verified_terms_and_aliases():
    payload = json.loads((ROOT / "game_profiles.json").read_text(encoding="utf-8"))
    items = payload["profiles"]["原神"]["terms"]
    by_name = {item["canonical"]: item for item in items}
    assert {"若娜瓦", "菲林斯", "伊涅芙", "薇斯纳", "达妮卡", "星扩散"} <= set(by_name)
    assert "若纳瓦" in by_name["若娜瓦"]["aliases"]
    assert {"伊涅福", "伊涅弗"} <= set(by_name["伊涅芙"]["aliases"])
    assert by_name["至冬"]["replacement_mode"] == "global"
    assert by_name["纪行"]["replacement_mode"] == "global"


def test_genshin_aliases_fix_current_machine_transcript(monkeypatch):
    monkeypatch.setattr(subtitle_core, "RUNTIME_GAME_NAME", "原神")
    monkeypatch.setattr(subtitle_core, "RUNTIME_ENABLE_DOMAIN_TERMS", True)
    text = "跟若纳瓦打起来了哦侍奉至东王座啊菲林斯伊涅福哦骑行换新了"
    fixed = subtitle_core.normalize_output_text(text)
    assert fixed == "跟若娜瓦打起来了哦侍奉至冬王座啊菲林斯伊涅芙哦纪行换新了"


def test_term_search_candidates_include_consensus_and_overlap_segments():
    consensus = _segment(1, "跟若纳瓦打起来了", confidence=0.95)
    overlap = _segment(2, "哦侍奉至东王座", confidence=0.9, overlap=True)
    low_confidence = _segment(3, "啊菲林斯伊涅福", confidence=0.5)
    rows = collect_global_term_disputes(
        [consensus, overlap, low_confidence],
        stable_term_candidates=[],
    )
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {1, 2, 3}
    assert by_id[1]["audit_reason"] == "broad_proper_noun_audit"
    assert by_id[2]["overlapping_speaker_conflict"] is True
    assert by_id[3]["low_confidence"] is True
