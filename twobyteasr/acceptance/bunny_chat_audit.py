"""Normal-entry offline rabbit motion and interface audit."""
from pathlib import Path
import json, os, sys, time

def audit(win, output: Path, theme: str) -> int:
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output / 'profile')
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow, _app_font, _register_bundled_fonts
    from twobyteasr.app.help_menu import CuteMenu, CuteMenuAction
    from twobyteasr.app import bunny_chat
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    from twobyteasr.design.theme_manager import apply_theme, save_theme_key
    save_theme_key(theme)
    apply_theme(theme, app)
    checks, notes = [], {}
    loop_done = {'code': None}

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    def shot(name, widget=None):
        """The window with every visible window above it (a private desktop has no screen to grab)."""
        from PySide6.QtGui import QPainter
        if widget is not None:
            widget.grab().save(str(output / f'{name}.png'))
            return
        base = win.grab()
        painter = QPainter(base)
        origin = win.mapToGlobal(QPoint(0, 0))
        for top in QApplication.topLevelWidgets():
            if top is win or not top.isVisible() or top.width() < 2:
                continue
            at = top.mapToGlobal(QPoint(0, 0)) - origin
            painter.drawPixmap(at, top.grab())
        painter.end()
        base.save(str(output / f'{name}.png'))

    win.resize(1440, 900)
    win.show()

    def chat():
        live = getattr(win, '_bunny_chat', None)
        return live if live is not None and live.isVisible() else None

    def lines(card):
        return [v.replace(chr(0x2060), '') for v in card.last_reply_html()]

    def script():
        yield 3.0
        menus = []

        def capture_exec(menu, position, *args, **kwargs):
            menus.append(menu)
            menu.popup(position)
        CuteMenu.exec = capture_exec
        QTimer.singleShot(0, win._show_help_menu)
        yield lambda: bool(menus) and menus[0].isVisible()
        yield 0.4
        menu = menus[0]
        rows = [a.text() for a in menu.actions() if isinstance(a, CuteMenuAction)]
        # 2026-11-14 (user): 「问问兔白」 left 说明 for its own header button beside 设置.
        check('「问问兔白」 is no longer a row of 说明', '问问兔白' not in rows, rows)
        shot('01-help-menu-card', menu)
        menu.close()
        button = win.ask_bunny_button
        check('「问问兔白」 sits just left of 设置',
              button.isVisible() and button.geometry().right() <= win.app_settings_button.geometry().left(),
              [button.geometry().getRect(), win.app_settings_button.geometry().getRect()])
        shot('01b-ask-bunny-button', button.parentWidget())
        QTimer.singleShot(0, button.click)
        yield lambda: chat() is not None
        yield 1.2
        card = chat()
        card.reveal_all()
        yield 0.3
        check('the card floats above the window', card.floating and card.isWindow(), card.windowFlags())
        inside = win.geometry().contains(card.geometry())
        corner = win.geometry().right() - card.geometry().right()
        check('at the right inside the window', inside and 0 <= corner < 60,
              [card.geometry().getRect(), win.geometry().getRect()])
        start = win.start_button
        start_rect = QRect(start.mapToGlobal(QPoint(0, 0)), start.size())
        check('it leaves 「开始生成字幕」 uncovered', not start.isVisible() or not card.geometry().intersects(start_rect),
              [card.geometry().getRect(), start_rect.getRect(), start.isVisible()])
        check('兔白 stands beside the card', card.mascot is not None and card.mascot.isVisible())
        check('no AI: she says so and offers the AI settings',
              '找功能在哪里' in ''.join(lines(card)) and card.go_button.isVisible(), [lines(card), card.go_button.text()])
        check('the input has the keys', card.input.hasFocus() or app.focusWidget() is card.input,
              type(app.focusWidget()).__name__)
        shot('02-greeting-no-ai')

        card.input.setText('检查更新在哪')
        card.send()
        yield 0.2
        card.reveal_all()
        yield 0.3
        check('without AI she still finds the place', '检查更新' in ''.join(lines(card)) and card.spotlight.isVisible(),
              lines(card))
        shot('03-offline-points')

        # A stand-in AI answer: no request leaves the machine.
        monkey_ready = bunny_chat.ai_readiness
        bunny_chat.ai_readiness = lambda settings: (True, 'DeepSeek · deepseek-chat')
        answer = json.dumps({'lines': ['哇！下载模型要去上面的 **模型工坊** 哦～', '~~兔白才不会说它很好找~~ 这一步 ==不花钱==！'],
                             'point_to': 'model_workshop', 'offer_open': 'model_workshop', 'mood': 'excited'},
                            ensure_ascii=False)
        bunny_chat.BunnyChatWorker.run = lambda worker: worker.answered.emit(answer)
        card.close_chat()
        yield lambda: chat() is None
        QTimer.singleShot(0, win._open_bunny_chat)
        yield lambda: chat() is not None
        card = chat()
        check('first AI disclosure is complete before advancing',
              'DeepSeek' in card.box.label.source_html and '额度' in card.box.label.source_html.replace(chr(0x2060), '')
              and '字幕原文' in card.box.label.source_html.replace(chr(0x2060), '')
              and '关闭' in card.box.label.source_html.replace(chr(0x2060), ''), card.box.label.source_html)
        card.reveal_all()
        check('with AI the first greeting names the service', 'DeepSeek' in ''.join(lines(card)), lines(card))
        card.input.setText('模型去哪里下载')
        card.send()
        yield lambda: not card.busy
        yield 0.5
        card.reveal_all()
        yield 0.3
        target = card.spotlight.target
        button = win.model_workshop_button
        check('she points at 「模型工坊」', card.spotlight.isVisible()
              and target.topLeft() == button.mapTo(win, QPoint(0, 0)), [target.getRect()])
        check('「带我去」 is offered', card.go_button.isVisible() and card.go_button.text().endswith('模型工坊'),
              card.go_button.text())
        check('jokes are crossed out, key words marked', 'line-through' in ''.join(lines(card)), lines(card))
        card.spotlight.anim.pause()
        card.spotlight.level = 1.0
        card.spotlight.update()
        yield 0.2
        shot('04-answer-points')
        shot('04-answer-card', card)
        joke = card.box.label
        notes['joke_strike_lines'] = [[round(v, 1) for v in row] for row in joke.strike_lines()]
        notes['joke_class'] = type(joke).__name__
        notes['joke_font'] = [joke.font().family(), joke.font().pixelSize(), joke.font().pointSizeF()]
        notes['input_size'] = [card.input.width(), card.input.height(), card.input.minimumHeight(),
                               card.input.maximumHeight()]
        notes['send_size'] = [card.send_button.width(), card.send_button.height()]
        notes['app_sheet_has_lineedit'] = 'QLineEdit' in (app.styleSheet() or '')
        notes['window_sheet_len'] = len(win.styleSheet() or '')
        check('crossed-out words get a drawn line', bool(notes['joke_strike_lines']), notes['joke_strike_lines'])
        check('her words use 猫啃什锦黑', bunny_chat.chat_font_family() and joke.font().family() == bunny_chat.chat_font_family(),
              notes['joke_font'])
        check('the dialog box is the default view', card.mode == 'dialog' and card.box.isVisible())
        # She floated over to 「模型工坊」 when pointing at it, and comes back after a moment.
        check('pointing, she floats over to the place', card.puck is None or not card.puck.docked)
        yield lambda: card.puck is None or card.puck.docked
        # A, the chat thread: same talk, one bubble per line, 兔白 beside the panel.
        card.set_mode('thread')
        yield 0.6
        card.thread.scroll_to_end()
        yield 0.3
        shot('05-thread')
        shot('05-thread-card', card)
        painted = card.mascot.geometry().adjusted(card.mascot.pad_x, 0, -card.mascot.pad_x, 0)
        check('in the thread 兔白 covers no words', not card.thread.geometry().intersects(painted),
              [card.thread.geometry().getRect(), painted.getRect()])
        from twobyteasr.app.tour_mascot import MarkedLabel
        bubbles = [label.source_html.replace(chr(0x2060), '') for label in card.thread.body.findChildren(MarkedLabel)]
        check('the thread shows the whole talk', any('模型去哪里下载' in text for text in bubbles)
              and any('不花钱' in text for text in bubbles), len(bubbles))
        card.set_mode('dialog')
        yield 0.4
        # Thrown: she leaves the card, bounces off the window's edges and floats back.
        puck = card.puck
        hits = []
        real_hit = puck._edge_hit
        puck._edge_hit = lambda side, power: (hits.append(side), real_hit(side, power))
        puck.undock()
        import time as _time
        puck.velocity = QPointF(-2600, -1500)
        puck.started = puck.last = _time.perf_counter()
        puck.timer.start()
        yield lambda: bool(hits)
        yield 0.05
        shot('06-thrown-bounce')
        check('thrown, she bounces off the window edges', bool(hits), hits)
        check('she flies inside the window only', win.rect().adjusted(-200, -200, 200, 200).contains(
            QRect(puck.pos.toPoint(), puck.mascot.size())), [puck.pos.toTuple()])
        yield lambda: puck.docked
        check('then she floats back beside the box', puck.docked and card.mascot.parent() is card)
        puck._edge_hit = real_hit
        # Real Qt mouse delivery through the visible mascot, including reparenting while held.
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        mascot = card.mascot
        grab = QPointF(mascot.width()/2, mascot.height()/2)
        origin = QPointF(mascot.mapToGlobal(grab.toPoint()))
        start_card = card.pos()
        target = QPointF(win.mapToGlobal(QPoint(260, 180)))
        def pointer(kind, point):
            event = QMouseEvent(kind, grab, point,
                Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
            app.sendEvent(mascot, event)
        pointer(QEvent.Type.MouseButtonPress, origin)
        for index in range(1, 11):
            pointer(QEvent.Type.MouseMove, origin+(target-origin)*(index/10))
            yield .03
        yield 1.3
        check('carrying bunny moves and flips the chat card', card.flipped and card.box.flipped
              and card.pos().x() < start_card.x()-150 and card.pos().y() < start_card.y()-80)
        check('whole carried bunny stays inside the stationary mask', puck.carrier.rect().contains(mascot.geometry())
              and puck.carrier.mask().contains(mascot.geometry()))
        check('carried card and bunny update in the same frame', puck.card_at is not None
              and (puck.card_at-puck.pos).manhattanLength() < .01)
        shot('06b-carried-card')
        pointer(QEvent.Type.MouseButtonRelease, target)
        yield lambda: puck.docked
        kept = card.pos()
        card.relayout()
        check('after carrying card keeps its position and bunny docks on left', puck.card_at is None
              and card.mascot_slot.x() == 0 and (card.pos()-kept).manhattanLength() <= 2)
        # 「帮我做」: she floats to the dropdown, outlines it and changes it.
        before = win.recognition_language.currentData()
        wanted = 'en' if before != 'en' else 'ja'
        answer = json.dumps({'lines': ['要我帮你改吗？'], 'do': {'action': 'set_spoken_language', 'value': wanted}},
                            ensure_ascii=False)
        bunny_chat.BunnyChatWorker.run = lambda worker: worker.answered.emit(answer)
        card.input.setText('帮我改一下视频的语言')
        card.send()
        yield lambda: not card.busy
        card.reveal_all()
        yield 0.3
        check('「帮我做」 is offered and nothing changed yet', card.do_button.isVisible()
              and win.recognition_language.currentData() == before, card.do_button.text())
        shot('07-do-offered', card)
        card.do_button.click()
        yield lambda: win.recognition_language.currentData() == wanted
        yield 0.2
        spot = puck.spot_beside(win.recognition_language)
        shot('08-did-it')
        check('she floated beside the dropdown and changed it', not puck.docked
              and abs(puck.pos.x() - spot.x()) < 3 and abs(puck.pos.y() - spot.y()) < 3,
              [puck.pos.toTuple(), spot.toTuple()])
        win.recognition_language.setCurrentIndex(win.recognition_language.findData(before))
        # Exercise the actual frozen mascot painter and all named reactions.
        from twobyteasr.design.bunny_moves import MOVES, STICKERS, ACTS
        mascot = card.mascot
        for name in MOVES:
            mascot.stop_move()
            check('native move: ' + name, mascot.play(name))
            yield 0.04
            mascot.grab().save(str(output / ('move-' + name + '.png')))
        mascot.stop_move()
        for name in STICKERS:
            check('native sticker: ' + name, mascot.stick(name))
            yield 0.04
            mascot.grab().save(str(output / ('sticker-' + name + '.png')))
            mascot.unstick(name)
        for name, reaction in ACTS.items():
            mascot.stop_move()
            check('native reaction: ' + name, mascot.act(name))
            yield 0.04
        mascot.stop_move()
        card.task_finished(2)
        yield 0.2
        check('task completion cheers', mascot.current_move == 'cheer')
        shot('09-task-cheer')
        card.reveal_all()
        mascot.stop_move()
        original_idle = bunny_chat.IDLE_DOZE_S
        bunny_chat.IDLE_DOZE_S = 0.0
        card._active_at -= 1
        card._heartbeat()
        check('idle dozes', card._dozing and mascot.current_move == 'doze')
        shot('10-idle-doze')
        from PySide6.QtTest import QTest
        QTest.keyClicks(card.input, 'hello')
        yield 0.1
        check('typing wakes her', not card._dozing)
        bunny_chat.IDLE_DOZE_S = original_idle
        bunny_chat.ai_readiness = monkey_ready

        before = card.pos() - win.pos()
        win.move(win.pos() + QPoint(-40, -30))
        yield 0.5
        check('the card follows the window', (card.pos() - win.pos() - before).manhattanLength() <= 2,
              [(card.pos() - win.pos()).toTuple(), before.toTuple()])
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        app.sendEvent(card, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        yield lambda: chat() is None
        check('Esc closes it', getattr(win, '_bunny_chat', None) is None)
        loop_done['code'] = 0 if all(c['passed'] for c in checks) else 1

    steps = script()

    def drive():
        if loop_done['code'] is not None:
            return
        try:
            wanted = next(steps)
        except StopIteration:
            return
        except Exception as exc:  # noqa: BLE001
            import traceback
            notes['error'] = traceback.format_exc()
            check(f'no error ({exc})', False)
            loop_done['code'] = 1
            return
        if callable(wanted):
            deadline = time.monotonic() + 25

            def wait():
                if wanted():
                    QTimer.singleShot(20, drive)
                elif time.monotonic() > deadline:
                    check('bounded wait', False, getattr(wanted, '__name__', ''))
                    loop_done['code'] = 1
                else:
                    QTimer.singleShot(30, wait)
            QTimer.singleShot(0, wait)
        else:
            QTimer.singleShot(int(float(wanted) * 1000), drive)

    QTimer.singleShot(0, drive)
    deadline = time.monotonic() + 150
    while loop_done['code'] is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    result = dict(passed=loop_done['code'] == 0, checks=checks, notes=notes,
                  dpr=app.primaryScreen().devicePixelRatio())
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['passed'] else 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def run():
        try:
            code = audit(window, output, os.environ.get('TWOBYTEASR_BUNNY_THEME', 'sand'))
        except Exception:
            import traceback
            (output/'result.json').write_text(json.dumps(dict(passed=False,error=traceback.format_exc())), 'utf8')
            code=1
        QApplication.instance().exit(code)
    QTimer.singleShot(500, run)
