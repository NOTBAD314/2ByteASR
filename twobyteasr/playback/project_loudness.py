"""Read-only BS.1770 metering of the frozen export bus before master gain."""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import threading
import time

MIN_GAIN_DB, MAX_GAIN_DB = -60., 24.
ALGORITHM = 'ebur128-truepeak-export-bus-v1'


def baseline_identity(project):
    """Cheap state gate: no monitor, master gain or target in this identity."""
    from .audio_graph import audio_graph_signature
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    signature = audio_graph_signature(project)
    # Input signature is linear in clip count. Resolving all intersecting
    # mix segments belongs to the worker, never to the panel's timer.
    mix_state = (signature[1:5], signature[6:])
    media = []
    for source in sorted({asset.canonical_source for asset in project.media_pool}):
        try:
            stat = Path(source).stat(); media.append((source, stat.st_size, stat.st_mtime_ns))
        except OSError: media.append((source, 'missing'))
    from ..system.platform_media import ffmpeg_tool
    tool = ffmpeg_tool()
    try:
        stat = tool.stat(); tool_identity = (str(tool),stat.st_size,stat.st_mtime_ns)
    except OSError: tool_identity = (str(tool),'missing')
    value = (ALGORITHM, mix_state, timeline_duration_ms(project), media,
             [(a.asset_id,a.canonical_source,a.offline) for a in project.media_pool],
             {key:project.render_settings.get(key) for key in ('output_kind','container','audio_sample_rate','audio_channels')},
             tool_identity)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def project_gain_db(project):
    try:
        value = float(project.studio_state.get('project_gain_db', 0.))
        return max(MIN_GAIN_DB, min(MAX_GAIN_DB, value)) if math.isfinite(value) else 0.
    except (TypeError, ValueError):
        return 0.


def project_gain_command(project, value):
    from PySide6.QtGui import QUndoCommand
    from ..projects.studio_runtime_state import DirtyDomain, state_for
    value = float(value)
    if not math.isfinite(value) or not MIN_GAIN_DB <= value <= MAX_GAIN_DB:
        raise ValueError('工程增益超出 −60…+24 dB')

    class MasterGainCommand(QUndoCommand):
        def __init__(self):
            super().__init__('调整工程总增益')
            self.before, self.after = project_gain_db(project), value

        def apply(self, number):
            with state_for(project).transaction(project, action_id=self.text(),
                    dirty=DirtyDomain.AUDIO_GAIN | DirtyDomain.AUTOSAVE, snapshot_cues=False):
                project.studio_state['project_gain_db'] = number

        def redo(self): self.apply(self.after)
        def undo(self): self.apply(self.before)

    return MasterGainCommand()


def match_gain(integrated, true_peak, target=-14., ceiling=-1.):
    values = (integrated, true_peak, target, ceiling)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError('无有效综合响度或真峰值')
    wanted, safe = target-integrated, ceiling-true_peak
    if safe < MIN_GAIN_DB:
        return dict(available=False, reason='范围不足，−60 dB 仍不能保证真峰值安全')
    gain = max(MIN_GAIN_DB, min(MAX_GAIN_DB, wanted, safe))
    return dict(available=True, gain_db=gain, integrated=integrated+gain,
                true_peak=true_peak+gain, delta=target-integrated-gain,
                peak_limited=safe < wanted, range_limited=wanted < MIN_GAIN_DB or wanted > MAX_GAIN_DB)


def freeze_baseline(project, ffmpeg):
    from .audio_graph import capture_audio_graph
    from ..exports.audio_delivery import mix_format
    from ..exports.studio_render import RenderSettings
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    missing = {asset.asset_id for asset in project.media_pool if asset.offline}
    if any(clip.asset_id in missing and clip.enabled for track in (*project.video_tracks,*project.audio_tracks)
           if track.enabled and not track.muted for clip in track.clips):
        raise ValueError('工程存在失联音频素材，请重新链接后分析')
    graph = capture_audio_graph(project)
    layers = [{**row, 'project_gain_db': 0.} for row in graph['segments']]
    if not layers:
        raise ValueError('无可听音轨：请检查音轨、静音与有效剪辑')
    identities = []
    for source in sorted({row['source_path'] for row in layers}):
        path = Path(source).resolve()
        stat = path.stat()  # Missing media must never turn into a 0 LUFS result.
        identities.append((str(path), stat.st_size, stat.st_mtime_ns))
    duration = timeline_duration_ms(project)/1000.
    if duration < .4:
        raise ValueError('工程短于400毫秒，无法可靠测量综合响度')
    from dataclasses import fields
    known = {field.name for field in fields(RenderSettings)}
    settings = RenderSettings(**{key:value for key,value in project.render_settings.items() if key in known})
    if settings.output_kind != 'audio':
        # Video compiler's output bus is 48 kHz stereo. Audio-only jobs keep
        # the explicit output layout, or the source layout when set to auto.
        settings.audio_sample_rate, settings.audio_channels = 48000, 2
    rate, channels = mix_format(ffmpeg, layers, settings)
    data = dict(algorithm=ALGORITHM, layers=layers, duration=duration,
                sample_rate=rate, channels=channels, media=identities)
    key = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return key, data


