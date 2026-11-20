"""App-wide smooth wheel scrolling (2026-11-18, the calm feel 「A 沉穩」)."""
from __future__ import annotations

import time

import pytest


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design.smooth_scroll import install
    install(app)
    return app


def _wheel(widget, notches=-1, modifiers=None, pixel=None):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), pixel or QPoint(), QPoint(0, 120 * notches),
                        Qt.MouseButton.NoButton, modifiers or Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


def _area(content_height=4000, cls=None):
    from PySide6.QtWidgets import QLabel, QScrollArea
    area = (cls or QScrollArea)()
    label = QLabel('x')
    label.setFixedSize(300, content_height)
    area.setWidget(label)
    area.resize(320, 300)
    area.show()
    return area


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def test_a_notch_glides_the_same_distance_qt_would_jump(app):
    from PySide6.QtWidgets import QApplication
    area = _area()
    bar = area.verticalScrollBar()
    expected = QApplication.wheelScrollLines() * bar.singleStep()
    _wheel(area.viewport(), -1)
    assert bar.value() == 0                                  # nothing jumps on the event itself
    seen = []
    end = time.time() + 1.2
    while time.time() < end:
        app.processEvents()
        seen.append(bar.value())
        time.sleep(0.004)
    assert seen[-1] == expected
    assert len(set(seen)) > 4                                # several in-between positions
    assert seen == sorted(seen)                              # always forward: no overshoot back
    assert max(seen) == expected
    area.deleteLater()


def test_fast_spins_add_up(app):
    from PySide6.QtWidgets import QApplication
    area = _area()
    bar = area.verticalScrollBar()
    for _ in range(4):
        _wheel(area.viewport(), -1)
        _pump(app, 0.02)
    _pump(app, 1.2)
    assert bar.value() == 4 * QApplication.wheelScrollLines() * bar.singleStep()
    area.deleteLater()


def test_modifiers_and_touchpad_pixels_are_left_to_qt(app):
    from PySide6.QtCore import QPoint, Qt
    from twobyteasr.design.smooth_scroll import SmoothScroller
    area = _area()
    scroller = app._smooth_scroller
    assert isinstance(scroller, SmoothScroller)
    _wheel(area.viewport(), -1, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert not scroller.gliding(area.verticalScrollBar())
    _wheel(area.viewport(), -1, pixel=QPoint(0, -40))
    assert not scroller.gliding(area.verticalScrollBar())
    area.deleteLater()


def test_scroll_areas_with_their_own_wheel_keep_it(app):
    from PySide6.QtWidgets import QPlainTextEdit, QScrollArea
    from twobyteasr.design.smooth_scroll import scroll_area_for

    class Zooming(QScrollArea):
        def wheelEvent(self, event):  # noqa: N802
            event.accept()

    zooming = _area(cls=Zooming)
    assert scroll_area_for(zooming.viewport()) is None
    plain = QPlainTextEdit('\n'.join(str(i) for i in range(500)))
    assert scroll_area_for(plain.viewport()) is None              # its bar counts lines
    opted_out = _area()
    opted_out.setProperty('smoothScroll', False)
    assert scroll_area_for(opted_out.viewport()) is None
    plain_area = _area()
    assert scroll_area_for(plain_area.viewport()) is plain_area
    assert scroll_area_for(plain_area.widget()) is None           # only at the viewport
    for widget in (zooming, plain, opted_out, plain_area):
        widget.deleteLater()


def test_at_the_end_the_wheel_still_reaches_an_outer_area(app):
    area = _area()
    bar = area.verticalScrollBar()
    event = _wheel(area.viewport(), +1)                            # wheel up at the top
    assert not app._smooth_scroller.gliding(bar) and bar.value() == 0
    area.deleteLater()


def test_dragging_the_bar_during_a_glide_takes_over(app):
    area = _area()
    bar = area.verticalScrollBar()
    for _ in range(5):
        _wheel(area.viewport(), -1)
    _pump(app, 0.05)
    assert app._smooth_scroller.gliding(bar)
    bar.setValue(1000)                                             # the user (or code) moved it
    _pump(app, 0.3)
    assert bar.value() == 1000 and not app._smooth_scroller.gliding(bar)
    area.deleteLater()


def test_reduced_motion_scrolls_the_qt_way(app, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_SMOOTH_SCROLL', '0')
    area = _area()
    _wheel(area.viewport(), -1)
    assert not app._smooth_scroller.gliding(area.verticalScrollBar())
    area.deleteLater()


def test_custom_lists_with_their_own_bar_glide_too(app):
    """The proofread list, completion preview and Studio highlight cards keep their own scroll bar."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollBar
    from twobyteasr.design.smooth_scroll import glide_wheel
    bar = QScrollBar(Qt.Orientation.Vertical)
    bar.setRange(0, 2000)
    bar.show()

    class Event:
        def __init__(self): self.accepted = False
        def angleDelta(self):
            from PySide6.QtCore import QPoint
            return QPoint(0, -120)
        def pixelDelta(self):
            from PySide6.QtCore import QPoint
            return QPoint()
        def phase(self): return Qt.ScrollPhase.NoScrollPhase
        def modifiers(self): return Qt.KeyboardModifier.NoModifier
        def accept(self): self.accepted = True

    event = Event()
    glide_wheel(bar, event, 90)
    assert event.accepted and bar.value() == 0 and app._smooth_scroller.gliding(bar)
    _pump(app, 1.0)
    assert bar.value() == 90
    bar.deleteLater()


def test_the_term_library_card_view_is_smoothed_and_keeps_its_restore_cancel(app):
    from twobyteasr.design.smooth_scroll import _handles_wheel_itself
    from twobyteasr.glossary.glossary_term_cards import TermCardView
    assert TermCardView.smooth_wheel is True and callable(TermCardView.on_smooth_wheel)
    view = TermCardView.__new__(TermCardView)            # the class decides; no model needed
    assert not _handles_wheel_itself(view)


def test_the_studio_caption_list_scrolls_by_pixel(app):
    from PySide6.QtWidgets import QAbstractItemView
    from twobyteasr.studio.studio_workspace import ResponsiveCueTableView
    view = ResponsiveCueTableView()
    assert view.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    view.deleteLater()


def test_the_real_app_turns_it_on_at_startup():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'quick_start.py').read_text('utf-8')
    assert 'install_smooth_scroll(app)' in source
