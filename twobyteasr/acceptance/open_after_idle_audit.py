"""Real-window check: open Studio from the home page after the app has idled (2026-10-22).

User report (daily ``b9260c23``): entering 字幕工作台 often crashed. Both crashes
happened on the first Studio open of a session, 30–60 s after start, from the
home page's 「进入字幕工作台」 button; the native fault was raised while the Studio
page was being built (``MotionEffectTile.__init__``). A session that opened
Studio 6 s after start did not crash.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=open-after-idle`` (isolated data).
The event loop keeps running while the home page idles for
``TWOBYTEASR_OPEN_IDLE_S`` seconds (default 40); then the real button is clicked,
the project's readiness is awaited and the app closes. ``result.json`` records the
timings; a native crash leaves ``native-fault.txt`` in the session folder instead.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    output.mkdir(parents=True, exist_ok=True)
    idle_s = float(os.environ.get('TWOBYTEASR_OPEN_IDLE_S', '40'))
    result = dict(passed=False, idle_s=idle_s, pid=os.getpid(), events=[])
    began = time.monotonic()

    def note(name, **fields):
        result['events'].append(dict(name=name, at_s=round(time.monotonic() - began, 2), **fields))
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), 'utf8')

    def finish(passed, error=None):
        result['passed'] = bool(passed)
        if error:
            result['error'] = error
        note('finish')
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), 'utf8')
        QTimer.singleShot(500, QApplication.instance().quit)

    def open_now():
        try:
            note('click')
            button = getattr(window, 'studio_entry_open', None)
            path = os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')
            if path:
                window.open_studio_project(path, source='home_open_project')
            else:
                button.click()
            note('page_built')
            deadline = time.monotonic() + 90

            def poll():
                page = getattr(window, '_studio_page_instance', None)
                try:
                    ready = page is not None and page.project is not None and page._readiness.ready
                except Exception:  # noqa: BLE001
                    ready = False
                if ready:
                    note('ready', cues=len(page.project.cues))
                    QTimer.singleShot(4000, lambda: finish(True))
                elif time.monotonic() > deadline:
                    finish(False, 'readiness timeout')
                else:
                    QTimer.singleShot(100, poll)
            poll()
        except Exception:  # noqa: BLE001
            finish(False, traceback.format_exc())

    window.showMaximized()
    note('shown')
    QTimer.singleShot(int(idle_s * 1000), open_now)
