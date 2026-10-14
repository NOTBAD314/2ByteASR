"""PySide6 desktop shell for the 2ByteASR settings, progress, and result flow."""

from __future__ import annotations

import os
from .glossary_write_feedback import glossary_write_errors
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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import qtawesome as qta
import requests
from PySide6.QtCore import (
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

from twobyteasr.typography import TITLE_FONT_STACK, UI_FONT_STACK
from twobyteasr.ui_theme import (
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
from twobyteasr.hardware import detect_cuda_runtime
from twobyteasr.model_workshop import (
    MODELS,
    ModelDownloadDialog,
    ModelPickerPanel,
    ModelTechnicalDialog,
    ModelWorkshopPage,
    _model_roles,
    installed_model_keys,
)
from twobyteasr.model_registry import ModelHealth, ModelRegistry, scan_model_registry
from twobyteasr.recognition_history import RecognitionHistoryPage
from twobyteasr.glossary_learning import GlossaryLearningStore
from twobyteasr.project_profiles import ASR_CONFIG_KEYS, ProjectProfile, ProjectProfileStore, normalize_llm_config
from twobyteasr.runtime_trace import GLOBAL_STUDIO_TRACE
from twobyteasr.recognition_plans import (
    lightweight_media_profile,
    matching_plan,
    plan_options,
    recognition_plan,
)
from twobyteasr.ui_navigation import NAVIGATION_QSS, WorkspaceNavigation, style_workspace_sidebar_heading
from twobyteasr.settings import save_runtime_settings
from twobyteasr.llm_config import (
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
from twobyteasr.ai_providers import AITransport
from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY

from .i18n import bind_text, tr, user_text


def provider_for_stage(settings, stage):
    """Compatibility seam; all real clients come from the shared registry."""
    return GLOBAL_PROVIDER_REGISTRY.client(stage=stage, settings=settings)
from subtitle_core import run_llm_json_self_test
from twobyteasr.service import CancellationToken, RunOptions, run_media_queue
from twobyteasr.updater import (
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
from twobyteasr.startup_trace import mark as _startup_mark
from twobyteasr import ui_zoom
from twobyteasr.lazy_pages import existing_page

# Work that must not delay the first window; run on the GUI thread about
# 2.5 s after it is interactive (MainWindow._warm_studio_module).
_STARTUP_IDLE_TASKS = []


def after_startup_idle(task):
    _STARTUP_IDLE_TASKS.append(task)


from twobyteasr.main_ui_helpers import (
    APP_ROOT, APP_ICON_SOURCE_PATH, APP_ICON_FALLBACK_PATH, APP_ICON_PATH,
    LAST_MEDIA_DIRECTORY_KEY, SUPPORTED_MEDIA_SUFFIXES, GUI_PROFILE_ENABLED,
    _media_dialog_initial_directory, _remember_media_directory,
    _select_media_paths, _merge_media_paths, _is_ai_config_failure,
)
from twobyteasr.main_ui_theme import APP_QSS
from twobyteasr.theme_manager import apply_application_theme, apply_theme, theme_key
from twobyteasr.themed_icons import install_themed_icon, themed_icon
from twobyteasr.main_ui_dialogs import DialogSurface, SpringDialog
from twobyteasr.main_ui_branding import HeaderMascot, _app_icon, _brand_pixmap
from twobyteasr.main_ui_glossary import (
    TermLibraryDialog,
    TermGameListRow,
    _CategoryPillDelegate,
    _TermMappingsModel,
    term_library_game_names,
)
from twobyteasr.main_ui_popup import EditableHistoryCombo, FramelessPopupCombo, _ComboPopup
from twobyteasr.main_ui_smart_glossary import SmartGlossaryDialog, SmartGlossaryWorker
from twobyteasr.ui_widgets import AnimatedButton, SwitchControl
from twobyteasr.glossary_binding import GlossaryBindingResolver

QWEN_API_KEY_HELP_URL = "https://help.aliyun.com/zh/model-studio/get-api-key"

ASR_API_PRESETS = {
    # 2026-10-13: Qwen Cloud — the official international Qwen API platform
    # (home.qwencloud.com). One pay-as-you-go key, no workspace host, no OSS:
    # audio goes through the provider's own 48-hour temporary upload.
    "qwen_cloud_filetrans": {
        "short": "Qwen Cloud 录音文件识别", "label": "Qwen Cloud（Qwen 官方 API）｜录音文件识别",
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
        # (twobyteasr.qwen31_asr.FILETRANS_MODELS).
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
        "label": "OpenRouter MAI 2.1（模型映射待验证）",
        "protocol": "openrouter_verbose_json",
        "model": "",
        "url": "https://openrouter.ai/api/v1/audio/transcriptions",
    },
    "azure": {
        "short": "Azure",
        "label": "Azure MAI 2.1（部署映射待验证）",
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
)


def populate_available_asr_choices(primary, review, timeline, settings, root=APP_ROOT):
    """Populate selectors from complete local installs, never from catalog claims."""
    installed = installed_model_keys(Path(root))
    desired = settings.get("models", {})
    missing = []

    def fill(combo, local_choices, trailing, setting_key, fallback):
        wanted = str(desired.get(setting_key, fallback))
        combo.blockSignals(True)
        combo.clear()
        for label, value, required in local_choices:
            if required <= installed:
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


def _icon(name: str, color: str | None = None) -> QIcon:
    # No explicit color means "follow the active theme's primary icon color".
    if color is None:
        return themed_icon(name, "primary")
    return qta.icon(name, color=color)

def parse_ai_game_terms(content: str, limit: int = 36) -> list[dict]:
    """Parse and constrain one search-enabled model response for the term library."""
    text = str(content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 没有返回可读取的术语 JSON。")
    payload = json.loads(text[start : end + 1])
    raw_terms = payload.get("terms", []) if isinstance(payload, dict) else []
    if not isinstance(raw_terms, list):
        raise ValueError("AI 返回结果缺少 terms 数组。")
    result = []
    seen = set()
    for item in raw_terms:
        if not isinstance(item, dict):
            continue
        term = " ".join(str(item.get("term", "") or "").split()).strip("，,。；;：:")
        if not (2 <= len(term) <= 18) or term in seen or any(char in term for char in "\r\n<>[]{}"):
            continue
        category = " ".join(str(item.get("category", "游戏术语") or "游戏术语").split())[:12]
        sources = [
            str(url).strip()
            for url in item.get("sources", ())
            if str(url).strip().lower().startswith("https://")
        ][:3]
        result.append({"term": term, "category": category, "sources": sources})
        seen.add(term)
        if len(result) >= max(1, int(limit)):
            break
    if not result:
        raise ValueError("AI 没有找到可加入词库的可靠游戏术语。")
    return result


def request_ai_game_terms(
    endpoint: dict,
    game_name: str,
    requests_module=requests,
    *,
    content_type: str = "game",
) -> list[dict]:
    """Build a bounded, reviewable lexicon with any OpenAI-compatible text model."""
    validate_endpoint(endpoint, "AI 游戏术语搜索")
    supports_forced_search = endpoint.get("provider") == "bailian"
    research_instruction = (
        "请联网检索官方资料、可信百科或大型攻略站"
        if supports_forced_search
        else "请根据你掌握的可靠游戏资料整理；不确定的词不要输出"
    )
    type_labels = {
        "game": "游戏",
        "event": "活动或嘉年华",
        "series": "系列或 IP",
        "creator": "主播或创作者",
        "other": "内容主题",
    }
    type_label = type_labels.get(str(content_type), "内容主题")
    prompt = f"""你是字幕术语资料整理员。目标类型是“{type_label}”，名称为《{game_name}》。{research_instruction}，整理适合语音识别的中文专名。

要求：
1. 优先角色名、技能名、地点、阵营、物品、机制和常用简称；不要收录普通汉语词、整句说明、版本号或未经证实的昵称。
2. 每个词必须是资料中实际出现的正式写法，2-18 个字符；同一词不要重复。
3. 每项给出 category；只有确实知道公开 HTTPS 来源时才填写 sources，禁止编造网址。
4. 最多 36 项。只返回 JSON：{{"terms":[{{"term":"三月七","category":"角色","sources":["https://example.com"]}}]}}。"""
    payload = {
        "model": endpoint["model"],
        "messages": [
            {"role": "system", "content": "只整理可信的游戏专名，不得编造；只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    if supports_forced_search:
        payload.update(
            enable_search=True,
            search_options={"forced_search": True, "search_strategy": "turbo"},
        )
    response = requests_module.post(
        endpoint["url"],
        headers={
            "Authorization": f"Bearer {endpoint['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(10, 180),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_ai_game_terms(content)


def _register_bundled_fonts() -> None:
    """Register bundled Source Han Sans OTFs so every machine renders alike."""
    from PySide6.QtGui import QFontDatabase
    root = Path(__file__).resolve().parents[1]
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
    from twobyteasr.typography import application_font
    return application_font()


def _acquire_instance_lock():
    """Return the pingable GUI ownership endpoint, or ``None`` if it is live."""
    from twobyteasr.single_instance import SingleInstanceGuard

    guard = SingleInstanceGuard(SingleInstanceGuard.application_name())
    if not guard.acquire():
        return None
    return guard


def _completion_notification_spec(result, outcomes=None):
    """Use the same terminal model as completion, reports and history."""
    from .recognition_outcome import normalize_recognition_outcome, normalize_recognition_queue
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





class BrandLabel(QLabel):
    hover_entered = Signal()
    hover_left = Signal()

    def enterEvent(self, event):
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)


class WindowTitleBar(QFrame):
    """Native-looking window controls without a native, dark title strip.

    Keeping this small bar inside ``appHeader`` gives the desktop shell one
    visual surface while retaining the expected move/minimize/maximize/close
    behaviour for a Windows tool.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("windowTitleBar")
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 1, 8, 1)
        row.setSpacing(4)
        # The product brand belongs to the main header below.  Keeping the
        # draggable chrome intentionally quiet prevents a duplicate wordmark
        # while the title bar still reads as part of the same warm surface.
        self.title = QLabel("2ByteASR  兔白字幕")
        self.title.setObjectName("windowChromeTitle")
        self.title.hide()
        row.addStretch(1)

        self.minimize_button = self._control_button(
            "fa5s.minus", "最小化", self._window.showMinimized
        )
        self.maximize_button = self._control_button(
            "fa5s.square", "最大化", self.toggle_maximized
        )
        self.close_button = self._control_button(
            "fa5s.times", "关闭", self._window.close, close=True
        )
        row.addWidget(self.minimize_button)
        row.addWidget(self.maximize_button)
        row.addWidget(self.close_button)

    def _control_button(self, icon_name: str, tooltip: str, callback, *, close: bool = False):
        button = QPushButton()
        button.setObjectName("windowControlClose" if close else "windowControl")
        install_themed_icon(button, icon_name, "window_control")
        button.setIconSize(QSize(12, 12))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def set_title(self, text: str):
        self.title.setText(text)

    def toggle_maximized(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def sync_window_state(self):
        maximized = self._window.isMaximized()
        install_themed_icon(
            self.maximize_button,
            "fa5s.compress-alt" if maximized else "fa5s.square",
            "window_control",
        )
        (bind_text(self.maximize_button, '还原窗口', property='toolTip') if maximized else bind_text(self.maximize_button, '最大化', property='toolTip'))
        self.maximize_button.setAccessibleName(self.maximize_button.toolTip())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            if self._window.isMaximized():
                # 2026-10-15: a click (or the first click of a double-click)
                # no longer restores the window; dragging past the drag
                # distance does, under the cursor (window_constraints).
                from .window_constraints import begin_title_drag
                self._drag_offset = None
                begin_title_drag(self._window, global_pos, event.position().y())
            else:
                self._drag_offset = global_pos - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _NativeResizeHandle(QWidget):
    """Thin edge overlay that delegates resizing to the window manager."""

    def __init__(self, owner: QWidget, edges: Qt.Edge, cursor: Qt.CursorShape):
        super().__init__(owner)
        self.owner = owner
        self.edges = edges
        self.setCursor(cursor)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; border: 0;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.owner.isMaximized():
            handle = self.owner.windowHandle()
            if handle is not None and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class CompletionDialog(SpringDialog):
    """Theme-stable completion card that does not inherit native dark dialogs."""

    _VISUALS = {
        QMessageBox.Icon.Information: ("success", "fa5s.check", "处理完成"),
        QMessageBox.Icon.Warning: ("warning", "fa5s.exclamation", "任务提醒"),
        QMessageBox.Icon.Critical: ("danger", "fa5s.exclamation", "需要处理"),
    }

    def __init__(self, title: str, message: str, icon, details: str = "", parent=None):
        super().__init__(parent)
        role, icon_name, badge_text = self._VISUALS.get(
            icon,
            self._VISUALS[QMessageBox.Icon.Information],
        )
        theme = theme_definition(theme_key())
        self.accent = getattr(theme, role)
        self.tint = getattr(theme, f"{role}_soft", theme.accent_soft)
        self.setObjectName("completionDialog")
        self.setWindowTitle(f"2ByteASR｜{title}")
        self.setWindowIcon(_app_icon())
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(580)
        self.setSizeGripEnabled(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.card = DialogSurface(
            self,
            title="2ByteASR",
            close_callback=self.reject,
        )
        self.card.setObjectName("completionCard")
        outer.addWidget(self.card)

        brand_icon = QLabel()
        brand_icon.setFixedSize(30, 30)
        # Use full original sprite for the small UI header logo (do not use the Taskbar face-crop here).
        # The face-cropped icon is only for window/taskbar (setWindowIcon + AppUserModelID).
        if APP_ICON_SOURCE_PATH.is_file():
            brand_icon.setPixmap(QIcon(str(APP_ICON_SOURCE_PATH)).pixmap(QSize(30, 30)))
        else:
            brand_icon.setPixmap(_app_icon().pixmap(QSize(30, 30)))
        brand_icon.setStyleSheet("border: 0; background: transparent;")
        self.card.header_layout.insertWidget(0, brand_icon)

        self.status_badge = QLabel(badge_text)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            f"color: {self.accent}; background: {self.tint}; border: 1px solid {self.accent}; "
            "border-radius: 11px; padding: 3px 10px; font-size: 12px; font-weight: 800;"
        )
        self.card.header_layout.insertWidget(
            self.card.header_layout.count() - 1,
            self.status_badge,
        )
        card_layout = self.card.body_layout

        body = QHBoxLayout()
        body.setContentsMargins(2, 0, 2, 0)
        body.setSpacing(18)
        icon_well = QLabel()
        icon_well.setFixedSize(72, 72)
        icon_well.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_well.setPixmap(_icon(icon_name, self.accent).pixmap(QSize(34, 34)))
        icon_well.setStyleSheet(
            f"background: {self.tint}; border: 2px solid {self.accent}; border-radius: 36px;"
        )
        body.addWidget(icon_well, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(7)
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"color: {theme.text}; font-size: 22px; font-weight: 900; border: 0; background: transparent;"
        )
        copy.addWidget(self.title_label)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setStyleSheet(
            f"color: {theme.text_muted}; font-size: 14px; border: 0; background: transparent;"
        )
        copy.addWidget(self.message_label)
        body.addLayout(copy, 1)
        card_layout.addLayout(body)

        self.details_label = QLabel(details)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.setStyleSheet(
            f"color: {theme.text}; background: {self.tint}; border: 1px solid {theme.border}; border-radius: 12px; "
            "padding: 10px 12px; font-size: 13px;"
        )
        # 2026-10-15: a long failure (worker stderr, traceback) scrolls inside
        # the card instead of stretching the dialog to the full screen height.
        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("completionDetailsScroll")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setStyleSheet("QScrollArea#completionDetailsScroll { background: transparent; border: 0; }")
        self.details_scroll.setWidget(self.details_label)
        self.details_scroll.setMaximumHeight(240)
        self.details_scroll.setVisible(bool(details))
        card_layout.addWidget(self.details_scroll)

        footer = self.card.footer_layout
        footer.setSpacing(12)
        hint = QLabel("任务结果已同步到工作台")
        hint.setStyleSheet(f"color: {theme.text_muted}; font-size: 12px; border: 0; background: transparent;")
        footer.addWidget(hint)
        footer.addStretch(1)
        self.confirm_button = AnimatedButton("知道了")
        self.confirm_button.setDefault(True)
        self.confirm_button.setMinimumSize(112, 42)
        self.confirm_button.setStyleSheet(
            f"QPushButton {{ color: {theme.text_on_accent}; background: {theme.accent}; border: 1px solid {theme.accent}; "
            "border-radius: 12px; padding: 8px 22px; font-size: 14px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}"
            f"QPushButton:pressed {{ background: {theme.accent_pressed}; border-color: {theme.accent_pressed}; padding-top: 10px; }}"
        )
        self.confirm_button.clicked.connect(self.accept)
        footer.addWidget(self.confirm_button)

        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(190)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        apply_ui_language(self)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(parent.window().frameGeometry().center())
            self.move(geometry.topLeft())
        self.setWindowOpacity(0.0)
        self._fade_in.stop()
        self._fade_in.start()
        self.confirm_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)


class SignalTextStream:
    """Tee text written by the pipeline to both the GUI and the original console."""

    def __init__(self, signal, level: str, fallback=None):
        self.signal = signal
        self.level = level
        self.fallback = fallback
        self._buffer = ""
        self._lock = threading.RLock()

    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return False

    def writable(self):
        return True

    def write(self, value):
        text = str(value or "")
        if not text:
            return 0
        with self._lock:
            if self.fallback is not None:
                try:
                    self.fallback.write(text)
                except Exception:
                    pass
            self._buffer += text.replace("\r\n", "\n").replace("\r", "\n")
            lines = self._buffer.split("\n")
            self._buffer = lines.pop()
            for line in lines:
                if line.strip():
                    self.signal.emit(line, self.level)
        return len(text)

    def flush(self):
        with self._lock:
            if self._buffer.strip():
                self.signal.emit(self._buffer, self.level)
            self._buffer = ""
            if self.fallback is not None:
                try:
                    self.fallback.flush()
                except Exception:
                    pass


def keep_log_view_at_left(edit) -> None:
    """Pin a runtime log view's horizontal scrollbar to the left edge.

    Manual horizontal scrolling stays possible: this is only called right
    after a programmatic content change, never on user input.
    """
    bar = edit.horizontalScrollBar()
    if bar is not None:
        bar.setValue(bar.minimum())


def append_log_html_keep_left(edit, fragment: str) -> None:
    """Follow a live tail, but preserve a user's place in earlier log entries."""
    vertical = edit.verticalScrollBar()
    previous = vertical.value() if vertical is not None else 0
    follow_tail = vertical is None or previous >= vertical.maximum() - 2
    old_cursor = edit.textCursor()
    edit.append(fragment)
    if follow_tail:
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
        edit.setTextCursor(cursor)
    else:
        edit.setTextCursor(old_cursor)
    if vertical is not None:
        vertical.setValue(vertical.maximum() if follow_tail else previous)
    keep_log_view_at_left(edit)


def set_log_html_keep_left(edit, html_text: str) -> None:
    """Replace the whole log (task reload/completion fill) from the left."""
    edit.setHtml(html_text)
    keep_log_view_at_left(edit)


def _active_theme_definition():
    """Theme tokens for locally-styled runtime widgets (never warm literals)."""
    from twobyteasr.theme_manager import theme_key

    return theme_definition(theme_key())


from .progress_widgets import _ElidedValue as ElidedValueLabel
from .progress_widgets import (ElidedRowsLabel, FeedList, ProgressPhaseCard, RecognitionPreview, ResizeWatcher,
                               RunningIndicator, StageMetricGrid, StageProgressBar, TaskEventCard, log_line_html,
                               progress_page_qss)
from .i18n import join_text
from .recognition_status_text import recognition_event_text


class FlowStage(QWidget):
    def __init__(self, icon_name: str, title: str, subtitle: str, color: str):
        super().__init__()
        self.color = color
        self._state = ""
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(50, 50)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(_icon(icon_name, color).pixmap(QSize(31, 31)))
        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.icon_label)
        layout.addLayout(text)
        self.set_state("pending")

    def _stage_fill(self, state: str) -> str:
        theme = _active_theme_definition()
        if state == "done":
            return theme.accent_soft
        if state == "active":
            return theme.warning_soft
        return theme.surface_elevated

    def set_state(self, state: str):
        self._state = state
        opacity = "1.0" if state in {"active", "done"} else "0.68"
        self.setStyleSheet(f"opacity: {opacity};")
        self.icon_label.setStyleSheet(
            f"border: 2px solid {self.color}; border-radius: 25px; background: {self._stage_fill(state)};"
        )

    def refresh_theme_palette(self) -> None:
        self.set_state(self._state or "pending")


class WorkflowStrip(QFrame):
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 10, 18, 15)
        outer.setSpacing(7)
        ribbon = QLabel("  字幕生成流程  ")
        ribbon.setObjectName("sectionTitle")
        # P0: keep height minimal but let width breathe; CN text must not truncate.
        ribbon.setMinimumHeight(28)
        ribbon.setMaximumWidth(220)
        outer.addWidget(ribbon, 0, Qt.AlignmentFlag.AlignLeft)
        row = QHBoxLayout()
        row.setSpacing(17)
        specs = [
            ("fa5s.wave-square", "本地识别", "语音转写", GREEN),
            ("fa5s.pen-nib", "字幕校对", "识别错误修正", AMBER),
            ("fa5s.comment-alt", "全文断句", "添加标点与分句", BLUE),
            ("fa5s.file-export", "导出", "生成字幕文件", CORAL),
        ]
        self.stages = []
        for index, spec in enumerate(specs):
            stage = FlowStage(*spec)
            self.stages.append(stage)
            row.addWidget(stage, 1)
            if index < len(specs) - 1:
                arrow = QLabel()
                arrow.setPixmap(_icon("fa5s.arrow-right", "#99978f").pixmap(QSize(22, 22)))
                row.addWidget(arrow)
        outer.addLayout(row)
        self.set_active(0)

    def enterEvent(self, event):
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)

    def set_active(self, index: int, finished: bool = False):
        for stage_index, stage in enumerate(self.stages):
            if finished or stage_index < index:
                state = "done"
            elif stage_index == index:
                state = "active"
            else:
                state = "pending"
            stage.set_state(state)


class MediaPickCard(QFrame):
    """Whole local-media card is one accessible pick/drop target."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaRow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '选择本地视频或音频', property='accessibleName')
        self.setAccessibleDescription("按回车或空格打开文件选择，也可以把文件拖到这里")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint()) if hasattr(event, "position") else self.childAt(event.pos())
            button = child
            while button is not None and not isinstance(button, QAbstractButton):
                button = button.parentWidget() if button is not self else None
                if button is self:
                    button = None
                    break
            if button is None:
                self.activated.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MediaNameLabel(QLabel):
    """Media file name that elides in the middle instead of widening the page."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def text(self):
        return self._full_text

    def setText(self, text):
        self._full_text = str(text)
        self._elide()
        self.updateGeometry()

    def sizeHint(self):
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full_text) + margins.left() + margins.right() + 4
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(self.sizeHint().width(), 120), super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, max(20, self.contentsRect().width())
        )
        if shown != super().text():
            super().setText(shown)


class CollapsibleFrame(QFrame):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        icon_name: str,
        summary: str = "",
        expanded: bool = False,
        action_text: str = "",
    ):
        super().__init__()
        self.setObjectName("accordion")
        self._expanded = bool(expanded)
        # B3：整行都是 hit target。header 自身接收空白区/摘要点击，
        # title/chevron 子按钮 accept 自己的事件不会冒泡，天然单次 toggle。
        self.header = QWidget()
        self.header.setObjectName("accordionHeader")
        self.header.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.mousePressEvent = lambda event: (
            self.set_expanded(not self._expanded) if event.button() == Qt.MouseButton.LeftButton else None
        )
        self.header.keyPressEvent = lambda event: (
            self.set_expanded(not self._expanded)
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space)
            else QWidget.keyPressEvent(self.header, event)
        )
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 2, 8, 2)
        header_layout.setSpacing(10)
        self.title_button = AnimatedButton(title)
        self.title_button.setObjectName("accordionButton")
        self.title_button.setIcon(_icon(icon_name))
        self.title_button.setIconSize(QSize(21, 21))
        self.title_button.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header_layout.addWidget(self.title_button)
        header_layout.addStretch(1)
        self.summary_label = QLabel(summary)
        self.summary_label.setObjectName("accordionSummary")
        self.summary_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(self.summary_label)
        if action_text:
            self.action_button = AnimatedButton(action_text)
            self.action_button.clicked.connect(lambda: self.set_expanded(True))
            header_layout.addWidget(self.action_button)
        else:
            self.action_button = None
        self.chevron = AnimatedButton()
        self.chevron.setObjectName("flat")
        self.chevron.setFixedSize(30, 30)
        self.chevron.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header_layout.addWidget(self.chevron)
        self._title = title
        self._summary = summary
        self.content = QWidget()
        # Its maximum height follows its own size hint (interface zoom: own size).
        self.content.setProperty("uiZoomOwnSize", True)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 3, 16, 12)
        self.content_layout.setSpacing(8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self.animation = QPropertyAnimation(self.content, b"maximumHeight", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.set_expanded(expanded, animate=False)

    def set_summary(self, summary: str):
        self._summary = summary
        self._refresh_header()

    def _refresh_header(self):
        self.summary_label.setText(self._summary)
        icon_name = "fa5s.chevron-up" if self._expanded else "fa5s.chevron-down"
        self.chevron.setIcon(_icon(icon_name))
        self.chevron.setIconSize(QSize(14, 14))

    def set_expanded(self, expanded: bool, animate: bool = True):
        from .ui_motion import MOTION_STANDARD_MS, motion_duration
        self._expanded = bool(expanded)
        # 留 6px 余量：不同系统字体度量差异会导致 sizeHint 低估、内容被截
        target = self.content.sizeHint().height() + 6 if expanded else 0
        self.content.setVisible(True)
        self.content.setMinimumHeight(0)
        # 展开 180ms / 收起 150ms：收起不承载阅读内容，短一档让连续开关更干脆。
        duration = motion_duration(MOTION_STANDARD_MS if expanded else 150)
        if animate and duration and self.isVisible() and target <= 360:
            self.animation.stop()
            self.animation.setDuration(duration)
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.animation.setStartValue(min(self.content.height(), self.content.maximumHeight(), 360))
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self.animation.stop()
            self.content.setMaximumHeight(target)
        self._refresh_header()
        self.toggled.emit(bool(expanded))

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示后字体/布局已定型，重算展开高度，防止内容被截
        if self._expanded:
            self.content.setMaximumHeight(self.content.sizeHint().height() + 6)


class EndpointEditor(QFrame):
    def __init__(self, title: str, accent: str, stage: str, settings: dict):
        super().__init__()
        self.setObjectName("endpointCard")
        self.stage = stage
        self.accent = accent
        models = settings["models"]
        prefix = "polish" if stage == "polish" else "group"
        # Provider profile 是唯一事实源：base/model/protocol 按 active profile
        # 解析（旧扁平字段仅在非跨服务泄漏时参与回退），打开即自愈混合状态。
        self._settings_ref = settings
        GLOBAL_PROVIDER_REGISTRY.bind(settings)
        active = active_service_values(settings, stage=stage)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 13)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("endpointTitle")
        self.title_label.setStyleSheet(f"color: {accent}; font-size: 15px; font-weight: 700;")
        layout.addWidget(self.title_label)

        def section_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("endpointSectionLabel")
            return label
        self.service = FramelessPopupCombo()
        for service_id, spec in AI_SERVICE_SPECS.items():
            self.service.addItem(spec["label"], service_id)

        # Compatibility controls remain available to the existing persistence
        # and summary code, but the user selects a concrete service above.
        self.transport = FramelessPopupCombo()
        self.transport.addItem("API", AITransport.OPENAI_COMPATIBLE.value)
        self.transport.addItem("Google Antigravity", AITransport.ANTIGRAVITY_CLI.value)
        self.transport.addItem("Grok Account", AITransport.GROK_CLI.value)
        self.transport.addItem("OpenAI Codex CLI", AITransport.CODEX_CLI.value)
        self.transport.hide()
        current_transport = active["transport"]
        self.transport.setCurrentIndex(max(0, self.transport.findData(current_transport)))
        self.provider = FramelessPopupCombo()
        for key, spec in PROVIDER_PRESETS.items():
            self.provider.addItem(spec["label"], key)
        current_provider = active["provider"]
        self.provider.setCurrentIndex(max(0, self.provider.findData(current_provider)))
        self.provider.hide()
        self.model = FramelessPopupCombo()
        self.model.setEditable(True)
        defaults = list(service_model_catalog(settings, active.get("service", "custom")))
        if not defaults and active["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            defaults = ["qwen3.7-flash-2026-07-15", "qwen3.7-max", "glm-5.2"]
        self.model.addItems(defaults)
        self.model.setCurrentText(active["model"] or (defaults[0] if defaults else ""))
        self.base_url = QLineEdit(active["base_url"])
        self.base_url.setObjectName("endpointInput")
        self.custom_name = QLineEdit("自定义服务")
        self.custom_name.setObjectName("endpointInput")
        self.protocol = FramelessPopupCombo()
        for label, value in (
            ("Auto", "auto"),
            ("Responses API", "responses"),
            ("Chat Completions", "chat_completions"),
            ("OpenAI-compatible Chat", "openai_compatible_chat"),
        ):
            self.protocol.addItem(label, value)
        protocol_value = active["protocol"] or "auto"
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(protocol_value)))
        self.endpoint_hint = QLabel()
        self.endpoint_hint.setObjectName("fieldHint")
        self.endpoint_hint.setWordWrap(True)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.reveal_key = QToolButton()
        self.reveal_key.setIcon(_icon("fa5s.eye"))
        self.reveal_key.setFixedSize(36, 36)
        self.reveal_key.setCheckable(True)
        bind_text(self.reveal_key, '显示或隐藏 API Key', property='toolTip')
        bind_text(self.reveal_key, '显示或隐藏 API Key', property='accessibleName')
        self.reveal_key.toggled.connect(
            lambda visible: (
                self.key.setEchoMode(
                    QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
                ),
                self.reveal_key.setIcon(
                    _icon("fa5s.eye-slash" if visible else "fa5s.eye")
                ),
            )
        )
        # Provider-scoped key: read by (provider, base_url) so switching models keeps the key.
        prov = current_provider
        burl = active["base_url"]
        existing, source = read_api_key(prov, burl)
        # Legacy fallback is valid only for the historical Bailian preset.
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(stage)
        # P8C-R3.1 三态密钥：UNCHANGED（未输入，保持已存密钥）/ REPLACE（输入新值）/
        # CLEAR（仅点击“清除密钥”按钮）。空输入框永远不等于“删除已有密钥”，
        # placeholder 只是 UI metadata，绝不参与 secret 保存。
        self._key_state = "unchanged"
        self.key.textChanged.connect(self._on_key_text_changed)
        (bind_text(self.key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.key, '请输入 API Key', property='placeholderText'))
        self.clear_key_button = QToolButton()
        self.clear_key_button.setIcon(_icon("fa5s.eraser"))
        self.clear_key_button.setFixedSize(36, 36)
        bind_text(self.clear_key_button, '清除已保存的 API Key（保存时生效；环境变量不受影响）', property='toolTip')
        bind_text(self.clear_key_button, '清除已保存的 API Key', property='accessibleName')
        self.clear_key_button.clicked.connect(self._request_key_clear)
        self.clear_key_button.setVisible(bool(existing))
        self.test_button = AnimatedButton("测试连接")
        self.test_button.setObjectName("endpointPrimary")
        self.status = QLabel("已配置" if existing else "未配置密钥")
        self.status.setObjectName("statusGood" if existing else "statusWarn")
        self.status.setOpenExternalLinks(True)
        self.status.setWordWrap(True)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.reveal_key)
        key_row.addWidget(self.clear_key_button)
        self.api_page = QWidget()
        self.api_page.setObjectName("endpointApiPage")
        form = QFormLayout(self.api_page)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.custom_name_label = QLabel("Provider 名称")
        form.addRow(self.custom_name_label, self.custom_name)
        self.provider_label = QLabel("服务商预设")
        self.base_url_label = QLabel("Base URL")
        self.protocol_label = QLabel("协议 / Protocol")
        # Rarely changed connection details live in the advanced group below
        # (2026-10-08); the key stays in the main form.
        self.api_advanced = QWidget()
        advanced_form = QFormLayout(self.api_advanced)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setHorizontalSpacing(12)
        advanced_form.setVerticalSpacing(8)
        advanced_form.addRow(self.base_url_label, self.base_url)
        advanced_form.addRow("", self.endpoint_hint)
        advanced_form.addRow(self.protocol_label, self.protocol)
        self.key_label = QLabel("API 密钥")
        self.key_row_host = QWidget()
        self.key_row_host.setLayout(key_row)
        form.addRow(self.key_label, self.key_row_host)

        advanced = QHBoxLayout()
        advanced.setContentsMargins(0, 0, 0, 0)
        self.json_mode = QCheckBox("JSON Mode")
        self.structured_output = QCheckBox("Structured Output")
        self.stream_output = QCheckBox("stream")
        self.json_mode.setChecked(active.get('json_mode', models.get(f'{prefix}_json_mode', True)))
        self.structured_output.setChecked(active.get('structured_output', models.get(f'{prefix}_structured_output', True)))
        self.stream_output.setEnabled(False)
        bind_text(self.stream_output, '当前字幕处理后端使用非流式结构化响应', property='toolTip')
        advanced.addWidget(self.json_mode)
        advanced.addWidget(self.structured_output)
        advanced.addWidget(self.stream_output)
        advanced.addStretch(1)
        self.capabilities_host = QWidget()
        self.capabilities_host.setLayout(advanced)
        self.json_capability_status = QLabel()
        self.json_capability_status.setObjectName('fieldHint')
        self.json_capability_status.setWordWrap(True)

        self.cli_page = QWidget()
        self.cli_page.setObjectName("endpointCliPage")
        cli_layout = QVBoxLayout(self.cli_page)
        cli_layout.setContentsMargins(0, 0, 0, 0)
        cli_layout.setSpacing(7)
        self.cli_status = QLabel("CLI：未检测")
        self.cli_status.setObjectName("endpointCliStatus")
        self.account_status = QLabel("CLI Session：未知")
        self.account_status.setObjectName("endpointAccountStatus")
        self.cli_status.setWordWrap(True)
        self.account_status.setWordWrap(True)
        self.cli_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.account_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        cli_layout.addWidget(self.cli_status)
        cli_layout.addWidget(self.account_status)
        cli_actions = QHBoxLayout()
        self.detect_cli_button = QPushButton("重新检测")
        self.login_button = QPushButton("登录")
        self.install_button = QPushButton("安装帮助")
        self.update_cli_button = QPushButton("更新 CLI / 查看方法")
        self.update_cli_button.clicked.connect(self.start_cli_update)
        for button in (self.detect_cli_button, self.login_button, self.install_button, self.update_cli_button):
            button.setObjectName("endpointSecondary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            cli_actions.addWidget(button)
        cli_layout.addLayout(cli_actions)
        self.logout_button = QPushButton("退出 Codex 登录")
        self.logout_button.setObjectName("endpointSecondary")
        self.logout_button.clicked.connect(lambda: self.start_login(action="logout"))
        self.copy_diagnostics_button = QPushButton("复制诊断信息")
        self.copy_diagnostics_button.setObjectName("endpointSecondary")
        self.copy_diagnostics_button.clicked.connect(self.copy_provider_diagnostics)
        account_actions = QHBoxLayout()
        account_actions.addWidget(self.logout_button)
        account_actions.addWidget(self.copy_diagnostics_button)
        cli_layout.addLayout(account_actions)
        self.diagnostics_toggle = QPushButton('展开诊断详情')
        self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.setObjectName('endpointSecondary')
        self.diagnostics_details = QPlainTextEdit()
        self.diagnostics_details.setObjectName('endpointDiagnostics')
        self.diagnostics_details.setReadOnly(True)
        self.diagnostics_details.setMaximumHeight(180)
        self.diagnostics_details.hide()
        self.diagnostics_toggle.toggled.connect(self.diagnostics_details.setVisible)
        cli_layout.addWidget(self.diagnostics_toggle)
        cli_layout.addWidget(self.diagnostics_details)

        service_form = QFormLayout()
        service_form.setHorizontalSpacing(12)
        service_form.setVerticalSpacing(8)
        service_row = QHBoxLayout()
        service_row.setContentsMargins(0, 0, 0, 0)
        service_row.addWidget(self.service, 1)
        # 2026-10-13: every provider has its own application guide.
        self.guide_button = QPushButton("申请教程")
        self.guide_button.setObjectName("helpLink")
        self.guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.guide_button, '查看这家服务的申请步骤、官方链接与费用说明', property='toolTip')
        self.guide_button.clicked.connect(self._open_provider_guide)
        service_row.addWidget(self.guide_button)
        service_form.addRow("AI 服务", service_row)
        layout.addWidget(section_label("Provider"))
        layout.addLayout(service_form)
        layout.addWidget(section_label("Account / Auth"))
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.test_button)
        layout.addLayout(status_row)
        layout.addWidget(section_label("Connection"))
        self.settings_stack = QStackedWidget()
        self.settings_stack.setObjectName("endpointSettingsStack")
        self.settings_stack.addWidget(self.api_page)
        self.settings_stack.addWidget(self.cli_page)
        layout.addWidget(self.settings_stack)
        layout.addWidget(section_label("Model"))
        model_form = QFormLayout()
        self.model_label = QLabel("模型")
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.addWidget(self.model, 1)
        self.discover_models_button = QPushButton("刷新模型")
        self.discover_models_button.setObjectName("endpointSecondary")
        bind_text(self.discover_models_button, '后台获取模型列表；不支持时仍可手动输入', property='toolTip')
        model_row.addWidget(self.discover_models_button)
        model_form.addRow(self.model_label, model_row)
        # 已下线模型的显式提示位：不静默换模型，也绝不把墓碑 id 当正常选项。
        self.model_warning = QLabel()
        self.model_warning.setObjectName("fieldHint")
        self.model_warning.setWordWrap(True)
        self.model_warning.setStyleSheet("color:#f2c66d;")
        self.model_warning.hide()
        model_form.addRow(self.model_warning)
        layout.addLayout(model_form)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("endpointAdvancedToggle")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind_text(self.advanced_toggle, '进阶设置：Base URL、协议与输出能力')
        self.advanced_box = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_box)
        advanced_layout.setContentsMargins(0, 4, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self.api_advanced)
        advanced_layout.addWidget(section_label("Capabilities"))
        advanced_layout.addWidget(self.capabilities_host)
        advanced_layout.addWidget(self.json_capability_status)
        self.advanced_box.hide()

        def show_advanced(checked):
            self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            self.advanced_box.setVisible(checked)

        self.advanced_toggle.toggled.connect(show_advanced)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced_box)
        self.last_connection_ok = None

        restored_service = active["service"] if active["service"] in AI_SERVICE_SPECS else self._service_for_settings(current_transport, str(current_provider), self.base_url.text())
        self.service.setCurrentIndex(max(0, self.service.findData(restored_service)))
        self.provider.currentIndexChanged.connect(self._provider_or_url_changed)
        self.service.currentIndexChanged.connect(self._service_changed)
        self.base_url.textChanged.connect(self._provider_or_url_changed)
        self.base_url.textChanged.connect(self._refresh_endpoint_hint)
        self.protocol.currentIndexChanged.connect(self._refresh_endpoint_hint)
        self.test_button.clicked.connect(self.test_connection)
        self.detect_cli_button.clicked.connect(self.detect_cli)
        self.login_button.clicked.connect(self.start_login)
        self.install_button.clicked.connect(self.show_install_instructions)
        self.discover_models_button.clicked.connect(
            lambda: self.cancel_model_discovery() if self._model_discovery_running() else self.discover_models(refresh=True)
        )
        self._tester = None
        self._login_worker = None
        self._model_discovery_worker = None
        self._model_discovery_timer = QTimer(self)
        self._model_discovery_timer.setSingleShot(True)
        self._model_discovery_timer.setInterval(650)
        self._model_discovery_timer.timeout.connect(self.discover_models)
        self._connection_started_at = 0.0
        # remember last resolved provider+url to avoid wiping typed key on focus changes
        self._last_key_scope = (str(prov), str(burl))
        self._service_changed(initial=True)
        self._refresh_model_retirement_warning(restored_service)
        # 用户手动改选模型即视为对"重新选择"警告的回应；保存后旧值移除。
        self.model.currentTextChanged.connect(lambda *_: self.model_warning.hide())
        for signal in (
            self.base_url.editingFinished,
            self.key.editingFinished,
            self.protocol.currentIndexChanged,
            self.service.currentIndexChanged,
        ):
            signal.connect(self._queue_model_discovery)
        self._discovery_pending = False
        self.base_url.textChanged.connect(self._invalidate_model_discovery)
        self.key.textChanged.connect(self._invalidate_model_discovery)
        for signal in (self.model.currentTextChanged, self.base_url.textChanged,
                self.key.textChanged, self.protocol.currentIndexChanged,
                self.json_mode.toggled, self.structured_output.toggled):
            signal.connect(self._invalidate_endpoint_tasks)
        self._queue_model_discovery()
        self.refresh_theme_palette()

    def _refresh_model_retirement_warning(self, service_id: str = "") -> None:
        """已下线模型的显式告知：编辑器回落默认，但绝不静默沿用墓碑 id。"""
        service_id = str(service_id or getattr(self, "_active_service_id", "") or "custom")
        profile = normalize_provider_profile(
            get_provider_profiles(self._settings_ref).get(service_id, {})
        )
        stored = profile.get("model", "")
        if not stored:
            flat_prefix = self.stage if self.stage in {"polish", "group"} else "polish"
            stored = str(
                self._settings_ref.get("models", {}).get(f"{flat_prefix}_model", "") or ""
            ).strip()
        if model_is_retired(stored):
            bind_text(self.model_warning, '此前选择的模型 {stored} 已不可用，请从当前可用模型中重新选择；保存新选择后旧值会被移除。', stored=stored)
            self.model_warning.show()
        else:
            self.model_warning.hide()

    @staticmethod
    def _service_for_settings(transport: str, provider: str, base_url: str) -> str:
        if transport == AITransport.ANTIGRAVITY_CLI.value:
            return "antigravity"
        if transport == AITransport.GROK_CLI.value:
            return "grok_account"
        if transport == AITransport.CODEX_CLI.value:
            return "codex_cli"
        if provider in AI_SERVICE_SPECS and provider not in {"antigravity", "grok_account"}:
            return provider
        host = str(base_url or "").casefold()
        if "api.openai.com" in host:
            return "openai"
        if "api.deepseek.com" in host:
            return "deepseek"
        if "generativelanguage.googleapis.com" in host:
            return "gemini"
        if "api.x.ai" in host:
            return "xai"
        return "custom"

    def _service_changed(self, _index: int = -1, *, initial: bool = False) -> None:
        self._invalidate_endpoint_tasks()
        if hasattr(self, '_model_discovery_timer'):
            self._invalidate_model_discovery()
        service_id = str(self.service.currentData() or "custom")
        spec = AI_SERVICE_SPECS[service_id]
        self._active_service_id = service_id
        transport = str(spec["transport"])
        self.transport.blockSignals(True)
        self.transport.setCurrentIndex(max(0, self.transport.findData(transport)))
        self.transport.blockSignals(False)
        provider = str(spec["provider"])
        provider_index = self.provider.findData(provider)
        if provider_index >= 0:
            self.provider.blockSignals(True)
            self.provider.setCurrentIndex(provider_index)
            self.provider.blockSignals(False)
        is_api = transport == AITransport.OPENAI_COMPATIBLE.value
        self.settings_stack.setCurrentWidget(self.api_page if is_api else self.cli_page)
        self.settings_stack.setMaximumHeight(16777215)
        # A hidden page must not reserve height (QStackedLayout skips Ignored).
        for page in (self.api_page, self.cli_page):
            visible = page is self.settings_stack.currentWidget()
            page.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Preferred if visible else QSizePolicy.Policy.Ignored)
        self.settings_stack.updateGeometry()
        self.custom_name.setVisible(service_id == "custom")
        self.custom_name_label.setVisible(service_id == "custom")
        self.api_advanced.setVisible(is_api)
        if service_id == "custom" and hasattr(self, "advanced_toggle"):
            # A custom service needs its Base URL: open the advanced group.
            self.advanced_toggle.setChecked(True)
        if not initial:
            # 原子切换：Base URL / 模型 / 协议必须一次性按新 Provider 的
            # profile 加载。期间屏蔽这些控件自身的信号，避免旧字段的部分
            # 更新（例如把 Google Base URL 残留进 DeepSeek profile）。
            values = resolved_service_values(self._settings_ref, service_id)
            self.base_url.blockSignals(True)
            self.base_url.setText(values["base_url"])
            self.base_url.blockSignals(False)
            self.model.blockSignals(True)
            self.model.setCurrentText(values["model"])
            self.model.blockSignals(False)
            protocol_index = self.protocol.findData(values["protocol"] or "auto")
            if protocol_index >= 0:
                self.protocol.blockSignals(True)
                self.protocol.setCurrentIndex(protocol_index)
                self.protocol.blockSignals(False)
            self._last_key_scope = (provider, values["base_url"])
            self.json_mode.setChecked(values.get('json_mode', True))
            self.structured_output.setChecked(values.get('structured_output', True))
            self.refresh_secret_status()
            self._queue_model_discovery()
        self._refresh_model_retirement_warning(service_id)
        (bind_text(self.model, '默认模型', property='placeholderText') if not is_api else bind_text(self.model, '模型名称', property='placeholderText'))
        (bind_text(self.login_button, '打开官方 Codex 登录') if service_id == 'codex_cli' else (bind_text(self.login_button, '打开 Google 登录') if service_id == 'antigravity' else bind_text(self.login_button, '管理 Grok 登录')))
        self.logout_button.setVisible(service_id == "codex_cli")
        self.install_button.setVisible(not is_api)
        self.update_cli_button.setVisible(service_id == 'grok_account')
        self.diagnostics_details.clear()
        self.diagnostics_toggle.setChecked(False)
        self.json_mode.setEnabled(True)
        self.structured_output.setEnabled(True)
        bind_text(self.structured_output, 'Structured Output')
        bind_text(self.json_mode, 'JSON 答案始终进行本地校验；CLI 外层事件 JSON 与模型答案 JSON 分别校验。', property='toolTip')
        bind_text(self.structured_output, '启用时优先使用已检测支持的原生 JSON Schema；关闭时使用兼容 JSON／本地校验。', property='toolTip')
        bind_text(self.json_capability_status, '结构化能力：尚未检测；模型列表获取不决定 JSON 能力。')
        bind_text(self.cli_status, 'CLI：未检测')
        (bind_text(self.account_status, 'Antigravity CLI Session：未知') if service_id == 'antigravity' else bind_text(self.account_status, '{value0} Session：未知', value0=spec['label']))
        if is_api:
            self.refresh_secret_status()
        else:
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '请先检测 CLI 与登录状态')
        self._refresh_endpoint_hint()

    def _transport_changed(self) -> None:
        self._service_changed()

    def _open_provider_guide(self) -> None:
        from dataclasses import replace
        from .api_setup_dialog import ApiSetupDialog
        window = self.window()
        factory = getattr(window, '_api_setup_host', None)
        if factory is None:
            parent = window.parentWidget() if window is not None else None
            factory = getattr(parent.window() if parent is not None else None, '_api_setup_host', None)
        if factory is None:
            return
        host = replace(factory(), open_text_settings=None)
        service_id = str(self.service.currentData() or 'custom')
        ApiSetupDialog(window, host, kind='text', initial=service_id,
                       show_advanced=service_id in {'custom', 'grok_account', 'codex_cli', 'antigravity'}).exec()

    def refresh_theme_palette(self) -> None:
        theme = _active_theme_definition()
        accent = theme.primary_role if self.stage == "polish" else theme.secondary_role
        self.setStyleSheet(f"""
            QFrame#endpointCard {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
            QFrame#endpointCard QLabel {{ color: {theme.text}; background: transparent; }}
            QFrame#endpointCard QLabel#endpointTitle {{ color: {accent}; font-size: 15px; font-weight: 700; }}
            QFrame#endpointCard QLabel#endpointSectionLabel {{
                color: {theme.text_muted}; font-size: 12px; font-weight: 700;
                padding-top: 4px; border: 0;
            }}
            QFrame#endpointCard QLineEdit, QFrame#endpointCard QComboBox {{
                color: {theme.text}; background: {theme.surface_input}; border: 1px solid {theme.border};
                border-radius: 6px; padding: 6px 8px; selection-background-color: {theme.selected};
            }}
            QFrame#endpointCard QLineEdit:focus, QFrame#endpointCard QComboBox:focus {{ border-color: {theme.accent}; }}
            QFrame#endpointCard QPlainTextEdit#endpointDiagnostics {{
                color: {theme.text}; background: {theme.surface_input}; border: 1px solid {theme.border};
                border-radius: 6px; padding: 6px; font-family: {UI_FONT_STACK}; font-size: 12px;
                selection-background-color: {theme.selected};
            }}
            QFrame#endpointCard QPushButton#endpointSecondary {{
                color: {theme.text}; background: {theme.control_background}; border: 1px solid {theme.border};
                border-radius: 6px; padding: 6px 10px;
            }}
            QFrame#endpointCard QPushButton#endpointSecondary:hover {{ background: {theme.control_hover}; border-color: {theme.accent}; }}
            QFrame#endpointCard QPushButton#endpointPrimary {{
                color: {theme.text_on_accent}; background: {theme.accent}; border: 1px solid {theme.accent};
                border-radius: 6px; padding: 6px 12px; font-weight: 650;
            }}
            QFrame#endpointCard QWidget#endpointApiPage, QFrame#endpointCard QWidget#endpointCliPage,
            QFrame#endpointCard QStackedWidget#endpointSettingsStack {{ background: transparent; border: 0; }}
        """)
        self.title_label.setObjectName("endpointTitle")
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)

    def _current_provider_base(self):
        prov = str(self.provider.currentData() or "custom")
        burl = normalize_base_url(self.base_url.text())
        return prov, burl

    def _refresh_endpoint_hint(self):
        base = normalize_base_url(self.base_url.text())
        protocol = str(self.protocol.currentData() or "auto")
        suffix = "/responses" if protocol == "responses" else "/chat/completions"
        bind_text(self.endpoint_hint, "实际请求：{url}", url=base+suffix) if base else bind_text(self.endpoint_hint, "填写 Base URL，程序会按所选协议补全请求路径。")

    def _on_key_text_changed(self, text: str) -> None:
        # Manual editing (including select-all + delete) never clears the
        # stored secret: typing anything = REPLACE, emptying by hand returns
        # to UNCHANGED. Only the explicit "清除密钥" button requests CLEAR.
        if self._key_state == "clear":
            return
        self._key_state = "replace" if text.strip() else "unchanged"

    def _request_key_clear(self) -> None:
        self._key_state = "clear"
        self.key.clear()
        bind_text(self.key, '将在保存时清除已保存的密钥（环境变量不受影响）', property='placeholderText')
        self.status.setObjectName("statusWarn")
        bind_text(self.status, '已请求清除：点击“保存 AI 配置”生效')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.clear_key_button.setVisible(False)

    def refresh_secret_status(self):
        prov, burl = self._current_provider_base()
        if getattr(self, "_key_state", "unchanged") == "clear":
            return  # keep the "清除已请求" status until save/reload
        existing, source = read_api_key(prov, burl)
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(self.stage)
        (bind_text(self.key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.key, '请输入 API Key', property='placeholderText'))
        self.clear_key_button.setVisible(bool(existing))
        self.status.setObjectName("statusGood" if existing else "statusWarn")
        (bind_text(self.status, credential_storage_notice() if session_credentials_enabled() else '密钥已保存') if existing else bind_text(self.status, '尚未配置密钥'))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _provider_or_url_changed(self):
        prov, burl = self._current_provider_base()
        # Load provider-scoped key for the new (provider, base). Do not overwrite if user has typed something new.
        existing, source = read_api_key(prov, burl)
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(self.stage)
        # If scope changed, update placeholder; if user already typed in this session, keep it.
        scope = (prov, burl)
        if scope != getattr(self, "_last_key_scope", None):
            self._last_key_scope = scope
            # Only reset placeholder text; do not clear an explicitly typed value.
            typed = self.key.text().strip()
            if not typed:
                (bind_text(self.key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.key, '请输入 API Key', property='placeholderText'))
            # If nothing typed, show hint of existing for this provider/url.
            if not typed and existing:
                self.status.setObjectName("statusGood")
                bind_text(self.status, credential_storage_notice() if session_credentials_enabled() else '密钥已保存（此服务商）')
                self.status.style().unpolish(self.status)
                self.status.style().polish(self.status)

    def values(self) -> dict:
        service_id = str(self.service.currentData() or "custom")
        spec = AI_SERVICE_SPECS[service_id]
        return {
            "service": service_id,
            "transport": str(spec["transport"]),
            "provider": str(spec["provider"]),
            "provider_name": self.custom_name.text().strip() if service_id == "custom" else str(spec["label"]),
            "model": self.model.currentText().strip(),
            "base_url": normalize_base_url(self.base_url.text()),
            "key": self.key.text().strip(),
            "key_state": getattr(self, "_key_state", "unchanged"),
            "protocol": str(self.protocol.currentData() or "auto"),
            "json_mode": self.json_mode.isChecked(),
            "structured_output": self.structured_output.isChecked(),
            "stream": False,
        }

    def restore_profile_values(self, values: dict, settings: dict) -> None:
        """Restore one endpoint without intermediate signals or network work."""
        from PySide6.QtCore import QSignalBlocker
        self._invalidate_model_discovery()
        self._discovery_pending = False
        self._settings_ref = settings
        controls = (self.service, self.provider, self.transport, self.model, self.base_url,
                    self.protocol, self.key, self.custom_name, self.json_mode, self.structured_output)
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            index = self.service.findData(values["service"])
            if index < 0:
                raise ValueError("方案中的 AI 服务不可用")
            self.service.setCurrentIndex(index)
            self._service_changed(initial=True)
            self.model.setCurrentText(values["model"])
            self.base_url.setText(values["base_url"])
            self.protocol.setCurrentIndex(max(0, self.protocol.findData(values.get("protocol") or "auto")))
            bind_text(self.custom_name, values.get('provider_name') or '自定义服务')
            self.json_mode.setChecked(values.get("json_mode", True))
            self.structured_output.setChecked(values.get("structured_output", True))
            self.key.clear()
            self._key_state = "unchanged"
            self._last_key_scope = (values["provider"], values["base_url"])
        finally:
            del blockers
        self.refresh_secret_status()
        self._refresh_endpoint_hint()

    def _cli_settings(self) -> dict:
        """Test exactly what Generate will resolve after these edits are saved.

        A bare ``{transport, model}`` dict tested a different resolution path
        than the saved-settings one AI Design uses, so Test could pass on
        Antigravity while Generate left for another transport. Overlay the
        editor selection onto a copy of the live settings and activate the
        selected service in that copy — identical post-save resolution.
        """
        return self._provider_settings()

    def _provider_settings(self) -> dict:
        """Model discovery must resolve the same post-save world as _cli_settings.

        2026-09-04：裸平铺 dict 缺 ``ai_service``/``polish_provider`` 时，
        get_active_service 迁移路径在 group 编辑器（全文断句模型）下回落默认
        grok_account——选 DeepSeek 预设点“刷新模型”却拉到 Grok CLI 的模型列表。
        与连接测试同构：live settings 拷贝 + activate_ai_service 覆盖层。
        """
        values = self.values()
        base = self._settings_ref
        overlay = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
        overlay.setdefault("models", {})
        service_id = str(values.get("service") or "custom")
        if service_id in AI_SERVICE_SPECS:
            activate_ai_service(overlay, service_id, stage=self.stage)
        overlay["models"][f"{self.stage}_transport"] = values["transport"]
        overlay["models"][f"{self.stage}_provider"] = values["provider"]
        overlay["models"][f"{self.stage}_protocol"] = values["protocol"]
        overlay["models"][f"{self.stage}_model"] = values["model"]
        overlay["models"][f"{self.stage}_base_url"] = values["base_url"]
        update_active_profile(overlay, stage=self.stage, base_url=values['base_url'],
                              model=values['model'], protocol=values['protocol'],
                              json_mode=values['json_mode'], structured_output=values['structured_output'])
        # Ephemeral only: persist_ai_configuration never serializes this key.
        overlay["models"][f"{self.stage}_api_key"] = values["key"]
        if overlay.get('switches',{}).get('unified_glm_processing'):
            overlay['models']['group_api_key']=values['key']
            overlay['models']['polish_api_key']=values['key']
        return overlay

    def _model_discovery_identity(self):
        from .model_discovery import identity
        values=self.values()
        key=values['key'] or read_api_key(values['provider'],values['base_url'])[0]
        return identity(values['provider'], values['base_url'], key)+(values['service'],values['protocol'])

    def _invalidate_model_discovery(self, *_):
        self._discovery_epoch = getattr(self, '_discovery_epoch', 0) + 1
        self._model_discovery_timer.stop()
        if self._model_discovery_running():
            self._model_discovery_worker.requestInterruption()
        # Edits invalidate old callbacks immediately; only editingFinished
        # or an explicit refresh initiates network traffic.

    def _model_discovery_done(self, worker):
        if self._model_discovery_worker is worker:
            self._model_discovery_worker=None
            bind_text(self.discover_models_button, '刷新模型')
            self.discover_models_button.setEnabled(True)
            if self._discovery_pending:
                self._discovery_pending=False
                self._queue_model_discovery()
        worker.deleteLater()

    def _queue_model_discovery(self, *_args) -> None:
        if not hasattr(self, "_model_discovery_timer"):
            return
        values = self.values()
        if values["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            if not values["base_url"]:
                return
            stored_key = read_api_key(values["provider"], values["base_url"])[0]
            if not values["key"] and not stored_key:
                return
        self._model_discovery_timer.start()

    def _model_discovery_running(self) -> bool:
        return bool(
            self._model_discovery_worker is not None
            and self._model_discovery_worker.isRunning()
        )

    def discover_models(self, *, refresh: bool = False) -> None:
        if self._model_discovery_running():
            self._discovery_pending=True
            return
        values = self.values()
        if not supports_model_discovery(values.get("service", "custom")):
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '该服务不支持自动获取模型列表；可直接输入模型 ID')
            return
        if values["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            stored_key = read_api_key(values["provider"], values["base_url"])[0]
            if not values["base_url"] or (not values["key"] and not stored_key):
                self.status.setObjectName("statusWarn")
                bind_text(self.status, '填写 Base URL 与 API Key 后可获取模型；也可手动输入模型 ID')
                return
        bind_text(self.discover_models_button, '取消')
        self.status.setObjectName("statusWarn")
        bind_text(self.status, '正在后台获取模型列表…')
        worker = ProviderModelDiscoveryWorker(
            self._provider_settings(),
            self.stage,
            refresh=refresh,
            parent=self,
        )
        self._model_discovery_worker = worker
        scope=self._model_discovery_identity()
        epoch = getattr(self, '_discovery_epoch', 0)
        worker.succeeded.connect(lambda models: self._model_discovery_succeeded(models)
            if epoch==getattr(self, '_discovery_epoch', 0) and scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
        worker.failed.connect(lambda message: self._model_discovery_failed(message)
            if epoch==getattr(self, '_discovery_epoch', 0) and scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
        worker.finished.connect(lambda:self._model_discovery_done(worker))
        worker.start()

    def cancel_model_discovery(self) -> None:
        if not self._model_discovery_running():
            return
        self._model_discovery_worker.requestInterruption()
        self.discover_models_button.setEnabled(False)
        bind_text(self.status, '正在取消模型发现…')

    def _model_discovery_succeeded(self, models: list) -> None:
        current = self.model.currentText().strip()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems([str(item) for item in models])
        if current:
            # 刷新列表绝不悄悄改选择：saved model 仍存在 → 原样保留；
            # 已不存在 → 保留文本但明确提示需要确认（Test 3/4）。
            self.model.setCurrentText(current)
        else:
            self.model.setCurrentIndex(-1)
            self.model.setEditText('')
        self.model.blockSignals(False)
        self._refresh_model_retirement_warning()
        self.discover_models_button.setEnabled(True)
        discovered = [str(item).strip() for item in models]
        if current and discovered and current not in discovered:
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '已发现 {value0} 个模型 · 当前所选不在最新列表中，请确认后保存', value0=len(models))
        else:
            self.status.setObjectName("statusGood")
            bind_text(self.status, '已发现 {value0} 个模型 · 可搜索选择或手动输入', value0=len(models))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _model_discovery_failed(self, message: str) -> None:
        self.discover_models_button.setEnabled(True)
        self.status.setObjectName("statusWarn")
        self.status.setText(str(message))

    def detect_cli(self) -> None:
        service_id = str(self.service.currentData() or "")
        self.detect_cli_button.setEnabled(False)
        bind_text(self.cli_status, 'CLI：检测中…')
        (bind_text(self.account_status, 'Antigravity CLI Session：检测真实请求中…') if service_id == 'antigravity' else bind_text(self.account_status, '{value0} Session：检测中…', value0=str(AI_SERVICE_SPECS[service_id]['label'])))
        self._tester = ProviderConnectionTester(
            self._cli_settings(), self.stage, prompt_test=False, force_refresh=True
        )
        self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._detect_finished))
        self._tester.start()

    def _detect_finished(self, ok: bool, message: str) -> None:
        self.detect_cli_button.setEnabled(True)
        detected_models = tuple(getattr(self._tester, "models", ()) or ())
        if detected_models:
            current_model = self.model.currentText().strip()
            self.model.blockSignals(True)
            self.model.clear()
            self.model.addItems(list(dict.fromkeys(filter(None, (current_model, *detected_models)))))
            self.model.setCurrentText(current_model or detected_models[0])
            self.model.blockSignals(False)
        diagnostics = dict(getattr(self._tester, 'diagnostics', {}) or {})
        self._show_cli_diagnostics(diagnostics, ok=ok, request_test=False)
        installed = bool(diagnostics.get('executable')) if diagnostics else "未安装" not in message and "未检测到" not in message
        self.install_button.setVisible(not installed)
        service_id = str(self.service.currentData() or "")
        prefix = str(AI_SERVICE_SPECS[service_id]["label"]) + " Session"
        if ok and service_id == "codex_cli":
            bind_text(self.login_button, '重新登录或切换账号')
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def copy_provider_diagnostics(self):
        from .provider_diagnostics import redact_diagnostics
        provider=provider_for_stage(self._provider_settings(),self.stage)
        payload=redact_diagnostics({"provider":self.values()["service"],"model":self.model.currentText(),
            "status":self.status.text(),"diagnostics":getattr(self, '_last_cli_diagnostics', {}),
            "trace":provider.invocation_trace()})
        QApplication.clipboard().setText(json.dumps(payload,ensure_ascii=False,indent=2))

    def _show_cli_diagnostics(self, diagnostics, *, ok, request_test):
        from .provider_diagnostics import redact_diagnostics
        diagnostics = redact_diagnostics(diagnostics)
        self._last_cli_diagnostics = diagnostics
        self._show_json_capabilities(diagnostics.get('json_capabilities', {}))
        path = diagnostics.get('executable') or '未检测到'
        version = diagnostics.get('cli_version') or '版本未检测'
        self.cli_status.setText(f'CLI：{version}\n{path}')
        evidence = diagnostics.get('auth_evidence')
        credential = {'model_catalog': '模型目录验证过凭据', 'successful_model_request': '实际请求验证过凭据',
                      'official_auth_error': '官方 CLI 提示未登录'}.get(evidence, '凭据状态未知')
        category = diagnostics.get('category')
        request = ('连接测试通过（中文 JSON）' if ok and request_test else
                   '需更新 CLI；本次请求失败' if category == 'upgrade_required' else
                   '连接测试失败' if request_test else '当前配置真实请求尚未验证')
        tested = diagnostics.get('last_tested_at')
        self.account_status.setText(f'登录/凭据：{credential}\n请求：{request}' + (f' · {tested}' if tested else ''))
        self.update_cli_button.setVisible(str(self.service.currentData()) == 'grok_account')
        self.diagnostics_details.setPlainText(json.dumps(diagnostics, ensure_ascii=False, indent=2))

    def _show_json_capabilities(self, evidence):
        state = evidence.get('state', 'unverified')
        if state == 'verified':
            text = '结构化能力：原生 JSON Schema 已验证；答案同时通过本地校验。'
        elif evidence.get('native_schema'):
            text = '结构化能力：本机 CLI 支持原生 JSON Schema；当前模型尚未通过请求验证。'
        elif state == 'unsupported':
            text = '结构化能力：本机 CLI 未提供原生 Schema；使用兼容 JSON／本地校验。'
        elif state == 'failed':
            text = '结构化能力：检测失败；保留 JSON 选项，可重新检测。'
        else:
            text = '结构化能力：尚未检测；模型列表获取不决定 JSON 能力。'
        bind_text(self.json_capability_status, text)

    def start_cli_update(self):
        settings = self._provider_settings()
        provider = provider_for_stage(settings, self.stage)
        try:
            plan = provider.cli_update_plan()
        except Exception as exc:
            self.status.setText(str(exc))
            return
        target = plan.get('executable') or '未检测到 CLI'
        command = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in plan.get('command', []))
        if not plan.get('supported'):
            QMessageBox.information(self, '查看 CLI 更新方法', f'实际目标：{target}\n\n{plan["message"]}\n\n更新后点击重新检测和测试连接。')
            return
        result = QMessageBox.question(self, '确认更新这份 CLI',
            f'目标路径：{target}\n当前版本：{plan.get("version") or "未检测"}\n动作：{command}\n\n'
            f'{plan["message"]}\n完成后将重新读取路径/版本并执行一次最小普通文本请求。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if result != QMessageBox.StandardButton.Yes:
            return
        self._invalidate_endpoint_tasks()
        self._update_worker = ProviderCLIUpdateWorker(settings, self.stage, plan)
        self._update_worker.finished_status.connect(self._endpoint_callback(self._update_worker, '_update_worker', self._cli_update_finished))
        self.update_cli_button.setEnabled(False)
        self.status.setText('正在更新已确认的 CLI…')
        self._update_worker.start()

    def _cli_update_finished(self, ok, message):
        self.update_cli_button.setEnabled(True)
        self._show_cli_diagnostics(self._update_worker.diagnostics, ok=ok, request_test=True)
        self.status.setObjectName('statusGood' if ok else 'statusWarn')
        self.status.setText(message)

    def start_login(self, _checked=False, *, action="login") -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            self._login_worker.requestInterruption()
            bind_text(self.status, '正在取消官方登录…')
            return
        bind_text(self.login_button, '取消登录')
        self.logout_button.setEnabled(False)
        (bind_text(self.account_status, '正在启动官方登录窗口…') if action == 'login' else bind_text(self.account_status, '正在退出官方 CLI 登录…'))
        self._login_worker = ProviderLoginWorker(self._cli_settings(), self.stage, action=action)
        self._login_worker.finished_status.connect(self._endpoint_callback(self._login_worker, '_login_worker', self._login_finished))
        self._login_worker.login_progress.connect(self._endpoint_callback(self._login_worker, '_login_worker', self._login_progress))
        self._login_worker.start()

    @staticmethod
    def _linkify(message: str) -> str:
        message = html.unescape(str(message or ""))
        match = re.search(r"https?://[^\s\"'<]+", str(message or ""))
        if not match:
            return message
        url = match.group(0)
        head, _, tail = str(message).partition(url)
        return (
            f"{html.escape(head)}<a href=\"{html.escape(url, quote=True)}\">{html.escape(url)}</a>{html.escape(tail)}"
        )

    def _login_progress(self, message: str) -> None:
        text = str(message or "")
        if text.startswith("http"):
            self.status.setTextFormat(Qt.TextFormat.RichText)
            self.status.setObjectName("statusInfo")
            bind_text(self.status, '在浏览器完成登录即可（窗口会自动收尾，无需保持任何外部窗口）：<br>{value0}', value0=self._linkify(text))
        else:
            self.status.setTextFormat(Qt.TextFormat.PlainText)
            self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _login_finished(self, ok: bool, message: str) -> None:
        self.login_button.setEnabled(True)
        service_id=str(self.service.currentData() or "custom")
        label=str(AI_SERVICE_SPECS[service_id]["label"])
        ((bind_text(self.login_button, '重新登录或切换账号') if ok else bind_text(self.login_button, '打开官方 Codex 登录')) if service_id == 'codex_cli' else bind_text(self.login_button, '打开登录'))
        self.logout_button.setEnabled(True)
        bind_text(self.account_status, f'{label}：' + ('登录流程完成；当前配置请求仍需测试' if ok else '登录未完成，请重新检测'))
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setText(html.unescape(str(message)))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if ok:
            self.discover_models(refresh=True)

    def show_install_instructions(self) -> None:
        service_id = str(self.service.currentData() or "")
        name = str(AI_SERVICE_SPECS.get(service_id, {}).get("label") or "CLI")
        QMessageBox.information(
            self,
            tr('安装 {value0}', value0=name),
            tr('当前未由 2ByteASR 自动安装 {value0}。请从该服务的官方发布渠道安装，完成后回到这里点击“检测 CLI”。\n\n2ByteASR 不读取或保存 OAuth token。', value0=name),
        )

    def test_connection(self):
        values = self.values()
        if values["transport"] != AITransport.OPENAI_COMPATIBLE.value:
            if self._tester is not None and self._tester.isRunning():
                self._tester.requestInterruption()
                self.test_button.setEnabled(False)
                bind_text(self.status, '正在取消测试…')
                return
            self._connection_started_at = time.monotonic()
            self.test_button.setEnabled(True)
            bind_text(self.test_button, '取消测试')
            bind_text(self.status, '正在执行最小连接测试…')
            self._tester = ProviderConnectionTester(self._cli_settings(), self.stage, prompt_test=True)
            self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._connection_finished))
            self._tester.start()
            tester = self._tester
            QTimer.singleShot(5000, lambda: self._show_slow_connection_hint(tester))
            return
        prov = str(self.provider.currentData() or "custom")
        burl = values.get("base_url", "")
        # P8C-R3.1: resolve the scoped secret for the current (provider, base).
        # A dead `'read_api_key' in dir()` check (dir() is the LOCAL namespace,
        # so this was always False) made every Test Connection with an empty
        # input field fail with "当前模型缺少 API 密钥" even while the DPAPI
        # store / environment held a working key. Respect the three widget
        # states: REPLACE uses the typed value, CLEAR tests the post-clear
        # reality (store key ignored, environment still applies), UNCHANGED
        # resolves the stored secret.
        key_state = values.get("key_state", "unchanged")
        if values["key"]:
            key = values["key"]
        elif key_state == "clear":
            key = ""
        else:
            prov_key, _ = read_api_key(prov, burl)
            key = prov_key
        if not key and prov in {"bailian", "dashscope"}:
            key = resolve_api_key(self.stage)[0]
        endpoint = {
            **values,
            "api_key": key,
            "url": responses_url(values["base_url"]) if values.get("protocol") == "responses" else chat_completion_url(values["base_url"]),
        }
        try:
            validate_endpoint(endpoint, "当前模型")
        except RuntimeError as exc:
            self.status.setObjectName("statusWarn")
            self.status.setText(str(exc))
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        self.test_button.setEnabled(False)
        bind_text(self.status, '正在测试…')
        self._tester = ProviderConnectionTester(self._provider_settings(), self.stage, prompt_test=True)
        self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._connection_finished))
        self._tester.start()

    def _show_slow_connection_hint(self, tester) -> None:
        if tester is self._tester and tester is not None and tester.isRunning():
            elapsed = max(5, int(time.monotonic() - self._connection_started_at))
            bind_text(self.status, '模型响应较慢，仍在等待… {elapsed} 秒 · 可取消', elapsed=elapsed)

    def _invalidate_endpoint_tasks(self) -> None:
        self.last_connection_ok = None
        self._endpoint_epoch = getattr(self, '_endpoint_epoch', 0) + 1
        for name in ('_tester', '_login_worker', '_update_worker'):
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                # Keep the parentless QThread alive until its native run exits.
                pending = getattr(self, '_retired_endpoint_tasks', set())
                self._retired_endpoint_tasks = pending
                pending.add(worker)
                if hasattr(worker, 'finished'):
                    worker.finished.connect(lambda w=worker, owned=pending: owned.discard(w))
            setattr(self, name, None)
        if hasattr(self, 'test_button'):
            self.test_button.setEnabled(True)
            bind_text(self.test_button, '测试连接')
            self.detect_cli_button.setEnabled(True)
            self.logout_button.setEnabled(True)
            self.update_cli_button.setEnabled(True)

    def _endpoint_callback(self, worker, slot, callback):
        epoch = getattr(self, '_endpoint_epoch', 0)
        identity = self.values()
        def deliver(*args):
            if (epoch == getattr(self, '_endpoint_epoch', 0)
                    and getattr(self, slot, None) is worker and self.values() == identity):
                callback(*args)
        return deliver

    def _connection_finished(self, ok: bool, message: str):
        self.last_connection_ok = bool(ok)
        self.test_button.setEnabled(True)
        bind_text(self.test_button, '测试连接')
        if self.values()['transport'] != AITransport.OPENAI_COMPATIBLE.value:
            self._show_cli_diagnostics(dict(getattr(self._tester, 'diagnostics', {}) or {}), ok=ok, request_test=True)
        if ok:
            if str(self.service.currentData()) == "codex_cli":
                bind_text(self.login_button, '重新登录或切换账号')
            try:
                base = GLOBAL_PROVIDER_REGISTRY.settings()
                saved_service = get_active_service(base) if isinstance(base, dict) else "custom"
                if saved_service != str(self.values().get("service") or "custom"):
                    message = f"{message} · 尚未保存：点击保存后 AI 设计才会使用此 Provider"
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


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
) -> dict:
    """Validate and persist AI form values without requiring a subtitle run."""
    use_ai_grouping = bool(use_ai_grouping)
    enable_ai_polish = bool(enable_ai_polish)
    unified = bool(unified and use_ai_grouping and enable_ai_polish)
    polish = dict(group) if unified else dict(polish)
    group = dict(group)
    polish_key = str(polish.get("key", "") or "").strip()
    group_key = str(group.get("key", "") or "").strip()
    existing_polish_key = read_api_key(
        polish.get("provider", "custom"), polish.get("base_url", "")
    )[0] if enable_ai_polish else ""
    if enable_ai_polish and not existing_polish_key and polish.get("provider") in {"bailian", "dashscope"}:
        existing_polish_key = resolve_api_key("polish")[0]
    existing_group_key = read_api_key(
        group.get("provider", "custom"), group.get("base_url", "")
    )[0] if use_ai_grouping or unified else ""
    if use_ai_grouping and not existing_group_key and group.get("provider") in {"bailian", "dashscope"}:
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
    endpoints = [("字幕校对模型", polish, effective_polish_key)] if enable_ai_polish else []
    if use_ai_grouping:
        endpoints.append(("全文断句模型", group, effective_group_key))
    for label, values, api_key in endpoints:
        if values.get("transport", AITransport.OPENAI_COMPATIBLE.value) == AITransport.OPENAI_COMPATIBLE.value:
            from .llm_config import endpoint_requires_key
            if not api_key and endpoint_requires_key(values):
                missing_keys.append(label)
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
        return {"models": models, "unified": unified, "missing_keys": tuple(missing_keys)}
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
    return {"models": models, "missing_keys": tuple(missing_keys)}


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
    from .speaker_strategy import resolve
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
    if models["firered_asr_backend"] not in {"local", "qwen_aligner", "mlx_qwen_aligner", "whisper_turbo", "paraformer", "off"}:
        raise RuntimeError("字幕时间轴后端选项无效。")
    missing_keys = []
    if models["qwen_asr_backend"] == "api" or models["primary_asr_backend"] == "api":
        from .llm_config import read_asr_api_key

        existing_key = read_asr_api_key(
            models["qwen_asr_api_provider"], models["qwen_asr_api_url"]
        )[0]
        effective_key = str(qwen_key or "").strip() or existing_key
        from .llm_config import read_spark_credentials
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


