"""兔白 in the tutorial, the rounder 说明 menu and the comparison before step ① (2026-11-11).

User: the tutorial gets the user's PNGTuber bunny beside its bubble, talking
in an Animal Crossing like babble while the words appear, important words in
a bright colour, a friendly line when it is clicked; the 说明 menu becomes
rounder and keeps five entries; 新手教学 opens the cloud / local comparison
first instead of showing step ① and then the window over it.
"""
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


COLORS = dict(accent='#c0502a', mark='#ffe27a', mark_text='#4a3300')


def test_marks_split_into_controls_and_points():
    from twobyteasr.app.tour_mascot import marked_segments, plain
    text = '① 先选==识别方案==，再点**下一步**'
    assert marked_segments(text) == [('① 先选', ''), ('识别方案', 'hi'), ('，再点', ''), ('下一步', 'em')]
    assert plain(text) == '① 先选识别方案，再点下一步'


def test_typing_keeps_the_untyped_words_in_place_transparent():
    from twobyteasr.app.tour_mascot import marked_segments, segments_html
    segments = marked_segments('点==这里==<b>')
    partial = segments_html(segments, COLORS, 2)
    assert '点' in partial and 'background-color:#ffe27a' in partial      # "这" shown on the marker
    assert partial.count('color:transparent') == 2                         # "里" and "<b>" wait, invisible
    assert '&lt;b&gt;' in partial                                          # escaped, never markup
    full = segments_html(segments, COLORS)
    assert 'transparent' not in full and full.count('#ffe27a') == 1


def test_the_typewriter_types_then_finishes_on_demand(app):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.app.tour_mascot import Typewriter
    label = QLabel()
    typer = Typewriter()
    spoken, done = [], []
    typer.spoke.connect(spoken.append)
    typer.finished.connect(lambda: done.append(True))
    typer.prepare([(label, '你好，**兔白**')], COLORS)
    assert label.text().count('transparent') >= 1 and not spoken
    typer.start()
    _until(app, lambda: len(spoken) >= 2)
    typer.finish()
    assert done == [True] and 'transparent' not in label.text() and not typer.running


def test_the_voice_skips_punctuation_and_keeps_a_gap(monkeypatch):
    from twobyteasr.app import tour_mascot
    monkeypatch.setattr(tour_mascot, 'voice_enabled', lambda: False)
    voice = tour_mascot.MascotVoice()
    assert not voice.say('，') and not voice.say(' ')
    assert voice.say('兔')                     # silent (voice off) but the mouth still moves
    assert not voice.say('白')                 # within the gap
    voice._last -= 1.0
    assert voice.say('白')
    assert voice.syllable_for('a')[:2] == ('', 'a') and voice.syllable_for('兔') == voice.syllable_for('兔')
    sounds = {voice.syllable_for(char) for char in '嗨我是兔白跟着点几下就会啦'}
    assert len(sounds) >= 8                                         # a babble, not one repeated blip


def test_the_babble_syllables_are_short_distinct_and_in_the_output_format():
    import numpy as np
    from twobyteasr.app.tour_mascot import RATE, SYLLABLE_S, syllable_pcm
    a, i = syllable_pcm('m', 'a', 0, 0), syllable_pcm('l', 'i', 3, 4)
    assert len(a) == int(RATE * SYLLABLE_S) * 2 * 2                  # 48 kHz, stereo, 16 bit
    samples = np.frombuffer(a, '<i2').reshape(-1, 2)
    assert (samples[:, 0] == samples[:, 1]).all()                     # the same on both sides
    assert 4000 < np.abs(samples).max() < 32767 * 0.95                # audible, never clipping
    assert abs(int(samples[0, 0])) < 200 and abs(int(samples[-1, 0])) < 200   # no click at either end
    assert a != i and syllable_pcm('m', 'a', 0, 0) is a               # different syllables; made once
    # 2026-11-11 round 3 (user: too shrill and noisy): soft and sweet, little energy above 3 kHz.
    mono = samples[:, 0].astype(float)
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1 / RATE)
    assert spectrum[freqs > 3000].sum() / spectrum.sum() < 0.15


def test_the_bunny_has_tips_about_subtitles_and_encoding_and_never_repeats_at_once():
    from twobyteasr.app.tour_mascot import CHAT_LINES, CUTE, TIPS, next_chat_line
    assert len(TIPS) >= 15 and len(CUTE) >= 10
    for word in ('SRT', 'AV1', 'H.264', '码率'):
        assert any(word in line for line in TIPS), word
    recent, last = [], ''
    for _ in range(60):
        line = next_chat_line(last, recent)
        assert line in CHAT_LINES and line != last and line not in recent
        recent, last = (recent + [line])[-6:], line


def _tour(app, steps, floating=False):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app.home_tour import GuidedTour
    window = QWidget()
    window.resize(1400, 900)
    window.show()
    tour = GuidedTour(window, steps)
    tour.FLOATING = floating
    return window, tour


