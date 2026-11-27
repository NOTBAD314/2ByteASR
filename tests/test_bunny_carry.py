"""「问问兔白」 carried around (2026-11-15): she stays on top. 2026-11-26: picked up, the card folds away."""
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
    # 2026-11-18: the box keeps a whole answer now, so the first-time notice makes it tall; these
    # tests carry her with a short sentence in the box, as they did when it showed one at a time.
    from twobyteasr.app import bunny_persona
    card.say(bunny_persona.BunnyReply(lines=['嗯。']))
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


def test_picked_up_her_card_folds_away_and_her_bubble_brings_it_back_beside_her(app, chat):
    """2026-11-26 (user): picked up, the dialog box folds away so she can be played with; a small
    bubble stays over her head, and one more click on it brings the box back."""
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
    assert chat.collapsed and not chat.isVisible() and puck.card_at is None
    bubble = puck.carrier.bubble
    assert bubble is not None and bubble.isVisible()
    # Over her head: above her centre of mass, and clicks on it reach it through the layer's mask.
    assert bubble.geometry().bottom() < puck.phys.pose.y
    assert puck.carrier.mask().boundingRect().contains(bubble.geometry())
    # Still an open chat: the little corner bunny does not come back meanwhile.
    from types import SimpleNamespace
    from twobyteasr.app.bunny_resident import BunnyResident
    assert getattr(window, '_bunny_chat', None) is chat and chat.open_now()
    assert BunnyResident._chat_open(SimpleNamespace(window_=window))
    assert chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, grab, target))
    # Let go, she lands and stays where she is (no card to float back to).
    assert _until(app, lambda: puck.mode == 'rest', seconds=16)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)
    assert not puck.docked and chat.collapsed and bubble.isVisible()
    # A short line of hers (a touch reaction) shows in the bubble itself.
    from twobyteasr.app import bunny_persona
    chat._asked = False
    chat.say(bunny_persona.BunnyReply(lines=['叮铃叮铃～']))
    assert bubble.text == '叮铃叮铃～' and not bubble.unread
    chat.reveal_all()
    landed = puck.pos.toPoint()           # (thrown, she bounces and rolls: where she ends up varies)
    bubble.clicked.emit()
    assert not chat.collapsed and chat.isVisible() and not bubble.isVisible()
    assert _until(app, lambda: puck.docked, seconds=8)
    assert chat.mascot.parent() is chat
    kept = chat.geometry().topLeft()
    slot = kept + chat.mascot_slot        # the card came back beside her, where she landed
    assert abs(slot.x() - landed.x()) < 40, (landed, slot, start_card)
    assert chat.mascot.geometry().topLeft() == chat.mascot_slot
    chat.relayout()                         # a new line later on: the card stays where she left it
    assert abs(chat.geometry().x() - kept.x()) < 2 and abs(chat.geometry().y() - kept.y()) < 2


def test_folded_away_a_long_answer_waits_in_the_card_with_a_dot(app, chat):
    puck = chat.puck
    puck.undock()
    chat.collapse()
    bubble = puck.carrier.bubble
    from twobyteasr.app import bunny_persona
    chat._asked = True
    chat.say(bunny_persona.BunnyReply(lines=['字幕比声音慢半秒的话，可以在字幕工作台整体往前挪。']))
    # 2026-11-27: the bubble shows how it begins; the whole answer waits in the card (the dot).
    assert bubble.unread and bubble.isVisible() and bubble.text.startswith('字幕比声音慢半秒')
    # 「问问兔白」 again: the card comes back instead of a second chat.
    from twobyteasr.app.bunny_chat import open_bunny_chat
    chat.window_._bunny_chat = chat
    assert open_bunny_chat(chat.window_) is chat
    assert not chat.collapsed and chat.isVisible() and not bubble.unread


