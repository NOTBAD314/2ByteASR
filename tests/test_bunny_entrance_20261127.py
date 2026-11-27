"""兔白's entrance at start (2026-11-27).

User (2026-11-27): at start she popped in two or three seconds late. Now she fades in rising a
little into place, then waves (motion_tokens, no bounce), drawn whole so nothing shows through.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=6.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def window(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QStackedWidget, QWidget
    from twobyteasr.app import bunny_chat, bunny_errands, bunny_puck
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    monkeypatch.setattr(bunny_puck, 'REST_BEFORE_HOME_MS', 50)
    monkeypatch.setattr(bunny_puck, 'SETTLE_MS', 60)
    monkeypatch.setattr(bunny_errands, 'PACE', 0.05)
    win = QWidget()
    win.resize(1400, 860)
    win.pages = QStackedWidget(win)
    win.pages.setGeometry(0, 0, 1400, 860)
    win.settings_scroll = QWidget()
    win.start_button = QPushButton('开始生成字幕', win.settings_scroll)
    win.start_button.setGeometry(900, 700, 200, 44)
    for name, x in (('media_frame', 80), ('home_process_card', 520)):
        card = QPushButton(name, win.settings_scroll)
        card.setGeometry(x, 300, 380, 220)
        setattr(win, name, card)
    win.pages.addWidget(win.settings_scroll)
    win.show()
    app.processEvents()
    yield win
    chat = getattr(win, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    win.close()
    win.deleteLater()
    app.processEvents()


def _folded(win):
    from twobyteasr.app import bunny_chat
    chat = bunny_chat.show_bunny(win)
    if chat is None:
        pytest.skip('no mascot pictures in this build')
    return chat


def test_she_fades_in_rising_into_place_then_waves_without_a_hop(app, window):
    from twobyteasr.design import motion_tokens
    chat = _folded(window)
    mascot = chat.mascot
    assert mascot.entering(), 'she enters instead of popping in'
    assert mascot._hop_from < 0, 'no hop at start (calm, no bounce)'
    entrance = mascot._entrance
    assert entrance['tween'] == motion_tokens.BUNNY_ENTER
    entrance['started'] = 100.0
    frames = [mascot._entrance_step(100.0 + ms / 1000.0) for ms in range(0, motion_tokens.BUNNY_ENTER.ms, 20)]
    opacity = [frame[0] for frame in frames]
    rise = [frame[1] for frame in frames]
    assert opacity[0] == pytest.approx(0.0, abs=.02) and rise[0] == pytest.approx(entrance['rise'], abs=.5)
    assert all(b >= a for a, b in zip(opacity, opacity[1:])), 'the fade never goes back'
    assert all(0.0 <= value <= 1.0 for value in opacity) and all(value >= 0.0 for value in rise), 'no overshoot'
    assert mascot._entrance_step(100.0 + motion_tokens.BUNNY_ENTER.ms / 1000.0 + .01) is None
    assert not mascot.entering()
    # The wave was cued while she settled in.
    assert _until(app, lambda: mascot.current_move != '' , seconds=2)


def test_fading_in_she_is_see_through_as_a_whole_not_layer_by_layer(app, window):
    """Layer by layer at half opacity, her face showed through her hair (a real start, 2026-11-27)."""
    from twobyteasr.design import motion_tokens
    chat = _folded(window)
    mascot = chat.mascot
    assert _until(app, lambda: mascot._layers() is not None, seconds=6)
    assert _until(app, lambda: not mascot.entering() and not mascot.current_move, seconds=4)
    mascot.enter(motion_tokens.BUNNY_ENTER, 0)
    now = [500.0]
    mascot.clock = lambda: now[0]
    mascot._entrance['started'] = 500.0
    curve = mascot._entrance['curve']
    k = next(i / 100 for i in range(100) if curve.valueForProgress(i / 100) >= .5)
    now[0] = 500.0 + k * motion_tokens.BUNNY_ENTER.ms / 1000.0
    half = mascot.grab().toImage()
    opacity = curve.valueForProgress(k)
    alphas = [half.pixelColor(x, y).alpha() for x in range(0, half.width(), 3) for y in range(0, half.height(), 3)]
    assert max(alphas) > 0, 'she is drawn while fading in'
    assert max(alphas) <= round(255 * opacity) + 2, 'no part of her is more opaque than the fade'


def test_the_entrance_waits_for_her_real_layers(app, window, monkeypatch):
    from twobyteasr.design import bunny_mascot, motion_tokens
    chat = _folded(window)
    mascot = chat.mascot
    mascot.enter(motion_tokens.BUNNY_ENTER, 18)
    monkeypatch.setattr(mascot, '_layers', lambda: None)
    mascot.repaint()
    assert mascot._entrance['started'] is None, 'the clock waits for her first real frame'
    mascot._entrance['asked'] -= bunny_mascot.ENTRANCE_WAIT_S + 1
    mascot.repaint()
    assert not mascot.entering(), 'layers that never come do not keep her hidden'