def test_the_bunny_stands_away_from_the_outline_and_the_pointer_leaves_the_card(app):
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app.home_tour import TourStep
    window, tour = _tour(app, [])
    button = QPushButton('目标', window)
    button.setGeometry(60, 380, 160, 44)
    button.show()
    tour.steps = [TourStep('点==目标==', lambda: button)]
    tour.start()
    _until(app, lambda: tour.mode == 'shown' and tour.reveal >= 1.0 and tour.bubble.isVisible())
    bubble = tour.bubble
    assert bubble.mascot is not None and bubble.mascot.isVisible()
    assert bubble.side == 'right'                                     # the bubble is right of the outline
    card = QRectF(bubble.card_rect()).translated(QRectF(bubble.geometry()).topLeft())
    mascot = QRectF(bubble.mascot.geometry()).translated(QRectF(bubble.geometry()).topLeft())
    assert mascot.center().x() > card.center().x()                    # ...so the bunny is on its far side
    assert tour.pointer is not None and abs(tour.pointer[1].x() - (card.left() + 1)) < 1.5
    assert not QRectF(bubble.geometry()).intersects(tour.hole)
    tour.close_tour(True)
    window.close()


def test_words_are_typed_a_click_shows_them_and_the_bunny_chats(app, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import tour_mascot
    from twobyteasr.app.home_tour import TourStep
    monkeypatch.setattr(tour_mascot, 'voice_enabled', lambda: False)
    window, tour = _tour(app, [TourStep('跟着兔白点几下，学会做==第一份字幕==，很快的', note='用的是自带的演示视频')])
    tour.start()
    _until(app, lambda: tour.mode == 'shown' and tour.reveal >= 1.0 and tour.bubble.isVisible())
    _until(app, lambda: tour._typer.running and 'transparent' in tour.text.text(), 2.0)
    assert 'transparent' in tour.note.text()                           # the note waits for the line

    def press(widget):
        center = QPointF(widget.rect().center())
        event = QMouseEvent(QEvent.Type.MouseButtonPress, center, widget.mapToGlobal(center),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)

    press(tour.text)                                                   # a click on the words: all at once
    assert not tour._typer.running and 'transparent' not in tour.text.text() + tour.note.text()
    assert '#ffe27a' in tour.text.text() or '#f7cf4a' in tour.text.text()
    tour._greeted = True                                               # no greeting in the way
    press(tour.bubble.mascot)
    assert not tour.chat.isVisible()                                   # 2026-11-11: a click is press + release
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(tour.bubble.mascot.rect().center()),
                          tour.bubble.mascot.mapToGlobal(QPointF(tour.bubble.mascot.rect().center())),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(tour.bubble.mascot, release)
    assert tour.chat.isVisible() and tour._chat_line in tour_mascot.CHAT_LINES
    assert not tour.bubble.mascot.toolTip()                             # user: no 戳一下兔白 pop-up
    assert tour.mask().isEmpty() or tour.mask().contains(tour.chat.geometry().center())
    tour.go(0)                                                         # the step changes: the balloon goes
    assert not tour.chat.isVisible()
    tour.close_tour(True)
    window.close()


def test_the_voice_button_switches_and_remembers(app, monkeypatch):
    from twobyteasr.app import tour_mascot
    saved = {}
    monkeypatch.setattr(tour_mascot, 'voice_enabled', lambda: True)
    monkeypatch.setattr(tour_mascot, 'set_voice_enabled', lambda on: saved.update(on=on))
    window, tour = _tour(app, [])
    assert tour.voice.enabled
    tour.voice_button.click()
    assert saved == {'on': False} and not tour.voice.enabled
    assert '关' in tour.voice_button.toolTip() or 'off' in tour.voice_button.toolTip().lower()
    tour.close_tour(False)
    window.close()


def test_the_help_menu_keeps_five_round_entries(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import help_menu
    from twobyteasr.app.ui import MainWindow
    shown = []
    monkeypatch.setattr(help_menu.CuteMenu, 'exec', lambda menu, *a, **k: shown.append(menu))
    calls = []
    window = QWidget()
    window.help_button = QPushButton('说明', window)
    window._start_home_tour = lambda: calls.append('tour')
    window._open_sample_project = lambda: calls.append('sample')
    window._next_step_action = lambda action: calls.append(action)
    window._open_diagnostics_dialog = lambda: calls.append('diagnostics')
    window._reset_teach_hints = lambda: calls.append('hints')
    MainWindow._show_help_menu(window)
    menu = shown[0]
    rows = [a for a in menu.actions() if isinstance(a, help_menu.CuteMenuAction)]
    assert [a.text() for a in rows] == ['新手教学', '打开范例工程', '选择识别方式…', '回报问题／导出诊断…',
                                        '重新显示工作台操作提示']
    texts = ' '.join(a.text() for a in menu.actions())
    for gone in ('显示新手引导', '申请与设置 API', 'API Key 是什么', '搜索功能与设置', '快捷键'):
        assert gone not in texts
    assert all(a.caption for a in rows)
    for action in rows:
        action.trigger()
    assert calls == ['tour', 'sample', 'choose_plan', 'diagnostics', 'hints']
    from PySide6.QtCore import Qt
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)   # really round corners


def test_tutorial_opens_the_comparison_before_step_one(app, monkeypatch):
    from twobyteasr.app import home_tour
    from twobyteasr.app.ui import MainWindow
    order = []
    home = object()
    window = SimpleNamespace(pages=SimpleNamespace(currentWidget=lambda: home), findChild=lambda _kind: None,
                             _tutorial_finish=lambda completed: None)
    window.settings_scroll = home

    def compare():
        order.append(('compare', bool(window.__dict__.get('_tutorial_plan_chosen'))))
        return 'cloud'
    window._choose_plan_in_tutorial = compare
    monkeypatch.setattr(home_tour, 'start_home_tour',
                        lambda w, done, part, **_kw: order.append(('tour', bool(w.__dict__.get('_tutorial_plan_chosen')))))
    MainWindow._start_home_tour(window)
    assert order == [('compare', False), ('tour', True)]               # the window first, then step ①
    order.clear()
    MainWindow._start_home_tour(window)                                # already chosen (first-run chooser)
    assert order == [('tour', True)]


def _mouse(widget, kind, global_point, buttons):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    local = QPointF(widget.mapFromGlobal(global_point.toPoint()))
    button = Qt.MouseButton.LeftButton
    QApplication.sendEvent(widget, QMouseEvent(kind, local, global_point, button, buttons, Qt.KeyboardModifier.NoModifier))


def test_the_bunny_is_dragged_slides_bounces_and_shakes_the_window(app, monkeypatch):
    """User: drag 兔白; let go and it glides like an air-hockey puck, bounces off the edges and the window shakes."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from twobyteasr.app import tour_mascot
    from twobyteasr.app.home_tour import TourStep
    monkeypatch.setattr(tour_mascot, 'voice_enabled', lambda: False)
    window, tour = _tour(app, [TourStep('卡片'), TourStep('下一张')])
    tour.start()
    _until(app, lambda: tour.mode == 'shown' and tour.reveal >= 1.0 and tour.bubble.isVisible())
    mascot = tour.bubble.mascot
    start = QPointF(mascot.mapToGlobal(mascot.rect().center()))
    _mouse(mascot, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    import time as clock
    for step in range(1, 10):                                          # a quick flick to the right
        end = clock.monotonic() + 0.016
        while clock.monotonic() < end:                                 # it follows the pointer frame by frame
            app.processEvents()
            clock.sleep(0.002)
        _mouse(mascot, QEvent.Type.MouseMove, start + QPointF(step * 40, step * 4), Qt.MouseButton.LeftButton)
    assert not tour.bubble.docked and mascot.parentWidget() is tour     # out on its own, under the pointer
    assert not tour.chat.isVisible()
    shakes = []
    monkeypatch.setattr(type(tour), '_shake_window', lambda self, strength, direction=None: shakes.append(strength))
    _mouse(mascot, QEvent.Type.MouseButtonRelease, start + QPointF(360, 36), Qt.MouseButton.NoButton)
    assert not tour.chat.isVisible() and tour._puck.isActive()          # a drag is not a click: it slides
    _until(app, lambda: bool(shakes), 4.0)                              # it reached the right edge hard enough
    limits = tour._puck_limits()
    _until(app, lambda: not tour._puck.isActive(), 16.0)
    assert limits.left() - 0.5 <= tour._puck_pos.x() <= limits.right() + 0.5
    assert limits.top() - 0.5 <= tour._puck_pos.y() <= limits.bottom() + 0.5
    assert tour.mask().isEmpty() or tour.mask().contains(tour._mascot_rect().center().toPoint())
    tour.go(1)                                                          # next step: back beside the card
    assert tour.bubble.docked and mascot.parentWidget() is tour.bubble
    tour.close_tour(True)
    window.close()


def test_a_shake_is_local_and_never_moves_the_window(app):
    from PySide6.QtCore import QPointF, QVariantAnimation
    from twobyteasr.app.home_tour import TourStep
    window, tour = _tour(app, [TourStep('卡片')])
    window.move(200, 150)
    app.processEvents()
    origin = window.pos()
    tour.start()
    _until(app, lambda: tour.mode == 'shown')
    tour._shake_window(1.0)
    seen = set()
    mascot = tour.bubble.mascot
    _until(app, lambda: seen.add((mascot.impact_offset.x(), mascot.impact_offset.y())) or
           tour._shake.state() != QVariantAnimation.State.Running, 2.0)
    assert len(seen) > 2 and window.pos() == origin
    assert mascot.impact_offset == QPointF()
    tour.close_tour(False)
    window.close()
