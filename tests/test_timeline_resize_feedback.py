import math
import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QPoint, Qt, QObject, QEvent
from PySide6.QtGui import QUndoStack, QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.timeline.studio_commands import EditCueIntervalsCommand
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project, save_project
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def scene(application):
    app = application
    project = SubtitleProject(media=StudioMedia("", duration_ms=16000), speakers=[StudioSpeaker("A"), StudioSpeaker("B")],
        cues=[StudioCue("a", 3000, 5000, "左边与右边拉伸", "A"), StudioCue("b", 6200, 7500, "接话目标", "B")])
    project.validate()
    timeline = WaveformTimeline()
    class Events(QObject):
        def eventFilter(self, obj, event):
            if event.type() in {QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave}:
                timeline._test_events.append((str(event.type()), str(event.position()) if hasattr(event, "position") else ""))
            if event.type() == QEvent.Type.MouseMove:
                timeline._last_test_move = event.position().toPoint()
            return False
    timeline._test_events = []
    timeline._last_test_move = None
    observer = Events(timeline)
    timeline.installEventFilter(observer)
    timeline.resize(1100, 480)
    timeline.move(100, 100)
    timeline.set_project(project)
    timeline.set_visible_window(0, 10000)
    timeline.set_snap_enabled(False)
    stack = QUndoStack()
    timeline.timing_edit_committed.connect(lambda values: stack.push(EditCueIntervalsCommand(project, values, lambda: timeline.set_project(project))))
    timeline.show()
    timeline.raise_()
    timeline.activateWindow()
    QTest.qWaitForWindowExposed(timeline)
    QTest.qWait(40)
    expected_dpr = os.environ.get("TWOBYTEASR_EXPECTED_DPR")
    if expected_dpr:
        assert timeline.devicePixelRatioF() == pytest.approx(float(expected_dpr))
        folder = Path(os.environ["TWOBYTEASR_RESIZE_SHOTS"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "dpi.json").write_text(json.dumps({"actual_dpr": timeline.devicePixelRatioF(), "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"), "screen": timeline.screen().name()}), encoding="utf-8")
    yield timeline, project, stack
    timeline.close()
    timeline.deleteLater()
    app.processEvents()


def move_mouse(timeline, point):
    QTest.mouseMove(timeline.windowHandle(), point)
    deadline = time.monotonic()+.6
    while timeline._last_test_move != point and time.monotonic() < deadline:
        QTest.qWait(10)
    assert timeline._last_test_move == point, ("native move not delivered", point, timeline._test_events[-8:])


def edge_point(timeline, cue, edge, offset=0, vertical=.5):
    track = timeline._track_layout()[0][cue.speaker_id]
    x = timeline._time_to_x(cue.start_ms if edge == "left" else cue.end_ms)
    # Round toward the edge so a requested 10px is <=10 logical pixels.
    target = math.ceil(x+offset) if offset < 0 else math.floor(x+offset)
    return QPoint(target, round(track.top()+7+(track.height()-14)*vertical))


@pytest.mark.parametrize("zoom", [8000, 16000])
@pytest.mark.parametrize("edge", ["left", "right"])
@pytest.mark.parametrize("offset", [-10, -6, -2, 2, 6, 10])
@pytest.mark.parametrize("vertical", [.08, .5, .92])
def test_real_mouse_edges_win_over_marquee(scene, zoom, edge, offset, vertical):
    timeline, project, stack = scene
    timeline.set_visible_window(0, zoom)
    cue = project.cues[0]
    start = edge_point(timeline, cue, edge, offset, vertical)
    move_mouse(timeline, QPoint(20, 20))
    move_mouse(timeline, start)
    assert timeline.cursor().shape() == Qt.CursorShape.SizeHorCursor, (start, timeline._cue_at(start), timeline._test_events[-8:], timeline.mapFromGlobal(QCursor.pos()), timeline.geometry())
    assert timeline._resize_hover == (cue.id, edge)
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=start)
    assert timeline._drag and timeline._drag[1] == edge
    assert timeline._marquee_origin is None
    move_mouse(timeline, start+QPoint(18, 0))
    QTest.qWait(5)
    assert timeline._drag_preview is not None
    assert timeline._drag_preview != (cue.start_ms, cue.end_ms)
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=start+QPoint(18, 0))
    assert stack.count() == 1
    assert project.cues[0].end_ms > project.cues[0].start_ms


