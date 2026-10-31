"""Row-level review without text mutation, and stale/background safety."""
import copy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue
from twobyteasr.glossary.proofread_rules import DECISIONS_KEY, normalize_occurrence
from twobyteasr.glossary.terminology import TermResolver, snapshot_from_pairs
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.studio.studio_text_tools import TextOccurrence

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def workspace(tmp_path):
    p = SubtitleProject(StudioMedia("", duration_ms=9000), cues=[
        StudioCue("stable-90", 1000, 2400, "古龙和火龙来了"),
        StudioCue("stable-3", 4000, 5900, "另一条古龙"),
    ], generation_metadata={"translations": {"stable-90": "日本語"}},
        studio_state={"speaker_confirmations": {"S00": "keep"}})
    p.validate()
    page = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    page._project = p
    page._project_path = str(tmp_path / "校对.2byteproj")
    page._standalone = _StandalonePage(p)
    page._bind_stack(page._standalone.session.undo_stack)
    page._build_rows(p, start_checks=False)
    row = page._by_id["stable-90"]
    row["issues"] = [_issue("term", (0, 2), "古龙", "骨龙", checked=False),
                     _issue("near", (3, 5), "火龙", "火笼", checked=False)]
    page._by_id["stable-3"]["issues"] = [_issue("term", (3, 5), "古龙", "骨龙", checked=False)]
    page._apply_filter()
    yield page, p
    page._save_timer.stop()
    if hasattr(page, "_local_timer"):
        page._local_timer.stop()
    page._rematch_timer.stop()
    page.shutdown()
    page.deleteLater()
    APP.processEvents()


def test_ignore_whole_row_counts_persists_and_undo_redo(workspace, tmp_path):
    page, p = workspace
    before = copy.deepcopy((p.cues, p.generation_metadata, p.studio_state))
    page.filter_buttons["suggested"].setChecked(True)
    page._apply_filter()
    page._dismiss_group("stable-90", 1)
    assert [page._rows[i]["cue_id"] for i in page.list.visible] == ["stable-3"]
    assert all(i["ignored"] and i["reviewed"] and not i["checked"] for i in page._by_id["stable-90"]["issues"])
    assert page.proposal_counts()["adopted"] == page.proposal_counts()["changed"] == 0
    assert page.proposal_counts()["ignored"] == 1
    assert (p.cues, p.generation_metadata) == before[:2]
    assert p.studio_state["speaker_confirmations"] == before[2]["speaker_confirmations"]
    assert {r["state"] for r in p.studio_state[DECISIONS_KEY]["stable-90"]} == {"ignored"}
    page.filter_buttons["changed"].setChecked(True)
    page._apply_filter()
    assert [page._rows[i]["cue_id"] for i in page.list.visible] == []  # ignoring alone never changes text
    path = tmp_path / "重开.2byteproj"
    save_project(p, path)
    reopened = load_project(path)
    row = page._by_id["stable-90"]
    page._project = reopened
    for i in row["issues"]:
        i["ignored"] = i["reviewed"] = False
    page._apply_decisions(row, {})
    assert all(i["ignored"] for i in row["issues"])
    page._project = p
    page._undo()
    assert not any(i["ignored"] for i in row["issues"])
    assert page.proposal_counts()["ignored"] == 0
    assert page.proposal_counts()["adopted"] == 0
    page._redo()
    assert all(i["ignored"] for i in row["issues"])


def test_ignore_keeps_applied_edit_and_local_refresh_cannot_reopen_this_round(workspace):
    page, p = workspace
    page._toggle_issue("stable-90", 0)
    page._dismiss_group("stable-90", 1)
    assert p.cues[0].text == "骨龙和火龙来了"
    assert page._by_id["stable-90"]["issues"][0]["checked"]
    new = _issue("near", (3, 5), "火龙", "火隆", checked=False)
    row = page._by_id["stable-90"]
    row["issues"].append(new)
    page._apply_decisions(row, {})
    assert new['reviewed'] and new['ignored']


def test_same_word_proposal_does_not_resurface_when_its_local_or_ai_source_changes(workspace):
    page, _ = workspace
    page._dismiss_group("stable-90", 0)
    row = page._by_id["stable-90"]
    row["issues"] = [_issue("ai", (0, 2), "古龙", "骨龙", checked=False)]
    page._apply_decisions(row, {})
    assert row["issues"][0]["ignored"]


