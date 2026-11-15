"""兔白's moves, stickers and reactions (2026-11-14): the library, the mascot engine, the chat's use."""
from __future__ import annotations

import json
import time

import pytest

from twobyteasr.design.bunny_moves import ACTS, MOVES, STICKERS, Pose


@pytest.fixture(autouse=True)
def no_saved_chats():
    """2026-11-16: each project's chat is kept; a test never inherits another test's chat."""
    from twobyteasr.app import bunny_memory
    bunny_memory.clear_chats()
    yield
    bunny_memory.clear_chats()


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_move_gives_a_pose_and_settles_back():
    for name, move in MOVES.items():
        for step in range(21):
            pose = move.pose(step / 20, step / 20 * move.seconds)
            assert isinstance(pose, Pose), name
        if not move.loop and name not in ('peek', 'dizzy'):
            end = move.pose(1.0, move.seconds)
            assert abs(end.dx) < 1 and abs(end.dy) < 2 and abs(end.turn) < 1.5, name     # ends where it began


def test_every_reaction_names_a_real_move_and_sticker():
    for name, act in ACTS.items():
        assert not act.move or act.move in MOVES, name
        assert not act.sticker or act.sticker in STICKERS, name
        assert act.title and act.when, name
    assert len(MOVES) >= 32 and len(STICKERS) == 18
    pairs = [(act.move, act.sticker) for act in ACTS.values()]
    assert len(pairs) == len(set(pairs)), 'two reactions look exactly the same'


def test_the_ai_can_pick_a_reaction_and_only_a_listed_one():
    from twobyteasr.app import bunny_lore, bunny_persona
    keys = [key for key, _t, _w in bunny_lore.feature_index()]
    assert bunny_persona.parse_reply('{"lines": ["欧耶"], "act": "cheer"}', keys).act == 'cheer'
    assert bunny_persona.parse_reply('{"lines": ["好"], "act": "explode"}', keys).act == ''
    prompt = bunny_persona.system_prompt(bunny_lore.feature_index())
    assert '# 可以做的动作（act）' in prompt and 'cheer=欢呼' in prompt


@pytest.fixture
def mascot(app):
    from twobyteasr.design.bunny_mascot import BunnyMascot
    bunny = BunnyMascot(height=120)
    bunny.reduced_motion = False
    clock = {'now': 100.0}
    bunny.clock = lambda: clock['now']
    bunny.test_clock = clock
    return bunny


def test_moves_and_stickers_run_their_time_and_loops_stay(mascot):
    clock = mascot.test_clock
    assert mascot.act('cheer') and mascot.current_move == 'cheer' and mascot.stickers == ['confetti']
    clock['now'] += MOVES['cheer'].seconds + 0.1
    assert mascot._pose(clock['now']) is None and mascot.current_move == ''
    clock['now'] += STICKERS['confetti'].seconds
    assert mascot._live_stickers(clock['now']) == []
    mascot.play('think')
    mascot.stick('dots')
    clock['now'] += 30
    assert mascot._pose(clock['now']) is not None and mascot._live_stickers(clock['now'])
    mascot.stop_move('think')
    mascot.unstick('dots')
    assert mascot.current_move == '' and mascot.stickers == []
    assert not mascot.play('no_such_move') and not mascot.stick('no_such_sticker') and not mascot.act('nope')


def test_reduced_motion_plays_nothing(mascot):
    mascot.reduced_motion = True
    assert not mascot.play('dance') and not mascot.stick('heart')


def test_painting_every_move_and_sticker_does_not_fail(app, mascot):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QRegion
    from PySide6.QtWidgets import QWidget
    deadline = time.time() + 10
    while mascot._layers() is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if mascot._layers() is None:
        pytest.skip('mascot pictures not available')
    image = QImage(mascot.size(), QImage.Format.Format_ARGB32_Premultiplied)
    for name in MOVES:
        mascot.play(name)
        for _ in range(4):
            mascot.test_clock['now'] += MOVES[name].seconds / 4.5
            image.fill(Qt.GlobalColor.transparent)
            mascot.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    for name in STICKERS:
        mascot.stick(name)
        mascot.test_clock['now'] += STICKERS[name].seconds / 3
        image.fill(Qt.GlobalColor.transparent)
        mascot.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)


def test_drawn_expressions_replace_the_plain_layer_only_when_present(mascot):
    mascot.expression = {'eyes': 'cry'}
    assert mascot._variant('eyes') == 'eyes'                     # not drawn yet: the plain eyes
    if mascot.rig is not None:
        layers = mascot.rig[0]['layers']
        layers.append(dict(layers[[layer.get('role') for layer in layers].index('eyes')], role='eyes:cry'))
        try:
            assert mascot._variant('eyes') == 'eyes:cry'
        finally:
            layers.pop()


