import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.timeline_scrub import TimelineScrub


def test_drag_has_one_inflight_and_release_replaces_latest_intent():
    app = QApplication.instance() or QApplication([])
    page = QObject()
    snapshot = SimpleNamespace(paused=True, seeking=False)
    page.timeline = SimpleNamespace(_scrub_drag=True)
    page.video = SimpleNamespace(playback_position_snapshot=lambda: snapshot,
                                 set_paused=lambda value: setattr(snapshot, 'paused', value))
    calls = []
    def seek(target, accurate=True):
        calls.append((target, accurate))
        snapshot.seeking = True
    page._seek = seek
    router = TimelineScrub(page)
    router.request(0)  # press: no pause/coarse decode until actual movement
    router.request(1)
    router._flush()
    for target in range(2, 601):
        router.request(target)
        router._flush()
    assert calls == [(1., False)]
    assert router.pending == 600
    snapshot.seeking = False
    router._flush()
    router.request(605)
    router.finish(610)
    router._flush()
    assert calls == [(1., False), (600., False), (610., True)]
    assert not router.timer.isActive() and router.pending is None
    assert not page._timeline_scrub_active


def test_scrub_keeps_playing_intent_and_click_stays_immediate():
    app = QApplication.instance() or QApplication([])
    page = QObject()
    snapshot = SimpleNamespace(paused=False, seeking=False)
    pauses, seeks = [], []
    page.timeline = SimpleNamespace(_scrub_drag=False)
    page.video = SimpleNamespace(playback_position_snapshot=lambda: snapshot,
                                 set_paused=pauses.append)
    page._seek = lambda target, accurate=True: seeks.append((target, accurate))
    router = TimelineScrub(page)
    router.request(5)
    assert seeks == [(5, True)] and not pauses
    page.timeline._scrub_drag = True
    router.request(7)
    assert not pauses
    router.request(8)
    router.finish(9)
    assert pauses == [True, False]
    assert seeks[-1] == (9., True)


def test_ruler_click_uses_one_exact_seek_without_transport_toggle():
    app = QApplication.instance() or QApplication([])
    page = QObject(); pauses=[];seeks=[]
    page.timeline=SimpleNamespace(_scrub_drag=True)
    page.video=SimpleNamespace(playback_position_snapshot=lambda:SimpleNamespace(paused=False,seeking=False),set_paused=pauses.append)
    page._seek=lambda target,accurate=True:seeks.append((target,accurate))
    router=TimelineScrub(page)
    router.request(4);router._flush();router.finish(4)
    assert seeks==[(4.,True)] and pauses==[]
    assert not router.pressed and router.pending is None


def test_buffered_resume_survives_a_late_paused_observation():
    app=QApplication.instance() or QApplication([])
    page=QObject();pauses=[]
    page.timeline=SimpleNamespace(_scrub_drag=True)
    page.video=SimpleNamespace(_buffered_play_pending=True,
        playback_position_snapshot=lambda:SimpleNamespace(paused=True,seeking=False),set_paused=pauses.append)
    page._seek=lambda *args,**kwargs:None
    router=TimelineScrub(page);router.request(3)
    page.video._buffered_play_pending=False
    router.request(4);router.finish(5)
    assert pauses==[True,False]
