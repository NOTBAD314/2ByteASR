"""Reusable file-backed pixels for the external mpv process.

The caller retains the slot until mpv acknowledges reading it. Mapped writes
avoid opening/truncating/scanning a new raw file on every animation frame.
"""
import mmap
from pathlib import Path


class OverlayBuffer:
    def __init__(self, path, capacity):
        self.path = Path(path)
        self.closed = False
        self.capacity = (capacity + 65535) // 65536 * 65536
        self.file = path.open('w+b')
        self.file.truncate(self.capacity)
        self.mapping = mmap.mmap(self.file.fileno(), self.capacity, access=mmap.ACCESS_WRITE)
        from .overlay_session import lease_overlay
        self._lease = lease_overlay(self.path, 'mpv_overlay_buffer')

    def write(self, pixels):
        self.mapping[:len(pixels)] = pixels

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.mapping.close()
        self.file.close()
        # Publishers call close after ACK (or after the consumer exited).
        # Closing a mapping alone used to leave every session's buffers behind.
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass  # The registered leaf remains visible/retryable in storage.
        try:
            self._lease.__exit__(None, None, None)
        except Exception:
            pass  # A stale lease is reclaimed after this process exits.
