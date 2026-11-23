"""Bounded stderr capture for Studio audio processes."""
from __future__ import annotations

from ..providers.provider_diagnostics import redact_diagnostics


class AudioStderr:
    _EDGE_BYTES = 4096

    def __init__(self):
        self._head = b''
        self._tail = b''
        self._size = 0

    def append(self, chunk):
        room = self._EDGE_BYTES - len(self._head)
        self._size += len(chunk)
        self._head += chunk[:room]
        self._tail = (self._tail + chunk[room:])[-self._EDGE_BYTES:]

    def drain(self, stream):
        try:
            for chunk in iter(lambda: stream.read1(4096), b''):
                self.append(chunk)
        except (OSError, ValueError):
            # Closing the pipe during user cancellation is expected.
            pass

    def text(self):
        head, tail = self._head, self._tail
        omitted = self._size - len(head) - len(tail)
        gap = b'\n[stderr truncated]\n' if omitted > 0 else b''
        return redact_diagnostics((head + gap + tail).decode('utf-8', errors='replace')).strip()
