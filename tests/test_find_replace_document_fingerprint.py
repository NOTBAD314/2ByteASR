"""Find/replace preview fence without deep-copying the project per keystroke.

2026-10-22 (report-eb10, 0.8.2): every live-search keystroke ran
``asdict(project)`` + JSON + SHA-256 on the GUI thread, 2-4 s on a 62 MB
project. The fingerprint must still catch persisted changes that bypass the
runtime revision (since the evening of 2026-10-22 evidence is hashed row by
row, reusing rows a keystroke hashed before).
"""
from dataclasses import asdict

from twobyteasr.glossary.glossary_proofread import _TextReviewBinding
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_find_replace import PreviewBinding


def _project():
    project = SubtitleProject(
        media=StudioMedia("clip.mp4", duration_ms=5000),
        cues=[StudioCue("a", 0, 1000, "原句", evidence_refs=["seg:0"])],
        asr_evidence={"seg:0": {"words": [{"text": "原句", "start_ms": 0, "end_ms": 900}], "engines": {"m": (1, 2)}}},
        generation_metadata={"translations": {"a": "line"}},
        studio_state={"zoom": 3, "playhead_ms": 10, "term_word_overrides": {"a": {"words": []}}},
    )
    project.validate()
    return project


def test_fingerprint_follows_content_and_leaves_the_project_untouched():
    import copy
    project = _project()
    before = asdict(project)
    first = PreviewBinding._document_fingerprint(project)
    assert asdict(project) == before  # view keys are removed from a copy only
    twin = copy.deepcopy(project)
    assert PreviewBinding._document_fingerprint(twin) == first
    assert _TextReviewBinding._document_fingerprint(project) != first  # without media durations
    project.studio_state["zoom"] = 9  # view state only
    assert PreviewBinding._document_fingerprint(project) == first
    # 2026-10-22: evidence is hashed row by row; any row change still shows.
    project.asr_evidence["seg:0"]["words"][0]["text"] = "改"
    assert PreviewBinding._document_fingerprint(project) != first
    project.asr_evidence["seg:0"]["words"][0]["text"] = "原句"
    assert PreviewBinding._document_fingerprint(project) == first


def test_keystrokes_trust_hashed_rows_and_apply_rereads_them():
    project = _project()
    revision = state_for(project).revision
    binding = PreviewBinding.capture(project)
    project.asr_evidence["seg:0"]["engines"]["m"] = (3, 4)  # in place, no new revision
    # A keystroke in the same revision reuses the memo; applying re-reads every row.
    assert PreviewBinding._cached_document_fingerprint(project, revision) == binding.document_fingerprint
    assert not binding.matches(project)


def test_live_search_hashes_once_per_revision(monkeypatch):
    project = _project()
    calls = []
    original = PreviewBinding._document_fingerprint.__func__

    def counted(cls, value, **kwargs):
        calls.append(cls)
        return original(cls, value, **kwargs)
    monkeypatch.setattr(PreviewBinding, "_document_fingerprint", classmethod(counted))
    first = PreviewBinding.capture(project)
    for _ in range(5):
        assert PreviewBinding.capture(project).document_fingerprint == first.document_fingerprint
    assert len(calls) == 1
    revision = state_for(project).revision
    PreviewBinding._cached_document_fingerprint(project, revision + 1)
    assert len(calls) == 2


def test_change_without_revision_makes_preview_stale_then_recovers():
    project = _project()
    PreviewBinding.capture(project)
    project.studio_state["term_word_overrides"]["a"]["words"].append({"text": "x"})
    stale = PreviewBinding.capture(project)  # memo of the earlier state
    assert not stale.matches(project)  # apply refuses: never applies on a changed document
    fresh = PreviewBinding.capture(project)  # matches() refreshed the memo
    assert fresh.matches(project)
    project.media.duration_ms = 6000
    assert not fresh.matches(project)
