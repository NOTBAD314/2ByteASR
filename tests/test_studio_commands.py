import copy

from PySide6.QtGui import QUndoStack

from twobyteasr.timeline.studio_commands import (
    AssignSpeakerCommand,
    MergeSpeakerCommand,
    SetSpeakerCommand,
    SetCueFieldsCommand,
    SetCuePresentationCommand,
    SetCuesPresentationCommand,
    SetCueTranslationCommand,
    delete_cues_command,
    merge_cues_command,
    split_cue_command,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject


def _project():
    return SubtitleProject(
        media=StudioMedia(path="D:/game.mp4"),
        cues=[
            StudioCue("a", 0, 1000, "第一句", original_text="第一句", evidence_refs=["p1"]),
            StudioCue("b", 1100, 2100, "第二句", original_text="第二句", evidence_refs=["p2"]),
        ],
    )


def test_text_ai_style_and_timing_share_one_undo_stack():
    project = _project()
    stack = QUndoStack()
    stack.push(SetCueFieldsCommand(project, "a", {"text": "AI 修正"}, "AI Apply"))
    stack.push(SetCueFieldsCommand(project, "a", {"style_id": "game"}, "Change style"))
    stack.push(SetCueFieldsCommand(project, "a", {"start_ms": 50}, "Adjust timing"))

    assert (project.cues[0].text, project.cues[0].style_id, project.cues[0].start_ms) == (
        "AI 修正",
        "game",
        50,
    )
    stack.undo()
    stack.undo()
    stack.undo()
    assert (project.cues[0].text, project.cues[0].style_id, project.cues[0].start_ms) == (
        "第一句",
        "default",
        0,
    )
    stack.redo()
    assert project.cues[0].text == "AI 修正"


def test_split_merge_delete_are_reversible():
    project = _project()
    stack = QUndoStack()
    stack.push(split_cue_command(project, "a", 500, "第一", "句"))
    split_ids = [cue.id for cue in project.cues[:2]]
    assert [(cue.start_ms, cue.end_ms) for cue in project.cues[:2]] == [(0, 500), (500, 1000)]

    stack.push(merge_cues_command(project, split_ids))
    assert project.cues[0].text == "第一句"
    stack.push(delete_cues_command(project, ["b"]))
    assert len(project.cues) == 1

    stack.undo()
    assert len(project.cues) == 2
    stack.undo()
    assert len(project.cues) == 3
    stack.undo()
    assert [cue.id for cue in project.cues] == ["a", "b"]


def test_consecutive_text_edits_merge_but_keep_first_before_value():
    project = _project()
    stack = QUndoStack()
    stack.push(SetCueFieldsCommand(project, "a", {"text": "第"}, "Edit text"))
    stack.push(SetCueFieldsCommand(project, "a", {"text": "第一"}, "Edit text"))
    stack.push(SetCueFieldsCommand(project, "a", {"text": "第一句。"}, "Edit text"))

    assert stack.count() == 1
    assert project.cues[0].text == "第一句。"
    stack.undo()
    assert project.cues[0].text == "第一句"


def test_ai_presentation_apply_undoes_text_and_effect_definition_together():
    project = _project()
    stack = QUndoStack()
    effects = dict(project.effects)
    effects["ai-a"] = {"entry": {"type": "fade", "duration": 200}, "exit": {"type": "none"}}
    stack.push(
        SetCuePresentationCommand(
            project,
            "a",
            cue_changes={"text": "AI 结果", "effect_id": "ai-a"},
            effects=effects,
            text="AI Apply",
        )
    )
    assert project.cues[0].effect_id == "ai-a"
    assert "ai-a" in project.effects
    stack.undo()
    assert project.cues[0].text == "第一句"
    assert project.cues[0].effect_id == "none"
    assert "ai-a" not in project.effects


def test_translation_edits_share_undo_stack_without_schema_change():
    project = _project()
    stack = QUndoStack()
    stack.push(SetCueTranslationCommand(project, "a", "First line"))
    stack.push(SetCueTranslationCommand(project, "a", "First line edited"))

    assert stack.count() == 1
    assert project.generation_metadata["translations"]["a"] == "First line edited"
    stack.undo()
    assert "a" not in project.generation_metadata["translations"]


def test_speaker_rename_merge_and_undo_restore_exact_references_and_styles():
    project = _project()
    project.speakers = [
        StudioSpeaker("S01", "S01", "host", "#447755"),
        StudioSpeaker("S03", "S03", "guest", "#aa7755"),
    ]
    project.styles.extend([])
    project.cues[0].speaker_id = "S01"
    project.cues[0].style_id = "host"
    project.cues[1].speaker_id = "S03"
    project.cues[1].style_id = "guest"
    # Keep style IDs valid for project output even though speaker validation is independent.
    project.styles[0].id = "host"
    from twobyteasr.projects.studio_project import SubtitleStyle
    project.styles.append(SubtitleStyle(id="guest", name="Guest"))
    project.styles.append(SubtitleStyle(id="default", name="Default"))
    stack = QUndoStack()
    stack.push(SetSpeakerCommand(project, "S01", {"name": "主播"}))
    stack.push(MergeSpeakerCommand(project, "S03", "S01"))

    assert [speaker.id for speaker in project.speakers] == ["S01"]
    assert [cue.speaker_id for cue in project.cues] == ["S01", "S01"]
    assert project.cues[1].style_id == "host"
    assert project.speakers[0].name == "主播"
    stack.undo()
    assert [speaker.id for speaker in project.speakers] == ["S01", "S03"]
    assert [cue.speaker_id for cue in project.cues] == ["S01", "S03"]
    assert project.cues[1].style_id == "guest"
    stack.undo()
    assert project.speakers[0].name == "S01"


def test_assign_selected_cues_to_speaker_is_one_undo_step():
    project = _project()
    project.speakers = [StudioSpeaker("S01"), StudioSpeaker("S02")]
    project.cues[0].speaker_id = "S01"
    project.cues[1].speaker_id = "S01"
    stack = QUndoStack()
    stack.push(AssignSpeakerCommand(project, ["a", "b"], "S02"))
    assert [cue.speaker_id for cue in project.cues] == ["S02", "S02"]
    stack.undo()
    assert [cue.speaker_id for cue in project.cues] == ["S01", "S01"]


def test_bulk_presentation_change_refreshes_once_and_undoes_atomically():
    project = _project()
    stack = QUndoStack()
    changed = []
    stack.push(
        SetCuesPresentationCommand(
            project,
            ["a", "b"],
            style_id="default",
            effect_id="fade",
            effects={**project.effects, "fade": {"type": "fade", "duration": 180}},
            text="Apply style to subtitles",
            changed=lambda: changed.append("refresh"),
        )
    )

    assert [cue.effect_id for cue in project.cues] == ["fade", "fade"]
    assert changed == ["refresh"]
    stack.undo()
    assert [cue.effect_id for cue in project.cues] == ["none", "none"]
    assert changed == ["refresh", "refresh"]
    stack.redo()
    assert [cue.effect_id for cue in project.cues] == ["fade", "fade"]
    assert changed == ["refresh", "refresh", "refresh"]


def test_consecutive_bulk_presentation_changes_merge_without_losing_end_states():
    project = _project()
    stack = QUndoStack()
    original_effects = copy.deepcopy(project.effects)
    first_effects = {**project.effects, "fade": {"type": "fade", "duration": 180}}
    final_effects = {**project.effects, "fade": {"type": "fade", "duration": 260}}

    stack.push(
        SetCuesPresentationCommand(
            project,
            ["a", "b"],
            style_id="default",
            effect_id="fade",
            effects=first_effects,
            text="Apply style to subtitles",
        )
    )
    stack.push(
        SetCuesPresentationCommand(
            project,
            ["a", "b"],
            style_id="default",
            effect_id="fade",
            effects=final_effects,
            text="Apply style to subtitles",
        )
    )

    assert stack.count() == 1
    assert project.effects["fade"]["duration"] == 260
    stack.undo()
    assert [cue.effect_id for cue in project.cues] == ["none", "none"]
    assert project.effects == original_effects
    stack.redo()
    assert [cue.effect_id for cue in project.cues] == ["fade", "fade"]
    assert project.effects["fade"]["duration"] == 260
