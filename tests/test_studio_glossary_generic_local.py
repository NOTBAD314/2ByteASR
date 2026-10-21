"""Generic confirmed aliases through the real local review and apply services."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

# Install the profile boundary before any Qt or product module import, including
# when this file is collected without scripts/run_isolated_tests.py.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "TWOBYTEASR_TEST_ROOT",
    str(Path(__file__).resolve().parents[1] / "tmp" / "real-repair-20261006"
        / "glossary" / ("generic-local-standalone-" + uuid.uuid4().hex)),
)
os.environ.setdefault(
    "TWOBYTEASR_STARTUP_TRACE",
    str(Path(os.environ["TWOBYTEASR_TEST_ROOT"]) / "startup-trace.jsonl"),
)
from twobyteasr.test_isolation import install

install()

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_find_replace import PreviewBinding, apply_occurrences
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, SubtitleProject, load_project, save_project,
)
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_text_tools import values_from_occurrences
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry


@pytest.fixture
def no_cloud(monkeypatch):
    import subtitle_core  # Initialize the legacy facade before its re-exports.
    import twobyteasr.providers.asr_provider_snapshot as providers
    import twobyteasr.subtitle_rules.polishing as polishing

    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("provider-or-polishing")
        raise AssertionError("use_ai=False must not resolve or call a provider")

    monkeypatch.setattr(providers, "resolve_provider_snapshot", forbidden)
    monkeypatch.setattr(polishing, "call_correction_api", forbidden)
    return calls


def snapshot(term, revision):
    return GlossarySnapshot((GlossaryLibrary(
        "generic-local-library", "瓦罗兰特", revision, terms=(term,),
        profile_json=json.dumps({"_content_domain": {
            "id": "v", "name": "瓦罗兰特", "source": "saved_library_game",
        }}),
    ),))


def test_generic_confirmed_alias_current_baseline_revision_and_single_undo(
    no_cloud, tmp_path,
):
    app = QApplication.instance() or QApplication([])
    current_text = "这次Borlin守住，随后Borlin撤回"
    original_asr = "Borlin守住"
    old_snapshot = snapshot(TermEntry("PreviousPlayer", category="选手ID"), "1")
    current_snapshot = snapshot(
        TermEntry("BerLIN", ("Borlin",), category="选手ID"), "2",
    )
    cue = StudioCue(
        "generic-cue", 2000, 4500, current_text, original_text=original_asr,
        speaker_id="S01", evidence_refs=["original-evidence"],
        transform={"x": 0.2, "y": 0.7, "scale": 1.15},
    )
    project = SubtitleProject(
        media=StudioMedia(path="owned-generic-fixture.mp4"), cues=[cue],
        glossary_ids=["generic-local-library"],
        generation_metadata={"terminology_snapshot": old_snapshot.to_dict()},
        asr_evidence={"original-evidence": {
            "moss_text": original_asr, "primary_source": "MOSS",
            "words": [{"text": "Borlin", "start_ms": 2100, "end_ms": 2700},
                      {"text": "守住", "start_ms": 2700, "end_ms": 3300}],
        }},
    )
    project.validate()
    before = copy.deepcopy(project)
    binding = PreviewBinding.capture(project)
    baseline_revision = state_for(project).revision

    preview = preview_glossary_correction(
        project, [cue.id], current_snapshot, {}, use_ai=False,
    )
    receipt = preview.receipt
    row = receipt["segments"][0]
    final_text = "这次BerLIN守住，随后BerLIN撤回"
    assert project == before
    assert binding.matches(project)
    assert state_for(project).revision == baseline_revision
    assert receipt["mode"] == "current_committed_selected_libraries"
    assert receipt["snapshot"]["libraries"][0]["revision"] == "2"
    assert receipt["parent_snapshot_digest"] == old_snapshot.digest
    assert receipt["snapshot_summary"]["snapshot_digest"] == current_snapshot.digest
    assert receipt["ai_requested"] is False and receipt["provider"] is None
    assert receipt["asr_run"] is False and receipt["web_search_run"] is False
    assert receipt["request_errors"] == [] and no_cloud == []
    assert row["original_baseline"] == current_text
    assert row["original_asr"] == original_asr
    assert row["local_draft"] == row["ai_draft"] == row["final_text"] == final_text
    assert receipt["local_normalization_count"] == 2
    assert receipt["proposed_changes"] == receipt["automatic_changes"] == 2
    assert len(preview.hits) == 2
    assert all(hit.source == "local_confirmed" and hit.default_selected
               for hit in preview.hits)
    assert all(hit.original == "Borlin" and hit.replacement == "BerLIN"
               for hit in preview.hits)
    assert len(row["final_diff"]) == 2
    assert values_from_occurrences(project, preview.hits) == {cue.id: final_text}
    diagnostic = Path(receipt["diagnostic_path"]).resolve()
    assert diagnostic.is_relative_to(Path(os.environ["TWOBYTEASR_TEST_ROOT"]).resolve())
    assert diagnostic.is_file()

    page = SimpleNamespace(
        session=SimpleNamespace(project=project, undo_stack=QUndoStack()),
        _changed=lambda: None,
    )
    assert apply_occurrences(
        page, preview.hits, title="确认通用别名", binding=binding,
        glossary_ids=["generic-local-library"], review_receipt=receipt,
    ) == (2, 1)
    assert project.cues[0].text == final_text
    assert state_for(project).revision == baseline_revision + 1
    assert page.session.undo_stack.count() == 1
    assert not binding.matches(project)
    # An already consumed preview cannot silently apply again.
    assert apply_occurrences(
        page, preview.hits, title="过期预览", binding=binding,
        glossary_ids=["generic-local-library"], review_receipt=receipt,
    ) == (0, 0)
    assert page.session.undo_stack.count() == 1
    assert project.asr_evidence == before.asr_evidence
    assert project.cues[0].original_text == original_asr
    assert project.cues[0].transform == before.cues[0].transform
    assert (project.cues[0].start_ms, project.cues[0].end_ms,
            project.cues[0].speaker_id) == (2000, 4500, "S01")
    applied = project.generation_metadata["glossary_review_jobs"][-1]
    assert applied["applied_changes"] == 2
    assert applied["applied_texts"] == {cue.id: final_text}

    page.session.undo_stack.undo()
    assert state_for(project).revision == baseline_revision + 2
    assert project.cues == before.cues
    assert project.asr_evidence == before.asr_evidence
    assert project.generation_metadata == before.generation_metadata
    assert project.studio_state == before.studio_state
    page.session.undo_stack.redo()
    assert state_for(project).revision == baseline_revision + 3
    assert project.cues[0].text == final_text
    assert page.session.undo_stack.count() == 1
    target = tmp_path / "generic-local.2byteproj"
    save_project(project, target)
    reopened = load_project(target)
    assert reopened.cues[0].text == final_text
    assert reopened.cues[0].original_text == original_asr
    assert reopened.asr_evidence == before.asr_evidence
    assert reopened.cues[0].transform == before.cues[0].transform
    assert no_cloud == []


def test_animation_context_does_not_use_confirmed_player_alias(no_cloud):
    QApplication.instance() or QApplication([])
    project = SubtitleProject(
        media=StudioMedia(path="owned-animation-fixture.mp4"),
        cues=[StudioCue("animation-cue", 1000, 3000,
                       "小时候喜欢看奥特曼动画", original_text="小时候喜欢看奥特曼动画",
                       speaker_id="S01")],
        glossary_ids=["generic-local-library"],
    )
    project.validate()
    before = copy.deepcopy(project)
    current_snapshot = snapshot(
        TermEntry("autumn", ("奥特曼",), category="选手ID"), "3",
    )
    preview = preview_glossary_correction(
        project, ["animation-cue"], current_snapshot, {}, use_ai=False,
    )
    row = preview.receipt["segments"][0]
    assert project == before
    assert not preview.hits
    assert preview.receipt["local_normalization_count"] == 0
    assert row["original_baseline"] == row["local_draft"] == row["final_text"] == before.cues[0].text
    assert row["final_diff"] == []
    assert preview.receipt["ai_requested"] is False
    assert preview.receipt["request_errors"] == []
    assert no_cloud == []
