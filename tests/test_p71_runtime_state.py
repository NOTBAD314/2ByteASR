"""P7.1A runtime-state, transaction, persistence and hard-gate regressions."""

from __future__ import annotations

import copy
import os
from dataclasses import FrozenInstanceError

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import twobyteasr.timeline.studio_edit_sequence as edit_sequence_module
from twobyteasr.timeline.studio_edit_commands import razor_video_command, replace_candidates_command
from twobyteasr.timeline.studio_edit_sequence import (
    EditSequence,
    HighlightCandidate,
    ensure_edit_sequence,
    runtime_of,
    sequence_of,
    timeline_duration_ms,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    load_project,
    save_autosave,
    save_project,
)
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _project(duration_ms: int = 60_000) -> SubtitleProject:
    project = SubtitleProject(
        media=StudioMedia(path="D:/p71-fixture.mp4", duration_ms=duration_ms),
        cues=[
            StudioCue("a", 0, 1_500, "alpha"),
            StudioCue("b", 2_000, 3_500, "beta"),
        ],
    )
    ensure_edit_sequence(project)
    return project


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('field,value,dirty', [
    ('style_id', 'updated-style', DirtyDomain.CUE_STYLE),
    ('text', '人工修改保留', DirtyDomain.CUE_CONTENT),
])
def test_projected_playback_cue_refreshes_after_content_or_style_edit(field, value, dirty):
    from twobyteasr.timeline.studio_edit_sequence import VideoSegment, store_sequence
    project = _project()
    store_sequence(project, EditSequence(source_path=project.media.path, source_duration_ms=60_000,
        segments=[VideoSegment('cut', project.media.path, 0, 10_000, 1_000, 11_000)]))
    state = state_for(project)
    before = state.cues_at(1_200)[0]
    assert before is not project.cues[0]
    with state.transaction(project, action_id='edit_projected_caption', dirty=dirty,
                           affected_cue_ids=('a',)):
        setattr(project.cues[0], field, value)
    after = state.cues_at(1_200)[0]
    assert getattr(after, field) == value
    assert (after.start_ms, after.end_ms) == (1_000, 2_500)
    assert state.cue_by_id[after.id] is project.cues[0]


def test_runtime_read_is_stable_and_never_parses_serializes_validates_or_stores(monkeypatch):
    project = _project()
    canonical = sequence_of(project)
    persisted_before = copy.deepcopy(project.edit_sequence)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read crossed the persisted serialization boundary")

    monkeypatch.setattr(EditSequence, "from_dict", classmethod(forbidden))
    monkeypatch.setattr(EditSequence, "to_dict", forbidden)
    monkeypatch.setattr(EditSequence, "validate", forbidden)
    monkeypatch.setattr(edit_sequence_module, "store_sequence", forbidden)

    assert sequence_of(project) is canonical
    assert timeline_duration_ms(project) == 60_000
    assert runtime_of(project).segment_at(12_000) is canonical.segments[0]
    assert project.edit_sequence == persisted_before


def test_nested_transaction_commits_one_immutable_combined_delta():
    project = _project()
    state = state_for(project)
    rows = []
    state.subscribe(rows.append)
    before = state.commit_count

    with state.transaction(
        project,
        action_id="outer_edit",
        dirty=DirtyDomain.CUE_CONTENT | DirtyDomain.AUTOSAVE,
        affected_cue_ids=("a",),
    ):
        project.cues[0].text = "outer"
        with state.transaction(
            project,
            action_id="nested_timing",
            dirty=(
                DirtyDomain.CUE_TIMING
                | DirtyDomain.TIMELINE_INDEX
                | DirtyDomain.TIMELINE_PIXELS
            ),
            affected_cue_ids=("a",),
        ):
            project.cues[0].start_ms = 100
            project.cues[0].end_ms = 1_600

    assert state.commit_count == before + 1
    assert len(rows) == 1
    delta = rows[0]
    assert delta.action_id == "outer_edit"
    assert delta.touches(DirtyDomain.CUE_CONTENT | DirtyDomain.CUE_TIMING)
    assert delta.affected_cue_ids == frozenset({"a"})
    with pytest.raises(FrozenInstanceError):
        delta.revision = 999


