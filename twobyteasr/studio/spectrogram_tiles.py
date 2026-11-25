"""Visible-window spectrogram tiles with bounded decoding and image caches."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import threading

from PySide6.QtCore import QObject, QRectF, Signal
from PySide6.QtGui import QImage

from ..system.platform_media import ffmpeg_tool
from ..system.processes import run_hidden_subprocess

_LEVELS = (8000, 32000, 128000)
_COLUMNS = 192
_ROWS = 96
_RATE = 8000
_CACHE_LIMIT = 48
_MAX_PENDING = 10


def tile_span(start, end):
    extent = end - start
    if extent <= 0:
        return None
    for level in _LEVELS:
        if extent <= level * 8:
            return level
    return None


def render_samples(pcm):
    """One short Fourier window per display column, without allocating a whole STFT."""
    import numpy as np

    data = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    if not len(data):
        return None
    bins = 384
    offsets = np.arange(bins) - bins // 2
    centers = np.linspace(0, len(data) - 1, _COLUMNS).astype(np.int64)
    locations = np.clip(centers[:, None] + offsets, 0, len(data) - 1)
    windows = data[locations] * np.hanning(bins)
    spectrum = np.abs(np.fft.rfft(windows)) / (bins / 2)
    frequencies = np.linspace(1, spectrum.shape[1] - 1, _ROWS).astype(np.int64)
    levels = np.clip((20 * np.log10(np.maximum(spectrum[:, frequencies], 1e-6)) + 68) / 62, 0, 1)
    levels = levels.T[::-1, :, None]
    dark = np.array([19, 18, 28])
    bright = np.array([214, 176, 243])
    return (dark + levels * (bright - dark)).astype(np.uint8).tobytes()


def decode_tile(path, stream, start, length):
    if not Path(path).is_file():
        return None
    exe = ffmpeg_tool()
    if not exe.is_file():
        return None
    process = run_hidden_subprocess([
        str(exe), "-nostdin", "-v", "error", "-ss", f"{start / 1000:.3f}", "-i", str(path),
        "-t", f"{length / 1000:.3f}", "-map", f"0:a:{stream}", "-ac", "1", "-ar", str(_RATE),
        "-f", "s16le", "pipe:1",
    ], purpose="spectrogram decode", capture_output=True, timeout=28)
    expected = _RATE * length * 2 // 1000
    if process.returncode or not process.stdout or len(process.stdout) > expected:
        return None
    return render_samples(process.stdout.ljust(expected, b"\0"))


class SpectrogramTiles(QObject):
    finished = Signal(object, object)
    repaint_requested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._tiles = OrderedDict()
        self._requested = set()
        self._queue = Queue(_MAX_PENDING)
        self._stop = threading.Event()
        self._thread = None
        stop = self._stop
        parent.destroyed.connect(lambda *_: stop.set())
        self.finished.connect(self._accept)

    def _accept(self, key, raw):
        self._requested.discard(key)
        image = None if raw is None else QImage(raw, _COLUMNS, _ROWS, _COLUMNS * 3, QImage.Format.Format_RGB888).copy()
        self._tiles[key] = image
        while len(self._tiles) > _CACHE_LIMIT:
            self._tiles.popitem(last=False)
        self.repaint_requested.emit()

    def _worker(self):
        while not self._stop.is_set():
            try:
                key = self._queue.get(timeout=.35)
            except Empty:
                continue
            _, path, stream, offset, span = key
            try:
                result = decode_tile(path, stream, offset, span)
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                result = None
            try:
                self.finished.emit(key, result)
            except RuntimeError:
                return

    def _request(self, key):
        if key in self._requested or len(self._requested) >= _MAX_PENDING:
            return
        try:
            self._queue.put_nowait(key)
        except Full:
            return
        self._requested.add(key)
        if self._thread is None:
            self._thread = threading.Thread(target=self._worker, daemon=True, name="visible-spectrogram")
            self._thread.start()

    def paint(self, painter, asset, stream, source_in, source_out, left, right, rect):
        span = tile_span(source_in, source_out)
        if span is None or right <= left:
            return
        first = int(source_in) // span * span
        width = (right - left) / (source_out - source_in)
        painter.save()
        painter.setOpacity(.88)
        for offset in range(first, int(source_out), span):
            key = (asset.fingerprint, asset.canonical_source, int(stream), offset, span)
            if key not in self._tiles:
                self._request(key)
                continue
            image = self._tiles[key]
            self._tiles.move_to_end(key)
            if image is None:
                continue
            a, b = max(source_in, offset), min(source_out, offset + span)
            target = QRectF(left + width * (a - source_in), rect.top(), width * (b - a), rect.height())
            sample = QRectF(_COLUMNS * (a - offset) / span, 0, _COLUMNS * (b - a) / span, _ROWS)
            painter.drawImage(target, image, sample)
        painter.restore()