def test_narrow_cue_nearest_edge_locked_and_genuine_blank(scene):
    timeline, project, _ = scene
    cue = project.cues[0]
    cue.end_ms = cue.start_ms+90
    timeline.set_project(project)
    for edge in ("left", "right"):
        point = edge_point(timeline, cue, edge)
        QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
        assert timeline._drag[1] == edge
        timeline.cancel_timing_edit()
        QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    timeline.locked_speakers.add("A")
    point = edge_point(timeline, cue, "left", -6)
    move_mouse(timeline, point)
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    assert timeline._drag is None and timeline._marquee_origin is None
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    blank = QPoint(round(timeline._time_to_x(9000)), point.y())
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=blank)
    assert timeline._marquee_origin is not None
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=blank)


def test_resize_undo_redo_save_reopen(scene, tmp_path):
    timeline, project, stack = scene
    point = edge_point(timeline, project.cues[0], "right", 6)
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    move_mouse(timeline, point+QPoint(30, 0))
    QTest.qWait(5)
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point+QPoint(30, 0))
    changed = project.cues[0].end_ms
    assert changed > 5000
    stack.undo(); assert project.cues[0].end_ms == 5000
    stack.redo(); assert project.cues[0].end_ms == changed
    path = save_project(project, tmp_path / "resized.2byteproj")
    assert load_project(path).cues[0].end_ms == changed


def test_snap_target_hysteresis_alt_release_and_minimum(scene):
    timeline, project, _ = scene
    timeline.set_snap_enabled(True)
    cue = project.cues[0]
    point = edge_point(timeline, cue, "right")
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    target_x = round(timeline._time_to_x(6200))
    move_mouse(timeline, QPoint(target_x, point.y()))
    QTest.qWait(5)
    assert timeline._snap_target and timeline._snap_target["time"] == 6200
    assert timeline._snap_target["cue_id"] == "b"
    assert timeline._drag_preview[1] == 6200
    shots = os.environ.get("TWOBYTEASR_RESIZE_SHOTS")
    if shots:
        folder = Path(shots); folder.mkdir(parents=True, exist_ok=True)
        timeline.grab().save(str(folder / "snap-feedback.png"))
    # Enter at ~6px; release at ~10.5px (existing 8px time threshold *1.75).
    move_mouse(timeline, QPoint(target_x+9, point.y()))
    QTest.qWait(5)
    assert timeline._snap_target and timeline._snap_target["time"] == 6200
    move_mouse(timeline, QPoint(target_x+19, point.y()))
    QTest.qWait(5)
    assert timeline._snap_target is None
    QTest.keyPress(timeline, Qt.Key.Key_Alt)
    move_mouse(timeline, QPoint(target_x+1, point.y()))
    QTest.qWait(5)
    assert timeline._snap_target is None
    QTest.keyRelease(timeline, Qt.Key.Key_Alt)
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(target_x+1, point.y()))
    assert timeline._snap_target is None
    assert timeline._drag is None
    # Drag far beyond the start: minimum duration stays positive and no false target is shown.
    point = edge_point(timeline, project.cues[0], "right")
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    move_mouse(timeline, QPoint(round(timeline._time_to_x(1000)), point.y()))
    QTest.qWait(5)
    assert timeline._drag_preview[1]-timeline._drag_preview[0] >= 50
    assert timeline._snap_target is None
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(round(timeline._time_to_x(1000)), point.y()))