def test_transaction_exception_rolls_back_sequence_and_scoped_cues():
    project = _project()
    state = state_for(project)
    sequence_before = copy.deepcopy(sequence_of(project))
    cues_before = copy.deepcopy(project.cues)
    commits_before = state.commit_count

    with pytest.raises(RuntimeError, match="abort"):
        with state.transaction(
            project,
            action_id="failing_edit",
            dirty=(
                DirtyDomain.SEQUENCE_STRUCTURE
                | DirtyDomain.CUE_CONTENT
                | DirtyDomain.TIMELINE_INDEX
            ),
            affected_cue_ids=("a",),
        ):
            sequence_of(project).segments.clear()
            project.cues[0].text = "partial"
            raise RuntimeError("abort")

    assert sequence_of(project) == sequence_before
    assert project.cues == cues_before
    assert state.commit_count == commits_before
    assert state._active is None


def test_razor_undo_redo_each_commit_once_without_read_serialization(monkeypatch):
    project = _project()
    sequence_of(project).video_track_locked = False
    state = state_for(project)
    deltas = []
    state.subscribe(deltas.append)
    persisted_before = copy.deepcopy(project.edit_sequence)
    counts = {"from_dict": 0, "to_dict": 0, "validate": 0, "store": 0}

    original_from_dict = EditSequence.from_dict.__func__
    original_to_dict = EditSequence.to_dict
    original_validate = EditSequence.validate
    original_store = edit_sequence_module.store_sequence

    def counted_from_dict(cls, *args, **kwargs):
        counts["from_dict"] += 1
        return original_from_dict(cls, *args, **kwargs)

    def counted_to_dict(self, *args, **kwargs):
        counts["to_dict"] += 1
        return original_to_dict(self, *args, **kwargs)

    def counted_validate(self, *args, **kwargs):
        counts["validate"] += 1
        return original_validate(self, *args, **kwargs)

    def counted_store(*args, **kwargs):
        counts["store"] += 1
        return original_store(*args, **kwargs)

    monkeypatch.setattr(EditSequence, "from_dict", classmethod(counted_from_dict))
    monkeypatch.setattr(EditSequence, "to_dict", counted_to_dict)
    monkeypatch.setattr(EditSequence, "validate", counted_validate)
    monkeypatch.setattr(edit_sequence_module, "store_sequence", counted_store)

    cue_list_identity = project.cues
    command = razor_video_command(project, 10_000)
    assert command.before_cues is None
    assert command.after_cues is None
    before = state.commit_count
    command.redo()
    assert state.commit_count == before + 1
    command.undo()
    assert state.commit_count == before + 2
    command.redo()
    assert state.commit_count == before + 3
    assert counts["from_dict"] == 0
    assert counts["to_dict"] == 0
    assert counts["store"] == 0
    assert counts["validate"] == 3  # one relevant validation per commit
    assert project.edit_sequence == persisted_before
    assert len(deltas) == 3
    assert all(delta.dirty & DirtyDomain.SEQUENCE_STRUCTURE for delta in deltas)
    assert all(not delta.dirty & DirtyDomain.CLIP_STATUS for delta in deltas)
    assert all(not delta.dirty & DirtyDomain.NATIVE_SUBTITLE for delta in deltas)
    assert all(not delta.dirty & DirtyDomain.QC for delta in deltas)
    assert project.cues is cue_list_identity


def test_candidate_replacement_still_publishes_clip_status_delta():
    project = _project()
    state = state_for(project)
    deltas = []
    state.subscribe(deltas.append)
    candidate = HighlightCandidate(
        id="candidate-1",
        title="候选",
        source_in_ms=1_000,
        source_out_ms=12_000,
    )

    replace_candidates_command(project, [candidate]).redo()

    assert len(deltas) == 1
    assert deltas[0].dirty & DirtyDomain.CLIP_STATUS


