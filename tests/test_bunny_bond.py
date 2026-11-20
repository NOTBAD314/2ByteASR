"""How familiar 兔白 is with this user, and what she does on her own (2026-11-18, phase 4)."""
from __future__ import annotations

import time

import pytest

from twobyteasr.app import bunny_bond, bunny_events, bunny_permissions, bunny_persona


@pytest.fixture(autouse=True)
def strangers():
    bunny_bond.clear()
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS))
    yield
    bunny_bond.clear()
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS))


def test_they_get_to_know_each_other_by_what_they_did_together():
    assert bunny_bond.level() == 0 and bunny_bond.points() == 0
    assert bunny_bond.greeting() == ('嗨～小兔纸，我是兔白。', '有不懂的随时问我，想聊天也可以哦。')
    for _ in range(5):
        bunny_bond.note('chat', today='2026-11-18')
    assert bunny_bond.points() == 5 + 3                       # five questions on one day
    assert bunny_bond.note('done', today='2026-11-19') == 1   # a subtitle made together, a second day
    assert bunny_bond.points() == 5 + 5 + 6
    assert bunny_bond.greeting() in bunny_bond.GREETINGS[1]
    assert bunny_bond.note('nonsense') == 1
    values = dict(bunny_bond.load(), chat=500)
    assert bunny_bond.level(values) == len(bunny_bond.LEVELS) - 1
    assert len(bunny_bond.GREETINGS) == len(bunny_bond.LEVELS) == len(bunny_bond.LEVEL_UP)


def test_a_new_level_is_said_once_and_a_welcome_comes_once_a_day():
    assert bunny_bond.level_up_line() == '' and not bunny_bond.welcome_due()      # strangers: nothing to say
    for _ in range(4):
        bunny_bond.note('done', today='2026-11-18')
    assert bunny_bond.level() == 1
    assert bunny_bond.level_up_line() == bunny_bond.LEVEL_UP[1]
    assert bunny_bond.level_up_line() == ''
    assert bunny_bond.welcome_due(today='2026-11-19')
    assert not bunny_bond.welcome_due(today='2026-11-19')
    assert bunny_bond.welcome_due(today='2026-11-20')


def test_nothing_is_counted_when_she_may_not_remember():
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS, remember=False))
    for _ in range(40):
        bunny_bond.note('chat')
    assert bunny_bond.points() == 0 and bunny_bond.level() == 0
    assert bunny_bond.level_up_line() == '' and not bunny_bond.welcome_due()


def test_the_ai_is_told_how_familiar_they_are_and_how_to_hold_someone():
    line = bunny_bond.inner_line()
    assert '刚认识' in line and '第 1 级' in line
    block = bunny_persona.inner_block({'uneasy': 0, 'meme_ok': True, 'plot_ok': False, 'bond': line})
    assert line in block
    assert '熟悉度' not in bunny_persona.inner_block({'uneasy': 0, 'meme_ok': True, 'plot_ok': False})
    persona = bunny_persona.PERSONA
    assert '先接住情绪，再给办法' in persona and '夸要夸具体的' in persona and '这样说 / 不要这样说' in persona
    # The fixed prompt stays the same for everyone: the level is per question only.
    assert '第 1 级' not in persona


def test_her_own_words_for_coming_back_levels_and_muttering():
    for key in ('welcome_back', 'welcome_plain', 'level_up', 'mutter'):
        hint = bunny_events.HINTS[key]
        assert not hint.urgent and hint.lines
    line, buttons = bunny_events.wording(bunny_events.HINTS['welcome_back'], {'name': '原神第12期'})
    assert '原神第12期' in line and buttons[0][1] and buttons[1][1] == ''
    said, none = bunny_events.wording(bunny_events.HINTS['level_up'], {'line': bunny_bond.LEVEL_UP[2]})
    assert said == bunny_bond.LEVEL_UP[2] and none == ()
    errors_only = dict(bunny_events.load(), mode='errors', intro=True)
    assert bunny_events.decide('mutter', errors_only, bunny_events.Session()) is None       # jokes are not trouble


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_she_moves_on_her_own_dozes_off_and_wakes(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_chat, bunny_resident
    from twobyteasr.app.onboarding import load_state, save_state
    save_state({key: value for key, value in load_state().items() if key != bunny_events.KEY})
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_resident.BunnyResident, '_app_in_front', staticmethod(lambda: True))
    window = QWidget()
    window.resize(900, 600)
    window.show()
    app.processEvents()
    resident = bunny_resident.install(window, hello=False)
    try:
        if resident is None or resident.mascot is None:
            pytest.skip('no mascot pictures in this build')
        mascot = resident.mascot
        mascot.reduced_motion = False
        now = time.monotonic()
        resident._next_antic = now - 1
        resident._antics(now, idle=10.0)
        assert mascot.current_move in bunny_resident.ANTICS and resident._next_antic > now
        mascot.stop_move()
        window._run_in_progress = True                      # a recognition is running: she watches it
        resident._next_antic = now - 1
        resident._antics(now, idle=10.0)
        assert mascot.current_move in bunny_resident.WATCHING
        mascot.stop_move()
        window._run_in_progress = False
        resident._next_antic = now - 1
        resident._antics(now, idle=bunny_resident.DOZE_AFTER_S + 1)
        assert resident._dozing and mascot.current_move == 'doze'
        resident._antics(now + 1, idle=1.0)                 # a key or a click
        assert not resident._dozing and mascot.current_move == 'wake'
        # While she is saying something she does not fidget.
        mascot.stop_move()
        resident.hint_key = 'idle_page'
        resident._next_antic = now - 1
        resident._antics(now, idle=10.0)
        assert mascot.current_move == ''
        resident.hint_key = ''
    finally:
        if resident is not None:
            resident._timer.stop()
            app.removeEventFilter(resident)
        window.close()
        window.deleteLater()
        app.processEvents()
        save_state({key: value for key, value in load_state().items() if key != bunny_events.KEY})
