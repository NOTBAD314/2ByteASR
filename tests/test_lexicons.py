"""Lexicon files must stay valid: unique names, no single CJK characters
(they would pollute the term candidates), and registered in game profiles."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

LEXICONS = Path(__file__).resolve().parents[1] / "lexicons"
PROFILES = Path(__file__).resolve().parents[1] / "game_profiles.json"


@pytest.mark.parametrize(
    "name",
    [
        "arknights_operators.json",
        "arknights_terms.json",
        "zenless_characters.json",
        "zenless_terms.json",
        "rocom_skills.json",
        "rocom_spirits.json",
    ],
)
def test_lexicon_schema_and_uniqueness(name):
    payload = json.loads((LEXICONS / name).read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    names = [entry["name"] for entry in payload["entries"]]
    assert all(isinstance(n, str) and n for n in names)
    # 新增词典必须唯一；rocom 为历史数据（存在既有重复），只校验 schema
    if name.startswith(("arknights_", "zenless_")):
        assert len(names) == len(set(names)), "entry names must be unique"


def test_no_single_character_entries_in_new_lexicons():
    for name in ("arknights_operators.json", "arknights_terms.json",
                 "zenless_characters.json", "zenless_terms.json"):
        payload = json.loads((LEXICONS / name).read_text(encoding="utf-8"))
        for entry in payload["entries"]:
            assert not re.fullmatch(r"[\u4e00-\u9fff]", entry["name"]), (
                f"single CJK character must not be a lexicon entry: {entry['name']}"
            )


def test_new_lexicons_registered_in_game_profiles():
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    registered = {
        path
        for profile in profiles["profiles"].values()
        for path in (profile.get("lexicons") or [])
    }
    assert "lexicons/arknights_operators.json" in registered
    assert "lexicons/zenless_characters.json" in registered
    assert "明日方舟" in profiles["profiles"]


def test_every_lexicon_parses_and_only_the_common_lists_are_unwired():
    """2026-10-17: streaming_common_terms.json had a stray ']' and nothing noticed."""
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    files = {path.name: path for path in LEXICONS.glob("*.json")}
    for name, path in files.items():
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
        assert entries and all(str(entry.get("name") or "").strip() for entry in entries), name
    registered = {
        Path(path).name
        for profile in profiles["profiles"].values()
        for path in (profile.get("lexicons") or [])
    }
    assert registered <= set(files)
    # Everyday words (弹幕、关注、辅助…) would only pull ordinary speech toward
    # themselves as reference names, so these two stay out of every profile.
    assert set(files) - registered == {"gaming_common_terms.json", "streaming_common_terms.json"}