def test_save_autosave_and_reopen_are_explicit_runtime_persistence_boundaries(tmp_path):
    project = _project()
    sequence_of(project).video_track_locked = False
    razor_video_command(project, 10_000).redo()
    assert len(project.edit_sequence["segments"]) == 1  # persisted schema is still old
    assert len(sequence_of(project).segments) == 2

    path = save_project(project, tmp_path / "runtime.2byteproj")
    assert len(project.edit_sequence["segments"]) == 2
    reopened = load_project(path)
    assert len(sequence_of(reopened).segments) == 2
    assert sequence_of(reopened) is sequence_of(reopened)

    sequence_of(project).video_track_locked = True
    autosave = save_autosave(project, path, base=tmp_path / "local")
    recovered = load_project(autosave)
    assert sequence_of(recovered).video_track_locked is True


def test_first_save_materializes_legacy_identity_sequence_with_locked_video(tmp_path):
    project = SubtitleProject(
        media=StudioMedia(path="D:/first-save.mp4", duration_ms=12_000),
        cues=[StudioCue("a", 0, 1_000, "first")],
    )

    path = save_project(project, tmp_path / "first-save.2byteproj")
    reopened = load_project(path)
    sequence = sequence_of(reopened)

    assert sequence.video_track_locked is True
    assert len(sequence.segments) == 1
    assert sequence.segments[0].source_in_ms == 0
    assert sequence.segments[0].source_out_ms == 12_000


def test_direct_schema_assignment_invalidates_runtime_compatibly():
    project = _project()
    first = sequence_of(project)
    payload = copy.deepcopy(project.edit_sequence)
    payload["video_track_locked"] = False
    project.edit_sequence = payload
    second = sequence_of(project)
    assert second is not first
    assert second.video_track_locked is False


def test_selection_commit_has_no_persistence_autosave_or_timeline_reindex(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    project = _project()
    page.project = project
    page.session._cue_lookup = {cue.id: cue for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._autosave_timer.stop()
    reindexes = 0
    original_reindex = page.timeline.reindex_project

    def counted_reindex():
        nonlocal reindexes
        reindexes += 1
        return original_reindex()

    monkeypatch.setattr(page.timeline, "reindex_project", counted_reindex)
    persisted_before = copy.deepcopy(project.edit_sequence)
    before = page.session.runtime.commit_count
    page.select_cue("b")

    assert page.session.runtime.commit_count == before + 1
    assert page.session.runtime.last_delta.dirty & DirtyDomain.CUE_SELECTION
    assert not page.session.runtime.last_delta.dirty & DirtyDomain.AUTOSAVE
    assert project.edit_sequence == persisted_before
    assert not page._autosave_timer.isActive()
    assert reindexes == 0
    assert page.session.runtime.subscriber_errors == []
    page.close_page()


def test_text_commit_is_one_scoped_transaction_without_timeline_reindex(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    project = _project()
    page.project = project
    page.session._cue_lookup = {cue.id: cue for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page.select_cue("a")
    page._autosave_timer.stop()
    reindexes = 0
    original_reindex = page.timeline.reindex_project

    def counted_reindex():
        nonlocal reindexes
        reindexes += 1
        return original_reindex()

    monkeypatch.setattr(page.timeline, "reindex_project", counted_reindex)
    persisted_before = copy.deepcopy(project.edit_sequence)
    before = page.session.runtime.commit_count

    assert page.cue_controller.set_text("a", "scoped text") is True

    delta = page.session.runtime.last_delta
    assert page.session.runtime.commit_count == before + 1
    assert delta.dirty & DirtyDomain.CUE_CONTENT
    assert delta.affected_cue_ids == frozenset({"a"})
    assert not delta.dirty & DirtyDomain.TIMELINE_INDEX
    assert project.edit_sequence == persisted_before
    assert reindexes == 0
    assert page.session.runtime.subscriber_errors == []
    page.close_page()
