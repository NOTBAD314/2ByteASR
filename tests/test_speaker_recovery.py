import copy
import json
import os
from dataclasses import asdict
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.recognition.speaker_recovery import candidate_snapshot, candidate_statistics, load_candidate_snapshot, rebuild_selected_speakers, representative_interval, selected_display_mapping, recovery_preview
from twobyteasr.timeline.studio_commands import RecoverSpeakersCommand
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project, save_autosave


def fixture_project():
    raw = [dict(speaker=label, start=float(n*10+offset), end=float(n*10+offset+2), text=f"{label}的原始文字")
           for label, offset in (("S02", 0), ("S03", 3), ("S06", 6)) for n in range(3)]
    project = SubtitleProject(media=StudioMedia("", duration_ms=30000), speakers=[StudioSpeaker("S02")],
                              cues=[StudioCue("edited", 0, 2000, "已有的校对文字", "S02")])
    project.validate()
    state = candidate_snapshot(raw, ["S02"], 0)
    project.generation_metadata["speaker_recovery"] = state
    return project, state


def test_auto_requires_confirmation_without_claiming_an_identity():
    project, state = fixture_project()
    assert state["needs_confirmation"] and state["expected_speakers"] == 0
    assert state["roles"] == {"S02": "game", "S03": "game", "S06": "game"}
    result = rebuild_selected_speakers(project, state, {"S02": "main", "S03": "unconfirmed", "S06": "unconfirmed"})
    assert result.generation_metadata["speaker_recovery"]["unconfirmed_candidates"] == ["S03", "S06"]
    assert not result.generation_metadata["speaker_recovery"]["needs_confirmation"]


@pytest.mark.parametrize("second", ["S03", "S06"])
def test_user_choice_restores_only_two_tracks_and_reuses_existing_text(second):
    project, state = fixture_project()
    raw_before = copy.deepcopy(state["raw_segments"])
    roles = {label: "main" if label in {"S02", second} else "game" for label in state["roles"]}
    result = rebuild_selected_speakers(project, state, roles)
    assert {s.id for s in result.speakers} == {"S02", second, "GAME_BACKGROUND"}
    assert {c.speaker_id for c in result.cues} == {"S02", second, "GAME_BACKGROUND"}
    assert asdict(result.cues[0]) == asdict(project.cues[0])
    assert "".join(c.text for c in result.cues if c.speaker_id == second) == "".join(r["text"] for r in raw_before if r["speaker"] == second)
    assert result.generation_metadata["speaker_recovery"]["raw_segments"] == raw_before
    assert state["raw_segments"] == raw_before


def test_manual_labels_override_expected_count_hint():
    project, state = fixture_project()
    state["expected_speakers"] = 2
    result = rebuild_selected_speakers(project, state, {"S02": "main", "S03": "game", "S06": "ignore"})
    assert {s.id for s in result.speakers} == {"S02","GAME_BACKGROUND"}


def test_confirmed_s03_applies_while_s06_remains_unconfirmed():
    project, state = fixture_project()
    roles = dict(S02="main", S03="main", S06="unconfirmed")
    result = rebuild_selected_speakers(project, state, roles)
    assert {c.speaker_id for c in result.cues} == {"S02", "S03","GAME_BACKGROUND"}
    assert {s.id: s.name for s in result.speakers} == {"S02": "S02", "S03": "S03","GAME_BACKGROUND":"游戏背景声"}
    assert result.generation_metadata["speaker_recovery"]["roles"]["S06"] == "unconfirmed"
    assert recovery_preview(project, state, roles) == {"S02": 1, "S03": 3,"GAME_BACKGROUND":3}


def test_manual_short_low_support_label_is_never_filtered():
    project, state = fixture_project()
    state["raw_segments"] = [row for row in state["raw_segments"] if row["speaker"] != "S03"]
    state["raw_segments"].append(dict(speaker="S03", start=3., end=3.2, text="是"))
    result = rebuild_selected_speakers(project, state, dict(state["roles"], S03="main"))
    assert [c.text for c in result.cues if c.speaker_id == "S03"] == ["是"]


