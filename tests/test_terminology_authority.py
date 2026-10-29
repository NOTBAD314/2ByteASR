"""Recall, transmitted evidence and storage share existing confirmation authority."""
import json
from types import SimpleNamespace

import pytest

import subtitle_core as legacy
from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry, TermResolver, snapshot_glossaries
from twobyteasr.glossary.terminology_retrieval import retrieve_candidates


def case_snapshot(lower_kind, reverse=False):
    if lower_kind == "builtin":
        lower = GlossaryLibrary("official", "Official", "1", (
            TermEntry("berlin", ("berlin",), provenance="builtin", priority=10),))
    else:
        lower = GlossaryLibrary("reference", "Reference", "1", reference_terms=("berlin",))
    manual = GlossaryLibrary("manual", "Manual", "2", (TermEntry("BerLIN"),))
    return GlossarySnapshot((manual, lower) if reverse else (lower, manual))


@pytest.mark.parametrize("lower_kind", ["builtin", "reference"])
@pytest.mark.parametrize("reverse", [False, True])
def test_manual_case_wins_in_recall_and_serialized_prompt(context, monkeypatch, lower_kind, reverse):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = case_snapshot(lower_kind, reverse)
    original_snapshot = owner.glossary_snapshot.to_dict()
    row = SpeechSegment(4, 0, 1, "Borlin也没有接住", .85, [])
    resolver = TermResolver(owner.glossary_snapshot)
    assert resolver.resolve("berlin").text == "BerLIN" and not resolver.conflicts
    candidates = retrieve_candidates(owner.glossary_snapshot, [row])
    assert [(x["canonical"], x["ambiguous"]) for x in candidates] == [("BerLIN", False)]
    assert {x["library_id"] for x in candidates[0]["sources"]} == {
        "manual", "official" if lower_kind == "builtin" else "reference"}
    sent = []
    def complete(messages, **kwargs):
        body = json.loads(messages[1]["content"])
        sent.append(body)
        # Definitions are transmitted once in the candidate table; the legacy
        # duplicate evidence list no longer carries a second spelling source.
        assert [x["canonical"] for x in body["terminology_candidates"]] == ["BerLIN"]
        return json.dumps({"checked_ids": [4], "cues": [{"id": 4, "edits": [
            {"from": "Borlin", "to": "berlin", "basis": "glossary+context"}]}]})
    monkeypatch.setattr("twobyteasr.providers.ai_providers.provider_for_stage", lambda *a, **k:
        SimpleNamespace(complete=complete))
    result = polishing.call_correction_api([row], [], "", "", "Real transcript", "", [], [], [],
        glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[4] == "BerLIN也没有接住" and len(sent) == 1
    # Projection does not revise the original task snapshot or its sources.
    assert owner.glossary_snapshot.to_dict() == original_snapshot


@pytest.mark.parametrize("other", ["berlin", "Barlin"])
@pytest.mark.parametrize("reverse", [False, True])
def test_equal_priority_case_conflict_and_distinct_names_keep_ambiguity(other, reverse):
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    libraries = (GlossaryLibrary("a", "A", "1", (TermEntry("BerLIN"),)),
                 GlossaryLibrary("b", "B", "1", (TermEntry(other),)))
    snapshot = GlossarySnapshot(tuple(reversed(libraries)) if reverse else libraries)
    row = SpeechSegment(4, 0, 1, "Borlin也没有接住", .85, [])
    candidates = retrieve_candidates(snapshot, [row])
    assert {x["canonical"] for x in candidates} == {"BerLIN", other}
    assert all(x["ambiguous"] for x in candidates)
    text, edits = apply_correction_edits(row.text, [], [
        {"from": "Borlin", "to": "BerLIN", "basis": "glossary+context"}],
        contextual_term_candidates=candidates, cue_id=4, independent_sources=[])
    assert text == row.text and edits == []
    if other == "berlin":
        assert "berlin" not in TermResolver(snapshot).canonical_spellings
        assert set(snapshot.evidence()["canonical_terms"]) == {"BerLIN", "berlin"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "terms.json"
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(path))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: {})
    return path


@pytest.mark.parametrize("manual_evidence", [
    {"verification": "user_manual"}, {"sources": ["user_manual"]},
    {"origin": "手动"}, {"provenance": "user_confirmed"},
])
@pytest.mark.parametrize("operation", ["ai_merge", "import"])
def test_legacy_manual_without_confirmed_is_preserved_on_update(store, manual_evidence, operation):
    old = {"from": "BerLIN", "to": "BerLIN", **manual_evidence}
    payload = {"schema": 1, "games": {"v": {"game": "Library", "mappings": [old]}}}
    store.write_text(json.dumps(payload), encoding="utf8")
    assert snapshot_glossaries(legacy, ["v"]).canonical_terms == ("BerLIN",)
    if operation == "ai_merge":
        report = legacy.persist_learned_mappings("v", [
            {"from": "berlin", "to": "berlin", "confirmed": True, "verification": "web_official"},
            {"from": "OldAlias", "to": "berlin", "confirmed": True, "verification": "web_official"}])
        assert report["protected"] == 1
        assert {x["to"] for x in legacy.learned_mappings_for_game("v")} == {"BerLIN"}
    else:
        assert legacy.add_learned_mapping("v", "berlin", "berlin", origin="批量导入") is False
        assert legacy.add_learned_mapping("v", "OldAlias", "berlin", origin="批量导入") is True
    reopened = snapshot_glossaries(legacy, ["v"])
    assert reopened.canonical_terms == ("BerLIN",)
    saved = json.loads(store.read_text("utf8"))["games"]["v"]["mappings"]
    assert saved[0] == old
    assert all(x["to"] == "BerLIN" for x in saved)


@pytest.mark.parametrize("extra", [
    {"confirmed": False}, {"provenance": "candidate"},
])
def test_explicit_unconfirmed_or_candidate_manual_record_does_not_gain_authority(store, extra):
    old = {"from": "BerLIN", "to": "BerLIN", "verification": "user_manual", **extra}
    store.write_text(json.dumps({"schema": 1, "games": {"v": {"game": "Library", "mappings": [old]}}}), encoding="utf8")
    assert snapshot_glossaries(legacy, ["v"]).canonical_terms == ()
    report = legacy.persist_learned_mappings("v", [
        {"from": "berlin", "to": "berlin", "confirmed": True, "verification": "web_official"}])
    assert report["protected"] == 0
    assert snapshot_glossaries(legacy, ["v"]).canonical_terms == ()
