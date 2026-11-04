"""Bounded source-waveform worker. Qt receives arrays, never worker QPixmaps.

Uses Studio's shared FFmpeg/process and media identity services. Only the
visible source window is decoded at higher zoom; memory is bounded to 4096
peak pairs per window. Replaced requests terminate the owned decoder.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..media.media_service import GLOBAL_MEDIA_SERVICE
from ..projects.studio_project import studio_data_root
from ..system.processes import popen_hidden_subprocess


class SourceWaveCache(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = studio_data_root() / 'source-wave-v1'
        self.memory = OrderedDict()
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.closed = False
        self.active_key = ''
        self.cancel = threading.Event()
        self.process = None
        self.worker = threading.Thread(target=self._work, name='source-waveform', daemon=True)
        self.worker.start()

    @staticmethod
    def key(source, stream, start, end):
        path = Path(source)
        try:
            stat = path.stat()
            identity = f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{stream}|{start}|{end}'
        except OSError:
            identity = str(path)
        return hashlib.sha256(identity.encode()).hexdigest()

    def request(self, source, stream, start, end, *, priority=False):
        key = self.key(source, stream, start, end)
        if key in self.memory:
            self.memory.move_to_end(key)
            return key, self.memory[key]
        with self.condition:
            if self.closed:
                return key, None
            if priority and self.active_key and self.active_key != key:
                self._cancel_active()
            if key != self.active_key or self.cancel.is_set():
                self.pending[key] = (source, int(stream), int(start), int(end))
                if priority:
                    self.pending.move_to_end(key, last=False)
                while len(self.pending) > 24:
                    self.pending.popitem()
                self.condition.notify_all()
        return key, None

    def _cancel_active(self):
        self.cancel.set()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    def reset(self):
        with self.condition:
            self.pending.clear()
            self._cancel_active()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self._cancel_active()
            self.condition.notify_all()

    def _work(self):
        while True:
            with self.condition:
                while not self.pending and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                key, job = self.pending.popitem(last=False)
                self.active_key = key
                self.cancel = threading.Event()
                cancel = self.cancel
            try:
                target = self.root / (key + '.npy')
                if target.is_file():
                    peaks = np.load(target, allow_pickle=False)
                else:
                    from ..system.resource_governor import GLOBAL_RESOURCE_GOVERNOR, ResourceKind
                    with GLOBAL_RESOURCE_GOVERNOR.lease(ResourceKind.WAVEFORM, cancelled=cancel.is_set) as allowed:
                        if not allowed or cancel.is_set():
                            continue
                        peaks = self._decode(*job, cancel)
                    if cancel.is_set():
                        continue
                    self.root.mkdir(parents=True, exist_ok=True)
                    np.save(target, peaks, allow_pickle=False)
                    # Dedicated generated cache only, never a user media path.
                    entries = sorted(self.root.glob('*.npy'), key=lambda p: p.stat().st_mtime, reverse=True)
                    for stale in entries[1024:]:
                        stale.unlink(missing_ok=True)
                if not cancel.is_set():
                    self.memory[key] = peaks
                    while len(self.memory) > 64:
                        self.memory.popitem(last=False)
                    self.ready.emit(key, peaks)
            except (OSError, ValueError, RuntimeError) as exc:
                if not cancel.is_set():
                    try:
                        self.ready.emit(key, {'error': str(exc)})
                    except RuntimeError:
                        return
            finally:
                with self.condition:
                    self.active_key = ''
                    self.process = None

    def _decode(self, source, stream, start, end, cancel):
        rate = 8000
        bucket = max(1, math.ceil((end - start) * rate / 1000 / 4096))
        command = [str(GLOBAL_MEDIA_SERVICE.ffmpeg_path), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-ss', f'{start/1000:.6f}', '-i', str(source), '-t', f'{(end-start)/1000:.6f}',
            '-map', f'0:a:{stream}', '-vn', '-ac', '1', '-ar', str(rate), '-threads', '1', '-f', 'f32le', '-']
        process = popen_hidden_subprocess(command, purpose='source waveform', stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        with self.condition:
            self.process = process
            if cancel.is_set():
                process.terminate()
        pairs, carry = [], np.empty(0, dtype=np.float32)
        try:
            while not cancel.is_set():
                data = process.stdout.read(65536 * 4)
                if not data:
                    break
                samples = np.concatenate((carry, np.frombuffer(data[:len(data)//4*4], dtype='<f4')))
                count = len(samples) // bucket
                if count:
                    chunks = samples[:count*bucket].reshape(count, bucket)
                    pairs.extend(zip(chunks.min(axis=1), chunks.max(axis=1)))
                carry = samples[count*bucket:].copy()
            if carry.size:
                pairs.append((carry.min(), carry.max()))
            if not cancel.is_set() and process.wait(timeout=5) != 0:
                raise RuntimeError('音频波形解码失败；仍可使用播放器试听，或重新定位素材后重试')
            return np.asarray(pairs[:4096], dtype=np.float32).reshape(-1, 2)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()


class SourceMediaResolver(QObject):
    """Latest-request worker for FLV's existing canonical content-time proxy."""
    ready = Signal(int, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.condition = threading.Condition()
        self.pending = None
        self.cancel = threading.Event()
        self.closed = False
        self.worker = None

    def request(self, token, source):
        with self.condition:
            self.cancel.set()
            self.pending = (token, source)
            if self.worker is None:
                self.worker = threading.Thread(target=self._work, name='source-media-resolve', daemon=True)
                self.worker.start()
            self.condition.notify_all()

    def reset(self):
        with self.condition:
            self.cancel.set(); self.pending = None

    def close(self):
        with self.condition:
            self.closed = True; self.cancel.set(); self.pending = None
            self.condition.notify_all()

    def _work(self):
        while True:
            with self.condition:
                while self.pending is None and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                token, source = self.pending; self.pending = None
                self.cancel = threading.Event(); cancelled = self.cancel
            try:
                from ..media.indexed_media import GLOBAL_INDEXED_MEDIA
                receipt = GLOBAL_INDEXED_MEDIA.prepare_timeline_source(source,
                    ffmpeg=GLOBAL_MEDIA_SERVICE.ffmpeg_path, cancelled=cancelled.is_set)
                if not cancelled.is_set():
                    self.ready.emit(token, source, str(receipt['path']), '')
            except Exception as exc:
                if not cancelled.is_set():
                    try:
                        self.ready.emit(token, source, '', str(exc))
                    except RuntimeError:
                        return
