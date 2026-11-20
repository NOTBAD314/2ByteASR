"""兔白 smoothness and the save question's charm (2026-11-18).

User (2026-11-18): 「问问兔白」 stutters or vanishes for a moment while she moves; the bunny charm
in the save question is not centred; the whole app should feel smooth.
"""
from __future__ import annotations

import inspect
import time

import pytest


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_charm_sits_in_the_middle_of_its_disc(app):
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '关闭', 'demo')
    try:
        disc = dialog.bunny_disc
        if disc is None:
            pytest.skip('no mascot pictures in this build')
        mascot = disc.mascot
        body = mascot.body_center() + mascot.pos()
        assert abs(body.x() - disc.centre.x()) <= 1 and abs(body.y() - disc.centre.y()) <= 1, (body, disc.centre)
        # Her feet stay inside the disc, and the keyring above her head is not cut by the widget.
        s = mascot.scale
        feet = mascot.pos().y() + mascot.pad_top + (mascot.BODY_BOX[3] - mascot.trim[1]) * s
        assert feet <= disc.centre.y() + disc.diameter / 2
        assert mascot.pos().y() + mascot.pad_top >= 0
        assert disc.height() >= disc.centre.y() + disc.diameter / 2
    finally:
        dialog.deleteLater()


def test_prepared_heights_are_the_ones_the_chat_and_questions_use():
    from twobyteasr.app import ask_bunny_button
    from twobyteasr.app.bunny_chat import BunnyChat
    from twobyteasr.projects import project_recovery_dialog, save_changes_dialog
    chat, save, recovery = ask_bunny_button.PREWARM_HEIGHTS
    assert chat == BunnyChat.MASCOT_HEIGHT
    assert f'self.bunny({save})' in inspect.getsource(save_changes_dialog)
    assert f"self.bunny({recovery}, 'happy')" in inspect.getsource(project_recovery_dialog)


def test_prewarm_prepares_layers_before_anyone_asks(app):
    from twobyteasr.design.mascot_assets import prewarm, provider
    assets = provider()
    if assets.rig is None:
        pytest.skip('no mascot pictures in this build')
    prewarm((61,), 1.0)
    end = time.time() + 10
    while (61, 1.0) not in assets.cache and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert (61, 1.0) in assets.cache


def test_her_first_line_never_waits_for_the_word_list(monkeypatch):
    """Opening the chat took about 0.9 s: the first line ran jieba while its dictionary loaded."""
    import threading
    from twobyteasr.app import tour_mascot
    colors = {'accent': '#f00', 'mark': '#ff0', 'mark_text': '#000'}
    loading = threading.Event()
    monkeypatch.setattr(tour_mascot, '_words_ready', loading)        # still loading
    started = time.perf_counter()
    html_text = tour_mascot.marked_html('先去 **新手教学** 看看，首页有新手引导', colors, keep_words=True)
    assert time.perf_counter() - started < 0.2
    joiner = tour_mascot.WORD_JOINER
    assert f'新{joiner}手{joiner}教{joiner}学' in html_text             # marked runs still stay whole
    loading.set()                                                      # loaded: whole words from now on
    assert tour_mascot._words_ready.wait(1)
    again = tour_mascot.marked_html('首页有新手引导哦', colors, keep_words=True)
    try:
        import jieba  # noqa: F401
    except ImportError:
        return
    assert f'引{joiner}导' in again


def test_the_breathing_button_runs_slowly_and_rests_in_the_background(app, monkeypatch):
    from twobyteasr.app.ask_bunny_button import AskBunnyButton, BREATH_FRAME_MS
    button = AskBunnyButton('问问兔白')
    assert button._breath.interval() == BREATH_FRAME_MS >= 33
    painted = []
    monkeypatch.setattr(button, 'update', lambda *a: painted.append(1))
    monkeypatch.setattr(button, 'window', lambda: type('W', (), {'isActiveWindow': lambda self: False})())
    button._breath_clock.start()
    button._phase = 0.5
    button._breathe()
    button._breathe()
    assert button._phase == 0.0 and len(painted) == 1      # one repaint to clear the halo, then nothing
    button.deleteLater()
