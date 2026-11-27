"""兔白 while a project opens: the loading card is a scene of its own (2026-11-27).

User (2026-11-27): on the studio's loading card she still roamed as on Home, and a second bunny
sat on the card. Now she sits on the card and stays put; its own bunny steps aside.
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


def _loading(app, win, tmp_path):
    from twobyteasr.studio.studio_loading import StudioLoadingSession
    project = tmp_path / '未命名工程 14' / '识别结果.2byteproj'
    project.parent.mkdir(parents=True)
    project.write_text('{}', encoding='utf-8')
    session = win._studio_loading_session = StudioLoadingSession(win)
    session.begin(str(project))
    session.view.setGeometry(win.rect())
    session.view.show()
    session.view.raise_()
    app.processEvents()
    return session


def test_on_the_loading_card_she_sits_on_it_and_stays_put(app, window, tmp_path, monkeypatch):
    chat = _folded(window)
    errands, mascot = chat.errands, chat.mascot
    assert _until(app, lambda: not mascot.entering() and not mascot.current_move, seconds=4)
    assert errands.context() == 'home'
    session = _loading(app, window, tmp_path)
    view = session.view
    assert errands.context() == 'loading'
    assert errands.candidates() == [], 'no errands on the loading card'
    assert not errands._watchable(), 'no pounces either'
    choice = errands.pick()
    assert choice == ('loading_seat', view)
    errands.input_at = 0.0
    assert _until(app, lambda: errands.name == 'loading_seat' and view.live_bunny, seconds=6), \
        'she goes over and sits on the card'
    assert not view.perch.isVisible(), "the card's own bunny steps aside: one bunny, not two"
    spot = errands._loading_seat_spot(view)
    assert spot is not None and abs(chat.puck.pos.x() - spot.x()) < 2 and abs(chat.puck.pos.y() - spot.y()) < 2
    seated_at = chat.puck.pos
    # She stays put: no fidget, no wander, for a while.
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert chat.puck.pos == seated_at and errands.name == 'loading_seat'
    # Opening fails: she is sad with the card and says so.
    session.fail('准备播放器', '准备超时；请检查素材和播放器状态。')
    assert errands.context() == 'loading'
    assert _until(app, lambda: mascot.mood == 'sad', seconds=3)
    # The card goes: she is free again and the card's bunny is back on the (hidden) card.
    session.abort()
    view.hide()
    assert _until(app, lambda: errands.context() == 'home' and errands.name != 'loading_seat', seconds=3)
    assert not view.live_bunny and mascot.mood == 'idle'


def test_a_page_change_behind_the_card_does_not_unseat_her(app, window, tmp_path):
    from PySide6.QtWidgets import QWidget
    chat = _folded(window)
    errands = chat.errands
    assert _until(app, lambda: not chat.mascot.entering() and not chat.mascot.current_move, seconds=4)
    session = _loading(app, window, tmp_path)
    errands.input_at = 0.0
    assert _until(app, lambda: session.view.live_bunny, seconds=6)
    other = QWidget()
    window.pages.addWidget(other)
    window.pages.setCurrentWidget(other)
    app.processEvents()
    assert errands.name == 'loading_seat' and session.view.live_bunny


def test_the_loading_view_hides_its_bunny_only_while_she_sits_there(app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.studio.studio_loading import StudioLoadingSession
    host = QWidget()
    host.resize(1400, 860)
    view = StudioLoadingSession(host).view
    if not view.perch.available:
        pytest.skip('no mascot pictures in this build')
    view.set_mode(library=False)
    assert not view.perch.isHidden()
    view.set_live_bunny(True)
    assert view.perch.isHidden()
    view.set_mode(library=False)               # a new request keeps her seat
    assert view.perch.isHidden()
    view.set_live_bunny(False)
    assert not view.perch.isHidden()
    host.deleteLater()
