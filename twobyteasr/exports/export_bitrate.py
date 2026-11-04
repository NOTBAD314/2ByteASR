"""Streaming packet measurements; container/audio rates never stand in for video."""
from __future__ import annotations

from fractions import Fraction
import math
import os
from pathlib import Path
import subprocess
import threading
import time


def _number(value, positive=False):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and (not positive or result > 0) else None
    except (TypeError, ValueError, OverflowError):
        return None


class PacketMeasurement:
    """Constant-memory presentation extent, independent of packet arrival/B order."""
    def __init__(self):
        self.bytes = self.count = self.missing_pts = 0
        self.first = self.last = self.last_duration = None
        self.end = None

    def add(self, packet):
        size = _number(packet.get('size'), positive=True)
        if size is None or not size.is_integer() or size > 2**63 - 1:
            return
        self.bytes += int(size)
        self.count += 1
        pts = _number(packet.get('pts_time'))
        duration = _number(packet.get('duration_time'), positive=True)
        if pts is None:
            self.missing_pts += 1
            return
        self.first = pts if self.first is None else min(self.first, pts)
        if self.last is None or pts > self.last:
            self.last, self.last_duration = pts, duration
        elif pts == self.last and duration:
            self.last_duration = max(self.last_duration or 0, duration)
        if duration:
            endpoint = _number(pts + duration)
            if endpoint is not None:
                self.end = max(self.end if self.end is not None else pts, endpoint)

    def result(self, stream):
        reported_duration = _number(stream.get('duration'), positive=True)
        reported_rate = _number(stream.get('bit_rate'), positive=True)
        fps = None
        try:
            fps = _number(Fraction(stream.get('avg_frame_rate') or '0'), positive=True)
        except (ValueError, ZeroDivisionError, TypeError):
            pass
        duration = None
        source, reason = 'unavailable', 'missing presentation timestamps or packet duration'
        if self.count and not self.missing_pts and self.last is not None:
            final_duration = self.last_duration
            if final_duration is None and fps and reported_duration:
                frames = _number(stream.get('nb_frames'), positive=True)
                # Infer only the last frame interval when count, extent and stream clock agree.
                candidate = self.last - self.first + 1 / fps
                if (frames == self.count and abs(candidate - reported_duration) <= 2 / fps
                        and abs((self.last - self.first) - (self.count - 1) / fps) <= 1 / fps):
                    final_duration = 1 / fps
                    source = 'packet_pts+verified_final_frame_interval'
            if final_duration:
                end = max(self.end if self.end is not None else self.last, self.last + final_duration)
                candidate = _number(end - self.first, positive=True)
                tolerance = max(.05, 2 / fps) if fps else .05
                if candidate is not None and (reported_duration is None or abs(candidate - reported_duration) <= tolerance):
                    duration = candidate
                    source = source if source != 'unavailable' else 'packet_presentation_extent'
                    reason = ''
                else:
                    reason = 'packet presentation duration disagrees with stream duration'
        return dict(packet_bytes=self.bytes, packet_count=self.count,
            duration_seconds=duration, duration_source=source, reliable=duration is not None,
            average_bitrate_bps=self.bytes * 8 / duration if duration else None,
            metadata_bitrate_bps=reported_rate, metadata_duration_seconds=reported_duration,
            packet_start_seconds=self.first, packet_last_pts_seconds=self.last,
            missing_pts=self.missing_pts, reason=reason)


def measure_packets(ffmpeg, path, stream, *, selector='v:0', cancelled=None):
    return _measure_packet_streams(ffmpeg,path,{0:stream},selector=selector,cancelled=cancelled)[0]


