"""Observe normal CLI project startup before running shared edit/save checks."""
import json
import os
from pathlib import Path
import time


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .macos_desktop_evidence import studio_snapshot
    target = Path(os.environ['EDIT_SAVE_PROJECT']).resolve()
    started = time.monotonic()
    timer = QTimer(window)
    timer.setInterval(50)
    record = dict(passed=False, passive_cli_startup=True, project_path=str(target))

    def save():
        (output/'startup-project-result.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str), 'utf8')

    def observe():
        page = window.built_page('studio')
        loading = window.__dict__.get('_studio_loading_session')
        ready = bool(page is not None and page.project is not None and page.project_path is not None
                     and Path(page.project_path).resolve() == target and page._readiness.ready)
        failed = loading is not None and loading.state == 'failed'
        if not ready and not failed and time.monotonic()-started < 120:
            return
        timer.stop()
        record.update(elapsed_ms=(time.monotonic()-started)*1000, passed=ready,
                      snapshot=studio_snapshot(page), loading=loading.snapshot() if loading is not None else None)
        window.grab().save(str(output/'startup-project.png'))
        save()
        if ready:
            if os.environ.get('EDIT_SAVE_PART') == 'caret':
                from .caption_caret_split_audit import start as shared_start
            elif os.environ.get('EDIT_SAVE_PART') == 'waveform-full':
                from .waveform_full_audit import start as shared_start
            elif os.environ.get('EDIT_SAVE_PART') == 'waveform':
                from .waveform_stability_audit import start as shared_start
            else:
                from .edit_save_audit import start as shared_start
            shared_start(window, output)
            return
        result = dict(passed=False, checks={}, phase='passive-cli-project-startup', startup=record,
                      error='Normal CLI project startup failed or exceeded the bounded wait')

        def receipt():
            (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

        def shutdown():
            result['gui_shutdown'] = True
            receipt()

        result['gui_shutdown'] = False
        QApplication.instance().aboutToQuit.connect(shutdown)
        receipt()
        window.close()
    timer.timeout.connect(observe)
    timer.start()
    QTimer.singleShot(0, observe)
