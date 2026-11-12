"""Opt-in speaker-board checks through the normal, isolated MainWindow."""
from __future__ import annotations

import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, lambda: run(window, output))


def run(window, output):
    from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project, save_project
    from ..studio.studio_speaker_board import SPEAKER_MIME
    from ..studio.studio_speaker_manager import SpeakerManagerDialog

    app = QApplication.instance()
    checks, dialogs = [], []
    page = None
    error = None
    identity = load_build_identity().to_dict()

    def persist():
        (output / 'result.json').write_text(json.dumps(dict(
            passed=bool(checks) and error is None and all(c['passed'] for c in checks),
            checks=checks, error=error, identity=identity, pid=os.getpid(),
            theme=os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME', 'sand'),
            scale=os.environ.get('QT_SCALE_FACTOR', '1'), dpr=window.devicePixelRatioF(),
            input_scope='Qt clicks, keyboard and drag/drop events; physical mouse/IME feel not evaluated',
        ), ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        persist()
        if not value:
            raise AssertionError(name + ': ' + str(detail))

    def pump(seconds=.05):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            app.processEvents()
            # This audit lives in one timer callback inside dialog.exec().
            # Match normal input turns by delivering their deferred deletions.
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            time.sleep(.003)

    def wait(predicate, seconds=40):
        until = time.perf_counter() + seconds
        while not predicate() and time.perf_counter() < until:
            pump(.02)
        if not predicate():
            raise TimeoutError('Normal workbench did not become ready')

    def shot(dialog, name):
        pump(.15)
        check('window screenshot ' + name, dialog.grab().save(str(output / (name + '.png'))))

    def caption_content():
        return [(c.id, c.start_ms, c.end_ms, c.text) for c in page.project.cues]

    def drop(dialog, keys, kind, target=''):
        widget = dialog.boxes[dialog._box_index[target] if target else kind]
        mime = QMimeData()
        mime.setData(SPEAKER_MIME, '\n'.join(keys).encode('utf8'))
        # A box's centre can contain another speaker: that correctly merges.
        # Use its empty border for regrouping, or a named tile for merging.
        point = dialog.tiles[target].mapTo(widget, dialog.tiles[target].rect().center()) if target else QPoint(8, 8)
        enter = QDragEnterEvent(QPoint(point), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(widget, enter)
        check('drop target accepts ' + kind + target, enter.isAccepted())
        event = QDropEvent(QPointF(point), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(widget, event)
        pump(.15)
        check('drop event accepted ' + kind + target, event.isAccepted())

    try:
        apply_theme(os.environ.get('TWOBYTEASR_ACCEPTANCE_THEME', 'sand'), app)
        window.refresh_theme_palette()
        window.open_studio_project(str(output / 'fixture.2byteproj'))
        wait(lambda: window.built_page('studio') is not None and window.studio_page.project is not None)
        page = window.studio_page
        wait(lambda: getattr(window, '_studio_loading_session', None) is None
             or not window._studio_loading_session.active)
        wait(lambda: page.video._startup_state == 'READY')
        page.video.set_paused(True)
        initial = caption_content()
        original_speakers = [(s.id, s.name) for s in page.project.speakers]
        check('normal workbench owns twenty speakers', len(original_speakers) == 20)

        def exercise():
            nonlocal error
            dialog = app.activeModalWidget()
            if isinstance(dialog, SpeakerManagerDialog):
                dialogs.append(dialog)
            try:
                check('opened with normal speaker manager action', isinstance(dialog, SpeakerManagerDialog)
                      and dialog.page is page)
                check('frameless rounded window', bool(dialog.windowFlags() & Qt.FramelessWindowHint))
                check('two main eighteen secondary four boxes', len(dialog._box_keys('main')) == 2
                      and len(dialog._box_keys('secondary')) == 18 and len(dialog.boxes) == 4)
                viewport = dialog.scroll.viewport()
                visible = [tile for tile in dialog.boxes['secondary'].tiles if tile.isVisible()
                           and viewport.rect().contains(tile.mapTo(viewport, tile.rect().bottomRight()))]
                if os.environ.get('QT_SCALE_FACTOR', '1') in {'1', '1.0'}:
                    check('all secondary speakers visible at 100 percent', len(visible) == 18, len(visible))
                else:
                    check('secondary scroll remains available at 150 percent', bool(visible)
                          and dialog.scroll.verticalScrollBar().maximum() > 0, len(visible))
                shot(dialog, '01-board')
                original_size = dialog.size()
                for width in (original_size.width(), 1040, 1240):
                    dialog.resize(width, original_size.height()); pump(.15)
                    rows = {}
                    for tile in dialog.boxes['secondary'].tiles:
                        if not tile.isHidden():
                            rows.setdefault(tile.y(), []).append(tile.geometry())
                    ordered = [sorted(row, key=lambda rect: rect.x()) for _, row in sorted(rows.items())]
                    columns = [rect.x() for rect in ordered[0]]
                    check('secondary rows share column positions at width ' + str(width),
                          all([rect.x() for rect in row] == columns[:len(row)] for row in ordered)
                          and len({rect.width() for row in ordered for rect in row}) == 1,
                          [[rect.getRect() for rect in row] for row in ordered])
                dialog.resize(original_size); pump(.15)
                shot(dialog, '01b-aligned-board')
                QTest.mouseClick(dialog.tiles['API_S06'], Qt.LeftButton)
                pump()
                check('single click opens existing detail card', dialog.cards['API_S06'].isVisible())
                shot(dialog, '02-detail')
                QTest.mouseClick(dialog.tiles['API_S03'], Qt.LeftButton)
                QTest.mouseClick(dialog.tiles['API_S04'], Qt.LeftButton, Qt.ControlModifier)
                check('control click selects multiple', dialog._selection == {'API_S03', 'API_S04'})
                before = page.undo_stack.index()
                drop(dialog, ['API_S03', 'API_S04'], 'game')
                check('multiple dropped to game in one undo', page.undo_stack.index() == before + 1
                      and {'API_S03', 'API_S04', 'GAME_BACKGROUND'} <= set(dialog._box_keys('game')))
                shot(dialog, '03-game')
                page.undo_stack.undo(); pump()
                check('game undo restores exact caption content', caption_content() == initial
                      and len(page.project.speakers) == 20)
                before = page.undo_stack.index()
                drop(dialog, ['API_S19'], 'ignore')
                check('ignored label remains recoverable', 'API_S19' in dialog._box_keys('ignore'))
                drop(dialog, ['API_S19'], 'secondary')
                restored = caption_content()
                (output / 'restore-content.json').write_text(json.dumps(dict(
                    original=initial, restored=restored,
                    secondary=dialog._box_keys('secondary')), ensure_ascii=False, indent=2), 'utf8')
                check('restored label regains captions', 'API_S19' in dialog._box_keys('secondary')
                      and sorted(row[1:] for row in restored) == sorted(row[1:] for row in initial),
                      dict(before=len(initial), after=len(restored)))
                page.undo_stack.setIndex(before); pump()
                QTest.mouseClick(dialog.group_merge_button, Qt.LeftButton)
                pump()
                check('group button opens confirmation', dialog.inspector.currentWidget() is dialog.merge_panel
                      and len(dialog._selection) == 18)
                dialog.merge_panel.name_edit.setText('Board QA')
                target = dialog.merge_panel.target()
                shot(dialog, '04-merge-panel')
                before = page.undo_stack.index()
                QTest.mouseClick(dialog.merge_panel.confirm_button, Qt.LeftButton)
                pump(.15)
                check('group merge and rename use one undo', len(page.project.speakers) == 3
                      and page.undo_stack.index() == before + 1
                      and next(s for s in page.project.speakers if s.id == target).name == 'Board QA')
                check('group merge preserves text and timing', caption_content() == initial)
                shot(dialog, '05-merged')
                page.undo_stack.undo(); pump()
                check('group undo restores all speaker identities',
                      [(s.id, s.name) for s in page.project.speakers] == original_speakers)
                before = page.undo_stack.index()
                drop(dialog, ['API_S03'], 'main', target=dialog._box_keys('main')[0])
                check('drop onto speaker merges once', len(page.project.speakers) == 19
                      and page.undo_stack.index() == before + 1 and caption_content() == initial)
                page.undo_stack.undo(); pump()
                QTest.mouseClick(dialog.more_toggle, Qt.LeftButton); pump()
                check('existing more tools accessible', dialog.more_tools.isVisible()
                      and dialog.cleanup_range_button.isVisible())
                dialog.more_tools.hide()
                QTest.mouseClick(dialog.tiles['API_S06'], Qt.LeftButton); pump()
                dialog.cards['API_S06'].name_edit.setText('Close QA')
                dialog.accept(); pump()
                check('done commits pending speaker name',
                      next(s for s in page.project.speakers if s.id == 'API_S06').name == 'Close QA')
                page.undo_stack.undo(); pump()
                save_project(page.project, output / 'saved.2byteproj')
                reopened = load_project(output / 'saved.2byteproj')
                check('save reopen preserves content and speakers',
                      [(s.id, s.name) for s in reopened.speakers] == original_speakers
                      and [(c.id, c.start_ms, c.end_ms, c.text) for c in reopened.cues] == initial)
            except Exception:
                error = traceback.format_exc()
                (output / 'error.txt').write_text(error, 'utf8')
                if isinstance(dialog, SpeakerManagerDialog):
                    dialog.grab().save(str(output / 'failure.png'))
            finally:
                if isinstance(dialog, SpeakerManagerDialog):
                    dialog.accept()
                persist()

        QTimer.singleShot(250, exercise)
        page._open_speaker_manager()
    except Exception:
        error = traceback.format_exc()
        (output / 'error.txt').write_text(error, 'utf8')
    finally:
        for dialog in dialogs:
            dialog.accept()
        if page is not None:
            page.undo_stack.setClean()
            page.project_dirty = False
        persist()
        window.close()
        app.quit()
