"""PySide6 main window: home, progress and completion pages, term library.

Where things are (search for the name):
- ``run_desktop_app``: GUI entry called by quick_start.main.
- ``MainWindow``: the main window.  Its QStackedWidget pages are
  0 ``_settings_page`` (the Home page; the name is historical),
  1 ``_progress_page``, 2 ``_result_page`` (completion page), 3 ``TermLibraryPage``;
  the model workshop, recognition history and Studio pages are built on first use.
  Starting a run: ``_start_run`` -> ``_launch_pipeline_worker`` -> ``PipelineWorker``.
  Opening Studio: ``open_studio_project`` -> ``_open_subtitle_studio``.
- First-run setup flow: ``_offer_first_run_setup`` -> ``_open_quick_setup`` /
  ``_open_guided_setup`` -> ``_apply_setup_choice`` (saves via ``persist_asr_configuration``).
- ASR choices and saving: ``ASR_API_PRESETS``, ``populate_available_asr_choices``,
  ``persist_asr_configuration``; AI settings: ``persist_ai_configuration``.

Moved out on 2026-10-15 and imported back below under the same names:
- providers/endpoint_editor_ui.py: ``EndpointEditor``, the ``Provider*`` check threads,
  ``AsrModelsFetchWorker``, ``PromptDialog``, ``provider_for_stage``.
- app/guided_setup_dialog.py: ``GuidedSetupDialog``; app/modal_host_widgets.py: ``ModalHost``.
- app/pipeline_worker.py: ``PipelineWorker``; app/update_dialog.py: update dialog and threads.
- app/window_chrome_widgets.py: ``WindowTitleBar``, ``BrandLabel``; app/completion_dialog.py.
- app/home_widgets.py: ``CollapsibleFrame``, ``MediaPickCard``, ``DropOverlay``, workflow strip.
- app/progress_widgets.py: run-log helpers; app/main_ui_helpers.py: ``_icon``,
  ``_active_theme_definition``.
- glossary/term_library_ui.py: ``TermLibraryPage``, ``GlossaryPickerDialog``;
  glossary/ai_term_search.py: AI game-term search.
Shared widgets live in design/.
"""

from __future__ import annotations

from ..diagnostics.navigation_timing import phase as navigation_phase, timed as navigation_timed
from ..diagnostics.studio_events import observed

import os
from ..glossary.glossary_write_feedback import glossary_write_errors
import sys
import time
import html
import json
import re
import copy
import threading
import traceback
import uuid
from dataclasses import dataclass, replace
from contextlib import ExitStack, contextmanager, nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path

import qtawesome as qta
import requests
from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSignalBlocker,
    QSize,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    QAbstractTableModel,
    QModelIndex,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPalette,
    QRegion,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QGridLayout,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

from twobyteasr.design.typography import TITLE_FONT_STACK, UI_FONT_STACK
from twobyteasr.design.ui_theme import (
    AMBER,
    BACKGROUND as IVORY,
    BACKGROUND_ALT as PARCHMENT,
    BLUE,
    BORDER as LINE,
    CHARCOAL,
    CORAL,
    GREEN,
    GREEN_HOVER,
    GREEN_PRESSED,
    GREEN_SOFT,
    GREEN_SUBTLE,
    INK,
    MINT,
    MUTED,
    MUTED_LIGHT,
    PURPLE,
    SURFACE,
    theme_definition,
)
from twobyteasr.i18n import apply_ui_language, current_language, save_language, translate, tr, bind_text, user_text, ui_literal
from twobyteasr.system.hardware import detect_cuda_runtime
from twobyteasr.local_models.model_workshop import (
    MODELS,
    ModelDownloadDialog,
    ModelPickerPanel,
    ModelTechnicalDialog,
    ModelWorkshopPage,
    _model_roles,
    installed_model_keys,
)
from twobyteasr.local_models.model_registry import ModelHealth, ModelRegistry, scan_model_registry
from twobyteasr.recognition.recognition_history import RecognitionHistoryPage
from twobyteasr.glossary.glossary_learning import GlossaryLearningStore
from twobyteasr.recognition.recognition_profiles import ASR_CONFIG_KEYS, ProjectProfile, ProjectProfileStore, normalize_llm_config
from twobyteasr.diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE
from twobyteasr.recognition.recognition_plans import (
    FOREIGN,
    lightweight_media_profile,
    matching_plan,
    plan_options,
    recognition_plan,
)
from twobyteasr.design.ui_navigation import NAVIGATION_QSS, WorkspaceNavigation, style_workspace_sidebar_heading
from twobyteasr.storage.settings import save_runtime_settings
from twobyteasr.providers.llm_config import (
    AI_SERVICE_SPECS,
    PROVIDER_PRESETS,
    activate_ai_service,
    active_service_values,
    chat_completion_url,
    delete_api_key_for,
    credential_storage_notice,
    session_credentials_enabled,
    endpoint_from_settings,
    get_active_service,
    get_provider_profiles,
    fetch_openai_compatible_models,
    get_cached_models,
    model_is_retired,
    normalize_base_url,
    normalize_provider_profile,
    resolved_service_values,
    service_model_catalog,
    responses_url,
    qwen_asr_endpoint_from_settings,
    read_api_key,
    read_asr_api_key,
    resolve_api_key,
    save_api_key_for,
    save_api_keys,
    set_cached_models,
    supports_model_discovery,
    update_active_profile,
    validate_endpoint,
    validate_qwen_asr_endpoint,
)
from twobyteasr.providers.ai_providers import AITransport
from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY

from ..i18n import bind_text, tr, user_text


from subtitle_core import run_llm_json_self_test
from twobyteasr.recognition.service import CancellationToken, RunOptions, run_media_queue
from twobyteasr.app.updater import (
    GITCODE_RELEASE_PAGE,
    RELEASE_PAGE,
    UpdateCancelled,
    automatic_check_delay_ms,
    automatic_check_due,
    automatic_checks_allowed,
    check_for_update,
    cleanup_after_update,
    confirm_started,
    current_version,
    format_bytes,
    launch_update_helper,
    prepare_update,
)
from twobyteasr.diagnostics.startup_trace import mark as _startup_mark
from twobyteasr.app import ui_zoom
from twobyteasr.app.ui_recognition import home_plan_height
from twobyteasr.app.lazy_pages import existing_page

# Work that must not delay the first window; run on the GUI thread about
# 2.5 s after it is interactive (MainWindow._warm_studio_module).
_STARTUP_IDLE_TASKS = []


def after_startup_idle(task):
    _STARTUP_IDLE_TASKS.append(task)


from twobyteasr.app.main_ui_helpers import (
    APP_ROOT, APP_ICON_SOURCE_PATH, APP_ICON_FALLBACK_PATH, APP_ICON_PATH,
    LAST_MEDIA_DIRECTORY_KEY, SUPPORTED_MEDIA_SUFFIXES, GUI_PROFILE_ENABLED,
    _media_dialog_initial_directory, _remember_media_directory,
    _select_media_paths, _merge_media_paths, _is_ai_config_failure,
)
from twobyteasr.design.main_ui_theme import APP_QSS
from twobyteasr.design.theme_manager import apply_application_theme, apply_theme, theme_key
from twobyteasr.design.themed_icons import install_themed_icon, themed_icon
from twobyteasr.design.main_ui_dialogs import DialogSurface, SpringDialog
from twobyteasr.app.main_ui_branding import HeaderMascot, _app_icon, _brand_pixmap
from twobyteasr.glossary.main_ui_glossary import (
    TermLibraryDialog,
    TermGameListRow,
    _CategoryPillDelegate,
    _TermMappingsModel,
    term_library_game_names,
)
from twobyteasr.design.main_ui_popup import EditableHistoryCombo, FramelessPopupCombo, _ComboPopup
from twobyteasr.glossary.main_ui_smart_glossary import SmartGlossaryDialog, SmartGlossaryWorker
from twobyteasr.design.ui_widgets import AnimatedButton, SwitchControl
from twobyteasr.glossary.glossary_binding import GlossaryBindingResolver

# Split out of this file on 2026-10-15 (see docs/CODE_MAP.md).  Imported back
# under the old names so ``ui.X`` keeps working; tests that fake a name used
# inside one of these classes must patch the module that now holds the class.
from .completion_dialog import CompletionDialog
from .guided_setup_dialog import _CudaProbeRelay, GuidedSetupDialog
from .home_widgets import (
    CollapsibleFrame, DropOverlay, FlowStage, MediaNameLabel, MediaPickCard, WorkflowStrip,
)
from .main_ui_helpers import _active_theme_definition, _icon
from .modal_host_widgets import _ModalBackdrop, ModalHost
from .pipeline_worker import PipelineWorker, SignalTextStream
from .progress_widgets import append_log_html_keep_left, keep_log_view_at_left, set_log_html_keep_left
from .update_dialog import UpdateCheckWorker, UpdateDownloadWorker, UpdateOfferDialog
from .window_chrome_widgets import _NativeResizeHandle, BrandLabel, WindowTitleBar
from ..glossary.ai_term_search import parse_ai_game_terms, request_ai_game_terms, TermSearchWorker
from ..glossary.term_library_ui import (
    build_term_library_page_qss, GlossaryPickerDialog, TERM_LIBRARY_PAGE_QSS, TermLibraryPage,
)
from ..providers.endpoint_editor_ui import (
    AsrModelsFetchWorker, ConnectionTester, EndpointEditor, PromptDialog, provider_for_stage,
    ProviderCLIUpdateWorker, ProviderConnectionTester, ProviderLoginWorker,
    ProviderModelDiscoveryWorker,
)

QWEN_API_KEY_HELP_URL = "https://help.aliyun.com/zh/model-studio/get-api-key"

ASR_API_PRESETS = {
    # 2026-10-13: Qwen Cloud — the official international Qwen API platform
    # (home.qwencloud.com). One pay-as-you-go key, no workspace host. 2026-10-25:
    # the same entry also serves the mainland site 千问AI平台 (maas.qianwenaiapi.com);
    # the setup dialog writes that host into the URL when 中国站 is chosen.
    "qwen_cloud_filetrans": {
        "short": "Qwen 官方 录音文件识别", "label": "Qwen 官方 API（千问AI平台 / Qwen Cloud）｜录音文件识别",
        "protocol": "dashscope_filetrans", "model": "qwen-audio-3.1-asr-flash-filetrans",
        "models": ("qwen-audio-3.1-asr-flash-filetrans", "qwen3-asr-flash-filetrans"),
        "url": "https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription",
    },
    "spark_asr_v2": {
        "short": "讯飞 Spark V2", "label": "讯飞 Spark-ASR-2.0（原生 WSS）",
        "protocol": "spark_wss", "model": "spark_asr_v2",
        "url": "wss://iat.cn-huabei-1.xf-yun.com/v1",
    },
    "qwen31_filetrans": {
        # One Bailian provider (one key + one OSS setup) with two documented
        # 录音文件识别 models; each keeps its own request schema
        # (twobyteasr.providers.qwen31_asr.FILETRANS_MODELS).
        "short": "百炼 录音文件识别", "label": "阿里云百炼｜录音文件识别（Qwen3-ASR / Qwen-Audio-3.1）",
        "protocol": "dashscope_filetrans", "model": "qwen-audio-3.1-asr-flash-filetrans",
        "models": ("qwen3-asr-flash-filetrans", "qwen-audio-3.1-asr-flash-filetrans"),
        "url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
    },
    # 2026-10-13: MOSS-Transcribe-Diarize Pro on the MOSI platform. A separate
    # cloud engine; it shares nothing with the local MOSS backend.
    "mosi_moss_pro": {
        "short": "MOSS Pro 云端", "label": "MOSS-Transcribe-Diarize Pro 云端（MOSI 平台）",
        "protocol": "mosi_transcriptions", "model": "moss-transcribe-diarize-pro",
        "url": "https://api.mosi.cn/v1",
    },
    "groq": {
        "short": "Groq",
        "label": "Groq Whisper",
        "protocol": "openai_transcription",
        "model": "whisper-large-v3-turbo",
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
    },
    "openai": {
        "short": "OpenAI",
        "label": "OpenAI Transcribe",
        "protocol": "openai_transcription",
        "model": "gpt-transcribe",
        "url": "https://api.openai.com/v1/audio/transcriptions",
    },
    "custom": {
        "short": "兼容 ASR",
        "label": "自定义 OpenAI 兼容 ASR",
        "protocol": "openai_transcription",
        "model": "",
        "url": "",
    },
    # 三十八轮：旧的 openrouter multipart 通道删除（用户验证字级通道可用后
    # 要求移除）；settings 加载器把存量 provider=openrouter 迁移到字级通道。
    "openrouter_word": {
        "short": "OpenRouter",
        "label": "OpenRouter MAI-Transcribe 2",
        "protocol": "openrouter_verbose_json",
        "model": "microsoft/mai-transcribe-2",
        "url": "https://openrouter.ai/api/v1/audio/transcriptions",
    },
    "azure": {
        "short": "Azure",
        "label": "Azure OpenAI 部署（如 whisper）",
        "protocol": "azure_transcription",
        "model": "",
        "url": "",
    },
    # 四十轮：录音文件识别（异步 filetrans）——整段上传用户 OSS 临时对象，
    # 预签名 HTTPS URL 提交 Qwen；词级时间戳 + 说话人分离（speaker_id）。
    # 需要 OSS 配置（配置弹窗 OSS 分组），AccessKey 走 DPAPI。
    # 四十一轮：地址换用户推荐的工作台域名（四十分轮默认的 dashscope 中心域名
    # 对该模型在执行期报 InvalidParameter.ParseError）。
}

PRIMARY_MODEL_CHOICES = (
    ("MOSS（推荐，长音频与说话人区分）", "moss", {"moss", "firered_vad", "speaker_embedding"}),
    ("FireRedASR2-AED（中文与方言）", "firered", {"firered_aed"}),
    ("Qwen3-ASR 1.7B 本地（准确，多语种）", "qwen_local", {"qwen_asr"}),
    ("FireRedASR2-LLM（中文、方言、English）", "firered_llm", {"firered_llm"}),
    ("Whisper large-v3-turbo（多语种，可用 CPU）", "whisper_turbo", {"whisper_turbo"}),
    ("SenseVoice Small（轻量，CPU 友好）", "sensevoice", {"sensevoice"}),
    ("Paraformer（中文快速时间戳）", "paraformer", {"paraformer"}),
    ("Fun-ASR Nano（中文与方言）", "funasr_nano", {"funasr_nano"}),
    ("GLM-ASR Nano（独立运行库）", "glm_asr_nano", {"glm_asr_nano"}),
    ("Canary-Qwen（英语，独立运行库）", "canary_qwen", {"canary_qwen", "canary_qwen_tokenizer"}),
    # Apple Silicon only (MLX); the folders never exist elsewhere.
    ("Qwen3-ASR 0.6B（Apple Silicon · MLX）", "mlx_qwen3_asr", {"mlx_qwen3_asr_0_6b"}),
    ("Qwen3-ASR 1.7B（Apple Silicon · MLX）", "mlx_qwen3_asr_1_7b", {"mlx_qwen3_asr_1_7b"}),
)
REVIEW_MODEL_CHOICES = (
    ("本地 Qwen3-ASR 1.7B（更准确，约 4.7 GB）", "local", {"qwen_asr"}),
    ("本地 FireRedASR2-LLM（高精度，约 17.57 GiB）", "firered_llm", {"firered_llm"}),
    ("本地 Whisper large-v3-turbo（多语种，约 1.6 GB）", "whisper_turbo", {"whisper_turbo"}),
    ("本地 SenseVoice Small（CPU 友好，约 0.9 GB）", "sensevoice", {"sensevoice"}),
    ("本地 Fun-ASR Nano 2512（中文方言，约 2.4 GB）", "funasr_nano", {"funasr_nano"}),
)
TIMELINE_MODEL_CHOICES = (
    ("FireRed 字幕时间轴（字级，推荐）", "local", {"firered_aed"}),
    ("Qwen3 ForcedAligner 字幕时间轴（多语种强制对齐）", "qwen_aligner", {"qwen_aligner"}),
    ("Whisper 字幕时间轴（多语种，短块级）", "whisper_turbo", {"whisper_turbo"}),
    ("Paraformer 字幕时间轴（中文时间戳）", "paraformer", {"paraformer"}),
    ("Qwen3 ForcedAligner 字幕时间轴（Apple Silicon · MLX）", "mlx_qwen_aligner", {"mlx_qwen_aligner"}),
    ("MFA 字幕时间轴（实验 · 中文 / 日语）", "mfa_aligner", {"mfa_aligner", "mfa_aligner_ja"}),
)


def populate_available_asr_choices(primary, review, timeline, settings, root=APP_ROOT):
    """Populate selectors from complete local installs, never from catalog claims."""
    from ..local_models.model_workshop import MODELS, model_platform_available
    unavailable_backends = {backend for model in MODELS if not model_platform_available(model)
                            for _role, backend in model.adapter_bindings}
    installed = installed_model_keys(Path(root))
    desired = settings.get("models", {})
    missing = []

    def fill(combo, local_choices, trailing, setting_key, fallback):
        wanted = str(desired.get(setting_key, fallback))
        combo.blockSignals(True)
        combo.clear()
        for label, value, required in local_choices:
            if required <= installed and value not in unavailable_backends:
                combo.addItem(label, value)
        for label, value in trailing:
            combo.addItem(label, value)
        index = combo.findData(wanted)
        if index < 0:
            if wanted not in {value for _label, value in trailing}:
                missing.append((setting_key, wanted))
            index = combo.findData(fallback)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    fill(
        primary,
        PRIMARY_MODEL_CHOICES,
        (("在线 ASR API（免下载）", "api"), ("尚未选择（先浏览界面）", "none")),
        "primary_asr_backend",
        "none",
    )
    fill(
        review,
        REVIEW_MODEL_CHOICES,
        (("API（更快、免下载，需配置 Key）", "api"), ("关闭文字复核", "off")),
        "qwen_asr_backend",
        "off",
    )
    fill(
        timeline,
        TIMELINE_MODEL_CHOICES,
        (("不生成字幕时间轴（仅输出 TXT）", "off"),),
        "firered_asr_backend",
        "off",
    )
    return tuple(missing)


def _language_preflight_values(values: dict, spoken: str, settings: dict) -> dict:
    """Check the effective timeline without rewriting the user's saved choice."""
    from ..recognition.recognition_choices import language_timeline
    result = dict(values)
    timeline = str(result.get('firered_asr_backend', 'off'))
    resolved = language_timeline(timeline, spoken, settings or {})
    if resolved is not None and resolved['rerouted']:
        result['firered_asr_backend'] = 'qwen_aligner'
    return result


def missing_selected_local_models(values: dict, root=APP_ROOT) -> tuple[str, ...]:
    installed = installed_model_keys(Path(root))
    requirements = {
        "primary": {value: required for _label, value, required in PRIMARY_MODEL_CHOICES},
        "review": {value: required for _label, value, required in REVIEW_MODEL_CHOICES},
        "timeline": {value: required for _label, value, required in TIMELINE_MODEL_CHOICES},
    }
    selections = {
        "primary": str(values.get("primary_asr_backend", "none")),
        "review": str(values.get("qwen_asr_backend", "off")),
        "timeline": str(values.get("firered_asr_backend", "off")),
    }
    labels = {"primary": "主力转写", "review": "文字复核", "timeline": "字幕时间轴"}
    missing = []
    for role, selected in selections.items():
        required = requirements[role].get(selected, set())
        absent = sorted(required - installed)
        if absent:
            missing.append(f"{labels[role]}：{selected}（缺少 {', '.join(absent)}）")
    return tuple(missing)


@dataclass(frozen=True)
class StartupModelPreflight:
    """Registry-backed startup decision for the saved recognition plan."""

    installed_count: int
    required_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    corrupt_keys: tuple[str, ...]

    @property
    def should_prompt(self) -> bool:
        return bool(self.missing_keys or self.corrupt_keys)


def required_recognition_model_keys(values: dict) -> tuple[str, ...]:
    models = values.get("models", values) if isinstance(values, dict) else {}
    requirements = {
        "primary_asr_backend": {
            value: required for _label, value, required in PRIMARY_MODEL_CHOICES
        },
        "qwen_asr_backend": {
            value: required for _label, value, required in REVIEW_MODEL_CHOICES
        },
        "firered_asr_backend": {
            value: required for _label, value, required in TIMELINE_MODEL_CHOICES
        },
    }
    defaults = {
        "primary_asr_backend": "none",
        "qwen_asr_backend": "off",
        "firered_asr_backend": "off",
    }
    required: set[str] = set()
    for key, choices in requirements.items():
        required.update(choices.get(str(models.get(key, defaults[key])), set()))
    return tuple(sorted(required))


def startup_model_preflight(
    values: dict,
    *,
    registry: ModelRegistry | None = None,
) -> StartupModelPreflight:
    registry = registry or scan_model_registry()
    required = required_recognition_model_keys(values)
    missing: list[str] = []
    corrupt: list[str] = []
    for key in required:
        record = registry.record(key)
        health = record.health if record is not None else ModelHealth.MISSING
        if health in {ModelHealth.MISSING, ModelHealth.PARTIAL}:
            missing.append(key)
        elif health in {ModelHealth.CORRUPT, ModelHealth.INCOMPATIBLE}:
            corrupt.append(key)
    return StartupModelPreflight(
        installed_count=registry.installed_count(),
        required_keys=required,
        missing_keys=tuple(missing),
        corrupt_keys=tuple(corrupt),
    )


def _show_error(title: str, message: str) -> None:
    """Display a startup error even when the app was launched by pythonw."""
    try:
        QMessageBox.critical(None, title, message)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            pass


def _register_bundled_fonts() -> None:
    """Register bundled Source Han Sans OTFs so every machine renders alike."""
    from PySide6.QtGui import QFontDatabase
    root = Path(__file__).resolve().parents[2]
    candidates = [root / "assets" / "fonts", root / "tools" / "fonts"]
    found = 0
    for directory in candidates:
        if not directory.is_dir():
            continue
        for font_path in sorted(directory.glob("*.otf")) + sorted(directory.glob("*.ttf")):
            try:
                QFontDatabase.addApplicationFont(str(font_path))
                found += 1
            except Exception:
                pass
    if found:
        print(f"[fonts] registered {found} bundled font file(s)")


def _app_font() -> QFont:
    from twobyteasr.design.typography import application_font
    return application_font()


def _acquire_instance_lock():
    """Return the pingable GUI ownership endpoint, or ``None`` if it is live."""
    from twobyteasr.app.single_instance import SingleInstanceGuard

    guard = SingleInstanceGuard(SingleInstanceGuard.application_name())
    if not guard.acquire():
        return None
    return guard


def _completion_notification_spec(result, outcomes=None):
    """Use the same terminal model as completion, reports and history."""
    from ..recognition.recognition_outcome import normalize_recognition_outcome, normalize_recognition_queue
    if outcomes is None:
        outcomes = []
        for item in result.results:
            payload = None
            if item.report_json_path:
                try:
                    payload = json.loads(Path(item.report_json_path).read_text(encoding='utf-8-sig'))
                except (OSError, ValueError, TypeError):
                    pass
            if not isinstance(payload, dict):
                payload = dict(status=item.status, result=dict(outputs=dict(project=item.project_path, srt=item.srt_path)))
                if item.error and item.status == 'failed':
                    payload['result']['error'] = item.error
            outcomes.append(normalize_recognition_outcome(payload))
    queue = normalize_recognition_queue(outcomes)
    icon = {'error': QMessageBox.Icon.Critical, 'warning': QMessageBox.Icon.Warning,
            'information': QMessageBox.Icon.Information}[queue.notification_level]
    message = tr('完成 {completed} 个 · 部分完成 {partial} 个 · 失败 {failed} 个 · 取消 {cancelled} 个',
        completed=queue.completed_count, partial=queue.partial_count, failed=queue.failed_count, cancelled=queue.cancelled_count)
    details = tr('待检查问题 {review} 项 · 联网核验未完成或未执行 {search} 个任务',
        review=queue.review_issue_count, search=queue.search_incomplete_count)
    return tr(queue.title), message, icon, details


def _configure_windows_app_identity() -> None:
    """Give the Qt window its own taskbar identity instead of Python's icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "2ByteASR.Desktop.2026"
        )
    except (AttributeError, OSError):
        pass


from .progress_widgets import _ElidedValue as ElidedValueLabel
from .progress_widgets import (ElidedRowsLabel, FeedList, ProgressPhaseCard, RecognitionPreview, ResizeWatcher,
                               RunningIndicator, StageMetricGrid, StageProgressBar, TaskEventCard, log_line_html,
                               progress_page_qss)
from ..i18n import join_text
from .recognition_status_text import recognition_event_text


def _secret_save_trace(stage: str, editor, values: dict, *, extra: dict | None = None) -> None:
    """A1 Secret Save Trace (P8C-R3.1): field states around save, never the key."""
    if os.environ.get("TWOBYTEASR_SECRET_TRACE", "") != "1":
        return
    try:
        from twobyteasr.runtime_paths import user_data_root
        from urllib.parse import urlsplit as _urlsplit

        provider = str(values.get("provider") or "")
        base_url = str(values.get("base_url") or "")
        stored, source = read_api_key(provider, base_url)
        settings_ref = getattr(editor, "_settings_ref", None)
        settings_view = settings_ref if isinstance(settings_ref, dict) else {"models": {}, "switches": {}}
        endpoint = endpoint_from_settings(settings_view, editor.stage)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trace_stage": stage,
            "editor_stage": editor.stage,
            "provider_id": provider,
            "base_url": base_url,
            "model": values.get("model", ""),
            "secret_ref": ((provider.lower().replace(" ", "_") + "__" + (_urlsplit(base_url).netloc or "")) if base_url else provider),
            "secret_source": source,
            "resolver_has_secret": bool(stored),
            "runtime_auth_present": bool(endpoint.get("api_key")),
            "api_key_widget_text_length": len(values.get("key") or ""),
            "api_key_widget_display_state": "placeholder-configured" if "已配置" in editor.key.placeholderText() else "placeholder-empty",
            "api_key_widget_state": values.get("key_state", "unchanged"),
            "clear_requested": values.get("key_state") == "clear",
        }
        if extra:
            row.update(extra)
        logs = Path(user_data_root()) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "secret_save_trace.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def persist_ai_configuration(
    legacy,
    polish: dict,
    group: dict,
    *,
    unified: bool,
    share_key: bool,
    require_ready: bool,
    use_ai_grouping: bool = True,
    enable_ai_polish: bool = True,
    dry_run: bool = False,
    prefer_arabic_numbers: bool | None = None,
    local_without_key: bool = False,
) -> dict:
    """Validate and persist AI form values without requiring a subtitle run.

    ``local_without_key`` (2026-10-15, a run start): an enabled step whose key
    was never filled in is not an error; it is returned in ``local_roles`` and
    that run uses the local rules for it. Other endpoint errors still raise.
    """
    use_ai_grouping = bool(use_ai_grouping)
    enable_ai_polish = bool(enable_ai_polish)
    unified = bool(unified and use_ai_grouping and enable_ai_polish)
    polish = dict(group) if unified else dict(polish)
    group = dict(group)
    polish_key = str(polish.get("key", "") or "").strip()
    group_key = str(group.get("key", "") or "").strip()
    existing_polish_key = read_api_key(
        polish.get("provider", "custom"), polish.get("base_url", "")
    )[0] if enable_ai_polish and polish.get('key_state') != 'clear' else ""
    if enable_ai_polish and polish.get('key_state') != 'clear' and not existing_polish_key and polish.get("provider") in {"bailian", "dashscope"}:
        existing_polish_key = resolve_api_key("polish")[0]
    existing_group_key = read_api_key(
        group.get("provider", "custom"), group.get("base_url", "")
    )[0] if (use_ai_grouping or unified) and group.get('key_state') != 'clear' else ""
    if use_ai_grouping and group.get('key_state') != 'clear' and not existing_group_key and group.get("provider") in {"bailian", "dashscope"}:
        existing_group_key = resolve_api_key("group")[0]
    effective_polish_key = (
        group_key or existing_group_key
        if unified
        else polish_key or existing_polish_key
    )
    effective_group_key = (
        polish_key
        if share_key and not unified and polish_key
        else group_key or existing_group_key
    )
    missing_keys = []
    local_roles = []
    endpoints = [("polish", "字幕校对模型", polish, effective_polish_key)] if enable_ai_polish else []
    if use_ai_grouping:
        endpoints.append(("group", "全文断句模型", group, effective_group_key))
    for role, label, values, api_key in endpoints:
        if values.get("transport", AITransport.OPENAI_COMPATIBLE.value) == AITransport.OPENAI_COMPATIBLE.value:
            from ..providers.llm_config import endpoint_requires_key
            if not api_key and endpoint_requires_key(values):
                missing_keys.append(label)
                if local_without_key:
                    local_roles.append(role)
                    continue
            validate_endpoint(
                {
                    **values,
                    "api_key": api_key,
                },
                label,
                require_credentials=require_ready,
            )
    models = {
        "polish_transport": polish.get("transport", AITransport.OPENAI_COMPATIBLE.value),
        "polish_protocol": polish.get("protocol", "auto"),
        "polish_provider": polish["provider"],
        "polish_model": polish["model"],
        "polish_base_url": polish["base_url"],
        "group_transport": group.get("transport", AITransport.OPENAI_COMPATIBLE.value),
        "group_protocol": group.get("protocol", "auto"),
        "group_provider": group["provider"],
        "group_model": group["model"],
        "group_base_url": group["base_url"],
    }
    # Active service + per-provider profile: the profile store is the single
    # source of truth for provider endpoint state; the flat fields above are
    # the resolved active view consumed by the request path. In unified mode
    # polish already holds the (authoritative) group editor values.
    active_service = str(polish.get("service") or "")
    if active_service in AI_SERVICE_SPECS:
        profile_view = {
            "models": copy.deepcopy(getattr(legacy, "RUNTIME_SETTINGS", {}).get("models", {})),
            "switches": {"unified_glm_processing": bool(unified)},
        }
        activate_ai_service(
            profile_view, active_service, stage="polish", unified=bool(unified)
        )
        update_active_profile(
            profile_view,
            stage="polish",
            base_url=models["polish_base_url"],
            model=models["polish_model"],
            protocol=models["polish_protocol"],
            json_mode=polish.get('json_mode', True),
            structured_output=polish.get('structured_output', True),
            unified=bool(unified),
        )
        models["ai_service"] = active_service
        models["provider_profiles"] = profile_view["models"].get("provider_profiles", {})
    for stage, values in (('polish', polish), ('group', group)):
        models[f'{stage}_json_mode'] = bool(values.get('json_mode', True))
        models[f'{stage}_structured_output'] = bool(values.get('structured_output', True))
    if dry_run:
        return {"models": models, "unified": unified, "missing_keys": tuple(missing_keys),
                "local_roles": tuple(local_roles)}
    # Validate first. A failed secret write is a failed save, never swallowed.
    for values in (polish, group):
        if values.get('key_state') == 'clear':
            delete_api_key_for(values.get('provider', 'custom'), values.get('base_url', ''))
    if polish_key and models["polish_transport"] == AITransport.OPENAI_COMPATIBLE.value:
        save_api_key_for(polish["provider"], polish["base_url"], polish_key)
    if group_key and models["group_transport"] == AITransport.OPENAI_COMPATIBLE.value:
        save_api_key_for(group["provider"], group["base_url"], group_key)
    elif share_key and polish_key and use_ai_grouping:
        save_api_key_for(group["provider"], group["base_url"], polish_key)
    number_option = {} if prefer_arabic_numbers is None else {'prefer_arabic_numbers': prefer_arabic_numbers}
    legacy.configure_runtime_llms(
        models,
        polish_key=("" if unified else polish_key),
        group_key=group_key,
        share_key=(share_key and use_ai_grouping and not unified),
        unified_glm_processing=unified,
        use_ai_grouping=use_ai_grouping,
        enable_ai_polish=enable_ai_polish,
        **number_option,
    )
    live_runtime = getattr(legacy, "RUNTIME_SETTINGS", None)
    if isinstance(live_runtime, dict):
        GLOBAL_PROVIDER_REGISTRY.bind(live_runtime)
        from ..providers.ai_config_state import trace_configuration
        trace_configuration('persisted', live_runtime)
    # 结构化留痕（绝不含密钥）：对照 UI 展示值与磁盘/运行时实际生效值。
    try:
        print(
            "[AI_CONFIG_SAVED] "
            f"service={active_service or 'custom'} "
            f"provider={group.get('provider', '')} "
            f"model={group.get('model', '')} "
            f"polish_model={polish.get('model', '')} "
            f"unified={int(bool(unified))} use_ai_grouping={int(use_ai_grouping)}",
            flush=True,
        )
    except Exception:
        pass
    return {"models": models, "missing_keys": tuple(missing_keys), "local_roles": tuple(local_roles)}


def text_ai_roles_without_key(legacy, polish: dict, group: dict, *, unified: bool, share_key: bool) -> tuple:
    """The text-AI steps that cannot run because no API key is filled in (2026-10-21).

    Asked as if each step were switched on, so the answer does not depend on
    the switches it is used to show. A key typed into the form counts, as do
    CLI logins and endpoints that need no key. Any other configuration error
    is not "no key" (saving reports it), so that step is left out.
    """
    missing = []
    for role in ("polish", "group"):
        try:
            result = persist_ai_configuration(
                legacy, polish, group, unified=unified, share_key=share_key, require_ready=False,
                use_ai_grouping=bool(unified) or role == "group",
                enable_ai_polish=bool(unified) or role == "polish",
                dry_run=True, local_without_key=True)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            continue
        if role in result["local_roles"]:
            missing.append(role)
    return tuple(missing)


def persist_asr_configuration(
    legacy,
    values: dict,
    *,
    qwen_key: str = "",
    require_ready: bool = False,
) -> dict:
    """Validate and persist local/API ASR backend choices."""
    models = {
        "primary_asr_backend": str(values.get("primary_asr_backend", "moss")),
        "qwen_asr_backend": str(values.get("qwen_asr_backend", "local")),
        "qwen_asr_model": str(values.get("qwen_asr_model", "Qwen/Qwen3-ASR-1.7B")),
        "qwen_asr_api_provider": str(values.get("qwen_asr_api_provider", "qwen31_filetrans")),
        "qwen_asr_api_protocol": str(values.get("qwen_asr_api_protocol", "dashscope_filetrans")),
        "qwen_asr_api_model": str(values.get("qwen_asr_api_model", "qwen-audio-3.1-asr-flash-filetrans")),
        "qwen_asr_api_url": str(values.get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"])).rstrip("/"),
        "firered_asr_backend": str(values.get("firered_asr_backend", "local")),
        "api_transcribe_style": str(values.get("api_transcribe_style", "clean") or "clean"),
        "speaker_source": str(values.get("speaker_source", legacy.RUNTIME_SETTINGS.get('models',{}).get('speaker_source','single')) or 'single'),
    }
    from ..recognition.speaker_strategy import resolve
    resolve({'models':models})
    if models["api_transcribe_style"] not in {"clean", "verbatim"}:
        raise RuntimeError("转写风格选项无效。")
    if models["primary_asr_backend"] not in {
        "moss", "firered", "qwen_local", "firered_llm", "whisper_turbo", "sensevoice",
        "paraformer", "funasr_nano", "glm_asr_nano", "canary_qwen", "mlx_qwen3_asr",
        "mlx_qwen3_asr_1_7b", "api", "none",
    }:
        raise RuntimeError("主力转写后端选项无效。")
    if models["qwen_asr_backend"] not in {
        "api", "local", "firered_llm", "whisper_turbo", "sensevoice", "funasr_nano", "off"
    }:
        raise RuntimeError("文字复核后端选项无效。")
    # A saved user deployment can outlive a removed preset. Retain its exact
    # provider/protocol ownership; do not silently select another service.
    saved_models = legacy.RUNTIME_SETTINGS.get("models", {})
    retained_endpoint = (models["qwen_asr_api_provider"] == saved_models.get("qwen_asr_api_provider")
                         and models["qwen_asr_api_protocol"] == saved_models.get("qwen_asr_api_protocol"))
    if models["qwen_asr_api_provider"] not in ASR_API_PRESETS and not retained_endpoint:
        raise RuntimeError("ASR API 服务商选项无效。")
    if models["qwen_asr_api_protocol"] not in {
        "dashscope_multimodal", "openai_transcription", "azure_transcription",
        "openrouter_verbose_json", "dashscope_filetrans", "dashscope_asr_flash", "spark_wss",
        "mosi_transcriptions",
    }:
        raise RuntimeError("ASR API 协议选项无效。")
    if models["firered_asr_backend"] not in {"local", "qwen_aligner", "mlx_qwen_aligner", "mfa_aligner", "whisper_turbo", "paraformer", "off"}:
        raise RuntimeError("字幕时间轴后端选项无效。")
    missing_keys = []
    if models["qwen_asr_backend"] == "api" or models["primary_asr_backend"] == "api":
        from ..providers.llm_config import read_asr_api_key

        existing_key = read_asr_api_key(
            models["qwen_asr_api_provider"], models["qwen_asr_api_url"]
        )[0]
        effective_key = str(qwen_key or "").strip() or existing_key
        from ..providers.llm_config import read_spark_credentials
        spark=read_spark_credentials(models['qwen_asr_api_url']) if models['qwen_asr_api_protocol']=='spark_wss' else {}
        if spark:effective_key=spark['api_key']
        validate_qwen_asr_endpoint(
            {
                "provider": models["qwen_asr_api_provider"],
                "protocol": models["qwen_asr_api_protocol"],
                "model": models["qwen_asr_api_model"],
                "url": models["qwen_asr_api_url"],
                "api_key": effective_key,
                **spark,
            },
            require_key=require_ready,
        )
        if not effective_key or (spark and not all(spark.values())):
            missing_keys.append("ASR API Key")
    legacy.configure_runtime_asr(models, qwen_asr_key=qwen_key)
    return {"models": models, "missing_keys": tuple(missing_keys)}


def api_help_popover_qss(theme) -> str:
    """Theme-token stylesheet for the ASR API help popover."""

    return (
        f"QFrame#apiHelpPopover {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 10px; }}"
        f"QLabel {{ color: {theme.text}; }}"
        f"QPushButton#helpLink {{ background: transparent; border: 0; color: {theme.accent}; padding: 2px 4px; }}"
        f"QPushButton#helpLink:hover {{ text-decoration: underline; }}"
        f"QPushButton#helpCloseX {{ background: transparent; border: 0; color: {theme.text_muted}; font-size: 16px; padding: 2px 6px; }}"
        f"QPushButton#helpCloseX:hover {{ color: {theme.text}; background: {theme.surface_muted}; border-radius: 8px; }}"
    )


# Role-card statuses meaning "this computer cannot run it" (recognition_choices.unavailable_on_host).
_HOST_LIMIT_STATUSES = frozenset({"需要 NVIDIA 显卡", "只能在 Apple Silicon Mac 上运行"})
_HOST_LIMIT_RECOVERY = "换成能用的方式"


def studio_translation_choice(language_options: dict, studio_context: dict, ai_ready: bool) -> dict:
    """The run's language options with the Studio sheet's translation choice (2026-10-23).

    The 识别字幕 sheet picks 原文 / 双语 / 只显示翻译 and the target for that one
    run; the home choice stays as it is. Translating still needs a connected AI.
    """
    options = dict(language_options)
    output = str((studio_context or {}).get("subtitle_output") or "")
    if output:
        options["subtitle_output"] = output if ai_ready else "original"
        target = str((studio_context or {}).get("translation_script") or "")
        if target:
            options["translation_script"] = target
    return options


def _bind_home_shortcuts(window, owner):
    """Home keys from the shared registry: start, choose media, search (2026-10-13).

    The shortcuts belong to the home action bar, which is only visible on
    the home page, so Studio keys such as Ctrl+K stay with Studio.
    """
    from PySide6.QtGui import QShortcut
    from ..studio import shortcut_registry as keys

    def start_key(key):
        window.start_button.setShortcut(QKeySequence(key))
        window._start_run_key = key  # the readiness bar rewrites this tooltip
        bind_text(window.start_button, '开始生成字幕 ({key})', property='toolTip',
                  key=keys.display(key) if key else tr('未绑定'))
        if getattr(window, "_last_plan_items", None) is not None:
            window._refresh_readiness_bar(window._last_plan_items)  # keeps "先选择素材…" while no media

    choose = QShortcut(QKeySequence("Ctrl+O"), owner)
    choose.setContext(Qt.ShortcutContext.WindowShortcut)
    choose.activated.connect(lambda: window._choose_media() if window._home_page_active() else None)
    search = QShortcut(QKeySequence("Ctrl+K"), owner)
    search.setContext(Qt.ShortcutContext.WindowShortcut)
    search.activated.connect(lambda: window._open_feature_search() if window._home_page_active() else None)
    # 2026-10-17: the same button as the studio card; settings from any page
    # of the main window (owner = the window, not the home action bar).
    studio = QShortcut(QKeySequence(), owner)
    studio.setContext(Qt.ShortcutContext.WindowShortcut)
    studio.activated.connect(lambda: window.open_studio_project() if window._home_page_active() else None)
    settings = QShortcut(QKeySequence("Ctrl+,"), window)
    settings.setContext(Qt.ShortcutContext.WindowShortcut)

    def open_settings():
        modal = getattr(window, "_modal_host", None)
        if not (modal is not None and modal.isVisible()):
            window._open_application_settings()
    settings.activated.connect(open_settings)
    window._home_shortcuts = (choose, search, studio, settings)
    keys.keep_keys({"home.start_run": start_key, "home.choose_media": choose, "home.search": search,
                    "home.open_studio": studio, "app.open_settings": settings})


class MainWindow(QWidget):
    # 2026-10-13: background results for the home "现在先做什么" card and the example project.
    _onboarding_facts_ready = Signal(object)
    _sample_ready = Signal(object)

    def __init__(self, media_paths, legacy, pipeline, startup_self_test, *, startup_page="recognition"):
        super().__init__()
        # The light loading surface now exists before Studio. Establish the
        # existing native-child policy before any shell child becomes native,
        # otherwise Qt promotes its ordinary siblings into separate HWNDs.
        from ..design.native_surfaces import isolate_native_children
        isolate_native_children()
        self._onboarding_facts_ready.connect(self._onboarding_facts_received)
        self._sample_ready.connect(self._sample_project_ready)
        self._workshop_page_instance = None
        self._history_page_instance = None
        self._studio_page_instance = None
        self.media_paths = list(media_paths)
        self.legacy = legacy
        self.pipeline = pipeline
        self.startup_self_test = startup_self_test
        from ..diagnostics.navigation_timing import install_shutdown_flush
        install_shutdown_flush(QApplication.instance())
        self._recognition_page_deferred = startup_page == "project_library"
        self.profile_store = ProjectProfileStore()
        self.current_project_profile: ProjectProfile | None = None
        # 方案切换守卫与脏标：_applying_profile 期间控件信号不标记脏、不回写方案。
        self._applying_profile = False
        self._asr_config_dirty = False
        self.token = None
        self.worker = None
        self.update_check_worker = None
        self.update_download_worker = None
        self._available_update = None
        self._prepared_update = None
        self._pending_update = None
        self.started_at = 0.0
        self.result_exit_code = 0
        # P1-4：active run 重入守卫。preparing / runtime checking / worker
        # starting / worker running / cancelling 任一状态为 True；由
        # _release_run_state 统一释放。不能用 worker.isRunning() 代替——
        # worker 创建前（CUDA 探测等准备阶段）isRunning 为 False。
        self._run_in_progress = False
        # 四十二轮：_start_run 早退原因（Studio 后台识别把它显示到字幕列表芯片）。
        self._run_block_reason = ""
        self._glossary_binding = None
        self._media_input_cards: dict[str, QWidget] = {}
        self._completion_dialog = None
        self._support_dialog = None
        self.setAcceptDrops(True)
        self.setObjectName("appRoot")
        # Frameless but fully resizable (P0). Custom titlebar + edge resize.
        # 2026-10-15: the system menu and min/max styles keep the native
        # fallbacks a frameless popup lacked (taskbar click minimizes,
        # Win+Up/Down, Alt+Space) for when the title buttons are out of reach.
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        bind_text(self, tr('2ByteASR  兔白字幕') + ('【隔离测试】' if os.environ.get('TWOBYTEASR_TEST_ROOT') else ''), property='windowTitle')
        self.setWindowIcon(_app_icon())
        self.setMinimumSize(900, 500)
        self.resize(1320, 880)
        self.setMouseTracking(True)
        # Logical-pixel resize hit areas. Native Windows hit testing scales
        # these values before comparing them with physical screen coordinates.
        self._resize_border = 8
        self._resize_corner = 12
        self._resize_edge = None  # one of: 'left','right','top','bottom','tl','tr','bl','br'
        self._resize_start_geom = None
        self._resize_start_pos = None
        self._density_comfortable = None
        self._gui_profiler = None
        if GUI_PROFILE_ENABLED:
            try:
                from twobyteasr.diagnostics.gui_performance import GuiPerformanceProfiler

                self._gui_profiler = GuiPerformanceProfiler(
                    QApplication.instance(), APP_ROOT / "reports" / "gui-performance", self
                )
                self._gui_profiler.start()
            except Exception as exc:
                print(f"[perf] GUI profiler unavailable: {exc}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        content_host = QWidget()
        content_host.setObjectName("appContent")
        content = QVBoxLayout(content_host)
        self.content_layout = content
        content.setContentsMargins(18, 12, 18, 14)
        content.setSpacing(12)
        # Keep the existing task-state sink, but remove the obsolete hover
        # workflow strip from the visible layout.
        self.workflow = WorkflowStrip(self)
        self.workflow.hide()
        self._workflow_expanded = False
        # Ensure resize cursors are respected over titlebar area too
        try:
            self.window_title_bar.setMouseTracking(True)
        except Exception:
            pass
        self.pages = QStackedWidget(content_host)
        if sys.platform == 'win32':
            self.pages.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            self.pages.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.settings_scroll = self._scrollable(
            QWidget() if self._recognition_page_deferred else self._settings_page())
        self.pages.addWidget(self.settings_scroll)
        self.pages.addWidget(self._progress_page())
        self.pages.addWidget(self._result_page())
        # 2026-10-10 启动：模型工坊、识别记录与 Studio 共占启动时约 82% 的控件
        # （识别记录随报告数增长），首页用不到。第一次进入时才构造（见
        # workshop_page / history_page / studio_page 属性）；被动检查用
        # built_page()，不会因此把整页建出来。
        self.term_library_page = TermLibraryPage(self)
        self.term_library_page.recognition_requested.connect(self._return_to_settings)
        self.term_library_page.workshop_requested.connect(self._open_model_workshop)
        self.term_library_page.history_requested.connect(self._open_recognition_history)
        self.pages.addWidget(self.term_library_page)
        self._studio_recognition_context = None
        content.addWidget(self.pages, 1)
        # P1: 底部“取消 / 开始生成字幕”固定在主页面底部，不随中间内容滚动。
        # 无论窗口高度如何（1366x768 / 1920x1080 / 2560x1440），CTA 始终可见。
        # 只有在设置页（index 0）才显示该 bar；进度/结果页使用各自的控制。
        if getattr(self, "bottom_bar", None) is None:
            self.bottom_bar = self._action_bar()
        self.settings_action_bar = self.bottom_bar
        content.addWidget(self.bottom_bar, 0)
        self.bottom_bar.setVisible(True)
        root.addWidget(content_host, 1)
        self.pages.currentChanged.connect(self._page_changed)
        self.pages.currentChanged.connect(self._update_bottom_bar_visibility)
        # Apply sane default geometry once (after construction) to avoid tiny/offscreen windows.
        QTimer.singleShot(0, self, self._apply_sane_initial_geometry)
        from ..storage.storage_ui import IdleStorageMaintenance
        self._storage_maintenance = IdleStorageMaintenance(self)
        self.drop_overlay = DropOverlay(self)
        self.drop_overlay.setGeometry(self.rect().adjusted(16, 16, -16, -16))
        self.drop_overlay.hide()

        # P0: internal modal host for all app popups (picker, term library, technical, edit/delete, smart build).
        # Eliminates new top-level native windows (no extra HWND black flash). Backdrop fade only; card is final-size opaque.
        self._modal_host = ModalHost(self)
        self._modal_host.setGeometry(self.rect())
        self._modal_host.hide()
        # Safe slot for ModalHost.closed; per-show on_closed callbacks are handled inside show_content/hide_content.
        self._modal_host.closed.connect(self._on_modal_closed)
        # Click-to-first-paint measurement support (mouse timestamp provided by caller).
        self._popup_click_ts = None
        self._popup_first_paint_title = ""

        if not self._recognition_page_deferred:
            self._refresh_media_summary()
            self._apply_saved_ai_configuration(source='startup')
        self._create_resize_handles()
        self._apply_ui_language()
        self._encoder_capability_cancel = threading.Event()
        self._encoder_capability_worker = None
        self._startup_background_ready_thread = None
        # P0: background preload of model install status + term index after first paint.
        # Never on click path; cheap FS/metadata only. No spinners.
        if self._recognition_page_deferred:
            self.open_studio_project(source='startup_library')
        else:
            QTimer.singleShot(0, self, self._background_preload)
            QTimer.singleShot(0, self, self._restore_last_project_profile)
        # Local MCP access (2026-10-12, off by default): one settings read;
        # the pipe and its modules load only when the user turned it on.
        QTimer.singleShot(0, self, self._start_mcp_bridge)

    def _start_mcp_bridge(self):
        try:
            from ..local_mcp.mcp_common import read_settings
            if read_settings().get("enabled"):
                from ..local_mcp.mcp_bridge import start_if_enabled
                start_if_enabled(self)
        except Exception as exc:  # noqa: BLE001 - the editor must open regardless
            print(f"[MCP] 本机访问未启动：{exc}", file=sys.stderr)

    def _set_brand_text(self):
        self.brand.setText(
            f'<span style="font-size:{ui_zoom.px(26)}px; font-weight:800;">2</span>'
            f'<span style="font-size:{ui_zoom.px(23)}px; font-weight:800;">ByteASR</span>'
        )

    def apply_ui_zoom(self, _factor):
        """Interface zoom changed: rich-text brand sizes and the home card band."""
        if hasattr(self, "brand"):
            self._set_brand_text()
        self._refresh_header_density()
        # Zoomed pages may need more width than a small window has: scroll
        # sideways rather than clip. At 100% the pages keep their policy.
        policy = (Qt.ScrollBarPolicy.ScrollBarAlwaysOff if ui_zoom.zoom_percent() == ui_zoom.DEFAULT_PERCENT
                  else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for area in getattr(self, "_page_scroll_areas", ()):
            area.setHorizontalScrollBarPolicy(policy)
        if hasattr(self, "recognition_plan"):
            self.apply_density()

    def built_page(self, name: str):
        """The lazily built page ``name`` if it exists; never builds it."""
        return getattr(self, f"_{name}_page_instance", None)

    @property
    def workshop_page(self):
        page = getattr(self, "_workshop_page_instance", None)
        return page if page is not None else self._build_lazy_page("workshop")

    @workshop_page.setter
    def workshop_page(self, page):
        self._workshop_page_instance = page

    @property
    def history_page(self):
        page = getattr(self, "_history_page_instance", None)
        return page if page is not None else self._build_lazy_page("history")

    @history_page.setter
    def history_page(self, page):
        self._history_page_instance = page

    @property
    def studio_page(self):
        page = getattr(self, "_studio_page_instance", None)
        return page if page is not None else self._build_lazy_page("studio")

    @studio_page.setter
    def studio_page(self, page):
        self._studio_page_instance = page

    def _build_lazy_page(self, name: str):
        if name == 'studio' and (self.__dict__.get('_studio_page_building') is not None
                                  or self.__dict__.get('_studio_entry_pending') is not None):
            raise RuntimeError('Studio construction is pending; use built_page() or the ready callback')
        queued = False
        # First visit builds the page (0.5-2 s with many reports): show the
        # busy cursor at once instead of an unexplained pause after the click.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = self._construct_lazy_page(name)
        finally:
            QApplication.restoreOverrideCursor()
        if queued:
            request, self._studio_entry_pending = self.__dict__.get('_studio_entry_pending'), None
            if request is not None:
                path, options = request
                self.open_studio_project(path, **options)
        return page

    def _construct_lazy_page(self, name: str, prepared=None):
        started = time.perf_counter()
        if name == "workshop":
            page = ModelWorkshopPage(APP_ROOT, self.legacy.RUNTIME_SETTINGS, self)
            self._workshop_page_instance = page
            page.return_requested.connect(self._return_to_settings)
            page.terms_requested.connect(self._open_terms_from_workshop)
            page.history_requested.connect(self._open_recognition_history)
            page.task_settings_requested.connect(self._open_task_settings_from_workshop)
            page.ai_segmentation_requested.connect(self._open_ai_from_workshop)
            page.update_requested.connect(self._check_updates)
            page.api_config_requested.connect(self._open_qwen_api_from_workshop)
            page.api_preset_requested.connect(self._apply_asr_api_preset)
            page.api_configure_requested.connect(self._open_api_setup_guide)
            page.backend_requested.connect(self._apply_workshop_backend)
            page.auto_stage_changed.connect(self._timeline_helper_changed)
            if self._density_comfortable is not None:
                page.apply_density(self._density_comfortable)
        elif name == "history":
            # Reports live in the stable user-data root; the install tree (and
            # any legacy roots) are still scanned so history survives rebuilds.
            from ..recognition import reporting as _reporting

            page = RecognitionHistoryPage(
                _reporting.REPORT_ROOT,
                self,
                extra_roots=_reporting.LEGACY_REPORT_ROOTS,
            )
            self._history_page_instance = page
            page.recognition_requested.connect(self._return_to_settings)
            page.workshop_requested.connect(self._open_model_workshop)
            page.terms_requested.connect(self._open_terms_from_history)
            page.result_requested.connect(self._open_completion_from_history)
            page.diagnose_requested.connect(self._open_history_diagnosis)
        elif name == "studio":
            # Imported on first use (or by the idle warm-up after startup):
            # the Studio module tree is ~0.5 s of the home page's start.
            from twobyteasr.studio.studio_ui import SubtitleStudioPage
            page = prepared if prepared is not None else SubtitleStudioPage(self)
            self._studio_page_instance = page
            page.return_requested.connect(self._return_to_settings)
            page.glossary_proofread_requested.connect(self._open_studio_glossary_proofread)
            page.close_ready_signal.connect(self._finish_studio_close)
            page.recognition_requested.connect(self._handle_studio_recognition_request)
            # 四十二轮：左侧字幕列表状态芯片上的"取消识别"→ 主窗口取消令牌。
            page.recognition_cancel_requested.connect(self._cancel_run)
            # 四十三轮："查看详细进度"→ 跳主页识别进度页（识别继续后台跑）。
            page.recognition_detail_requested.connect(self._show_studio_recognition_detail)
        else:
            raise KeyError(name)
        self.pages.addWidget(page)
        _startup_mark(f"LAZY_{name.upper()}_PAGE_BUILT",
                      duration_ms=round((time.perf_counter() - started) * 1000, 1))
        return page

    def _ensure_recognition_page(self):
        """Build recognition controls only when the user enters that workflow."""
        if not self._recognition_page_deferred:
            return
        self._recognition_page_deferred = False
        previous = self.settings_scroll.takeWidget()
        self.settings_scroll.setWidget(self._settings_page())
        if previous is not None:
            previous.deleteLater()
        self._refresh_media_summary()
        self._apply_saved_ai_configuration(source='home_created')
        self._apply_ui_language()
        self._restore_last_project_profile()
        QTimer.singleShot(0, self, self._background_preload)

    def _on_modal_closed(self):
        # Lightweight hook for global post-close housekeeping if needed.
        # Individual show_content callers supply their on_closed callback.
        pass

    def retranslate_ui(self):
        # refresh_application() calls this from inside _apply_ui_language(),
        # which has just done the same pass; repeating it walked the whole
        # window tree and refreshed every page a second time.
        if getattr(self, "_applying_ui_language", False):
            return
        self._apply_ui_language(refresh_all=False)

    def _apply_ui_language(self, *, refresh_all=True):
        # 冻结启动：早期 import 链可能把"设置就绪前"的默认语言(zh)读进缓存，
        # 这里强制失效重读，保证已保存的界面语言在启动时就生效（2026-09-19）。
        from ..i18n import invalidate_language_cache
        from ..diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE

        invalidate_language_cache()
        code = current_language()
        GLOBAL_STUDIO_TRACE.emit(
            "STARTUP_LANGUAGE",
            {
                "language": code,
                "combo_current": str(
                    (getattr(self, "language_combo", None) and self.language_combo.currentData()) or ""
                ),
            },
        )
        # 语言下拉选中态与生效语言同步（下拉构建可能早于本函数且读到了旧缓存）。
        if hasattr(self, "language_combo"):
            index = self.language_combo.findData(code)
            if index >= 0 and index != self.language_combo.currentIndex():
                self.language_combo.blockSignals(True)
                self.language_combo.setCurrentIndex(index)
                self.language_combo.blockSignals(False)
        self._ui_language = code
        if hasattr(self, "phase_cards") and hasattr(self, "_active_stages"):
            self._refresh_progress_cards()
            self._update_progress_clock()
        bind_text(self, tr('2ByteASR  兔白字幕') + ('【隔离测试】' if os.environ.get('TWOBYTEASR_TEST_ROOT') else ''), property='windowTitle')
        if hasattr(self, "window_title_bar"):
            self.window_title_bar.set_title(
                tr("2ByteASR  兔白字幕")
            )
        apply_ui_language(self, code)
        if getattr(self, '_completion_tasks', None):
            self._select_completion_task(self.result_task_selector.currentIndex())
        self._refresh_project_profile_combo()
        if hasattr(self, "recognition_plan"):
            self.recognition_plan.retranslate(code)
            self._refresh_asr_summary()
        if hasattr(self, "_refresh_ai_summary"):
            self._refresh_ai_summary()
        workshop = self.built_page("workshop")
        if workshop is not None:
            workshop.refresh()
            for technical in workshop._technical_cache.values():
                technical.retranslate(code)
        history = self.built_page("history")
        if history is not None:
            history.refresh()
        if (
            hasattr(self, "term_library_page")
            and self.term_library_page.library is not None
        ):
            library = self.term_library_page.library
            library.refresh_current_game()
            apply_ui_language(library, code)
        if hasattr(self, "pages"):
            for index in range(self.pages.count()):
                self.pages.widget(index).setProperty("_2b_language_applied", code)
        if hasattr(self, "_refresh_studio_entry_card"):
            self._refresh_studio_entry_card()
        from ..i18n_widgets import refresh_application
        if refresh_all:
            self._applying_ui_language = True
            try:
                refresh_application(code)
            finally:
                self._applying_ui_language = False
        if hasattr(self, "language_combo"):
            self._refresh_header_density()

    def _change_language(self, index):
        code = self.language_combo.itemData(index) or "zh"
        save_language(code)

    def _scrollable(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        self._page_scroll_areas = getattr(self, "_page_scroll_areas", []) + [area]
        return area

    def _schedule_ai_panel_visibility(self, expanded: bool):
        if not (hasattr(self, "settings_page_widget") and self.settings_page_widget.isAncestorOf(self.ai_panel)
                and self.ai_panel.isVisible()):
            return
        if hasattr(self, "settings_page_layout"):
            self.settings_page_layout.setContentsMargins(0, 0, 0, 40 if expanded else 0)
        if expanded:
            QTimer.singleShot(0, self, self._ensure_ai_panel_visible)
            duration = getattr(getattr(self, "ai_panel", None), "animation", None)
            QTimer.singleShot(
                (duration.duration() if duration is not None else 180) + 20,
                self._ensure_ai_panel_visible,
            )

    def _ensure_ai_panel_visible(self):
        """Keep the expanded AI form in view after its layout height settles."""
        if not (
            hasattr(self, "settings_scroll")
            and hasattr(self, "ai_panel")
            and self.ai_panel._expanded
            and self.ai_panel.isVisible()
            and self.settings_page_widget.isAncestorOf(self.ai_panel)
        ):
            return
        # The tile is the visible header of the in-place form.
        anchor = self.setting_tiles["ai"] if hasattr(self, "setting_tiles") else self.ai_panel
        self.settings_scroll.ensureWidgetVisible(anchor, 24, 24)
        panel_top = anchor.mapTo(self.settings_page_widget, QPoint(0, 0)).y()
        scroll_bar = self.settings_scroll.verticalScrollBar()
        scroll_bar.setValue(
            min(scroll_bar.maximum(), max(scroll_bar.minimum(), panel_top - 12))
        )
        if hasattr(self, "polish_editor"):
            self.settings_scroll.ensureWidgetVisible(self.polish_editor, 24, 36)
            editor_top = self.polish_editor.mapTo(
                self.settings_scroll.viewport(), QPoint(0, 0)
            ).y()
            viewport_height = self.settings_scroll.viewport().height()
            if editor_top >= viewport_height - 36:
                scroll_bar.setValue(
                    min(
                        scroll_bar.maximum(),
                        scroll_bar.value() + editor_top - viewport_height + 36,
                    )
                )

    def _header(self):
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(104)
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.app_header = header
        outer = QHBoxLayout(header)
        outer.setContentsMargins(14, 6, 8, 6)
        outer.setSpacing(8)
        mascot = HeaderMascot(full_artwork=True, logical_size=86)
        self.header_mascot = mascot
        bind_text(mascot, '2ByteASR 品牌标志', property='accessibleName')
        outer.addWidget(mascot, 0, Qt.AlignmentFlag.AlignVCenter)
        chrome = QWidget()
        chrome_column = QVBoxLayout(chrome)
        chrome_column.setContentsMargins(0, 0, 0, 0)
        chrome_column.setSpacing(0)
        self.window_title_bar = WindowTitleBar(self)
        chrome_column.addWidget(self.window_title_bar)
        header_content = QWidget()
        header_content.setFixedHeight(58)
        self.header_content = header_content
        row = QHBoxLayout(header_content)
        row.setContentsMargins(2, 0, 8, 0)
        row.setSpacing(10)
        self.brand = BrandLabel()
        self._set_brand_text()
        self.brand.setObjectName("brand")
        self.brand.setTextFormat(Qt.TextFormat.RichText)
        self.brand.setAccessibleName("2ByteASR")
        subtitle = QLabel("兔白字幕")
        self.header_subtitle = subtitle
        subtitle.setObjectName("headerSubtitle")
        self.header_status = QLabel("")
        self.header_status.setObjectName("headerStatus")
        bind_text(self.header_status, '当前任务状态', property='accessibleName')
        self.header_status.hide()
        row.addWidget(self.brand)
        row.addWidget(subtitle)
        row.addSpacing(12)
        row.addStretch(1)
        from .support_entry import support_entry_hidden
        from ..design.presentation import button_role
        self.support_button = button_role(QPushButton(), "secondary", size="compact")
        self.support_button.setObjectName("supportEntry")
        bind_text(self.support_button, "支持我！")
        install_themed_icon(self.support_button, "fa5s.heart", "zone_studio")
        self.support_button.clicked.connect(self._open_support)
        row.addWidget(self.support_button)
        # After adoption: showing a parentless button made it a native
        # top-level window for a moment (~0.3 s at startup).
        self.support_button.setVisible(not support_entry_hidden())
        self.update_button = AnimatedButton("检查更新")
        self.update_button.setObjectName("softAction")
        install_themed_icon(self.update_button, "fa5s.sync-alt", "accent")
        bind_text(self.update_button, '当前版本 {value0} · 检查 GitHub Release', property='toolTip', value0=current_version())
        self.update_button.clicked.connect(self._check_updates)
        row.addWidget(self.update_button)
        self.subtitle_studio_button = AnimatedButton("字幕工作台")
        self.subtitle_studio_button.setObjectName("softAction")
        install_themed_icon(self.subtitle_studio_button, "fa5s.closed-captioning", "accent")
        self.subtitle_studio_button.clicked.connect(lambda _checked=False: self.open_studio_project(source='header'))
        row.addWidget(self.subtitle_studio_button)
        self.model_workshop_button = AnimatedButton("模型工坊")
        self.model_workshop_button.setObjectName("softAction")
        install_themed_icon(self.model_workshop_button, "fa5s.cubes", "accent")
        self.model_workshop_button.clicked.connect(self._open_model_workshop)
        row.addWidget(self.model_workshop_button)
        self.return_recognition_button = AnimatedButton("返回字幕识别")
        self.return_recognition_button.setObjectName("outline")
        install_themed_icon(self.return_recognition_button, "fa5s.arrow-left", "accent")
        self.return_recognition_button.clicked.connect(self._return_to_settings)
        self.return_recognition_button.hide()
        row.addWidget(self.return_recognition_button)
        self.app_settings_button = AnimatedButton("设置")
        self.app_settings_button.setObjectName("softAction")
        install_themed_icon(self.app_settings_button, "fa5s.cog", "accent")
        bind_text(self.app_settings_button, '应用设置（界面主题、工程库、自动保存）', property='toolTip')
        self.app_settings_button.clicked.connect(self._open_application_settings)
        row.addWidget(self.app_settings_button)
        # 2026-10-13: 说明 — guide, example, plan, API setup, search, shortcuts, diagnostics.
        self.help_button = AnimatedButton("说明")
        self.help_button.setObjectName("softAction")
        install_themed_icon(self.help_button, "fa5s.question-circle", "accent")
        bind_text(self.help_button, '新手引导、范例工程、功能搜索、快捷键与诊断信息', property='toolTip')
        self.help_button.clicked.connect(self._show_help_menu)
        row.addWidget(self.help_button)
        from ..design.presentation import button_role
        for button in (self.update_button, self.subtitle_studio_button, self.model_workshop_button,
                       self.app_settings_button, self.help_button):
            button_role(button, "secondary", size="default")
            button.setProperty("homeNavigation", True)
            button.setIconSize(QSize(18, 18))
        # 2026-10-23 (home design A): the two places you go to carry the accent
        # tint; update, settings and help a quiet neutral one.
        for button, icon in ((self.update_button, "fa5s.sync-alt"), (self.app_settings_button, "fa5s.cog"),
                             (self.help_button, "fa5s.question-circle")):
            button.setProperty("homeTone", "quiet")
            install_themed_icon(button, icon, "secondary")
        # Keyboard users still Tab to every header command; a mouse click or
        # window activation no longer leaves a focus ring on the support button.
        for button in (self.support_button, self.update_button, self.subtitle_studio_button,
                       self.model_workshop_button, self.return_recognition_button, self.app_settings_button,
                       self.help_button):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.language_combo = user_text(FramelessPopupCombo())
        self.language_combo.setObjectName("headerLanguage")
        self.language_combo.setMinimumWidth(100)
        self.language_combo.setMaximumWidth(160)  # soft for CN labels
        from twobyteasr.i18n import LANGUAGE_NATIVE_NAMES
        for code, name in LANGUAGE_NATIVE_NAMES.items():  # 2026-10-19: + es/de/fr/pt/it/ru
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(current_language()))
        )
        self.language_combo.currentIndexChanged.connect(self._change_language)
        row.addWidget(self.language_combo)
        chrome_column.addWidget(header_content, 1)
        outer.addWidget(chrome, 1)
        return header

    def _show_help_menu(self):
        from PySide6.QtWidgets import QMenu
        from ..studio import shortcut_registry as keys
        menu = QMenu(self)
        menu.setObjectName("helpMenu")
        search_key = keys.tooltip_key("home.search")
        entries = (
            ("新手教学", self._start_home_tour),
            ("显示新手引导", lambda: self._next_step_action("show_guide")),
            ("打开范例工程", self._open_sample_project),
            ("选择识别方式…", lambda: self._next_step_action("choose_plan")),
            ("申请与设置 API…", self._open_api_setup_guide),
            ("API Key 是什么？", self._open_api_key_explainer),
            (None, None),
            (tr("搜索功能与设置…（{key}）", key=search_key), self._open_feature_search),
            ("快捷键…", lambda: self._open_application_settings(initial_section="快捷键")),
            ("回报问题／导出诊断…", self._open_diagnostics_dialog),
            ("重新显示工作台操作提示", self._reset_teach_hints),
        )
        for label, handler in entries:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(str(tr(label)) if type(label) is str else str(label))
            action.triggered.connect(lambda _checked=False, callback=handler: callback())
        menu.exec(self.help_button.mapToGlobal(self.help_button.rect().bottomLeft()))

    def _open_diagnostics_dialog(self):
        from ..diagnostics.diagnostics_report import open_diagnostics_dialog
        open_diagnostics_dialog(self)

    def _anchor_header_mascot(self):
        # Retained for older audit hooks. The brand mark is now owned by the
        # header layout and never absolutely positioned over the wordmark.
        return

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_initial_focus_settled', False):
            self._initial_focus_settled = True
            # Start with no control focused; the first Tab reaches the header.
            QTimer.singleShot(0, self, lambda: self.setFocus(Qt.FocusReason.OtherFocusReason))

    def showNormal(self):
        from .window_constraints import restore_normal_window
        restore_normal_window(self)

    def showMaximized(self):
        from .window_constraints import maximize_window
        maximize_window(self)

    def normalGeometry(self):
        from .window_constraints import normal_restore_geometry, _special_window_state
        if _special_window_state(self):
            return normal_restore_geometry(self)
        return QWidget.normalGeometry(self)

    def showFullScreen(self):
        from .window_constraints import remember_normal_geometry
        remember_normal_geometry(self)
        self._window_geometry_transition=True
        try:
            QWidget.showFullScreen(self)
        finally:
            self._window_geometry_transition=False

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_title_bar"):
            self.window_title_bar.sync_window_state()
            studio = self.built_page("studio")
            if studio is not None:
                studio._sync_window_controls()
            self._layout_resize_handles()
        super().changeEvent(event)

    def paintEvent(self, event):
        # The complete native client surface is opaque, including newly
        # exposed resize strips and corners formerly clipped by root radius.
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        painter.end()
        super().paintEvent(event)

    def _create_resize_handles(self):
        specs = {
            "left": (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            "right": (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            "top": (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            "bottom": (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            "tl": (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            "tr": (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            "bl": (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
            "br": (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
        }
        self._resize_handles = {
            name: _NativeResizeHandle(self, edges, cursor)
            for name, (edges, cursor) in specs.items()
        }
        self._layout_resize_handles()

    def _layout_resize_handles(self):
        if not hasattr(self, "_resize_handles"):
            return
        hidden = self.isMaximized() or self.isFullScreen()
        width, height, edge, corner = self.width(), self.height(), 7, 12
        geometry = {
            "left": QRect(0, corner, edge, max(0, height - corner * 2)),
            "right": QRect(max(0, width - edge), corner, edge, max(0, height - corner * 2)),
            "top": QRect(corner, 0, max(0, width - corner * 2), edge),
            "bottom": QRect(corner, max(0, height - edge), max(0, width - corner * 2), edge),
            "tl": QRect(0, 0, corner, corner),
            "tr": QRect(max(0, width - corner), 0, corner, corner),
            "bl": QRect(0, max(0, height - corner), corner, corner),
            "br": QRect(max(0, width - corner), max(0, height - corner), corner, corner),
        }
        for name, handle in self._resize_handles.items():
            handle.setGeometry(geometry[name])
            handle.setVisible(not hidden)
            handle.raise_()

    @navigation_timed('navigation.refresh')
    def _page_changed(self, index: int):
        current = self.pages.widget(index)
        if current is self.__dict__.get("settings_scroll"):
            self._schedule_next_step_probe()
            if self.__dict__.pop("_home_tour_pending", False):
                QTimer.singleShot(500, self._start_home_tour)
        completion = current.objectName() == 'completionScroll'
        studio = existing_page(self, "studio")
        loading = self.__dict__.get('_studio_loading_session')
        in_studio = (studio is not None and current is studio) or bool(loading and loading.state in {'preparing', 'failed'})
        self.content_layout.setContentsMargins(*( (0, 0, 0, 0) if in_studio
            else (18, 0, 18, 14) if completion else (18, 12, 18, 14) ))
        self.content_layout.setSpacing(0 if in_studio else 12)
        self.app_header.setVisible(not in_studio)
        self.model_workshop_button.setVisible(current is self.settings_scroll)
        self.subtitle_studio_button.setVisible(not in_studio)
        self.return_recognition_button.setVisible(
            current is self.term_library_page
            or current in {existing_page(self, "workshop"), existing_page(self, "history")}
        )
        # 四十三轮：主页进度页的"返回 Studio"只在 Studio 后台识别进行中显示。
        progress_page = self.pages.widget(1) if self.pages.count() > 1 else None
        if getattr(self, "back_to_studio_button", None) is not None:
            self.back_to_studio_button.setVisible(
                current is progress_page
                and bool(getattr(self, "_studio_recognition_context", None))
            )
        # Resident pages are translated once per language. Walking the entire
        # MainWindow tree on every switch caused a visible 50-140 ms stall.
        self._prepare_page_presentation(current)
        self._update_bottom_bar_visibility(index)

    def _prepare_page_presentation(self, current):
        language = getattr(self, "_ui_language", current_language())
        if current.property("_2b_language_applied") != language:
            with navigation_phase('navigation.language'):
                apply_ui_language(current, language)
                current.setProperty("_2b_language_applied", language)
        # Interface zoom: pages built or changed since the last zoom step
        # catch up here (no-op at 100%; Studio keeps its own size).
        from .ui_zoom import apply_to_changed as _apply_ui_zoom
        with navigation_phase('navigation.zoom'):
            _apply_ui_zoom(current)

    def _native_video_handoff(self):
        """Hold only this editor's existing Qt native child visibility."""
        loading = self.__dict__.get('_studio_loading_session')
        if loading is not None and getattr(loading, 'uses_native_cover', False):
            # The cover owns the handoff. Holding a video HWND while its native
            # pages parent moves to Home carries old pixels over the new page.
            return nullcontext()
        studio = self.built_page('studio')
        if studio is None:
            return nullcontext()
        from ..design.native_visibility_commit import NativeVisibilityCommit
        from ..studio.studio_video_canvas import MpvCanvas
        from shiboken6 import isValid
        coordinator = self.__dict__.get('_studio_native_visibility')
        if coordinator is None:
            coordinator = self._studio_native_visibility = NativeVisibilityCommit(
                self, after_commit=self._flush_native_page_presentation)
        widgets = [getattr(studio, 'video_overlay_host', None),
                   getattr(studio, 'subtitle_edit_card', None)]
        for canvas in studio.findChildren(MpvCanvas):
            widget = canvas
            while widget is not None and widget is not studio and widget is not self.pages:
                if widget not in widgets:
                    widgets.append(widget)
                widget = widget.parentWidget()
        return coordinator.scope([widget for widget in widgets if widget is not None
            and isValid(widget) and not widget.isWindow() and widget.window() is self])

    def _flush_native_page_presentation(self, _receipt):
        """Submit already-painted pixels after the outer native visibility commit.

        The earlier Raster flush can be clipped by the still-visible video
        child. This completes that same paint, including nested loader scopes;
        it does not create a second image, window, layout pass, or frame clock.
        """
        from ..design.backing_store_flush import flush_existing_widget_backing_store
        result = flush_existing_widget_backing_store(self, self.pages)
        if result.get('status') != 'submitted':
            from shiboken6 import isValid
            if (isValid(self) and isValid(self.pages)
                    and not getattr(self, '_studio_close_pending', False)
                    and not getattr(self, '_studio_close_finalizing', False)):
                self.pages.repaint()
                self.repaint()
                result['fallback'] = 'repaint_requested'
        return result

    @navigation_timed('navigation.layout')
    def _switch_page(self, target) -> None:
        """Commit a stacked-page transition under one paint boundary."""
        widget = self.pages.widget(target) if isinstance(target, int) else target
        if widget is self.settings_scroll:
            self._ensure_recognition_page()
        if widget is None or self.pages.currentWidget() is widget:
            return
        if widget is self.pages.widget(2) and hasattr(self, 'result_preview'):
            self._refresh_completion_preview()
        with navigation_phase('navigation.prepare_target'):
            self._prepare_page_presentation(widget)
            widget.ensurePolished()
        from ..design.ui_motion import atomic_layout, reveal_cue
        studio = self.built_page("studio")
        from shiboken6 import isValid
        surfaces = []
        if studio is not None:
            from ..studio.studio_video_canvas import MpvCanvas
            surfaces = studio.findChildren(MpvCanvas)
        departing = self.pages.currentWidget() is studio and widget is not studio
        loading = self.__dict__.get('_studio_loading_session')
        native_cover_mode = bool(loading is not None and getattr(loading, 'uses_native_cover', False))
        with ExitStack() as presentation:
            if native_cover_mode:
                # Retire native video before changing its parent's rectangle.
                # During loading the separately held card already covers this.
                if not departing:
                    # A retained hot editor can enter without showing the card.
                    # Its showEvent must not expose pixels over the old Home.
                    for surface in surfaces:
                        surface.set_presentation_blocked('page-handoff', True)
                        presentation.callback(lambda item=surface:
                            item.set_presentation_blocked('page-handoff', False) if isValid(item) else None)
            elif departing:
                # Retire requests immediately, but commit region changes with
                # the destination paint instead of blanking the old editor.
                for surface in surfaces:
                    presentation.enter_context(surface.defer_presentation_changes())
                presentation.enter_context(self._native_video_handoff())
            else:
                # showEvent may release navigation ownership while entering.
                # Keep the incoming native video gated through the first paint.
                presentation.enter_context(self._native_video_handoff())
                for surface in surfaces:
                    surface.set_presentation_blocked('page-handoff', True)
                    presentation.callback(lambda item=surface:
                        item.set_presentation_blocked('page-handoff', False) if isValid(item) else None)
            with atomic_layout(self):
                with navigation_phase('navigation.set_current'):
                    self.pages.setCurrentWidget(widget)
                with navigation_phase('navigation.activate'):
                    self.pages.layout().activate()
                    if hasattr(self, "content_layout"):
                        self.content_layout.activate()
            # Native pages have their own paint target. Repainting only the
            # shell can leave their previous pixels beneath the resumed video.
            if native_cover_mode:
                with navigation_phase('navigation.paint_shell'):
                    self.repaint()
                with navigation_phase('navigation.paint_pages'):
                    self.pages.repaint()
            else:
                with navigation_phase('navigation.paint_pages'):
                    self.pages.repaint()
                with navigation_phase('navigation.paint_shell'):
                    self.repaint()
        reveal_cue(self.app_header if self.app_header.isVisible() or studio is None else studio.studio_toolbar)

    def _update_bottom_bar_visibility(self, index: int = None):
        # Bottom CTA is only relevant on the main settings page (index 0).
        # Keep it fixed at the content_host level so it never scrolls away.
        try:
            idx = self.pages.currentIndex() if index is None else index
            if hasattr(self, "bottom_bar") and self.bottom_bar is not None:
                loading = self.__dict__.get('_studio_loading_session')
                busy = loading is not None and loading.state in {'preparing', 'failed'}
                self.bottom_bar.setVisible(self.pages.widget(idx) is self.settings_scroll and not busy)
        except Exception:
            pass

    def _apply_sane_initial_geometry(self):
        """Apply a sane default/restore geometry using QScreen.availableGeometry().
        Avoids tiny or off-screen windows on start.
        """
        try:
            screen = self.screen()
            avail = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
            # Reasonable defaults for supported resolutions
            min_w, min_h = min(640, avail.width()-16), min(360, avail.height()-16)
            self.setMinimumSize(min_w, min_h)
            def_w, def_h = 1320, 880
            w = max(min_w, min(def_w, avail.width() - 16))
            h = max(min_h, min(def_h, avail.height() - 16))
            # Try to restore previous if sane
            settings = QSettings("2ByteASR", "2ByteASR")
            geo_b = settings.value("mainWindow/geometry")
            restored = False
            if geo_b:
                try:
                    g = QRect()
                    ok = g != g  # force, we'll overwrite below
                    # QSettings may store QByteArray or list; try common paths
                    if isinstance(geo_b, (bytes, bytearray)):
                        ba = QByteArray(geo_b)
                        g = QRect()
                        # best-effort parse not reliable; fall through to default if weird
                    elif isinstance(geo_b, (list, tuple)) and len(geo_b) >= 4:
                        g = QRect(int(geo_b[0]), int(geo_b[1]), int(geo_b[2]), int(geo_b[3]))
                    # Validate
                    if g.width() >= min_w and g.height() >= min_h and g.width() <= avail.width() and g.height() <= avail.height():
                        # keep within current screen roughly
                        gx = max(avail.left() + 10, min(g.left(), avail.right() - g.width() - 10))
                        gy = max(avail.top() + 10, min(g.top(), avail.bottom() - g.height() - 10))
                        g.moveLeft(gx); g.moveTop(gy)
                        self.setGeometry(g)
                        restored = True
                except Exception:
                    restored = False
            if not restored:
                # Center a good default
                g = QRect(0, 0, w, h)
                g.moveCenter(avail.center())
                self.setGeometry(g)
            # 2026-10-10 (user): a window closed maximized opens maximized. Older
            # versions saved only the size, so a saved size that almost fills the
            # screen is read as maximized too; un-maximizing then gives the default.
            flag = settings.value("mainWindow/maximized")
            near_full = restored and g.width() >= avail.width() - 48 and g.height() >= avail.height() - 48
            maximize = str(flag).lower() in {"true", "1"} if flag is not None else near_full
            if maximize and near_full:
                g = QRect(0, 0, w, h)
                g.moveCenter(avail.center())
                self.setGeometry(g)
            from .window_constraints import install_window_bounds
            install_window_bounds(self, native_events=True)
            if maximize:
                self.showMaximized()
            # Persist on close
            try:
                self._persist_geometry = True
            except Exception:
                pass
        except Exception:
            # Never break startup on geometry heuristics
            pass

    def _open_model_workshop(self):
        self._ensure_recognition_page()
        self.workshop_page.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
        self.workshop_page.restore_active_navigation()
        self._switch_page(self.workshop_page)

    @navigation_timed('studio.entry.dispatch')
    def open_studio_project(self, project_path=None, *, mode="edit", source="canonical", on_ready=None, expected_result_ref=None):
        """Canonical Studio navigation entry for every project-opening source."""
        if getattr(self, '_studio_close_pending', False) or getattr(self, '_studio_close_finalizing', False):
            return
        studio = self.built_page('studio')
        if studio is not None:
            from ..projects.studio_save import cancel_navigation_after_save, defer_navigation_until_saved
            if defer_navigation_until_saved(studio, lambda: self.open_studio_project(
                    project_path, mode=mode, source=source, on_ready=on_ready, expected_result_ref=expected_result_ref)):
                return
            cancel_navigation_after_save(studio)
        if self.built_page('studio') is None:
            self._queue_studio_construction(project_path, mode=mode, source=source,
                on_ready=on_ready, expected_result_ref=expected_result_ref)
            return
        proofread = getattr(self, "glossary_proofread_page", None)
        if proofread is not None and project_path and not proofread.settle_writes(project_path):
            # The proofreading edits of this file are not saved yet; Studio
            # would load (and later save over) the older file.
            loading = self.__dict__.get('_studio_loading_session')
            if loading is not None and loading.active and loading.path == str(Path(project_path).resolve()):
                self._reject_studio_loading()
            return
        if (source == "external" and project_path and self.built_page("studio") is not None
                and self.studio_page.project is not None):
            from .external_open import path_identity
            current = self.studio_page.session.project_path
            if current and path_identity(current) == path_identity(project_path):
                from ..studio.studio_readiness import project_file_identity
                readiness = getattr(self.studio_page, '_readiness', None)
                if (readiness is not None and readiness.ready
                        and readiness.loaded_file_identity == project_file_identity(project_path)):
                    self._switch_page(self.studio_page)
                    return
        self.studio_page._studio_trace(
            "ENTRY",
            source=str(source),
            mode=str(mode),
            project_path=str(project_path or ""),
        )
        self._open_subtitle_studio(project_path, mode=mode,
            skip_dirty_guard=source == 'studio_recognition', on_ready=on_ready,
            expected_result_ref=expected_result_ref)

    def _loading_surface_painted(self):
        if self.__dict__.get('_studio_entry_start_queued', False):
            session = self.__dict__.get('_studio_loading_session')
            if session is None or not session.active:
                return
            if (getattr(session, 'uses_native_cover', False)
                    and not session.native_cover_state().get('verified')):
                return
            self._studio_entry_start_queued = False
            QTimer.singleShot(0, self, self._start_studio_construction)

    def _prepare_studio_loading(self, path, **options):
        """Own the loading surface before construction, hydration or native video."""
        from ..studio.studio_loading import StudioLoadingSession
        session = self.__dict__.get('_studio_loading_session')
        if session is None:
            # The native-child experiment keeps a real, opaque loading surface
            # above a visible editor. Ordinary platforms retain StackOne.
            native_cover = (os.name == 'nt' and QApplication.platformName() == 'windows'
                and os.environ.get('TWOBYTEASR_NATIVE_LOADING_COVER', '1') == '1')
            session = self._studio_loading_session = StudioLoadingSession(
                self.pages, self, page_stack=True, native_cover=native_cover,
                input_host=self.pages if native_cover else None)
            if session.uses_native_cover:
                session.on_present = self._present_native_loading_destination
                session.on_retired = self._paint_loading_destination
                session.handoff_scope = self._loading_cover_handoff
            else:
                self.pages.addWidget(session.view)
                session.on_present = lambda: self._switch_page(session.view)
                session.handoff_scope = self._native_video_handoff
            session.on_reveal = self._reveal_prepared_studio
            session.view.painted.connect(self._loading_surface_painted)
            session.view.geometry_changed.connect(self._queue_hidden_studio_geometry)
            # Compatibility name for instrumentation, never a separate page.
            self._studio_entry_loading = session.view
            self._studio_entry_status = session.view.label
        target = str(Path(path).resolve()) if path else ''
        studio = self.built_page('studio')
        if studio is not None:
            session.attach_surface(studio.video)
        if not session.active or session.path != target:
            continuation = session.active or (session.state == 'failed' and session.path == target)
            previous_origin = session.return_target if continuation else None
            origin = previous_origin or ('hub' if self.pages.currentWidget() is self.built_page('studio') else 'home')
            origin_widget = getattr(session, 'origin_widget', None) if continuation else self.pages.currentWidget()
            session.begin(target, on_cancel=self._cancel_studio_construction,
                on_retry=lambda: self.open_studio_project(path, **options), return_target=origin, present=False)
            session.origin_widget = origin_widget
        self._page_changed(self.pages.currentIndex())
        self.layout().activate()
        self.pages.layout().activate()
        session.present()
        return session

    def _present_native_loading_destination(self):
        """Only a verified native child cover may expose its editor behind it."""
        session = self.__dict__.get('_studio_loading_session')
        if (session is None or not session.active or not session.uses_native_cover
                or not session.native_cover_state().get('verified')):
            return
        studio = self.built_page('studio')
        if studio is not None:
            if not studio.video._paused:
                studio.video.set_paused(True)
            self._switch_page(studio)
        session.view.raise_()
        self._loading_surface_painted()

    def _paint_loading_destination(self):
        # The card is logically hidden but its own native layer is still held.
        # Paint the enabled destination before that layer's final HIDE.
        self._page_changed(self.pages.currentIndex())
        self.layout().activate()
        self.pages.layout().activate()
        self.repaint()
        # Native pages are the final backing-store writer for their rectangle.
        self.pages.repaint()

    @contextmanager
    def _loading_cover_handoff(self):
        """Commit video changes first; retire the opaque card native layer last."""
        session = self.__dict__.get('_studio_loading_session')
        if session is None or not session.uses_native_cover:
            with self._native_video_handoff():
                yield
            return
        from ..design.native_visibility_commit import NativeVisibilityCommit
        coordinator = self.__dict__.get('_studio_cover_visibility')
        if coordinator is None:
            coordinator = self._studio_cover_visibility = NativeVisibilityCommit(self)
        with coordinator.scope([session.view]):
            with self._native_video_handoff():
                yield

    def _reveal_prepared_studio(self):
        studio = self.built_page('studio')
        if studio is None:
            raise RuntimeError('cannot reveal an unconstructed Studio')
        self._switch_page(studio)

    def _prepare_hidden_studio_geometry(self, page, *, force_settle=False):
        """Resolve the loading owner's final rectangle before restoring splits.

        StackOne does not size an inactive page. Restoring splitters against
        its 100x30 placeholder both distorts defaults and triggers recovery
        for perfectly valid saved sidebars. Keep the editor hidden and use
        the already-visible loading page's final stack geometry.
        """
        from shiboken6 import isValid
        session = self.__dict__.get('_studio_loading_session')
        if (page is None or not isValid(page)
                or getattr(self, '_studio_close_pending', False)
                or getattr(self, '_studio_close_finalizing', False)
                or getattr(page, '_close_requested', False)
                or page is not self.built_page('studio') or page.isVisible()
                or page.parentWidget() is not self.pages or session is None
                or not session.active or self.pages.currentWidget() is not session.view):
            return False
        generation = getattr(session, 'generation', None)
        self.layout().activate()
        self.pages.layout().activate()
        if (self.__dict__.get('_studio_loading_session') is not session
                or getattr(session, 'generation', None) != generation or not session.active
                or self.pages.currentWidget() is not session.view or page.isVisible()):
            return False
        target = self.pages.contentsRect()
        if target.isEmpty():
            return False
        same_rectangle = page.geometry() == target
        if same_rectangle and not force_settle:
            return True  # Ordinary LayoutRequest must not walk the tree again.
        before = page.size()
        timeline = getattr(page, 'timeline', None)
        timeline_before = timeline.size() if isinstance(timeline, QWidget) else None
        if not same_rectangle:
            page.setGeometry(target)
        from ..design.ui_motion import settle_layout
        # The first restore may follow a root-only Hub resize. Its newly
        # exposed workspace still needs one pass even at the same outer size.
        settle_layout(page)
        if (page.size() != before or (timeline_before is not None
                and isValid(timeline) and timeline.size() != timeline_before)):
            gate = getattr(page, '_readiness', None)
            invalidate = getattr(gate, 'invalidate_surface_geometry', None)
            if callable(invalidate):
                invalidate()
        return True

    def _queue_hidden_studio_geometry(self):
        """Coalesce one stack-geometry update for this exact loading request."""
        from shiboken6 import isValid
        session = self.__dict__.get('_studio_loading_session')
        page = self.built_page('studio')
        if (session is None or not session.active or page is None or not isValid(page)
                # The initial Hub still hides the workspace subtree. Its
                # placeholder must not consume the first project-layout pass.
                or getattr(page, 'project', None) is None
                or getattr(self, '_studio_close_pending', False)
                or getattr(self, '_studio_close_finalizing', False)
                or getattr(page, '_close_requested', False)
                or self.pages.currentWidget() is not session.view or page.isVisible()
                or page.parentWidget() is not self.pages):
            return
        generation = session.generation
        pending = self.__dict__.get('_studio_hidden_geometry_pending')
        if (pending is not None and pending[0] is session
                and pending[1] == generation and pending[2] is page):
            return
        request = (session, generation, page)
        self._studio_hidden_geometry_pending = request
        def synchronize():
            if self.__dict__.get('_studio_hidden_geometry_pending') is not request:
                return
            self._studio_hidden_geometry_pending = None
            if (self.__dict__.get('_studio_loading_session') is not session
                    or session.generation != generation or self.built_page('studio') is not page):
                return
            self._prepare_hidden_studio_geometry(page)
        QTimer.singleShot(0, self, synchronize)

    def _queue_studio_construction(self, project_path, **options):
        """One request owns construction and the subsequent project preparation."""
        self._studio_entry_pending = (project_path, options)
        session = self._prepare_studio_loading(project_path, **options)
        if not session.active:
            self._studio_entry_pending = None
            return
        session.stage('创建工作台界面')
        if self.__dict__.get('_studio_entry_discarding', False):
            return
        building = self.__dict__.get('_studio_page_building')
        if building is not None:
            building.resume_workspace_construction()
        elif not self.__dict__.get('_studio_entry_start_queued', False):
            self._studio_entry_start_queued = True
            session.view.update()

    def _start_studio_construction(self):
        self._studio_entry_start_queued = False
        if self.__dict__.get('_studio_entry_pending') is None:
            return
        if (self.__dict__.get('_studio_page_building') is not None
                or self.__dict__.get('_studio_entry_discarding', False)):
            return  # A queued start cannot overlap construction/disposal.
        session = self.__dict__.get('_studio_loading_session')
        if session is not None and getattr(session, 'uses_native_cover', False):
            if not session.active:
                self._studio_entry_pending = None
                return
            if not session.native_cover_state().get('verified'):
                self._studio_entry_start_queued = True
                return
        if self.built_page('studio') is not None:
            request, self._studio_entry_pending = self._studio_entry_pending, None
            path, options = request
            self.open_studio_project(path, **options)
            return
        try:
            from ..studio.studio_ui import SubtitleStudioPage
            page = SubtitleStudioPage(self, deferred_build=True)
            self._studio_page_building = page
            page.workspace_build_progress.connect(
                lambda stage: self._studio_loading_session.stage('创建工作台界面', stage)
                if self.__dict__.get('_studio_page_building') is page else None)
            page.workspace_build_failed.connect(self._studio_construction_failed)
            page.workspace_built.connect(self._studio_construction_finished)
            page.resume_workspace_construction()
        except Exception as exc:
            self._studio_construction_failed(str(exc))

    def _studio_construction_failed(self, error):
        self._studio_entry_pending = None
        self._studio_loading_session.fail('创建工作台界面', error)
        page = self.__dict__.get('_studio_page_building')
        if page is None:
            return
        self._studio_entry_discarding = True
        def disposed():
            if self.__dict__.get('_studio_page_building') is page:
                self._studio_page_building = None
            self._studio_entry_discarding = False
            if self.__dict__.pop('_close_after_studio_discard', False):
                self.close()
            elif self.__dict__.get('_studio_entry_pending') is not None:
                self._studio_entry_start_queued = True
                self._studio_loading_session.stage('创建工作台界面')
                self._studio_loading_session.view.update()
        page.discard_workspace_construction(disposed)

    def _studio_construction_finished(self):
        page = self.__dict__.get('_studio_page_building')
        if page is None:
            return
        self._studio_page_building = None
        self._studio_loading_session.attach_surface(page.video)
        self._construct_lazy_page('studio', prepared=page)
        self._studio_loading_session.mark('创建工作台界面')
        request, self._studio_entry_pending = self.__dict__.get('_studio_entry_pending'), None
        if request is not None:
            path, options = request
            self.open_studio_project(path, **options)

    def _cancel_pending_studio_entries(self):
        self._studio_navigation_cancel_generation = int(getattr(self, '_studio_navigation_cancel_generation', 0)) + 1
        from ..projects.studio_save import cancel_navigation_after_save
        cancel_navigation_after_save(self.built_page('studio'))

    def _cancel_studio_construction(self):
        self._cancel_pending_studio_entries()
        session = self.__dict__.get('_studio_loading_session')
        destination = session.return_target if session is not None else 'home'
        if session is not None:
            session.hold_navigation()
        self._studio_entry_pending = None
        self._studio_entry_start_queued = False
        page = self.__dict__.get('_studio_page_building')
        if page is not None:
            page.pause_workspace_construction()
        studio = self.built_page('studio')
        gate = getattr(studio, '_readiness', None)
        if studio is not None:
            block = getattr(studio.video, 'set_presentation_blocked', None)
            if callable(block):
                block('navigation', True)
        def reveal():
            if destination == 'hub' and studio is not None:
                studio.show_project_hub(skip_dirty_guard=True)
                self._switch_page(studio)
            else:
                self._switch_page(self.settings_scroll)
            # A same-page switch is a no-op, but cancelling loading still
            # restores Home's chrome before the native card can disappear.
            self._page_changed(self.pages.currentIndex())
            self.layout().activate()
            self.pages.layout().activate()
        if gate is not None:
            gate.cancel(navigate=False, reveal=reveal)
        elif session is not None:
            session.abort(reveal=reveal)
        else:
            reveal()

    def _reject_studio_loading(self):
        """Declining the dirty guard cancels the request, never the old project."""
        session = self.__dict__.get('_studio_loading_session')
        if session is None:
            return
        self._cancel_pending_studio_entries()
        origin = getattr(session, 'origin_widget', None)
        studio = self.built_page('studio')
        if studio is not None and studio.project is not None:
            studio._project_view_state = 'open'
            studio._sync_navigation_chrome()
        def reveal():
            if origin is not None:
                self._switch_page(origin)
            self._page_changed(self.pages.currentIndex())
            self.layout().activate()
            self.pages.layout().activate()
        session.abort(reveal=reveal)

    def _retry_pending_recognition_reload(self):
        """Reload a recognition handoff that failed to land earlier.

        The saved subtitles exist; only the in-app reload can have failed
        (readiness timeout/cancel). Retrying on the next Studio entry keeps
        the user from having to reopen the project from the library.
        """
        studio = self.built_page("studio")
        pending = str(getattr(studio, "_pending_recognition_reload", "") or "")
        if not pending:
            return
        if studio is not None:
            studio._pending_recognition_reload = ""
        target = Path(pending)
        if not target.is_file():
            return
        if studio is not None:
            studio._studio_trace(
                "StudioSubtitleRefresh", retry=True, project_path=str(target)
            )
        # A retry happens on a later Studio entry, after delivery: the user
        # may have proofread this project meanwhile. Keep the strict identity
        # (path, project, job, recognition stamp, media) but accept their
        # edits, like every other reopen of a delivered result (ADR 0102).
        from ..recognition.recognition_result import working_reference
        self.open_studio_project(str(target), mode="edit", source="studio_recognition",
            expected_result_ref=working_reference(
                getattr(studio, '_pending_recognition_result_ref', None)) or None)

    @navigation_timed('studio.switch_and_open')
    def _open_subtitle_studio(self, project_path=None, *, mode="edit", skip_dirty_guard=False, on_ready=None, expected_result_ref=None):
        if self.built_page('studio') is None:
            self._queue_studio_construction(project_path, mode=mode,
                source='studio_recognition' if skip_dirty_guard else 'legacy_entry',
                on_ready=on_ready, expected_result_ref=expected_result_ref)
            return
        if expected_result_ref:
            from ..recognition.recognition_result import verify_result_reference
            try:
                verify_result_reference(expected_result_ref, project_path=project_path)
            except (OSError, ValueError, TypeError) as exc:
                loading = self.__dict__.get('_studio_loading_session')
                if loading is not None and loading.active and loading.path == str(Path(project_path).resolve()):
                    loading.fail('核对识别结果', str(exc))
                else:
                    QMessageBox.warning(self, tr('无法确认本次识别工程'), str(exc))
                return
        candidate = str(project_path or self.studio_page.project_path or '') if self.studio_page.project is not None else str(project_path or '')
        gate = getattr(self.studio_page, '_readiness', None)
        from ..studio.studio_readiness import project_file_identity
        hot = bool(candidate and gate is not None and gate.ready and gate.path == str(Path(candidate).resolve())
                   and gate.loaded_file_identity == project_file_identity(candidate))
        loading = None if hot else self._prepare_studio_loading(candidate, mode=mode,
            source='studio_recognition' if skip_dirty_guard else 'canonical', on_ready=on_ready,
            expected_result_ref=expected_result_ref)
        if loading is not None and getattr(loading, 'uses_native_cover', False):
            if not loading.active:
                return
            if not loading.native_cover_state().get('verified'):
                self._studio_entry_pending = (project_path, dict(mode=mode,
                    source='studio_recognition' if skip_dirty_guard else 'canonical',
                    on_ready=on_ready, expected_result_ref=expected_result_ref))
                self._studio_entry_start_queued = True
                loading.view.update()
                return
            self._studio_entry_pending = None
            self._studio_entry_start_queued = False
            # The same card may have been presented before Studio existed.
            # Its once-per-request presentation callback is not a new open.
            self._present_native_loading_destination()
        transition_started = time.perf_counter()
        if self.pages.currentWidget() is not self.studio_page and not self._recognition_page_deferred:
            current = self.current_project_profile
            self._home_profile_snapshot = ProjectProfile.from_dict(dict(
                self._profile_configuration(), id=current.id if current else '',
                name=current.name if current else '自定义方案'))
        # Resolve the Studio shell before changing the stack so the first
        # Studio paint already owns the final geometry.
        self.app_header.hide()
        if hasattr(self, "bottom_bar"):
            self.bottom_bar.hide()
        self.layout().activate()
        if loading is None:
            self._switch_page(self.studio_page)
        self.pages.layout().activate()
        self.last_studio_transition_profile = {
            "request_to_layout_settled_ms": round((time.perf_counter() - transition_started) * 1000, 3)
        }
        # Resume the retained editor after Home. The explicit library command
        # still closes the project with its save guard and opens the Hub.
        candidate = str(project_path or "")
        if not candidate and self.studio_page.project is not None:
            candidate = str(self.studio_page.project_path or '')
        if candidate and not Path(candidate).is_file():
            if loading is not None:
                loading.fail('读取工程', tr('工程文件不存在：{path}', path=candidate))
            return
        if candidate and Path(candidate).is_file():
            def ready():
                project = self.studio_page.project
                if expected_result_ref:
                    from ..recognition.recognition_result import verify_result_reference
                    verify_result_reference(expected_result_ref, project=project, project_path=candidate)
                if skip_dirty_guard:
                    self._refresh_progress_cards()
                    self.studio_page._studio_trace('RECOGNITION_LOADED', project_path=candidate,
                        cue_count=len(project.cues) if project else 0,
                        project_id=project.project_id if project else '')
                profile_id = str(project.studio_state.get("profile_id", "")) if project else ""
                profile = self.profile_store.get(profile_id)
                # Opening an existing project is not an instruction to apply
                # its historical recognition settings to future jobs.
                if mode == "review":
                    self.studio_page._activate_filter("priority")
                elif mode == "render":
                    self.studio_page._open_render_dialog()
            if on_ready is not None:
                _base_ready = ready

                def ready(_base=_base_ready, _extra=on_ready):  # noqa: F811
                    _base()
                    try:
                        _extra(self.studio_page)
                    except Exception as exc:
                        self.studio_page._studio_trace(
                            "RECOGNITION_RESTORE_FAILED", error=str(exc)
                        )
            self.studio_page.open_project(candidate, on_ready=ready, skip_dirty_guard=skip_dirty_guard,
                expected_result_ref=expected_result_ref)
        else:
            self.studio_page.show_project_hub()
            if loading is not None:
                for stage in loading.view.steps_view.tasks:
                    if stage == '创建工作台界面':
                        loading.mark(stage)
                    elif stage == '首屏绘制':
                        self.studio_page.grab()
                        loading.mark(stage)
                    else:
                        loading.skip(stage, '进入工程库，没有载入工程')
                epoch = loading.generation
                def hub_ready():
                    if (loading.deliver(epoch) and loading.generation == epoch
                            and loading.state == 'ready' and on_ready is not None):
                        on_ready(self.built_page('studio'))
                QTimer.singleShot(0, self, hub_ready)
            self._retry_pending_recognition_reload()

    @navigation_timed('home.return')
    def _return_to_settings(self):
        loading = self.__dict__.get('_studio_loading_session')
        if loading is not None and (loading.active or loading.state == 'failed'):
            loading.return_target = 'home'
            self._cancel_studio_construction()
        else:
            self._cancel_pending_studio_entries()
        self._ensure_recognition_page()
        self._apply_saved_ai_configuration(source='home')
        self._refresh_available_asr_choices()
        self._restore_global_recognition_plan_for_home()
        self._switch_page(self.settings_scroll)

    def _restore_global_recognition_plan_for_home(self) -> None:
        """返回主页只刷新当前设置的视图；历史方案书签不拥有设置写权限。"""
        try:
            profile = getattr(self, "current_project_profile", None)
            if profile is None:
                return
            self._refresh_project_profile_combo(profile.id)
            self._refresh_glossary_chips()
            self._refresh_asr_summary()
            self._refresh_workshop_after_asr_change()
        except Exception:
            pass

    def _handle_studio_recognition_request(
        self, action: str, media_path: str, project_path: str
    ) -> None:
        self._ensure_recognition_page()
        media = Path(str(media_path or ""))
        project = Path(str(project_path or ""))
        if not media.is_file() or not project.is_file():
            self.studio_page.fail_recognition_runtime('当前工程或媒体文件已移动，请重新关联后再试。')
            QMessageBox.warning(
                self,
                tr('无法开始识别'),
                tr('当前工程或媒体文件已经移动，请在 Studio 中重新关联后再试。'),
            )
            return
        if str(action) == "configure":
            modal = getattr(self, "_modal_host", None)
            if modal is not None:
                modal.hide_content()
            self._switch_page(self.settings_scroll)
            return
        try:
            self.studio_page.save()
        except Exception as exc:
            self.studio_page.fail_recognition_runtime('工程保存失败：' + str(exc))
            QMessageBox.critical(self, tr('工程保存失败'), str(exc))
            return
        request_options = self.studio_page.recognition_request_options()
        plan_key = str(request_options.get("recognition_plan") or "home")
        index = self.recognition_mode_combo.findData(plan_key)
        if index >= 0:
            self.recognition_mode_combo.setCurrentIndex(index)
            self._apply_recognition_plan_from_ui()
        models = request_options.get("models") if isinstance(request_options.get("models"), dict) else {}
        for control, key in (
            (self.primary_asr_backend, "primary"),
            (self.firered_asr_backend, "timeline"),
            (self.qwen_asr_backend, "review"),
        ):
            value = str(models.get(key) or "")
            if value:
                self._set_backend_combo(control, value)
        self._studio_recognition_context = {
            "media_path": str(media.resolve()),
            "project_path": str(project.resolve()),
            "project_id": str(self.studio_page.project.project_id),
            "recognition_purpose": "analysis" if str(action) == "start_analysis" else "final",
            "enabled_glossary_ids": list(request_options.get("enabled_glossary_ids") or []),
            "replace_policy": str(request_options.get("replace_policy") or "replace_cues"),
            "recognition_plan": plan_key,
            "models": dict(models),
            "speaker_source": str(models.get('speaker_source') or self.speaker_source.currentData() or 'native'),
            # 2026-10-23: the sheet's translation choice is for this run only (home keeps its own).
            "subtitle_output": str(request_options.get("subtitle_output") or ""),
            "translation_script": str(request_options.get("translation_script") or ""),
        }
        # 2026-10-25: 只重新识别这一段 hears only this stretch of the timeline.
        range_ms = request_options.get("recognition_range_ms")
        if range_ms:
            self._studio_recognition_context["recognition_range_ms"] = [int(v) for v in range_ms]
        from ..recognition.recognition_input import capture_recognition_snapshot
        # 2026-10-24: audio tracks picked in Studio, each recognized on its own
        # input (a fast analysis reads the one picked track).
        lanes = [dict(row) for row in request_options.get("audio_lanes") or ()]
        self._studio_recognition_context["audio_lanes"] = lanes
        try:
            if range_ms:
                snapshot = capture_recognition_snapshot(self.studio_page.project, str(project.resolve()),
                                                        range_ms=range_ms)
                snapshot["requested_range_ms"] = [int(v) for v in request_options.get("requested_range_ms") or range_ms]
            elif lanes and str(action) == "start_analysis":
                snapshot = capture_recognition_snapshot(self.studio_page.project, str(project.resolve()), lane=lanes[0])
            else:
                snapshot = capture_recognition_snapshot(self.studio_page.project, str(project.resolve()),
                                                        lanes=lanes or None)
        except (OSError, ValueError, RuntimeError) as exc:
            self._studio_recognition_context = None
            self.studio_page.fail_recognition_runtime(str(exc))
            QMessageBox.warning(self, tr('无法开始识别'), str(exc))
            return
        self._studio_recognition_context["snapshot"] = snapshot
        self.media_paths = [str(media.resolve())]
        self._refresh_media_summary()
        if str(action) in {"start", "start_final", "start_analysis"}:
            # 四十二轮：同步调用 _start_run。此前 singleShot 异步启动，预检分支
            # （如 API 缺 Key 的"识别后端未保存"）弹出的 QMessageBox 会盖在
            # Studio 识别弹窗之下，嵌套模态吞掉全部输入=用户看到的"一直卡住"，
            # 且早退后无人复位弹窗状态。现在：识别弹窗已在 dispatch 里先关闭，
            # 警告框正常可见；未启动成功则把原因落到左侧字幕列表芯片。
            self._run_block_reason = ""
            try:
                self._start_run()
            except Exception as exc:
                self._studio_recognition_context = None
                self.studio_page.fail_recognition_runtime('启动识别失败：' + str(exc))
                QMessageBox.critical(self, tr('无法开始识别'), str(exc))
                return
            if not self._run_in_progress:
                self.studio_page.fail_recognition_runtime(
                    str(self._run_block_reason or "识别未能启动，请查看运行日志")
                )

    def _finish_studio_recognition(self, project_path: str, expected_result_ref=None) -> None:
        context = getattr(self, "_studio_recognition_context", None) or {}
        snapshot = context.get("snapshot")
        if snapshot and snapshot.get("range_ms"):
            # Only one stretch was recognized: the Studio splices it into the
            # open project as one undo step instead of opening the result.
            self._studio_recognition_context = None
            self.studio_page.apply_range_recognition_result(project_path, snapshot)
            return
        if snapshot:
            from ..recognition.recognition_input import project_content_revision
            studio = self.studio_page
            current = getattr(studio, "project", None)
            unchanged = (current is not None and current.project_id == snapshot["project_id"]
                         and project_content_revision(current.to_dict()) == snapshot["project_revision"])
            studio.note_recognition_kept_in_memory()
            self._studio_recognition_context = None
            if unchanged:
                self.open_studio_project(project_path, mode="edit", source="studio_recognition",
                    expected_result_ref=expected_result_ref)
            else:
                self._show_task_notification("识别结果已保存", "当前工程已有变化；请从完成页打开独立识别结果。", QMessageBox.Icon.Information)
            return
        target = Path(str(project_path or ""))
        if not target.is_file():
            bind_text(self.progress_stage, '字幕已生成，工程载入失败')
            bind_text(self.progress_resource, '工程文件未找到：{target}；请从结果页打开已保存的字幕', target=target)
            self._switch_page(2)
            return
        dialog = getattr(self, "_completion_dialog", None)
        if dialog is not None:
            dialog.close()
        modal = getattr(self, "_modal_host", None)
        if modal is not None:
            modal.hide_content()
        self._studio_recognition_context = None
        self._refresh_media_summary()
        # 四十二轮：识别转后台后，用户可能在识别期间继续编辑工程。有编辑时
        # 不再无条件重载（会静默丢弃），改为二选；无编辑保持原行为直接重载。
        # 2026-09-17：编辑判定改用 undo 栈计数——autosave 代次会被无编辑的
        # 周期保存顶掉，曾把无编辑的交接误判成"识别期间有编辑"。
        studio = self.built_page("studio")
        try:
            same_open = (
                studio is not None
                and getattr(studio, "project_path", None)
                and Path(str(studio.project_path)) == target.resolve()
            )
        except (OSError, ValueError):
            same_open = False
        edited_during_run = False
        if same_open and studio is not None:
            started_undo = getattr(studio, "_recognition_undo_count", None)
            current_undo = int(studio.undo_stack.count()) if getattr(studio, "undo_stack", None) is not None else 0
            edited_during_run = (
                started_undo is not None
                and int(current_undo) != int(started_undo)
            )
        # 无字幕且无编辑的工程没有任何"保留"价值，直接重载，不再弹问题框。
        if (
            same_open
            and studio is not None
            and getattr(studio.project, "cues", None) is not None
            and len(studio.project.cues) == 0
        ):
            edited_during_run = False
        if same_open and edited_during_run:
            box = QMessageBox(self)
            bind_text(box, '识别完成', property='windowTitle')
            box.setIcon(QMessageBox.Icon.Question)
            bind_text(box, '识别期间你对工程做了编辑。')
            bind_text(box, '重新加载将载入新字幕并丢弃这些编辑；保留编辑则新字幕已写入工程文件，稍后重新打开工程即可加载。', property='informativeText')
            box.addButton("重新加载", QMessageBox.ButtonRole.AcceptRole)
            keep_button = box.addButton("保留编辑", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            if box.clickedButton() is keep_button:
                studio.note_recognition_kept_in_memory()
                return
        # 保留用户当前的观察位置：重载只换数据，不重置视口（用户 2026-09-17 §2.3/2.4）。
        view_state = None
        if studio is not None:
            timeline = getattr(studio, "timeline", None)
            view_state = {
                "playhead_ms": int(getattr(timeline, "playhead_ms", 0) or 0),
                "visible_start_ms": int(getattr(timeline, "visible_start_ms", 0) or 0),
                "visible_duration_ms": int(getattr(timeline, "visible_duration_ms", 0) or 0),
                "selected_cue_id": str(getattr(studio, "selected_cue_id", "") or ""),
            }
            # 就绪门超时/取消会让这次重载静默失败；挂起待重载，Studio 下次
            # 进入时自动重试，用户不必回工程库手动重开。
            studio._pending_recognition_reload = str(target)
            studio._pending_recognition_result_ref = expected_result_ref

        def _restore_after_reload(page):
            cues = len(getattr(getattr(page, "project", None), "cues", ()) or ())
            page._studio_trace(
                "StudioSubtitleRefresh",
                asr_completed=True,
                segments=cues,
                project_model_updated=True,
                timeline_updated=True,
                subtitle_list_updated=True,
            )
            state = view_state or {}
            timeline = getattr(page, "timeline", None)
            if timeline is None:
                return
            duration = int(getattr(timeline, "_project_duration_ms", 0) or 0)
            start = max(0, min(int(state.get("visible_start_ms", 0) or 0), max(0, duration - 1000)))
            span = max(1, int(state.get("visible_duration_ms", 0) or 0))
            if duration:
                timeline.set_visible_window(start, min(span, duration))
            timeline.set_playhead(int(state.get("playhead_ms", 0) or 0))
            selected = str(state.get("selected_cue_id", "") or "")
            if selected:
                cues_by_id = getattr(timeline, "_timeline_cue_by_id", {}) or {}
                if selected in cues_by_id:
                    page.select_cue(selected)

        bind_text(self.progress_stage, '正在载入 Studio')
        self.progress_resource.setText(str(target))
        self.studio_page._studio_trace('RECOGNITION_HANDOFF', project_path=str(target),
            same_open=bool(same_open), edited_during_run=bool(edited_during_run))
        self.open_studio_project(target, mode="edit", source="studio_recognition",
                                 on_ready=_restore_after_reload, expected_result_ref=expected_result_ref)

    @observed('settings.open')
    def _open_application_settings(self, initial_section=None):
        """One shared settings entry for every workspace (Recognition/Library/Studio)."""
        from .application_settings import open_application_settings

        studio_page = self.built_page("studio")
        open_application_settings(
            self,
            on_saved=getattr(studio_page, "_after_application_settings_saved", None),
            reset_layout=getattr(studio_page, "_reset_studio_layout_preferences", None),
            refresh_library=getattr(studio_page, "_refresh_visible_library", None),
            initial_section=initial_section,
        )

    def _open_recognition_history(self):
        # Nav buttons are checkable and exclusive: reset the highlight that may
        # have been left on another item when this page was visited before.
        if hasattr(self.history_page, "restore_active_navigation"):
            self.history_page.restore_active_navigation()
        self._switch_page(self.history_page)

    @navigation_timed('home.asr_choices')
    def _refresh_available_asr_choices(self):
        """Refresh selectors after a model workshop install or uninstall."""
        if not hasattr(self, "primary_asr_backend"):
            return
        saved_models = self.legacy.RUNTIME_SETTINGS.get("models", {})
        current_models = {
            "primary_asr_backend": self.primary_asr_backend.currentData(),
            "qwen_asr_backend": self.qwen_asr_backend.currentData(),
            "firered_asr_backend": self.firered_asr_backend.currentData(),
        }
        # A saved first-run choice is intentionally absent from selectors until
        # its files are complete.  Preserve that pending choice across workshop
        # refreshes so a successful download activates the requested combination
        # instead of silently replacing its timeline with "off".
        pending_keys = {
            item[0] for item in getattr(self, "_missing_saved_asr_backends", ())
        }
        for key in pending_keys:
            current_models[key] = saved_models.get(key, current_models.get(key))
        live_settings = {
            "models": {
                **saved_models,
                **current_models,
            }
        }
        self._missing_saved_asr_backends = populate_available_asr_choices(
            self.primary_asr_backend,
            self.qwen_asr_backend,
            self.firered_asr_backend,
            live_settings,
        )
        self._apply_asr_backend_mode()

    def _open_terms_from_workshop(self):
        self._manage_terms()

    def _open_terms_from_history(self):
        self._manage_terms()

    def _open_ai_from_workshop(self):
        """Open the exact same AI settings dialog used on the home page."""
        self._open_ai_settings_dialog(on_finished=self.workshop_page.restore_active_navigation)

    def _open_task_settings_from_workshop(self):
        self._open_application_settings(initial_section="高级设置")

    def _reset_teach_hints(self) -> None:
        studio = self.built_page("studio")
        if studio is not None:
            studio._teach_hints.reset()
        else:
            # No need to build the whole workbench just to clear a small file.
            from .teach_hints import TeachHintStore
            TeachHintStore().reset()
        bind_text(self.term_hint, '教学提示已重置；下次进入相应功能时会再次显示。')
        self.term_hint.setVisible(bool(self.term_hint.text()))

    def _open_qwen_api_from_workshop(self):
        self._apply_asr_api_preset("qwen31_filetrans")

    def _saved_asr_api_endpoint(self) -> tuple[str, str, str]:
        """(provider, model, url) 已保存值——用户自定义地址不被预设强制刷新的依据。"""
        models = self.legacy.RUNTIME_SETTINGS.get("models", {})
        return (
            str(models.get("qwen_asr_api_provider", "qwen31_filetrans") or "qwen31_filetrans"),
            str(models.get("qwen_asr_api_model", "") or ""),
            str(models.get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"]) or ""),
        )

    def _apply_asr_preset_fields(self, preset_key: str):
        """按预设填模型/地址——除非用户已为该服务保存过自定义值（四十一轮：
        "最好是让用户能自行保存和确认 api 地址 而不是强制刷新"）。"""
        preset = ASR_API_PRESETS.get(str(preset_key))
        if preset is None or str(preset_key) == "custom":
            return
        saved_provider, saved_model, saved_url = self._saved_asr_api_endpoint()
        if str(preset_key) == saved_provider and (saved_model or saved_url):
            if saved_model:
                self.qwen_asr_api_model.setText(saved_model)
            if saved_url:
                self.qwen_asr_api_url.setText(saved_url)
            return
        self.qwen_asr_api_model.setText(preset["model"])
        self.qwen_asr_api_url.setText(preset["url"])

    def _open_api_key_dialog_for_preset(self, preset_key: str):
        """Explicit '配置' entry: always open the key dialog for this provider."""
        preset = ASR_API_PRESETS.get(str(preset_key))
        if preset is None:
            return
        provider_index = self.qwen_asr_api_provider.findData(str(preset_key))
        if provider_index >= 0:
            self.qwen_asr_api_provider.setCurrentIndex(provider_index)
        self._apply_asr_preset_fields(str(preset_key))
        self._open_api_key_dialog()

    def _apply_asr_api_preset(self, preset_key: str):
        preset = ASR_API_PRESETS.get(str(preset_key))
        if preset is None:
            QMessageBox.warning(self, tr('无法配置 API'), tr('未知的 ASR API 预设：{value0}', value0=preset_key))
            return
        target_combo = (
            self.primary_asr_backend
            if getattr(self.built_page("workshop"), "api_target_role", "") == "primary"
            else self.qwen_asr_backend
        )
        index = target_combo.findData("api")
        if index >= 0:
            target_combo.setCurrentIndex(index)
        provider_index = self.qwen_asr_api_provider.findData(preset_key)
        if provider_index >= 0:
            self.qwen_asr_api_provider.setCurrentIndex(provider_index)
        self._apply_asr_preset_fields(preset_key)
        from ..providers.llm_config import read_asr_api_key

        existing_key = read_asr_api_key(preset_key, self.qwen_asr_api_url.text().strip())[0]
        if existing_key:
            # 已保存过该服务商的 Key：不再弹窗（三十三轮用户实录"保存后又按
            # 一次使用又弹窗"），直接保存应用并刷新工坊选中态。
            self.qwen_asr_api_key.setText("")
            if self._save_asr_configuration(show_feedback=False):
                self.asr_save_status.setObjectName("statusOk")
                bind_text(self.asr_save_status, '已使用 {value0} · {value1}', value0=preset['label'], value1=self.qwen_asr_api_model.text().strip())
                self._refresh_workshop_after_asr_change()
            return
        self.asr_save_status.setObjectName("statusWarn")
        bind_text(self.asr_save_status, '已载入 {value0}；请填写该服务的 API Key 后保存', value0=preset['label'])
        self.asr_save_status.style().unpolish(self.asr_save_status)
        self.asr_save_status.style().polish(self.asr_save_status)
        self._open_api_setup_guide(preset_key)

    # ---- 「申请与设置 API」 guide (2026-10-13) --------------------------------
    def _api_setup_host(self):
        from ..providers.api_setup_dialog import SetupHost
        from ..providers.llm_config import read_asr_api_key, read_oss_credentials

        def saved_key(provider, url):
            return read_asr_api_key(provider, url)[0]

        def open_text_settings(service_id):
            self._open_ai_settings_dialog()
            # Open on the service the guide was about (it is saved only with 保存).
            dialog = getattr(self, "_ai_settings_dialog", None)
            # The top form (2026-10-22): the shared service, or 校对 and translation.
            editor = self.__dict__.get("_ai_main_editor") if dialog is not None else None
            index = editor.service.findData(str(service_id)) if editor is not None else -1
            if index >= 0:
                editor.service.setCurrentIndex(index)

        return SetupHost(settings=lambda: self.legacy.RUNTIME_SETTINGS, saved_key=saved_key,
                         saved_oss_credentials=read_oss_credentials,
                         save=self._save_cloud_provider_from_guide,
                         open_advanced=self._open_api_key_dialog_for_preset,
                         open_text_settings=open_text_settings)

    def _open_api_setup_guide(self, preset_key: str = "", kind: str = "asr"):
        from ..providers.api_setup_dialog import ApiSetupDialog
        initial = str(preset_key or self.qwen_asr_api_provider.currentData() or "mosi_moss_pro")
        dialog = ApiSetupDialog(self, self._api_setup_host(), kind=kind, initial=initial)
        dialog.exec()

    def _save_cloud_provider_from_guide(self, provider: str, values: dict, use_as_primary: bool):
        """Save one cloud ASR provider from the guide through the existing paths.

        Keys go to the same encrypted store as the advanced form; settings go
        through ``_save_asr_configuration``. Nothing is switched silently: any
        follow-up change needed to run without CUDA is reported back.
        """
        from ..providers.llm_config import save_oss_credentials, save_spark_credentials, validate_qwen_asr_endpoint
        preset = ASR_API_PRESETS.get(str(provider))
        if preset is None:
            return False, tr('未知的服务：{value0}', value0=provider)
        model = str(values.get('model') or preset['model'])
        url = str(values.get('url') or preset['url'])
        if provider == 'spark_asr_v2':
            credentials = {name: str(values.get(name) or '').strip() for name in ('app_id', 'api_key', 'api_secret')}
            try:
                validate_qwen_asr_endpoint(dict(protocol='spark_wss', model=model, url=url, **credentials),
                                           require_key=False)
                save_spark_credentials(url, **credentials)
            except Exception as exc:
                return False, str(exc)
        from ..providers.api_setup_catalog import UPLOAD_OWN_OSS, UPLOAD_PROVIDER
        if preset['protocol'] == 'dashscope_filetrans' and str(values.get('filetrans_upload') or '') == UPLOAD_OWN_OSS:
            bucket = str(values.get('oss_bucket') or '').strip()
            endpoint = str(values.get('oss_endpoint') or '').strip()
            if not bucket:
                return False, tr('请填写 OSS Bucket 名称（选了“使用我自己的 OSS”时需要它临时存放音频）。')
            if not endpoint.lower().startswith('https://'):
                return False, tr('OSS 地域无效。')
            key_id = str(values.get('oss_access_key_id') or '').strip()
            secret = str(values.get('oss_access_key_secret') or '').strip()
            if key_id or secret:
                try:
                    save_oss_credentials(key_id, secret)
                except Exception as exc:
                    return False, tr('OSS 凭据保存失败：{exc}', exc=exc)
            self.legacy.configure_runtime_asr({
                'oss_region': str(values.get('oss_region') or 'cn-hangzhou'), 'oss_endpoint': endpoint,
                'oss_bucket': bucket, 'oss_prefix': str(values.get('oss_prefix') or 'asr-temp/'),
                'oss_auto_delete': bool(values.get('oss_auto_delete', True)), 'filetrans_upload': UPLOAD_OWN_OSS})
        elif preset['protocol'] == 'dashscope_filetrans' and str(values.get('filetrans_upload') or '') == UPLOAD_PROVIDER:
            # The provider's temporary space (the default since 2026-10-28); an existing OSS setup stays saved.
            self.legacy.configure_runtime_asr({'filetrans_upload': UPLOAD_PROVIDER})
        index = self.qwen_asr_api_provider.findData(provider)
        if index >= 0:
            self.qwen_asr_api_provider.setCurrentIndex(index)
        self.qwen_asr_api_model.setText(model)
        self.qwen_asr_api_url.setText(url)
        self.qwen_asr_api_key.setText('' if provider == 'spark_asr_v2' else str(values.get('api_key') or '').strip())
        notes = []
        if use_as_primary:
            combo_index = self.primary_asr_backend.findData('api')
            if combo_index >= 0:
                self.primary_asr_backend.setCurrentIndex(combo_index)
            from ..recognition.recognition_choices import cloud_followups, host_profile
            current = dict(self.legacy.RUNTIME_SETTINGS.get('models', {}), **self._asr_values())
            patch, notes = cloud_followups(current, installed_model_keys(APP_ROOT), host_profile())
            for key, combo in (('firered_asr_backend', self.firered_asr_backend),
                               ('qwen_asr_backend', self.qwen_asr_backend)):
                if key in patch:
                    found = combo.findData(patch[key])
                    if found >= 0:
                        combo.setCurrentIndex(found)
        if not self._save_asr_configuration(show_feedback=False):
            return False, getattr(self, '_run_block_reason', '') or tr('保存失败')
        self._refresh_workshop_after_asr_change()
        message = tr('已保存。') + (tr('已设为主力转写。') if use_as_primary else '')
        return True, message + ''.join(notes)

    @navigation_timed('home.workshop')
    def _refresh_workshop_after_asr_change(self):
        workshop = self.built_page("workshop")
        if workshop is None:
            return
        try:
            workshop.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            active=getattr(self,'current_project_profile',None)
            (bind_text(workshop.combo_title, active.name + (' · ' + tr('自定义方案') if active.recognition_plan == 'custom' else '')) if active else bind_text(workshop.combo_title, '自定义方案'))
        except Exception:
            pass
        try:
            self.asr_save_status.style().unpolish(self.asr_save_status)
            self.asr_save_status.style().polish(self.asr_save_status)
        except Exception:
            pass

    def _timeline_helper_changed(self):
        self._refresh_asr_summary()

    def _apply_workshop_backend(self, role: str, value: str):
        if role == 'speaker':
            self.speaker_source.setCurrentIndex(max(0,self.speaker_source.findData(value)))
            if self._save_asr_configuration(show_feedback=False):
                self.workshop_page.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            return
        self._refresh_available_asr_choices()
        combo = (
            self.primary_asr_backend
            if role == "primary"
            else (self.qwen_asr_backend if role == "qwen" else self.firered_asr_backend)
        )
        index = combo.findData(value)
        if index < 0:
            QMessageBox.warning(self, tr('无法切换模型'), tr('不支持的识别后端：{value0} / {value1}', value0=role, value1=value))
            return
        combo.setCurrentIndex(index)
        if self._save_asr_configuration(show_feedback=False):
            self.workshop_page.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)

    def _open_support(self):
        from .support_entry import SupportDialog, support_entry_hidden
        if support_entry_hidden():
            self.support_button.hide()
            return
        if self._support_dialog is not None:
            target = self._support_dialog._confirmation or self._support_dialog
            target.raise_()
            target.activateWindow()
            return
        dialog = SupportDialog(self)
        self._support_dialog = dialog
        dialog.entry_hidden.connect(self._support_entry_hidden)
        dialog.finished.connect(self._support_closed)
        dialog.show()

    def _support_closed(self, _result):
        dialog, self._support_dialog = self._support_dialog, None
        if dialog is not None:
            dialog.deleteLater()

    def _support_entry_hidden(self):
        self.support_button.hide()
        self._refresh_header_density()

    def _set_update_idle(self):
        self.update_button.setEnabled(True)
        if getattr(self, '_prepared_update', None) is not None:
            bind_text(self.update_button, '重启以完成更新')
        elif getattr(self, '_available_update', None) is not None:
            bind_text(self.update_button, '新版本 {value0}', value0=self._available_update.latest_version)
        else:
            bind_text(self.update_button, '检查更新')

    def _after_startup_interactive(self):
        """Startup has painted: confirm a just-applied update, then idle work."""
        try:
            confirm_started(current_version())
        except Exception as exc:  # noqa: BLE001 - never block startup
            print(f"[update] confirm failed: {exc}")
        threading.Thread(target=cleanup_after_update, name='update-cleanup', daemon=True).start()
        if automatic_checks_allowed():
            from .application_settings import update_reminder_enabled
            QTimer.singleShot(automatic_check_delay_ms(update_reminder_enabled()), self, self._auto_check_updates)
        QTimer.singleShot(2500, self, self._warm_studio_module)
        # Hardware, models and cloud setup are checked off the GUI thread.
        QTimer.singleShot(0, self, self._refresh_next_step)

    # ---- 现在先做什么 (2026-10-13) --------------------------------------------
    def _refresh_next_step(self, probe: bool = True):
        """Re-evaluate the home card; ``probe`` re-checks this computer in the background."""
        card = self.__dict__.get("next_step_card")
        if card is None:
            return
        if os.environ.get("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD") == "1" and not os.environ.get("TWOBYTEASR_ONBOARDING"):
            card.hide()  # automated acceptance runs keep their historic home page
            return
        from . import onboarding
        self._onboarding_state = onboarding.ensure_state()
        self._render_next_step()
        if not probe:
            return
        if not (getattr(self, "media_paths", None) or []):
            # The welcome card needs no facts and nothing else shows without
            # media: no background model/hardware scan competes with startup.
            return
        self._onboarding_generation = getattr(self, "_onboarding_generation", 0) + 1
        generation = self._onboarding_generation
        settings = copy.deepcopy(self.legacy.RUNTIME_SETTINGS)

        def work():
            try:
                facts = onboarding.probe_facts(settings, APP_ROOT)
            except Exception:
                traceback.print_exc()
                return
            self._onboarding_facts_ready.emit((generation, facts))

        threading.Thread(target=work, name="onboarding-facts", daemon=True).start()

    def _schedule_next_step_probe(self):
        """Coalesce bursts of setting changes into one background check."""
        timer = self.__dict__.get("_next_step_probe_timer")
        if timer is None:
            timer = self._next_step_probe_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(lambda: self._refresh_next_step(probe=True))
        timer.start()

    def _onboarding_facts_received(self, payload):
        generation, facts = payload
        if generation != getattr(self, "_onboarding_generation", 0):
            return
        self._onboarding_facts = facts
        self._render_next_step()
        self._onboarding_rendered = generation   # the tutorial waits for this after the demo video (2026-10-24)

    def _render_next_step(self):
        card = self.__dict__.get("next_step_card")
        if card is None:
            return
        from .onboarding import compute_next_step
        step = compute_next_step(media_count=len(getattr(self, "media_paths", []) or []),
                                 facts=getattr(self, "_onboarding_facts", None),
                                 state=getattr(self, "_onboarding_state", {}) or {},
                                 running=bool(getattr(self, "_run_in_progress", False)))
        card.show_step(step)

    def _next_step_action(self, action: str):
        from . import onboarding
        if action == "choose_media":
            self._choose_media()
        elif action == "open_projects":
            self.open_studio_project()
        elif action == "open_sample":
            self._open_sample_project()
        elif action == "choose_plan":
            if _open_quick_setup(self):
                self._refresh_asr_summary()
            self._refresh_next_step()
            self._after_quick_setup()
        elif action == "setup_api":
            self._open_api_setup_guide()
            self._refresh_next_step()
        elif action.startswith("use_plan:"):
            self._apply_plan_choice(action.split(":", 1)[1])
        elif action == "dismiss":
            self._onboarding_state = onboarding.set_guide(False)
            self._render_next_step()
        elif action == "show_guide":
            self._onboarding_state = onboarding.set_guide(True)
            self._switch_page(0)
            self._refresh_next_step()
        elif action == "tour":
            self._start_home_tour()

    def _start_home_tour(self, part: str = "all"):
        """Point at the real page parts one by one (2026-10-14).

        2026-10-22 (user: "进阶" made people think the basics were enough): one
        tutorial from the first video to the workbench; it starts on the home page.
        """
        if part != "advanced" and self.pages.currentWidget() is not self.__dict__.get("settings_scroll"):
            self._switch_page(0)
            self._home_tour_pending = True
            return
        from . import onboarding
        from .home_tour import start_home_tour

        def done(completed):
            onboarding.save_state(dict(onboarding.load_state(), tour_done=True))
            self._tutorial_finish(completed)
        start_home_tour(self, done, part)

    def _current_plan_key(self) -> str:
        """Which quick-chooser plan the saved roles are: cloud, local, apple, light or '' (custom)."""
        from .quick_setup import PLANS
        models = dict((self.legacy.RUNTIME_SETTINGS or {}).get("models") or {})
        primary = str(models.get("primary_asr_backend") or "")
        if primary == "api":
            return "cloud" if str(models.get("qwen_asr_api_provider") or "") == "mosi_moss_pro" else ""
        return next((key for key, plan in PLANS.items() if key != "cloud" and plan.backends[0] == primary), "")

    def _choose_plan_in_tutorial(self) -> str:
        """The tutorial's plan step (2026-10-22): cloud or local compared, the choice saved, downloads after the tutorial.

        2026-10-24: the first step, with the language the videos mainly speak."""
        choice = _open_quick_setup(self, compare=True)
        self._refresh_asr_summary()
        self._refresh_next_step()
        return choice or ""

    def _after_quick_setup(self):
        """After the chooser (2026-10-21): the tutorial if its box stayed ticked, on the home page.

        2026-10-24: when a plan was just chosen there, the tutorial's first step
        (plan and language) does not open the comparison again by itself."""
        chosen = bool(self.__dict__.pop("_quick_setup_chosen", False))
        if not self.__dict__.pop("_quick_setup_tour", False):
            return
        self._tutorial_plan_chosen = chosen
        def start_when_home():
            if self.pages.currentWidget() is self.__dict__.get("settings_scroll"):
                self._start_home_tour()
            else:
                self._home_tour_pending = True  # e.g. the workshop opened for a download
        QTimer.singleShot(500, start_when_home)

    def _start_first_run_downloads(self):
        """The cloud choice's timeline model, once the tutorial is over (2026-10-21)."""
        pending = self.__dict__.pop("_first_run_downloads", None)
        if not pending:
            return
        primary, keys, *rest = pending
        source = rest[0] if rest else 'AUTO'
        try:
            from ..local_models.model_workshop import MODELS, installed_model_keys
            installed = installed_model_keys(APP_ROOT)
            have = {model.download_key for model in MODELS if model.key in installed and model.download_key}
            keys = tuple(key for key in keys if key not in have)
        except Exception:  # noqa: BLE001 - the workshop checks again before it downloads anything
            traceback.print_exc()
        if keys:
            _open_combination_download(self, primary, keys, source)

    # ---- tutorial demo data (2026-10-14): the bundled example, nothing uploaded --------
    def _tutorial_prepare_demo(self):
        """Make sure the tutorial project and its video exist (first time ~2 s, off the GUI thread)."""
        def work():
            try:
                from .sample_project import ensure_tutorial_project
                self._tutorial_sample = ensure_tutorial_project()
            except Exception:  # noqa: BLE001 - the media step reports it
                traceback.print_exc()
        threading.Thread(target=work, name="tutorial-sample", daemon=True).start()

    def _tutorial_demo_media(self):
        from .sample_project import ensure_tutorial_project, tutorial_root
        media = tutorial_root() / "教学影片.mp4"
        if not media.is_file():
            ensure_tutorial_project()
        return media

    def _tutorial_add_demo_media(self):
        self._tutorial_media = str(self._tutorial_demo_media())
        self.import_media([self._tutorial_media], replace=True)

    def _tutorial_demo_completion(self):
        """The result page of a pretend recognition: a fresh copy of the tutorial project."""
        from .sample_project import ensure_tutorial_project, tutorial_root
        from ..recognition.service import MediaResult, QueueResult
        from ..projects.studio_project import load_project
        from ..exports.studio_subtitle_export import compile_srt
        project_path = ensure_tutorial_project()
        root = tutorial_root()
        srt = root / "兔白字幕教学.srt"
        srt.write_text(compile_srt(load_project(project_path).cues), encoding="utf-8")
        report = root / "demo-report.json"
        media = str(self._tutorial_demo_media())
        report.write_text(json.dumps({
            "status": "success", "demo": True, "media": {"path": media},
            "result": {"outputs": {"project": str(project_path), "srt": str(srt)}, "elapsed_seconds": 12.6},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        item = MediaResult(media_path=media, status="success", srt_path=str(srt), report_json_path=str(report),
                           project_path=str(project_path), elapsed_seconds=12.6)
        self._last_run_options = None
        self._tutorial_demo_result = True  # not a first task, not a history record
        try:
            self._handle_result(QueueResult((item,), 12.6))
        finally:
            self._tutorial_demo_result = False

    def _tutorial_finish(self, completed: bool):
        """Leave the window as a new user expects: demo media gone, back on the home page."""
        demo = getattr(self, "_tutorial_media", "")
        if demo and [str(p) for p in (getattr(self, "media_paths", None) or [])] == [demo]:
            self._clear_media_paths()
        proofread = self.__dict__.get("glossary_proofread_page")
        if proofread is not None:
            proofread.ai_stand_in = None  # "AI 校对" asks the real service again
        try:
            from .sample_project import tutorial_project_path
            studio = self.built_page("studio")
            if studio is not None and studio.project is not None and str(studio.project_path or "") and \
                    os.path.normcase(os.path.abspath(str(studio.project_path))) == \
                    os.path.normcase(os.path.abspath(str(tutorial_project_path()))):
                # Demo data: put it away without a "save changes?" question later.
                studio.undo_stack.setClean()
                studio._close_project_session("tutorial-finished")
            from .sample_project import discard_tutorial_autosave
            discard_tutorial_autosave()   # and no "recover autosave" for it on the next start
            # The demo project is not one of the user's projects: keep it out of "最近工程".
            remove = getattr(studio, "_remove_recent_project_metadata_batch", None) if studio is not None else None
            if callable(remove):
                remove({str(tutorial_project_path())})
            self._refresh_studio_entry_card()
        except Exception:  # noqa: BLE001 - leaving the tutorial must never fail
            traceback.print_exc()
        if completed and self.pages.currentWidget() is not self.__dict__.get("settings_scroll"):
            self._return_to_settings()
        self.activateWindow()
        self.setFocus()  # keys go to the home page again, not to a page left behind
        QTimer.singleShot(400, self._start_first_run_downloads)   # 云端识别's timeline model (2026-10-21)

    def _apply_plan_choice(self, option_key: str):
        """A plan the user picked on the card: set the three roles, save once."""
        from .onboarding import plan_patch
        facts = getattr(self, "_onboarding_facts", None)
        patch = plan_patch(option_key, facts) if facts is not None else {}
        if not patch:
            return
        for key, combo in (("primary_asr_backend", self.primary_asr_backend),
                           ("firered_asr_backend", self.firered_asr_backend),
                           ("qwen_asr_backend", self.qwen_asr_backend)):
            if key in patch:
                index = combo.findData(patch[key])
                if index < 0:
                    combo.addItem(str(patch[key]), patch[key])
                    index = combo.findData(patch[key])
                combo.setCurrentIndex(index)
        if self._save_asr_configuration(show_feedback=False):
            self._refresh_asr_summary()
        self._refresh_next_step()

    def _open_sample_project(self):
        """The bundled example (generated on first use, ~2 s, nothing uploaded)."""
        from .sample_project import ensure_sample_project, sample_project_path
        path = sample_project_path()
        if path.is_file():
            self.open_studio_project(str(path))
            return
        self._sample_progress = QMessageBox(self)
        self._sample_progress.setIcon(QMessageBox.Icon.Information)
        bind_text(self._sample_progress, '范例工程', property='windowTitle')
        bind_text(self._sample_progress, '正在准备范例工程（示意影片与说明字幕，不上传任何东西）…')
        self._sample_progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
        self._sample_progress.show()

        def work():
            try:
                result = (True, str(ensure_sample_project()))
            except Exception as exc:  # noqa: BLE001 - reported to the user
                result = (False, str(exc))
            self._sample_ready.emit(result)

        threading.Thread(target=work, name="sample-project", daemon=True).start()

    def _sample_project_ready(self, result):
        ok, value = result
        box = getattr(self, "_sample_progress", None)
        if box is not None:
            box.hide()
            box.deleteLater()
            self._sample_progress = None
        if ok:
            self.open_studio_project(value)
        else:
            QMessageBox.warning(self, tr('范例工程'), tr('没能准备范例工程：{reason}', reason=value))

    def _warm_studio_module(self):
        """Run the startup idle tasks, then load the Studio module tree.

        Neither runs before the first window (~0.35 s of the start each).
        Done on the GUI thread on purpose: a background import could race a
        GUI-thread import of the same package cycle. Without this the first
        click into Studio would pay for it."""
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activePopupWidget():
            QTimer.singleShot(1000, self, self._warm_studio_module)
            return
        while _STARTUP_IDLE_TASKS:
            _STARTUP_IDLE_TASKS.pop(0)()
        if self.built_page("studio") is not None or "twobyteasr.studio.studio_ui" in sys.modules:
            return
        import twobyteasr.studio.studio_ui  # noqa: F401

    def _auto_check_updates(self):
        if (self.update_check_worker and self.update_check_worker.isRunning()) or \
                (self.update_download_worker and self.update_download_worker.isRunning()):
            return
        from .application_settings import update_reminder_enabled
        worker = UpdateCheckWorker(self, automatic=True, reminder=update_reminder_enabled())
        self.update_check_worker = worker
        worker.result_ready.connect(self._auto_update_check_finished)
        worker.failed.connect(self._auto_update_check_failed)
        worker.start()

    def _auto_update_check_failed(self, detail: str):
        print(f"[update] automatic check failed: {detail}")

    def _auto_update_check_finished(self, check):
        if check.newer and getattr(self, '_prepared_update', None) is None:
            self._available_update = check
            self._set_update_idle()
            bind_text(self.update_button, '发现新版本 {value0}，点击查看更新内容和下载量', property='toolTip',
                      value0=check.latest_version)
            if not getattr(self.update_check_worker, '_user_waiting', False):
                # The user pressed 检查更新 meanwhile: that click shows the offer.
                self._remind_update(check)

    def _update_reminder_busy(self) -> bool:
        """The user is in the middle of something the reminder must not cut into."""
        from PySide6.QtWidgets import QApplication
        from .home_tour import GuidedTour
        workers = (self.update_check_worker, self.update_download_worker)
        tour = self.findChild(GuidedTour)
        return bool(QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None
                    or (tour is not None and tour.isVisible()) or getattr(self, '_home_tour_pending', False)
                    or getattr(self, '_run_in_progress', False) or getattr(self, '_prepared_update', None) is not None
                    or getattr(self, '_update_offer_dialog', None) is not None
                    or any(worker is not None and worker.isRunning() and not getattr(worker, 'reminder', False)
                           for worker in workers))

    def _remind_update(self, check, tries=0):
        """Start-up reminder (2026-10-24): offer a newer version by itself once
        per start, when the user is not busy; the dialog's check box or
        应用设置 → 关于 turns it off."""
        from .application_settings import update_reminder_enabled
        from .update_dialog import REMINDER_RETRY_MS, reminder_action
        action = reminder_action(check, enabled=update_reminder_enabled(),
                                 reminded_version=getattr(self, '_reminded_update_version', ''),
                                 busy=self._update_reminder_busy(), tries=tries)
        if action == 'later':
            QTimer.singleShot(REMINDER_RETRY_MS, self, lambda: self._remind_update(check, tries + 1))
        elif action == 'show' and getattr(self, '_available_update', None) is check:
            self._reminded_update_version = check.latest_version
            self._offer_update(check, reminder=True)

    def _check_updates(self):
        if getattr(self, '_prepared_update', None) is not None:
            self._offer_prepared_update(self._prepared_update)
            return
        if self.update_download_worker and self.update_download_worker.isRunning():
            answer = QMessageBox.question(self, tr('正在下载更新'),
                                          tr('要取消这次更新下载吗？已下载的部分会保留，下次继续。'))
            if answer == QMessageBox.StandardButton.Yes:
                self.update_download_worker.cancel_event.set()
            return
        running = self.update_check_worker
        if running and running.isRunning():
            if getattr(running, 'automatic', False) and not getattr(running, '_user_waiting', False):
                # A silent background check is in flight: show its result to the user.
                running._user_waiting = True
                running.result_ready.connect(self._update_check_finished)
                running.failed.connect(self._update_check_failed)
                running.skipped.connect(self._auto_check_skipped_for_user)
                running.finished.connect(self._auto_check_finished_for_user)
                self.update_button.setEnabled(False)
                bind_text(self.update_button, '正在检查…')
            return
        self.update_button.setEnabled(False)
        bind_text(self.update_button, '正在检查…')
        worker = UpdateCheckWorker(self)
        self.update_check_worker = worker
        worker.result_ready.connect(self._update_check_finished)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(self._set_update_idle)
        worker.start()

    def _auto_check_skipped_for_user(self):
        self._update_check_rerun = True

    def _auto_check_finished_for_user(self):
        # Slots of the main window run on the GUI thread (queued connection).
        if getattr(self, '_update_check_rerun', False):
            self._update_check_rerun = False
            self._check_updates()
        else:
            self._set_update_idle()

    def _update_check_failed(self, detail: str):
        message = QMessageBox(self)
        bind_text(message, '检查更新失败', property='windowTitle')
        message.setIcon(QMessageBox.Icon.Warning)
        bind_text(message, '暂时无法取得更新信息，程序可以照常使用。')
        bind_text(message, '{value0}\n\n可稍后重试，或打开发布页手动下载。在中国大陆，GitCode 通常更快。',
                  property='informativeText', value0=detail)
        # 2026-10-22: github.com timed out on a mainland line while GitCode
        # carried the same release files at ~14 MB/s.
        pages = {message.addButton(tr("打开 GitHub 发布页"), QMessageBox.ButtonRole.AcceptRole): RELEASE_PAGE,
                 message.addButton(tr("打开 GitCode 发布页"), QMessageBox.ButtonRole.AcceptRole): GITCODE_RELEASE_PAGE}
        message.addButton(tr("关闭"), QMessageBox.ButtonRole.RejectRole)
        message.exec()
        if message.clickedButton() in pages:
            QDesktopServices.openUrl(QUrl(pages[message.clickedButton()]))

    def _update_check_finished(self, check):
        if not check.newer:
            self._available_update = None
            QMessageBox.information(
                self,
                tr('已经是最新版'),
                tr('当前版本 {value0}，发布版 {value1}。', value0=check.current_version, value1=check.latest_version),
            )
            return
        self._available_update = check
        self._offer_update(check)

    def _offer_update(self, check, *, reminder=False):
        dialog = UpdateOfferDialog(check, self, reminder=reminder)
        self._update_offer_dialog = dialog
        dialog.exec()
        self._update_offer_dialog = None
        if reminder and not dialog.keep_reminding:
            from .application_settings import save_update_reminder
            save_update_reminder(False)
        if dialog.choice == 'page':
            QDesktopServices.openUrl(QUrl(check.release_url))
        elif dialog.choice == 'setup':
            QDesktopServices.openUrl(QUrl(check.installer_url))
        elif dialog.choice == 'download':
            self._download_update(check)

    def _download_update(self, check):
        worker = UpdateDownloadWorker(check, self)
        self.update_download_worker = worker
        worker.progress_changed.connect(self._update_download_progress)
        worker.completed.connect(self._update_download_finished)
        worker.failed.connect(self._update_download_failed)
        worker.cancelled.connect(self._set_update_idle)
        bind_text(self.update_button, '准备下载更新…')
        worker.start()

    def _update_download_progress(self, received: int, total: int):
        if total > 0:
            percent = min(100, int(received * 100 / total))
            bind_text(self.update_button, '下载更新 {percent}%', percent=percent)
        else:
            bind_text(self.update_button, '已下载 {value0:.1f} MB', value0=received / 1048576)

    def _update_download_failed(self, detail: str):
        self._set_update_idle()
        QMessageBox.warning(
            self,
            tr('更新下载失败'),
            tr('更新未修改任何程序文件。可稍后重试或直接覆盖安装新版。\n\n{value0}', value0=detail),
        )

    def _update_download_finished(self, prepared):
        self._prepared_update = prepared
        self._set_update_idle()
        self._offer_prepared_update(prepared)

    def _offer_prepared_update(self, prepared):
        answer = QMessageBox.question(
            self,
            tr('更新已准备好'),
            tr('兔白字幕 {value0} 已下载并校验完成（本次下载 {value1}）。\n\n需要退出程序才能完成更新：'
               '退出前会提示保存未保存的工程，更新完成后自动重新打开。设置、词库、工程、模型和运行环境都会保留。'
               '\n\n现在退出并更新吗？',
               value0=prepared.version, value1=format_bytes(prepared.downloaded_bytes)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._apply_prepared_update(prepared)

    def _update_blockers(self) -> list[str]:
        """Work that must finish first; updating never cancels it."""
        blockers = []
        if self.worker is not None and self.worker.isRunning():
            blockers.append(tr('字幕识别正在进行'))
        studio = self.built_page('studio')
        if getattr(getattr(studio, 'export_workspace', None), '_running', False):
            blockers.append(tr('视频导出正在进行'))
        workshop = self.built_page('workshop')
        active_download = getattr(workshop, '_active_download_dialog', None)
        if callable(active_download) and active_download() is not None:
            blockers.append(tr('模型下载或环境准备正在进行'))
        own = (self.update_check_worker, self.update_download_worker, self.worker)
        for value in list(vars(self).values()):
            if isinstance(value, QThread) and value not in own and value.isRunning():
                blockers.append(tr('后台任务正在进行'))
                break
        return blockers

    def _apply_prepared_update(self, prepared):
        blockers = self._update_blockers()
        if blockers:
            QMessageBox.information(
                self, tr('暂时不能更新'),
                tr('{value0}。请等它完成后再点“重启以完成更新”；更新已保留，不会重复下载。', value0='；'.join(blockers)))
            return
        self._pending_update = prepared
        self.close()
        if self.isVisible() and not getattr(self, '_studio_close_pending', False):
            # The user cancelled at the save prompt: keep working, keep the update.
            self._pending_update = None
            self._set_update_idle()

    def launch_pending_update(self) -> bool:
        """Called after the event loop ended; hands over to the updater."""
        prepared = getattr(self, '_pending_update', None)
        if prepared is None:
            return False
        try:
            launch_update_helper(prepared, wait_pid=os.getpid())
            return True
        except Exception as exc:  # noqa: BLE001 - the old program stays intact
            print(f"[update] helper launch failed: {exc}")
            return False

    def _queue_workflow_show(self):
        return

    def _queue_workflow_hide(self):
        return

    def _keep_workflow_open(self):
        return

    def show_workflow_popover(self):
        return

    def _collapse_workflow(self):
        self._workflow_expanded = False
        self.workflow.hide()

    def _workflow_animation_finished(self):
        self.workflow.hide()

    def _settings_page(self):
        """Build the Home page (recognition setup); the name predates the home redesign."""
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        self.settings_page_widget = page
        self.settings_page_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        page_heading = QHBoxLayout()
        page_heading.setSpacing(12)
        # 2026-10-23 (user: the plan toolbar sat on the page's top edge): the
        # same room above the heading row as below it, so the row sits midway.
        page_heading.setContentsMargins(0, 10, 0, 0)
        title = QLabel("本批字幕")
        title.setObjectName("sectionTitle")
        # P0: allow natural width; CN text must not truncate. Max was causing squeeze on some locales.
        title.setMaximumWidth(320)
        page_heading.addWidget(title)
        page_subtitle = QLabel("依次确认素材、当前内容、启用词库和识别方案")
        page_subtitle.setObjectName("pageSubtitle")
        page_heading.addWidget(page_subtitle)
        page_heading.addStretch(1)
        layout.addLayout(page_heading)
        # 2026-10-13: "现在先做什么" — one short card from the real state
        # (welcome for a fresh install, or what is missing). Hidden otherwise.
        from .onboarding import build_card
        self.next_step_card = build_card(page)  # styles itself from the current theme
        self.next_step_card.action_requested.connect(self._next_step_action)
        layout.addWidget(self.next_step_card)
        # 素材区放在最上方：整张卡片是选择/拖放主操作。空态是一块醒目的大投放区，
        # 载入素材后收成一行（2026-10-08）；见 _apply_media_mode。
        self.media_frame = MediaPickCard()
        self.media_frame.setProperty("dropActive", False)
        self.media_frame.setMinimumHeight(66)
        self.media_frame.activated.connect(self._choose_media)
        media_row = QHBoxLayout(self.media_frame)
        self.media_row_layout = media_row
        media_row.setContentsMargins(12, 8, 12, 8)
        self.media_lead_space = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        media_row.addSpacerItem(self.media_lead_space)
        media_icon = QLabel()
        media_icon.setObjectName("mediaIcon")
        media_icon.setFixedSize(36, 36)
        media_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_type_icon = media_icon
        media_row.addWidget(media_icon)
        media_row.addSpacing(4)
        self.media_kind_label = QLabel("本地素材")
        media_row.addWidget(self.media_kind_label)
        self.media_kind_gap = QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        media_row.addSpacerItem(self.media_kind_gap)
        media_text = QVBoxLayout()
        media_text.setSpacing(1)
        media_text.addStretch(1)  # lines stay together, centred, at any drop-zone height
        self.media_name = MediaNameLabel("")
        self.media_name.setObjectName("mediaName")
        self.media_drop_hint = QLabel("可把视频 / 音频拖到窗口，或按回车选择")
        self.media_drop_hint.setObjectName("dropHint")
        media_name_row = QHBoxLayout()
        media_name_row.setSpacing(8)
        media_name_row.addWidget(self.media_name)
        self.media_ready_badge = QLabel()
        self.media_ready_badge.setObjectName("mediaReadyBadge")
        bind_text(self.media_ready_badge, '已就绪')
        self.media_ready_badge.hide()
        media_name_row.addWidget(self.media_ready_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        media_name_row.addStretch(1)
        media_text.addLayout(media_name_row)
        media_text.addWidget(self.media_drop_hint)
        from ..media.media_intake import SUPPORTED_MEDIA_SUFFIXES
        formats = sorted(suffix.lstrip(".").upper() for suffix in SUPPORTED_MEDIA_SUFFIXES)
        self.media_formats = QLabel("  ·  ".join(formats))
        self.media_formats.setObjectName("mediaFormats")
        self.media_formats.hide()
        media_text.addWidget(self.media_formats)
        self.media_origin_label = QLabel("来自兔白字幕工程")
        self.media_origin_label.setObjectName("studioOrigin")
        self.media_origin_label.hide()
        media_text.addWidget(self.media_origin_label)
        media_text.addStretch(1)
        media_row.addLayout(media_text, 1)
        self._media_text_index = media_row.count() - 1
        media_row.addSpacing(12)
        self.choose_media_button = AnimatedButton("选择素材")
        self.choose_media_button.setObjectName("softAction")
        install_themed_icon(self.choose_media_button, "fa5s.folder-open")
        self.choose_media_button.clicked.connect(self._choose_media)
        media_row.addWidget(self.choose_media_button)
        self.link_download_button = AnimatedButton("链接下载")
        self.link_download_button.setObjectName("softAction")
        bind_text(self.link_download_button, "链接下载")
        install_themed_icon(self.link_download_button, "fa5s.link")
        from .link_download_controller import show_link_download
        self.link_download_button.clicked.connect(lambda: show_link_download(self))
        media_row.addWidget(self.link_download_button)
        self.clear_single_media_button = QToolButton()
        self.clear_single_media_button.setAutoRaise(True)
        install_themed_icon(self.clear_single_media_button, "fa5s.times")
        bind_text(self.clear_single_media_button, '移除素材', property='toolTip')
        self.clear_single_media_button.clicked.connect(self._clear_media_paths)
        media_row.addWidget(self.clear_single_media_button)
        self.media_tail_space = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        media_row.addSpacerItem(self.media_tail_space)
        layout.addWidget(self.media_frame)
        # A visible input list keeps multi-file ingestion reversible. The drop
        # card remains the primary action; rows expose type/status and removal.
        self.media_input_list = QFrame()
        self.media_input_list.setObjectName("mediaInputList")
        self.media_input_list_layout = QVBoxLayout(self.media_input_list)
        self.media_input_list_layout.setContentsMargins(8, 4, 8, 4)
        self.media_input_list_layout.setSpacing(4)
        self.media_input_list.hide()
        layout.addWidget(self.media_input_list)
        # Grows on tall windows (_fit_home_rhythm) so the cards sit between
        # even gaps instead of above an empty strip.
        self._home_mid_space = QSpacerItem(0, 2, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout.addSpacerItem(self._home_mid_space)
        # 2026-10-08 (user): the left third is the project entrance — one
        # cover of the latest project with its name and info, a few other
        # recent project names, and the way into the Studio. A cover or row
        # opens that project; the button or card background opens the library.
        from .home_studio_entry import RecentProjectHero, RecentProjectList, StudioEntryCard
        studio_entry = StudioEntryCard()
        studio_entry.setObjectName("studioEntryCard")
        studio_entry.show_backdrop = False
        studio_entry.clicked.connect(lambda: self.open_studio_project())
        entry_layout = QVBoxLayout(studio_entry)
        entry_layout.setContentsMargins(20, 18, 20, 18)
        self._home_studio_layout = entry_layout
        entry_layout.setSpacing(12)
        entry_head = QHBoxLayout()
        entry_head.setSpacing(14)
        entry_icon = QLabel()
        entry_icon.setObjectName("homeCardIcon")
        entry_icon.setFixedSize(40, 40)
        entry_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.studio_entry_icon = entry_icon
        entry_head.addWidget(entry_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        entry_text = QVBoxLayout()
        entry_text.setSpacing(2)
        entry_eyebrow = QLabel("字幕与视频编辑")
        entry_eyebrow.setObjectName("studioEntryEyebrow")
        entry_eyebrow.setParent(studio_entry)
        entry_eyebrow.hide()
        entry_title = QLabel("字幕工作台")
        entry_title.setObjectName("homeSectionTitle")
        entry_text.addWidget(entry_title)
        entry_hint = QLabel("校对字幕、剪辑片段、调整样式并压制成片")
        entry_hint.setObjectName("homeSectionHint")
        entry_hint.setWordWrap(True)
        entry_text.addWidget(entry_hint)
        # Kept for callers/audits; the gallery below shows the same project.
        self.studio_entry_recent = QLabel("最近：暂无工程")
        self.studio_entry_recent.setObjectName("studioEntryHint")
        self.studio_entry_recent.setParent(studio_entry)
        self.studio_entry_recent.hide()
        for label in (entry_icon, entry_title, entry_hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        entry_head.addLayout(entry_text, 1)
        entry_head.setContentsMargins(0, 0, 0, 0)
        entry_layout.addLayout(entry_head)

        def open_recent(path):
            self.open_studio_project(path) if path else self.open_studio_project()

        self.studio_recent_hero = RecentProjectHero(studio_entry)
        self.studio_recent_hero.open_requested.connect(open_recent)
        entry_layout.addWidget(self.studio_recent_hero, 1)
        self.studio_recent_caption = QLabel("最近工程")
        self.studio_recent_caption.setObjectName("homeFactCaption")
        entry_layout.addWidget(self.studio_recent_caption)
        self.studio_recent_list = RecentProjectList(studio_entry, limit=2)
        self.studio_recent_list.open_requested.connect(open_recent)
        self.studio_recent_list.preview_requested.connect(self._preview_recent_project)
        entry_layout.addWidget(self.studio_recent_list)
        # The cover caps at 16:10; any spare height stays above the button.
        entry_layout.addStretch(0)
        entry_open = AnimatedButton("进入字幕工作台")
        entry_open.setObjectName("studioEntryPrimary")
        install_themed_icon(entry_open, "fa5s.closed-captioning")
        entry_open.clicked.connect(lambda: self.open_studio_project())
        from ..design.presentation import button_role
        button_role(entry_open, "secondary", size="default")
        self.studio_entry_open = entry_open
        entry_layout.addWidget(entry_open)
        self.studio_entry_card = studio_entry
        studio_entry.refresh_requested.connect(self._refresh_studio_entry_card)
        self._refresh_studio_entry_card()
        surface = QFrame()
        surface.setObjectName("settingsSurface")
        # P0 Resize: allow vertical growth on tall windows; keep a sensible minimum for density.
        surface.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        surface.setMinimumHeight(320)
        self.settings_surface = surface
        # 2026-10-17 home C′ (user): left = the Studio card; right = one
        # settings card in hairline-divided sections — recognition plan (three
        # model cards level with the cover), AI segmentation, content & terms,
        # subtitle language & output. Each section carries its zone colour.
        surface_layout = QHBoxLayout(surface)
        surface_layout.setContentsMargins(0, 2, 0, 0)
        surface_layout.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        self.settings_left_column = left
        settings_card = QFrame()
        settings_card.setObjectName("homeSettingsCard")
        self.home_settings_card = settings_card
        content_profile = QFrame()
        content_profile.setObjectName("homeContentProfile")
        self.content_profile_card = content_profile
        profile_layout = QVBoxLayout(content_profile)
        profile_layout.setContentsMargins(22, 16, 22, 18)
        self._home_content_layout = profile_layout
        profile_layout.setSpacing(12)
        # 2026-10-08: the content name lives once, in the combo; the term
        # switch and its state line live once, in the term column.
        content_head = QHBoxLayout()
        content_head.setSpacing(12)
        self.content_icon = QLabel()
        self.content_icon.setObjectName("homeCardIcon")
        self.content_icon.setFixedSize(36, 36)
        self.content_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_head.addWidget(self.content_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        current_eyebrow = QLabel("内容与术语")
        current_eyebrow.setObjectName("homeSectionTitle")
        content_head.addWidget(current_eyebrow)
        content_head.addStretch(1)
        profile_layout.addLayout(content_head)
        # Three columns divided by hairlines: content name and recent chips |
        # glossary correction | the optional web check. One widget, so the
        # frosted lock can cover exactly these columns (2026-10-22).
        self.content_terms_body = QWidget()
        self.content_terms_body.setObjectName("homeContentBody")
        content_body = QHBoxLayout(self.content_terms_body)
        content_body.setContentsMargins(0, 0, 0, 0)
        content_body.setSpacing(20)
        choice_panel = QWidget()
        choice_panel.setObjectName("homeContentPlain")
        self.content_choice_panel = choice_panel
        content_choice = QVBoxLayout(choice_panel)
        content_choice.setContentsMargins(0, 0, 0, 0)
        content_choice.setSpacing(10)
        content_body.addWidget(choice_panel, 16)
        # Label + 46 px box: its size hint is taken before the QSS fonts apply.
        ui_zoom.set_size(choice_panel, min_h=80)
        profile_layout.addWidget(self.content_terms_body)
        self.current_content_title = QLabel("通用内容")
        self.current_content_title.setObjectName("contentHeroTitle")
        self.current_content_title.setParent(content_profile)
        self.current_content_title.hide()
        name_label = QLabel("游戏 / 内容名称")
        name_label.setObjectName("homeFieldLabel")
        content_choice.addWidget(name_label)
        bind_text(self.content_profile_card, '游戏 / 内容名称', property='accessibleDescription')
        self.game_box = EditableHistoryCombo()
        choices = []
        seen = set()
        for value in (*term_library_game_names(self.legacy), *self.legacy.load_runtime_game_history()):
            canonical = self.legacy.canonicalize_runtime_game_name(value)
            identity = self.legacy.runtime_game_identity(canonical)
            if canonical and identity not in seen:
                choices.append(canonical)
                seen.add(identity)
        self.game_box.addItems(choices)
        self.game_box.setCurrentIndex(-1)
        bind_text(self.game_box, '选择历史记录或内置游戏，也可以直接输入；留空为通用模式', property='placeholderText')
        bind_text(self.game_box, '点击右侧箭头选择历史记录或内置游戏；输入新名称也会自动保存', property='toolTip')
        self.game_box.setObjectName("homeContentCombo")
        ui_zoom.set_size(self.game_box, min_h=46)  # its QSS height; the row must reserve it
        content_choice.addWidget(self.game_box)
        # Recent content names as one-click chips (same history as the combo).
        from .home_widgets import QuickPickRow
        self.content_quick_picks = QuickPickRow("最近")
        self.content_quick_picks.picked.connect(self._pick_recent_content)
        content_choice.addWidget(self.content_quick_picks)
        self.game_box.currentTextChanged.connect(self._sync_content_quick_picks)
        self.terms = SwitchControl("术语库校对")
        self.terms.setObjectName("homeSwitch")
        self._restore_glossary_switch()
        bind_text(self.terms, '使用本批已确认词库进行本地匹配和文字校对；联网核验独立选择', property='toolTip')
        self.game_box.currentTextChanged.connect(self._auto_enable_terms)
        self.terms.toggled.connect(lambda _checked: self._resolve_glossary_binding())
        self.game_box.currentTextChanged.connect(self._refresh_asr_summary)
        self.game_box.currentTextChanged.connect(
            lambda value: bind_text(self.current_content_title, value.strip() or '通用内容')
        )
        # The term panel: switch, real state line and the enabled libraries.
        batch_glossary = QFrame()
        batch_glossary.setObjectName("homeBatchGlossary")
        self.batch_glossary_card = batch_glossary
        batch_layout = QVBoxLayout(batch_glossary)
        batch_layout.setContentsMargins(0, 2, 0, 0)
        batch_layout.setSpacing(6)
        terms_row = QHBoxLayout()
        terms_row.setSpacing(8)
        terms_row.addWidget(self.terms, 1)
        terms_help = AnimatedButton("")
        terms_help.setObjectName("flat")
        terms_help.setFixedSize(30, 30)
        install_themed_icon(terms_help, "fa5s.info-circle", "secondary")
        bind_text(terms_help, '已确认词库可直接参与校对，不需要每次重新联网。', property='toolTip')
        terms_help.clicked.connect(
            lambda: QMessageBox.information(
                self,
                tr('术语增强说明'),
                tr('本批已确认的术语库可直接参与文字校对。\n\n联网补充核验是独立的可选步骤，需要实际搜索能力；未配置时仍保留已完成的字幕和本地词库修改。\n\n网页信息只证明术语和语境，无法替代原音复核。'),
            )
        )
        terms_row.addWidget(terms_help)
        manage = AnimatedButton("管理术语库")
        manage.setObjectName("homeHeaderAction")
        manage.setProperty("homeZone", "content")
        install_themed_icon(manage, "fa5s.book-open", "zone_content")
        manage.clicked.connect(self._manage_terms)
        manage.setMaximumWidth(260)  # soft; EN/JA/RU labels must not truncate (bolder since 10-23)
        content_head.addWidget(manage)
        self.add_glossary_button = manage
        batch_layout.addLayout(terms_row)
        self.term_state_label = QLabel("")
        self.term_state_label.setObjectName("homeTermState")
        self.term_state_label.setWordWrap(True)
        # Indented to the switch label (track 46px + gap) so the panel reads
        # as one statement: switch, its state, the enabled libraries.
        self.term_state_label.setContentsMargins(46, 0, 0, 0)
        batch_layout.addWidget(self.term_state_label)
        # 2026-10-22: shown while the AI is not connected (the switch is locked).
        self.terms_unlock_button = AnimatedButton("去设置 AI")
        self.terms_unlock_button.setObjectName("linkButton")
        self.terms_unlock_button.setIcon(_icon("fa5s.key"))
        self.terms_unlock_button.clicked.connect(lambda: self._open_ai_settings_dialog())
        self.terms_unlock_button.hide()
        unlock_row = QHBoxLayout()
        unlock_row.setContentsMargins(40, 0, 0, 0)
        unlock_row.addWidget(self.terms_unlock_button)
        unlock_row.addStretch(1)
        batch_layout.addLayout(unlock_row)
        self.term_search = SwitchControl('联网补充核验（可选）')
        self.term_search.setObjectName("homeSwitch")
        self.term_search.setChecked(False)
        bind_text(self.term_search, '仅本次任务启用；需可验证的搜索能力。当前文字校对服务保持不变，未配置搜索时不会发送请求。', property='toolTip')
        # 手动添加术语：入口收敛到术语库；首页不再常驻添加框（批准图 #1/#2）。
        self.term_input = QLineEdit()
        bind_text(self.term_input, '添加专名（角色名 / 技能名 / 物品名），回车确认', property='placeholderText')
        bind_text(self.term_input, '手动确认的专名会作为强参考参与本地校对，也会进入联网复核候选', property='toolTip')
        self.term_input.returnPressed.connect(self._add_custom_term)
        self.term_input.hide()
        # 术语添加反馈行（平时为空，添加后由 _add_custom_term 填充）
        term_hint = QLabel("")
        term_hint.setObjectName("muted")
        term_hint.setWordWrap(True)
        content_choice.addWidget(term_hint)
        term_hint.hide()
        self.term_hint = term_hint
        # The ON/OFF status text stays the switch-state contract (tests and
        # audits); the visible state line above avoids repeating the switch.
        self.batch_glossary_status = QLabel("术语增强 OFF")
        self.batch_glossary_status.setObjectName("homeGlossaryStatus")
        self.batch_glossary_status.setParent(batch_glossary)
        self.batch_glossary_status.hide()
        self.glossary_chips_layout = QHBoxLayout()
        self.glossary_chips_layout.setSpacing(6)
        self.glossary_chips_layout.setContentsMargins(46, 0, 0, 0)
        batch_layout.addLayout(self.glossary_chips_layout)
        batch_layout.addStretch(1)

        def column_rule():
            rule = QFrame()
            rule.setObjectName("homePanelRule")
            rule.setFixedWidth(1)
            return rule

        content_body.addWidget(column_rule())
        content_body.addWidget(batch_glossary, 8)
        # The optional web check is its own column (home C′).
        search_panel = QWidget()
        search_panel.setObjectName("homeTermSearchPanel")
        self.term_search_panel = search_panel
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 2, 0, 0)
        search_layout.setSpacing(6)
        search_layout.addWidget(self.term_search)
        self.term_search_note = QLabel("仅本次任务启用；需可验证的搜索能力")
        self.term_search_note.setObjectName("homeTermState")
        self.term_search_note.setProperty("tone", "off")
        self.term_search_note.setWordWrap(True)
        self.term_search_note.setContentsMargins(46, 0, 0, 0)
        search_layout.addWidget(self.term_search_note)
        search_layout.addStretch(1)
        content_body.addWidget(column_rule())
        content_body.addWidget(search_panel, 7)
        content_choice.addStretch(1)
        # Subtitle language and output: one row under a hairline.
        language_rule = QFrame()
        language_rule.setObjectName("homePanelRule")
        language_rule.setFixedHeight(1)
        profile_layout.addWidget(language_rule)
        self._build_subtitle_language_row(profile_layout)
        # AI segmentation section; filled once the AI tile exists.
        self.home_process_card = QFrame()
        self.home_process_card.setObjectName("homeProcessCard")
        process_layout = QVBoxLayout(self.home_process_card)
        # The AI card fills its band edge to edge (2026-10-23: no frame in a frame).
        process_layout.setContentsMargins(0, 0, 0, 0)
        self._home_ai_layout = process_layout
        process_layout.setSpacing(0)

        plan_block = QWidget()
        plan_block.setObjectName("homePlanBlock")
        right = QVBoxLayout(plan_block)
        # The three model cards are the card's first band, edge to edge (C′).
        right.setContentsMargins(0, 0, 0, 0)
        self._home_plan_layout = right
        right.setSpacing(0)
        recognition_header = QHBoxLayout()
        recognition_header.setContentsMargins(0, 0, 0, 0)
        recognition_header.setSpacing(10)
        recognition_heading = QLabel("识别方案")
        recognition_heading.setObjectName("homeSectionTitle")
        recognition_header.addWidget(recognition_heading)
        self.home_task_settings_button = AnimatedButton("高级设置")
        self.home_task_settings_button.setObjectName("homeHeaderAction")
        install_themed_icon(self.home_task_settings_button, "fa5s.cog")
        bind_text(self.home_task_settings_button, '设置对白覆盖、说话人数、复核轨与缓存策略', property='toolTip')
        self.home_task_settings_button.clicked.connect(
            self._open_task_settings_from_workshop
        )
        recognition_note = QLabel("三个角色协作，可点击任一模型卡进行更换")
        recognition_note.setObjectName("pageSubtitle")
        recognition_note.hide()
        profile_row = QHBoxLayout()
        profile_row.setSpacing(7)
        profile_label = QLabel("当前方案")
        profile_label.setObjectName("fieldLabel")
        profile_row.addWidget(profile_label)
        self.project_profile_combo = FramelessPopupCombo()
        self.project_profile_combo.setObjectName("projectProfileCombo")
        bind_text(self.project_profile_combo, '保存并复用模型、词库、样式、输出与审核设置', property='toolTip')
        self.project_profile_combo.currentIndexChanged.connect(self._project_profile_selected)
        profile_row.addWidget(self.project_profile_combo, 1)
        self.project_profile_manage = AnimatedButton("")
        self.project_profile_manage.setObjectName("softAction")
        self.project_profile_manage.setProperty("homeTool", True)
        install_themed_icon(self.project_profile_manage, "fa5s.ellipsis-h")
        bind_text(self.project_profile_manage, '管理 Project / Game Profile', property='toolTip')
        self.project_profile_manage.setFixedSize(38, 38)
        self.project_profile_manage.clicked.connect(self._show_project_profile_menu)
        profile_row.addWidget(self.project_profile_manage)
        self.profile_recommendation = QLabel("")
        self.profile_recommendation.setObjectName("muted")
        self.profile_recommendation.setWordWrap(True)
        self.profile_recommendation.hide()
        self._refresh_project_profile_combo()
        plan_row = QHBoxLayout()
        plan_row.setSpacing(7)
        plan_label = QLabel("先选目标")
        plan_label.setObjectName("fieldLabel")
        plan_row.addWidget(plan_label)
        self.recognition_mode_combo = FramelessPopupCombo()
        self.recognition_mode_combo.setObjectName("recognitionPlanCombo")
        for plan in plan_options():
            self.recognition_mode_combo.addItem(plan.label, plan.key)
        bind_text(self.recognition_mode_combo, '选一个目标即可；在下面的模型卡换了模型时，这里显示「自定义」', property='toolTip')
        self.recognition_mode_combo.currentIndexChanged.connect(self._apply_recognition_plan_from_ui)
        plan_row.addWidget(self.recognition_mode_combo)
        self.recognition_plan_hint = QLabel("")
        self.recognition_plan_hint.setObjectName("muted")
        self.recognition_plan_hint.setWordWrap(True)
        self.recognition_plan_hint.hide()
        plan_row.addSpacing(6)
        plan_row.addLayout(profile_row)
        # 2026-10-08 (user): the plan toolbar sits on the 本批字幕 heading row;
        # 2026-10-17 (home C′): its dropdowns keep a natural width instead of
        # stretching across the row.
        for combo, length, widest in ((self.recognition_mode_combo, 7, 220), (self.project_profile_combo, 11, 300)):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(length)
            combo.setMaximumWidth(widest)
        plan_row.setContentsMargins(0, 0, 0, 0)
        self.plan_controls = QWidget()
        self.plan_controls.setLayout(plan_row)
        self.plan_header_layout = recognition_header
        recognition_header.addWidget(self.plan_controls)
        recognition_header.addWidget(self.home_task_settings_button)
        page_heading.addLayout(recognition_header)
        self.page_subtitle = page_subtitle
        # 识别方案：三张角色模型卡（批准图核心区）
        from twobyteasr.app.ui_recognition import RecognitionPlanWidget

        self.recognition_plan = RecognitionPlanWidget()
        # Its height band is set per window tier (and zoom) in apply_density.
        self.recognition_plan.setProperty("uiZoomOwnSize", True)
        self.recognition_plan.role_requested.connect(self._open_model_picker)
        self.recognition_plan.recovery_requested.connect(self._recognition_recovery)
        # Three equal columns divided by hairlines (home QSS), no gaps.
        plan_columns = self.recognition_plan.layout()
        plan_columns.setSpacing(0)
        policy = self.recognition_plan.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)  # its size hint, between the tier height and +48
        self.recognition_plan.setSizePolicy(policy)
        for index in range(plan_columns.count()):
            plan_columns.setStretch(index, 1)
        right.addWidget(self.recognition_plan)
        # 兼容属性：旧测试/逻辑引用（内容由 _refresh_asr_summary 同步）
        self.recognition_summary = QLabel("")
        self.recognition_summary.hide()
        self.run_summary = QLabel("")
        self.run_summary.hide()
        self.run_next_action = QLabel("")
        self.run_next_action.hide()
        self.recognition_action = AnimatedButton("")
        self.recognition_action.hide()
        # Right two thirds: one card — plan, AI, content & terms, language —
        # and the left project card takes exactly that height.
        produce = QVBoxLayout(settings_card)
        produce.setContentsMargins(0, 0, 0, 0)
        produce.setSpacing(0)
        produce.addWidget(plan_block)
        produce.addWidget(self.home_process_card)
        produce.addWidget(content_profile, 1)
        self.settings_right_column = produce
        left.addWidget(studio_entry, 1)
        surface_layout.addLayout(left, 1)
        surface_layout.addWidget(settings_card, 2)
        layout.addWidget(surface)

        settings = self.legacy.RUNTIME_SETTINGS
        self.asr_panel = CollapsibleFrame(
            "语音识别增强后端",
            "fa5s.microphone-alt",
            expanded=False,
        )
        asr_form = QFormLayout()
        asr_form.setHorizontalSpacing(14)
        asr_form.setVerticalSpacing(9)
        self.primary_asr_backend = FramelessPopupCombo()
        self.qwen_asr_backend = FramelessPopupCombo()
        self.qwen_asr_api_provider = FramelessPopupCombo()
        for key, preset in ASR_API_PRESETS.items():
            self.qwen_asr_api_provider.addItem(preset["label"], key)
        api_provider = settings["models"].get("qwen_asr_api_provider", "qwen31_filetrans")
        if api_provider not in ASR_API_PRESETS:
            self.qwen_asr_api_provider.addItem(str(api_provider), api_provider)
        self.qwen_asr_api_provider.setCurrentIndex(
            max(0, self.qwen_asr_api_provider.findData(api_provider))
        )
        # 四十轮：模型/服务商下拉打开时当前选中项置顶（免滚动寻找）。
        self.primary_asr_backend.setProperty("selectedFirst", True)
        self.qwen_asr_api_provider.setProperty("selectedFirst", True)
        self.qwen_asr_api_model = QLineEdit(
            settings["models"].get("qwen_asr_api_model", "qwen-audio-3.1-asr-flash-filetrans")
        )
        self.qwen_asr_api_url = QLineEdit(
            settings["models"].get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"])
        )
        self.qwen_asr_api_key = QLineEdit()
        self.qwen_asr_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        from ..providers.llm_config import read_asr_api_key

        qwen_key, qwen_key_source = read_asr_api_key(
            str(self.legacy.RUNTIME_SETTINGS.get("models", {}).get("qwen_asr_api_provider", "qwen31_filetrans") or "qwen31_filetrans"),
            str(self.legacy.RUNTIME_SETTINGS.get("models", {}).get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"]) or ""),
        )
        (bind_text(self.qwen_asr_api_key, '已保存（···{value0}，留空保持）', property='placeholderText', value0=qwen_key[-4:]) if qwen_key else bind_text(self.qwen_asr_api_key, '请输入当前 ASR 服务的 API Key', property='placeholderText'))
        # P0-4: "获取模型" flow. Prefer dropdown from /v1/models; manual entry is fallback.
        self.qwen_fetch_models_btn = AnimatedButton("获取模型")
        self.qwen_fetch_models_btn.setObjectName("outline")
        bind_text(self.qwen_fetch_models_btn, '调用该服务的 /v1/models 自动列出可用模型', property='toolTip')
        self.qwen_models_combo = FramelessPopupCombo()
        self.qwen_models_combo.setEditable(False)
        self.qwen_models_combo.setMinimumContentsLength(18)
        self.qwen_models_combo.setVisible(False)  # shown after a successful fetch
        self.qwen_models_status = QLabel("")
        self.qwen_models_status.setObjectName("muted")
        self.qwen_models_status.setVisible(False)
        # Wire: selecting in fetched list writes into the canonical text field used by save
        def _apply_fetched_model(idx: int):
            try:
                txt = self.qwen_models_combo.itemText(idx) if idx >= 0 else ""
                if txt:
                    self.qwen_asr_api_model.setText(txt)
            except Exception:
                pass
        self.qwen_models_combo.activated.connect(_apply_fetched_model)
        self.qwen_fetch_models_btn.clicked.connect(self._fetch_asr_models)
        self.firered_asr_backend = FramelessPopupCombo()
        # 三十九轮：转写风格。clean=去语气词（字幕/纪要，默认）；verbatim=
        # 逐字保留嗯/那个/口误（合规/质检）。OpenRouter MAI 通道直传官方
        # transcribeStyle；本地门控孤立语气词省略。
        self.api_transcribe_style = FramelessPopupCombo()
        for style_label, style_value in (
            ("清爽（去语气词，适合字幕/纪要）", "clean"),
            ("逐字 verbatim（保留嗯/那个/口误，适合合规/质检）", "verbatim"),
        ):
            self.api_transcribe_style.addItem(style_label, style_value)
        saved_style = str(settings["models"].get("api_transcribe_style", "clean") or "clean")
        if saved_style not in {"clean", "verbatim"}:
            saved_style = "clean"
        self.api_transcribe_style.setCurrentIndex(
            max(0, self.api_transcribe_style.findData(saved_style))
        )
        bind_text(self.api_transcribe_style, '转写风格：清爽=模型与本地成片规则都会去掉语气词；逐字=按原话保留（含口误），孤立语气词不再省略。', property='toolTip')
        self._missing_saved_asr_backends = populate_available_asr_choices(
            self.primary_asr_backend,
            self.qwen_asr_backend,
            self.firered_asr_backend,
            settings,
        )
        asr_form.addRow("主力转写模型", self.primary_asr_backend)
        asr_form.addRow("文字复核模型", self.qwen_asr_backend)
        self.qwen_api_provider_label = QLabel("API 服务")
        asr_form.addRow(self.qwen_api_provider_label, self.qwen_asr_api_provider)
        self.qwen_api_model_label = QLabel("API 模型")
        asr_form.addRow(self.qwen_api_model_label, self.qwen_asr_api_model)
        self.qwen_api_url_label = QLabel("API 地址")
        asr_form.addRow(self.qwen_api_url_label, self.qwen_asr_api_url)
        self.qwen_api_key_label = QLabel("API 密钥")
        asr_form.addRow(self.qwen_api_key_label, self.qwen_asr_api_key)
        # P0-4: 获取模型按钮 + 自动下拉（优先）；保留原模型文本框作为手动回退。
        fetch_row = QHBoxLayout()
        fetch_row.addWidget(self.qwen_fetch_models_btn)
        fetch_row.addStretch(1)
        asr_form.addRow("自动获取", fetch_row)
        asr_form.addRow("可用模型（自动）", self.qwen_models_combo)
        asr_form.addRow("", self.qwen_models_status)
        # 说明：选择后会写入“API 模型”文本框；若厂商不支持 /v1/models，可直接手动填写。
        asr_form.addRow("API 模型（可手动）", self.qwen_asr_api_model)
        asr_form.addRow("转写风格", self.api_transcribe_style)
        asr_form.addRow("字幕时间轴", self.firered_asr_backend)
        self.asr_panel.content_layout.addLayout(asr_form)
        asr_note = QLabel(
            "使用所选主转写模型的原生说话人结果；没有该能力时保留一条字幕轨。"
            "本地 Qwen 通常识别更准确，会为每个时间片段增加一份独立文字与词汇证据；"
            "API 可选阿里百炼、Groq、OpenAI 或自定义兼容服务，更快且不占本地显存，"
            "但需要对应服务的 Key，识别精度和国内可访问性取决于服务商。"
            "两者都只提供文字复核；选择字幕时间轴后输出 SRT，关闭时只输出 TXT。"
        )
        asr_note.setWordWrap(True)
        asr_note.setObjectName("muted")
        self.asr_panel.content_layout.addWidget(asr_note)
        asr_actions = QHBoxLayout()
        self.asr_save_status = QLabel(credential_storage_notice() if session_credentials_enabled() else "可单独保存，API 密钥使用 Windows DPAPI 加密")
        self.asr_save_status.setObjectName("muted")
        if self._missing_saved_asr_backends:
            self.asr_save_status.setObjectName("statusWarn")
            bind_text(self.asr_save_status, '原配置中的本地模型尚未安装，已自动切换到可用选项')
        # Inline help (ⓘ) preferred. Opens a compact popover; "查看完整教程" opens a proper dialog.
        self.qwen_api_help_button = AnimatedButton("ⓘ")
        self.qwen_api_help_button.setObjectName("outline")
        bind_text(self.qwen_api_help_button, 'API 帮助 · 悬停或点击查看简要说明', property='toolTip')
        self.qwen_api_help_button.setFixedWidth(36)
        self.qwen_api_help_button.clicked.connect(self._show_qwen_asr_api_inline_help)
        self.save_asr_button = AnimatedButton("保存识别后端")
        self.save_asr_button.setObjectName("outline")
        self.save_asr_button.setIcon(_icon("fa5s.save"))
        self.save_asr_button.clicked.connect(
            lambda: self._save_asr_configuration(show_feedback=True)
        )
        asr_actions.addWidget(self.asr_save_status, 1)
        asr_actions.addWidget(self.qwen_api_help_button)
        asr_actions.addWidget(self.save_asr_button)
        self.asr_panel.content_layout.addLayout(asr_actions)
        self.qwen_asr_backend.currentIndexChanged.connect(
            self._apply_asr_backend_mode
        )
        self.qwen_asr_backend.currentIndexChanged.connect(self._refresh_recognition_recommendation)
        self.primary_asr_backend.currentIndexChanged.connect(
            self._apply_asr_backend_mode
        )
        self.primary_asr_backend.currentIndexChanged.connect(self._refresh_recognition_recommendation)
        self.firered_asr_backend.currentIndexChanged.connect(self._refresh_recognition_recommendation)
        self.qwen_asr_api_provider.currentIndexChanged.connect(
            self._asr_api_provider_changed
        )
        self.qwen_asr_api_provider.currentIndexChanged.connect(self._try_restore_asr_models_from_cache)
        self.qwen_asr_api_url.textChanged.connect(self._try_restore_asr_models_from_cache)
        for control, signal in (
            (self.primary_asr_backend, self.primary_asr_backend.currentIndexChanged),
            (self.qwen_asr_backend, self.qwen_asr_backend.currentIndexChanged),
            (self.qwen_asr_api_provider, self.qwen_asr_api_provider.currentIndexChanged),
            (self.qwen_asr_api_model, self.qwen_asr_api_model.textChanged),
            (self.qwen_asr_api_url, self.qwen_asr_api_url.textChanged),
            (self.qwen_asr_api_key, self.qwen_asr_api_key.textChanged),
            (self.firered_asr_backend, self.firered_asr_backend.currentIndexChanged),
        ):
            signal.connect(self._mark_asr_configuration_dirty)
        self._apply_asr_backend_mode()
        self._refresh_content_choices()
        self._refresh_asr_summary()
        # Best-effort: prefill combo from cache on first paint if we have a base URL
        QTimer.singleShot(0, self, self._try_restore_asr_models_from_cache)
        # 四十轮：每日一次的 OSS 临时对象过期清理（>48h），后台线程不阻塞启动。
        QTimer.singleShot(20000, self, self._oss_startup_cleanup)
        # 识别增强入口已删除（批准图）：模型选择集中到识别方案角色卡；
        # 表单对象保留（逻辑引用），不再渲染到首页。
        self.asr_panel.hide()
        self.asr_panel.set_expanded(False, animate=False)

        self.ai_panel = CollapsibleFrame(
            "AI 智能断句",
            "fa5s.project-diagram",
            expanded=False,
        )
        # 2026-10-22 (design B): one page — the service, key and test first,
        # then 「让 AI 负责」, then 高级设置 (closed): model, address, protocol,
        # output, a second service for line breaking and the prompt.
        panel_layout = self.ai_panel.content_layout
        panel_layout.setSpacing(14)
        self.ai_polish = SwitchControl("字幕校对")
        self.ai_polish.setChecked(settings["switches"].get("enable_ai_polish", True))
        bind_text(self.ai_polish, '关闭后不请求校对模型，也不需要校对 API Key；保留本地转写和文字规则。', property='toolTip')
        self.ai_grouping = SwitchControl("按意思断句")
        self.ai_grouping.setChecked(
            settings["switches"].get("use_ai_grouping", True)
        )
        bind_text(self.ai_grouping, '关闭后不请求断句模型，也不需要断句 API Key；将使用 MOSS 自然语句、FireRed 停顿与本地护栏断句。', property='toolTip')
        # 2026-10-21: why 按意思断句 / 字幕校对 are off and locked (no key yet);
        # shown under them in 「让 AI 负责」.
        self.ai_key_off_note = QLabel()
        self.ai_key_off_note.setObjectName("statusWarn")
        self.ai_key_off_note.setWordWrap(True)
        # It wraps to the column's width and never widens it (2026-10-25: the AI
        # settings must be as wide with and without a key).
        self.ai_key_off_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.ai_key_off_note.hide()
        self.prefer_arabic_numbers = SwitchControl('数字规范化')
        self.prefer_arabic_numbers.setChecked(settings['switches'].get('prefer_arabic_numbers', True))
        bind_text(self.prefer_arabic_numbers, '只影响之后生成的字幕；普通整数1～9保留原文，明确数值从10开始转为阿拉伯数字；小数、百分比和比例除外。保留约数、成语和已确认术语，不求和或去重，不改已保存工程。', property='toolTip')
        self.prefer_arabic_numbers.toggled.connect(self._mark_ai_configuration_dirty)
        # The saved switch keeps its meaning (one service for both stages); the
        # page shows its plain opposite, 「断句另用一个服务」, in 高级设置.
        self.unified_glm = SwitchControl("同一云端模型负责字幕校对与全文断句（推荐）")
        self.unified_glm.setChecked(
            settings["switches"].get("unified_glm_processing", True)
        )
        self.unified_glm.hide()
        self.polish_editor = EndpointEditor("字幕校对模型", CORAL, "polish", settings)
        self.group_editor = EndpointEditor("全文断句模型", BLUE, "group", settings)
        for editor in (self.polish_editor, self.group_editor):
            editor.connection_tested.connect(lambda _ok: self._refresh_home_process_facts())
            editor.connection_tested.connect(lambda _ok: self._refresh_ai_dialog_state())
            editor.advanced_wanted.connect(lambda: self.ai_advanced_toggle.setChecked(True))
            editor.key_help_requested.connect(lambda: self._open_api_key_explainer())
        # The main form: the shared editor, or 校对 (and translation) when line
        # breaking has its own service (_place_ai_editors).
        # 2026-10-22 (design D2 refined): the guide column (what to do now, the
        # three steps, the lent 「申请教程」) beside the form; everything else is
        # folded into 「更多选项」, whose closed line says what is set inside.
        from .ai_settings_widgets import AiGuidePanel, NoteLabel, YieldingBox, keep_label_width
        split = QHBoxLayout()
        split.setSpacing(16)
        self.ai_guide = AiGuidePanel()
        split.addWidget(self.ai_guide)
        form_column = QVBoxLayout()
        form_column.setSpacing(10)
        self.ai_main_slot = QVBoxLayout()
        self.ai_main_slot.setContentsMargins(0, 0, 0, 0)
        self.ai_main_slot.addWidget(self.polish_editor)
        self.ai_main_slot.addWidget(self.group_editor)
        form_column.addLayout(self.ai_main_slot)
        form_column.addStretch(1)
        # The dialog puts its save line, 取消 and 保存设置 here, level with the
        # guide's foot (2026-10-22, user: no empty block under 测试连接).
        self.ai_actions_row = QHBoxLayout()
        self.ai_actions_row.setContentsMargins(0, 0, 0, 0)
        self.ai_actions_row.setSpacing(10)
        form_column.addLayout(self.ai_actions_row)
        split.addLayout(form_column, 1)
        panel_layout.addLayout(split)
        advanced_head = QHBoxLayout()
        advanced_head.setSpacing(10)
        self.ai_advanced_toggle = QToolButton()
        self.ai_advanced_toggle.setObjectName("endpointAdvancedToggle")
        self.ai_advanced_toggle.setCheckable(True)
        self.ai_advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.ai_advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind_text(self.ai_advanced_toggle, '更多选项')
        advanced_head.addWidget(self.ai_advanced_toggle)
        # The notes in 更多选项 wrap when the dialog is narrow (NoteLabel, 2026-10-25).
        self.ai_advanced_summary = NoteLabel()
        self.ai_advanced_summary.setObjectName("aiAdvancedSummary")
        advanced_head.addWidget(self.ai_advanced_summary, 1)
        advanced_head.addStretch(0)
        panel_layout.addLayout(advanced_head)
        self._ai_advanced_head = advanced_head   # how wide 更多选项 will open (fit)
        self.ai_advanced_box = QFrame()
        self.ai_advanced_box.setObjectName("aiAdvancedBox")
        advanced_layout = QVBoxLayout(self.ai_advanced_box)
        advanced_layout.setContentsMargins(16, 12, 16, 14)
        advanced_layout.setSpacing(10)
        # Left: 「让 AI 负责」, one switch per line with its effect beside it.
        # Right: the top form's model, protocol, address and output.
        options_row = QHBoxLayout()
        options_row.setSpacing(20)
        duties = QVBoxLayout()
        duties.setSpacing(2)
        duty_title = QLabel("让 AI 负责")
        duty_title.setObjectName("aiSectionTitle")
        duties.addWidget(duty_title)
        self._ai_duty_notes = {}
        for name, switch, note in (
                ("group", self.ai_grouping, "关掉后用本地规则断句"),
                ("polish", self.ai_polish, "改错字、统一专名"),
                ("numbers", self.prefer_arabic_numbers, "“十二个”写成“12 个”")):
            line_row = QHBoxLayout()
            line_row.setSpacing(10)
            line_row.addWidget(keep_label_width(switch))
            line = NoteLabel()
            bind_text(line, note)
            line.setObjectName("aiDutyNote")
            line_row.addWidget(line, 1)
            duties.addLayout(line_row)
            self._ai_duty_notes[name] = line
            switch.toggled.connect(self._refresh_ai_advanced_summary)
            switch.toggled.connect(self._refresh_ai_dialog_state)
        duties.addWidget(self.ai_key_off_note)
        duties.addStretch(1)
        # 2026-10-25: both sides first get what they ask for — the notes their
        # one line, the model group its minimum (YieldingBox) — then share the
        # rest. (A stretch factor would let Qt squeeze the notes to their minimum.)
        duties_host = QWidget()
        duties.setContentsMargins(0, 0, 0, 0)
        duties_host.setLayout(duties)
        self.ai_advanced_editor_slot = QVBoxLayout()
        self.ai_advanced_editor_slot.setContentsMargins(0, 0, 0, 0)
        editor_host = YieldingBox()
        editor_host.setLayout(self.ai_advanced_editor_slot)
        for side in (duties_host, editor_host):
            side.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            options_row.addWidget(side)
        advanced_layout.addLayout(options_row)
        self._ai_options_row = options_row   # the dialog's comfortable width (fit)
        advanced_rule = QFrame()
        advanced_rule.setObjectName("aiAdvancedRule")
        advanced_rule.setFixedHeight(1)
        advanced_layout.addWidget(advanced_rule)
        # The switch, what it means and the prompt share one row.
        separate_row = QHBoxLayout()
        separate_row.setSpacing(12)
        self.separate_group_service = SwitchControl("断句另用一个服务")
        self.separate_group_service.setChecked(not self.unified_glm.isChecked())
        self.separate_group_service.toggled.connect(lambda on: self.unified_glm.setChecked(not on))
        separate_row.addWidget(keep_label_width(self.separate_group_service))
        self.separate_group_note = NoteLabel()
        bind_text(self.separate_group_note, '关着时断句、校对和翻译共用上面的服务和 Key')
        self.separate_group_note.setObjectName("aiDutyNote")
        separate_row.addWidget(self.separate_group_note)
        advanced_layout.addLayout(separate_row)
        advanced_layout.addWidget(self.unified_glm)
        self.ai_second_slot = QVBoxLayout()
        self.ai_second_slot.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addLayout(self.ai_second_slot)
        self.ai_advanced_box.hide()
        self.ai_advanced_toggle.toggled.connect(self._show_ai_advanced)
        self.share_key = SwitchControl("断句也用上面新填的 Key")
        self.share_key.setChecked(True)
        # 2026-10-18: the line-breaking guidance of the AI prompt is editable.
        prompt_button = AnimatedButton("断句提示词")
        prompt_button.setObjectName("linkButton")
        prompt_button.setIcon(_icon("fa5s.edit"))
        bind_text(prompt_button, '查看或修改 AI 断句提示词里的断句说明', property='toolTip')
        prompt_button.clicked.connect(
            lambda: PromptDialog(prompt_button.window(), self.legacy.RUNTIME_SETTINGS).exec())
        self.grouping_prompt_button = prompt_button
        self.save_ai_button = AnimatedButton("保存 AI 配置")
        self.save_ai_button.setObjectName("outline")
        self.save_ai_button.setIcon(_icon("fa5s.save"))
        self.save_ai_button.clicked.connect(
            lambda: self._save_ai_configuration(show_feedback=True)
        )
        separate_row.addWidget(keep_label_width(self.share_key))
        separate_row.addStretch(1)
        separate_row.addWidget(prompt_button)
        separate_row.addWidget(self.save_ai_button)
        panel_layout.addWidget(self.ai_advanced_box)
        self.ai_save_status = QLabel(credential_storage_notice() if session_credentials_enabled() else "供应商、模型、地址和新填写的密钥可在这里单独保存")
        self.ai_save_status.setObjectName("muted")
        self.ai_panel.content_layout.addWidget(self.ai_save_status)
        self.ai_grouping.toggled.connect(self._apply_ai_grouping_mode)
        self.ai_polish.toggled.connect(lambda _: self._apply_unified_glm_mode(self.unified_glm.isChecked()))
        self.ai_polish.toggled.connect(self._mark_ai_configuration_dirty)
        self.ai_polish.toggled.connect(self._mark_profile_configuration_dirty)
        self.unified_glm.toggled.connect(self._apply_unified_glm_mode)
        self.ai_panel.toggled.connect(self._schedule_ai_panel_visibility)
        self.ai_panel.animation.finished.connect(self._ensure_ai_panel_visible)
        self.polish_editor.model.currentTextChanged.connect(self._refresh_ai_summary)
        self.group_editor.model.currentTextChanged.connect(self._refresh_ai_summary)
        for editor in (self.polish_editor, self.group_editor):
            editor.service.currentIndexChanged.connect(self._mark_ai_configuration_dirty)
            editor.service.currentIndexChanged.connect(self._refresh_ai_summary)
            editor.transport.currentIndexChanged.connect(self._mark_ai_configuration_dirty)
            editor.transport.currentIndexChanged.connect(self._refresh_ai_summary)
            editor.provider.currentIndexChanged.connect(self._mark_ai_configuration_dirty)
            editor.provider.currentIndexChanged.connect(self._refresh_ai_summary)
            editor.model.currentTextChanged.connect(self._mark_ai_configuration_dirty)
            editor.base_url.textChanged.connect(self._mark_ai_configuration_dirty)
            editor.protocol.currentIndexChanged.connect(self._mark_ai_configuration_dirty)
            editor.key.textChanged.connect(self._mark_ai_configuration_dirty)
            editor.key.textChanged.connect(self._refresh_ai_dialog_state)
            editor.model.currentTextChanged.connect(self._refresh_ai_advanced_summary)
            editor.base_url.textChanged.connect(self._refresh_ai_advanced_summary)
            editor.service.currentIndexChanged.connect(self._refresh_ai_advanced_summary)
            editor.json_mode.toggled.connect(self._mark_ai_configuration_dirty)
            editor.structured_output.toggled.connect(self._mark_ai_configuration_dirty)
        self.ai_grouping.toggled.connect(self._mark_ai_configuration_dirty)
        self.unified_glm.toggled.connect(self._mark_ai_configuration_dirty)
        self.share_key.toggled.connect(self._mark_ai_configuration_dirty)
        # 断句开关/断句模型属于识别方案快照（llm_enabled / llm_config_ref）：
        # 变更同样进入方案脏标，切换方案前给出保存/放弃提示。
        self.ai_grouping.toggled.connect(self._mark_profile_configuration_dirty)
        self.group_editor.model.currentTextChanged.connect(self._mark_profile_configuration_dirty)
        # A key typed in, or a service that already has one, unlocks its switch.
        for editor in (self.polish_editor, self.group_editor):
            editor.key.textChanged.connect(self._sync_ai_switches_with_keys)
            editor.base_url.textChanged.connect(self._sync_ai_switches_with_keys)
            editor.service.currentIndexChanged.connect(self._sync_ai_switches_with_keys)
            editor.configuration_edited.connect(self._sync_ai_switches_with_keys)
            editor.configuration_edited.connect(self._mark_ai_configuration_dirty)
            editor.configuration_edited.connect(self._refresh_ai_dialog_state)
        for control in (self.ai_polish, self.ai_grouping, self.unified_glm, self.share_key):
            control.toggled.connect(self._sync_ai_switches_with_keys)
        self._apply_ai_grouping_mode(self.ai_grouping.isChecked())
        # AI 智能断句留在主要工作区；任务/缓存设置收敛到模型工坊。

        self.advanced_disclosure = CollapsibleFrame("高级选项", "fa5s.sliders-h", expanded=False)
        self.advanced_disclosure.set_summary("对白覆盖 · 复核轨 · 预计说话人数")
        coverage_row = QHBoxLayout()
        coverage_label = QLabel("对白覆盖模式")
        self.dialogue_coverage = FramelessPopupCombo()
        self.dialogue_coverage.addItem("全部对白（推荐）", "all_dialogue")
        self.dialogue_coverage.addItem("主播优先", "host_priority")
        self.dialogue_coverage.addItem("仅主播", "host_only")
        coverage_mode = settings.get("switches", {}).get(
            "dialogue_coverage_mode", "all_dialogue"
        )
        coverage_index = self.dialogue_coverage.findData(coverage_mode)
        self.dialogue_coverage.setCurrentIndex(max(0, coverage_index))
        bind_text(self.dialogue_coverage, '全部对白保留可信角色/NPC 对话；主播优先仅恢复有独立证据的其他说话人；仅主播沿用旧策略。', property='toolTip')
        coverage_row.addWidget(coverage_label)
        coverage_row.addWidget(self.dialogue_coverage)
        coverage_row.addStretch(1)
        self.advanced_disclosure.content_layout.addLayout(coverage_row)
        self.review_track = SwitchControl("输出疑似吞字幕复核轨")
        self.review_track.setChecked(self.legacy.RUNTIME_SETTINGS["switches"]["output_review_track"])
        bind_text(self.review_track, '默认关闭；复核轨保存到项目 review_tracks/', property='toolTip')
        self.advanced_disclosure.content_layout.addWidget(self.review_track)
        self.jianying_txt = SwitchControl("同文件夹输出剪映文稿 txt")
        self.jianying_txt.setChecked(bool(self.legacy.RUNTIME_SETTINGS["switches"].get("output_jianying_txt", False)))
        bind_text(self.jianying_txt, '默认关闭；识别完成后素材同目录只保留合并 SRT，文稿 txt 在需要导入剪映时再打开', property='toolTip')
        self.advanced_disclosure.content_layout.addWidget(self.jianying_txt)
        self.speaker_tracks = SwitchControl("同文件夹输出分主播 SRT")
        self.speaker_tracks.setChecked(bool(self.legacy.RUNTIME_SETTINGS["switches"].get("output_speaker_tracks", False)))
        bind_text(self.speaker_tracks, '默认关闭；需要按主播分轨导入其它工具时再打开', property='toolTip')
        self.advanced_disclosure.content_layout.addWidget(self.speaker_tracks)
        speaker_row = QHBoxLayout()
        source_row=QHBoxLayout()
        source_row.addWidget(bind_text(QLabel(),'说话人来源'))
        self.speaker_source=FramelessPopupCombo()
        self.speaker_source.addItem(tr('跟随当前主模型'),'native')
        self.speaker_source.setCurrentIndex(0)
        source_row.addWidget(self.speaker_source);source_row.addStretch(1)
        self.advanced_disclosure.content_layout.addLayout(source_row)
        speaker_label = QLabel("预计说话人数")
        self.expected_speakers = FramelessPopupCombo()
        self.expected_speakers.addItems(["自动", "1", "2", "3", "4", "5", "6"])
        bind_text(self.expected_speakers, '自动不等于单人。多个持续标签无法可靠判定时，需要在说话人管理中试听确认；指定人数也不代表自动确认真人身份。', property='toolTip')
        self.expected_speakers.setMaximumWidth(220)  # soft; avoid CN truncation in forms
        speaker_row.addWidget(speaker_label)
        speaker_row.addWidget(self.expected_speakers)
        speaker_row.addStretch(1)
        self.advanced_disclosure.content_layout.addLayout(speaker_row)

        self.advanced_panel = CollapsibleFrame("高级设置（缓存与覆盖）", "fa5s.cog", expanded=False)
        self.advanced_panel.set_summary("刷新校对 / 断句缓存 · 覆盖策略")
        advanced_row = QHBoxLayout()
        self.refresh_polish = SwitchControl("刷新字幕校对缓存")
        self.refresh_polish.setChecked(settings["cache"]["force_refresh_polish"])
        self.refresh_group = SwitchControl("刷新全文断句缓存")
        self.refresh_group.setChecked(settings["cache"]["force_refresh_group"])
        self.refresh_group.setEnabled(self.ai_grouping.isChecked())
        self.overwrite = FramelessPopupCombo()
        self.overwrite.addItem("覆盖已有结果", "overwrite")
        self.overwrite.addItem("跳过已有结果", "skip")
        self.overwrite.addItem("已有结果则报错", "error")
        advanced_row.addWidget(self.refresh_polish)
        advanced_row.addWidget(self.refresh_group)
        advanced_row.addStretch(1)
        advanced_row.addWidget(QLabel("已有字幕："))
        advanced_row.addWidget(self.overwrite)
        self.advanced_panel.content_layout.addLayout(advanced_row)
        # ------------------------------------------------------------
        # 首页只保留直接影响本批任务的 AI 智能断句入口。
        # ------------------------------------------------------------
        from .home_ai_widgets import HomeAiCard

        self._tile_panels = [
            ("ai", self.ai_panel, "AI 智能断句", "fa5s.project-diagram"),
        ]
        # 2026-10-22 (design B): one card under the recognition plan; it
        # opens the AI settings dialog (_build_home_process_card).
        self.setting_tiles = {"ai": HomeAiCard()}
        self._build_home_process_card(self.setting_tiles["ai"])
        self._refresh_ai_summary()
        for key, panel, _t, _i in self._tile_panels:
            if key == "ai":
                # Lives off-page; the AI settings dialog borrows it. Hidden
                # explicitly: a re-parented child is otherwise shown with the
                # page and floated over the home page's top-left corner.
                panel.setParent(page)
                panel.hide()
                continue
            layout.addWidget(panel)
            panel.toggled.connect(
                lambda checked, key=key: self.setting_tiles[key].setChecked(checked)
            )
            panel.set_expanded(False, animate=False)
            panel.setVisible(False)
        # 任务设置仍使用原控件作为运行参数的唯一来源，但不再占用首页。
        for panel in (self.advanced_disclosure, self.advanced_panel):
            panel.setParent(page)
            panel.setVisible(False)
        # Spare height stays below both columns instead of stretching a card.
        layout.addStretch(1)
        self.ai_panel.set_expanded(self.ai_panel._expanded, animate=False)
        # NOTE: The primary "取消 / 开始生成字幕" bar is now owned as self.bottom_bar
        # at the content_host level (fixed, outside any scroll). Do not add another here.
        if not self.ai_polish.isChecked() and not self.ai_grouping.isChecked():
            has_required_keys = True
        elif not self.ai_polish.isChecked():
            has_required_keys = bool(read_api_key(self.group_editor.values()['provider'], self.group_editor.values()['base_url'])[0])
        elif not self.ai_grouping.isChecked():
            has_required_keys = bool(resolve_api_key("polish")[0])
        elif self.unified_glm.isChecked():
            has_required_keys = bool(resolve_api_key("group")[0])
        else:
            has_required_keys = bool(
                resolve_api_key("polish")[0] and resolve_api_key("group")[0]
            )
        if not has_required_keys:
            self.ai_panel.set_expanded(True, animate=False)
        return page

    def _refresh_studio_entry_card(self) -> None:
        if not hasattr(self, "studio_entry_recent"):
            return
        studio = self.built_page("studio")
        if studio is not None:
            records = studio.recent_project_records()
        else:
            from ..projects.studio_project import studio_settings_path
            try:
                payload = json.loads(studio_settings_path().read_text('utf-8-sig'))
                records = payload.get('recent_projects', []) if isinstance(payload, dict) else []
            except FileNotFoundError:
                records = []
            except (OSError, ValueError) as exc:
                bind_text(self.studio_entry_recent, '工程记录读取失败：{exc}', exc=exc)
                self.studio_entry_card.set_cover_path("")
                return
        from .home_studio_entry import latest_studio_entry, recent_studio_entries
        name, cover_path = latest_studio_entry(records)
        bind_text(self.studio_entry_recent, "最近：{name}", name=name) if name else bind_text(self.studio_entry_recent, "最近：暂无工程")
        card = getattr(self, "studio_entry_card", None)
        if card is not None:
            card.set_cover_path(cover_path)
        hero = getattr(self, "studio_recent_hero", None)
        if hero is not None:
            entries = recent_studio_entries(records, limit=1 + self.studio_recent_list.limit)
            key = (entries, current_language())
            if key != getattr(self, "_studio_recent_key", None):
                self._studio_recent_key = key
                self._studio_recent_entries = entries
                hero.set_entry(entries[0] if entries else None)
                # The cover is the current project; the list holds the other
                # recent ones (2–4 by window height), and hovering a row previews it.
                self.studio_recent_list.set_entries(entries[1:])
                self.studio_recent_caption.setVisible(len(entries) > 1)

    def _sync_home_plan(self, tier: int) -> None:
        """Compact model cards at a fixed height per window-height tier (home
        C′, 2026-10-17); taller windows list one more recent project."""
        height = ui_zoom.px(home_plan_height(tier) + getattr(self, "_home_plan_extra", 0))
        # A recovery button wrapped under the badges may need a little more.
        self.recognition_plan.setMinimumHeight(height)
        self.recognition_plan.setMaximumHeight(height + ui_zoom.px(48))
        rows = 3 if tier == 2 else 2
        ai_card = getattr(self, "setting_tiles", {}).get("ai")
        if ai_card is not None:
            ai_card.set_compact(tier == 0)  # short windows: one row, no feature tags
        recent = getattr(self, "studio_recent_list", None)
        if recent is not None and recent.limit != rows:
            recent.limit = rows
            self._studio_recent_key = None
            self._refresh_studio_entry_card()

    def _schedule_home_fit(self) -> None:
        timer = getattr(self, "_home_fit_timer", None)
        if timer is None:
            timer = self._home_fit_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(self._fit_home_rhythm)
        timer.start()

    def _fit_home_rhythm(self) -> None:
        """Share a tall window's spare height a little at a time — a roomier
        drop zone (+40 px), taller model cards (+40 px) and up to 10 px more
        room around the sections — instead of an empty strip under the cards
        or one stretched card (home C′, 2026-10-17)."""
        page = getattr(self, "settings_page_widget", None)
        if page is None or not page.isVisible() or not hasattr(self, "_home_plan_layout"):
            return
        area = page.parentWidget()
        while area is not None and not hasattr(area, "viewport"):
            area = area.parentWidget()
        viewport = area.viewport().height() if area is not None else page.height()
        # Rate the page with the drop zone at its empty height: loading media
        # only shrinks the drop zone and never re-flows the cards (the tutorial
        # points at the language row right after its demo video loads).
        frame = self.media_frame
        drop_now = max(frame.minimumHeight(), min(frame.sizeHint().height(), frame.maximumHeight()))
        drop_base = ui_zoom.px(88 if ui_zoom.logical(self.height()) >= 900 else 82)
        natural = (page.layout().sizeHint().height() - (drop_now - drop_base)
                   - getattr(self, "_home_room_px", 0))
        room = max(0, min(40, round(ui_zoom.logical(viewport - natural) / 3.1)))  # 0..40 ≈ 0..125 px
        # What is still left is shared above and below the cards (≤ 40 px above).
        middle = max(0, min(40, round((ui_zoom.logical(viewport - natural) - room * 3.1) / 2)))
        if (room, middle) == getattr(self, "_home_room", None):
            return
        self._home_room = (room, middle)
        self._home_mid_space.changeSize(0, ui_zoom.px(2 + middle), QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        step, self._home_drop_extra, self._home_plan_extra = room // 4, room, room
        # Everything added outside the drop zone (its own extra is in drop_now).
        self._home_room_px = ui_zoom.px(round(step * 4.5) + self._home_plan_extra + middle)
        ui_zoom.set_layout(self._home_studio_layout, (20, 18 + step, 20, 18 + step), 12)
        ui_zoom.set_layout(self._home_ai_layout, (0, step // 2, 0, step // 2), 0)
        ui_zoom.set_layout(self._home_content_layout, (22, 16 + step, 22, 18 + step), 12 + step // 2)
        self._sync_home_plan(getattr(self, "_home_tier", (1,))[0])
        if not getattr(self, "media_paths", None):
            self._apply_media_mode(False)

    def _refresh_readiness_bar(self, plan_items) -> None:
        """Missing items as buttons that open their fix, and the reason the
        start button is disabled (2026-10-08). Start stays media-gated."""
        layout = getattr(self, "readiness_chips_layout", None)
        if layout is None:
            return
        from .ui_recognition import _ROLE_LABELS
        language = getattr(self, "_ui_language", current_language())
        self._last_plan_items = list(plan_items)
        # Narrow windows name the role only; the tooltip keeps the detail.
        compact = ui_zoom.logical(self.width()) < 1600
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # never left visible until the deferred delete
                item.widget().deleteLater()
        media_missing = not getattr(self, "media_paths", None)
        items = []
        if media_missing:
            items.append(("media", translate("选择素材", language), self._choose_media))
        for role, status in plan_items:
            action = ("安装模型" if status == "需要下载" else
                      _HOST_LIMIT_RECOVERY if status in _HOST_LIMIT_STATUSES else "配置 API")
            items.append(("plan", f"{translate(_ROLE_LABELS.get(role, role), language)} · {translate(status, language)}",
                          lambda _=False, r=role, a=action: self._recognition_recovery(r, a)))
        for kind, text, handler in items:
            chip = QPushButton(text.split(" · ")[0] if compact else text)
            chip.setToolTip(text)
            chip.setProperty("uiZoomOwnSize", True)  # minimum follows its (zoomed) size hint
            chip.setMinimumWidth(chip.sizeHint().width())
            chip.setObjectName("readinessChip")
            chip.setProperty("kind", kind)
            chip.setProperty("flexibleWidth", True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            install_themed_icon(chip, "fa5s.file-import" if kind == "media" else "fa5s.exclamation-circle",
                                "accent" if kind == "media" else "warning")
            chip.clicked.connect(handler)
            layout.addWidget(chip)
        # One group of clickable missing items; the button only says why.
        self.start_hint.hide()
        reason = translate("先选择素材才能开始", language) if media_missing else ""
        # The key follows home.start_run (2026-10-17: was a literal Ctrl+Enter).
        from ..studio import shortcut_registry as keys
        start_key = getattr(self, "_start_run_key", keys.BY_ID["home.start_run"].default)
        start_tip = translate("开始生成字幕 ({key})", language).format(
            key=keys.display(start_key) if start_key else translate("未绑定", language))
        self.start_button.setToolTip(reason or start_tip)

    def _preview_recent_project(self, index: int) -> None:
        timer = getattr(self, "_studio_preview_timer", None)
        if timer is None:
            timer = self._studio_preview_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(140)
            timer.timeout.connect(lambda: self._show_recent_project(0))
        if index < 0:
            timer.start()
            return
        timer.stop()
        self._show_recent_project(index + 1)

    def _show_recent_project(self, index: int) -> None:
        """index 0 is the current project (cover); rows are 1 and 2."""
        entries = getattr(self, "_studio_recent_entries", [])
        if 0 <= index < len(entries):
            self.studio_recent_hero.set_entry(entries[index])
            self.studio_recent_list.set_current(index - 1)

    def _build_home_process_card(self, tile) -> None:
        """The AI card under the recognition plan (2026-10-22, design B): only
        the way to set the AI up while it is not connected (the card and
        内容与术语 turn blue-grey, the content columns go under frosted glass),
        who does the work once it is. Settings open in a dialog."""
        card = self.home_process_card
        card.layout().addWidget(tile)
        self.ai_settings_button = tile.settings_button
        # 2026-10-15: the picture explainer for people who never heard of a key.
        self.ai_key_help_button = tile.help_button
        # 2026-10-22: a key that was never tested (or failed) locks translation and the
        # glossary; the test runs right here, without opening the settings.
        self.home_ai_test_button = tile.test_button
        self.home_ai_connect_button = tile.connect_button
        tile.clicked.connect(lambda _checked=False: self._open_ai_settings_dialog())
        tile.connect_requested.connect(lambda: self._open_ai_settings_dialog(enable_grouping=True))
        tile.settings_requested.connect(lambda: self._open_ai_settings_dialog())
        tile.test_requested.connect(self._test_ai_connection_from_home)
        tile.help_requested.connect(lambda: self._open_api_key_explainer())
        from .home_ai_widgets import FrostOverlay
        self.content_frost = FrostOverlay(self.content_terms_body, self.content_profile_card)
        self.content_frost.activated.connect(lambda: self._open_ai_settings_dialog(enable_grouping=True))
        self._refresh_home_process_facts()

    def _open_api_key_explainer(self) -> None:
        from .api_key_explainer import open_api_key_explainer
        open_api_key_explainer(self)

    def _refresh_home_process_facts(self, *_args) -> None:
        """The AI card's facts, then what they unlock on the home page (2026-10-22)."""
        self._refresh_home_ai_chips()
        self._apply_ai_feature_gate()

    def _apply_saved_ai_configuration(self, *, source, saved=False):
        """Startup and Save publish one effective state before notifying views.

        Existing requests retain their own snapshots; only idle UI references
        and clients created later observe this publication.
        """
        settings = self.legacy.RUNTIME_SETTINGS
        GLOBAL_PROVIDER_REGISTRY.bind(settings)
        if getattr(self, '_recognition_page_deferred', False):
            return
        for editor in (self.polish_editor, self.group_editor):
            editor._settings_ref = settings
        if saved:
            for editor in (self.polish_editor, self.group_editor):
                editor.accept_saved_configuration(settings)
        self._sync_ai_switches_with_keys()
        self._refresh_ai_advanced_summary()
        self._refresh_ai_summary()
        studio = self.built_page('studio')
        if studio is not None:
            studio.runtime_settings = settings
            refresh = getattr(studio, '_reload_ai_provider_selection', None)
            if callable(refresh):
                refresh(probe=False)
        from ..providers.ai_config_state import trace_configuration
        trace_configuration(source, settings)

    def _refresh_home_ai_chips(self) -> None:
        """The AI card's state (2026-10-22, design B): the AI gate, a test
        running from the home card and, once connected, who does the work.
        Key and connection stay separate facts in its words (user, 2026-10-08);
        a key that was never tested is never called connected."""
        tile = getattr(self, "setting_tiles", {}).get("ai")
        if tile is None or not hasattr(tile, "set_view"):
            return
        from ..providers import ai_connection_record as record
        from ..providers.llm_config import effective_ai_identity
        from .home_ai_widgets import AiCardView, TESTING
        saved = self.legacy.RUNTIME_SETTINGS
        switches = saved.get("switches", {})
        polish_on = bool(switches.get("enable_ai_polish", True))
        group_on = bool(switches.get("use_ai_grouping", True))
        stage = 'polish' if polish_on else 'group'
        try:
            gate = record.feature_gate(saved, stage)
        except Exception:  # noqa: BLE001 - unknown is not connection evidence
            gate = record.UNTESTED
        configured = record.service_gate(saved, stage) != record.NO_KEY
        view = AiCardView(gate, polish_on=polish_on, group_on=group_on, configured=configured, auxiliary_ready=record.service_gate(saved) == record.READY)
        if self._primary_ai_editor().connection_test_running(saved):
            view = AiCardView(TESTING, polish_on=polish_on, group_on=group_on)
        elif gate == record.READY:
            try:
                identity = effective_ai_identity(saved, "polish" if polish_on else "group")
            except (OSError, RuntimeError, TypeError, ValueError, KeyError):
                identity = {}
            checked = record.checked_at(saved, stage)
            view = AiCardView(record.READY, service=tr(str(identity.get("label") or "AI")),
                              model=str(identity.get("model") or ""),
                              tested_at=checked[5:16].replace("T", " ") if len(checked) >= 16 else "",
                              polish_on=polish_on, group_on=group_on,
                              auxiliary_ready=record.service_gate(saved) == record.READY)
        tile.set_view(view)
        self._apply_ai_zone_lock(view.locked, record.service_gate(saved))

    def _apply_ai_zone_lock(self, locked: bool, gate: str) -> None:
        """Blue-grey AI card and 内容与术语 while the AI is not connected; the
        content columns under frosted glass (2026-10-22, user)."""
        frames = ((self.__dict__.get("home_process_card"), locked),
                  (self.__dict__.get("content_profile_card"), False))
        for frame, frame_locked in frames:
            if frame is None or frame.property("aiLock") == frame_locked:
                continue
            frame.setProperty("aiLock", frame_locked)
            for widget in (frame, *frame.findChildren(QWidget)):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        frost = self.__dict__.get("content_frost")
        if frost is not None:
            frost.set_gate(gate)
            # Local glossary/name fields remain available; online controls own their gates.
            frost.set_active(False)
            if gate != self.__dict__.get("_ai_zone_gate"):
                frost.refresh()  # the columns' lock lines change with the gate
        self._ai_zone_gate = gate

    def _primary_ai_editor(self):
        """The service form AI 设置 shows first: the shared one when both stages use one service."""
        switches = self.legacy.RUNTIME_SETTINGS.get("switches", {})
        polish, group = switches.get("enable_ai_polish", True), switches.get("use_ai_grouping", True)
        shared = bool(switches.get("unified_glm_processing", True)) and polish and group
        return self.group_editor if shared or not polish else self.polish_editor

    def _test_ai_connection_from_home(self) -> None:
        """测试连接 on the home card: the saved service and key, as the AI settings would test them."""
        self._primary_ai_editor().test_connection()
        self._refresh_home_ai_chips()

    # ---- 2026-10-22: AI-only features wait for a key and a passed 测试连接 -------------
    AI_LOCK_LINES = {
        "no_key": "需要先填 API Key 并测试连接才能用",
        "untested": "需要先测试 AI 连接才能用",
        "failed": "AI 连接测试没通过，暂时不能用",
        "off": "AI 已关闭，打开后才能用",
    }

    def _ai_unlocked(self) -> bool:
        """Translation, 术语库校对 and 联网补充核验 may be used (the last _apply_ai_feature_gate answer)."""
        return _ai_unlocked(self)

    def _apply_ai_feature_gate(self) -> None:
        """Grey out what needs the AI text service until it has a key and passed a test.

        User (10-22): 术语库校对, 联网补充核验 and translation stay dark grey and
        say a key is needed; punctuation is local and stays free. Only the
        shown and the task's values change: the saved choices (enable_domain_terms,
        the subtitle output) are kept and come back once the AI is connected.
        """
        try:
            from ..providers.ai_connection_record import service_gate
            gate = service_gate(self.legacy.RUNTIME_SETTINGS)
        except Exception:  # noqa: BLE001 - unknown is not connection evidence
            gate = "untested"
        was = self.__dict__.get("_ai_gate_state")
        self._ai_gate_state = gate
        ready = gate == "ready"
        line = "" if ready else self.AI_LOCK_LINES.get(gate, self.AI_LOCK_LINES["no_key"])
        terms = self.__dict__.get("terms")
        if terms is not None:
            saved = bool((self.legacy.RUNTIME_SETTINGS.get("glossary") or {}).get("enable_domain_terms", False))
            with QSignalBlocker(terms):
                terms.setChecked(saved)
            terms.setEnabled(True)
            bind_text(terms, '使用本批已确认词库进行本地匹配；不需要启用 AI 断句。AI 校对与联网核验独立选择',
                      property='toolTip')
        search = self.__dict__.get("term_search")
        if search is not None:
            if not ready:
                with QSignalBlocker(search):
                    search.setChecked(False)
            search.setEnabled(ready)
        note = self.__dict__.get("term_search_note")
        if note is not None:
            bind_text(note, line or '仅本次任务启用；需可验证的搜索能力')
            note.setProperty("tone", "warn" if line else "off")
            note.style().unpolish(note)
            note.style().polish(note)
        unlock = self.__dict__.get("terms_unlock_button")
        if unlock is not None:
            unlock.setVisible(not ready)
        self._sync_translation_lock(ready)
        if was != gate:
            self._refresh_glossary_chips()
            if self.__dict__.get("recognition_language") is not None:
                self._subtitle_language_changed(save=False)

    def _sync_translation_lock(self, ready: bool) -> None:
        """Only "只显示原文" while the AI is not connected; the saved choice comes back after."""
        combo = self.__dict__.get("subtitle_output")
        if combo is None:
            return
        labels = {"original": "只显示原文", "bilingual": "原文 + 翻译（双语）", "translation": "只显示翻译"}
        model = combo.model()
        for index in range(combo.count()):
            value = str(combo.itemData(index) or "")
            item = model.item(index) if hasattr(model, "item") else None
            if value == "original" or item is None:
                continue
            item.setEnabled(ready)
            label = labels.get(value, combo.itemText(index))
            combo.setItemText(index, str(tr(label)) if ready else str(tr("{value0}（文字服务未就绪）", value0=tr(label))))
        saved = str(((self.legacy.RUNTIME_SETTINGS or {}).get("subtitle_language") or {}).get("output") or "original")
        wanted = saved if ready else "original"
        index = combo.findData(wanted)
        if index >= 0 and combo.currentIndex() != index:
            with QSignalBlocker(combo):
                combo.setCurrentIndex(index)
        # User (10-23): locked shut, in the lock colour with a lock, on 「只显示原文」
        # (the saved choice is untouched and comes back once the AI is connected).
        combo.setEnabled(ready)
        combo.setProperty("aiLock", not ready)
        original = combo.findData("original")
        if original >= 0:
            from PySide6.QtGui import QIcon
            icon = QIcon()
            if not ready:
                import qtawesome as qta
                from ..design.home_qss import ai_lock_palette
                side = ui_zoom.px(14)
                pixmap = qta.icon("fa5s.lock", color=ai_lock_palette(_active_theme_definition())["title"]).pixmap(
                    QSize(side, side))
                for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled):
                    icon.addPixmap(pixmap, mode)
            combo.setItemIcon(original, icon)
        bind_text(combo, '译文/双语：识别完成后用已配置的 AI 文字服务把字幕翻成所选语言（只发送字幕文字，不发送音频）；原文、说话人和时间保持不变。'
                  if ready else '连上 AI 才能翻译字幕；现在只显示原文，连上后恢复你选的', property='toolTip')
        caption = self.__dict__.get("subtitle_output_caption")
        if caption is not None:
            bind_text(caption, '字幕显示' if ready else '字幕显示 · 连上 AI 才能翻译')
            caption.setProperty("aiLock", not ready)
        field = combo.parentWidget()
        field = field if hasattr(field, "refresh_theme") else None
        if field is not None:
            field.setProperty("aiLock", not ready)   # the whole field takes the lock look (design A)
        for widget in (field, combo, caption, getattr(field, "chevron", None)):
            if widget is not None:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        if field is not None:
            field.refresh_theme()

    def _ai_settings_snapshot(self) -> dict:
        names = ("ai_polish", "ai_grouping", "prefer_arabic_numbers", "unified_glm", "share_key")
        return {"polish": self.polish_editor.values(), "group": self.group_editor.values(),
                "switches": {name: getattr(self, name).isChecked() for name in names if hasattr(self, name)},
                "asr_dirty": getattr(self, "_asr_config_dirty", False),
                "status": (self.ai_save_status.objectName(), self.ai_save_status.text())}

    def _restore_ai_settings(self, snapshot: dict) -> None:
        """Cancel: put every control back exactly as it was when opened."""
        from PySide6.QtCore import QSignalBlocker
        for name, value in snapshot["switches"].items():
            control = getattr(self, name)
            blocker = QSignalBlocker(control)
            control.setChecked(value)
            del blocker
        for editor, key in ((self.polish_editor, "polish"), (self.group_editor, "group")):
            try:
                editor.restore_profile_values(snapshot[key], self.legacy.RUNTIME_SETTINGS)
            except (KeyError, ValueError):
                pass
        self._apply_unified_glm_mode(self.unified_glm.isChecked())
        if hasattr(self, "refresh_group"):
            self.refresh_group.setEnabled(self.ai_grouping.isChecked())
        self._asr_config_dirty = snapshot["asr_dirty"]
        name, status = snapshot["status"]
        self.ai_save_status.setObjectName(name)
        self.ai_save_status.setText(status)
        self.ai_save_status.style().unpolish(self.ai_save_status)
        self.ai_save_status.style().polish(self.ai_save_status)

    from .settings_lifecycle import owned_settings as _owned_settings

    @observed('settings.ai_open')
    @_owned_settings('ai')
    def _open_ai_settings_dialog(self, on_finished=None, *, enable_grouping: bool = False) -> None:
        """AI segmentation & proofreading settings (2026-10-08): fixed title,
        close, Cancel and Save; the form scrolls between them. Cancel restores
        every control; the home page's media, settings and scroll stay put."""
        # Direct project startup defers Home, which owns these shared controls.
        # Build them on demand without leaving Studio or losing translation scope.
        self._ensure_recognition_page()
        tile = getattr(self, "setting_tiles", {}).get("ai")
        if tile is not None and tile.isChecked():
            tile.setChecked(False)
        current = getattr(self, "_ai_settings_dialog", None)
        if current is not None and current.isVisible():
            current.raise_()
            current.activateWindow()
            return
        from ..design.presentation import button_role
        panel = self.ai_panel
        snapshot = self._ai_settings_snapshot()
        # Only the explicit Home enable action changes the draft switch. Cancel
        # restores the snapshot; ordinary settings preserve the saved OFF choice.
        if enable_grouping:
            self.ai_grouping.setChecked(True)
        dialog = SpringDialog(self)
        dialog.ENTRY_ANIMATED = False
        from .settings_lifecycle import retain, trace
        retain(self, dialog, 'ai')
        dialog.setObjectName("aiSettingsDialog")
        dialog.setProperty("enableGroupingIntent", enable_grouping)
        bind_text(dialog, 'AI 文字服务设置', property='windowTitle')
        dialog.setWindowIcon(_app_icon())
        # 2026-10-22 (design D2 refined): narrow and as tall as its content (fit()).
        dialog.resize(min(ui_zoom.px(800), max(ui_zoom.px(660), self.width() - 120)),
                      min(800, max(520, self.height() - 120)))
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame(dialog)
        header.setObjectName("aiDialogHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(20, 14, 14, 12)
        head.setSpacing(10)
        # One line: the title and where the connection stands; what a key is
        # and what to do now live in the guide column (2026-10-22).
        title = QLabel("AI 文字服务设置")
        title.setObjectName("aiDialogTitle")
        head.addWidget(title)
        self.ai_dialog_state_label = QLabel()
        self.ai_dialog_state_label.setObjectName("aiDialogState")
        head.addWidget(self.ai_dialog_state_label, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        close = button_role(QPushButton(""), "ghost")
        close.setFixedSize(36, 36)
        install_themed_icon(close, "fa5s.times", "secondary")
        close.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        bind_text(close, '关闭 AI 设置', property='accessibleName')
        bind_text(close, '关闭（不保存修改）', property='toolTip')
        close.clicked.connect(dialog.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)
        scroll = QScrollArea(dialog)
        scroll.setObjectName("aiDialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("aiDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 14)
        body_layout.setSpacing(0)
        panel.setParent(body)
        body_layout.addWidget(panel)
        body_layout.addStretch(1)
        panel.header.hide()
        self.save_ai_button.hide()
        panel.setVisible(True)
        panel.set_expanded(True, animate=False)
        # 高级设置 starts closed, except for a custom service (it needs its address).
        main_editor = self.__dict__.get("_ai_main_editor") or self._primary_ai_editor()
        self.ai_advanced_toggle.setChecked(str(main_editor.service.currentData() or "") == "custom")
        self._show_ai_advanced(self.ai_advanced_toggle.isChecked())
        # Inside the scrolling form the panel may grow (advanced groups).
        panel.content.setMaximumHeight(16777215)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        # 取消 and 保存设置 sit at the foot of the form column, beside the save
        # line (only a warning — unsaved changes, a failed save — shows there).
        foot = self.ai_actions_row
        status = self.ai_save_status
        status_home = panel.content_layout
        status.setWordWrap(True)   # other languages' warnings are longer than the room beside the buttons
        foot.addWidget(status, 3)
        status.setVisible(status.objectName() == "statusWarn")
        foot.addStretch(1)
        cancel = button_role(QPushButton("取消"), "secondary")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("保存并启用断句" if enable_grouping else "保存设置")
        save.setObjectName("primary")
        button_role(save, "primary")
        for button in (cancel, save):   # as tall as the fields and 测试连接 beside them
            button.setProperty("aiDialogAction", True)
        foot.addWidget(cancel)
        foot.addWidget(save)
        self.ai_dialog_save_button = save
        self._refresh_ai_dialog_state()
        self._refresh_ai_advanced_summary()

        def fit():
            """As tall as the form (2026-10-22: no empty band under it) and never
            narrower than it (2026-10-25, user: with 更多选项 open its right side
            was cut off — the form has no horizontal scroll bar), within the window."""
            if not dialog.isVisible():
                return

            def height_of(widget, width):
                # Wrapped labels over-state their size hint; ask for this width.
                value = widget.heightForWidth(width) if widget.hasHeightForWidth() else -1
                return value if value > 0 else widget.sizeHint().height()

            from .window_constraints import available_rect
            bounds = available_rect(dialog, within_parent=True)   # the main window, on its screen
            bar = scroll.verticalScrollBar().sizeHint().width()
            need = max(header.minimumSizeHint().width(), body.minimumSizeHint().width() + bar)
            # Room permitting, wide enough for 「让 AI 负责」 to keep its notes on one
            # line (longer languages wrapped them into narrow columns) — already
            # while 更多选项 is closed, so opening it does not make the dialog jump.
            body.layout().activate()
            row, box, line = self._ai_options_row, self.ai_advanced_box, self._ai_advanced_head
            if box.isVisible() and row.geometry().width() > 0:
                room = row.geometry().width()
                self._ai_options_inset = line.geometry().width() - room   # the box's margins and border
            else:
                box.ensurePolished()   # its notes measure with their own fonts
                # A closed box keeps the sizes of texts it had before (a language
                # switch); nested rows refresh only when they are laid out.
                for owner in (box, *box.findChildren(QWidget)):
                    stack = [owner.layout()] if owner.layout() is not None else []
                    while stack:
                        layout = stack.pop()
                        layout.invalidate()
                        stack.extend(item.layout() for item in (layout.itemAt(i) for i in range(layout.count()))
                                     if item.layout() is not None)
                margins = box.layout().contentsMargins()
                room = line.geometry().width() - (self.__dict__.get("_ai_options_inset")
                                                  or margins.left() + margins.right() + 2)
            comfortable = max(need, dialog.width() + row.sizeHint().width() - room) if room > 0 else need
            width = max(dialog.width(), min(comfortable, bounds.width()))
            # Only a main window narrower than the form makes it scroll sideways.
            sideways = need > width
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if sideways
                                                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = max(body.minimumSizeHint().width(),
                        width - (bar if scroll.verticalScrollBar().isVisible() else 0))
            want = height_of(header, width) + height_of(body, inner) + 6
            if sideways:
                want += scroll.horizontalScrollBar().sizeHint().height()
            screen = dialog.screen().availableGeometry() if dialog.screen() is not None else None
            limit = min(max(520, self.height() - 80), screen.height() - 60 if screen is not None else 10_000)
            height = max(300, min(limit, want))
            if (width, height) != (dialog.width(), dialog.height()):
                center = self.geometry().center()
                x = max(bounds.left(), min(center.x() - width // 2, bounds.right() + 1 - width))
                grew = width > dialog.width()
                dialog.setGeometry(x, max(0, center.y() - height // 2), width, height)
                if grew:   # the taller form may now have a scroll bar that takes some width back
                    QTimer.singleShot(0, fit)

        self._ai_dialog_fit = fit
        saved = [False]

        def save_and_close():
            if self._save_ai_configuration(show_feedback=True):
                saved[0] = True
                dialog.accept()

        save.clicked.connect(save_and_close)

        def finished(_result):
            if not saved[0]:
                self._restore_ai_settings(snapshot)
            panel.set_expanded(False, animate=False)
            panel.setParent(self.settings_page_widget)
            panel.hide()
            self.save_ai_button.show()
            self._ai_settings_dialog = None
            self.ai_dialog_state_label = None   # it and the save button go with the dialog
            self.ai_dialog_save_button = None
            self._ai_dialog_fit = None
            while foot.count():                  # the dialog's buttons and spacer go with it
                widget = foot.takeAt(0).widget()
                if widget is cancel or widget is save:
                    widget.hide()
                    widget.deleteLater()
            status_home.addWidget(status)       # back under the off-page form
            status.show()
            self._refresh_ai_summary()
            if on_finished is not None:
                on_finished()
            dialog.deleteLater()

        dialog.finished.connect(finished)
        trace('showing', 'ai')
        dialog.show()
        # CollapsibleFrame.showEvent re-caps the content height; inside the
        # scrolling form it must grow freely (advanced groups, two editors).
        panel.content.setMaximumHeight(16777215)
        fit()
        # Again once the zoom and the style sheets have settled: the first pass
        # came out a few px short and left a scroll bar (10-23, real window).
        QTimer.singleShot(0, fit)
        QTimer.singleShot(250, fit)
        dialog.raise_()
        dialog.activateWindow()
        # Ready to paste: the key box has the focus while there is no key.
        main_editor = self.__dict__.get("_ai_main_editor")
        if main_editor is not None:
            (main_editor.key if not main_editor.has_key() else main_editor.service).setFocus()

    def _apply_media_mode(self, ready: bool) -> None:
        """Empty: a one-row dashed drop zone (title, hint and formats, the
        button at the right; home C′ 2026-10-17). Loaded: the compact row."""
        layout = getattr(self, "media_row_layout", None)
        if layout is None:
            return
        hero = not ready
        for spacer in (self.media_lead_space, self.media_tail_space):
            spacer.changeSize(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.media_kind_gap.changeSize(0 if hero else 20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        layout.setStretch(self._media_text_index, 1)
        self.media_kind_label.setVisible(not hero)
        self.media_formats.setVisible(hero)
        tall = ui_zoom.logical(self.height()) >= 900
        icon = (48 if tall else 44) if hero else 36
        self.media_type_icon.setFixedSize(icon, icon)
        layout.setContentsMargins(*((24, 8, 24, 8) if hero else (12, 8, 12, 8)))
        layout.setSpacing(16 if hero else 6)
        if hero:
            height = (88 if tall else 82) + getattr(self, "_home_drop_extra", 0)
            self.media_frame.setMinimumHeight(height)
            self.media_frame.setMaximumHeight(height)
        else:
            self.media_frame.setMinimumHeight(66)
            self.media_frame.setMaximumHeight(16777215)
        self.choose_media_button.setProperty("heroAction", hero)
        install_themed_icon(self.choose_media_button, "fa5s.folder-open", "on_accent" if hero else "primary")
        self.choose_media_button.style().unpolish(self.choose_media_button)
        self.choose_media_button.style().polish(self.choose_media_button)
        layout.invalidate()

    def _style_home_icons(self) -> None:
        icon = getattr(self, "studio_entry_icon", None)
        if icon is None:
            return
        import qtawesome as qta
        theme = _active_theme_definition()
        zones = theme.zone_colors
        icon.setPixmap(qta.icon("fa5s.closed-captioning", color=zones["studio"]).pixmap(QSize(20, 20)))
        content_icon = getattr(self, "content_icon", None)
        if content_icon is not None:
            content_icon.setPixmap(qta.icon("fa5s.tags", color=zones["content"]).pixmap(QSize(18, 18)))
        tile = getattr(self, "setting_tiles", {}).get("ai")
        if tile is not None:
            tile.refresh_theme()
        # 2026-10-23 (home design A): the language row's chevrons and arrow chip.
        arrow = self.__dict__.get("home_language_arrow")
        if arrow is not None:
            side = ui_zoom.px(14)
            arrow.setPixmap(qta.icon("fa5s.arrow-right", color=zones["content"]).pixmap(QSize(side, side)))
        for name in ("spoken_language_field", "translation_field", "punctuation_field"):
            field = self.__dict__.get(name)
            if field is not None and hasattr(field, "refresh_theme"):
                field.refresh_theme()
        output = self.__dict__.get("subtitle_output")
        if output is not None and hasattr(output.parentWidget(), "refresh_theme"):
            output.parentWidget().refresh_theme()


    def _action_bar(self):
        from ..design.presentation import button_role
        # Idle only exposes actions that can be performed in the current
        # state. Closing the application remains the window close action;
        # a task-running stop control is owned by the progress page.
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 10, 16, 10)
        self.action_status = QLabel("")
        self.action_status.setObjectName("statusGood")
        bar_layout.addWidget(self.action_status)
        # 2026-10-08: what is missing, as clickable items that open the fix.
        self.readiness_chips_layout = QHBoxLayout()
        self.readiness_chips_layout.setSpacing(6)
        bar_layout.addSpacing(6)
        bar_layout.addLayout(self.readiness_chips_layout)
        bar_layout.addStretch(1)
        # Why start is unavailable, as a link to the fix (start stays disabled).
        self.start_hint = QPushButton("")
        self.start_hint.setObjectName("startHint")
        self.start_hint.setProperty("flexibleWidth", True)
        self.start_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_hint.clicked.connect(lambda: getattr(self, "_start_hint_action", lambda: None)())
        self.start_hint.hide()
        bar_layout.addWidget(self.start_hint)
        bar_layout.addSpacing(10)
        studio_button = AnimatedButton("字幕工作台")
        studio_button.setObjectName("studioFooterButton")
        studio_button.setIcon(_icon("fa5s.closed-captioning"))
        bind_text(studio_button, '进入已有字幕工程与后期工作台', property='toolTip')
        studio_button.clicked.connect(lambda: self.open_studio_project())
        self.studio_footer_button = studio_button
        button_role(studio_button, "secondary", size="default")
        self.start_button = AnimatedButton("开始生成字幕")
        self.start_button.setObjectName("primary")
        install_themed_icon(self.start_button, "fa5s.play-circle", "on_accent")
        self.start_button.setIconSize(QSize(24, 24))
        self.start_button.setMinimumWidth(220)
        button_role(self.start_button, "primary", size="large")
        self.start_button.setProperty("homeGenerate", True)
        self.start_button.setMinimumWidth(320)
        self.start_button.setShortcut(QKeySequence("Ctrl+Return"))
        bind_text(self.start_button, '开始生成字幕 (Ctrl+Enter)', property='toolTip')
        _bind_home_shortcuts(self, bar)
        self.start_button.clicked.connect(self._start_run)
        # The dedicated Studio card owns this entrance; retain the attribute
        # for callers without a second competing footer action.
        studio_button.setParent(bar)
        studio_button.hide()
        # 2026-10-14 匹配文稿: the user's own line-broken script, timed by the
        # character-timestamp model only (no other model, no AI).
        self.script_match_button = AnimatedButton("匹配文稿")
        self.script_match_button.setObjectName("homeScriptMatch")
        button_role(self.script_match_button, "secondary", size="large", icon="fa5s.align-left")
        bind_text(self.script_match_button, '已有断好句的文稿：只用字级时间对齐，不跑其他识别模型或 AI', property='toolTip')

        def open_script_match():
            from .home_script_match import open_home_script_match
            open_home_script_match(self)
        self.script_match_button.clicked.connect(open_script_match)
        bar_layout.addWidget(self.script_match_button)
        bar_layout.addSpacing(10)
        bar_layout.addWidget(self.start_button)
        self.action_bar = bar
        return bar

    def _progress_page(self):
        """Recognition progress (2026-10-07): overall progress, current phase,
        what is running and elapsed time first; feed and full log second."""
        page = QWidget()
        page.setObjectName("progressPage")
        self.progress_page_root = page
        page.setStyleSheet(progress_page_qss(_active_theme_definition()))
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 18, 28, 14)
        layout.setSpacing(14)

        # 2026-10-08 (M13, user): no frame around the overview. A frameless
        # header with the run bar, then an independent phase row; header,
        # phases and both columns share the page's edges and one spacing.
        hero = QWidget()
        hero.setObjectName("progressHeader")
        self.progress_hero = hero
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(28)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        title = QLabel("2ByteASR 正在制作字幕")
        title.setObjectName("progressTitle")
        self.progress_title = title
        hero_text.addWidget(title)
        self.progress_context = QLabel("正在准备任务…")
        self.progress_context.setObjectName("progressContext")
        # One short line; a wrapping label would make the whole window
        # height-for-width and Qt then refuses short windows (M12).
        hero_text.addWidget(self.progress_context)
        head.addLayout(hero_text, 1)
        steps_box = QVBoxLayout()
        steps_box.setSpacing(2)
        steps_caption = QLabel("已完成")
        steps_caption.setObjectName("progressElapsedCaption")
        steps_caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        steps_box.addWidget(steps_caption)
        self.progress_steps = QLabel("0 / 11 步")
        self.progress_steps.setObjectName("progressStat")
        self.progress_steps.setAlignment(Qt.AlignmentFlag.AlignRight)
        steps_box.addWidget(self.progress_steps)
        head.addLayout(steps_box)
        elapsed_box = QVBoxLayout()
        elapsed_box.setSpacing(2)
        elapsed_caption = QLabel("已用时")
        elapsed_caption.setObjectName("progressElapsedCaption")
        elapsed_caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        elapsed_box.addWidget(elapsed_caption)
        self.stage_elapsed = QLabel("00:00")
        self.stage_elapsed.setObjectName("progressElapsed")
        self.stage_elapsed.setAlignment(Qt.AlignmentFlag.AlignRight)
        elapsed_box.addWidget(self.stage_elapsed)
        head.addLayout(elapsed_box)
        head_rule = QFrame()
        head_rule.setObjectName("progressFooterRule")
        head_rule.setFixedWidth(1)
        head_rule.setMinimumHeight(40)
        head.addWidget(head_rule, 0, Qt.AlignmentFlag.AlignVCenter)
        self.progress_percent = QLabel("0%")
        self.progress_percent.setObjectName("progressPercent")
        self.progress_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_percent.setMinimumWidth(92)
        bind_text(self.progress_percent, '按已完成的步骤计算；正在运行的步骤有真实批次进度时计入。保存成功后才显示 100%', property='toolTip')
        head.addWidget(self.progress_percent)
        hero_layout.addLayout(head)

        # 2026-10-08 (M12): always determinate. Steps are drawn as segments;
        # the running step's segment brightens only on real output events.
        self.progress_bar = StageProgressBar()
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setFixedHeight(8)
        hero_layout.addWidget(self.progress_bar)
        layout.addWidget(hero)
        self._recognition_live_work = {}
        self._phase_degraded = {}
        self._progress_motion = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_motion.setDuration(460)
        self._progress_motion.setEasingCurve(QEasingCurve.Type.OutCubic)

        phase_row = QHBoxLayout()
        phase_row.setSpacing(14)
        self.phase_cards = [
            ProgressPhaseCard("fa5s.wave-square", "本地识别", "转写与主播", GREEN, number=1),
            ProgressPhaseCard("fa5s.magic", "字幕校对", "模型安全纠错", AMBER, number=2),
            ProgressPhaseCard("fa5s.comment-alt", "全文断句", "语义与时间轴", BLUE, number=3),
            ProgressPhaseCard("fa5s.file-export", "保存结果", "工程与报告", CORAL, number=4),
        ]
        for card in self.phase_cards:
            phase_row.addWidget(card, 1)
        layout.addLayout(phase_row)

        self.progress_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.progress_splitter.setObjectName("progressSplitter")
        self.progress_splitter.setChildrenCollapsible(False)
        self.progress_splitter.setHandleWidth(14)
        left_host = QWidget()
        left_host.setObjectName("progressLeftContent")
        left_column = QVBoxLayout(left_host)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(14)

        current_card = QFrame()
        current_card.setObjectName("currentStageCard")
        self.current_stage_card = current_card
        current_layout = QVBoxLayout(current_card)
        current_layout.setContentsMargins(20, 14, 20, 16)
        current_layout.setSpacing(8)
        eyebrow_row = QHBoxLayout()
        eyebrow_row.setSpacing(10)
        eyebrow = QLabel("当前步骤")
        eyebrow.setObjectName("stageEyebrow")
        eyebrow_row.addWidget(eyebrow)
        self.stage_step_label = QLabel()
        self.stage_step_label.setObjectName("stageStep")
        eyebrow_row.addWidget(self.stage_step_label)
        eyebrow_row.addStretch(1)
        # Device / service is context, not the headline (M13).
        self.stage_device_label = QLabel()
        self.stage_device_label.setObjectName("stageDevice")
        eyebrow_row.addWidget(self.stage_device_label)
        self.running_indicator = RunningIndicator()
        self.running_indicator.set_status('准备中', 'muted')
        eyebrow_row.addWidget(self.running_indicator)
        current_layout.addLayout(eyebrow_row)
        # 2026-10-08 (M12): the action in plain words first, then its live
        # facts (elapsed, real output, last output, device).
        # 2026-10-09 (M14, user): action and a one-line description on the
        # left, the live facts as a label / value column on the right.
        stage_body = QHBoxLayout()
        stage_body.setSpacing(28)
        stage_lead = QVBoxLayout()
        stage_lead.setSpacing(4)
        self.progress_stage = QLabel("等待启动")
        self.progress_stage.setObjectName("stageLarge")
        self.progress_stage.setWordWrap(True)
        stage_lead.addWidget(self.progress_stage)
        self.progress_resource = QLabel("准备检查运行环境")
        self.progress_resource.setObjectName("stageSubtitle")
        self.progress_resource.setWordWrap(True)
        stage_lead.addWidget(self.progress_resource)
        stage_lead.addStretch(1)
        stage_body.addLayout(stage_lead, 1)
        self.stage_metrics = StageMetricGrid()
        self.stage_metrics.setMinimumWidth(200)
        self.stage_metrics.hide()
        stage_body.addWidget(self.stage_metrics, 0, Qt.AlignmentFlag.AlignTop)
        current_layout.addLayout(stage_body)
        # 2026-10-15: provider-reported token usage of this step and of the
        # task, full width and wrapped so long numbers never squeeze the title.
        self.stage_usage_label = QLabel()
        self.stage_usage_label.setObjectName("stageSubtitle")
        self.stage_usage_label.setWordWrap(True)
        self.stage_usage_label.hide()
        current_layout.addWidget(self.stage_usage_label)
        # One-line notice; the full explanation opens on demand.
        self.stage_note_row = QFrame()
        self.stage_note_row.setObjectName("stageNoteRow")
        note_layout = QGridLayout(self.stage_note_row)
        note_layout.setContentsMargins(12, 6, 8, 6)
        note_layout.setHorizontalSpacing(8)
        note_layout.setVerticalSpacing(4)
        self.stage_note_icon = QLabel()
        self.stage_note_icon.setObjectName("stageNoteIcon")
        self.stage_note_icon.setFixedSize(16, 16)
        note_layout.addWidget(self.stage_note_icon, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self.stage_note = ElidedValueLabel()
        self.stage_note.setObjectName("stageNote")
        self.stage_note.setMinimumWidth(0)
        self.stage_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        note_layout.addWidget(self.stage_note, 0, 1)
        self.stage_note_more = QToolButton()
        self.stage_note_more.setObjectName("stageNoteMore")
        self.stage_note_more.setCheckable(True)
        self.stage_note_more.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.stage_note_more, '查看详情')
        note_layout.addWidget(self.stage_note_more, 0, 2, Qt.AlignmentFlag.AlignVCenter)
        self.stage_note_detail = QLabel()
        self.stage_note_detail.setObjectName("stageNoteDetail")
        self.stage_note_detail.setWordWrap(True)
        self.stage_note_detail.hide()
        note_layout.addWidget(self.stage_note_detail, 1, 1, 1, 2)
        note_layout.setColumnStretch(1, 1)
        self.stage_note_more.toggled.connect(self._toggle_stage_note_detail)
        self.stage_note_row.hide()
        current_layout.addWidget(self.stage_note_row)
        self.active_tasks_label = QLabel("尚无运行中的子任务")
        self.active_tasks_label.setWordWrap(True)
        self._style_active_tasks_label()
        self.active_tasks_label.hide()
        current_layout.addWidget(self.active_tasks_label)
        # Raw live rows stay for audits; the metrics above and the preview
        # below show the same events in readable form.
        live_caption = QLabel("实时识别输出")
        live_caption.setObjectName("sectionNote")
        live_caption.hide()
        self.progress_live_caption = live_caption
        current_layout.addWidget(live_caption)
        self.recognition_live_status = ElidedRowsLabel()
        self.recognition_live_status.setText('等待真实识别结果；文字将在已完成批次返回后显示')
        self.recognition_live_status.hide()
        current_layout.addWidget(self.recognition_live_status)
        left_column.addWidget(current_card)

        feed_card = QFrame()
        feed_card.setObjectName("eventFeedCard")
        feed_layout = QVBoxLayout(feed_card)
        feed_layout.setContentsMargins(18, 14, 14, 14)
        feed_layout.setSpacing(8)
        feed_header = QHBoxLayout()
        feed_title = QLabel("处理记录")
        feed_title.setObjectName("sectionCaption")
        feed_header.addWidget(feed_title)
        feed_header.addStretch(1)
        feed_note = QLabel("每一步的用时与结果")
        feed_note.setObjectName("sectionNote")
        feed_header.addWidget(feed_note)
        feed_layout.addLayout(feed_header)
        self.event_log = FeedList()
        self.event_log.setObjectName("eventFeed")
        self.event_log.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.event_log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.event_log.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.event_log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The record is the left column's body (M13); the preview below
        # keeps a few rows only.
        feed_layout.addWidget(self.event_log, 1)
        # 2026-10-08 (M12): the newest readable text, marked as not yet
        # proofread until a later step says otherwise.
        feed_rule = QFrame()
        feed_rule.setObjectName("feedRule")
        feed_rule.setFixedHeight(1)
        feed_layout.addSpacing(2)
        feed_layout.addWidget(feed_rule)
        feed_layout.addSpacing(2)
        preview_header = QHBoxLayout()
        preview_title = QLabel("最新识别内容")
        preview_title.setObjectName("sectionCaption")
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        self.preview_source = QLabel()
        self.preview_source.setObjectName("sectionNote")
        preview_header.addWidget(self.preview_source)
        feed_layout.addLayout(preview_header)
        self.recognition_preview = RecognitionPreview()
        feed_layout.addWidget(self.recognition_preview, 0)
        left_column.addWidget(feed_card, 1)
        # 2026-10-08 (M12): on short windows the left column scrolls instead
        # of forcing the window taller than the screen.
        left_scroll = QScrollArea()
        left_scroll.setObjectName("progressLeftScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_host)
        self.progress_left_column = left_scroll
        self.progress_left_content = left_host
        self.progress_splitter.addWidget(left_scroll)

        console_card = QFrame()
        console_card.setObjectName("consoleCard")
        console_layout = QVBoxLayout(console_card)
        console_layout.setContentsMargins(16, 12, 12, 12)
        console_layout.setSpacing(8)
        console_header = QHBoxLayout()
        console_header.setSpacing(10)
        console_title = QLabel("完整运行日志")
        console_title.setObjectName("sectionCaption")
        console_header.addWidget(console_title)
        console_badge = QLabel("已接入原 CMD 输出")
        console_badge.setObjectName("sectionNote")
        console_header.addWidget(console_badge)
        console_header.addStretch(1)
        self.copy_console_button = AnimatedButton("复制全部")
        self.copy_console_button.setProperty("buttonRole", "ghost")
        self.copy_console_button.setProperty("controlSize", "compact")
        install_themed_icon(self.copy_console_button, "fa5s.copy", "secondary")
        self.copy_console_button.clicked.connect(self._copy_console_log)
        console_header.addWidget(self.copy_console_button)
        self.expand_console_button = AnimatedButton("放大日志")
        self.expand_console_button.setProperty("buttonRole", "ghost")
        self.expand_console_button.setProperty("controlSize", "compact")
        self.expand_console_button.setCheckable(True)
        install_themed_icon(self.expand_console_button, "fa5s.expand-alt", "secondary")
        bind_text(self.expand_console_button, '放大日志，暂时收起左侧步骤与任务动态（会记住选择）', property='toolTip')
        self.expand_console_button.toggled.connect(self._set_console_expanded)
        console_header.addWidget(self.expand_console_button)
        console_layout.addLayout(console_header)
        self.console_log = QTextEdit()
        self.console_log.setObjectName("consoleLog")
        self.console_log.setReadOnly(True)
        self.console_log.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.console_log.document().setMaximumBlockCount(800)
        self.console_log.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.console_log.customContextMenuRequested.connect(
            self._show_console_context_menu
        )
        console_layout.addWidget(self.console_log, 1)
        self.progress_splitter.addWidget(console_card)
        self.progress_splitter.setStretchFactor(0, 5)
        self.progress_splitter.setStretchFactor(1, 7)
        self.progress_splitter.splitterMoved.connect(self._remember_progress_layout)
        layout.addWidget(self.progress_splitter, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.progress_hint = QLabel("运行日志会同步保存在项目报告中")
        self.progress_hint.setObjectName("muted")
        row.addWidget(self.progress_hint)
        row.addStretch(1)
        # 四十三轮：Studio 后台识别跳转来看详细进度时，提供回程（studio
        # context 存在时才显示）。
        self.back_to_studio_button = AnimatedButton("返回 Studio")
        self.back_to_studio_button.setObjectName("outline")
        bind_text(self.back_to_studio_button, '回到字幕工程继续查看（识别仍在后台运行）', property='toolTip')
        self.back_to_studio_button.clicked.connect(self._back_to_studio_from_progress)
        self.back_to_studio_button.hide()
        row.addWidget(self.back_to_studio_button)
        self.cancel_run_button = AnimatedButton("安全取消")
        self.cancel_run_button.setObjectName("danger")
        self.cancel_run_button.setShortcut(QKeySequence("Escape"))
        bind_text(self.cancel_run_button, '安全取消当前任务 (Esc)', property='toolTip')
        self.cancel_run_button.clicked.connect(self._cancel_run)
        row.addWidget(self.cancel_run_button)
        layout.addLayout(row)
        self._restore_progress_layout()
        self._progress_resize_watcher = ResizeWatcher(page, self._adapt_progress_density)

        self._active_stages = {}
        self._completed_stages = set()
        self._skipped_stages = set()
        self._recognition_terminal = ''
        self._failed_stages = set()
        self._reset_progress_presentation()
        self._stage_total = 11
        self._current_media_index = 1
        self._current_media_total = max(1, len(self.media_paths))
        self._progress_timer = QTimer(self)
        # A precise 200 ms heartbeat makes the displayed integer second advance
        # reliably once per second even when the UI thread briefly handles a burst
        # of log events. A coarse 1000 ms timer can visibly jump by two seconds.
        self._progress_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._update_progress_clock)
        return page

    def _adapt_progress_density(self):
        """Compact spacing on short pages instead of shrinking type."""
        root = getattr(self, 'progress_page_root', None)
        if root is None:
            return
        compact = ui_zoom.logical(root.height()) < 700
        if getattr(self, '_progress_compact', None) == compact:
            return
        self._progress_compact = compact
        root.layout().setContentsMargins(28, 10 if compact else 18, 28, 10 if compact else 14)
        root.layout().setSpacing(10 if compact else 14)
        self.progress_hero.layout().setSpacing(8 if compact else 12)
        for card in self.phase_cards:
            # Two text lines (16px title + 13px state) need ~60px; compact
            # trims padding, never clips the state line.
            card.setMinimumHeight(62 if compact else 70)
            card.layout().setContentsMargins(52, 8 if compact else 11, 14, 8 if compact else 11)
        self.current_stage_card.layout().setContentsMargins(20, 10 if compact else 14, 20, 10 if compact else 16)
        self.current_stage_card.layout().setSpacing(6 if compact else 8)
        self.stage_metrics.set_compact(compact)
        self.recognition_preview.set_max_rows(1 if compact else 4)

    def _progress_settings(self):
        from ..design.theme_manager import SETTINGS_APP, SETTINGS_ORG
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def _run_settings_snapshot(self) -> dict:
        """The settings this run uses (2026-10-15): the saved settings, with each
        text-AI step that has no key turned off, so it runs on the local rules.
        The saved switches stay as they are; filling in a key turns AI back on."""
        settings = json.loads(json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False))
        switches = settings.setdefault("switches", {})
        for role in getattr(self, "_text_ai_local_roles", ()) or ():
            switches[{"polish": "enable_ai_polish", "group": "use_ai_grouping"}[role]] = False
        from ..providers.ai_config_state import trace_configuration
        trace_configuration('task_snapshot', settings)
        return settings

    def _text_ai_local_note(self) -> str:
        roles = set(getattr(self, "_text_ai_local_roles", ()) or ())
        if roles == {"polish", "group"}:
            return tr("没填 API Key：这次用本地规则断句、不做 AI 校对，字幕照常生成")
        if roles == {"group"}:
            return tr("AI 断句没填 API Key：这次用本地规则断句")
        if roles == {"polish"}:
            return tr("AI 校对没填 API Key：这次不做 AI 校对，字幕照常生成")
        return ""

    def _confirm_run_disclosure(self) -> bool:
        """State what this run will use; ask once before audio goes to a cloud service (2026-10-13).

        Every run logs engine, speaker source, timestamp source, uploads and
        cost basis. A run that uploads audio asks once per provider/model/host
        (the answer is remembered locally); text-only AI is never interrupted.
        """
        import hashlib
        from ..recognition.recognition_choices import disclosure_text, run_disclosure
        try:
            settings = self._run_settings_snapshot()
            settings.setdefault("models", {}).update(self._asr_values())
            text = disclosure_text(settings)
            info = run_disclosure(settings)
        except Exception as exc:
            self._append_console_line(f"[本次识别] 无法生成使用摘要：{exc}")
            return True
        self._append_console_line("[本次识别] " + text.replace("\n", "；"))
        audio_uploads = [item for item in info["uploads"] if item.startswith("音频")]
        if not audio_uploads or os.environ.get("TWOBYTEASR_TEST_ROOT"):
            return True
        signature = hashlib.sha256("|".join([info["engine"], *audio_uploads]).encode("utf-8")).hexdigest()[:24]
        store = self._progress_settings()
        if store.value(f"cloud_upload_ack/{signature}", False, type=bool):
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("本次识别会上传音频"))
        box.setText(tr("开始前请确认本次识别实际会使用的服务："))
        box.setInformativeText(text)
        remember = QCheckBox(tr("同样的服务与设置以后不再询问"))
        remember.setChecked(True)
        box.setCheckBox(remember)
        start = box.addButton(tr("开始识别"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("取消"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not start:
            self._append_console_line("[本次识别] 已取消：未上传任何音频。")
            return False
        if remember.isChecked():
            store.setValue(f"cloud_upload_ack/{signature}", True)
        return True

    def _run_limit_lines(self) -> list:
        """What this run cannot do, one sentence each (2026-10-21); [] when nothing.

        A text-AI step without its key (``_text_ai_local_roles``, set by the
        run-start save) and a run without measured word times (the primary's
        sentence times only).
        """
        roles = frozenset(getattr(self, "_text_ai_local_roles", ()) or ())
        lines = []
        key_line = {
            frozenset({"polish", "group"}): "没填 API Key，无法启用 AI 断句和 AI 校对：这次用本地规则断句，不做 AI 校对。",
            frozenset({"group"}): "全文断句模型没填 API Key，无法启用 AI 断句：这次用本地规则断句。",
            frozenset({"polish"}): "字幕校对模型没填 API Key，无法启用 AI 校对：这次不做 AI 校对。",
        }.get(roles)
        if key_line:
            lines.append(tr(key_line))
        try:
            from ..recognition.recognition_choices import run_disclosure
            settings = self._run_settings_snapshot()
            settings.setdefault("models", {}).update(self._asr_values())
            word_timing = bool(run_disclosure(settings).get("word_timing", True))
        except Exception:  # noqa: BLE001 - an unreadable plan is reported by the run itself
            word_timing = True
        if not word_timing:
            lines.append(tr("只有主力转写，没有字级时间戳：字幕时间只能按整句估算，长句切开处的时间可能不准。"
                            "要更准，请在首页「字幕时间轴」选 FireRed 或 Qwen3 对齐模型。"))
        return lines

    def _confirm_run_limits(self) -> bool:
        """Ask “确定要继续吗” when this run cannot use AI 断句 / 校对 or word times (2026-10-21).

        User: many people do not fill in a key, and some setups have only the
        primary transcript without word-level times; say so before the run
        starts. 继续生成 starts, 去填 API Key opens the AI settings, 取消 stops;
        the same situation can be remembered. Logged, but not asked, under a
        test root (offscreen tests would block on the box).
        """
        if (getattr(self, "_studio_recognition_context", None) or {}).get("recognition_purpose") == "analysis":
            return True
        lines = self._run_limit_lines()
        if not lines:
            return True
        for line in lines:
            self._append_console_line("[开始前提醒] " + line)
        if os.environ.get("TWOBYTEASR_TEST_ROOT"):
            return True
        import hashlib
        roles = sorted(getattr(self, "_text_ai_local_roles", ()) or ())
        word_line = len(lines) > (1 if roles else 0)
        signature = hashlib.sha256(f"{','.join(roles)}|{int(word_line)}".encode("utf-8")).hexdigest()[:16]
        store = self._progress_settings()
        if store.value(f"run_limits_ack/{signature}", False, type=bool):
            return True
        box = QMessageBox(self)
        box.setObjectName("runLimitsBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("开始前请确认"))
        box.setText(tr("这次生成字幕有以下限制："))
        box.setInformativeText("\n\n".join("• " + line for line in lines)
                               + "\n\n" + tr("字幕照常生成，之后可以在工作台修改。确定要继续吗？"))
        remember = QCheckBox(tr("同样的情况以后不再提醒"))
        box.setCheckBox(remember)
        go = box.addButton(tr("继续生成"), QMessageBox.ButtonRole.AcceptRole)
        fill = box.addButton(tr("去填 API Key"), QMessageBox.ButtonRole.ActionRole) if roles else None
        box.addButton(tr("取消"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(go)
        grid = box.layout()
        if isinstance(grid, QGridLayout):   # two sentences read better on wider lines
            grid.addItem(QSpacerItem(520, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding),
                         grid.rowCount(), 0, 1, grid.columnCount())
        box.exec()
        clicked = box.clickedButton()
        if clicked is go:
            if remember.isChecked():
                store.setValue(f"run_limits_ack/{signature}", True)
            return True
        if fill is not None and clicked is fill:
            QTimer.singleShot(0, self, self._open_ai_settings_dialog)
        self._run_block_reason = "开始前提醒：已取消，没有开始识别。"
        self._append_console_line("[开始前提醒] 已取消，没有开始识别。")
        return False

    def _restore_progress_layout(self):
        settings = self._progress_settings()
        sizes = settings.value("progress/splitterSizes")
        try:
            sizes = [int(value) for value in (sizes or ())]
        except (TypeError, ValueError):
            sizes = []
        if len(sizes) == 2 and all(value > 0 for value in sizes):
            self.progress_splitter.setSizes(sizes)
        expanded = str(settings.value("progress/logExpanded", "false")).lower() in {"1", "true"}
        self.expand_console_button.setChecked(expanded)
        self._set_console_expanded(expanded, remember=False)

    def _remember_progress_layout(self, *_args):
        sizes = self.progress_splitter.sizes()
        if len(sizes) == 2 and all(sizes):
            self._progress_settings().setValue("progress/splitterSizes", sizes)

    def _set_console_expanded(self, expanded, remember=True):
        expanded = bool(expanded)
        self.progress_left_column.setVisible(not expanded)
        bind_text(self.expand_console_button, '还原布局' if expanded else '放大日志')
        install_themed_icon(self.expand_console_button, "fa5s.compress-alt" if expanded else "fa5s.expand-alt", "secondary")
        if remember:
            self._progress_settings().setValue("progress/logExpanded", expanded)

    def _copy_console_log(self):
        lines = getattr(self, '_console_lines', None)
        QApplication.clipboard().setText('\n'.join(lines) if lines else self.console_log.toPlainText())

    def _restyle_progress_page(self):
        root = getattr(self, 'progress_page_root', None)
        if root is not None:
            root.setStyleSheet(progress_page_qss(_active_theme_definition()))
        lines = getattr(self, '_console_lines', None)
        levels = getattr(self, '_console_levels', None)
        if lines and hasattr(self, 'console_log'):
            levels = levels if levels and len(levels) == len(lines) else ['stdout'] * len(lines)
            theme = _active_theme_definition()
            self._console_fragments = [log_line_html(line, level, theme) for line, level in zip(lines, levels)]
            set_log_html_keep_left(self.console_log, ''.join(self._console_fragments[-800:]))
            bar = self.console_log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _show_console_context_menu(self, position):
        menu = QMenu(self.console_log)
        menu.setObjectName("consoleContextMenu")
        copy_action = menu.addAction(tr("复制"))
        copy_action.setShortcut("Ctrl+C")
        copy_action.setEnabled(self.console_log.textCursor().hasSelection())
        copy_all_action = menu.addAction(tr("复制全部"))
        select_all_action = menu.addAction(tr("全选"))
        select_all_action.setShortcut("Ctrl+A")
        selected = menu.exec(self.console_log.mapToGlobal(position))
        if selected is copy_action:
            self.console_log.copy()
        elif selected is copy_all_action:
            self._copy_console_log()
        elif selected is select_all_action:
            self.console_log.selectAll()

    def _result_page(self):
        from .completion_widgets import (CompletionContent, CompletionActionCard, CompletionActionGrid,
                                         CompletionMoreButton, CompletionTaskSelector, CompletionFilename, CompletionTitle,
                                         CompletionAccordionHeader, CompletionInfoPanel, COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_SMALL,
                                         COMPLETION_MAX_WIDTH, COMPLETION_TOP_GAP, CompletionSecondaryButton)
        scroll = QScrollArea()
        scroll.setObjectName('completionScroll')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        scroll.setWidget(page)
        outer = QHBoxLayout(page)
        outer.setContentsMargins(28, COMPLETION_TOP_GAP, 28, COMPLETION_TOP_GAP)
        outer.addStretch(1)
        self.result_content = CompletionContent()
        self.result_content.setMaximumWidth(COMPLETION_MAX_WIDTH)
        self.result_content.setMinimumWidth(0)
        self.result_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self.result_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        outer.addWidget(self.result_content, 1000)
        outer.setAlignment(self.result_content, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)
        summary_card = QFrame()
        summary_card.setObjectName('resultSummaryCard')
        summary_card.setProperty('completionRadius', COMPLETION_RADIUS_MAIN)
        summary_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.result_summary_card = summary_card
        summary_layout = QHBoxLayout(summary_card)
        # 2026-10-09 (M14, user): a shorter two-sided summary — result and
        # file on the left; cue count, time and the review entry on the right.
        summary_layout.setContentsMargins(22, 16, 22, 16)
        summary_layout.setSpacing(16)
        self.result_icon = QLabel()
        self.result_icon.setFixedSize(40, 40)
        self.result_icon.setStyleSheet('padding:0; margin:0; border:none; background:transparent;')
        self.result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.result_icon, 0, Qt.AlignmentFlag.AlignTop)
        summary_copy = QVBoxLayout()
        summary_copy.setSpacing(4)
        self.result_title = CompletionTitle('字幕已生成')
        self.result_title.qualifier_clicked.connect(
            lambda: self._completion_action('repolish', self._open_glossary_proofread))
        summary_copy.addWidget(self.result_title)
        self.result_summary = QLabel('')
        self.result_summary.setWordWrap(True)
        self.result_summary.setObjectName('resultSummaryStats')
        summary_copy.addWidget(self.result_summary)
        self.result_single_filename = CompletionFilename('')
        self.result_single_filename.setObjectName('resultSummaryFile')
        self.result_single_filename.setMinimumWidth(0)
        summary_copy.addWidget(self.result_single_filename)
        self.result_task_selector = CompletionTaskSelector()
        self.result_task_selector.setProperty("completionRole", "secondary")
        self.result_task_selector.setProperty("completionRadius", COMPLETION_RADIUS_SMALL)
        self.result_task_selector.setMinimumWidth(0)
        self.result_task_selector.setMinimumContentsLength(12)
        self.result_task_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.result_task_selector.currentIndexChanged.connect(self._select_completion_task)
        summary_copy.addWidget(self.result_task_selector)
        # The full sentence stays in result_summary (history/audits read it);
        # with a result the page shows this short qualifier plus the stats.
        self.result_summary_meta = QLabel('')
        self.result_summary_meta.setObjectName('resultSummaryMeta')
        self.result_summary_meta.setWordWrap(True)
        self.result_summary_meta.hide()
        summary_copy.addWidget(self.result_summary_meta)
        self.result_review_summary = QLabel('')
        self.result_review_summary.setWordWrap(True)
        self.result_review_summary.hide()
        summary_copy.addWidget(self.result_review_summary)
        self.result_review_status = QToolButton()
        self.result_review_status.setObjectName("completionReviewChip")
        self.result_review_status.setProperty("completionRole", "chip")
        self.result_review_status.setProperty("completionRadius", COMPLETION_RADIUS_SMALL)
        self.result_review_status.setText('有待检查项')
        self.result_review_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.result_review_status.setMinimumHeight(32)
        self.result_review_status.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        install_themed_icon(self.result_review_status, 'fa5s.flag', 'warning')
        self.result_review_status.clicked.connect(self._show_completion_review_details)
        summary_notices = QHBoxLayout()
        summary_notices.setContentsMargins(0, 4, 0, 0)
        summary_notices.setSpacing(10)
        # Retry belongs beside the unfinished notice it resolves (2026-10-07);
        # it only appears for retryable outcomes with known run options.
        self.retry_failed_button = AnimatedButton('重试失败项')
        self.retry_failed_button.setObjectName('completionRetry')
        self.retry_failed_button.setProperty('completionRole', 'chip')
        self.retry_failed_button.setProperty('completionRadius', COMPLETION_RADIUS_SMALL)
        self.retry_failed_button.setMinimumHeight(32)
        install_themed_icon(self.retry_failed_button, 'fa5s.redo', 'accent')
        self.retry_failed_button.clicked.connect(self._retry_failed_items)
        self.retry_failed_button.hide()
        summary_notices.addWidget(self.retry_failed_button, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.result_exception_summary = QLabel('')
        self.result_exception_summary.setObjectName('resultSummaryNote')
        self.result_exception_summary.setWordWrap(True)
        self.result_exception_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_notices.addWidget(self.result_exception_summary, 1)
        summary_notices.addStretch(1)
        summary_copy.addLayout(summary_notices)
        # 2026-10-23 (user): the likely cause of a failure or a poor result,
        # from the local check of the report; opens 排查原因 (all findings,
        # what to do, and an optional AI analysis).
        from .completion_widgets import CompletionDiagnosisHint
        self.result_diagnosis_hint = CompletionDiagnosisHint()
        self.result_diagnosis_hint.clicked.connect(
            lambda: self._completion_action('diagnose', self._open_completion_diagnosis))
        summary_copy.addWidget(self.result_diagnosis_hint)
        self.result_task_summary = QLabel('')
        self.result_task_summary.setWordWrap(True)
        summary_copy.addWidget(self.result_task_summary)
        summary_layout.addLayout(summary_copy, 1)
        self.result_stats = QWidget()
        self.result_stats.setObjectName('resultStats')
        stats_layout = QHBoxLayout(self.result_stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(28)
        self.result_stat_values = {}
        self.result_stat_captions = {}
        for key, caption in (('count', '条字幕'), ('elapsed', '用时')):
            block = QVBoxLayout()
            block.setSpacing(0)
            value = QLabel('—')
            value.setObjectName('resultStatValue')
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            label = QLabel(caption)
            label.setObjectName('resultStatCaption')
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            block.addWidget(value)
            block.addWidget(label)
            stats_layout.addLayout(block)
            self.result_stat_values[key] = value
            self.result_stat_captions[key] = label
        stats_layout.addWidget(self.result_review_status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.result_stats.hide()
        summary_layout.addWidget(self.result_stats, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(summary_card)
        self.result_files_toggle = CompletionAccordionHeader('任务与输出')
        self.result_log_toggle = CompletionAccordionHeader('运行日志')
        self.result_files = QTextEdit()
        self.result_files.setObjectName('resultFiles')
        self.result_files.setProperty('completionRadius', COMPLETION_RADIUS_MAIN)
        self.result_files.setReadOnly(True)
        self.result_files_panel = CompletionInfoPanel(self.result_files_toggle, self.result_files)
        layout.addWidget(self.result_files_panel)
        self.result_console = QTextEdit()
        self.result_console.setObjectName('resultConsole')
        self.result_console.setProperty('completionRadius', COMPLETION_RADIUS_MAIN)
        self.result_console.setReadOnly(True)
        self.result_console.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.result_log_panel = CompletionInfoPanel(self.result_log_toggle, self.result_console)
        self.result_log_panel.mode_changed.connect(lambda: self._toggle_completion_log(self.result_log_panel.mode == 'full'))
        layout.addWidget(self.result_log_panel)
        self.result_details_toggle = self.result_log_toggle
        self.result_detail_row = self.result_console
        self.export_result_button = CompletionActionCard('导出字幕', '保存 SRT、ASS、TXT 等字幕文件', 'fa5s.file-export', hue='primary')
        self.open_studio_result_button = CompletionActionCard('打开字幕工作台', '检查字幕、调整时间轴与字幕样式', 'fa5s.closed-captioning', hue='brand')
        self.result_return_button = CompletionActionCard('完成并返回主菜单', '确认结果已保存，返回主菜单', 'fa5s.home', hue='finish')
        self.export_result_button.clicked.connect(lambda: self._completion_action('export', self._export_completion_result))
        self.open_studio_result_button.clicked.connect(lambda: self._completion_action('studio', self._open_studio_from_result))
        self.result_return_button.clicked.connect(lambda: self._completion_action('return', self._return_to_main_menu))
        self.result_action_grid = CompletionActionGrid((self.export_result_button, self.open_studio_result_button, self.result_return_button))
        layout.addWidget(self.result_action_grid)
        # The delivered subtitles themselves, below the actions (2026-10-07).
        from .completion_widgets import CompletionPreview
        self.result_preview = CompletionPreview()
        layout.addWidget(self.result_preview)
        self.open_priority_review_button = CompletionSecondaryButton('开始优先审核')
        self.open_priority_review_button.setObjectName('softAction')
        install_themed_icon(self.open_priority_review_button, 'fa5s.flag', 'secondary')
        self.open_priority_review_button.clicked.connect(lambda: self._completion_action('review', self._open_priority_review_from_result))
        self.open_priority_review_button.hide()
        # 2026-10-09 (M14, user): a proofreading workspace on the result
        # itself — choose libraries, add terms, review and apply suggestions.
        self.repolish_current_glossary_button = CompletionSecondaryButton('AI 词库校对…')
        self.repolish_current_glossary_button.setObjectName('softAction')
        install_themed_icon(self.repolish_current_glossary_button, 'fa5s.book', 'secondary')
        bind_text(self.repolish_current_glossary_button, '整理词库、对照原文与建议，勾选后才写回字幕；写回后可在字幕工作台撤销', property='toolTip')
        self.repolish_current_glossary_button.clicked.connect(lambda: self._completion_action('repolish', self._open_glossary_proofread))
        self.result_more_button = CompletionMoreButton()
        self.result_more_button.setText('更多操作')
        self.result_more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.result_more_menu = QMenu(self.result_more_button)
        self.result_more_menu.setProperty("completionRole", "secondary")
        self.result_more_menu.setProperty("completionRadius", COMPLETION_RADIUS_SMALL)
        self.diagnose_result_action = self.result_more_menu.addAction(
            '排查原因…', lambda: self._completion_action('diagnose', self._open_completion_diagnosis))
        self.diagnose_result_action.setEnabled(False)
        self.result_more_menu.addAction('打开报告目录', self._open_completion_report_directory)
        self.open_subtitle_result_button = self.result_more_menu.addAction('打开字幕目录', self._open_subtitle_dir)
        self.open_subtitle_result_button.setEnabled(False)
        self.recover_recognition_button = self.result_more_menu.addAction('恢复已有识别结果…', self._recover_recognition_output)
        self.result_more_menu.addAction('复制输出路径', self._copy_completion_output_paths)
        self.result_more_menu.addAction('复制完整运行日志', self._copy_completion_log)
        self.retry_term_action = self.result_more_menu.addAction('重试联网核验', lambda: self._retry_completion_stage('terminology'))
        self.retry_term_action.setVisible(False)
        self.result_more_menu.addSeparator()
        self.result_more_menu.addAction('AI 模型与密钥…', self._open_ai_provider_config)
        self.result_more_button.setMenu(self.result_more_menu)
        self.result_action_grid.set_secondary_actions((self.open_priority_review_button,
            self.repolish_current_glossary_button, self.result_more_button))
        self.result_secondary_bar = self.result_action_grid
        self.result_secondary_layout = self.result_action_grid.grid
        self.result_content.bind_actions(layout,
            (self.export_result_button, self.open_studio_result_button, self.result_return_button),
            viewport=scroll.viewport(), summary_layout=summary_layout, summary_copy=summary_copy, page_layout=outer,
            panels=(self.result_files_panel, self.result_log_panel), action_grid=self.result_action_grid)
        return scroll

    def _open_completion_from_history(self, record):
        if getattr(self, '_run_in_progress', False) or getattr(self, '_completion_retry_in_progress', False):
            QMessageBox.information(self, tr('任务正在运行'), tr('本批识别仍在运行。结束后可打开历史识别结果。'))
            return
        from ..recognition.service import MediaResult, QueueResult
        payload = record.payload
        result = payload.get('result') or {}
        outputs = result.get('outputs') or {}
        item = MediaResult(media_path=str((payload.get('media') or {}).get('path') or record.media_name),
            status=str(payload.get('status') or 'unknown'), project_path=str(outputs.get('project') or ''),
            srt_path=str(outputs.get('srt') or ''), report_json_path=str(record.path),
            report_text_path=str(record.path.with_suffix('.txt')),
            elapsed_seconds=float(result.get('elapsed_seconds') or 0))
        self._last_run_options = None
        self._handle_result(QueueResult((item,), item.elapsed_seconds))
        events = payload.get('events') or []
        self._completion_log_lines = tuple(json.dumps(row, ensure_ascii=False) for row in events)
        self._completion_log_fragments = tuple(self._completion_plain_log_fragment(line) for line in self._completion_log_lines)
        self._completion_log_loaded = 0
        self._completion_log_generation += 1
        self.result_console.clear()
        bind_text(self.result_log_toggle, '运行日志 · 本次报告事件')

    def _open_history_diagnosis(self, record):
        """排查原因 of a recognition history record (2026-10-23); task-only actions are left out."""
        from .run_diagnosis_dialog import TASK_ACTIONS, open_run_diagnosis
        from ..recognition.diagnosis_catalog import ACTION_LABELS
        payload = getattr(record, 'payload', None)
        if not isinstance(payload, dict):
            return
        error = str(((payload.get('result') or {}) if isinstance(payload.get('result'), dict) else {}).get('error') or '')
        open_run_diagnosis(self, payload, item_error=error, task_name=str(getattr(record, 'media_name', '') or ''),
                           available_actions=set(ACTION_LABELS) - TASK_ACTIONS)

    def _show_completion_review_details(self):
        self.result_files_panel.set_mode('full')
        self.result_files.setFocus()

    @staticmethod
    def _completion_task_key(item):
        path = str(getattr(item, 'report_json_path', '') or getattr(item, 'project_path', '') or item.media_path)
        stream = int(getattr(item, 'audio_stream', -1))
        # One picked audio track of a multi-track file is a result of its own.
        return str(getattr(item, 'job_id', '') or '') + ':' + path + (f'#a{stream}' if stream >= 0 else '')

    def _select_completion_task(self, index):
        tasks = getattr(self, '_completion_tasks', [])
        task = tasks[index] if 0 <= index < len(tasks) else None
        self.result_task_selector.setVisible(len(tasks) > 1)
        self.result_single_filename.setVisible(len(tasks) == 1)
        self._last_studio_project = task[0].project_path if task and task[1] else ''
        self._last_result_ref_json = getattr(task[0], 'result_ref_json', '') if task and task[1] else ''
        self._last_recognition_report = task[0].report_json_path if task else ''
        evidence = self._completion_task_evidence.get(self._completion_task_key(task[0]), {}) if task else {}
        selected_outcome = evidence.get('outcome')
        available = bool(task and task[1] and selected_outcome and selected_outcome.result_usable)
        for button in (self.export_result_button, self.open_studio_result_button):
            button.setEnabled(available)
        self.repolish_current_glossary_button.setVisible(True)
        self.repolish_current_glossary_button.setEnabled(available)
        self.result_return_button.setEnabled(True)
        if not available:
            self._last_studio_project = ''
        if not task:
            self._last_srt_dir = ''
            self.open_subtitle_result_button.setEnabled(False)
            self.open_priority_review_button.show()
            self.open_priority_review_button.setEnabled(False)
            self.result_review_status.hide()
            self.result_stats.hide()
            self.result_summary_meta.hide()
            self.result_summary.show()
            self.result_single_filename.clear()
            self.result_task_selector.setToolTip('')
            bind_text(self.result_task_summary, '')
            self.result_task_summary.hide()
            self.result_diagnosis_hint.set_finding(None)
            self.diagnose_result_action.setEnabled(False)
            self._refresh_completion_summaries()
            return
        item, project = task
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        from ..recognition.processing_recovery import refresh_completion_evidence
        refresh_completion_evidence(project,evidence)
        outcome = evidence.get('outcome')
        self._last_srt_dir = str(Path(item.srt_path).parent) if item.srt_path else ''
        self.open_subtitle_result_button.setEnabled(bool(self._last_srt_dir))
        self._completion_output_paths = list(evidence.get('output_paths', ()))
        if evidence.get('display_payload') is not None:
            detail_lines = list(outcome.localized_detail_lines(getattr(self, '_ui_language', 'zh')))
            detail_lines.extend(outcome.problems + outcome.review_notes)
            if 'path_entries' in evidence:
                detail_lines.extend(translate(label, getattr(self, '_ui_language', 'zh')) + '：' + str(target)
                                    for label, target in evidence['path_entries'])
            else:
                detail_lines.extend(evidence.get('path_lines', ()))
            content = '<b>' + html.escape(translate(outcome.status_label, getattr(self, '_ui_language', 'zh'))) + '</b><br>' + '<br>'.join(html.escape(line) for line in detail_lines)
            self.result_files.setHtml(content)
        else:
            self.result_files.setHtml(evidence.get('details_html', ''))
        filename = Path(item.media_path).name
        self.result_single_filename.set_full_name(filename)
        self.result_task_selector.setToolTip(filename)
        self.open_priority_review_button.show()
        self.open_priority_review_button.setEnabled(bool(available and outcome and outcome.has_review))
        self.result_review_status.setVisible(bool(outcome and outcome.has_review))
        if outcome:
            bind_text(self.result_title, outcome.title)
            # 2026-10-09 (M15, user): an unfinished AI check is a button to
            # AI proofreading, not only a status.
            if available and outcome.polish_status == 'partial' and ' · ' in outcome.title:
                self.result_title.set_qualifier_action(
                    tr('去 AI 校对 ›'),
                    tr('有 {count} 段文字的 AI 校对没有完成。点击打开 AI 词库校对，可用「AI 校对建议」补做；勾选后才写回。',
                       count=outcome.fallback_records) if outcome.fallback_records else
                    tr('部分字幕的 AI 校对没有完成。点击打开 AI 词库校对，可用「AI 校对建议」补做；勾选后才写回。'))
            else:
                self.result_title.set_qualifier_action('')
            elapsed = float(item.elapsed_seconds or outcome.elapsed_seconds)
            minutes, seconds = divmod(round(elapsed), 60)
            duration = f'{minutes}:{seconds:02d}' if minutes else f'{seconds}s'
            qualified = ' · ' in outcome.title
            polish = '' if (qualified and outcome.polish_status == 'partial') else translate(
                'AI文字检查已执行' if outcome.polish_status == 'completed' else outcome.polish_label,
                getattr(self, '_ui_language', 'zh'))
            bind_text(self.result_summary, '{count} 条字幕 · 采纳 {accepted} 处文字修改 · 本文件耗时 {elapsed}{polish}',
                      accepted=outcome.accepted_edits, count=outcome.final_cues, elapsed=duration,
                      polish=(' · ' + polish) if polish else '')
            self.result_stat_values['count'].setText(str(outcome.final_cues))
            self.result_stat_values['elapsed'].setText(duration)
            bind_text(self.result_summary_meta, '采纳 {accepted} 处文字修改{polish}', accepted=outcome.accepted_edits,
                      polish=(' · ' + polish) if polish else '')
            if len(tasks) > 1:
                batch = translate('整批：完成 {success} 个 · 部分完成 {partial} 个 · 失败 {failure} 个 · 取消 {cancel} 个 · 跳过 {skipped} 个 · 待确认 {unknown} 个 · 耗时 {elapsed} 秒', getattr(self, '_ui_language', 'zh')).format(**getattr(self, '_completion_batch_counts', {}))
                self.result_summary.setText(self.result_summary.text() + '\n' + batch)
                self.result_summary_meta.setText(self.result_summary_meta.text() + '\n' + batch)
            self.result_summary.hide()
            self.result_summary_meta.show()
            self.result_stats.show()
            bind_text(self.result_review_status, '有待检查项 · {count} 项', count=outcome.review_issue_count)
            self.result_review_status.setToolTip('\n'.join(outcome.problems + outcome.review_notes))
            bind_text(self.result_review_summary, '待检查问题 {count} 项', count=outcome.review_issue_count)
            self.result_review_summary.hide()
            messages = []
            if outcome.polish_status == 'partial' and ' · ' not in outcome.title:
                messages.append(translate('部分AI文字校对未完成', getattr(self, '_ui_language', 'zh')))
            if outcome.search_status in {'unsupported', 'not_configured', 'failed', 'partial', 'timeout', 'insufficient_evidence'}:
                messages.append(translate(outcome.search_label, getattr(self, '_ui_language', 'zh')))
            messages.extend(outcome.core_errors)
            if item.error and outcome.core_status in {'failed', 'cancelled'}:
                messages.append(str(item.error)[:220])
            self.result_exception_summary.setProperty('i18nText', None)
            self.result_exception_summary.setText(' · '.join(dict.fromkeys(messages)))
            self.result_exception_summary.setVisible(bool(messages))
            theme = _active_theme_definition()
            # Usable result → success mark; the unfinished part is the title's
            # warning pill, so both facts are stated without contradiction.
            usable = bool(outcome.result_usable) and outcome.core_status not in {'failed', 'cancelled', 'unknown'}
            if outcome.core_status == 'failed':
                color, icon, tone = theme.danger, 'fa5s.exclamation-circle', 'danger'
            elif outcome.core_status == 'cancelled':
                color, icon, tone = theme.text_muted, 'fa5s.stop-circle', 'muted'
            elif outcome.core_status == 'unknown' or not usable:
                color, icon, tone = theme.warning, 'fa5s.question-circle', 'warning'
            else:
                color, icon, tone = theme.success, 'fa5s.check-circle', 'warning' if outcome.core_status == 'partial' else 'success'
            self.result_title.set_tone(tone)
            self.result_icon.setPixmap(_icon(icon, color).pixmap(QSize(32, 32)))
            # Card wash follows the result itself (usable → success); the
            # unfinished part stays in the title pill and the review chip.
            outcome_tone = 'success' if usable and outcome.core_status not in {'unknown'} else tone
            self.result_summary_card.setProperty('outcome', outcome_tone)
            self.result_summary_card.style().unpolish(self.result_summary_card)
            self.result_summary_card.style().polish(self.result_summary_card)
        project_error = evidence.get('project_error', '')
        self.result_task_summary.setProperty('i18nTemplate', None)
        self.result_task_summary.setProperty('i18nArguments', {})
        self.result_task_summary.setToolTip(project_error)
        if project_error:
            bind_text(self.result_task_summary, '工程无法载入：{reason}\n请通过“更多操作 → 恢复已有识别结果”恢复副本。', reason=project_error[:200])
        else:
            bind_text(self.result_task_summary, '')
        self.result_task_summary.setVisible(bool(project_error))
        recovery=evidence.get('stage_recovery') or {}
        retryable = bool(recovery.get('failed_tasks') or recovery.get('pending_proposals') or outcome and (outcome.polish_retryable or outcome.search_retryable or outcome.core_status == 'failed'))
        self.retry_failed_button.setVisible(retryable)
        optional_retry=bool(recovery.get('failed_tasks') or recovery.get('pending_proposals') or outcome and (outcome.polish_retryable or outcome.search_retryable))
        self.retry_failed_button.setEnabled(bool(retryable and (available or not optional_retry)))
        if recovery.get('failed_tasks'):
            bind_text(self.retry_failed_button,'重试失败任务 {count} 项',count=recovery['failed_tasks'])
            bind_text(self.result_task_summary,'失败任务 {tasks} 项 · 影响当前字幕 {cues} 条 · 可执行重试 {retryable} 项；人工检查项另计。',
                tasks=recovery['failed_tasks'],cues=recovery['affected_cues'],retryable=recovery['retryable_tasks'])
            self.result_task_summary.show()
        elif recovery.get('pending_proposals'):
            bind_text(self.retry_failed_button,'查看重试校对建议')
        elif outcome and outcome.polish_retryable:
            bind_text(self.retry_failed_button, '重试未完成 AI 校对')
        elif outcome and outcome.search_retryable:
            bind_text(self.retry_failed_button, '重试联网核验')
        else:
            bind_text(self.retry_failed_button, '重试失败项')
        self.retry_term_action.setVisible(bool(outcome and outcome.search_retryable and getattr(self, '_last_run_options', None)))
        diagnosis = self._completion_diagnosis(item, evidence)
        self.diagnose_result_action.setEnabled(diagnosis is not None)
        self.result_diagnosis_hint.set_finding(
            diagnosis.headline() if diagnosis is not None else None,
            failed=bool(outcome and outcome.core_status == 'failed'),
            others=[finding for finding in (diagnosis.findings if diagnosis is not None else ()) if finding.severity != 'tip'])
        self._refresh_completion_summaries()

    def _completion_diagnosis(self, item, evidence):
        """The local check of one task's report, computed once per task (2026-10-23)."""
        if 'diagnosis' in evidence:
            return evidence['diagnosis']
        report = evidence.get('display_payload')
        if isinstance(report, dict) and not report.get('events') and item.status in {'failed', 'cancelled'}:
            # A failed task's result carries no report path; its report has
            # the steps and events that explain the failure.
            from .run_diagnosis_dialog import locate_task_report
            located = locate_task_report(item.media_path, str(getattr(item, 'job_id', '') or ''))
            if located is not None:
                report = located
        evidence['diagnosis_report'] = report
        diagnosis = None
        if isinstance(report, dict):
            from ..recognition.run_diagnosis import DiagnosisInput, diagnose_run
            try:
                diagnosis = diagnose_run(DiagnosisInput(report=report, item_error=str(getattr(item, 'error', '') or ''),
                                                        ai_ready=self._text_ai_ready()))
            except Exception as exc:  # the page must still show the result
                print(f"[diagnosis] local check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        evidence['diagnosis'] = diagnosis
        return diagnosis

    def _completion_notification_with_cause(self, result, outcomes):
        """The end-of-run note, plus the likely cause of the first failed task (2026-10-23)."""
        title, message, icon, details = _completion_notification_spec(result, outcomes)
        for item, _project in getattr(self, '_completion_tasks', ()):
            if item.status != 'failed':
                continue
            evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
            diagnosis = self._completion_diagnosis(item, evidence)
            headline = diagnosis.headline() if diagnosis is not None else None
            if headline is not None:
                cause = tr('可能原因：{title}（结果页的「查看原因与解决办法」有详细说明）', title=tr(headline.issue.title))
                details = f'{details}\n{cause}' if details else str(cause)
            break
        return title, message, icon, details

    def _text_ai_ready(self):
        """Has the 字幕校对 text AI a key (no request); None when unknown."""
        try:
            from ..providers.llm_config import text_ai_key_missing
            return not text_ai_key_missing(self.legacy.RUNTIME_SETTINGS, 'polish')
        except Exception:
            return None

    def _open_completion_diagnosis(self):
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks):
            return
        item, project = tasks[index]
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        self._completion_diagnosis(item, evidence)
        report = evidence.get('diagnosis_report')
        if not isinstance(report, dict):
            return
        from .run_diagnosis_dialog import TASK_ACTIONS, open_run_diagnosis
        from ..recognition.diagnosis_catalog import ACTION_LABELS
        outcome = evidence.get('outcome')
        available = set(ACTION_LABELS) - TASK_ACTIONS
        if project is not None and outcome is not None and outcome.result_usable:
            available |= {'studio', 'glossary_proofread'}
        if getattr(self, '_last_failed_items', None) and getattr(self, '_last_run_options', None):
            available.add('retry')
        if self._cloud_gap_resplit(item):
            available.add('mosi_resplit')
        if outcome is not None and not outcome.result_usable:
            available.add('recover')
        open_run_diagnosis(self, report, item_error=str(getattr(item, 'error', '') or ''),
                           task_name=Path(item.media_path).name, available_actions=available)

    def _refresh_completion_summaries(self):
        from .completion_summary import completion_summary
        tasks = getattr(self, '_completion_tasks', ())
        index = self.result_task_selector.currentIndex()
        if not tasks or not 0 <= index < len(tasks):
            self._completion_summary = None
            self.result_files_panel.set_summary_lines(())
            self.result_log_panel.set_summary_lines(())
            self._refresh_completion_preview()
            return
        self._refresh_completion_preview()
        # The preview re-reads a project Studio or proofreading saved.
        item, project = self._completion_tasks[index]
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        outcome = evidence.get('outcome')
        if outcome is None:
            return
        summary = completion_summary(evidence.get('display_payload'), outcome,
            media_path=item.media_path, project_path=item.project_path, project_loaded=project is not None,
            project_cues=len(project.cues) if project is not None else None,
            project_error=evidence.get('project_error', ''), language=getattr(self, '_ui_language', 'zh'))
        self._completion_summary = summary
        self.result_files_panel.set_summary_lines(summary.task_lines)
        self.result_log_panel.set_summary_lines(summary.log_lines)

    def _refresh_completion_preview(self):
        """First cues of the selected task's saved project (re-read after Studio edits)."""
        preview = getattr(self, 'result_preview', None)
        if preview is None:
            return
        tasks = getattr(self, '_completion_tasks', ())
        index = self.result_task_selector.currentIndex() if hasattr(self, 'result_task_selector') else -1
        if not tasks or not 0 <= index < len(tasks):
            preview.set_rows((), 0)
            return
        item, project = tasks[index]
        path = Path(item.project_path) if getattr(item, 'project_path', '') else None
        try:
            stamp = path.stat().st_mtime_ns if path is not None else None
        except OSError:
            stamp = None
        cache = getattr(self, '_completion_preview_stamps', {})
        if stamp is not None and project is not None and cache.get(str(path)) not in (None, stamp):
            from ..projects.studio_project import load_project
            try:
                project = load_project(path)
                self._completion_tasks[index] = (item, project)
            except (OSError, ValueError, TypeError):
                pass
        if stamp is not None:
            self._completion_preview_stamps = {**cache, str(path): stamp}
        if project is None:
            preview.set_rows((), 0)
            return
        from ..projects.speaker_names import display_speaker_name
        from ..studio.studio_cue_table import _speaker_color
        speakers = {speaker.id: speaker for speaker in project.speakers}
        cues = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms))
        rows = []
        for cue in cues:
            seconds, millis = divmod(max(0, int(cue.start_ms)), 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            stamp_text = (f'{hours}:{minutes:02d}:{seconds:02d}.{millis // 100}' if hours
                          else f'{minutes:02d}:{seconds:02d}.{millis // 100}')
            speaker = speakers.get(cue.speaker_id)
            name = display_speaker_name(project, speaker) if speaker is not None else cue.speaker_id
            rows.append((stamp_text, name, _speaker_color(project, cue.speaker_id).name(),
                         ' '.join(str(cue.text).split())))
        preview.set_rows(rows, len(cues))
        self._sync_completion_count(item, len(cues))

    def _sync_completion_count(self, item, project_cues):
        """The big count is the saved project's (what preview, proofreading
        and export read); a different recognition count is named, not hidden
        (2026-10-09, M15, user)."""
        values = getattr(self, 'result_stat_values', {})
        captions = getattr(self, 'result_stat_captions', {})
        if 'count' not in values:
            return
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        outcome = evidence.get('outcome')
        recognized = outcome.final_cues if outcome is not None else None
        values['count'].setText(str(project_cues))
        if recognized is not None and recognized != project_cues:
            bind_text(captions['count'], '条字幕 · 识别时 {count} 条', count=recognized)
            bind_text(captions['count'], '字幕工程在识别后被修改过（例如剪辑或删改字幕）。预览、AI 词库校对和导出都按工程当前的 {current} 条字幕。',
                      property='toolTip', current=project_cues)
        else:
            bind_text(captions['count'], '条字幕')
            captions['count'].setToolTip('')

    def _export_completion_result(self):
        from ..exports.completion_export import CompletionExportDialog
        tasks = getattr(self, "_completion_tasks", [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or tasks[index][1] is None:
            return
        item, project = tasks[index]
        # Export the currently saved project after Studio edits, never the
        # stale object loaded when the original completion event arrived.
        if item.project_path:
            from ..projects.studio_project import load_project
            try:
                project = load_project(item.project_path)
                self._completion_tasks[index] = (item, project)
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.warning(self, tr('无法导出字幕'), str(exc))
                return
        dialog = CompletionExportDialog(project, Path(item.media_path).stem, self,
                                        getattr(self, "_ui_language", "zh"))
        if dialog.exec() and dialog.artifacts:
            self._last_srt_dir = str(dialog.artifacts[0].path.parent)
            self.open_subtitle_result_button.setEnabled(True)
            self.result_files.append("\n".join(str(a.path) for a in dialog.artifacts))
            self._completion_output_paths.extend(str(a.path) for a in dialog.artifacts)

    def _completion_action(self, name, callback):
        """One activation across reentrant dialogs and rapid double-clicks."""
        if getattr(self, '_completion_action_busy', False):
            return
        now = time.monotonic()
        interval = max(.65, QApplication.doubleClickInterval() / 1000 + .05)
        last_actions = getattr(self, '_completion_action_last_by_name', {})
        if now - last_actions.get(name, -1.0) < interval:
            return
        self._completion_action_busy = True
        self._completion_action_last_by_name = {**last_actions, name: now}
        try:
            callback()
        finally:
            self._completion_action_busy = False

    def _open_studio_from_result(self):
        project = getattr(self, '_last_studio_project', '')
        self._open_completion_project(project, mode='edit', source='completion_edit')

    def _open_completion_project(self, project, *, mode, source, on_ready=None):
        if not project or getattr(self, '_completion_project_opening', False):
            return
        self._completion_project_opening = True
        reference = getattr(self, '_last_result_ref_json', '') if str(project) == str(getattr(self, '_last_studio_project', '')) else ''
        if reference:
            # Delivered and checked exactly in _handle_result. From here on it
            # is the user's project: proofreading and Studio edits are its
            # content, so only its identity is checked (2026-10-10).
            from ..recognition.recognition_result import working_reference
            reference = working_reference(reference)
        def ready(studio):
            self._completion_project_opening = False
            if on_ready is not None:
                on_ready(studio)
        try:
            kwargs = dict(mode=mode, source=source, on_ready=ready)
            if reference:
                kwargs['expected_result_ref'] = reference
            self.open_studio_project(project, **kwargs)
        finally:
            # Failed readiness has no success callback. Release when the
            # production readiness gate finishes or the open is rejected.
            QTimer.singleShot(100, self, self._release_completion_project_opening)

    def _release_completion_project_opening(self):
        if not getattr(self, '_completion_project_opening', False):
            return
        readiness = getattr(self.built_page("studio"), '_readiness', None)
        if readiness is not None and readiness.active:
            QTimer.singleShot(100, self, self._release_completion_project_opening)
        else:
            self._completion_project_opening = False

    def _open_glossary_proofread(self):
        """The selected task's saved project in the AI glossary workspace."""
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or tasks[index][1] is None or not tasks[index][0].project_path:
            return
        if not self._prepare_glossary_for_task():
            return
        item, project = tasks[index]
        outcome = self._completion_task_evidence.get(self._completion_task_key(item), {}).get('outcome')
        hint = ''
        if outcome is not None and outcome.polish_status == 'partial':
            hint = (tr('识别时有 {count} 段文字的 AI 校对没有完成。点「AI 校对建议」可按所选词库对全部字幕补做（会调用你配置的校对模型），勾选后才写回。',
                       count=outcome.fallback_records) if outcome.fallback_records else
                    tr('识别时部分字幕的 AI 校对没有完成。点「AI 校对建议」可按所选词库对全部字幕补做（会调用你配置的校对模型），勾选后才写回。'))
        from ..projects.studio_project import load_project
        try:
            fresh = load_project(item.project_path)
        except (OSError, ValueError, TypeError):
            fresh = project
        self._show_glossary_proofread(item.project_path, fresh, hint=hint)

    def _open_studio_glossary_proofread(self):
        """Review the editor's current document, including unsaved changes."""
        studio = self.studio_page
        if studio.project is None or not self._prepare_glossary_for_task():
            return
        studio.timeline._commit_inline_edit()
        if getattr(studio, '_canvas_editor', None) is not None:
            studio._commit_canvas_inline_edit(advance=False)
        studio.video.set_paused(True)
        self._show_glossary_proofread(studio.project_path, studio.project, studio=studio)

    def _show_glossary_proofread(self, path, project, *, hint='', studio=None):
        self._glossary_proofread_return = studio if studio is not None else self.pages.widget(2)
        page = getattr(self, 'glossary_proofread_page', None)
        opening = time.perf_counter()
        if page is None:
            from ..glossary.glossary_proofread import GlossaryProofreadPage
            page = GlossaryProofreadPage(self)
            _startup_mark("PROOFREAD_PAGE_BUILT", duration_ms=round((time.perf_counter() - opening) * 1000, 1))
            page.back_requested.connect(lambda: self._switch_page(self._glossary_proofread_return))
            page.applied.connect(self._glossary_proofread_applied)
            QApplication.instance().aboutToQuit.connect(page.shutdown)
            self.glossary_proofread_page = page
            self.pages.addWidget(page)
        bind_text(page.back_button, '返回字幕工作台' if studio is not None else '返回结果')
        self._switch_page(page)
        # Bind after the page transition; text review also tolerates the
        # asynchronous source-duration probe from native playback.
        switched = time.perf_counter()
        page.open_task(path, project, hint=hint, studio=studio)
        _startup_mark("PROOFREAD_TASK_OPENED", switch_ms=round((switched - opening) * 1000, 1),
                      open_task_ms=round((time.perf_counter() - switched) * 1000, 1))

    def _glossary_proofread_applied(self, path):
        """Applied changes reach the result page, its export and Studio."""
        from ..projects.studio_project import load_project
        tasks = getattr(self, '_completion_tasks', [])
        for index, (item, _project) in enumerate(list(tasks)):
            if str(item.project_path) == str(path):
                try:
                    tasks[index] = (item, load_project(path))
                except (OSError, ValueError, TypeError):
                    continue
        self._completion_preview_stamps = {}
        self._refresh_completion_preview()

    def _repolish_completion_with_current_glossary(self):
        project = getattr(self, '_last_studio_project', '')
        if not project:
            return
        if not self._prepare_glossary_for_task():
            return
        def preview(studio):
            from ..studio.studio_find_replace import GlossaryReviewDialog
            GlossaryReviewDialog(studio, studio).exec()
        self._open_completion_project(project, mode='edit', source='completion_current_glossary', on_ready=preview)

    def _open_completion_report_directory(self):
        report = getattr(self, '_last_recognition_report', '')
        target = Path(report).parent if report else Path(self.legacy.task_reporting.REPORT_ROOT)
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _copy_completion_output_paths(self):
        QApplication.clipboard().setText('\n'.join(getattr(self, '_completion_output_paths', ())))

    def _copy_completion_log(self):
        QApplication.clipboard().setText('\n'.join(getattr(self, '_completion_log_lines', ())) or self.console_log.toPlainText())

    def _completion_plain_log_fragment(self, line):
        # QTextDocument defaults can retain an earlier page's dark ink. Give
        # plain/history logs an explicit foreground on the console surface.
        theme = _active_theme_definition()
        background = QColor(theme.media)
        foreground = theme.text
        if QColor(foreground).lightnessF() < 0.5 and background.lightnessF() < 0.5:
            foreground = '#edf0e9'
        return f'<div style="white-space:pre; color:{foreground};">{html.escape(line)}</div>'

    def _prepare_completion_log(self):
        """Record the full run immediately; defer document layout until opened."""
        if not hasattr(self, 'result_log_toggle'):
            set_log_html_keep_left(self.result_console, self.console_log.toHtml())
            return
        bind_text(self.result_log_toggle, '运行日志')
        self._completion_log_lines = tuple(getattr(self, '_console_lines', ()))
        self._completion_log_fragments = tuple(getattr(self, '_console_fragments', ()))
        if not self._completion_log_fragments:
            self._completion_log_lines = tuple(self.console_log.toPlainText().splitlines())
            self._completion_log_fragments = tuple(self._completion_plain_log_fragment(line)
                                                   for line in self._completion_log_lines)
        self._completion_log_loaded = 0
        self._completion_log_generation = getattr(self, '_completion_log_generation', 0) + 1
        self.result_console.clear()
        # 2026-10-07 contract: both folds start collapsed; their headers still
        # show the first real facts, and the user's own choice is not overridden.
        self.result_log_panel.set_mode('collapsed')
        self.result_files_panel.set_mode('collapsed')
        self._refresh_completion_summaries()

    def _toggle_completion_log(self, expanded):
        if expanded and hasattr(self, '_completion_log_fragments'):
            self._render_completion_log_batch(self._completion_log_generation)

    def _render_completion_log_batch(self, generation):
        if generation != self._completion_log_generation or not self.result_log_toggle.isChecked():
            return
        start = self._completion_log_loaded
        end = min(start + 100, len(self._completion_log_fragments))
        if end == start:
            return
        append_log_html_keep_left(self.result_console, ''.join(self._completion_log_fragments[start:end]))
        self._completion_log_loaded = end
        if end < len(self._completion_log_fragments):
            QTimer.singleShot(0, self, lambda: self._render_completion_log_batch(generation))

    def _style_active_tasks_label(self) -> None:
        theme = _active_theme_definition()
        label = getattr(self, "active_tasks_label", None)
        if label is not None:
            label.setStyleSheet(
                f"background: {theme.panel}; border-radius: 8px; padding: 7px 9px; color: {theme.text_secondary};"
            )

    def _return_to_main_menu(self):
        """Confirm persisted delivery before leaving, independent of startup preference."""
        from ..projects.studio_project import load_project
        from ..timeline.studio_edit_sequence import projected_cues
        studio = self.built_page("studio")
        studio_path = str(getattr(studio, 'project_path', '') or '')
        if studio and studio_path and any(str(item.project_path) == studio_path for item, _ in getattr(self, '_completion_tasks', ())):
            stack = getattr(getattr(studio, 'session', None), 'undo_stack', None)
            if (stack is not None and not stack.isClean()) or getattr(studio, '_recovered_autosave_pending', False):
                studio.project_controller.save()
                if (stack is not None and not stack.isClean()) or getattr(studio, '_recovered_autosave_pending', False):
                    bind_text(self.result_task_summary, '结果尚未安全保存，请先保存工作台修改。')
                    self.result_task_summary.show()
                    return
        for item, project in getattr(self, '_completion_tasks', ()):
            expected = self._completion_task_evidence.get(self._completion_task_key(item), {}).get('outcome')
            if item.status not in {'success', 'degraded_success', 'completed'} and not (expected and expected.delivery_recovered):
                continue
            try:
                if not item.project_path:
                    raise ValueError(tr('本次任务没有保存可用的工程文件'))
                saved = load_project(item.project_path)
                expected = self._completion_task_evidence.get(self._completion_task_key(item), {}).get('outcome')
                if expected and expected.core_errors:
                    raise ValueError('; '.join(expected.core_errors))
                if expected and expected.final_cues and not projected_cues(saved):
                    raise ValueError(tr('保存的工程没有可用字幕'))
            except (OSError, ValueError, TypeError) as exc:
                bind_text(self.result_task_summary, '结果尚未安全保存：{reason}。请先恢复已有识别结果。', reason=str(exc)[:220])
                self.result_task_summary.show()
                QMessageBox.warning(self, tr('无法完成并返回'), tr('结果尚未安全保存，请先恢复已有识别结果。') + '\n' + str(exc))
                return
        dialog = getattr(self, '_completion_dialog', None)
        if dialog is not None:
            dialog.close()
        self._switch_page(0)
        self.workflow.set_active(0)
        self._refresh_media_summary()
        self._resolve_glossary_binding()

    def _open_priority_review_from_result(self) -> None:
        project = getattr(self, "_last_studio_project", "")
        if not project:
            return
        self._open_completion_project(project, mode="review", source="completion_review")

    def _open_subtitle_dir(self):
        target = getattr(self, "_last_srt_dir", "") or str(Path(self.legacy.SCRIPT_DIR))
        os.startfile(target)

    def _open_ai_provider_config(self) -> None:
        """跳到首页并打开 AI 设置（重试失败项引导）。The form lives in its dialog
        since 2026-10-08; expanding the off-page panel showed nothing (2026-10-22)."""
        try:
            self._switch_page(self.settings_scroll)
        except Exception:
            return
        self._open_ai_settings_dialog()

    def _retry_completion_stage(self, stage=None):
        if getattr(self, '_run_in_progress', False) or getattr(self, '_completion_retry_in_progress', False):
            return
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or not tasks[index][1]:
            return
        item, project = tasks[index]
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        from ..recognition.processing_recovery import refresh_completion_evidence
        refresh_completion_evidence(project,evidence)
        outcome = evidence.get('outcome')
        recovery=evidence.get('stage_recovery') or {}
        stage = stage or ('failed' if recovery.get('failed_tasks') or recovery.get('pending_proposals') else 'polish' if outcome and outcome.polish_retryable else 'terminology')
        if not outcome or not (stage == 'failed' or (stage == 'polish' and outcome.polish_retryable) or (stage == 'terminology' and outcome.search_retryable)):
            return
        report = copy.deepcopy(evidence.get('display_payload') or {})
        snapshot = getattr(self, '_last_run_options', None)
        def task_current():
            current=getattr(self,'_completion_tasks',())
            return 0<=index<len(current) and self._completion_task_key(current[index][0])==self._completion_task_key(item)
        def review(studio):
            from .completion_retry_ui import open_completion_retry_review
            self._completion_retry_in_progress = True
            origin=getattr(getattr(studio,'session',None),'project',None)
            origin_path=getattr(studio,'project_path',None)
            try:
                if stage=='failed':
                    from .stage_retry_ui import open_failed_stage_review
                    receipt=open_failed_stage_review(studio,report,snapshot)
                else:receipt = open_completion_retry_review(studio, report, snapshot, stage=stage)
                if receipt is not None:
                    evidence.setdefault('retry_receipts', []).append(receipt)
                if hasattr(studio,'session') and task_current():
                    result_project=studio.session.project
                    if result_project is not origin or getattr(studio,'project_path',None)!=origin_path:
                        from ..projects.studio_project import load_project
                        try:
                            result_project=load_project(item.project_path)
                            if origin is not None and result_project.project_id!=origin.project_id:raise ValueError('工程文件身份已改变')
                        except (OSError,ValueError,TypeError) as exc:
                            result_project=None;evidence['project_error']=str(exc)
                    self._completion_tasks[index]=(item,result_project)
                    refresh_completion_evidence(result_project,evidence)
            finally:
                self._completion_retry_in_progress = False
                if task_current() and hasattr(self,'result_title'):self._select_completion_task(index)
        self._open_completion_project(item.project_path, mode='edit', source='completion_failed_stage_retry', on_ready=review)

    def _retry_failed_items(self):
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if 0<=index<len(tasks) and tasks[index][1] is None:
            selected=self._completion_task_evidence.get(self._completion_task_key(tasks[index][0]),{})
            outcome=selected.get('outcome');payload=selected.get('display_payload') or {}
            if outcome and (outcome.polish_retryable or outcome.search_retryable or (payload.get('polishing_summary') or {}).get('fallback_cues')):
                QMessageBox.information(self,tr('无法重试当前范围'),tr('原工程尚未载入或身份已改变。请先恢复已有识别结果；未重新提交整段转写。'))
                return
        if 0 <= index < len(tasks) and tasks[index][1]:
            evidence=self._completion_task_evidence.get(self._completion_task_key(tasks[index][0]), {})
            from ..recognition.processing_recovery import refresh_completion_evidence
            refresh_completion_evidence(tasks[index][1],evidence)
            outcome=evidence.get('outcome');recovery=evidence.get('stage_recovery') or {}
            if outcome and outcome.result_usable and (recovery.get('failed_tasks') or recovery.get('pending_proposals') or outcome.polish_retryable or outcome.search_retryable):
                self._retry_completion_stage()
                return
        failed = getattr(self, "_last_failed_items", [])
        if not failed or getattr(self, '_run_in_progress', False):
            return
        snapshot = getattr(self, '_last_run_options', None)
        if snapshot is None:
            QMessageBox.information(self, tr('无法重试原任务'), tr('本页没有原任务的配置快照。请返回识别页开始新任务，或按当前词库预览重新校对。'))
            return
        # 配置类失败（缺密钥/缺模型/未登录）盲目重排只会再失败一次；
        # 先引导用户打开 AI 模型与密钥（2026-09-03 用户实录：30 分钟转写
        # 因校对缺密钥作废后，重试入口无法选择厂商，只能反复失败）。
        config_failures = [
            item for item in failed
            if _is_ai_config_failure(getattr(item, "error", ""))
        ]
        if config_failures:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            bind_text(box, 'AI 模型配置缺失', property='windowTitle')
            bind_text(box, '上次失败与 AI 模型配置有关（示例：{value0}）。\n\n请先在「AI 模型与密钥」中选择厂商并填写 API 密钥，或使用 Grok 账号登陆；完成后再回本页重试失败项。', value0=str(config_failures[0].error)[:160])
            open_button = box.addButton(
                "打开 AI 模型与密钥", QMessageBox.ButtonRole.AcceptRole
            )
            box.addButton("仍要重试", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_button:
                self._open_ai_provider_config()
                return
        # A cloud task that ended, vanished or whose submission is uncertain is
        # never sent again automatically (it may be billed twice). Ask once.
        from ..providers.cloud_api_worker import failure_from_text
        resubmit = [problem for problem in (failure_from_text(str(getattr(item, 'error', '') or '')) for item in failed)
                    if problem and problem.get('resubmit')]
        settings_json = snapshot.settings_snapshot_json
        if settings_json and ('cloud_resubmit_confirmed' in settings_json or 'mosi_resplit_blocked' in settings_json):
            # The confirmation belongs to one retry only; never carry it forward.
            try:
                cleaned = json.loads(settings_json)
                cleaned.get('models', {}).pop('cloud_resubmit_confirmed', None)
                cleaned.get('models', {}).pop('mosi_resplit_blocked', None)
                settings_json = json.dumps(cleaned, ensure_ascii=False)
            except (TypeError, ValueError, AttributeError):
                pass
        if resubmit:
            box = QMessageBox(self)
            first = next((problem for problem in resubmit if problem.get('code') == 'content_blocked'), resubmit[0])
            reason = str(first.get('message') or '')
            if first.get('code') == 'content_blocked':
                # The provider's content review stopped this audio (2026-10-24):
                # sending it unchanged is very likely stopped again.
                box.setIcon(QMessageBox.Icon.Warning)
                bind_text(box, '仍要重新提交被拦下的音频？', property='windowTitle')
                bind_text(box, '{reason}\n\n同一段音频原样重新提交多半还会被内容审查拦下，服务商也可能再次计费。建议改用本地识别，或换别的在线识别服务再识别这个视频。', reason=reason)
                again = box.addButton(tr('仍要重新提交'), QMessageBox.ButtonRole.AcceptRole)
                box.setDefaultButton(box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole))
            else:
                box.setIcon(QMessageBox.Icon.Question)
                bind_text(box, '重新提交云端识别？', property='windowTitle')
                bind_text(box, '{reason}\n\n重新提交会再次上传音频，服务商可能再次计费。如果你不确定上次是否已经扣费，可以先到服务商控制台查看任务与账单。', reason=reason)
                again = box.addButton(tr('重新提交'), QMessageBox.ButtonRole.AcceptRole)
                box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not again:
                return
            try:
                settings = json.loads(settings_json) if settings_json else copy.deepcopy(self.legacy.RUNTIME_SETTINGS)
                settings.setdefault('models', {})['cloud_resubmit_confirmed'] = True
                settings_json = json.dumps(settings, ensure_ascii=False)
            except (TypeError, ValueError):
                return
        self.media_paths = _merge_media_paths([], [f.media_path for f in failed])
        self._retry_cached_failed=True
        self._retry_run_options = replace(snapshot, force_refresh_polish=False,
                                          force_refresh_group=False, overwrite_policy='error',
                                          settings_snapshot_json=settings_json,
                                          audio_streams_json=self._retry_audio_streams(snapshot, failed))
        self.retry_failed_button.setEnabled(False)
        self._switch_page(0)
        self._refresh_media_summary()
        # 已完成阶段会命中阶段缓存，重试只重跑失败部分
        QTimer.singleShot(0, self, self._start_run)

    def _retry_audio_streams(self, snapshot, failed):
        """重试失败项 of a multi-track file reruns only the tracks that failed.

        The tracks that finished last time keep their captions: the retry adds
        to that run's combined result (2026-10-24).
        """
        from ..recognition.audio_stream_choice import base_projects, parse_request, request_json
        request = parse_request(getattr(snapshot, 'audio_streams_json', '') or '')
        if not request:
            return ''
        failed_tracks = {}
        for item in failed:
            key = str(Path(item.media_path).resolve())
            if int(getattr(item, 'audio_stream', -1)) >= 0:
                failed_tracks.setdefault(key, set()).add(int(item.audio_stream))
            elif key in request:
                failed_tracks.setdefault(key, set()).update(pick['ordinal'] for pick in request[key])
        picks = {key: [pick for pick in request[key] if pick['ordinal'] in ordinals]
                 for key, ordinals in failed_tracks.items() if key in request}
        bases = dict(base_projects(snapshot.audio_streams_json))
        for item in getattr(self, '_last_queue_results', ()) or ():
            if (item.status in {'success', 'degraded_success'} and item.project_path
                    and int(getattr(item, 'audio_stream', -1)) < 0):
                bases[str(Path(item.media_path).resolve())] = str(item.project_path)
        return request_json(picks, bases)

    def _cloud_gap_resplit(self, item) -> list:
        """Ranges of ``item`` that MOSI's content review stopped and that can
        go again in pieces (2026-10-24), from the task report. Single-track
        runs of this session only: the run's settings snapshot is needed."""
        snapshot = getattr(self, '_last_run_options', None)
        if snapshot is None or int(getattr(item, 'audio_stream', -1)) >= 0 \
                or str(getattr(snapshot, 'audio_streams_json', '') or '').strip():
            return []
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        self._completion_diagnosis(item, evidence)
        report = evidence.get('diagnosis_report')
        events = report.get('events') if isinstance(report, dict) else None
        rows = [row for row in events or () if isinstance(row, dict) and row.get('event') == 'cloud_asr_gap_fill']
        return [gap for gap in (rows[-1].get('gaps') or ()) if gap.get('resplittable')] if rows else []

    def _resplit_blocked_cloud_segments(self):
        """切成小段再交 MOSI…: the ranges MOSI's content review stopped go
        again in pieces of about 3 minutes (2026-10-24). Billed again, outcome
        uncertain; pieces still stopped are filled locally as before."""
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        snapshot = getattr(self, '_last_run_options', None)
        if not 0 <= index < len(tasks) or snapshot is None or getattr(self, '_run_in_progress', False):
            return
        item, _project = tasks[index]
        gaps = self._cloud_gap_resplit(item)
        if not gaps:
            return
        from ..providers.mosi_asr import PIECE_SECONDS, PRICE_CNY_PER_HOUR, estimate_cost_cny
        seconds = sum(max(0.0, float(gap['end']) - float(gap['start'])) for gap in gaps)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        bind_text(box, '切成小段再交 MOSI？', property='windowTitle')
        bind_text(box, '被内容审查拦下的 {count} 段（共 {minutes} 分钟）会切成约 {piece} 分钟的小段，重新上传给 MOSS Pro 云端；已经有字幕的段不会重新上传。\n\n'
                       '会再次计费：按每小时 ¥{price} 估算约 ¥{cost}（被拦下的小段收不收费，MOSI 官方没写）。\n\n'
                       '能不能通过不确定：审查规则在服务商那边，小段可能都能通过，也可能仍被拦下；仍被拦下的小段照旧用本地模型补，没有本地模型时空着。',
                  count=len(gaps), minutes=f'{seconds / 60:.1f}', piece=PIECE_SECONDS // 60,
                  price=f'{PRICE_CNY_PER_HOUR:.2f}', cost=f'{estimate_cost_cny(seconds):.2f}')
        again = box.addButton(tr('切成小段再交'), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole))
        box.exec()
        if box.clickedButton() is not again:
            return
        try:
            settings_json = snapshot.settings_snapshot_json
            settings = json.loads(settings_json) if settings_json else copy.deepcopy(self.legacy.RUNTIME_SETTINGS)
            models = settings.setdefault('models', {})
            models.pop('cloud_resubmit_confirmed', None)
            # For this one run only (asr_api_process reads it).
            models['mosi_resplit_blocked'] = True
            settings_json = json.dumps(settings, ensure_ascii=False)
        except (TypeError, ValueError, AttributeError):
            return
        self.media_paths = _merge_media_paths([], [item.media_path])
        self._retry_cached_failed = True
        self._retry_run_options = replace(snapshot, force_refresh_polish=False, force_refresh_group=False,
                                          overwrite_policy='overwrite', settings_snapshot_json=settings_json)
        self._switch_page(0)
        self._refresh_media_summary()
        QTimer.singleShot(0, self, self._start_run)

    @staticmethod
    def _supported_paths(paths):
        from ..media.media_intake import validate_media_paths
        return validate_media_paths(paths, check_readable=False)[0]

    def _set_drop_active(self, active: bool):
        if not hasattr(self, "media_frame"):
            return
        self.media_frame.setProperty("dropActive", bool(active))
        self.media_frame.style().unpolish(self.media_frame)
        self.media_frame.style().polish(self.media_frame)
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.set_active(bool(active))

    def _refresh_header_density(self):
        """Keep the full brand visible; compact navigation becomes icon buttons."""
        if hasattr(self, "language_combo"):
            navigation = ((self.support_button, "支持我！"),
                          (self.update_button, "检查更新"),
                          (self.subtitle_studio_button, "字幕工作台"),
                          (self.model_workshop_button, "模型工坊"),
                          (self.return_recognition_button, "返回字幕识别"),
                          (self.app_settings_button, "设置"))
            # Measure the current language, theme and visible controls before
            # compacting. A fixed threshold alone clips longer translations.
            for button, label in navigation:
                button.setText(tr(label))
                button.setMinimumWidth(0)
            ui_zoom.set_size(self.language_combo, min_w=100)
            self.header_content.layout().invalidate()
            compact = (ui_zoom.logical(self.width()) < 1050 or self.header_content.width()
                       < self.header_content.layout().sizeHint().width())
            self.header_mascot.setVisible(True)
            self.brand.setVisible(True)
            self.header_subtitle.setVisible(True)
            ui_zoom.set_size(self.language_combo, min_w=72 if compact else 100)
            # The full brand mascot keeps one size at every window height
            # (established contract); short pages compact their own spacing.
            # Logical px: the interface zoom scales them (ui_zoom.set_size).
            ui_zoom.set_size(self.app_header, fixed_h=104)
            for button, label in navigation:
                button.setAccessibleName(tr(label))
                button.setToolTip(tr(label))
                button.setText("" if compact else translate(label, current_language()))
                ui_zoom.set_size(button, min_w=36 if compact else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_header_density()
        if ui_zoom.zoom_percent() != ui_zoom.DEFAULT_PERCENT:
            # Responsive code re-sets constant sizes on resize; one zoom pass
            # after the resize settles scales them again (values the zoom set
            # itself are left alone).
            timer = getattr(self, "_ui_zoom_settle", None)
            if timer is None:
                timer = self._ui_zoom_settle = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(120)
                timer.timeout.connect(lambda: (ui_zoom.apply_to(self.app_header),
                                               ui_zoom.apply_to(self.pages.currentWidget()),
                                               ui_zoom.apply_to(self.bottom_bar)))
            timer.start()
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.setGeometry(self.rect().adjusted(16, 16, -16, -16))
        if hasattr(self, "_modal_host") and self._modal_host.isVisible():
            self._modal_host.resize_to_parent()
        studio = self.built_page("studio")
        if studio is None or self.pages.currentWidget() is not studio:
            self.apply_density()
        self._layout_resize_handles()

    # ------------------------- Frameless edge resize (P0) -------------------------
    @staticmethod
    def _resize_edge_in_rect(x, y, width, height, border, corner):
        """Return an edge only when the point is inside a strict edge band."""
        if width <= 0 or height <= 0:
            return None
        if x < 0 or y < 0 or x >= width or y >= height:
            return None

        corner_left = x <= corner
        corner_right = x >= width - corner
        corner_top = y <= corner
        corner_bottom = y >= height - corner
        if corner_top and corner_left: return "tl"
        if corner_top and corner_right: return "tr"
        if corner_bottom and corner_left: return "bl"
        if corner_bottom and corner_right: return "br"
        left = x <= border
        right = x >= width - border
        top = y <= border
        bottom = y >= height - border
        if left: return "left"
        if right: return "right"
        if top: return "top"
        if bottom: return "bottom"
        return None

    def _resize_edge_at(self, pos: QPoint):
        """Hit test a Qt-local point expressed in logical pixels."""
        return self._resize_edge_in_rect(
            pos.x(),
            pos.y(),
            self.width(),
            self.height(),
            self._resize_border,
            self._resize_corner,
        )

    @classmethod
    def _native_resize_edge_at(
        cls,
        screen_x,
        screen_y,
        window_rect,
        device_pixel_ratio,
        logical_border=8,
        logical_corner=12,
    ):
        """Hit test Windows physical coordinates without passing through Qt."""
        left, top, right, bottom = window_rect
        if right <= left or bottom <= top or device_pixel_ratio <= 0:
            return None
        border = max(1, round(logical_border * device_pixel_ratio))
        corner = max(border, round(logical_corner * device_pixel_ratio))
        return cls._resize_edge_in_rect(
            screen_x - left,
            screen_y - top,
            right - left,
            bottom - top,
            border,
            corner,
        )

    def nativeEvent(self, event_type, message):
        """Let Windows own frameless resize hit testing and resize cursors.

        The manual Qt drag path below remains the cross-platform fallback.
        WM_NCHITTEST and GetWindowRect both use physical screen pixels.  They
        must not pass through Qt's logical-coordinate mapFromGlobal().
        """
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                from .window_constraints import existing_native_handle
                hwnd = int(msg.hWnd or 0)
                if msg.message in (0x0002, 0x0082):  # WM_DESTROY / WM_NCDESTROY
                    if hwnd == getattr(self, '_native_frame_hwnd', hwnd):
                        self._native_frame_active = self._native_caption_active = False
                    return super().nativeEvent(event_type, message)
                if not existing_native_handle(self, hwnd=hwnd):
                    return super().nativeEvent(event_type, message)
                bounds = getattr(self, '_window_bounds', None)
                if bounds is not None:
                    result=bounds.native_message(int(msg.message), int(msg.wParam), int(msg.lParam))
                    if result is not None:
                        return True,result
                if msg.message == 0x0046:
                    studio = self.__dict__.get('_studio_page_instance')
                    pages = self.__dict__.get('pages')
                    if studio is not None and pages is not None and pages.currentWidget() is studio:
                        from .window_constraints import native_windowpos
                        if native_windowpos(self, int(msg.lParam)):
                            return True, 0
                if msg.message in (0x0083,0x0024):
                    from .window_native_frame import handle_message
                    result = handle_message(self,int(msg.message),int(msg.wParam),int(msg.lParam),hwnd=hwnd)
                    if result is not None:
                        return True,result
            except (ValueError, TypeError, OSError, RuntimeError):
                return super().nativeEvent(event_type, message)
        if os.name == "nt" and not self.isFullScreen():
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    packed = int(msg.lParam)
                    screen_x = ctypes.c_short(packed & 0xFFFF).value
                    screen_y = ctypes.c_short((packed >> 16) & 0xFFFF).value
                    window_rect = wintypes.RECT()
                    from .window_constraints import _user32
                    user32 = _user32()
                    get_window_rect = user32.GetWindowRect
                    get_window_rect.argtypes = [
                        wintypes.HWND,
                        ctypes.POINTER(wintypes.RECT),
                    ]
                    get_window_rect.restype = wintypes.BOOL
                    if not get_window_rect(msg.hWnd, ctypes.byref(window_rect)):
                        return super().nativeEvent(event_type, message)
                    device_pixel_ratio = float(self.devicePixelRatioF())
                    get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
                    if get_dpi_for_window is not None:
                        get_dpi_for_window.argtypes = [wintypes.HWND]
                        get_dpi_for_window.restype = wintypes.UINT
                        dpi = int(get_dpi_for_window(msg.hWnd))
                        if dpi > 0:
                            device_pixel_ratio = dpi / 96.0
                    edge = None if self.isMaximized() or user32.IsZoomed(msg.hWnd) else self._native_resize_edge_at(
                        screen_x,
                        screen_y,
                        (
                            window_rect.left,
                            window_rect.top,
                            window_rect.right,
                            window_rect.bottom,
                        ),
                        device_pixel_ratio,
                        self._resize_border,
                        self._resize_corner,
                    )
                    hit_codes = {
                        "left": 10,    # HTLEFT
                        "right": 11,   # HTRIGHT
                        "top": 12,     # HTTOP
                        "tl": 13,      # HTTOPLEFT
                        "tr": 14,      # HTTOPRIGHT
                        "bottom": 15,  # HTBOTTOM
                        "bl": 16,      # HTBOTTOMLEFT
                        "br": 17,      # HTBOTTOMRIGHT
                    }
                    if edge in hit_codes:
                        return True, hit_codes[edge]
                    from .window_native_frame import caption_hit
                    if caption_hit(self,screen_x,screen_y,device_pixel_ratio,hwnd=int(msg.hWnd or 0)):
                        return True,2  # HTCAPTION: Windows owns threshold, restore and drag
            except Exception:
                # A malformed native message must never break ordinary input;
                # Qt's existing manual fallback remains available.
                pass
        return super().nativeEvent(event_type, message)

    def _apply_resize_cursor(self, edge):
        cursors = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edge, Qt.CursorShape.ArrowCursor))

    def mouseMoveEvent(self, event):
        if getattr(self, "_resize_dragging", False) and self._resize_edge and self._resize_start_geom and self._resize_start_pos:
            self._perform_resize_drag(event.globalPosition().toPoint())
            event.accept()
            return
        if self.isMaximized() or self.isFullScreen():
            self.unsetCursor()
            super().mouseMoveEvent(event)
            return
        edge = self._resize_edge_at(event.position().toPoint())
        self._apply_resize_cursor(edge)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._resize_edge_at(event.position().toPoint())
            if edge and not (self.isMaximized() or self.isFullScreen()):
                from .window_constraints import start_system_resize
                edges = Qt.Edge(0)
                if edge in ('left','tl','bl'): edges |= Qt.LeftEdge
                if edge in ('right','tr','br'): edges |= Qt.RightEdge
                if edge in ('top','tl','tr'): edges |= Qt.TopEdge
                if edge in ('bottom','bl','br'): edges |= Qt.BottomEdge
                if start_system_resize(self, edges):
                    event.accept()
                    return
                bounds = getattr(self, '_window_bounds', None)
                if bounds is not None:
                    bounds.begin_interaction('manual-resize')
                self._resize_edge = edge
                self._resize_start_geom = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_dragging = True
                self.grabMouse()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_resize_dragging", False):
            self._resize_dragging = False
            self._resize_edge = None
            self._resize_start_geom = None
            self._resize_start_pos = None
            self.releaseMouse()
            self.unsetCursor()
            bounds = getattr(self, '_window_bounds', None)
            if bounds is not None:
                bounds.end_interaction('resize-release')
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not getattr(self, "_resize_dragging", False):
            self.unsetCursor()
        super().leaveEvent(event)

    def _perform_resize_drag(self, global_pos: QPoint):
        if not self._resize_start_geom or not self._resize_start_pos:
            return
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        g = QRect(self._resize_start_geom)
        edge = self._resize_edge
        minw = self.minimumWidth()
        minh = self.minimumHeight()
        if edge in ("left", "tl", "bl"):
            new_left = g.left() + dx
            new_w = max(minw, g.right() - new_left)
            g.setLeft(g.right() - new_w)
        if edge in ("right", "tr", "br"):
            new_w = max(minw, g.width() + dx)
            g.setWidth(new_w)
        if edge in ("top", "tl", "tr"):
            new_top = g.top() + dy
            new_h = max(minh, g.bottom() - new_top)
            g.setTop(g.bottom() - new_h)
        if edge in ("bottom", "bl", "br"):
            new_h = max(minh, g.height() + dy)
            g.setHeight(new_h)
        self.setGeometry(g)

    def apply_density(self):
        """两档密度：Comfortable ≥1600 宽；Compact ≤1440（1366 主力）。

        只调字号与少量高度，不做同比缩放；QSS 静态部分由角色卡等
        组件内 apply_density 覆盖。
        P0 Resize: never force fixed heights on main surfaces that starve content.
        """
        studio = self.built_page("studio")
        if studio is not None and self.pages.currentWidget() is studio:
            return
        # Breakpoints in 100% pixels: a zoomed page takes the smaller window's layout.
        width, height = ui_zoom.logical(self.width()), ui_zoom.logical(self.height())
        comfortable = width >= 1600
        tier = 2 if height >= 1150 else 1 if height >= 900 else 0
        zoom = ui_zoom.zoom_percent()
        if hasattr(self, "recognition_plan") and getattr(self, "_home_tier", None) != (tier, comfortable, zoom):
            previous = getattr(self, "_home_tier", None)
            self._home_tier = (tier, comfortable, zoom)
            # 2026-10-17 (user, home C′): compact model cards at their natural
            # height per tier; the card profile follows that height.
            self._sync_home_plan(tier)
            if hasattr(self, "media_row_layout") and (previous or (None,))[0] != tier:
                self._apply_media_mode(bool(getattr(self, "media_paths", None)))
                if not self.media_paths:
                    self._style_media_summary()
        if hasattr(self, "_home_plan_layout"):
            self._schedule_home_fit()
        # Recognition cards also depend on their current height, so let that
        # lightweight cached path run on every resize.
        if hasattr(self, "recognition_plan"):
            self.recognition_plan.apply_density(comfortable)
        if hasattr(self, "page_subtitle"):
            # Narrow windows give the heading row to the plan toolbar.
            self.page_subtitle.setVisible(comfortable)
        if getattr(self, "_density_comfortable", None) is not comfortable and hasattr(self, "_last_plan_items"):
            self._refresh_readiness_bar(self._last_plan_items)
        if self._density_comfortable is comfortable:
            return
        self._density_comfortable = comfortable
        if hasattr(self, "settings_surface"):
            # Use a minimum; allow layout-driven growth on tall windows.
            self.settings_surface.setMinimumHeight(320 if comfortable else 300)
        if hasattr(self, "setting_tiles"):
            for tile in self.setting_tiles.values():
                tile.apply_density(comfortable)
        workshop = self.built_page("workshop")
        if workshop is not None:
            workshop.apply_density(comfortable)

    def refresh_theme_palette(self) -> None:
        """Refresh MainWindow-owned inline colors after a global theme switch."""
        if hasattr(self, "media_name") and hasattr(self, "media_drop_hint"):
            self._style_media_summary()
        # The runtime-page active-tasks box is styled inline (not via the global
        # QSS), so it must be re-styled here too. A second same-name definition
        # used to shadow this call and left the box on its build-time theme.
        self._style_active_tasks_label()
        self._restyle_progress_page()
        frost = self.__dict__.get("content_frost")
        if frost is not None:
            frost.refresh()  # the frosted picture and its tint follow the theme

    def _style_media_summary(self) -> None:
        theme = _active_theme_definition()
        ready = bool(getattr(self, "media_paths", None))
        if hasattr(self, "media_type_icon"):
            import qtawesome as qta

            # Ready: check on the success chip; empty: brand import glyph.
            icon = (qta.icon("fa5s.check", color=theme.on_vivid) if ready
                    else qta.icon("fa5s.file-import", color=theme.accent_text))
            self.media_type_icon.setPixmap(icon.pixmap(QSize(18, 18)))
            # Descendant rules keyed on the card's [empty] state need a re-polish.
            self.media_type_icon.style().unpolish(self.media_type_icon)
            self.media_type_icon.style().polish(self.media_type_icon)
        if hasattr(self, "media_ready_badge"):
            self.media_ready_badge.setVisible(ready)
        self._apply_media_mode(ready)
        if hasattr(self, "media_type_icon") and not ready:
            glyph = max(24, round(self.media_type_icon.width() * 0.42))
            self.media_type_icon.setPixmap(
                qta.icon("fa5s.file-import", color=theme.accent_text).pixmap(QSize(glyph, glyph)))
        self.media_name.setStyleSheet(
            f"font-size: {16 if ready else 19}px; font-weight: 600; color: {theme.text};"
        )
        self.media_drop_hint.setStyleSheet(
            f"color: {theme.text_secondary}; font-size: 13px;"
        )
        self._style_home_icons()
        if hasattr(self, "media_origin_label"):
            self.media_origin_label.setStyleSheet(
                f"color:{theme.accent}; font-size:12px; font-weight:700;"
            )

    def _refresh_media_summary(self):
        language = getattr(self, "_ui_language", current_language())
        ready = bool(self.media_paths)
        self._render_next_step()
        self.media_frame.setProperty("empty", not ready)
        self.media_frame.style().unpolish(self.media_frame)
        self.media_frame.style().polish(self.media_frame)
        # P1-4：运行期间（含准备/取消）开始按钮保持禁用，
        # 避免切页重选素材等路径重新启用它。
        self.start_button.setEnabled(ready and not self._run_in_progress)
        if ready:
            # Which files carry several audio tracks is known before 开始识别.
            from .home_audio_tracks import warm_up
            warm_up(self.media_paths)
            preview = "、".join(Path(path).name for path in self.media_paths[:2])
            if len(self.media_paths) > 2:
                preview += f" 等 {len(self.media_paths)} 个文件"
            self.media_name.setText(preview)
            self.media_name.setToolTip("\n".join(self.media_paths))
            # Bind the Chinese source, not a translation: the binding is
            # re-rendered on every language switch. A translated source stayed
            # in the language that was active at this refresh.
            bind_text(self.media_drop_hint, '可继续拖入另一批素材，或点击右侧重新选择')
            bind_text(self.header_status, f'●  {len(self.media_paths)} ' + ('media items ready' if language == 'en' else ui_literal('个素材已就绪', language)))
        else:
            bind_text(self.media_name, '把视频或音频拖到这里')
            self.media_name.setToolTip("")
            bind_text(self.media_drop_hint, '支持多选；也可以点击右侧“选择素材”')
            bind_text(self.header_status, '● {status}', status=tr('等待素材'))
        if hasattr(self, "media_origin_label"):
            self.media_origin_label.setVisible(
                bool(getattr(self, "_studio_recognition_context", None))
            )
        self._style_media_summary()
        self.start_button.setEnabled(ready and not self._run_in_progress)
        if hasattr(self, "_refresh_asr_summary"):
            self._refresh_asr_summary()
        self._refresh_recognition_recommendation()
        self._refresh_media_input_list()

    def _refresh_media_input_list(self) -> None:
        """Render a compact, removable row for every selected source."""
        host = getattr(self, "media_input_list", None)
        if host is None:
            return
        while self.media_input_list_layout.count():
            item = self.media_input_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._media_input_cards = {}
        host.setVisible(len(self.media_paths) > 1)
        self.clear_single_media_button.setVisible(len(self.media_paths) == 1)
        if len(self.media_paths) > 1:
            header = QFrame(host)
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(4, 0, 4, 0)
            header_layout.addWidget(bind_text(QLabel(), '已选择 {value0} 个素材', value0=len(self.media_paths)), 1)
            clear = QToolButton(header)
            bind_text(clear, '清空全部')
            bind_text(clear, '移除全部待处理素材', property='toolTip')
            clear.clicked.connect(self._clear_media_paths)
            header_layout.addWidget(clear)
            self.media_input_list_layout.addWidget(header)
        for raw_path in self.media_paths:
            path = str(raw_path)
            row = QFrame(host)
            row.setObjectName("mediaInputRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 5, 8, 5)
            row_layout.setSpacing(8)
            name = QLabel(Path(path).name)
            name.setToolTip(path)
            name.setObjectName("mediaInputName")
            suffix = Path(path).suffix.lower().lstrip(".").upper() or "FILE"
            kind = QLabel(suffix)
            kind.setObjectName("mediaInputMeta")
            status = QLabel("待处理")
            status.setObjectName("mediaInputMeta")
            row_layout.addWidget(name, 1)
            row_layout.addWidget(kind)
            row_layout.addWidget(status)
            remove = QToolButton(row)
            remove.setObjectName("mediaInputRemove")
            remove.setIcon(_icon("fa5s.times"))
            bind_text(remove, '移除素材', property='toolTip')
            remove.setAutoRaise(True)
            remove.clicked.connect(lambda _checked=False, value=path: self._remove_media_path(value))
            row_layout.addWidget(remove)
            self.media_input_list_layout.addWidget(row)
            self._media_input_cards[path] = row
        if self.media_paths:
            bind_text(self.media_input_list, '已选择 %d 个素材；拖入可追加，选择素材可重新选择' % len(self.media_paths), property='toolTip')

    def _remove_media_path(self, path: str) -> bool:
        if self._run_in_progress or (self.worker is not None and self.worker.isRunning()):
            answer = QMessageBox.question(
                self, tr('素材正在处理中'), tr('该素材正在处理中，停止该素材任务后移除？'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            if self.token is not None:
                self.token.cancel()
            return False
        normalized = str(Path(path).resolve()) if path else str(path)
        kept = []
        removed = False
        for item in self.media_paths:
            try:
                same = str(Path(item).resolve()) == normalized
            except (OSError, ValueError):
                same = str(item) == str(path)
            if same and not removed:
                removed = True
                continue
            kept.append(item)
        if removed:
            self.media_paths = kept
            self._refresh_media_summary()
        return removed

    def _clear_media_paths(self) -> bool:
        if not self.media_paths:
            return True
        if self._run_in_progress or (self.worker is not None and self.worker.isRunning()):
            QMessageBox.information(self, tr('任务运行中'), tr('请先结束当前识别任务，再清空素材。'))
            return False
        self.media_paths = []
        self._refresh_media_summary()
        return True

    def _set_backend_combo(self, combo, value: str) -> bool:
        index = combo.findData(value)
        if index < 0:
            return False
        combo.setCurrentIndex(index)
        return True

    @navigation_timed('home.profiles')
    def _refresh_project_profile_combo(self, selected_id: str = "") -> None:
        if not hasattr(self, "project_profile_combo"):
            return
        selected_id = selected_id or (
            self.current_project_profile.id if self.current_project_profile else ""
        )
        self.project_profile_combo.blockSignals(True)
        self.project_profile_combo.clear()
        self.project_profile_combo.addItem(tr("自定义方案"), "")
        for profile in self.profile_store.list():
            label = profile.name + (' · ' + tr('自定义方案') if profile.recognition_plan == 'custom' else '')
            self.project_profile_combo.addItem(label, profile.id)
            self.project_profile_combo.setItemData(self.project_profile_combo.count()-1, True, Qt.ItemDataRole.UserRole+175)
        index = self.project_profile_combo.findData(selected_id)
        self.project_profile_combo.setCurrentIndex(max(0, index))
        self.project_profile_combo.blockSignals(False)

    @navigation_timed('home.profile_snapshot')
    def _profile_configuration(self) -> dict:
        settings = self.legacy.RUNTIME_SETTINGS
        studio = settings.get("studio", {}) if isinstance(settings.get("studio", {}), dict) else {}
        output = settings.get("output", {}) if isinstance(settings.get("output", {}), dict) else {}
        review = settings.get("review", {}) if isinstance(settings.get("review", {}), dict) else {}
        llm_enabled = bool(getattr(getattr(self, "ai_grouping", None), "isChecked", lambda: False)())
        llm_config_ref = ""
        try:
            llm_config_ref = str(self.group_editor.model.currentText() or "")
        except Exception:
            pass
        return {
            "recognition_plan": str(self.recognition_mode_combo.currentData() or "custom"),
            "primary_asr": str(self.primary_asr_backend.currentData() or ""),
            "timestamp_model": str(self.firered_asr_backend.currentData() or ""),
            "evidence_model": str(self.qwen_asr_backend.currentData() or ""),
            "llm_enabled": llm_enabled,
            "llm_config_ref": llm_config_ref,
            "llm_config": self._llm_profile_configuration(),
            # 2026-09-19 方案独立轮：ASR 细参数（provider/protocol/model/url/风格等）
            # 随方案深拷贝快照保存——此前只有一个全局槽，改 A 必改 B。
            "asr_config": copy.deepcopy(self._asr_values()),
            "glossary_ids": self._enabled_glossary_ids(),
            "language": current_language(),
            "subtitle_mode": str(studio.get("subtitle_mode", "monolingual")),
            "subtitle_style_preset": str(studio.get("style_preset", "default")),
            "render_preset": str(studio.get("render_preset", "default")),
            "export_format": str(output.get("format", "srt")),
            "review_threshold": float(review.get("threshold", 0.65)),
            "review_strategy": str(review.get("strategy", "risk_first")),
        }

    def _llm_profile_configuration(self) -> dict:
        return normalize_llm_config({"polish": self.polish_editor.values(),
                                     "group": self.group_editor.values(),
                                     "unified": self.unified_glm.isChecked(),
                                     "enable_ai_polish": self.ai_polish.isChecked(),
                                     "use_ai_grouping": self.ai_grouping.isChecked()})

    def _apply_profile_llm_config(self, snapshot: dict, *, persist: bool = True) -> bool:
        snapshot = normalize_llm_config(snapshot)
        if not snapshot:
            # Model-only legacy bookmarks cannot identify a billing endpoint.
            return False
        for editor in (self.polish_editor, self.group_editor):
            editor._invalidate_model_discovery()
            editor._discovery_pending = False
        if persist:
            persist_ai_configuration(self.legacy, snapshot["polish"], snapshot["group"],
                unified=snapshot["unified"], share_key=False, require_ready=False,
                use_ai_grouping=snapshot["use_ai_grouping"], enable_ai_polish=snapshot["enable_ai_polish"])
        from PySide6.QtCore import QSignalBlocker
        blockers = [QSignalBlocker(box) for box in (self.ai_polish, self.ai_grouping, self.unified_glm, self.share_key)]
        try:
            self.ai_grouping.setChecked(snapshot["use_ai_grouping"])
            self.ai_polish.setChecked(snapshot["enable_ai_polish"])
            self.unified_glm.setChecked(snapshot["unified"])
            self.share_key.setChecked(False)
            self.polish_editor.restore_profile_values(snapshot["polish"], self.legacy.RUNTIME_SETTINGS)
            self.group_editor.restore_profile_values(snapshot["group"], self.legacy.RUNTIME_SETTINGS)
        finally:
            del blockers
        self._apply_ai_grouping_mode(snapshot["use_ai_grouping"])
        return True

    def _apply_profile_asr_config(self, asr_config: dict, *, persist: bool = True) -> None:
        """把方案 ASR 快照写回全局 settings 并同步到界面控件。

        快照不含密钥：密钥按 provider+base_url 继续走 DPAPI 存储。
        v1 旧方案无快照时保持现状（等价旧全局行为），等首次保存后落快照。
        """
        if not isinstance(asr_config, dict) or not asr_config:
            return
        models = {key: str(asr_config.get(key, "") or "") for key in ASR_CONFIG_KEYS}
        models['speaker_source']=asr_config.get('speaker_source') or 'single'
        # Profiles use the same exact ASR retirement migration as settings.
        # Merge over the current snapshot to retain an omitted workspace URL;
        # then project only fields owned by this ASR bookmark back to controls.
        from ..storage.settings import DEFAULT_SETTINGS, _merge_known_settings
        supplied = copy.deepcopy(self.legacy.RUNTIME_SETTINGS)
        supplied.setdefault('models', {}).update({key:value for key,value in models.items() if value})
        normalized, _ = _merge_known_settings(DEFAULT_SETTINGS, supplied)
        migrated = (models.get('qwen_asr_api_provider') in {'qwen_filetrans','qwen31_flash','dashscope_qwen_audio'}
                    or (models.get('qwen_asr_api_provider')=='dashscope' and models.get('qwen_asr_api_model')=='qwen3-asr-flash'))
        for key,value in list(models.items()):
            if value or (migrated and key.startswith('qwen_asr_api_')):
                models[key] = normalized['models'][key]
        # 先落全局（configure_runtime_asr 内部深拷贝+落盘+刷新模块全局），
        # 这样后续 _apply_asr_preset_fields 读到的"已保存值"就是快照本身。
        if persist:
            self.legacy.configure_runtime_asr(models, qwen_asr_key="")
        if hasattr(self,'speaker_source'):
            self.speaker_source.blockSignals(True)
            self.speaker_source.setCurrentIndex(0)
            self.speaker_source.blockSignals(False)
        provider = models.get("qwen_asr_api_provider", "")
        provider_index = self.qwen_asr_api_provider.findData(provider) if provider else -1
        if provider and provider_index < 0:
            self.qwen_asr_api_provider.addItem(provider, provider)
            provider_index = self.qwen_asr_api_provider.findData(provider)
        if provider_index >= 0 and provider_index != self.qwen_asr_api_provider.currentIndex():
            self.qwen_asr_api_provider.setCurrentIndex(provider_index)
        # 快照值拥有最终决定权（provider 切换信号可能刚按预设填过默认值）。
        if models.get("qwen_asr_api_model"):
            self.qwen_asr_api_model.setText(models["qwen_asr_api_model"])
        if models.get("qwen_asr_api_url"):
            self.qwen_asr_api_url.setText(models["qwen_asr_api_url"])
        style_index = self.api_transcribe_style.findData(models.get("api_transcribe_style", "")) \
            if hasattr(self, "api_transcribe_style") else -1
        if style_index >= 0:
            self.api_transcribe_style.setCurrentIndex(style_index)
        self._refresh_asr_key_placeholder()

    def _refresh_asr_key_placeholder(self) -> None:
        """按当前 provider+base 刷新 API Key 输入框占位（不弹任何网络请求）。"""
        if not hasattr(self, "qwen_asr_api_key"):
            return
        try:
            provider = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
            base = self.qwen_asr_api_url.text().strip()
            existing, source = read_asr_api_key(provider, base)
            (bind_text(self.qwen_asr_api_key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.qwen_asr_api_key, '请输入当前 ASR 服务的 API Key', property='placeholderText'))
        except Exception:
            pass

    def _apply_profile_controls(self, profile, *, persist: bool = True) -> None:
        """同步方案到界面控件与全局 ASR 快照（不写工程绑定/不 mark_used）。"""
        self._set_backend_combo(self.primary_asr_backend, profile.primary_asr)
        self._set_backend_combo(self.firered_asr_backend, profile.timestamp_model)
        self._set_backend_combo(self.qwen_asr_backend, profile.evidence_model)
        if str(profile.recognition_plan) == "custom":
            self._show_plan_choice("custom")  # not a menu choice; shown while it is the current one
        plan_index = self.recognition_mode_combo.findData(profile.recognition_plan)
        if plan_index >= 0:
            self.recognition_mode_combo.setCurrentIndex(plan_index)
        # ASR 细参数快照恢复（v1 无快照=保持全局现状）。
        self._apply_profile_asr_config(getattr(profile, "asr_config", {}) or {}, persist=persist)
        # llm 开关/断句模型引用恢复（墓碑 ref 不回灌，见 _save_ai_configuration
        # 的方案书签同步）。
        if hasattr(self, "ai_grouping") and bool(profile.llm_enabled) != self.ai_grouping.isChecked():
            self.ai_grouping.setChecked(bool(profile.llm_enabled))
        self._apply_profile_llm_config(getattr(profile, "llm_config", {}), persist=persist)

    def _apply_project_profile(self, profile: ProjectProfile, *, mark_used: bool = True, bind_project: bool = True) -> bool:
        if self.worker is not None and self.worker.isRunning():
            bind_text(self.profile_recommendation, '当前识别任务正在运行；请完成或取消后切换方案。')
            return False
        previous = self.current_project_profile
        self._applying_profile = True
        try:
            # 2026-09-19：方案不再驱动界面语言——历史方案存的 language 是保存时的
            # 界面语言快照，回灌会在启动时把用户已选语言覆盖回旧值（真机实录：
            # STARTUP_LANGUAGE en → 3 秒后 zh，来自 _restore_last_project_profile
            # 触发的方案应用）。profile.language 字段保留存储但永不应用。
            # Validate and save the entire snapshot before changing any active
            # profile, control or module global. One atomic settings write.
            settings = copy.deepcopy(self.legacy.RUNTIME_SETTINGS)
            asr = getattr(profile, 'asr_config', {}) or {}
            if 'speaker_source' in asr:
                settings['models']['speaker_source'] = asr['speaker_source']
            if asr:
                settings['models'].update({k: str(v) for k, v in asr.items() if k in ASR_CONFIG_KEYS and str(v)})
                settings['switches']['enable_qwen_asr_reference'] = settings['models']['qwen_asr_backend'] != 'off'
                settings['switches']['enable_firered_boundary_refinement'] = settings['models']['firered_asr_backend'] != 'off'
            from ..recognition.recognition_profiles import normalize_llm_config
            llm = normalize_llm_config(getattr(profile, 'llm_config', {}))
            if llm:
                prepared = persist_ai_configuration(self.legacy, llm['polish'], llm['group'],
                    unified=llm['unified'], share_key=False, require_ready=False,
                    use_ai_grouping=llm['use_ai_grouping'], enable_ai_polish=llm['enable_ai_polish'], dry_run=True)
                settings['models'].update(prepared['models'])
                settings['switches'].update(unified_glm_processing=prepared['unified'], use_ai_grouping=llm['use_ai_grouping'], enable_ai_polish=llm['enable_ai_polish'])
            retired_ref = ""
            profile_ref = str(getattr(profile, "llm_config_ref", "") or "")
            if model_is_retired(profile_ref):
                retired_ref = profile_ref
            settings.setdefault("glossary", {})["enabled_glossary_ids"] = list(profile.glossary_ids)
            settings["glossary"]["enable_domain_terms"] = bool(profile.glossary_ids)
            settings.setdefault("studio", {}).update({
                "subtitle_mode": profile.subtitle_mode,
                "style_preset": profile.subtitle_style_preset,
                "render_preset": profile.render_preset,
            })
            settings.setdefault("output", {})["format"] = profile.export_format
            settings.setdefault("review", {}).update({
                "threshold": profile.review_threshold,
                "strategy": profile.review_strategy,
            })
            settings, _, warnings = save_runtime_settings(settings)
        except (OSError, ValueError, RuntimeError) as exc:
            self._refresh_project_profile_combo(previous.id if previous else '')
            bind_text(self.profile_recommendation, '方案切换失败，仍保留原方案：{exc}', exc=exc)
            return False
        finally:
            self._applying_profile = False
        self.legacy.adopt_profile_runtime_settings(settings, warnings)
        self._restore_glossary_switch()
        GLOBAL_PROVIDER_REGISTRY.bind(settings)
        self.current_project_profile = profile
        self._applying_profile = True
        try:
            self._apply_profile_controls(profile, persist=False)
        finally:
            self._applying_profile = False
        usage_warning = ''
        if mark_used:
            try:
                self.profile_store.set_last_selected(profile.id)
            except (OSError, ValueError) as exc:
                usage_warning = f'；最近使用记录未保存：{exc}'
        studio = self.built_page("studio")
        if bind_project and studio is not None and studio.project:
            studio.project.studio_state["profile_id"] = profile.id
        self._asr_config_dirty = False
        self._refresh_project_profile_combo(profile.id)
        self._refresh_glossary_chips()
        self._refresh_asr_summary()
        self._refresh_workshop_after_asr_change()
        if retired_ref and hasattr(self, "ai_save_status"):
            self.ai_save_status.setObjectName("statusWarn")
            bind_text(self.ai_save_status, '方案中的断句模型 {retired_ref} 已不可用；已保留当前全局选择，重新选择并保存后将更新方案。', retired_ref=retired_ref)
            self.ai_save_status.style().unpolish(self.ai_save_status)
            self.ai_save_status.style().polish(self.ai_save_status)
        bind_text(self.profile_recommendation, translate('已应用：', getattr(self, '_ui_language', current_language())) + profile.name + usage_warning)
        self._apply_saved_ai_configuration(source='profile_applied')
        return True

    def _project_profile_selected(self, _index: int = -1) -> None:
        if getattr(self, "_applying_profile", False):
            return
        new_id = str(self.project_profile_combo.currentData() or "")
        current = self.current_project_profile
        if current is not None and current.id == new_id:
            return
        if getattr(self, "_asr_config_dirty", False):
            answer = self._prompt_unsaved_profile_changes(current)
            if answer == "cancel":
                self._refresh_project_profile_combo(current.id if current else "")
                return
            if answer == "save" and current is not None:
                if not self._update_project_profile():
                    self._refresh_project_profile_combo(current.id)
                    return
        profile = self.profile_store.get(new_id)
        if profile is not None:
            if self._apply_project_profile(profile):
                self._profile_explicitly_selected = True
                self._home_profile_selection = profile.id
            return
        # 切到"自定义方案"（无快照）：保留当前全局值，仅解除方案绑定。
        self.current_project_profile = None
        self._profile_explicitly_selected = True
        self._home_profile_selection = ''
        self._asr_config_dirty = False
        try:
            self.profile_store.set_last_selected("")
        except Exception:
            pass
        bind_text(self.profile_recommendation, translate('自定义方案：当前配置未保存到方案', getattr(self, '_ui_language', current_language())))

    def _prompt_unsaved_profile_changes(self, current: ProjectProfile | None) -> str:
        """切换方案时有未保存修改：返回 save / discard / cancel。"""
        language = getattr(self, "_ui_language", current_language())
        box = QMessageBox(self)
        bind_text(box, translate('未保存的方案修改', language), property='windowTitle')
        if current is not None:
            bind_text(box, translate('方案“{name}”有未保存的识别参数修改。', language).replace('{name}', current.name))
            bind_text(box, translate('保存到当前方案后切换，或放弃修改。', language), property='informativeText')
            save_text = translate("保存并切换", language)
            box.addButton(save_text, QMessageBox.ButtonRole.AcceptRole)
            box.addButton(translate("放弃修改", language), QMessageBox.ButtonRole.DestructiveRole)
        else:
            bind_text(box, translate('当前识别参数修改尚未保存为方案，切换后将按目标方案恢复。', language))
            bind_text(box, translate('放弃当前修改并切换，或取消。', language), property='informativeText')
            box.addButton(translate("放弃修改", language), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(translate("取消", language), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None:
            return "cancel"
        # 按钮文案已本地化，身份判定一律用角色，不比较文案。
        role = box.buttonRole(clicked)
        if role == QMessageBox.ButtonRole.AcceptRole:
            return "save"
        if role == QMessageBox.ButtonRole.DestructiveRole:
            return "discard"
        return "cancel"

    def _restore_last_project_profile(self) -> None:
        if getattr(self, '_profile_explicitly_selected', False):
            return
        # Restore the bookmark only. The current settings file owns the latest
        # explicit edits; last_started is an immutable historical task receipt.
        profile = self.profile_store.get(self.profile_store.last_selected_id())
        self.current_project_profile = profile
        self._refresh_project_profile_combo(profile.id if profile else '')
        self._refresh_workshop_after_asr_change()

    def _new_project_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, tr('新建方案'), tr('方案名称：'))
        if not accepted or not name.strip():
            return
        try:
            profile = self.profile_store.create(name.strip(), **self._profile_configuration())
        except ValueError as exc:
            QMessageBox.information(self, tr('无法新建方案'), str(exc))
            return
        # 用户显式创建/采用 = 全局上次使用（2026-09-20：否则重启回旧方案）。
        self.profile_store.set_last_selected(profile.id)
        self._apply_project_profile(profile, mark_used=False)

    def _save_project_profile_as(self) -> None:
        source = self.current_project_profile
        name, accepted = QInputDialog.getText(self, tr('另存为方案'), tr('新方案名称：'))
        if not accepted or not name.strip():
            return
        try:
            if source is None:
                profile = self.profile_store.create(name.strip(), **self._profile_configuration())
            else:
                profile = self.profile_store.save_as(source.id, name.strip(), **self._profile_configuration())
        except (KeyError, ValueError) as exc:
            QMessageBox.information(self, tr('无法另存方案'), str(exc))
            return
        self.profile_store.set_last_selected(profile.id)
        self._apply_project_profile(profile, mark_used=False)

    def _rename_project_profile(self) -> None:
        profile = self.current_project_profile
        if profile is None:
            return
        name, accepted = QInputDialog.getText(self, tr('重命名方案'), tr('方案名称：'), text=profile.name)
        if not accepted or not name.strip():
            return
        try:
            profile = self.profile_store.rename(profile.id, name.strip())
        except ValueError as exc:
            QMessageBox.information(self, tr('无法重命名'), str(exc))
            return
        self.current_project_profile = profile
        self._refresh_project_profile_combo(profile.id)

    def _update_project_profile(self) -> bool:
        profile = self.current_project_profile
        if profile is None:
            self._new_project_profile()
            return False
        try:
            profile = self.profile_store.update(profile.id, **self._profile_configuration())
            self.profile_store.set_last_selected(profile.id)
        except (OSError, ValueError) as exc:
            bind_text(self.profile_recommendation, '方案保存失败：{exc}', exc=exc)
            return False
        self.current_project_profile = profile
        self._asr_config_dirty = False
        self._refresh_project_profile_combo(profile.id)
        bind_text(self.profile_recommendation, translate('已更新方案：', getattr(self, '_ui_language', current_language())) + profile.name)
        return True

    def _delete_project_profile(self) -> None:
        profile = self.current_project_profile
        if profile is None:
            return
        answer = QMessageBox.question(self, tr('删除方案'), tr('删除“{value0}”？模型文件不会被删除。', value0=profile.name))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.profile_store.delete(profile.id)
        self.current_project_profile = None
        self._refresh_project_profile_combo()
        bind_text(self.profile_recommendation, translate('方案已删除；当前配置仍保留。', getattr(self, '_ui_language', current_language())))

    def _show_project_profile_menu(self) -> None:
        menu = QMenu(self)
        new_action = menu.addAction(_icon("fa5s.plus"), "新建")
        save_as_action = menu.addAction(_icon("fa5s.copy"), "另存为")
        update_action = menu.addAction(_icon("fa5s.save"), "更新当前 Profile")
        rename_action = menu.addAction(_icon("fa5s.pen"), "重命名")
        delete_action = menu.addAction(_icon("fa5s.trash-alt"), "删除")
        has_profile = self.current_project_profile is not None
        for action in (update_action, rename_action, delete_action):
            action.setEnabled(has_profile)
        chosen = menu.exec(self.project_profile_manage.mapToGlobal(self.project_profile_manage.rect().bottomLeft()))
        callbacks = {
            new_action: self._new_project_profile,
            save_as_action: self._save_project_profile_as,
            update_action: self._update_project_profile,
            rename_action: self._rename_project_profile,
            delete_action: self._delete_project_profile,
        }
        callback = callbacks.get(chosen)
        if callback:
            callback()

    def _apply_recognition_plan_from_ui(self, _index: int = -1) -> None:
        if getattr(self, "_applying_recognition_plan", False) or getattr(self, "_applying_profile", False):
            return
        key = str(self.recognition_mode_combo.currentData() or "custom")
        plan = recognition_plan(key)
        if key != "custom" and all(hasattr(self, name) for name in ("primary_asr_backend", "firered_asr_backend", "qwen_asr_backend")):
            self._applying_recognition_plan = True
            try:
                if plan.language and self.__dict__.get("recognition_language") is not None:
                    # 日语 / 外语 also set the spoken language (2026-10-14); 外语 keeps a
                    # foreign language already chosen and starts at English otherwise.
                    current = str(self.recognition_language.currentData() or "auto")
                    wanted = plan.language if plan.language != FOREIGN else (current if plan.for_language(current) else "en")
                    language_index = self.recognition_language.findData(wanted)
                    if language_index >= 0:
                        self.recognition_language.setCurrentIndex(language_index)
                # API 转写 times Chinese with FireRedASR2 and other languages (or a
                # computer without an NVIDIA GPU) with Qwen3 对齐 (2026-10-23).
                spoken = (self._subtitle_language_options()["recognition_language"]
                          if self.__dict__.get("recognition_language") is not None else "")
                host = self.__dict__.get("_home_host_profile")
                if host is None:
                    from ..recognition.recognition_choices import host_profile
                    host = self._home_host_profile = host_profile()
                primary, timeline, review = plan.backends(spoken, host)
                self._set_backend_combo(self.primary_asr_backend, primary)
                self._set_backend_combo(self.firered_asr_backend, timeline)
                self._set_backend_combo(self.qwen_asr_backend, review)
                if plan.language == "ja":
                    try:
                        from ..recognition.ctc_alignment import set_enabled
                        set_enabled(True, self.legacy.RUNTIME_SETTINGS)
                    except (OSError, RuntimeError, ValueError):
                        pass  # the plan's backends still apply; the workshop card shows the switch
                if plan.api_provider and self.__dict__.get("qwen_asr_api_provider") is not None:
                    provider_index = self.qwen_asr_api_provider.findData(plan.api_provider)
                    if provider_index >= 0:
                        self.qwen_asr_api_provider.setCurrentIndex(provider_index)
                    self._apply_asr_preset_fields(plan.api_provider)
            finally:
                self._applying_recognition_plan = False
            self._mark_asr_configuration_dirty()
            self._refresh_asr_summary()
            if plan.api_provider:
                self._remind_plan_api_key(plan)
        self._refresh_recognition_recommendation()

    def _show_plan_choice(self, key: str) -> None:
        """Select ``key`` in the plan menu without applying it.

        2026-10-23 (user): the menu lists 本地识别 / API 转写 / 日语 / 外语 only;
        自定义 is added while the models match none of them and removed after.
        """
        combo = self.recognition_mode_combo
        combo.blockSignals(True)
        try:
            custom = combo.findData("custom")
            if key == "custom" and custom < 0:
                combo.addItem(recognition_plan("custom").label, "custom")
            elif key != "custom" and custom >= 0:
                combo.removeItem(custom)
            index = combo.findData(key)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _remind_plan_api_key(self, plan) -> None:
        """A cloud plan without its saved key opens the key guide (2026-10-22, user:
        「使用后要提醒配置」). Once per plan and session; a saved key stays silent."""
        from ..providers.llm_config import read_asr_api_key
        url = self.qwen_asr_api_url.text().strip() if self.__dict__.get("qwen_asr_api_url") is not None else ""
        if read_asr_api_key(plan.api_provider, url)[0]:
            return
        reminded = self.__dict__.setdefault("_plan_key_reminded", set())
        if plan.key in reminded:
            return
        reminded.add(plan.key)
        QTimer.singleShot(0, lambda: self._open_api_setup_guide(plan.api_provider))

    def _refresh_recognition_recommendation(self) -> None:
        if not hasattr(self, "recognition_mode_combo"):
            return
        primary, timeline, review = self._shown_asr_backends()
        language = (self._subtitle_language_options()["recognition_language"]
                    if self.__dict__.get("recognition_language") is not None else "")
        provider = (str(self.qwen_asr_api_provider.currentData() or "")
                    if self.__dict__.get("qwen_asr_api_provider") is not None else None)
        key = matching_plan(primary, timeline, review, language, provider=provider)
        blocker = bool(getattr(self, "_applying_recognition_plan", False))
        if not blocker:
            self._show_plan_choice(key)
        profile = lightweight_media_profile(self.media_paths)
        recommended = recognition_plan(str(profile["recommended_plan"]))
        current = recognition_plan(key)
        bind_text(self.recognition_plan_hint, '{value0} · 预计显存约 {value1:.1f} GB。{value2}', value0=current.description, value1=current.estimated_vram_gb, value2=f' 当前素材更推荐：{recommended.label}。' if recommended.key != key and self.media_paths else '')
        if hasattr(self, "profile_recommendation"):
            if self.current_project_profile is not None:
                bind_text(self.profile_recommendation, '当前使用：{value0}', value0=self.current_project_profile.name)
            else:
                suggested, reason = self.profile_store.recommend(
                    self.media_paths,
                    glossary_ids=self._enabled_glossary_ids(),
                )
                if suggested is not None:
                    bind_text(self.profile_recommendation, '最近用于类似素材：{value0} · {reason}，可从上方一键采用。', value0=suggested.name, reason=reason)
                elif key == "custom":
                    bind_text(self.profile_recommendation, '这套自定义配置可从右侧菜单保存为方案。')
                else:
                    self.profile_recommendation.clear()

    def _home_page_active(self) -> bool:
        stack = getattr(self, "pages", None)
        current = stack.currentIndex() if stack is not None else 0
        modal = getattr(self, "_modal_host", None)
        return current == 0 and not (modal is not None and modal.isVisible())

    def _open_feature_search(self):
        from .feature_search import open_feature_search
        open_feature_search(self)

    def _choose_media(self):
        if self._run_in_progress or (self.worker is not None and self.worker.isRunning()):
            QMessageBox.information(self, tr('任务运行中'), tr('当前任务正在处理，请结束后再重新选择素材。'))
            return
        paths = _select_media_paths(self)
        if paths:
            self.import_media(paths, replace=True)

    def import_media(self, paths, *, replace=False):
        from .desktop_intake import DesktopIntake
        if not hasattr(self, "_desktop_intake"):
            self._desktop_intake = DesktopIntake(self)
        self._desktop_intake.submit(paths, replace=replace)

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        from .external_open import classify_open_paths
        accepted = [path for kind, path in classify_open_paths(paths) if kind != 'unsupported']
        if accepted:
            event.acceptProposedAction()
            self.drop_overlay.set_file_count(len(accepted))
            self._set_drop_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        from .external_open import classify_open_paths
        accepted = [path for kind, path in classify_open_paths(paths) if kind != 'unsupported']
        if accepted:
            self.drop_overlay.set_file_count(len(accepted))
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        from .external_open import classify_open_paths
        accepted = [path for kind, path in classify_open_paths(paths) if kind != 'unsupported']
        self._set_drop_active(False)
        if not accepted:
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            code = getattr(self, "_ui_language", "zh")
            QMessageBox.information(
                self,
                translate('任务运行中', code),
                translate('当前任务正在处理，请结束后再拖入新素材。', code),
            )
            event.ignore()
            return
        # 追加而非替换：提示文案是“可继续拖入另一批素材”，第二批应与第一批合并
        self.import_media(paths)
        event.acceptProposedAction()

    def _restore_glossary_switch(self):
        settings = self.legacy.RUNTIME_SETTINGS.get("glossary", {})
        with QSignalBlocker(self.terms):
            self.terms.setChecked(bool(settings.get("enable_domain_terms", False)))
        self._refresh_glossary_chips()

    def _task_glossary_selection(self):
        context = getattr(self, "_studio_recognition_context", None) or {}
        if "enabled_glossary_ids" in context:
            ids = tuple(context["enabled_glossary_ids"])
            checked = bool(context.get("enable_domain_terms", bool(ids)))
            return ids if checked else (), checked
        ids = tuple(self._enabled_glossary_ids())
        checked = self.terms.isChecked()
        return ids if checked else (), checked

    def _auto_enable_terms(self, value: str):
        # Editing the content name must preserve an explicit OFF choice.
        self._resolve_glossary_binding()

    def _resolve_glossary_binding(self) -> dict:
        name = self.legacy.canonicalize_runtime_game_name(self.game_box.currentText())
        resolver = GlossaryBindingResolver(self.legacy)
        content_id = self.game_box.currentData() if self.game_box.currentText() == self.game_box.itemText(self.game_box.currentIndex()) else ""
        result = resolver.resolve(name, str(content_id or name), self.terms.isChecked())
        self._glossary_binding = result
        if self.terms.isChecked():
            settings = self.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
            settings["enabled_glossary_ids"] = list(dict.fromkeys([*self._enabled_glossary_ids(), *result["active_glossaries"]]))
        self._save_glossary_settings()
        if hasattr(self, "_refresh_glossary_chips"):
            self._refresh_glossary_chips()
        return result

    def _refresh_content_choices(self):
        """Refresh the small catalog on library mutations, preserving content and batch."""
        if not hasattr(self, "game_box"):
            return
        text = self.game_box.currentText()
        identity = self.game_box.currentData()
        catalog = getattr(self.legacy, "glossary_catalog", lambda: [])() or []
        self.game_box.blockSignals(True)
        try:
            self.game_box.clear()
            seen = set()
            for row in catalog:
                key = str(row.get("id", ""))
                if key and key not in seen:
                    self.game_box.addItem(str(row.get("name", key)), key)
                    seen.add(key)
            resolve = getattr(self.legacy, "resolve_glossary_identity", self.legacy.runtime_game_identity)
            for name in self.legacy.load_runtime_game_history():
                key = str(resolve(name) or self.legacy.runtime_game_identity(name))
                if key and key not in seen:
                    self.game_box.addItem(str(name), key)
                    seen.add(key)
            index = self.game_box.findData(identity) if identity else -1
            if index >= 0:
                self.game_box.setCurrentIndex(index)
            else:
                self.game_box.setCurrentIndex(-1)
                self.game_box.setEditText(text)
        finally:
            self.game_box.blockSignals(False)
        self._refresh_glossary_chips()
        refresh_picks = getattr(self, "_refresh_content_quick_picks", None)
        if callable(refresh_picks):
            refresh_picks()

    def _refresh_content_quick_picks(self) -> None:
        """Reload the recent content names (library / history mutations)."""
        try:
            self._content_quick_names = list(self.legacy.load_runtime_game_history())[:6]
        except (OSError, ValueError, TypeError, AttributeError):
            self._content_quick_names = []
        self._sync_content_quick_picks()

    def _sync_content_quick_picks(self, *_args) -> None:
        picks = getattr(self, "content_quick_picks", None)
        if picks is None:
            return
        current = self.legacy.canonicalize_runtime_game_name(self.game_box.currentText())
        picks.set_items(getattr(self, "_content_quick_names", []), current)

    def _build_subtitle_language_row(self, layout):
        """Spoken language and subtitle output, chosen before a task starts.

        2026-10-21 (user: three dropdowns that all pick a language, and none
        says which is the speech and which the subtitles): every dropdown has a
        caption — 视频里说的话 → 字幕显示 (翻译成 only while translating), 标点 —
        the output choices name no language, and one line under the row says
        what the subtitles will show.

        2026-10-23 (home design A): each dropdown is a filled field with its
        caption inside and a round chevron; an arrow chip joins the spoken
        language to the subtitles, and the summary is a pill with an eye.
        """
        from .home_widgets import LanguageField
        label = QLabel("字幕语言与输出")
        label.setObjectName("homeLanguageTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row = QHBoxLayout()
        row.setSpacing(10)

        def column(caption, widget, stretch=0, into=None):
            """One filled field: the caption inside, over its dropdown."""
            box = LanguageField(caption, widget)
            (into if into is not None else row).addWidget(box, stretch)
            return box

        # One row with its own title (home C′, 2026-10-17).
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)
        saved = dict((self.legacy.RUNTIME_SETTINGS or {}).get("subtitle_language") or {})
        self.recognition_language = FramelessPopupCombo()
        # 简体中文 / 繁体中文 (2026-10-19): one Chinese recognition; "zh-Hant" is
        # saved as recognition_language "zh" + chinese_script "zh-Hant".
        for text, value in (("自动识别语言", "auto"), ("简体中文", "zh"), ("繁体中文", "zh-Hant"),
                            ("日语", "ja"), ("英语", "en"), ("韩语", "ko"), ("西班牙语", "es"), ("德语", "de"),
                            ("法语", "fr"), ("葡萄牙语", "pt"), ("意大利语", "it"), ("俄语", "ru")):
            self.recognition_language.addItem(tr(text), value)
        if saved.get("recognition_language") == "zh" and saved.get("chinese_script") == "zh-Hant":
            saved["recognition_language"] = "zh-Hant"
        self.subtitle_output = FramelessPopupCombo()
        for text, value in (("只显示原文", "original"), ("原文 + 翻译（双语）", "bilingual"), ("只显示翻译", "translation")):
            self.subtitle_output.addItem(tr(text), value)
        # Translation target (any language other than the source, 2026-10-14);
        # native names like the UI language menu. Refilled by _sync_translation_targets.
        self.translation_script = user_text(FramelessPopupCombo())
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, TARGETS
        for value in TARGETS:
            self.translation_script.addItem(TARGET_LABELS[value], value)
        for combo, key, default in ((self.recognition_language, "recognition_language", "auto"),
                                    (self.subtitle_output, "output", "original"),
                                    (self.translation_script, "translation_script", "zh-Hans")):
            combo.setCurrentIndex(max(0, combo.findData(saved.get(key, default))))
            combo.setObjectName("homeLanguageCombo")
        self.spoken_language_field = column("视频里说的话", self.recognition_language, 1)
        arrow = QLabel()
        arrow.setObjectName("homeLanguageArrow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ui_zoom.set_size(arrow, fixed_w=30, fixed_h=30)
        self.home_language_arrow = arrow
        row.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        # 字幕显示 and 翻译成 in one box (the tutorial points at both at once).
        self.subtitle_output_fields = QWidget()
        self.subtitle_output_fields.setObjectName("homeLanguageGroup")
        output_row = QHBoxLayout(self.subtitle_output_fields)
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(10)
        output_box = column("字幕显示", self.subtitle_output, 1, output_row)
        self.subtitle_output_caption = output_box.caption
        self.translation_field = column("翻译成", self.translation_script, 1, output_row)
        row.addWidget(self.subtitle_output_fields, 2)
        self._subtitle_language_row = row
        # 2026-10-13: punctuation default for new tasks (display/export only).
        from ..subtitle_rules.punctuation_style import MODE_ADD, MODE_NONE, MODE_ORIGINAL, default_mode_for_new_tasks
        self.subtitle_punctuation = FramelessPopupCombo()
        self.subtitle_punctuation.setObjectName("homeLanguageCombo")
        for text, value in (("保留原文", MODE_ORIGINAL), ("添加标点", MODE_ADD), ("不加标点", MODE_NONE)):
            self.subtitle_punctuation.addItem(tr(text), value)
        self.subtitle_punctuation.setCurrentIndex(max(0, self.subtitle_punctuation.findData(
            default_mode_for_new_tasks(self.legacy.RUNTIME_SETTINGS))))
        bind_text(self.subtitle_punctuation, '新任务的字幕标点；文稿不变，工作台里随时能换', property='toolTip')
        self.punctuation_field = column("标点", self.subtitle_punctuation, 1)
        bind_text(self.recognition_language, '自动：按转写里的文字判断说的是哪种语言（只有汉字不算日语证据）。中文以外的语言都改用 Qwen3-ForcedAligner 对齐字词时间，需在模型工坊下载。', property='toolTip')
        bind_text(self.subtitle_output, '译文/双语：识别完成后用已配置的 AI 文字服务把字幕翻成所选语言（只发送字幕文字，不发送音频）；原文、说话人和时间保持不变。', property='toolTip')
        bind_text(self.translation_script, '译文语言', property='toolTip')
        # Long choices (German, Russian…) must not widen the page: the dropdowns may shrink and
        # elide in a narrow window; the open list always shows the whole text.
        for combo in (self.recognition_language, self.subtitle_output, self.translation_script, self.subtitle_punctuation):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        layout.addLayout(row)
        from .home_widgets import MarkedPill
        self.subtitle_language_summary = MarkedPill(mark="fa5s.eye")
        self.subtitle_language_summary.setObjectName("homeLanguageSummary")
        layout.addWidget(self.subtitle_language_summary, 0, Qt.AlignmentFlag.AlignLeft)
        self.subtitle_language_hint = QLabel("")
        self.subtitle_language_hint.setObjectName("homeTermState")
        self.subtitle_language_hint.setWordWrap(True)
        layout.addWidget(self.subtitle_language_hint)
        self.aligner_download_button = AnimatedButton("去模型工坊下载 Qwen3-ForcedAligner（约 1.8 GB）")
        self.aligner_download_button.setObjectName("homeHeaderAction")
        self.aligner_download_button.clicked.connect(self._open_aligner_in_workshop)
        self.aligner_download_button.hide()
        layout.addWidget(self.aligner_download_button)
        for combo in (self.recognition_language, self.subtitle_output, self.translation_script, self.subtitle_punctuation):
            combo.currentIndexChanged.connect(self._subtitle_language_changed)
        self._subtitle_language_changed(save=False)

    def _subtitle_language_options(self):
        if self.__dict__.get("recognition_language") is None:
            saved = dict((self.legacy.RUNTIME_SETTINGS or {}).get("subtitle_language") or {})
            spoken = saved.get("recognition_language", "auto")
            return {"recognition_language": spoken,
                    "chinese_script": ("zh-Hant" if spoken == "zh" and saved.get("chinese_script") == "zh-Hant"
                                       else "zh-Hans"),
                    "subtitle_output": saved.get("output", "original") if _ai_unlocked(self) else "original",
                    "translation_script": saved.get("translation_script", "zh-Hans")}
        choice = str(self.recognition_language.currentData() or "auto")
        return {"recognition_language": "zh" if choice == "zh-Hant" else choice,
                "chinese_script": "zh-Hant" if choice == "zh-Hant" else "zh-Hans",
                "subtitle_output": str(self.subtitle_output.currentData() or "original"),
                "translation_script": str(self.translation_script.currentData() or "zh-Hans")}

    def _sync_translation_targets(self, recognition_language):
        """Offer only targets in another language than a chosen source (all for auto)."""
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, TARGETS, targets_for
        combo = self.translation_script
        wanted = TARGETS if recognition_language == "auto" else targets_for(recognition_language)
        if tuple(combo.itemData(index) for index in range(combo.count())) == tuple(wanted):
            return
        current = str(combo.currentData() or "zh-Hans")
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            for value in wanted:
                combo.addItem(TARGET_LABELS[value], value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        finally:
            combo.blockSignals(blocked)

    def _subtitle_language_changed(self, *_args, save=True):
        if self.__dict__.get("recognition_language") is not None:
            self._sync_translation_targets(self._subtitle_language_options()["recognition_language"])
        options = self._subtitle_language_options()
        if save and hasattr(self, "recognition_plan_hint"):
            self._refresh_recognition_recommendation()  # 日语/英语推荐 follow the language
        if save and hasattr(self, "recognition_plan"):
            self._refresh_asr_summary()   # the timeline card names the model for this language
        translating = options["subtitle_output"] != "original"
        self.translation_script.setEnabled(translating)
        # 2026-10-21: 翻译成 shows only while translating; the output choices name
        # no language — the line under the row says it in words.
        field = self.__dict__.get("translation_field")
        if field is not None:
            field.setVisible(translating)
            self._subtitle_language_row.setStretchFactor(self.subtitle_output_fields, 2 if translating else 1)
        summary = self.__dict__.get("subtitle_language_summary")
        if summary is not None:
            from ..subtitle_rules.subtitle_translation import TARGET_LABELS
            spoken = (tr("视频原文") if options["recognition_language"] == "auto" and options["chinese_script"] != "zh-Hant"
                      else tr("{value0}原文", value0=self.recognition_language.currentText()))
            target = TARGET_LABELS.get(options["translation_script"], "")
            shows = {"original": spoken,
                     "bilingual": tr("{value0} + {value1}翻译", value0=spoken, value1=target),
                     "translation": tr("{value0}翻译", value0=target)}.get(options["subtitle_output"], spoken)
            summary.setText(tr("字幕会显示：{value0}", value0=shows))
        hints = []
        aligner_missing = False
        timeline = self.__dict__.get("firered_asr_backend")
        timeline_enabled = timeline is None or str(timeline.currentData()) != "off"
        from ..subtitle_rules.european_text import LABELS as european_labels
        if timeline_enabled and options["recognition_language"] != "zh":
            try:
                from ..recognition.asr import resolve_qwen_aligner_local_source
                aligner_missing = not resolve_qwen_aligner_local_source()
            except Exception:
                aligner_missing = False
        if not timeline_enabled and options["recognition_language"] not in ("zh", "auto"):
            hints.append("字幕时间轴已关闭；不会运行字词对齐或日语 CTC 句首校正。")
        if timeline_enabled and options["recognition_language"] == "ja":
            try:
                from ..recognition.ctc_alignment import enabled as ctc_enabled, model_dir as ctc_model_dir
                timeline = self.__dict__.get("firered_asr_backend")
                ctc_runs = bool((timeline is None or str(timeline.currentData()) != "off")
                                and ctc_enabled(self.legacy.RUNTIME_SETTINGS) and ctc_model_dir())
            except Exception:  # noqa: BLE001
                ctc_runs = False
            hints.append("日语：不送中文时间轴模型；字词时间由 Qwen3-ForcedAligner 对齐，句首再由日语 CTC 对齐模型校正。"
                         if ctc_runs else "日语：不送中文时间轴模型；字词时间由 Qwen3-ForcedAligner 对齐。")
        if timeline_enabled and options["recognition_language"] == "en":
            hints.append("英语：按单词断句，单词之间保留空格；单词时间由 Qwen3-ForcedAligner 对齐。")
        if timeline_enabled and options["recognition_language"] == "ko":
            hints.append(tr("韩语：按词断句，词之间保留空格；字词时间由 Qwen3-ForcedAligner 对齐。"))
        if timeline_enabled and options["recognition_language"] in european_labels:
            hints.append(tr("{value0}：按单词断句，单词之间保留空格；单词时间由 Qwen3-ForcedAligner 对齐。",
                            value0=tr(european_labels[options["recognition_language"]])))
        if options["chinese_script"] == "zh-Hant":
            hints.append(tr("繁体中文：照常按中文识别，完成后在本机把字幕转成繁体字；只换字形，不改用词。"))
        if aligner_missing and options["recognition_language"] == "ja":
            hints.append("还没有安装 Qwen3-ForcedAligner：日语字幕将没有字词时间（剃刀只能按估算切），不会悄悄改用估算冒充。")
        if aligner_missing and options["recognition_language"] == "en":
            hints.append("还没有安装 Qwen3-ForcedAligner：英文字幕将没有单词时间（剃刀只能按估算切），不会悄悄改用估算冒充。")
        if aligner_missing and options["recognition_language"] == "ko":
            hints.append(tr("还没有安装 Qwen3-ForcedAligner：韩语字幕将没有字词时间（剃刀只能按估算切），不会悄悄改用估算冒充。"))
        if aligner_missing and options["recognition_language"] in european_labels:
            hints.append(tr("还没有安装 Qwen3-ForcedAligner：{value0}字幕将没有单词时间（剃刀只能按估算切），不会悄悄改用估算冒充。",
                            value0=tr(european_labels[options["recognition_language"]])))
        self.aligner_download_button.setVisible(aligner_missing and options["recognition_language"] not in ("zh", "auto"))
        if translating:
            # 2026-10-21: plain words, and the key it needs said where the choice is made.
            try:
                from ..providers.llm_config import text_ai_key_missing
                no_key = text_ai_key_missing(self.legacy.RUNTIME_SETTINGS, "polish")
            except Exception:  # noqa: BLE001
                no_key = False
            hints.append(tr("还没填 API Key：先在上面「AI 智能断句」点「连接 AI」填好，才能翻译。") if no_key
                         else tr("翻译由 AI 完成，只发送字幕文字（可能产生少量费用）；说的话和译文是同一种语言时不翻译。"))
        saved_output = str(((self.legacy.RUNTIME_SETTINGS or {}).get("subtitle_language") or {}).get("output")
                           or "original")
        if not _ai_unlocked(self) and saved_output != "original":
            hints.append(tr("你选的翻译要先连接 AI（填 API Key 并测试连接）才会生效，现在只显示原文。"))
        punctuation = str(self.subtitle_punctuation.currentData() or "original") \
            if self.__dict__.get("subtitle_punctuation") is not None else "original"
        if punctuation != "original":
            from ..subtitle_rules.punctuation_style import preview_rows
            sample = preview_rows(None, punctuation, limit=1)[0][1]
            hints.append(tr("标点效果：{value0}", value0=sample))
        bind_text(self.subtitle_language_hint, " ".join(str(hint) for hint in hints))
        self.subtitle_language_hint.setVisible(bool(hints))
        if save:
            try:
                section = self.legacy.RUNTIME_SETTINGS.setdefault("subtitle_language", {})
                section.update(recognition_language=options["recognition_language"],
                               chinese_script=options["chinese_script"],
                               # locked (no connected AI): "只显示原文" is shown, the choice is kept
                               output=(options["subtitle_output"] if _ai_unlocked(self)
                                       else section.get("output", "original")),
                               translation_script=options["translation_script"])
                self.legacy.RUNTIME_SETTINGS.setdefault("switches", {})["subtitle_punctuation"] = punctuation
                save_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            except Exception:
                pass

    def _open_aligner_in_workshop(self):
        self._open_model_workshop()
        view = getattr(self.workshop_page, "_view_model", None)
        if callable(view):
            try:
                view("qwen_aligner")
            except Exception:
                pass

    def _pick_recent_content(self, name: str) -> None:
        index = self.game_box.findText(name)
        if index >= 0:
            self.game_box.setCurrentIndex(index)
        else:
            self.game_box.setEditText(name)

    def _asr_values(self):
        provider = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
        preset = ASR_API_PRESETS.get(provider)
        protocol = (preset["protocol"] if preset else
                    self.legacy.RUNTIME_SETTINGS["models"].get("qwen_asr_api_protocol", ""))
        return {
            "speaker_source": str(self.speaker_source.currentData() or 'native'),
            "primary_asr_backend": str(self.primary_asr_backend.currentData()),
            "qwen_asr_backend": str(self.qwen_asr_backend.currentData()),
            "qwen_asr_model": self.legacy.RUNTIME_SETTINGS["models"].get(
                "qwen_asr_model", "Qwen/Qwen3-ASR-1.7B"
            ),
            "qwen_asr_api_provider": provider,
            "qwen_asr_api_protocol": protocol,
            "qwen_asr_api_model": self.qwen_asr_api_model.text().strip(),
            "qwen_asr_api_url": self.qwen_asr_api_url.text().strip(),
            "firered_asr_backend": str(self.firered_asr_backend.currentData()),
            "api_transcribe_style": str(
                getattr(self, "api_transcribe_style", None) and
                self.api_transcribe_style.currentData() or "clean"
            ),
        }

    # ------------------------------------------------------------------
    # Inline Help / Popover for ASR API (preferred over large modal tutorials)
    # ------------------------------------------------------------------
    def _show_qwen_asr_api_inline_help(self):
        """Compact popover triggered by ⓘ. Click outside or press Esc to dismiss.
        Contains a '查看完整教程' action that opens a properly styled dialog.
        """
        btn = self.qwen_api_help_button
        provider = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
        label = ASR_API_PRESETS.get(provider, ASR_API_PRESETS["qwen31_filetrans"])["label"]

        pop = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        pop.setObjectName("apiHelpPopover")
        pop.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        pop.setStyleSheet(api_help_popover_qss(theme_definition(theme_key())))

        v = QVBoxLayout(pop)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        # Header row with provider + close X
        head = QHBoxLayout()
        head.setSpacing(6)
        title = bind_text(QLabel(), '<b>API 帮助</b> · {label}', label=label)
        title.setObjectName("muted")
        head.addWidget(title, 1)

        xbtn = QPushButton("×")
        xbtn.setObjectName("helpCloseX")
        xbtn.setFixedSize(22, 22)
        xbtn.setCursor(Qt.CursorShape.PointingHandCursor)
        xbtn.clicked.connect(pop.close)
        head.addWidget(xbtn, 0)
        v.addLayout(head)

        # Concise bullets (per user spec)
        bullets = QLabel(
            "• API：通过服务商在线转写音频（OpenAI 兼容或 DashScope 协议）。\n"
            "• 去哪里申请：各服务商控制台创建 Key（阿里百炼 / Groq / OpenAI 等）。\n"
            "• 是否收费：按服务商计费（通常按音频时长或 token）。\n"
            "• 是否需要联网：需要联网；识别时把音频发往服务商。\n"
            f"• {credential_storage_notice()}"
        )
        bullets.setWordWrap(True)
        bullets.setStyleSheet("font-size: 13px; line-height: 1.35;")
        v.addWidget(bullets)

        # Actions row
        row = QHBoxLayout()
        row.addStretch(1)
        full = QPushButton("查看完整教程")
        full.setObjectName("helpLink")
        full.setCursor(Qt.CursorShape.PointingHandCursor)
        full.clicked.connect(lambda: (pop.close(), self._open_api_setup_guide(provider)))
        row.addWidget(full)

        doc = QPushButton("服务商文档")
        doc.setObjectName("helpLink")
        doc.setCursor(Qt.CursorShape.PointingHandCursor)
        def _open_doc():
            urls = {
                "dashscope": QWEN_API_KEY_HELP_URL,
                "groq": "https://console.groq.com/docs/speech-to-text",
                "openai": "https://platform.openai.com/docs/guides/speech-to-text",
                "custom": "https://platform.openai.com/docs/api-reference/audio/createTranscription",
            }
            QDesktopServices.openUrl(QUrl(urls.get(provider, urls["dashscope"])))
            pop.close()
        doc.clicked.connect(_open_doc)
        row.addWidget(doc)
        v.addLayout(row)

        # Position near the ⓘ button
        pop.adjustSize()
        gp = btn.mapToGlobal(btn.rect().bottomLeft())
        pop.move(gp + QPoint(0, 6))
        pop.show()
        pop.raise_()

    def _open_asr_api_full_tutorial_dialog(self, provider: str):
        """Styled, non-system dialog for the full tutorial content. Has a real close X."""
        dlg = SpringDialog(self)
        bind_text(dlg, 'ASR API 设置 · 完整说明', property='windowTitle')
        dlg.resize(520, 420)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(bind_text(QLabel(), '<b>当前选择</b>：{value0}', value0=ASR_API_PRESETS.get(provider, ASR_API_PRESETS['qwen31_filetrans'])['label']), 1)
        x = QPushButton("×")
        x.setObjectName("helpCloseX")
        x.setFixedSize(26, 26)
        tutorial_theme = theme_definition(theme_key())
        x.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 0; color: {tutorial_theme.text_muted}; font-size: 18px; }} "
            f"QPushButton:hover {{ color: {tutorial_theme.text}; }}"
        )
        x.clicked.connect(dlg.reject)
        header.addWidget(x)
        lay.addLayout(header)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setObjectName("muted")
        body.setStyleSheet(
            f"QTextEdit {{ background: {tutorial_theme.surface_input}; color: {tutorial_theme.text};"
            f" border: 1px solid {tutorial_theme.border}; border-radius: 8px; padding: 10px; }}"
        )
        body.setPlainText(
            "1. 在所选服务商控制台创建并复制 API Key。\n"
            "2. 回到这里选择“API（更快、免下载，需配置 Key）”。\n"
            "3. 选择 API 服务；程序会预填模型名和地址，再粘贴对应 Key。\n"
            f"4. 点击“保存识别后端”。{credential_storage_notice()}\n\n"
            "本地版：通常更准确、增加独立文字和词汇证据，但约 4.7 GB，且占用 CUDA 显存。\n"
            "API 版：启动和处理更快、无需下载模型，但需要联网、账户额度与自行配置 Key。\n\n"
            "提示：常用说明使用 ⓘ 悬停/点击的轻量提示；只有复杂流程才打开本窗口。"
        )
        lay.addWidget(body, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        ok = AnimatedButton("知道了")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(ok)
        lay.addLayout(btns)

        dlg.exec()

    def _asr_api_provider_changed(self, *_args):
        provider = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
        # 四十一轮：切回用户已保存过的服务时恢复其保存的模型/地址，
        # 不强制刷回预设值（自定义工作台域名等用户输入必须留住）。
        self._apply_asr_preset_fields(provider)
        self._mark_asr_configuration_dirty()
        # After preset change, try to show cached models for the new base if available.
        QTimer.singleShot(0, self, self._try_restore_asr_models_from_cache)

    # ------------------------------------------------------------------
    # P0-4: Auto-fetch models from OpenAI-compatible /v1/models
    # ------------------------------------------------------------------
    def _fetch_asr_models(self):
        provider = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
        if provider in {'spark_asr_v2','qwen31_filetrans','qwen_cloud_filetrans'}:
            self.qwen_models_status.setVisible(True)
            bind_text(self.qwen_models_status, '原生接口无模型列表；按官方固定型号调用，实际识别尚需验证。')
            return
        base = self.qwen_asr_api_url.text().strip()
        typed_key = self.qwen_asr_api_key.text().strip()
        persisted, _ = read_api_key(provider, base)
        key = typed_key or persisted
        if not base:
            self.qwen_models_status.setVisible(True)
            bind_text(self.qwen_models_status, '请先填写 API 地址后再获取模型列表。')
            return
        self.qwen_fetch_models_btn.setEnabled(False)
        self.qwen_models_status.setVisible(True)
        bind_text(self.qwen_models_status, '正在获取模型列表…')
        # Kick off worker
        self._asr_models_worker = AsrModelsFetchWorker(base, key)
        self._asr_models_worker.succeeded.connect(self._on_asr_models_fetched)
        self._asr_models_worker.failed.connect(self._on_asr_models_fetch_failed)
        self._asr_models_worker.start()

    def _on_asr_models_fetched(self, models: list[str]):
        self.qwen_fetch_models_btn.setEnabled(True)
        if not models:
            bind_text(self.qwen_models_status, '服务未返回模型列表，可直接手动填写。')
            self.qwen_models_combo.setVisible(False)
            return
        # cache
        prov = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
        set_cached_models(prov, self.qwen_asr_api_url.text().strip(), models)
        # populate UI
        self.qwen_models_combo.blockSignals(True)
        self.qwen_models_combo.clear()
        for m in models:
            self.qwen_models_combo.addItem(m)
        self.qwen_models_combo.blockSignals(False)
        self.qwen_models_combo.setVisible(True)
        # try to select current or first
        current = self.qwen_asr_api_model.text().strip()
        idx = -1
        if current:
            idx = self.qwen_models_combo.findText(current)
        if idx < 0:
            idx = 0
        if idx >= 0:
            self.qwen_models_combo.setCurrentIndex(idx)
            # also mirror into the canonical text field
            try:
                self.qwen_asr_api_model.setText(self.qwen_models_combo.currentText())
            except Exception:
                pass
        bind_text(self.qwen_models_status, '已获取 {value0} 个模型；选择后自动填入“API 模型”。如列表不全可手动填写。', value0=len(models))

    def _on_asr_models_fetch_failed(self, err: str):
        self.qwen_fetch_models_btn.setEnabled(True)
        self.qwen_models_combo.setVisible(False)
        # Keep a friendly message; manual entry remains available
        short = " ".join(str(err).split())[:120]
        bind_text(self.qwen_models_status, '自动获取失败：{short}；请直接在“API 模型（可手动）”填写。', short=short)

    def _try_restore_asr_models_from_cache(self):
        """If we have a cached list for current (provider, base), show the dropdown without network."""
        try:
            prov = str(self.qwen_asr_api_provider.currentData() or "qwen31_filetrans")
            base = self.qwen_asr_api_url.text().strip()
            if not base:
                return
            cached = get_cached_models(prov, base)
            if not cached:
                return
            self.qwen_models_combo.blockSignals(True)
            self.qwen_models_combo.clear()
            for m in cached:
                self.qwen_models_combo.addItem(m)
            self.qwen_models_combo.blockSignals(False)
            self.qwen_models_combo.setVisible(True)
            current = self.qwen_asr_api_model.text().strip()
            idx = self.qwen_models_combo.findText(current) if current else -1
            if idx >= 0:
                self.qwen_models_combo.setCurrentIndex(idx)
            self.qwen_models_status.setVisible(True)
            bind_text(self.qwen_models_status, '已从缓存载入 {value0} 个模型（最近成功获取）。', value0=len(cached))
        except Exception:
            pass

    def _apply_asr_backend_mode(self, *_args):
        api_mode = (
            self.qwen_asr_backend.currentData() == "api"
            or self.primary_asr_backend.currentData() == "api"
        )
        for widget in (
            self.qwen_api_provider_label,
            self.qwen_asr_api_provider,
            self.qwen_api_model_label,
            self.qwen_asr_api_model,
            self.qwen_api_url_label,
            self.qwen_asr_api_url,
            self.qwen_api_key_label,
            self.qwen_asr_api_key,
        ):
            widget.setEnabled(api_mode)
        self._refresh_asr_summary()

    def _shown_asr_backends(self) -> tuple[str, str, str]:
        """(primary, timeline, review) as the home page names them.

        2026-10-21: a saved choice whose files are still to come (云端识别's
        timeline model downloads after the tutorial) is shown as itself with
        需要下载, not as the 已关闭 / 未选择 its selector falls back to.
        2026-10-24: the plan menu reads the same; right after 云端识别 or 本地识别
        on a fresh install it said 自定义.
        """
        pending = dict(getattr(self, "_missing_saved_asr_backends", ()) or ())

        def shown(key, fallback):
            combo = getattr(self, key, None)   # the selectors are named after their setting
            current = str(combo.currentData() or "") if combo is not None else ""
            # Only while the selector still sits on the fallback it was given; a choice made since wins.
            return str(pending[key]) if key in pending and current == fallback else current

        return (shown("primary_asr_backend", "none"), shown("firered_asr_backend", "off"),
                shown("qwen_asr_backend", "off"))

    def recognition_role_state(self, backends=None, provider=None) -> dict:
        """Per role what the home card shows: effective backend, name, readiness and model.

        2026-10-23: one rule for the home cards and the Studio 识别字幕 sheet.
        The sheet passes its own ``backends`` (primary / timeline / review) and,
        for a plan with its own cloud service (MOSS Pro + Qwen 对齐), that
        ``provider``; without them the home selectors are read.
        """
        language = getattr(self, "_ui_language", current_language())
        # 短标签：角色卡 / 摘要共用的紧凑叫法。
        primary_short = {
            "moss": "MOSS",
            "firered": "FireRed",
            "qwen_local": translate("Qwen 本地", language),
            "firered_llm": "FireRed LLM",
            "whisper_turbo": "Whisper",
            "sensevoice": "SenseVoice",
            "paraformer": "Paraformer",
            "funasr_nano": "Fun-ASR Nano",
            "mlx_qwen3_asr": "Qwen3-ASR 0.6B",
            "mlx_qwen3_asr_1_7b": "Qwen3-ASR 1.7B",
            "api": translate("在线 API", language),
            "none": translate("未选择", language),
        }
        review_short = {
            "api": "Qwen API",
            "local": "Qwen3-ASR",
            "firered_llm": "FireRed LLM",
            "whisper_turbo": "Whisper",
            "sensevoice": "SenseVoice",
            "funasr_nano": "Fun-ASR Nano",
            "off": translate("已关闭", language),
        }
        timeline_short = {
            "local": "FireRedASR2-AED",
            "qwen_aligner": "Aligner",
            "mlx_qwen_aligner": "Aligner",
            "mfa_aligner": "MFA",
            "whisper_turbo": "Whisper",
            "paraformer": "Paraformer",
            "off": translate("已关闭", language),
        }
        models_cfg = dict(self.legacy.RUNTIME_SETTINGS.get("models", {}) or {})
        typed_key = self.qwen_asr_api_key.text()
        if provider and provider != str(models_cfg.get("qwen_asr_api_provider") or ""):
            preset = ASR_API_PRESETS.get(str(provider)) or {}
            models_cfg.update(qwen_asr_api_provider=str(provider), qwen_asr_api_model=str(preset.get("model") or ""),
                              qwen_asr_api_url=str(preset.get("url") or ""),
                              qwen_asr_api_protocol=str(preset.get("protocol") or ""))
            typed_key = ""  # the typed key belongs to the provider shown on home
        if backends is None:
            primary_backend, firered_backend, qwen_backend = self._shown_asr_backends()
        else:
            primary_backend = str(backends.get("primary") or "none")
            firered_backend = str(backends.get("timeline") or "off")
            qwen_backend = str(backends.get("review") or "off")
        if sys.platform == 'darwin':
            primary_short['sensevoice'] = 'SenseVoice · CPU'
            review_short['sensevoice'] = 'SenseVoice · CPU'
        # 主页角色卡在 API 生效时显示具体服务商 · 模型（三十三轮：要能
        # 看出当前用的是哪个 API）。
        if primary_backend == "api":
            from ..local_models.model_workshop import _api_combo_label

            api_label, _ready = _api_combo_label(models_cfg)
            primary_short["api"] = api_label
        from ..recognition.recognition_choices import cloud_asr_readiness
        key_ready, block_reason = cloud_asr_readiness(models_cfg, typed_key=typed_key)
        # 2026-10-14: the timeline card names what really runs for the spoken
        # language. Japanese and English never use the Chinese timeline model:
        # words are timed by Qwen3-ForcedAligner, and Japanese line starts are
        # then checked by the CTC aligner when it is installed and switched on
        # (moss_firered_pipeline). Before, the card kept saying FireRedASR2-AED
        # and the CTC model chosen in the workshop showed nowhere.
        # 2026-10-18: one rule (language_timeline) for the card, the model
        # picker and the workshop. When the chosen model is not used for this
        # language the card says why: the picker used to call FireRed current
        # while this card said Qwen3 对齐.
        from ..recognition.recognition_choices import language_timeline
        timeline_backend = firered_backend
        timeline_name = timeline_short.get(firered_backend, firered_backend)
        spoken = self._subtitle_language_options()["recognition_language"]
        timeline_note = None
        language_stage = language_timeline(firered_backend, spoken, self.legacy.RUNTIME_SETTINGS)
        if language_stage is not None:
            # 2026-10-19: the experimental MFA aligner runs Japanese itself;
            # (2026-10-28) the Apple Silicon aligner runs every language
            # (run_qwen_aligner_worker), so its own files are what count.
            runs_itself = firered_backend in {"mfa_aligner", "mlx_qwen_aligner"} and not language_stage["rerouted"]
            timeline_backend = firered_backend if runs_itself else "qwen_aligner"
            if language_stage["rerouted"]:
                from ..subtitle_rules.european_text import LABELS as european_labels
                if spoken in european_labels:
                    timeline_note = tr("字幕语言是{value1}，{value0} 只用于中文", value0=timeline_name,
                                       value1=tr(european_labels[spoken]))
                else:
                    timeline_note = tr({"ja": "字幕语言是日语，{value0} 只用于中文",
                                        "ko": "字幕语言是韩语，{value0} 只用于中文"}.get(
                                           spoken, "字幕语言是英语，{value0} 只用于中文"), value0=timeline_name)
            timeline_name = translate(language_stage["name"], language)
        timeline_short = dict(timeline_short, **{timeline_backend: timeline_name})
        installed = installed_model_keys(APP_ROOT)
        # The files each choice needs, from the selectors' own lists. A copy
        # kept here lacked the Apple Silicon (MLX) choices, so on a Mac the
        # downloaded Qwen3 aligner always said 需要下载 (2026-10-28).
        required = {role: {value: set(needs) for _label, value, needs in choices}
                    for role, choices in (("primary", PRIMARY_MODEL_CHOICES), ("review", REVIEW_MODEL_CHOICES),
                                          ("timeline", TIMELINE_MODEL_CHOICES))}

        # 2026-10-14: a component this computer cannot run (CUDA without an
        # NVIDIA GPU, MLX off Apple Silicon) is said before start, not after.
        from ..recognition.recognition_choices import host_profile, unavailable_on_host
        host = self.__dict__.get("_home_host_profile")
        if host is None:
            host = self._home_host_profile = host_profile()

        def _status(role: str, backend: str) -> tuple[str, str, str]:
            """(kind, status_text, tone)。tone: good/warn/muted。"""
            if backend == "off":
                return ("", "已关闭", "muted")
            if backend == "api":
                if key_ready:
                    return ("在线", "已配置", "good")
                return ("在线", "未配置", "warn")
            limit = unavailable_on_host(role, backend, host)
            if limit:
                return ("本地", limit, "warn")  # downloading would not help
            needs = required[role].get(backend)
            ready = bool(needs and needs <= installed)
            return ("本地", "已就绪" if ready else "需要下载", "good" if ready else "warn")

        from ..local_models.model_workshop import model_for_backend, model_role_line
        roles = {}
        for role, backend, labels in (
            ("primary", primary_backend, primary_short),
            ("timeline", timeline_backend, timeline_short),
            ("review", qwen_backend, review_short),
        ):
            kind, status, tone = _status(role, backend)
            if backend == "api" and status == "未配置":
                recovery = "配置 API"
            elif status in _HOST_LIMIT_STATUSES:
                recovery = _HOST_LIMIT_RECOVERY
            elif status == "需要下载":
                recovery = "安装模型"
            else:
                recovery = ""
            # 2026-10-18: logo, the line under the name and the language
            # badges come from the model this role really runs.
            model = model_for_backend(
                role, backend, str(models_cfg.get("qwen_asr_api_provider", "qwen31_filetrans")))
            line = model_role_line(model, role) if model is not None else None
            if line is not None and role == "timeline" and language_stage and language_stage["ctc"]:
                line = tr("{line}，日语句首再校正", line=line)
            short = labels.get(backend, backend)
            if backend == "api":
                # The sheet's thin rows name the service only; the model id stays in the tooltip.
                preset = ASR_API_PRESETS.get(str(models_cfg.get("qwen_asr_api_provider") or "qwen31_filetrans")) or {}
                short = str(preset.get("short") or short)
            roles[role] = {
                "backend": backend, "name": translate(labels.get(backend, backend), language),
                "short": translate(short, language),
                "kind": translate(kind, language), "status": translate(status, language),
                "status_key": status, "tone": tone, "recovery": translate(recovery, language),
                "model": model, "line": line, "note": timeline_note if role == "timeline" else None,
            }
        summary = " / ".join((
            primary_short.get(primary_backend, primary_backend),
            review_short.get(qwen_backend, qwen_backend),
            timeline_name,
        ))
        return {"roles": roles, "summary": summary, "block_reason": block_reason}

    @navigation_timed('home.summary')
    def _refresh_asr_summary(self):
        if not hasattr(self, "asr_panel"):
            return
        self._schedule_next_step_probe()
        language = getattr(self, "_ui_language", current_language())
        state = self.recognition_role_state()
        self._cloud_asr_block_reason = state["block_reason"]
        if self.__dict__.get("subtitle_language_hint") is not None:
            self._subtitle_language_changed(save=False)
        self.asr_panel.set_summary(state["summary"])

        # 角色卡：model 名是视觉主体；卡点击 → 工坊对应角色。
        if hasattr(self, "recognition_plan"):
            for role, facts in state["roles"].items():
                card = self.recognition_plan.cards[role]
                card.set_state(facts["name"], facts["kind"], facts["status"], facts["tone"], facts["recovery"])
                card.set_model(facts["model"], facts["line"])
                if role == "timeline":
                    card.set_note(facts["note"])
                if sys.platform == 'darwin' and facts["backend"] == 'sensevoice':
                    from ..system.platform_macos import macos_copy
                    card.setToolTip(macos_copy(
                        '当前采用 CPU 路线；MPS 设备可用性与模型算子支持分开验证，模型 MPS 适配尚未验证。',
                        'CPU is selected. MPS device availability and model/operator support require separate validation; model MPS support is not verified.',
                        '現在は CPU を使用します。MPS の利用可否とモデル／演算子の対応は別々に検証します。モデルの MPS 対応は未検証です。'))

        # CTA 状态：识别方案与 N 个词库就绪
        if hasattr(self, "action_status"):
            problems = []
            plan_items = []
            for role in ("primary", "timeline", "review"):
                status = state["roles"][role]["status_key"]
                if status in {"需要下载", "未配置"} or status in _HOST_LIMIT_STATUSES:
                    problems.append(status)
                    plan_items.append((role, status))
            refresh_bar = getattr(self, "_refresh_readiness_bar", None)
            if callable(refresh_bar):
                refresh_bar(plan_items)
            glossary_count = len(self._enabled_glossary_ids())
            if problems:
                self.action_status.setObjectName("statusWarn")
                pending = ", ".join(translate(item, language) for item in dict.fromkeys(problems))
                if language == "en":
                    text = "⚠ Before starting:"
                elif language != "zh":
                    text = "⚠ " + translate("开始前还需处理：", language)
                else:
                    text = "⚠ 开始前还需处理："
                self.action_status.setText(text)
            else:
                self.action_status.setObjectName("statusGood")
                if language == "en":
                    text = f"✔ Recognition plan and {glossary_count} term libraries are ready"
                elif language != "zh":
                    text = "✔ " + translate("识别方案与 {n} 个词库已就绪", language).replace("{n}", str(glossary_count))
                else:
                    text = f"✔ 识别方案与 {glossary_count} 个词库已就绪"
                if not getattr(self, "media_paths", None):
                    text += " · " + translate("开始前还需：", language)
                self.action_status.setText(text)
            self.action_status.style().unpolish(self.action_status)
            self.action_status.style().polish(self.action_status)
        self._refresh_glossary_chips()

    # ------------------------------------------------------------ P0 background preload (after first paint, never on click)
    def _background_preload(self):
        """Warm cheap caches so first click on ModelPicker/TermLibrary/Glossary/Technical is fast.
        - installed_model_keys FS scan (status)
        - term game list + counts (names only; full per-game mappings deferred until dialog shows a game)
        - touch model logos/icons (qta + bundled) to prime font/icon caches
        No heavy widget creation or 650-term loads here.
        """
        studio = self.built_page("studio")
        if studio is not None and self.pages.currentWidget() is studio:
            return  # Home-only caches are irrelevant to Studio's first paint.
        import time as _t
        _t0 = _t.perf_counter()
        try:
            # 1) Model install status (used by workshop + picker cards)
            keys = installed_model_keys(APP_ROOT)
            # Warm the workshop cache (cheap assignment, no UI rebuild). The
            # page itself is built on first use and picks these keys up then.
            self._preloaded_installed_model_keys = set(keys)
            workshop = self.built_page("workshop")
            if workshop is not None:
                try:
                    workshop._installed = set(keys)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # 2) Term game index (names + counts via cheap path; not full mappings)
            _ = term_library_game_names(self.legacy, self.game_box_text() if hasattr(self, "game_box") else "")
            # Touch counts for a bounded set to warm learned file reads without loading 650-term lists for all games.
            try:
                games = term_library_game_names(self.legacy, self.game_box_text() if hasattr(self, "game_box") else "")
                for g in games[:6]:
                    _ = self.legacy.learned_mappings_for_game(g)  # may be cached by legacy layer; cheap if small
            except Exception:
                pass
        except Exception:
            pass
        try:
            # 3) Prime icons used in pickers/workshop (no-op if already registered)
            for name in ("fa5s.wave-square", "fa5s.fire", "fa5s.magic", "fa5s.cloud", "fa5s.book-open", "fa5s.search"):
                try:
                    _ = _icon(name, GREEN)
                except Exception:
                    pass
            # Touch a couple of model logos
            from twobyteasr.local_models.model_workshop import _model_logo, MODELS as _MODELS
            for m in _MODELS[:4]:
                try:
                    _ = _model_logo(m, QSize(24, 24))
                except Exception:
                    pass
        except Exception:
            pass
        capability_worker = None
        try:
            from twobyteasr.exports.studio_render import start_encoder_capability_scan

            ffmpeg = APP_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
            if ffmpeg.is_file():
                capability_worker = start_encoder_capability_scan(
                    ffmpeg,
                    cancel_event=self._encoder_capability_cancel,
                )
                self._encoder_capability_worker = capability_worker
        except Exception:
            pass
        _dt = (_t.perf_counter() - _t0) * 1000
        try:
            if GUI_PROFILE_ENABLED and _dt > 1:
                print(f"[perf] _background_preload done ~{int(_dt)}ms")
        except Exception:
            pass
        if capability_worker is None:
            _startup_mark("BACKGROUND_READY", duration_ms=round(_dt, 3))
        else:
            def finish_background_ready():
                capability_worker.join()
                total = (_t.perf_counter() - _t0) * 1000
                _startup_mark("BACKGROUND_READY", duration_ms=round(total, 3))

            ready_thread = threading.Thread(
                target=finish_background_ready,
                daemon=True,
                name="startup-background-ready",
            )
            self._startup_background_ready_thread = ready_thread
            ready_thread.start()

    # ------------------------------------------------------------ 角色卡交互

    def _open_model_picker(self, role: str, *, on_closed=None):
        """Choose, install and switch a role model without leaving the home page.
        P0: use MainWindow-internal ModalHost (no new native top-level window) to eliminate black flash.
        Card shows at final size immediately; only backdrop fades. Skeleton + defer heavy work.
        四十二轮：on_closed 供二级宿主（Studio 识别弹窗）在弹窗关闭后恢复自身。
        """
        self._popup_click_ts = time.perf_counter() if GUI_PROFILE_ENABLED else None
        self._popup_first_paint_title = f"选择{ModelPickerPanel.ROLE_LABELS.get(role, '识别')}模型"
        self.workshop_page.runtime_settings = self.legacy.RUNTIME_SETTINGS
        latest_installed = installed_model_keys(APP_ROOT)
        if latest_installed != self.workshop_page._installed:
            self.workshop_page._installed = latest_installed
        installed_before = frozenset(self.workshop_page._installed)
        # The picker only needs controller state. Refiltering and repainting the
        # hidden full Workshop page made every open pay for two interfaces.
        key = f"_model_picker_{role}"
        panel = getattr(self, key + "_panel", None)
        if panel is None:
            panel = ModelPickerPanel(self.workshop_page, role, self._modal_host.body)
            panel.close_requested.connect(self._modal_host._request_close)
            setattr(self, key + "_panel", panel)
        else:
            # reparent to host body if needed
            if panel.parent() is not self._modal_host.body:
                panel.setParent(self._modal_host.body)
        panel.begin_session()

        def _after_close():
            # Installs rebuild the choices; helper switches also change the
            # effective timeline without changing the installed model set.
            if frozenset(self.workshop_page._installed) != installed_before:
                self._refresh_available_asr_choices()
            self._timeline_helper_changed()
            if on_closed is not None:
                try:
                    on_closed()
                except Exception:
                    pass

        # Show via internal host: backdrop fade only; card at final size; 100% opaque card.
        self._modal_host.show_content(
            panel,
            title=self._popup_first_paint_title,
            size=(860, 680),
            min_size=(760, 560),
            on_closed=_after_close,
            retain_content=True,
        )
        # Log the request time (real first-paint is measured inside ModalHost).
        try:
            if self._popup_click_ts is not None:
                dt = (time.perf_counter() - self._popup_click_ts) * 1000
                print(f"[perf] _open_model_picker({role}) request→host ~{int(dt)}ms")
        except Exception:
            pass

    def _open_workshop_role(self, role: str):
        """Compatibility alias: role-card actions now open the shared picker."""
        self._open_model_picker(role)

    def _recognition_recovery(self, role: str, action: str):
        # Role cards emit the label in the current UI language; chips pass the
        # Chinese source. Accept both (the en/ja "Install model" did nothing).
        install = {"安装模型", tr("安装模型")}
        api = {"配置 API", tr("配置 API")}
        if action in {_HOST_LIMIT_RECOVERY, str(tr(_HOST_LIMIT_RECOVERY))}:
            self._next_step_action("choose_plan")  # the chooser only offers what this computer can run
        elif action in install or "安装" in action or "下载" in action:
            self._open_model_picker(role)
        elif action in api or "API" in action or "配置" in action:
            # The step-by-step guide (per provider, with tests) replaces the bare key form.
            self._open_api_setup_guide()

    def _open_api_key_dialog(self):
        """ASR API Key 配置（批准图：密钥进 AI 与密钥，不再有识别增强卡）。"""
        dialog = SpringDialog(self)
        bind_text(dialog, '配置在线 ASR API', property='windowTitle')
        dialog.setWindowIcon(_app_icon())
        dialog.resize(520, 380)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(18, 16, 18, 16)
        dialog_layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("在线识别服务")
        title.setProperty("typography", "title")
        header.addWidget(title, 1)
        from ..design.presentation import button_role, glyph_button
        close_header = glyph_button(button_role(QPushButton("×"), "ghost"))
        bind_text(close_header, '关闭在线识别设置', property='accessibleName')
        close_header.clicked.connect(dialog.reject)
        header.addWidget(close_header)
        dialog_layout.addLayout(header)
        hint = QLabel(
            "在线识别会使用所选服务商；本地模型组合不需要 Key。\n"
            f"{credential_storage_notice()}"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        dialog_layout.addWidget(hint)
        provider = FramelessPopupCombo()
        provider.setObjectName('asrCredentialProvider')
        for key, preset in ASR_API_PRESETS.items():
            provider.addItem(preset["label"], key)
        provider.setCurrentIndex(max(0, provider.findData(self.qwen_asr_api_provider.currentData())))
        # 四十轮：下拉打开时当前选中项置于第一行（用户不必滚动寻找）。
        provider.setProperty("selectedFirst", True)
        model = QLineEdit(self.qwen_asr_api_model.text())
        url = QLineEdit(self.qwen_asr_api_url.text())
        key_editor = QLineEdit()
        model.setObjectName('asrCredentialModel');url.setObjectName('asrCredentialUrl');key_editor.setObjectName('asrCredentialKey')
        key_editor.setEchoMode(QLineEdit.EchoMode.Password)
        # 四十轮：转写风格同源下拉（用户实录在配置弹窗里找不到设置页才有的
        # 选项——"下拉的两个选项在哪呢？"）。保存时回写设置面板的同一控件。
        style_combo = FramelessPopupCombo()
        for style_label, style_value in (
            ("清爽（去语气词，适合字幕/纪要）", "clean"),
            ("逐字 verbatim（保留嗯/那个/口误，适合合规/质检）", "verbatim"),
        ):
            style_combo.addItem(style_label, style_value)
        style_combo.setCurrentIndex(
            max(0, style_combo.findData(self.api_transcribe_style.currentData()))
        )
        style_combo.setToolTip(self.api_transcribe_style.toolTip())
        # 四十轮：OSS 临时中转存储（Qwen 录音文件识别需要公网 URL）。
        # 只在选中 filetrans 服务时显示；凭据 DPAPI 保存，绝不明文进 settings。
        oss_models = self.legacy.RUNTIME_SETTINGS.get("models", {})
        from ..providers.llm_config import read_oss_credentials

        saved_oss_id, saved_oss_secret = read_oss_credentials()
        # 2026-10-28：录音文件识别默认交给服务商临时空间；只有选“我自己的 OSS”才显示并要求 OSS 分组。
        from ..providers.api_setup_catalog import UPLOAD_CHOICES, UPLOAD_MISSING, UPLOAD_OWN_OSS, resolve_upload_mode
        upload_mode = FramelessPopupCombo()
        upload_mode.setObjectName('asrCredentialUpload')
        for upload_value, upload_label in UPLOAD_CHOICES:
            upload_mode.addItem(upload_label, upload_value)
        saved_upload = resolve_upload_mode(oss_models, has_oss_credentials=bool(saved_oss_id and saved_oss_secret))
        upload_mode.setCurrentIndex(max(0, upload_mode.findData(
            UPLOAD_OWN_OSS if saved_upload == UPLOAD_MISSING else saved_upload)))
        oss_group = QGroupBox("OSS 临时中转存储")
        oss_form = QFormLayout(oss_group)
        oss_form.setHorizontalSpacing(14)
        oss_form.setVerticalSpacing(8)
        oss_region = QLineEdit(str(oss_models.get("oss_region") or "cn-hangzhou"))
        oss_endpoint = QLineEdit(
            str(oss_models.get("oss_endpoint") or "https://oss-cn-hangzhou.aliyuncs.com")
        )
        oss_bucket = QLineEdit(str(oss_models.get("oss_bucket") or ""))
        bind_text(oss_bucket, '例如 2byte', property='placeholderText')
        oss_prefix = QLineEdit(str(oss_models.get("oss_prefix") or "asr-temp/"))
        oss_key_id = QLineEdit(saved_oss_id)
        bind_text(oss_key_id, '尚未保存，请输入 AccessKey ID（RAM 子账号即可）', property='placeholderText')
        oss_secret = QLineEdit()
        oss_secret.setEchoMode(QLineEdit.EchoMode.Password)
        if saved_oss_secret:
            oss_secret.setText(saved_oss_secret)
            bind_text(oss_secret, '已保存（···{value0}；修改后保存即覆盖）', property='placeholderText', value0=saved_oss_secret[-4:])
        else:
            bind_text(oss_secret, '尚未保存，请输入 AccessKey Secret', property='placeholderText')
        oss_ttl = QLineEdit(str(oss_models.get("oss_signed_url_ttl") or 86400))
        oss_auto_delete = QCheckBox("识别结束后自动删除临时对象（48 小时后启动清理兜底）")
        oss_auto_delete.setChecked(bool(oss_models.get("oss_auto_delete", True)))
        oss_note = QLabel(
            "音频会临时上传到你的 OSS 前缀并生成预签名 HTTPS 链接提交识别，结束后自动删除；"
            "AccessKey 只在本机签名，不会发送给识别服务。"
            "RAM 子账号最小权限：PutObject / GetObject / DeleteObject。"
        )
        oss_note.setObjectName("muted")
        oss_note.setWordWrap(True)
        secret_row = QHBoxLayout()
        secret_row.setContentsMargins(0, 0, 0, 0)
        secret_row.addWidget(oss_secret, 1)
        secret_toggle = AnimatedButton("显示")
        secret_toggle.setObjectName("outline")
        secret_toggle.setCheckable(True)

        def _toggle_secret(checked: bool):
            oss_secret.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
            (bind_text(secret_toggle, '隐藏') if checked else bind_text(secret_toggle, '显示'))

        secret_toggle.toggled.connect(_toggle_secret)
        secret_row.addWidget(secret_toggle)
        oss_form.addRow("OSS Region", oss_region)
        oss_form.addRow("OSS Endpoint", oss_endpoint)
        oss_form.addRow("Bucket", oss_bucket)
        oss_form.addRow("临时前缀", oss_prefix)
        oss_form.addRow("AccessKey ID", oss_key_id)
        oss_form.addRow("AccessKey Secret", secret_row)
        oss_form.addRow("签名 URL 有效期（秒）", oss_ttl)
        oss_form.addRow("", oss_auto_delete)
        oss_form.addRow("", oss_note)
        from ..providers.llm_config import read_asr_api_key, read_spark_credentials, save_spark_credentials
        spark_group=QWidget()
        spark_form=QFormLayout(spark_group); spark_form.setContentsMargins(0,0,0,0)
        spark_app=QLineEdit(); spark_secret=QLineEdit()
        spark_app.setObjectName('sparkAppId');spark_secret.setObjectName('sparkApiSecret')
        spark_secret.setEchoMode(QLineEdit.EchoMode.Password)
        spark_form.addRow('AppID',spark_app);spark_form.addRow('APISecret',spark_secret)

        def _scoped_key(provider_key: str, base_url: str) -> str:
            if provider_key=='spark_asr_v2':return read_spark_credentials(base_url)['api_key']
            return read_asr_api_key(provider_key, base_url)[0]

        def _sync_key_field():
            is_spark=provider.currentData()=='spark_asr_v2'
            credentials=read_spark_credentials(url.text().strip()) if is_spark else {}
            spark_app.setText(credentials.get('app_id',''));spark_secret.setText(credentials.get('api_secret',''))
            spark_group.setVisible(is_spark)
            saved = _scoped_key(str(provider.currentData()), url.text().strip())
            if saved:
                # 预填已保存的 key（可显示/隐藏），留空保存=保持不变
                key_editor.setText(saved)
                bind_text(key_editor, '已保存（···{value0}；修改后保存即覆盖）', property='placeholderText', value0=saved[-4:])
            else:
                key_editor.clear()
                bind_text(key_editor, '尚未保存该服务商的 Key，请输入', property='placeholderText')

        _sync_key_field()
        key_editor.setCursorPosition(0)
        url.setCursorPosition(0)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(key_editor, 1)
        key_toggle = AnimatedButton("显示")
        key_toggle.setObjectName("outline")
        key_toggle.setCheckable(True)

        def _toggle_key(checked: bool):
            key_editor.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
            (bind_text(key_toggle, '隐藏') if checked else bind_text(key_toggle, '显示'))

        key_toggle.toggled.connect(_toggle_key)
        key_row.addWidget(key_toggle)

        # 四十一轮：记住打开时的保存值——切换服务再切回时恢复用户地址，
        # 不强制刷回预设（自定义工作台域名必须留住）。
        original_provider = str(provider.currentData() or "")
        original_model = model.text()
        original_url = url.text()
        bind_text(url, '可自行修改并保存；重新打开或切回该服务时会恢复你保存的地址', property='toolTip')

        def provider_changed():
            current = str(provider.currentData() or "")
            if current == original_provider and (original_model or original_url):
                if original_model:
                    model.setText(original_model)
                if original_url:
                    url.setText(original_url)
            elif current != "custom":
                preset = ASR_API_PRESETS.get(current, {})
                model.setText(str(preset.get("model") or model.text()))
                url.setText(str(preset.get("url") or url.text()))
            # 长 URL 默认右滚会把 https:// 前缀滚出视野（视觉评审第 1 项）。
            url.setCursorPosition(0)
            _sync_key_field()
            key_editor.setCursorPosition(0)
            _sync_oss_visibility()

        def _sync_oss_visibility():
            uses_filetrans = ASR_API_PRESETS.get(str(provider.currentData()),{}).get('protocol')=='dashscope_filetrans'
            uses_oss = uses_filetrans and upload_mode.currentData() == UPLOAD_OWN_OSS
            try:
                form.setRowVisible(upload_mode, uses_filetrans)
            except (AttributeError, TypeError):
                upload_mode.setVisible(uses_filetrans)
            oss_group.setVisible(uses_oss)
            oss_test_button.setVisible(uses_oss)
            status.clear()
            if uses_oss:
                dialog.resize(560, 720)
            else:
                # 自适应收缩：隐藏 OSS 区后不留大块空白（视觉评审第 3 项）。
                dialog.adjustSize()
                dialog.resize(max(520, dialog.width()), dialog.height())

        provider.currentIndexChanged.connect(provider_changed)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.addRow("API 服务", provider)
        form.addRow("API 模型", model)
        form.addRow("API 地址", url)
        form.addRow("API 密钥", key_row)
        form.addRow("转写风格", style_combo)
        form.addRow("音频交给服务商的方式", upload_mode)
        upload_mode.currentIndexChanged.connect(lambda _index: _sync_oss_visibility())
        dialog_layout.addLayout(form)
        dialog_layout.addWidget(spark_group)
        # OSS 中转存储区（默认隐藏；选中 filetrans 服务且选了“我自己的 OSS”时显示）
        dialog_layout.addWidget(oss_group)
        oss_group.hide()
        status = QLabel()
        status.setObjectName("muted")
        status.setWordWrap(True)
        dialog_layout.addWidget(status)
        actions = QHBoxLayout()
        test_button = AnimatedButton("测试连接")
        test_button.setObjectName("outline")
        actions.addWidget(test_button)
        oss_test_button = AnimatedButton("测试 OSS 连接")
        oss_test_button.setObjectName("outline")
        actions.addWidget(oss_test_button)
        oss_test_button.hide()
        actions.addStretch(1)
        save_button = AnimatedButton("保存")
        save_button.setObjectName("primary")
        actions.addWidget(save_button)
        close_button = AnimatedButton("关闭")
        close_button.setObjectName("outline")
        close_button.clicked.connect(dialog.accept)
        actions.addWidget(close_button)
        dialog_layout.addLayout(actions)

        class _AsrConnectionWorker(QThread):
            finished_status = Signal(bool, str)

            def __init__(self, base_url: str, api_key: str, protocol: str):
                super().__init__()
                self._base_url = base_url
                self._api_key = api_key
                self._protocol = protocol

            def run(self):
                from ..providers.llm_config import fetch_openai_compatible_models

                if self._protocol in {"dashscope_multimodal", "dashscope_filetrans", "dashscope_asr_flash", "spark_wss"}:
                    self.finished_status.emit(
                        False,
                        "此原生转写接口不支持模型列表；凭据已填写不代表实际识别已验证"
                        "（OSS 中转可用左侧「测试 OSS 连接」验证）。",
                    )
                    return
                if not self._base_url.strip() or not self._api_key.strip():
                    self.finished_status.emit(False, "请先填写地址与 Key。")
                    return
                try:
                    models_list = fetch_openai_compatible_models(
                        self._base_url, self._api_key
                    )
                except Exception as exc:
                    self.finished_status.emit(False, f"连接失败：{' '.join(str(exc).split())[:120]}")
                    return
                names = [str(item) for item in models_list][:8]
                self.finished_status.emit(
                    True, f"连接正常（{len(models_list)} 个模型，如 {', '.join(names[:3])}…）"
                )

        _worker_ref: list = []

        def _run_test():
            test_button.setEnabled(False)
            bind_text(status, '正在测试连接…')
            protocol = str(ASR_API_PRESETS.get(str(provider.currentData()), {}).get("protocol", ""))
            typed = key_editor.text().strip()
            saved = _scoped_key(str(provider.currentData()), url.text().strip())
            worker = _AsrConnectionWorker(url.text().strip(), typed or saved, protocol)
            worker.finished_status.connect(
                lambda ok, text: (
                    status.setText(text),
                    status.setProperty("ok", ok),
                    test_button.setEnabled(True),
                )
            )
            _worker_ref.append(worker)
            worker.start()

        test_button.clicked.connect(_run_test)

        class _OssTestWorker(QThread):
            finished_status = Signal(bool, str)

            def __init__(self, region, endpoint, bucket, prefix, key_id, key_secret, ttl):
                super().__init__()
                self._values = (region, endpoint, bucket, prefix, key_id, key_secret, ttl)

            def run(self):
                from ..providers.temp_audio_storage import OssTemporaryStorage

                region, endpoint, bucket, prefix, key_id, key_secret, ttl = self._values
                try:
                    try:
                        ttl_value = int(ttl)
                    except (TypeError, ValueError):
                        ttl_value = 86400
                    storage = OssTemporaryStorage(
                        region=region,
                        endpoint=endpoint,
                        bucket=bucket,
                        prefix=prefix,
                        access_key_id=key_id,
                        access_key_secret=key_secret,
                        signed_url_ttl=ttl_value,
                    )
                except Exception as exc:
                    self.finished_status.emit(False, f"OSS 配置无效：{exc}")
                    return
                result = storage.test_connection()
                self.finished_status.emit(result.ok, result.message)

        def _run_oss_test():
            oss_test_button.setEnabled(False)
            bind_text(status, '正在测试 OSS（上传探针 → 预签名下载 → 删除）…')
            worker = _OssTestWorker(
                oss_region.text().strip(),
                oss_endpoint.text().strip(),
                oss_bucket.text().strip(),
                oss_prefix.text().strip() or "asr-temp/",
                oss_key_id.text().strip() or saved_oss_id,
                oss_secret.text().strip() or saved_oss_secret,
                oss_ttl.text().strip() or "86400",
            )
            worker.finished_status.connect(
                lambda ok, text: (
                    status.setText(text),
                    status.setProperty("ok", ok),
                    oss_test_button.setEnabled(True),
                )
            )
            _worker_ref.append(worker)
            worker.start()

        oss_test_button.clicked.connect(_run_oss_test)

        def _persist_oss_fields() -> str:
            """保存 OSS 非密钥字段（settings）+ 凭据（DPAPI）。返回错误文案或空。"""
            from ..providers.llm_config import save_oss_credentials

            try:
                ttl_value = int(oss_ttl.text().strip() or "86400")
            except (TypeError, ValueError):
                return "签名 URL 有效期必须是整数秒数。"
            if not oss_endpoint.text().strip().lower().startswith("https://"):
                return "OSS Endpoint 必须使用 https:// 开头。"
            if not oss_bucket.text().strip():
                return "OSS Bucket 不能为空。"
            if oss_key_id.text().strip() or oss_secret.text().strip():
                try:
                    save_oss_credentials(oss_key_id.text().strip(), oss_secret.text().strip())
                except Exception as exc:
                    return f"OSS 凭据保存失败：{exc}"
            models_patch = {
                "oss_region": oss_region.text().strip() or "cn-hangzhou",
                "oss_endpoint": oss_endpoint.text().strip(),
                "oss_bucket": oss_bucket.text().strip(),
                "oss_prefix": oss_prefix.text().strip() or "asr-temp/",
                "oss_signed_url_ttl": ttl_value,
                "oss_auto_delete": oss_auto_delete.isChecked(),
                "filetrans_upload": UPLOAD_OWN_OSS,
            }
            self.legacy.configure_runtime_asr(models_patch)
            return ""

        def save():
            if provider.currentData()=='spark_asr_v2':
                try:
                    from ..providers.llm_config import validate_qwen_asr_endpoint
                    credentials=dict(app_id=spark_app.text().strip(),api_key=key_editor.text().strip(),api_secret=spark_secret.text().strip())
                    validate_qwen_asr_endpoint(dict(protocol='spark_wss',model=model.text().strip(),url=url.text().strip(),**credentials))
                    save_spark_credentials(url.text().strip(),**credentials)
                except Exception as exc:
                    status.setText(str(exc));return
            self.qwen_asr_api_provider.setCurrentIndex(
                max(0, self.qwen_asr_api_provider.findData(provider.currentData()))
            )
            self.qwen_asr_api_model.setText(model.text().strip())
            self.qwen_asr_api_url.setText(url.text().strip())
            self.qwen_asr_api_key.setText(key_editor.text().strip())
            style_index = self.api_transcribe_style.findData(style_combo.currentData())
            if style_index >= 0:
                self.api_transcribe_style.setCurrentIndex(style_index)
            if ASR_API_PRESETS.get(str(provider.currentData()),{}).get('protocol')=='dashscope_filetrans':
                if upload_mode.currentData() == UPLOAD_OWN_OSS:
                    oss_error = _persist_oss_fields()
                    if oss_error:
                        status.setText(oss_error)
                        status.setProperty("ok", False)
                        return
                else:
                    # 服务商临时空间：不要求 OSS；已存的 OSS 设置原样保留，改回时还在。
                    self.legacy.configure_runtime_asr({"filetrans_upload": str(upload_mode.currentData())})
            if self._save_asr_configuration(show_feedback=False):
                self._refresh_workshop_after_asr_change()
                dialog.accept()

        save_button.clicked.connect(save)
        _sync_oss_visibility()
        key_editor.setFocus()
        dialog.exec()

    def _oss_startup_cleanup(self):
        """启动 20s 后在后台线程清理 OSS 临时对象（>48h），任何失败都静默。"""

        def _run():
            try:
                from ..providers.temp_audio_storage import maybe_cleanup_stale_objects

                maybe_cleanup_stale_objects(self.legacy.RUNTIME_SETTINGS)
            except Exception:
                pass

        import threading

        threading.Thread(target=_run, name="oss-cleanup", daemon=True).start()

    def _recognition_action_clicked(self):
        """Compatibility entry: basic model recovery stays on the home page."""
        text = self.recognition_action.text()
        if "安装" in text or "下载" in text:
            self._open_model_picker("primary")
        elif "API" in text or "密钥" in text or "配置" in text:
            self._open_api_key_dialog()

    # ------------------------------------------------------------ 多词库

    def _enabled_glossary_ids(self) -> list[str]:
        settings = self.legacy.RUNTIME_SETTINGS
        enabled = [
            str(item).strip()
            for item in settings.get("glossary", {}).get("enabled_glossary_ids", []) or []
            if str(item).strip()
        ]
        return list(dict.fromkeys(enabled))

    @navigation_timed('home.glossary')
    def _refresh_glossary_chips(self):
        if not hasattr(self, "glossary_chips_layout"):
            return
        while self.glossary_chips_layout.count():
            item = self.glossary_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        enabled = self._enabled_glossary_ids()
        effective = bool(getattr(getattr(self, "terms", None), "isChecked", lambda: False)())
        for identity in enabled:
            chip = AnimatedButton("")
            chip.setObjectName("glossaryChip")
            display = self._glossary_display_name(identity)
            chip.setText(f"{display}  ×")
            bind_text(chip, translate('点击移出本批词库', current_language()), property='toolTip')
            chip.clicked.connect(
                lambda _checked=False, value=identity: self._remove_glossary(value)
            )
            self.glossary_chips_layout.addWidget(chip)
        self.glossary_chips_layout.addStretch(1)
        terms_on = bool(getattr(getattr(self, "terms", None), "isChecked", lambda: False)())
        if hasattr(self, "batch_glossary_status"):
            if enabled and effective:
                names = [self._glossary_display_name(identity) for identity in enabled[:3]]
                suffix = "…" if len(enabled) > 3 else ""
                from ..glossary.terminology import snapshot_glossaries
                catalog = getattr(self.legacy, 'glossary_catalog', lambda: [])()
                key = (tuple(enabled), tuple((r['id'], r.get('revision', '')) for r in catalog))
                if key != getattr(self, '_home_term_summary_key', None):
                    self._home_term_summary = snapshot_glossaries(self.legacy, enabled).summary()
                    self._home_term_summary_key = key
                summary = self._home_term_summary
                count = summary['effective_terms']
                reason = ('；存在冲突，请检查术语库' if summary['conflicts'] else
                          '；所选词库只有参考项、无已确认词，或词库已不存在' if count == 0 else '')
                bind_text(self.batch_glossary_status, '术语增强 ON · 本批启用：{names}\n实际生效 {count} 个规范词{reason}', names='、'.join(names) + suffix, count=count, reason=reason)
            elif enabled:
                bind_text(self.batch_glossary_status, '术语增强 OFF · 已选择词库；本次不应用')
            elif terms_on:
                bind_text(self.batch_glossary_status, '术语增强 ON · 未选择词库，本次暂不应用')
            else:
                bind_text(self.batch_glossary_status, translate('术语增强 OFF', current_language()))
            bind_text(self.add_glossary_button, translate('管理术语库', current_language()))
        state = getattr(self, "term_state_label", None)
        if state is not None:
            if enabled and effective:
                count = self._home_term_summary['effective_terms']
                reason = ('；存在冲突，请检查术语库' if self._home_term_summary['conflicts'] else
                          '；所选词库只有参考项、无已确认词，或词库已不存在' if count == 0 else '')
                bind_text(state, '生效 {count} 个规范词{reason}', count=count, reason=reason)
                tone = "warn" if reason else "on"
            elif enabled:
                bind_text(state, '已选择词库，本次不应用')
                tone = "off"
            elif terms_on:
                bind_text(state, '未选择词库，本次暂不应用')
                tone = "warn"
            else:
                bind_text(state, '启用后用于专名、角色名与错词修正')
                tone = "off"
            state.setProperty("tone", tone)
            state.style().unpolish(state)
            state.style().polish(state)

    def _glossary_display_name(self, identity: str) -> str:
        display = getattr(self.legacy, "glossary_display_name", None)
        if callable(display):
            return str(display(identity) or identity)
        profiles = getattr(self.legacy, "load_game_profiles", lambda: {})()
        for name, profile in (profiles or {}).items():
            if self.legacy.runtime_game_identity(str(profile.get("identity", name))) == identity:
                return str(name)
        learned = getattr(self.legacy, "load_learned_term_payload", lambda: {"games": {}})()
        for _key, entry in (learned or {}).get("games", {}).items():
            if isinstance(entry, dict) and self.legacy.runtime_game_identity(str(entry.get("game", ""))) == identity:
                return str(entry.get("game", identity))
        return identity

    def _save_glossary_settings(self):
        try:
            self.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
            self.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = self._enabled_glossary_ids()
            self.legacy.RUNTIME_SETTINGS["glossary"]["enable_domain_terms"] = bool(self.terms.isChecked())
            save_runtime_settings(self.legacy.RUNTIME_SETTINGS)
        except Exception as exc:
            if hasattr(self, "term_hint"):
                self.term_hint.setText(f"词库配置保存失败：{exc}")
                self.term_hint.show()
            raise
        self._refresh_glossary_chips()
        page = getattr(getattr(self, "term_library_page", None), "library", None)
        if page is not None:
            page._refresh_batch_bar()
        self._refresh_asr_summary()

    def _remove_glossary(self, identity: str):
        enabled = [i for i in self._enabled_glossary_ids() if i != identity]
        self.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled
        self._save_glossary_settings()
        # Chips and the persistent status already describe the current state.
        self.term_hint.clear()
        self.term_hint.hide()

    def _pick_glossaries(self):
        """打开可搜索的多选词库选择器。 P0: use ModalHost (no native window), skeleton first."""
        import time as _t
        self._popup_click_ts = _t.perf_counter()
        self._popup_first_paint_title = "本批字幕使用的词库"
        picker = GlossaryPickerDialog(self, self._modal_host.body)
        # Populate on next tick
        QTimer.singleShot(0, picker, picker._populate)

        def _after_close():
            chosen = picker.take_result()
            if chosen is not None:
                self.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = chosen
                self._save_glossary_settings()
                (bind_text(self.term_hint, f'{len(chosen)} term libraries enabled for this batch') if current_language() == 'en' else bind_text(self.term_hint, '本批已启用 {value0} 个词库', value0=len(chosen)))
                self.term_hint.setVisible(bool(self.term_hint.text()))

        self._modal_host.show_content(
            picker,
            title=self._popup_first_paint_title,
            size=(460, 480),
            min_size=(400, 360),
            on_closed=_after_close,
        )
        try:
            if GUI_PROFILE_ENABLED:
                dt = (_t.perf_counter() - self._popup_click_ts) * 1000
                print(f"[perf] _pick_glossaries host→visible ~{int(dt)}ms")
        except Exception:
            pass

    def _mark_asr_configuration_dirty(self, *_args):
        if getattr(self, "_applying_profile", False):
            return
        self._mark_profile_configuration_dirty()
        if not hasattr(self, "asr_save_status"):
            return
        language = getattr(self, "_ui_language", current_language())
        self.asr_save_status.setObjectName("statusWarn")
        bind_text(self.asr_save_status, translate('有未保存的识别后端修改', language))
        self.asr_save_status.style().unpolish(self.asr_save_status)
        self.asr_save_status.style().polish(self.asr_save_status)
        self._refresh_asr_summary()

    def _mark_profile_configuration_dirty(self, *_args):
        """方案级脏标：切换方案前据此提示保存/放弃（2026-09-19 方案独立轮）。"""
        if getattr(self, "_applying_profile", False):
            return
        self._asr_config_dirty = True

    def _save_asr_configuration(self, *, show_feedback: bool, require_ready: bool = False) -> bool:
        if self.worker is not None and self.worker.isRunning():
            bind_text(self.asr_save_status, '当前任务仍使用启动配置；请任务结束后保存转写与对齐设置。')
            return False
        try:
            qk = self.qwen_asr_api_key.text().strip()
            av = self._asr_values()
            # Provider-scoped ASR key persistence: key belongs to provider+base_url, not to model id.
            try:
                if qk:
                    save_api_key_for(av.get("qwen_asr_api_provider", "qwen31_filetrans"), av.get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"]), qk)
            except Exception:
                pass
            result = persist_asr_configuration(
                self.legacy,
                av,
                qwen_key=qk,
                require_ready=require_ready,
            )
        except Exception as exc:
            self._run_block_reason = f"识别后端未保存：{exc}"
            self.asr_panel.set_expanded(True)
            self.asr_save_status.setObjectName("statusWarn")
            bind_text(self.asr_save_status, '保存失败：{exc}', exc=exc)
            self.asr_save_status.style().unpolish(self.asr_save_status)
            self.asr_save_status.style().polish(self.asr_save_status)
            if show_feedback:
                QMessageBox.warning(self, tr('识别后端未保存'), str(exc))
            return False
        self.qwen_asr_api_key.clear()
        # Read back using provider-scoped lookup to show correct placeholder for current provider/base.
        prov = av.get("qwen_asr_api_provider", "qwen31_filetrans")
        burl = av.get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"])
        existing, source = read_asr_api_key(prov, burl)
        (bind_text(self.qwen_asr_api_key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.qwen_asr_api_key, '请输入当前 ASR 服务的 API Key', property='placeholderText'))
        missing = result["missing_keys"]
        language = getattr(self, "_ui_language", current_language())
        self.asr_save_status.setObjectName("statusWarn" if missing else "statusGood")
        (bind_text(self.asr_save_status, translate('配置已保存；运行前还需填写：', language) + '、'.join(missing)) if missing else bind_text(self.asr_save_status, credential_storage_notice(language) if session_credentials_enabled() else translate('识别后端与密钥已保存', language)))
        self.asr_save_status.style().unpolish(self.asr_save_status)
        self.asr_save_status.style().polish(self.asr_save_status)
        self._asr_config_dirty = False
        # 隐式保存（保存按钮/工坊应用/API 预设/识别启动/Studio 弹窗回写）同步
        # 当前方案的 ASR 快照——只更新激活方案，其他方案不受影响。
        active = getattr(self, "current_project_profile", None)
        if active is not None and not getattr(self, "_applying_profile", False):
            try:
                self.current_project_profile = self.profile_store.update_asr_config(
                    active.id, copy.deepcopy(av)
                )
            except Exception:
                pass
        self._refresh_project_profile_combo()
        self._refresh_workshop_after_asr_change()
        self._refresh_asr_summary()
        return True

    def _refresh_ai_summary(self):
        if getattr(self, '_recognition_page_deferred', False):
            return
        sync_switches = getattr(self, "_sync_ai_switches_with_keys", None)
        if callable(sync_switches):
            sync_switches()
        language = getattr(self, "_ui_language", current_language())
        from ..providers.llm_config import effective_ai_identity
        saved = self.legacy.RUNTIME_SETTINGS
        saved_values = {stage: effective_ai_identity(saved, stage) for stage in ('polish', 'group')}
        def describe(identity, enabled):
            if not enabled:
                return translate('未启用', language)
            return f"{translate(identity['label'], language)} · {identity['model'] or translate('默认模型', language)}"
        draft_switches = {'unified': self.unified_glm.isChecked(),
                          'polish': self.ai_polish.isChecked(), 'group': self.ai_grouping.isChecked()}
        saved_switches = {'unified': bool(saved.get('switches', {}).get('unified_glm_processing', False)),
                          'polish': bool(saved.get('switches', {}).get('enable_ai_polish', True)),
                          'group': bool(saved.get('switches', {}).get('use_ai_grouping', True))}
        def pair(values, switches):
            if switches['unified'] and switches['polish'] and switches['group'] and values['polish'] == values['group']:
                return describe(values['polish'], True)
            return translate('校对：{polish} · 断句：{group}', language).format(
                polish=describe(values['polish'], switches['polish']), group=describe(values['group'], switches['group']))
        summary = translate('已保存', language) + '：' + pair(saved_values, saved_switches)
        try:
            # Use the save path's validation and unified editor authority. The
            # preview does not write settings or keys, nor activate a provider.
            preview = persist_ai_configuration(self.legacy,
                self.polish_editor.values(), self.group_editor.values(),
                unified=draft_switches['unified'], share_key=self.share_key.isChecked(),
                use_ai_grouping=draft_switches['group'], enable_ai_polish=draft_switches['polish'],
                require_ready=False, dry_run=True)
            draft_settings = copy.deepcopy(saved)
            draft_settings.pop('_asr_provider_snapshot', None)
            draft_settings.setdefault('models', {}).update(preview['models'])
            draft_settings.setdefault('switches', {}).update({
                'unified_glm_processing': preview['unified'],
                'enable_ai_polish': draft_switches['polish'], 'use_ai_grouping': draft_switches['group']})
            draft_switches['unified'] = preview['unified']
            drafts = {stage: effective_ai_identity(draft_settings, stage) for stage in ('polish', 'group')}
            self._ai_has_draft = drafts != saved_values or draft_switches != saved_switches
            if self._ai_has_draft:
                summary += ' · ' + translate('未保存草稿', language) + '：' + pair(drafts, draft_switches)
        except (ValueError, KeyError, RuntimeError):
            # validate_endpoint raises RuntimeError (missing or retired model, bad URL); before
            # 2026-10-18 that escaped here and a saved retired model stopped the app at startup.
            self._ai_has_draft = True
            summary += ' · ' + translate('未保存草稿', language) + '：' + translate('配置未通过保存校验', language)
        summary += ' · ' + translate('真实连接需单独测试', language)
        self.ai_panel.set_summary(summary)
        if hasattr(self, "setting_tiles"):
            self.setting_tiles["ai"].set_summary(summary)
        # The home card shows the current service/model and separate facts.
        refresh_card = getattr(self, "_refresh_home_process_facts", None)
        if callable(refresh_card):
            refresh_card()
        refresh_dialog = getattr(self, "_refresh_ai_dialog_state", None)
        if callable(refresh_dialog):
            refresh_dialog()

    def _mark_ai_configuration_dirty(self, *_args):
        if getattr(self, "_applying_profile", False):
            return
        self._mark_profile_configuration_dirty()
        if not hasattr(self, "ai_save_status"):
            return
        self.ai_save_status.setObjectName("statusWarn")
        bind_text(self.ai_save_status, '有未保存的 AI 配置修改')
        self.ai_save_status.show()
        self.ai_save_status.style().unpolish(self.ai_save_status)
        self.ai_save_status.style().polish(self.ai_save_status)

    def _save_ai_configuration(self, *, show_feedback: bool, require_ready: bool = False,
                               local_without_key: bool = False) -> bool:
        from ..providers.ai_config_state import trace_configuration
        trace_configuration('before_save', self.legacy.RUNTIME_SETTINGS)
        self._text_ai_local_roles = ()
        try:
            p = self.polish_editor.values()
            g = self.group_editor.values()
            _secret_save_trace("before_save", self.polish_editor, p, extra={"editor": "polish"})
            _secret_save_trace("before_save", self.group_editor, g, extra={"editor": "group"})
            result = persist_ai_configuration(
                self.legacy,
                p,
                g,
                unified=self.unified_glm.isChecked(),
                share_key=self.share_key.isChecked(),
                require_ready=require_ready,
                use_ai_grouping=self.ai_grouping.isChecked(),
                enable_ai_polish=self.ai_polish.isChecked(),
                prefer_arabic_numbers=self.prefer_arabic_numbers.isChecked() if hasattr(self,'prefer_arabic_numbers') else None,
                local_without_key=local_without_key,
            )
            self._text_ai_local_roles = tuple(result.get("local_roles") or ())
            _secret_save_trace("after_persist_ai_configuration", self.polish_editor, self.polish_editor.values(), extra={"editor": "polish"})
            _secret_save_trace("after_persist_ai_configuration", self.group_editor, self.group_editor.values(), extra={"editor": "group"})
        except Exception as exc:
            self._run_block_reason = f"AI 配置未保存：{exc}"
            self.ai_panel.set_expanded(True)
            self.ai_save_status.setObjectName("statusWarn")
            bind_text(self.ai_save_status, '保存失败：{exc}', exc=exc)
            self.ai_save_status.style().unpolish(self.ai_save_status)
            self.ai_save_status.style().polish(self.ai_save_status)
            if show_feedback:
                QMessageBox.warning(self, tr('AI 配置未保存'), str(exc))
            return False
        self._apply_saved_ai_configuration(source='applied', saved=True)
        # 方案书签同步：保存 AI 配置是唯一权威写入时刻。不同步的话，识别
        # 方案快照里的旧 llm_config_ref 会在下次启动/切方案时把已保存的
        # 模型选择覆盖回去（vision-exp 反复复活的第二环）。
        try:
            current_profile = getattr(self, "current_project_profile", None)
            if current_profile is not None:
                saved_ref = str(self.group_editor.model.currentText() or "").strip()
                saved_llm_config = self._llm_profile_configuration()
                if (
                    str(current_profile.llm_config_ref) != saved_ref
                    or bool(current_profile.llm_enabled) != self.ai_grouping.isChecked()
                    or getattr(current_profile, "llm_config", {}) != saved_llm_config
                ):
                    current_profile = self.profile_store.update(
                        current_profile.id,
                        llm_config_ref=saved_ref,
                        llm_enabled=self.ai_grouping.isChecked(),
                        llm_config=saved_llm_config,
                    )
                    self.current_project_profile = current_profile
        except Exception as exc:
            self._run_block_reason = f"AI 配置已保存，但当前方案保存失败：{exc}"
            self.ai_save_status.setText(self._run_block_reason)
            return False
        self._refresh_ai_summary()
        missing = result["missing_keys"]
        language = getattr(self, "_ui_language", current_language())
        # 2026-10-15: a step without a key is not a problem any more; it runs
        # on the local rules until a key is filled in.
        self.ai_save_status.setObjectName("muted" if missing else "statusGood")
        (bind_text(self.ai_save_status, translate('已保存。没填 Key 的步骤会用本地规则：', language) + '、'.join(translate(item, language) for item in missing)) if missing else bind_text(self.ai_save_status, credential_storage_notice(language) if session_credentials_enabled() else translate('AI 配置与密钥已保存，重启后仍会保留', language)))
        self.ai_save_status.style().unpolish(self.ai_save_status)
        self.ai_save_status.style().polish(self.ai_save_status)
        self._refresh_home_process_facts()
        return True

    def _apply_unified_glm_mode(self, checked: bool):
        use_ai_grouping = self.ai_grouping.isChecked()
        enable_ai_polish = self.ai_polish.isChecked()
        self.unified_glm.setEnabled(use_ai_grouping and enable_ai_polish)
        unified = bool(checked and use_ai_grouping and enable_ai_polish)
        separate = self.__dict__.get("separate_group_service")
        if separate is not None:
            with QSignalBlocker(separate):
                separate.setChecked(not self.unified_glm.isChecked())
            separate.setEnabled(use_ai_grouping and enable_ai_polish)
        self._place_ai_editors(unified, enable_ai_polish, use_ai_grouping)
        own_key = use_ai_grouping and enable_ai_polish and not unified
        self.share_key.setVisible(own_key)
        note = self.__dict__.get("separate_group_note")
        if note is not None:
            note.setVisible(not own_key)   # the key switch takes the note's place on that row
        self.group_editor.title_label.setText(
            "统一校对与断句模型" if unified else "全文断句模型"
        )
        self.group_editor.setToolTip(
            "这一套模型、地址和密钥将同时用于字幕校对与全文断句。"
            if unified
            else "仅用于全文断句。"
        )
        self._refresh_ai_summary()

    def _place_ai_editors(self, unified: bool, polish_on: bool, group_on: bool) -> None:
        """One form on top (2026-10-22, design B): the shared service, or 校对
        and translation when line breaking has its own service, which then
        sits in 高级设置. The top form's model, address and protocol live in
        高级设置 too. With both stages off the 校对 form stays: translation
        uses it."""
        if "ai_main_slot" not in self.__dict__:
            return
        main = self.group_editor if unified or (group_on and not polish_on) else self.polish_editor
        second = self.group_editor if main is self.polish_editor and polish_on and group_on else None
        target, other = ((self.ai_second_slot, self.ai_main_slot) if second is self.group_editor
                         else (self.ai_main_slot, self.ai_second_slot))
        if target.indexOf(self.group_editor) < 0:
            other.removeWidget(self.group_editor)
            target.addWidget(self.group_editor)
        for editor in (self.polish_editor, self.group_editor):
            if editor is not main:
                editor.restore_advanced()
                editor.restore_guide()
                editor.set_emphasis(test=False, guide=False)
                editor.set_bare(False)
                editor.key_help_button.hide()
        main.host_advanced(self.ai_advanced_editor_slot)
        main.host_guide(self.ai_guide.guide_slot)
        main.set_bare(True)
        main.key_help_button.show()
        self.polish_editor.setVisible(main is self.polish_editor)
        self.group_editor.setVisible(main is self.group_editor or second is self.group_editor)
        # No titles: the top form is the dialog's subject, the second one sits
        # under 「断句另用一个服务」 (2026-10-22: no row for a few words).
        main.title_label.hide()
        if second is not None:
            second.title_label.hide()
        self._ai_main_editor = main
        self._refresh_ai_advanced_summary()
        fit = self.__dict__.get("_ai_dialog_fit")
        if fit is not None:
            QTimer.singleShot(0, fit)

    def _show_ai_advanced(self, shown: bool) -> None:
        self.ai_advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        self.ai_advanced_box.setVisible(bool(shown))
        self.ai_advanced_summary.setVisible(not shown)
        fit = self.__dict__.get("_ai_dialog_fit")
        if fit is not None:
            QTimer.singleShot(0, fit)

    def _refresh_ai_advanced_summary(self, *_args) -> None:
        """What 高级设置 holds, on its closed line: model, address, the line-breaking service."""
        label = self.__dict__.get("ai_advanced_summary")
        main = self.__dict__.get("_ai_main_editor")
        if label is None or main is None:
            return
        values = main.values()
        # A step shown off for lack of a key (_sync_ai_switches_with_keys) is not listed.
        duties = [str(tr(name)) for name, switch in (("断句", self.ai_grouping), ("校对", self.ai_polish),
                                                     ("数字", self.prefer_arabic_numbers)) if switch.is_shown_on()]
        parts = [str(tr("AI 负责：{duties}", duties=" · ".join(duties))) if duties else str(tr("AI 负责的事都关着"))]
        parts.append(str(tr("模型 {model}", model=values.get("model") or tr("默认模型"))))
        if self.separate_group_service.isChecked() and self.separate_group_service.isEnabled():
            parts.append(str(tr("断句另用一个服务")))
        label.setText("  ｜  ".join(parts))

    def _refresh_ai_dialog_state(self, *_args) -> None:
        """Where the AI settings stand (2026-10-22, design D2 refined): the tag,
        the guide column, and the one pink button of the moment — 申请教程
        without a key, 测试连接 once one is in, 保存设置 after a passed test."""
        from ..providers import ai_connection_record as record
        from .ai_settings_widgets import FAILED, NO_KEY, OFF, READY, UNTESTED
        from .home_ai_widgets import STATE_CHIP
        editor = self.__dict__.get("_ai_main_editor") or self._primary_ai_editor()
        stage = "group" if editor is self.group_editor else "polish"
        draft = bool(getattr(self, "_ai_has_draft", False))
        result = getattr(editor, "last_connection_ok", None)
        try:
            gate = record.feature_gate(self.legacy.RUNTIME_SETTINGS, stage)
        except Exception:  # noqa: BLE001 - unknown is not connection evidence
            gate = record.UNTESTED
        if not (self.ai_polish.isChecked() or self.ai_grouping.isChecked()):
            state = OFF
        elif result is True:
            state = READY
        elif result is False:
            state = FAILED
        elif not editor.has_key():
            state = NO_KEY
        elif not draft and gate in (READY, FAILED):
            state = gate
        else:
            state = UNTESTED
        service = editor.service.currentText().split("（")[0].strip()
        guide = self.__dict__.get("ai_guide")
        if guide is not None:
            detail = ""
            if state == READY:
                # When it passed; the model is on the 更多选项 line below.
                checked = record.checked_at(self.legacy.RUNTIME_SETTINGS, stage) if not draft else ""
                if result is True:
                    detail = str(tr("刚刚测试通过"))
                elif len(checked) >= 16 and checked[:10] == time.strftime("%Y-%m-%d"):
                    detail = str(tr("今天 {time} 测试通过", time=checked[11:16]))
                elif len(checked) >= 16:
                    detail = str(tr("{time} 测试通过", time=checked[5:16].replace("T", " ")))
            guide.set_state(state, service=service, detail=detail, fresh=result is True,
                            features={"group": self.ai_grouping.isChecked(), "polish": self.ai_polish.isChecked()})
        editor.set_emphasis(test=state in (UNTESTED, FAILED), guide=state == NO_KEY)
        editor.key_help_button.setVisible(state != READY)   # connected: no need to explain the key
        if state == NO_KEY:
            # A space only between Chinese and a Latin name (打开 DeepSeek 申请教程, 打开阿里云百炼申请教程);
            # the other languages' sentences carry their own spaces.
            from ..i18n import current_language
            spaced = service
            if current_language().startswith("zh"):
                spaced = (" " if service[:1].isascii() else "") + service + (" " if service[-1:].isascii() else "")
            bind_text(editor.guide_button, '打开{service}申请教程', service=spaced)
        else:
            bind_text(editor.guide_button, '再看一次申请教程')
        editor.guide_button.setVisible(state != READY)
        bind_text(editor.test_button, '重新测试' if state == READY else '测试连接')
        if state == READY and result is None and editor.status.objectName() != "statusWarn":
            # Connected from an earlier test: say so beside the button (the guide
            # column names the model and when it passed).
            editor.status.setObjectName("statusGood")
            bind_text(editor.status, '连接正常')
            editor.status.style().unpolish(editor.status)
            editor.status.style().polish(editor.status)
        editor.test_button.setEnabled(editor.has_key() or state == READY)
        save = self.__dict__.get("ai_dialog_save_button")
        if save is not None:
            dialog = self.__dict__.get("_ai_settings_dialog")
            if dialog is not None and dialog.property("enableGroupingIntent"):
                bind_text(save, "保存并启用断句" if self.ai_grouping.isChecked() else "保存设置")
            from ..design.presentation import button_role
            role = "primary" if state == READY else "secondary"
            if save.property("buttonRole") != role:
                save.setObjectName("primary" if state == READY else "aiDialogSave")
                button_role(save, role)
                save.style().unpolish(save)
                save.style().polish(save)
        fit = self.__dict__.get("_ai_dialog_fit")
        if fit is not None:   # texts change with the state; never leave a scroll bar behind
            QTimer.singleShot(0, fit)
        label = self.__dict__.get("ai_dialog_state_label")
        if label is None:
            return
        if state == READY:
            text, tone = ("连接正常 · 保存后生效" if draft else "已连接"), "ready"
        elif state == FAILED:
            text, tone = "测试没通过", "warn"
        else:
            text, tone = STATE_CHIP.get(state, "未连接"), "lock"
        bind_text(label, text)
        label.setProperty("state", tone)
        label.style().unpolish(label)
        label.style().polish(label)

    def _sync_ai_switches_with_keys(self, *_args) -> tuple:
        """Show a text-AI step switched off while its key is missing (2026-10-21).

        User: many people do not want to fill in a key, so without one AI
        校对 / AI 断句 are off by default. The switch keeps the saved choice
        (``isChecked()``) and is only shown off and locked; a key typed in or
        saved for that service shows the choice again. Returns the steps that
        are shown off.
        """
        if not all(hasattr(self, name) for name in ("polish_editor", "group_editor", "ai_key_off_note")):
            return ()
        missing = text_ai_roles_without_key(
            self.legacy, self.polish_editor.values(), self.group_editor.values(),
            unified=self.unified_glm.isChecked(), share_key=self.share_key.isChecked())
        forced = tuple(role for role, switch in (("polish", self.ai_polish), ("group", self.ai_grouping))
                       if role in missing and switch.isChecked())
        self.ai_polish.set_forced_off("polish" in forced)
        self.ai_grouping.set_forced_off("group" in forced)
        note = {
            ("polish", "group"): "没填 API Key：AI 校对和 AI 断句先关闭，这时用本地规则断句。在下面填好 Key 就会自动打开。",
            ("group",): "全文断句模型没填 API Key：AI 断句先关闭，这时用本地规则断句。填好 Key 就会自动打开。",
            ("polish",): "字幕校对模型没填 API Key：AI 校对先关闭（字幕照常生成）。填好 Key 就会自动打开。",
        }.get(forced, "")
        if note:
            bind_text(self.ai_key_off_note, note)
        self.ai_key_off_note.setVisible(bool(note))
        return forced

    def _apply_ai_grouping_mode(self, enabled: bool):
        enabled = bool(enabled)
        self.unified_glm.setEnabled(enabled)
        if not enabled and self.unified_glm.isChecked():
            self.unified_glm.setChecked(False)
        self._apply_unified_glm_mode(self.unified_glm.isChecked())
        if hasattr(self, "refresh_group"):
            self.refresh_group.setEnabled(enabled)

    @glossary_write_errors
    def _add_custom_term(self):
        game_name = self.legacy.canonicalize_runtime_game_name(self.game_box.currentText())
        if not game_name:
            QMessageBox.information(self, tr('添加术语'), tr('请先输入或选择游戏 / 内容名称。'))
            return
        value = self.term_input.text().strip()
        if not value:
            return
        if self.legacy.add_learned_mapping(game_name, value, value):
            self.term_input.clear()
            bind_text(self.term_hint, '已添加术语：{value}（可在“术语库与学习记录”中删除）', value=value)
            self.term_hint.setVisible(bool(self.term_hint.text()))
        else:
            QMessageBox.information(self, tr('添加术语'), tr('该术语已存在或内容为空。'))

    def _manage_terms(self):
        # Full CRUD is a resident page. The lightweight per-batch selector
        # remains in _pick_glossaries().
        self._switch_page(self.term_library_page)
        QTimer.singleShot(0, self.term_library_page, self.term_library_page.prepare_for_show)

    def _ensure_runtime_environment(self):
        """Offer Repair Mode when preflight fails.  Versions stay in details."""
        from twobyteasr.environment_repair import (
            diagnose_repair,
            repair_roles,
            user_facing_copy,
        )

        settings = json.loads(json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False))
        settings.setdefault("models", {}).update(self._asr_values())
        plan = diagnose_repair(settings)
        if plan is None:
            return True
        copy = user_facing_copy(plan.failures)
        while True:
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Icon.Warning)
            message.setWindowTitle(copy.title)
            message.setText(copy.title)
            message.setInformativeText(copy.subtitle)
            repair_button = message.addButton(
                copy.repair_label, QMessageBox.ButtonRole.AcceptRole
            )
            details_button = message.addButton(
                copy.details_label, QMessageBox.ButtonRole.ActionRole
            )
            message.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            message.exec()
            clicked = message.clickedButton()
            if clicked is details_button:
                details = QMessageBox(self)
                details.setIcon(QMessageBox.Icon.Information)
                details.setWindowTitle(copy.details_label)
                details.setText(copy.subtitle)
                bind_text(details, copy.details or '没有额外技术细节。', property='informativeText')
                repair_from_details = details.addButton(
                    "立即修复", QMessageBox.ButtonRole.AcceptRole
                )
                details.addButton("返回", QMessageBox.ButtonRole.RejectRole)
                details.exec()
                if details.clickedButton() is not repair_from_details:
                    continue
                clicked = repair_button
            if clicked is not repair_button:
                return False
            progress = QMessageBox(self)
            progress.setIcon(QMessageBox.Icon.Information)
            progress.setWindowTitle(copy.title)
            bind_text(progress, '正在修复运行环境，请稍候…')
            bind_text(progress, '只重建不兼容的环境，成功后才会替换。', property='informativeText')
            progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
            progress.show()
            QApplication.processEvents()
            try:
                result = repair_roles(plan.roles)
            finally:
                progress.close()
            if result.ok:
                # A successful staging swap is not enough to claim recovery.
                # Re-probe the live interpreter immediately so the user sees
                # the actual post-repair state and failing module, if any.
                follow = diagnose_repair(settings, roles=plan.roles)
                if follow is None:
                    QMessageBox.information(
                        self, copy.title, result.success_message
                    )
                    return True
                plan = follow
                copy = user_facing_copy(plan.failures)
                QMessageBox.warning(
                    self,
                    copy.title,
                    tr('修复后重新检查仍未通过。\n\n{value0}', value0=copy.details or tr('未能确定具体失败模块。')),
                )
                return False
            QMessageBox.warning(
                self,
                copy.title,
                tr('修复未完成，原环境已保留。\n\n{value0}', value0=result.error or tr('请关闭 2ByteASR 后从配置器点击“重新检查”。')),
            )
            return False

    def _ensure_cuda_runtime(self):
        from twobyteasr.system.hardware import (
            detect_torch_audio_runtime,
            selected_cuda_components,
            selected_local_runtime_components,
        )

        settings = json.loads(json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False))
        settings.setdefault("models", {}).update(self._asr_values())
        local_components = selected_local_runtime_components(settings)
        local_status = detect_torch_audio_runtime()
        if local_components and not local_status.ready:
            QMessageBox.critical(
                self,
                tr('本地模型运行库需要修复'),
                tr('{value0}\n\n{value1}\n\n请打开模型工坊，选择当前模型并点击“校验并修复”。', value0=local_status.summary, value1=local_status.guidance),
            )
            return False
        required = selected_cuda_components(settings)
        if not required:
            return True
        status = detect_cuda_runtime()
        if status.ready:
            return True
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Critical)
        bind_text(message, '当前模型组合需要 NVIDIA CUDA GPU', property='windowTitle')
        bind_text(message, '当前组合中的以下组件需要 CUDA：\n{value0}', value0='\n'.join((f'• {item}' for item in required)))
        bind_text(message, '{value0}\n\n{value1}\n\n处理完成后请关闭并重新打开 2ByteASR。\nNVIDIA 驱动：https://www.nvidia.com/Download/index.aspx', property='informativeText', value0=status.summary, value1=status.guidance)
        bind_text(message, '诊断代码：{value0}\nGPU：{value1}\n显存：{value2} MB\nNVIDIA 驱动：{value3}\nPyTorch：{value4}\nPyTorch CUDA 构建：{value5}', property='detailedText', value0=status.code, value1=status.gpu_name or '未检测到', value2=status.memory_mb or 0, value3=status.driver_version or '未检测到', value4=status.torch_version or '未检测到', value5=status.cuda_version or '无')
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.exec()
        return False

    def _release_run_state(self):
        """统一释放 active run 状态（P1-4）。

        完成 / 失败 / 取消 / 启动前异常 / 验证提前返回 全部经由这里释放；
        worker.start() 成功后由 _handle_result / _handle_unexpected_error
        在 worker 生命周期结束时调用。
        """
        self._run_in_progress = False
        self.start_button.setEnabled(bool(self.media_paths))
        self.cancel_run_button.setEnabled(False)

    def _prepare_glossary_for_task(self):
        """Commit an open library editor before a new task freezes its snapshot."""
        dialog = getattr(self, '_term_library_dialog', None)
        if dialog is None:
            return True
        if getattr(self, '_preparing_glossary_for_task', False):
            return False
        self._preparing_glossary_for_task = True
        try:
            return bool(dialog.prepare_for_task())
        finally:
            self._preparing_glossary_for_task = False

    def _start_run(self):
        # P1-4 重入守卫：任意时刻最多一个 active run。必须在任何耗时准备
        # （CUDA 探测、配置保存、文件检查、token/worker 构建）之前声明占用；
        # 重复调用为 no-op（不创建 token、不覆盖 worker、不重置 UI）。
        if getattr(self, '_completion_retry_in_progress', False):
            self._run_block_reason = "已有校对或核验预览在进行中，请先完成或取消预览。"
            return
        if self._run_in_progress:
            self._run_block_reason = "已有识别任务在进行中，请等待完成或先取消。"
            return
        if getattr(self, '_retry_run_options', None) is None and not self._prepare_glossary_for_task():
            self._run_block_reason = '词库编辑尚未提交；请保存或取消编辑后继续。'
            return
        # 四十二轮：早退分支的原因都记录在 _run_block_reason，供 Studio 后台
        # 识别把失败原因显示到字幕列表芯片（弹窗已关，看不到对话框的场景）。
        self._run_block_reason = ""
        self._run_in_progress = True
        self.start_button.setEnabled(False)
        launched = False
        try:
            if not self.media_paths:
                self._run_block_reason = "还没有素材：请先拖入或选择视频 / 音频文件。"
                QMessageBox.information(self, tr('还没有素材'), tr('请先拖入或选择视频 / 音频文件。'))
                return
            retry_options = getattr(self, '_retry_run_options', None)
            if retry_options is not None:
                # Retrying failed stages has immutable task ownership. Do not
                # save/read the currently edited Home settings or glossary.
                self._launch_pipeline_worker(retry_options)
                self._retry_run_options = None
                self._retry_cached_failed = False
                launched = True
                return
            if self.primary_asr_backend.currentData() == "none":
                self._run_block_reason = (
                    "当前没有可运行的主力转写模型：请到模型工坊下载并选择模型，或配置在线 ASR API。"
                )
                message = QMessageBox(self)
                message.setIcon(QMessageBox.Icon.Information)
                bind_text(message, '请先选择主力模型', property='windowTitle')
                bind_text(message, '当前没有可运行的主力转写模型。')
                bind_text(message, '请先到模型工坊下载并选择模型，或配置在线 ASR API。', property='informativeText')
                open_workshop = message.addButton("打开模型工坊", QMessageBox.ButtonRole.AcceptRole)
                message.addButton("暂不处理", QMessageBox.ButtonRole.RejectRole)
                message.exec()
                if message.clickedButton() is open_workshop:
                    self._open_model_workshop()
                return
            effective = _language_preflight_values(self._asr_values(),
                self._subtitle_language_options()['recognition_language'], self.legacy.RUNTIME_SETTINGS)
            missing_models = missing_selected_local_models(effective)
            if missing_models:
                self._run_block_reason = "所选模型尚未下载完整：" + "、".join(missing_models)
                message = QMessageBox(self)
                message.setIcon(QMessageBox.Icon.Warning)
                bind_text(message, '所选模型尚未下载完整', property='windowTitle')
                bind_text(message, '当前组合不能开始运行：')
                message.setInformativeText("\n".join(f"• {item}" for item in missing_models))
                open_workshop = message.addButton("打开模型工坊", QMessageBox.ButtonRole.AcceptRole)
                message.addButton("返回设置", QMessageBox.ButtonRole.RejectRole)
                message.exec()
                if message.clickedButton() is open_workshop:
                    self._open_model_workshop()
                return
            home_audio_streams = ''
            if not getattr(self, '_studio_recognition_context', None):
                # 2026-10-24: a file with several audio tracks first asks which
                # ones to recognize (home_audio_tracks); its 开始识别 resumes here.
                choice = self.__dict__.pop('_home_audio_track_choice', None)
                if choice is not None and choice[0] == tuple(self.media_paths):
                    home_audio_streams = choice[1]
                else:
                    from .home_audio_tracks import begin as ask_audio_tracks
                    if ask_audio_tracks(self, self._resume_with_audio_tracks):
                        self._run_block_reason = '正在选择要识别的音轨。'
                        return
            if not self._save_asr_configuration(show_feedback=True, require_ready=True):
                return
            # 方案身份 + 脱敏生效参数留痕：验证"用 A/B 启动识别实际参数不同"。
            try:
                from urllib.parse import urlsplit

                _models = self.legacy.RUNTIME_SETTINGS.get("models", {})
                _profile = getattr(self, "current_project_profile", None)
                _url = str(_models.get("qwen_asr_api_url", ASR_API_PRESETS["qwen31_filetrans"]["url"]) or "")
                GLOBAL_STUDIO_TRACE.emit(
                    "PROFILE_RUN",
                    {
                        "profile_id": _profile.id if _profile else "",
                        "profile_name": _profile.name if _profile else "custom",
                        "primary": _models.get("primary_asr_backend", ""),
                        "review": _models.get("qwen_asr_backend", ""),
                        "timeline": _models.get("firered_asr_backend", ""),
                        "api_provider": _models.get("qwen_asr_api_provider", ""),
                        "api_protocol": _models.get("qwen_asr_api_protocol", ""),
                        "api_model": _models.get("qwen_asr_api_model", ""),
                        "api_host": urlsplit(_url).netloc if _url else "",
                        "transcribe_style": _models.get("api_transcribe_style", ""),
                    },
                )
            except Exception:
                pass
            # P0 CRITICAL FIX:
            # NEVER call blocking environment repair dialogs, heavy torch imports,
            # or any synchronous preflight that can freeze the main thread when
            # the user clicks "开始生成字幕".
            #
            # Root cause of the reported freeze + spurious repair:
            #   - _ensure_runtime_environment() popped QMessageBox + ran diagnose/repair on UI thread.
            #   - _ensure_cuda_runtime() did torch detection + critical dialogs on UI thread.
            #   - Plus a contract contradiction: main had huggingface_hub==1.24.0 while
            #     transformers==4.57.6 requires huggingface-hub<1.0 → pip resolver blew up during repair.
            #
            # Correct architecture:
            #   - The single source of truth is dependencies.lock.json (environments.main / environments.moss).
            #   - The authoritative gate is inside the worker thread: run_media_queue → ensure_environment_ready.
            #   - UI only does cheap non-blocking hints here.
            #
            # We intentionally skip _ensure_runtime_environment() and _ensure_cuda_runtime()
            # in the hot path. If the worker later fails preflight, it returns failed results
            # and the result handler can offer repair without ever freezing the "Start" click.

            # Ultra-light non-blocking hint only (no dialogs, no heavy imports on this thread).
            try:
                from twobyteasr.system.environment import fast_preflight, required_environment_roles
                settings = json.loads(json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False))
                settings.setdefault("models", {}).update(self._asr_values())
                for r in required_environment_roles(settings):
                    try:
                        fr = fast_preflight(r)
                        if not fr.ok:
                            self._append_console_line(f"[env] {r} 快速检查提示：将在后台验证。")
                    except Exception:
                        pass
            except Exception:
                pass

            local_analysis=(getattr(self,'_studio_recognition_context',None) or {}).get('recognition_purpose')=='analysis'
            # 2026-10-15: a text-AI step without a key runs on the local rules
            # (users who never fill in a key still get exportable subtitles).
            if not self._save_ai_configuration(show_feedback=True, require_ready=not local_analysis,
                                               local_without_key=True):
                return
            if local_analysis:
                self._text_ai_local_roles = ()   # an analysis run has no text-AI steps at all
            if not self._confirm_run_limits():
                return
            if not self._confirm_run_disclosure():
                return
            game_name = self.legacy.canonicalize_runtime_game_name(self.game_box.currentText())
            if game_name:
                self.legacy.save_runtime_game_history(game_name)
            coverage_control = self.__dict__.get("dialogue_coverage")
            if coverage_control is not None:
                coverage_mode = str(coverage_control.currentData() or "all_dialogue")
            else:
                coverage_mode = str(
                    getattr(self.legacy, "RUNTIME_DIALOGUE_COVERAGE_MODE", "")
                    or getattr(self.legacy, "RUNTIME_SETTINGS", {})
                    .get("switches", {})
                    .get("dialogue_coverage_mode", "all_dialogue")
                    or "all_dialogue"
                )
            studio_context = getattr(self, "_studio_recognition_context", None) or {}
            enabled_glossary_ids, terms_enabled = self._task_glossary_selection()
            # Persist output extras so the same-folder artifact set stays stable
            # between runs (merged SRT is always written; txt/per-speaker opt-in).
            try:
                switches = self.legacy.RUNTIME_SETTINGS.setdefault("switches", {})
                switches["output_jianying_txt"] = self.jianying_txt.isChecked()
                switches["output_speaker_tracks"] = self.speaker_tracks.isChecked()
                save_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            except Exception:
                pass
            from ..glossary.terminology import snapshot_glossaries
            language_options = studio_translation_choice(
                self._subtitle_language_options(), studio_context, _ai_unlocked(self))
            options = RunOptions(
                **language_options,
                settings_snapshot_json=json.dumps(self._run_settings_snapshot(), ensure_ascii=False),
                glossary_snapshot_json=json.dumps(
                    snapshot_glossaries(self.legacy, enabled_glossary_ids if terms_enabled else ()).to_dict(),
                    ensure_ascii=False),
                content_name=game_name,
                enable_domain_terms=terms_enabled,
                enable_term_search=bool(getattr(self, 'term_search', None) and self.term_search.isChecked()
                                        and _ai_unlocked(self)),
                enabled_glossary_ids=enabled_glossary_ids,
                output_review_track=self.review_track.isChecked(),
                output_jianying_txt=self.jianying_txt.isChecked(),
                output_speaker_tracks=self.speaker_tracks.isChecked(),
                force_refresh_polish=self.refresh_polish.isChecked() and not getattr(self,'_retry_cached_failed',False),
                force_refresh_group=self.refresh_group.isChecked() and not getattr(self,'_retry_cached_failed',False),
                expected_speakers=(
                    int(self.expected_speakers.currentText())
                    if self.expected_speakers.currentText().isdigit()
                    else 0
                ),
                dialogue_coverage_mode=coverage_mode,
                overwrite_policy='overwrite' if getattr(self,'_retry_cached_failed',False) else str(self.overwrite.currentData()),
                studio_project_path=str(
                    (getattr(self, "_studio_recognition_context", None) or {}).get(
                        "project_path", ""
                    )
                ),
                recognition_purpose=str(
                    (getattr(self, "_studio_recognition_context", None) or {}).get(
                        "recognition_purpose", "final"
                    )
                ),
                recognition_snapshot_json=json.dumps(
                    (getattr(self, "_studio_recognition_context", None) or {}).get("snapshot", {}),
                    ensure_ascii=False,
                ),
                speaker_source=__import__('twobyteasr.recognition.speaker_strategy',fromlist=['resolve']).resolve(
                    self.legacy.RUNTIME_SETTINGS,(getattr(self, "_studio_recognition_context", None) or {}).get("speaker_source")),
                audio_streams_json=home_audio_streams,
            )
            self._last_run_options = options
            self._launch_pipeline_worker(options)
            launched = True
            local_note = self._text_ai_local_note()
            if local_note:
                self._append_feed('任务配置', local_note, BLUE)
                self._append_console_line('[本次识别] ' + local_note)
            started_profile = getattr(self, 'current_project_profile', None)
            started_configuration = self._profile_configuration()
            try:
                self.profile_store.record_started(started_profile.id if started_profile else '',
                    started_configuration, self.media_paths)
            except (OSError, ValueError) as exc:
                bind_text(self.profile_recommendation, '识别已启动；上次运行配置保存失败：{exc}', exc=exc)
        finally:
            if not launched:
                self._release_run_state()

    def _resume_with_audio_tracks(self, paths, request):
        """The home track picker's 开始识别: start the run with these picks."""
        self._home_audio_track_choice = (tuple(paths), str(request or ''))
        QTimer.singleShot(0, self, self._start_run)

    def _dispatch_recognition_job(self, job_id, callback, *args, allow_committed=False):
        """Queued signals belong to the launching job, never the current title."""
        if job_id != getattr(self, '_active_job_id', None):
            return False
        if not allow_committed and job_id in getattr(self, '_committed_job_ids', set()):
            return False
        callback(*args)
        return True

    def _launch_pipeline_worker(self, options):
        options = replace(options, job_id=uuid.uuid4().hex)
        self._last_run_options = options
        self._active_job_id = options.job_id
        self._committed_job_ids = getattr(self, '_committed_job_ids', set())
        self._cancelled_job_ids = getattr(self, '_cancelled_job_ids', set())
        self.token = CancellationToken()
        self.worker = PipelineWorker(self.media_paths, options, self.token, self.legacy,
                                     self.pipeline, self.startup_self_test)
        job_id = options.job_id
        self.worker.event_received.connect(lambda event: self._dispatch_recognition_job(job_id, self._handle_event, event))
        self.worker.console_received.connect(lambda line: self._dispatch_recognition_job(job_id, self._append_console_line, line))
        self.worker.result_ready.connect(lambda result: self._dispatch_recognition_job(job_id, self._handle_result, result))
        self.worker.unexpected_error.connect(lambda error: self._dispatch_recognition_job(job_id, self._handle_unexpected_error, error))
        self.worker.finished.connect(lambda: self._dispatch_recognition_job(job_id, self._release_run_state))
        self.started_at = time.perf_counter()
        self._active_stages.clear()
        self._completed_stages.clear()
        self._skipped_stages = set()
        self._recognition_terminal = ''
        self._recognition_live_work = {}
        self._phase_degraded = {}
        self._feed_stage_rows = {}
        self._reset_progress_presentation()
        if hasattr(self, 'recognition_live_status'):
            bind_text(self.recognition_live_status, '正在准备识别任务；临时转写将在实际批次完成后显示')
        self._failed_stages.clear()
        self.event_log.clear()
        self.console_log.clear()
        self._console_lines = []
        self._console_levels = []
        self._console_fragments = []
        self.progress_bar.setValue(0)
        self.progress_percent.setText('0%')
        self.cancel_run_button.setEnabled(True)
        self._append_feed('准备', '配置已确认，正在建立任务队列', GREEN)
        self._refresh_progress_cards()
        self._progress_timer.start()
        self.workflow.set_active(0)
        if not getattr(self, '_studio_recognition_context', None):
            self._switch_page(1)
        self.worker.start()
        self._retry_cached_failed = False

    def _stage_group(self, stage_index: int) -> int:
        """Display phase of a step, following the run's real step count
        (11 with AI proofreading, 10 without, 8 for analysis runs)."""
        from .progress_model import phase_ranges
        for index, ids in enumerate(phase_ranges(getattr(self, '_stage_total', 11))):
            if stage_index in ids:
                return index
        return 0 if stage_index < 1 else 3

    def _append_feed(self, badge: str, message: str, color: str = MUTED, *, nested=None, meta='', **arguments):
        primary = {'开始', '运行中', '完成', '已回退', '失败', '跳过', '准备', '素材', '取消',
                   '已取消', '未完成', '已停止', '已结束'}
        nested = badge not in primary if nested is None else nested
        card = TaskEventCard(badge, message, color, nested=nested, meta=meta)
        if arguments:
            card.set_event(badge, template=message, **arguments)
        self.event_log.add_row(card)
        # Only the newly created card needs a language overlay. Walking the
        # complete window here made long runs progressively more expensive.
        apply_ui_language(card, getattr(self, "_ui_language", "zh"))
        return card

    def _feed_stage(self, event):
        """One record row per step: started → finished/fallback/failed in
        place, named in plain words (technical label on hover), with the
        live elapsed time while it runs (2026-10-08, M12)."""
        from shiboken6 import isValid
        from .progress_model import stage_record_name
        rows = self.__dict__.setdefault('_feed_stage_rows', {})
        key = (event.media_index, event.stage_index, str(event.label))
        name = tr(stage_record_name(event.label))
        technical = join_text((tr(event.label), tr(event.resource))) if event.resource else tr(event.label)
        if event.kind == 'stage_started':
            card = self._append_feed('运行中', '{stage}', meta='00:00', stage=name)
            if card is not None:
                card._started_at = time.perf_counter()
                card.setToolTip(technical)
            rows[key] = card
            return
        card = rows.pop(key, None)
        group = self._stage_group(event.stage_index)
        duration = self._duration_text(event.elapsed_seconds)
        if event.kind == 'stage_skipped':
            badge, template, arguments, duration = '跳过', '{stage} · 本次配置不适用', dict(stage=name), ''
        elif event.kind == 'stage_completed' and self._is_ai_text_step(event.stage_index) and group in self._phase_degraded:
            badge, template, arguments = '已回退', '{stage} · {detail}', dict(
                stage=name, detail=self._phase_degraded[group])
        elif event.kind == 'stage_completed':
            badge, template, arguments = '完成', '{stage}', dict(stage=name)
        else:
            badge, template, arguments = '失败', '{stage} · {error}', dict(stage=name, error=tr(event.error))
        usage = (getattr(self, '_usage_steps', {}) or {}).get(event.stage_index)
        if event.kind == 'stage_completed' and usage is not None and usage.calls:
            # The finished step's provider-reported usage stays in its record row (2026-10-15).
            from ..providers.api_usage import usage_text
            template, arguments = template + ' · {usage}', dict(arguments, usage=usage_text(usage))
        if card is not None and isValid(card):
            card._started_at = 0
            card.set_event(badge, template=template, **arguments)
            card.set_meta(duration)
            self.event_log.refit(card)
            self.event_log.scrollToBottom()
        else:
            card = self._append_feed(badge, template, meta=duration, **arguments)
        if card is not None:
            card.setToolTip(technical)

    def _append_console_line(self, line: str, level: str = "stdout"):
        compact = str(line or "").rstrip()
        if not compact:
            return
        if not hasattr(self, '_console_lines'):
            self._console_lines = []
            self._console_fragments = []
        self._console_lines.append(compact)
        lowered = compact.lower()
        if getattr(self, "_studio_recognition_context", None):
            if "cuda" in lowered or "显存" in compact:
                self.studio_page.set_recognition_runtime_stage("初始化 CUDA", compact)
            elif "加载" in compact and ("模型" in compact or "asr" in lowered):
                self.studio_page.set_recognition_runtime_stage("加载权重", compact)
            elif "转写" in compact or "短块" in compact:
                self.studio_page.set_recognition_runtime_stage("识别中", compact)
        if not hasattr(self, '_console_levels') or len(self._console_levels) != len(self._console_lines) - 1:
            self._console_levels = ['stdout'] * (len(self._console_lines) - 1)
        self._console_levels.append(level)
        fragment = log_line_html(compact, level, _active_theme_definition())
        self._console_fragments.append(fragment)
        append_log_html_keep_left(self.console_log, fragment)

    def _reset_progress_presentation(self):
        """Fresh per-run presentation state (2026-10-08, M12)."""
        self._stage_live = {}
        self._stage_partial = {}
        self._stopped_stages = set()
        self._last_completed_stage = None
        self._preview_buffer = []
        self._preview_family = None
        self._preview_batches = (0, 0)
        self._cancel_requested_at = 0.0
        self._cancel_feed_card = None
        self._worker_running = {}
        self._cloud_batches = {}
        # 2026-10-15: provider-reported usage (per step and for the whole
        # task), batches being processed and retries of online API steps.
        from ..providers.api_usage import UsageTotals
        self._usage_steps = {}
        self._usage_total = UsageTotals()
        self._cloud_inflight = {}
        self._cloud_retries = {}
        self._delivery_verified = False
        self._terminal_elapsed = 0.0
        self._last_clock_second = -1
        self._workflow_group = None
        self._current_media_index = 1
        self._current_media_total = max(1, len(getattr(self, 'media_paths', None) or []))
        self._current_media_name = ''
        button = getattr(self, 'cancel_run_button', None)
        if isinstance(button, QWidget):
            bind_text(button, '安全取消')
        preview = getattr(self, 'recognition_preview', None)
        if isinstance(preview, RecognitionPreview):
            preview.set_rows([])
        bar = getattr(self, 'progress_bar', None)
        if isinstance(bar, StageProgressBar):
            bar.set_segments(0, ())

    def _focus_stage(self):
        """The step the current card describes. A step with real live data
        leads (MOSS runs beside the quick voice check); otherwise the latest
        started step."""
        active = getattr(self, '_active_stages', {}) or {}
        if not active:
            return None
        live = getattr(self, '_stage_live', {})
        with_live = [stage for stage in active if stage in live]
        return max(with_live) if with_live else max(active)

    def _is_ai_text_step(self, stage_index) -> bool:
        total = int(getattr(self, '_stage_total', 11) or 11)
        return stage_index == total - 2 or (total == 11 and stage_index == 8)

    @staticmethod
    def _duration_text(seconds):
        from .progress_model import clock
        seconds = max(0.0, float(seconds or 0))
        return tr('{seconds:.1f} 秒', seconds=seconds) if seconds < 60 else clock(seconds)

    def _set_stage_device(self, text, tooltip='') -> None:
        label = getattr(self, 'stage_device_label', None)
        if label is None:
            return
        bind_text(label, text or '')
        label.setToolTip(str(tooltip or ''))
        label.setVisible(bool(text))

    def _set_stage_note(self, text, detail='') -> None:
        """One line on the card; the longer explanation behind 查看详情."""
        row = getattr(self, 'stage_note_row', None)
        if row is None:
            return
        self.stage_note.setText(str(text or ''))
        self.stage_note.setToolTip(str(text or ''))
        self.stage_note_detail.setText(str(detail or ''))
        self.stage_note_more.setVisible(bool(detail))
        if not detail and self.stage_note_more.isChecked():
            self.stage_note_more.setChecked(False)
        if text and getattr(self, '_stage_note_icon_key', None) is None:
            self._stage_note_icon_key = True
            self.stage_note_icon.setPixmap(_icon('fa5s.info-circle', _active_theme_definition().text_muted).pixmap(QSize(14, 14)))
        row.setVisible(bool(text))

    def _toggle_stage_note_detail(self, checked) -> None:
        self.stage_note_detail.setVisible(bool(checked) and bool(self.stage_note_detail.text()))
        bind_text(self.stage_note_more, '收起' if checked else '查看详情')

    def _refresh_progress_cards(self):
        """2026-10-08 (M12): one honest picture of the run.

        Steps, the running step's live facts, the bar and the record all come
        from pipeline events. Nothing estimates time left, nothing calls a
        quiet model stuck or a busy one healthy, and an ended run closes
        every card. 100% only after the save step completed.
        """
        from .progress_model import active_spans, ended_steps, overall_fraction, percent_text, phase_ranges
        terminal = getattr(self, '_recognition_terminal', '')
        total = max(1, int(getattr(self, '_stage_total', 11) or 11))
        completed = set(self._completed_stages)
        skipped = set(getattr(self, '_skipped_stages', ()))
        failed = set(self._failed_stages)
        ended = ended_steps(completed, skipped, failed, total)
        active_ids = set(self._active_stages)
        stopped = set(getattr(self, '_stopped_stages', ())) if terminal else set()
        degraded = getattr(self, '_phase_degraded', {})
        succeeded = terminal in {'success', 'degraded_success'}
        cancelling = bool(getattr(self, '_cancel_requested_at', 0)) and not terminal
        for index, (card, ids) in enumerate(zip(self.phase_cards, phase_ranges(total))):
            if not ids:
                state = "off"
            elif ids & failed:
                state = "failed"
            elif succeeded or ids <= ended:
                # A finished phase whose AI step fell back is not "done".
                state = "degraded" if index in degraded else "done"
            elif terminal:
                touched = ids & (ended | stopped)
                state = ("cancelled" if terminal == 'cancelled' else "stopped") if touched else "notrun"
            elif ids & active_ids:
                state = "active"
            else:
                state = "pending"
            card.set_state(state)
            card.set_detail(degraded.get(index, '') if state == 'degraded' else '')
            card.set_steps(len(ids & ended), len(ids))
        focus_id = self._focus_stage()
        if terminal:
            self._render_terminal_step(terminal, ended, total)
        elif cancelling:
            self._render_cancelling_step(focus_id, total)
        elif focus_id is not None:
            self._render_active_step(focus_id, total)
            group = self._stage_group(focus_id)
            # The refresh also runs once a second; restyle only on change.
            if getattr(self, '_workflow_group', None) != group:
                self._workflow_group = group
                self.workflow.set_active(group)
        elif ended:
            self._render_between_steps(ended, total)
        else:
            self._render_preparing_step()
        self._render_preview()

        media_total = max(1, self._current_media_total)
        media_index = max(1, self._current_media_index)
        partial = {stage: value for stage, value in getattr(self, '_stage_partial', {}).items() if stage in active_ids}
        fraction = overall_fraction(total, ended, partial, media_index, media_total)
        if succeeded and getattr(self, '_delivery_verified', False):
            fraction = 1.0
        value = max(0, min(1000, int(round(fraction * 1000))))
        if isinstance(self.progress_bar, StageProgressBar):
            self.progress_bar.set_segments(total if media_total == 1 else 0,
                                           () if terminal else active_spans(total, active_ids, media_index, media_total, ended))
        self.progress_bar.setRange(0, 1000)
        if self.progress_bar.value() != value:
            self._progress_motion.stop()
            self._progress_motion.setStartValue(self.progress_bar.value())
            self._progress_motion.setEndValue(value)
            self._progress_motion.start()
        self.progress_percent.setText(percent_text(fraction))
        done = len(ended)
        steps = getattr(self, 'progress_steps', None)
        if steps is not None:
            bind_text(steps, '{done} / {total} 步', done=done, total=total)
        if terminal:
            if succeeded:
                bind_text(self.progress_context, '已完成 {done} / {total} 步 · 工程已保存' if fraction >= 1
                          else '已完成 {done} / {total} 步 · 保存状态见结果页', done=done, total=total)
            elif terminal == 'cancelled':
                bind_text(self.progress_context, '任务已取消 · 已完成 {done} / {total} 步', done=done, total=total)
            else:
                bind_text(self.progress_context, '任务未完成 · 已完成 {done} / {total} 步', done=done, total=total)
        elif cancelling:
            bind_text(self.progress_context, '正在安全取消 · 已等待 {seconds} 秒',
                      seconds=int(max(0, time.perf_counter() - self._cancel_requested_at)))
        elif getattr(self, '_current_media_name', ''):
            bind_text(self.progress_context, '素材 {media_index} / {media_total} · {name}',
                      media_index=media_index, media_total=media_total, name=self._current_media_name)
        else:
            bind_text(self.progress_context, '素材 {media_index} / {media_total}',
                      media_index=media_index, media_total=media_total)
        title = getattr(self, 'progress_title', None)
        if title is not None:
            bind_text(title, '正在安全取消字幕任务' if cancelling else {
                'success': '字幕已制作完成', 'degraded_success': '字幕已完成，有需复核项',
                'cancelled': '字幕任务已取消', 'failed': '字幕任务未完成', 'unknown': '任务状态待确认',
            }.get(terminal, '2ByteASR 正在制作字幕'))

    def _render_active_step(self, focus_id, total):
        from .progress_model import (clock, moss_action, moss_description, resource_mode, stage_action,
                                     stage_description, stage_record_name)
        item = self._active_stages[focus_id]
        live = getattr(self, '_stage_live', {}).get(focus_id) or {}
        kind, payload = live.get('kind', ''), live.get('payload') or {}
        # One clock for everything shown (M13): "last output" can never be
        # older than the step or the task itself.
        now_perf = now = time.perf_counter()
        started = item.get('started')
        ceiling = min(value for value in (
            now - started if started else None,
            now - self.started_at if getattr(self, 'started_at', 0) else None,
            float('inf')) if value is not None)

        def since(at):
            return max(0.0, min(now - at, ceiling))
        moss = kind == 'asr_worker_progress' and payload.get('backend') == 'moss'
        self.running_indicator.set_status('运行中', 'accent')
        bind_text(self.stage_step_label, '第 {step} / {total} 步', step=focus_id, total=total)
        bind_text(self.progress_stage, moss_action(payload.get('phase')) if moss else stage_action(item.get('label')))
        metrics, quiet, wait = [], None, None
        if started:
            metrics.append((tr('已运行'), clock(now_perf - started)))
        if moss:
            if int(payload.get('window_count') or 0) > 1:
                # A long task runs as several windows (2026-10-13).
                metrics.append((tr('识别分段'), f"{int(payload['window_index'])} / {int(payload['window_count'])}"))
            tokens = payload.get('generated_tokens')
            metrics.append((tr('累计输出'), f"{int(tokens):,} tokens" if tokens is not None else tr('尚未开始')))
            if payload.get('phase') in {'completed', 'needs_review'}:
                metrics.append((tr('最近输出'), tr('已完成')))
            elif live.get('at'):
                quiet = since(live['at'])
                metrics.append((tr('最近输出'), tr('{seconds} 秒前', seconds=int(quiet))))
            else:
                metrics.append((tr('最近输出'), tr('尚无输出')))
            rate = payload.get('tokens_per_second')
            if payload.get('phase') == 'generation' and payload.get('prefill_running') and rate is None:
                # Before the first token the model reads the whole audio context;
                # that wait is not a generation rate.
                metrics.append((tr('生成速度'), tr('正在读取整段音频上下文…')))
            if payload.get('phase') == 'generation' and isinstance(rate, (int, float)):
                free, total = payload.get('vram_free_gb'), payload.get('vram_total_gb')
                # Measured by the worker; a slow rate with nearly full VRAM is
                # the "other programs hold the GPU" case, shown as such.
                pressured = isinstance(free, (int, float)) and free < 1.0
                metrics.append((tr('生成速度'), tr('{rate:.1f} tokens/秒 · 显存将满', rate=float(rate)) if pressured
                                else tr('{rate:.1f} tokens/秒', rate=float(rate))))
                if isinstance(free, (int, float)) and isinstance(total, (int, float)):
                    metrics.append((tr('显存可用'), f"{float(free):.1f} / {float(total):.1f} GB"))
                if isinstance(payload.get('context_tokens'), int):
                    metrics.append((tr('上下文'), f"{int(payload['context_tokens']):,} tokens"))
        elif kind == 'asr_evidence_delta':
            metrics.append((tr('已完成批次'), f"{payload.get('completed_chunks', 0)} / {payload.get('total_chunks', 0)}"))
            metrics.append((tr('已处理音频'), clock(payload.get('processed_end', 0))))
        elif kind == 'asr_progress':
            from .progress_model import cloud_job_phase, cloud_wait, upload_progress
            phase = cloud_job_phase(payload)
            if phase is not None:
                # Async cloud recognition: upload, queue and processing states (2026-10-15).
                metrics.append((tr('云端阶段'), tr(phase[0], **phase[1])))
                sent = upload_progress(payload)
                if sent is not None:
                    metrics.append((tr('已上传'), tr(sent[0], **sent[1])))
            # While the provider has the request: which one and how long it has
            # waited (2026-10-23: "1 / 2 · 0 秒前" for 24 minutes read as frozen).
            wait = cloud_wait(payload, since(live['at']) if live.get('at') else 0.0)
            batches = int(payload.get('total_batches') or 0)
            if phase is None or batches > 1:
                metrics.append((tr('已返回批次'), f"{payload.get('completed_batches', 0)} / {payload.get('total_batches', 0)}"))
            # Several MOSI requests can be in the cloud at once (2026-10-23);
            # the wait shown is the longest one's.
            active = [int(index) for index in payload.get('active_requests') or ()]
            if batches > 1 and (active or wait is not None):
                current = ', '.join(map(str, active)) or str(int(payload.get('completed_batches') or 0) + 1)
                metrics.append((tr('当前分段'), f"{current} / {batches}"))
            if wait is not None:
                metrics.append((tr('本段已等') if batches > 1 and len(active) <= 1 else tr('云端已等'), clock(wait[0])))
            if phase is None or 'cue_count' in payload:
                metrics.append((tr('临时转写'), tr('{count} 条', count=payload.get('cue_count', 0))))
            if live.get('at'):
                quiet = since(live['at'])
                metrics.append((tr('最近回应'), tr('{seconds} 秒前', seconds=int(quiet))))
        elif kind == 'cloud':
            from .progress_model import cloud_batch_list
            if payload.get('total'):
                metrics.append((tr('已完成批次'), f"{payload.get('done', 0)} / {payload['total']}"))
            inflight = (getattr(self, '_cloud_inflight', {}) or {}).get(focus_id) or ()
            if inflight:
                metrics.append((tr('正在处理'), tr('第 {batches} 批', batches=cloud_batch_list(inflight))))
            if live.get('at'):
                quiet = since(live['at'])
                metrics.append((tr('最近活动'), tr('{seconds} 秒前', seconds=int(quiet))))
        elif kind == 'translation':
            metrics.append((tr('已翻译'), tr('{done} / {total} 条', done=payload.get('done', 0), total=payload.get('total', 0))))
        api_step = kind in {'cloud', 'asr_progress', 'translation'} or focus_id in (getattr(self, '_usage_steps', {}) or {})
        self.stage_metrics.set_metrics(metrics + self._api_step_metrics(focus_id), limit=6 if api_step else 4)
        self._render_usage_line(focus_id, waiting=kind == 'cloud')
        mode = resource_mode(item.get('resource'))
        self._set_stage_device(tr(mode[1]) if mode else '', tr(item.get('resource') or ''))
        others = [stage for stage in sorted(self._active_stages) if stage != focus_id]
        if others:
            parts = []
            for stage in others:
                other = self._active_stages[stage]
                name = tr(stage_record_name(other.get('label')))
                begun = other.get('started')
                parts.append(tr('{name}（{elapsed}）', name=name, elapsed=clock(now_perf - begun)) if begun else name)
            bind_text(self.progress_resource, '同时进行：{steps}', steps=join_text(parts, separator='、'))
        else:
            # What the step is doing, in one sentence (M14: no "previous step").
            description = (moss_description(payload.get('phase'), int(payload.get('window_count') or 0) > 1)
                           if moss else stage_description(item.get('label')))
            bind_text(self.progress_resource, description or '')
        self.progress_resource.setVisible(bool(self.progress_resource.text()))
        self.active_tasks_label.hide()
        note, detail = '', ''
        if quiet is not None and quiet >= 60:
            if moss and getattr(self, '_worker_running', {}).get('moss'):
                note = tr('已有 {seconds} 秒未收到新输出。子进程仍在运行。', seconds=int(quiet))
                detail = tr('整段识别较长的音频时，可能较长时间没有新输出。可以继续等待，也可以安全取消：会在当前步骤可以安全停止时退出。')
            elif moss:
                note = tr('已有 {seconds} 秒未收到新输出。', seconds=int(quiet))
                detail = tr('可以继续等待，也可以安全取消：会在当前步骤可以安全停止时退出。')
            else:
                note = tr('已有 {seconds} 秒未收到新数据，请求还没有结束。', seconds=int(quiet))
                detail = tr('云端模型生成较长内容时，可能较长时间没有返回。可以继续等待，也可以安全取消。')
        elif wait is not None and wait[1]:
            note = tr('这一段在云端已等 {minutes} 分钟，比平常久很多。', minutes=int(wait[0] // 60))
            detail = tr('约 {audio} 分钟的音频平常几分钟内就会识别完，服务商那边可能在排队或卡住了。'
                        '可以继续等待，也可以安全取消：任务编号已保存，下次开始会接着查询原来的任务，不会重新上传或重复计费。',
                        audio=max(1, round(float(payload.get('request_audio_seconds') or 0) / 60)))
        self._set_stage_note(note, detail)

    def _api_step_metrics(self, step):
        """Retries of an online API step (2026-10-15); every retry is also in the record."""
        retries = int((getattr(self, '_cloud_retries', {}) or {}).get(step) or 0)
        return [(tr('重试'), tr('{count} 次', count=retries))] if retries else []

    def _render_usage_line(self, step=None, *, waiting=False, total_label='任务累计：{usage}'):
        """Provider-reported usage of the step and of the whole task, under the
        step card (2026-10-15). Hidden until an online API was called."""
        from ..providers.api_usage import usage_text
        label = getattr(self, 'stage_usage_label', None)
        if label is None:
            return
        lines = []
        usage = (getattr(self, '_usage_steps', {}) or {}).get(step) if step is not None else None
        calls = usage.calls if usage is not None else 0
        if calls:
            lines.append(tr('本步用量：{usage}', usage=usage_text(usage)))
        elif waiting:
            lines.append(tr('本步用量：{usage}', usage=tr('等待服务商返回')))
        total = getattr(self, '_usage_total', None)
        if total is not None and total.calls > calls:
            lines.append(tr(total_label, usage=usage_text(total)))
        bind_text(label, join_text(lines, separator='\n') if lines else '')
        label.setVisible(bool(lines))

    def _render_cancelling_step(self, focus_id, total):
        from .progress_model import clock, stage_record_name
        waited = max(0.0, time.perf_counter() - self._cancel_requested_at)
        self.running_indicator.set_status('取消中', 'warning')
        self._set_stage_device('')
        if focus_id is not None:
            bind_text(self.stage_step_label, '第 {step} / {total} 步', step=focus_id, total=total)
        else:
            bind_text(self.stage_step_label, '')
        bind_text(self.progress_stage, '正在安全取消…')
        metrics = [(tr('已等待'), clock(waited))]
        if focus_id is not None:
            metrics.append((tr('等待停止'), tr(stage_record_name(self._active_stages[focus_id].get('label')))))
        workers = getattr(self, '_worker_running', {})
        if workers:
            metrics.append((tr('模型子进程'), tr('仍在运行') if any(workers.values()) else tr('已停止')))
        self.stage_metrics.set_metrics(metrics)
        self._render_usage_line()
        bind_text(self.progress_resource, '将在当前可安全停止的阶段边界退出')
        self.progress_resource.show()
        self.active_tasks_label.hide()
        self._set_stage_note(tr('取消会在当前步骤可以安全停止时生效。'), tr('之后的步骤不再执行；正在运行的模型子进程会被停止。'))

    def _render_terminal_step(self, terminal, ended, total):
        from .progress_model import clock
        tone, pill = {'success': ('success', '已完成'), 'degraded_success': ('warning', '已完成 · 需复核'),
                      'cancelled': ('warning', '已取消'), 'failed': ('danger', '未完成')}.get(terminal, ('muted', '待确认'))
        self.running_indicator.set_status(pill, tone)
        self._set_stage_device('')
        bind_text(self.stage_step_label, '')
        bind_text(self.progress_stage, {'success': '完成', 'degraded_success': '完成，有需复核项', 'failed': '任务结束，有失败项',
                                        'cancelled': '任务已取消'}.get(terminal, '任务结束'))
        metrics = []
        elapsed = getattr(self, '_terminal_elapsed', 0.0)
        if elapsed:
            metrics.append((tr('总用时'), clock(elapsed)))
        metrics.append((tr('完成步骤'), f'{len(ended)} / {total}'))
        self.stage_metrics.set_metrics(metrics)
        self._render_usage_line(total_label='API 用量：{usage}')
        bind_text(self.progress_resource, '字幕文件与工程交付状态见结果页')
        self.progress_resource.show()
        bind_text(self.active_tasks_label, '识别子任务已退出')
        self.active_tasks_label.hide()
        self._set_stage_note('')

    def _render_between_steps(self, ended, total):
        from .progress_model import stage_record_name
        self.running_indicator.set_status('等待下一步', 'muted')
        self._set_stage_device('')
        bind_text(self.stage_step_label, '已完成 {done} / {total} 步', done=len(ended), total=total)
        bind_text(self.progress_stage, '正在进入下一步')
        last = getattr(self, '_last_completed_stage', None)
        metrics = []
        if last:
            metrics = [(tr('上一步'), tr(stage_record_name(last[1]))), (tr('用时'), self._duration_text(last[2]))]
        self.stage_metrics.set_metrics(metrics)
        self._render_usage_line()
        bind_text(self.progress_resource, '')
        self.progress_resource.hide()
        self.active_tasks_label.hide()
        self._set_stage_note('')

    def _render_preparing_step(self):
        self.running_indicator.set_status('准备中', 'muted')
        self._set_stage_device('')
        bind_text(self.stage_step_label, '')
        bind_text(self.progress_stage, '正在准备任务')
        self.stage_metrics.set_metrics([])
        self._render_usage_line()
        bind_text(self.progress_resource, '检查运行环境并建立任务队列')
        self.progress_resource.show()
        self.active_tasks_label.hide()
        self._set_stage_note('')

    def _push_preview(self, kind, payload):
        from .progress_model import merge_preview, preview_rows
        family, rows = preview_rows(kind, payload)
        if not family or not rows:
            return
        self._preview_buffer = merge_preview(getattr(self, '_preview_buffer', []), family,
                                             getattr(self, '_preview_family', None), rows)
        self._preview_family = family
        if kind == 'asr_evidence_delta':
            self._preview_batches = (int(payload.get('completed_chunks') or 0), int(payload.get('total_chunks') or 0))

    def _render_preview(self):
        preview = getattr(self, 'recognition_preview', None)
        if preview is None:
            return
        from .progress_model import PREVIEW_TAGS, time_label
        rows = []
        for row in getattr(self, '_preview_buffer', []):
            tag, tone = PREVIEW_TAGS.get(row.get('state'), ('尚未校对', 'muted'))
            when = time_label(row['start']) if row.get('start') is not None else f"#{row.get('cue', '')}"
            rows.append((when, row.get('text', ''), str(tr(tag)), tone))
        preview.set_rows(rows)
        family = getattr(self, '_preview_family', None)
        if family == 'evidence':
            done, count = getattr(self, '_preview_batches', (0, 0))
            bind_text(self.preview_source, 'FireRed 逐字识别 · {done}/{total} 批', done=done, total=count)
        else:
            bind_text(self.preview_source, {'draft': '在线识别 · 临时转写', 'polish': 'AI 校对结果',
                                            'grouped': 'AI 断句结果', 'final': '已保存的字幕'}.get(family, ''))
        if not rows:
            live = getattr(self, '_stage_live', {}).get(2) or {}
            moss_running = 2 in getattr(self, '_active_stages', {}) and (live.get('payload') or {}).get('backend') == 'moss'
            windowed = int((live.get('payload') or {}).get('window_count') or 0) > 1
            text = ('本次没有收到可预览的文字' if getattr(self, '_recognition_terminal', '') else
                    'MOSS 正在分段识别，全部分段结束前不会产生逐句文字；之后逐字识别出的内容会在这里显示最近几句'
                    if moss_running and windowed else
                    'MOSS 正在整段识别，识别结束前不会产生逐句文字；之后逐字识别出的内容会在这里显示最近几句' if moss_running else
                    '模型返回可读文字后，这里会实时显示最近几句')
            preview.set_empty_text(str(tr(text)))

    def _tick_live_rows(self):
        from shiboken6 import isValid
        from .progress_model import clock
        now = time.perf_counter()
        for card in list(getattr(self, '_feed_stage_rows', {}).values()):
            started = getattr(card, '_started_at', 0)
            if started and isValid(card):
                card.set_meta(clock(now - started))
        card = getattr(self, '_cancel_feed_card', None)
        requested = getattr(self, '_cancel_requested_at', 0)
        if card is not None and requested and isValid(card) and not getattr(self, '_recognition_terminal', ''):
            card.set_meta(tr('已等待 {seconds} 秒', seconds=int(now - requested)))

    def _finish_progress_presentation(self):
        """Close every open record row when a run ends (M12): nothing keeps
        saying "running" after the worker is gone."""
        from shiboken6 import isValid
        from .progress_model import clock
        terminal = getattr(self, '_recognition_terminal', '') or 'failed'
        badge = {'cancelled': '已取消', 'success': '已结束', 'degraded_success': '已结束'}.get(terminal, '未完成')
        now = time.perf_counter()
        stopped = set(getattr(self, '_active_stages', {}) or {})
        rows = getattr(self, '_feed_stage_rows', {}) or {}
        for (_media, stage_index, _label), card in list(rows.items()):
            stopped.add(stage_index)
            if card is not None and isValid(card):
                card.set_event(badge)
                started = getattr(card, '_started_at', 0)
                if started:
                    card.set_meta(clock(now - started))
                card._started_at = 0
        rows.clear()
        self._stopped_stages = stopped
        started_at = getattr(self, 'started_at', 0) or 0
        self._terminal_elapsed = max(0.0, now - started_at) if started_at else 0.0
        button = getattr(self, 'cancel_run_button', None)
        if isinstance(button, QWidget):
            bind_text(button, '安全取消')
        card = getattr(self, '_cancel_feed_card', None)
        requested = getattr(self, '_cancel_requested_at', 0)
        if card is not None and isValid(card):
            if terminal == 'cancelled':
                card.set_event('已取消', '已安全取消，之后的步骤没有执行')
            else:
                card.set_event('已结束', '取消请求送达前任务已经结束')
            if requested:
                card.set_meta(tr('等待 {seconds} 秒', seconds=int(max(0, now - requested))))
        self._cancel_feed_card = None


    def _update_progress_clock(self):
        if not self.started_at:
            return
        elapsed = max(0, int(time.perf_counter() - self.started_at))
        minutes, seconds = divmod(elapsed, 60)
        self.stage_elapsed.setText(f"{minutes:02d}:{seconds:02d}")
        work = getattr(self, '_recognition_live_work', {})
        if work and hasattr(self,'recognition_live_status'):
            now=time.monotonic()
            rows=[]
            for row in work.values():
                message=recognition_event_text(row['kind'],row['payload'])
                rows.append(tr('{message} · 距最近有效结果 {seconds} 秒',message=message,seconds=int(max(0,now-row['at'])))
                    if row['at'] else tr('{message} · 尚无转写结果',message=message))
            bind_text(self.recognition_live_status, join_text(rows, separator='\n'))
        # M12: running record rows and the step's live facts tick once a
        # second; events refresh them immediately in between.
        if elapsed != getattr(self, '_last_clock_second', -1):
            self._last_clock_second = elapsed
            if hasattr(self, 'stage_metrics'):
                self._tick_live_rows()
                if not getattr(self, '_recognition_terminal', ''):
                    self._refresh_progress_cards()

    def _live_stage_for(self, kind, backend):
        """Which running step a live event belongs to: primary transcription
        is step 2 (it runs beside the voice check); everything else belongs
        to the latest started step."""
        active = getattr(self, '_active_stages', {}) or {}
        if not active:
            return None
        if (backend == 'moss' or kind in {'asr_progress', 'asr_wait'}) and 2 in active:
            return 2
        return max(active)

    @staticmethod
    def _live_fraction(kind, payload):
        """Real in-step fraction from real counters, or None."""
        pairs = {'asr_evidence_delta': ('completed_chunks', 'total_chunks'),
                 'asr_progress': ('completed_batches', 'total_batches')}
        if kind in pairs:
            done, total = (float(payload.get(key) or 0) for key in pairs[kind])
            return done / total if total > 0 else None
        percent = payload.get('progress_percent') if payload.get('backend') == 'moss' else None
        return float(percent) / 100 if isinstance(percent, (int, float)) else None

    @staticmethod
    def _is_fresh_output(kind, payload, prior):
        """True only when the event carries new real output."""
        if kind == 'asr_worker_progress' and payload.get('backend') == 'moss':
            return (int(payload.get('generated_tokens') or 0) > int(prior.get('generated_tokens') or 0)
                    or payload.get('phase') != prior.get('phase'))
        if kind == 'asr_evidence_delta':
            return int(payload.get('completed_chunks') or 0) > int(prior.get('completed_chunks') or 0)
        if kind == 'asr_progress':
            # Async cloud jobs: a new upload byte count or task state is real
            # progress too (2026-10-15).
            return (int(payload.get('completed_batches') or 0) > int(prior.get('completed_batches') or 0)
                    or int(payload.get('cue_count') or 0) > int(prior.get('cue_count') or 0)
                    or int(payload.get('uploaded_bytes') or 0) > int(prior.get('uploaded_bytes') or 0)
                    or payload.get('state') != prior.get('state'))
        return False

    def _handle_event(self, event):
        active_job = getattr(self, '_active_job_id', '')
        if active_job and str(getattr(event, 'job_id', '') or '') != active_job:
            return
        degraded = self.__dict__.setdefault('_phase_degraded', {})
        if event.kind in {'asr_evidence_delta', 'cue_delta', 'terminology_polish_final',
                          'cloud_batch_preview'} and hasattr(self, 'recognition_preview'):
            self._push_preview(event.kind, event.payload)
        if event.kind == 'polishing_summary':
            fallback = int(event.payload.get('fallback_cues') or 0)
            total = fallback + int(event.payload.get('success_cues') or 0)
            if fallback or int(event.payload.get('fallback_batches') or 0):
                degraded[1] = tr('{fallback}/{total} 条回退原文', fallback=fallback, total=total)
        elif event.kind == 'grouping_api_fallback':
            degraded[2] = tr('部分断句改用本地规则')
        elif event.kind == 'text_ai_terminal_failure':
            stage = str(event.payload.get('stage') or '')
            if stage.startswith('polish'):
                degraded[1] = tr('AI 校对未完成，保留原文')
            elif stage.startswith('group'):
                degraded[2] = tr('AI 断句未完成，使用本地规则')
        if event.kind=='asr_provider_snapshot' and event.payload.get('stage')=='group':
            payload=event.payload
            speaker=payload.get('speaker_source','single')
            label=tr('实际断句模型：{provider} / {model} · 说话人区分：{state}', provider=payload.get('provider',''), model=payload.get('model',''), state=tr('已关闭') if speaker=='single' else tr('已开启：{speaker}', speaker=speaker))
            self._append_feed('任务配置',label,BLUE)
        elif event.kind=='speaker_progress':
            payload=event.payload
            state=payload.get('state')
            label=recognition_event_text(event.kind,payload)
            if not hasattr(self,'_recognition_live_work'):self._recognition_live_work={}
            self._recognition_live_work['speaker']={'kind':event.kind,'payload':dict(payload),'at':time.monotonic()}
            self._append_feed('说话人区分',label,BLUE)
            if getattr(self,'_studio_recognition_context',None):self.studio_page.set_recognition_runtime_stage(label,'')
            self._update_progress_clock()
        elif event.kind in {'asr_progress','asr_evidence_delta','asr_worker_progress','asr_wait'}:
            payload=event.payload; backend=str(payload.get('backend','asr'))
            label=recognition_event_text(event.kind,payload)
            if not hasattr(self,'_recognition_live_work'):self._recognition_live_work={}
            prior=self._recognition_live_work.get(backend,{})
            activity_at = (time.monotonic() - max(0, float(payload.get('elapsed_seconds', 0)) - float(payload.get('last_activity_elapsed_seconds', 0)))
                           if backend == 'moss' else time.monotonic() if event.kind in {'asr_progress','asr_evidence_delta'} else prior.get('at'))
            self._recognition_live_work[backend]={'kind':event.kind,'payload':dict(payload),'at':activity_at}
            # M12: the bar stays determinate; live facts belong to their step.
            stage = self._live_stage_for(event.kind, backend)
            stage_live = self.__dict__.setdefault('_stage_live', {})
            previous = stage_live.get(stage, {}) if stage is not None else {}
            # Same clock as the task and step timers (perf_counter).
            if backend == 'moss':
                stage_at = time.perf_counter() - max(0.0, float(payload.get('elapsed_seconds', 0) or 0)
                                                     - float(payload.get('last_activity_elapsed_seconds', 0) or 0))
            elif event.kind in {'asr_progress', 'asr_evidence_delta'}:
                stage_at = time.perf_counter()
            else:
                stage_at = previous.get('at')
            richer = previous.get('kind') in {'asr_evidence_delta', 'asr_progress'} and event.kind == 'asr_worker_progress' and backend != 'moss'
            if stage is not None and not richer:
                fresh = self._is_fresh_output(event.kind, payload, previous.get('payload') or {})
                kept = dict(payload)
                if backend == 'moss':
                    # Token milestones carry no measurements; keep the last
                    # measured rate and VRAM until the next heartbeat.
                    for name in ('tokens_per_second', 'vram_free_gb', 'vram_total_gb', 'reserved_gb', 'context_tokens'):
                        if name not in kept and name in (previous.get('payload') or {}):
                            kept[name] = previous['payload'][name]
                stage_live[stage] = {'kind': event.kind, 'payload': kept, 'at': stage_at, 'backend': backend}
                fraction = self._live_fraction(event.kind, payload)
                if fraction is not None:
                    self.__dict__.setdefault('_stage_partial', {})[stage] = fraction
                if fresh and isinstance(self.progress_bar, StageProgressBar):
                    self.progress_bar.note_activity()
            if backend == 'moss' and getattr(self, '_studio_recognition_context', None):
                self.studio_page.set_recognition_runtime_stage(label, '')
            self._update_progress_clock()
        elif event.kind in {'studio_project_saving', 'studio_project_saved'}:
            label = '正在保存工程' if event.kind=='studio_project_saving' else '工程已保存，准备载入 Studio'
            self._append_feed('交付', label, BLUE)
            if getattr(self, '_studio_recognition_context', None):
                self.studio_page.set_recognition_runtime_stage(label, str(event.payload.get('project_path','')))
        elif event.kind == "audio_lane_started":
            payload = event.payload
            label = tr('音轨 {index}/{total} · {label}', index=payload.get('lane_index', 1),
                       total=payload.get('lane_total', 1), label=payload.get('label', ''))
            self._append_feed('音轨', label, BLUE)
            if getattr(self, '_studio_recognition_context', None):
                self.studio_page.set_recognition_lane_note(label)
        elif event.kind in {"audio_lane_failed", "audio_lane_finished"}:
            payload = event.payload
            if event.kind == "audio_lane_failed" or payload.get('status') not in {'success', 'degraded_success'}:
                self._append_feed('音轨', tr('{lane} 未完成：{reason}', lane=payload.get('label') or payload.get('audio_lane', ''),
                                            reason=payload.get('error') or payload.get('status', '')), BLUE)
        elif event.kind == "cue_delta":
            context = getattr(self, "_studio_recognition_context", None)
            # Picked tracks are combined at the end; one track's live rows
            # must not stand in for the captions of the others meanwhile.
            if context and not context.get("audio_lanes") and not context.get("recognition_range_ms"):
                self.studio_page.apply_recognition_cue_delta(event.payload)
            cue_count = len(event.payload.get("cues", ()) or ())
            label = "最终字幕" if event.payload.get("state") == "final" else "临时转写（待校对）"
            self._append_feed(label, tr('已接收 {count} 条', count=cue_count), BLUE)
        elif event.kind == "stage_started":
            if max(1, event.media_index) != self._current_media_index and self._completed_stages:
                # A new media file restarts the step count; the previous
                # file's steps stay in the record above.
                self._completed_stages.clear()
                self._skipped_stages = set()
                self._failed_stages.clear()
                self._stage_live = {}
                self._stage_partial = {}
                self._cloud_batches = {}
                self._usage_steps, self._cloud_inflight, self._cloud_retries = {}, {}, {}
                self._preview_buffer, self._preview_family = [], None
            self._stage_total = max(1, event.stage_total)
            self._current_media_index = max(1, event.media_index)
            self._current_media_total = max(1, event.media_total)
            if event.media_path:
                self._current_media_name = Path(event.media_path).name
            if isinstance(self.progress_bar, StageProgressBar):
                self.progress_bar.note_activity()
            self._active_stages[event.stage_index] = {
                "label": event.label,
                "resource": event.resource,
                "started": time.perf_counter(),
            }
            self._feed_stage(event)
            if getattr(self, "_studio_recognition_context", None):
                label = str(event.label or "")
                if "音频" in label or "VAD" in label or "人声" in label:
                    stage = "分析音频"
                elif any(token in label for token in ("转写", "ASR", "MOSS", "时间轴", "主稿")):
                    stage = "识别中"
                elif "写入" in label:
                    stage = "写回工程"
                else:
                    stage = "准备模型"
                self.studio_page.set_recognition_runtime_stage(stage, label)
        elif event.kind in {"stage_completed", "stage_skipped"}:
            self._active_stages.pop(event.stage_index, None)
            self._completed_stages.add(event.stage_index)
            getattr(self, '_stage_partial', {}).pop(event.stage_index, None)
            getattr(self, '_stage_live', {}).pop(event.stage_index, None)
            if event.kind == 'stage_completed':
                self._last_completed_stage = (event.stage_index, event.label, event.elapsed_seconds)
            if event.kind == 'stage_skipped':
                if not hasattr(self, '_skipped_stages'):self._skipped_stages=set()
                self._skipped_stages.add(event.stage_index)
            self._feed_stage(event)
        elif event.kind in {"stage_failed", "media_failed"}:
            if event.stage_index:
                self._active_stages.pop(event.stage_index, None)
                self._failed_stages.add(event.stage_index)
                getattr(self, '_stage_partial', {}).pop(event.stage_index, None)
                getattr(self, '_stage_live', {}).pop(event.stage_index, None)
                self._feed_stage(event)
            else:
                self._append_feed("失败", join_text((tr(event.label) if event.label else Path(event.media_path).name, tr(event.error))), CORAL)
        elif event.kind == "cache_hit":
            stage = event.payload.get("stage", "")
            self._append_feed("缓存", tr('复用 {stage}，跳过重复计算', stage=tr(stage)), BLUE)
        elif event.kind == "cloud_batches_parallel":
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
                self.__dict__.setdefault('_cloud_batches', {})[stage] = {
                    'done': 0, 'total': int(event.payload.get('batches') or 0)}
            self._append_feed(
                "并行",
                tr('{count} 个云端批次，最多 {workers} 路', count=event.payload.get('batches',0), workers=event.payload.get('workers',1)),
                PURPLE,
            )
        elif event.kind == "cloud_batch_started":
            # 2026-10-15: which batches are with the provider right now.
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
                self.__dict__.setdefault('_cloud_inflight', {}).setdefault(stage, set()).add(
                    int(event.payload.get('batch_index') or 0))
                batches = self.__dict__.setdefault('_cloud_batches', {}).setdefault(stage, {'done': 0, 'total': 0})
                batches['total'] = max(int(batches.get('total') or 0), int(event.payload.get('batch_total') or 0))
                live = self.__dict__.setdefault('_stage_live', {}).get(stage) or {}
                if live.get('kind') in (None, 'cloud'):
                    self._stage_live[stage] = {'kind': 'cloud', 'payload': dict(live.get('payload') or {}, **batches),
                                               'at': live.get('at') or time.perf_counter()}
        elif event.kind in {'llm_request_retry', 'asr_request_retry'}:
            payload = event.payload
            stage = (self._live_stage_for('asr_progress', 'api') if event.kind == 'asr_request_retry'
                     else max(self._active_stages) if self._active_stages else None)
            if stage is not None:
                retries = self.__dict__.setdefault('_cloud_retries', {})
                retries[stage] = int(retries.get(stage) or 0) + 1
            if event.kind == 'llm_request_retry':
                self._append_feed('重试', '第 {batch} / {total} 批 · 第 {attempt} 次请求', AMBER, nested=True,
                                  batch=payload.get('batch_index', 0), total=payload.get('batch_total', 0),
                                  attempt=payload.get('attempt', 0))
        elif event.kind == 'asr_retry_sweep':
            self._append_feed('补扫', '第 {sweep} / {count} 轮 · 重试 {chunks} 个失败短块', AMBER, nested=True,
                              sweep=event.payload.get('sweep', 0), count=event.payload.get('max_sweeps', 0),
                              chunks=event.payload.get('chunks', 0))
        elif event.kind == 'api_usage':
            payload = event.payload
            active = getattr(self, '_active_stages', {}) or {}
            stage = (2 if payload.get('stage') == 'asr_primary' and 2 in active
                     else max(active) if active else None)
            from ..providers.api_usage import UsageTotals
            if stage is not None:
                self.__dict__.setdefault('_usage_steps', {}).setdefault(stage, UsageTotals()).add(payload)
            total = self.__dict__.get('_usage_total')
            if total is None:
                total = self._usage_total = UsageTotals()
            total.add(payload)
        elif event.kind == 'subtitle_translation_progress':
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
                done, total = int(event.payload.get('done') or 0), int(event.payload.get('total') or 0)
                self.__dict__.setdefault('_stage_live', {})[stage] = {
                    'kind': 'translation', 'payload': dict(done=done, total=total), 'at': time.perf_counter()}
                if total:
                    self.__dict__.setdefault('_stage_partial', {})[stage] = done / total
                if isinstance(self.progress_bar, StageProgressBar):
                    self.progress_bar.note_activity()
        elif event.kind == "cloud_batch_completed":
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
                self.__dict__.setdefault('_cloud_inflight', {}).get(stage, set()).discard(
                    int(event.payload.get('batch_index') or 0))
                batches = self.__dict__.setdefault('_cloud_batches', {}).setdefault(stage, {'done': 0, 'total': 0})
                batches['done'] = int(batches.get('done') or 0) + 1
                batches['total'] = max(int(batches.get('total') or 0), int(event.payload.get('batch_total') or 0))
                if batches['total']:
                    self.__dict__.setdefault('_stage_partial', {})[stage] = batches['done'] / batches['total']
                live = self.__dict__.setdefault('_stage_live', {}).get(stage) or {}
                self._stage_live[stage] = {'kind': 'cloud', 'payload': dict(live.get('payload') or {}, **batches),
                                           'at': time.perf_counter()}
                if isinstance(self.progress_bar, StageProgressBar):
                    self.progress_bar.note_activity()
            fallback = int(event.payload.get('fallback_cues') or 0)
            if fallback:
                # A returned batch whose cues fell back is not a completed edit.
                self._append_feed('已回退', '{done} / {total} · {fallback} 条回退原文 · {seconds:.1f} 秒', BLUE, nested=True,
                    done=event.payload.get('batch_index', 0), total=event.payload.get('batch_total', 0),
                    fallback=fallback, seconds=event.elapsed_seconds)
            else:
                self._append_feed(
                    "批次",
                    tr('{done} / {total} 完成 · {seconds:.1f} 秒', done=event.payload.get('batch_index',0), total=event.payload.get('batch_total',0), seconds=event.elapsed_seconds),
                    BLUE,
                )
        elif event.kind == "final_text_conservation_recovery":
            self._append_feed(
                "自愈",
                "检测到断句调序，已从校对源段安全重建并重新校验",
                GREEN,
            )
        elif event.kind == 'asr_provider_progress':
            # Each provider event is real network activity for the AI step.
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
                live = self.__dict__.setdefault('_stage_live', {}).get(stage) or {}
                prior = live.get('payload') or {} if live.get('kind') == 'cloud' else {}
                count = int(event.payload.get('event_count') or 0)
                fresh = count != int(prior.get('event_count') or -1)
                batches = getattr(self, '_cloud_batches', {}).get(stage, {})
                self._stage_live[stage] = {'kind': 'cloud', 'payload': dict(prior, **batches, event_count=count),
                                           'at': time.perf_counter() if fresh else live.get('at')}
                if fresh and isinstance(self.progress_bar, StageProgressBar):
                    self.progress_bar.note_activity()
        elif event.kind == 'asr_worker_started':
            name = str(event.payload.get('backend') or event.payload.get('model_id') or '')
            self.__dict__.setdefault('_worker_running', {})[name] = True
        elif event.kind == 'asr_worker_exited':
            name = str(event.payload.get('backend') or event.payload.get('model_id') or '')
            self.__dict__.setdefault('_worker_running', {})[name] = False
            if getattr(self, '_cancel_requested_at', 0):
                display = {'moss': 'MOSS', 'firered': 'FireRed', 'qwen3-asr': 'Qwen3-ASR'}.get(name, name)
                self._append_feed('已停止', '{model} 子进程已停止', MUTED, model=display)
        elif event.kind in {'media_cancelled', 'queue_cancelled'}:
            if event.kind == 'media_cancelled' and event.media_path:
                self._append_feed('已取消', '{name} 已停止处理', AMBER, name=Path(event.media_path).name)
            elif event.kind == 'queue_cancelled':
                self._append_feed('已取消', '队列已停止，正在整理任务报告', AMBER)
        elif event.kind == "media_completed":
            self._append_feed("素材", tr('已完成 {name}', name=Path(event.media_path).name), GREEN)
            if getattr(self, "_studio_recognition_context", None):
                self.studio_page.finish_recognition_runtime(event.elapsed_seconds)
        self._refresh_progress_cards()

    def _cancel_run(self):
        if not self.token:
            return
        job_id = getattr(self, '_active_job_id', '')
        self._cancelled_job_ids = getattr(self, '_cancelled_job_ids', set()) | {job_id}
        self.token.cancel()
        self.cancel_run_button.setEnabled(False)
        # 2026-10-08 (M12): the request stays visible until the run really
        # ends — live waiting time, the step being stopped, worker exits.
        self._cancel_requested_at = time.perf_counter()
        if isinstance(self.cancel_run_button, QWidget):
            bind_text(self.cancel_run_button, '正在取消…')
        bind_text(self.progress_stage, '正在安全取消…')
        bind_text(self.progress_resource, '将在当前可安全停止的阶段边界退出')
        self._cancel_feed_card = self._append_feed("取消", "已发出安全取消请求，正在等待当前阶段收尾", AMBER,
                                                   meta=tr('已等待 {seconds} 秒', seconds=0))
        if hasattr(self, 'phase_cards'):
            self._refresh_progress_cards()
        # 四十三轮：Studio 后台识别的取消此前只写主页进度页控件——留在
        # Studio 的用户完全看不到反馈（"点了取消没反应"）。同步落到
        # 字幕列表芯片与"暂无字幕"状态卡，并禁用取消按钮防重复点击。
        if getattr(self, "_studio_recognition_context", None):
            studio_page = self.built_page("studio")
            if studio_page is not None:
                studio_page.set_recognition_cancelling()

    def _back_to_studio_from_progress(self):
        """从主页详细进度页回到 Studio 工程（识别继续后台运行）。"""
        studio_page = self.built_page("studio")
        if studio_page is None:
            return
        self._switch_page(studio_page)

    def _show_studio_recognition_detail(self):
        """Studio 后台识别 → 主页识别进度页看详细阶段/日志（可返回）。"""
        self._switch_page(1)

    def _show_task_notification(self, title, message, icon, details=""):
        """Raise a modal completion alert even when the workbench is minimized."""
        previous = self._completion_dialog
        if previous is not None:
            previous.close()
        QApplication.beep()
        QApplication.alert(self, 0)
        from .window_constraints import restore_minimized_window
        restore_minimized_window(self)
        self.raise_()
        self.activateWindow()

        dialog = CompletionDialog(title, message, icon, details, self)
        self._completion_dialog = dialog

        def clear_dialog(_result):
            if self._completion_dialog is dialog:
                self._completion_dialog = None

        dialog.finished.connect(clear_dialog)
        dialog.open()

    def _recover_recognition_output(self):
        report_path = getattr(self, '_last_recognition_report', '')
        if not report_path or not Path(report_path).is_file():
            report_path, _ = QFileDialog.getOpenFileName(self, tr('选择已有字幕任务报告'), '', '任务报告 (*.json)')
        if not report_path:
            return
        try:
            from ..recognition.recognition_recovery import recover_report
            from ..recognition.recognition_outcome import RecognitionDeliveryWitness, normalize_recognition_outcome
            from ..projects.studio_project import load_project
            from ..timeline.studio_edit_sequence import projected_cues
            import hashlib
            path = recover_report(report_path)
            project = load_project(path)
            raw = Path(report_path).read_bytes()
            payload = json.loads(raw.decode('utf-8-sig'))
            witness = RecognitionDeliveryWitness(report_path=str(report_path),
                report_sha256=hashlib.sha256(raw).hexdigest(), report_started_at=str(payload.get('started_at') or ''),
                project_path=str(path), project_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                cue_count=len(projected_cues(project)), verified_saved_project=True)
            tasks = getattr(self, '_completion_tasks', [])
            index = self.result_task_selector.currentIndex()
            if 0 <= index < len(tasks) and str(tasks[index][0].report_json_path) == str(report_path):
                item = replace(tasks[index][0], project_path=str(path))
                tasks[index] = (item, project)
                evidence = self._completion_task_evidence[self._completion_task_key(item)]
                evidence.update(outcome=normalize_recognition_outcome(payload, delivery_witness=witness),
                    delivery_witness=witness, display_payload=payload, project_error='')
                evidence['output_paths'] = list(dict.fromkeys([str(path), *evidence.get('output_paths', ())]))
                evidence['path_lines'] = [tr('恢复工程') + '：' + str(path), *evidence.get('path_lines', ())]
                evidence['path_entries'] = [('恢复工程', str(path)), *evidence.get('path_entries', ())]
                self._select_completion_task(index)
            self._last_studio_project = str(path)
            self.open_studio_project(path, mode='edit', source='recognition_recovery')
        except Exception as exc:
            QMessageBox.warning(self, tr('恢复未完成'), tr('{value0}\n原工程及字幕输出保持不变。', value0=str(exc)))

    def _handle_result(self, result):
        from ..recognition.recognition_outcome import normalize_recognition_outcome, normalize_recognition_queue
        from ..projects.studio_project import load_project
        from ..timeline.studio_edit_sequence import projected_cues
        job_id = str(getattr(result, 'job_id', '') or '')
        active = getattr(self, '_active_job_id', '')
        if active and job_id != active:
            return
        committed = getattr(self, '_committed_job_ids', set())
        if job_id and job_id in committed:
            return
        if job_id in getattr(self, '_cancelled_job_ids', set()) and result.successes:
            self._committed_job_ids = committed | {job_id}
            self._handle_unexpected_error('任务已取消，迟到的识别结果未自动载入；可从识别记录检查已保存输出。')
            return
        if job_id:
            self._committed_job_ids = committed | {job_id}
        self._release_run_state()
        self._progress_timer.stop()
        self.result_exit_code = result.exit_code
        if getattr(result, "successes", None) and not getattr(self, "_tutorial_demo_result", False):
            try:
                from .onboarding import mark_first_task_done
                mark_first_task_done()  # the welcome guide has done its job
            except Exception:
                pass
        self._active_stages.clear()
        if hasattr(self, '_progress_motion'):
            self._progress_motion.stop()
        self._refresh_progress_cards()
        self.workflow.set_active(3, finished=True)
        self._completion_tasks = []
        self._completion_task_evidence = {}
        self._completion_output_paths = []
        self._last_studio_project = ''
        self._last_recognition_report = ''
        self._last_srt_dir = ''
        self._last_failed_items = []
        self._last_queue_results = list(result.results)
        outcomes = []
        self.result_task_selector.blockSignals(True)
        self.result_task_selector.clear()
        for item in result.results:
            report = {}
            if item.report_json_path:
                try:
                    report = json.loads(Path(item.report_json_path).read_text(encoding='utf-8-sig'))
                except (OSError, ValueError, TypeError):
                    pass
            report = dict(report) if isinstance(report, dict) else {}
            report.setdefault('status', item.status)
            report_result = dict(report.get('result') or {})
            project = None
            project_error = ''
            if item.project_path:
                try:
                    if job_id:
                        from ..recognition.recognition_result import verify_result_reference
                        if str(getattr(item, 'job_id', '')) != job_id:
                            raise ValueError('素材结果不属于当前识别任务。')
                        project = verify_result_reference(getattr(item, 'result_ref_json', ''), project_path=item.project_path)
                    else:
                        project = load_project(item.project_path)
                except (OSError, ValueError, TypeError) as exc:
                    project_error = str(exc)
            elif item.status in {'success', 'degraded_success'}:
                project_error = tr('本次任务没有保存可用的工程文件')
            if project:
                report_result.setdefault('cue_count', len(projected_cues(project)))
            report_result.setdefault('elapsed_seconds', item.elapsed_seconds)
            report['result'] = report_result
            outcome = normalize_recognition_outcome(report)
            outcomes.append(outcome)
            details = list(outcome.localized_detail_lines(getattr(self, '_ui_language', 'zh')))
            details.extend(outcome.problems + outcome.review_notes)
            details.append(translate('当前文件耗时 {elapsed} 秒', getattr(self, '_ui_language', 'zh')).format(elapsed=f'{item.elapsed_seconds or outcome.elapsed_seconds:.3f}'))
            output_paths = []
            for label, target in (('工程', item.project_path), ('字幕', item.srt_path),
                                  ('JSON 报告', item.report_json_path), ('报告', item.report_text_path)):
                if target:
                    output_paths.append(target)
                    details.append(f'{label}：{target}')
            if item.error:
                details.append(str(item.error))
            content = '<b>' + html.escape(outcome.status_label) + '</b><br>' + '<br>'.join(html.escape(line) for line in details)
            self._completion_task_evidence[self._completion_task_key(item)] = dict(outcome=outcome,
                project_error=project_error, review_count=outcome.review_issue_count, output_paths=output_paths, details_html=content, display_payload=report, path_entries=[(label, target) for label, target in (('工程', item.project_path), ('字幕', item.srt_path), ('JSON 报告', item.report_json_path), ('报告', item.report_text_path)) if target], path_lines=[f'{label}：{target}' for label, target in (('工程', item.project_path), ('字幕', item.srt_path), ('JSON 报告', item.report_json_path), ('报告', item.report_text_path)) if target])
            self._completion_tasks.append((item, project))
            task_name = Path(item.media_path).name
            if int(getattr(item, 'audio_stream', -1)) >= 0:
                task_name = str(join_text((task_name, tr('音轨 {number}', number=int(item.audio_stream) + 1)), ' · '))
            self.result_task_selector.addItem(task_name)
            self.result_task_selector.setItemData(self.result_task_selector.count()-1, task_name, Qt.ItemDataRole.ToolTipRole)
            if outcome.polish_retryable or outcome.search_retryable or outcome.core_status == 'failed':
                self._last_failed_items.append(item)
        self.result_task_selector.blockSignals(False)
        queue_outcome = normalize_recognition_queue(outcomes)
        success_count = queue_outcome.completed_count + queue_outcome.partial_count
        failure_count = queue_outcome.failed_count
        cancel_count = queue_outcome.cancelled_count
        review_total = queue_outcome.review_issue_count
        self._recognition_terminal = ('failed' if queue_outcome.core_status == 'failed' else
            'cancelled' if queue_outcome.core_status == 'cancelled' else
            'unknown' if queue_outcome.core_status == 'unknown' else
            'degraded_success' if queue_outcome.core_status == 'partial' or queue_outcome.review_task_count else 'success')
        # 100% means saved: every delivered media has a verified project.
        self._delivery_verified = bool(self._completion_tasks) and all(
            project is not None for item, project in self._completion_tasks
            if item.status in {'success', 'degraded_success'})
        if hasattr(self, 'phase_cards'):
            self._finish_progress_presentation()
            self._refresh_progress_cards()
        self._completion_batch_counts = dict(success=queue_outcome.completed_count, partial=queue_outcome.partial_count,
            failure=queue_outcome.failed_count, cancel=queue_outcome.cancelled_count, skipped=queue_outcome.skipped_count,
            unknown=queue_outcome.unknown_count, elapsed=f'{result.elapsed_seconds:.1f}')
        self.result_files_toggle.setChecked(False)
        self._select_completion_task(0)
        if not outcomes:
            bind_text(self.result_title, '任务状态待确认')
            bind_text(self.result_summary, '')
            self.result_exception_summary.hide()
            self.result_review_summary.clear()
        studio_context = getattr(self, '_studio_recognition_context', None)
        self._prepare_completion_log()
        apply_ui_language(self, getattr(self, '_ui_language', 'zh'))
        history = self.built_page("history")
        if history is not None:
            history.refresh()
        if not studio_context:
            self._switch_page(2)
        if hasattr(self, "open_studio_result_button"):
            self.open_studio_result_button.setVisible(True)
        if hasattr(self, "open_priority_review_button"):
            if not hasattr(self, 'result_task_selector'):
                self.open_priority_review_button.setVisible(bool(self._last_studio_project and review_total))
        if not studio_context and not getattr(self, "_tutorial_demo_result", False):
            self._show_task_notification(*self._completion_notification_with_cause(result, outcomes))
        elif studio_context and (failure_count or cancel_count):
            self.studio_page.fail_recognition_runtime(
                "任务已取消" if cancel_count and not failure_count else "识别失败，请检查模型与运行日志"
            )
            # 四十二轮：识别转后台后用户可能已离开 Studio 页——失败/取消也要
            # 任务通知，否则只剩藏在字幕列表里的芯片，用户无感知。
            self._show_task_notification(*self._completion_notification_with_cause(result, outcomes))
        if studio_context and result.successes:
            delivered = next((item for item, loaded in self._completion_tasks if loaded is not None
                and os.path.normcase(os.path.abspath(item.media_path)) == os.path.normcase(os.path.abspath(studio_context.get('media_path','')))), None)
            target = str(delivered.project_path) if delivered else ''
            if target and any(
                os.path.normcase(os.path.abspath(item.media_path))
                == os.path.normcase(os.path.abspath(studio_context.get("media_path", "")))
                for item in result.successes
            ):
                reference = getattr(delivered, 'result_ref_json', '')
                QTimer.singleShot(0, lambda path=target, ref=reference, owner=job_id:
                    self._dispatch_recognition_job(owner, self._finish_studio_recognition, path, ref, allow_committed=True)
                    if owner else self._finish_studio_recognition(path, ref))
            elif not target:
                self.studio_page.fail_recognition_runtime('字幕输出已保存，工程交付未完成；请在结果页点击“恢复已有识别结果”')
                self._switch_page(2)

    def _handle_unexpected_error(self, message: str):
        active_job = getattr(self, '_active_job_id', '')
        if active_job:
            self._committed_job_ids = getattr(self, '_committed_job_ids', set()) | {active_job}
        self._release_run_state()
        self._progress_timer.stop()
        if hasattr(self, 'phase_cards'):
            if not getattr(self, '_recognition_terminal', ''):
                self._recognition_terminal = 'failed'
            self._finish_progress_presentation()
            self._refresh_progress_cards()
        self.result_icon.setPixmap(_icon("fa5s.exclamation-circle", CORAL).pixmap(QSize(72, 72)))
        bind_text(self.result_title, '任务未能启动')
        self.result_title.setProperty("i18nText","任务未能启动")
        self.result_summary.setProperty("i18nTemplate",None)
        self.result_summary.setText(message)
        if hasattr(self, 'result_stats'):
            self.result_stats.hide()
            self.result_summary_meta.hide()
            self.result_summary.show()
        error_theme = _active_theme_definition()
        self.result_files.setHtml(
            f'<div style="background:{error_theme.danger_soft}; border-left:4px solid {error_theme.danger}; '
            f'padding:10px; border-radius:7px;"><b>启动失败</b><br>{html.escape(message)}</div>'
        )
        self._prepare_completion_log()
        if hasattr(self, 'result_task_selector'):
            self._completion_tasks = []
            self.result_task_selector.clear()
            self._select_completion_task(-1)
            self.repolish_current_glossary_button.setEnabled(False)
            self.open_priority_review_button.show()
            self.open_priority_review_button.setEnabled(False)
            self.retry_failed_button.hide()
            self.result_exception_summary.setText(message)
            self.result_exception_summary.show()
            self.result_review_summary.setProperty('i18nTemplate', None)
            self.result_review_summary.setProperty('i18nArguments', {})
            bind_text(self.result_review_summary, '')
            self._completion_output_paths = []
        if getattr(self, "_studio_recognition_context", None):
            self.studio_page.fail_recognition_runtime(message)
            return
        self._switch_page(2)
        if hasattr(self, "result_details_toggle"):
            self.result_details_toggle.setChecked(False)
        apply_ui_language(self, getattr(self, "_ui_language", "zh"))
        self._show_task_notification(
            "字幕任务异常中止",
            "任务未能正常完成，请查看结果页和运行日志。",
            QMessageBox.Icon.Critical,
            message,
        )

    def _finish_studio_close(self, profile=None) -> None:
        if profile is not None:
            self.last_studio_close_profile = dict(profile)
        capability_worker = getattr(self, "_encoder_capability_worker", None)
        if capability_worker is not None and capability_worker.is_alive():
            capability_worker.join(timeout=1.0)
        if hasattr(self, "last_studio_close_profile"):
            self.last_studio_close_profile["encoder_capability_idle"] = bool(
                capability_worker is None or not capability_worker.is_alive()
            )
        self._studio_close_cleanup_done = True
        self._maybe_finalize_close()

    def _worker_close_finished(self) -> None:
        self._worker_close_cleanup_done = True
        self._maybe_finalize_close()

    def _force_close_worker(self) -> None:
        if not getattr(self, "_studio_close_pending", False):
            return
        worker = getattr(self, "worker", None)
        if worker is None or not worker.isRunning():
            self._worker_close_finished()
            return
        if not getattr(self, "_worker_close_terminated", False):
            self._worker_close_terminated = True
            worker.requestInterruption()
            worker.terminate()
            QTimer.singleShot(100, self, self._force_close_worker)
            return
        deadline = float(getattr(self, "_worker_close_hard_deadline", 0.0) or 0.0)
        if deadline and time.monotonic() < deadline:
            QTimer.singleShot(100, self, self._force_close_worker)
            return
        self.last_worker_close_status = "hard_termination_timeout"
        self._worker_close_cleanup_done = True
        self._maybe_finalize_close()

    def _maybe_finalize_close(self) -> None:
        if getattr(self, "_studio_close_finalizing", False):
            return
        if not getattr(self, "_studio_close_cleanup_done", False):
            return
        worker = getattr(self, "worker", None)
        if worker is not None and worker.isRunning() and not getattr(
            self, "_worker_close_cleanup_done", False
        ):
            return
        self._studio_close_finalizing = True
        QTimer.singleShot(0, self, self.close)

    def _retire_studio_loading_for_close(self):
        self._cancel_pending_studio_entries()
        native_visibility = self.__dict__.get('_studio_native_visibility')
        if native_visibility is not None:
            native_visibility.close()
        cover_visibility = self.__dict__.get('_studio_cover_visibility')
        if cover_visibility is not None:
            cover_visibility.close()
        loading = self.__dict__.get('_studio_loading_session')
        if loading is not None and (loading.active or loading.state == 'failed'):
            self._studio_entry_pending = None
            self._studio_entry_start_queued = False
            gate = getattr(self.built_page('studio'), '_readiness', None)
            if gate is not None:
                gate.cancel(navigate=False)
            else:
                loading.abort()

    def _confirm_application_close(self, studio, worker_running):
        gate = getattr(studio, '_readiness', None)
        waiting = gate.confirmation_wait() if gate is not None and gate.active else nullcontext()
        with waiting:
            if not self._prepare_glossary_for_task():
                return False
            if worker_running:
                answer = QMessageBox.question(
                    self, tr('任务仍在运行'), tr('要安全取消当前任务并关闭窗口吗？'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return False
            guard = getattr(getattr(studio, 'project_controller', None), 'dirty_guard', None)
            return guard is None or guard.confirm('退出应用')

    def closeEvent(self, event):
        if self.__dict__.get('_studio_entry_discarding', False):
            self._retire_studio_loading_for_close()
            self._studio_entry_pending = None
            self._close_after_studio_discard = True
            event.ignore()
            return
        partial = self.__dict__.get('_studio_page_building')
        if partial is not None:
            self._retire_studio_loading_for_close()
            event.ignore()
            if not self.__dict__.get('_studio_construction_discarding', False):
                self._studio_construction_discarding = True
                self._studio_entry_pending = None
                def disposed():
                    self._studio_page_building = None
                    self._studio_construction_discarding = False
                    self.close()
                partial.discard_workspace_construction(disposed)
            return
        if getattr(self, "_studio_close_pending", False) and not getattr(
            self, "_studio_close_finalizing", False
        ):
            event.ignore()
            return
        worker_running = bool(self.worker and self.worker.isRunning())
        studio = self.built_page('studio')
        if not getattr(self, '_studio_close_finalizing', False):
            if not self._confirm_application_close(studio, worker_running):
                event.ignore()
                return
            self._retire_studio_loading_for_close()
        if worker_running:
            self.token.cancel()
            self.worker.requestInterruption()
            self._worker_close_cleanup_done = False
            self._worker_close_terminated = False
            self._worker_close_hard_deadline = time.monotonic() + 7.0
            self.worker.finished.connect(self._worker_close_finished)
            QTimer.singleShot(5_000, self, self._force_close_worker)
        else:
            self._worker_close_cleanup_done = True
        if studio is not None and not getattr(self, "_studio_close_finalizing", False):
            encoder_cancel = getattr(self, "_encoder_capability_cancel", None)
            if encoder_cancel is not None:
                encoder_cancel.set()
            begin_close = getattr(studio, "begin_close_page", None)
            if not callable(begin_close):
                studio.close_page()
                if getattr(self, "_gui_profiler", None) is not None:
                    self._gui_profiler.stop()
                event.accept()
                return
            event.ignore()
            self._studio_close_pending = True
            self._studio_close_cleanup_done = False
            # 窗口关闭=应用退出意图：停放次级播放器（frozen ffmpeg 后端的
            # 会话卸载/析构会在 GUI 线程楔进驱动；进程由 os._exit 终止）。
            from ..playback.secondary_video import set_defer_media_destruction

            set_defer_media_destruction(True)
            response_started = time.perf_counter()
            trace_close = getattr(studio, "_studio_trace", None)
            if callable(trace_close):
                trace_close("MAIN_CLOSE_STEP", step="before_window_hide")
            self.hide()
            if callable(trace_close):
                trace_close(
                    "MAIN_CLOSE_STEP",
                    step="after_window_hide",
                    elapsed_ms=round(
                        (time.perf_counter() - response_started) * 1000.0, 3
                    ),
                )
            try:
                begin_close()
            except Exception as exc:
                print(f"[studio] final close failed: {exc}")
                self._finish_studio_close()
            self.last_close_visible_response_ms = round(
                (time.perf_counter() - response_started) * 1000.0, 3
            )
            return
        if getattr(self, "_persist_geometry", False):
            try:
                settings = QSettings("2ByteASR", "2ByteASR")
                geometry = self.normalGeometry() if (self.isMaximized() or self.isFullScreen() or self.isMinimized()) else self.geometry()
                if geometry.width() >= 200 and geometry.height() >= 200:
                    settings.setValue(
                        "mainWindow/geometry",
                        [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    )
                    settings.setValue("mainWindow/maximized", bool(self.isMaximized() or self.isFullScreen()))
                    settings.sync()
            except Exception as exc:
                print(f"[ui] geometry persistence failed: {exc}")
        if self._gui_profiler is not None:
            try:
                target = self._gui_profiler.stop()
                if target is not None:
                    print(f"[perf] GUI profile written: {target}")
            except Exception as exc:
                print(f"[perf] GUI profile write failed: {exc}")
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)


def run_desktop_app(
    legacy,
    pipeline,
    startup_self_test,
    *,
    select_media: bool = True,
    initial_paths=(),
    instance_guard=None,
) -> int:
    _configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    _startup_mark("QAPPLICATION_CREATED")
    from .application_settings import read_studio_preferences
    from ..design.ui_motion import system_reduced_motion

    preferences = read_studio_preferences()
    motion_preference = preferences.get("reduce_motion")
    app.setProperty(
        "reduceMotion",
        system_reduced_motion() if motion_preference is None else bool(motion_preference),
    )
    if os.environ.get("TWOBYTEASR_AUDIT_TOP_LEVELS") == "1":
        from twobyteasr.acceptance.window_audit import TopLevelWindowAudit

        app._top_level_window_audit = TopLevelWindowAudit(
            app,
            Path(os.environ.get("TWOBYTEASR_AUDIT_TOP_LEVEL_PATH", "tmp/top-level-windows.jsonl")),
        )
    app.setApplicationName("2ByteASR")
    from ..diagnostics.editor_diagnostics import install_gui
    install_gui(app)
    from ..playback.playback_gc_budget import install_gui_thread_collector
    install_gui_thread_collector(app)
    app.setApplicationDisplayName("2ByteASR")
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")
    apply_application_theme(app)
    _register_bundled_fonts()
    app.setFont(_app_font())
    instance_guard = instance_guard or _acquire_instance_lock()
    if instance_guard is None:
        _show_error(
            "2ByteASR 已在运行",
            "检测到另一个 2ByteASR 实例正在运行，请先关闭它再启动。",
        )
        return 2
    app._instance_guard = instance_guard
    app.aboutToQuit.connect(instance_guard.release)
    media_paths = []
    from .external_open import startup_destination
    startup_page = startup_destination(initial_paths, preferences,
        explicit_operation=bool(select_media))
    if select_media and not initial_paths:
        media_paths = _select_media_paths()
        if not media_paths:
            instance_guard.release()
            return 0
    _startup_mark("SETTINGS_LOADED")
    # The window's construction scans the model registry several times
    # (ASR choices, summaries, language pass); nothing installs or removes a
    # model meanwhile, so they share one scan's path/record memo.
    from ..runtime_paths import single_scan
    with single_scan():
        window = MainWindow([], legacy, pipeline, startup_self_test, startup_page=startup_page)
    from .desktop_intake import DesktopIntake
    window._desktop_intake = DesktopIntake(window)
    instance_guard.paths_received.connect(window._desktop_intake.receive_external)
    def accept_startup_requests():
        # One queue owns cold arguments and messages received during startup.
        # The first layout has settled before either starts loading a project.
        if media_paths or initial_paths:
            window._desktop_intake.submit(media_paths or initial_paths)
        instance_guard.enable_receiver()
    QTimer.singleShot(0, accept_startup_requests)
    # Ctrl+wheel / Ctrl+= / Ctrl+- / Ctrl+0 interface zoom (remembered).
    from .ui_zoom import install as _install_ui_zoom
    window._ui_zoom = _install_ui_zoom(app, window)
    _startup_mark("MAIN_WINDOW_CREATED")

    class _FirstPaintProbe(QObject):
        def eventFilter(self, watched, event):
            if watched is window and event.type() == QEvent.Type.Paint:
                _startup_mark("FIRST_PAINT")
                QTimer.singleShot(0, lambda: _startup_mark("INTERACTIVE"))
                QTimer.singleShot(0, window._after_startup_interactive)
                if os.environ.get("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE") == "1":
                    QTimer.singleShot(2500, app.quit)
                window.removeEventFilter(self)
            return False

    paint_probe = _FirstPaintProbe(window)
    window._startup_paint_probe = paint_probe
    window.installEventFilter(paint_probe)
    window.show()
    _startup_mark("FIRST_SHOW")
    # 2026-10-14: a fresh install is offered the quick chooser once, after the
    # window shows; upgraded users and double-clicked projects never are.
    if startup_page == "recognition":
        QTimer.singleShot(600, lambda: _offer_first_run_setup(window))
    if os.environ.get("TWOBYTEASR_STARTUP_OPEN_STUDIO") == "1" or os.environ.get("TWOBYTEASR_STARTUP_RAISE") == "1":
        # Instrumented startup route: navigate to the Studio Project Library as
        # if the user clicked the workbench entry, keeping the audit on the
        # real run_desktop_app path for startup regression evidence.
        open_studio = os.environ.get("TWOBYTEASR_STARTUP_OPEN_STUDIO") == "1"
        startup_theme = os.environ.get("TWOBYTEASR_STARTUP_THEME", "")
        startup_size = os.environ.get("TWOBYTEASR_STARTUP_SIZE", "")

        def _open_studio_for_audit():
            if startup_theme:
                apply_theme(startup_theme, app)
            if startup_size:
                try:
                    width, height = (int(part) for part in startup_size.split("x"))
                    window.setGeometry(120, 60, width, height)
                except ValueError:
                    pass
            window.showNormal()
            window.raise_()
            window.activateWindow()
            if os.name == "nt":
                # A background-started process has no foreground rights; the
                # topmost flip reliably lifts the window above shell windows
                # for real-desktop screenshot acceptance.
                import ctypes

                hwnd = int(window.winId())
                user32 = ctypes.windll.user32
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)  # HWND_TOPMOST, NOSIZE|NOMOVE
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)  # HWND_NOTOPMOST
            if open_studio:
                startup_project = os.environ.get("TWOBYTEASR_STARTUP_PROJECT", "")
                if startup_project and Path(startup_project).is_file():
                    window.open_studio_project(startup_project, mode="edit", source="startup_audit")
                else:
                    window.open_studio_project(source="startup_audit")
                if os.environ.get("TWOBYTEASR_STARTUP_LEAVE_STUDIO") == "1":
                    def _leave_studio_for_audit():
                        if hasattr(window, "_return_to_settings"):
                            window._return_to_settings()

                    QTimer.singleShot(9000, _leave_studio_for_audit)

        # Audits can open Studio later, like a user who first looks at Home
        # (the Studio module is preloaded while Home is idle).
        QTimer.singleShot(int(os.environ.get('TWOBYTEASR_STARTUP_OPEN_STUDIO_DELAY_MS', '250') or 250),
                          _open_studio_for_audit)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR'):
        from ..acceptance.studio_acceptance_audit import start_acceptance
        QTimer.singleShot(1500, lambda: start_acceptance(window))
    try:
        app.exec()
        window.launch_pending_update()
        return int(window.result_exit_code)
    finally:
        instance_guard.release()


def _run_first_run_wizard(parent) -> None:
    """Offer model setup only when the saved recognition plan is not healthy."""
    if os.environ.get("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD") == "1":
        return
    settings = getattr(getattr(parent, "legacy", None), "RUNTIME_SETTINGS", {})
    preflight = startup_model_preflight(settings)
    _startup_mark(
        "MODEL_PREFLIGHT",
        installed_count=preflight.installed_count,
        required=list(preflight.required_keys),
        missing=list(preflight.missing_keys),
        corrupt=list(preflight.corrupt_keys),
        prompt=preflight.should_prompt,
    )
    if not preflight.should_prompt:
        return
    _open_guided_setup(parent)


def _offer_first_run_setup(window) -> None:
    """A fresh install starts with the quick chooser, once (2026-10-14).

    Upgraded users (recent projects, reports, saved keys) never see it at
    startup; anyone can reopen it from the home card or 说明.
    2026-10-21: the tutorial follows unless the chooser's 新手教学 box was
    unticked; a cloud choice downloads its timeline model when the tutorial is
    over (the download window would cover it).
    """
    if os.environ.get("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD") == "1":
        return
    from . import onboarding
    state = onboarding.ensure_state()
    if not state.get("fresh") or state.get("setup_offered"):
        return
    onboarding.save_state(dict(state, setup_offered=True))
    if _open_quick_setup(window):
        window._refresh_asr_summary()
    window._refresh_next_step()
    window._after_quick_setup()


def _ai_unlocked(owner) -> bool:
    """Decide from live configuration; a task must not inherit a stale UI gate."""
    settings = getattr(getattr(owner, 'legacy', None), 'RUNTIME_SETTINGS', None)
    if isinstance(settings, dict):
        from ..providers.ai_connection_record import service_gate
        return service_gate(settings) == 'ready'
    return getattr(owner, "__dict__", {}).get("_ai_gate_state", "ready") == "ready"


def _open_quick_setup(parent, *, compare: bool = False):
    """Big cards: cloud / local / light (Mac: cloud / Apple chip / light). ``自己选择模型…`` opens the detailed dialog.

    2026-10-22 ``compare``: the tutorial's plan step. Only cloud and local, each with
    what it is good for and what to watch out for, the saved plan chosen; downloads
    wait for the end of the tutorial. Returns the plan key ('' when nothing changed).
    """
    try:
        from . import onboarding
        from .quick_setup import QuickSetupDialog
        extra = dict(compare=True, current=parent._current_plan_key()) if compare else {}
        dialog = QuickSetupDialog(parent, size_of=lambda backends: GuidedSetupDialog.estimate_size(*backends),
                                  spoken=_home_spoken_language(parent), **extra)
        if onboarding.load_state().get("tour_done"):
            dialog.tour_check.setChecked(False)   # reopened later: no tutorial unless asked for
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if not compare:
            parent._quick_setup_tour = dialog.tour_check.isChecked()
        if not accepted or dialog.choice is None:
            return "" if compare else False
        # 2026-10-24: the language picked above the cards is the home page's 视频里说的话.
        _apply_spoken_language(parent, getattr(dialog, "spoken", ""))
        if not compare:
            parent._quick_setup_chosen = True   # the tutorial that follows does not ask again
        if compare:
            _apply_plan_for_tutorial(parent, dialog)
            return dialog.choice
        if dialog.choice == "custom":
            return _open_guided_setup(parent)
        primary, timeline, review = dialog.backends
        if dialog.choice == "cloud":
            # 2026-10-21: MOSS Pro in the cloud + the timeline model on this computer.
            preset = getattr(dialog, "api_preset", "") or "mosi_moss_pro"
            index = parent.qwen_asr_api_provider.findData(preset)
            if index >= 0:
                parent.qwen_asr_api_provider.setCurrentIndex(index)
            parent._apply_asr_preset_fields(preset)
            keys = GuidedSetupDialog.download_keys_for(primary, timeline, review)
            _apply_setup_choice(parent, primary, timeline, review, keys, open_workshop=False, auto_download=False)
            # The source chosen in the chooser applies to the timeline model too (download after the tutorial).
            parent._first_run_downloads = (primary, tuple(keys), str(dialog.source_combo.currentData() or 'AUTO'))
            if not dialog.tour:
                # No tutorial: the MOSS Pro sign-up guide now, the timeline download after it.
                def guide_then_download():
                    parent._open_api_setup_guide(preset)
                    parent._start_first_run_downloads()
                QTimer.singleShot(0, guide_then_download)
            return True
        keys = GuidedSetupDialog.download_keys_for(primary, timeline, review)
        _apply_setup_choice(parent, primary, timeline, review, keys, open_workshop=True, auto_download=True,
                            download_source=str(dialog.source_combo.currentData() or 'AUTO'))
        return True
    except Exception:
        traceback.print_exc()
        _startup_mark("FIRST_RUN_WIZARD_FAILED", traceback=traceback.format_exc())
        return False


def _home_spoken_language(parent) -> str:
    """The home page's 视频里说的话 as the plan window's language row names it ('' for 自动)."""
    combo = parent.__dict__.get("recognition_language")
    value = str(combo.currentData() or "") if combo is not None else ""
    return "" if value == "auto" else value


def _apply_spoken_language(parent, spoken: str) -> None:
    """Select ``spoken`` on the home page; its own handler saves it and renames the timeline card."""
    combo = parent.__dict__.get("recognition_language")
    index = combo.findData(spoken) if combo is not None and spoken else -1
    if index >= 0 and index != combo.currentIndex():
        combo.setCurrentIndex(index)


def _apply_plan_for_tutorial(parent, dialog) -> None:
    """Save the plan picked in the tutorial; what it downloads waits for the end of the tutorial."""
    primary, timeline, review = dialog.backends
    if dialog.choice == "cloud":
        preset = getattr(dialog, "api_preset", "") or "mosi_moss_pro"
        index = parent.qwen_asr_api_provider.findData(preset)
        if index >= 0:
            parent.qwen_asr_api_provider.setCurrentIndex(index)
        parent._apply_asr_preset_fields(preset)
    keys = GuidedSetupDialog.download_keys_for(primary, timeline, review)
    _apply_setup_choice(parent, primary, timeline, review, keys, open_workshop=False, auto_download=False)
    parent._first_run_downloads = (primary, tuple(keys), str(dialog.source_combo.currentData() or 'AUTO'))


def _open_guided_setup(parent) -> bool:
    """The detailed chooser: every role and model (presets for this computer)."""
    try:
        dialog = GuidedSetupDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        primary, timeline, review = dialog.selected_backends()
        _apply_setup_choice(parent, primary, timeline, review, dialog.selected_download_keys(),
                            open_workshop=dialog.open_workshop, auto_download=dialog.auto_download)
        return True
    except Exception:
        # A broken wizard must not strand a first-run user silently.
        traceback.print_exc()
        _startup_mark("FIRST_RUN_WIZARD_FAILED", traceback=traceback.format_exc())
        return False


def _apply_setup_choice(parent, primary, timeline, review, download_keys, *, open_workshop, auto_download,
                        download_source='AUTO'):
    """Save the chosen roles, refresh the home page, then open the workshop download if asked."""
    desired = parent._asr_values()
    desired.update(
        primary_asr_backend=primary,
        firered_asr_backend=timeline,
        qwen_asr_backend=review,
    )
    # Persist the user's desired backends even though incomplete local models
    # are deliberately hidden from the main selectors.  Once downloading
    # finishes, refresh selects these saved roles automatically.
    persist_asr_configuration(parent.legacy, desired, require_ready=False)
    parent._missing_saved_asr_backends = populate_available_asr_choices(
        parent.primary_asr_backend,
        parent.qwen_asr_backend,
        parent.firered_asr_backend,
        parent.legacy.RUNTIME_SETTINGS,
    )
    parent._apply_asr_backend_mode()
    parent._refresh_recognition_recommendation()   # the plan menu names the choice at once (2026-10-24)
    if open_workshop:
        QTimer.singleShot(0, lambda: _open_combination_download(parent, primary,
                                                                download_keys if auto_download else (),
                                                                download_source))


def _open_combination_download(parent, primary, download_keys, download_source='AUTO'):
    """The workshop on the chosen main model, downloading what the combination still needs."""
    parent._open_model_workshop()
    parent.workshop_page.focus_primary_backend(primary)
    if download_keys:
        parent.workshop_page.download_combination(
            download_keys,
            "首次选择的字幕识别组合",
            auto_start=True,
            source_mode=download_source,
        )


def _preview(screenshot_path: str, state: str = "settings") -> int:
    import moss_firered_pipeline
    import subtitle_core

    _configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")
    apply_application_theme(app)
    _register_bundled_fonts()
    app.setFont(_app_font())
    preview_media = [] if state in {"empty", "terms"} else [
        r"F:\直播回放\舰礼有等身抱枕～代刮刮刮乐～_vocal.wav"
    ]
    window = MainWindow(
        preview_media,
        subtitle_core,
        moss_firered_pipeline,
        {"id": "preview", "checks": 0},
    )
    if preview_media:
        window.game_box.setCurrentText("舰礼有等身抱枕～代刮刮刮乐～")
    show_workflow_after_show = state == "workflow"
    if state == "ai":
        window.ai_panel.set_expanded(True, animate=False)
    elif state == "local-grouping":
        window.ai_grouping.setChecked(False)
        window.ai_panel.set_expanded(True, animate=False)
    elif state == "progress":
        window.pages.setCurrentIndex(1)
        window.started_at = time.perf_counter() - 89
        for stage_index in range(1, 8):
            window._completed_stages.add(stage_index)
        window._active_stages[8] = {
            "label": "云端模型受限校对",
            "resource": "OpenAI 兼容 API + 本地安全裁决",
            "started": time.perf_counter(),
        }
        window._append_feed("完成", "本地识别与说话人筛选 · 40.5 秒", GREEN)
        window._append_feed("并行", "3 个字幕校对批次正在运行", PURPLE)
        window._append_feed("自愈", "异常断句会回退源段重建并重新校验", GREEN)
        window._append_console_line("[阶段 8/11] 云端模型受限校对（OpenAI 兼容 API+本地安全裁决）")
        window._append_console_line("   [并行加速] 3 个校对批次，最多 4 路并发。")
        window._append_console_line("   校对批次 1/3")
        window._append_console_line("   [缓存命中] polished_batch，复用已完成批次。")
        window._refresh_progress_cards()
        window._progress_motion.setCurrentTime(window._progress_motion.duration())
        window._update_progress_clock()
    elif state == "result":
        window.pages.setCurrentIndex(2)
        window.workflow.set_active(3, finished=True)
        window.result_icon.setPixmap(_icon("fa5s.check-circle", GREEN).pixmap(QSize(72, 72)))
        bind_text(window.result_title, '字幕生成完成')
        bind_text(window.result_summary, '成功 1 个 · 失败 0 个 · 取消 0 个 · 总耗时 168.4 秒')
        window.result_files.setHtml(
            f'<div style="background:#edf5e9; border-left:4px solid {GREEN}; '
            f'padding:10px; border-radius:7px;"><b style="color:{GREEN};">完成</b>'
            "&nbsp;&nbsp;<b>示例素材.wav</b><br>字幕：桌面\\示例素材_剪映文稿.srt"
            "<br>报告：项目\\reports\\示例素材_字幕任务报告.txt</div>"
        )
        window._append_console_line("[完成] 断句：35 条，中位 5 字/1.22 秒。")
        window._append_console_line("[阶段 11/11] 写入剪映文稿、总SRT与分轨SRT（磁盘）")
        window._append_console_line("[文件完成 1/1] 168.4秒")
        set_log_html_keep_left(window.result_console, window.console_log.toHtml())
    elif state in {
        "workshop",
        "workshop-api",
        "workshop-download",
        "workshop-timeline",
        "workshop-review",
        "workshop-technical",
    }:
        window.resize(1440, 960)
        window._open_model_workshop()
        if state == "workshop-api":
            window.workshop_page._set_role("api")
            window.workshop_page._view_model("qwen31_filetrans")
        elif state == "workshop-timeline":
            window.workshop_page._set_role("timeline")
            window.workshop_page._view_model("firered")
        elif state == "workshop-review":
            window.workshop_page._set_role("review")
            window.workshop_page._view_model("qwen_local")
        elif state == "workshop-download":
            model = window.workshop_page._cards["moss"].model
            dialog = ModelDownloadDialog(window.workshop_page.root, model, window.workshop_page)
            window.workshop_page._download_dialogs.append(dialog)
            dialog.show()
        elif state == "workshop-technical":
            dialog = ModelTechnicalDialog(
                window.workshop_page._cards["paraformer"].model,
                window.workshop_page,
            )
            window.workshop_page._technical_preview_dialog = dialog
            dialog.show()
    elif state == "history":
        window.resize(1440, 960)
        window._open_recognition_history()
    window.show()
    app.processEvents()
    if state == "first-run":
        dialog = GuidedSetupDialog(window)
        dialog.show()
        app.processEvents()
        target = Path(screenshot_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ok = dialog.grab().save(str(target), "PNG")
        dialog.close()
        window.close()
        return 0 if ok else 1
    if state == "terms":
        target = Path(screenshot_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        capture_result = {"ok": False}

        def capture_term_library():
            active = QApplication.activeModalWidget()
            if active is not None:
                capture_result["ok"] = active.grab().save(str(target), "PNG")
                active.accept()

        QTimer.singleShot(180, capture_term_library)
        window._manage_terms()
        window.close()
        return 0 if capture_result["ok"] else 1
    if state == "smart-terms":
        target = Path(screenshot_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        capture_result = {"ok": False}

        def capture_smart_terms():
            active = QApplication.activeModalWidget()
            if active is not None:
                capture_result["ok"] = active.grab().save(str(target), "PNG")
                active.accept()

        QTimer.singleShot(180, capture_smart_terms)
        SmartGlossaryDialog(window, "我的世界", window).exec()
        window.close()
        return 0 if capture_result["ok"] else 1
    if state == "drop":
        window.drop_overlay.set_file_count(2)
        window._set_drop_active(True)
        window.drop_overlay.animation.setCurrentTime(window.drop_overlay.animation.duration())
        app.processEvents()
    if show_workflow_after_show:
        window.show_workflow_popover()
        window._workflow_animation.setCurrentTime(window._workflow_animation.duration())
        app.processEvents()
    capture_widget = window
    if state == "workshop-download":
        capture_widget = window.workshop_page._download_dialogs[-1]
    if state == "workshop-technical":
        capture_widget = window.workshop_page._technical_preview_dialog
    if state == "combo":
        window.language_combo.showPopup()
        app.processEvents()
        popup = window.language_combo._popup
        if popup._animation is not None:
            popup._animation.setCurrentTime(popup._animation.duration())
        app.processEvents()
        capture_widget = popup
    target = Path(screenshot_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ok = capture_widget.grab().save(str(target), "PNG")
    window.close()
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) in {3, 4} and sys.argv[1] == "--screenshot":
        raise SystemExit(_preview(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "settings"))
    raise SystemExit("请通过 2ByteASR.bat 启动 2ByteASR。")
