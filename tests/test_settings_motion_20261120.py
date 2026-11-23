"""Settings window motion (2026-11-20).

User: switching pages in the settings flashed a black frame first, and the window opened at a low
frame rate, slowly. Measured in a real start: the old page's picture was black (the window is
translucent, and copying a layered window's pixels gives black); opened soon after a start, the
growth ran at 24 fps with 70-110 ms gaps, or ended in a jump.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QVBoxLayout, QWidget


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design import transitions
    transitions.install(app)
    return app


def _translucent_stack():
    window = QWidget()
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.resize(420, 320)
    layout = QVBoxLayout(window)
    stack = QStackedWidget()
    for color in ('#d04040', '#4060d0'):
        page = QLabel('page')
        page.setStyleSheet(f'background: {color};')
        stack.addWidget(page)
    layout.addWidget(stack)
    window.show()
    QApplication.processEvents()
    return window, stack


def test_a_translucent_window_gives_its_page_picture_not_black(app, monkeypatch):
    from twobyteasr.design import transitions
    monkeypatch.setattr(transitions, 'enabled', lambda: True)
    window, stack = _translucent_stack()
    picture = transitions.capture_region(stack)
    assert picture is not None
    centre = picture.toImage().pixelColor(picture.width() // 2, picture.height() // 2)
    assert centre == QColor('#d04040')
    window.deleteLater()


def test_the_settings_copy_the_old_page_before_the_switch(app, monkeypatch, tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from twobyteasr.design import transitions
    dialog = ApplicationSettingsDialog(None, {}, tmp_path / 'Projects', browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.show()
    app.processEvents()
    monkeypatch.setattr(transitions, 'enabled', lambda: True)
    seen, faded = [], []
    capture, crossfade = transitions.capture_page, transitions.start_page_crossfade
    monkeypatch.setattr(transitions, 'capture_page',
                        lambda stack: seen.append(stack.currentIndex()) or capture(stack))
    monkeypatch.setattr(transitions, 'start_page_crossfade',
                        lambda stack, picture: faded.append((stack.currentIndex(), picture)) or crossfade(stack, picture))
    before = dialog.pages.currentIndex()
    dialog.navigation.setCurrentRow(2)
    app.processEvents()
    # Copied while the old page was shown; one fade only (the app-wide page fade stood down).
    assert seen == [before] and len(faded) == 1 and faded[0][0] == 2 and faded[0][1] is not None
    dialog.reject()
    dialog.deleteLater()


def test_idle_preparation_waits_while_a_dialog_is_open_or_moving(app, monkeypatch):
    from twobyteasr.app import idle_prepare
    from twobyteasr.design import transitions
    monkeypatch.setattr(app, '_spring_visible_dialogs', [], raising=False)
    monkeypatch.setattr(transitions, '_ACTIVE_FADES', set())
    assert not idle_prepare._dialog_or_motion()
    app._spring_visible_dialogs = [object()]
    assert idle_prepare._dialog_or_motion()
    app._spring_visible_dialogs = []
    monkeypatch.setattr(transitions, '_ACTIVE_FADES', {object()})
    assert idle_prepare._dialog_or_motion() and transitions.motion_playing()


def test_the_dim_draws_a_held_picture_of_the_window_while_it_fades(app, monkeypatch):
    from twobyteasr.design import main_ui_dialogs, transitions
    from twobyteasr.design import motion_tokens as tokens
    monkeypatch.setattr(transitions, 'enabled', lambda: True)
    host = QWidget()
    host.resize(300, 200)
    child = QLabel('home', host)
    child.setGeometry(0, 0, 300, 200)
    child.setStyleSheet('background: #20a020;')
    host.show()
    app.processEvents()
    painted = []
    original = QLabel.paintEvent
    monkeypatch.setattr(child, 'paintEvent', lambda event: painted.append(1) or original(child, event))
    backdrop = main_ui_dialogs._FadingBackdrop(host, '#000000')
    backdrop.setGeometry(host.rect())
    backdrop.show()
    done = []
    backdrop.fade_to(140, tokens.SCRIM_IN, then=lambda: done.append(1))
    held = backdrop._under
    assert held is not None and backdrop.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    # The held picture is the window without the dim itself.
    assert held.toImage().pixelColor(150, 100) == QColor('#20a020')
    painted.clear()
    end = time.time() + 0.5
    while time.time() < end and not done:
        app.processEvents()
        time.sleep(0.005)
    assert done and backdrop._under is None
    assert not backdrop.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert len(painted) <= 2                     # the window under the dim was not drawn every step
    host.deleteLater()


def test_a_late_frame_moves_the_dialog_one_frame_instead_of_ending_it(app):
    from twobyteasr.design import transitions
    from twobyteasr.design import motion_tokens as tokens
    motion = transitions.DialogMotion(app)
    dropped, advanced = [], []

    class Flight:
        opening = False
        dialog = None

        def advance(self, dt):
            advanced.append(dt)
            return True

    motion._flights[1] = Flight()
    motion._drop = lambda key, restore: (dropped.append(key), motion._flights.pop(key, None))
    motion._timer.setInterval(16)
    motion._last = time.perf_counter() - 0.2      # a 200 ms stall
    motion._late = 0
    motion._step()
    assert dropped == [] and advanced == [pytest.approx(0.016)]
    for _ in range(tokens.MAX_LATE_FRAMES):
        motion._last = time.perf_counter() - 0.2
        motion._step()
    assert dropped == [1]                         # a GUI thread that stays busy still ends it


def test_bunny_layers_wait_while_a_motion_plays_but_never_for_long(monkeypatch):
    from twobyteasr.design import mascot_assets, transitions
    playing = [True]
    monkeypatch.setattr(transitions, 'motion_playing', lambda: playing[0])
    began = time.monotonic()
    mascot_assets._wait_for_quiet(began + 0.12)
    assert 0.1 <= time.monotonic() - began < 0.5
    playing[0] = False
    began = time.monotonic()
    mascot_assets._wait_for_quiet(began + 5)
    assert time.monotonic() - began < 0.05
