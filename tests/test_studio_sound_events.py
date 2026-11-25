"""Event annotations belong to their own editable project layer."""
from types import SimpleNamespace

from PySide6.QtGui import QImage, QPainter, QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.studio.studio_sound_events import KEY, SoundEvent, SoundEventsCommand, paint, read_events


def test_event_edits_are_undoable_and_preserve_the_caption_track(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia("", duration_ms=6000),
                              cues=[StudioCue("text", 1000, 3000, "Original caption")])
    project.validate()
    record = SoundEvent("one", "laugh", 1500, 2200, True)
    before = [(cue.id, cue.start_ms, cue.end_ms, cue.text) for cue in project.cues]
    stack = QUndoStack()
    stack.push(SoundEventsCommand(project, [record]))
    assert read_events(project) == (record,)
    path = save_project(project, tmp_path / "annotated.2byteproj")
    reopened = load_project(path)
    assert read_events(reopened) == (record,)
    assert [(cue.id, cue.start_ms, cue.end_ms, cue.text) for cue in reopened.cues] == before

    stack.undo()
    assert KEY not in project.studio_state and read_events(project) == ()
    stack.redo()
    assert read_events(project) == (record,)


def test_event_overlay_highlights_only_intersecting_marked_time():
    project = SubtitleProject(media=StudioMedia("", duration_ms=6000),
                              studio_state={KEY: [
                                  dict(id="late", kind="cry", start_ms=4000, end_ms=5000),
                                  dict(id="good", kind="laugh", start_ms=1500, end_ms=2200, confirmed=True),
                                  dict(id="invalid", kind=["bad"], start_ms=200, end_ms=500),
                              ]})
    image = QImage(260, 34, QImage.Format.Format_ARGB32)
    image.fill(0)
    timeline = SimpleNamespace(project=project, TRACK_HEADER_WIDTH=20, RULER_HEIGHT=34,
                               _content_right=lambda: 260, _time_to_x=lambda ms: ms / 10)
    painter = QPainter(image)
    try:
        paint(timeline, painter, 1200, 2300)
    finally:
        painter.end()
    assert image.pixelColor(175, 28).alpha() == 255
    assert image.pixelColor(30, 28).alpha() == 0
    assert [event.id for event in read_events(project)] == ["good", "late"]


def test_automatic_vocal_selection_uses_the_union_of_confirmed_music():
    from twobyteasr.studio.studio_reasr_batch import confirmed_music_overlap

    cue = StudioCue("capt", 1000, 2500, "Original")
    notes = [SoundEvent("one", "music", 950, 1350, True),
             SoundEvent("two", "music", 1200, 1600, True),
             SoundEvent("three", "music", 1700, 2400, False),
             SoundEvent("four", "laugh", 2100, 2600, True)]
    assert confirmed_music_overlap(cue, notes) == 600
    confirmed = notes[:2] + [SoundEvent("three", "music", 1700, 2400, True)]
    assert confirmed_music_overlap(cue, confirmed) == 1300
