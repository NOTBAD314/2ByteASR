"""兔白 folded at start, folded by its button, and busy with the page's parts (2026-11-26).

User (2026-11-26): opening the software showed the big dialog box at once; only the big 兔白 should
show, a click on her opens the box, and the box can be folded without sending her away too. Folded,
she should do more with the software itself — take a wrench to the settings gear, read the term
library's book, play on the page's parts — so she feels like a real character.
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


def _button(parent, text, icon, rect):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.design.themed_icons import install_themed_icon
    button = QPushButton(text, parent)
    install_themed_icon(button, icon, 'accent')
    button.setGeometry(*rect)
    button.show()
    return button


@pytest.fixture
def page(app, monkeypatch):
    """A window with the parts she knows: a gear, the term library's book, a seat, header buttons."""
    from PySide6.QtWidgets import QFrame, QWidget
    from twobyteasr.app import bunny_chat, bunny_errands, bunny_puck
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    monkeypatch.setattr(bunny_puck, 'REST_BEFORE_HOME_MS', 50)
    monkeypatch.setattr(bunny_puck, 'SETTLE_MS', 60)
    monkeypatch.setattr(bunny_errands, 'PACE', 0.05)
    window = QWidget()
    window.resize(1200, 800)
    window.home_task_settings_button = _button(window, '高级设置', 'fa5s.cog', (900, 140, 120, 34))
    window.add_glossary_button = _button(window, '管理术语库', 'fa5s.book-open', (520, 420, 130, 34))
    window.support_button = _button(window, '支持我！', 'fa5s.heart', (300, 40, 110, 36))
    window.update_button = _button(window, '检查更新', 'fa5s.sync-alt', (420, 40, 110, 36))
    window.app_settings_button = _button(window, '设置', 'fa5s.cog', (540, 40, 90, 36))
    seat = QFrame(window)
    seat.setGeometry(120, 520, 360, 160)
    seat.show()
    window.media_frame = seat
    window.show()
    app.processEvents()
    yield window
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def _folded(page):
    from twobyteasr.app import bunny_chat
    chat = bunny_chat.show_bunny(page)
    if chat is None:
        pytest.skip('no mascot pictures in this build')
    return chat


def _mouse(kind, local, global_point):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    held = kind.name != 'MouseButtonRelease'
    return QMouseEvent(kind, QPointF(local), QPointF(global_point),
                       Qt.MouseButton.LeftButton if kind.name != 'MouseMove' else Qt.MouseButton.NoButton,
                       Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


def test_the_software_opens_with_only_the_big_bunny_and_a_click_opens_her_box(app, page):
    from PySide6.QtCore import QEvent
    chat = _folded(page)
    puck, mascot = chat.puck, chat.mascot
    app.processEvents()
    assert chat.collapsed and chat.fold_reason == 'start'
    assert not chat.isVisible(), 'no dialog box at start'
    assert not puck.docked and puck.carrier.isVisible() and mascot.parent() is puck.carrier
    assert puck.carrier.bubble is None or puck.carrier.bubble.isHidden(), 'no bubble while she has nothing to say'
    assert chat.transcript == [] and not chat._greeted, 'her hello waits for the box'
    # A card folded at start never comes back by itself.
    time.sleep(0.2)
    app.processEvents()
    assert chat.collapsed
    # One click on her opens the box beside her and she says hello then.
    face = mascot.rig_to_widget(458, 470)
    origin = mascot.mapToGlobal(face.toPoint())
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, face, origin))
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, face, origin))
    assert _until(app, lambda: chat.isVisible() and not chat.collapsed)
    assert chat._greeted and chat.transcript
    assert _until(app, lambda: puck.docked, seconds=4), 'she floats back onto the box'


