"""User-visible, bounded diagnostics over existing playback telemetry."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from collections import deque
from time import perf_counter

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                              QPlainTextEdit, QPushButton, QVBoxLayout, QFileDialog)

from ..i18n import bind_text


def performance_snapshot(page, *, compact=False) -> dict:
    canvas = getattr(page, "video", None)
    clock = getattr(canvas, "_playback_clock", None)
    scene = getattr(page, "video_compositor", None)
    layers = {str(x.get("clip_id")): x for x in getattr(scene, "_layers", ())}
    decoders = {key: {"track": layers.get(key, {}).get("track_name") or layers.get(key, {}).get("track_id"),
                     "source_name": Path(source.path).name, **source.performance_snapshot()}
                for key, source in getattr(scene, "_players", {}).items()}
    if compact:
        for row in decoders.values():
            for key in ('recent_requests','samples','callback_gaps_ms'):row.pop(key,None)
    engine=getattr(page,'audio_engine',None)
    decision=getattr(page,'_audio_playback_decision',None)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "clock": asdict(clock.snapshot()) if clock else None,
        "compositor": scene.performance_snapshot() if scene else None,
        "native_overlay": _native_overlay_snapshot(canvas),
        "render_geometry": _render_geometry(canvas, scene),
        "decoders": decoders,
        "audio": engine.telemetry_snapshot() if engine else None,
        "audio_request": dict(getattr(engine,'_last_payload',{})),
        "audio_routing": asdict(decision) if decision else None,
        "preview_key": getattr(page,'_active_video_preview_key',''),
        "preview_source": getattr(page,'_active_video_preview_source_path',''),
        "playback_mode": getattr(page,'_playback_mode',''),
        "tracks": [{'id':t.id,'enabled':getattr(t,'enabled',True),'muted':getattr(t,'muted',False)}
                   for t in getattr(getattr(page,'project',None),'audio_tracks',())],
        "autosave": list(getattr(page, "_autosave_profile", ()))[-8:],
        "gui_loop": _gui_loop_stats(),
        "pending": _pending_work(page),
        "ipc": _ipc_snapshot(canvas, compact=compact),
        "primary_backend": _primary_backend_snapshot(canvas),
        "playback_plan": _playback_plan_snapshot(page),
        "qc_worker": getattr(page,'_qc_worker').snapshot() if getattr(page,'_qc_worker',None) else None,
        "qc_timings": getattr(page,'_qc_worker_timings',None),
    }


def _native_overlay_snapshot(canvas):
    from ..diagnostics.publication_metrics import upload_snapshot
    samples = getattr(canvas, '_video_upload_samples', None)
    rows = list(samples.copy())[-1200:] if samples is not None else []
    return upload_snapshot(rows, perf_counter())


def _render_geometry(canvas, scene):
    """Record the actual Qt canvas and raster mapping, never monitor resolution."""
    result = {}
    for name, widget in (('canvas', canvas), ('compositor', scene)):
        if widget is None or not callable(getattr(widget, 'devicePixelRatioF', None)):
            continue
        ratio = float(widget.devicePixelRatioF())
        top = widget.mapToGlobal(QPoint(0, 0))
        result[name] = {'logical_size': [widget.width(), widget.height()], 'dpr': ratio,
            'physical_size': [round(widget.width()*ratio), round(widget.height()*ratio)],
            'global_logical_origin': [top.x(), top.y()], 'visible': widget.isVisible()}
    return result


def _ipc_snapshot(canvas, *, compact=False):
    actor=getattr(getattr(canvas,'controller',None),'_actor',None)
    snapshot=getattr(actor,'request_metrics',None)
    return snapshot(include_raw=not compact) if callable(snapshot) else None


def _primary_backend_snapshot(canvas):
    controller=getattr(canvas,'controller',None)
    observed=getattr(controller,'observed_properties',None)
    values=observed() if callable(observed) else {}
    keys=('mpv-version','current-vo','hwdec-current','video-codec','video-sync','display-sync-active','video-speed-correction',
          'display-fps','estimated-display-fps','container-fps','video-params',
          'decoder-frame-drop-count','frame-drop-count','vo-delayed-frame-count','speed','pause')
    frame = getattr(controller, 'observed_frame', None)
    return {'measurement':'cached backend observations; no synchronous IPC',
            'frame_ready_witness': frame() if callable(frame) else {'status':'unsupported'},
            **{key:values.get(key) for key in keys}}


def _playback_plan_snapshot(page):
    runtime=getattr(getattr(page,'session',None),'runtime',None)
    plan=getattr(runtime,'_playback_plan',None)
    return {'revision':getattr(runtime,'playback_revision',None),
            'builds':getattr(runtime,'playback_plan_builds',0),
            'invalidation':getattr(runtime,'playback_invalidation',''),
            'build_ms':getattr(plan,'build_ms',None),'samples':getattr(plan,'samples',0)}


def _gui_loop_stats() -> dict | None:
    from ..diagnostics.gui_stall_watchdog import instance
    watchdog = instance()
    return watchdog.lag_stats() if watchdog is not None else None


def _pending_work(page) -> dict:
    """Queued requests that can pile up behind a busy GUI thread."""
    engine = getattr(page, 'audio_engine', None)
    canvas = getattr(page, 'video', None)
    controller = getattr(canvas, 'controller', None)
    actor = getattr(controller, '_actor', None)
    requests = getattr(actor, '_requests', None)
    scene = getattr(page, '_caption_scene', None)
    return {
        "audio_sync_inflight": bool(getattr(engine, '_sync_inflight', False)),
        "audio_sync_queued": getattr(engine, '_pending_sync', None) is not None,
        "mpv_actor_queue": len(requests) if requests is not None else None,
        "caption_warm_pending": len(getattr(scene, 'warm_pending', ()) or ()),
        "caption_frames_cached": len(getattr(scene, 'frames', ()) or ()),
    }


def stall_context(page) -> dict:
    """Small playback picture attached to a GUI_STALL record (GUI thread)."""
    canvas = getattr(page, 'video', None)
    clock = getattr(canvas, '_playback_clock', None)
    snapshot = clock.snapshot() if clock is not None else None
    project = getattr(page, 'project', None)
    return {
        "page_visible": bool(page.isVisible()),
        "paused": bool(getattr(canvas, '_paused', True)),
        "rate": float(getattr(canvas, '_playback_rate', 1.0) or 1.0),
        "startup_state": str(getattr(canvas, '_startup_state', '')),
        "playhead_ms": int(getattr(getattr(page, 'timeline', None), 'playhead_ms', 0) or 0),
        "clock_media_ms": round(float(snapshot.presentation_media_ms), 1) if snapshot else None,
        "clock_generation": int(snapshot.playback_generation) if snapshot else None,
        "cue_count": len(getattr(project, 'cues', ()) or ()),
        "playback_mode": str(getattr(page, '_playback_mode', '')),
        "pending": _pending_work(page),
    }


class StudioPerformanceDialog(QDialog):
    exported = Signal(str)
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setObjectName("studioPerformance")
        bind_text(self, '播放性能 · Ctrl+Shift+P', property='windowTitle')
        self.resize(760, 600)
        layout = QVBoxLayout(self)
        title = QLabel("播放性能", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        note = QLabel("每 0.5 秒更新。合成提交与播放器命令确认按次/秒计；它们不代表屏幕帧率。记录 15 秒会保存播放、音频和像素处理耗时；未采集到的项目显示 —。", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setObjectName("performanceDetails")
        layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("复制诊断数据", self)
        self.copy_button.setObjectName("studioPrimary")
        self.copy_button.clicked.connect(self.copy_snapshot)
        buttons.addWidget(self.copy_button)
        self.record_button=QPushButton('记录 15 秒',self)
        self.record_button.clicked.connect(self.start_capture)
        buttons.addWidget(self.record_button)
        self.export_button=QPushButton('导出播放诊断…',self)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_capture)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        close = QPushButton("关闭", self)
        close.setObjectName("studioButton")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._snapshot = {}
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self._capture_token=None
        self._capture_rows=deque(maxlen=4096)
        self._capture_snapshots=deque(maxlen=40)
        self._capture_timer=QTimer(self)
        self._capture_timer.setTimerType(Qt.PreciseTimer)
        self._capture_timer.setInterval(8)
        self._capture_timer.timeout.connect(self.capture_tick)
        self._export_worker=None
        self.exported.connect(lambda message:self.export_button.setText(message))

    def showEvent(self, event):
        from ..design.studio_theme import build_studio_qss
        self.setStyleSheet(build_studio_qss())
        self.refresh()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._capture_token is not None:self.finish_capture()
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        self._snapshot = performance_snapshot(self.page)
        if self._capture_token is not None:
            self._capture_snapshots.append({'at':perf_counter(),**performance_snapshot(self.page,compact=True)})
        comp = self._snapshot["compositor"] or {}
        clock = self._snapshot["clock"] or {}
        state = "定位中" if clock.get("seeking") else "暂停" if clock.get("paused", True) else "播放中"
        def number(key):
            value = comp.get(key)
            return "—" if value is None else f"{value:.1f}"
        native = self._snapshot['native_overlay']
        ack = native['ack']['events_per_second']
        ack_text = '—' if ack is None else f'{ack:.1f}'
        bind_text(self.summary, '{state}  ·  {value1:g}×  ·  {value2} 个解码器\n合成提交 {value3} 次/秒    播放器确认 {value4} 次/秒    合成 P95 {value5} ms', state=state, value1=clock.get('playback_rate', 1), value2=len(self._snapshot['decoders']), value3=number('native_publish_fps'), value4=ack_text, value5=number('render_p95_ms'))
        scroll = self.details.verticalScrollBar().value()
        # Keep selection stable so the user can inspect/copy a specific value.
        if not self.details.textCursor().hasSelection():
            self.details.setPlainText(json.dumps(self._snapshot, ensure_ascii=False, indent=2, allow_nan=False))
            self.details.verticalScrollBar().setValue(scroll)

    def copy_snapshot(self):
        self.refresh()
        QApplication.clipboard().setText(json.dumps(self._snapshot, ensure_ascii=False, indent=2, allow_nan=False))
        bind_text(self.copy_button, '已复制诊断数据')

    def start_capture(self):
        if self._capture_token is not None:return
        from ..diagnostics import playback_probe
        self._capture_rows.clear();self._capture_snapshots.clear()
        self._capture_begin=self._capture_previous=perf_counter()
        self._capture_token=playback_probe.configure(enabled=True,light=True)
        self.record_button.setEnabled(False);self.record_button.setText('正在记录…')
        self._capture_timer.start()

    def capture_tick(self):
        now=perf_counter()
        self._capture_rows.append({'at':now,'delay_ms':max(0,(now-self._capture_previous)*1000-8)})
        self._capture_previous=now
        if now-self._capture_begin>=15:self.finish_capture()

    def finish_capture(self):
        from ..diagnostics import playback_probe
        from ..diagnostics.playback_metrics import distribution
        from ..diagnostics.build_identity import load_build_identity
        from ..diagnostics.event_log import recorder,emit
        self._capture_timer.stop();token,self._capture_token=self._capture_token,None
        if token is None:return
        playback_probe.restore(token)
        end=perf_counter();begin=self._capture_begin
        events=[r for r in playback_probe.take() if begin<=r['at']<=end]
        project=getattr(self.page,'project',None)
        import sys,PySide6
        from PySide6.QtCore import qVersion
        from ..app.ui_zoom import zoom_percent
        report={'schema':1,'identity':load_build_identity().to_dict(),
            'environment':{'python':sys.version,'platform':sys.platform,'PySide6':PySide6.__version__,'Qt':qVersion(),
                           'interface_zoom_percent':zoom_percent()},
            'captured_at':datetime.now(timezone.utc).isoformat(),'effective_seconds':end-begin,
            'functional_pass':'UNVERIFIED','measurement_valid':{'gui':end-begin>=15,'desktop':False,'system_present':False},
            'performance_pass':'UNVERIFIED','clock':'Python perf_counter / QPC; 8ms event-loop heartbeat',
            'media':vars(project.media) if project else None,
            'features':{'cue_count':len(project.cues),'video_tracks':len(project.video_tracks),
                'audio_tracks':len(project.audio_tracks),'bilingual':project.studio_state.get('bilingual',{}),
                'effect_ids':sorted({cue.effect_id for cue in project.cues})} if project else {},
            'screens':[{'name':s.name(),'geometry':s.geometry().getRect(),'dpr':s.devicePixelRatio(),'refresh_hz':s.refreshRate()} for s in QApplication.screens()],
            'ui_delay_ms':distribution([r['delay_ms'] for r in self._capture_rows]),
            'apply_playhead_ms':distribution([r['ms'] for r in events if r['stage']=='apply_playhead' and 'ms' in r]),
            'probe':playback_probe.counters(),'heartbeat':list(self._capture_rows),
            'telemetry':list(self._capture_snapshots),'events':events[-10000:],
            'events_omitted':max(0,len(events)-10000)}
        samples = getattr(getattr(self.page, 'video', None), '_video_upload_samples', None)
        uploads = list(samples.copy()) if samples is not None else []
        uploads = [row for row in uploads if begin <= row.get('started', 0) <= end]
        report['pixel_pipeline'] = {'measurement': 'QPC stage timestamps; native ACK is not GPU completion',
            'status': 'measured' if uploads else 'not_sampled', 'samples': uploads[-2400:],
            'samples_omitted': max(0, len(uploads)-2400),
            'gpu_time_status': 'unsupported: current external mpv IPC has no GPU timestamps'}
        self._capture_report=report
        instance=recorder()
        if instance is not None:instance.playback_capture=report
        emit('playback.short_capture',seconds=report['effective_seconds'],ui_delay_ms=report['ui_delay_ms'],performance_pass='UNVERIFIED')
        self.record_button.setEnabled(True);self.record_button.setText('再记录 15 秒')
        self.export_button.setEnabled(True)

    def export_capture(self):
        if not getattr(self,'_capture_report',None):return
        path,_=QFileDialog.getSaveFileName(self,'导出播放诊断','playback-diagnostic.json','JSON (*.json)')
        if not path:return
        from ..rendering.latest_work import LatestWork
        from ..diagnostics.event_log import Sanitizer
        if self._export_worker is None:self._export_worker=LatestWork('playback-diagnostic-export')
        report=self._capture_report
        self.export_button.setText('正在导出…')
        def write():
            try:
                import os
                # Serialize/sanitize/write only after capture, on the bounded
                # existing latest-work executor, never on a playback tick.
                data=Sanitizer().clean(report)
                target=Path(path);temporary=target.with_name(target.name+'.tmp')
                temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
                os.replace(temporary,target)
                self.exported.emit('已导出播放诊断')
            except Exception as error:self.exported.emit('导出失败：'+str(error))
        self._export_worker.submit(write)