# ------------------------------------------------------------------ in the chat
@pytest.fixture
def chat(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek'))
    window = QWidget()
    window.resize(1000, 700)
    window.model_workshop_button = QPushButton('模型工坊', window)
    window.show()
    card = bunny_chat.open_bunny_chat(window)
    card.reveal_all()
    if card.mascot is None:
        pytest.skip('mascot pictures not available')
    yield bunny_chat, window, card
    card.close_chat()
    window.close()
    window.deleteLater()


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def test_an_ai_reaction_or_a_mood_shows_on_her(chat):
    bunny_chat, _window, card = chat
    from twobyteasr.app import bunny_persona
    card.say(bunny_persona.BunnyReply(lines=['做好啦'], mood='happy', act='cheer'))
    assert card.mascot.current_move == 'cheer' and 'confetti' in card.mascot.stickers
    card.reveal_all()
    card.say(bunny_persona.BunnyReply(lines=['对不起……'], mood='sorry'))
    assert card.mascot.current_move == 'apology' and 'gloom' in card.mascot.stickers
    assert card.mascot.expression == {'eyes': 'cry', 'blink': 'cry'}


def test_waiting_looking_up_failing_and_doing_each_look_different(app, chat, monkeypatch):
    bunny_chat, window, card = chat
    calls = []

    def fake_run(worker):
        calls.append(worker._lookup)
        if not worker._lookup:
            worker.answered.emit(json.dumps({'lines': ['我去看看'], 'check': 'last_task'}, ensure_ascii=False))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    card.input.setText('为什么识别出错')
    card.send()
    assert _until(app, lambda: card.mascot.current_move == 'search' and 'magnifier' in card.mascot.stickers)
    card._failed(card._generation, '超时')
    assert card.mascot.current_move == 'fog' and 'magnifier' not in card.mascot.stickers
    card.reveal_all()
    card._show_thinking()
    assert card.mascot.current_move == 'think' and 'dots' in card.mascot.stickers
    card._clear_thinking()


def test_too_many_pokes_and_she_turns_away(chat):
    _bunny_chat, _window, card = chat
    for _ in range(4):
        card.reveal_all()
        card.poke()
    assert card.mascot.current_move == 'turn_away' and 'anger' in card.mascot.stickers


def test_quiet_for_long_she_dozes_and_wakes_when_spoken_to(chat, monkeypatch):
    bunny_chat, _window, card = chat
    card.reveal_all()
    card.mascot.stop_move()
    monkeypatch.setattr(bunny_chat, 'IDLE_DOZE_S', 0.0)
    card._active_at -= 1
    card._heartbeat()
    assert card._dozing and card.mascot.current_move == 'doze' and 'zzz' in card.mascot.stickers
    card._typing('h')
    assert not card._dozing and card.mascot.current_move == 'wake' and card.mascot.lean_target < 0


def test_a_finished_recognition_gets_a_cheer_and_the_window_drag_a_sway(chat):
    _bunny_chat, window, card = chat
    card.task_finished(2)
    assert card.mascot.current_move == 'cheer'
    assert '识别做完啦' in ''.join(card.last_reply_html())
    card.mascot._sway_v = 0.0
    window.move(window.pos().x() + 80, window.pos().y())
    card.eventFilter(window, __import__('PySide6.QtCore', fromlist=['QEvent']).QEvent(
        __import__('PySide6.QtCore', fromlist=['QEvent']).QEvent.Type.Move))
    assert card.mascot._sway_v != 0.0


def test_review_round_two_moves_are_big_enough_to_see():
    wave = MOVES['wave'].pose(.5, .9)
    assert 'right' in wave.paws and 'left' not in wave.paws and wave.paws['right'][1] < -60   # one paw, raised
    cheer = MOVES['cheer'].pose(1 / 6, .3)
    assert cheer.dy <= -75 and cheer.eyes_closed and cheer.paws['left'][0] < -150    # a big jump, paws out wide
    assert MOVES['peek'].pose(.05, .1).dy > 400 and MOVES['peek'].pose(.95, 2.1).dy == 0      # rises from below
    assert MOVES['glint'].pose(.27, .2).lens_flash > .9
    shy = MOVES['shy'].pose(.5, 1.0)
    assert shy.blush > 3 and shy.blush_scale > 1.3 and shy.sx < .9
    assert MOVES['brow_raise'].pose(.5, .6).layer_shift['眉毛'][1] <= -40