def _measure_packet_streams(ffmpeg,path,streams,*,selector=None,cancelled=None):
    from ..system.processes import popen_hidden_subprocess, stop_process_tree
    command = [str(Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
        '-v', 'error', *(['-select_streams',selector] if selector else []), '-show_packets', '-show_entries',
        'packet=stream_index,pts_time,dts_time,duration_time,size', '-of', 'compact=p=0:nk=0', str(path)]
    process = popen_hidden_subprocess(command, purpose=f'export {selector} packet bitrate measurement',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    results = {index:PacketMeasurement() for index in streams}
    errors = []
    stopped = threading.Event()
    state = {'cancelled': False, 'timeout': False}
    def drain():
        for line in process.stderr:
            errors.append(line)
            del errors[:-20]
    def watch():
        deadline = time.monotonic() + max(30, max((_number(s.get('duration'), positive=True) or 0 for s in streams.values()),default=0) * 2)
        while not stopped.wait(.05):
            if cancelled and cancelled():
                state['cancelled'] = True
                stop_process_tree(process)
                return
            if time.monotonic() > deadline:
                state['timeout'] = True
                stop_process_tree(process)
                return
    reader = threading.Thread(target=drain, daemon=True, name='export-packet-stderr')
    watcher = threading.Thread(target=watch, daemon=True, name='export-packet-cancel')
    reader.start(); watcher.start()
    try:
        for line in process.stdout:
            packet = dict(part.split('=', 1) for part in line.strip().split('|') if '=' in part)
            index=0 if selector else int(packet.get('stream_index',-1))
            if index in results:results[index].add(packet)
        code = process.wait()
        reader.join(timeout=2)
        if state['cancelled'] or (cancelled and cancelled()):
            raise InterruptedError('export packet measurement cancelled')
        if state['timeout']:
            raise RuntimeError('export packet measurement timed out')
        if code:
            raise RuntimeError('export packet measurement failed: ' + ''.join(errors)[-1000:])
        return {index:result.result(streams[index]) for index,result in results.items()}
    finally:
        stopped.set()
        if process.poll() is None:
            stop_process_tree(process)
        watcher.join(timeout=1)


def export_bitrate_measurements(ffmpeg, path, metadata, *, cancelled=None):
    """Called in the export worker after decode validation; unknown is explicit."""
    result = {}
    audio = []
    video_index = audio_index = 0
    streams={int(s.get('index',i)):s for i,s in enumerate(metadata.get('streams',[]))
             if s.get('codec_type') in {'video','audio'}}
    try:
        scanned=_measure_packet_streams(ffmpeg,path,streams,cancelled=cancelled)
        scan_error=None
    except InterruptedError:raise
    except Exception as exc:
        scanned={};scan_error=exc
    for index,stream in streams.items():
        kind = stream.get('codec_type')
        if kind not in {'video', 'audio'}:
            continue
        if kind == 'video' and video_index:
            continue  # The delivered primary video stream is v:0.
        selector = f'v:{video_index}' if kind == 'video' else f'a:{audio_index}'
        try:
            if scan_error is not None:raise scan_error
            measurement = scanned[index]
        except InterruptedError:
            raise
        except Exception as exc:
            measurement = dict(reliable=False, average_bitrate_bps=None, duration_seconds=None,
                duration_source='unavailable', metadata_bitrate_bps=_number(stream.get('bit_rate'), positive=True),
                reason=f'packet measurement unavailable: {type(exc).__name__}')
        measurement['stream_index'] = stream.get('index')
        if kind == 'video':
            result['video_bitrate'] = measurement
            video_index += 1
        else:
            audio.append(measurement)
            audio_index += 1
    result['audio_bitrate'] = audio
    return result


def target_comparison(job, metadata):
    settings = getattr(job, 'settings', None)
    is_target = settings is not None and settings.quality_mode in {'target', 'vbr', 'limited', 'cbr'}
    requested = settings.bitrate_kbps * 1000 if is_target else None
    measurement = metadata.get('video_bitrate') or {}
    actual = _number(measurement.get('average_bitrate_bps'), positive=True) if measurement.get('reliable') else None
    error = abs(actual - requested) / requested if actual is not None and requested else None
    return dict(requested_video_bitrate_bps=requested, bitrate_target_relative_error=error,
        bitrate_target_met=(error <= .10 if error is not None else None))