def test_the_fold_button_folds_the_box_and_keeps_her(app, page):
    chat = _folded(page)
    chat.expand()
    assert _until(app, lambda: chat.puck.docked, seconds=4)
    assert chat.fold_button.isVisibleTo(chat)
    chat.fold_button.click()
    app.processEvents()
    assert chat.collapsed and chat.fold_reason == 'user' and not chat.isVisible()
    assert not chat.puck.docked and chat.puck.carrier.isVisible(), 'she stays out on the page'
    time.sleep(0.3)
    app.processEvents()
    assert chat.collapsed, 'folded by the user it stays folded'
    assert page._bunny_chat is chat


def test_a_short_line_while_folded_shows_over_her_head_and_goes_away(app, page, monkeypatch):
    from twobyteasr.app import bunny_head_bubble
    monkeypatch.setattr(bunny_head_bubble, 'reading_ms', lambda _text: 120)
    chat = _folded(page)
    chat.puck.bubble_line('修好啦！')
    bubble = chat.puck.carrier.bubble
    assert bubble.isVisible() and bubble.text == '修好啦！'
    assert chat.puck.carrier.mask().boundingRect().contains(bubble.geometry())
    assert _until(app, lambda: bubble.isHidden(), seconds=2)
    # 2026-11-27 (user: idle hints showed only "…" and had to be clicked): a longer line of hers
    # shows in the bubble too, wrapped; it is not left waiting behind a dot.
    from twobyteasr.app import bunny_persona
    monkeypatch.setattr(bunny_head_bubble, 'reading_ms', lambda _text: 4000)
    chat.say(bunny_persona.BunnyReply(lines=['这是一段比较长的话，以前要打开对话框才看得完，现在直接显示在气泡里。']))
    assert bubble.isVisible() and not bubble.unread and bubble.text.startswith('这是一段比较长的话')
    assert bubble.height() > bunny_head_bubble.HEIGHT + bunny_head_bubble.TAIL, 'wrapped onto more rows'
    assert bubble.width() <= bunny_head_bubble.MAX_W
    assert chat.puck.carrier.mask().boundingRect().contains(bubble.geometry())


def test_resting_only_her_body_takes_clicks(app, page):
    chat = _folded(page)
    puck, mascot = chat.puck, chat.mascot
    mascot.stop_move()
    mascot._stickers.clear()
    assert _until(app, lambda: not mascot.animating(), seconds=3)
    mascot._shape_check()
    puck.carrier.rest()
    rest = puck.carrier._resting_rect()
    assert mascot.geometry().contains(rest) and rest.width() < mascot.width() and rest.height() < mascot.height()
    assert puck.carrier.mask().boundingRect() == rest
    # 2026-11-27 (user: while she acts her sides were cut off): acting, her whole box is shown.
    mascot.play('cheer')
    assert puck.carrier.mask().boundingRect() == mascot.geometry()
    mascot.stop_move()
    app.processEvents()
    mascot.repaint()
    assert puck.carrier.mask().boundingRect() == rest


def _run(app, errands, name, target, seconds=8.0):
    assert errands.start(name, target)
    return _until(app, lambda: not errands.busy(), seconds=seconds)


def test_she_mends_the_gear_with_her_wrench_and_the_icon_turns(app, page):
    chat = _folded(page)
    errands, mascot, puck = chat.errands, chat.mascot, chat.puck
    gear = page.home_task_settings_button
    still = gear.icon().cacheKey()
    assert ('fix_gear', gear) in errands.candidates()
    assert errands.start('fix_gear', gear)
    assert _until(app, lambda: mascot.current_move == 'strike' and mascot.held == 'wrench', seconds=6)
    assert errands.fx.moving(gear), 'the gear button rattles and goes crooked'
    # The wrench comes down on the gear's icon (round 2: it is swung down, not turned in place).
    from twobyteasr.app.bunny_errands import icon_centre
    from twobyteasr.design.bunny_props import wrench_jaw
    jaw, aim = puck.window_point(wrench_jaw()), icon_centre(gear, page)
    assert abs(jaw.x() - aim.x()) < 4 and abs(jaw.y() - aim.y()) < 4
    turned = set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(turned) < 3:
        app.processEvents()
        time.sleep(0.01)
        turned.add(gear.icon().cacheKey())
    assert len(turned) >= 3, 'the gear icon turns while she cranks'
    assert _until(app, lambda: not errands.busy(), seconds=10)
    assert mascot.held == '' and mascot.current_move != 'strike' and not mascot.mirrored
    assert gear.property('_themed_icon') == ('fa5s.cog', 'accent')
    assert gear.icon().cacheKey() != 0 and still != 0
    assert abs(puck.pos.x() - errands.home.x()) < 2 and abs(puck.pos.y() - errands.home.y()) < 2, 'back where she was'