class ConnectionTester(QThread):
    finished_status = Signal(bool, str)

    def __init__(self, endpoint: dict):
        super().__init__()
        self.endpoint = endpoint

    def run(self):
        try:
            run_llm_json_self_test(self.endpoint)
            self.finished_status.emit(True, "连接正常 · JSON 结构化输出正常")
        except Exception as exc:
            compact = " ".join(str(exc).split())[:90]
            self.finished_status.emit(False, f"连接失败：{compact}")


class ProviderConnectionTester(QThread):
    finished_status = Signal(bool, str)

    def __init__(
        self,
        settings: dict,
        stage: str,
        *,
        prompt_test: bool = False,
        force_refresh: bool = False,
    ):
        super().__init__()
        self.settings = settings
        self.stage = stage
        self.prompt_test = bool(prompt_test)
        self.force_refresh = bool(force_refresh)
        self.models: tuple[str, ...] = ()
        self.timings: dict[str, float | bool] = {}
        self.diagnostics: dict = {}

    def run(self):
        started = time.monotonic()
        provider = None
        import datetime
        def finish(ok, message):
            measured = getattr(provider, 'cli_diagnostics', lambda: {})() if provider is not None else {}
            explicit = {key: self.diagnostics[key] for key in ('category', 'request_succeeded') if key in self.diagnostics}
            self.diagnostics = {**self.diagnostics, **measured, **explicit}
            self.diagnostics['last_tested_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.finished_status.emit(ok, message)
        try:
            provider = provider_for_stage(self.settings, self.stage)
            validate_started = time.monotonic()
            if self.prompt_test:
                schema = {'type': 'object', 'properties': {
                    'ok': {'type': 'boolean', 'const': True},
                    'text': {'type': 'string', 'const': '兔白字幕'}},
                    'required': ['ok', 'text'], 'additionalProperties': False}
                answer = provider.structured_complete([
                    {'role': 'user', 'content': '请只返回 JSON：{"ok":true,"text":"兔白字幕"}。'}],
                    schema, max_tokens=80, temperature=0, timeout=45,
                    cancel_check=self.isInterruptionRequested, stage='connection_test',
                    operation_kind='polish')
                from jsonschema import Draft202012Validator
                Draft202012Validator(schema).validate(answer)
                if self.isInterruptionRequested():
                    finish(False, '连接测试已取消')
                    return
                self.timings = dict(getattr(provider, 'last_timings', {}) or {})
                self.timings['total_seconds'] = time.monotonic() - started
                self.diagnostics.update(request_succeeded=True, category='',
                    auth_evidence='successful_model_request',
                    json_capabilities=provider.json_capabilities())
                mode = provider.structured_output_mode()
                label = '原生 JSON Schema＋本地校验' if mode == 'STRICT_JSON_SCHEMA' else '兼容 JSON／本地校验'
                finish(True, tr('连接测试通过 · 中文 JSON 字段正确 · {value0} · {value1}s',
                    value0=label, value1=f'{self.timings["total_seconds"]:.2f}'))
                return
            # 45s: an Antigravity cold start alone costs 3-10s per CLI call and
            # the readiness probe rides on top; 20s reported healthy sessions
            # as "未登录或不可调用" under load.
            status = provider.validate(
                timeout=45.0,
                cancel_check=self.isInterruptionRequested,
                use_cache=not self.force_refresh,
            )
            self.timings = dict(getattr(provider, "last_timings", {}) or {})
            self.timings["validation_seconds"] = time.monotonic() - validate_started
            self.models = tuple(status.models)
            self.diagnostics = dict(getattr(status, 'diagnostics', {}) or {})
            self.diagnostics['json_capabilities'] = provider.json_capabilities(
                probe=True, cancel_check=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                finish(False, "连接测试已取消")
                return
            measured_readiness = self.timings.get("readiness_request_seconds")
            if measured_readiness is not None and not self.timings.get("cache_hit"):
                self.timings["response_seconds"] = measured_readiness
            self.timings["total_seconds"] = time.monotonic() - started
            cache_note = "缓存状态" if self.timings.get("cache_hit") else "实时检测"
            timing = f"{cache_note} {float(self.timings['validation_seconds']):.2f}s"
            if "response_seconds" in self.timings:
                timing += f" · 模型响应 {float(self.timings['response_seconds']):.2f}s"
            timing += f" · 总计 {float(self.timings['total_seconds']):.2f}s"
            finish(
                bool(status.available and status.authenticated),
                f"{status.message} · {timing}",
            )
        except Exception as exc:
            self.diagnostics['category'] = getattr(exc, 'category', 'provider_error')
            self.diagnostics['request_succeeded'] = False if self.prompt_test else None
            compact = " ".join(str(exc).split())[:120]
            if self.isInterruptionRequested() or "取消" in compact:
                finish(False, "连接测试已取消")
            else:
                elapsed = time.monotonic() - started
                finish(False, f"{str(exc) if getattr(exc, 'category', '') == 'upgrade_required' else compact} · {elapsed:.2f}s")
        finally:
            measured = getattr(provider, 'cli_diagnostics', lambda: {})() if provider is not None else {}
            explicit = {key: self.diagnostics[key] for key in ('category', 'request_succeeded') if key in self.diagnostics}
            self.diagnostics = {**self.diagnostics, **measured, **explicit}
            self.diagnostics['last_tested_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()


class ProviderCLIUpdateWorker(QThread):
    finished_status = Signal(bool, str)

    def __init__(self, settings, stage, plan):
        super().__init__()
        self.settings = copy.deepcopy(settings)
        self.stage = stage
        self.plan = copy.deepcopy(plan)
        self.diagnostics = {}

    def run(self):
        provider = provider_for_stage(self.settings, self.stage)
        try:
            status = provider.update_cli(self.plan, user_confirmed=True, cancel_check=self.isInterruptionRequested)
            self.diagnostics = dict(status.diagnostics)
            self.finished_status.emit(status.request_succeeded is True, status.message)
        except Exception as exc:
            from .provider_diagnostics import redact_diagnostics
            self.diagnostics = provider.cli_diagnostics()
            self.diagnostics.update(category=getattr(exc, 'category', 'cli_update_failed'), request_succeeded=False)
            self.finished_status.emit(False, redact_diagnostics(str(exc)))


class ProviderLoginWorker(QThread):
    finished_status = Signal(bool, str)
    login_progress = Signal(str)

    def __init__(self, settings: dict, stage: str, *, action="login"):
        super().__init__()
        self.settings = settings
        self.stage = stage
        self.action = action

    def run(self):
        try:
            provider = provider_for_stage(self.settings, self.stage)
            login = getattr(provider, "login", None)
            if not callable(login):
                self.finished_status.emit(False, "当前服务不支持 OAuth CLI 登录")
                return

            def emit_progress(message: str) -> None:
                self.login_progress.emit(str(message))

            if self.action == "logout":
                status = provider.logout(cancel_check=self.isInterruptionRequested)
            else:
                status = login(timeout=300.0, on_progress=emit_progress, cancel_check=self.isInterruptionRequested,user_initiated=True)
            self.finished_status.emit(bool(status.available and status.authenticated), status.message)
        except Exception as exc:
            from .provider_diagnostics import redact_diagnostics
            compact = redact_diagnostics(" ".join(str(exc).split())[:300])
            self.finished_status.emit(False, compact)


class ProviderModelDiscoveryWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, settings: dict, stage: str, *, refresh: bool = False, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.stage = stage
        self.refresh = bool(refresh)

    def run(self):
        try:
            provider = provider_for_stage(self.settings, self.stage)
            models = provider.discover_models(
                timeout=20.0,
                cancel_check=self.isInterruptionRequested,
                refresh=self.refresh,
            )
            if self.isInterruptionRequested():
                self.failed.emit("模型发现已取消；可继续手动输入模型 ID")
                return
            if not models:
                self.failed.emit("该 Provider 未返回模型列表，可手动输入模型 ID")
                return
            self.succeeded.emit(list(models))
        except Exception as exc:
            compact = " ".join(str(exc).split())[:220]
            if self.isInterruptionRequested() or "取消" in compact:
                compact = "模型发现已取消；可继续手动输入模型 ID"
            elif "手动输入" not in compact:
                compact += "；可继续手动输入模型 ID"
            self.failed.emit(compact)


class AsrModelsFetchWorker(QThread):
    """Lightweight worker to fetch /v1/models without blocking the UI thread."""
    succeeded = Signal(list)  # list[str]
    failed = Signal(str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        try:
            models = fetch_openai_compatible_models(self.base_url, self.api_key)
            self.succeeded.emit(models)
        except Exception as exc:
            self.failed.emit(str(exc))


class TermSearchWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, legacy, endpoint: dict, game_name: str, parent=None, content_type="game"):
        super().__init__(parent)
        self.legacy = legacy
        self.endpoint = dict(endpoint)
        self.game_name = str(game_name)
        self.content_type = str(content_type)

    def run(self):
        try:
            terms = request_ai_game_terms(
                self.endpoint,
                self.game_name,
                content_type=self.content_type,
            )
            self.completed.emit(self.game_name, terms)
        except Exception as exc:  # noqa: BLE001 - thread must report a useful UI error
            self.failed.emit(self.game_name, " ".join(str(exc).split())[:240])


class UpdateCheckWorker(QThread):
    """Fetch and verify the signed update manifest off the GUI thread."""

    result_ready = Signal(object)
    failed = Signal(str)
    skipped = Signal()

    def __init__(self, parent=None, *, automatic: bool = False):
        super().__init__(parent)
        self.automatic = automatic

    def run(self):
        try:
            if self.automatic and not automatic_check_due():
                self.skipped.emit()
                return
            self.result_ready.emit(check_for_update(use_cache=not self.automatic))
        except Exception as exc:  # noqa: BLE001 - UI must report network failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateDownloadWorker(QThread):
    """Download, verify and stage only the components this update changes."""

    progress_changed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, check, parent=None):
        super().__init__(parent)
        self.check = check
        self.cancel_event = threading.Event()

    def run(self):
        try:
            prepared = prepare_update(
                self.check,
                progress=lambda _name, done, total: self.progress_changed.emit(int(done), int(total)),
                cancel=self.cancel_event,
            )
            self.completed.emit(prepared)
        except UpdateCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - UI must report mirror/checksum failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateOfferDialog(QDialog):
    """Current/new version, release notes and the real download size."""

    def __init__(self, check, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(tr('发现新版本'))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        manifest, plan = check.manifest, check.plan
        heading = QLabel(tr('兔白字幕 {value0}（当前 {value1}）', value0=check.latest_version,
                            value1=check.current_version))
        heading.setObjectName('sectionTitle')
        layout.addWidget(heading)
        notes = manifest.note_for(current_language()) if manifest else ''
        if notes:
            layout.addWidget(QLabel(tr('主要变更')))
            box = QPlainTextEdit(notes)
            box.setReadOnly(True)
            box.setMaximumHeight(170)
            layout.addWidget(box)
        lines = []
        if plan is not None and plan.mode == 'components':
            lines.append(tr('本次需要下载：{value0}', value0=format_bytes(plan.download_bytes)))
            for action in plan.downloads:
                cached = '' if action.download_bytes else tr('（已下载过，直接使用）')
                lines.append('  · ' + tr('{value0}：{value1}', value0=tr(action.label),
                                         value1=format_bytes(action.archive_bytes)) + cached)
            if plan.reused:
                lines.append(tr('沿用、不下载：{value0}', value0='、'.join(tr(a.label) for a in plan.reused)))
        elif plan is not None:
            lines.append(tr('需要用完整安装包更新（{value0}）。', value0=format_bytes(plan.setup_bytes)))
            if plan.fallback_reason:
                lines.append(tr('原因：{value0}', value0=plan.fallback_reason))
            lines.append(tr('安装包会保留设置、词库、工程、模型和运行环境，覆盖安装即可，不要先卸载。'))
        if plan is not None:
            if plan.environment_changes:
                lines.append(tr('运行环境：{value0} 的需求有变化，用到时程序会提示补齐。',
                                value0='、'.join(plan.environment_changes)))
            else:
                lines.append(tr('运行环境：沿用，不需要重新下载。'))
            if plan.model_changes:
                lines.append(tr('模型：{value0} 有新版本，只有用到该模型时才需要下载。',
                                value0='、'.join(plan.model_changes)))
            else:
                lines.append(tr('模型：沿用，不需要重新下载。'))
        detail = QLabel('\n'.join(lines))
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail)
        buttons = QHBoxLayout()
        page = QPushButton(tr('打开发布页'))
        page.clicked.connect(lambda: self._finish('page'))
        later = QPushButton(tr('稍后'))
        later.clicked.connect(self.reject)
        if plan is not None and plan.mode == 'components':
            primary = QPushButton(tr('下载并准备更新'))
            primary.clicked.connect(lambda: self._finish('download'))
        else:
            primary = QPushButton(tr('下载安装包'))
            primary.clicked.connect(lambda: self._finish('setup'))
        primary.setObjectName('primary')
        primary.setDefault(True)
        buttons.addWidget(page)
        buttons.addStretch(1)
        buttons.addWidget(later)
        buttons.addWidget(primary)
        layout.addLayout(buttons)

    def _finish(self, choice):
        self.choice = choice
        self.accept()

class PipelineWorker(QThread):
    event_received = Signal(object)
    console_received = Signal(str, str)
    result_ready = Signal(object)
    unexpected_error = Signal(str)

    def __init__(self, media_paths, options, token, legacy, pipeline, startup_self_test):
        super().__init__()
        self.media_paths = list(media_paths)
        self.options = options
        self.token = token
        self.legacy = legacy
        self.pipeline = pipeline
        self.startup_self_test = startup_self_test

    def run(self):
        stdout_stream = SignalTextStream(self.console_received, "stdout", sys.stdout)
        stderr_stream = SignalTextStream(self.console_received, "stderr", sys.stderr)
        try:
            with redirect_stdout(stdout_stream), redirect_stderr(stderr_stream):
                startup_self_test = self.startup_self_test
                if startup_self_test is None:
                    print("[后台自测] 首次开始任务，正在检查字幕护栏……")
                    startup_self_test = self.legacy.run_startup_self_test()
                    print(
                        f"[后台自测通过] {startup_self_test['id']}："
                        f"{startup_self_test['checks']} 项关键护栏正常"
                    )
                result = run_media_queue(
                    self.media_paths,
                    self.options,
                    event_sink=self.event_received.emit,
                    cancel_token=self.token,
                    _legacy=self.legacy,
                    _pipeline=self.pipeline,
                    _startup_self_test=startup_self_test,
                )
            self.result_ready.emit(result)
        except BaseException as exc:
            self.unexpected_error.emit(" ".join(str(exc).split()) or exc.__class__.__name__)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()


class PromptDialog(SpringDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        bind_text(self, '项目内置提示词', property='windowTitle')
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            "字幕校对提示词（项目内置，只读）\n\n"
            "模型会收到 MOSS 主稿、FireRed/Qwen3-ASR 独立证据、项目背景、术语候选和严格安全规则；"
            "只能返回结构化修正，不允许自由改写原话。\n\n"
            "全文断句提示词（项目内置，只读）\n\n"
            "模型只能在已经校对的原文中插入字幕边界；不得增删改字，必须保留硬边界、完整词、"
            "说话人切换与真实停顿。更换服务商或模型不会移除这些提示词。"
        )
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_ui_language(self)


class _CudaProbeRelay(QObject):
    """Carries the background CUDA probe result to the GUI thread."""

    finished = Signal(object)


class GuidedSetupDialog(SpringDialog):
    """First-run model-combination chooser. Nothing is downloaded implicitly."""

    cuda_probe_finished = Signal(object)

    PRESETS = {
        "quality": ("moss", "local", "local"),
        "light": ("sensevoice", "off", "off"),
        "online": ("api", "off", "off"),
        # Cloud text + local word times; the aligner runs on the CPU without CUDA.
        "online_align": ("api", "qwen_aligner", "off"),
        "custom": ("none", "off", "off"),
    }
    SIZES = {
        "mlx_qwen3_asr": 1.0,
        "mlx_qwen3_asr_1_7b": 2.5,
        "mlx_qwen_aligner": 1.3,
        "moss": 1.7,
        "firered": 4.4,
        "qwen_local": 4.7,
        "whisper_turbo": 1.6,
        "sensevoice": 0.9,
        "paraformer": 1.0,
        "funasr_nano": 2.4,
        "local_timeline": 4.4,
        "qwen_aligner": 1.8,
        "local_review": 4.7,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open_workshop = False
        self.auto_download = False
        self._applying_preset = False
        self._cuda_status = None
        self._cuda_probe_started = False
        self.cuda_probe_finished.connect(self._cuda_probe_ready)
        # Presets follow this computer (2026-10-13): Apple Silicon gets the MLX
        # plan instead of the CUDA one; an Intel Mac has no local plan.
        from .mlx_backend import platform_supported
        self._apple_silicon = platform_supported()
        self._intel_mac = sys.platform == "darwin" and not self._apple_silicon
        self.PRESETS = dict(type(self).PRESETS)
        if self._apple_silicon:
            self.PRESETS["apple_local"] = ("mlx_qwen3_asr", "mlx_qwen_aligner", "off")
            self.PRESETS["online_align"] = ("api", "mlx_qwen_aligner", "off")
        bind_text(self, '首次使用设置 - 2ByteASR', property='windowTitle')
        self.setMinimumSize(760, 610)
        self.resize(820, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("先选择一套字幕识别组合")
        title.setStyleSheet("font-size: 21px; font-weight: 700;")
        title_box.addWidget(title)
        hint = QLabel("随时可以在模型工坊替换。这里不会偷偷下载任何模型。")
        hint.setObjectName("muted")
        title_box.addWidget(hint)
        header.addLayout(title_box, 1)
        self.lang_combo = FramelessPopupCombo()
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.addItem("繁體中文", "zh-Hant")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("日本語", "ja")
        self.lang_combo.addItem("한국어", "ko")
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(current_language())))
        self.lang_combo.currentIndexChanged.connect(self._change_lang)
        header.addWidget(self.lang_combo)
        layout.addLayout(header)

        preset_heading = QLabel("① 先选择一种使用方式")
        preset_heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(preset_heading)
        preset_hint = QLabel("选中的方案会用绿色边框标出；下方仍可逐项调整模型。")
        preset_hint.setObjectName("muted")
        layout.addWidget(preset_hint)

        preset_row = QGridLayout()
        preset_row.setSpacing(10)
        self.preset_group = QButtonGroup(self)
        online_align_note = "上传音频；本机补字级时间"
        preset_copy = (
            ("quality", "质量优先", "MOSS + FireRed + Qwen"),
            ("light", "快速轻量", "CPU 友好，小体积"),
            ("online", "在线疾速", "免下载，需要 API Key"),
            ("online_align", "云端 + 本地对齐", online_align_note),
            ("custom", "稍后决定", "先看界面，不下载"),
        )
        if self._apple_silicon:
            preset_copy = (("apple_local", "Mac 本地识别", "M 系列芯片，不上传音频"),) + preset_copy[1:]
        elif self._intel_mac:
            # No PyTorch or MLX build exists for Intel Macs: cloud only.
            preset_copy = tuple(row for row in preset_copy if row[0] in {"online", "custom"})
        columns = 3 if len(preset_copy) > 4 else max(1, len(preset_copy))
        for index, (key, label, note) in enumerate(preset_copy):
            button = QPushButton(f"{label}\n{note}")
            button.setCheckable(True)
            button.setMinimumHeight(98)
            button.setProperty("preset", key)
            button.setObjectName("presetCard")
            # Equal columns; every note fits at the dialog's minimum width.
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.preset_group.addButton(button, index)
            preset_row.addWidget(button, index // columns, index % columns)
        for column in range(columns):
            preset_row.setColumnStretch(column, 1)
        self.preset_group.buttonClicked.connect(self._preset_clicked)
        layout.addLayout(preset_row)

        panel = QFrame()
        panel.setObjectName("surface")
        form = QFormLayout(panel)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        self.primary_combo = FramelessPopupCombo()
        for label, value in (
            ("MOSS（推荐，长音频与说话人区分）", "moss"),
            ("FireRedASR2-AED（中文与方言）", "firered"),
            ("Qwen3-ASR 1.7B 本地", "qwen_local"),
            ("FireRedASR2-LLM 本地", "firered_llm"),
            ("Whisper large-v3-turbo", "whisper_turbo"),
            ("SenseVoice Small（CPU 友好）", "sensevoice"),
            ("Paraformer（中文快速）", "paraformer"),
            ("Fun-ASR Nano（中文与方言）", "funasr_nano"),
            *((("Qwen3-ASR 0.6B（Apple Silicon · MLX）", "mlx_qwen3_asr"),
               ("Qwen3-ASR 1.7B（Apple Silicon · MLX）", "mlx_qwen3_asr_1_7b")) if self._apple_silicon else ()),
            ("在线 ASR API", "api"),
            ("尚未选择", "none"),
        ):
            self.primary_combo.addItem(label, value)
        self.timeline_combo = FramelessPopupCombo()
        for label, value in (
            ("FireRed 字幕时间轴（字级，推荐）", "local"),
            ("Qwen3 ForcedAligner 字幕时间轴", "qwen_aligner"),
            ("Whisper 字幕时间轴（短块级）", "whisper_turbo"),
            ("Paraformer 字幕时间轴", "paraformer"),
            *((("Qwen3 ForcedAligner 字幕时间轴（Apple Silicon · MLX）", "mlx_qwen_aligner"),)
              if self._apple_silicon else ()),
            ("不生成字幕时间轴（仅 TXT）", "off"),
        ):
            self.timeline_combo.addItem(label, value)
        self.review_combo = FramelessPopupCombo()
        for label, value in (
            ("Qwen3-ASR 本地复核（更准确）", "local"),
            ("FireRedASR2-LLM 本地复核", "firered_llm"),
            ("在线 ASR API 复核", "api"),
            ("Whisper 本地复核", "whisper_turbo"),
            ("SenseVoice 本地复核", "sensevoice"),
            ("Fun-ASR Nano 本地复核", "funasr_nano"),
            ("不使用独立文字复核", "off"),
        ):
            self.review_combo.addItem(label, value)
        form.addRow("主力转写", self.primary_combo)
        form.addRow("字幕时间轴", self.timeline_combo)
        form.addRow("文字复核", self.review_combo)
        layout.addWidget(panel)

        self.combo_summary = QLabel()
        self.combo_summary.setWordWrap(True)
        self.combo_summary.setObjectName("muted")
        layout.addWidget(self.combo_summary)
        self.gpu_info = QLabel()
        self.gpu_info.setWordWrap(True)
        layout.addWidget(self.gpu_info)
        for combo in (self.primary_combo, self.timeline_combo, self.review_combo):
            combo.currentIndexChanged.connect(self._selection_changed)

        layout.addStretch(1)
        actions = QHBoxLayout()
        reminder = QLabel("模型可断点续传，缺少时会在开始任务前明确提示。")
        reminder.setObjectName("muted")
        actions.addWidget(reminder, 1)
        browse = AnimatedButton("只保存，暂不下载")
        browse.setObjectName("outline")
        browse.clicked.connect(self._accept_workshop)
        actions.addWidget(browse)
        self.install_button = AnimatedButton("确认组合并一键安装")
        start = self.install_button
        start.setObjectName("primary")
        start.clicked.connect(self._accept_install)
        actions.addWidget(start)
        layout.addLayout(actions)

        self.preset_group.button(0).setChecked(True)
        self._apply_preset(str(self.preset_group.button(0).property("preset")))
        self._start_cuda_probe()

    def _set_combo(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _preset_clicked(self, button):
        self._apply_preset(str(button.property("preset")))

    def _apply_preset(self, key):
        if self._applying_preset:
            return
        self._applying_preset = True
        try:
            primary, timeline, review = self.PRESETS[key]
            blockers = [
                QSignalBlocker(self.primary_combo),
                QSignalBlocker(self.timeline_combo),
                QSignalBlocker(self.review_combo),
            ]
            self._set_combo(self.primary_combo, primary)
            self._set_combo(self.timeline_combo, timeline)
            self._set_combo(self.review_combo, review)
            del blockers
            self._selection_changed()
        finally:
            self._applying_preset = False

    def _start_cuda_probe(self):
        if self._cuda_probe_started:
            return
        self._cuda_probe_started = True

        # The thread holds only a child relay, never the dialog: if the dialog
        # is closed before the probe ends, its last reference must not be
        # dropped (and the widget destroyed) on this thread (2026-10-14,
        # 0xC0000374 at teardown). A deleted relay just refuses the emit.
        relay = _CudaProbeRelay(self)
        relay.finished.connect(self.cuda_probe_finished)

        def probe():
            try:
                status = detect_cuda_runtime()
            except Exception:
                status = None
            try:
                relay.finished.emit(status)
            except RuntimeError:
                pass

        threading.Thread(target=probe, name="2ByteASR-CUDA-probe", daemon=True).start()

    def _cuda_probe_ready(self, status):
        self._cuda_status = status
        self._selection_changed()

    def _selection_changed(self, *_args):
        primary = str(self.primary_combo.currentData())
        timeline = str(self.timeline_combo.currentData())
        review = str(self.review_combo.currentData())
        selected_tuple = (primary, timeline, review)
        matched_preset = next(
            (key for key, values in self.PRESETS.items() if values == selected_tuple),
            None,
        )
        self.preset_group.setExclusive(False)
        for button in self.preset_group.buttons():
            button.setChecked(button.property("preset") == matched_preset)
        self.preset_group.setExclusive(True)
        size = self.estimate_size(primary, timeline, review)
        notes = []
        if primary not in {"moss", "none", "api"}:
            notes.append("非 MOSS 主力当前按单说话人输出")
        if primary in {"mlx_qwen3_asr", "mlx_qwen3_asr_1_7b"}:
            notes.append("只按语音段给文字，字词时间由对齐模型补上")
        if primary == "api" and timeline == "off":
            notes.append("时间精度取决于所选云端服务（有的只有句段时间）")
        if primary == "api" or review == "api":
            notes.append("需要在“申请与设置 API”里填写 API Key，识别时会上传音频")
        if primary == "none":
            notes.append("运行字幕前必须在模型工坊选择主力模型")
        if primary == "none":
            bind_text(self.install_button, '保存并打开模型工坊')
        elif primary == "api":
            bind_text(self.install_button, '保存并配置在线模型')
        else:
            bind_text(self.install_button, '确认组合并一键安装')
        bind_text(self.combo_summary, '预计模型下载约 {value0:.1f} GB。{value1}', value0=size, value1='；'.join(notes) if notes else tr('推荐用于中文长视频与多人内容。'))
        from twobyteasr.hardware import selected_cuda_components

        settings = {
            "models": {
                "primary_asr_backend": primary,
                "firered_asr_backend": timeline,
                "qwen_asr_backend": review,
            }
        }
        required = selected_cuda_components(settings)
        if not required:
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, '这套组合不强制要求 NVIDIA CUDA，可在 CPU 或在线模式下开始。')
        elif self._cuda_status is None:
            self.gpu_info.setObjectName("muted")
            bind_text(self.gpu_info, '正在后台检查 CUDA；需要 CUDA 的组件：{value0}。选择组合时无需等待检查完成。', value0='、'.join(required))
        elif self._cuda_status.ready:
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, 'CUDA 已就绪：{value0}。需要 CUDA 的组件：{value1}', value0=self._cuda_status.gpu_name, value1='、'.join(required))
        elif getattr(self._cuda_status, "code", "") == "torch_missing" and self._cuda_status.gpu_name:
            # A fresh install has no PyTorch yet; one-click install brings the CUDA build.
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, '已检测到 NVIDIA 显卡：{value0}。一键安装会同时装好 CUDA 版 PyTorch。需要 CUDA 的组件：{value1}', value0=self._cuda_status.gpu_name, value1='、'.join(required))
        elif getattr(self._cuda_status, "code", "") == "torch_missing":
            self.gpu_info.setObjectName("statusBad")
            bind_text(self.gpu_info, '未检测到 NVIDIA 显卡或驱动，{value0} 需要 NVIDIA CUDA。可换成轻量/在线组合，或安装/更新 NVIDIA 显卡驱动后再安装。', value0='、'.join(required))
        else:
            self.gpu_info.setObjectName("statusBad")
            bind_text(self.gpu_info, '当前设备还不能运行：{value0}。可换成轻量/在线组合，或修复 NVIDIA 驱动与 PyTorch。', value0='、'.join(required))
        self.gpu_info.style().unpolish(self.gpu_info)
        self.gpu_info.style().polish(self.gpu_info)

    @classmethod
    def estimate_size(cls, primary, timeline, review) -> float:
        """Approximate download in GB for one combination (shared with the quick chooser)."""
        size = cls.SIZES.get(primary, 0.0)
        if timeline == "local" and primary != "firered":
            size += cls.SIZES["local_timeline"]
        elif timeline in {"qwen_aligner", "mlx_qwen_aligner"}:
            size += cls.SIZES[timeline]
        elif timeline == "whisper_turbo" and primary != "whisper_turbo":
            size += cls.SIZES["whisper_turbo"]
        elif timeline == "paraformer" and primary != "paraformer":
            size += cls.SIZES["paraformer"]
        if review == "local" and primary != "qwen_local":
            size += cls.SIZES["local_review"]
        elif review not in {"off", "api", "local"} and review != primary:
            size += cls.SIZES.get(review, 0.0)
        return size

    def selected_backends(self):
        return (
            str(self.primary_combo.currentData()),
            str(self.timeline_combo.currentData()),
            str(self.review_combo.currentData()),
        )

    def selected_download_keys(self):
        return self.download_keys_for(*self.selected_backends())

    @staticmethod
    def download_keys_for(primary, timeline, review):
        primary_keys = {
            "moss": "moss",
            "firered": "firered_aed",
            "qwen_local": "qwen_asr",
            "whisper_turbo": "whisper_turbo",
            "sensevoice": "sensevoice",
            "paraformer": "paraformer",
            "funasr_nano": "funasr_nano",
            "glm_asr_nano": "glm_asr_nano",
            "canary_qwen": "canary_qwen",
            "mlx_qwen3_asr": "mlx_qwen3_asr_0_6b",
            "mlx_qwen3_asr_1_7b": "mlx_qwen3_asr_1_7b",
        }
        timeline_keys = {
            "local": "firered_aed",
            "qwen_aligner": "qwen_aligner",
            "mlx_qwen_aligner": "mlx_qwen_aligner",
            "whisper_turbo": "whisper_turbo",
            "paraformer": "paraformer",
        }
        review_keys = {
            "local": "qwen_asr",
            "whisper_turbo": "whisper_turbo",
            "sensevoice": "sensevoice",
            "funasr_nano": "funasr_nano",
        }
        return tuple(
            dict.fromkeys(
                key
                for key in (
                    primary_keys.get(primary),
                    timeline_keys.get(timeline),
                    review_keys.get(review),
                )
                if key
            )
        )

    def _accept_install(self):
        self.open_workshop = True
        self.auto_download = True
        self.accept()

    def _accept_workshop(self):
        self.open_workshop = True
        self.auto_download = False
        self.accept()

    def _change_lang(self, index):
        code = self.lang_combo.itemData(index) or "zh"
        save_language(code)


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


class DropOverlay(QFrame):
    """Full-window drag target that dims the workbench without stealing drops."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 64, 64, 64)
        layout.addStretch(1)
        self.target = QFrame(self)
        self.target.setObjectName("dropTarget")
        self.target.setMinimumSize(420, 220)
        self.target.setMaximumSize(680, 320)
        target_layout = QVBoxLayout(self.target)
        target_layout.setContentsMargins(36, 30, 36, 30)
        target_layout.addStretch(1)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.icon)
        target_layout.addSpacing(12)
        self.title = QLabel("把文件放入这里")
        self.title.setObjectName("dropOverlayTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.title)
        self.hint = QLabel("松开鼠标即可添加视频或音频 · 支持多选")
        self.hint.setObjectName("dropOverlayHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.hint)
        target_layout.addStretch(1)
        layout.addWidget(self.target, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finish_animation)
        self._requested_visible = False
        self.refresh_theme_palette()
        self.hide()

    def refresh_theme_palette(self):
        theme = theme_definition(theme_key())
        self.icon.setPixmap(_icon("fa5s.file-upload", theme.accent).pixmap(QSize(82, 82)))
        # A light theme scrim dims the page without covering it; the drop card
        # itself carries the themed surface and accent border from APP_QSS.
        self.setStyleSheet(
            f"QFrame#dropOverlay {{ background: {theme.overlay_scrim}; border: 0; }}"
        )

    def set_file_count(self, count: int):
        (bind_text(self.hint, '松开鼠标即可放入 {value0} 个可用文件', value0=count) if count > 1 else bind_text(self.hint, '松开鼠标即可添加这个视频或音频'))

    def set_active(self, active: bool):
        self._requested_visible = bool(active)
        self.animation.stop()
        if active:
            self.show()
            self.raise_()
            start = max(0.0, float(self.opacity.opacity()))
            self.animation.setDuration(150)
            self.animation.setStartValue(start)
            self.animation.setEndValue(1.0)
        else:
            self.animation.setDuration(105)
            self.animation.setStartValue(float(self.opacity.opacity()))
            self.animation.setEndValue(0.0)
        self.animation.start()

    def _finish_animation(self):
        if not self._requested_visible:
            self.hide()


class _ModalBackdrop(QFrame):
    """Lightweight backdrop whose paint alpha can change without restyling Qt."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._alpha = 0.0
        self.setObjectName("modalBackdrop")
        self.setAutoFillBackground(False)

    @property
    def alpha(self) -> float:
        return self._alpha

    def set_alpha(self, value) -> None:
        alpha = max(0.0, min(1.0, float(value)))
        if abs(alpha - self._alpha) < 0.001:
            return
        self._alpha = alpha
        self.update()

    def paintEvent(self, event):
        if self._alpha <= 0.0:
            return
        color = QColor(_active_theme_definition().app_background)
        color.setAlphaF(self._alpha)
        painter = QPainter(self)
        painter.fillRect(event.rect(), color)


class ModalHost(QFrame):
    """MainWindow-internal overlay for app popups.

    Eliminates new top-level native windows (SpringDialog / QDialog) for:
    Model Picker, Term Library, Technical Info, Edit/Delete Term, Smart Glossary.

    - Backdrop: direct-painted 0.27 alpha, shown and hidden immediately.
    - Dialog card: always 100% opaque, shown at FINAL size immediately.
    - No geometry/resize/scale/minHeight animation on the card.
    - Three close affordances: X (host header), click backdrop outside card, Esc.
    - Content is a plain QWidget placed into the card body.
    - Only Download/Repair truly independent windows stay as separate top-level.
    """

    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("appModalHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # Host must be fully transparent container. Only its backdrop child dims the main UI.
        self.setStyleSheet("QFrame#appModalHost { background: transparent; border: 0; }")
        self.hide()

        self._current_content: QWidget | None = None
        self._retain_current_content = False
        self._on_closed = None
        self._click_ts: float | None = None

        # Full-size host that covers the window content area.
        # We draw nothing ourselves; backdrop + card are children.

        # Direct painting avoids per-frame stylesheet parsing and keeps the large
        # content tree free of QGraphicsOpacityEffect.
        self.backdrop = _ModalBackdrop(self)
        self._backdrop_target_alpha = 0.27

        # One shared opaque surface owns the modal chrome. Keeping Header,
        # Body, and Footer in one primitive prevents transparent edge drift.
        self.surface = DialogSurface(self, close_callback=self._request_close)
        self.card = self.surface
        self.header = self.surface.header
        self.title_label = self.surface.header_title
        self.xbtn = self.surface.close_button
        self.body = self.surface.body
        self.body.setObjectName("modalCardBody")
        self.body_lay = self.surface.body_layout
        self.surface.footer.hide()
        from .window_constraints import EmbeddedCardInteraction
        self._card_interaction = EmbeddedCardInteraction(self.card, self.header)
        from PySide6.QtGui import QShortcut, QKeySequence
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self._request_close)

        # Outside click closes.
        self.backdrop.mousePressEvent = lambda event: event.accept()
        self.backdrop.mouseReleaseEvent = self._backdrop_pressed
        self.backdrop.show()
        self.backdrop.lower()

        # Esc on card.
        self.card.installEventFilter(self)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        self.surface.refresh_theme_palette()
        self.backdrop.update()

    def eventFilter(self, obj, ev):
        if obj is self.card and ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self._request_close()
                return True
        return super().eventFilter(obj, ev)

    def _backdrop_pressed(self, e):
        e.accept()
        if not self.card.geometry().contains(e.position().toPoint()):
            self._request_close()

    def _request_close(self):
        # Record close click time for real desktop "close click → dialog gone" measurement.
        self._close_click_ts = time.perf_counter() if GUI_PROFILE_ENABLED else None
        self.hide_content()
        self.closed.emit()
        if self._on_closed:
            try:
                self._on_closed()
            except Exception:
                pass
            self._on_closed = None

    def show_content(
        self,
        content: QWidget,
        title: str = "",
        size=None,
        min_size=None,
        on_closed=None,
        *,
        retain_content: bool = False,
    ):
        """Show the card and stable backdrop at their final state immediately."""
        self._click_ts = time.perf_counter() if GUI_PROFILE_ENABLED else None
        self._first_paint = False
        self._first_paint_marked = False

        # Cached picker/technical widgets remain children of the modal body.
        # Reparenting a large styled tree on every open forces a full polish and
        # layout pass even though none of its content changed.
        if self._current_content is not None:
            self.body_lay.removeWidget(self._current_content)
            self._current_content.hide()
            if not self._retain_current_content:
                self._current_content.setParent(None)
        self._current_content = content
        self._retain_current_content = bool(retain_content)
        self._on_closed = on_closed

        self.title_label.setText(title or "")

        # Swap body content
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w and w is not content:
                w.hide()
                w.setParent(None)
        if content.parentWidget() is not self.body:
            content.setParent(self.body)
        self.body_lay.addWidget(content, 1)
        from .design.presentation import prepare_controls
        prepare_controls(content)
        content.show()
        content.setMinimumSize(0, 0)
        from PySide6.QtWidgets import QLayout
        self.surface.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # The body belongs to the shared host, not to any hosted page.  Restore
        # it defensively so one page's stale visibility state cannot blank the
        # next dialog shown through this host.
        self.body.show()

        # Explicitly sized production modals do not need an expensive
        # adjustSize()/sizeHint() traversal over every card or benchmark row.
        if size is None:
            content.adjustSize()
            sh = content.sizeHint()
            hinted_w, hinted_h = sh.width(), sh.height()
        else:
            hinted_w = hinted_h = 0
        target_w = max((size and size[0]) or hinted_w or 520, (min_size and min_size[0]) or 420)
        target_h = max((size and size[1]) or hinted_h or 420, (min_size and min_size[1]) or 320)

        parent = self.parentWidget()
        if parent:
            pr = parent.rect()
            cw = min(target_w, max(1, pr.width() - 24))
            ch = min(target_h, max(1, pr.height() - 24))
            cx = (pr.width() - cw) // 2
            cy = max(12, (pr.height() - ch) // 2)
            self.card.setGeometry(cx, cy, cw, ch)
            self.setGeometry(pr)
        else:
            self.card.setGeometry(60, 60, target_w, target_h)
            self.setGeometry(self.card.geometry())

        # Card is already at its final geometry and remains fully opaque.
        self.show()
        self.raise_()
        self.card.show()
        self.card.raise_()

        # Real-desktop verification showed a short fade coalescing into 2-4
        # large paint steps under production content. Use the final alpha at
        # once; stable response is preferable to a segmented fade.
        self.backdrop.setGeometry(self.rect())
        self.backdrop.set_alpha(self._backdrop_target_alpha)
        self.backdrop.show()
        self.backdrop.raise_()
        self.card.raise_()
        self.raise_()

        # Record real desktop timing: click → backdrop visible
        try:
            if self._click_ts is not None:
                dt_bd = (time.perf_counter() - self._click_ts) * 1000
                print(f"[perf] backdrop visible ~{int(dt_bd)}ms title={title!r}")
        except Exception:
            pass

        # Critical stacking
        def _force_stack():
            try:
                self.raise_()
            except Exception:
                pass
            try:
                self.backdrop.raise_()
            except Exception:
                pass
            try:
                self.card.raise_()
            except Exception:
                pass
        QTimer.singleShot(0, _force_stack)

        # Schedule the first paint without forcing a nested event loop.
        self.card.update()

    def paintEvent(self, event):
        # Mark first paint relative to the click timestamp captured in show_content.
        try:
            if not getattr(self, "_first_paint_marked", False) and self._click_ts is not None:
                dt = (time.perf_counter() - self._click_ts) * 1000
                title = getattr(self, "title_label", None)
                t = title.text() if title else ""
                print(f"[perf] modal paintEvent first-frame ~{int(dt)}ms title={t!r}")
                self._first_paint_marked = True
        except Exception:
            pass
        super().paintEvent(event)

    def hide_content(self):
        # Card, content, and backdrop disappear together. No large-area effect
        # or coalesced alpha animation is kept alive after the close action.
        _now = time.perf_counter() if GUI_PROFILE_ENABLED else 0.0
        dirty_rect = self.geometry()
        try:
            self.card.hide()
        except Exception:
            pass
        if self._current_content is not None:
            try:
                self.body_lay.removeWidget(self._current_content)
                self._current_content.hide()
                if not self._retain_current_content:
                    self._current_content.setParent(None)
            except Exception:
                pass
            self._current_content = None
        if GUI_PROFILE_ENABLED:
            try:
                base = getattr(self, "_close_click_ts", None) or getattr(self, "_click_ts", None)
                if base is not None:
                    dt = (_now - base) * 1000
                    src = "close_click" if getattr(self, "_close_click_ts", None) else "open_click_fallback"
                    print(f"[perf] close (dialog gone) ~{int(dt)}ms src={src}")
            except Exception:
                pass
        self.backdrop.set_alpha(0.0)
        self.backdrop.hide()
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            # Embedded D3D video surfaces do not always invalidate the Qt
            # backing store after an in-window modal disappears. Force the
            # vacated card/backdrop area to repaint so no stale dialog pixels
            # remain over the Studio preview.
            parent.update(dirty_rect)
            parent.repaint(dirty_rect)
        self._retain_current_content = False
        self._close_click_ts = None

    def resize_to_parent(self):
        parent = self.parentWidget()
        if not parent:
            return
        self.setGeometry(parent.rect())
        if self.card.isVisible():
            cr = self.card.geometry()
            pr = parent.rect()
            width = min(cr.width(), max(1, pr.width()-24))
            height = min(cr.height(), max(1, pr.height()-24))
            cx = max(12, (pr.width() - width) // 2)
            cy = max(12, (pr.height() - height) // 2)
            self.card.setGeometry(cx, cy, width, height)
        if self.backdrop.isVisible():
            self.backdrop.setGeometry(self.rect())


# Role-card statuses meaning "this computer cannot run it" (recognition_choices.unavailable_on_host).
_HOST_LIMIT_STATUSES = frozenset({"需要 NVIDIA 显卡", "只能在 Apple Silicon Mac 上运行"})
_HOST_LIMIT_RECOVERY = "换成能用的方式"


def _bind_home_shortcuts(window, owner):
    """Home keys from the shared registry: start, choose media, search (2026-10-13).

    The shortcuts belong to the home action bar, which is only visible on
    the home page, so Studio keys such as Ctrl+K stay with Studio.
    """
    from PySide6.QtGui import QShortcut
    from . import shortcut_registry as keys

    def start_key(key):
        window.start_button.setShortcut(QKeySequence(key))
        bind_text(window.start_button, '开始生成字幕 ({key})', property='toolTip',
                  key=keys.display(key) if key else tr('未绑定'))

    choose = QShortcut(QKeySequence("Ctrl+O"), owner)
    choose.setContext(Qt.ShortcutContext.WindowShortcut)
    choose.activated.connect(lambda: window._choose_media() if window._home_page_active() else None)
    search = QShortcut(QKeySequence("Ctrl+K"), owner)
    search.setContext(Qt.ShortcutContext.WindowShortcut)
    search.activated.connect(lambda: window._open_feature_search() if window._home_page_active() else None)
    window._home_shortcuts = (choose, search)
    keys.keep_keys({"home.start_run": start_key, "home.choose_media": choose, "home.search": search})


class MainWindow(QWidget):
    # 2026-10-13: background results for the home "现在先做什么" card and the example project.
    _onboarding_facts_ready = Signal(object)
    _sample_ready = Signal(object)

    def __init__(self, media_paths, legacy, pipeline, startup_self_test, *, startup_page="recognition"):
        super().__init__()
        self._onboarding_facts_ready.connect(self._onboarding_facts_received)
        self._sample_ready.connect(self._sample_project_ready)
        self._workshop_page_instance = None
        self._history_page_instance = None
        self._studio_page_instance = None
        self.media_paths = list(media_paths)
        self.legacy = legacy
        self.pipeline = pipeline
        self.startup_self_test = startup_self_test
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
                from twobyteasr.gui_performance import GuiPerformanceProfiler

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
        self.pages = QStackedWidget()
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
        from .storage_ui import IdleStorageMaintenance
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
            self._refresh_ai_summary()
        self._create_resize_handles()
        self._apply_ui_language()
        self._encoder_capability_cancel = threading.Event()
        self._encoder_capability_worker = None
        self._startup_background_ready_thread = None
        # P0: background preload of model install status + term index after first paint.
        # Never on click path; cheap FS/metadata only. No spinners.
        if self._recognition_page_deferred:
            self._switch_page(self.studio_page)
        else:
            QTimer.singleShot(0, self, self._background_preload)
            QTimer.singleShot(0, self, self._restore_last_project_profile)
        # Local MCP access (2026-10-12, off by default): one settings read;
        # the pipe and its modules load only when the user turned it on.
        QTimer.singleShot(0, self, self._start_mcp_bridge)

    def _start_mcp_bridge(self):
        try:
            from .mcp_common import read_settings
            if read_settings().get("enabled"):
                from .mcp_bridge import start_if_enabled
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
        # First visit builds the page (0.5-2 s with many reports): show the
        # busy cursor at once instead of an unexplained pause after the click.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return self._construct_lazy_page(name)
        finally:
            QApplication.restoreOverrideCursor()

    def _construct_lazy_page(self, name: str):
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
            if self._density_comfortable is not None:
                page.apply_density(self._density_comfortable)
        elif name == "history":
            # Reports live in the stable user-data root; the install tree (and
            # any legacy roots) are still scanned so history survives rebuilds.
            from . import reporting as _reporting

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
        elif name == "studio":
            # Imported on first use (or by the idle warm-up after startup):
            # the Studio module tree is ~0.5 s of the home page's start.
            from twobyteasr.studio_ui import SubtitleStudioPage
            page = SubtitleStudioPage(self)
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
        self._refresh_ai_summary()
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
        from .i18n import invalidate_language_cache
        from .runtime_trace import GLOBAL_STUDIO_TRACE

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
        from .i18n_widgets import refresh_application
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
        from .design.presentation import button_role
        self.support_button = button_role(QPushButton(), "secondary", size="compact")
        self.support_button.setObjectName("supportEntry")
        bind_text(self.support_button, "支持我！")
        install_themed_icon(self.support_button, "fa5s.heart", "primary")
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
        self.subtitle_studio_button.clicked.connect(self._open_subtitle_studio)
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
        from .design.presentation import button_role
        for button in (self.subtitle_studio_button, self.model_workshop_button, self.app_settings_button,
                       self.help_button):
            button_role(button, "secondary", size="default")
            button.setProperty("homeNavigation", True)
            button.setIconSize(QSize(18, 18))
        # Keyboard users still Tab to every header command; a mouse click or
        # window activation no longer leaves a focus ring on the support button.
        for button in (self.support_button, self.update_button, self.subtitle_studio_button,
                       self.model_workshop_button, self.return_recognition_button, self.app_settings_button,
                       self.help_button):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.language_combo = user_text(FramelessPopupCombo())
        self.language_combo.setMinimumWidth(100)
        self.language_combo.setMaximumWidth(160)  # soft for CN labels
        self.language_combo.addItem("简体中文", "zh")
        self.language_combo.addItem("繁體中文", "zh-Hant")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("日本語", "ja")
        self.language_combo.addItem("한국어", "ko")
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
        from . import shortcut_registry as keys
        menu = QMenu(self)
        menu.setObjectName("helpMenu")
        search_key = keys.tooltip_key("home.search")
        entries = (
            ("新手教学", self._start_home_tour),
            ("显示新手引导", lambda: self._next_step_action("show_guide")),
            ("打开范例工程", self._open_sample_project),
            ("选择识别方式…", lambda: self._next_step_action("choose_plan")),
            ("申请与设置 API…", self._open_api_setup_guide),
            (None, None),
            (tr("搜索功能与设置…（{key}）", key=search_key), self._open_feature_search),
            ("快捷键…", lambda: self._open_application_settings(initial_section="快捷键")),
            ("复制诊断信息…", self._open_diagnostics_dialog),
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
        from .diagnostics_report import open_diagnostics_dialog
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

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_title_bar"):
            self.window_title_bar.sync_window_state()
            studio = self.built_page("studio")
            if studio is not None:
                studio._sync_window_controls()
            self._layout_resize_handles()
        super().changeEvent(event)

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
        hidden = self.isMaximized()
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

    def _page_changed(self, index: int):
        current = self.pages.widget(index)
        if current is self.__dict__.get("settings_scroll"):
            self._schedule_next_step_probe()
            if self.__dict__.pop("_home_tour_pending", False):
                QTimer.singleShot(500, self._start_home_tour)
        completion = current.objectName() == 'completionScroll'
        studio = existing_page(self, "studio")
        in_studio = studio is not None and current is studio
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
        language = getattr(self, "_ui_language", current_language())
        if current.property("_2b_language_applied") != language:
            apply_ui_language(current, language)
            current.setProperty("_2b_language_applied", language)
        # Interface zoom: pages built or changed since the last zoom step
        # catch up here (no-op at 100%; Studio keeps its own size).
        from .ui_zoom import apply_to_changed as _apply_ui_zoom
        _apply_ui_zoom(current)
        self._update_bottom_bar_visibility(index)

    def _switch_page(self, target) -> None:
        """Commit a stacked-page transition under one paint boundary."""
        widget = self.pages.widget(target) if isinstance(target, int) else target
        if widget is self.settings_scroll:
            self._ensure_recognition_page()
        if widget is None or self.pages.currentWidget() is widget:
            return
        if widget is self.pages.widget(2) and hasattr(self, 'result_preview'):
            self._refresh_completion_preview()
        from .ui_motion import atomic_layout, reveal_cue
        with atomic_layout(self):
            widget.ensurePolished()
            self.pages.setCurrentWidget(widget)
            self.pages.layout().activate()
            if hasattr(self, "content_layout"):
                self.content_layout.activate()
        studio = self.built_page("studio")
        reveal_cue(self.app_header if self.app_header.isVisible() or studio is None else studio.studio_toolbar)

    def _update_bottom_bar_visibility(self, index: int = None):
        # Bottom CTA is only relevant on the main settings page (index 0).
        # Keep it fixed at the content_host level so it never scrolls away.
        try:
            idx = self.pages.currentIndex() if index is None else index
            if hasattr(self, "bottom_bar") and self.bottom_bar is not None:
                self.bottom_bar.setVisible(self.pages.widget(idx) is self.settings_scroll)
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
            install_window_bounds(self)
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

    def closeEvent(self, event):
        try:
            studio = self.built_page("studio")
            if studio is not None:
                studio.close_page()
            if getattr(self, "_persist_geometry", False):
                settings = QSettings("2ByteASR", "2ByteASR")
                g = self.geometry()
                if g.width() >= 200 and g.height() >= 200:
                    settings.setValue("mainWindow/geometry", [g.x(), g.y(), g.width(), g.height()])
                    settings.sync()
        except Exception:
            pass
        super().closeEvent(event)

    def _open_model_workshop(self):
        self._ensure_recognition_page()
        self.workshop_page.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
        self.workshop_page.restore_active_navigation()
        self._switch_page(self.workshop_page)

    def open_studio_project(self, project_path=None, *, mode="edit", source="canonical", on_ready=None, expected_result_ref=None):
        """Canonical Studio navigation entry for every project-opening source."""
        proofread = getattr(self, "glossary_proofread_page", None)
        if proofread is not None and project_path and not proofread.settle_writes(project_path):
            # The proofreading edits of this file are not saved yet; Studio
            # would load (and later save over) the older file.
            return
        if (source == "external" and project_path and self.built_page("studio") is not None
                and self.studio_page.project is not None):
            from .external_open import path_identity
            current = self.studio_page.session.project_path
            if current and path_identity(current) == path_identity(project_path):
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
        from .recognition_result import working_reference
        self.open_studio_project(str(target), mode="edit", source="studio_recognition",
            expected_result_ref=working_reference(
                getattr(studio, '_pending_recognition_result_ref', None)) or None)

    def _open_subtitle_studio(self, project_path=None, *, mode="edit", skip_dirty_guard=False, on_ready=None, expected_result_ref=None):
        if expected_result_ref:
            from .recognition_result import verify_result_reference
            try:
                verify_result_reference(expected_result_ref, project_path=project_path)
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.warning(self, tr('无法确认本次识别工程'), str(exc))
                return
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
        self._switch_page(self.studio_page)
        self.pages.layout().activate()
        self.last_studio_transition_profile = {
            "request_to_layout_settled_ms": round((time.perf_counter() - transition_started) * 1000, 3)
        }
        # Opening the Studio entry always lands in the Project Hub. Explicit
        # project paths from completed runs remain a deliberate deep link.
        candidate = str(project_path or "")
        if candidate and not Path(candidate).is_file():
            self.studio_page._studio_trace(
                "OPEN_FAILED",
                stage="VALIDATE",
                source="canonical",
                project_path=candidate,
                message="Project file not found",
            )
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            bind_text(box, '无法打开工程', property='windowTitle')
            box.setText(f"Project file not found:\n{candidate}")
            box.exec()
            return
        if candidate and Path(candidate).is_file():
            def ready():
                project = self.studio_page.project
                if expected_result_ref:
                    from .recognition_result import verify_result_reference
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
            self._retry_pending_recognition_reload()

    def _return_to_settings(self):
        self._ensure_recognition_page()
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
        }
        from .recognition_input import capture_recognition_snapshot
        try:
            snapshot = capture_recognition_snapshot(self.studio_page.project, str(project.resolve()))
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
            self._start_run()
            if not self._run_in_progress:
                self.studio_page.fail_recognition_runtime(
                    str(self._run_block_reason or "识别未能启动，请查看运行日志")
                )

    def _finish_studio_recognition(self, project_path: str, expected_result_ref=None) -> None:
        context = getattr(self, "_studio_recognition_context", None) or {}
        snapshot = context.get("snapshot")
        if snapshot:
            from .recognition_input import project_content_revision
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
        from .llm_config import read_asr_api_key

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
        from .api_setup_dialog import SetupHost
        from .llm_config import read_asr_api_key, read_oss_credentials

        def saved_key(provider, url):
            return read_asr_api_key(provider, url)[0]

        def open_text_settings(service_id):
            self._open_ai_settings_dialog()
            # Open on the service the guide was about (it is saved only with 保存).
            dialog = getattr(self, "_ai_settings_dialog", None)
            editor = dialog.findChild(EndpointEditor) if dialog is not None else None
            index = editor.service.findData(str(service_id)) if editor is not None else -1
            if index >= 0:
                editor.service.setCurrentIndex(index)

        return SetupHost(settings=lambda: self.legacy.RUNTIME_SETTINGS, saved_key=saved_key,
                         saved_oss_credentials=read_oss_credentials,
                         save=self._save_cloud_provider_from_guide,
                         open_advanced=self._open_api_key_dialog_for_preset,
                         open_text_settings=open_text_settings)

    def _open_api_setup_guide(self, preset_key: str = "", kind: str = "asr"):
        from .api_setup_dialog import ApiSetupDialog
        initial = str(preset_key or self.qwen_asr_api_provider.currentData() or "mosi_moss_pro")
        dialog = ApiSetupDialog(self, self._api_setup_host(), kind=kind, initial=initial)
        dialog.exec()

    def _save_cloud_provider_from_guide(self, provider: str, values: dict, use_as_primary: bool):
        """Save one cloud ASR provider from the guide through the existing paths.

        Keys go to the same encrypted store as the advanced form; settings go
        through ``_save_asr_configuration``. Nothing is switched silently: any
        follow-up change needed to run without CUDA is reported back.
        """
        from .llm_config import save_oss_credentials, save_spark_credentials, validate_qwen_asr_endpoint
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
        from .api_setup_catalog import UPLOAD_OWN_OSS, UPLOAD_PROVIDER
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
            # Trial temporary upload, only when explicitly chosen (ADR 0112); an existing OSS setup stays saved.
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
            from .recognition_choices import cloud_followups, host_profile
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
            QTimer.singleShot(automatic_check_delay_ms(), self, self._auto_check_updates)
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

    def _start_home_tour(self):
        """Point at the real home page parts one by one (2026-10-14)."""
        if self.pages.currentWidget() is not self.__dict__.get("settings_scroll"):
            self._switch_page(0)
            self._home_tour_pending = True
            return
        from . import onboarding
        from .home_tour import start_home_tour

        def done(completed):
            onboarding.save_state(dict(onboarding.load_state(), tour_done=True))
            self._tutorial_finish(completed)
        start_home_tour(self, done)

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
        from .service import MediaResult, QueueResult
        from .studio_project import load_project
        from .studio_subtitle_export import compile_srt
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
        if self.built_page("studio") is not None or "twobyteasr.studio_ui" in sys.modules:
            return
        import twobyteasr.studio_ui  # noqa: F401

    def _auto_check_updates(self):
        if (self.update_check_worker and self.update_check_worker.isRunning()) or \
                (self.update_download_worker and self.update_download_worker.isRunning()):
            return
        worker = UpdateCheckWorker(self, automatic=True)
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
        bind_text(message, '{value0}\n\n可稍后重试，或打开发布页手动下载。', property='informativeText', value0=detail)
        open_release = message.addButton(tr("打开发布页"), QMessageBox.ButtonRole.AcceptRole)
        message.addButton(tr("关闭"), QMessageBox.ButtonRole.RejectRole)
        message.exec()
        if message.clickedButton() is open_release:
            QDesktopServices.openUrl(QUrl(RELEASE_PAGE))

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
        dialog = UpdateOfferDialog(check, self)
        self._update_offer_dialog = dialog
        dialog.exec()
        self._update_offer_dialog = None
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
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        self.settings_page_widget = page
        self.settings_page_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        page_heading = QHBoxLayout()
        page_heading.setSpacing(12)
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
        from .media_intake import SUPPORTED_MEDIA_SUFFIXES
        formats = sorted(suffix.lstrip(".").upper() for suffix in SUPPORTED_MEDIA_SUFFIXES)
        self.media_formats = QLabel("  ·  ".join(formats))
        self.media_formats.setObjectName("mediaFormats")
        self.media_formats.hide()
        media_text.addWidget(self.media_formats)
        self.media_origin_label = QLabel("来自兔白字幕工程")
        self.media_origin_label.setObjectName("studioOrigin")
        self.media_origin_label.hide()
        media_text.addWidget(self.media_origin_label)
        media_row.addLayout(media_text, 1)
        self._media_text_index = media_row.count() - 1
        media_row.addSpacing(12)
        self.choose_media_button = AnimatedButton("选择素材")
        self.choose_media_button.setObjectName("softAction")
        install_themed_icon(self.choose_media_button, "fa5s.folder-open")
        self.choose_media_button.clicked.connect(self._choose_media)
        media_row.addWidget(self.choose_media_button)
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
        layout.addSpacing(2)
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
        from .design.presentation import button_role
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
        # 2026-10-08 home columns (user): left = content & terms, then the
        # Studio gallery; right = recognition plan, then AI segmentation.
        # Each column stacks at natural height; blocks are not forced equal.
        surface_layout = QHBoxLayout(surface)
        surface_layout.setContentsMargins(0, 2, 0, 0)
        surface_layout.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(16)
        self.settings_left_column = left
        content_profile = QFrame()
        content_profile.setObjectName("homeContentProfile")
        self.content_profile_card = content_profile
        profile_layout = QVBoxLayout(content_profile)
        profile_layout.setContentsMargins(20, 16, 20, 16)
        profile_layout.setSpacing(9)
        # 2026-10-08: the content name lives once, in the combo; the term
        # switch and its state line live once, in the term panel below.
        content_head = QHBoxLayout()
        content_head.setSpacing(12)
        self.content_icon = QLabel()
        self.content_icon.setObjectName("homeCardIcon")
        self.content_icon.setFixedSize(40, 40)
        self.content_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_head.addWidget(self.content_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        current_eyebrow = QLabel("内容与术语")
        current_eyebrow.setObjectName("homeSectionTitle")
        content_head.addWidget(current_eyebrow)
        content_head.addStretch(1)
        profile_layout.addLayout(content_head)
        # Two framed panels of equal height: content choice | terms
        # (glossary correction and the optional web check as parallel rows).
        content_body = QHBoxLayout()
        content_body.setSpacing(14)
        # Left: name, input and recent chips without an extra frame.
        choice_panel = QWidget()
        choice_panel.setObjectName("homeContentPlain")
        self.content_choice_panel = choice_panel
        content_choice = QVBoxLayout(choice_panel)
        content_choice.setContentsMargins(2, 4, 4, 4)
        content_choice.setSpacing(10)
        content_body.addWidget(choice_panel, 1)
        profile_layout.addLayout(content_body)
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
        content_choice.addWidget(self.game_box)
        # Recent content names as one-click chips (same history as the combo).
        from .home_widgets import QuickPickRow
        self.content_quick_picks = QuickPickRow("最近")
        self.content_quick_picks.picked.connect(self._pick_recent_content)
        content_choice.addWidget(self.content_quick_picks)
        self._build_subtitle_language_row(content_choice)
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
        batch_layout.setContentsMargins(16, 12, 16, 12)
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
        install_themed_icon(manage, "fa5s.book-open")
        manage.clicked.connect(self._manage_terms)
        manage.setMaximumWidth(175)  # soft; EN/JA label must not truncate
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
        terms_rule = QFrame()
        terms_rule.setObjectName("homePanelRule")
        terms_rule.setFixedHeight(1)
        batch_layout.addSpacing(4)
        batch_layout.addWidget(terms_rule)
        batch_layout.addSpacing(4)
        batch_layout.addWidget(self.term_search)
        self.term_search_note = QLabel("仅本次任务启用；需可验证的搜索能力")
        self.term_search_note.setObjectName("homeTermState")
        self.term_search_note.setProperty("tone", "off")
        self.term_search_note.setWordWrap(True)
        self.term_search_note.setContentsMargins(46, 0, 0, 0)
        batch_layout.addWidget(self.term_search_note)
        batch_layout.addStretch(1)
        content_body.addWidget(batch_glossary, 1)
        content_choice.addStretch(1)
        # AI segmentation card; filled once the AI tile exists.
        self.home_process_card = QFrame()
        self.home_process_card.setObjectName("homeProcessCard")
        process_layout = QVBoxLayout(self.home_process_card)
        process_layout.setContentsMargins(4, 4, 4, 14)
        process_layout.setSpacing(4)

        plan_block = QWidget()
        plan_block.setObjectName("homePlanBlock")
        right = QVBoxLayout(plan_block)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(14)
        recognition_header = QHBoxLayout()
        recognition_header.setSpacing(8)
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
        recognition_header.addWidget(self.home_task_settings_button)
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
        install_themed_icon(self.project_profile_manage, "fa5s.ellipsis-h")
        bind_text(self.project_profile_manage, '管理 Project / Game Profile', property='toolTip')
        self.project_profile_manage.setFixedSize(36, 36)
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
        bind_text(self.recognition_mode_combo, '新手只需选择目标；高级用户可切换到自定义并继续使用模型卡', property='toolTip')
        self.recognition_mode_combo.currentIndexChanged.connect(self._apply_recognition_plan_from_ui)
        plan_row.addWidget(self.recognition_mode_combo, 1)
        self.recognition_plan_hint = QLabel("")
        self.recognition_plan_hint.setObjectName("muted")
        self.recognition_plan_hint.setWordWrap(True)
        self.recognition_plan_hint.hide()
        plan_row.addLayout(profile_row, 1)
        # Wide windows: one header row (title, goal, saved plan, advanced);
        # narrower ones put goal / plan on their own line (2026-10-08). The
        # dropdowns may shrink so neither form widens the page.
        for combo in (self.recognition_mode_combo, self.project_profile_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        plan_row.setContentsMargins(8, 0, 0, 0)
        self.plan_controls = QWidget()
        self.plan_controls.setLayout(plan_row)
        self.plan_header_layout = recognition_header
        recognition_header.insertWidget(1, self.plan_controls, 1)
        # 2026-10-08 (user): the plan toolbar sits on the 本批字幕 heading row
        # so the three model cards start level with the Studio card.
        page_heading.addLayout(recognition_header, 3)
        self.page_subtitle = page_subtitle
        # 识别方案：三张角色模型卡（批准图核心区）
        from twobyteasr.ui_recognition import RecognitionPlanWidget

        self.recognition_plan = RecognitionPlanWidget()
        # Its height band is set per window tier (and zoom) in apply_density.
        self.recognition_plan.setProperty("uiZoomOwnSize", True)
        self.recognition_plan.role_requested.connect(self._open_model_picker)
        self.recognition_plan.recovery_requested.connect(self._recognition_recovery)
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
        # Right two thirds: plan, AI, content & terms as one column; the
        # left project card takes exactly that height (follows the right).
        produce = QVBoxLayout()
        produce.setSpacing(16)
        produce.addWidget(plan_block)
        produce.addWidget(self.home_process_card)
        produce.addWidget(content_profile)
        self.settings_right_column = produce
        left.addWidget(studio_entry, 1)
        surface_layout.addLayout(left, 1)
        surface_layout.addLayout(produce, 2)
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
        from .llm_config import read_asr_api_key

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
        self.ai_polish = SwitchControl("字幕校对使用 AI（可关闭）")
        self.ai_polish.setChecked(settings["switches"].get("enable_ai_polish", True))
        bind_text(self.ai_polish, '关闭后不请求校对模型，也不需要校对 API Key；保留本地转写和文字规则。', property='toolTip')
        self.ai_panel.content_layout.addWidget(self.ai_polish)
        self.ai_grouping = SwitchControl("全文断句使用 AI（关闭后使用本地规则）")
        self.ai_grouping.setChecked(
            settings["switches"].get("use_ai_grouping", True)
        )
        bind_text(self.ai_grouping, '关闭后不请求断句模型，也不需要断句 API Key；将使用 MOSS 自然语句、FireRed 停顿与本地护栏断句。', property='toolTip')
        self.ai_panel.content_layout.addWidget(self.ai_grouping)
        self.prefer_arabic_numbers = SwitchControl('数字规范化（保留口语小数字）')
        self.prefer_arabic_numbers.setChecked(settings['switches'].get('prefer_arabic_numbers', True))
        bind_text(self.prefer_arabic_numbers, '只影响之后生成的字幕；普通整数1～9保留原文，明确数值从10开始转为阿拉伯数字；小数、百分比和比例除外。保留约数、成语和已确认术语，不求和或去重，不改已保存工程。', property='toolTip')
        self.ai_panel.content_layout.addWidget(self.prefer_arabic_numbers)
        self.prefer_arabic_numbers.toggled.connect(self._mark_ai_configuration_dirty)
        self.unified_glm = SwitchControl("同一云端模型负责字幕校对与全文断句（推荐）")
        self.unified_glm.setChecked(
            settings["switches"].get("unified_glm_processing", True)
        )
        self.ai_panel.content_layout.addWidget(self.unified_glm)
        endpoint_row = QHBoxLayout()
        self.polish_editor = EndpointEditor("字幕校对模型", CORAL, "polish", settings)
        self.group_editor = EndpointEditor("全文断句模型", BLUE, "group", settings)
        endpoint_row.addWidget(self.polish_editor, 1)
        endpoint_row.addWidget(self.group_editor, 1)
        self.ai_panel.content_layout.addLayout(endpoint_row)
        prompt_row = QHBoxLayout()
        self.share_key = SwitchControl("两阶段共用新填写的校对密钥")
        self.share_key.setChecked(True)
        prompt_button = AnimatedButton("查看项目内置提示词")
        prompt_button.setObjectName("linkButton")
        prompt_button.setIcon(_icon("fa5s.info-circle"))
        prompt_button.clicked.connect(lambda: PromptDialog(self).exec())
        self.save_ai_button = AnimatedButton("保存 AI 配置")
        self.save_ai_button.setObjectName("outline")
        self.save_ai_button.setIcon(_icon("fa5s.save"))
        self.save_ai_button.clicked.connect(
            lambda: self._save_ai_configuration(show_feedback=True)
        )
        prompt_row.addWidget(self.share_key)
        prompt_row.addStretch(1)
        prompt_row.addWidget(prompt_button)
        prompt_row.addWidget(self.save_ai_button)
        self.ai_panel.content_layout.addLayout(prompt_row)
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
            editor.json_mode.toggled.connect(self._mark_ai_configuration_dirty)
            editor.structured_output.toggled.connect(self._mark_ai_configuration_dirty)
        self.ai_grouping.toggled.connect(self._mark_ai_configuration_dirty)
        self.unified_glm.toggled.connect(self._mark_ai_configuration_dirty)
        self.share_key.toggled.connect(self._mark_ai_configuration_dirty)
        # 断句开关/断句模型属于识别方案快照（llm_enabled / llm_config_ref）：
        # 变更同样进入方案脏标，切换方案前给出保存/放弃提示。
        self.ai_grouping.toggled.connect(self._mark_profile_configuration_dirty)
        self.group_editor.model.currentTextChanged.connect(self._mark_profile_configuration_dirty)
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
        from twobyteasr.ui_widgets import SettingTile

        self.setting_tiles: dict[str, SettingTile] = {}
        self._tile_panels = [
            ("ai", self.ai_panel, "AI 智能断句", "fa5s.project-diagram"),
        ]
        tiles = []
        for key, _panel, title, icon_name in self._tile_panels:
            tile = SettingTile(title, "", icon_name)
            self.setting_tiles[key] = tile
            tiles.append(tile)
            if key == "ai":
                # Opens the AI settings dialog (_build_home_process_card).
                continue

            def _toggle(tile=tile, key=key):
                panels = {k: p for k, p, _t, _i in self._tile_panels}
                panel = panels[key]
                if tile.isChecked():
                    for other_key, other_panel, _t, _i in self._tile_panels:
                        if other_key != key:
                            other_panel.set_expanded(False, animate=False)
                            other_panel.setVisible(False)
                    panel.setVisible(True)
                    panel.set_expanded(True, animate=True)
                else:
                    panel.set_expanded(False, animate=True)
                    panel.setVisible(False)

            tile.toggled.connect(
                lambda _checked=False, tile=tile, key=key: _toggle(tile, key)
            )
        self._build_home_process_card(tiles[0])
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
            from .studio_project import studio_settings_path
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
            entries = recent_studio_entries(records, limit=3)
            key = (entries, current_language())
            if key != getattr(self, "_studio_recent_key", None):
                self._studio_recent_key = key
                self._studio_recent_entries = entries
                hero.set_entry(entries[0] if entries else None)
                # The cover is the current project; the list holds the two
                # other recent ones, and hovering a row previews it.
                self.studio_recent_list.set_entries(entries[1:])
                self.studio_recent_caption.setVisible(len(entries) > 1)

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
        self.start_button.setToolTip(reason or translate("开始生成字幕 (Ctrl+Enter)", language))

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
        """AI segmentation summary (2026-10-08): the current service and model,
        separate saved / key / connection facts, and a 设置 AI button. All
        settings open in a dialog; nothing expands on the home page."""
        card = self.home_process_card
        layout = card.layout()
        tile.chevron.hide()
        self.ai_settings_button = AnimatedButton("设置 AI")
        self.ai_settings_button.setObjectName("homeAiSettings")
        install_themed_icon(self.ai_settings_button, "fa5s.sliders-h", "secondary")
        self.ai_settings_button.clicked.connect(lambda: self._open_ai_settings_dialog())
        tile.layout().addWidget(self.ai_settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        tile.clicked.connect(lambda _checked=False: self._open_ai_settings_dialog())
        layout.addWidget(tile)
        self.home_fact_row = QWidget()
        row = QHBoxLayout(self.home_fact_row)
        row.setContentsMargins(70, 0, 16, 0)
        row.setSpacing(8)
        self._ai_state_chips = {}
        for key in ("saved", "key", "connection"):
            chip = QLabel()
            chip.setObjectName("homeFactChip")
            row.addWidget(chip)
            self._ai_state_chips[key] = chip
        row.addStretch(1)
        layout.addWidget(self.home_fact_row)
        self._refresh_home_process_facts()

    def _refresh_home_process_facts(self, *_args) -> None:
        """Saved settings, key and connection are three facts, never one
        "ready" (user, 2026-10-08)."""
        chips = getattr(self, "_ai_state_chips", None)
        if not chips:
            return
        from .llm_config import effective_ai_identity
        language = getattr(self, "_ui_language", current_language())

        def show(name, text, state):
            chip = chips[name]
            chip.setVisible(bool(text))
            chip.setText(translate(text, language) if text else "")
            chip.setProperty("state", state)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

        saved = self.legacy.RUNTIME_SETTINGS
        switches = saved.get("switches", {})
        polish_on = bool(switches.get("enable_ai_polish", True))
        group_on = bool(switches.get("use_ai_grouping", True))
        tile = getattr(self, "setting_tiles", {}).get("ai")
        if not (polish_on or group_on):
            if tile is not None:
                tile.set_summary(translate("未启用 AI · 使用本地规则断句", language))
            show("saved", "AI 已关闭", "off")
            show("key", "", "off")
            show("connection", "", "off")
            return
        stage = "polish" if polish_on else "group"
        try:
            identity = effective_ai_identity(saved, stage)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            identity = {}
        if tile is not None and identity:
            tile.set_summary(f"{translate(str(identity.get('label', '')), language)} · {identity.get('model') or translate('默认模型', language)}")
        if getattr(self, "_ai_has_draft", False):
            show("saved", "有未保存的修改", "warn")
        else:
            show("saved", "设置已保存", "on")
        if str(identity.get("transport", "")) == AITransport.OPENAI_COMPATIBLE.value:
            show("key", "密钥已配置" if identity.get("credential_configured") else "未配置密钥",
                 "on" if identity.get("credential_configured") else "warn")
        else:
            show("key", "使用账号登录", "off")
        editor = self.polish_editor if stage == "polish" else self.group_editor
        result = getattr(editor, "last_connection_ok", None)
        if result is None:
            show("connection", "尚未测试连接", "off")
        else:
            show("connection", "连接正常" if result else "连接失败", "on" if result else "warn")

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

    def _open_ai_settings_dialog(self, on_finished=None) -> None:
        """AI segmentation & proofreading settings (2026-10-08): fixed title,
        close, Cancel and Save; the form scrolls between them. Cancel restores
        every control; the home page's media, settings and scroll stay put."""
        tile = getattr(self, "setting_tiles", {}).get("ai")
        if tile is not None and tile.isChecked():
            tile.setChecked(False)
        current = getattr(self, "_ai_settings_dialog", None)
        if current is not None and current.isVisible():
            current.raise_()
            current.activateWindow()
            return
        from .design.presentation import button_role
        panel = self.ai_panel
        snapshot = self._ai_settings_snapshot()
        dialog = SpringDialog(self)
        self._ai_settings_dialog = dialog
        dialog.setObjectName("aiSettingsDialog")
        bind_text(dialog, 'AI 智能断句设置', property='windowTitle')
        dialog.setWindowIcon(_app_icon())
        dialog.resize(min(1040, max(720, self.width() - 160)), min(800, max(520, self.height() - 120)))
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame(dialog)
        header.setObjectName("aiDialogHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(24, 18, 16, 14)
        head.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("AI 智能断句设置")
        title.setObjectName("aiDialogTitle")
        subtitle = QLabel("字幕校对、全文断句与数字规范化共用这里的服务、模型与密钥")
        subtitle.setObjectName("aiDialogSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        close = button_role(QPushButton(""), "ghost")
        close.setFixedSize(36, 36)
        install_themed_icon(close, "fa5s.times", "secondary")
        close.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        bind_text(close, '关闭 AI 设置', property='accessibleName')
        bind_text(close, '关闭（不保存修改）', property='toolTip')
        close.clicked.connect(dialog.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(header)
        scroll = QScrollArea(dialog)
        scroll.setObjectName("aiDialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("aiDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 4, 24, 16)
        body_layout.setSpacing(0)
        panel.setParent(body)
        body_layout.addWidget(panel)
        body_layout.addStretch(1)
        panel.header.hide()
        self.save_ai_button.hide()
        panel.setVisible(True)
        panel.set_expanded(True, animate=False)
        # Inside the scrolling form the panel may grow (advanced groups).
        panel.content.setMaximumHeight(16777215)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        footer = QFrame(dialog)
        footer.setObjectName("aiDialogFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(24, 12, 24, 16)
        foot.setSpacing(10)
        foot.addStretch(1)
        cancel = button_role(QPushButton("取消"), "secondary")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("保存设置")
        save.setObjectName("primary")
        button_role(save, "primary")
        foot.addWidget(cancel)
        foot.addWidget(save)
        outer.addWidget(footer)
        self.ai_dialog_save_button = save
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
            self._refresh_ai_summary()
            if on_finished is not None:
                on_finished()
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.show()
        # CollapsibleFrame.showEvent re-caps the content height; inside the
        # scrolling form it must grow freely (advanced groups, two editors).
        panel.content.setMaximumHeight(16777215)
        dialog.raise_()
        dialog.activateWindow()

    def _apply_media_mode(self, ready: bool) -> None:
        """Empty: a tall, centred drop zone. Loaded: the compact one-line row."""
        layout = getattr(self, "media_row_layout", None)
        if layout is None:
            return
        hero = not ready
        policy = QSizePolicy.Policy.Expanding if hero else QSizePolicy.Policy.Fixed
        for spacer in (self.media_lead_space, self.media_tail_space):
            spacer.changeSize(0, 0, policy, QSizePolicy.Policy.Minimum)
        self.media_kind_gap.changeSize(0 if hero else 20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        layout.setStretch(self._media_text_index, 0 if hero else 1)
        self.media_kind_label.setVisible(not hero)
        self.media_formats.setVisible(hero)
        tall = ui_zoom.logical(self.height()) >= 900
        icon = (64 if tall else 52) if hero else 36
        self.media_type_icon.setFixedSize(icon, icon)
        layout.setContentsMargins(*((28, 18, 28, 18) if hero else (12, 8, 12, 8)))
        layout.setSpacing(18 if hero else 6)
        if hero:
            height = 130 if ui_zoom.logical(self.height()) >= 1150 else 124 if tall else 116
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
            tile.icon_label.setPixmap(qta.icon("fa5s.project-diagram", color=zones["ai"]).pixmap(QSize(19, 19)))


    def _action_bar(self):
        from .design.presentation import button_role
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
        from .theme_manager import SETTINGS_APP, SETTINGS_ORG
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def _confirm_run_disclosure(self) -> bool:
        """State what this run will use; ask once before audio goes to a cloud service (2026-10-13).

        Every run logs engine, speaker source, timestamp source, uploads and
        cost basis. A run that uploads audio asks once per provider/model/host
        (the answer is remembered locally); text-only AI is never interrupted.
        """
        import hashlib
        from .recognition_choices import disclosure_text, run_disclosure
        try:
            settings = json.loads(json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False))
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
        from .service import MediaResult, QueueResult
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

    def _show_completion_review_details(self):
        self.result_files_panel.set_mode('full')
        self.result_files.setFocus()

    @staticmethod
    def _completion_task_key(item):
        path = str(getattr(item, 'report_json_path', '') or getattr(item, 'project_path', '') or item.media_path)
        return str(getattr(item, 'job_id', '') or '') + ':' + path

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
            self._refresh_completion_summaries()
            return
        item, project = task
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
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
        retryable = bool(outcome and (outcome.polish_retryable or outcome.search_retryable or outcome.core_status == 'failed'))
        self.retry_failed_button.setVisible(bool(retryable and getattr(self, '_last_run_options', None)))
        self.retry_failed_button.setEnabled(retryable)
        if outcome and outcome.polish_retryable:
            bind_text(self.retry_failed_button, '重试未完成 AI 校对')
        elif outcome and outcome.search_retryable:
            bind_text(self.retry_failed_button, '重试联网核验')
        else:
            bind_text(self.retry_failed_button, '重试失败项')
        self.retry_term_action.setVisible(bool(outcome and outcome.search_retryable and getattr(self, '_last_run_options', None)))
        self._refresh_completion_summaries()

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
            from .studio_project import load_project
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
        from .speaker_names import display_speaker_name
        from .studio_cue_table import _speaker_color
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
        from .completion_export import CompletionExportDialog
        tasks = getattr(self, "_completion_tasks", [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or tasks[index][1] is None:
            return
        item, project = tasks[index]
        # Export the currently saved project after Studio edits, never the
        # stale object loaded when the original completion event arrived.
        if item.project_path:
            from .studio_project import load_project
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
            from .recognition_result import working_reference
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
        from .studio_project import load_project
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
            from .glossary_proofread import GlossaryProofreadPage
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
        from .studio_project import load_project
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
            from .studio_find_replace import FindReplaceDialog
            dialog = FindReplaceDialog(studio, studio)
            dialog.tabs.setCurrentIndex(3)
            dialog.exec()
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
        from .studio_project import load_project
        from .studio_edit_sequence import projected_cues
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
        """跳到设置页并展开 AI 模型与密钥面板（重试失败项引导）。"""
        try:
            self._switch_page(self.settings_scroll)
        except Exception:
            return
        panel = getattr(self, "ai_panel", None)
        if panel is not None:
            try:
                panel.set_expanded(True)
                self._schedule_ai_panel_visibility(True)
            except Exception:
                pass

    def _retry_completion_stage(self, stage=None):
        if getattr(self, '_run_in_progress', False) or getattr(self, '_completion_retry_in_progress', False):
            return
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or not tasks[index][1]:
            return
        item, project = tasks[index]
        evidence = self._completion_task_evidence.get(self._completion_task_key(item), {})
        outcome = evidence.get('outcome')
        stage = stage or ('polish' if outcome and outcome.polish_retryable else 'terminology')
        if not outcome or not ((stage == 'polish' and outcome.polish_retryable) or (stage == 'terminology' and outcome.search_retryable)):
            return
        report = copy.deepcopy(evidence.get('display_payload') or {})
        snapshot = getattr(self, '_last_run_options', None)
        def review(studio):
            from .completion_retry_ui import open_completion_retry_review
            self._completion_retry_in_progress = True
            try:
                receipt = open_completion_retry_review(studio, report, snapshot, stage=stage)
                if receipt is not None:
                    evidence.setdefault('retry_receipts', []).append(receipt)
            finally:
                self._completion_retry_in_progress = False
        self._open_completion_project(item.project_path, mode='edit', source='completion_failed_stage_retry', on_ready=review)

    def _retry_failed_items(self):
        tasks = getattr(self, '_completion_tasks', [])
        index = self.result_task_selector.currentIndex()
        if 0 <= index < len(tasks) and tasks[index][1]:
            outcome = self._completion_task_evidence.get(self._completion_task_key(tasks[index][0]), {}).get('outcome')
            if outcome and outcome.result_usable and (outcome.polish_retryable or outcome.search_retryable):
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
        from .cloud_api_worker import failure_from_text
        resubmit = [problem for problem in (failure_from_text(str(getattr(item, 'error', '') or '')) for item in failed)
                    if problem and problem.get('resubmit')]
        settings_json = snapshot.settings_snapshot_json
        if settings_json and 'cloud_resubmit_confirmed' in settings_json:
            # The confirmation belongs to one retry only; never carry it forward.
            try:
                cleaned = json.loads(settings_json)
                cleaned.get('models', {}).pop('cloud_resubmit_confirmed', None)
                settings_json = json.dumps(cleaned, ensure_ascii=False)
            except (TypeError, ValueError, AttributeError):
                pass
        if resubmit:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            bind_text(box, '重新提交云端识别？', property='windowTitle')
            bind_text(box, '{reason}\n\n重新提交会再次上传音频，服务商可能再次计费。如果你不确定上次是否已经扣费，可以先到服务商控制台查看任务与账单。', reason=str(resubmit[0].get('message') or ''))
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
                                          settings_snapshot_json=settings_json)
        self.retry_failed_button.setEnabled(False)
        self._switch_page(0)
        self._refresh_media_summary()
        # 已完成阶段会命中阶段缓存，重试只重跑失败部分
        QTimer.singleShot(0, self, self._start_run)

    @staticmethod
    def _supported_paths(paths):
        from .media_intake import validate_media_paths
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
        if os.name == "nt" and not (self.isMaximized() or self.isFullScreen()):
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    packed = int(msg.lParam)
                    screen_x = ctypes.c_short(packed & 0xFFFF).value
                    screen_y = ctypes.c_short((packed >> 16) & 0xFFFF).value
                    window_rect = wintypes.RECT()
                    user32 = ctypes.windll.user32
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
                    edge = self._native_resize_edge_at(
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
        edge = self._resize_edge_at(event.position().toPoint())
        self._apply_resize_cursor(edge)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._resize_edge_at(event.position().toPoint())
            if edge and not self.isMaximized():
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
            # The card row has a bounded height per window tier: the card
            # profile follows its height, and a natural-height column would
            # otherwise keep whichever profile minimum it started with. The
            # range stays inside one profile (compact < 300 <= normal < 365);
            # narrower windows leave room for a wrapped recovery button.
            if tier == 2:
                low, high = (306, 306) if comfortable else (306, 360)
            else:
                low, high = 240, 296
            if zoom == ui_zoom.DEFAULT_PERCENT:
                self.recognition_plan.setMinimumHeight(low)
                self.recognition_plan.setMaximumHeight(high)
            else:
                # Zoomed text wraps more than the band allows: grow, never clip.
                self.recognition_plan.setMinimumHeight(ui_zoom.px(low))
                self.recognition_plan.setMaximumHeight(16777215)
            if hasattr(self, "media_row_layout") and (previous or (None,))[0] != tier:
                self._apply_media_mode(bool(getattr(self, "media_paths", None)))
                if not self.media_paths:
                    self._style_media_summary()
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
            f"font-size: {16 if ready else 22}px; font-weight: 600; color: {theme.text};"
        )
        self.media_drop_hint.setStyleSheet(
            f"color: {theme.text_secondary}; font-size: {13 if ready else 14}px;"
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
        from .settings import DEFAULT_SETTINGS, _merge_known_settings
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
            from .project_profiles import normalize_llm_config
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
                self._set_backend_combo(self.primary_asr_backend, plan.primary)
                self._set_backend_combo(self.firered_asr_backend, plan.timeline)
                self._set_backend_combo(self.qwen_asr_backend, plan.review)
                if plan.language and self.__dict__.get("recognition_language") is not None:
                    # 日语/英语推荐 also set the spoken language (2026-10-14).
                    language_index = self.recognition_language.findData(plan.language)
                    if language_index >= 0:
                        self.recognition_language.setCurrentIndex(language_index)
                if plan.language == "ja":
                    try:
                        from .ctc_alignment import set_enabled
                        set_enabled(True, self.legacy.RUNTIME_SETTINGS)
                    except (OSError, RuntimeError, ValueError):
                        pass  # the plan's backends still apply; the workshop card shows the switch
            finally:
                self._applying_recognition_plan = False
            self._mark_asr_configuration_dirty()
            self._refresh_asr_summary()
        self._refresh_recognition_recommendation()

    def _refresh_recognition_recommendation(self) -> None:
        if not hasattr(self, "recognition_mode_combo"):
            return
        primary = str(self.primary_asr_backend.currentData() or "") if hasattr(self, "primary_asr_backend") else ""
        timeline = str(self.firered_asr_backend.currentData() or "") if hasattr(self, "firered_asr_backend") else ""
        review = str(self.qwen_asr_backend.currentData() or "") if hasattr(self, "qwen_asr_backend") else ""
        language = (str(self.recognition_language.currentData() or "")
                    if self.__dict__.get("recognition_language") is not None else "")
        key = matching_plan(primary, timeline, review, language)
        blocker = bool(getattr(self, "_applying_recognition_plan", False))
        if not blocker:
            self.recognition_mode_combo.blockSignals(True)
            index = self.recognition_mode_combo.findData(key)
            if index >= 0:
                self.recognition_mode_combo.setCurrentIndex(index)
            self.recognition_mode_combo.blockSignals(False)
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
        """Spoken language and subtitle output, chosen before a task starts."""
        label = QLabel("字幕语言与输出")
        label.setObjectName("homeFieldLabel")
        layout.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(8)
        saved = dict((self.legacy.RUNTIME_SETTINGS or {}).get("subtitle_language") or {})
        self.recognition_language = FramelessPopupCombo()
        for text, value in (("自动识别语言", "auto"), ("中文", "zh"), ("日语", "ja"), ("英语", "en")):
            self.recognition_language.addItem(tr(text), value)
        self.subtitle_output = FramelessPopupCombo()
        for text, value in (("只要原文", "original"), ("只要中文译文", "translation"), ("日中双语", "bilingual")):
            self.subtitle_output.addItem(tr(text), value)
        # Translation target (any language other than the source, 2026-10-14);
        # native names like the UI language menu. Refilled by _sync_translation_targets.
        self.translation_script = user_text(FramelessPopupCombo())
        from .subtitle_translation import TARGET_LABELS, TARGETS
        for value in TARGETS:
            self.translation_script.addItem(TARGET_LABELS[value], value)
        for combo, key, default in ((self.recognition_language, "recognition_language", "auto"),
                                    (self.subtitle_output, "output", "original"),
                                    (self.translation_script, "translation_script", "zh-Hans")):
            combo.setCurrentIndex(max(0, combo.findData(saved.get(key, default))))
            combo.setObjectName("homeLanguageCombo")
            row.addWidget(combo)
        # 2026-10-13: punctuation default for new tasks (display/export only).
        from .punctuation_style import MODE_ADD, MODE_NONE, MODE_ORIGINAL, default_mode_for_new_tasks
        self.subtitle_punctuation = FramelessPopupCombo()
        self.subtitle_punctuation.setObjectName("homeLanguageCombo")
        for text, value in (("标点：保留原文", MODE_ORIGINAL), ("标点：添加标点", MODE_ADD), ("标点：不加标点", MODE_NONE)):
            self.subtitle_punctuation.addItem(tr(text), value)
        self.subtitle_punctuation.setCurrentIndex(max(0, self.subtitle_punctuation.findData(
            default_mode_for_new_tasks(self.legacy.RUNTIME_SETTINGS))))
        bind_text(self.subtitle_punctuation, '新任务的字幕标点；文稿不变，工作台里随时能换', property='toolTip')
        row.addWidget(self.subtitle_punctuation)
        row.addStretch(1)
        bind_text(self.recognition_language, '自动：按转写里的文字判断中文、日语或英语（只有汉字不算日语证据）。日语和英语改用 Qwen3-ForcedAligner 对齐字词时间，需在模型工坊下载。', property='toolTip')
        bind_text(self.subtitle_output, '译文/双语：识别完成后用已配置的 AI 文字服务把字幕翻成所选语言（只发送字幕文字，不发送音频）；原文、说话人和时间保持不变。', property='toolTip')
        bind_text(self.translation_script, '译文语言', property='toolTip')
        layout.addLayout(row)
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
            return {"recognition_language": saved.get("recognition_language", "auto"),
                    "subtitle_output": saved.get("output", "original"),
                    "translation_script": saved.get("translation_script", "zh-Hans")}
        return {"recognition_language": str(self.recognition_language.currentData() or "auto"),
                "subtitle_output": str(self.subtitle_output.currentData() or "original"),
                "translation_script": str(self.translation_script.currentData() or "zh-Hans")}

    def _sync_translation_targets(self, recognition_language):
        """Offer only targets in another language than a chosen source (all for auto)."""
        from .subtitle_translation import TARGET_LABELS, TARGETS, targets_for
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
            self._sync_translation_targets(str(self.recognition_language.currentData() or "auto"))
        options = self._subtitle_language_options()
        if save and hasattr(self, "recognition_plan_hint"):
            self._refresh_recognition_recommendation()  # 日语/英语推荐 follow the language
        translating = options["subtitle_output"] != "original"
        self.translation_script.setEnabled(translating)
        # The bilingual item names the pair: 日中双语 / 英中双语 (2026-10-14);
        # other targets read "原文 + 译文双语" / "只要译文".
        chinese_target = options["translation_script"] in ("zh-Hans", "zh-Hant")
        bilingual = self.subtitle_output.findData("bilingual")
        if bilingual >= 0:
            pair = ({"ja": "日中双语", "en": "英中双语"}.get(options["recognition_language"], "原文 + 中文双语")
                    if chinese_target else "原文 + 译文双语")
            self.subtitle_output.setItemText(bilingual, tr(pair))
        translation_only = self.subtitle_output.findData("translation")
        if translation_only >= 0:
            self.subtitle_output.setItemText(translation_only,
                                             tr("只要中文译文" if chinese_target else "只要译文"))
        hints = []
        aligner_missing = False
        if options["recognition_language"] in ("ja", "en", "auto"):
            try:
                from .asr import resolve_qwen_aligner_local_source
                aligner_missing = not resolve_qwen_aligner_local_source()
            except Exception:
                aligner_missing = False
        if options["recognition_language"] == "ja":
            hints.append("日语：不送中文时间轴模型；字词时间由 Qwen3-ForcedAligner 对齐。")
        if options["recognition_language"] == "en":
            hints.append("英语：按单词断句，单词之间保留空格；单词时间由 Qwen3-ForcedAligner 对齐。")
        if aligner_missing and options["recognition_language"] == "ja":
            hints.append("还没有安装 Qwen3-ForcedAligner：日语字幕将没有字词时间（剃刀只能按估算切），不会悄悄改用估算冒充。")
        if aligner_missing and options["recognition_language"] == "en":
            hints.append("还没有安装 Qwen3-ForcedAligner：英文字幕将没有单词时间（剃刀只能按估算切），不会悄悄改用估算冒充。")
        self.aligner_download_button.setVisible(aligner_missing and options["recognition_language"] in ("ja", "en"))
        if translating:
            from .subtitle_translation import TARGET_LABELS
            hints.append(tr("完成识别后翻译成{value0}，发送字幕文字到已配置的 AI 文字服务（可能产生费用）。"
                            "译文语言与识别语言相同时不翻译。",
                            value0=TARGET_LABELS.get(options["translation_script"], "")))
        punctuation = str(self.subtitle_punctuation.currentData() or "original") \
            if self.__dict__.get("subtitle_punctuation") is not None else "original"
        if punctuation != "original":
            from .punctuation_style import preview_rows
            sample = preview_rows(None, punctuation, limit=1)[0][1]
            hints.append(tr("标点效果：{value0}", value0=sample))
        bind_text(self.subtitle_language_hint, " ".join(str(hint) for hint in hints))
        self.subtitle_language_hint.setVisible(bool(hints))
        if save:
            try:
                section = self.legacy.RUNTIME_SETTINGS.setdefault("subtitle_language", {})
                section.update(recognition_language=options["recognition_language"],
                               output=options["subtitle_output"],
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

    def _refresh_asr_summary(self):
        if not hasattr(self, "asr_panel"):
            return
        self._schedule_next_step_probe()
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
            "whisper_turbo": "Whisper",
            "paraformer": "Paraformer",
            "off": translate("已关闭", language),
        }
        primary_backend = str(self.primary_asr_backend.currentData())
        if sys.platform == 'darwin':
            primary_short['sensevoice'] = 'SenseVoice · CPU'
            review_short['sensevoice'] = 'SenseVoice · CPU'
        qwen_backend = str(self.qwen_asr_backend.currentData())
        firered_backend = str(self.firered_asr_backend.currentData())
        # 主页角色卡在 API 生效时显示具体服务商 · 模型（三十三轮：要能
        # 看出当前用的是哪个 API）。
        if primary_backend == "api":
            from .model_workshop import _api_combo_label

            api_label, _ready = _api_combo_label(self.legacy.RUNTIME_SETTINGS.get("models", {}))
            primary_short["api"] = api_label
        from .llm_config import read_asr_api_key

        _models_cfg = self.legacy.RUNTIME_SETTINGS.get("models", {})
        from .recognition_choices import cloud_asr_readiness
        key_ready, self._cloud_asr_block_reason = cloud_asr_readiness(
            _models_cfg, typed_key=self.qwen_asr_api_key.text())
        self.asr_panel.set_summary(
            " / ".join(
                (
                    primary_short.get(primary_backend, primary_backend),
                    review_short.get(qwen_backend, qwen_backend),
                    timeline_short.get(firered_backend, firered_backend),
                )
            )
        )
        installed = installed_model_keys(APP_ROOT)
        required = {
            "primary": {
                "moss": {"moss", "firered_vad", "speaker_embedding"},
                "firered": {"firered_aed"},
                "qwen_local": {"qwen_asr"},
                "firered_llm": {"firered_llm"},
                "whisper_turbo": {"whisper_turbo"},
                "sensevoice": {"sensevoice"},
                "paraformer": {"paraformer"},
                "funasr_nano": {"funasr_nano"},
                "glm_asr_nano": {"glm_asr_nano"},
                "canary_qwen": {"canary_qwen", "canary_qwen_tokenizer"},
                "api": set(),
            },
            "review": {
                "local": {"qwen_asr"},
                "firered_llm": {"firered_llm"},
                "whisper_turbo": {"whisper_turbo"},
                "sensevoice": {"sensevoice"},
                "funasr_nano": {"funasr_nano"},
                "api": set(),
            },
            "timeline": {
                "local": {"firered_aed"},
                "qwen_aligner": {"qwen_aligner"},
                "whisper_turbo": {"whisper_turbo"},
                "paraformer": {"paraformer"},
                "off": set(),
            },
        }

        # 2026-10-14: a component this computer cannot run (CUDA without an
        # NVIDIA GPU, MLX off Apple Silicon) is said before start, not after.
        from .recognition_choices import host_profile, unavailable_on_host
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

        # 角色卡：model 名是视觉主体；卡点击 → 工坊对应角色。
        if hasattr(self, "recognition_plan"):
            role_specs = (
                ("primary", primary_backend, primary_short),
                ("timeline", firered_backend, timeline_short),
                ("review", qwen_backend, review_short),
            )
            for role, backend, labels in role_specs:
                card = self.recognition_plan.cards[role]
                kind, status, tone = _status(role, backend)
                model_name = labels.get(backend, backend)
                if backend == "api" and status == "未配置":
                    recovery = "配置 API"
                elif status in _HOST_LIMIT_STATUSES:
                    recovery = _HOST_LIMIT_RECOVERY
                elif status == "需要下载":
                    recovery = "安装模型"
                else:
                    recovery = ""
                card.set_state(
                    translate(model_name, language),
                    translate(kind, language),
                    translate(status, language),
                    tone,
                    translate(recovery, language),
                )
                if sys.platform == 'darwin' and backend == 'sensevoice':
                    from .platform_macos import macos_copy
                    card.setToolTip(macos_copy(
                        '当前采用 CPU 路线；MPS 设备可用性与模型算子支持分开验证，模型 MPS 适配尚未验证。',
                        'CPU is selected. MPS device availability and model/operator support require separate validation; model MPS support is not verified.',
                        '現在は CPU を使用します。MPS の利用可否とモデル／演算子の対応は別々に検証します。モデルの MPS 対応は未検証です。'))

        # CTA 状态：识别方案与 N 个词库就绪
        if hasattr(self, "action_status"):
            problems = []
            plan_items = []
            for role, backend in (
                ("primary", primary_backend),
                ("timeline", firered_backend),
                ("review", qwen_backend),
            ):
                _kind, status, _tone = _status(role, backend)
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
                elif language in ("ja", "zh-Hant", "ko"):
                    text = "⚠ " + translate("开始前还需处理：", language)
                else:
                    text = "⚠ 开始前还需处理："
                self.action_status.setText(text)
            else:
                self.action_status.setObjectName("statusGood")
                if language == "en":
                    text = f"✔ Recognition plan and {glossary_count} term libraries are ready"
                elif language in ("ja", "zh-Hant", "ko"):
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
            from twobyteasr.model_workshop import _model_logo, MODELS as _MODELS
            for m in _MODELS[:4]:
                try:
                    _ = _model_logo(m, QSize(24, 24))
                except Exception:
                    pass
        except Exception:
            pass
        capability_worker = None
        try:
            from twobyteasr.studio_render import start_encoder_capability_scan

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
            # Selection changes already update the home controls through
            # _apply_workshop_backend. Refresh only if a download changed local
            # availability while this picker was open.
            if frozenset(self.workshop_page._installed) != installed_before:
                self._refresh_available_asr_choices()
                self._refresh_asr_summary()
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
        from .design.presentation import button_role, glyph_button
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
        from .llm_config import read_oss_credentials

        saved_oss_id, saved_oss_secret = read_oss_credentials()
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
        from .llm_config import read_asr_api_key, read_spark_credentials, save_spark_credentials
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
            oss_group.setVisible(uses_filetrans)
            oss_test_button.setVisible(uses_filetrans)
            status.clear()
            if uses_filetrans:
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
        dialog_layout.addLayout(form)
        dialog_layout.addWidget(spark_group)
        # OSS 中转存储区（默认隐藏；选中 filetrans 服务时显示）
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
                from .llm_config import fetch_openai_compatible_models

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
                from .temp_audio_storage import OssTemporaryStorage

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
            from .llm_config import save_oss_credentials

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
            }
            self.legacy.configure_runtime_asr(models_patch)
            return ""

        def save():
            if provider.currentData()=='spark_asr_v2':
                try:
                    from .llm_config import validate_qwen_asr_endpoint
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
                oss_error = _persist_oss_fields()
                if oss_error:
                    status.setText(oss_error)
                    status.setProperty("ok", False)
                    return
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
                from .temp_audio_storage import maybe_cleanup_stale_objects

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
                from .terminology import snapshot_glossaries
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
        language = getattr(self, "_ui_language", current_language())
        from .llm_config import effective_ai_identity
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
        except (ValueError, KeyError) as exc:
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

    def _mark_ai_configuration_dirty(self, *_args):
        if getattr(self, "_applying_profile", False):
            return
        self._mark_profile_configuration_dirty()
        if not hasattr(self, "ai_save_status"):
            return
        self.ai_save_status.setObjectName("statusWarn")
        bind_text(self.ai_save_status, '有未保存的 AI 配置修改')
        self.ai_save_status.style().unpolish(self.ai_save_status)
        self.ai_save_status.style().polish(self.ai_save_status)

    def _save_ai_configuration(self, *, show_feedback: bool, require_ready: bool = False) -> bool:
        try:
            p = self.polish_editor.values()
            g = self.group_editor.values()
            _secret_save_trace("before_save", self.polish_editor, p, extra={"editor": "polish"})
            _secret_save_trace("before_save", self.group_editor, g, extra={"editor": "group"})
            # P8C-R3.1 三态语义：REPLACE 覆写、CLEAR 显式删除、UNCHANGED 完全
            # 不触碰已存密钥。空输入框不再是“删除”。
            try:
                pk = (p.get("key") or "").strip()
                gk = (g.get("key") or "").strip()
                if p.get("key_state") == "clear":
                    delete_api_key_for(p.get("provider", "custom"), p.get("base_url", ""))
                elif pk:
                    save_api_key_for(p.get("provider", "custom"), p.get("base_url", ""), pk)
                if g.get("key_state") == "clear":
                    delete_api_key_for(g.get("provider", "custom"), g.get("base_url", ""))
                elif gk:
                    save_api_key_for(g.get("provider", "custom"), g.get("base_url", ""), gk)
            except Exception:
                pass
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
            )
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
        self.polish_editor.key.clear()
        self.group_editor.key.clear()
        self.polish_editor._key_state = "unchanged"
        self.group_editor._key_state = "unchanged"
        self.polish_editor.refresh_secret_status()
        self.group_editor.refresh_secret_status()
        for editor in (self.polish_editor, self.group_editor):
            editor._settings_ref = self.legacy.RUNTIME_SETTINGS
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
        self.ai_save_status.setObjectName("statusWarn" if missing else "statusGood")
        (bind_text(self.ai_save_status, translate('配置已保存；运行前还需填写：', language) + '、'.join(missing)) if missing else bind_text(self.ai_save_status, credential_storage_notice(language) if session_credentials_enabled() else translate('AI 配置与密钥已保存，重启后仍会保留', language)))
        self.ai_save_status.style().unpolish(self.ai_save_status)
        self.ai_save_status.style().polish(self.ai_save_status)
        return True

    def _apply_unified_glm_mode(self, checked: bool):
        use_ai_grouping = self.ai_grouping.isChecked()
        enable_ai_polish = self.ai_polish.isChecked()
        self.unified_glm.setEnabled(use_ai_grouping and enable_ai_polish)
        unified = bool(checked and use_ai_grouping and enable_ai_polish)
        self.polish_editor.setVisible(enable_ai_polish and not unified)
        self.group_editor.setVisible(use_ai_grouping)
        self.share_key.setVisible(use_ai_grouping and not unified)
        self.group_editor.title_label.setText(
            "统一校对与断句模型" if unified else "全文断句模型"
        )
        self.group_editor.setToolTip(
            "这一套模型、地址和密钥将同时用于字幕校对与全文断句。"
            if unified
            else "仅用于全文断句。"
        )
        self._refresh_ai_summary()

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
        from twobyteasr.hardware import (
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
            missing_models = missing_selected_local_models(self._asr_values())
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
                from twobyteasr.environment import fast_preflight, required_environment_roles
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
            if not self._save_ai_configuration(show_feedback=True, require_ready=not local_analysis):
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
            from .terminology import snapshot_glossaries
            language_options = self._subtitle_language_options()
            options = RunOptions(
                **language_options,
                settings_snapshot_json=json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False),
                glossary_snapshot_json=json.dumps(
                    snapshot_glossaries(self.legacy, enabled_glossary_ids if terms_enabled else ()).to_dict(),
                    ensure_ascii=False),
                content_name=game_name,
                enable_domain_terms=terms_enabled,
                enable_term_search=bool(getattr(self, 'term_search', None) and self.term_search.isChecked()),
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
                speaker_source=__import__('twobyteasr.speaker_strategy',fromlist=['resolve']).resolve(
                    self.legacy.RUNTIME_SETTINGS,(getattr(self, "_studio_recognition_context", None) or {}).get("speaker_source")),
            )
            self._last_run_options = options
            self._launch_pipeline_worker(options)
            launched = True
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
        metrics, quiet = [], None
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
            metrics.append((tr('已返回批次'), f"{payload.get('completed_batches', 0)} / {payload.get('total_batches', 0)}"))
            metrics.append((tr('临时转写'), tr('{count} 条', count=payload.get('cue_count', 0))))
        elif kind == 'cloud':
            if payload.get('total'):
                metrics.append((tr('已完成批次'), f"{payload.get('done', 0)} / {payload['total']}"))
            if live.get('at'):
                quiet = since(live['at'])
                metrics.append((tr('最近活动'), tr('{seconds} 秒前', seconds=int(quiet))))
        self.stage_metrics.set_metrics(metrics)
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
        self._set_stage_note(note, detail)

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
                                            'final': '已保存的字幕'}.get(family, ''))
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
            return (int(payload.get('completed_batches') or 0) > int(prior.get('completed_batches') or 0)
                    or int(payload.get('cue_count') or 0) > int(prior.get('cue_count') or 0))
        return False

    def _handle_event(self, event):
        active_job = getattr(self, '_active_job_id', '')
        if active_job and str(getattr(event, 'job_id', '') or '') != active_job:
            return
        degraded = self.__dict__.setdefault('_phase_degraded', {})
        if event.kind in {'asr_evidence_delta', 'cue_delta', 'terminology_polish_final'} and hasattr(self, 'recognition_preview'):
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
        elif event.kind == "cue_delta":
            if getattr(self, "_studio_recognition_context", None):
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
        elif event.kind == "cloud_batch_completed":
            stage = max(self._active_stages) if self._active_stages else None
            if stage is not None:
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
            from .recognition_recovery import recover_report
            from .recognition_outcome import RecognitionDeliveryWitness, normalize_recognition_outcome
            from .studio_project import load_project
            from .studio_edit_sequence import projected_cues
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
        from .recognition_outcome import normalize_recognition_outcome, normalize_recognition_queue
        from .studio_project import load_project
        from .studio_edit_sequence import projected_cues
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
                        from .recognition_result import verify_result_reference
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
            self.result_task_selector.addItem(Path(item.media_path).name)
            self.result_task_selector.setItemData(self.result_task_selector.count()-1, Path(item.media_path).name, Qt.ItemDataRole.ToolTipRole)
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
            self._show_task_notification(*_completion_notification_spec(result, outcomes))
        elif studio_context and (failure_count or cancel_count):
            self.studio_page.fail_recognition_runtime(
                "任务已取消" if cancel_count and not failure_count else "识别失败，请检查模型与运行日志"
            )
            # 四十二轮：识别转后台后用户可能已离开 Studio 页——失败/取消也要
            # 任务通知，否则只剩藏在字幕列表里的芯片，用户无感知。
            self._show_task_notification(*_completion_notification_spec(result, outcomes))
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

    def closeEvent(self, event):
        if getattr(self, "_studio_close_pending", False) and not getattr(
            self, "_studio_close_finalizing", False
        ):
            event.ignore()
            return
        if not getattr(self, "_studio_close_finalizing", False) and not self._prepare_glossary_for_task():
            event.ignore()
            return
        worker_running = bool(self.worker and self.worker.isRunning())
        if worker_running:
            answer = QMessageBox.question(
                self,
                tr('任务仍在运行'),
                tr('要安全取消当前任务并关闭窗口吗？'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.token.cancel()
            self.worker.requestInterruption()
            self._worker_close_cleanup_done = False
            self._worker_close_terminated = False
            self._worker_close_hard_deadline = time.monotonic() + 7.0
            self.worker.finished.connect(self._worker_close_finished)
            QTimer.singleShot(5_000, self, self._force_close_worker)
        else:
            self._worker_close_cleanup_done = True
        studio = self.built_page("studio")
        if studio is not None and not getattr(self, "_studio_close_finalizing", False):
            guard = getattr(getattr(studio, "project_controller", None), "dirty_guard", None)
            if guard is not None and not guard.confirm("退出应用"):
                event.ignore()
                return
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
            from .secondary_video import set_defer_media_destruction

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


class GlossaryPickerDialog(QWidget):
    """本批词库多选器（hosted inside ModalHost）。

    No top-level native window. Host provides title/X/backdrop/Esc.
    Content shows at final size immediately; only backdrop fades.
    """

    def __init__(self, owner: "MainWindow", container: QWidget | None = None):
        parent = container if container is not None else owner
        super().__init__(parent)
        self.owner = owner
        self.legacy = owner.legacy
        self._selected: set[str] = set(owner._enabled_glossary_ids())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        hint = QLabel("本批字幕同时使用选中的词库；关闭一个不会影响其它词库。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        bind_text(self.search, '搜索词库…', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("glossaryPickerList")
        layout.addWidget(self.list_widget, 1)
        self.select_all = AnimatedButton("全选")
        self.select_all.setObjectName("flat")
        self.select_all.clicked.connect(self._toggle_select_all)
        layout.addWidget(self.select_all, 0, Qt.AlignmentFlag.AlignRight)
        actions = QHBoxLayout()
        actions.addStretch(1)
        save_button = AnimatedButton("确定")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._accept_choice)
        actions.addWidget(save_button)
        close_button = AnimatedButton("取消")
        close_button.setObjectName("outline")
        close_button.clicked.connect(self._cancel_choice)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self._result = None
        self._populate()

    def _accept_choice(self):
        self._result = self.selected_ids()
        # Notify host to close (if hosted) or do nothing if used directly.
        mw = self._find_main_window()
        if mw and hasattr(mw, "_modal_host") and mw._modal_host.isVisible():
            mw._modal_host._request_close()
        else:
            # Fallback if somehow not hosted: try to close parent dialog if any.
            p = self.parentWidget()
            while p and not isinstance(p, QDialog):
                p = p.parentWidget()
            if p:
                p.accept()
            else:
                self.hide()

    def _cancel_choice(self):
        self._result = None
        mw = self._find_main_window()
        if mw and hasattr(mw, "_modal_host") and mw._modal_host.isVisible():
            mw._modal_host._request_close()
        else:
            p = self.parentWidget()
            while p and not isinstance(p, QDialog):
                p = p.parentWidget()
            if p:
                p.reject()
            else:
                self.hide()

    def _find_main_window(self):
        p = self.parentWidget()
        while p:
            if hasattr(p, "_modal_host"):
                return p
            p = p.parentWidget()
        return None

    def selected_ids(self) -> list[str]:
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return list(dict.fromkeys(result))

    def take_result(self):
        r = self._result
        self._result = None
        return r

    # Keep the rest of the behavior identical.

    def _available_entries(self) -> list[tuple[str, str]]:
        """(display_name, identity) 可用词库：profiles + learned + history。"""
        catalog = getattr(self.legacy, "glossary_catalog", None)
        if callable(catalog):
            return [(str(row["name"]), str(row["id"])) for row in catalog()]
        entries: dict[str, str] = {}
        profiles = getattr(self.legacy, "load_game_profiles", lambda: {})() or {}
        for name in profiles:
            entries[self.legacy.runtime_game_identity(name)] = str(name)
        learned = getattr(self.legacy, "load_learned_term_payload", lambda: {"games": {}})()
        for _key, entry in (learned or {}).get("games", {}).items():
            if isinstance(entry, dict):
                name = str(entry.get("game", ""))
                if name:
                    entries.setdefault(self.legacy.runtime_game_identity(name), name)
        return [(name, identity) for identity, name in entries.items()]

    def _populate(self):
        self.list_widget.clear()
        for name, identity in self._available_entries():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, identity)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if identity in self._selected else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(item)

    def _apply_filter(self, text=""):
        query = text.strip().casefold()
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def _toggle_select_all(self):
        all_checked = all(
            self.list_widget.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.list_widget.count())
        )
        state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def selected_ids(self) -> list[str]:
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return list(dict.fromkeys(result))

TERM_LIBRARY_PAGE_QSS = NAVIGATION_QSS + f"""
QWidget#termLibraryPage {{
    background: transparent;
}}
QFrame#recognitionRoleCard[density="compact"] QLabel#recognitionModelName {{ font-size: 18px; }}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionModelName {{ font-size: 22px; }}
QFrame#termWorkspaceSidebar {{
    background: #f4f1ea;
    border: 1px solid #ded7ca;
    border-radius: 12px;
}}
QLabel#termWorkspaceLabel {{
    color: {MUTED};
    font-weight: 600;
}}
QLabel#termSyncStatus {{
    color: {GREEN};
    font-size: 12px;
}}
"""


def build_term_library_page_qss(theme=None) -> str:
    from twobyteasr.qss_retheme import retheme_qss

    from twobyteasr.design.semantic_qss import build_semantic_qss
    active = theme or _active_theme_definition()
    return retheme_qss(TERM_LIBRARY_PAGE_QSS, active) + build_semantic_qss(active)


class TermLibraryPage(QWidget):
    """Resident workbench shell around the existing high-performance library."""

    recognition_requested = Signal()
    workshop_requested = Signal()
    history_requested = Signal()

    def __init__(self, owner: "MainWindow", parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.setObjectName("termLibraryPage")
        self.setStyleSheet(build_term_library_page_qss())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        from twobyteasr.ui_navigation import WorkspaceSidebar
        sidebar = WorkspaceSidebar("terms", object_name="termWorkspaceSidebar")
        side = sidebar.body
        self.workspace_navigation = sidebar.navigation
        self.workspace_navigation.recognition_requested.connect(self.recognition_requested)
        self.workspace_navigation.workshop_requested.connect(self.workshop_requested)
        self.workspace_navigation.history_requested.connect(self.history_requested)
        side.addStretch(1)
        sync_status = QLabel("●  官方词库已同步")
        sync_status.setObjectName("termSyncStatus")
        side.addWidget(sync_status)
        outer.addWidget(sidebar)

        self._content_layout = outer
        self.library = None
        self._placeholder = QFrame()
        self._placeholder.setObjectName("termLibraryContent")
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.addStretch(1)
        loading = QLabel("正在载入术语库…")
        loading.setObjectName("muted")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(loading)
        placeholder_layout.addStretch(1)
        outer.addWidget(self._placeholder, 1)

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(build_term_library_page_qss())

    def _ensure_library(self):
        if self.library is not None:
            return self.library
        self.library = TermLibraryDialog(self.owner, self, page_mode=True)
        self.owner._term_library_dialog = self.library
        self._content_layout.replaceWidget(self._placeholder, self.library)
        self._placeholder.hide()
        self.library.show()
        language = getattr(self.owner, "_ui_language", current_language())
        apply_ui_language(self, language)
        self.setProperty("_2b_language_applied", language)
        return self.library

    def prepare_for_show(self):
        self.workspace_navigation.set_active("terms")
        library = self._ensure_library()
        current = library.game_list.currentItem()
        target = library._canonical(library.game_box_text())
        if target:
            target_identity = library._game_identity(target)
            matching = None
            for index in range(library.game_list.count()):
                item = library.game_list.item(index)
                if library._game_identity(
                    item.data(Qt.ItemDataRole.UserRole)
                ) == target_identity:
                    matching = item
                    break
            if matching is None:
                matching = library.add_game_item(target)
            if current is None and matching is not None:
                library.game_list.setCurrentItem(matching)
                return
        if current is None and library.game_list.count():
            library.game_list.setCurrentRow(0)
            return
        QTimer.singleShot(0, library.refresh_current_game)


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
    from .ui_motion import system_reduced_motion

    preferences = read_studio_preferences()
    motion_preference = preferences.get("reduce_motion")
    app.setProperty(
        "reduceMotion",
        system_reduced_motion() if motion_preference is None else bool(motion_preference),
    )
    if os.environ.get("TWOBYTEASR_AUDIT_TOP_LEVELS") == "1":
        from twobyteasr.window_audit import TopLevelWindowAudit

        app._top_level_window_audit = TopLevelWindowAudit(
            app,
            Path(os.environ.get("TWOBYTEASR_AUDIT_TOP_LEVEL_PATH", "tmp/top-level-windows.jsonl")),
        )
    app.setApplicationName("2ByteASR")
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
    from .runtime_paths import single_scan
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
        from .studio_acceptance_audit import start_acceptance
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
    if not onboarding.load_state().get("tour_done"):
        if window.pages.currentWidget() is window.__dict__.get("settings_scroll"):
            QTimer.singleShot(500, window._start_home_tour)
        else:
            window._home_tour_pending = True  # e.g. the workshop opened for a download


def _open_quick_setup(parent) -> bool:
    """Big cards: local / cloud / light (Mac: Apple chip). ``自己选择模型…`` opens the detailed dialog."""
    try:
        from .quick_setup import QuickSetupDialog
        dialog = QuickSetupDialog(parent, size_of=lambda backends: GuidedSetupDialog.estimate_size(*backends))
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.choice is None:
            return False
        if dialog.choice == "custom":
            return _open_guided_setup(parent)
        primary, timeline, review = dialog.backends
        if dialog.choice == "cloud":
            _apply_setup_choice(parent, primary, timeline, review, (), open_workshop=False, auto_download=False)
            QTimer.singleShot(0, parent._open_api_setup_guide)
            return True
        keys = GuidedSetupDialog.download_keys_for(primary, timeline, review)
        _apply_setup_choice(parent, primary, timeline, review, keys, open_workshop=True, auto_download=True)
        return True
    except Exception:
        traceback.print_exc()
        _startup_mark("FIRST_RUN_WIZARD_FAILED", traceback=traceback.format_exc())
        return False


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


def _apply_setup_choice(parent, primary, timeline, review, download_keys, *, open_workshop, auto_download):
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
    if open_workshop:
        def open_selected_combination():
            parent._open_model_workshop()
            parent.workshop_page.focus_primary_backend(primary)
            if auto_download and download_keys:
                parent.workshop_page.download_combination(
                    download_keys,
                    "首次选择的字幕识别组合",
                    auto_start=True,
                )

        QTimer.singleShot(0, open_selected_combination)


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
