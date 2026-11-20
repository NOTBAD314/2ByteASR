"""A page is shown once, finished: the old picture stays until the new page is done (2026-11-19)."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stack(app, monkeypatch):
    from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget
    from twobyteasr.design import transitions
    monkeypatch.setattr(transitions, 'enabled', lambda: True)
    pages = QStackedWidget()
    pages.resize(640, 420)
    for name in ('old', 'new'):
        page = QWidget()
        page.setObjectName(name)
        QVBoxLayout(page).addWidget(QLabel(name))
        pages.addWidget(page)
    pages.show()
    app.processEvents()
    yield pages
    transitions.end_all()
    pages.close()
    pages.deleteLater()
    app.processEvents()


def _spin(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def _switch(stack):
    from twobyteasr.design import transitions
    picture = transitions.capture_page(stack)
    assert picture is not None
    stack.setCurrentIndex(1)
    return picture


def test_the_old_picture_stays_while_the_new_page_is_still_building(app, stack):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.design import motion_tokens as tokens, transitions
    done = []
    hold = transitions.start_page_hold(stack, _switch(stack), settled=lambda: True, on_settled=lambda: done.append(1))
    new = stack.currentWidget()
    assert hold is not None and hold.phase == 'hold' and transitions.is_held(new)
    # The page keeps adding rows: it is not shown.
    until = time.monotonic() + 0.25
    while time.monotonic() < until:
        new.layout().addWidget(QLabel('row'))
        _spin(app, 0.02)
        assert hold.phase == 'hold' and not done
    # Nothing more is added: after the quiet time the fade starts, between two pictures.
    _spin(app, tokens.PAGE_SETTLE_QUIET_MS / 1000 + 0.12)
    assert done == [1] and hold.phase == 'fade' and hold.new is not None and not hold.new.isNull()
    assert not transitions.is_held(new)
    _spin(app, tokens.PAGE_CROSSFADE.ms / 1000 + 0.25)
    assert not stack.findChildren(transitions.PageHold) or not hold.isVisible()


def test_a_page_that_says_it_is_not_done_is_waited_for_up_to_the_limit(app, stack, monkeypatch):
    from twobyteasr.design import motion_tokens as tokens, transitions
    monkeypatch.setattr(tokens, 'PAGE_SETTLE_LIMIT_MS', 260)
    ready = []
    hold = transitions.start_page_hold(stack, _switch(stack), settled=lambda: bool(ready))
    _spin(app, 0.16)
    assert hold.phase == 'hold'                        # quiet, but the page is still reading its data
    ready.append(1)
    _spin(app, 0.1)
    assert hold.phase == 'fade'
    transitions.end_all()
    # A page that never says so is shown when the limit is over.
    stack.setCurrentIndex(0)
    app.processEvents()
    hold = transitions.start_page_hold(stack, _switch(stack), settled=lambda: False)
    _spin(app, 0.16)
    assert hold.phase == 'hold'
    _spin(app, 0.22)
    assert hold.phase == 'fade'


def test_a_page_that_was_shown_before_does_not_wait_and_clicks_are_kept_from_the_hidden_page(app, stack):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from twobyteasr.design import transitions
    hold = transitions.start_page_hold(stack, _switch(stack), wait=False)
    _spin(app, 0.06)
    assert hold.phase == 'fade'
    transitions.end_all()
    stack.setCurrentIndex(0)
    app.processEvents()
    hold = transitions.start_page_hold(stack, _switch(stack), settled=lambda: False)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(20, 20), QPointF(20, 20), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    press.ignore()
    hold.mousePressEvent(press)
    assert press.isAccepted() and not hold.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_ending_all_motion_removes_the_picture_and_starts_none_for_a_while(app, stack):
    from twobyteasr.design import transitions
    hold = transitions.start_page_hold(stack, _switch(stack), settled=lambda: False)
    assert hold in transitions._ACTIVE_FADES
    transitions.end_all()
    assert hold not in transitions._ACTIVE_FADES and not hold.isVisible()


def test_motion_is_off_for_the_time_asked_when_the_app_closes(app, monkeypatch):
    from twobyteasr.design import transitions
    monkeypatch.setattr(transitions, '_SUSPENDED_UNTIL', 0.0)
    monkeypatch.delenv('TWOBYTEASR_TRANSITIONS', raising=False)
    monkeypatch.setattr('twobyteasr.design.ui_motion.reduced_motion', lambda: False)
    assert transitions.enabled()
    transitions.end_all(suspend_s=0.15)
    assert not transitions.enabled()
    time.sleep(0.2)
    assert transitions.enabled()


def test_the_model_list_is_built_in_one_turn_and_without_its_own_fade_behind_a_held_page(app, stack, monkeypatch):
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
    from twobyteasr.design import transitions
    from twobyteasr.local_models.model_loading_surface import ModelListReveal

    class Card(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self._card = None

        def materialize(self):
            time.sleep(0.003)                          # two of them fill one visible step (4 ms)
            self._card = object()

    new = stack.widget(1)
    scroll = QScrollArea()
    body = QWidget()
    column = QVBoxLayout(body)
    cards = {index: Card(body) for index in range(6)}
    for card in cards.values():
        column.addWidget(card)
    scroll.setWidget(body)
    new.layout().addWidget(scroll)
    reveal = ModelListReveal(scroll, cards)
    transitions.start_page_hold(stack, _switch(stack), settled=lambda: not reveal.building)
    app.processEvents()
    assert reveal.building or reveal.ready
    _spin(app, 0.03)
    assert all(card._card is not None for card in cards.values())     # one turn, not three
    _spin(app, 0.03)
    assert reveal.ready and not reveal.building and not reveal.veil.isVisible()
