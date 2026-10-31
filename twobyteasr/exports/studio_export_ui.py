"""Embedded Export Workspace 2.1 for subtitle-burned video delivery."""

from __future__ import annotations

import json
import copy
import re
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
from ..design.typography import TITLE_FONT_STACK
from ..design.tokens import WEIGHT_SCALE
from ..design.presentation import button_role, field_width

from ..i18n import current_language, bind_text

from ..i18n import join_text, tr

_ASSETS_ROOT = Path(__file__).resolve().parents[2] / "assets"
_EXPORT_CHECK_ICON = (_ASSETS_ROOT / "check-dark.png").as_posix()
_EXPORT_DOT_ICON = (_ASSETS_ROOT / "dot-dark.png").as_posix()

from PySide6.QtCore import QEvent, QSettings, QUrl, Qt, Signal, QTimer, QSize, QRectF
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QMouseEvent, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QGridLayout, QLineEdit, QMenu, QPushButton, QProgressBar, QScrollArea, QSizePolicy, QSlider,
    QRadioButton, QSpinBox, QSplitter, QStackedWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from ..projects.studio_project import SubtitleProject
from ..system.platform_media import ffmpeg_tool


class ProcessedFrameView(QLabel):
    """Latest processed frame, fitted at paint time in logical coordinates."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._frame = QPixmap()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.setMinimumSize(160, 90)
        self.setAlignment(Qt.AlignCenter)

    def sizeHint(self):
        return QSize(640, 360)

    def setPixmap(self, pixmap):
        self._frame = pixmap
        self.update()

    def pixmap(self):
        return self._frame

    def clear(self):
        self._frame = QPixmap()
        super().clear()
        self.update()

    def frame_rect(self):
        if self._frame.isNull():
            return QRectF()
        target = QRectF(self.contentsRect())
        size = self._frame.size().scaled(target.size().toSize(), Qt.KeepAspectRatio)
        result = QRectF(0, 0, size.width(), size.height())
        result.moveCenter(target.center())
        return result

    def paintEvent(self, event):
        if self._frame.isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self.frame_rect(), self._frame, QRectF(self._frame.rect()))
        painter.end()
from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, has_translations
from ..design.controls import StyledCheckBox, StyledRadio
from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
from ..timeline.studio_sequence_mapper import export_source_slices
from ..rendering.advanced_renderer import AdvancedRendererBackend, project_requires_advanced
from .studio_render import (
    RenderJob, RenderSettings, STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX, STAGE_VALIDATE,
    STAGE_ORDER, STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES, STAGE_COMPOSE_VIDEO,
    SVT_AV1_SPEED_PRESETS, cached_encoder_choices, export_progress, load_encoder_capabilities,
    parse_ffmpeg_out_time_seconds, run_render_job, validate_export_config,
)
from .export_presets import (
    load_user_presets, save_user_presets, visible_product_presets,
)
from .studio_render_queue import get_render_queue
from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme, build_secondary_surface_qss
from ..design.soft_widgets import FoldCard, SegmentedControl, WrapLayout
from ..design.themed_icons import install_themed_icon
from .export_setup_widgets import (
    FIELD_HEIGHT, PresetChips, captioned, export_setup_qss, fill_pills, fit_affix, name_well, show_field,
    source_is_audio_only,
)
from ..design.theme_manager import theme_key
from ..design.ui_theme import ThemeDefinition, theme_definition

# "Auto" H.264 on NVENC: the preset number + this keeps the x264 picture.
# Real 1080p60 game footage, 120 s (2026-10-28): x264 medium CRF 20 6.2 Mb/s,
# SSIM 0.9936; NVENC p4 CQ 20 14.8 Mb/s 0.9956; CQ 24 9.3 Mb/s 0.9937.
AUTO_NVENC_CQ_OFFSET = 4


def _workspace_theme() -> ThemeDefinition:
    return theme_definition(theme_key())


def _directory_is_writable(path: Path) -> bool:
    target = Path(path).expanduser()
    if target.exists():
        return target.is_dir() and os.access(target, os.W_OK)
    parent = target.parent
    while parent != parent.parent and not parent.exists():
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def resolve_subtitle_export_destination(
    project: SubtitleProject,
    project_path: Path | None,
    mode: str,
    custom_directory: str = "",
) -> tuple[Path, str]:
    """Resolve ordinary-user subtitle delivery with a safe project fallback."""

    source_path = str(project.media.path or "").strip()
    source_directory = Path(source_path).expanduser().parent if source_path else None
    project_exports = (
        Path(project_path).expanduser().parent / "exports"
        if project_path is not None
        else source_directory / "exports" if source_directory is not None else None
    )
    normalized = str(mode or "source")
    if normalized == "custom":
        custom = Path(str(custom_directory or "").strip()).expanduser()
        if not str(custom_directory or "").strip():
            raise ValueError("请先选择自定义字幕保存文件夹")
        if not _directory_is_writable(custom):
            raise PermissionError(f"自定义字幕目录不可写：{custom}")
        return custom, "自定义位置"
    if normalized == "project":
        if project_exports is None:
            raise ValueError("工程尚未保存且没有源媒体，请选择自定义字幕保存文件夹")
        return project_exports, "工程 exports 目录"
    if source_directory is not None and _directory_is_writable(source_directory):
        return source_directory, "与源媒体同目录"
    if project_exports is None:
        raise ValueError("工程尚未保存且没有源媒体，请选择自定义字幕保存文件夹")
    return project_exports, "源媒体目录不可写，已改用工程 exports 目录"


def _export_workspace_qss(theme: ThemeDefinition) -> str:
    """Page-level export surface sheet, fully token-driven (no warm literals)."""
    return f"""
        QWidget#studioExportWorkspace, QWidget#exportSetupPage,
        QWidget#exportingPage, QWidget#exportSuccessPage, QWidget#exportFailurePage,
        QScrollArea#exportSettingsScroll, QWidget#exportSettingsViewport,
        QScrollArea#exportPreviewScroll, QWidget#exportPreviewViewport,
        QWidget#exportSettingsPage, QFrame#exportPreviewPanel {{
            background: {theme.app_background}; color: {theme.text}; border: 0;
        }}
        QGroupBox {{ background: {theme.surface}; border: 1px solid {theme.border};
            border-radius: 10px; margin-top: 10px; padding-top: 8px; color: {theme.text}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {theme.text}; }}
        QGroupBox[exportCard="true"] {{ background: {theme.surface}; border: 1px solid {theme.border};
            border-radius: 12px; margin-top: 0; padding: 0; }}
        QGroupBox[exportCard="true"][nested="true"] {{ background: transparent; border: 0;
            border-top: 1px solid {theme.hairline}; border-radius: 0; }}
        QFrame#exportPreviewPanel {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
        QFrame#exportPreviewPanel QGroupBox[exportCard="true"] {{ background: transparent; border: 0;
            border-top: 1px solid {theme.hairline}; border-radius: 0; }}
        QFrame#exportPreviewCard, QFrame#exportRangeCard, QFrame#exportFooter {{
            background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
        QLabel#exportCardTitle {{ color: {theme.text}; font-size: 15px; font-weight: 600; background: transparent; }}
        QLabel#exportCardIcon {{ background: {theme.accent_tint}; border-radius: 8px; }}
        QLabel#exportFieldLabel {{ color: {theme.text_secondary}; font-size: 13px; font-weight: 500; background: transparent; }}
        QLabel#exportPageContext {{ color: {theme.text_muted}; font-size: 13px; font-weight: 500; }}
        QLabel#exportOutputPath {{ color: {theme.text_secondary}; font-size: 13px; }}
        QPushButton#exportBackButton {{ background: transparent; color: {theme.text_secondary};
            border: 1px solid {theme.border}; border-radius: 8px; padding: 4px 12px; font-weight: 500; }}
        QPushButton#exportBackButton:hover {{ background: {theme.selected}; color: {theme.text}; border-color: {theme.border_strong}; }}
        QPushButton#exportPlayButton {{ background: {theme.accent_tint}; color: {theme.accent_text};
            border: 1px solid transparent; border-radius: 8px; padding: 5px 14px; font-weight: 600; }}
        QPushButton#exportPlayButton:hover {{ background: {theme.accent}; color: {theme.text_on_accent}; }}
        QLabel#exportPageTitle, QLabel#exportFailureTitle {{ color: {theme.text}; font-family: {TITLE_FONT_STACK}; font-weight: {WEIGHT_SCALE['heavy']}; }}
        QLabel#exportSummaryBody {{ color: {theme.text}; font-size: 14px; font-variant-numeric: tabular-nums; }}
        QLabel#exportRendererBadge {{
            background: {theme.success_soft}; color: {theme.success}; border: 0;
            border-radius: 7px; padding: 3px 10px; font-weight: 600;
        }}
        QLabel#exportRendererBadge[rendererKind="advanced"] {{
            background: {theme.info_soft}; color: {theme.info};
        }}
        QPushButton#exportQueueButton {{ font-size: 14px; font-weight: {WEIGHT_SCALE['medium']}; }}
        QPushButton#exportStartButton {{ font-size: 16px; font-weight: {WEIGHT_SCALE['bold']}; color: {theme.text_on_accent}; }}
        QFrame#exportPreviewHost, QFrame#renderPreviewHost {{
            background: {theme.media}; border: 1px solid {theme.border}; border-radius: 10px;
        }}
        QLabel#exportPreviewFallback, QLabel#renderPreviewFallback {{ color: {theme.text}; }}
        QLabel#exportPreviewTime {{ color: {theme.text_muted}; font-variant-numeric: tabular-nums; }}
        QLabel#exportRangeLabel {{ color: {theme.text_secondary}; font-size: 13px; font-variant-numeric: tabular-nums; }}
        QFrame#exportRunningHeader {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 12px; }}
        QLabel#exportPercentBadge {{
            color: {theme.text}; background: {theme.selected}; border: 1px solid {theme.border_strong};
            border-radius: 18px; font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums;
        }}
        QLabel[exportStage="true"] {{ border-radius: 10px; padding: 9px; font-weight: 700; }}
        QLabel[stageState="waiting"] {{ background: {theme.panel}; color: {theme.text_muted}; border: 1px solid {theme.border}; }}
        QLabel[stageState="running"] {{ background: {theme.accent_tint}; color: {theme.accent_text}; border: 1px solid {theme.accent_text}; }}
        QLabel[stageState="complete"] {{ background: {theme.success_soft}; color: {theme.success}; border: 1px solid {theme.success}; }}
        QLabel#exportCurrentStage {{
            font-weight: 600; color: {theme.accent_text}; background: {theme.accent_tint};
            border: 1px solid {theme.accent_text}; border-radius: 8px; padding: 8px;
        }}
        QLabel#exportProcessingInfo {{ color: {theme.text_muted}; font-variant-numeric: tabular-nums; }}
        QToolButton#exportRunningDetails {{
            background: {theme.surface}; color: {theme.text}; border: 1px solid {theme.border};
            border-radius: 8px; padding: 6px 10px;
        }}
        QWidget#subtitleExportDialog QCheckBox, QWidget#exportSetupPage QCheckBox {{
            spacing: 7px; padding: 3px 5px; color: {theme.text};
        }}
        QWidget#subtitleExportDialog QCheckBox::indicator, QWidget#exportSetupPage QCheckBox::indicator {{
            width: 16px; height: 16px; border: 1px solid {theme.border_strong};
            border-radius: 3px; background: {theme.surface};
        }}
        QWidget#subtitleExportDialog QCheckBox::indicator:checked, QWidget#exportSetupPage QCheckBox::indicator:checked {{
            background: {theme.accent}; border-color: {theme.accent};
            image: url({_EXPORT_CHECK_ICON});
        }}
        QWidget#subtitleExportDialog QRadioButton, QWidget#exportSetupPage QRadioButton {{
            spacing: 7px; padding: 3px 5px; color: {theme.text};
        }}
        QWidget#subtitleExportDialog QRadioButton::indicator, QWidget#exportSetupPage QRadioButton::indicator {{
            width: 15px; height: 15px; border: 1px solid {theme.border_strong};
            border-radius: 8px; background: {theme.surface};
        }}
        QWidget#subtitleExportDialog QRadioButton::indicator:checked, QWidget#exportSetupPage QRadioButton::indicator:checked {{
            background: {theme.accent}; border: 1px solid {theme.accent};
            image: url({_EXPORT_DOT_ICON});
        }}
        QLabel#exportSuccessIcon {{ color: {theme.success}; background: {theme.surface}; border-radius: 8px; font-size:22px; }}
        QLabel#exportSuccessMeta {{ color: {theme.text_muted}; font-variant-numeric: tabular-nums; }}
        QFrame#exportResultCard {{
            background: {theme.surface}; border: 1px solid {theme.border};
            border-radius: 14px;
        }}
        QWidget#exportResultInfo {{ background: transparent; }}
        QLabel#exportSectionLabel {{ color: {theme.text_secondary}; font-size: 17px; font-weight: 700; }}
        QLabel#exportResultPath {{ color: {theme.text}; font-size: 16px; }}
        QWidget#exportResultInfo QLabel#exportSuccessMeta {{ font-size: 16px; }}
        QFrame#exportResultRule {{ background: {theme.border}; border: 0; }}
        QPushButton#exportSuccessNav {{
            background: {theme.surface}; color: {theme.text}; border: 1px solid {theme.border_strong};
            border-radius: 8px; font-size: 15px; font-weight: 600; padding: 0 18px;
        }}
        QPushButton#exportSuccessNav:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
        QWidget#exportSuccessBody, QWidget#exportSuccessPage QScrollArea {{ background:{theme.app_background}; border:0; }}
        QLabel#exportFailureTitle {{ color: {theme.danger}; }}
        QLabel#exportSuccessTitle {{ font-family: {TITLE_FONT_STACK}; font-size: 28px; font-weight: {WEIGHT_SCALE['heavy']}; color: {theme.text}; }}
        QLabel#exportSuccessName {{ font-size: 15px; font-weight: 600; color: {theme.text_secondary}; }}
        QLabel#exportResultValue {{ font-size:26px; font-weight:700; color:{theme.text}; }}
        QPushButton#exportResultPreview {{ background:{theme.panel}; border:1px solid {theme.border}; border-radius:12px; }}
        QPushButton#exportResultPreview:hover {{ border-color:{theme.accent}; }}
        QPushButton#successOpenVideo {{
            background: {theme.accent}; color: {theme.text_on_accent}; border: 1px solid {theme.accent_pressed};
            border-radius: 8px; font-size: 16px; font-weight: 700; padding: 0 22px; min-height: 58px; max-height: 58px;
        }}
        QPushButton#successOpenVideo:hover {{ background: {theme.accent_hover}; }}
        QPushButton#successOpenFolder {{
            background: {theme.surface_elevated}; color: {theme.text}; border: 1px solid {theme.border_strong};
            border-radius: 8px; font-size: 16px; font-weight: 600; padding: 0 20px; min-height: 48px; max-height: 48px;
        }}
        QPushButton#successOpenFolder:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
        QPushButton#exportSuccessTertiary {{
            background: {theme.surface}; color: {theme.text}; border: 1px solid {theme.border};
            border-radius: 8px; font-size: 13px; font-weight: 500; padding:0 14px;
        }}
        QPushButton#exportSuccessTertiary:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
        QPushButton#exportSuccessQuiet {{ background:transparent; color:{theme.text_muted}; border:1px solid transparent; font-size:13px; padding:0 12px; }}
        QPushButton#exportSuccessQuiet:hover {{ color:{theme.text}; background:{theme.selected}; }}
        QWidget#exportSuccessPage QPushButton:pressed {{ background:{theme.selected}; }}
        QPushButton#successOpenVideo:pressed {{ background:{theme.accent_pressed}; }}
        QWidget#exportSuccessPage QPushButton:focus {{ border:1px solid {theme.accent}; }}
        QWidget#exportSuccessPage QPushButton:disabled {{ color:{theme.text_muted}; background:{theme.surface}; border-color:{theme.border}; }}
    """


@dataclass(frozen=True)
class ExportTarget:
    directory: Path
    base_name: str
    extension: str = "mp4"

    @property
    def full_path(self) -> Path:
        extension = self.extension.lstrip(".") or "mp4"
        base_name = self.base_name.strip()
        return self.directory / (base_name if base_name.lower().endswith(f".{extension.lower()}") else f"{base_name}.{extension}")


class SubtitleExportDialog(QDialog):
    """Focused subtitle-only export dialog used by the Studio toolbar.

    2026-10-18: format cards with a line on each format's use, segmented
    speaker / destination choices, a short path with “打开文件夹” and a preview
    of the files that will be written. With ``export_on_accept`` the dialog
    exports itself and ends on a result page (打开文件夹 / 复制路径).
    """

    def __init__(self, project: SubtitleProject, project_path: str | Path | None = None, parent=None, *,
                 export_on_accept: bool = False, base_name: str = ""):
        super().__init__(parent)
        from ..design.studio_theme import _active_theme
        from .subtitle_export_widgets import (
            DESTINATION_CHOICES, LANGUAGE_CHOICES, SPEAKER_CHOICES, FileList, PathRow, SegmentedChoice,
            build_subtitle_export_qss, chip, footer_frame, format_grid, section_label,
        )
        self.project = project
        self.project_path = Path(project_path).resolve() if project_path else None
        self.export_on_accept = bool(export_on_accept)
        self.base_name = str(base_name or Path(project.media.path).stem or "subtitles")
        self.artifacts: tuple = ()
        self.result_reason = ""
        self._settings = QSettings("2ByteASR", "2ByteASR")
        bind_text(self, '导出字幕', property='windowTitle')
        self.setMinimumWidth(680)
        self.setObjectName("subtitleExportDialog")
        apply_secondary_surface_theme(self)
        theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(theme) + build_subtitle_export_qss(theme))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)

        setup = QWidget()
        outer = QVBoxLayout(setup)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body_host = QWidget()
        body = QVBoxLayout(body_host)
        body.setContentsMargins(22, 18, 22, 12)
        body.setSpacing(9)
        self.setup_scroll = QScrollArea()
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setup_scroll.setWidget(body_host)
        outer.addWidget(self.setup_scroll, 1)
        title = QLabel()
        title.setObjectName("exportDialogTitle")
        bind_text(title, "导出字幕")
        body.addWidget(title)
        from .export_preferences import output_basename
        name = QLabel()
        name.setObjectName("exportDialogMeta")
        bind_text(name, "文件名：{name}", name=output_basename(self.base_name))
        body.addWidget(name)
        body.addSpacing(4)

        body.addWidget(section_label("格式（可多选）"))
        saved_formats = str(self._settings.value("subtitle/export_formats", "srt") or "srt").split(",")
        self.format_checks: dict = {}
        body.addWidget(format_grid(self.format_checks, saved_formats))
        for card in self.format_checks.values():
            card.toggled.connect(lambda _checked: self._refresh_preview())

        # Language layers, only when the project has translations: the same
        # original / translation / bilingual SRT set as the export page.
        self.language_checks: dict = {}
        self.language_row = QWidget()
        language = QVBoxLayout(self.language_row)
        language.setContentsMargins(0, 2, 0, 0)
        language.setSpacing(6)
        language.addWidget(section_label("语言（SRT）"))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for layer, label in LANGUAGE_CHOICES:
            button = chip(label, checked=True)
            button.toggled.connect(lambda _checked: self._refresh_preview())
            self.language_checks[layer] = button
            chips.addWidget(button)
        self.translation_first = StyledCheckBox("双语译文在上")
        self.translation_first.setChecked(True)
        chips.addSpacing(6)
        chips.addWidget(self.translation_first)
        chips.addStretch(1)
        language.addLayout(chips)
        self.language_row.setVisible(has_translations(project))
        body.addWidget(self.language_row)

        body.addWidget(section_label("说话人"))
        self.speaker_choice = SegmentedChoice(SPEAKER_CHOICES)
        self.speaker_modes = self.speaker_choice.buttons
        saved_speaker = str(self._settings.value("subtitle/export_speaker_mode", "combined") or "combined")
        self.speaker_choice.set_value(saved_speaker if saved_speaker in self.speaker_modes else "combined")
        self.speaker_choice.group.buttonToggled.connect(lambda *_args: self._refresh_preview())
        body.addWidget(self.speaker_choice)
        self.speaker_hint = QLabel()
        self.speaker_hint.setObjectName("exportHint")
        self.speaker_hint.setWordWrap(True)
        body.addWidget(self.speaker_hint)

        body.addWidget(section_label("存到"))
        self.destination_choice = SegmentedChoice(DESTINATION_CHOICES)
        self.destination_modes = self.destination_choice.buttons
        saved_destination = str(self._settings.value("subtitle/export_destination", "source") or "source")
        if saved_destination not in self.destination_modes:
            saved_destination = "source"
        self.custom_directory = QLineEdit(str(self._settings.value("subtitle/custom_directory", "") or ""))
        self.custom_directory.setReadOnly(True)
        self.custom_directory.hide()
        if saved_destination == "custom" and not self.custom_directory.text().strip():
            saved_destination = "source"
        self.destination_choice.set_value(saved_destination)
        self.destination_choice.changed.connect(self._destination_clicked)
        body.addWidget(self.destination_choice)
        self.path_row = PathRow()
        self.path_row.open_clicked.connect(self._open_destination)
        self.path_row.change_clicked.connect(self._choose_custom_directory)
        body.addWidget(self.path_row)
        self.destination_status = QLabel()
        self.destination_status.setObjectName("exportHint")
        self.destination_status.setWordWrap(True)
        body.addWidget(self.destination_status)
        self.file_list = FileList()
        body.addWidget(self.file_list)
        self.warning = QLabel()
        self.warning.setObjectName("checkWarning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        error_host = QWidget()
        error_row = QHBoxLayout(error_host)
        error_row.setContentsMargins(22, 0, 22, 0)
        error_row.addWidget(self.warning, 1)
        self._error_details = ""
        self.error_details_button = QPushButton("错误详情…")
        self.error_details_button.setObjectName("subtitleErrorDetails")
        button_role(self.error_details_button, "secondary")
        self.error_details_button.clicked.connect(self._show_error_details)
        self.error_details_button.hide()
        error_row.addWidget(self.error_details_button)
        body.addStretch(1)
        outer.addWidget(error_host)
        footer, row = footer_frame()
        row.addStretch(1)
        cancel = QPushButton()
        bind_text(cancel, "取消")
        button_role(cancel, "secondary")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.export_button = QPushButton()
        bind_text(self.export_button, "导出字幕")
        button_role(self.export_button, "primary")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._accept)
        row.addWidget(self.export_button)
        outer.addWidget(footer)
        self.pages.addWidget(setup)
        self.setup_page = setup

        done = QWidget()
        done_outer = QVBoxLayout(done)
        done_outer.setContentsMargins(0, 0, 0, 0)
        done_outer.setSpacing(0)
        done_body = QVBoxLayout()
        done_body.setContentsMargins(24, 22, 24, 12)
        done_body.setSpacing(10)
        badge = QLabel("✓")
        badge.setObjectName("exportDoneBadge")
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        done_body.addWidget(badge)
        self.done_title = QLabel()
        self.done_title.setObjectName("exportDialogTitle")
        done_body.addWidget(self.done_title)
        self.done_note = QLabel()
        self.done_note.setObjectName("exportHint")
        self.done_note.setWordWrap(True)
        done_body.addWidget(self.done_note)
        self.done_files = FileList()
        done_body.addWidget(self.done_files)
        self.done_path = PathRow(can_change=False)
        self.done_path.open_button.hide()  # the footer's primary button opens it
        done_body.addWidget(self.done_path)
        done_body.addStretch(1)
        done_outer.addLayout(done_body, 1)
        done_footer, done_row = footer_frame()
        self.copy_paths_button = QPushButton()
        bind_text(self.copy_paths_button, "复制路径")
        button_role(self.copy_paths_button, "secondary")
        self.copy_paths_button.clicked.connect(self._copy_paths)
        done_row.addWidget(self.copy_paths_button)
        done_row.addStretch(1)
        self.done_button = QPushButton()
        bind_text(self.done_button, "完成")
        button_role(self.done_button, "secondary")
        self.done_button.clicked.connect(self.accept)
        done_row.addWidget(self.done_button)
        self.open_folder_button = QPushButton()
        bind_text(self.open_folder_button, "打开文件夹")
        button_role(self.open_folder_button, "primary")
        self.open_folder_button.clicked.connect(lambda: (self._open_result_folder(), self.accept()))
        done_row.addWidget(self.open_folder_button)
        done_outer.addWidget(done_footer)
        self.pages.addWidget(done)
        self.done_page = done
        for button in self.findChildren(QPushButton):
            if button is not self.export_button:
                button.setAutoDefault(False)
        self._last_destination = saved_destination
        self._destination_changed(saved_destination, persist=False)

    # ----------------------------------------------------------- choices
    def _selected_destination(self) -> str:
        return self.destination_choice.value() or "source"

    def selected_speaker_mode(self) -> str:
        return self.speaker_choice.value() or "combined"

    def _selected_formats(self) -> frozenset[str]:
        return frozenset(name for name, box in self.format_checks.items() if box.isChecked())

    def _selected_layers(self) -> tuple[str, ...]:
        if self.language_row.isHidden():
            return ()
        return tuple(layer for layer, button in self.language_checks.items() if button.isChecked())

    def selected_options(self) -> SubtitleExportOptions:
        return SubtitleExportOptions(self._selected_formats(), self.selected_speaker_mode())

    def selected_destination(self) -> tuple[Path, str]:
        return resolve_subtitle_export_destination(self.project, self.project_path, self._selected_destination(), self.custom_directory.text())

    def _destination_clicked(self, mode: str) -> None:
        if mode == "custom" and not self.custom_directory.text().strip():
            if not self._choose_custom_directory():
                self.destination_choice.set_value(self._last_destination)
            return
        self._destination_changed(mode)

    def _destination_changed(self, mode: str, *, persist: bool = True) -> None:
        if not mode:
            return
        self._last_destination = mode
        if persist:
            self._settings.setValue("subtitle/export_destination", mode)
        self.path_row.change_button.setVisible(mode == "custom")
        try:
            destination, reason = resolve_subtitle_export_destination(
                self.project, self.project_path, mode, self.custom_directory.text()
            )
            self.path_row.set_path(str(destination))
            fallback = reason not in {"自定义位置", "工程 exports 目录", "与源媒体同目录"}
            bind_text(self.destination_status, reason) if fallback else self.destination_status.clear()
        except (ValueError, PermissionError) as exc:
            self.path_row.set_path("", exists=False)
            self.destination_status.setText(str(exc))
        self.destination_status.setVisible(bool(self.destination_status.text()))
        self._refresh_preview()

    def _choose_custom_directory(self) -> bool:
        path = QFileDialog.getExistingDirectory(self, tr('选择字幕保存文件夹'), self.custom_directory.text() or str(Path(self.project.media.path).parent))
        if not path:
            return False
        self.custom_directory.setText(path)
        self._settings.setValue("subtitle/custom_directory", path)
        self.destination_choice.set_value("custom")
        self._destination_changed("custom")
        return True

    def _open_destination(self) -> None:
        from .subtitle_export_widgets import open_folder
        open_folder(self.path_row.path_label.path())

    def _refresh_preview(self) -> None:
        from .studio_subtitle_export import planned_subtitle_files
        formats = self._selected_formats()
        layers = self._selected_layers()
        mode = self.selected_speaker_mode()
        try:
            directory, _reason = self.selected_destination()
        except (ValueError, PermissionError):
            directory = None
        planned = planned_subtitle_files(self.project, directory, self.base_name,
                                         SubtitleExportOptions(formats, mode), layers) if formats else ()
        self.file_list.set_files(planned)
        missing_layer = bool(self.language_row.isVisibleTo(self) and "srt" in formats and not layers)
        if missing_layer:
            bind_text(self.file_list.header, "SRT 至少选一种语言")
        self.export_button.setEnabled(bool(planned) and not missing_layer)
        (bind_text(self.export_button, "导出 {count} 个文件", count=len(planned)) if planned
         else bind_text(self.export_button, "导出字幕"))
        from ..projects.speaker_names import display_speaker_name
        visible = {cue.speaker_id for cue in self.project.visible_cues()}
        names = {speaker.id: display_speaker_name(self.project, speaker) for speaker in self.project.speakers}
        shown = [names.get(speaker_id, speaker_id) for speaker_id in dict.fromkeys(
            cue.speaker_id for cue in self.project.visible_cues())]
        hidden = [names[speaker.id] for speaker in self.project.speakers
                  if speaker.hidden and speaker.id not in visible
                  and any(cue.speaker_id == speaker.id for cue in self.project.cues)]
        parts = []
        if mode != "combined" and shown:
            parts.append(tr("每人一份：{names}", names="、".join(shown)))
        if hidden:
            parts.append(tr("已隐藏的说话人不导出：{names}", names="、".join(hidden)))
        self.speaker_hint.setText("\n".join(parts))
        self.speaker_hint.setVisible(bool(parts))

    # ------------------------------------------------------------ export
    def _accept(self) -> None:
        self.warning.hide()
        if not self._selected_formats():
            bind_text(self.warning, '至少选择一种字幕格式')
            self.warning.show()
            return
        try:
            self.selected_destination()
        except (ValueError, PermissionError) as exc:
            self.warning.setText(str(exc))
            self.warning.show()
            return
        self._settings.setValue("subtitle/export_formats", ",".join(name for name, box in self.format_checks.items() if box.isChecked()))
        self._settings.setValue("subtitle/export_speaker_mode", self.selected_speaker_mode())
        self._settings.setValue("subtitle/export_destination", self._selected_destination())
        if not self.export_on_accept:
            self.accept()
            return
        self._run_export()

    def _run_export(self) -> None:
        from .studio_subtitle_export import export_language_layers
        directory, reason = self.selected_destination()
        formats = set(self._selected_formats())
        layers = self._selected_layers()
        mode = self.selected_speaker_mode()
        self.export_button.setEnabled(False)
        bind_text(self.export_button, "正在写入并回读验证…")
        QApplication.processEvents()
        layered = None
        self._error_details = ""
        self.error_details_button.hide()
        self.warning.hide()
        try:
            # All formats/layers see one committed edit, including after a
            # later asynchronous replacement of the live project's cues.
            export_project = copy.deepcopy(self.project)
            if layers and "srt" in formats:
                layered = export_language_layers(
                    export_project, directory, self.base_name,
                    tuple(layers) + (("json",) if "json" in formats else ()),
                    translation_first=self.translation_first.isChecked(), speaker_mode=mode)
                formats -= {"srt", "json"}
            artifacts = list(layered.artifacts) if layered is not None else []
            if formats:
                artifacts += list(export_subtitle_artifacts(
                    export_project, directory, self.base_name, SubtitleExportOptions(frozenset(formats), mode)))
        except Exception as exc:
            published = list(layered.artifacts) if layered is not None else []
            published.extend(getattr(exc, "published", ()))
            self.artifacts = tuple(published)
            partial = ("已写入：" + "、".join(a.path.name for a in published) + "。其余文件未全部完成。\n") if published else ""
            summary = partial + str(exc)
            self._error_details = partial + (exc.details() if callable(getattr(exc, "details", None)) else traceback.format_exc())
            self.warning.setTextFormat(Qt.TextFormat.PlainText)
            bind_text(self.warning, '导出字幕失败：{error}', error=summary)
            self.warning.show()
            self.error_details_button.show()
            self._refresh_preview()
            return
        self.artifacts = tuple(artifacts)
        self.result_reason = reason
        bind_text(self.done_title, "已导出并检查 {count} 个文件", count=len(self.artifacts))
        notes = [tr(reason)]
        if layered is not None and layered.missing_translation_count:
            notes.append(tr("{count} 条没有译文：译文文件跳过，双语保留原文", count=layered.missing_translation_count))
        if layered is not None and layered.needs_update_count:
            notes.append(tr("{count} 条译文需要更新", count=layered.needs_update_count))
        self.done_note.setText(" · ".join(notes))
        self.done_files.set_files([artifact.path.name for artifact in self.artifacts],
                                  header=tr("已写入并回读检查："))
        folder = self.artifacts[0].path.parent if self.artifacts else Path(directory)
        self.done_path.set_path(str(folder))
        # The result is shorter than the choices: drop the choices page so the
        # dialog can shrink to the result (the format cards' height-for-width
        # would otherwise keep the old height).
        self.pages.setCurrentWidget(self.done_page)
        self.pages.removeWidget(self.setup_page)
        QTimer.singleShot(0, lambda: self.resize(self.width(), self.sizeHint().height()))
        self.open_folder_button.setDefault(True)
        self.open_folder_button.setFocus()

    def _show_error_details(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("字幕导出错误详情")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        note = QLabel("详情可能含字幕原文，仅保留在本机；请自行决定是否复制并提供。")
        note.setWordWrap(True)
        layout.addWidget(note)
        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(self._error_details)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_button = buttons.addButton("复制详情", QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._error_details))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _open_result_folder(self) -> None:
        from .subtitle_export_widgets import open_folder
        open_folder(self.done_path.path_label.path())

    def _copy_paths(self) -> None:
        QApplication.clipboard().setText("\n".join(str(item.path.resolve()) for item in self.artifacts))
        bind_text(self.done_note, "已复制 {count} 个字幕路径", count=len(self.artifacts))


def _clock(milliseconds: int, millis: bool = False) -> str:
    value = max(0, int(milliseconds))
    hours, value = divmod(value, 3_600_000)
    minutes, value = divmod(value, 60_000)
    seconds, ms = divmod(value, 1000)
    if millis:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _speed(value: object) -> float:
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", str(value or ""))
    return float(match.group()) if match else 0.0


class ExportTimelineSlider(QSlider):
    """Absolute click/drag timeline with an explicit In/Out range overlay."""

    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._range_start = self.minimum()
        self._range_end = self.maximum()

    def set_range_points(self, start: int, end: int) -> None:
        self._range_start, self._range_end = int(start), int(end)
        self.update()

    def _value_at(self, x: float) -> int:
        # The painted track leaves 7 px at each end for the range handles.
        ratio = max(0.0, min(1.0, (float(x) - 7) / max(1, self.width() - 15)))
        return self.minimum() + round(ratio * (self.maximum() - self.minimum()))

    def _seek_mouse(self, event: QMouseEvent) -> None:
        value = self._value_at(event.position().x())
        self.setValue(value)
        self.setToolTip(_clock(value, True))
        self.seek_requested.emit(value)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._seek_mouse(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_mouse(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def set_theme(self, theme: ThemeDefinition) -> None:
        """Colours of the soft track (design A): a filled groove, the export
        range as an accent wash with end handles, the playhead in ink."""
        from ..design.ui_theme import blend_hex
        light = theme.is_light
        self._colors = {
            "track": QColor(blend_hex(theme.surface, theme.text, 0.13 if light else 0.2)),
            "range": QColor(blend_hex(theme.surface, theme.accent, 0.26 if light else 0.38)),
            "accent": QColor(theme.accent),
            "edge": QColor(theme.surface),
            "head": QColor(theme.text),
        }
        self.update()

    def paintEvent(self, event) -> None:
        colors = getattr(self, "_colors", None)
        if colors is None:
            self.set_theme(_workspace_theme())
            colors = self._colors
        span = max(1, self.maximum() - self.minimum())
        inset = 7
        usable = max(1, self.width() - 1 - inset * 2)
        x_of = lambda value: inset + round((value - self.minimum()) / span * usable)
        middle = self.height() / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["track"])
        painter.drawRoundedRect(QRectF(inset, middle - 3, usable, 6), 3, 3)
        whole = self._range_start <= self.minimum() and self._range_end >= self.maximum()
        if not whole:
            left, right = x_of(self._range_start), x_of(self._range_end)
            painter.setBrush(colors["range"])
            painter.setPen(colors["accent"])
            painter.drawRoundedRect(QRectF(left, middle - 7, max(2, right - left), 14), 5, 5)
            painter.setPen(colors["edge"])
            painter.setBrush(colors["accent"])
            for x in (left, right):
                painter.drawRoundedRect(QRectF(x - 5, middle - 12, 10, 24), 4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["head"])
        head = x_of(self.value())
        painter.drawRoundedRect(QRectF(head - 1.5, middle - 14, 3, 28), 1.5, 1.5)
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), 36)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), 36)


class StudioExportWorkspace(QWidget):
    """A four-state Export surface that reuses Studio's one mpv canvas."""

    back_requested = Signal()
    render_succeeded = Signal(str)
    render_failed = Signal(str)
    render_cancelled = Signal()
    progress_updated = Signal(int, dict)
    trace_line = Signal(str)
    renderer_install_finished = Signal(bool, str)
    run_event = Signal(int, str, object)

    def __init__(self, project: SubtitleProject, ass_path: str, project_path: str | Path | None = None,
                 parent=None, preview_widget: QWidget | None = None):
        super().__init__(parent)
        self.project, self.ass_path = project, str(ass_path)
        self.project_path = Path(project_path).resolve() if project_path else None
        self.ffmpeg = ffmpeg_tool()
        self._updating_export_controls = False
        self._settings = QSettings("2ByteASR", "2ByteASR")
        try:
            self._saved_export_preferences = json.loads(str(self._settings.value('render/preferences_v1', '{}')))
        except (ValueError, TypeError):
            self._saved_export_preferences = {}
        if not isinstance(self._saved_export_preferences, dict):
            self._saved_export_preferences = {}
        overrides = project.render_settings.get('export_preferences', {})
        if isinstance(overrides, dict):
            self._saved_export_preferences.update(overrides)
        self._cancelled, self._running = threading.Event(), False
        self._released = False
        self._run_generation = 0
        self._worker, self._last_job = None, None
        self._last_failure, self._started_at, self._last_preview_sync_ms = "", 0.0, -10_000
        self._preview_volume_before_export = None
        self._preview_widget = preview_widget
        self._preview_signals_connected = False
        origin_parent = preview_widget.parentWidget() if preview_widget else None
        self._preview_origin_parent = origin_parent
        self._preview_origin_layout = origin_parent.layout() if origin_parent else None
        self._preview_origin_index = self._preview_origin_layout.indexOf(preview_widget) if self._preview_origin_layout else -1
        self._preview_origin_cell = (
            self._preview_origin_layout.getItemPosition(self._preview_origin_index)
            if self._preview_origin_index >= 0 and hasattr(self._preview_origin_layout, "getItemPosition")
            else None
        )
        self.setObjectName("studioExportWorkspace")
        self._compact_layout = None
        try:
            self._build()
        except BaseException:
            self.release_preview()
            self.deleteLater()
            raise
        # Polish the complete subtree once, just like a later palette refresh.
        self._apply_workspace_theme()
        self._apply_responsive_layout()
        self.render_succeeded.connect(self._show_success)
        self.render_failed.connect(self._show_failure)
        self.render_cancelled.connect(self._show_cancelled)
        self.progress_updated.connect(self._apply_progress)
        self.trace_line.connect(self._append_running_log)
        self.renderer_install_finished.connect(self._renderer_install_done)
        self.run_event.connect(self._receive_run_event)
        self._update_range()
        self._progress_target = 0
        self._progress_display = 0.0
        self._progress_payload = {}
        self._progress_indeterminate = True
        self._progress_clock = QTimer(self)
        self._progress_clock.setInterval(80)
        self._progress_clock.timeout.connect(self._tick_progress)
        self._preview_lock = threading.Lock()
        self._pending_export_preview = None
        self._advanced_route = False

    def _apply_workspace_theme(self) -> None:
        """One token-driven sheet for the whole export surface (never warm)."""
        theme = _workspace_theme()
        local = build_secondary_surface_qss(theme) + _export_workspace_qss(theme) + export_setup_qss(theme)
        if hasattr(self, "preview_scrub"):
            self.preview_scrub.set_theme(theme)
        app = QApplication.instance()
        # A detached workspace inherits the application root typography on
        # first Show. Keep that same base when its palette is refreshed.
        if self.parentWidget() is None and app is not None:
            self._theme_root_local_sheet = local
            self._theme_root_sheet = getattr(app, '_theme_window_qss', '') + local
            self.setStyleSheet(self._theme_root_sheet)
        else:
            self.setStyleSheet(local)

    def refresh_theme_palette(self) -> None:
        self._apply_workspace_theme()
        if hasattr(self, "preview_panel"):
            self._refresh_card_icons()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()
        if hasattr(self, 'render_body'):
            self.render_body.setOrientation(Qt.Vertical if self.width() < 850 else Qt.Horizontal)

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "settings_scroll") or not hasattr(self, "preview_scroll"):
            return
        compact = self.width() < 1180 or self.height() < 680
        if self._compact_layout is compact:
            return
        self._compact_layout = compact
        if compact:
            self.settings_scroll.setMinimumWidth(360)
            self.settings_scroll.setMaximumWidth(460)
            self.preview_scroll.setMinimumWidth(380)
            self.preview_host.setMinimumSize(360, 203)
            self.preview_host.setMaximumSize(640, 360)
            self._size_actions(130, 170)
            self.splitter.setSizes([400, max(420, self.width() - 408)])
        else:
            self.settings_scroll.setMinimumWidth(480)
            self.settings_scroll.setMaximumWidth(680)
            self.preview_scroll.setMinimumWidth(520)
            self.preview_host.setMinimumSize(520, 292)
            self.preview_host.setMaximumSize(820, 410)
            self._size_actions(170, 220)
            self.splitter.setSizes([560, 980])

    def _size_actions(self, queue: int, export: int) -> None:
        """At least these widths; a longer language (Russian) widens them."""
        for button, width in ((self.queue_button, queue), (self.export_button, export)):
            button.setFixedHeight(46)
            button.setMinimumWidth(width)
            button.setMaximumWidth(16777215)
            button.resize(max(width, button.sizeHint().width()), 46)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "preview_scroll", None) and event.type() == QEvent.Type.Resize:
            self._fit_range_row(watched.width())
        return super().eventFilter(watched, event)

    def _fit_range_row(self, width: int) -> None:
        """Range choice and in / out points share a row only when both fit."""
        grid = getattr(self, "_range_grid", None)
        if grid is None:
            return
        margins = self.preview_panel.layout().contentsMargins()
        needed = (self.export_range_choice.minimumWidth() + grid.horizontalSpacing()
                  + self.project_range_bar.minimumSizeHint().width() + margins.left() + margins.right() + 12)
        stacked = width < needed
        if getattr(self, "_range_stacked", None) is stacked:
            return
        self._range_stacked = stacked
        for widget in (self.export_range_choice, self.project_range_bar):
            grid.removeWidget(widget)
        if stacked:
            grid.addWidget(self.export_range_choice, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(self.project_range_bar, 1, 0, 1, 2)
        else:
            grid.addWidget(self.export_range_choice, 0, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(self.project_range_bar, 0, 1)

    def _export_trace(self, event: str, value: object = None, **fields: object) -> None:
        record = {
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": str(event),
            **({"value": value} if value is not None else {}),
            **fields,
        }
        from ..diagnostics.event_bridge import legacy_event,technical
        from ..diagnostics.editor_diagnostics import safe
        legacy_event('video.export.'+str(event),record,module='exports',project_id=getattr(getattr(self,'project',None),'project_id',None))
        record=safe(technical(record))
        if not self._released:
            try:
                self.trace_line.emit(f"[{record['time']}] {record['event']}  {json.dumps(record, ensure_ascii=False, default=str)}")
            except RuntimeError:
                pass  # A released export may still be draining its own worker.

    def _combo(self, items) -> StudioComboBox:
        combo = field_width(StudioComboBox(), "compact", size="compact")
        for label, value in items:
            combo.addItem(label, value)
        return combo

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        from .export_success import ExportPages
        self.pages = ExportPages()
        self.pages.currentChanged.connect(self.pages.updateGeometry)
        root.addWidget(self.pages)
        self.setup_page = self._setup_page()
        self.exporting_page = self._exporting_page()
        self.success_page = self._success_page()
        self.failure_page = self._failure_page()
        for page in (self.setup_page, self.exporting_page, self.success_page, self.failure_page):
            self.pages.addWidget(page)
        # The Studio's 设置入点 / 设置出点 keys, rebinds included (2026-10-17: were I / O literals).
        from ..projects.project_range import text_input_focused
        from ..studio import shortcut_registry
        for command_id, callback in (("mark_in", self._set_in), ("mark_out", self._set_out)):
            shortcut = QShortcut(QKeySequence(), self)
            shortcut.activated.connect(lambda cb=callback: None if text_input_focused() else cb())
            setattr(self, f"_shortcut_{command_id}", shortcut)
        shortcut_registry.keep_keys({"mark_in": self._shortcut_mark_in, "mark_out": self._shortcut_mark_out})

    def _setup_page(self) -> QWidget:
        # 2026-10-23 design A (user-picked): output file / picture and encoding
        # cards, advanced encoding and subtitle-file export as fold rows, the
        # range on the preview's timeline, facts as pills under the preview.
        page = QWidget()
        page.setObjectName("exportSetupPage")
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(14)
        back = QPushButton()
        bind_text(back, "返回字幕工作台")
        back.setObjectName("exportBackButton")
        install_themed_icon(back, "fa5s.arrow-left", "secondary")
        back.clicked.connect(self._back)
        header.addWidget(back)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        title = self.setup_title = QLabel("导出字幕视频")
        title.setObjectName("exportPageTitle")
        title.setStyleSheet(f"font-size:23px;font-weight:{WEIGHT_SCALE['heavy']}")
        heading.addWidget(title)
        from ..design.elided_label import ElidedLabel
        self.export_context = ElidedLabel("", minimum=60, mode=Qt.TextElideMode.ElideRight)
        self.export_context.setObjectName("exportPageContext")
        heading.addWidget(self.export_context)
        header.addLayout(heading, 1)
        self.renderer_badge = QLabel()
        self.renderer_badge.setObjectName("exportRendererBadge")
        self.renderer_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header.addWidget(self.renderer_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)
        self._refresh_context()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(16)
        scroll = QScrollArea()
        self.settings_scroll = scroll
        scroll.setObjectName("exportSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(480)
        scroll.setMaximumWidth(680)
        settings = QWidget()
        settings.setObjectName("exportSettingsPage")
        scroll.viewport().setObjectName("exportSettingsViewport")
        column = QVBoxLayout(settings)
        column.setContentsMargins(0, 0, 8, 4)
        column.setSpacing(12)
        scroll.setWidget(settings)
        self._file_settings(column)
        self._video_settings(column)
        self._audio_settings(column)
        from .audio_export_ui import AudioExportControls
        self.audio_delivery = AudioExportControls(self)
        column.addWidget(self.audio_delivery)
        self._advanced_settings(column)
        self._subtitle_settings(column)
        column.addStretch(1)
        self.splitter.addWidget(scroll)
        self._preview_panel(self.splitter)
        self.splitter.setStretchFactor(0, 36)
        self.splitter.setStretchFactor(1, 64)
        self.splitter.setSizes([560, 980])
        root.addWidget(self.splitter, 1)
        footer_bar = QFrame()
        footer_bar.setObjectName("exportFooter")
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(14, 9, 10, 9)
        footer.setSpacing(12)
        output_icon = QLabel()
        output_icon.setObjectName("exportOutputIcon")
        output_icon.setFixedSize(30, 30)
        output_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        output_icon.setProperty("iconName", "fa5s.folder")
        footer.addWidget(output_icon)
        self.status = QLabel()
        self.status.setObjectName("exportOutputPath")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        # Export actions stay reachable even when either column must scroll.
        footer.addLayout(self._export_actions)
        root.addWidget(footer_bar)
        self._refresh_card_icons(page)
        QTimer.singleShot(0, self._restore_export_preferences)
        return page

    # Icon per settings card (titles stay the translated card titles).
    _CARD_ICONS = {
        "输出文件": "fa5s.file-video", "画面与编码": "fa5s.film",
    }

    def _card(self, title: str, meta: str = "") -> tuple[QFrame, QVBoxLayout, QLabel]:
        """A settings card: icon, title and a quiet note on the right."""
        from ..design.elided_label import ElidedLabel
        card = QFrame()
        card.setProperty("exportCard", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(10)
        icon = QLabel()
        icon.setObjectName("exportCardIcon")
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setProperty("iconName", self._CARD_ICONS.get(title, "fa5s.circle"))
        caption = QLabel()
        caption.setObjectName("exportCardTitle")
        bind_text(caption, title)
        note = ElidedLabel("", minimum=40, mode=Qt.TextElideMode.ElideRight)
        note.setObjectName("exportCardMeta")
        note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if meta:
            bind_text(note, meta)
        head.addWidget(icon)
        head.addWidget(caption)
        head.addSpacing(8)
        head.addWidget(note, 1)
        layout.addLayout(head)
        return card, layout, note

    def _refresh_context(self) -> None:
        media = self.project.media
        name = Path(media.path).name if media.path else str(media.display_name or "")
        bind_text(self.export_context, join_text([name, _clock(self._duration_ms(), True),
                                                  tr("{count} 条字幕", count=len(self.project.cues))]))

    def _refresh_card_icons(self, root: QWidget | None = None) -> None:
        import qtawesome as qta
        theme = _workspace_theme()
        root = root or self
        for name in ("exportCardIcon", "exportOutputIcon"):
            for icon in root.findChildren(QLabel, name):
                icon.setPixmap(qta.icon(str(icon.property("iconName") or "fa5s.circle"),
                                        color=theme.accent_text).pixmap(QSize(15, 15)))

    def _file_settings(self, layout: QVBoxLayout) -> None:
        group, form, _note = self._card("输出文件", "前缀、后缀和位置会记住")
        self.file_card = group
        self.output_kind = self._combo((("影片", "video"), ("音频", "audio")))
        from .audio_export_ui import change_mode
        self.output_kind.currentIndexChanged.connect(lambda: change_mode(self))
        # 影片 / 音频 sits in the card's title row: a row of its own pushed the
        # left column past the window, and design A keeps it without scrolling.
        self.output_kind_choice = SegmentedControl(self.output_kind)
        self.output_kind_choice.setProperty("tone", "soft")
        self.output_kind_choice.setMinimumWidth(120)
        self.output_kind_choice.setMaximumWidth(170)
        bind_text(self.output_kind_choice, "导出类型", property='toolTip')
        bind_text(self.output_kind_choice, "导出类型", property='accessibleName')
        form.itemAt(0).layout().addWidget(self.output_kind_choice, 0, Qt.AlignmentFlag.AlignVCenter)
        from .export_preferences import clean_affix
        assets = {a.canonical_source for a in self.project.media_pool}
        stem = str(self.project.studio_state.get('project_name') or (self.project_path.stem if self.project_path else '字幕视频')) if len(assets) > 1 else Path(self.project.media.path).stem
        suffix = clean_affix(self._saved_export_preferences.get('suffix', self._settings.value('render/export_suffix', '')))
        try:
            affix_values = json.loads(str(self._settings.value('render/affixes_v1', '{}')))
        except (ValueError, TypeError):
            affix_values = {}
        if not isinstance(affix_values, dict):
            affix_values = {}
        self._filename_source = str(self.project_path or self.project.media.path)
        if affix_values.get('base_source') == self._filename_source:
            stem = str(affix_values.get('base', stem))
        self.filename = field_width(QLineEdit(stem), "expanding", size="compact")
        self.filename.textChanged.connect(self._target_changed)
        self.filename.editingFinished.connect(self._save_affix_preferences)
        from .export_affix import ExportAffixCombo
        self.filename_prefix = ExportAffixCombo(
            str(affix_values.get('prefix', self._saved_export_preferences.get('prefix', ''))),
            affix_values.get('prefix_history', []), '前缀')
        self.filename_suffix = ExportAffixCombo(
            str(affix_values.get('suffix', suffix)), affix_values.get('suffix_history', []), '后缀')
        for widget, short, hint in ((self.filename_prefix, '前缀', '前缀，可留空'),
                                    (self.filename_suffix, '后缀', '后缀，可留空')):
            # Short words inside the chip; the whole hint on hover.
            bind_text(widget.lineEdit(), short, property='placeholderText')
            bind_text(widget, hint, property='toolTip')
            widget.currentTextChanged.connect(self._target_changed)
            widget.confirmed.connect(self._save_affix_preferences)
        self.filename_extension = QLabel(".mp4")
        form.addWidget(name_well(self.filename_prefix, self.filename, self.filename_suffix, self.filename_extension))
        # The whole name stays readable for checks; the well and the footer show it.
        self.complete_name_preview = QLabel()
        self.complete_name_preview.setWordWrap(True)
        self.complete_name_preview.hide()
        form.addWidget(self.complete_name_preview)
        fallback = self.project_path.parent / "exports" if self.project_path else Path(self.project.media.path).parent
        saved = str(self._saved_export_preferences.get('directory') or self._settings.value("render/last_export_directory", "") or "")
        valid_saved = bool(saved and Path(saved).is_dir() and _directory_is_writable(Path(saved)))
        self.directory = field_width(QLineEdit(saved if valid_saved else str(fallback)), "expanding", size="compact")
        if saved and not valid_saved:
            bind_text(self.directory, '上次保存目录不存在或不可写，已回退到工程导出目录。', property='toolTip')
        self.directory.textChanged.connect(self._target_changed)
        choose = QPushButton()
        choose.setObjectName("exportChooseFolder")
        choose.setFixedSize(46, 46)
        install_themed_icon(choose, "fa5s.folder-open", "secondary")
        bind_text(choose, "选择…", property='toolTip')
        bind_text(choose, "选择…", property='accessibleName')
        choose.clicked.connect(self._choose_directory)
        self.extension = self._combo((("MP4", "mp4"), ("MKV", "mkv"), ("MOV", "mov"), ("WebM / AV1", "webm")))
        self.extension.currentIndexChanged.connect(self._container_changed)
        # Segments while they fit; the same dropdown in a narrow column.
        self.extension_choice = SegmentedControl(self.extension)
        self.extension_choice.setProperty("tone", "soft")
        self.extension_choice.setMaximumWidth(230)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(captioned("保存位置", self.directory, role="expanding"), 3)
        row.addWidget(choose)
        row.addWidget(self.extension_choice, 2, Qt.AlignmentFlag.AlignVCenter)
        form.addLayout(row)
        layout.addWidget(group)

    def _subtitle_settings(self, layout: QVBoxLayout) -> None:
        self.subtitle_export_button = QPushButton()
        bind_text(self.subtitle_export_button, "导出字幕")
        self.subtitle_export_button.setObjectName("studioButton")
        self.subtitle_export_button.setProperty("exportTone", "tint")
        self.subtitle_export_button.setProperty("exportSize", "sm")
        install_themed_icon(self.subtitle_export_button, "fa5s.closed-captioning", "accent")
        self.subtitle_export_button.clicked.connect(self._export_subtitles)
        # Folded unless it was left open last time.
        opened = str(self._settings.value("subtitle/export_fold_open", "false")).lower() == "true"
        group = self.subtitle_file_group = self.subtitle_card = FoldCard("只导出字幕文件", expanded=opened,
                                              trailing=self.subtitle_export_button)
        group.toggled.connect(lambda shown: self._settings.setValue("subtitle/export_fold_open", bool(shown)))
        group.layout().setContentsMargins(16, 10, 12, 10)
        column = group.body_layout
        column.setSpacing(10)
        hint = QLabel("独立导出字幕文件，不会同时启动视频压制。")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        column.addWidget(hint)

        # Each choice under a small label; its items wrap in a narrow column
        # or a longer interface language instead of widening the page.
        self.subtitle_format_checks = {}
        format_flow = self._subtitle_group(column, "格式")
        for label, format_name, checked in (
            ("SRT", "srt", True),
            ("ASS", "ass", False),
            ("TXT", "txt", False),
            ("JSON", "json", False),
        ):
            check = QCheckBox()
            check.setChecked(checked)
            check.setProperty("formatLabel", label)
            # The native indicator is the single source of checkbox state;
            # drawing an extra Unicode box in the label creates a double
            # indicator on Windows themes.
            check.setText(label)
            check.toggled.connect(self._refresh_subtitle_summary)
            self.subtitle_format_checks[format_name] = check
            format_flow.addWidget(check)

        # Language layers (shown when the project has translations): original,
        # translation (any target language), and both in one cue (two lines).
        self.subtitle_language_row = QWidget()
        language_column = QVBoxLayout(self.subtitle_language_row)
        language_column.setContentsMargins(0, 0, 0, 0)
        language_column.setSpacing(6)
        self.subtitle_language_label = QLabel("语言")
        self.subtitle_language_label.setObjectName("exportFieldLabel")
        language_column.addWidget(self.subtitle_language_label)
        language_host = QWidget()
        language_flow = WrapLayout(language_host, spacing=12, fill=False)
        language_column.addWidget(language_host)
        self.subtitle_language_checks = {}
        for label, layer, checked in (("原文", "original", True), ("译文", "translation", True),
                                      ("双语（同一条两行）", "bilingual", True)):
            check = QCheckBox()
            check.setChecked(checked)
            bind_text(check, label)
            self.subtitle_language_checks[layer] = check
            language_flow.addWidget(check)
        self.subtitle_translation_first = QCheckBox()
        bind_text(self.subtitle_translation_first, "双语译文在上")
        self.subtitle_translation_first.setProperty("softSwitch", True)
        self.subtitle_translation_first.setChecked(True)
        language_flow.addWidget(self.subtitle_translation_first)
        self.subtitle_language_row.setVisible(has_translations(self.project))
        column.addWidget(self.subtitle_language_row)

        self.subtitle_speaker_group = QButtonGroup(self)
        self.subtitle_speaker_modes = {}
        speaker_track = self._choice_track()
        self._subtitle_group(column, "说话人", speaker_track)
        for label, mode, checked in (
            ("合并", "combined", True),
            ("分别导出", "per_speaker", False),
            ("两者", "both", False),
        ):
            radio = QRadioButton()
            radio.setChecked(checked)
            radio.setProperty("modeLabel", label)
            radio.setText(label)
            radio.toggled.connect(self._refresh_subtitle_summary)
            self.subtitle_speaker_group.addButton(radio)
            self.subtitle_speaker_modes[mode] = radio
            speaker_track.layout().addWidget(radio)

        self.subtitle_destination_group = QButtonGroup(self)
        self.subtitle_destination_modes = {}
        saved_mode = str(
            self._settings.value("subtitle/export_destination", "source") or "source"
        )
        if saved_mode not in {"source", "project", "custom"}:
            saved_mode = "source"
        destination_track = self._choice_track()
        self._subtitle_group(column, "保存位置", destination_track)
        for label, mode in (
            ("与源媒体同目录", "source"),
            ("工程 exports", "project"),
            ("自定义位置", "custom"),
        ):
            radio = QRadioButton(label)
            radio.setChecked(mode == saved_mode)
            radio.toggled.connect(
                lambda selected, selected_mode=mode: self._subtitle_destination_changed(
                    selected_mode if selected else ""
                )
            )
            self.subtitle_destination_group.addButton(radio)
            self.subtitle_destination_modes[mode] = radio
            destination_track.layout().addWidget(radio)

        self.subtitle_custom_directory = field_width(QLineEdit(
            str(self._settings.value("subtitle/custom_directory", "") or "")
        ), "expanding", size="compact")
        self.subtitle_custom_directory.setReadOnly(True)
        bind_text(self.subtitle_custom_directory, '尚未选择自定义文件夹', property='placeholderText')
        self.subtitle_custom_choose = QPushButton("选择文件夹")
        self.subtitle_custom_choose.setFixedHeight(46)
        self.subtitle_custom_choose.clicked.connect(self._choose_subtitle_custom_directory)
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.addWidget(captioned("自定义位置", self.subtitle_custom_directory, role="expanding"), 1)
        custom_row.addWidget(self.subtitle_custom_choose)
        self.subtitle_custom_host = QWidget()
        self.subtitle_custom_host.setLayout(custom_row)
        column.addWidget(self.subtitle_custom_host)

        action_row = QHBoxLayout()
        self.subtitle_export_status = QLabel()
        self.subtitle_export_status.setObjectName("cardMeta")
        self.subtitle_export_status.setWordWrap(True)
        column.addWidget(self.subtitle_export_status)
        action_row.addStretch(1)
        self.subtitle_open_folder = QPushButton("打开所在文件夹")
        self.subtitle_open_folder.setProperty("exportSize", "sm")
        self.subtitle_open_folder.clicked.connect(self._open_subtitle_export_folder)
        self.subtitle_open_folder.hide()
        action_row.addWidget(self.subtitle_open_folder)
        self.subtitle_copy_path = QPushButton("复制路径")
        self.subtitle_copy_path.setProperty("exportSize", "sm")
        self.subtitle_copy_path.clicked.connect(self._copy_subtitle_export_paths)
        self.subtitle_copy_path.hide()
        action_row.addWidget(self.subtitle_copy_path)
        column.addLayout(action_row)
        layout.addWidget(group)
        self._last_subtitle_artifacts = ()
        self._subtitle_destination_changed(saved_mode, persist=False)

    def _choice_track(self) -> QFrame:
        """A filled track whose radio buttons read as segments (they wrap
        onto a second line rather than widen a narrow column)."""
        track = QFrame()
        track.setObjectName("exportChoiceTrack")
        track.setContentsMargins(3, 3, 3, 3)
        WrapLayout(track, spacing=2, fill=True)
        return track

    def _subtitle_group(self, column: QVBoxLayout, title: str, content: QWidget | None = None):
        """A small label above one choice; returns the flow for loose items."""
        label = QLabel()
        label.setObjectName("exportFieldLabel")
        bind_text(label, title)
        column.addWidget(label)
        if content is not None:
            column.addWidget(content)
            return content.layout()
        host = QWidget()
        flow = WrapLayout(host, spacing=14, fill=False)
        column.addWidget(host)
        return flow

    def _refresh_subtitle_summary(self, *_args) -> None:
        if not hasattr(self, "subtitle_card") or not hasattr(self, "subtitle_destination_modes"):
            return
        formats = [control.property("formatLabel") for control in self.subtitle_format_checks.values()
                   if control.isChecked()]
        speaker = next((control for control in self.subtitle_speaker_modes.values() if control.isChecked()), None)
        destination = next((control for control in self.subtitle_destination_modes.values()
                            if control.isChecked()), None)
        parts = [" / ".join(formats) if formats else tr("至少选择一种字幕格式")]
        parts += [tr(str(control.property("modeLabel") or control.text())) for control in (speaker,) if control]
        parts += [tr(self._destination_source(control)) for control in (destination,) if control]
        self.subtitle_card.set_summary(join_text(parts))

    def _destination_source(self, control: QRadioButton) -> str:
        return next((label for mode, label in (("source", "与源媒体同目录"), ("project", "工程 exports"),
                                                ("custom", "自定义位置"))
                     if self.subtitle_destination_modes.get(mode) is control), control.text())

    def _selected_subtitle_destination_mode(self) -> str:
        return next(
            (
                mode for mode, control in self.subtitle_destination_modes.items()
                if control.isChecked()
            ),
            "source",
        )

    def _subtitle_destination_changed(self, mode: str, *, persist: bool = True) -> None:
        if not mode:
            return
        custom = mode == "custom"
        self.subtitle_custom_host.setVisible(custom)
        if persist:
            self._settings.setValue("subtitle/export_destination", mode)
        try:
            destination, reason = resolve_subtitle_export_destination(
                self.project,
                self.project_path,
                mode,
                self.subtitle_custom_directory.text(),
            )
        except (ValueError, PermissionError) as exc:
            self.subtitle_export_status.setText(str(exc))
        else:
            bind_text(self.subtitle_export_status, '{reason} · {destination}', reason=tr(reason), destination=destination)
        self._refresh_subtitle_summary()

    def _choose_subtitle_custom_directory(self) -> None:
        initial = self.subtitle_custom_directory.text().strip()
        if not initial:
            initial = str(Path(self.project.media.path).parent)
        path = QFileDialog.getExistingDirectory(self, tr('选择字幕保存文件夹'), initial)
        if not path:
            return
        self.subtitle_custom_directory.setText(path)
        self._settings.setValue("subtitle/custom_directory", path)
        self.subtitle_destination_modes["custom"].setChecked(True)
        self._subtitle_destination_changed("custom")

    def _export_subtitles(self) -> None:
        # The header button works while the card is folded: open it so the
        # result or the problem (and 打开所在文件夹 / 复制路径) is in view.
        self.subtitle_card.set_expanded(True)
        formats = frozenset(
            format_name
            for format_name, control in self.subtitle_format_checks.items()
            if control.isChecked()
        )
        if not formats:
            bind_text(self.subtitle_export_status, '至少选择一种字幕格式')
            return
        mode = next(
            (name for name, control in self.subtitle_speaker_modes.items() if control.isChecked()),
            "combined",
        )
        try:
            directory, destination_reason = resolve_subtitle_export_destination(
                self.project,
                self.project_path,
                self._selected_subtitle_destination_mode(),
                self.subtitle_custom_directory.text(),
            )
        except (ValueError, PermissionError) as exc:
            self.subtitle_export_status.setText(str(exc))
            return
        base_name = self.export_target().base_name
        self._confirm_affixes()
        self.subtitle_export_button.setEnabled(False)
        self.subtitle_open_folder.hide()
        self.subtitle_copy_path.hide()
        bind_text(self.subtitle_export_status, '正在写入并回读验证…')
        layered = None
        try:
            layers = [layer for layer, control in getattr(self, "subtitle_language_checks", {}).items()
                      if control.isChecked()] if not self.subtitle_language_row.isHidden() else []
            if layers and "srt" in formats:
                from .studio_subtitle_export import export_language_layers
                # Japanese / Chinese / bilingual SRT (+ JSON with both texts and word timing);
                # never overwrites an existing file.
                layered = export_language_layers(
                    self.project, directory, base_name,
                    tuple(layers) + (("json",) if "json" in formats else ()),
                    translation_first=self.subtitle_translation_first.isChecked(), speaker_mode=mode)
                formats = frozenset(formats - {"srt", "json"})
            artifacts = list(layered.artifacts) if layered is not None else []
            if formats:
                artifacts += list(export_subtitle_artifacts(
                    self.project,
                    directory,
                    base_name,
                    SubtitleExportOptions(formats, mode),
                ))
        except Exception as exc:
            bind_text(self.subtitle_export_status, '字幕导出失败：{value0}', value0=' '.join(str(exc).split())[:180])
            return
        finally:
            self.subtitle_export_button.setEnabled(True)
        self._last_subtitle_artifacts = artifacts
        self._settings.setValue(
            "subtitle/export_destination", self._selected_subtitle_destination_mode()
        )
        bind_text(self.subtitle_export_status, '已导出并验证 {value0} 个文件 · {destination_reason}', value0=len(artifacts), destination_reason=tr(destination_reason))
        if layered is not None and (layered.missing_translation_count or layered.needs_update_count):
            bind_text(self.subtitle_export_status,
                      '已导出并验证 {value0} 个文件 · {destination_reason} · {missing} 条没有译文：译文文件跳过，双语保留原文 · {stale} 条译文需要更新',
                      value0=len(artifacts), destination_reason=tr(destination_reason),
                      missing=layered.missing_translation_count, stale=layered.needs_update_count)
        self.subtitle_open_folder.show()
        self.subtitle_copy_path.show()

    def _open_subtitle_export_folder(self) -> None:
        if not self._last_subtitle_artifacts:
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._last_subtitle_artifacts[0].path.parent.resolve()))
        )

    def _copy_subtitle_export_paths(self) -> None:
        if not self._last_subtitle_artifacts:
            return
        QApplication.clipboard().setText(
            "\n".join(str(item.path.resolve()) for item in self._last_subtitle_artifacts)
        )
        bind_text(self.subtitle_export_status, '已复制 {value0} 个字幕路径', value0=len(self._last_subtitle_artifacts))

    def _video_settings(self, layout: QVBoxLayout) -> None:
        group, form, self.picture_note = self._card("画面与编码")
        self.video_group = self.picture_card = group
        self.preset = field_width(StudioComboBox(), "preferred", size="compact")
        self._reload_preset_combo()
        persisted = str(self._settings.value("render/preset", "recommended") or "recommended")
        index = self.preset.findData(persisted)
        self.preset.setCurrentIndex(max(0, index))
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.preset_chips = PresetChips(self.preset)
        self.preset.setParent(self.preset_chips)
        self.preset.hide()
        self.preset_menu_button = QToolButton()
        self.preset_menu_button.setObjectName("exportPresetMenu")
        install_themed_icon(self.preset_menu_button, "fa5s.ellipsis-h", "secondary")
        bind_text(self.preset_menu_button, '管理导出预设', property='accessibleName')
        bind_text(self.preset_menu_button, '管理预设：保存、另存为、删除', property='toolTip')
        self.preset_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        preset_menu = QMenu(self.preset_menu_button)
        preset_menu.addAction("保存预设", self._save_current_preset)
        preset_menu.addAction("另存为…", self._save_preset_as)
        preset_menu.addSeparator()
        preset_menu.addAction("删除自定义预设", self._delete_user_preset)
        self.preset_menu_button.setMenu(preset_menu)
        # The menu rides at the end of the chips and wraps with them.
        self.preset_chips.set_trailing(self.preset_menu_button)
        form.addWidget(self.preset_chips)
        self.codec = self._combo((("H.264", "h264"), ("HEVC / H.265", "hevc"), ("AV1", "av1")))
        self._apply_codec_capabilities()
        self.codec.currentIndexChanged.connect(self._codec_changed)
        self.quality = self._combo((("推荐", "recommended"), ("高质量", "high"), ("极高质量", "very_high"),
                                   ("体积优先", "size"), ("自定义", "custom")))
        self.quality.currentIndexChanged.connect(self._quality_changed)
        # The quality hint is the note on the right of the card title.
        self.quality_hint = self.picture_note
        resolutions = [("跟随源视频", (0, 0))]
        source_h = int(self.project.media.height or 0)
        for width, height in ((3840, 2160), (2560, 1440), (1920, 1080), (1280, 720)):
            if not source_h or height <= max(1080, source_h):
                resolutions.append((f"{width} × {height}", (width, height)))
        resolutions.append(("自定义", (-1, -1)))
        self.resolution = self._combo(resolutions)
        self.resolution.currentIndexChanged.connect(self._resolution_changed)
        self.fps = self._combo((("源帧率", 0.0), ("60 fps", 60.0), ("30 fps", 30.0), ("24 fps", 24.0), ("自定义", -1.0)))
        self.fps.currentIndexChanged.connect(self._fps_changed)
        grid = self._picture_grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(captioned("编码", self.codec), 0, 0)
        grid.addWidget(captioned("分辨率", self.resolution), 0, 1)
        grid.addWidget(captioned("帧率", self.fps), 0, 2)
        grid.addWidget(captioned("质量", self.quality), 1, 0, 1, 2)
        for column_index in range(3):
            grid.setColumnStretch(column_index, 1)
        form.addLayout(grid)
        self.custom_resolution_width = QSpinBox(); self.custom_resolution_width.setRange(160, 7680); self.custom_resolution_width.setValue(max(1920, int(self.project.media.width or 0)))
        self.custom_resolution_height = QSpinBox(); self.custom_resolution_height.setRange(90, 4320); self.custom_resolution_height.setValue(max(1080, int(self.project.media.height or 0)))
        for spin in (self.custom_resolution_width, self.custom_resolution_height):
            field_width(spin, "numeric", size="compact")
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.custom_resolution_separator = QLabel("×")
        self.custom_resolution_separator.setObjectName("exportFieldLabel")
        self.custom_resolution_label = QLabel("自定义尺寸")
        size_pair = QWidget()
        size_row = QHBoxLayout(size_pair)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(6)
        size_row.addWidget(self.custom_resolution_width, 1)
        size_row.addWidget(self.custom_resolution_separator)
        size_row.addWidget(self.custom_resolution_height, 1)
        self.custom_resolution_host = captioned("", size_pair, label=self.custom_resolution_label)
        for spin in (self.custom_resolution_width, self.custom_resolution_height):
            spin.setMinimumWidth(0)
            spin.setMinimumHeight(FIELD_HEIGHT)
            spin.setMaximumHeight(FIELD_HEIGHT)
        self.custom_resolution_width.hide(); self.custom_resolution_height.hide(); self.custom_resolution_separator.hide(); self.custom_resolution_label.hide()
        self.custom_resolution_host.hide()
        self.custom_resolution_width.valueChanged.connect(self._target_changed); self.custom_resolution_height.valueChanged.connect(self._target_changed)
        self.custom_fps = QSpinBox(); self.custom_fps.setRange(1, 240); self.custom_fps.setValue(30); self.custom_fps.setSuffix(" fps")
        field_width(self.custom_fps, "numeric", size="compact")
        self.custom_fps.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.custom_fps_label = QLabel("自定义帧率")
        self.custom_fps_host = captioned("", self.custom_fps, label=self.custom_fps_label, role="numeric")
        self.custom_fps.hide(); self.custom_fps_label.hide(); self.custom_fps_host.hide(); self.custom_fps.valueChanged.connect(self._target_changed)
        extras = self._picture_extras = QHBoxLayout()
        extras.setSpacing(8)
        extras.addWidget(self.custom_resolution_host, 2)
        extras.addWidget(self.custom_fps_host, 1)
        form.addLayout(extras)
        # The range choice lives under the preview, beside the in / out points.
        self.export_range = self._combo((("整个视频", "all"), ("入点到出点", "in_out")))
        self.export_range.currentIndexChanged.connect(self._range_mode_changed)
        layout.addWidget(group)

    def _audio_settings(self, layout: QVBoxLayout) -> None:
        # Audio shares the picture card: one field in its grid, the AAC rate
        # beside the custom size / frame rate when AAC is chosen.
        self.video_audio_group = self.picture_card
        self.audio = self._combo((("直接复制", "copy"), ("AAC", "aac"), ("无音频", "none")))
        self.audio.currentIndexChanged.connect(self._audio_changed)
        self._picture_grid.addWidget(captioned("音频", self.audio), 1, 2)
        self.audio_bitrate = self._combo(tuple((f"{value} kbps", value) for value in (128, 192, 256, 320)))
        self.audio_bitrate.setCurrentIndex(1)
        self.audio_bitrate.currentIndexChanged.connect(self._target_changed)
        self.audio_bitrate_label = QLabel("AAC 码率")
        self.audio_bitrate_host = captioned("", self.audio_bitrate, label=self.audio_bitrate_label)
        self._picture_extras.addWidget(self.audio_bitrate_host, 1)
        self.audio_bitrate.hide(); self.audio_bitrate_label.hide(); self.audio_bitrate_host.hide()

    def _advanced_settings(self, layout: QVBoxLayout) -> None:
        self.advanced_card = FoldCard("高级编码", expanded=False)
        self.advanced_card.layout().setContentsMargins(16, 10, 16, 10)
        # The fold header is the old 高级设置 toggle and its body the old panel.
        self.advanced_button = self.advanced_card.header
        self.advanced_panel = self.advanced_card.body
        body = self.advanced_card.body_layout
        body.setSpacing(10)
        self.actual_encoder_hint = QLabel()
        self.actual_encoder_hint.setObjectName("cardMeta")
        self.actual_encoder_hint.setWordWrap(True)
        body.addWidget(self.actual_encoder_hint)
        self.encoder = field_width(StudioComboBox(), "preferred", size="compact"); self._populate_encoders()
        self.encoder.currentIndexChanged.connect(self._encoder_changed)
        self.encoder_preset = self._combo((("最快", "fastest"), ("快速", "fast"), ("均衡（推荐）", "balanced"),
                                           ("高质量", "quality"), ("最高质量", "best")))
        self.encoder_preset.setCurrentIndex(self.encoder_preset.findData("balanced"))
        self.encoder_preset.currentIndexChanged.connect(self._refresh_advanced_summary)
        pair = QHBoxLayout()
        pair.setSpacing(8)
        pair.addWidget(captioned("编码器", self.encoder, role="preferred"), 1)
        pair.addWidget(captioned("编码速度", self.encoder_preset), 1)
        body.addLayout(pair)
        self.rate_control = field_width(StudioComboBox(), "compact", size="compact")
        self.rate_control.currentIndexChanged.connect(self._rate_control_changed)
        self.rate_control_choice = SegmentedControl(self.rate_control)
        self.rate_control_choice.setProperty("tone", "soft")
        rate_row = QHBoxLayout()
        rate_row.setSpacing(10)
        rate_label = QLabel("质量控制方式")
        rate_label.setObjectName("exportFieldLabel")
        rate_row.addWidget(rate_label)
        rate_row.addWidget(self.rate_control_choice, 1)
        body.addLayout(rate_row)
        self.quality_value = QSpinBox(); self.quality_value.setRange(0, 63); self.quality_value.setValue(20)
        field_width(self.quality_value, "numeric", size="compact")
        self.quality_value_label = QLabel("质量")
        self.bitrate = QSpinBox(); self.bitrate.setRange(100, 200_000); self.bitrate.setValue(8000); self.bitrate.setSuffix(" kbps")
        field_width(self.bitrate, "numeric", size="compact")
        self.bitrate_label = QLabel("目标码率")
        self.max_bitrate = QSpinBox(); self.max_bitrate.setRange(100, 300_000); self.max_bitrate.setValue(12000); self.max_bitrate.setSuffix(" kbps")
        field_width(self.max_bitrate, "numeric", size="compact")
        self.max_bitrate_label = QLabel("最大码率")
        numbers = QHBoxLayout()
        numbers.setSpacing(8)
        for spin, label in ((self.quality_value, self.quality_value_label), (self.bitrate, self.bitrate_label),
                            (self.max_bitrate, self.max_bitrate_label)):
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            spin.valueChanged.connect(self._manual_encoding_changed)
            numbers.addWidget(captioned("", spin, label=label, role="numeric"), 1)
        body.addLayout(numbers)

        self.expert_card = FoldCard("专家编码设置", expanded=False)
        self.expert_card.layout().setContentsMargins(0, 2, 0, 0)
        self.expert_card.title.setProperty("nested", True)
        self.expert_button = self.expert_card.header
        self.expert_panel = self.expert_card.body
        self.profile = self._combo((("自动", ""), ("High", "high"), ("Main", "main")))
        bind_text(self.profile, '控制编码兼容性。通常保持自动即可。', property='toolTip')
        self.level = self._combo((("自动", ""), ("4.1", "4.1"), ("5.1", "5.1")))
        bind_text(self.level, '限制解码复杂度。除特殊播放设备外建议自动。', property='toolTip')
        self.pixel_format = self._combo((("yuv420p", "yuv420p"), ("yuv420p10le", "yuv420p10le")))
        bind_text(self.pixel_format, '影响颜色格式和兼容性。yuv420p 兼容性最好。', property='toolTip')
        self.gop = QSpinBox(); self.gop.setRange(0, 600); bind_text(self.gop, "自动", property='specialValueText')
        field_width(self.gop, "numeric", size="compact")
        self.gop.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        bind_text(self.gop, '关键帧间隔。一般无需手动修改。', property='toolTip')
        expert_grid = QGridLayout()
        expert_grid.setHorizontalSpacing(8)
        expert_grid.setVerticalSpacing(8)
        for index, (caption, field) in enumerate((("Profile", self.profile), ("Level", self.level),
                                                   ("Pixel Format", self.pixel_format), ("GOP", self.gop))):
            expert_grid.addWidget(captioned(caption, field), index // 2, index % 2)
        expert_grid.setColumnStretch(0, 1)
        expert_grid.setColumnStretch(1, 1)
        self.expert_card.body_layout.addLayout(expert_grid)
        for widget in (self.profile, self.level, self.pixel_format):
            widget.currentIndexChanged.connect(self._refresh_advanced_summary)
        self.gop.valueChanged.connect(self._refresh_advanced_summary)
        body.addWidget(self.expert_card)
        layout.addWidget(self.advanced_card)
        self._encoder_changed()

    def _refresh_advanced_summary(self, *_args) -> None:
        if not hasattr(self, "expert_card"):
            return
        encoder = self._resolved_encoder()
        mode = str(self.rate_control.currentData() or "crf")
        if mode in {"crf", "cq"}:
            control = f"{'CRF' if mode == 'crf' else 'CQ'} {self.quality_value.value()}"
        else:
            control = f"{mode.upper()} {self.bitrate.value()} kbps"
        if str(self.encoder.currentData() or "auto") == "auto":
            pattern = "{}（{}）" if current_language().startswith("zh") else "{} ({})"
            encoder = pattern.format(tr("自动"), encoder)
        self.advanced_card.set_summary(join_text([encoder, control, tr(self.encoder_preset.currentText())]))
        self.expert_card.set_summary(join_text([
            f"Profile {self.profile.currentText()}", f"Level {self.level.currentText()}",
            self.pixel_format.currentText(), f"GOP {self.gop.text()}"]))

    def _summary_box(self, layout: QVBoxLayout) -> None:
        group = QWidget()
        group.setObjectName("exportSummaryBox")
        box = QVBoxLayout(group)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.summary_chip_host = QWidget(group)
        self.summary_chips = WrapLayout(self.summary_chip_host, spacing=6, fill=False)
        box.addWidget(self.summary_chip_host)
        # The joined text stays the page's readable summary (checks read it).
        self.summary = QLabel(); self.summary.setWordWrap(True)
        self.summary.setObjectName("exportSummaryBody")
        self.summary.hide()
        box.addWidget(self.summary)
        self.estimated_size = QLabel(); self.estimated_size.setObjectName("exportEstimate")
        self.estimated_size.setWordWrap(True)
        box.addWidget(self.estimated_size)
        layout.addWidget(group)

    def _preview_panel(self, splitter: QSplitter) -> None:
        panel, layout = QFrame(), QVBoxLayout()
        self.preview_panel = panel
        panel.setObjectName("exportPreviewPanel")
        panel.setLayout(layout); layout.setContentsMargins(20, 16, 20, 18); layout.setSpacing(12)
        panel.setMinimumHeight(560)
        head = QHBoxLayout()
        head.setSpacing(10)
        title = self.preview_title = QLabel("导出预览"); title.setObjectName("exportCardTitle"); head.addWidget(title)
        head.addStretch(1)
        self.source_pill = QLabel()
        self.source_pill.setObjectName("exportSourcePill")
        bind_text(self.source_pill, "源是音频 · 黑色画面")
        self.source_pill.setVisible(source_is_audio_only(self.project))
        head.addWidget(self.source_pill)
        layout.addLayout(head)
        self.preview_host = QFrame(); self.preview_host.setObjectName("exportPreviewHost")
        self.preview_host.setMinimumSize(520, 292); self.preview_host.setMaximumSize(820, 410)
        self.preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_host_layout = QVBoxLayout(self.preview_host); self.preview_host_layout.setContentsMargins(0, 0, 0, 0)
        if self._preview_widget:
            self.preview_host_layout.addWidget(self._preview_widget); self._preview_widget.show()
            self._preview_widget.position_changed.connect(self._preview_position_changed)
            self._preview_widget.playback_state_changed.connect(self._preview_state_changed)
            self._preview_signals_connected = True
        else:
            self.preview = QLabel("当前视频预览\n播放器将在 Studio 中复用"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setObjectName("exportPreviewFallback")
            self.preview.setStyleSheet("color:#f8f5ee;padding:20px"); self.preview_host_layout.addWidget(self.preview); self._load_cover()
        layout.addWidget(self.preview_host, 0, Qt.AlignmentFlag.AlignHCenter)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.preview_play_button = QPushButton(); self.preview_play_button.clicked.connect(self._toggle_preview)
        self.preview_play_button.setObjectName("exportPlayButton")
        self.preview_play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_state_changed(True)
        self.preview_time = QLabel(_clock(0, True)); self.preview_time.setObjectName("exportPreviewTime")
        self.preview_scrub = ExportTimelineSlider(); self.preview_scrub.setRange(0, self._duration_ms())
        self.preview_scrub.seek_requested.connect(self._seek_preview)
        self.preview_scrub.valueChanged.connect(lambda value: self.preview_time.setText(_clock(value, True)))
        for widget in (self.preview_play_button, self.preview_time): controls.addWidget(widget)
        controls.addWidget(self.preview_scrub, 1)
        self.duration_label = QLabel(_clock(self._duration_ms(), True)); self.duration_label.setObjectName("exportPreviewTime")
        controls.addWidget(self.duration_label)
        layout.addLayout(controls)
        from .output_caption_layout import OutputCaptionLayoutPreview
        self.output_layout_preview = OutputCaptionLayoutPreview(panel)
        self.output_layout_preview.hide()
        layout.addWidget(self.output_layout_preview)
        # One row when wide; the choice above the points when narrow
        # (_apply_responsive_layout).
        range_row = self._range_grid = QGridLayout()
        range_row.setHorizontalSpacing(10)
        range_row.setVerticalSpacing(8)
        self.export_range_choice = SegmentedControl(self.export_range)
        self.export_range_choice.setProperty("tone", "soft")
        self.export_range_choice.setMinimumWidth(170)
        self.export_range_choice.setMaximumWidth(240)
        range_row.addWidget(self.export_range_choice, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        from ..studio.project_range_ui import ProjectRangeBar
        self.project_range_bar = ProjectRangeBar(lambda:self.project,
            lambda:self.preview_scrub.value(), self._seek_preview,
            getattr(self.parentWidget(),'undo_stack',None), self)
        self.project_range_bar.layout().setContentsMargins(0, 0, 0, 0)
        self.project_range_bar.layout().setSpacing(6)
        for field in self.project_range_bar.fields:
            field.setMinimumWidth(80)
        # Each point keeps its own width; spare room stays at the row's end.
        for segment in self.project_range_bar.findChildren(QFrame, "rangeSegment"):
            segment.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.project_range_bar.layout().addStretch(1)
        self.project_range_bar.changed.connect(self._update_range)
        range_row.addWidget(self.project_range_bar, 0, 1)
        range_row.setColumnStretch(1, 1)
        layout.addLayout(range_row)
        # The bar keeps writing its duration / problem line and owns 清除范围;
        # both sit on their own line here so the two points fit a narrow column.
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        for name in ("rangeStatus", "rangeClear"):
            widget = self.project_range_bar.findChild(QWidget, name)
            self.project_range_bar.layout().removeWidget(widget)
            widget.setParent(panel)
            status_row.addWidget(widget, 1 if name == "rangeStatus" else 0)
        layout.addLayout(status_row)
        # The bar's line already names a range problem; this one stays for
        # code that reads it.
        self.range_label = QLabel(); self.range_label.setObjectName("exportRangeLabel")
        self.range_label.setWordWrap(True)
        self.range_label.hide()
        layout.addWidget(self.range_label)
        rule = QFrame(); rule.setObjectName("exportRule"); rule.setFixedHeight(1)
        layout.addWidget(rule)
        self._summary_box(layout)
        layout.addStretch(1)
        cta = QHBoxLayout(); cta.setSpacing(10)
        self.queue_button = QPushButton("加入队列")
        self.queue_button.setObjectName("exportQueueButton")
        self.queue_button.setFixedHeight(46)
        self.queue_button.setMinimumWidth(170)
        self.queue_button.resize(170, 46)
        self.queue_button.clicked.connect(self._enqueue)
        cta.addWidget(self.queue_button)
        self.export_button = QPushButton("开始导出")
        self.export_button.setObjectName("exportStartButton")
        self.export_button.setFixedHeight(46)
        self.export_button.setMinimumWidth(220)
        self.export_button.resize(220, 46)
        self.export_button.setProperty("studioPrimary", True)
        button_role(self.export_button, "primary", size="large")
        install_themed_icon(self.export_button, "fa5s.file-export", "on_accent")
        self.export_button.clicked.connect(self._start)
        cta.addWidget(self.export_button)
        self._export_actions = cta
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setObjectName("exportPreviewScroll")
        self.preview_scroll.viewport().setObjectName("exportPreviewViewport")
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setWidget(panel)
        self.preview_scroll.installEventFilter(self)
        splitter.addWidget(self.preview_scroll)

    def _exporting_page(self) -> QWidget:
        page, layout = QWidget(), QVBoxLayout(); page.setLayout(layout); page.setObjectName("exportingPage")
        layout.setContentsMargins(18, 12, 18, 12); layout.setSpacing(8)
        header = QFrame(); header.setObjectName("exportRunningHeader")
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        header_layout = QHBoxLayout(header); header_layout.setContentsMargins(12, 8, 12, 8)
        header_copy = QHBoxLayout()
        title = self.processing_title = QLabel("正在压制字幕视频"); title.setStyleSheet('font-size:16px;font-weight:700')
        header_copy.addWidget(title)
        self.elapsed_label = QLabel("已用时 00:00")
        header_copy.addWidget(self.elapsed_label)
        header_layout.addLayout(header_copy, 1)
        self.render_percent = QLabel("…"); self.render_percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.render_percent.setMinimumWidth(52); self.render_percent.setStyleSheet('font-size:18px;font-weight:700')
        header_layout.addWidget(self.render_percent); layout.addWidget(header)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setFixedHeight(6); self.progress.setTextVisible(False); layout.addWidget(self.progress)
        stages = QHBoxLayout(); self.render_stage_labels = []
        self._stage_specs = [
            (STAGE_PREPARE_PROJECT, "准备工程"),
            (STAGE_COMPOSE_VIDEO, "视频轨合成"),
            (STAGE_PREPARE_SUBTITLES, "准备字幕"),
            (STAGE_ADVANCED_RENDER, "高级样式"),
            (STAGE_ENCODE, "视频编码"),
            (STAGE_MUX, "封装收尾"),
            (STAGE_VALIDATE, "验证与发布"),
        ]
        for _key, label in self._stage_specs:
            card = QLabel(f"○  {label}")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            card.setProperty("exportStage", True)
            card.setProperty("stageState", "waiting")
            stages.addWidget(card, 1); self.render_stage_labels.append(card)
        self.render_stage_labels[1].hide()
        self.render_stage_labels[3].hide()
        self._pipeline_stage_states = None
        layout.addLayout(stages)
        body = self.render_body = QSplitter(Qt.Orientation.Horizontal); body.setChildrenCollapsible(False)
        detail = QFrame(); detail.setMinimumWidth(260)
        detail_layout = QVBoxLayout(detail); detail_layout.setContentsMargins(0, 0, 8, 0)
        self.current_stage_title = QLabel("当前步骤  ·  准备工程")
        self.current_stage_title.setObjectName("exportCurrentStage")
        detail_layout.addWidget(self.current_stage_title)
        self.processing_time = QLabel("正在准备…"); self.processing_time.setWordWrap(True); self.processing_time.setStyleSheet("font-size:14px;font-weight:600"); detail_layout.addWidget(self.processing_time)
        self.processing_info = QLabel("正在解析工程、检查输入文件并准备字幕。编码器尚未开始。")
        self.processing_info.setWordWrap(True); self.processing_info.setObjectName("exportProcessingInfo"); detail_layout.addWidget(self.processing_info)
        self.processing_output = QLabel(); self.processing_output.setWordWrap(True); self.processing_output.setTextInteractionFlags(Qt.TextSelectableByMouse); self.processing_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); detail_layout.addWidget(self.processing_output)
        self.running_details_button = QToolButton(); bind_text(self.running_details_button, '▾ 运行详情'); self.running_details_button.setObjectName("exportRunningDetails"); self.running_details_button.setCheckable(True); self.running_details_button.setChecked(True); detail_layout.addWidget(self.running_details_button)
        self.running_log = QTextEdit(); self.running_log.setObjectName("exportRunningLog"); self.running_log.setReadOnly(True); self.running_log.setStyleSheet('font-size:13px'); self.running_log.document().setMaximumBlockCount(3000); detail_layout.addWidget(self.running_log, 1)
        self.running_details_button.toggled.connect(self._toggle_running_details)
        body.addWidget(detail)
        self.render_preview_host = QFrame(); self.render_preview_host.setObjectName("renderPreviewHost")
        self.render_preview_host.setMinimumSize(280, 180)
        pass  # renderPreviewHost styling lives in _export_workspace_qss
        self.render_preview_layout = QVBoxLayout(self.render_preview_host); self.render_preview_layout.setContentsMargins(0, 0, 0, 0)
        self.render_preview = ProcessedFrameView("正在准备当前处理画面")
        self.render_preview.setObjectName("renderPreviewFallback"); self.render_preview_layout.addWidget(self.render_preview, 1)
        self.render_preview_time = QLabel("等待首个处理帧")
        self.render_preview_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.render_preview_time.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.render_preview_layout.addWidget(self.render_preview_time)
        body.addWidget(self.render_preview_host); body.setStretchFactor(0, 1); body.setStretchFactor(1, 2); body.setSizes([360, 760]); layout.addWidget(body, 1)
        footer = QHBoxLayout(); footer.addStretch(1)
        cancel = QPushButton("安全取消"); cancel.clicked.connect(self._cancel_export); cancel.setMinimumSize(150, 42); footer.addWidget(cancel)
        layout.addLayout(footer); return page

    def _toggle_running_details(self, checked: bool) -> None:
        self.running_log.setVisible(bool(checked))
        (bind_text(self.running_details_button, '▾ 运行详情') if checked else bind_text(self.running_details_button, '▸ 运行详情'))

    def _append_running_log(self, text):
        bar = self.running_log.verticalScrollBar()
        position = bar.value()
        follow = position >= bar.maximum()-2
        self.running_log.append(text)
        bar.setValue(bar.maximum() if follow else position)

    def _success_page(self) -> QWidget:
        from .export_success import ExportSuccessPanel
        panel = ExportSuccessPanel(self._open_success_video, self._open_success_folder, self._back, self._return_to_settings)
        self.success_name, self.success_meta = panel.name, panel.elapsed
        self.open_video_button, self.open_folder_button = panel.play, panel.reveal
        return panel

    def _failure_page(self) -> QWidget:
        page, layout = QWidget(), QVBoxLayout(); page.setLayout(layout); page.setObjectName("exportFailurePage"); layout.setContentsMargins(60, 60, 60, 60); layout.addStretch(1)
        title = QLabel("无法开始导出"); title.setAlignment(Qt.AlignmentFlag.AlignCenter); title.setObjectName("exportFailureTitle"); title.setStyleSheet("font-size:29px;font-weight:800"); layout.addWidget(title)
        self.failure_reason = QLabel(); self.failure_reason.setAlignment(Qt.AlignmentFlag.AlignCenter); self.failure_reason.setWordWrap(True); layout.addWidget(self.failure_reason)
        row = QHBoxLayout(); row.addStretch(1)
        back, self.retry_button, self.install_renderer_button, self.details_button = QPushButton("返回设置"), QPushButton("重试"), QPushButton("安装渲染环境"), QToolButton()
        back.clicked.connect(self._return_to_settings); self.retry_button.clicked.connect(self._retry); self.retry_button.setProperty("studioPrimary", True)
        self.install_renderer_button.clicked.connect(self._install_renderer_environment)
        self.install_renderer_button.hide()
        bind_text(self.details_button, '查看详情'); self.details_button.setCheckable(True); self.details_button.toggled.connect(self._toggle_details)
        for button in (back, self.retry_button, self.install_renderer_button, self.details_button): row.addWidget(button)
        row.addStretch(1); layout.addLayout(row)
        self.details = QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumSize(900, 220); self.details.hide(); layout.addWidget(self.details, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1); return page

    def _duration_ms(self) -> int:
        return max(0, timeline_duration_ms(self.project))

    def _load_cover(self) -> None:
        from .audio_export_ui import is_audio
        if is_audio(self): return
        if self.project_path:
            cover = self.project_path.parent / "preview" / "project-cover.jpg"
            if cover.is_file(): self.preview.setPixmap(QPixmap(str(cover)).scaled(960, 540, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _preview_position_changed(self, seconds: float) -> None:
        if self._running or self.preview_scrub.isSliderDown(): return
        value = round(float(seconds) * 1000)
        host = self.parentWidget()
        if getattr(host,'_playback_mode','source') == 'mapped':
            from ..timeline.studio_sequence_mapper import source_to_timeline
            mapped = source_to_timeline(sequence_of(self.project),value,
                segment=host._mapped_sequence_segment())
            if mapped is None:return
            value = mapped.timeline_ms
        value = max(0, min(self._duration_ms(), value))
        self.preview_scrub.setValue(value); self.preview_time.setText(_clock(value, True))
        if hasattr(self, 'output_layout_preview'):
            self.output_layout_preview.set_time(value)

    def _preview_state_changed(self, paused: bool) -> None:
        # A round accent button: the icon shows the action, the name says it.
        install_themed_icon(self.preview_play_button, "fa5s.play" if paused else "fa5s.pause", "on_accent")
        self.preview_play_button.setIconSize(QSize(14, 14))
        label = '播放' if paused else '暂停'
        bind_text(self.preview_play_button, label, property='accessibleName')
        bind_text(self.preview_play_button, label, property='toolTip')

    def _toggle_preview(self) -> None:
        callback = getattr(self.parentWidget(), "_toggle_playback", None)
        if callable(callback): callback()

    def _scrub_preview(self) -> None:
        self._seek_preview(self.preview_scrub.value())

    def _seek_preview(self, milliseconds: int) -> None:
        callback = getattr(self.parentWidget(), "_seek", None)
        if callable(callback): callback(max(0, int(milliseconds)) / 1000.0)
        self.preview_time.setText(_clock(milliseconds, True))
        if hasattr(self, 'output_layout_preview'):
            self.output_layout_preview.set_time(milliseconds)

    def _set_in(self) -> None:
        if self._running or self.pages.currentWidget() is not self.setup_page: return
        self.project_range_bar.mark(0)

    def _set_out(self) -> None:
        if self._running or self.pages.currentWidget() is not self.setup_page: return
        self.project_range_bar.mark(1)

    def _clear_range(self) -> None:
        from ..projects.project_range import set_range
        set_range(self.project,None,None,getattr(self.parentWidget(),'undo_stack',None))
        self._update_range()

    @property
    def in_ms(self):
        from ..projects.project_range import effective_range
        return effective_range(self.project)[0]

    @property
    def out_ms(self):
        from ..projects.project_range import effective_range
        return effective_range(self.project)[1]

    def _update_range(self, *_args) -> None:
        if not hasattr(self, "preview_scrub"): return
        from ..projects.project_range import range_points, validated_range
        points = range_points(self.project)
        mode = 'all' if points == (None,None) else 'in_out'
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.export_range):
            self.export_range.setCurrentIndex(self.export_range.findData(mode))
        start, end = self.in_ms, self.out_ms
        self.preview_scrub.set_range_points(start, end)
        error = ''
        try:validated_range(self.project)
        except ValueError as exc:error=str(exc)
        if error:
            bind_text(self.range_label, error)
        else:
            bind_text(self.range_label, '入点 {start}  →  出点 {end} · 时长 {duration}', start=_clock(start, True), end=_clock(end, True), duration=_clock(end-start, True))
        choice = getattr(self, "export_range_choice", None)
        if choice is not None:
            choice.sync()
        for name in ('queue_button','export_button'):
            button=getattr(self,name,None)
            if button is not None:button.setEnabled(not error)
        self._target_changed()

    def _range_mode_changed(self, *_args):
        if not hasattr(self,'project_range_bar'):return
        if self.export_range.currentData() == 'all':self._clear_range()
        else:self._update_range()

    def _populate_encoders(self) -> None:
        if not hasattr(self, "encoder"): return
        self.encoder.clear(); self.encoder.addItem("自动", "auto")
        # Cache-only: the capability scan runs in the background and the
        # render worker does the authoritative probe at export time.
        choices = cached_encoder_choices(
            self.ffmpeg, str(self.codec.currentData() or "h264")
        ) or []
        for choice in choices:
            label = (
                "NVIDIA NVENC" if "nvenc" in choice else
                "Intel Quick Sync" if "qsv" in choice else
                "AMD AMF" if "amf" in choice else
                f"Software {choice.replace('lib', '')}"
            )
            self.encoder.addItem(label, choice)

    def _resolved_encoder(self) -> str:
        codec = str(self.codec.currentData() or "h264")
        selected = str(self.encoder.currentData() or "auto")
        if selected != "auto":
            return selected
        # Cache-only hint resolution: encoder_choices would probe FFmpeg
        # synchronously on the UI thread when the cache is cold.
        choices = cached_encoder_choices(self.ffmpeg, codec) or []
        software = {"h264": "libx264", "hevc": "libx265", "av1": "libaom-av1"}[codec]
        # 2026-10-28 (users: burning is slow and unsteady): "auto" took the
        # software encoder whenever it existed. The HEVC / AV1 presets are only
        # offered when a hardware encoder exists, yet ran libx265 / libaom-av1;
        # H.264 never used a verified NVENC. Now: the capability order
        # (hardware first, only encoders whose test encode passed; SVT-AV1
        # before libaom). H.264 takes NVENC only: measured on real 1080p60
        # game footage it is 2-4.6x faster than x264 medium at the same SSIM
        # (AUTO_NVENC_CQ_OFFSET); Quick Sync / AMF H.264 were not measured and
        # stay a manual choice. A hardware failure still falls back to software.
        if not choices:
            return software
        if codec == "h264":
            return next((name for name in choices if name.endswith("_nvenc")),
                        software if software in choices else choices[0])
        return choices[0]

    def _encoder_changed(self, *_args) -> None:
        if not hasattr(self, "rate_control"):
            return
        encoder = self._resolved_encoder()
        friendly = (
            "NVIDIA NVENC" if "nvenc" in encoder else
            "Intel Quick Sync" if "qsv" in encoder else
            "AMD AMF" if "amf" in encoder else
            f"Software {encoder.replace('lib', '')}"
        )
        bind_text(self.actual_encoder_hint, '当前将使用：{friendly}', friendly=friendly)
        previous = str(self.rate_control.currentData() or "")
        self.rate_control.blockSignals(True)
        self.rate_control.clear()
        choices = (
            (("恒定质量（CRF）", "crf"), ("目标码率", "target"), ("限制码率", "limited"))
            if encoder.startswith("lib")
            else (("恒定质量（CQ / CQP）", "cq"), ("可变码率（VBR）", "vbr"), ("恒定码率（CBR）", "cbr"))
        )
        for label, value in choices:
            self.rate_control.addItem(label, value)
        index = self.rate_control.findData(previous)
        self.rate_control.setCurrentIndex(index if index >= 0 else 0)
        self.rate_control.blockSignals(False)
        self._rate_control_changed()

    def _rate_control_changed(self, *_args) -> None:
        if not hasattr(self, "rate_control"):
            return
        if _args:
            self._mark_custom_export()
        mode = str(self.rate_control.currentData() or "crf")
        quality_visible = mode in {"crf", "cq"}
        bitrate_visible = mode in {"target", "limited", "vbr", "cbr"}
        max_visible = mode in {"limited", "vbr"}
        self.quality_value_label.setText("CRF" if mode == "crf" else "CQ / CQP")
        self.quality_value_label.setVisible(quality_visible); show_field(self.quality_value, quality_visible)
        (bind_text(self.bitrate_label, '码率') if mode == 'cbr' else bind_text(self.bitrate_label, '目标码率'))
        self.bitrate_label.setVisible(bitrate_visible); show_field(self.bitrate, bitrate_visible)
        self.max_bitrate_label.setVisible(max_visible); show_field(self.max_bitrate, max_visible)
        # The mode list is refilled with signals blocked: show the pick.
        if hasattr(self, "rate_control_choice"):
            self.rate_control_choice.sync()
        self._target_changed()

    def _mark_custom_export(self) -> None:
        if self._updating_export_controls:
            return
        if hasattr(self, 'quality'):
            self.quality.setCurrentIndex(max(0, self.quality.findData('custom')))
        if hasattr(self, 'preset'):
            previous = self.preset.blockSignals(True)
            self.preset.setCurrentIndex(max(0, self.preset.findData('custom')))
            self.preset.blockSignals(previous)
            if hasattr(self, 'preset_chips'):
                self.preset_chips.sync()

    def _manual_encoding_changed(self, *_args) -> None:
        self._mark_custom_export()
        self._target_changed()

    def _commit_export_fields(self) -> None:
        # QSpinBox's editor can hold a newer value than value() until focus leaves.
        for name in ('quality_value', 'bitrate', 'max_bitrate', 'custom_resolution_width',
                     'custom_resolution_height', 'custom_fps', 'gop'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.interpretText()

    def _apply_codec_capabilities(self) -> None:
        try: cached = load_encoder_capabilities(self.ffmpeg)
        except (OSError, RuntimeError, ValueError, TypeError): cached = None
        if not cached: return
        available = cached.get("available_by_codec", {})
        for index in range(self.codec.count()):
            codec = str(self.codec.itemData(index))
            item = self.codec.model().item(index)
            if item is not None and not available.get(codec, []):
                item.setEnabled(False)
                bind_text(item, '当前 FFmpeg / GPU 不支持', property='toolTip')

    def _codec_changed(self, *_args) -> None:
        if self.extension.currentData() == "webm" and self.codec.currentData() != "av1":
            self.codec.setCurrentIndex(self.codec.findData("av1")); return
        if self.extension.currentData() == "mov" and self.codec.currentData() == "av1": self.codec.setCurrentIndex(self.codec.findData("h264")); return
        self._populate_encoders(); self._encoder_changed(); self._target_changed()

    def _container_changed(self, *_args) -> None:
        from .audio_export_ui import is_audio
        if is_audio(self):
            self.audio_delivery.update_settings(); return
        if self.extension.currentData() == "webm":
            self.codec.setCurrentIndex(self.codec.findData("av1"))
            self.audio.setCurrentIndex(self.audio.findData("aac"))
        if self.extension.currentData() == "mov" and self.codec.currentData() == "av1": self.codec.setCurrentIndex(self.codec.findData("h264"))
        self._target_changed()

    def _audio_changed(self, *_args) -> None:
        visible = self.audio.currentData() == "aac"; show_field(self.audio_bitrate, visible); self.audio_bitrate_label.setVisible(visible); self._target_changed()

    def _resolution_changed(self, *_args) -> None:
        custom = (self.resolution.currentData() or (0, 0))[0] < 0
        self.custom_resolution_width.setVisible(custom); self.custom_resolution_height.setVisible(custom); self.custom_resolution_separator.setVisible(custom); self.custom_resolution_label.setVisible(custom)
        self.custom_resolution_host.setVisible(custom)
        self._target_changed()

    def _fps_changed(self, *_args) -> None:
        custom = float(self.fps.currentData() or 0.0) < 0
        show_field(self.custom_fps, custom); self.custom_fps_label.setVisible(custom); self._target_changed()

    def _preset_catalog(self) -> list[dict]:
        catalog = visible_product_presets(self.ffmpeg)
        catalog.extend(load_user_presets())
        return catalog

    def _reload_preset_combo(self, *, keep: str | None = None) -> None:
        current = keep or (str(self.preset.currentData() or "") if hasattr(self, "preset") else "")
        self.preset.blockSignals(True)
        self.preset.clear()
        for item in self._preset_catalog():
            self.preset.addItem(str(item.get("label") or item.get("id")), str(item.get("id")))
        index = self.preset.findData(current)
        self.preset.setCurrentIndex(max(0, index))
        self.preset.blockSignals(False)
        if hasattr(self, "preset_chips"):
            self.preset_chips.sync()

    def _preset_payload(self, preset_id: str) -> dict | None:
        return next((item for item in self._preset_catalog() if str(item.get("id")) == preset_id), None)

    def _capture_export_preset(self, preset_id: str, label: str) -> dict:
        self._commit_export_fields()
        resolution = self.resolution.currentData() or (0, 0)
        return {
            "id": preset_id,
            "label": label,
            "container": str(self.extension.currentData() or "mp4"),
            "codec": str(self.codec.currentData() or "h264"),
            "encoder": str(self.encoder.currentData() or "auto"),
            "quality_mode": str(self.rate_control.currentData() or "cq"),
            "quality": int(self.quality_value.value()),
            "bitrate_kbps": int(self.bitrate.value()),
            "max_bitrate_kbps": int(self.max_bitrate.value()),
            "custom_resolution_width": self.custom_resolution_width.value(),
            "custom_resolution_height": self.custom_resolution_height.value(),
            "custom_fps": self.custom_fps.value(),
            "preset_speed": str(self.encoder_preset.currentData() or "balanced"),
            "resolution": list(resolution) if isinstance(resolution, (list, tuple)) else [0, 0],
            "fps": float(self.fps.currentData() or 0.0),
            "audio_codec": str(self.audio.currentData() or "copy"),
            "audio_bitrate_kbps": int(self.audio_bitrate.currentData() or 192),
            "user": True,
        }

    def _apply_preset_payload(self, payload: dict) -> None:
        if not hasattr(self, "encoder"):
            return
        self._updating_export_controls = True
        try:
            self._apply_preset_controls(payload)
        finally:
            self._updating_export_controls = False
        self._target_changed()

    def _apply_preset_controls(self, payload: dict) -> None:
        self.extension.setCurrentIndex(max(0, self.extension.findData(payload.get("container", "mp4"))))
        self.codec.setCurrentIndex(max(0, self.codec.findData(payload.get("codec", "h264"))))
        self._populate_encoders()
        encoder = str(payload.get("encoder") or "auto")
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(encoder)))
        quality = int(payload['quality']) if payload.get('quality') is not None else 20
        if quality <= 17:
            self.quality.setCurrentIndex(max(0, self.quality.findData("high")))
        elif quality >= 26:
            self.quality.setCurrentIndex(max(0, self.quality.findData("size")))
        else:
            self.quality.setCurrentIndex(max(0, self.quality.findData("recommended")))
        if str(payload.get("id")) == "custom" or payload.get("user"):
            self.quality.setCurrentIndex(max(0, self.quality.findData("custom")))
        self.quality_value.setValue(quality)
        mode = str(payload.get('quality_mode') or 'cq')
        if self._resolved_encoder().startswith('lib') and mode == 'cq':
            mode = 'crf'
        index = self.rate_control.findData(mode)
        if index >= 0:
            self.rate_control.setCurrentIndex(index)
        if payload.get("bitrate_kbps"):
            self.bitrate.setValue(int(payload["bitrate_kbps"]))
        if payload.get('max_bitrate_kbps'):
            self.max_bitrate.setValue(int(payload['max_bitrate_kbps']))
        resolution = tuple(payload.get('resolution') or (0, 0))
        resolution_index = next((i for i in range(self.resolution.count())
            if tuple(self.resolution.itemData(i) or ()) == resolution), -1)
        if resolution_index < 0 and len(resolution) == 2 and min(resolution) > 0:
            resolution_index = next(i for i in range(self.resolution.count())
                if tuple(self.resolution.itemData(i) or ()) == (-1, -1))
            self.custom_resolution_width.setValue(int(resolution[0]))
            self.custom_resolution_height.setValue(int(resolution[1]))
        self.resolution.setCurrentIndex(max(0, resolution_index))
        for name in ('custom_resolution_width', 'custom_resolution_height', 'custom_fps'):
            if name in payload:
                getattr(self, name).setValue(int(payload[name]))
        speed = str(payload.get("preset_speed") or "balanced")
        self.encoder_preset.setCurrentIndex(max(0, self.encoder_preset.findData(speed)))
        fps = float(payload.get("fps") or 0.0)
        self.fps.setCurrentIndex(max(0, self.fps.findData(fps)))
        self.audio.setCurrentIndex(max(0, self.audio.findData(payload.get("audio_codec", "copy"))))

    def _preset_changed(self, *_args) -> None:
        if not hasattr(self, "encoder"):
            return
        preset_id = str(self.preset.currentData() or "recommended")
        payload = self._preset_payload(preset_id)
        if payload and preset_id != "custom":
            self._apply_preset_payload(payload)
        self._target_changed()

    def _save_current_preset(self) -> None:
        preset_id = str(self.preset.currentData() or "")
        payload = self._preset_payload(preset_id)
        if not payload or not payload.get("user"):
            self._save_preset_as()
            return
        presets = load_user_presets()
        updated = self._capture_export_preset(preset_id, str(payload.get("label") or preset_id))
        presets = [updated if item.get("id") == preset_id else item for item in presets]
        save_user_presets(presets)
        bind_text(self.status, '已保存导出预设')

    def _save_preset_as(self) -> None:
        name, ok = QInputDialog.getText(self, tr('另存为导出预设'), tr('预设名称'))
        if not ok or not str(name).strip():
            return
        label = str(name).strip()
        preset_id = f"user-{abs(hash(label)) % 10_000_000}"
        presets = load_user_presets()
        presets.append(self._capture_export_preset(preset_id, label))
        save_user_presets(presets)
        self._reload_preset_combo(keep=preset_id)
        bind_text(self.status, '已另存为「{label}」', label=label)

    def _delete_user_preset(self) -> None:
        preset_id = str(self.preset.currentData() or "")
        payload = self._preset_payload(preset_id)
        if not payload or not payload.get("user"):
            bind_text(self.status, '只能删除自定义预设')
            return
        save_user_presets([item for item in load_user_presets() if item.get("id") != preset_id])
        self._reload_preset_combo(keep="recommended")
        self._preset_changed()

    def _quality_changed(self, *_args) -> None:
        selected = str(self.quality.currentData() or 'recommended')
        custom = selected == "custom"
        if not custom and hasattr(self, 'rate_control') and not self._updating_export_controls:
            self._updating_export_controls = True
            try:
                mode = 'target' if selected == 'size' else ('crf' if self._resolved_encoder().startswith('lib') else 'cq')
                self.rate_control.setCurrentIndex(max(0, self.rate_control.findData(mode)))
                self.quality_value.setValue({'very_high':16, 'high':18, 'recommended':20, 'size':28}[selected])
            finally:
                self._updating_export_controls = False
        if custom:
            self.advanced_button.setChecked(True)
            QTimer.singleShot(0, lambda: self.settings_scroll.ensureWidgetVisible(self.advanced_panel, 0, 24))
        self._target_changed()

    def _target_changed(self, *_args) -> None:
        if self._released or self._updating_export_controls:
            return
        if not hasattr(self, "status"): return
        bind_text(self.status, '输出：{value0}', value0=self.export_target().full_path)
        duration = self.out_ms - self.in_ms if self.export_range.currentData() == "in_out" else self._duration_ms()
        from .audio_export_ui import is_audio
        if is_audio(self):
            settings = self.audio_delivery.settings()
            self._effective_export_settings = settings
            self.renderer_badge.setText(tr('工程音频'))
            self.summary.setText(f"{self.extension.currentText()} · {self.audio_delivery.rate.currentText()} · {self.audio_delivery.channels.currentText()}\n{tr('范围')} {_clock(duration)}")
            if hasattr(self, 'summary_chips'):
                fill_pills(self.summary_chips, self.summary_chip_host, [self.extension.currentText(),
                    self.audio_delivery.rate.currentText(), self.audio_delivery.channels.currentText(),
                    tr('工程音频'), tr('时长 {duration}', duration=_clock(duration))])
            if hasattr(self, 'filename_extension'): self.filename_extension.setText('.'+str(self.extension.currentData()))
            self.estimated_size.setText(tr('只处理工程音轨，不渲染影片与字幕'))
            return
        resolution = self.resolution.currentData() or (0, 0)
        if resolution[0] < 0: resolution = (self.custom_resolution_width.value(), self.custom_resolution_height.value())
        resolution_text = f"{resolution[0]} × {resolution[1]}" if resolution[0] > 0 else (f"{self.project.media.width} × {self.project.media.height}" if self.project.media.width else "跟随源视频")
        fps_text = f"{self.custom_fps.value()} fps" if float(self.fps.currentData() or 0.0) < 0 else self.fps.currentText()
        effective = self._render_settings(commit=False)
        self._effective_export_settings = effective
        from .export_timeline import export_project_snapshot
        frozen = export_project_snapshot(self.project, start_ms=self.in_ms, end_ms=self.out_ms,
                                         width=effective.width or self.project.media.width,
                                         height=effective.height or self.project.media.height)
        self._output_layout_project = frozen
        if hasattr(self, 'output_layout_preview'):
            canvas = getattr(frozen, '_output_canvas', {})
            width, height = canvas.get('output', (1920, 1080))
            self.output_layout_preview.setVisible(bool(canvas.get('relayout')))
            if canvas.get('relayout'):
                self.output_layout_preview.set_project(frozen, width, height, self.preview_scrub.value())
            else:
                self.output_layout_preview.clear_view()
        advanced = project_requires_advanced(frozen)
        subtitle_text = tr('跟随工程可见性：烧录 {count} 条字幕', count=len(frozen.cues)) if frozen.cues else tr('跟随工程可见性：不烧录字幕')
        route = ("字幕样式：合成烧录" if advanced else "普通字幕：直接烧录") if frozen.cues else tr('无字幕处理')
        self.renderer_badge.setProperty("rendererKind", "advanced" if advanced else "native")
        self.renderer_badge.style().unpolish(self.renderer_badge)
        self.renderer_badge.style().polish(self.renderer_badge)
        bind_text(self.renderer_badge, route)
        mode_text = (f'{effective.quality_mode.upper()} {effective.quality}' if effective.quality_mode in {'crf', 'cq'}
                     else f'{tr(self.rate_control.currentText())} {effective.bitrate_kbps} kbps')
        bind_text(self.summary, '{resolution_text} · {fps_text}\n{value2} · {value3} · {value4}\n{value5} · {subtitles} · 范围 {value6}', resolution_text=tr(resolution_text), fps_text=tr(fps_text), value2=self.codec.currentText(), value3=effective.encoder, value4=mode_text, value5=tr(self.audio.currentText()), subtitles=subtitle_text, value6=_clock(duration))
        fill_pills(self.summary_chips, self.summary_chip_host, [
            tr(resolution_text), tr(fps_text), self.codec.currentText(), effective.encoder, mode_text,
            tr('音频：{audio}', audio=tr(self.audio.currentText())), subtitle_text,
            tr('时长 {duration}', duration=_clock(duration))])
        if hasattr(self, "filename_extension"):
            self.filename_extension.setText("." + str(self.extension.currentData() or "mp4"))
        self._refresh_advanced_summary()
        audio_rate = int(self.audio_bitrate.currentData() or 0) if self.audio.currentData() == "aac" else 0
        if effective.quality_mode in {'crf', 'cq'}:
            bind_text(self.estimated_size, '恒定质量模式：文件大小随画面复杂度变化')
        else:
            bind_text(self.estimated_size, '预计文件大小：~{value0} MB（十进制，音频复制及封装另计）',
                value0=max(1, round((effective.bitrate_kbps + audio_rate) * duration / 8000000)))
        hints = {"recommended":"推荐：适合普通上传", "high":"高质量：更高码率，文件较大", "very_high":"极高质量：适合存档", "size":"体积优先：更小文件", "custom":"自定义：使用高级参数"}
        bind_text(self.quality_hint, hints.get(str(self.quality.currentData()), ""))

    def export_target(self) -> ExportTarget:
        directory = Path(self.directory.text().strip() or self.project.media.path).expanduser()
        from .export_preferences import output_basename
        base = output_basename(self.filename.text().strip() or Path(self.project.media.path).stem,
                               self.filename_prefix.text(), self.filename_suffix.text())
        if hasattr(self, 'complete_name_preview'):
            self.complete_name_preview.setText(base + '.' + str(self.extension.currentData() or 'mp4'))
        return ExportTarget(directory, base, str(self.extension.currentData() or "mp4"))

    def _restore_export_preferences(self):
        self._updating_export_controls = True
        try:
            self._restore_export_controls()
        finally:
            self._updating_export_controls = False
        self._target_changed()

    def _restore_export_controls(self):
        values = self._saved_export_preferences
        if not values:
            self._preset_changed()
            return
        # Restore dependency owners first, then encoder-dependent fields.
        for name in ('extension', 'codec', 'encoder', 'quality', 'rate_control', 'resolution', 'fps',
                     'audio', 'audio_bitrate', 'encoder_preset', 'profile', 'level', 'pixel_format', 'preset'):
            if name not in values:
                continue
            widget = getattr(self, name)
            if name == 'resolution':
                raw = values[name]
                # Old/invalid combo state can have been saved as null. Keep
                # the current valid default instead of throwing in a Qt slot.
                if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                    continue
                value = tuple(raw)
                index = next((i for i in range(widget.count())
                    if isinstance(widget.itemData(i), (list, tuple)) and tuple(widget.itemData(i)) == value), -1)
            else:
                value = values[name]
                index = widget.findData(value)
            if index >= 0:
                blocked = widget.blockSignals(name == 'preset')
                widget.setCurrentIndex(index)
                widget.blockSignals(blocked)
            elif name == 'encoder':
                bind_text(self.actual_encoder_hint, '上次编码器当前不可用，已回退到自动选择。')
        for name in ('quality_value','bitrate','max_bitrate','custom_resolution_width','custom_resolution_height','custom_fps','gop'):
            if name in values:
                getattr(self, name).setValue(int(values[name]))
        self._target_changed()

    def _confirm_export_preferences(self):
        from .audio_export_ui import is_audio
        if is_audio(self): return
        self._commit_export_fields()
        self._confirm_affixes()
        values = {name: getattr(self,name).currentData() for name in (
            'extension','codec','encoder','quality','rate_control','resolution','fps','audio','audio_bitrate',
            'encoder_preset','profile','level','pixel_format','preset')}
        values.update({name: getattr(self,name).value() for name in (
            'quality_value','bitrate','max_bitrate','custom_resolution_width','custom_resolution_height','custom_fps','gop')})
        values.update(prefix=self.filename_prefix.text(), suffix=self.filename_suffix.text(), directory=self.directory.text())
        self._settings.setValue('render/preferences_v1', json.dumps(values, ensure_ascii=False))
        self._settings.setValue('render/export_suffix', values['suffix'])
        self._settings.setValue('render/last_export_directory', values['directory'])
        self._settings.setValue('render/preset', values['preset'])
        self._settings.sync()

    def _save_affix_preferences(self):
        values = dict(prefix=self.filename_prefix.currentText(), suffix=self.filename_suffix.currentText(),
                      prefix_history=self.filename_prefix.history(), suffix_history=self.filename_suffix.history(),
                      base=self.filename.text(), base_source=self._filename_source)
        self._settings.setValue('render/affixes_v1', json.dumps(values, ensure_ascii=False))
        self._settings.sync()

    def _confirm_affixes(self):
        self.filename_prefix.confirm()
        self.filename_suffix.confirm()

    def closeEvent(self, event):
        self.release_preview()
        super().closeEvent(event)

    def _choose_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr('选择导出目录'), self.directory.text())
        if path: self.directory.setText(path)

    def _render_settings(self, *, commit=True) -> RenderSettings:
        from .audio_export_ui import is_audio
        if is_audio(self): return self.audio_delivery.settings()
        if commit:
            self._commit_export_fields()
        codec, encoder = str(self.codec.currentData() or "h264"), self._resolved_encoder()
        # Presets update visible controls; the visible mode owns execution.
        quality = self.quality_value.value()
        rate_mode = str(self.rate_control.currentData() or ('crf' if encoder.startswith('lib') else 'cq'))
        if (str(self.encoder.currentData() or "auto") == "auto" and codec == "h264"
                and encoder.endswith("_nvenc") and rate_mode in {"cq", "crf"}):
            # The H.264 preset numbers were always run as x264 CRF; keep that picture.
            quality += AUTO_NVENC_CQ_OFFSET
        resolution = self.resolution.currentData() or (0, 0)
        width, height = (self.custom_resolution_width.value(), self.custom_resolution_height.value()) if resolution[0] < 0 else resolution
        fps_value = float(self.custom_fps.value()) if float(self.fps.currentData() or 0.0) < 0 else float(self.fps.currentData() or 0.0)
        speed = str(self.encoder_preset.currentData() or "balanced")
        if encoder.endswith("_nvenc"):
            encoder_preset = {"fastest":"p1", "fast":"p3", "balanced":"p4", "quality":"p6", "best":"p7"}[speed]
        elif encoder.endswith("_amf"):
            encoder_preset = {"fastest":"speed", "fast":"speed", "balanced":"balanced", "quality":"quality", "best":"quality"}[speed]
        elif encoder == "libaom-av1":
            encoder_preset = ""
        elif encoder == "libsvtav1":
            encoder_preset = SVT_AV1_SPEED_PRESETS[speed]
        else:
            encoder_preset = {"fastest":"ultrafast", "fast":"fast", "balanced":"medium", "quality":"slow", "best":"slower"}[speed]
        return RenderSettings(container=str(self.extension.currentData()), codec=codec, encoder=encoder,
            quality_mode=rate_mode, quality=quality,
            bitrate_kbps=self.bitrate.value(), max_bitrate_kbps=self.max_bitrate.value(),
            width=int(width), height=int(height), fps=max(0.0, fps_value),
            audio_codec=("opus" if self.extension.currentData()=="webm" and self.audio.currentData()!="none" else str(self.audio.currentData())), audio_bitrate_kbps=int(self.audio_bitrate.currentData() or 192),
            preset=encoder_preset, profile=str(self.profile.currentData()), level=str(self.level.currentData()),
            pixel_format=str(self.pixel_format.currentData()), gop=self.gop.value())

    def _range_seconds(self) -> tuple[float | None, float | None, float]:
        from ..projects.project_range import validated_range
        start,end = validated_range(self.project)
        duration = (end-start)/1000.0
        return start/1000.0,duration,duration

    def _job(self, output: Path, settings=None) -> RenderJob:
        from .audio_export_ui import is_audio, audio_job
        if is_audio(self): return audio_job(self, output, settings)
        from .video_export import capture_video_graph
        start, duration, effective = self._range_seconds()
        sequence = sequence_of(self.project)
        slices = ()
        if not sequence.is_linear_source():
            start_ms = None if start is None else round(float(start) * 1000)
            duration_ms = None if duration is None else round(float(effective) * 1000)
            slices = tuple(export_source_slices(sequence, start_ms, duration_ms))
        from ..projects.studio_project import studio_data_root
        import uuid
        cover_dir = studio_data_root()/'cache/export-completion'
        cover_dir.mkdir(parents=True, exist_ok=True)
        from .export_timeline import write_export_ass
        from dataclasses import asdict, replace
        import hashlib
        settings = replace(settings or self._render_settings())
        export_ass = cover_dir / (uuid.uuid4().hex + '.ass')
        self._export_project = write_export_ass(self.project, export_ass, fps=settings.fps or None,
            skip_empty=True, start_ms=round((start or 0)*1000), end_ms=round(((start or 0)+effective)*1000),
            width=settings.width or self.project.media.width, height=settings.height or self.project.media.height,
            require_layout_fit=True)
        project_data = self._export_project.to_dict()
        revision = hashlib.sha256(json.dumps(project_data, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        return RenderJob(
            self._export_project.media.path, str(export_ass) if self._export_project.cues else '', str(output), settings,
            start_seconds=start, duration_seconds=effective, edit_segments=slices,
            video_graph=capture_video_graph(self._export_project),
            export_project_data=project_data,
            export_context=dict(job_id=uuid.uuid4().hex, project_revision='sha256:' + revision,
                caption_canvas=getattr(self._export_project, '_output_canvas', {}),
                project_path=str(self.project_path or ''), requested_encoder=str(self.encoder.currentData() or 'auto'),
                requested_settings=asdict(settings)),
            completion_preview_path=str(cover_dir/(uuid.uuid4().hex+'.jpg')),
            preview_callback=self._receive_export_preview,
        )

    def _start(self) -> None:
        if self._released:
            return
        from .audio_export_ui import is_audio, start_audio
        if is_audio(self): return start_audio(self)
        self._export_trace("button_clicked")
        self._export_trace("EXPORT_CLICK")
        if self._running:
            return
        try:
            target = self.export_target(); output = target.full_path
            media = Path(self.project.media.path)
            ass = Path(self.ass_path)
            start, duration, effective_duration = self._range_seconds()
            # The worker performs bounded filesystem/decode checks immediately
            # before rendering; cached offline state can explain the failure now.
            from ..media.media_availability import export_sources, require_available
            from .video_export import capture_video_graph
            sources = export_sources(capture_video_graph(self.project), (start or 0) * 1000,
                                     ((start or 0) + effective_duration) * 1000)
            health = getattr(self.project, '_media_availability', {})
            require_available({p: health[p] for p in sources if p in health})
            # Preview generations are disposable and may already have been
            # removed after a text/style edit. _job writes its own frozen ASS.
            if not self.ffmpeg.is_file(): raise FileNotFoundError(f"FFmpeg 不存在：{self.ffmpeg}")
            target.directory.mkdir(parents=True, exist_ok=True)
            if not target.directory.is_dir(): raise NotADirectoryError(f"输出目录无效：{target.directory}")
            if output.exists(): raise FileExistsError(f"输出文件已存在：{output}\n请修改文件名，或移走现有文件后重试。")
            if effective_duration <= 0: raise ValueError("导出范围为空，请重新设置入点和出点。")
            settings = self._render_settings()
            sequence = sequence_of(self.project)
            slices = ()
            if not sequence.is_linear_source():
                start_ms = None if start is None else round(float(start) * 1000)
                duration_ms = None if duration is None else round(float(effective_duration) * 1000)
                slices = tuple(export_source_slices(sequence, start_ms, duration_ms))
            job = self._job(output, settings=settings)
            settings = job.settings
            validate_export_config(job)
            self._advanced_route = project_requires_advanced(self._export_project,
                start_ms=round((start or 0)*1000), end_ms=round(((start or 0)+effective_duration)*1000))
            if self._advanced_route:
                AdvancedRendererBackend().require_available()
            self._export_trace(
                "EXPORT_CONFIG", START=start, END=(start or 0.0) + effective_duration,
                DURATION=effective_duration, FPS=settings.fps, WIDTH=settings.width,
                HEIGHT=settings.height, CRF=settings.quality if settings.quality_mode == "crf" else None,
                CQ=settings.quality if settings.quality_mode == "cq" else None,
                BITRATE=settings.bitrate_kbps if settings.quality_mode not in {"crf", "cq"} else None,
                PRESET=settings.preset, ENCODER=settings.encoder, RATE_CONTROL=settings.quality_mode,
                OUTPUT_PATH=str(output), RENDER_ROUTE="advanced" if self._advanced_route else "native",
            )
        except Exception as exc:
            stack = traceback.format_exc()
            self._export_trace("target_validated", False, reason=str(exc), traceback=stack)
            self._show_failure(f"{exc}\n\n{stack}")
            return
        self._export_trace(
            "target_validated", True, media_path=str(media), project_path=str(self.project_path or ""),
            ass_path=str(ass), output_path=str(output), range_start=start or 0.0,
            range_end=(start or 0.0) + effective_duration, codec=settings.codec, encoder=settings.encoder,
        )
        self._last_job, self._running, self._started_at = job, True, time.monotonic()
        self._completion_notified = False
        job.completion_metadata.clear()
        job.completion_metadata['requested_started_monotonic'] = self._started_at
        self._has_composition_stage = False
        from .export_filtergraph import simple_video_clips
        from .export_progress import ExportProgress
        from .export_media import identity_video_graph
        from .static_caption_export import static_graph_project
        static_advanced=bool(self._advanced_route and static_graph_project(self._export_project))
        static_direct=bool(static_advanced and job.video_graph and simple_video_clips(job.video_graph) is not None)
        self._has_composition_stage = bool(job.video_graph and not identity_video_graph(job.video_graph, job.media_path)
            and ((self._advanced_route and not static_direct) or simple_video_clips(job.video_graph) is None))
        self._work_progress = ExportProgress(effective_duration, raster=self._has_composition_stage,
            advanced=self._advanced_route, static_advanced=static_advanced)
        with self._preview_lock:
            self._pending_export_preview = None
        self.render_preview.clear()
        bind_text(self.render_preview_time, '等待首个处理帧')
        self._cancelled = threading.Event()
        self._run_generation += 1
        generation, cancellation = self._run_generation, self._cancelled
        self._last_preview_sync_ms = -10_000
        bind_text(self.processing_output, '输出：{output}', output=output)
        self._progress_target = 0; self._progress_display = 0.0; self._progress_indeterminate = True
        self._show_advanced_stage(bool(self._advanced_route))
        self._apply_progress(-1, export_progress(
            STAGE_PREPARE_PROJECT, message="正在解析工程并检查输入文件…"
        ))
        self._move_preview_to_render(); self.pages.setCurrentWidget(self.exporting_page)
        if self._preview_widget and callable(getattr(self._preview_widget, "set_paused", None)): self._preview_widget.set_paused(True)
        self._confirm_export_preferences()
        submitted_project=self._export_project
        submitted_job=job
        submitted_advanced=self._advanced_route
        def deliver(kind, payload=None):
            # Only the UI thread consumes run state. This worker owns its event
            # even if another export has started or its QWidget was destroyed.
            if self._released or generation != self._run_generation:
                return  # do not enter a Qt emitter after its page was retired
            try:
                self.run_event.emit(generation, kind, payload)
            except RuntimeError:
                pass
        def worker():
            try:
                if submitted_advanced:
                    result = AdvancedRendererBackend().render(
                        submitted_project, self.ffmpeg, submitted_job, progress=lambda data: deliver('progress', data),
                        cancelled=cancellation.is_set, trace=self._export_trace,
                    )
                else:
                    result = run_render_job(
                        self.ffmpeg, submitted_job, progress=lambda data: deliver('progress', data),
                        cancelled=cancellation.is_set, trace=self._export_trace,
                    )
                deliver('success', str(result))
            except InterruptedError: deliver('cancelled')
            except Exception as exc:
                stack = traceback.format_exc()
                self._export_trace("EXPORT_FAILURE", reason=str(exc), traceback=stack)
                deliver('failure', f"{exc}\n\n{stack}")
        self._worker = threading.Thread(target=worker, daemon=True, name="studio-export")
        self._export_trace("worker_started", {"name": self._worker.name})
        try:
            self._worker.start()
        except Exception as exc:
            self._show_failure(str(exc))

    def _receive_run_event(self, generation: int, kind: str, payload: object) -> None:
        if self._released or generation != self._run_generation or not self._running:
            return
        if kind == 'progress':
            self._progress(payload)
        elif kind == 'success':
            self.render_succeeded.emit(str(payload))
        elif kind == 'cancelled':
            self.render_cancelled.emit()
        elif kind == 'failure':
            self.render_failed.emit(str(payload))

    def _finish_run(self) -> None:
        self._running = False
        self._progress_clock.stop()
        with self._preview_lock:
            self._pending_export_preview = None
        if self._preview_widget is not None:
            pause = getattr(self._preview_widget, 'set_paused', None)
            if callable(pause):
                try: pause(True)
                except RuntimeError: pass
        self._move_preview_to_setup()

    def _visible_stage_specs(self) -> list[tuple[str, str]]:
        from .audio_export_ui import is_audio
        if is_audio(self): return [(STAGE_PREPARE_PROJECT, "准备工程音轨"), (STAGE_ENCODE, "音频编码"), (STAGE_MUX, "验证与发布")]
        return [item for item in self._stage_specs
                if (item[0] != STAGE_ADVANCED_RENDER or self._advanced_route)
                and (item[0] != STAGE_PREPARE_SUBTITLES or bool(getattr(self._last_job, 'ass_path', True)))
                and (item[0] != STAGE_COMPOSE_VIDEO or getattr(self,'_has_composition_stage',False))]

    def _show_advanced_stage(self, visible: bool) -> None:
        advanced = self.render_stage_labels[3]
        advanced.setVisible(bool(visible))

    def _progress(self, payload: dict) -> None:
        data = {str(key): str(value) for key, value in dict(payload or {}).items()}
        stage = data.get("stage") or ""
        percent = None
        if data.get("percent") not in {"", None}:
            try:
                percent = float(data["percent"])
            except (TypeError, ValueError):
                percent = None
        elapsed = parse_ffmpeg_out_time_seconds(data)
        if percent is None and elapsed is not None and stage in {STAGE_ENCODE, STAGE_MUX, STAGE_VALIDATE, ""}:
            percent = elapsed / max(0.05, self._range_seconds()[2]) * 100.0
        if percent is not None:
            self.progress_updated.emit(max(0, min(100, round(percent))), data)
        else:
            self.progress_updated.emit(-1, data)

    def _apply_progress(self, value: int, payload: dict) -> None:
        if self._released:
            return
        self._progress_payload = dict(payload)
        from .export_progress import ExportProgress
        if not hasattr(self, '_work_progress'):
            self._work_progress = ExportProgress(self._range_seconds()[2], raster=payload.get('stage') == STAGE_COMPOSE_VIDEO)
        overall, stage_percent = self._work_progress.update(payload)
        self._progress_target = overall
        self._stage_percent = stage_percent
        self._progress_indeterminate = False
        if not self._progress_clock.isActive():
            self._progress_clock.start()
        self._paint_progress_copy(payload)
        self._tick_progress()

    def _tick_progress(self) -> None:
        if self.progress.maximum() != 100:
            self.progress.setRange(0, 100)
        self._progress_display = float(self._progress_target)
        shown = int(self._progress_target)
        self.progress.setValue(shown)
        self.render_percent.setText(f"{shown}%")
        if self._started_at:
            seconds = max(0, time.monotonic()-self._started_at)
            stale = max(0, time.monotonic()-self._work_progress.last_update)
            bind_text(self.elapsed_label, '已用时 {value0}{value1}', value0=_clock(round(seconds * 1000)), value1=tr(' · {seconds} 秒无新进度', seconds=int(stale)) if stale >= 15 else '')
        with self._preview_lock:
            preview, self._pending_export_preview = self._pending_export_preview, None
        if preview:
            frame, milliseconds, phase = preview
            self.render_preview.setPixmap(QPixmap.fromImage(frame))
            self.render_preview_time.setText(f'{_clock(round(milliseconds), True)} · {phase}')
            self._export_trace('processed_preview', {'project_ms': milliseconds, 'phase': phase})
        if shown >= 100 or not self._running:
            self._progress_clock.stop()

    def _receive_export_preview(self, image, milliseconds, phase):
        with self._preview_lock:
            if not self._released:
                self._pending_export_preview = (image, milliseconds, phase)

    def retranslate_ui(self):
        self._refresh_context()
        self._refresh_subtitle_summary()
        for affix in (self.filename_prefix, self.filename_suffix):
            fit_affix(affix)
        self._target_changed()
        self._update_range()
        if self._running and self._progress_payload:
            self._paint_progress_copy(self._progress_payload)
        elif self.pages.currentWidget() is self.failure_page:
            self._show_failure(self._last_failure)

    def _paint_progress_copy(self, payload: dict) -> None:
        stage = str(payload.get("stage") or STAGE_PREPARE_PROJECT)
        if stage == STAGE_COMPOSE_VIDEO:
            self._has_composition_stage = True
        label = str(payload.get("stage_label") or {
            STAGE_PREPARE_PROJECT: "准备工程",
            STAGE_PREPARE_SUBTITLES: "准备字幕",
            STAGE_ADVANCED_RENDER: "高级样式渲染",
            STAGE_ENCODE: "视频编码",
            STAGE_MUX: "封装收尾", STAGE_VALIDATE: "验证与发布",
        }.get(stage, "准备工程"))
        label = tr(label)
        message = tr(str(payload.get("message") or ""))
        specs = self._visible_stage_specs()
        keys = [item[0] for item in specs]
        active_index = keys.index(stage) if stage in keys else 0
        states = []
        for index, _key in enumerate(keys):
            if index < active_index:
                states.append("complete")
            elif index == active_index:
                states.append("running" if stage not in {STAGE_MUX, STAGE_VALIDATE} or str(payload.get("percent")) != "100.000" else "complete")
            else:
                states.append("waiting")
        if stage in {STAGE_MUX, STAGE_VALIDATE} and str(payload.get("indeterminate")) != "1":
            states = ["complete"] * len(keys)
            states[-1] = "running" if str(payload.get("percent")) != "100.000" else "complete"
        self._set_pipeline_stage_state(tuple(states), label, specs)
        elapsed = parse_ffmpeg_out_time_seconds(payload) or 0.0
        total = max(.05, self._range_seconds()[2])
        speed_text = str(payload.get("speed") or "--").strip()
        speed = _speed(speed_text)
        eta = max(0.0, (total - elapsed) / speed) if speed else 0.0
        size = "--"
        try:
            if self._last_job:
                size = f"{Path(self._last_job.output_path).stat().st_size / 1048576:.1f} MB"
        except OSError:
            pass
        if stage == STAGE_ENCODE and str(payload.get("indeterminate")) != "1":
            fps_text = str(payload.get("fps") or "--")
            self.processing_time.setText(
                f"{int(self._progress_target)}%  ·  {_clock(round(elapsed*1000))} / {_clock(round(total*1000))}"
            )
            bind_text(self.processing_info, '{value0} / {value1}  ·  {fps_text} FPS  ·  ETA {value3}\nframe {value4}  ·  速度 {speed_text}  ·  输出 {size}', value0=_clock(round(elapsed * 1000)), value1=_clock(round(total * 1000)), fps_text=fps_text, value3=_clock(round(eta * 1000)) if speed else '--', value4=payload.get('frame', '0'), speed_text=speed_text, size=size)
            self.render_percent.setToolTip(
                f"{int(self._progress_target)}% · {_clock(round(elapsed*1000))} / {_clock(round(total*1000))} · {fps_text} FPS · ETA {_clock(round(eta*1000)) if speed else '--'}"
            )
        else:
            self.processing_time.setText(message or label)
            bind_text(self.processing_info, message) if message else bind_text(self.processing_info, '当前步骤：{label}。编码尚未开始，因此不显示 0% 进度。', label=label)
        stage_percent = getattr(self, '_stage_percent', None)
        stage_copy = f'{stage_percent:.2f}%' if stage_percent is not None else tr('计算中')
        bind_text(self.processing_time, '总进度 {value0}% · {label} {stage_copy}', value0=int(self._progress_target), label=label, stage_copy=stage_copy)
        if message:
            self.processing_info.setText(message + (f' · {payload["fps"]} FPS' if payload.get('fps') else ''))

    def _set_pipeline_stage_state(self, states: tuple[str, ...], active: str, specs: list[tuple[str, str]] | None = None) -> None:
        specs = specs or self._visible_stage_specs()
        key = (states, active, tuple(item[0] for item in specs), current_language())
        if key == getattr(self, "_pipeline_stage_states", None):
            return
        self._pipeline_stage_states = key
        marks = {"waiting": "○", "running": "●", "complete": "✓"}
        labels = {"waiting": "等待", "running": "运行中", "complete": "完成"}
        visible_labels = []
        for widget, (stage_key, name) in zip(self.render_stage_labels, self._stage_specs):
            if stage_key not in {key for key,_name in specs}:
                widget.hide()
                continue
            widget.show()
            visible_labels.append(widget)
        for widget, (_stage_key, name), state in zip(visible_labels, specs, states):
            widget.setText(f"{marks.get(state, '○')}  {tr(name)}")
            widget.setProperty("stageState", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        bind_text(self.current_stage_title, '当前步骤  ·  {active} · 运行中', active=active)

    def _enqueue(self) -> None:
        target = self.export_target()
        try:
            job = self._job(target.full_path)
            job.preview_callback = None
            validate_export_config(job)
            get_render_queue(self.ffmpeg).enqueue(job)
            self._confirm_export_preferences()
            bind_text(self.status, '已加入队列：{value0}', value0=target.full_path)
        except Exception as exc: self.status.setText(str(exc))

    def _show_success(self, path: str) -> None:
        if self._released:
            return
        self._finish_run()
        output = Path(path); self._settings.setValue("render/last_export_directory", str(output.parent))
        self.success_name.setText(output.name)
        audio_output = getattr(getattr(self._last_job,"settings",None),"output_kind", "video") == "audio"
        bind_text(self.success_page.title,"音频导出完成" if audio_output else "压制完成")
        self.success_page.preview_host.setVisible(not audio_output)
        bind_text(self.success_page.section_label,"音频信息" if audio_output else "成片信息")
        for key,audio_label in (("分辨率","采样率"),("帧率","声道")):
            bind_text(self.success_page.metric_labels[key],audio_label if audio_output else key)
        self.success_page._fit()
        bind_text(self.success_page.play, "播放音频" if audio_output else "播放成片")
        panel=self.success_page
        panel.path.setText(str(output.parent))
        job=getattr(self,'_last_job',None)
        receipt=getattr(job,'completion_metadata',{}) or {}
        # A delayed callback must never display metadata from another output.
        if receipt.get('output_path') != str(output.resolve()):
            receipt={}
        from .export_validation import positive_number
        elapsed = positive_number(receipt.get('elapsed_seconds'))
        elapsed_display = '—'
        if elapsed is not None:
            minutes, tenths = divmod(round(elapsed * 10), 600)
            elapsed_display = (tr('{minutes} 分 {seconds} 秒', minutes=minutes, seconds=f'{tenths / 10:.1f}')
                if minutes else tr('{seconds} 秒', seconds=f'{tenths / 10:.1f}'))
        bind_text(self.success_meta, '压制耗时  {value0}', value0=elapsed_display)
        stream=next((s for s in receipt.get('streams',[]) if s.get('codec_type')=='video'),{})
        resolution_text=f"{stream['width']} × {stream['height']}" if stream.get('width') and stream.get('height') else '—'
        fps=stream.get('avg_frame_rate')
        from fractions import Fraction
        try: fps_text=f"{float(Fraction(str(fps))):g} fps"
        except (ValueError,ZeroDivisionError):fps_text='—'
        codec=stream.get('codec_name','')
        codec_text={'h264':'H.264','hevc':'HEVC','av1':'AV1'}.get(codec,codec.upper() or '—')
        duration=receipt.get('duration_seconds')
        size=receipt.get('size_bytes')
        bitrate=receipt.get('average_bitrate_bps')
        for key,value in {'格式':codec_text,'分辨率':resolution_text,'帧率':fps_text,
                          '时长':_clock(round(duration*1000)) if duration else '—',
                          '大小':f'{size / 1_000_000:.1f} MB' if size is not None else '—',
                          '平均码率':f'{bitrate / 1_000_000:.1f} Mb/s' if bitrate else '—'}.items():
            panel.values[key].setText(value)
        if audio_output:
            audio = next((s for s in receipt.get('streams', []) if s.get('codec_type') == 'audio'), {})
            panel.values['格式'].setText(audio.get('codec_name', '').upper())
            panel.values['分辨率'].setText(str(audio.get('sample_rate', '—'))+' Hz')
            panel.values['帧率'].setText(str(audio.get('channels', '—'))+' '+tr('声道'))
            bind_text(self.success_meta, '导出耗时  {value0}', value0=elapsed_display)
        panel.preview.image=QPixmap()
        thumbnail=getattr(job,'completion_preview_path','')
        if receipt and thumbnail and Path(thumbnail).is_file():
            panel.preview.image=QPixmap(thumbnail);panel.preview.update()
            Path(thumbnail).unlink(missing_ok=True)
        panel.preview.update()
        request = receipt.get('requested_video_bitrate_bps')
        measured = (receipt.get('video_bitrate') or {}).get('average_bitrate_bps')
        if request:
            actual = f'{measured / 1000:.0f} kbps' if measured is not None else tr('无法可靠测量')
            mode = str(receipt.get('actual_rate_control') or getattr(getattr(job, 'settings', None), 'quality_mode', ''))
            bind_text(self.success_meta, '压制耗时 {elapsed}\n请求视频码率 {requested} kbps · 实测平均视频码率 {actual} · 实际模式 {mode}',
                elapsed=elapsed_display, requested=f'{request / 1000:g}', actual=actual, mode=mode)
        if request and receipt.get('bitrate_target_met') is False:
            bind_text(panel.error, '导出完成，但码率目标未达到。成片与诊断信息已保留。'); panel.error.show()
        elif request and receipt.get('bitrate_target_met') is None:
            bind_text(panel.error, '导出完成，视频码率无法可靠测量。成片与诊断信息已保留。'); panel.error.show()
        else:
            panel.error.hide()
        self._success_output = output
        panel.painted = False   # ExportSuccessPanel.paintEvent sets it
        self.pages.setCurrentWidget(self.success_page)
        panel.play.setFocus()
        self._export_trace("success_page_shown", {"output": str(output)})
        if not getattr(self, "_completion_notified", False):
            self._completion_notified = True
            # 2026-10-27 (user report: 压制完成 arrived while the window still
            # showed 97%): the notification creates a tray icon and calls into
            # Explorer synchronously (0.24 s on the real desktop here, before
            # the result page could paint). Show the page first.
            after_paint = getattr(panel, "call_after_paint", None)
            if callable(after_paint):
                after_paint(lambda: self._notify_completed(output))
            else:
                StudioExportWorkspace._notify_completed(self, output)
        # Not reproduced here: a result page that has not painted 3 s later is
        # written down with the window's state, so the next support bundle
        # tells a blocked GUI thread (watchdog dump) from a window that stopped
        # repainting.
        from .export_success import report_unpainted_success
        QTimer.singleShot(3000, panel, lambda: report_unpainted_success(self, panel, output))

    def _notify_completed(self, output: Path) -> None:
        from .export_notification import notify_export_completed
        try:
            notify_export_completed(self, output)
        except Exception as exc:
            # OS notification failure must not turn a published video into
            # an export failure or hide its completion receipt.
            self._export_trace("completion_notification_failed", {"error": str(exc)})

    def _open_success_video(self) -> None:
        output = getattr(self, "_success_output", None)
        if output is None or not output.is_file():
            bind_text(self.success_page.error, '找不到成片文件，可能已被移动或删除。');self.success_page.error.show();return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))):
            bind_text(self.success_page.error, '无法启动默认播放器，请在文件夹中打开成片。');self.success_page.error.show()

    def _open_success_folder(self) -> None:
        output = getattr(self, "_success_output", None)
        if output is None or not output.is_file():
            bind_text(self.success_page.error, '找不到成片文件，可能已被移动或删除。');self.success_page.error.show();return
        try:
            from ..system.processes import popen_hidden_subprocess
            popen_hidden_subprocess(['explorer.exe','/select,',str(output)],purpose='reveal completed export')
        except OSError:
            bind_text(self.success_page.error, '无法打开资源管理器；可复制输出位置后手动打开。');self.success_page.error.show()

    def _show_failure(self, message: str) -> None:
        if self._released:
            return
        self._finish_run()
        self._last_failure = str(message)
        phase = str(getattr(self,'_progress_payload',{}).get('stage_label') or '准备工程')
        detail = str(message).strip().split('\n\n',1)[0] or '未返回可读原因'
        detail = detail.split('（cue.style_id=',1)[0]
        bind_text(self.failure_reason, '失败阶段：{phase}\n{value1}\n请返回设置修正后重试；完整诊断可在“查看详情”中查看。', phase=tr(phase), value1=tr(detail[:220]))
        self.install_renderer_button.setVisible("高级字幕渲染环境尚未安装" in str(message))
        diagnostics = (getattr(getattr(self, '_last_job', None), 'export_context', {}) or {}).get('diagnostics_path')
        details = str(message)
        if diagnostics:
            details += '\n\n' + tr('导出诊断目录：{path}', path=diagnostics)
        self.details.setPlainText(details); self.details.hide(); self.details_button.setChecked(False); self.pages.setCurrentWidget(self.failure_page)

    def _install_renderer_environment(self) -> None:
        self.install_renderer_button.setEnabled(False)
        bind_text(self.failure_reason, '正在安装高级字幕渲染环境…')
        root = Path(__file__).resolve().parents[2] / "renderer"
        def install() -> None:
            try:
                completed = __import__("subprocess").run(
                    ["npm.cmd" if os.name == "nt" else "npm", "install"], cwd=root,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                ok = completed.returncode == 0
                detail = (completed.stdout if ok else completed.stderr)[-3000:]
            except Exception as exc:
                ok, detail = False, str(exc)
            self.renderer_install_finished.emit(ok, detail)
        threading.Thread(target=install, daemon=True, name="advanced-renderer-install").start()

    def _renderer_install_done(self, ok: bool, detail: str) -> None:
        self.install_renderer_button.setEnabled(True)
        self.install_renderer_button.setVisible(not ok)
        (bind_text(self.failure_reason, '高级字幕渲染环境已安装，可以重试。') if ok else bind_text(self.failure_reason, '高级字幕渲染环境安装失败，请查看详情。'))
        self.details.setPlainText(detail)

    def _show_cancelled(self) -> None:
        if self._released:
            return
        self._finish_run()
        diagnostics = (getattr(getattr(self, '_last_job', None), 'export_context', {}) or {}).get('diagnostics_path')
        if diagnostics:
            bind_text(self.status, '导出已取消，未生成可交付文件。诊断目录：{path}', path=diagnostics)
        else:
            bind_text(self.status, '导出已取消，未生成可交付文件。')
        self.pages.setCurrentWidget(self.setup_page)

    def _cancel_export(self) -> None:
        if self._running: self._cancelled.set(); bind_text(self.processing_info, '正在取消导出…')

    def _retry(self) -> None:
        if not self._running: self.pages.setCurrentWidget(self.setup_page); self._start()

    def _return_to_settings(self) -> None:
        self._move_preview_to_setup(); self.pages.setCurrentWidget(self.setup_page); self._target_changed()

    def _toggle_details(self, expanded: bool) -> None:
        self.details.setVisible(expanded); self.details_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_card.set_expanded(expanded)

    def _toggle_expert(self, expanded: bool) -> None:
        self.expert_card.set_expanded(expanded)

    def _move_preview_to_render(self) -> None:
        if self._released:
            return
        if not self._preview_widget or self.render_preview_layout.indexOf(self._preview_widget) >= 0: return
        controller = getattr(self._preview_widget, "controller", None)
        if controller is not None:
            try:
                self._preview_volume_before_export = float(controller.get_property("volume", 100.0) or 0.0)
                controller.set_volume(0.0)
                self._export_trace("preview_muted", {"volume_before": self._preview_volume_before_export, "volume": 0.0})
            except (RuntimeError, TypeError, ValueError):
                self._preview_volume_before_export = None
        self.preview_host_layout.removeWidget(self._preview_widget)
        self.render_preview_layout.addWidget(self._preview_widget); self._preview_widget.hide()
        self.render_preview.show()

    def _move_preview_to_setup(self) -> None:
        if self._released:
            return
        if not self._preview_widget or self.preview_host_layout.indexOf(self._preview_widget) >= 0: return
        self.render_preview_layout.removeWidget(self._preview_widget)
        self.preview_host_layout.addWidget(self._preview_widget); self._preview_widget.show()
        controller = getattr(self._preview_widget, "controller", None)
        if controller is not None and self._preview_volume_before_export is not None:
            try: controller.set_volume(self._preview_volume_before_export)
            except RuntimeError: pass
        self._preview_volume_before_export = None

    def release_preview(self) -> None:
        if self._released:
            return
        self._released = True
        self._run_generation += 1
        self._cancelled.set()
        if hasattr(self, '_progress_clock'):
            self._progress_clock.stop()
        if hasattr(self, 'filename_prefix'):
            try: self._confirm_affixes()
            except (OSError, RuntimeError): pass
        preview, self._preview_widget = self._preview_widget, None
        if preview is None:
            return
        pause = getattr(preview, 'set_paused', None)
        if callable(pause):
            try: pause(True)
            except RuntimeError: pass
        controller = getattr(preview, 'controller', None)
        if controller is not None and self._preview_volume_before_export is not None:
            try: controller.set_volume(self._preview_volume_before_export)
            except RuntimeError: pass
        self._preview_volume_before_export = None
        for signal, callback in ((preview.position_changed, self._preview_position_changed),
                                 (preview.playback_state_changed, self._preview_state_changed)):
            if not self._preview_signals_connected:
                break
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self._preview_signals_connected = False
        if self._preview_origin_layout is not None and self._preview_origin_layout.indexOf(preview) < 0:
            current_parent = preview.parentWidget()
            if current_parent is not None and current_parent.layout() is not None:
                current_parent.layout().removeWidget(preview)
            if self._preview_origin_cell is not None:
                self._preview_origin_layout.addWidget(preview, *self._preview_origin_cell)
            else:
                self._preview_origin_layout.insertWidget(max(0, self._preview_origin_index), preview, 1)
        elif self._preview_origin_layout is None:
            preview.setParent(self._preview_origin_parent)
        preview.show()

    def _back(self) -> None:
        self._confirm_affixes()
        if self._running:
            self._cancel_export()
        try:
            self.release_preview()
        except Exception:
            pass
        self.back_requested.emit()
