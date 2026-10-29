import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QComboBox
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin


class Page(StudioPlaybackFlowMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.play_button = QPushButton(self)
        self.speed_box = QComboBox(self)
        for speed in (1., 2., 4., 8.):
            self.speed_box.addItem(str(speed), speed)
        self.timeline = SimpleNamespace(playhead_ms=0)
        self.project = object()
        self.audio_transitions = []
        self.video = SimpleNamespace(controller=object(), _paused=True, rate=1., at_eof=False)
        self.video.playback_position_snapshot = lambda: SimpleNamespace(paused=self.video._paused)
        def paused(value):
            self.video._paused = bool(value)
            self._sync_play_button(value)
        self.video.set_paused = paused
        self.video.set_speed = lambda value: setattr(self.video, "rate", value)
        self._seek = lambda seconds: setattr(self.timeline, "playhead_ms", round(seconds*1000))

    def _sync_video_compositor(self, _position):
        self.audio_transitions.append((self._shuttle_speed, self.video.rate, self.speed_box.currentData()))


@pytest.fixture
def page():
    app = QApplication.instance() or QApplication([])
    page = Page()
    yield page
    page.close()


def test_l_steps_pause_play_and_seek_are_temporary(page):
    for speed in (1., 2., 4., 8.):
        page._shuttle(1)
        assert page.video.rate == speed and page._shuttle_rate == speed
    page._toggle_playback()
    assert page.video._paused and page._shuttle_rate is None
    assert page.audio_transitions[-1] == (1., 1., 1.)
    page._seek(4)
    page._toggle_playback()
    assert not page.video._paused and page.video.rate == 1.
    page._shuttle(1)
    assert page._shuttle_rate == 1.


def test_manual_two_and_four_persist_across_pause(page):
    for speed in (2., 4.):
        page._set_speed(speed)
        page._toggle_playback()
        page._toggle_playback()
        assert page.video._paused and page.video.rate == speed
        assert page._manual_playback_rate == speed and page._shuttle_rate is None


def test_eof_and_stop_reset_only_temporary_state(page):
    page._shuttle(1); page._shuttle(1)
    page.video.at_eof = True
    page.video.set_paused(True)
    assert page._shuttle_rate is None and page.video.rate == 1.
    page._toggle_playback()
    assert page.video.rate == 1. and not page.video._paused
    page._shuttle(1); page._shuttle(1)
    page._sync_play_button(True)
    assert page.video.rate == 1. and page._shuttle_rate is None
