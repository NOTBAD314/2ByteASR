"""Exercise the new motion and quota feedback in the normal Windows app."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def start(window, output: Path):
    app = QApplication.instance()
    result = {'passed': False, 'pid': os.getpid(), 'checks': [], 'metrics': {}}

    def check(name, condition):
        result['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def wait_until(predicate, timeout=5):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            app.processEvents()
            if value := predicate():
                return value
            QTest.qWait(5)
        return None

    def save():
        (output / 'result.json').write_text(json.dumps(result, indent=2), 'utf-8')

    def shot(widget, filename):
        check(filename, widget.grab().save(str(output / (filename + '.png'))))

    def first_paint(scope, command, target):
        started = time.perf_counter()
        timestamps = []

        class FirstPaint(QObject):
            def eventFilter(self, watched, event):
                if not timestamps and event.type() == QEvent.Type.Paint and watched is target():
                    timestamps.append(round((time.perf_counter() - started) * 1000, 1))
                return False

        measure = FirstPaint()
        app.installEventFilter(measure)
        try:
            command()
            check(scope + ' first paint', wait_until(lambda: timestamps))
            result['metrics'][scope + '_first_paint_ms'] = timestamps[0]
        finally:
            app.removeEventFilter(measure)

    def run():
        try:
            from ..design.transitions import PageCrossfade, PageHold

            def overlay(parent):
                return next((item for item in parent.findChildren(
                    PageCrossfade, options=Qt.FindChildOption.FindDirectChildrenOnly)
                    if item.isVisible()), None)

            def observe_fade(parent, label, filename):
                cover = wait_until(lambda: overlay(parent))
                check(label + ' covers the live page without taking input',
                      cover is not None and cover.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                      and cover.pixmap is not None and not cover.pixmap.isNull())
                def progressed_or_finished():
                    item = overlay(parent)
                    return 'finished' if item is None else ('progressed' if .12 < item.progress < .87 else None)

                state = wait_until(progressed_or_finished)
                check(label + ' progresses or settles promptly after a late frame', state is not None)
                result['metrics'][filename] = state
                shot(parent, filename)
                check(label + ' clears itself', wait_until(lambda: not overlay(parent)))

            from ..design.motion_tokens import PRESS_SCALE
            from ..design.smooth_scroll import scroll_area_for

            app.setProperty('reduceMotion', False)
            window.showNormal()
            window.resize(1120, 740)
            check('home visible', wait_until(lambda: window.settings_scroll.isVisible()))
            check('idle preparation completed', wait_until(
                lambda: (runner := window.__dict__.get('_idle_preparation')) and runner.done, 36))
            cached = window.__dict__.get('_application_settings_cache')
            workshop = window.built_page('workshop')
            check('settings prepared hidden', cached is not None and not cached.isVisible())
            check('workshop prepared hidden', workshop is not None and workshop._ui_built
                  and not workshop.__dict__.get('_ui_refresh_pending', False) and not workshop.isVisible())
            check('Studio page still lazy', window.built_page('studio') is None)

            settings = window.app_settings_button
            QTest.mousePress(settings, Qt.MouseButton.LeftButton)
            effect = settings.graphicsEffect()
            check('actual button has press effect', effect is not None and hasattr(effect, 'scale'))
            check('press reaches a smaller scale', wait_until(lambda: PRESS_SCALE - .01 <= effect.scale < .995))
            shot(settings, 'settings-button-pressed')
            opened_settings = []
            auto_close = QTimer(window)
            auto_close.setInterval(80)

            dialog_motion = app._dialog_motion
            opening_frames = []

            def sample_settings(dialog):
                key = next((key for key, flight in dialog_motion._flights.items()
                            if flight.dialog is dialog), None)
                if key is None:
                    return
                flight = dialog_motion._flights[key]
                opening_frames.append(float(flight.ghost.rect_now.width()))
                if len(opening_frames) == 2:
                    shot(flight.ghost, 'settings-dialog-in-flight')

            def close_settings():
                dialog = window.__dict__.get('_application_settings_dialog')
                if dialog is None or not dialog.isVisible():
                    return
                sample_settings(dialog)
                if dialog_motion.flying(dialog) or dialog.windowOpacity() < 1:
                    return
                auto_close.stop()
                opened_settings.append((dialog is cached, dialog.grab().save(str(output / 'application-settings.png'))))
                QTest.keyClick(dialog, Qt.Key.Key_Escape)

            auto_close.timeout.connect(close_settings)
            auto_close.start()
            first_paint('settings', lambda: QTest.mouseRelease(settings, Qt.MouseButton.LeftButton),
                        lambda: window.__dict__.get('_application_settings_dialog'))
            auto_close.stop()
            check('settings opens from hidden cache and renders', opened_settings == [(True, True)])
            check('dialog animation approaches the settings window without growing past it',
                  all(a <= b for a, b in zip(opening_frames, opening_frames[1:]))
                  and all(width <= cached.width() + 1 for width in opening_frames))
            result['metrics']['settings_opening_sample_widths'] = opening_frames
            check('dialog closes with a ghost while its real window is hidden',
                  not cached.isVisible() and dialog_motion.flying(cached))
            check('dialog exit ghost clears itself', wait_until(lambda: not dialog_motion.flying(cached)))
            check('settings closes by Escape', not cached.isVisible())
            check('released button removes scale effect', wait_until(lambda: settings.graphicsEffect() is None))
            # An interrupted press must also unwind even when the mouse release goes elsewhere.
            QTest.mousePress(settings, Qt.MouseButton.LeftButton)
            check('new press starts another effect', settings.graphicsEffect() is not None)
            QCoreApplication.sendEvent(settings, QEvent(QEvent.Type.UngrabMouse))
            check('interrupted press returns to rest', wait_until(lambda: settings.graphicsEffect() is None))
            settings.setDown(False)

            scroll = window.settings_scroll
            viewport = scroll.viewport()
            bar = scroll.verticalScrollBar()
            if bar.maximum() < 15:
                window.resize(1040, 520)
            check('home scroll area has range', wait_until(lambda: bar.maximum() >= 15))
            check('normal home scroll viewport', scroll_area_for(viewport) is scroll)
            bar.setValue(bar.minimum())
            def notch():
                pos = viewport.rect().center()
                event = QWheelEvent(QPointF(pos), QPointF(viewport.mapToGlobal(pos)), QPoint(), QPoint(0, -120),
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
                QCoreApplication.sendEvent(viewport, event)

            notch()
            scroller = app._smooth_scroller
            check('wheel starts a glide', scroller.gliding(bar) and bar.value() == bar.minimum())
            check('glide settles', wait_until(lambda: not scroller.gliding(bar)))
            expected = min(bar.maximum(), bar.minimum() + QApplication.wheelScrollLines() * bar.singleStep())
            check('glide keeps wheel distance', bar.value() == expected and expected > bar.minimum())
            bar.setValue(bar.minimum())
            app.setProperty('reduceMotion', True)
            notch()
            check('reduced motion keeps native wheel response', not scroller.gliding(bar) and bar.value() > bar.minimum())
            app.setProperty('reduceMotion', False)

            from shiboken6 import isValid

            page_holds = []

            def open_workshop():
                window.model_workshop_button.click()
                holds = [item for item in window.pages.findChildren(
                    PageHold, options=Qt.FindChildOption.FindDirectChildrenOnly) if item.isVisible()]
                check('home to Workshop keeps exactly one old snapshot while the page settles',
                      len(holds) == 1 and holds[0].phase == 'hold' and not holds[0].old.isNull()
                      and holds[0].testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
                      and not holds[0].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
                page_holds.extend(holds)

            first_paint('workshop', open_workshop, lambda: workshop)
            check('workshop opened on its normal route', window.pages.currentWidget() is workshop)
            cover = page_holds[0]
            check('home to Workshop fades between two snapshots and passes input through',
                  wait_until(lambda: isValid(cover) and cover.phase == 'fade' and cover.new is not None
                             and not cover.new.isNull()
                             and cover.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)))
            check('home to Workshop slides in from the right in several parts',
                  cover.choreo is not None and cover.choreo.direction == 1 and len(cover.choreo.parts) > 1)
            shot(window.pages, 'home-to-workshop-fade')
            check('home to Workshop removes the cover after the fade',
                  wait_until(lambda: not isValid(cover) or not cover.isVisible()))
            browse = workshop._drag_scroll.scroll
            choices = [button for button in workshop.tab_group.buttons()
                       if button.isVisible() and button.property('role') != workshop.browser_role]
            check('alternate Workshop categories are available', choices)
            role_button = choices[0]
            role_button.click()
            check('Workshop category updates immediately', workshop.browser_role == role_button.property('role'))
            observe_fade(browse, 'Workshop category fade', 'workshop-category-fade')
            app.setProperty('reduceMotion', True)
            if len(choices) > 1:
                choices[1].click()
                check('reduced motion switches category without overlay',
                      workshop.browser_role == choices[1].property('role') and not overlay(browse))
            app.setProperty('reduceMotion', False)
            shot(workshop, 'model-workshop')

            from ..design.ui_navigation import WorkspaceSidebar

            def navigate_with_sidebar(page, key, destination, direction, name):
                sidebar = page.findChild(WorkspaceSidebar)
                old_position = sidebar.mapTo(window.pages, QPoint())
                sidebar.navigation.buttons[key].click()
                holders = [item for item in window.pages.findChildren(
                    PageHold, options=Qt.FindChildOption.FindDirectChildrenOnly) if item.isVisible()]
                check(f'{name} opens the destination under one hold',
                      len(holders) == 1 and window.pages.currentWidget() is destination)
                hold = holders[0]
                check(f'{name} starts a slide', wait_until(
                    lambda: isValid(hold) and hold.phase == 'fade' and hold.choreo is not None))
                motion = hold.choreo
                check(f'{name} keeps the sidebar and moves the highlight',
                      motion.direction == direction and motion.keep is not None and motion.glide is not None
                      and motion.keep.topLeft() == old_position
                      and motion.glide[0].y() != motion.glide[1].y())
                check(f'{name} keeps the selected button checked', motion.selected_button.isChecked())
                shot(window.pages, name + '-slide')
                check(f'{name} removes the overlay', wait_until(lambda: not isValid(hold) or not hold.isVisible()))

            terms = window.term_library_page
            navigate_with_sidebar(workshop, 'terms', terms, 1, 'workshop-to-terms')
            check('term library becomes usable', wait_until(
                lambda: terms.library and terms.library.game_list.isVisible(), 12))
            shot(terms, 'term-library-ready')
            navigate_with_sidebar(terms, 'workshop', workshop, -1, 'terms-to-workshop')
            window._return_to_settings()
            check('home visible after workshop', wait_until(lambda: window.settings_scroll.isVisible()))

            window.pages.setCurrentIndex(1)
            bar = window.progress_bar
            check('recognition progress bar is visible', wait_until(bar.isVisible))
            bar.setValue(0)
            bar.setValue(600)
            check('real progress updates immediately', bar.value() == 600)
            check('progress fill glides toward the real value', wait_until(lambda: 0 < bar._shown < 600))
            shot(bar, 'recognition-progress-in-flight')
            check('context menus fade with motion enabled', QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu))
            app.setProperty('reduceMotion', True)
            check('reducing motion settles the running glide', wait_until(lambda: bar._shown == bar.value()))
            check('reducing motion disables menu fades', not QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu))
            bar.setValue(0)
            check('reset immediately empties the fill', bar._shown == 0)
            app.setProperty('reduceMotion', False)
            window._return_to_settings()

            watch = window._quota_watch()
            window._append_console_line('[阶段 1/3] HTTP 429: rate limited')
            check('rate limit leaves balance watcher quiet', watch.problem is None)
            window._append_console_line('[文件失败] fixture.wav：MOSI 账户积分不足（HTTP 402）。')
            check('balance failure opens a real dialog', wait_until(lambda: watch.dialog and watch.dialog.isVisible()))
            dialog = watch.dialog
            check('balance dialog names MOSS and offers top-up', 'MOSS' in dialog.heading.text()
                  and dialog.top_up_button is not None and dialog.stop_button is None)
            window._append_console_line('[文件失败] fixture-2.wav：MOSI 账户积分不足（HTTP 402）。')
            app.processEvents()
            check('duplicate failure keeps a single dialog', watch.dialog is dialog)
            shot(dialog, 'recognition-balance-alert')
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            check('balance dialog dismisses on Escape', wait_until(lambda: watch.dialog is None))
            watch.reset()
            window._append_console_line('[文件失败] fixture.wav：账户欠费 Arrearage')
            check('next run can show provider-specific alert', wait_until(lambda: watch.dialog and
                  watch.dialog.isVisible() and watch.dialog.problem.service == 'qwen'))
            watch.reset()
            check('reset dismisses stale alert', watch.dialog is None)

            started = time.perf_counter()
            first_paint('studio_loading', window.subtitle_studio_button.click,
                        lambda: window.__dict__.get('_studio_entry_loading'))
            studio = wait_until(lambda: window.built_page('studio')
                                if window.pages.currentWidget() is window.built_page('studio') else None, 40)
            check('Studio finishes opening', studio is not None and studio.isVisible())
            result['metrics']['studio_page_visible_ms'] = round((time.perf_counter() - started) * 1000, 1)
            shot(studio, 'subtitle-studio')
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
        save()
        window.close()

    def quit_record():
        result['gui_shutdown'] = True
        save()

    app.aboutToQuit.connect(quit_record)
    QTimer.singleShot(1200, window, run)
