"""Observe real still preparation and retain local, replayable failure inputs."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid


class StaticCaptionPreparation:
    def __init__(self, total, progress=None, trace=None, *, identity=None):
        self.total, self.progress, self.trace = total, progress, trace
        self.identity=dict(identity or {})
        self.completed = self.reused = self.failed = 0
        self.slowest_ms = 0.0
        self.slowest_index = None
        self.started = self.task_started = self.stage_started = time.perf_counter()
        self.index, self.cue_id, self.stage = -1, '', 'prepare'
        self.last_report = 0.0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._observer = threading.Thread(target=self._observe, name='static-caption-observer', daemon=True)

    def __enter__(self):
        self._observer.start()
        self.report(force=True)
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._observer.join(timeout=2)

    def task(self, index, cue_id):
        with self._lock:
            self.index, self.cue_id = index, cue_id
            self.task_started = time.perf_counter()
            self.step('snapshot')

    def step(self, stage):
        with self._lock:
            self.stage, self.stage_started = stage, time.perf_counter()
            self.report()

    def done(self, *, reused=False):
        with self._lock:
            elapsed = (time.perf_counter() - self.task_started) * 1000
            if elapsed > self.slowest_ms:
                self.slowest_ms, self.slowest_index = elapsed, self.index
            self.completed += 1
            self.reused += bool(reused)
            self.stage = 'completed'
            self.report(force=self.completed == self.total)

    def report(self, *, force=False):
        with self._lock:
            now = time.perf_counter()
            if not force and now - self.last_report < .25:
                return
            self.last_report = now
            data = dict(self.identity,static_task_index=self.index, static_task_number=max(0, self.index + 1),
                        static_total=self.total, static_completed=self.completed,
                        static_reused=self.reused, static_failed=self.failed,
                        static_cue_id=self.cue_id, static_step=self.stage,
                        static_task_elapsed_ms=round((now-self.task_started)*1000, 2),
                        static_step_elapsed_ms=round((now-self.stage_started)*1000, 2),
                        static_elapsed_ms=round((now-self.started)*1000, 2),
                        static_slowest_ms=round(self.slowest_ms, 2), static_slowest_index=self.slowest_index,
                        static_remaining=max(0, self.total-self.completed-self.failed))
        if self.progress:
            from .studio_render import export_progress, STAGE_ADVANCED_RENDER
            labels = dict(prepare='准备', snapshot='解析布局/字体', raster='绘制', alpha='检查像素',
                          save='保存图片', completed='已完成', failed='失败')
            self.progress(export_progress(STAGE_ADVANCED_RENDER,
                message=f'静态字幕 {data["static_task_number"]}/{self.total} · '
                        f'{labels.get(self.stage, self.stage)} · 已完成 {self.completed}，缓存复用 {self.reused}，'
                        f'失败 {self.failed} · 当前耗时 {data["static_task_elapsed_ms"]/1000:.1f}s',
                **data))
        if self.trace:
            self.trace('static_caption_preparation', data)

    def _observe(self):
        sampled = -1
        while not self._stop.wait(1):
            self.report(force=True)
            with self._lock:
                stalled = self.index >= 0 and self.stage != 'completed' and time.perf_counter()-self.task_started >= 5
                index = self.index
            if stalled and sampled != index and self.trace:
                sampled = index
                # No locals or subtitle bodies: only thread identity and frames.
                frames = sys._current_frames()
                stacks = {thread.name: ''.join(traceback.format_stack(frames[thread.ident])[-20:])
                          for thread in threading.enumerate() if thread.ident in frames}
                resources={}
                try:
                    import psutil
                    process=psutil.Process(os.getpid())
                    resources=dict(cpu_seconds=process.cpu_times().user+process.cpu_times().system,
                                   rss_bytes=process.memory_info().rss,io=process.io_counters()._asdict())
                except Exception as exc:resources={'unavailable':type(exc).__name__}
                self.trace('static_caption_wait_stacks', dict(self.identity,task_index=index, cue_id=self.cue_id,
                           step=self.stage, stacks=stacks,resources=resources))


def retain_static_failure(project, props, job, task_index, snapshot, detail, error):
    """Full bodies stay in a separate local artifact, never the ordinary log."""
    from ..projects.studio_project import studio_data_root
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from .export_run_log import current_export_log
    log=current_export_log()
    parent=log.path if log is not None else studio_data_root()/'cache/export-completion'
    folder = parent / ('caption-failure-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    indices = range(max(0, task_index-1), min(len(props['cues']), task_index+2))
    ids = {props['cues'][index]['id'] for index in indices}
    payload = project.to_dict()
    payload['cues'] = [cue for cue in payload['cues'] if cue['id'] in ids]
    # A minimal materialized project contains the exact original/translation
    # layers already selected for this export; no live-project alias survives.
    (folder/'project.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), 'utf8')
    snapshots = []
    for index in indices:
        cue = props['cues'][index]
        try:
            current = snapshot if index == task_index and snapshot else build_visual_cue_snapshot(
                project, cue['id'], width=detail['output'][0], height=detail['output'][1], fps=props['fps'])
            snapshots.append(dict(task_index=index, cue=cue, snapshot=current.to_dict()))
        except Exception as exc:
            snapshots.append(dict(task_index=index, cue=cue, snapshot_error=type(exc).__name__))
    data = dict(schema=1, renderer='render_static_graph/qt-static', task=detail,
                context=job.export_context, snapshots=snapshots,
                requested_size=[job.settings.width, job.settings.height],
                media_size=[project.media.width, project.media.height],
                exception_chain=''.join(traceback.format_exception(type(error), error, error.__traceback__)))
    font_file=(detail.get('resolved_font') or {}).get('file')
    try:
        if font_file and Path(font_file).is_file():
            data['font_file_sha256']=hashlib.sha256(Path(font_file).read_bytes()).hexdigest()
    except OSError as exc:data['font_hash_error']=type(exc).__name__
    (folder/'failure.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), 'utf8')
    if log is not None:
        log.manifest['caption_failure']=dict(detail,local_artifact=str(folder))
        log._save_manifest()
        log.note('static_caption_failure',dict(detail,local_artifact=str(folder)))
    return folder
