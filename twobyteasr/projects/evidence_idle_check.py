"""After an autosave, re-read recognition evidence rows a slice at a time.

Autosave snapshots reuse an evidence row object they have seen before
(``StudioRevisionStore._frozen_evidence``, 2026-10-22): comparing all ~50 MB
of rows on every snapshot cost ~80 ms of GUI time. Editing code replaces rows
rather than changing them in place; this check, spread over idle GUI time
(~2 ms per slice), still gets a row changed in place into the next autosave.
Formal saves compare every row themselves.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer


class EvidenceIdleCheck(QObject):
    SLICE = 48
    INTERVAL_MS = 15

    def __init__(self, page) -> None:
        super().__init__(page)
        self._page = page
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)
        self._keys: list[str] = []
        self._index = 0
        self._store = None
        self.stale_found = 0

    def start(self) -> None:
        store = getattr(self._page, "_revision_store", None)
        rows = getattr(store, "_evidence_rows", None)
        if not rows:
            return
        self._store = store
        self._keys = list(rows)
        self._index = 0
        self._timer.start(self.INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._keys = []
        self._store = None

    def running(self) -> bool:
        return self._store is not None

    def _step(self) -> None:
        store = self._store
        if store is None or getattr(self._page, "_revision_store", None) is not store:
            self.stop()
            return
        chunk = self._keys[self._index:self._index + self.SLICE]
        self._index += len(chunk)
        if store.evidence_rows_changed_in_place(chunk):
            self.stale_found += 1
            self.stop()
            undo_stack = getattr(self._page, "undo_stack", None)
            if undo_stack is not None and not undo_stack.isClean():
                self._page._schedule_autosave()
            return
        if self._index < len(self._keys):
            self._timer.start(self.INTERVAL_MS)
        else:
            self.stop()
