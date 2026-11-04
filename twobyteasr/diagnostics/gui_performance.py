"""Opt-in GUI stall and paint profiler.

Enabled only when ``TWOBYTEASR_GUI_PROFILE=1``. It never runs in ordinary
sessions and does not touch ASR workers or subtitle data.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication


class GuiPerformanceProfiler(QObject):
    HEARTBEAT_MS = 16

    def __init__(self, app: QApplication, output_dir: Path, parent=None):
        super().__init__(parent)
        self.app = app
        self.output_dir = Path(output_dir)
        self.started_at = time.perf_counter()
        self.last_tick = self.started_at
        self.events = Counter()
        self.stalls: list[dict] = []
        self._running = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(self.HEARTBEAT_MS)
        self.timer.timeout.connect(self._heartbeat)

    def start(self):
        if self._running:
            return
        self._running = True
        self.last_tick = time.perf_counter()
        self.app.installEventFilter(self)
        self.timer.start()

    def eventFilter(self, _obj, event):
        event_type = event.type()
        if event_type == QEvent.Type.Paint:
            self.events["paint"] += 1
        elif event_type == QEvent.Type.Resize:
            self.events["resize"] += 1
        elif event_type == QEvent.Type.LayoutRequest:
            self.events["layout_request"] += 1
        return False

    def _heartbeat(self):
        now = time.perf_counter()
        delay_ms = max(0.0, (now - self.last_tick) * 1000 - self.HEARTBEAT_MS)
        self.last_tick = now
        if delay_ms < 50:
            return
        severity = "250ms" if delay_ms >= 250 else "100ms" if delay_ms >= 100 else "50ms"
        self.stalls.append(
            {
                "at_seconds": round(now - self.started_at, 3),
                "delay_ms": round(delay_ms, 3),
                "threshold": severity,
            }
        )

    def snapshot(self) -> dict:
        root = self.parent()
        timers = len(root.findChildren(QTimer)) if root is not None else 0
        return {
            "elapsed_seconds": round(time.perf_counter() - self.started_at, 3),
            "events": dict(self.events),
            "stalls": list(self.stalls),
            "objects": {
                "widgets": len(QApplication.allWidgets()),
                "timers": timers,
                "python_threads": threading.active_count(),
            },
        }

    def stop(self) -> Path | None:
        if not self._running:
            return None
        self._running = False
        self.timer.stop()
        self.app.removeEventFilter(self)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / f"gui-profile-{time.strftime('%Y%m%d-%H%M%S')}.json"
        target.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target