def test_carried_she_moves_inside_one_still_layer(app, chat):
    """Second round (user): still cut to one corner while carried. (2026-11-26: the card folds away.)"""
    import math
    from PySide6.QtCore import QEvent, QPointF, QRect
    from PySide6.QtGui import QRegion
    from twobyteasr.app import ui_zoom
    from twobyteasr.app.bunny_puck import FOLD_AFTER_PX
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
        # Off the card her widget is a roomy square (turns and squash never cut her off).
        assert mascot.geometry().topLeft() == (puck.pos - mascot.room).toPoint()
        # While she moves, the layer's clickable part is a box around her (and her bubble) that holds
        # her whole rectangle; the rest of the window still gets its clicks.
        here = mascot.geometry()
        assert puck.carrier.mask().boundingRect().contains(here)
        assert puck.carrier.mask().boundingRect().width() < window.width()
        # 2026-11-26 (user): a small move keeps the card beside her; carried further it folds away.
        moved = (target - origin) * (k / 15)
        if math.hypot(moved.x(), moved.y()) > ui_zoom.px(FOLD_AFTER_PX) + 24:
            assert not chat.isVisible() and chat.collapsed
    assert layer is not None
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, grab, target))
    # (2026-11-26: a stopped timer can also mean she lies on the floor about to hop upright.)
    assert _until(app, lambda: puck.mode == 'rest' or puck.docked, seconds=16)
    if not puck.docked:
        # At rest only her drawn body and her bubble take clicks again (2026-11-26: not her roomy
        # turning box, so the controls around her stay usable now that she rests out on the page).
        rest = puck.carrier._resting_rect()
        assert mascot.geometry().contains(rest) and rest.width() < mascot.width()
        assert puck.carrier.mask() == QRegion(rest.united(puck.carrier.bubble.geometry()))


def test_a_moving_bunny_never_falls_outside_the_clickable_layer(app, chat):
    """2026-11-18 (user: she stutters or vanishes for a moment while moving): every step of a glide
    keeps both her last and her new rectangle inside the layer's mask, and the mask is not reset on
    every frame."""
    from PySide6.QtCore import QPointF, QRect
    puck, mascot = chat.puck, chat.mascot
    puck.undock()
    changes = []
    real = puck.carrier.setMask
    puck.carrier.setMask = lambda region: (changes.append(region), real(region))
    previous = QRect(mascot.geometry())
    puck.glide_to(QPointF(40, 40))
    frames = 0
    while puck.glide.state().name == 'Running' and frames < 400:
        app.processEvents()
        time.sleep(0.004)
        if puck.glide.state().name != 'Running':
            break                          # arrived within this frame: she rests (checked below)
        here = QRect(mascot.geometry())
        box = puck.carrier.mask().boundingRect()
        assert box.contains(here) and box.contains(previous), (box, here, previous)
        previous = here
        frames += 1
    assert frames > 5
    assert len(changes) < frames, (len(changes), frames)
    # At rest the mask is her drawn body inside her roomy box (2026-11-26).
    assert puck.carrier.mask().boundingRect() == puck.carrier._resting_rect()
    assert mascot.geometry().contains(puck.carrier._resting_rect())


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
    assert raised, 'out of the card she starts on top'
    raised.clear()
    from PySide6.QtCore import QPointF
    puck.card_at = QPointF(puck.pos)             # carried: the card moves along
    puck._place(puck.pos + QPointF(-30, -20))
    assert raised, 'the card moving along never buries her'
    raised.clear()
    from PySide6.QtCore import QEvent
    chat.event(QEvent(QEvent.Type.WindowActivate))
    assert raised, 'the card coming to the front does not bury her'

def test_a_small_move_keeps_the_card_and_a_gentle_put_down_stays_where_she_is(app, chat):
    """2026-11-26 (user): a click or a small move must not fold the card away, and put down gently
    she stays there (no fall to the bottom) and the chat goes on beside her."""
    from PySide6.QtCore import QEvent, QPointF
    mascot, puck = chat.mascot, chat.puck
    grab = QPointF(mascot.width() / 2, mascot.height() / 2)
    origin = QPointF(mascot.mapToGlobal(grab.toPoint()))
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, grab, origin))
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseMove, grab, origin + QPointF(5, 0)))
    assert puck.docked                                   # under the grab slop: still a click
    for k in range(1, 9):
        chat.eventFilter(mascot, _mouse(QEvent.Type.MouseMove, grab, origin + QPointF(-6 * k, -4 * k)))
        app.processEvents()
        time.sleep(0.03)
    assert not puck.docked and chat.isVisible() and not chat.collapsed
    _until(app, lambda: False, seconds=0.2)              # held still: let go without speed
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, grab, origin + QPointF(-48, -32)))
    assert puck.mode == 'glide'                          # righted in place, not thrown
    assert _until(app, lambda: puck.docked, seconds=6)
    assert chat.isVisible() and not chat.collapsed


def test_put_down_with_the_card_folded_it_comes_back_beside_her(app, chat):
    puck = chat.puck
    puck.undock()
    chat.collapse()
    puck._stay_here()
    assert puck.settle_timer.isActive() and chat.collapsed
    puck._settled()
    assert not chat.collapsed and chat.isVisible()
