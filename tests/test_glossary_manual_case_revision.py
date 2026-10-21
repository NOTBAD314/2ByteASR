"""Manual case revision must reach persisted terms and new task snapshots."""
import json

import pytest

import subtitle_core as legacy
from twobyteasr.glossary.terminology import snapshot_glossaries


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})


@pytest.mark.parametrize("old,canonical", [("berlin", "BerLIN"), ("s0pp", "S0pp"), ("zhe", "Zhe")])
def test_manual_reentry_revises_canonical_spelling_without_alias_answers(old, canonical):
    legacy.add_learned_mapping("选手库", old, old, category="选手 ID")
    library_id = legacy.resolve_glossary_identity("选手库")
    old_snapshot = snapshot_glossaries(legacy, [library_id])

    assert legacy.add_learned_mapping(library_id, canonical, canonical, category="选手 ID")
    persisted = json.loads(open(legacy.LEARNED_TERMS_PATH, encoding="utf8").read())
    assert [(row["from"], row["to"]) for row in persisted["games"][library_id]["mappings"]] == [(canonical, canonical)]
    reopened = snapshot_glossaries(legacy, [library_id])
    assert reopened.canonical_terms == (canonical,)
    assert reopened.digest != old_snapshot.digest
    assert reopened.libraries[0].revision != old_snapshot.libraries[0].revision
    assert old_snapshot.canonical_terms == (old,)


def test_manual_revision_updates_existing_alias_targets_and_preserves_evidence():
    legacy.add_learned_mapping("库", "lowername", "lowername", category="选手 ID")
    legacy.add_learned_mapping("库", "旧别名", "lowername", category="选手 ID")
    prior = legacy.learned_mappings_for_game("库")[1]
    assert legacy.add_learned_mapping("库", "LowerNAME", "LowerNAME", category="选手 ID")
    rows = legacy.learned_mappings_for_game("库")
    assert {(row["from"], row["to"]) for row in rows} == {
        ("LowerNAME", "LowerNAME"), ("旧别名", "LowerNAME")}
    assert rows[1]["verification"] == prior["verification"]
    assert rows[1]["sources"] == prior["sources"]


def test_import_and_learning_do_not_revise_user_confirmed_case():
    legacy.add_learned_mapping("库", "LowerNAME", "LowerNAME")
    assert legacy.add_learned_mapping("库", "lowername", "lowername", origin="批量导入") is False
    legacy.persist_learned_mappings("库", [
        {"from": "lowername", "to": "lowername", "confirmed": True, "verification": "web_official"},
        {"from": "另个写法", "to": "lowername", "confirmed": True, "verification": "web_official"},
    ])
    assert {row["to"] for row in legacy.learned_mappings_for_game("库")} == {"LowerNAME"}


def test_manual_canonical_reentry_cannot_reassign_an_existing_alias():
    legacy.add_learned_mapping("库", "Alpha", "Beta")
    with pytest.raises(ValueError, match="冲突"):
        legacy.add_learned_mapping("库", "ALPHA", "ALPHA")
    assert [(row["from"], row["to"]) for row in legacy.learned_mappings_for_game("库")] == [("Alpha", "Beta")]
