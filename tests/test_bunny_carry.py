"""「问问兔白」 carried around (2026-11-15): the chat card comes along, and she stays on top."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def chat(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_chat, bunny_puck
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    monkeypatch.setattr(bunny_puck, 'REST_BEFORE_HOME_MS', 50)
    window = QWidget()
    window.resize(1100, 720)
    window.show()
    app.processEvents()
    card = bunny_chat.open_bunny_chat(window)
    card.reveal_all()
    if card.puck is None:
        pytest.skip('no mascot pictures in this build')
    yield card
    card.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def _mouse(kind, local, global_point):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    held = kind.name != 'MouseButtonRelease'
    return QMouseEvent(kind, QPointF(local), QPointF(global_point),
                       Qt.MouseButton.LeftButton if kind.name != 'MouseMove' else Qt.MouseButton.NoButton,
                       Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


def test_carrying_her_brings_the_card_along_and_it_stays_there(app, chat):
    from PySide6.QtCore import QEvent, QPointF
    mascot, puck = chat.mascot, chat.puck
    window = chat.window_
    start_card = chat.geometry().topLeft()
    grab = QPointF(mascot.width() / 2, mascot.height() / 2)
    origin = QPointF(mascot.mapToGlobal(grab.toPoint()))
    assert chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, grab, origin))
    # Up and to the left, well away from the card's corner.
    target = QPointF(window.mapToGlobal(window.rect().topLeft())) + QPointF(260, 160)
    for k in range(1, 11):
        point = origin + (target - origin) * (k / 10)
        chat.eventFilter(mascot, _mouse(QEvent.Type.MouseMove, grab, point))
        app.processEvents()
        time.sleep(0.02)
    assert not puck.docked
    # Let her catch up with the pointer and the card catch up with her.
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    moved = chat.geometry().topLeft()
    assert moved.x() < start_card.x() - 200 and moved.y() < start_card.y() - 150, (start_card, moved)
    # No room for the box on her left this close to the edge: she stands left of it, the tail points at her.
    assert chat.flipped and chat.box.flipped and chat.mascot_slot.x() == 0
    assert chat.box.geometry().left() > mascot.width() // 2
    slot = chat.geometry().topLeft() + chat.mascot_slot
    assert abs(slot.x() - puck.pos.x()) < 40 and abs(slot.y() - puck.pos.y()) < 40
    assert chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, grab, target))
    assert _until(app, lambda: puck.docked, seconds=8)
    assert chat.mascot.parent() is chat and puck.card_at is None
    kept = chat.geometry().topLeft()
    assert kept.x() < start_card.x() - 150 and kept.y() < start_card.y() - 100, (start_card, kept)
    assert chat.mascot.geometry().topLeft() == chat.mascot_slot     # docked on the left side
    chat.relayout()                         # a new line later on: the card stays where she left it
    assert abs(chat.geometry().x() - kept.x()) < 2 and abs(chat.geometry().y() - kept.y()) < 2


def test_carried_she_moves_inside_one_still_layer_and_the_card_keeps_step(app, chat):
    """Second round (user): still cut to one corner while carried, and the card a beat behind."""
    from PySide6.QtCore import QEvent, QPointF, QRect
    from PySide6.QtGui import QRegion
    mascot, puck = chat.mascot, chat.puck
    window = chat.window_
    grab = QPointF(mascot.width() / 2, mascot.height() / 2)
    origin = QPointF(mascot.mapToGlobal(grab.toPoint()))
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, grab, origin))
    target = QPointF(window.mapToGlobal(window.rect().center()))
    layer = None
    for k in range(1, 16):
        chat.eventFilter(mascot, _mouse(QEvent.Type.MouseMove, grab, origin + (target - origin) * (k / 15)))
        app.processEvents()
        time.sleep(0.016)
        if puck.docked:
            continue
        # The layer lies over the whole window and never moves; she moves inside it.
        assert puck.carrier.geometry() == window.rect()
        layer = layer or puck.carrier.geometry()
        assert puck.carrier.geometry() == layer and mascot.parent() is puck.carrier
        assert mascot.geometry().topLeft() == puck.pos.toPoint()
        # Only her rectangle takes clicks; everything else reaches the window under it.
        assert puck.carrier.mask() == QRegion(QRect(puck.pos.toPoint(), mascot.size()))
        # The card is exactly where she is, in the same frame.
        slot = chat.geometry().topLeft() + chat.mascot_slot
        if chat._home_rect().topLeft() == chat.geometry().topLeft():      # not held back by the window's edge
            assert slot == puck.pos.toPoint(), (slot, puck.pos)
    assert layer is not None
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, grab, target))


def test_before_her_layers_are_ready_she_is_drawn_at_her_real_size(app):
    """User (2026-11-15): on opening she was huge for a moment, then normal (the face crop, blown up)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from twobyteasr.design.bunny_mascot import BunnyMascot
    mascot = BunnyMascot(None, height=180)
    if not mascot.available:
        pytest.skip('no mascot pictures in this build')
    mascot._layers = lambda: None
    mascot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    image = mascot.grab().toImage()
    xs, ys = [], []
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if QColor(image.pixel(x, y)).alpha() > 40 and image.pixelColor(x, y) != image.pixelColor(0, 0):
                xs.append(x)
                ys.append(y)
    assert xs, 'something is drawn while the layers are prepared'
    drawn_w, drawn_h = max(xs) - min(xs), max(ys) - min(ys)
    assert drawn_h <= mascot.mascot_height + 4
    assert drawn_w <= mascot.trim[2] * mascot.scale + 4, (drawn_w, mascot.trim[2] * mascot.scale)
    assert drawn_h >= mascot.mascot_height * 0.8          # the whole bunny, not a tiny or cropped one
    mascot.deleteLater()


def test_carried_back_to_the_right_the_card_turns_back(app, chat):
    from PySide6.QtCore import QPointF
    chat.follow_bunny(QPointF(20, 300))
    assert chat.flipped
    chat.follow_bunny(QPointF(chat.window_.width() - chat.mascot.width() - 10, 300))
    assert not chat.flipped and chat.mascot_slot.x() > 0


def test_drifting_to_show_a_place_leaves_the_card_where_it_is(app, chat, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app import bunny_puck
    monkeypatch.setattr(bunny_puck, 'DRIFT_MS', 60)
    window = chat.window_
    button = QPushButton('模型工坊', window)
    button.setGeometry(40, 20, 90, 28)
    button.show()
    before = chat.geometry().topLeft()
    assert chat.puck.drift_to(button)
    assert _until(app, lambda: chat.puck.glide.state().name == 'Stopped', seconds=3)
    assert chat.geometry().topLeft() == before and chat.puck.card_at is None


def test_out_on_her_own_she_is_kept_above_the_card(app, chat, monkeypatch):
    puck = chat.puck
    raised = []
    monkeypatch.setattr(puck.carrier, 'raise_', lambda: raised.append(1))
    puck.undock()
    raised.clear()
    puck._place(puck.pos)
    assert raised, 'every move puts her back on top'
    raised.clear()
    from PySide6.QtCore import QEvent
    chat.event(QEvent(QEvent.Type.WindowActivate))
    assert raised, 'the card coming to the front does not bury her'
