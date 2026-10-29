"""2026-10-10 (user): gaps of 0.5 s or less make captions flicker; the earlier
caption should run on to the next one's start."""
from types import SimpleNamespace

from twobyteasr.subtitle_rules.display_timing import short_gap_bridges


def test_full_track_and_same_speaker_gaps_close_without_moving_starts():
    rows = [("a", "S1", 0, 1000), ("b", "S2", 1300, 2000),            # 300 ms blank screen
            ("c", "S1", 3000, 4000), ("x", "S2", 3500, 6000),          # S2 stays up ...
            ("d", "S1", 4234, 5000),                                   # ... while S1 blinks 234 ms
            ("e", "S1", 7000, 8000), ("f", "S1", 8600, 9000)]          # 600 ms: a real pause
    assert short_gap_bridges(rows, 500) == {"a": 1300, "c": 4234}


def test_same_speaker_gap_stays_when_someone_else_starts_inside_it():
    rows = [("c", "S1", 0, 1000), ("x", "S2", 1100, 3000), ("d", "S1", 1400, 2000)]
    assert short_gap_bridges(rows, 500, full_track=False) == {}


def test_maximum_duration_guard():
    rows = [("a", "S1", 0, 4800), ("b", "S1", 5200, 6000)]
    assert short_gap_bridges(rows, 500, max_duration=5000) == {}
    assert short_gap_bridges(rows, 500) == {"a": 5200}


def test_pipeline_bridge_also_closes_same_speaker_blinks():
    from twobyteasr.subtitle_rules.timing import bridge_short_display_gaps
    cue = lambda i, s, a, b: SimpleNamespace(cue_id=i, speaker=s, start=a, end=b)
    cues = [cue(1, "S01", 0.0, 1.0), cue(2, "S02", 0.5, 3.0), cue(3, "S01", 1.3, 2.0)]
    bridge_short_display_gaps(cues, 10.0, 60.0)
    assert abs(cues[0].end - 1.3) < 1 / 60
    assert cues[1].end == 3.0 and cues[2].end == 2.0


def test_relock_after_late_steps_closes_off_grid_blank_frames(monkeypatch):
    """2026-10-18 (日常 19): content recovery and CTC starts wrote raw times after the
    bridge; a start 12-40 ms after the previous end showed one blank frame."""
    from twobyteasr.subtitle_rules import timing
    events = []
    monkeypatch.setattr(timing, "record_run_event", lambda name, **values: events.append((name, values)))
    fps = 24000 / 1001
    cue = lambda i, s, a, b: SimpleNamespace(cue_id=i, speaker=s, start=a, end=b)
    cues = [cue(1, "S01", 0.0, 1.0), cue(2, "S02", 1.03, 2.0123),      # one blank frame after locking
            cue(3, "S01", 2.0123, 3.0),                                  # touching: stays touching
            cue(4, "S01", 3.7, 4.5)]                                     # 700 ms: a real pause
    timing.relock_display_timing(cues, 10.0, fps, stage="test")
    frames = [(round(c.start * fps, 6), round(c.end * fps, 6)) for c in cues]
    assert all(value == int(value) for pair in frames for value in pair)
    assert cues[0].end == cues[1].start and cues[1].end == cues[2].start
    assert cues[3].start - cues[2].end > 0.5 and cues[1].start == round(1.03 * fps) / fps
    assert events[-1][0] == "display_frame_relock" and events[-1][1]["short_gaps_after"] == 0
    assert events[-1][1]["short_gaps_before"] == 1 and events[-1][1]["stage"] == "test"


def test_studio_bridge_is_one_undo_step():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from twobyteasr.studio.display_handoff_ui import bridge_short_gaps
    project = SubtitleProject(media=StudioMedia(path="x.wav", duration_ms=20_000), cues=[
        StudioCue("a", 0, 1000, "第一句", speaker_id="S1"), StudioCue("b", 1300, 2000, "第二句", speaker_id="S2"),
        StudioCue("c", 3000, 4000, "第三句", speaker_id="S1")])
    project.render_settings["_cue_domain"] = "timeline"
    hints = []
    page = SimpleNamespace(project=project, undo_stack=QUndoStack(), _changed=lambda *a, **k: None,
                           _show_studio_hint=hints.append)
    assert bridge_short_gaps(page) == 1
    assert [(c.start_ms, c.end_ms) for c in project.cues] == [(0, 1300), (1300, 2000), (3000, 4000)]
    page.undo_stack.undo()
    assert project.cues[0].end_ms == 1000
    assert bridge_short_gaps(page) == 1 and "1" in hints[-1]
