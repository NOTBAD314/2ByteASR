"""Reusable file-backed pixels for the external mpv process.

The caller retains the slot until mpv acknowledges reading it. Mapped writes
avoid opening/truncating/scanning a new raw file on every animation frame.
"""
import mmap


class OverlayBuffer:
    def __init__(self, path, capacity):
        self.path = path
        self.capacity = (capacity + 65535) // 65536 * 65536
        self.file = path.open('w+b')
        self.file.truncate(self.capacity)
        self.mapping = mmap.mmap(self.file.fileno(), self.capacity, access=mmap.ACCESS_WRITE)

    def write(self, pixels):
        self.mapping[:len(pixels)] = pixels

    def close(self):
        self.mapping.close()
        self.file.close()
