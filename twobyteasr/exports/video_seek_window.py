"""Bounded packet evidence before shortening a simple MP4 decode preroll."""
import json
import math
import os
from pathlib import Path


def video_seek_window(ffmpeg, job, source_path, source):
    """Retain a predecessor frame; uncertain clocks/indexes keep the old path.

    Packet PTS are display timestamps for supported MP4 H.264/HEVC. A bounded
    indexed read proves a predecessor remains after the proposed input seek.
    No full-film PTS index or persisted media contract is introduced.
    """
    source = float(source)
    fallback = max(0., source - 10.)
    if Path(source_path).suffix.lower() == '.flv':
        return 0.
    if source <= 10. or Path(source_path).suffix.lower() not in {'.mp4', '.mov'}:
        return fallback
    if job.export_context.get('video_preroll') == 'legacy':
        return fallback
    key = f'{source_path}\n{source:.9f}'
    cache = job.export_context.setdefault('_video_seek_windows', {})
    if key in cache:
        return cache[key]
    seek = max(0., source-1.)
    detail = dict(source_seconds=source, legacy_seek=fallback, selected_seek=fallback,
                  reason='bounded packet/clock evidence unavailable')
    from ..system.processes import run_hidden_subprocess
    try:
        probe = Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        result = run_hidden_subprocess([str(probe), '-v', 'error', '-select_streams', 'v:0',
            '-read_intervals', f'{seek:.9f}%{source+1.:.9f}', '-show_packets',
            '-show_entries', 'format=start_time:stream=codec_name,start_time:packet=pts_time',
            '-of', 'json', str(source_path)], purpose='bounded video seek predecessor proof',
            capture_output=True, check=True, timeout=8)
        data = json.loads(result.stdout)
        stream = data['streams'][0]
        times = [float(p['pts_time']) for p in data.get('packets', []) if 'pts_time' in p]
        origin = float(data['format']['start_time'])
        video_origin = float(stream['start_time'])
        if (stream['codec_name'] in {'h264', 'hevc'} and abs(origin) < 1e-9
                and abs(video_origin) < 1e-9 and all(math.isfinite(t) for t in times)
                and any(seek+.05 <= t <= source for t in times)
                and any(source <= t <= source+1. for t in times)):
            fallback = seek
            detail.update(selected_seek=seek, reason='indexed zero-origin video has predecessor inside one-second preroll')
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    except Exception as error:
        # Probe timeout/process failure is optional evidence, never a reason to
        # discard the established correct export path.
        import subprocess
        if not isinstance(error, subprocess.SubprocessError):
            raise
    cache[key] = fallback
    from .export_run_log import note_export
    note_export('video_seek_window', detail)
    return fallback
