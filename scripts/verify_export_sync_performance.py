"""Production export of an isolated project; stage/resource evidence, no user writes."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--duration', type=float, default=12)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--encoder', default='libx264')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Output must stay in workspace tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import load_project, save_project
    from twobyteasr.export_timeline import write_export_ass
    from twobyteasr.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.video_export import capture_video_graph, prepared_video_job
    from twobyteasr.studio_edit_sequence import timeline_duration_ms
    project = load_project(args.project)
    save_project(project, out/'project.2byteproj')
    write_export_ass(project, out/'export.ass', fps=60)
    encoder = args.encoder
    settings = RenderSettings(encoder=encoder, preset='p6' if encoder.endswith('nvenc') else 'medium',
                              quality_mode='vbr' if encoder.endswith('nvenc') else 'crf',
                              quality=20, bitrate_kbps=14000, max_bitrate_kbps=20000,
                              width=2560, height=1440, fps=60, audio_codec='aac')
    job = RenderJob(project.media.path, str(out/'export.ass'), str(out/'output.mp4'), settings,
                    start_seconds=args.start, duration_seconds=args.duration or timeline_duration_ms(project)/1000,
                    video_graph=capture_video_graph(project), completion_preview_path=str(out/'cover.jpg'))
    events = []
    started = time.perf_counter()
    def event(kind, value):
        row = dict(seconds=time.perf_counter()-started, kind=kind, value=value)
        events.append(row)
        with (out/'events.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(row, ensure_ascii=False, default=str)+'\n')
    def progress(value):
        event('progress', value)
    job.preview_callback = lambda image, milliseconds, phase: event('preview', {'project_ms':milliseconds,'width':image.width(),'phase':phase})
    import psutil
    stop = threading.Event()
    def resources():
        owner = psutil.Process()
        while not stop.wait(1):
            rows = []
            for p in [owner, *owner.children(recursive=True)]:
                try:
                    rows.append(dict(pid=p.pid, name=p.name(), cpu_seconds=sum(p.cpu_times()[:2]),
                                     rss=p.memory_info().rss, io=p.io_counters()._asdict()))
                except psutil.Error:
                    pass
            event('resources', rows)
            from twobyteasr.processes import run_hidden_subprocess
            gpu = run_hidden_subprocess(['nvidia-smi','--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used','--format=csv,noheader,nounits'],
                purpose='export GPU measurement', capture_output=True, text=True, timeout=3)
            event('gpu', gpu.stdout.strip())
    monitor = threading.Thread(target=resources, daemon=True)
    monitor.start()
    try:
        ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
        if args.baseline:
            with prepared_video_job(ffmpeg, job, progress=progress) as prepared:
                run_render_job(ffmpeg, prepared, progress=progress, trace=event)
        else:
            run_render_job(ffmpeg, job, progress=progress, trace=event)
        result = dict(wall_seconds=time.perf_counter()-started, receipt=job.completion_metadata,
                      encoder=encoder, baseline=args.baseline, source_project=args.project)
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:result[k] for k in ('wall_seconds','encoder','baseline')}, ensure_ascii=False), flush=True)
    finally:
        stop.set()
        monitor.join(2)


if __name__ == '__main__':
    main()
