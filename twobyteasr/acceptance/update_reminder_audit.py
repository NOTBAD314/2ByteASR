"""Real-window audit: the start-up update reminder (2026-10-24).

User request: check for updates every time the program opens, pop up a newer
version by itself, and let the user turn the pop-up off in the settings.

``scripts/verify_update_reminder_headed.py`` starts the real program three
times with one isolated profile (``UPDATE_REMINDER_PHASE``). The update answer
is a stand-in "0.9.0 is out" inside the program: nothing goes to the network.

first   A dialog is open when the check returns: the offer waits until it is
        closed, then pops up by itself with its switch ticked. The switch is
        unticked and 稍后 pressed: the setting is off; the top button shows
        the new version.
second  No pop-up; the button still shows the new version. 应用设置 → 关于
        shows the switch off; it is turned on and saved.
third   The offer pops up by itself again; 稍后 keeps the setting on.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

VERSION = '0.9.0'
CALLS = []


def _fake_check(**kwargs):
    from ..app.updater import ComponentAction, UpdatePlan, current_version
    CALLS.append(dict(kwargs, at=time.time()))
    plan = UpdatePlan('components', (ComponentAction('app', 'changed', 48_000_000, 48_000_000, 48_000_000),),
                      48_000_000, 1_000_000_000, '', (), ())
    notes = '新增：每次打开软件自动检查更新，有新版本就提醒。（验收用的假版本）'
    return SimpleNamespace(manifest=SimpleNamespace(note_for=lambda language: notes), plan=plan, newer=True,
                           latest_version=VERSION, current_version=current_version(),
                           release_url='https://example.invalid/release', installer_url='https://example.invalid/setup')


def install_guards() -> None:
    """Loopback only, the stand-in answer, and the automatic check allowed in this QA run."""
    from .run_diagnosis_audit import install_guards as loopback_only
    from ..app import update_dialog, updater
    loopback_only()
    os.environ[updater.QA_AUTO_ENV] = '1'
    os.environ[updater.AUTO_DELAY_ENV] = '6000'
    update_dialog.check_for_update = _fake_check


def start(window, out):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QMessageBox
    from ..app.application_settings import update_reminder_enabled
    from ..app.update_dialog import UpdateOfferDialog
    from ..diagnostics.build_identity import load_build_identity

    out = Path(out)
    phase = os.environ.get('UPDATE_REMINDER_PHASE', 'first')
    result = dict(phase=phase, passed=False, checks=[], screenshots=[], pid=os.getpid(), executable=sys.executable,
                  build=load_build_identity().to_dict(), reminder_at_start=update_reminder_enabled())
    began = time.monotonic()

    def save():
        result['calls'] = len(CALLS)
        (out / f'result-{phase}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save()
        if not ok:
            raise AssertionError(name)

    def pump(seconds=.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def shot(name, widget=None):
        path = out / f'{phase}-{len(result["screenshots"]) + 1:02d}-{name}.png'
        (widget or window).grab().save(str(path))
        result['screenshots'].append(path.name)

    def offers():
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, UpdateOfferDialog) and w.isVisible()]

    def wait_for(condition, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump(.1)
            if condition():
                return True
        return False

    def describe(dialog):
        box = dialog.findChild(QCheckBox, 'updateReminderBox')
        hint = dialog.findChild(QLabel, 'updateReminderHint')
        return dict(title=dialog.windowTitle(), labels=[w.text() for w in dialog.findChildren(QLabel)][:4],
                    switch=box.isChecked() if box else None, switch_text=box.text() if box else '',
                    hint=hint.text() if hint else '', seconds_after_start=round(time.monotonic() - began, 1))

    # The offer and the settings run their own event loops (exec), with this
    # audit's code paused underneath; a timer instance answers them.
    answers = dict(untick=False, settings={})

    def watch():
        for dialog in offers():
            if 'offer' not in result:
                result['offer'] = describe(dialog)
                shot('offer', dialog)
            if answers['untick']:
                dialog.remind_box.setChecked(False)
            dialog.reject()
        settings = next((w for w in QApplication.topLevelWidgets()
                         if w.objectName() == 'applicationSettings' and w.isVisible()), None)
        seen = answers['settings']
        if settings is not None and 'before' not in seen:
            try:
                seen['before'] = settings.update_reminder_box.isChecked()
                seen['page'] = settings.navigation.currentItem().text() if settings.navigation.currentItem() else ''
                shot('settings-about', settings)
                settings.update_reminder_box.setChecked(True)
                from PySide6.QtWidgets import QDialogButtonBox
                settings.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            except Exception:
                seen['error'] = traceback.format_exc()
                settings.reject()
    watcher = QTimer(window)
    watcher.setInterval(400)
    watcher.timeout.connect(watch)

    def run():
        try:
            watcher.start()
            window.showNormal()
            window.resize(1440, 900)
            pump(.5)
            if phase == 'first':
                check('the reminder is on by default', result['reminder_at_start'] is True)
                # Something else is open when the answer arrives: the offer waits.
                busy = QMessageBox(QMessageBox.Icon.Information, '别的窗口', '用户正在看别的窗口', parent=window)
                busy.open()
                check('the check ran at start-up', wait_for(lambda: CALLS, 15), CALLS)
                check('the start-up check reuses only a recent answer',
                      CALLS[0].get('use_cache') is True and CALLS[0].get('cache_seconds') == 600, CALLS[0])
                pump(6.0)
                check('no offer while another dialog is open', 'offer' not in result and not offers())
                busy.done(0)
                answers['untick'] = True
                check('the offer pops up once the user is free', wait_for(lambda: 'offer' in result, 25))
                check('the offer names the new version and has the switch ticked',
                      VERSION in ' '.join(result['offer']['labels']) and result['offer']['switch'] is True
                      and '应用设置' in result['offer']['hint'], result['offer'])
                check('the offer closes', wait_for(lambda: not offers(), 10))
                pump(1.0)
                check('unticking turned the reminder off', update_reminder_enabled() is False)
                button = window.update_button.text()
                result['button'] = button
                shot('top-bar')
                check('the top button shows the new version', VERSION in button, button)
            elif phase == 'second':
                check('the reminder starts off', result['reminder_at_start'] is False)
                check('the daily background check still ran', wait_for(lambda: CALLS, 15), CALLS)
                pump(6.0)
                check('no pop-up with the reminder off', 'offer' not in result and not offers())
                button = window.update_button.text()
                result['button'] = button
                check('the top button shows the new version', VERSION in button, button)
                shot('top-bar')
                window._open_application_settings(initial_section='关于')
                pump(1.0)
                seen = result['settings'] = answers['settings']
                check('应用设置 → 关于 shows the switch off', seen.get('before') is False and not seen.get('error'), seen)
                check('turning it on in the settings saves it', update_reminder_enabled() is True)
            else:
                check('the reminder starts on again', result['reminder_at_start'] is True)
                check('the offer pops up by itself again', wait_for(lambda: 'offer' in result, 25))
                check('the offer closes', wait_for(lambda: not offers(), 10))
                pump(1.0)
                check('稍后 with the switch ticked keeps the reminder on', update_reminder_enabled() is True)
                check('one check per start', len(CALLS) == 1, len(CALLS))
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('failure')
            except Exception:
                pass
        finally:
            watcher.stop()
            save()
            QTimer.singleShot(300, close)

    def close():
        result['gui_shutdown'] = True
        save()
        window.result_exit_code = 0
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(1000, run)