def test_ignore_survives_late_results_but_undo_cannot_accept_an_old_result(workspace):
    page, p = workspace
    original = {c.id: c.text for c in p.cues}
    versions = dict(page._cue_versions)
    hit = TextOccurrence("stable-90", 1000, "古龙", "骨龙", (0, 2), source="local_review")
    result = SimpleNamespace(hits=[hit], receipt={})
    page._dismiss_group("stable-90", 0)
    page._show_result(result, p, False, original, versions_at_run=versions)
    assert all(i["ignored"] for i in page._by_id["stable-90"]["issues"])
    page._undo()
    page._edit_committed("stable-90", "全新文字")
    page._undo()
    assert p.cues[0].text == original["stable-90"]
    page._show_result(result, p, False, original, versions_at_run=versions)
    assert not any(i.get("ignored") for i in page._by_id["stable-90"]["issues"])


def test_complete_alias_with_one_changed_letter_is_preserved_but_single_character_is_filtered():
    resolver = TermResolver(snapshot_from_pairs([("古龙", "骨龙"), ("古", "骨")]))
    hit = TextOccurrence("id", 0, "古", "骨", (2, 3), source="local_confirmed")
    expanded = normalize_occurrence(hit, "这里古龙", resolver)
    assert (expanded.original, expanded.replacement, expanded.span) == ("古龙", "骨龙", (2, 4))
    assert normalize_occurrence(hit, "这里古代", resolver) is None
    assert normalize_occurrence(TextOccurrence("id", 0, "古，", "骨！", (0, 2), source="local_review"), "古，") is None
    assert normalize_occurrence(TextOccurrence("id", 0, "他", "她", (0, 1), source="ai_accepted"), "他来了") is not None
    # Without a real alias/full-word retrieval, never pad a model's bare diff
    # with the adjacent 龙 and pretend that was a complete word match.
    from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry
    unaliased = TermResolver(GlossarySnapshot((GlossaryLibrary("id", "name", "1", terms=(TermEntry("骨龙"),)),)))
    assert normalize_occurrence(TextOccurrence("id", 0, "古", "骨", (0, 1), source="ai_accepted"), "古龙", unaliased) is None
    whole = TextOccurrence("id", 0, "古龙", "骨龙", (0, 2), source="local_review")
    assert normalize_occurrence(whole, "古龙", unaliased) == whole


def test_view_reuses_unchanged_row_layout(workspace, monkeypatch):
    page, _ = workspace
    called = []
    actual = page.list._row_height
    def height(row):
        called.append(row["cue_id"])
        return actual(row)
    monkeypatch.setattr(page.list, "_row_height", height)
    page._dismiss_group("stable-90", 0)
    assert set(called) == {"stable-90"}


def test_newer_saved_term_flags_remain_readable_and_disabled_terms_stay_disabled():
    from twobyteasr.glossary.terminology import GlossarySnapshot
    payload = snapshot_from_pairs([("古龙", "骨龙")]).to_dict()
    term = payload["libraries"][0]["terms"][0]
    term.update(correction_enabled=False, emphasis_enabled=True)
    restored = GlossarySnapshot.from_dict(payload)
    assert restored.libraries[0].terms[0].emphasis_enabled
    assert not restored.libraries[0].terms[0].correction_enabled
    assert not restored.canonical_terms
    assert TermResolver(restored).resolve("古龙").text == "古龙"


def test_incremental_local_edit_queues_without_restarting_whole_project_match(workspace):
    page, _ = workspace
    def forbidden():
        raise AssertionError("a one-cue edit must not cancel/restart the whole-project match")
    page._worker = SimpleNamespace(isRunning=lambda: True, token=SimpleNamespace(cancel=forbidden))
    page._worker_ai = False
    page._worker_scope_all = True
    try:
        page._run(False, {"stable-3"})
        assert page._queued == (False, {"stable-3"})
    finally:
        page._worker = page._queued = None


def test_pending_local_timer_is_counted_as_running(workspace):
    page, _ = workspace
    page._schedule_local_checks({"stable-3"})
    assert page.checks_running()
    page._local_timer.stop()
    assert not page.checks_running()


def test_reopened_page_does_not_resurrect_the_same_cached_suggestions(workspace, tmp_path):
    page, p = workspace
    page._dismiss_group("stable-90", 0)
    path = tmp_path / "保存重开.2byteproj"
    save_project(p, path)
    reopened = load_project(path)
    fresh = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    try:
        fresh._project = reopened
        fresh._build_rows(reopened, start_checks=False)
        result = SimpleNamespace(receipt={}, hits=[
            TextOccurrence("stable-90", 1000, "古龙", "骨龙", (0, 2), source="local_confirmed"),
            TextOccurrence("stable-90", 1000, "火龙", "火笼", (3, 5), source="local_review")])
        fresh._show_result(result, reopened, False, {cue.id: cue.text for cue in reopened.cues})
        row = fresh._by_id["stable-90"]
        assert len(row["issues"]) == 2 and all(i["ignored"] for i in row["issues"])
        assert fresh._row_state(row) == (False, False, False)  # ignore does not modify text
    finally:
        fresh.shutdown()
        fresh.deleteLater()
