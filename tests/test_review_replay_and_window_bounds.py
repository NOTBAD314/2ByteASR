"""Review replay stays on its caption; review strip height; window bounds (2026-10-15)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr import studio_review_ui, window_constraints
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_qc import QCCandidate
from twobyteasr.studio_review import (
    REVIEW_NEXT_GUARD_MS,
    REVIEW_PREROLL_MS,
    REVIEW_TAIL_MS,
    ReviewPlayback,
    review_playback_window,
)
from twobyteasr.studio_ui import SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def _cue(cue_id, start, end):
    return SimpleNamespace(id=cue_id, start_ms=start, end_ms=end)


def test_replay_window_stops_before_a_close_next_caption():
    cue = _cue("b", 2700, 4200)
    start, stop = review_playback_window(cue, [cue, _cue("c", 4300, 6000)])
    assert start == 2700 - REVIEW_PREROLL_MS
    assert stop == 4300 - REVIEW_NEXT_GUARD_MS


def test_replay_window_keeps_the_tail_when_the_next_caption_is_far():
    cue = _cue("b", 2700, 4200)
    assert review_playback_window(cue, [_cue("c", 8000, 9000)]) == (2450, 4200 + REVIEW_TAIL_MS)
    assert review_playback_window(cue) == (2450, 4200 + REVIEW_TAIL_MS)


def test_replay_window_ignores_an_overlapping_speaker_and_clamps_at_zero():
    cue = _cue("a", 100, 2000)
    # Starts inside "a" (another speaker): must not cut "a" short.
    assert review_playback_window(cue, [_cue("x", 1500, 2600)]) == (0, 2000 + REVIEW_TAIL_MS)
    # Touching captions: stop a hair before the next one starts.
    assert review_playback_window(cue, [_cue("n", 2000, 3000)]) == (0, 2000 - REVIEW_NEXT_GUARD_MS)


def _page(tmp_path, monkeypatch, cues):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "review.mp4"), duration_ms=20_000), cues=cues)
    path = save_project(project, tmp_path / "review.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.resize(1600, 950)
    page.show()
    page.open_project(path)
    app.processEvents()
    return app, page


CLOSE_CUES = [
    StudioCue("a", 1000, 2500, "第一句"),
    StudioCue("b", 2700, 4200, "第二句紧跟其后"),
    StudioCue("c", 4300, 6000, "第三句也很近"),
]


def test_review_replay_holds_the_selection_across_neighbouring_captions(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, list(CLOSE_CUES))
    try:
        page._set_review_mode(True)
        page.select_cue("b")
        page._review_playback = ReviewPlayback("b", 2450, 4280, 7)
        # Lead-in (inside "a"), the caption, the tail and an overshoot into "c".
        for milliseconds in (2450, 3000, 4250, 4400):
            page.cue_controller.sync_playhead_target(milliseconds)
            assert page.selected_cue_id == "b"
        page.cue_controller.sync_playhead_target(4400, force=True)
        assert page.selected_cue_id == "b"
        # Released where the replay stopped: no retarget to what was observed.
        page._release_review_playback()
        page.cue_controller.sync_playhead_target(4400)
        assert page.selected_cue_id == "b"
        # A later clock target change follows the clock again.
        page.cue_controller.sync_playhead_target(1500)
        assert page.selected_cue_id == "a"
    finally:
        page.close_page()
        page.deleteLater()


def test_review_replay_stops_on_media_time_and_parks_the_hold(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, list(CLOSE_CUES))
    try:
        paused = []
        monkeypatch.setattr(page.video, "_paused", False, raising=False)
        monkeypatch.setattr(page.video, "_playback_rate", 2.0, raising=False)
        monkeypatch.setattr(page.video, "set_paused", lambda value: paused.append(bool(value)))
        monkeypatch.setattr(page.video, "controller", SimpleNamespace(running=False), raising=False)
        page._review_play_generation = 3
        page._review_playback = ReviewPlayback("b", 2450, 4280, 3)
        page._review_playback_tick(3000)
        assert paused == [] and not page._review_playback.finished
        page._review_playback_tick(4300)
        assert paused == [True]
        assert page._review_playback is not None and page._review_playback.finished
        assert page._review_held_cue_id() == "b"
        # Inside the replayed stretch the hold stays; leaving it ends the hold.
        page._review_playback_tick(4300)
        assert page._review_held_cue_id() == "b"
        page._review_playback_tick(9000)
        assert page._review_playback is None
    finally:
        page.close_page()
        page.deleteLater()


def test_user_seek_and_transport_play_release_the_review_hold(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, list(CLOSE_CUES))
    try:
        monkeypatch.setattr(page.video, "controller", SimpleNamespace(running=False), raising=False)
        monkeypatch.setattr(page.video, "seek", lambda *args, **kwargs: None)
        monkeypatch.setattr(page.video, "set_seek_visual_expectation", lambda *args, **kwargs: None, raising=False)
        page._review_playback = ReviewPlayback("b", 2450, 4280, 1, finished=True)
        page._review_seeking = True
        page._seek(2.45)  # the replay's own lead-in seek keeps it
        assert page._review_held_cue_id() == "b"
        page._review_seeking = False
        page._seek(5.0)
        assert page._review_playback is None
        page._review_playback = ReviewPlayback("b", 2450, 4280, 2, finished=True)
        page._set_review_mode(True)
        assert page._review_playback is None
    finally:
        page.close_page()
        page.deleteLater()


def test_review_strip_height_does_not_follow_the_candidate_count(tmp_path, monkeypatch):
    cues = [StudioCue(f"c{i}", i * 3000, i * 3000 + 2000, f"第{i}句候选不同") for i in range(4)]
    app, page = _page(tmp_path, monkeypatch, cues)
    counts = {"c0": 1, "c1": 2, "c2": 4, "c3": 3}

    def fake_candidates(project, cue):
        return tuple(QCCandidate(f"{cue.text}{n}" * (1 + n), ("MOSS", "Qwen")[n % 2:n % 2 + 1])
                     for n in range(counts[cue.id]))

    monkeypatch.setattr(studio_review_ui, "review_candidates", fake_candidates)
    try:
        page._set_review_mode(True)
        heights = []
        for cue in cues:
            page.select_cue(cue.id)
            page._refresh_review_summary_strip()
            for _ in range(3):
                app.processEvents()
            heights.append((page.review_summary_strip.height(), page.video.height()))
        assert len(set(heights)) == 1, heights
        # Four candidates share one row when the strip is wide enough.
        page.select_cue("c2")
        page._refresh_review_summary_strip()
        app.processEvents()
        layout = page.review_dock_candidate_layout
        rows = {layout.getItemPosition(i)[0] for i in range(layout.count())}
        columns = max(1, min(4, page.review_summary_strip.width() // 260))
        assert rows == set(range((4 + columns - 1) // columns)), (rows, page.review_summary_strip.width())
        if page.review_summary_strip.width() >= 1040:
            assert rows == {0}
        # Same caption, same width: the cards are kept, not rebuilt.
        first = layout.itemAt(0).widget()
        page._refresh_review_summary_strip()
        assert layout.itemAt(0).widget() is first
    finally:
        page.close_page()
        page.deleteLater()


class _FakeWindow:
    def __init__(self, frame, avail, maximized=True):
        self._frame, self._avail, self._maximized = QRect(*frame), QRect(*avail), maximized

    def isMinimized(self):
        return False

    def isVisible(self):
        return True

    def isMaximized(self):
        return self._maximized

    def isFullScreen(self):
        return False

    def screen(self):
        return SimpleNamespace(availableGeometry=lambda: self._avail, geometry=lambda: self._avail)

    def frameGeometry(self):
        return self._frame

    def testAttribute(self, attribute):
        return False


def test_maximized_window_outside_its_screen_is_reported_broken():
    _app()
    # Moved by Windows to a smaller, differently scaled monitor.
    assert window_constraints.special_geometry_broken(_FakeWindow((3860, 20, 2194, 1194), (3840, 0, 1080, 1880)))
    # Top-left above the screen: title buttons out of reach.
    assert window_constraints.special_geometry_broken(_FakeWindow((-811, -286, 2194, 1194), (0, 0, 2194, 1194)))
    assert not window_constraints.special_geometry_broken(_FakeWindow((0, 0, 2194, 1194), (0, 0, 2194, 1194)))
    assert not window_constraints.special_geometry_broken(
        _FakeWindow((-811, -286, 2194, 1194), (0, 0, 2194, 1194), maximized=False))


def test_title_drag_restores_a_maximized_window_only_after_moving(monkeypatch):
    app = _app()
    from PySide6.QtGui import QCursor, QGuiApplication

    window = QWidget()
    window.resize(900, 600)
    window.showMaximized()
    app.processEvents()
    state = {"pos": QPoint(400, 10), "buttons": Qt.MouseButton.LeftButton}
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(state["pos"])))
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: state["buttons"]))
    try:
        drag = window_constraints.begin_title_drag(window, QPoint(400, 10), 10)
        drag.poll()
        assert window.isMaximized()  # a click is not a drag
        state["buttons"] = Qt.MouseButton.NoButton
        drag.poll()
        app.processEvents()
        assert window.isMaximized() and getattr(window, "_title_drag", None) is None
        state.update(buttons=Qt.MouseButton.LeftButton)
        drag = window_constraints.begin_title_drag(window, QPoint(400, 10), 10)
        state["pos"] = QPoint(400 + QApplication.startDragDistance() + 20, 40)
        drag.poll()
        app.processEvents()
        assert not window.isMaximized()
        assert window.frameGeometry().contains(state["pos"])
        state["buttons"] = Qt.MouseButton.NoButton
        drag.poll()
    finally:
        window.close()
        window.deleteLater()