def test_she_borrows_the_term_librarys_book_and_puts_it_back(app, page):
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    book = page.add_glossary_button
    assert errands.start('read_book', book)
    assert _until(app, lambda: book.icon().isNull(), seconds=6), 'she takes the book out of the button'
    assert errands.overlay is not None and errands.overlay.busy(), 'it flies over to her paws'
    assert _until(app, lambda: mascot.held == 'book', seconds=4)
    assert book.icon().isNull(), 'the book is in her paws, not on the button'
    assert mascot.life is None or mascot.life.focus is not None, 'she looks down at the page'
    assert _until(app, lambda: not errands.busy(), seconds=10)
    assert not book.icon().isNull() and mascot.held == ''


def test_she_hangs_from_the_header_buttons_and_they_go_down_under_her(app, page):
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    bars = errands._header_buttons()
    assert len(bars) >= 2
    assert errands.start('hang_on', bars)
    assert _until(app, lambda: any(button.isDown() for button in bars), seconds=6)
    assert _until(app, lambda: mascot.current_move == 'hang', seconds=2)
    assert any(errands.fx.moving(button) for button in bars), 'the button she hangs on gives under her'
    assert _until(app, lambda: not errands.busy(), seconds=10)
    assert not any(button.isDown() for button in bars)


def test_she_sits_on_a_card_and_comes_back(app, page):
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    assert errands.start('sit_on', page.media_frame)
    assert _until(app, lambda: mascot.current_move == 'sit', seconds=6)
    from twobyteasr.app.bunny_errands import SEAT
    seat = chat.puck.window_point(SEAT)
    assert abs(seat.y() - (page.media_frame.geometry().top() + 3)) < 3, 'sitting on its top edge'
    assert errands.fx.moving(page.media_frame), 'the seat dips under her'
    assert _until(app, lambda: not errands.busy(), seconds=10)


def test_a_press_on_her_stops_an_errand_and_puts_everything_back(app, page):
    from PySide6.QtCore import QEvent
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    book = page.add_glossary_button
    assert errands.start('read_book', book)
    assert _until(app, lambda: mascot.held == 'book', seconds=6)
    face = mascot.rig_to_widget(458, 470)
    origin = mascot.mapToGlobal(face.toPoint())
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, face, origin))
    assert not errands.busy() and mascot.held == '' and not book.icon().isNull()
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, face, origin))


def test_put_down_on_the_book_she_reads_it(app, page):
    from PySide6.QtCore import QPoint, QPointF, QRect
    chat = _folded(page)
    puck, errands = chat.puck, chat.errands
    book = page.add_glossary_button
    rect = QRect(book.mapTo(page, QPoint(0, 0)), book.size())
    puck.pos = puck.spot_for((458.0, 612.0), QPointF(rect.center()))
    puck._place(puck.pos)
    puck._stay_here()
    assert errands.name == 'read_book'
    errands.interrupt()
    assert errands.name == '' and not book.icon().isNull()


