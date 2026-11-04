"""GUI ownership and cancellation while a real actor is blocked."""
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.studio_mpv import MpvController, _MpvCommandActor
from twobyteasr.studio.studio_video_canvas import MpvCanvas

APP = QApplication.instance() or QApplication([])


def test_cold_constructor_failure_completes_startup_request(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.playback import studio_mpv
    from twobyteasr.studio.studio_readiness import StudioReadiness
    completed, replies = threading.Event(), []
    def unavailable():
        raise RuntimeError('injected missing player runtime')
    def emit(*args):
        replies.append(args)
        completed.set()
    monkeypatch.setattr(studio_mpv, 'MpvController', unavailable)
    gate = SimpleNamespace(page=SimpleNamespace(video=SimpleNamespace(winId=lambda: 1, controller=None)),
                           player_loaded=SimpleNamespace(emit=emit))
    StudioReadiness._start_mpv_player(gate, 4)
    assert completed.wait(1)
    assert replies == [(4,None,'injected missing player runtime')]


class Running:
    def poll(self):
        return None


@pytest.fixture
def canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(_MpvCommandActor, '_heartbeat', lambda self: None)
    exe = tmp_path/'mpv.exe'
    exe.write_bytes(b'fixture')
    video = MpvCanvas()
    controller = MpvController(exe)
    controller._process = Running()
    controller._actor = _MpvCommandActor(controller)
    video.controller = controller
    monkeypatch.setattr(video, '_hold_media_cache', lambda path: None)
    monkeypatch.setattr(video, '_publish_first_picture', lambda path: None)
    try:
        yield video, controller
    finally:
        video._timer.stop()
        video._sync_timer.stop()
        for item in (controller, video.controller):
            if item is not None:
                if item._actor is not None:
                    item._actor.close()
                item._process = None
        video.close_player()
        video.deleteLater()
        APP.processEvents()


def until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.005)
    assert predicate()


def test_load_returns_without_waiting_for_blocked_ipc(canvas, tmp_path):
    video, controller = canvas
    entered, release = threading.Event(), threading.Event()
    controller._actor.post(lambda: (entered.set(), release.wait(4)))
    assert entered.wait(1)
    try:
        started = time.perf_counter()
        video.load(str(tmp_path/'A.mp4'), start_seconds=1.)
        elapsed = time.perf_counter() - started
        assert elapsed < .25
        assert video._startup_state == 'MEDIA_OPENING'
        assert video._submitted_load_position is not None
    finally:
        controller._actor._stopping = True
        release.set()


def recovery_fixture(video, old, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    closes, loads = [], []
    def close():
        closes.append(threading.current_thread().name)
        entered.set()
        release.wait(4)
        old._actor.close()
        old._process = None
    monkeypatch.setattr(old, 'close', close)
    monkeypatch.setattr(MpvController, 'start', lambda self, *a, **k: setattr(self, '_process', Running()))
    monkeypatch.setattr(video, 'load', lambda path, ass, **kw: loads.append((path, kw, threading.current_thread())))
    video._media_path = 'A.mp4'
    video._load_generation = 1
    return entered, release, closes, loads


def test_one_recovery_installs_only_latest_project_on_gui_thread(canvas, monkeypatch):
    video, old = canvas
    entered, release, closes, loads = recovery_fixture(video, old, monkeypatch)
    try:
        assert video._request_player_recovery('injected_timeout')
        assert entered.wait(1)
        video._media_path, video._load_generation = 'B.mp4', 2
        assert video._request_player_recovery('another_callback')
        MpvCanvas.load(video, 'B.mp4', start_seconds=0.)
        assert video._recovery_deadline > time.monotonic()
        assert len(closes) == 1 and video._recovery_attempts == 1
    finally:
        release.set()
    until(lambda: video._recovery_request is None)
    assert [row[0] for row in loads] == ['B.mp4']
    assert loads[0][2] is threading.main_thread()
    assert closes == ['studio-player-recovery']
    assert video.controller is not old
    assert video.controller.instance_id != old.instance_id


def test_cancelled_project_is_never_reloaded_by_recovery(canvas, monkeypatch):
    video, old = canvas
    entered, release, closes, loads = recovery_fixture(video, old, monkeypatch)
    try:
        video._request_player_recovery('injected_timeout')
        assert entered.wait(1)
        video.unload_project_media()
    finally:
        release.set()
    until(lambda: video._recovery_request is None)
    assert not loads and video._media_path == ''


def test_rebuild_budget_ends_attempt_and_new_load_gets_new_budget(canvas, tmp_path, monkeypatch):
    video, old = canvas
    video._media_path = 'A.mp4'
    video._recovery_attempts = video.PLAYER_REBUILD_LIMIT
    video._recovery_deadline = time.monotonic() + 5
    assert not video._request_player_recovery('injected_timeout')
    assert video._startup_state == 'FAILED' and video._last_load_error
    monkeypatch.setattr(old, 'post_load_at', lambda *a, **k: True)
    video.load(str(tmp_path/'B.mp4'), start_seconds=0.)
    assert video._recovery_attempts == 0 and video._last_load_error == ''
    assert video._startup_state == 'MEDIA_OPENING'
