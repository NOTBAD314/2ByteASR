"""Real-window Model Workshop download (2026-10-14 mainland download round).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=workshop-download`` (isolated
data; the network path is whatever the launcher gives the process, e.g. a relay
that leaves through a mainland line). Does what a user does: opens the Model
Workshop, clicks the model card's action button, clicks 开始下载 in the download
window, optionally pauses once the weights are partly downloaded and clicks
继续重试, then waits for the real installer (runtime, weights, readiness check).
Records the window's status text and progress every second, screenshots every
few seconds, and the card state afterwards. Writes ``result.json``.

Config ``workshop-download.json`` in the output directory:
``{"model": "funasr_nano", "pause_at_percent": 20, "timeout": 5400, "label": "first"}``;
results go to ``<output>/<label>/``.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QProcess, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity

    config = json.loads((output / 'workshop-download.json').read_text('utf-8'))
    output = output / str(config.get('label') or 'first')
    output.mkdir(parents=True, exist_ok=True)
    key = str(config['model'])
    pause_at = config.get('pause_at_percent')
    deadline = time.monotonic() + float(config.get('timeout', 5400))
    shots = output / 'shots'
    shots.mkdir(parents=True, exist_ok=True)
    result = dict(model=key, identity=load_build_identity().to_dict(), timeline=[], events=[], passed=False)
    state = dict(dialog=None, paused=False, resumed=False, finished=False, shot=0, last_shot=0.0, started=time.monotonic())

    def event(name, **detail):
        result['events'].append(dict(t=round(time.monotonic() - state['started'], 1), event=name, **detail))

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def grab(widget, name):
        try:
            widget.grab().save(str(shots / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            event('grab_failed', name=name, error=str(exc))

    def finish(passed, reason=''):
        if state['finished']:
            return
        state['finished'] = True
        page = window.workshop_page
        page.refresh() if hasattr(page, 'refresh') else None
        card = page._cards.get(key)
        if card is not None:
            QApplication.processEvents()
            result['card_after'] = dict(action=card.action.text(), badge=card.state_badge.text(),
                                        action_enabled=card.action.isEnabled())
            grab(card, 'card-after')
        result['passed'] = bool(passed)
        result['reason'] = reason
        dialog = state['dialog']
        if dialog is not None:
            result['final_status'] = dialog.progress_status.text()
            result['log_tail'] = dialog.log.toPlainText().splitlines()[-60:]
            grab(dialog, 'dialog-final')
        save()
        QTimer.singleShot(800, QApplication.instance().quit)

    def on_completed(ok, message):
        dialog = state['dialog']
        event('completed', ok=bool(ok), paused=bool(dialog._paused), message=message)
        grab(dialog, f"completed-{len(result['events'])}")
        if dialog._paused and not state['resumed']:
            state['resumed'] = True
            # What a user does after pausing: click 继续重试 in the same window.
            QTimer.singleShot(3000, lambda: (event('click_retry', text=dialog.start_button.text()),
                                            QTest.mouseClick(dialog.start_button, Qt.MouseButton.LeftButton)))
            return
        finish(ok, message)

    def poll():
        if state['finished']:
            return
        dialog = state['dialog']
        now = time.monotonic()
        try:
            if dialog is not None:
                running = dialog.process.state() != QProcess.ProcessState.NotRunning
                text = dialog.progress_status.text()
                value = dialog.progress.value() if dialog.progress.maximum() else -1
                if not result['timeline'] or result['timeline'][-1]['status'] != text or result['timeline'][-1]['value'] != value:
                    result['timeline'].append(dict(t=round(now - state['started'], 1), phase=dialog._phase, value=value,
                                                   running=running, status=text))
                if now - state['last_shot'] >= float(config.get('shot_every', 5)):
                    state['last_shot'] = now
                    state['shot'] += 1
                    grab(dialog, f"progress-{state['shot']:03d}")
                    save()
                if (pause_at is not None and not state['paused'] and running and value >= int(pause_at)
                        and dialog._phase in {'weights_downloading', 'downloading', 'preparing', 'files_verifying'}
                        and dialog.progress.maximum() == 100 and '整个模型' in text):
                    state['paused'] = True
                    event('click_pause', status=text)
                    grab(dialog, 'before-pause')
                    QTest.mouseClick(dialog.pause_button, Qt.MouseButton.LeftButton)
            if now > deadline:
                if dialog is not None and dialog.process.state() != QProcess.ProcessState.NotRunning:
                    dialog._request_pause()
                finish(False, 'timeout')
                return
        except Exception:  # noqa: BLE001
            result['error'] = traceback.format_exc()
            finish(False, 'exception')
            return
        QTimer.singleShot(1000, poll)

    def begin():
        try:
            window._open_model_workshop()
            QApplication.processEvents()
            page = window.workshop_page
            card = page._cards[key]
            if hasattr(page, '_select_card'):
                page._select_card(key)
            result['card_before'] = dict(action=card.action.text(), badge=card.state_badge.text())
            grab(window, 'workshop')
            event('click_card_action', text=card.action.text())
            QTest.mouseClick(card.action, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            dialogs = [d for d in page._download_dialogs if key in d.download_keys]
            if not dialogs:
                raise RuntimeError('clicking the card did not open a download window')
            dialog = state['dialog'] = dialogs[-1]
            dialog.completed.connect(on_completed)
            result['download_keys'] = list(dialog.download_keys)
            result['source_choice'] = dialog.source_combo.currentData()
            grab(dialog, 'dialog-opened')
            event('click_start', text=dialog.start_button.text())
            QTest.mouseClick(dialog.start_button, Qt.MouseButton.LeftButton)
            QTimer.singleShot(1000, poll)
        except Exception:  # noqa: BLE001
            result['error'] = traceback.format_exc()
            finish(False, 'exception')

    QTimer.singleShot(3000, begin)
