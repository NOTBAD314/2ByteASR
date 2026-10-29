"""A02: edit the sequence, never destructively retime canonical subtitles."""
import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.timeline.studio_edit_sequence import sequence_of, projected_cues, source_cue_id_of
from twobyteasr.timeline.studio_edit_commands import ripple_trim_command, restore_full_sequence_command, razor_video_command
from twobyteasr.studio.studio_autocut import auto_cut_silence_command, source_ranges_to_timeline
from twobyteasr.exports.studio_subtitle_export import _compile_format


def make_project(recognized=False):
    p = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=60000), cues=[
        StudioCue("head", 2000, 3000, "开头"), StudioCue("later", 35000, 37000, "后句")])
    p.validate()
    seq = sequence_of(p)
    seq.video_track_locked = False
    if recognized:
        p.generation_metadata["timeline_recognition"] = {"sequence": copy.deepcopy(seq.to_dict())}
    return p


@pytest.mark.parametrize("recognized", [False, True])
@pytest.mark.parametrize("operation,expected", [("q", (5000, 7000)), ("w", (5000, 7000)), ("silence", (29000, 31000))])
def test_ripple_preserves_canonical_export_undo_and_reopen(tmp_path, recognized, operation, expected):
    p = make_project(recognized)
    original = copy.deepcopy(p.cues)
    if operation == "w":
        razor_video_command(p, 30000).redo()
    for _ in range(20):
        command = (auto_cut_silence_command(p, [(5000, 11000)]) if operation == "silence"
                   else ripple_trim_command(p, "start" if operation == "q" else "end", 30000 if operation == "q" else 0))
        command.redo()
        assert p.cues == original
        view = projected_cues(p)
        later = next(c for c in view if source_cue_id_of(c.id) == "later")
        assert (later.start_ms, later.end_ms) == expected
        assert "后句" in _compile_format(p, "srt")
        ass = _compile_format(p, "ass")
        assert "后句" in ass
        wanted = { (5000, 7000): ',0:00:05.00,0:00:07.00,',
                   (29000, 31000): ',0:00:29.00,0:00:31.00,' }[expected]
        assert any(wanted in line and '后句' in line for line in ass.splitlines())
        command.undo()
        assert p.cues == original
        command.redo()
        assert p.cues == original
        command.undo()
    command.redo()
    loaded = load_project(save_project(p, tmp_path / "ripple.2byteproj"))
    assert loaded.cues == original
    assert [(c.text, c.start_ms, c.end_ms) for c in projected_cues(loaded)] == [(c.text, c.start_ms, c.end_ms) for c in projected_cues(p)]
    if not recognized:
        restore_full_sequence_command(loaded).redo()
        assert loaded.cues == original
        assert projected_cues(loaded) == original


def test_silence_ranges_respect_segment_rate():
    p = make_project()
    seq = sequence_of(p)
    seq.segments[0].timeline_out_ms = 30000
    assert source_ranges_to_timeline(seq, [(10000, 14000)]) == [(5000, 7000)]


def test_recognized_repeated_source_instances_stay_distinct(tmp_path):
    p = make_project()
    seq = sequence_of(p)
    a = seq.segments[0]
    a.source_in_ms, a.source_out_ms, a.timeline_out_ms = 30000, 50000, 10000
    b = copy.deepcopy(a)
    b.id, b.timeline_in_ms, b.timeline_out_ms = "repeat", 10000, 20000
    seq.segments = [a, b]
    p.cues = [StudioCue("first", 2000, 4000, "第一次"), StudioCue("second", 12000, 14000, "第二次")]
    p.validate()
    p.generation_metadata["timeline_recognition"] = {"sequence": copy.deepcopy(seq.to_dict())}
    original = copy.deepcopy(p.cues)
    ripple_trim_command(p, "start", 1000).redo()
    assert p.cues == original
    assert [(c.text, c.start_ms, c.end_ms) for c in projected_cues(p)] == [("第一次", 1000, 3000), ("第二次", 11000, 13000)]
    loaded = load_project(save_project(p, tmp_path / "repeat.2byteproj"))
    assert loaded.cues == original
    assert len(projected_cues(loaded)) == 2
