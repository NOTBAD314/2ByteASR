import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.timeline.studio_commands import EditCueIntervalsCommand
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.timeline_cue_gesture import CueInterval, preview_intervals


def test_group_delta_clamps_at_origin_and_minimum_without_moving_neighbours():
    values = {'a': CueInterval(100, 1000, 's1'), 'b': CueInterval(500, 800, 's2')}
    moved = preview_intervals(values, 'a', 'move', -900)
    assert moved['a'].start_ms == 0 and moved['b'].start_ms == 400
    resized = preview_intervals(values, 'a', 'left', 500)
    assert resized['b'].end_ms-resized['b'].start_ms == 50
    assert resized['a'].start_ms == 350
    assert preview_intervals(values, 'a', 'move', 20, target_speaker='s3')['b'].speaker_id == 's2'


def test_one_command_restores_time_and_track_in_one_undo():
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia(path="synthetic.mp4"), cues=[StudioCue('a', 100, 1000, '甲'), StudioCue('b', 1200, 2000, '乙')])
    stack = QUndoStack()
    stack.push(EditCueIntervalsCommand(project, {'a': CueInterval(400, 1800, 'new')}))
    assert stack.count() == 1
    assert (project.cues[0].start_ms, project.cues[0].speaker_id) == (400, 'new')
    stack.undo()
    assert project.cues[0].start_ms == 100
    assert project.cues[1].start_ms == 1200
    stack.redo()
    assert project.cues[0].end_ms == 1800


def test_real_widget_pointer_preview_never_mutates_project_and_cancel_restores():
    app = QApplication.instance() or QApplication([])
    timeline = WaveformTimeline()
    timeline.resize(1200, 480)
    project = SubtitleProject(media=StudioMedia(path="synthetic.mp4", duration_ms=8000),
                              cues=[StudioCue('a', 1000, 3000, '连续拖动')])
    timeline.set_project(project)
    timeline.set_visible_window(0, 8000)
    timeline.snap_enabled = False
    y = timeline._track_layout()[0][project.cues[0].speaker_id].center().y()
    origin = QPointF(timeline._time_to_x(2000), y)
    committed = []
    timeline.timing_edit_committed.connect(committed.append)
    def mouse(kind, point):
        event = QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(timeline, event)
    mouse(QEvent.Type.MouseButtonPress, origin)
    for dx in (10, 30, 60, 100):
        mouse(QEvent.Type.MouseMove, origin + QPointF(dx, 0))
    app.processEvents()
    delta = timeline._x_to_time(origin.x()+100)-timeline._x_to_time(origin.x())
    assert project.cues[0].start_ms == 1000
    assert timeline._timing_preview['a'].start_ms == 1000+delta
    assert timeline.visible_cues()[0].start_ms == 1000+delta
    assert len(timeline.timing_preview_metrics) == 1
    assert not committed
    assert timeline.cancel_timing_edit()
    assert timeline.visible_cues()[0].start_ms == 1000
    mouse(QEvent.Type.MouseButtonPress, origin)
    mouse(QEvent.Type.MouseMove, origin + QPointF(100, 0))
    mouse(QEvent.Type.MouseButtonRelease, origin + QPointF(100, 0))
    assert len(committed) == 1 and committed[0]['a'].start_ms == 1000+delta
    timeline.deleteLater()
