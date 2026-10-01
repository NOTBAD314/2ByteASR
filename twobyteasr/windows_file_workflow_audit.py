"""Opt-in observations for the normal entry, under the existing isolation guard."""
import json
import os
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

def start(window, output):
    started=time.monotonic()
    timer=QTimer(window)
    timer.setInterval(100)
    last=None
    def sample():
        nonlocal last
        state={"pid":os.getpid(),"media_paths":list(window.media_paths),
               "status":window.header_status.text(),"visible":window.isVisible(),
               "minimized":window.isMinimized(),"active":window.isActiveWindow(),
               "pending":len(window._desktop_intake.requests),
               "validating":window._desktop_intake.active}
        encoded=json.dumps(state,ensure_ascii=False)
        if encoded!=last:
            (output/'state.json').write_text(encoded,encoding='utf-8')
            with (output/'observations.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({**state,"time":time.time()},ensure_ascii=False)+'\n')
            QTimer.singleShot(200, lambda: window.grab().save(str(output/'home.png')))
            last=encoded
        if (output/'stop').exists() or time.monotonic()-started>180:
            timer.stop();QApplication.instance().quit()
    timer.timeout.connect(sample)
    timer.start()
    window._file_workflow_audit=timer
    sample()
