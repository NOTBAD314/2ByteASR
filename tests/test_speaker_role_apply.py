"""2026-10-18: one candidate label's role applies at once and touches only its captions."""
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.speaker_organization import apply_new_project_policy
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.speaker_recovery import (
    apply_candidate_role,
    candidate_destination,
    candidate_snapshot,
    load_candidate_snapshot,
    representative_row,
)

ROWS = [
    {"speaker": "API_S01", "start": 0.0, "end": 2.0, "text": "大家好今天打艾尔登法环", "utterance_id": 1},
    {"speaker": "API_S02", "start": 2.5, "end": 4.0, "text": "左边宝箱还没开", "utterance_id": 2},
    {"speaker": "API_S01", "start": 4.5, "end": 7.0, "text": "这个Boss第二阶段会跳", "utterance_id": 3},
    {"speaker": "API_S03", "start": 7.5, "end": 8.5, "text": "获得黄金种子", "utterance_id": 4},
    {"speaker": "API_S02", "start": 9.0, "end": 10.5, "text": "你试试看打断他", "utterance_id": 5},
    {"speaker": "API_S03", "start": 11.0, "end": 12.0, "text": "圣杯瓶次数增加", "utterance_id": 6},
]


def _project():
    cues = [StudioCue(f"c{index}", round(row["start"] * 1000), round(row["end"] * 1000), row["text"],
                      speaker_id=row["speaker"]) for index, row in enumerate(ROWS)]
    project = SubtitleProject(
        media=StudioMedia("fixture.mp4", duration_ms=13_000),
        speakers=[StudioSpeaker("API_S01", "说话人 1"), StudioSpeaker("API_S02", "说话人 2"),
                  StudioSpeaker("API_S03", "说话人 3")],
        cues=cues,
    )
    snapshot = candidate_snapshot(ROWS, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    project.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(project)
    return project


def _apply(project, label, role):
    result = apply_candidate_role(project, load_candidate_snapshot(project), label, role)
    assert result is not None
    project.speakers, project.cues = result.speakers, result.cues
    project.generation_metadata, project.studio_state = result.generation_metadata, result.studio_state
    project.asr_evidence = result.asr_evidence
    return project


def _texts(project, speaker):
    return [cue.text for cue in project.cues if cue.speaker_id == speaker]


def test_new_projects_start_unconfirmed_and_same_role_is_a_no_op():
    project = _project()
    snapshot = load_candidate_snapshot(project)
    assert set(snapshot["roles"].values()) == {"unconfirmed"}
    assert apply_candidate_role(project, snapshot, "API_S01", "unconfirmed") is None


def test_game_moves_only_this_label_and_main_brings_it_back_with_name():
    project = _project()
    before_s01 = [(cue.id, cue.text) for cue in project.cues if cue.speaker_id == "API_S01"]
    next(s for s in project.speakers if s.id == "API_S02").name = "阿凯"
    _apply(project, "API_S02", "game")
    assert "API_S02" not in {s.id for s in project.speakers}
    assert _texts(project, "GAME_BACKGROUND") == ["左边宝箱还没开", "你试试看打断他"]
    assert [(cue.id, cue.text) for cue in project.cues if cue.speaker_id == "API_S01"] == before_s01
    assert load_candidate_snapshot(project)["roles"]["API_S02"] == "game"
    _apply(project, "API_S02", "main")
    assert _texts(project, "API_S02") == ["左边宝箱还没开", "你试试看打断他"]
    assert "GAME_BACKGROUND" not in {s.id for s in project.speakers}
    restored = next(s for s in project.speakers if s.id == "API_S02")
    assert restored.name == "阿凯" and restored.is_host


def test_ignore_keeps_edits_and_deletions_when_restored():
    project = _project()
    next(c for c in project.cues if c.id == "c3").text = "获得黄金种子（已校对）"
    project.cues = [c for c in project.cues if c.id != "c5"]
    _apply(project, "API_S03", "ignore")
    assert not _texts(project, "API_S03")
    assert "API_S03" not in {s.id for s in project.speakers}
    _apply(project, "API_S03", "unconfirmed")
    assert _texts(project, "API_S03") == ["获得黄金种子（已校对）"]


def test_manual_reassignment_stays_when_the_label_moves():
    project = _project()
    next(c for c in project.cues if c.id == "c2").speaker_id = "API_S02"
    _apply(project, "API_S01", "game")
    assert _texts(project, "GAME_BACKGROUND") == ["大家好今天打艾尔登法环"]
    assert "这个Boss第二阶段会跳" in _texts(project, "API_S02")
    _apply(project, "API_S01", "main")
    assert _texts(project, "API_S01") == ["大家好今天打艾尔登法环"]
    assert "这个Boss第二阶段会跳" in _texts(project, "API_S02")


def test_merge_into_another_track_and_back():
    project = _project()
    _apply(project, "API_S03", "merge:API_S01")
    assert "API_S03" not in {s.id for s in project.speakers}
    assert _texts(project, "API_S01") == ["大家好今天打艾尔登法环", "这个Boss第二阶段会跳", "获得黄金种子", "圣杯瓶次数增加"]
    roles = load_candidate_snapshot(project)["roles"]
    assert candidate_destination(roles, "API_S03", True) == "API_S01"
    with pytest.raises(ValueError):
        apply_candidate_role(project, load_candidate_snapshot(project), "API_S02", "merge:API_S03")
    _apply(project, "API_S03", "unconfirmed")
    assert _texts(project, "API_S03") == ["获得黄金种子", "圣杯瓶次数增加"]
    assert len(_texts(project, "API_S01")) == 2


def test_confirmation_flags_follow_roles():
    project = _project()
    for label, role in (("API_S01", "main"), ("API_S02", "game"), ("API_S03", "ignore")):
        _apply(project, label, role)
    state = project.generation_metadata["speaker_recovery"]
    assert state["needs_confirmation"] is False and state["confirmed_by"] == "user"
    assert [s.id for s in project.speakers] == ["API_S01", "GAME_BACKGROUND"]
    assert project.studio_state["speaker_track_order"] == ["API_S01", "GAME_BACKGROUND"]
    project.validate()


def _slow_representative(snapshot, label):
    rows = [row for row in snapshot["raw_segments"] if str(row.get("speaker") or "S00") == label]
    def score(row):
        overlap = sum(max(0, min(row["end"], other["end"]) - max(row["start"], other["start"]))
                      for other in snapshot["raw_segments"] if other.get("speaker") != label)
        return (row["end"] - row["start"] - overlap, row["end"] - row["start"])
    return max(rows, key=score)


def test_fast_representative_matches_the_exact_overlap_rule():
    generator = random.Random(7)
    rows = []
    for index in range(600):
        start = generator.uniform(0, 3600)
        rows.append({"speaker": f"S0{generator.randint(1, 4)}", "start": start,
                     "end": start + generator.uniform(0.3, 9.0), "text": f"句子{index}"})
    snapshot = {"raw_segments": rows}
    for label in ("S01", "S02", "S03", "S04"):
        assert representative_row(snapshot, label) is _slow_representative(snapshot, label)
