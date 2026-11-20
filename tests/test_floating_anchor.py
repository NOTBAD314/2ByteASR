"""Small windows over the main window are placed and dragged in physical pixels (2026-11-19)."""
from __future__ import annotations

import pytest

from twobyteasr.app import bunny_events, floating_anchor


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_points_and_pixels_convert_both_ways_at_any_scale():
    from PySide6.QtCore import QPoint
    for scale in (1.0, 1.25, 1.75):
        frame = (3840, -521, 1890, 1400)               # a client area on a screen right of the main one
        x, y = floating_anchor.to_pixels(frame, scale, QPoint(200, 120))
        assert (x, y) == (3840 + round(200 * scale), -521 + round(120 * scale))
        back = floating_anchor.to_window(frame, scale, x, y)
        assert abs(back.x() - 200) < 1 and abs(back.y() - 120) < 1


def test_a_box_is_kept_inside_the_client_area_in_pixels():
    frame = (100, 50, 800, 600)
    assert floating_anchor.keep_inside(frame, 5000, 5000, 160, 190) == (100 + 800 - 160, 50 + 600 - 190)
    assert floating_anchor.keep_inside(frame, -5000, -5000, 160, 190) == (100, 50)       # never the far corner
    assert floating_anchor.keep_inside(frame, 300, 200, 160, 190) == (300, 200)
    assert floating_anchor.keep_inside(frame, 300, 200, 2000, 2000) == (100, 50)         # larger than the area


class _Screen:
    def __init__(self, x, y, factor):
        from PySide6.QtCore import QRect
        self._geometry, self._factor = QRect(x, y, 1000, 800), factor

    def geometry(self):
        return self._geometry

    def devicePixelRatio(self):  # noqa: N802 - Qt's name
        return self._factor


class _Handle:
    def __init__(self, screen):
        self._screen = screen

    def screen(self):
        return self._screen


class _Widget:
    def __init__(self, screen):
        self._handle = _Handle(screen)

    def window(self):
        return self

    def windowHandle(self):  # noqa: N802 - Qt's name
        return self._handle


class _Event:
    def __init__(self, x, y):
        from PySide6.QtCore import QPointF
        self._at = QPointF(x, y)

    def globalPosition(self):  # noqa: N802 - Qt's name
        return self._at


def test_an_event_position_is_turned_back_into_pixels_with_the_screen_qt_used_for_it():
    # The same physical point (4200, 300) as Qt reports it for a window on either screen: with the
    # 100 % screen at x=3840 it is 4200; with the 175 % main screen it is 4200 / 1.75 = 2400.
    on_side = floating_anchor.event_pixels(_Widget(_Screen(3840, 0, 1.0)), _Event(4200, 300))
    on_main = floating_anchor.event_pixels(_Widget(_Screen(0, 0, 1.75)), _Event(2400, 300 / 1.75))
    assert on_side == pytest.approx((4200, 300))
    assert on_main == pytest.approx((4200, 300))


def test_without_a_native_window_qt_places_and_the_event_gives_the_pointer(app):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QWidget
    window = QWidget()
    window.resize(800, 600)
    window.show()
    small = QWidget(window, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    small.resize(80, 90)
    try:
        assert floating_anchor.client_pixels(window) is None          # the offscreen platform
        assert floating_anchor.cursor_point(window) is None
        floating_anchor.place(small, window, QPoint(300, 200))
        assert small.pos() == window.mapToGlobal(QPoint(300, 200))
        floating_anchor.cover_window(small, window)
        assert small.size() == window.size() and small.pos() == window.mapToGlobal(QPoint(0, 0))
        at = QPointF(window.mapToGlobal(QPoint(120, 80)))
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), at, Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        pointer = floating_anchor.Pointer(window, small, press)
        assert not pointer.real
        assert pointer.at(press).toPoint() == QPoint(120, 80)
    finally:
        small.close()
        window.close()


def test_a_place_kept_before_the_fix_is_not_used_again():
    from twobyteasr.app.onboarding import load_state, save_state
    state = {key: value for key, value in load_state().items() if key != bunny_events.KEY}
    try:
        save_state(dict(state, **{bunny_events.KEY: {'resident': True, 'place': [-1200, -700]}}))
        assert bunny_events.load()['place'] is None                   # the corner a wrong jump left her in
        bunny_events.save({'place': [-240, -90]})
        assert bunny_events.load()['place'] == [-240, -90]
        bunny_events.save({'mode': 'errors'})                         # another choice keeps her place
        assert bunny_events.load()['place'] == [-240, -90]
    finally:
        save_state(state)


def test_places_asked_for_in_a_burst_run_once_per_frame_and_slower_when_costly(app):
    """2026-11-19 (user: opening a project in the workbench froze; the samples were in SetWindowPos,
    one per mouse move of 兔白's drag)."""
    import time
    from PySide6.QtCore import QObject
    owner, runs = QObject(), []
    cost = [0.0]

    def apply():
        runs.append(time.perf_counter())
        time.sleep(cost[0])
    placer = floating_anchor.Coalesced(owner, apply)
    for _ in range(500):
        placer.request()
    assert runs == [] and placer.pending()                 # never inside the events that asked
    deadline = time.monotonic() + 1
    while placer.pending() and time.monotonic() < deadline:
        app.processEvents()
    assert len(runs) == 1 and placer.runs == 1
    placer.request()
    assert placer._timer.interval() >= floating_anchor.FOLLOW_FRAME_MS // 2     # the next one a frame later
    placer.flush()                                         # a drag that ended: now
    assert len(runs) == 2 and not placer.pending()
    cost[0] = 0.03                                         # a native move this slow on that machine
    placer.request()
    placer.flush()
    placer.request()
    assert placer._timer.interval() >= (0.03 / floating_anchor.FOLLOW_SHARE - 0.03) * 1000 - 5   # at most 40 % of the time
    placer.cancel()
    assert len(runs) == 3 and not placer.pending()