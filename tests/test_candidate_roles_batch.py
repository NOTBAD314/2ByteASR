"""2026-11-12 speaker board: several label roles in one undoable result."""
import pytest
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.speaker_organization import apply_new_project_policy
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.recognition.speaker_recovery import (apply_candidate_role, apply_candidate_roles, candidate_snapshot,
                                                     load_candidate_snapshot)
from twobyteasr.timeline.studio_commands import SetCandidateRoleCommand

ROWS = [
    {"speaker": "API_S01", "start": 0.0, "end": 2.0, "text": "一", "utterance_id": 1},
    {"speaker": "API_S02", "start": 2.5, "end": 4.0, "text": "二", "utterance_id": 2},
    {"speaker": "API_S03", "start": 4.5, "end": 6.0, "text": "三", "utterance_id": 3},
    {"speaker": "API_S04", "start": 6.5, "end": 8.0, "text": "四", "utterance_id": 4},
]


def _project():
    cues = [StudioCue(f"c{i}", round(r["start"] * 1000), round(r["end"] * 1000), r["text"], speaker_id=r["speaker"])
            for i, r in enumerate(ROWS)]
    project = SubtitleProject(media=StudioMedia("fixture.mp4", duration_ms=9_000),
                              speakers=[StudioSpeaker(f"API_S0{i}", f"说话人 {i}") for i in range(1, 5)], cues=cues)
    snapshot = candidate_snapshot(ROWS, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    project.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(project)
    return project


def test_group_merge_is_one_result_and_each_label_keeps_its_role():
    project = _project()
    before = [(c.id, c.text, c.start_ms, c.end_ms) for c in project.cues]
    result = apply_candidate_roles(project, load_candidate_snapshot(project),
                                   [(label, "merge:API_S02") for label in ("API_S01", "API_S03", "API_S04")])
    assert [s.id for s in result.speakers] == ["API_S02"]
    assert {c.speaker_id for c in result.cues} == {"API_S02"}
    assert [(c.id, c.text, c.start_ms, c.end_ms) for c in result.cues] == before
    roles = result.generation_metadata["speaker_recovery"]["roles"]
    assert roles == {"API_S01": "merge:API_S02", "API_S02": "unconfirmed",
                     "API_S03": "merge:API_S02", "API_S04": "merge:API_S02"}
    assert [s.id for s in project.speakers] == ["API_S01", "API_S02", "API_S03", "API_S04"]
    stack = QUndoStack()
    stack.push(SetCandidateRoleCommand(project, result))
    assert [s.id for s in project.speakers] == ["API_S02"]
    stack.undo()
    assert [s.id for s in project.speakers] == ["API_S01", "API_S02", "API_S03", "API_S04"]
    # A merged label splits back on its own.
    split = apply_candidate_role(result, result.generation_metadata["speaker_recovery"], "API_S03", "unconfirmed")
    assert sorted(s.id for s in split.speakers) == ["API_S02", "API_S03"]


def test_game_for_several_labels_and_unchanged_roles_are_skipped():
    project = _project()
    snapshot = load_candidate_snapshot(project)
    result = apply_candidate_roles(project, snapshot, [("API_S03", "game"), ("API_S04", "game")])
    assert [s.id for s in result.speakers] == ["API_S01", "API_S02", "GAME_BACKGROUND"]
    assert apply_candidate_roles(project, snapshot, [("API_S01", "unconfirmed")]) is None


def test_invalid_target_raises_and_leaves_project():
    project = _project()
    with pytest.raises(ValueError):
        apply_candidate_roles(project, load_candidate_snapshot(project), [("API_S01", "merge:API_S01")])
    assert len(project.speakers) == 4
