"""Tests for upgraded AI Glossary Proofreading: in-place alias removal + undo & 4-key speed review."""
from __future__ import annotations

import json
from pathlib import Path

from twobyteasr.glossary.proofread_speed_review import (
    collect_manual_edit_pairs,
    find_term_record_for_issue,
    next_pending_cue_id,
    pick_adopt_index,
    remove_alias_from_term,
)
from twobyteasr.glossary.terminology import snapshot_glossaries


class _FakeLegacy:
    def __init__(self, path: Path, payload: dict):
        self.LEARNED_TERMS_PATH = path
        self.path = path
        self.atomic_write_json(path, payload)

    def load_learned_term_payload(self, strict: bool = False):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def atomic_write_json(self, path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _touch_glossary_entry(self, entry: dict, lib_id: str):
        entry["revision"] = str(int(entry.get("revision") or 0) + 1)

    def glossary_catalog(self):
        data = self.load_learned_term_payload()
        return [{"id": k, "name": v.get("game", k)} for k, v in data.get("games", {}).items()]

    def load_glossary_profile(self, lib_id: str):
        return {}

    def _profile_lexicon_paths_for(self, profile):
        return []


def test_inplace_find_and_remove_bad_alias_with_undo(tmp_path: Path):
    legacy = _FakeLegacy(tmp_path / "learned_terms.json", {
        "schema_version": 2,
        "games": {
            "val": {
                "game": "瓦罗兰特",
                "revision": "1",
                "mappings": [
                    {"from": "捷风", "to": "捷风", "category": "角色", "origin": "手动", "provenance": "user_confirmed", "confirmed": True},
                    {"from": "杰风", "to": "捷风", "category": "角色", "origin": "手动", "provenance": "user_confirmed", "confirmed": True},
                    {"from": "接风", "to": "捷风", "category": "角色", "origin": "手动", "provenance": "user_confirmed", "confirmed": True},
                ],
            }
        },
    })
    snap = snapshot_glossaries(legacy, ("val",))
    rec = find_term_record_for_issue(snap, "捷风", "接风")
    assert rec is not None
    assert rec.canonical == "捷风"
    assert "接风" in rec.aliases and "杰风" in rec.aliases

    # Remove ONLY the bad alias "接风" — canonical "捷风" and good alias "杰风" stay!
    change = remove_alias_from_term(legacy, rec, "接风")
    snap_after = snapshot_glossaries(legacy, ("val",))
    rec_after = find_term_record_for_issue(snap_after, "捷风")
    assert rec_after is not None
    assert "接风" not in rec_after.aliases
    assert "杰风" in rec_after.aliases

    # Undo restores "接风" cleanly
    change.undo(legacy)
    snap_undo = snapshot_glossaries(legacy, ("val",))
    rec_undo = find_term_record_for_issue(snap_undo, "捷风", "接风")
    assert rec_undo is not None and "接风" in rec_undo.aliases


def test_speed_review_navigation_option_pick_and_manual_pairs():
    visible = ["c1", "c2", "c3", "c4", "c5"]
    pending = {"c2", "c4"}

    # Forward circular wrap across pending-only rows
    assert next_pending_cue_id(visible, "c1", lambda cid: cid in pending) == "c2"
    assert next_pending_cue_id(visible, "c2", lambda cid: cid in pending) == "c4"
    assert next_pending_cue_id(visible, "c4", lambda cid: cid in pending) == "c2"
    # Reverse circular wrap
    assert next_pending_cue_id(visible, "c2", lambda cid: cid in pending, reverse=True) == "c4"
    assert next_pending_cue_id(visible, "c1", lambda _cid: False) == ""

    # Single unambiguous group -> key A picks first part
    single_groups = [{"state": "open", "reviewed": False, "options": False, "parts": [2]}]
    assert pick_adopt_index(single_groups) == (2, "")

    # Multi-option group -> key A hints to press 1..2; keys 1 / 2 pick exact option
    multi_groups = [{"state": "open", "reviewed": False, "options": True, "parts": [0, 1]}]
    idx_a, hint = pick_adopt_index(multi_groups)
    assert idx_a is None and "1～2" in hint
    assert pick_adopt_index(multi_groups, option_slot=0) == (0, "")
    assert pick_adopt_index(multi_groups, option_slot=1) == (1, "")

    # Collect repeated manual edits for QuickTermCaptureDialog
    rows = [
        {"origin": "杰风起大", "base": "捷风起大"},
        {"origin": "杰风进点", "base": "捷风进点"},
        {"origin": "不变", "base": "不变"},
    ]
    pairs = collect_manual_edit_pairs(rows, lambda a, b: ("杰风", "捷风") if a != b else None)
    assert pairs == [{"source": "杰风", "target": "捷风", "count": 2, "left": 0}]
