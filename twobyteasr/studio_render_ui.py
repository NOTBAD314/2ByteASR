"""Compact Simple/Advanced render panel for Subtitle Studio."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .studio_project import SubtitleProject, studio_data_root
from .studio_render import (
    CONTAINER_CODECS,
    RenderJob,
    RenderSettings,
    cached_encoder_choices,
    preview_job,
    run_render_job,
    scan_encoder_capabilities,
)
from .studio_render_queue import get_render_queue
from .studio_theme import StudioComboBox, apply_secondary_surface_theme, studio_message_box

from .i18n import bind_text

from .i18n import tr


class StudioRenderDialog(QDialog):
    render_succeeded = Signal(str, bool)
    render_failed = Signal(str)
    progress_received = Signal(object)
    encoders_ready = Signal()

    def __init__(
        self,
        project: SubtitleProject,
        ass_path: str,
        playhead_seconds: float,
        parent=None,
        *,
        project_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.ass_path = ass_path
        self.playhead_seconds = float(playhead_seconds)
        self.project_path = Path(project_path).resolve() if project_path else None
        self.ffmpeg = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        self._cancelled = threading.Event()
        self._running = False
        self._worker: threading.Thread | None = None
        self._encoder_scan: threading.Thread | None = None
        self._encoder_scan_started = False
        self._fallback_notice = ""
        self._config_widgets: list[QWidget] = []
        self._output_manual = False
        self._render_cursor_pushed = False
        self._duration_seconds = max(0.0, float(self.project.media.duration_ms or 0) / 1000.0)
        bind_text(self, '压制成片', property='windowTitle')
        self.setMinimumWidth(620)
        apply_secondary_surface_theme(self)
        self._build()
        self.render_succeeded.connect(self._finished)
        self.render_failed.connect(self._failed)
        self.progress_received.connect(self._progress)
        self.encoders_ready.connect(self._on_encoders_ready)
        self._refresh_encoders()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        preset_section = QGroupBox("渲染预设")
        form = QFormLayout(preset_section)
        self.render_preset = StudioComboBox()
        self.render_preset.addItem("B站上传", "bilibili")
        self.render_preset.addItem("高质量", "quality")
        self.render_preset.addItem("高压缩存档", "archive")
        self.render_preset.addItem("快速预览", "fast")
        self.render_preset.currentIndexChanged.connect(self._apply_render_preset)
        form.addRow("预设", self.render_preset)
        layout.addWidget(preset_section)
        self._config_widgets.append(preset_section)

        output_section = QGroupBox("输出")
        form = QFormLayout(output_section)
        self.container = StudioComboBox()
        self.container.addItems(("MP4", "MKV", "MOV", "WebM", "FLV"))
        self.container.currentTextChanged.connect(self._container_changed)
        form.addRow("输出格式", self.container)
        layout.addWidget(output_section)
        self._config_widgets.append(output_section)

        video_section = QGroupBox("视频")
        form = QFormLayout(video_section)
        self.codec = StudioComboBox()
        self.codec.addItem("H.264", "h264")
        self.codec.addItem("HEVC / H.265", "hevc")
        self.codec.addItem("AV1", "av1")
        self.codec.currentIndexChanged.connect(self._refresh_encoders)
        form.addRow("视频编码", self.codec)
        self.encoder = StudioComboBox()
        self.encoder.currentIndexChanged.connect(self._refresh_quality_modes)
        form.addRow("可用编码器", self.encoder)
        self.encoder_label = form.labelForField(self.encoder)
        self.quality_mode = StudioComboBox()
        self.quality_mode.addItem("CRF / CQ", "crf")
        self.quality_mode.addItem("VBR", "vbr")
        self.quality_mode.addItem("固定码率", "bitrate")
        self.quality_mode.currentIndexChanged.connect(self._quality_mode_changed)
        form.addRow("质量模式", self.quality_mode)
        self.quality = QSpinBox()
        self.quality.setRange(0, 63)
        self.quality.setValue(20)
        form.addRow("质量", self.quality)
        self.quality_label = form.labelForField(self.quality)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 200_000)
        self.bitrate.setValue(8000)
        self.bitrate.setSuffix(" kbps")
        form.addRow("视频码率", self.bitrate)
        self.bitrate_label = form.labelForField(self.bitrate)
        layout.addWidget(video_section)
        self._config_widgets.append(video_section)

        picture_section = QGroupBox("画面")
        form = QFormLayout(picture_section)
        self.resolution = StudioComboBox()
        self.resolution.addItem("跟随源视频", (0, 0))
        self.resolution.addItem("1920 x 1080", (1920, 1080))
        self.resolution.addItem("1280 x 720", (1280, 720))
        self.resolution.addItem("自定义", None)
        self.resolution.currentIndexChanged.connect(self._resolution_changed)
        form.addRow("分辨率", self.resolution)
        custom_resolution = QWidget()
        custom_resolution_layout = QHBoxLayout(custom_resolution)
        custom_resolution_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_width = QSpinBox()
        self.custom_height = QSpinBox()
        for control in (self.custom_width, self.custom_height):
            control.setRange(16, 16384)
        self.custom_width.setValue(1920)
        self.custom_height.setValue(1080)
        custom_resolution_layout.addWidget(self.custom_width)
        custom_resolution_layout.addWidget(QLabel("x"))
        custom_resolution_layout.addWidget(self.custom_height)
        form.addRow("自定义分辨率", custom_resolution)
        self.custom_resolution_widget = custom_resolution
        self.custom_resolution_label = form.labelForField(custom_resolution)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0, 240)
        self.fps.setValue(0)
        self.fps.setSpecialValueText("源帧率")
        form.addRow("帧率", self.fps)
        layout.addWidget(picture_section)
        self._config_widgets.append(picture_section)

        audio_section = QGroupBox("音频")
        form = QFormLayout(audio_section)
        self.audio = StudioComboBox()
        self.audio.addItem("直接复制", "copy")
        self.audio.addItem("AAC 192 kbps", "aac")
        self.audio.addItem("Opus 192 kbps", "opus")
        self.audio.currentIndexChanged.connect(self._audio_changed)
        form.addRow("音频", self.audio)
        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(32, 1024)
        self.audio_bitrate.setValue(192)
        self.audio_bitrate.setSuffix(" kbps")
        form.addRow("音频码率", self.audio_bitrate)
        self.audio_sample_rate = StudioComboBox()
        for label, value in (("源采样率", 0), ("32 kHz", 32000), ("44.1 kHz", 44100), ("48 kHz", 48000), ("96 kHz", 96000)):
            self.audio_sample_rate.addItem(label, value)
        form.addRow("采样率", self.audio_sample_rate)
        self.audio_channels = StudioComboBox()
        for label, value in (("源声道", 0), ("单声道", 1), ("立体声", 2), ("5.1", 6), ("7.1", 8)):
            self.audio_channels.addItem(label, value)
        form.addRow("声道", self.audio_channels)
        layout.addWidget(audio_section)
        self._config_widgets.append(audio_section)

        destination_section = QGroupBox("输出位置")
        form = QFormLayout(destination_section)
        output_row = QHBoxLayout()
        filename_row = QHBoxLayout()
        media = Path(self.project.media.path)
        self.filename_base = QLineEdit(media.stem)
        self.filename_suffix = QLineEdit(str(QSettings("2ByteASR", "2ByteASR").value("render/filename_suffix", "_成片")))
        bind_text(self.filename_suffix, '默认保存到全局设置；例如 _字幕版', property='toolTip')
        filename_row.addWidget(self.filename_base, 2)
        filename_row.addWidget(self.filename_suffix, 1)
        form.addRow("文件命名", filename_row)
        self.filename_base.textChanged.connect(self._update_output_name)
        self.filename_suffix.textChanged.connect(self._update_output_name)
        self.output = QLineEdit()
        archive_exports = self.project_path.parent / "exports" if self.project_path else None
        output_dir = archive_exports if archive_exports and archive_exports.is_dir() else media.parent
        bind_text(self.output, str(output_dir / f'{media.stem}_成片.mp4'))
        browse = QPushButton("浏览")
        browse.clicked.connect(self._browse)
        output_row.addWidget(self.output, 1)
        output_row.addWidget(browse)
        form.addRow("文件", output_row)
        layout.addWidget(destination_section)
        self._config_widgets.append(destination_section)
        self._resolution_changed()
        self._audio_changed()

        advanced = QGroupBox("高级编码设置")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_form = QFormLayout(advanced)
        self.preset = StudioComboBox()
        self.preset.addItems(("fast", "medium", "slow"))
        self.preset.setCurrentText("medium")
        advanced_form.addRow("编码速度", self.preset)
        self.profile = QLineEdit()
        advanced_form.addRow("编码 Profile", self.profile)
        self.level = QLineEdit()
        advanced_form.addRow("编码 Level", self.level)
        self.pixel_format = StudioComboBox()
        self.pixel_format.addItems(("yuv420p", "yuv420p10le"))
        advanced_form.addRow("像素格式", self.pixel_format)
        self.gop = QSpinBox()
        self.gop.setRange(0, 1000)
        self.gop.setSpecialValueText("Auto")
        advanced_form.addRow("关键帧间隔", self.gop)
        self.b_frames = QSpinBox()
        self.b_frames.setRange(-1, 16)
        self.b_frames.setSpecialValueText("Auto")
        advanced_form.addRow("B 帧", self.b_frames)
        self.max_bitrate = QSpinBox()
        self.max_bitrate.setRange(500, 300_000)
        self.max_bitrate.setValue(12_000)
        self.max_bitrate.setSuffix(" kbps")
        advanced_form.addRow("最大码率", self.max_bitrate)
        self.font_directory = QLineEdit()
        advanced_form.addRow("字体目录", self.font_directory)
        for index in range(advanced_form.rowCount()):
            role = QFormLayout.ItemRole.FieldRole
            item = advanced_form.itemAt(index, role)
            if item and item.widget():
                item.widget().setVisible(False)
            label_item = advanced_form.itemAt(index, QFormLayout.ItemRole.LabelRole)
            if label_item and label_item.widget():
                label_item.widget().setVisible(False)
        advanced.toggled.connect(
            lambda checked: self._set_advanced_visible(advanced_form, checked)
        )
        layout.addWidget(advanced)
        self._config_widgets.append(advanced)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("")
        layout.addWidget(self.status)
        self.rendering_label = QLabel("正在压制字幕视频")
        self.rendering_label.hide()
        layout.addWidget(self.rendering_label)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = QPushButton("预览 10 秒")
        self.preview_button.clicked.connect(lambda: self._start(True))
        actions.addWidget(self.preview_button)
        self.render_button = QPushButton("开始压制")
        self.render_button.setProperty("studioPrimary", True)
        self.render_button.clicked.connect(lambda: self._start(False))
        actions.addWidget(self.render_button)
        queue_button = QPushButton("加入队列")
        queue_button.clicked.connect(self._enqueue)
        actions.addWidget(queue_button)
        cancel = QPushButton("关闭")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def _update_output_name(self) -> None:
        if self._output_manual:
            return
        base = self.filename_base.text().strip() or Path(self.project.media.path).stem
        suffix = self.filename_suffix.text().strip()
        if suffix and not suffix.startswith("_"):
            suffix = "_" + suffix
        suffix = suffix or "_成片"
        QSettings("2ByteASR", "2ByteASR").setValue("render/filename_suffix", suffix)
        directory = Path(self.output.text()).parent if hasattr(self, "output") and self.output.text() else Path(self.project.media.path).parent
        extension = self.container.currentText().lower() if hasattr(self, "container") else "mp4"
        candidate = directory / f"{base}{suffix}.{extension}"
        if hasattr(self, "output"):
            self.output.setText(str(candidate))

    def _set_rendering_state(self, running: bool) -> None:
        for widget in self._config_widgets:
            widget.setVisible(not running)
        self.rendering_label.setVisible(running)
        self.progress.setVisible(running)
        if running:
            self.progress.setValue(0)
            bind_text(self.status, '正在压制 0%')

    def _set_advanced_visible(self, form: QFormLayout, visible: bool) -> None:
        for index in range(form.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                item = form.itemAt(index, role)
                if item and item.widget():
                    item.widget().setVisible(visible)

    def _refresh_encoders(self) -> None:
        """Populate encoders from the persisted capability cache only.

        A cold cache must never probe FFmpeg here: ``ffmpeg -encoders`` plus
        an 8-frame test encode per hardware encoder used to run inside the
        dialog constructor and freeze the UI for tens of seconds. Instead the
        scan runs in the background once and repopulates via ``encoders_ready``.
        """
        self.encoder.clear()
        cached = cached_encoder_choices(
            self.ffmpeg, str(self.codec.currentData() or "h264")
        )
        if cached is None:
            choices: list[str] = []
            self._start_encoder_scan()
        else:
            choices = cached
        labels = {
            "h264_nvenc": "NVIDIA NVENC",
            "hevc_nvenc": "NVIDIA NVENC",
            "av1_nvenc": "NVIDIA NVENC",
            "h264_qsv": "Intel QSV",
            "hevc_qsv": "Intel QSV",
            "av1_qsv": "Intel QSV",
            "h264_amf": "AMD AMF",
            "hevc_amf": "AMD AMF",
            "av1_amf": "AMD AMF",
            "libx264": "Software x264",
            "libx265": "Software x265",
            "libaom-av1": "Software libaom AV1",
        }
        for name in choices:
            self.encoder.addItem(labels.get(name, name), name)
        multiple = len(choices) > 1
        self.encoder.setVisible(multiple)
        self.encoder_label.setVisible(multiple)
        if not multiple and choices:
            bind_text(self.status, '编码器：{value0}', value0=labels.get(choices[0], choices[0]))
        self.render_button.setEnabled(bool(choices))
        self._refresh_quality_modes()

    def _start_encoder_scan(self) -> None:
        if self._encoder_scan_started:
            # A finished scan left no usable cache: FFmpeg is missing or its
            # probes fail. Report once instead of re-probing (and freezing).
            bind_text(self.status, '未能检测可用编码器，请检查 FFmpeg 运行时')
            self.render_button.setEnabled(False)
            return
        self._encoder_scan_started = True
        bind_text(self.status, '正在检测可用编码器（后台运行，不阻塞窗口）…')
        self.render_button.setEnabled(False)

        def work() -> None:
            # A failed scan surfaces through the still-missing cache path.
            try:
                scan_encoder_capabilities(self.ffmpeg)
            except Exception:
                pass
            self.encoders_ready.emit()

        self._encoder_scan = threading.Thread(
            target=work, daemon=True, name="render-dialog-encoder-scan"
        )
        self._encoder_scan.start()

    def _on_encoders_ready(self) -> None:
        # The background scan persisted the shared capability cache; the
        # refresh now finds it and populates without any subprocess call.
        self._refresh_encoders()

    def _settings(self) -> RenderSettings:
        resolution = self.resolution.currentData()
        width, height = (
            (self.custom_width.value(), self.custom_height.value())
            if resolution is None
            else resolution
        )
        mode = str(self.quality_mode.currentData() or "recommended")
        encoder = str(self.encoder.currentData() or "libx264")
        if mode in {"recommended", "high"}:
            quality_mode = "crf" if encoder.startswith("lib") else "cq"
        elif mode == "size":
            quality_mode = "bitrate"
        else:
            quality_mode = "crf" if encoder.startswith("lib") else "cq"
        return RenderSettings(
            container=self.container.currentText().lower(),
            codec=str(self.codec.currentData()),
            encoder=str(self.encoder.currentData()),
            quality_mode=quality_mode,
            quality=self.quality.value(),
            bitrate_kbps=self.bitrate.value(),
            max_bitrate_kbps=self.max_bitrate.value(),
            width=width,
            height=height,
            fps=self.fps.value(),
            audio_codec=str(self.audio.currentData()),
            audio_bitrate_kbps=self.audio_bitrate.value(),
            audio_sample_rate=int(self.audio_sample_rate.currentData() or 0),
            audio_channels=int(self.audio_channels.currentData() or 0),
            preset=self.preset.currentText(),
            profile=self.profile.text().strip(),
            level=self.level.text().strip(),
            pixel_format=self.pixel_format.currentText(),
            gop=self.gop.value(),
            b_frames=self.b_frames.value(),
            font_directory=self.font_directory.text().strip(),
        )

    def _browse(self) -> None:
        extension = self.container.currentText().lower()
        path, _selected = QFileDialog.getSaveFileName(
            self, tr('输出视频'), self.output.text(), f"{extension.upper()} (*.{extension})"
        )
        if path:
            self._output_manual = True
            self.output.setText(path)

    def _container_changed(self, value: str) -> None:
        current = Path(self.output.text())
        self.output.setText(str(current.with_suffix("." + value.lower())))
        wanted = str(self.codec.currentData() or "h264")
        allowed = CONTAINER_CODECS[value.lower()]
        self.codec.blockSignals(True)
        self.codec.clear()
        labels = {"h264": "H.264", "hevc": "HEVC / H.265", "av1": "AV1"}
        for codec in allowed:
            self.codec.addItem(labels[codec], codec)
        self.codec.setCurrentIndex(max(0, self.codec.findData(wanted)))
        self.codec.blockSignals(False)
        self._refresh_encoders()

    def _refresh_quality_modes(self) -> None:
        if not hasattr(self, "quality_mode"):
            return
        encoder = str(self.encoder.currentData() or "")
        wanted = str(self.quality_mode.currentData() or "recommended")
        modes = (("推荐", "recommended"), ("高质量", "high"), ("体积优先", "size"), ("自定义", "custom"))
        self.quality_mode.blockSignals(True)
        self.quality_mode.clear()
        for label, mode in modes:
            self.quality_mode.addItem(label, mode)
        self.quality_mode.setCurrentIndex(max(0, self.quality_mode.findData(wanted)))
        self.quality_mode.blockSignals(False)
        self._quality_mode_changed()

    def _quality_mode_changed(self) -> None:
        mode = str(self.quality_mode.currentData() or "")
        custom = mode == "custom"
        size_first = mode == "size"
        self.quality.setVisible(custom)
        self.quality_label.setVisible(custom)
        self.bitrate.setVisible(custom or size_first)
        self.bitrate_label.setVisible(custom or size_first)
        self.quality.setEnabled(custom)
        self.bitrate.setEnabled(custom or size_first)

    def _resolution_changed(self) -> None:
        custom = self.resolution.currentData() is None
        self.custom_resolution_widget.setVisible(custom)
        self.custom_resolution_label.setVisible(custom)

    def _audio_changed(self) -> None:
        reencode = str(self.audio.currentData() or "copy") != "copy"
        for control in (self.audio_bitrate, self.audio_sample_rate, self.audio_channels):
            control.setEnabled(reencode)

    def _apply_render_preset(self) -> None:
        preset = str(self.render_preset.currentData() or "bilibili")
        values = {
            "bilibili": ("MP4", "h264", 20, "medium", (1920, 1080)),
            "quality": ("MP4", "h264", 18, "slow", (0, 0)),
            "archive": ("MKV", "hevc", 18, "slow", (0, 0)),
            "fast": ("MP4", "h264", 28, "fast", (1280, 720)),
        }[preset]
        container, codec, quality, speed, resolution = values
        self.container.setCurrentText(container)
        codec_index = self.codec.findData(codec)
        if codec_index >= 0:
            self.codec.setCurrentIndex(codec_index)
        self.quality.setValue(quality)
        self.preset.setCurrentText(speed)
        resolution_index = self.resolution.findData(resolution)
        if resolution_index >= 0:
            self.resolution.setCurrentIndex(resolution_index)

    def _start(self, preview: bool) -> None:
        if self._running:
            return
        settings = self._settings()
        if preview:
            directory = studio_data_root() / "render-preview"
            directory.mkdir(parents=True, exist_ok=True)
            output = directory / f"{self.project.project_id}.{settings.container}"
            duration = self.project.media.duration_ms / 1000
            job = preview_job(
                self.project.media.path,
                self.ass_path,
                str(output),
                settings,
                self.playhead_seconds,
                duration,
            )
        else:
            output = Path(self.output.text())
            overwrite = self._confirm_existing_output(output)
            if overwrite is None:
                return
            job = RenderJob(
                self.project.media.path,
                self.ass_path,
                str(output),
                settings,
                overwrite_existing=overwrite,
            )
        self._cancelled.clear()
        self._fallback_notice = ""
        self._running = True
        self._output_manual = False if preview else self._output_manual
        self._set_rendering_state(True)
        self.render_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        bind_text(self.status, '正在压制...')

        def work():
            try:
                rendered = run_render_job(
                    self.ffmpeg,
                    job,
                    progress=self.progress_received.emit,
                    cancelled=self._cancelled.is_set,
                )
                self.render_succeeded.emit(str(rendered), preview)
            except Exception as exc:
                self.render_failed.emit(str(exc))

        self._worker = threading.Thread(target=work, daemon=True, name="studio-render")
        self._worker.start()

    def _enqueue(self) -> None:
        if self._running:
            return
        settings = self._settings()
        output = Path(self.output.text())
        overwrite = self._confirm_existing_output(output)
        if overwrite is None:
            return
        job = RenderJob(
            self.project.media.path,
            self.ass_path,
            str(output),
            settings,
            overwrite_existing=overwrite,
        )
        try:
            queued = get_render_queue(self.ffmpeg).enqueue(job)
        except Exception as exc:
            self.status.setText(str(exc))
            return
        bind_text(self.status, '已加入压制队列: {value0}', value0=queued.id[:8])

    def _progress(self, payload: dict) -> None:
        notice = str(payload.get("notice") or "")
        if notice:
            existing = self._fallback_notice.splitlines()
            if notice not in existing:
                self._fallback_notice = "\n".join([*existing, notice])
            self.status.setText(self._fallback_notice)
            return
        time_value = payload.get("out_time") or payload.get("out_time_ms") or ""
        seconds = self._parse_timecode(time_value)
        if self._duration_seconds > 0 and seconds >= 0:
            percent = max(0, min(100, round(seconds / self._duration_seconds * 100)))
            self.progress.setValue(percent)
            bind_text(self.status, '正在压制 {percent}% · {time_value}', percent=percent, time_value=time_value)
        else:
            (bind_text(self.status, '正在压制 {value0}', value0=time_value) if time_value else bind_text(self.status, '正在压制...'))

    def _finished(self, path: str, preview: bool) -> None:
        self._running = False
        self._release_render_interaction_state()
        self._set_rendering_state(False)
        self.render_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        suffix = f" {self._fallback_notice}" if self._fallback_notice else ""
        bind_text(self.status, ('预览已生成' if preview else f'已完成: {path}') + suffix)
        if not preview:
            self._show_render_success(Path(path))

    def _show_render_success(self, output: Path) -> None:
        dialog = QDialog(self)
        bind_text(dialog, '压制完成', property='windowTitle')
        dialog.setMinimumWidth(460)
        apply_secondary_surface_theme(dialog)
        layout = QVBoxLayout(dialog)
        title = QLabel("✓ 压制完成")
        from .ui_theme import theme_definition
        from .theme_manager import theme_key
        title.setStyleSheet(f"font-size:18px; font-weight:700; color:{theme_definition(theme_key()).success};")
        layout.addWidget(title)
        message = bind_text(QLabel(), '视频已保存：\n{output}', output=output)
        message.setWordWrap(True)
        layout.addWidget(message)
        if self._fallback_notice:
            notice = QLabel(self._fallback_notice)
            notice.setObjectName("cardMeta")
            notice.setWordWrap(True)
            layout.addWidget(notice)
        actions = QHBoxLayout()
        open_video = QPushButton("打开视频")
        open_video.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))))
        open_folder = QPushButton("打开文件夹")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent))))
        done = QPushButton("完成")
        done.setProperty("studioPrimary", True)
        done.clicked.connect(dialog.accept)
        actions.addWidget(open_video)
        actions.addWidget(open_folder)
        actions.addStretch(1)
        actions.addWidget(done)
        layout.addLayout(actions)
        dialog.exec()

    def _failed(self, message: str) -> None:
        self._running = False
        self._release_render_interaction_state()
        self._set_rendering_state(False)
        self.render_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        friendly = self._friendly_error(message)
        (bind_text(self.status, '压制已取消') if self._cancelled.is_set() else bind_text(self.status, friendly))
        if not self._cancelled.is_set():
            studio_message_box(self, QMessageBox.Icon.Critical, tr('压制失败'), friendly)

    def _confirm_existing_output(self, output: Path) -> bool | None:
        if not output.exists():
            return False
        answer = studio_message_box(
            self,
            QMessageBox.Icon.Warning,
            tr('输出文件已存在'),
            tr('是否在压制成功后替换现有文件？\n\n{value0}', value0=output),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return True if answer == QMessageBox.StandardButton.Yes else None

    @staticmethod
    def _friendly_error(message: str) -> str:
        lowered = message.lower()
        if "permission denied" in lowered or "access is denied" in lowered:
            return "输出目录不可写。请选择有写入权限的位置后重试。"
        if "no space left" in lowered or "not enough space" in lowered or "disk full" in lowered:
            return "输出磁盘空间不足。清理空间或更换输出位置后重试。"
        if "输出文件已存在" in message or "file exists" in lowered:
            return "输出文件已存在。确认替换或选择新的文件名后重试。"
        if "render cancelled" in lowered:
            return "压制已取消"
        if "ffmpeg render failed" in lowered:
            detail = message.split(":", 1)[-1].strip()
            return "FFmpeg 压制失败。可调整编码器或音频设置后重试。" + (f"\n\n{detail}" if detail else "")
        return message

    def reject(self) -> None:
        self._cancelled.set()
        self._release_render_interaction_state()
        super().reject()

    def closeEvent(self, event: QEvent) -> None:
        self._cancelled.set()
        self._release_render_interaction_state()
        super().closeEvent(event)

    @staticmethod
    def _parse_timecode(value: object) -> float:
        text = str(value or "")
        try:
            if ":" not in text:
                numeric = float(text)
                # FFmpeg's out_time_ms is expressed in microseconds.
                return numeric / 1_000_000.0 if abs(numeric) > 10_000 else numeric
            parts = text.split(":")
            if len(parts) != 3:
                return -1.0
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (TypeError, ValueError):
            return -1.0

    def _release_render_interaction_state(self) -> None:
        if self.mouseGrabber() is self:
            self.releaseMouse()
        if self._render_cursor_pushed:
            QApplication.restoreOverrideCursor()
            self._render_cursor_pushed = False
        self.unsetCursor()