def analyze_baseline(ffmpeg, baseline, *, cancelled=None, progress=None):
    from types import SimpleNamespace
    from ..exports.audio_export import compile_audio_mix
    from ..system.processes import popen_hidden_subprocess
    duration = baseline['duration']
    job = SimpleNamespace(start_seconds=0., duration_seconds=duration, video_graph=None)
    inputs, filters, label = compile_audio_mix(ffmpeg, job, baseline['layers'], input_offset=0,
        sample_rate=baseline['sample_rate'], channels=baseline['channels'], audio_only=True, audio_verified=True)
    if not label:
        raise ValueError('工程没有可测音频')
    # Explicitly use the same output channel conversion as audio export BEFORE metering.
    filters.append(f'{label}aformat=sample_rates={baseline["sample_rate"]}:channel_layouts={baseline["channels"]}c,'
                   'ebur128=peak=true:framelog=verbose[meter]')
    command = [str(ffmpeg), '-hide_banner', '-nostdin', '-xerror', '-loglevel', 'info',
        '-stats_period', '0.2', *inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(filters),
        '-map', '[meter]', '-vn', '-sn', '-dn', '-progress', 'pipe:1', '-f', 'null', '-']
    if cancelled and cancelled():
        raise InterruptedError('已取消响度分析')
    process = popen_hidden_subprocess(command, purpose='project BS.1770 loudness analysis',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8', errors='replace')
    tail = deque(maxlen=100)
    clock = [0.]
    def read_errors():
        for line in process.stderr: tail.append(line)
    def read_progress():
        for line in process.stdout:
            key, _, value = line.strip().partition('=')
            if key == 'out_time_us':
                try: clock[0] = max(clock[0], float(value)/1e6)
                except ValueError: pass
    readers = [threading.Thread(target=fn, daemon=True) for fn in (read_errors, read_progress)]
    for reader in readers: reader.start()
    started = time.monotonic()
    try:
        while process.poll() is None:
            if cancelled and cancelled(): raise InterruptedError('已取消响度分析')
            if progress: progress(min(.999, clock[0]/duration))
            time.sleep(.05)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        for reader in readers: reader.join(timeout=3)
        process.stdout.close(); process.stderr.close()
    log = ''.join(tail)
    if process.returncode:
        raise ValueError('响度分析解码失败：'+log[-800:])
    summary = log.rsplit('Summary:', 1)[-1]
    loud = re.search(r'\bI:\s*([-+\w.]+)\s*LUFS', summary)
    peak = re.search(r'True peak:\s*Peak:\s*([-+\w.]+)\s*dBFS', summary)
    gate = re.search(r'Threshold:\s*([-+\w.]+)\s*LUFS', summary)
    if not loud or not peak: raise ValueError('随包FFmpeg未返回综合响度/真峰值，请检查ebur128能力')
    integrated, true_peak = float(loud[1]), float(peak[1])
    # ebur128 returns its -70 floor for a completely gated/silent signal.
    if not all(math.isfinite(v) for v in (integrated, true_peak)) or integrated <= -70 or (gate and float(gate[1]) <= -70):
        raise ValueError('全静音、极低电平或无有效门控响度，不能自动匹配')
    if progress: progress(1.)
    return dict(integrated=integrated, true_peak=true_peak, duration=duration,
                elapsed=time.monotonic()-started, sample_rate=baseline['sample_rate'],
                channels=baseline['channels'], algorithm=ALGORITHM)
