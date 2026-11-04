"""Format-specific controls for the existing export workspace."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import threading
import time
import traceback
import uuid

from PySide6.QtCore import Signal, QSignalBlocker, Qt
from PySide6.QtWidgets import QGroupBox, QFormLayout, QLabel
from ..design.studio_theme import StudioComboBox
from ..i18n import tr, bind_text
from .audio_delivery import FORMATS, format_capabilities
from .studio_render import RenderSettings, RenderJob, run_render_job, export_progress


class AudioExportControls(QGroupBox):
    capabilities_ready = Signal(object)

    def __init__(self, workspace):
        super().__init__(tr('音频输出设置'))
        self.workspace=workspace
        self.capabilities=None
        self.scanning=False
        self.form=QFormLayout(self)
        def combo(items):
            control=StudioComboBox()
            for label,value in items:control.addItem(tr(label),value)
            control.currentIndexChanged.connect(self.update_settings)
            return control
        self.bitrate=combo([(f'{rate} kbps',rate) for rate in (64,96,128,192,256,320)])
        self.bitrate.setCurrentIndex(3)
        self.rate=combo([('跟随工程音源',0),('32000 Hz',32000),('44100 Hz',44100),('48000 Hz',48000),('96000 Hz',96000)])
        self.channels=combo([('跟随混音',0),('单声道',1),('立体声',2)])
        self.depth=combo([('16 bit',16),('24 bit',24),('32 bit PCM',32)])
        self.form.addRow(tr('码率'),self.bitrate)
        self.form.addRow(tr('采样率'),self.rate)
        self.form.addRow(tr('声道'),self.channels)
        self.form.addRow(tr('位深'),self.depth)
        self.note=QLabel();self.note.setWordWrap(True);self.form.addRow(self.note)
        self.capabilities_ready.connect(self.accept_capabilities)
        self.hide()

    def scan(self):
        if self.scanning or self.capabilities is not None:return
        self.scanning=True
        bind_text(self.note,'正在验证随包音频编码器与封装器…')
        self.workspace.export_button.setEnabled(False)
        def work():
            try:value=format_capabilities(self.workspace.ffmpeg)
            except Exception as exc:value={'error':str(exc)}
            try:self.capabilities_ready.emit(value)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='audio-format-probe').start()

    def accept_capabilities(self,value):
        self.scanning=False;self.capabilities=value
        if is_audio(self.workspace):self.update_settings()

    def update_settings(self,*_):
        w=self.workspace
        if not hasattr(w,'audio_delivery') or not is_audio(w):return
        name=w.extension.currentData()
        if name not in FORMATS:return
        lossless=name in {'wav','flac'}
        self.form.setRowVisible(self.bitrate,not lossless)
        self.form.setRowVisible(self.depth,lossless)
        for i in range(self.rate.count()):
            value=self.rate.itemData(i)
            enabled=not (name in {'mp3','ogg'} and value>48000 or name=='opus' and value not in (0,48000))
            self.rate.model().item(i).setEnabled(enabled)
        if not self.rate.model().item(self.rate.currentIndex()).isEnabled():
            self.rate.setCurrentIndex(0)
        self.depth.model().item(2).setEnabled(name=='wav')
        if name=='flac' and self.depth.currentData()==32:self.depth.setCurrentIndex(1)
        status=(self.capabilities or {}).get(name,{})
        ok=bool(status.get('available'))
        if self.capabilities is not None:
            bind_text(self.note, '使用工程编辑后的音轨；包含裁切、速度、音量、淡化、空隙与混音。' if ok else
                '当前随包工具不可用：{reason}', **({} if ok else {'reason':status.get('reason') or self.capabilities.get('error','编码器不可用')}))
        if name=='opus' and ok:
            bind_text(self.note,'Opus 使用 48000 Hz；副档名 .opus，Ogg 封装。输出工程编辑后的声音。')
        if name=='wav' and ok:
            bind_text(self.note,'PCM 无损音频；超过 4 GiB 时自动使用 RF64，播放器需要支持 RF64。')
        w.export_button.setEnabled(ok)
        w.queue_button.setEnabled(ok)
        w._target_changed()

    def settings(self):
        name=self.workspace.extension.currentData()
        return RenderSettings(output_kind='audio',container=name,encoder=FORMATS[name][1],
            audio_codec=FORMATS[name][1],audio_bitrate_kbps=self.bitrate.currentData(),
            audio_sample_rate=self.rate.currentData(),audio_channels=self.channels.currentData(),
            audio_bit_depth=self.depth.currentData())


def is_audio(workspace):
    return hasattr(workspace,'output_kind') and workspace.output_kind.currentData()=='audio'


def change_mode(workspace):
    w=workspace
    audio=is_audio(w)
    with QSignalBlocker(w.extension):
        w.extension.clear()
        for label,name in ([(label,key) for key,(label,*_) in FORMATS.items()] if audio else
                           [('MP4','mp4'),('MKV','mkv'),('MOV','mov'),('WebM / AV1','webm')]):
            w.extension.addItem(label,name)
    w.video_group.setVisible(not audio);w.video_audio_group.setVisible(not audio)
    w.subtitle_file_group.setVisible(not audio)
    w.audio_delivery.setVisible(audio)
    w.advanced_button.setVisible(not audio)
    w.advanced_panel.setVisible(not audio and w.advanced_button.isChecked())
    if hasattr(w, 'advanced_card'): w.advanced_card.setVisible(not audio)
    w.preview_host.setVisible(not audio)
    if hasattr(w, 'output_layout_preview') and audio:
        w.output_layout_preview.hide()
    for widget in (w.preview_play_button,w.preview_time,w.preview_scrub,w.duration_label):
        widget.setVisible(not audio)
    bind_text(w.preview_title,'音频导出范围' if audio else '导出预览')
    w.preview_panel.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
    w.render_preview_host.setVisible(not audio)
    bind_text(w.processing_title,'正在导出工程音频' if audio else '正在压制字幕视频')
    bind_text(w.setup_title,'导出工程音频' if audio else '导出字幕视频')
    bind_text(w.export_button,'导出音频' if audio else '开始导出')
    if audio:
        if w._preview_widget and callable(getattr(w._preview_widget,'set_paused',None)):
            w._preview_widget.set_paused(True)
        w.audio_delivery.scan()
        w.audio_delivery.update_settings()
    else:
        w.export_button.setEnabled(True);w.queue_button.setEnabled(True)
        w._container_changed()
    w._target_changed()


def audio_job(workspace, output, settings=None):
    from ..playback.audio_graph import capture_audio_graph
    w=workspace
    start,duration,effective=w._range_seconds()
    graph=copy.deepcopy(capture_audio_graph(w.project))
    fingerprint=hashlib.sha256(json.dumps(graph,sort_keys=True,ensure_ascii=False).encode('utf8')).hexdigest()
    settings=settings or w.audio_delivery.settings()
    return RenderJob(w.project.media.path,'',str(output),settings=settings,
        start_seconds=start,duration_seconds=effective,audio_graph=graph,
        export_context=dict(job_id=uuid.uuid4().hex,project_revision='audio-sha256:'+fingerprint,
            requested_encoder=settings.encoder,requested_settings=asdict(settings)))


def start_audio(workspace):
    from .studio_render import validate_export_config
    from .export_progress import ExportProgress
    w=workspace
    if w._running:return
    try:
        job=audio_job(w,w.export_target().full_path)
        validate_export_config(job)
        if not w.ffmpeg.is_file():raise FileNotFoundError('FFmpeg 不存在：'+str(w.ffmpeg))
        if Path(job.output_path).exists():raise FileExistsError('输出文件已存在：'+job.output_path)
        if not (job.audio_graph or {}).get('segments'):
            raise ValueError('工程没有可听音轨；请检查轨道启用与静音状态。')
    except Exception as exc:
        w._show_failure(str(exc));return
    w._advanced_route=False;w._has_composition_stage=False
    w._last_job=job;w._running=True;w._started_at=time.monotonic();w._completion_notified=False;w._last_failure=''
    job.completion_metadata['requested_started_monotonic']=w._started_at
    w._cancelled.clear()
    w._work_progress=ExportProgress(job.duration_seconds,raster=False,advanced=False,static_advanced=False)
    w._progress_target=0;w._progress_display=0.;w._progress_indeterminate=True
    w._show_advanced_stage(False)
    w._apply_progress(-1,export_progress('prepare_project',message='正在准备工程音轨…'))
    bind_text(w.processing_output,'输出：{output}',output=job.output_path)
    w.render_preview_host.hide();w.pages.setCurrentWidget(w.exporting_page)
    def work():
        try:
            path=run_render_job(w.ffmpeg,job,progress=w._progress,cancelled=w._cancelled.is_set,trace=w._export_trace)
            w.render_succeeded.emit(str(path))
        except InterruptedError:w.render_cancelled.emit()
        except Exception as exc:
            w._export_trace('audio_failure',reason=str(exc),traceback=traceback.format_exc())
            w.render_failed.emit(str(exc))
    w._worker=threading.Thread(target=work,daemon=True,name='studio-audio-export')
    w._worker.start()
