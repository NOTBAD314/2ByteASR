"""Reproducible production exports; isolated data, exact argv, phase and resource evidence.

Run with the existing app Python. No source project or settings are modified.
--source-root allows the same harness to measure an unmodified checkout.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--output', required=True, help='New directory within tmp')
    parser.add_argument('--settings-json', help='Exact RenderSettings JSON for matching a user export')
    parser.add_argument('--project', help='Read-only original .2byteproj')
    parser.add_argument('--media', help='Read-only media; omit with --make-fixture')
    parser.add_argument('--make-fixture', action='store_true')
    parser.add_argument('--force-raster', action='store_true', help='Synthetic fixture: opacity .99 requires the existing compositor')
    parser.add_argument('--reorder', action='store_true', help='Synthetic fixture: swap the two source halves')
    parser.add_argument('--mode', choices=['project', 'none', 'ass', 'static', 'motion'], default='project')
    parser.add_argument('--duration', type=float, default=60, help='0 = full timeline')
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--width', type=int, default=0)
    parser.add_argument('--height', type=int, default=0)
    parser.add_argument('--fps', type=float, default=0)
    parser.add_argument('--encoder', default='h264_nvenc')
    parser.add_argument('--codec', default='h264')
    parser.add_argument('--preset', default='p4')
    parser.add_argument('--quality', type=int, default=20)
    parser.add_argument('--pixel-format', default='yuv420p')
    parser.add_argument('--audio', default='aac', choices=['aac', 'copy', 'none'])
    parser.add_argument('--container', default='mp4')
    parser.add_argument('--validation', choices=['quick', 'full'], default='quick')
    parser.add_argument('--cache-profile', help='Reuse this isolated tmp profile for a warm repeat')
    parser.add_argument('--segments', type=int, choices=[1,2], default=1)
    parser.add_argument('--decode', choices=['software', 'cuda'], default='software')
    args = parser.parse_args()
    root = Path(args.source_root).resolve()
    out = Path(args.output).resolve()
    if 'tmp' not in out.parts or out.exists():
        raise ValueError('--output must be a NEW directory inside tmp')
    out.mkdir(parents=True)
    profile = Path(args.cache_profile).resolve() if args.cache_profile else out / 'profile'
    if 'tmp' not in profile.parts:
        raise ValueError('Cache profile must be inside tmp')
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(profile), QT_QPA_PLATFORM='offscreen',
                      TWOBYTEASR_EXPORT_LOG_ROOT=str(out / 'diagnostics'))
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(root / 'assets/fonts/SourceHanSansSC-Medium.otf'))
    from twobyteasr.system.processes import run_hidden_subprocess
    ffmpeg = Path(args.ffmpeg).resolve()
    ffprobe = ffmpeg.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')

    def command(argv, **kw):
        return run_hidden_subprocess([str(v) for v in argv], purpose='export performance fixture/probe',
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, **kw)

    media = Path(args.media).resolve() if args.media else out / 'fixture.mp4'
    if args.make_fixture:
        width, height, fps = args.width or 3840, args.height or 2160, args.fps or 30
        argv = [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                f'testsrc2=s={width}x{height}:r={fps}:d={args.duration or 60}',
                '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={args.duration or 60}',
                '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18', '-b:v', '0',
                '-pix_fmt', 'yuv420p', '-g', str(round(fps * 2)), '-c:a', 'aac', media]
        (out / 'fixture-command.json').write_text(json.dumps([str(v) for v in argv]), encoding='utf-8')
        command(argv, timeout=600)
    started = time.monotonic()
    lock = threading.Lock()
    events, samples = [], []

    def event(kind, value):
        row = dict(seconds=time.monotonic() - started, kind=kind, value=value)
        with lock:
            events.append(row)
            with (out / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    def timed(module, name):
        original = getattr(module, name)
        @wraps(original)
        def run(*a, **kw):
            at = time.monotonic()
            event('phase_started', dict(name=name))
            try:
                return original(*a, **kw)
            finally:
                event('phase_finished', dict(name=name, seconds=time.monotonic() - at))
        setattr(module, name, run)

    import psutil
    stopped = threading.Event()
    owner = psutil.Process()
    def monitor():
        last_gpu = 0
        while not stopped.wait(.5):
            rows = []
            for process in [owner, *owner.children(recursive=True)]:
                try:
                    rows.append(dict(pid=process.pid, name=process.name(), rss=process.memory_info().rss,
                        cpu_seconds=sum(process.cpu_times()[:2]), io=process.io_counters()._asdict()))
                except psutil.Error:
                    pass
            temporary = 0
            for base, dirs, files in os.walk(out):
                dirs[:] = [d for d in dirs if d not in {profile.name, 'diagnostics', '__pycache__'}]
                for name in files:
                    p = Path(base)/name
                    try:
                        if p.suffix.lower() in {'.mkv', '.mov', '.nut', '.raw', '.png', '.rgba'} or 'partial' in name or any(x.startswith(('.static-', '2byteasr-advanced-', '.video-composition-', '.parallel-video-')) for x in p.relative_to(out).parts):
                            temporary += p.stat().st_size
                    except OSError:pass
            row = dict(seconds=time.monotonic() - started, processes=rows, temporary_bytes=temporary,
                       system_cpu_percent=psutil.cpu_percent())
            try:row['system_disk_io'] = psutil.disk_io_counters()._asdict()
            except (OSError, AttributeError):row['system_disk_io'] = None
            if time.monotonic() - last_gpu >= 2:
                try:
                    row['gpu_device_percent'] = command(['nvidia-smi', '--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used', '--format=csv,noheader,nounits'], timeout=5).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    row['gpu_device_percent'] = 'unavailable'
                last_gpu = time.monotonic()
            samples.append(row)
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    from twobyteasr.exports import export_validation, export_bitrate, export_media, video_export
    from twobyteasr.rendering import advanced_renderer
    for module, name in [(export_validation, 'validate_output'), (export_bitrate, 'measure_packets'),
                         (export_bitrate, 'export_bitrate_measurements'), (export_media, '_build_probe'),
                         (video_export, 'compose_video'), (advanced_renderer, '_run_streaming_process'),
                         (advanced_renderer, 'compile_composition_data')]:
        timed(module, name)
    from twobyteasr.projects.studio_project import load_project, StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.timeline.studio_edit_sequence import timeline_duration_ms
    if args.project:
        project = load_project(args.project)
        media = Path(project.media.path)
    else:
        probe = json.loads(command([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', media], timeout=30).stdout)
        video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        duration = float(probe['format']['duration'])
        project = SubtitleProject(media=StudioMedia(str(media), duration_ms=round(duration * 1000),
            width=video['width'], height=video['height']),
            styles=[SubtitleStyle('g', '性能样本', font_family='Source Han Sans SC', font_size=64)],
            cues=[StudioCue(str(i), i * 2000, min(round(duration * 1000), i * 2000 + 1800),
                f'字幕导出性能样本 {i:03d}', style_id='g') for i in range(int(duration / 2))])
        project.project_id = 'perf-'+hashlib.sha256(str(media.resolve()).encode('utf8')).hexdigest()[:24]
        project.created_at = project.updated_at = '2026-11-04T00:00:00Z'
        if args.mode in {'static', 'motion'}:
            project.style_recipes['g'] = dict(name='静态渐变', engine='remotion', motion=dict(mode='none'),
                colors=dict(fill=dict(type='linear-gradient', angle=0, stops=[
                    dict(position=0, color='#FFFF8040'), dict(position=1, color='#FF40D0FF')])) )
            project.generation_metadata['translations'] = {c.id: f'Bilingual export sample {c.id}' for c in project.cues}
            project.studio_state['bilingual'] = dict(mode='bilingual', layout='ink_v1', gap_ratio=.13)
        if args.mode == 'motion':
            from copy import deepcopy
            recipe = deepcopy(project.style_recipes['g'])
            recipe['motion'] = dict(mode='fade', entry=dict(type='fade', duration=250), exit=dict(type='fade', duration=250))
            project.style_recipes['animated'] = recipe
            project.cues[len(project.cues) // 2].style_id = 'animated'
        project.validate()
    if args.reorder:
        from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
        from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
        total = project.media.duration_ms
        half = total//2
        sequence = EditSequence(source_path=str(media), source_duration_ms=total, segments=[
            VideoSegment('second', str(media), half, total, 0, total-half),
            VideoSegment('first', str(media), 0, half, total-half, total)])
        store_sequence(project, sequence)
        sync_primary_video_track_from_sequence(project, sequence)
    if args.mode == 'none':
        project.cues = []
    probe = json.loads(command([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', media], timeout=30).stdout)
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    duration = args.duration or timeline_duration_ms(project) / 1000 - args.start
    fps = args.fps or float(Fraction(video.get('avg_frame_rate') or '30'))
    graph = video_export.capture_video_graph(project)
    if args.force_raster:
        graph['video_tracks'][0]['clips'][0].setdefault('transform', {})['opacity'] = .99
    settings = RenderSettings(encoder=args.encoder, codec=args.codec, preset=args.preset, quality_mode='cq',
        quality=args.quality, width=args.width or project.media.width, height=args.height or project.media.height,
        fps=fps, audio_codec=args.audio, container=args.container, pixel_format=args.pixel_format)
    if args.settings_json:
        settings = RenderSettings(**json.loads(Path(args.settings_json).read_text('utf-8-sig')))
        settings.validate()
    fps = settings.fps or fps
    snapshot = write_export_ass(project, out / 'subtitles.ass', fps=fps)
    if not args.project:
        (out/'fixture.2byteproj').write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding='utf8')
    context = dict(validation_mode=args.validation, decode_backend=args.decode, parallel_segments=args.segments)
    job = RenderJob(str(media), str(out / 'subtitles.ass'), str(out / ('output.' + settings.container)), settings,
        start_seconds=args.start, duration_seconds=duration, video_graph=graph,
        completion_preview_path=str(out / 'cover.jpg'), export_context=context,
        export_project_data=snapshot.to_dict())
    job.completion_metadata['requested_started_monotonic'] = started
    inventory = dict(source_root=str(root), args=vars(args), source_media=probe,
        media_identity=dict(path=str(media.resolve()), size=media.stat().st_size, mtime_ns=media.stat().st_mtime_ns),
        project=dict(cues=len(project.cues), exported_cues=len(snapshot.cues),
            translations=len(project.generation_metadata.get('translations') or {}),
            video_tracks=len(graph['video_tracks']), clips=sum(len(t['clips']) for t in graph['video_tracks']),
            transitions=len(graph.get('clip_transitions', []))), settings=asdict(settings),
        source_vfr='known CFR generated fixture' if args.make_fixture else 'not fully scanned; avg/r frame rate metadata alone cannot prove CFR',
        monitor_scope='process tree sampled from source/project preparation through publication',
        python=sys.version, ffmpeg=str(ffmpeg), ffmpeg_version=command([ffmpeg, '-version'], timeout=10).stdout.splitlines()[0],
        source_version=(root / '2byteasr_version.json').read_text('utf-8'))
    if os.name == 'nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            inventory['cpu'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    try:
        inventory['gpu'] = command(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'], timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        inventory['gpu'] = 'unavailable'
    (out / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    error = None
    try:
        if advanced_renderer.project_requires_advanced(snapshot, start_ms=args.start * 1000, end_ms=(args.start + duration) * 1000):
            advanced_renderer.AdvancedRendererBackend().render(snapshot, ffmpeg, job,
                progress=lambda v: event('progress', v), trace=event)
        else:
            run_render_job(ffmpeg, job, progress=lambda v: event('progress', v), trace=event)
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        stopped.set()
        thread.join(7)
        elapsed = job.completion_metadata.get('elapsed_seconds') or time.monotonic() - started
        result = dict(wall_seconds=time.monotonic() - started, elapsed_to_publication_seconds=elapsed if not error else None,
            duration_seconds=duration, complete_speed=duration / elapsed if not error else None, complete_fps=duration * fps / elapsed if not error else None,
            receipt=job.completion_metadata, error=error,
            peak_tree_rss_bytes=max((sum(p['rss'] for p in s['processes']) for s in samples), default=0),
            peak_temporary_bytes=max((s['temporary_bytes'] for s in samples), default=0),
            resource_limits='0.5s sampled process-tree RSS/logical IO; GPU engine values are device-wide, include other apps; no physical disk busy counter',
            phases=[e for e in events if e['kind'] == 'phase_finished'])
        (out / 'resources.json').write_text(json.dumps(samples, ensure_ascii=False), encoding='utf-8')
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: result[k] for k in ['elapsed_to_publication_seconds', 'complete_speed', 'complete_fps', 'peak_tree_rss_bytes', 'peak_temporary_bytes', 'error']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