def test_display_ranking_and_custom_name_survive_round_trip(tmp_path):
    project, state = fixture_project()
    state["raw_segments"].append(dict(speaker="S03", start=33., end=37., text="更长发言"))
    project.speakers[0].name = "主播甲"
    roles = dict(state["roles"], S02="main", S03="main")
    result = rebuild_selected_speakers(project, state, roles)
    assert selected_display_mapping(state, roles, result) == {"S02": "主播甲", "S03": "S03"}
    assert next(s for s in result.speakers if s.id == "S02").name == "主播甲"
    reopened = load_project(save_project(result, tmp_path / "named.2byteproj"))
    again = rebuild_selected_speakers(reopened, reopened.generation_metadata["speaker_recovery"], roles)
    assert {s.id:s.name for s in again.speakers} == {"S02":"主播甲", "S03":"S03","GAME_BACKGROUND":"游戏背景声"}
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    artifacts = export_subtitle_artifacts(again, tmp_path, "双轨", SubtitleExportOptions(speaker_mode="per_speaker"))
    assert {a.speaker_id:a.path.name for a in artifacts} == {"S03":"双轨_S03.srt", "S02":"双轨_主播甲.srt","GAME_BACKGROUND":"双轨_游戏背景声.srt"}


def test_failed_refresh_rolls_back_current_project_atomically():
    app = QApplication.instance() or QApplication([])
    project, state = fixture_project()
    before = copy.deepcopy(project.to_dict())
    result = rebuild_selected_speakers(project, state, dict(state["roles"], S03="main"))
    def fail():
        raise RuntimeError("test refresh failure")
    command = RecoverSpeakersCommand(project, result, fail)
    stack = QUndoStack()
    stack.push(command)
    assert "test refresh failure" in command.error
    assert project.to_dict() == before
    assert stack.count() == 0


def test_undo_redo_save_and_autosave_preserve_speakers_and_raw_evidence(tmp_path):
    app = QApplication.instance() or QApplication([])
    project, state = fixture_project()
    result = rebuild_selected_speakers(project, state, {"S02": "main", "S03": "main", "S06": "game"})
    stack = QUndoStack()
    stack.push(RecoverSpeakersCommand(project, result))
    assert len(project.speakers) == 3
    stack.undo()
    assert len(project.speakers) == 1 and len(project.generation_metadata["speaker_recovery"]["raw_segments"]) == 9
    stack.redo()
    path = save_project(project, tmp_path / "recovery.2byteproj")
    reopened = load_project(path)
    assert len(reopened.speakers) == 3 and len(reopened.cues) == 7
    auto = save_autosave(project, project_path=path, base=tmp_path / "autosave")
    assert len(load_project(auto).speakers) == 3


def test_preview_is_bounded_and_candidate_statistics_keep_all_intervals():
    _, state = fixture_project()
    for item in candidate_statistics(state["raw_segments"]):
        assert item["segments"] == 3 and item["seconds"] == 6
        assert len(item["intervals"]) == 3
        a, b = representative_interval(state, item["label"])
        assert 2000 <= b-a <= 4000


def test_wrong_media_cache_rejected_without_mutation(tmp_path):
    project, _ = fixture_project()
    project.generation_metadata.clear()
    (tmp_path / "moss.json").write_text(json.dumps({"identity": {"path": "wrong.mp4"}, "data": {"segments": []}}))
    with pytest.raises(ValueError, match="不属于"):
        load_candidate_snapshot(project, tmp_path)
    assert project.generation_metadata == {}


def test_long_restored_display_split_does_not_invent_acoustic_bounds():
    project, state = fixture_project()
    state["raw_segments"] = [dict(speaker="S03", start=3., end=12., text="这是一段需要本地拆分但原始声学区间必须保留的文字")]
    state["roles"] = {"S03": "main"}
    recovered = rebuild_selected_speakers(project, state, {"S03": "main"})
    assert len(recovered.cues) == 2
    assert "".join(cue.text for cue in recovered.cues) == state["raw_segments"][0]["text"]
    for cue in recovered.cues:
        evidence = recovered.asr_evidence[cue.evidence_refs[0]]
        assert (evidence["acoustic_start_ms"], evidence["acoustic_end_ms"]) == (3000, 12000)
        assert evidence["display_split_estimated"] and evidence["review_required"]
