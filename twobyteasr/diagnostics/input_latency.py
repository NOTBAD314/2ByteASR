"""Input dispatch to Qt paint submission; queue age is unknown for synthetic/IME events."""
from collections import deque
from functools import lru_cache
import os
import time
from PySide6.QtWidgets import QPlainTextEdit
from .editor_diagnostics import record

@lru_cache(maxsize=1)
def _windows_tick_reader():
    # Loading/resolving a DLL per keystroke can contend with native loader
    # activity. The function pointer keeps its owning DLL alive.
    import ctypes
    kernel = ctypes.WinDLL("kernel32")
    reader = kernel.GetTickCount64
    reader.restype = ctypes.c_ulonglong
    return reader

def queued_ms(event):
    stamp = getattr(event, "timestamp", lambda: 0)()
    if not stamp or os.name != "nt":
        return None
    age=((int(_windows_tick_reader()()) & 0xffffffff)-int(stamp)) & 0xffffffff
    return float(age) if age < 60_000 else None

class InputLatencyTextEdit(QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input_pending=deque(maxlen=64)
        self.input_measurements=deque(maxlen=2048)
        self._input_active=None
        self.input_sequence=0
        self.document().contentsChanged.connect(self._document_changed)

    def _begin_input(self, kind, event=None):
        self.input_sequence += 1
        # Queue age is sampled at the END of the probe, so begin the next
        # interval there too. Otherwise a delayed probe is counted twice.
        queue_age = queued_ms(event) if event else None
        item=dict(kind=kind, input_id=self.input_sequence, started=time.perf_counter(), queue_ms=queue_age,
                  update_ms=None, chars_before=self.document().characterCount())
        self._input_pending.append(item)
        self._input_active=item
        record('INPUT_RECEIVED', input_id=self.input_sequence, operation=kind,
               queue_ms=item['queue_ms'], **getattr(self, '_diagnostic_context', {}))
        return item

    def _document_changed(self):
        item=self._input_active
        if item is not None:
            item["update_ms"]=(time.perf_counter()-item["started"])*1000

    def keyPressEvent(self, event):
        self._begin_input("key",event)
        try: super().keyPressEvent(event)
        finally: self._input_active=None

    def inputMethodEvent(self, event):
        self._begin_input("ime")
        try: super().inputMethodEvent(event)
        finally: self._input_active=None

    def insertFromMimeData(self, source):
        own=self._input_active is None
        if own:self._begin_input("paste")
        try:super().insertFromMimeData(source)
        finally:
            if own:self._input_active=None

    def paintEvent(self, event):
        super().paintEvent(event)
        now=time.perf_counter()
        while self._input_pending:
            item=self._input_pending.popleft()
            paint_ms=(now-item["started"])*1000
            row=dict(operation=item["kind"], input_id=item['input_id'], queue_ms=item["queue_ms"], update_ms=item["update_ms"],
                     paint_ms=paint_ms,total_ms=paint_ms+(item["queue_ms"] or 0),
                     includes_queue=item["queue_ms"] is not None)
            self.input_measurements.append(row)
            record("INPUT_PAINT",**row, **getattr(self, '_diagnostic_context', {}))

