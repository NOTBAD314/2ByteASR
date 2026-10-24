"""Bounded, read-only observation of video progress; never an encode timeout."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time


class EncodingObserver:
    def __init__(self, path, pid, *, fps=0., duration=0., context=None, interval=.5, encoder=''):
        self.path = Path(path)
        self.pid, self.fps, self.duration = pid, float(fps or 0), float(duration or 0)
        self.context, self.interval = context or {}, interval
        self.encoder = encoder
        self.started = time.monotonic()
        self.latest = {}
        self._pending = {}
        self._lock = threading.Lock()
        self._done = threading.Event()
        self.samples, self.stalls = 0, []
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name='export-encoding-observer')
        self.thread.start()

    def feed(self, value):
        # Called by pipe drainers: no file I/O, GUI callback or resource probe.
        if isinstance(value, bytes): value = value.decode('utf-8', errors='replace')
        for line in str(value).splitlines():
            key, sep, val = line.strip().partition('=')
            if sep and key in {'frame', 'fps', 'out_time_us', 'speed', 'total_size', 'progress', 'dup_frames', 'drop_frames'}:
                with self._lock:
                    self._pending[key] = val
                    if key == 'progress':
                        self.latest = dict(self._pending, received_monotonic=time.monotonic())
                        self._pending.clear()

    def close(self):
        self._done.set()
        self.thread.join(timeout=2)

    def _location(self, seconds):
        project = self.context.get('project') or {}
        ms = 1000 * (seconds + float(self.context.get('start_seconds') or 0))
        return dict(project_ms=round(ms, 3),
            clips=[c['id'] for t in project.get('video_tracks', []) for c in t.get('clips', [])
                   if c.get('timeline_in_ms', 0) <= ms < c.get('timeline_out_ms', 0)],
            cues=[c['id'] for c in project.get('cues', [])
                  if c.get('start_ms', 0) <= ms < c.get('end_ms', 0)])

    def _run(self):
        try:
            import psutil
            gpu = _gpu_sampler(self.encoder)
            process = psutil.Process(self.pid)
            parent = psutil.Process(os.getpid())
            process.cpu_percent(None); parent.cpu_percent(None)
            last_frames, last_change, previous_time, previous_frames = 0, self.started, self.started, 0
            open_stall = None
            history = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('w', encoding='utf-8') as stream:
                while True:
                    done = self._done.wait(self.interval)
                    now = time.monotonic()
                    with self._lock: progress = dict(self.latest)
                    frames = int(progress.get('frame') or 0)
                    video_seconds = frames / self.fps if self.fps > 0 else None
                    history.append((now, frames))
                    while len(history) > 2 and history[1][0] < now-2: history.pop(0)
                    window_time, window_frames = history[0]
                    location = self._location(video_seconds or 0)
                    if frames != last_frames:
                        if open_stall is not None:
                            open_stall.update(end_elapsed=now-self.started, duration=now-last_change,
                                              resumed_frame=frames)
                            self.stalls.append(open_stall); open_stall = None
                        last_frames, last_change = frames, now
                    idle = now-last_change
                    if idle >= 5 and open_stall is None and progress.get('progress') != 'end':
                        open_stall = dict(start_elapsed=last_change-self.started, start_frame=frames, **location)
                    resources = {}
                    for name, proc in [('encoder', process), ('worker', parent)]:
                        try:
                            with proc.oneshot():
                                io = proc.io_counters(); mem = proc.memory_info()
                                resources[name] = dict(pid=proc.pid, cpu_percent=proc.cpu_percent(None),
                                    rss=mem.rss, read_bytes=io.read_bytes, write_bytes=io.write_bytes,
                                    threads=proc.num_threads(), status=proc.status())
                        except psutil.Error: resources[name] = dict(pid=proc.pid, status='exited')
                    stage = 'encode'
                    if progress.get('progress') == 'end' or (video_seconds is not None and self.duration and video_seconds >= self.duration):
                        stage = 'mux'
                    row = dict(elapsed=now-self.started, monotonic=now, stage=stage, frame=frames,
                        video_seconds=video_seconds, ffmpeg_out_time_us=progress.get('out_time_us'),
                        window_seconds=now-previous_time,
                        window_fps=(frames-previous_frames)/max(.001, now-previous_time),
                        window_speed=((frames-previous_frames)/self.fps/max(.001, now-previous_time) if self.fps else None),
                        rolling_2s_speed=((frames-window_frames)/self.fps/max(.001, now-window_time) if self.fps else None),
                        no_video_progress_seconds=idle, suspect_stall=bool(open_stall),
                        progress_age_seconds=now-progress.get('received_monotonic', self.started),
                        supply=self.context.get('supply', 'ffmpeg owns decode/filter/encode; no application frame queue'),
                        resources=resources, gpu=gpu(), **location)
                    stream.write(json.dumps(row, ensure_ascii=False)+'\n');stream.flush()
                    self.samples += 1;previous_frames, previous_time = frames, now
                    if done:
                        if open_stall is not None:
                            open_stall.update(end_elapsed=now-self.started, duration=now-last_change, ended_without_resume=True)
                            self.stalls.append(open_stall)
                        break
            self.path.with_suffix('.summary.json').write_text(json.dumps(dict(pid=self.pid, fps=self.fps,
                elapsed=time.monotonic()-self.started, samples=self.samples, stalls=self.stalls,
                max_stall_seconds=max([s['duration'] for s in self.stalls] or [0])), ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'


def _gpu_sampler(encoder):
    if not any(encoder.endswith(s) for s in ('_nvenc', '_qsv', '_amf')):
        return lambda: {'status': 'not_applicable', 'reason': 'software encoder'}
    if not encoder.endswith('_nvenc'):
        return lambda: {'status': 'unavailable', 'reason': 'no vendor sampler for '+encoder}
    try:
        import ctypes
        from ctypes.util import find_library
        lib = ctypes.CDLL(find_library('nvml') or ('nvml.dll' if os.name == 'nt' else 'libnvidia-ml.so.1'))
        if lib.nvmlInit_v2() != 0: raise OSError('NVML initialization failed')
        handle=ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0: raise OSError('GPU unavailable')
        def sample():
            result={'status':'ok', 'scope':'device_0_aggregate'}
            for key, name in [('encoder','nvmlDeviceGetEncoderUtilization'),('decoder','nvmlDeviceGetDecoderUtilization')]:
                value, period=ctypes.c_uint(), ctypes.c_uint()
                code=getattr(lib,name)(handle,ctypes.byref(value),ctypes.byref(period))
                result[key+'_percent']=value.value if code==0 else None
            return result
        return sample
    except (OSError, AttributeError):
        return lambda: {'status': 'unavailable', 'reason': 'NVML unavailable'}
