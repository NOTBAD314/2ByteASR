"""Process-isolated libavcodec transport, driven only by PlaybackClock demand.

One replaceable command and one completed frame per follower. Pipe I/O and
pixel ownership transfer happen off the GUI. Rate changes keep the codec and
decode-ahead queue; only explicit discontinuities seek.
"""
from __future__ import annotations
import json
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from .processes import popen_hidden_subprocess


@dataclass(frozen=True)
class PipeFrame:
    epoch: int
    generation: int
    path: str
    requested_ms: int
    pts_ms: int
    width: int
    height: int
    pixels: memoryview
    raw_pts: int | None = None
    raw_dts: int | None = None
    time_base: str = ''
    decoded_at: float = 0.
    received_at: float = 0.
    codec_decoded_at: float = 0.


def _read_exact(stream, length):
    payload = bytearray(length)
    view = memoryview(payload)
    offset = 0
    while offset < length:
        count = stream.readinto(view[offset:])
        if not count: raise EOFError(f'decoder pipe ended at {offset}/{length}')
        offset += count
    return payload


class VideoDecodePipe:
    def __init__(self, ffmpeg: Path | None = None, *, max_size=(1920, 1080), sample_fps=None):
        # Compatibility constructor; the child now carries FFmpeg via PyAV.
        self.max_size = max_size
        self._condition = threading.Condition()
        self._epoch = 0
        self._version = 0
        self._request = None
        self._frame = None
        self.on_frame = None
        self._process = None
        self._closed = False
        self._last_pts = -1
        self._failures = 0
        self._progress_at = time.monotonic()
        self._requests = deque(maxlen=128)
        self._stderr = deque(maxlen=48)
        self._stats = dict(backend='libavcodec-process', starts=0, decoded=0,
            replaced=0, skipped=0, failures=0, error='', eof=False, state='IDLE')
        self._thread = threading.Thread(target=self._run, name='studio-video-pipe', daemon=True)
        self._thread.start()

    def request(self, path, source_ms, generation, paused, rate):
        with self._condition:
            old = self._request
            discontinuity = (old is None or path != old['path'] or generation != old['generation']
                or (paused and old['paused'] and abs(source_ms-old['source_ms']) > 50))
            if discontinuity:
                self._epoch += 1
                self._frame = None
                self._failures = 0
                self._stats.update(error='', eof=False)
            self._requests.append(dict(at=time.perf_counter(), source_ms=source_ms,
                generation=generation, epoch=self._epoch, paused=paused, rate=rate,
                restart=discontinuity))
            self._request = dict(epoch=self._epoch, path=path, source_ms=max(0, source_ms),
                generation=generation, paused=bool(paused), rate=rate, max_size=self.max_size,
                clock_observed_at=time.perf_counter())
            self._version += 1
            self._condition.notify_all()
            return self._epoch

    def cancel(self):
        with self._condition:
            self._epoch += 1
            self._request = None
            self._frame = None
            self._version += 1
            self._condition.notify_all()

    def take_frame(self):
        with self._condition:
            frame, self._frame = self._frame, None
            return frame

    def snapshot(self):
        with self._condition:
            process = self._process
            return {**self._stats, 'pid':process.pid if process and process.poll() is None else None,
                'source_path':self._request.get('path','') if self._request else '',
                'epoch':self._epoch, 'pts_ms':self._last_pts, 'mailbox_frames':int(self._frame is not None),
                'recent_requests':list(self._requests), 'stderr':list(self._stderr),
                'thread_alive':self._thread.is_alive(),
                'heartbeat_age_ms':round((time.monotonic()-self._progress_at)*1000, 2)}

    def watchdog(self):
        with self._condition:
            # A presentation stall alone is not grounds to kill a live worker.
            if (self._process is not None and self._request is not None
                    and time.monotonic()-self._progress_at > 5):
                self._stats['error'] = 'decoder heartbeat timeout'
                self._kill_locked()

    def _kill_locked(self):
        process = self._process
        if process is not None and process.poll() is None:
            try: process.kill()
            except OSError: pass

    def close(self, timeout=1.):
        with self._condition:
            self._closed = True
            self._frame = self._request = None
            self._kill_locked()
            self._condition.notify_all()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                if self._closed: break
                if self._request is None or self._failures >= 3:
                    self._condition.wait(.05)
                    continue
            process = None
            stopped = threading.Event()
            try:
                command = ([sys.executable, '--studio-video-worker'] if getattr(sys, 'frozen', False)
                           else [sys.executable, '-m', 'twobyteasr.video_decode_worker'])
                process = popen_hidden_subprocess(command, purpose='Studio follower video decoder',
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                with self._condition:
                    self._process = process
                    self._progress_at = time.monotonic()
                    self._stats.update(starts=self._stats['starts']+1, state='PREPARING')
                    if self._closed: self._kill_locked()

                def write_commands(child=process, stop=stopped):
                    version = -1
                    try:
                        while not stop.is_set():
                            with self._condition:
                                self._condition.wait_for(lambda: self._version != version or self._closed or stop.is_set(), .1)
                                if self._closed or stop.is_set(): break
                                if version == self._version: continue
                                version = self._version
                                value = self._request or dict(cancel=True, epoch=self._epoch)
                            child.stdin.write((json.dumps(value)+'\n').encode('utf8'))
                            child.stdin.flush()
                    except (OSError, BrokenPipeError): pass

                def read_errors(child=process):
                    try:
                        for line in child.stderr:
                            self._stderr.append(line.decode('utf8', errors='replace').strip())
                    except (OSError, ValueError): pass

                writer = threading.Thread(target=write_commands, daemon=True, name='video-command-slot')
                writer.start()
                errors = threading.Thread(target=read_errors, daemon=True, name='video-stderr')
                errors.start()
                while not self._closed:
                    length = struct.unpack('!I', _read_exact(process.stdout, 4))[0]
                    if length > 65536: raise ValueError('invalid video header length')
                    header = json.loads(_read_exact(process.stdout, length))
                    size = int(header.get('pixel_bytes', 0))
                    if not 0 <= size <= 64*1024*1024: raise ValueError('invalid video frame length')
                    started = time.perf_counter()
                    pixels = memoryview(_read_exact(process.stdout,size)).toreadonly() if size else memoryview(b'')
                    received = time.perf_counter()
                    with self._condition:
                        self._progress_at = time.monotonic()
                        if header['epoch'] != self._epoch: continue
                        self._stats.update(header.get('stats', {}))
                        self._stats['read_ms'] = (received-started)*1000
                        if header.get('heartbeat'): continue
                        if self._request is None or self._closed: continue
                        self._last_pts = header['pts_ms']
                        if self._frame is not None: self._stats['replaced'] += 1
                        self._frame = PipeFrame(header['epoch'], header['generation'], header['path'],
                            header['requested_ms'], header['pts_ms'], header['width'], header['height'], pixels,
                            header['raw_pts'], header['raw_dts'], header['time_base'], header['decoded_at'], received,header.get('codec_decoded_at',0.))
                        frame=self._frame
                    callback=self.on_frame
                    if callback is not None:
                        try:callback(frame)
                        except Exception:pass
            except (EOFError, OSError, ValueError, KeyError) as exc:
                with self._condition:
                    if not self._closed:
                        self._failures += 1
                        self._stats.update(failures=self._stats['failures']+1, error=str(exc), state='FAILED')
                        self._condition.wait(.1*self._failures)
            finally:
                stopped.set()
                with self._condition:
                    self._condition.notify_all()
                    self._kill_locked()
                if process is not None:
                    process.wait(timeout=1.)
                    for stream in (process.stdout, process.stderr, process.stdin):
                        try: stream.close()
                        except OSError: pass
                with self._condition: self._process = None
        self._stats['state'] = 'RELEASED'
