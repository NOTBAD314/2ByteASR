"""Batch-replace word overrides follow their caption when it moves.

A case-only/deletion-only replacement stores the measured words of the edited
caption under studio_state['term_word_overrides'] on the project clock, and
cue_words prefers them over the caption receipt. Moving the caption (group
move, ripple, timing edit) must carry them along, or the razor reports
"后段没有文字"/cuts by the moved distance while still calling it word timing.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.cue_word_alignment import cue_words
from twobyteasr.studio_caption_timeline import ensure_independent_captions, shift_caption
from twobyteasr.studio_commands import BatchReplaceTextCommand, SetCueFieldsCommand
from twobyteasr.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project, save_project,
)
from twobyteasr.studio_timing import SplitPreview, describe_split

HEARD = [("我", 1000, 1200), ("用", 1200, 1400), ("了", 1400, 1600),
         ("chichoo", 1600, 2400), ("打", 2400, 2600), ("他", 2600, 2800)]
TEXT = "我用了chichoo打他"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project():
    project = SubtitleProject(
        media=StudioMedia(path="D:/missing.mp4", duration_ms=30000),
        cues=[StudioCue("2", 1000, 2800, TEXT, speaker_id="S01", evidence_refs=["segment:2"])],
        speakers=[StudioSpeaker(id="S01", name="主播")],
        asr_evidence={"segment:2": {
            "text": TEXT, "start_ms": 1000, "end_ms": 2800, "final_timing_owner": "FireRed",
            "caption_arbitration": {"acoustic_words": [
                dict(text=t, start_ms=a, end_ms=b) for t, a, b in HEARD]},
            "words": []}},
    )
    project.validate()
    ensure_independent_captions(project)
    stack = QUndoStack()
    stack.push(BatchReplaceTextCommand(project, {"2": "我用了CHICHOO打他"}, needle="chichoo",
                                       glossary_ids=["lib"]))
    override = project.studio_state["term_word_overrides"]["2"]
    assert override["alignment_provenance"] == "case_only"
    return project, stack


def _starts(project):
    words, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text"
    return [(w.text, w.start_ms) for w in words]


def test_group_move_carries_case_override_through_save_and_reopen(app, tmp_path):
    project, _stack = _project()
    shift_caption(project, project.cues[0], 5000)
    cue = project.cues[0]
    assert (cue.start_ms, cue.end_ms) == (6000, 7800)
    assert _starts(project) == [("我", 6000), ("用", 6200), ("了", 6400),
                                ("CHICHOO", 6600), ("打", 7400), ("他", 7600)]
    split = describe_split(cue, 7500, project=project)
    assert isinstance(split, SplitPreview)
    assert (split.left_text, split.right_text) == ("我用了CHICHOO打", "他")
    target = tmp_path / "moved.2byteproj"
    save_project(project, target)
    reopened = load_project(target)
    ensure_independent_captions(reopened)
    assert _starts(reopened)[3] == ("CHICHOO", 6600)


def test_rigid_timing_edit_and_undo_move_override_back(app):
    project, stack = _project()
    stack.push(SetCueFieldsCommand(project, "2", {"start_ms": 4000, "end_ms": 5800}, "移动"))
    assert _starts(project)[0] == ("我", 4000)
    assert isinstance(describe_split(project.cues[0], 5500, project=project), SplitPreview)
    stack.undo()
    assert (project.cues[0].start_ms, project.cues[0].end_ms) == (1000, 2800)
    assert _starts(project)[3] == ("CHICHOO", 1600)
    stack.redo()
    assert _starts(project)[3] == ("CHICHOO", 4600)


def test_trim_keeps_measured_words_in_place(app):
    project, stack = _project()
    stack.push(SetCueFieldsCommand(project, "2", {"start_ms": 1200}, "裁剪"))
    words, _reason = cue_words(project, project.cues[0])
    assert ("CHICHOO", 1600) in [(w.text, w.start_ms) for w in words]