@pytest.mark.parametrize("zoom", [8000, 16000])
def test_visible_snap_targets_use_same_screen_distance(scene, zoom):
    timeline, project, _ = scene
    from twobyteasr.projects.studio_project import VideoTrack, VideoClip
    from types import SimpleNamespace
    import numpy as np
    project.speakers[0].name = "S01"
    project.speakers[1].name = "S02"
    project.video_tracks = [VideoTrack(id="V1", name="V1", clips=[VideoClip("v", "fixture", source_out_ms=7300,
                                                                                       timeline_out_ms=7300)])]
    # Evidence and a waveform minimum near blank space must never create a
    # snap point. This is intentionally valid data, not a missing-cache test.
    project.asr_evidence["hidden"] = {"start_ms":5500,"end_ms":5800,"words":[{"word":"字","start":5.5,"end":5.8}]}
    project.cues[0].evidence_refs = ["hidden"]
    timeline.set_project(project)
    timeline.set_visible_window(0, zoom)
    timeline.set_snap_enabled(True)
    point = edge_point(timeline, project.cues[0], "right")
    QTest.mousePress(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    class Cache:
        calls = 0
        def read_window(self, *_args):
            self.calls += 1
            return SimpleNamespace(milliseconds_per_frame=1), np.zeros((64,2))
    cache = Cache()
    # Skip waveform painting while this focused snap probe supplies its cache.
    original_cache = timeline.cache
    timeline.cache = cache
    blank = QPoint(round(timeline._time_to_x(5600)), point.y())
    timeline.setUpdatesEnabled(False)
    move_mouse(timeline, blank)
    timeline.cache = original_cache
    timeline.setUpdatesEnabled(True)
    assert cache.calls == 0
    assert timeline._snap_target is None


    assert abs(timeline._time_to_x(timeline._drag_preview[1])-blank.x()) < 1.5
    shots = os.environ.get("TWOBYTEASR_RESIZE_SHOTS")
    if shots:
        timeline.grab().save(str(Path(shots) / f"blank-no-snap-{zoom}.png"))
    target_x = round(timeline._time_to_x(6200))
    move_mouse(timeline, QPoint(target_x-17,point.y()))
    assert timeline._snap_target is None
    move_mouse(timeline, QPoint(target_x-6,point.y()))
    assert timeline._snap_target["time"] == 6200
    assert timeline._snap_target["label"] == "S02 轨 · 字幕开头"
    if shots:
        timeline.grab().save(str(Path(shots) / f"real-cue-edge-{zoom}.png"))
    move_mouse(timeline, QPoint(target_x+20,point.y()))
    assert timeline._snap_target is None
    video_x = round(timeline._time_to_x(7300))
    move_mouse(timeline, QPoint(video_x-6,point.y()))
    assert timeline._snap_target["time"] == 7300
    assert timeline._snap_target["label"] == "V1 素材结尾"
    if shots:
        timeline.grab().save(str(Path(shots) / f"real-video-edge-{zoom}.png"))
    QTest.mouseRelease(timeline.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(video_x-6,point.y()))
    assert timeline._snap_target is None


@pytest.mark.parametrize("moving", ["A", "B"])
def test_high_zoom_no_hidden_25ms_floor_and_both_display_tracks(scene, moving):
    timeline, project, _ = scene
    a,b = project.cues
    a.start_ms, a.end_ms = 5800,6000
    b.start_ms, b.end_ms = 6400,6600
    project.speakers[0].name, project.speakers[1].name = "S01", "S02"
    timeline.set_project(project)
    timeline.set_visible_window(5700,1000)
    timeline.set_snap_enabled(True)
    cue, edge, target, label = (a,"right",6400,"S02") if moving == "A" else (b,"left",6000,"S01")
    point = edge_point(timeline,cue,edge)
    QTest.mousePress(timeline.windowHandle(),Qt.MouseButton.LeftButton,pos=point)
    x=round(timeline._time_to_x(target))
    move_mouse(timeline,QPoint(x-18,point.y()))
    assert timeline._snap_target is None
    move_mouse(timeline,QPoint(x-6,point.y()))
    assert timeline._snap_target["time"] == target
    assert label in timeline._snap_target["label"]
    QTest.mouseRelease(timeline.windowHandle(),Qt.MouseButton.LeftButton,pos=QPoint(x-6,point.y()))
