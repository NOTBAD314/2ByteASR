"""兔白's tips (2026-11-16): a click mostly teaches a little trick, she sometimes says one on her own,
and the workbench's subtitle list row has 「问问兔白」."""
from __future__ import annotations

import os
import random
import re
import time
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_state():
    from twobyteasr.app import bunny_memory
    from twobyteasr.app.bunny_chat import NOTICE_KEY
    from twobyteasr.app.bunny_permissions import DEFAULTS, KEY
    from twobyteasr.app.bunny_tips import IDLE_KEY, SEEN_KEY
    from twobyteasr.app.onboarding import load_state, save_state
    bunny_memory.clear_chats()
    state = {k: v for k, v in load_state().items() if k not in (SEEN_KEY, IDLE_KEY)}
    save_state(dict(state, **{NOTICE_KEY: True, KEY: dict(DEFAULTS)}))
    yield
    bunny_memory.clear_chats()


def test_every_name_she_teaches_is_really_in_the_software():
    from twobyteasr.app import bunny_tips
    root = Path(bunny_tips.__file__).resolve().parents[1]
    skip = {'bunny_tips.py', 'bunny_manual.py', 'bunny_howto.py', 'bunny_lore.py', 'bunny_persona.py'}
    source = '\n'.join(path.read_text(encoding='utf-8') for path in root.rglob('*.py')
                       if path.name not in skip and 'acceptance' not in path.parts)
    missing = sorted({name for _where, text in bunny_tips.TIPS for name in re.findall(r'「([^」]+)」', text)
                      if name not in source})
    assert not missing, f'兔白会教界面上没有的东西：{missing}'
    assert len(bunny_tips.TIPS) >= 30 and all(len(text) <= 60 for _where, text in bunny_tips.TIPS)


def test_tips_for_the_page_come_first_and_none_repeats_until_all_were_heard():
    from twobyteasr.app import bunny_tips
    studio = [i for i, (where, _t) in enumerate(bunny_tips.TIPS) if where == bunny_tips.STUDIO]
    rng = random.Random(3)
    first = [bunny_tips.next_tip(bunny_tips.STUDIO, rng=rng)[0] for _ in studio]
    assert sorted(first) == studio                                  # the workbench's own, each once
    shared = [i for i, (where, _t) in enumerate(bunny_tips.TIPS) if where == bunny_tips.ANY]
    then = [bunny_tips.next_tip(bunny_tips.STUDIO, rng=rng)[0] for _ in shared]
    assert sorted(then) == shared                                   # then the ones for anywhere
    assert bunny_tips.next_tip(bunny_tips.STUDIO, rng=rng)[0] in studio   # a new round
    # where she is in the list is kept, so the next start goes on
    assert bunny_tips._seen()
    home = bunny_tips.next_tip(bunny_tips.HOME, rng=rng)
    assert bunny_tips.TIPS[home[0]][0] == bunny_tips.HOME
    lines = bunny_tips.tip_lines('', rng=rng)
    assert lines[0] in bunny_tips.OPENERS and len(lines) == 2


@pytest.fixture
def chat_env(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'Claude'))
    window = QWidget()
    window.resize(1100, 720)
    window.help_button = QPushButton('说明', window)
    window.show()
    app.processEvents()
    yield bunny_chat, window
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()


def _said(chat):
    chat.reveal_all()
    return [text for who, text in chat.transcript if who == 'bunny']


def test_a_click_mostly_teaches_a_tip(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_tips
    chat = bunny_chat.open_bunny_chat(window)
    before = len(_said(chat))
    monkeypatch.setattr(bunny_chat, 'POKE_TIP_SHARE', 1.0)
    chat.poke()
    said = _said(chat)[before:]
    assert said[0] in bunny_tips.OPENERS and any(said[1] == text for _w, text in bunny_tips.TIPS)
    monkeypatch.setattr(bunny_chat, 'POKE_TIP_SHARE', 0.0)
    chat._pokes = []
    chat.poke()
    assert _said(chat)[-1] in [line for line, _mood in bunny_chat.POKE_LINES]


def test_now_and_then_a_tip_on_her_own_but_never_over_a_pending_button(app, chat_env):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_tips
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    now = time.monotonic()
    assert not chat._idle_tip_due(now)                    # not right after opening
    chat._active_at = chat._last_idle_tip = now - 1000
    chat.do_button.show()                                 # a 「帮我做」 waits: she keeps quiet
    assert not chat._idle_tip_due(now)
    chat.do_button.hide()
    chat.input.setText('我在打字')
    assert not chat._idle_tip_due(now)
    chat.input.clear()
    bunny_tips.set_idle_allowed(False)
    assert not chat._idle_tip_due(now)
    bunny_tips.set_idle_allowed(True)
    assert chat._idle_tip_due(now)
    before = len(_said(chat))
    if chat.mascot is not None and chat.mascot.current_move:
        chat.mascot.stop_move(chat.mascot.current_move)      # her greeting hop is over
    chat._active_at = chat._last_idle_tip = time.monotonic() - 1000
    chat._heartbeat()
    said = _said(chat)[before:]
    assert said and said[0] in bunny_tips.OPENERS
    assert not chat._idle_tip_due(time.monotonic() + 60)   # not again for minutes


def test_the_workbench_list_row_has_ask_bunny_and_it_opens_her_chat(app, tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from twobyteasr.studio import studio_bunny_entry
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / 'video.mp4'), duration_ms=30_000),
                              cues=[StudioCue('c0', 0, 2000, '第一句')])
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, 'load', lambda *a, **k: None)
    monkeypatch.setattr(page, '_generate_waveform', lambda *a, **k: None)
    page.resize(1400, 860)
    page.show()
    page.open_project(save_project(project, tmp_path / 'studio.2byteproj'))
    deadline = time.monotonic() + 20
    while getattr(page, 'cue_bunny_button', None) is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    try:
        button = page.cue_bunny_button
        assert button.text() == '问问兔白' and button.objectName() == 'cueBunnyButton'
        row = studio_bunny_entry._layout_holding(page.cue_ai_button)
        assert row.indexOf(button) == row.indexOf(page.cue_ai_button) - 1          # left of 「AI 工具」
        assert studio_bunny_entry.install(page) is button                           # once only
        opened = []
        monkeypatch.setattr('twobyteasr.app.bunny_chat.open_bunny_chat', lambda window: opened.append(window) or 'chat')
        button.click()
        assert opened == [studio_bunny_entry.main_window(page)]
        button.refresh_theme_palette()
        assert 'cueBunnyButton' in button.styleSheet()
    finally:
        page.close_page()