def test_on_her_own_she_waits_for_a_quiet_moment(app, page, monkeypatch):
    chat = _folded(page)
    errands = chat.errands
    monkeypatch.setattr(errands, '_free', lambda: True)
    errands.next_at = time.monotonic() - 1
    errands.input_at = time.monotonic()            # the user just clicked
    errands._consider()
    assert not errands.busy()
    errands.input_at = time.monotonic() - 10
    errands._consider()
    from twobyteasr.app.bunny_errands import ONE_BUTTON
    assert errands.busy() and errands.name in (
        'fix_gear', 'read_book', 'sit_on', 'hang_on', 'domino', 'stomp', 'wander', *ONE_BUTTON)
    errands.interrupt()


def test_props_and_moves_for_her_errands_exist_and_draw(app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from twobyteasr.design.bunny_mascot import BunnyMascot
    from twobyteasr.design.bunny_moves import MOVES
    from twobyteasr.design.bunny_props import PROPS, wrench_jaw
    assert {'strike', 'knock', 'push', 'pull', 'read', 'sit', 'hang', 'trot', 'lift', 'polish'} <= set(MOVES)
    assert {'wrench', 'book', 'cloth'} <= set(PROPS)
    jaw = wrench_jaw()
    assert 600 < jaw[0] < 760 and 450 < jaw[1] < 620, 'the jaw sits out at her right, about face height'
    mascot = BunnyMascot(None, height=160, motion='swing')
    if not mascot.available:
        pytest.skip('no mascot pictures in this build')
    _until(app, lambda: mascot._layers() is not None, seconds=6)
    for move, prop in (('strike', 'wrench'), ('read', 'book'), ('polish', 'cloth'), ('sit', ''), ('hang', '')):
        mascot.play(move)
        if prop:
            assert mascot.hold(prop) and mascot.held == prop
        for mirrored in (False, True):
            mascot.mirrored = mirrored
            image = QImage(mascot.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            mascot.render(image)
        mascot.drop_prop()
        assert mascot.held == ''
    # Mirrored, a canvas point maps back to itself.
    mascot.mirrored = True
    point = mascot.rig_to_widget(600, 500)
    x, y = mascot.rig_point(point)
    assert abs(x - 600) < .5 and abs(y - 500) < .5


def test_the_corner_bunnys_hints_go_to_the_big_one_while_her_box_is_folded(app, page, monkeypatch):
    from twobyteasr.app import bunny_events, bunny_resident
    from twobyteasr.app.onboarding import load_state, save_state
    save_state({key: value for key, value in load_state().items() if key != bunny_events.KEY})
    monkeypatch.setattr(bunny_resident.BunnyResident, '_app_in_front', staticmethod(lambda: True))
    chat = _folded(page)
    resident = bunny_resident.install(page, hello=False)
    try:
        app.processEvents()
        assert not resident.isVisible(), 'the small one stays hidden while the big one is out'
        resident.notify('recognition_done')
        app.processEvents()
        bubble = chat.puck.carrier.bubble
        said = [text for who, text in chat.transcript if who == 'bunny'] + list(chat._pending) + chat._said_now
        assert said or (bubble is not None and bubble.isVisible()), 'her hint reached the big 兔白'
        assert bubble is not None and bubble.isVisible()
    finally:
        resident._timer.stop()
        resident.close()


def test_a_button_she_touches_is_really_drawn_crooked_and_then_plain_again(app):
    """Round 2 (user): her actions must really affect the buttons — crooked and shaking."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.design.bunny_button_fx import ButtonFx, WobbleEffect
    host = QWidget()
    host.resize(320, 140)
    host.setStyleSheet('QWidget { background: #101010; } QPushButton { background: #ff0000; border: none; }')
    button = QPushButton('', host)
    button.setGeometry(100, 60, 120, 30)
    host.show()
    app.processEvents()
    probe = (200, 40)                              # above the button's right end

    def red_at(point):
        color = QColor(host.grab().toImage().pixel(*point))
        return color.red() > 180 and color.green() < 80

    assert not red_at(probe)
    fx = ButtonFx()
    assert fx.hold(button, pivot=(0.0, 1.0), angle=-15)
    t = 0.0
    for _ in range(90):                            # three seconds at 30 fps: settled at -15 degrees
        t += 1 / 30
        fx.step(t)
    assert isinstance(button.graphicsEffect(), WobbleEffect)
    app.processEvents()
    assert red_at(probe), 'the right end is lifted: the button is drawn turned'
    fx.release(button)
    fx.kick(button, angle=200)
    angles = []
    for _ in range(240):
        t += 1 / 30
        fx.step(t)
        if button.graphicsEffect() is not None:
            angles.append(button.graphicsEffect().angle)
    assert any(a > 1 for a in angles) and any(a < -1 for a in angles), 'it wobbles back and forth'
    assert button.graphicsEffect() is None and not fx.busy(), 'plain again at rest'
    fx.shake(button, .5, t, px=2, degrees=4)
    fx.step(t + .05)
    assert button.graphicsEffect() is not None
    fx.clear()
    assert button.graphicsEffect() is None
    host.close()


def test_she_hops_there_step_by_step_instead_of_jumping_across(app, page, monkeypatch):
    """Round 2 (user): she must not appear at the place and back: a long way is many small hops."""
    from PySide6.QtCore import QPointF
    from twobyteasr.app import bunny_errands
    monkeypatch.setattr(bunny_errands, 'PACE', 1.0)
    chat = _folded(page)
    errands, puck = chat.errands, chat.puck
    now = [500.0]
    errands.manual = True
    errands._frame.stop()
    errands.clock = lambda: now[0]
    chat.mascot.clock = lambda: now[0]
    start = QPointF(puck.pos)
    errands.home = puck._clamp(QPointF(start.x() - 600, start.y() - 300))
    errands._gen = errands._go_home()
    errands._advance(now[0])
    assert puck.mode == 'walk' and puck.walking
    positions = [QPointF(puck.pos)]
    for _ in range(25 * 8):
        now[0] += 1 / 25
        errands.tick()
        positions.append(QPointF(puck.pos))
        if errands._gen is None:
            break
    steps = [((b.x() - a.x()) ** 2 + (b.y() - a.y()) ** 2) ** .5 for a, b in zip(positions, positions[1:])]
    assert errands._gen is None and puck.mode == 'rest' and not puck.walking
    assert abs(puck.pos.x() - errands.home.x()) < 1 and abs(puck.pos.y() - errands.home.y()) < 1
    assert len(steps) > 25 * 2, 'a 670 px way takes seconds, not one glide'
    assert max(steps) < 45, 'no frame jumps far'
    assert bunny_errands.MAX_HOPS >= 8


def test_in_subtitle_studio_she_stays_put_and_only_home_has_walks(app, page, monkeypatch):
    chat = _folded(page)
    errands = chat.errands
    monkeypatch.setattr('twobyteasr.app.bunny_errands.QApplication.applicationState',
                        lambda *_a: __import__('PySide6.QtCore', fromlist=['Qt']).Qt.ApplicationState.ApplicationActive)
    monkeypatch.setattr(errands, 'page', lambda: '字幕工作台')
    assert not errands._free()
    assert not errands.landed()
    monkeypatch.setattr(errands, 'page', lambda: '首页')
    # Her entrance (a fade, 2026-11-27) and then her hello wave are over.
    assert _until(app, lambda: not chat.mascot.entering() and not chat.mascot.current_move, seconds=4)
    assert errands._free()
    chat.puck.placed_at = time.monotonic()                 # just put down by the user
    monkeypatch.setattr('twobyteasr.app.bunny_errands.WANDER_SHARE', 1.0)
    choice = errands.pick()
    assert choice is None or choice[0] != 'wander', 'put down by the user she stays a while'
    chat.puck.placed_at = -1e9
    choice = errands.pick()
    assert choice is not None and choice[0] == 'wander'
    assert errands.start(*choice)
    _until(app, lambda: not errands.busy(), seconds=10)
    assert abs(chat.puck.pos.x() - errands.home.x()) < 1, 'her new place is her home now'


def _fake_studio(page, project_open=True):
    """Subtitle Studio's parts she knows, laid out like the editor: list left, tools right, timeline below."""
    from PySide6.QtWidgets import QFrame, QPushButton, QScrollArea
    studio = QFrame(page)
    studio.setGeometry(0, 100, 1200, 700)
    studio.cue_list_panel = QFrame(studio)
    studio.cue_list_panel.setGeometry(0, 0, 300, 420)
    studio.pager = QPushButton('›', studio.cue_list_panel)
    studio.pager.setGeometry(220, 380, 60, 32)
    studio.context_panel = QFrame(studio)
    studio.context_panel.setGeometry(900, 0, 300, 420)
    studio.tab = QPushButton('AI设计', studio.context_panel)
    studio.tab.setGeometry(10, 10, 280, 40)
    studio.video_overlay_host = QFrame(studio)
    studio.video_overlay_host.setGeometry(300, 0, 600, 420)
    studio.timeline = QFrame(studio)
    studio.timeline.setGeometry(0, 430, 1200, 270)
    studio.project_library_scroll = QScrollArea(studio)
    studio.project_library_scroll.setGeometry(0, 0, 1200, 700)
    studio.project_library_scroll.setVisible(not project_open)
    studio.show()
    page.built_page = lambda name: studio if name == 'studio' else None
    return studio


def test_in_the_studio_editor_she_turns_small_and_naps_clear_of_the_timeline(app, page, monkeypatch):
    """Round 3 (user): in Subtitle Studio she keeps clear of the timeline and important places — smaller,
    asleep at the bottom or top of the subtitle list or the tool panel."""
    from PySide6.QtCore import QRect
    from twobyteasr.app import bunny_errands, ui_zoom
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    studio = _fake_studio(page)
    app.processEvents()
    monkeypatch.setattr(errands, 'page', lambda: '字幕工作台')
    assert errands.context() == 'editor'
    assert errands.candidates() == [], 'no playing with the editor\'s buttons'
    small = errands._height_for('editor')
    assert small == ui_zoom.px(bunny_errands.SMALL_HEIGHT) < mascot.mascot_height
    assert errands.start('resize', small)
    assert _until(app, lambda: not errands.busy(), seconds=6)
    assert mascot.mascot_height == small
    spots = errands._safe_spots()
    assert spots
    rect = lambda w: QRect(w.mapTo(page, w.rect().topLeft()), w.size())  # noqa: E731
    for spot in spots:
        body = errands._drawn(spot).adjusted(4, 6, -4, -2)
        for widget in (studio.timeline, studio.video_overlay_host, studio.pager, studio.tab):
            assert not body.intersects(rect(widget).adjusted(2, 2, -2, -2)), widget
    choice = errands.pick()
    assert choice[0] == 'nap'
    monkeypatch.setattr(bunny_errands, 'NAP_S', (2.0, 2.0))
    assert errands.start(*choice)
    assert _until(app, lambda: mascot.current_move == 'curl_nap', seconds=6)
    assert 'zzz' in mascot.stickers
    assert errands._safe_here()
    assert _until(app, lambda: not errands.busy(), seconds=8)
    assert 'zzz' not in mascot.stickers
    # Out of the editor (the project library) she is her own size again.
    studio.project_library_scroll.show()
    app.processEvents()
    assert errands.context() == 'hub'
    assert errands._height_for('hub') > small


def test_she_hops_from_card_to_card_and_each_one_gives_under_her(app, page, monkeypatch):
    """Round 3 (user): in the project library she hops between the projects (also the workshop's model cards)."""
    from PySide6.QtWidgets import QFrame
    chat = _folded(page)
    errands = chat.errands
    studio = _fake_studio(page, project_open=False)
    cards = []
    for index in range(4):
        card = QFrame(studio.project_library_scroll)
        card.setGeometry(60 + index * 270, 260, 240, 180)
        card.show()
        cards.append(card)
    studio._hub_card_widgets = cards
    app.processEvents()
    monkeypatch.setattr(errands, 'page', lambda: '字幕工作台')
    assert errands.context() == 'hub'
    assert len(errands._cards()) == 4
    assert ('card_hop', errands._cards()) in [(n, t) for n, t in errands.candidates() if n == 'card_hop']
    assert errands.start('card_hop', errands._cards())
    assert _until(app, lambda: any(errands.fx.moving(card) for card in cards), seconds=6), 'a card dips as she lands'
    assert _until(app, lambda: not errands.busy(), seconds=12)
    assert _until(app, lambda: not any(errands.fx.moving(card) for card in cards), seconds=6)


def test_she_is_lively_from_the_start_and_fidgets_between_errands(app, page):
    """Round 4 (user): waiting 10-20 s before she moved was too long."""
    from twobyteasr.app import bunny_errands
    assert bunny_errands.FIRST_S[1] <= 5 and bunny_errands.GAP_S[1] <= 15 and bunny_errands.FIDGET_S[1] <= 5
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    assert errands.next_at - time.monotonic() <= bunny_errands.FIRST_S[1] + .5
    _until(app, lambda: not mascot.current_move, seconds=4)
    errands._fidget(False)
    assert mascot.current_move in errands.FIDGETS or mascot._hop_from > 0 or mascot.ear_bias != 0


def _rush_over(errands, page, monkeypatch, points):
    from PySide6.QtGui import QCursor
    monkeypatch.setattr(QCursor, 'pos', staticmethod(lambda: page.mapToGlobal(points[0].toPoint())))
    errands._watch()
    time.sleep(.05)
    points.pop(0)
    errands._watch()


def test_a_pointer_rushing_over_her_head_only_now_and_then_makes_her_leap(app, page, monkeypatch):
    """2026-11-27 (user): she leapt every time the pointer crossed her head; now and then is enough.
    The other passes she only notices it."""
    from PySide6.QtCore import QPointF
    from twobyteasr.app import bunny_errands
    chat = _folded(page)
    errands, mascot = chat.errands, chat.mascot
    zone = errands._head_zone()
    over = QPointF(zone.center().x(), zone.top() + 30)
    monkeypatch.setattr(errands, '_watchable', lambda: True)
    monkeypatch.setattr(bunny_errands, 'POUNCE_CHANCE', 0.0)
    mascot.stop_move()
    _rush_over(errands, page, monkeypatch, [QPointF(over.x() - 120, over.y()), QPointF(over.x() + 10, over.y())])
    assert errands.name == '' and mascot.current_move in ('ears_up', 'tilt'), 'noticed, no leap'
    assert bunny_errands.POUNCE_GAP_S >= 8 and bunny_errands.SWAT_GAP_S >= 12


def test_leaping_for_the_pointer_she_follows_it_and_hangs_on_when_caught(app, page, monkeypatch):
    """2026-11-27 (user): she jumped to a fixed spot; she should follow the pointer as she leaps, and
    once she has caught it really hang on it."""
    from PySide6.QtCore import QPointF
    from twobyteasr.app import bunny_errands
    from twobyteasr.app.bunny_errands import LIFT_TOP
    chat = _folded(page)
    errands, mascot, puck = chat.errands, chat.mascot, chat.puck
    monkeypatch.setattr(errands, '_watchable', lambda: True)
    monkeypatch.setattr(bunny_errands, 'POUNCE_CHANCE', 1.0)
    monkeypatch.setattr(bunny_errands, 'DANGLE_S', (1.0, 1.0))
    zone = errands._head_zone()
    over = QPointF(zone.center().x(), zone.top() + 30)
    points = [QPointF(over.x() - 120, over.y()), QPointF(over.x() + 10, over.y())]
    _rush_over(errands, page, monkeypatch, points)
    assert errands.name == 'pounce'
    start = QPointF(errands.home)
    assert _until(app, lambda: mascot.current_move == 'catch', seconds=3)
    # The pointer darts to the side while she is in the air: she comes down toward where it is now.
    side = -1 if over.x() > page.width() / 2 else 1    # toward the middle of the window
    points[0] = QPointF(over.x() + side * 110, over.y() + 30)
    assert _until(app, lambda: puck.mode == 'held', seconds=3), 'caught: she hangs on the pointer'
    assert (puck.pos.x() - start.x()) * side > 60, (puck.pos, start)
    assert mascot.current_move == 'cling'
    paws = puck.window_point(LIFT_TOP)
    assert abs(paws.x() - points[0].x()) < 70 and abs(paws.y() - points[0].y()) < 70
    # Hanging there, she swings after the pointer as it moves.
    points[0] = QPointF(points[0].x() - 160, points[0].y() + 30)
    before = QPointF(puck.pos)
    assert _until(app, lambda: puck.pos.x() < before.x() - 80, seconds=1.5)
    # Then she lets go and drops; the errand is over and she lands on her own.
    assert _until(app, lambda: not errands.busy(), seconds=4)
    assert _until(app, lambda: puck.mode == 'rest', seconds=10)
    assert mascot.current_move != 'cling'


def test_a_pointer_out_of_reach_she_misses_and_lands_where_she_was(app, page, monkeypatch):
    from PySide6.QtCore import QPointF
    from twobyteasr.app import bunny_errands
    chat = _folded(page)
    errands, mascot, puck = chat.errands, chat.mascot, chat.puck
    monkeypatch.setattr(errands, '_watchable', lambda: True)
    monkeypatch.setattr(bunny_errands, 'POUNCE_CHANCE', 1.0)
    zone = errands._head_zone()
    over = QPointF(zone.center().x(), zone.top() + 30)
    points = [QPointF(over.x() - 120, over.y()), QPointF(over.x() + 10, over.y())]
    _rush_over(errands, page, monkeypatch, points)
    assert errands.name == 'pounce'
    start = QPointF(errands.home)
    side = -1 if over.x() > page.width() / 2 else 1
    points[0] = QPointF(over.x() + side * 700, max(4.0, over.y() - 600))     # gone far away at once
    assert _until(app, lambda: puck.pos.y() < start.y() - 20, seconds=3), 'she leaps up at it'
    assert _until(app, lambda: not errands.busy(), seconds=6)
    assert puck.mode == 'rest'
    assert abs(puck.pos.y() - start.y()) < 1 and abs(puck.pos.x() - start.x()) < 1 and mascot.current_move != 'catch'


def test_a_pointer_resting_on_a_nearby_button_gets_pounced(app, page, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QPushButton
    chat = _folded(page)
    errands, puck = chat.errands, chat.puck
    body = errands._drawn(puck.pos)
    button = QPushButton('近处的按钮', page)
    button.setGeometry(body.left() - 140, body.top() + 10, 110, 32)
    button.show()
    app.processEvents()
    at = QPointF(button.geometry().center())
    from twobyteasr.app import bunny_errands
    monkeypatch.setattr(bunny_errands, 'SWAT_CHANCE', 1.0)
    monkeypatch.setattr(bunny_errands, 'SWAT_HOVER_S', 0.3)
    monkeypatch.setattr(bunny_errands, 'DANGLE_S', (0.6, 0.6))
    monkeypatch.setattr(errands, '_watchable', lambda: True)
    monkeypatch.setattr(QCursor, 'pos', staticmethod(lambda: page.mapToGlobal(at.toPoint())))
    errands._watch()
    time.sleep(.4)
    errands._watch()
    assert errands.name == 'pounce'
    assert _until(app, lambda: errands.fx.moving(button), seconds=4), 'the button jolts under her paws'
    assert _until(app, lambda: not errands.busy(), seconds=6)
