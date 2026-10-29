"""A native reader must keep the same pixels until its ACK, across epochs."""
import threading
import time
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_video_canvas import MpvCanvas


def test_native_pixel_slot_survives_epoch_change_until_reader_ack(tmp_path):
    app = QApplication.instance() or QApplication([])
    canvas = MpvCanvas()
    canvas._compositor_overlay_dir = tmp_path
    canvas._media_attached = True
    posted = threading.Event()

    class Reader:
        running = True

        def __init__(self):
            self.jobs = []

        def post_raw_overlay(self, overlay_id, path, **kwargs):
            self.jobs.append((Path(path), kwargs))
            posted.set()
            return True

        def post_remove_overlay(self, overlay_id):
            return True

    reader = Reader()
    canvas.controller = reader

    def publish(color):
        frame = QImage(64, 32, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(QColor(color))
        pixels = bytes(frame.constBits())
        assert canvas.publish_compositor_overlay(0, frame, QRect(0, 0, 64, 32),
            source_bounds=frame.rect(), context={'caller': 'video_compositor'})
        return pixels

    def receive(count):
        deadline = time.monotonic() + 2
        while len(reader.jobs) < count and time.monotonic() < deadline:
            posted.wait(.01)
            posted.clear()
        assert len(reader.jobs) == count
        return reader.jobs[-1]

    try:
        first = publish('red')
        path, request = receive(1)
        assert path.read_bytes()[:len(first)] == first
        canvas._video_overlay_epoch += 1
        second = publish('blue')
        # Changing epoch does not grant ownership of a still-read native slot.
        time.sleep(.06)
        assert len(reader.jobs) == 1
        assert path.read_bytes()[:len(first)] == first
        request['on_applied'](False)
        path, request = receive(2)
        assert path.read_bytes()[:len(second)] == second
        request['on_applied'](True)
        for count, color in enumerate(('green', 'yellow', 'blue'), 3):
            pixels = publish(color)
            path, request = receive(count)
            assert path.read_bytes()[:len(pixels)] == pixels
            request['on_applied'](True)
        assert len({path for path, _ in reader.jobs}) <= 2
    finally:
        canvas.detach_player_for_close()
        canvas._video_overlay_thread.join(timeout=2)
        assert not canvas._video_overlay_thread.is_alive()
        # On Windows an open mapping prevents unlink: verify real release.
        for path in tmp_path.glob('*.rgba'):
            path.unlink()
        canvas.deleteLater()
        app.processEvents()
