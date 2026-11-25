"""Known lyrics remain ordered and separate until explicitly imported."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.subtitle_import import imported_track
from twobyteasr.recognition.lyrics_ctc import measure_lines
from twobyteasr.studio.studio_lyrics_alignment import _import_plan
from twobyteasr.timeline.subtitle_import_command import ImportSubtitlesCommand


def _logits(tokens, vocabulary):
    matrix = np.full((len(tokens), len(vocabulary)), -15., dtype=np.float32)
    matrix[np.arange(len(tokens)), tokens] = 0.
    return matrix


def test_repeated_lines_keep_acoustic_separation_and_provisional_positions():
    vocab = {"<blank>": 0, "|": 1, "a": 2, "b": 3}
    logits = _logits([0, 2, 2, 0, 1, 0, 0, 2, 2, 0], vocab)
    rows = measure_lines(logits, ["a", "a"], vocab, 200)
    assert [row["text"] for row in rows] == ["a", "a"]
    assert [(row["start_ms"], row["end_ms"]) for row in rows] == [(20, 60), (140, 180)]
    with pytest.raises(ValueError, match="唱词证据不足"):
        measure_lines(_logits([0] * 10, vocab), ["a", "a"], vocab, 200)
    with pytest.raises(ValueError, match="不支持"):
        measure_lines(logits, ["unknown"], vocab, 200)


def test_measured_lyrics_use_project_time_and_one_additive_undo():
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia("", duration_ms=20000),
                              cues=[StudioCue("speech", 0, 1000, "speech")])
    project.validate()
    request = SimpleNamespace(points=(5000, 6000), lines=("again", "again"), enhance_voice=False)
    rows = [dict(text="again", start_ms=a, end_ms=b,
                 words=[dict(start_ms=a, end_ms=b, posterior=.8)]) for a, b in ((50, 250), (400, 800))]
    plan = _import_plan(project, request, rows)
    stack = QUndoStack()
    stack.push(ImportSubtitlesCommand(project, plan))
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in project.cues] == [
        (0, 1000, "speech"), (5050, 5250, "again"), (5400, 5800, "again")]
    assert imported_track(project, plan.speakers[0].id)["role"] == "lyrics"
    stack.undo()
    assert [cue.id for cue in project.cues] == ["speech"]
    assert imported_track(project, plan.speakers[0].id) == {}
