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
from dataclasses import dataclass
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
from twobyteasr.i18n import apply_ui_language, current_language, save_language, translate, tr, bind_text, user_text
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
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.ui_navigation import NAVIGATION_QSS, WorkspaceNavigation
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
    check_for_update,
    current_version,
    download_update,
    launch_update_helper,
)
from twobyteasr.startup_trace import mark as _startup_mark


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
    "spark_asr_v2": {
        "short": "讯飞 Spark V2", "label": "讯飞 Spark-ASR-2.0（原生 WSS）",
        "protocol": "spark_wss", "model": "spark_asr_v2",
        "url": "wss://iat.cn-huabei-1.xf-yun.com/v1",
    },
    "qwen31_flash": {
        "short": "Qwen 3.1 Flash", "label": "Qwen Audio 3.1 ASR Flash（短音频）",
        "protocol": "dashscope_asr_flash", "model": "qwen-audio-3.1-asr-flash",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
    },
    "qwen31_filetrans": {
        "short": "Qwen 3.1 Filetrans", "label": "Qwen Audio 3.1 ASR Filetrans（长文件）",
        "protocol": "dashscope_filetrans", "model": "qwen-audio-3.1-asr-flash-filetrans",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
    },
    "dashscope": {
        "short": "阿里云 Qwen",
        "label": "阿里云百炼 Qwen ASR",
        "protocol": "dashscope_multimodal",
        "model": "qwen3-asr-flash",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
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
        "label": "OpenRouter 转写（MAI · 字级时间戳）",
        "protocol": "openrouter_verbose_json",
        "model": "microsoft/mai-transcribe-2",
        "url": "https://openrouter.ai/api/v1/audio/transcriptions",
    },
    "azure": {
        "short": "Azure",
        "label": "Azure 转写（MAI）",
        "protocol": "azure_transcription",
        "model": "microsoft/mai-transcribe-2",
        "url": "",
    },
    "dashscope_qwen_audio": {
        "short": "Qwen-Audio",
        "label": "阿里云 Qwen-Audio 3.0",
        "protocol": "dashscope_multimodal",
        "model": "qwen-audio-3.0-asr-flash",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    },
    # 四十轮：录音文件识别（异步 filetrans）——整段上传用户 OSS 临时对象，
    # 预签名 HTTPS URL 提交 Qwen；词级时间戳 + 说话人分离（speaker_id）。
    # 需要 OSS 配置（配置弹窗 OSS 分组），AccessKey 走 DPAPI。
    # 四十一轮：地址换用户推荐的工作台域名（四十分轮默认的 dashscope 中心域名
    # 对该模型在执行期报 InvalidParameter.ParseError）。
    "qwen_filetrans": {
        "short": "百炼 Filetrans",
        "label": "阿里云 Qwen 录音文件识别（字级+说话人）",
        "protocol": "dashscope_filetrans",
        "model": "qwen-audio-3.0-asr-flash-filetrans",
        "url": "https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription",
    },
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


def _completion_notification_spec(result):
    """Build a concise, user-visible completion message for every queue outcome."""
    success_count = len(result.successes)
    failure_count = len(result.failures)
    cancel_count = len(result.cancelled)
    skipped_count = len(result.skipped)
    if failure_count:
        title = "字幕生成部分失败" if success_count else "字幕生成失败"
        icon = (
            QMessageBox.Icon.Warning
            if success_count
            else QMessageBox.Icon.Critical
        )
        message = (
            f"本批任务已结束：成功 {success_count} 个，失败 {failure_count} 个。"
            "请查看结果页中的失败原因。"
        )
        details = "\n".join(
            f"{Path(item.media_path).name}：{item.error or '任务失败但没有返回异常文本，请查看完整运行日志。'}"
            for item in result.failures[:3]
        )
    elif cancel_count:
        title = "字幕任务已取消"
        icon = QMessageBox.Icon.Warning
        message = (
            f"任务已安全停止：成功 {success_count} 个，取消 {cancel_count} 个。"
        )
        details = "已完成的字幕会保留，尚未开始或未完成的素材不会写入成片。"
    else:
        title = "字幕生成完成"
        icon = QMessageBox.Icon.Information
        message = (
            f"已成功生成 {success_count} 个素材的字幕。"
            if success_count
            else f"任务已完成，跳过 {skipped_count} 个已有结果。"
        )
        details = "可以在结果页查看字幕、分轨和任务报告路径。"
    return title, message, icon, details


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
                ratio = event.position().x() / max(1, self.width())
                normal = self._window.normalGeometry()
                self._window.showNormal()
                self._drag_offset = QPoint(
                    int(normal.width() * ratio),
                    max(8, int(event.position().y())),
                )
                target = global_pos - self._drag_offset
                # 2026-09-19：DPI/显示器变更后 normalGeometry 可宽于当前屏幕，
                # 换算 x 可为负（窗口出屏=内容左移、左侧固定区"消失"），钳回可用区。
                screen = self._window.screen().availableGeometry()
                self._window.move(
                    min(max(target.x(), screen.left()), screen.right() - normal.width()),
                    min(max(target.y(), screen.top()), screen.bottom() - 40),
                )
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
        self.details_label.setVisible(bool(details))
        self.details_label.setStyleSheet(
            f"color: {theme.text}; background: {self.tint}; border: 1px solid {theme.border}; border-radius: 12px; "
            "padding: 10px 12px; font-size: 13px;"
        )
        card_layout.addWidget(self.details_label)

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
    """Append one log block, keep vertical tail-follow AND the left edge.

    QTextEdit.append() parks the text cursor at the END of the appended
    block. Under NoWrap, any later ensureCursorVisible() pass (page reveal,
    details-row expand, window resize) scrolls the view to the far right of
    a long line — the 2026-09-10s run-signature lines made the completion
    log open showing only line tails. Park the cursor at the line start so
    every layout pass lands on column 0, then pin both scrollbars
    explicitly: horizontal to the minimum, vertical to the tail.
    """
    edit.append(fragment)
    cursor = edit.textCursor()
    cursor.movePosition(
        QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor
    )
    edit.setTextCursor(cursor)
    vertical = edit.verticalScrollBar()
    if vertical is not None:
        vertical.setValue(vertical.maximum())
    keep_log_view_at_left(edit)


def set_log_html_keep_left(edit, html_text: str) -> None:
    """Replace the whole log (task reload/completion fill) from the left."""
    edit.setHtml(html_text)
    keep_log_view_at_left(edit)


def _active_theme_definition():
    """Theme tokens for locally-styled runtime widgets (never warm literals)."""
    from twobyteasr.theme_manager import theme_key

    return theme_definition(theme_key())


class ProgressPhaseCard(QFrame):
    """Compact cartoon-like phase card with explicit pending/active/done states."""

    def __init__(self, icon_name: str, title: str, subtitle: str, accent: str):
        super().__init__()
        self.setObjectName("phaseCard")
        self.icon_name = icon_name
        self.accent = accent
        self.setMinimumHeight(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(42, 42)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 800;")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        self.state_label = QLabel("等待")
        self.state_label.setStyleSheet("font-size: 12px; font-weight: 700;")
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addWidget(self.state_label)
        layout.addLayout(text_layout, 1)
        self._state = ""
        self._pulse_light = False
        self._pulse = QTimer(self)
        self._pulse.setInterval(900)
        self._pulse.setTimerType(Qt.TimerType.CoarseTimer)
        self._pulse.timeout.connect(self._toggle_active_pulse)
        self.set_state("pending")

    def _state_palette(self, state: str):
        theme = _active_theme_definition()
        return {
            "pending": (theme.surface, theme.border_strong, theme.text_muted, "等待"),
            "active": (theme.warning_soft, theme.accent, theme.accent, "进行中"),
            "done": (theme.accent_soft, theme.success, theme.success, "已完成"),
            "failed": (theme.danger_soft, theme.danger, theme.danger, "需处理"),
        }.get(state, (theme.surface, theme.border_strong, theme.text_muted, "等待"))

    def _repaint_state(self) -> None:
        background, border, icon_color, _label = self._state_palette(self._state)
        border_width = 2 if self._state == "active" else 1
        self.setStyleSheet(
            f"QFrame#phaseCard {{ background: {background}; border: {border_width}px solid {border}; "
            "border-radius: 17px; }}"
        )
        theme = _active_theme_definition()
        self.icon_label.setPixmap(_icon(self.icon_name, icon_color).pixmap(QSize(25, 25)))
        self.icon_label.setStyleSheet(
            f"background: {theme.surface_elevated}; border: 2px solid {icon_color}; border-radius: 21px;"
        )
        self.state_label.setStyleSheet(f"color: {icon_color}; font-size: 12px; font-weight: 800;")

    def refresh_theme_palette(self) -> None:
        self._repaint_state()

    def _toggle_active_pulse(self):
        if self._state != "active":
            return
        self._pulse_light = not self._pulse_light
        theme = _active_theme_definition()
        background, border, _icon_color, _label = self._state_palette("active")
        self.setStyleSheet(
            f"QFrame#phaseCard {{ background: {background if self._pulse_light else theme.accent_soft}; "
            f"border: 2px solid {border}; border-radius: 17px; }}"
        )

    def set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        _background, _border, _icon_color, label = self._state_palette(state)
        self._repaint_state()
        bind_text(self.state_label, label)
        if state == "active":
            self._pulse_light = False
            self._pulse.start()
        else:
            self._pulse.stop()


class RunningIndicator(QLabel):
    """Small animated status pill that remains readable without relying on motion."""

    def __init__(self, parent=None):
        super().__init__("运行中", parent)
        self._step = 0
        self._running = False
        self._apply_theme()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(320)
        self._timer.timeout.connect(self._tick)

    def _apply_theme(self) -> None:
        theme = _active_theme_definition()
        self.setStyleSheet(
            f"background:{theme.warning_soft}; color:{theme.warning}; border:1px solid {theme.warning}; "
            "border-radius:11px; padding:4px 10px; font-size:11px; font-weight:800;"
        )

    def refresh_theme_palette(self) -> None:
        self._apply_theme()

    def _tick(self):
        self._step = (self._step + 1) % 4
        bind_text(self, '运行中{value0}', value0=' ·' * self._step)

    def set_running(self, running: bool):
        running = bool(running)
        if running == self._running:
            return
        self._running = running
        if running:
            self._timer.start()
            self._tick()
        else:
            self._timer.stop()
            self._step = 0
            bind_text(self, '阶段衔接')


from .i18n import join_text
from .recognition_status_text import recognition_event_text


class TaskEventCard(QFrame):
    """Rounded, glanceable representation of one structured pipeline event."""

    ICONS = {
        "准备": "fa5s.hourglass-start",
        "开始": "fa5s.play",
        "完成": "fa5s.check",
        "失败": "fa5s.exclamation",
        "缓存": "fa5s.database",
        "并行": "fa5s.project-diagram",
        "批次": "fa5s.layer-group",
        "素材": "fa5s.file-video",
        "取消": "fa5s.stop",
        "自愈": "fa5s.shield-alt",
    }

    def __init__(self, badge: str, message: str, color: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(48)
        self._badge = str(badge)
        self._message = str(message)
        self._accent = str(color)
        theme = _active_theme_definition()
        self._apply_theme(theme)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 7, 10, 7)
        row.setSpacing(9)
        icon = QLabel()
        icon.setObjectName("eventIcon")
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(_icon(self.ICONS.get(badge, "fa5s.circle"), "#ffffff").pixmap(QSize(12, 12)))
        row.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        badge_label = bind_text(QLabel(), badge)
        badge_label.setObjectName("eventBadge")
        message_label = bind_text(QLabel(), message)
        message_label.setObjectName("eventMessage")
        message_label.setWordWrap(True)
        text.addWidget(badge_label)
        text.addWidget(message_label)
        row.addLayout(text, 1)

    def _apply_theme(self, theme) -> None:
        accent = self._accent if QColor(self._accent).isValid() else theme.accent
        self.setStyleSheet(
            f"QFrame {{ background:{theme.surface_elevated}; border:1px solid {theme.border}; border-radius:13px; }}"
            f"QLabel#eventIcon {{ background:{accent}; border:0; border-radius:10px; }}"
            f"QLabel#eventBadge {{ color:{accent}; border:0; font-size:11px; font-weight:800; }}"
            f"QLabel#eventMessage {{ color:{theme.text}; border:0; font-size:12px; }}"
        )

    def refresh_theme_palette(self) -> None:
        self._apply_theme(_active_theme_definition())


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
            defaults = ["qwen3.7-flash-2026-07-15", "qwen3-max", "glm-5.2"]
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
        form.addRow(self.base_url_label, self.base_url)
        form.addRow("", self.endpoint_hint)
        self.protocol_label = QLabel("协议 / Protocol")
        form.addRow(self.protocol_label, self.protocol)
        self.key_label = QLabel("API 密钥")
        self.key_row_host = QWidget()
        self.key_row_host.setLayout(key_row)
        form.addRow(self.key_label, self.key_row_host)

        advanced = QHBoxLayout()
        advanced.setContentsMargins(0, 0, 0, 0)
        self.json_mode = QCheckBox("JSON Mode")
        self.structured_output = QCheckBox("Structured Output")
        self.stream_output = QCheckBox("stream")
        self.json_mode.setChecked(True)
        self.structured_output.setChecked(True)
        self.stream_output.setEnabled(False)
        bind_text(self.stream_output, '当前字幕处理后端使用非流式结构化响应', property='toolTip')
        advanced.addWidget(self.json_mode)
        advanced.addWidget(self.structured_output)
        advanced.addWidget(self.stream_output)
        advanced.addStretch(1)
        self.capabilities_host = QWidget()
        self.capabilities_host.setLayout(advanced)

        self.cli_page = QWidget()
        self.cli_page.setObjectName("endpointCliPage")
        cli_layout = QVBoxLayout(self.cli_page)
        cli_layout.setContentsMargins(0, 0, 0, 0)
        cli_layout.setSpacing(7)
        self.cli_status = QLabel("CLI：未检测")
        self.cli_status.setObjectName("endpointCliStatus")
        self.account_status = QLabel("CLI Session：未知")
        self.account_status.setObjectName("endpointAccountStatus")
        cli_layout.addWidget(self.cli_status)
        cli_layout.addWidget(self.account_status)
        cli_actions = QHBoxLayout()
        self.detect_cli_button = QPushButton("重新检测")
        self.login_button = QPushButton("登录")
        self.install_button = QPushButton("安装帮助")
        for button in (self.detect_cli_button, self.login_button, self.install_button):
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

        service_form = QFormLayout()
        service_form.setHorizontalSpacing(12)
        service_form.setVerticalSpacing(8)
        service_form.addRow("AI 服务", self.service)
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
        layout.addWidget(section_label("Capabilities"))
        layout.addWidget(self.capabilities_host)

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
        self.settings_stack.setMaximumHeight(16777215 if is_api else 190)
        self.custom_name.setVisible(service_id == "custom")
        self.custom_name_label.setVisible(service_id == "custom")
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
            self.refresh_secret_status()
            self._queue_model_discovery()
        self._refresh_model_retirement_warning(service_id)
        (bind_text(self.model, '默认模型', property='placeholderText') if not is_api else bind_text(self.model, '模型名称', property='placeholderText'))
        (bind_text(self.login_button, '打开官方 Codex 登录') if service_id == 'codex_cli' else (bind_text(self.login_button, '打开 Google 登录') if service_id == 'antigravity' else bind_text(self.login_button, '管理 Grok 登录')))
        self.logout_button.setVisible(service_id == "codex_cli")
        self.install_button.setVisible(not is_api)
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
        values = self.values()
        base = GLOBAL_PROVIDER_REGISTRY.settings()
        overlay = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
        overlay.setdefault("models", {})
        service_id = str(values.get("service") or "custom")
        if service_id in AI_SERVICE_SPECS:
            activate_ai_service(overlay, service_id, stage=self.stage)
        overlay["models"][f"{self.stage}_transport"] = values["transport"]
        overlay["models"][f"{self.stage}_model"] = values["model"]
        return overlay

    def _provider_settings(self) -> dict:
        """Model discovery must resolve the same post-save world as _cli_settings.

        2026-09-04：裸平铺 dict 缺 ``ai_service``/``polish_provider`` 时，
        get_active_service 迁移路径在 group 编辑器（全文断句模型）下回落默认
        grok_account——选 DeepSeek 预设点“刷新模型”却拉到 Grok CLI 的模型列表。
        与连接测试同构：live settings 拷贝 + activate_ai_service 覆盖层。
        """
        values = self.values()
        base = GLOBAL_PROVIDER_REGISTRY.settings()
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
                              model=values['model'], protocol=values['protocol'])
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
        worker.succeeded.connect(lambda models: self._model_discovery_succeeded(models)
            if scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
        worker.failed.connect(lambda message: self._model_discovery_failed(message)
            if scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
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
        installed = "未安装" not in message and "未检测到" not in message
        self.install_button.setVisible(not installed)
        (bind_text(self.cli_status, 'CLI：已安装') if installed else bind_text(self.cli_status, 'CLI：未检测到'))
        service_id = str(self.service.currentData() or "")
        prefix = str(AI_SERVICE_SPECS[service_id]["label"]) + " Session"
        if ok and service_id == "codex_cli":
            bind_text(self.login_button, '重新登录或切换账号')
        (bind_text(self.account_status, f'{prefix}：READY') if ok else (bind_text(self.account_status, '{value0}：未知', value0=prefix) if not installed else bind_text(self.account_status, '{value0}：未登录或不可调用', value0=prefix)))
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def copy_provider_diagnostics(self):
        from .provider_diagnostics import redact_diagnostics
        provider=provider_for_stage(self._provider_settings(),self.stage)
        payload=redact_diagnostics({"provider":self.values()["service"],"model":self.model.currentText(),
            "status":self.status.text(),"trace":provider.invocation_trace()})
        QApplication.clipboard().setText(json.dumps(payload,ensure_ascii=False,indent=2))

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
        bind_text(self.account_status, f'{label}：' + ('已登录/连接正常' if ok else '登录未完成，请重新检测'))
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
        self._tester = ConnectionTester(endpoint)
        self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._connection_finished))
        self._tester.start()

    def _show_slow_connection_hint(self, tester) -> None:
        if tester is self._tester and tester is not None and tester.isRunning():
            elapsed = max(5, int(time.monotonic() - self._connection_started_at))
            bind_text(self.status, '模型响应较慢，仍在等待… {elapsed} 秒 · 可取消', elapsed=elapsed)

    def _invalidate_endpoint_tasks(self) -> None:
        self._endpoint_epoch = getattr(self, '_endpoint_epoch', 0) + 1
        for name in ('_tester', '_login_worker'):
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

    def _endpoint_callback(self, worker, slot, callback):
        epoch = getattr(self, '_endpoint_epoch', 0)
        identity = self.values()
        def deliver(*args):
            if (epoch == getattr(self, '_endpoint_epoch', 0)
                    and getattr(self, slot, None) is worker and self.values() == identity):
                callback(*args)
        return deliver

    def _connection_finished(self, ok: bool, message: str):
        self.test_button.setEnabled(True)
        bind_text(self.test_button, '测试连接')
        if ok:
            if str(self.service.currentData()) == "codex_cli":
                bind_text(self.login_button, '重新登录或切换账号')
                bind_text(self.account_status, 'Codex：已登录/连接正常')
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
            unified=bool(unified),
        )
        models["ai_service"] = active_service
        models["provider_profiles"] = profile_view["models"].get("provider_profiles", {})
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
        "qwen_asr_api_provider": str(values.get("qwen_asr_api_provider", "dashscope")),
        "qwen_asr_api_protocol": str(values.get("qwen_asr_api_protocol", "dashscope_multimodal")),
        "qwen_asr_api_model": str(values.get("qwen_asr_api_model", "qwen3-asr-flash")),
        "qwen_asr_api_url": str(values.get("qwen_asr_api_url", "")).rstrip("/"),
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
        "paraformer", "funasr_nano", "glm_asr_nano", "canary_qwen", "api", "none",
    }:
        raise RuntimeError("主力转写后端选项无效。")
    if models["qwen_asr_backend"] not in {
        "api", "local", "firered_llm", "whisper_turbo", "sensevoice", "funasr_nano", "off"
    }:
        raise RuntimeError("文字复核后端选项无效。")
    if models["qwen_asr_api_provider"] not in ASR_API_PRESETS:
        raise RuntimeError("ASR API 服务商选项无效。")
    if models["qwen_asr_api_protocol"] not in {
        "dashscope_multimodal", "openai_transcription", "azure_transcription",
        "openrouter_verbose_json", "dashscope_filetrans", "dashscope_asr_flash", "spark_wss",
    }:
        raise RuntimeError("ASR API 协议选项无效。")
    if models["firered_asr_backend"] not in {"local", "qwen_aligner", "whisper_turbo", "paraformer", "off"}:
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

    def run(self):
        started = time.monotonic()
        try:
            provider = provider_for_stage(self.settings, self.stage)
            validate_started = time.monotonic()
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
            if self.isInterruptionRequested():
                self.finished_status.emit(False, "连接测试已取消")
                return
            measured_readiness = self.timings.get("readiness_request_seconds")
            if measured_readiness is not None and not self.timings.get("cache_hit"):
                self.timings["response_seconds"] = measured_readiness
            if self.prompt_test and status.available and status.authenticated and (measured_readiness is None or self.timings.get("cache_hit")):
                response_started = time.monotonic()
                reply = provider.complete(
                    [{"role": "user", "content": "Return exactly: 2ByteASR_OK"}],
                    max_tokens=32,
                    temperature=0.0,
                    timeout=45.0,
                    cancel_check=self.isInterruptionRequested,
                    stage="connection_test",
                ).strip()
                self.timings["response_seconds"] = time.monotonic() - response_started
                if reply != "2ByteASR_OK":
                    self.finished_status.emit(False, f"连接返回不符合预期：{reply[:80]}")
                    return
                status = type(status)(True, True, "连接正常 · 返回 2ByteASR_OK", status.models)
            self.timings["total_seconds"] = time.monotonic() - started
            cache_note = "缓存状态" if self.timings.get("cache_hit") else "实时检测"
            timing = f"{cache_note} {float(self.timings['validation_seconds']):.2f}s"
            if "response_seconds" in self.timings:
                timing += f" · 模型响应 {float(self.timings['response_seconds']):.2f}s"
            timing += f" · 总计 {float(self.timings['total_seconds']):.2f}s"
            self.finished_status.emit(
                bool(status.available and status.authenticated),
                f"{status.message} · {timing}",
            )
        except Exception as exc:
            compact = " ".join(str(exc).split())[:120]
            if self.isInterruptionRequested() or "取消" in compact:
                self.finished_status.emit(False, "连接测试已取消")
            else:
                elapsed = time.monotonic() - started
                self.finished_status.emit(False, f"{compact} · {elapsed:.2f}s")


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
    result_ready = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.result_ready.emit(check_for_update())
        except Exception as exc:  # noqa: BLE001 - UI must report network failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(int, int)
    completed = Signal(str, str)
    failed = Signal(str)

    def __init__(self, info, destination: Path):
        super().__init__()
        self.info = info
        self.destination = destination

    def run(self):
        try:
            package, checksum = download_update(
                self.info,
                self.destination,
                progress=self.progress_changed.emit,
            )
            self.completed.emit(str(package), checksum)
        except Exception as exc:  # noqa: BLE001 - UI must report mirror/checksum failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


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


class GuidedSetupDialog(SpringDialog):
    """First-run model-combination chooser. Nothing is downloaded implicitly."""

    cuda_probe_finished = Signal(object)

    PRESETS = {
        "quality": ("moss", "local", "local"),
        "light": ("sensevoice", "off", "off"),
        "online": ("api", "off", "off"),
        "custom": ("none", "off", "off"),
    }
    SIZES = {
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
        bind_text(self, '首次使用设置 - 2ByteASR', property='windowTitle')
        self.setMinimumSize(760, 610)
        self.resize(800, 640)
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
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("日本語", "ja")
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

        preset_row = QHBoxLayout()
        preset_row.setSpacing(10)
        self.preset_group = QButtonGroup(self)
        preset_copy = (
            ("quality", "质量优先", "MOSS + FireRed + Qwen"),
            ("light", "快速轻量", "CPU 友好，小体积"),
            ("online", "在线疾速", "免下载，需要 API Key"),
            ("custom", "稍后决定", "先看界面，不下载"),
        )
        for index, (key, label, note) in enumerate(preset_copy):
            button = QPushButton(f"{label}\n{note}")
            button.setCheckable(True)
            button.setMinimumHeight(98)
            button.setProperty("preset", key)
            button.setObjectName("presetCard")
            self.preset_group.addButton(button, index)
            preset_row.addWidget(button, 1)
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
        self._apply_preset("quality")
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

        def probe():
            try:
                status = detect_cuda_runtime()
            except Exception:
                status = None
            try:
                self.cuda_probe_finished.emit(status)
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
        size = self.SIZES.get(primary, 0.0)
        if timeline == "local" and primary != "firered":
            size += self.SIZES["local_timeline"]
        elif timeline == "qwen_aligner":
            size += self.SIZES["qwen_aligner"]
        elif timeline == "whisper_turbo" and primary != "whisper_turbo":
            size += self.SIZES["whisper_turbo"]
        elif timeline == "paraformer" and primary != "paraformer":
            size += self.SIZES["paraformer"]
        if review == "local" and primary != "qwen_local":
            size += self.SIZES["local_review"]
        elif review not in {"off", "api", "local"} and review != primary:
            size += self.SIZES.get(review, 0.0)
        notes = []
        if primary not in {"moss", "none"}:
            notes.append("非 MOSS 主力当前按单说话人输出")
        if primary == "api" or review == "api":
            notes.append("需要在设置页填写对应 API Key")
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
        else:
            self.gpu_info.setObjectName("statusBad")
            bind_text(self.gpu_info, '当前设备还不能运行：{value0}。可换成轻量/在线组合，或修复 NVIDIA 驱动与 PyTorch。', value0='、'.join(required))
        self.gpu_info.style().unpolish(self.gpu_info)
        self.gpu_info.style().polish(self.gpu_info)

    def selected_backends(self):
        return (
            str(self.primary_combo.currentData()),
            str(self.timeline_combo.currentData()),
            str(self.review_combo.currentData()),
        )

    def selected_download_keys(self):
        primary, timeline, review = self.selected_backends()
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
        }
        timeline_keys = {
            "local": "firered_aed",
            "qwen_aligner": "qwen_aligner",
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


class MainWindow(QWidget):
    def __init__(self, media_paths, legacy, pipeline, startup_self_test):
        super().__init__()
        self.media_paths = list(media_paths)
        self.legacy = legacy
        self.pipeline = pipeline
        self.startup_self_test = startup_self_test
        self.profile_store = ProjectProfileStore()
        self.current_project_profile: ProjectProfile | None = None
        # 方案切换守卫与脏标：_applying_profile 期间控件信号不标记脏、不回写方案。
        self._applying_profile = False
        self._asr_config_dirty = False
        self.token = None
        self.worker = None
        self.update_check_worker = None
        self.update_download_worker = None
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
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
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
        self.settings_scroll = self._scrollable(self._settings_page())
        self.pages.addWidget(self.settings_scroll)
        self.pages.addWidget(self._progress_page())
        self.pages.addWidget(self._result_page())
        self.workshop_page = ModelWorkshopPage(
            APP_ROOT,
            self.legacy.RUNTIME_SETTINGS,
            self,
        )
        self.workshop_page.return_requested.connect(self._return_to_settings)
        self.workshop_page.terms_requested.connect(self._open_terms_from_workshop)
        self.workshop_page.history_requested.connect(self._open_recognition_history)
        self.workshop_page.task_settings_requested.connect(self._open_task_settings_from_workshop)
        self.workshop_page.ai_segmentation_requested.connect(self._open_ai_from_workshop)
        self.workshop_page.update_requested.connect(self._check_updates)
        self.workshop_page.api_config_requested.connect(self._open_qwen_api_from_workshop)
        self.workshop_page.api_preset_requested.connect(self._apply_asr_api_preset)
        self.workshop_page.api_configure_requested.connect(self._open_api_key_dialog_for_preset)
        self.workshop_page.backend_requested.connect(self._apply_workshop_backend)
        self.pages.addWidget(self.workshop_page)
        self.term_library_page = TermLibraryPage(self)
        self.term_library_page.recognition_requested.connect(self._return_to_settings)
        self.term_library_page.workshop_requested.connect(self._open_model_workshop)
        self.term_library_page.history_requested.connect(self._open_recognition_history)
        self.pages.addWidget(self.term_library_page)
        # Reports live in the stable user-data root; the install tree (and any
        # legacy roots) are still scanned so history survives EXE rebuilds.
        from . import reporting as _reporting

        self.history_page = RecognitionHistoryPage(
            _reporting.REPORT_ROOT,
            self,
            extra_roots=_reporting.LEGACY_REPORT_ROOTS,
        )
        self.history_page.recognition_requested.connect(self._return_to_settings)
        self.history_page.workshop_requested.connect(self._open_model_workshop)
        self.history_page.terms_requested.connect(self._open_terms_from_history)
        self.pages.addWidget(self.history_page)
        self.studio_page = SubtitleStudioPage(self)
        self.studio_page.return_requested.connect(self._return_to_settings)
        self.studio_page.close_ready_signal.connect(self._finish_studio_close)
        self.studio_page.recognition_requested.connect(
            self._handle_studio_recognition_request
        )
        # 四十二轮：左侧字幕列表状态芯片上的"取消识别"→ 主窗口取消令牌。
        self.studio_page.recognition_cancel_requested.connect(self._cancel_run)
        # 四十三轮："查看详细进度"→ 跳主页识别进度页（识别继续后台跑）。
        self.studio_page.recognition_detail_requested.connect(
            self._show_studio_recognition_detail
        )
        self._studio_recognition_context = None
        self.pages.addWidget(self.studio_page)
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

        self._refresh_media_summary()
        self._refresh_ai_summary()
        self._create_resize_handles()
        self._apply_ui_language()
        self._encoder_capability_cancel = threading.Event()
        self._encoder_capability_worker = None
        self._startup_background_ready_thread = None
        # P0: background preload of model install status + term index after first paint.
        # Never on click path; cheap FS/metadata only. No spinners.
        QTimer.singleShot(0, self, self._background_preload)
        QTimer.singleShot(0, self, self._restore_last_project_profile)

    def _on_modal_closed(self):
        # Lightweight hook for global post-close housekeeping if needed.
        # Individual show_content callers supply their on_closed callback.
        pass

    def retranslate_ui(self):
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
        if hasattr(self, "recognition_plan"):
            self.recognition_plan.retranslate(code)
            self._refresh_asr_summary()
        if hasattr(self, "_refresh_ai_summary"):
            self._refresh_ai_summary()
        if hasattr(self, "workshop_page"):
            self.workshop_page.refresh()
            for technical in self.workshop_page._technical_cache.values():
                technical.retranslate(code)
        if hasattr(self, "history_page"):
            self.history_page.refresh()
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
            refresh_application(code)
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
        return area

    def _schedule_ai_panel_visibility(self, expanded: bool):
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
        self.settings_scroll.ensureWidgetVisible(self.ai_panel.header, 24, 24)
        panel_top = self.ai_panel.mapTo(self.settings_page_widget, QPoint(0, 0)).y()
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
        self.brand = BrandLabel(
            '<span style="font-size:26px; font-weight:800;">2</span>'
            '<span style="font-size:23px; font-weight:800;">ByteASR</span>'
        )
        self.brand.setObjectName("brand")
        self.brand.setTextFormat(Qt.TextFormat.RichText)
        self.brand.setAccessibleName("2ByteASR")
        self.brand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brand.setToolTip("2ByteASR")
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
        self.support_button.setVisible(not support_entry_hidden())
        self.support_button.clicked.connect(self._open_support)
        row.addWidget(self.support_button)
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
        from .design.presentation import button_role
        for button in (self.subtitle_studio_button, self.model_workshop_button, self.app_settings_button):
            button_role(button, "secondary", size="default")
            button.setProperty("homeNavigation", True)
            button.setIconSize(QSize(20, 20))
        self.language_combo = user_text(FramelessPopupCombo())
        self.language_combo.setMinimumWidth(100)
        self.language_combo.setMaximumWidth(160)  # soft for CN labels
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("日本語", "ja")
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(current_language()))
        )
        self.language_combo.currentIndexChanged.connect(self._change_language)
        row.addWidget(self.language_combo)
        chrome_column.addWidget(header_content, 1)
        outer.addWidget(chrome, 1)
        return header

    def _anchor_header_mascot(self):
        # Retained for older audit hooks. The brand mark is now owned by the
        # header layout and never absolutely positioned over the wordmark.
        return

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_title_bar"):
            self.window_title_bar.sync_window_state()
            if hasattr(self, "studio_page"):
                self.studio_page._sync_window_controls()
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
        self.content_layout.setContentsMargins(*( (0, 0, 0, 0) if current is self.studio_page else (18, 12, 18, 14) ))
        self.content_layout.setSpacing(0 if current is self.studio_page else 12)
        self.app_header.setVisible(current is not self.studio_page)
        self.model_workshop_button.setVisible(current is self.settings_scroll)
        self.subtitle_studio_button.setVisible(current is not self.studio_page)
        self.return_recognition_button.setVisible(
            current in {self.workshop_page, self.term_library_page, self.history_page}
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
        self._update_bottom_bar_visibility(index)

    def _switch_page(self, target) -> None:
        """Commit a stacked-page transition under one paint boundary."""
        widget = self.pages.widget(target) if isinstance(target, int) else target
        if widget is None or self.pages.currentWidget() is widget:
            return
        from .ui_motion import atomic_layout, reveal_cue
        with atomic_layout(self):
            widget.ensurePolished()
            self.pages.setCurrentWidget(widget)
            self.pages.layout().activate()
            if hasattr(self, "content_layout"):
                self.content_layout.activate()
        reveal_cue(self.app_header if self.app_header.isVisible() else self.studio_page.studio_toolbar)

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
            from .window_constraints import install_window_bounds
            install_window_bounds(self)
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
            if hasattr(self, "studio_page"):
                self.studio_page.close_page()
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
        self.workshop_page.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
        self.workshop_page.restore_active_navigation()
        self._switch_page(self.workshop_page)

    def open_studio_project(self, project_path=None, *, mode="edit", source="canonical", on_ready=None):
        """Canonical Studio navigation entry for every project-opening source."""
        if hasattr(self, "studio_page"):
            self.studio_page._studio_trace(
                "ENTRY",
                source=str(source),
                mode=str(mode),
                project_path=str(project_path or ""),
            )
        self._open_subtitle_studio(project_path, mode=mode,
            skip_dirty_guard=source == 'studio_recognition', on_ready=on_ready)

    def _retry_pending_recognition_reload(self):
        """Reload a recognition handoff that failed to land earlier.

        The saved subtitles exist; only the in-app reload can have failed
        (readiness timeout/cancel). Retrying on the next Studio entry keeps
        the user from having to reopen the project from the library.
        """
        studio = getattr(self, "studio_page", None)
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
        self.open_studio_project(str(target), mode="edit", source="studio_recognition")

    def _open_subtitle_studio(self, project_path=None, *, mode="edit", skip_dirty_guard=False, on_ready=None):
        transition_started = time.perf_counter()
        if self.pages.currentWidget() is not self.studio_page:
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
            self.studio_page.open_project(candidate, on_ready=ready, skip_dirty_guard=skip_dirty_guard)
        else:
            self.studio_page.show_project_hub()
            self._retry_pending_recognition_reload()

    def _return_to_settings(self):
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
        if request_options.get('speaker_source') == 'filetrans' and self.qwen_asr_api_provider.currentData()!='qwen31_filetrans':
            # This is an explicit model selection in the recognition dialog.
            provider_index = self.qwen_asr_api_provider.findData('qwen_filetrans')
            self.qwen_asr_api_provider.setCurrentIndex(provider_index)
            self._apply_asr_preset_fields('qwen_filetrans')
            self.qwen_asr_api_model.setText('qwen-audio-3.0-asr-flash-filetrans')
            self._set_backend_combo(self.primary_asr_backend, 'api')
            models['primary'] = 'api'
        self._studio_recognition_context = {
            "media_path": str(media.resolve()),
            "project_path": str(project.resolve()),
            "project_id": str(self.studio_page.project.project_id),
            "recognition_purpose": "analysis" if str(action) == "start_analysis" else "final",
            "enabled_glossary_ids": list(request_options.get("enabled_glossary_ids") or []),
            "replace_policy": str(request_options.get("replace_policy") or "replace_cues"),
            "recognition_plan": plan_key,
            "models": dict(models),
            "speaker_source": str(request_options.get("speaker_source") or "single"),
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

    def _finish_studio_recognition(self, project_path: str) -> None:
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
                self.open_studio_project(project_path, mode="edit", source="studio_recognition")
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
        studio = getattr(self, "studio_page", None)
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
                                 on_ready=_restore_after_reload)

    def _open_application_settings(self, initial_section=None):
        """One shared settings entry for every workspace (Recognition/Library/Studio)."""
        from .application_settings import open_application_settings

        studio_page = getattr(self, "studio_page", None)
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
        """Open the exact same AI configuration component used on the home page."""
        panel = self.ai_panel
        dialog = SpringDialog(self)
        bind_text(dialog, 'AI 模型 / 智能断句', property='windowTitle')
        dialog.setWindowIcon(_app_icon())
        dialog.resize(980, 660)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("AI 模型 / 智能断句")
        heading.setObjectName("termLibraryTitle")
        layout.addWidget(heading)
        note = QLabel("与字幕识别主页共用同一套供应商、模型、Base URL、密钥和开关配置。")
        note.setObjectName("muted")
        layout.addWidget(note)
        panel.setVisible(True)
        panel.set_expanded(True, animate=False)
        layout.addWidget(panel, 1)
        close = AnimatedButton("完成")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()
        layout.removeWidget(panel)
        panel.setParent(self.settings_page_widget)
        insert_at = max(0, self.settings_page_layout.indexOf(self.settings_action_bar))
        self.settings_page_layout.insertWidget(insert_at, panel)
        panel.set_expanded(False, animate=False)
        panel.hide()
        self.setting_tiles["ai"].setChecked(False)
        self.workshop_page.restore_active_navigation()

    def _open_task_settings_from_workshop(self):
        self._open_application_settings(initial_section="高级设置")

    def _reset_teach_hints(self) -> None:
        self.studio_page._teach_hints.reset()
        bind_text(self.term_hint, '教学提示已重置；下次进入相应功能时会再次显示。')
        self.term_hint.setVisible(bool(self.term_hint.text()))

    def _open_qwen_api_from_workshop(self):
        self._apply_asr_api_preset("dashscope")

    def _saved_asr_api_endpoint(self) -> tuple[str, str, str]:
        """(provider, model, url) 已保存值——用户自定义地址不被预设强制刷新的依据。"""
        models = self.legacy.RUNTIME_SETTINGS.get("models", {})
        return (
            str(models.get("qwen_asr_api_provider", "dashscope") or "dashscope"),
            str(models.get("qwen_asr_api_model", "") or ""),
            str(models.get("qwen_asr_api_url", "") or ""),
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
            if getattr(getattr(self, "workshop_page", None), "api_target_role", "") == "primary"
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
        self._open_api_key_dialog()

    def _refresh_workshop_after_asr_change(self):
        workshop = getattr(self, "workshop_page", None)
        if workshop is None:
            return
        try:
            workshop.update_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            active=getattr(self,'current_project_profile',None)
            (bind_text(workshop.combo_title, active.name) if active else bind_text(workshop.combo_title, '当前默认配置'))
        except Exception:
            pass
        try:
            self.asr_save_status.style().unpolish(self.asr_save_status)
            self.asr_save_status.style().polish(self.asr_save_status)
        except Exception:
            pass

    def _apply_workshop_backend(self, role: str, value: str):
        if role == 'speaker':
            from .speaker_strategy import resolve
            value=resolve(self.legacy.RUNTIME_SETTINGS,value)
            previous=self.legacy.RUNTIME_SETTINGS['models'].get('speaker_source','single')
            active=getattr(self,'current_project_profile',None)
            previous_asr=copy.deepcopy(active.asr_config) if active else None
            try:
                if active:
                    updated={**previous_asr,'speaker_source':value}
                    self.current_project_profile=self.profile_store.update_asr_config(active.id,updated)
                self.legacy.configure_runtime_asr({'speaker_source':value})
            except Exception as exc:
                if active:
                    self.current_project_profile=self.profile_store.update_asr_config(active.id,previous_asr)
                self.legacy.RUNTIME_SETTINGS['models']['speaker_source']=previous
                bind_text(self.asr_save_status, '说话人方案保存失败：{value0}', value0=str(exc))
                self._refresh_workshop_after_asr_change()
                return
            self._refresh_asr_summary()
            self._refresh_workshop_after_asr_change()
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
        bind_text(self.update_button, '检查更新')

    def _check_updates(self):
        if self.update_check_worker and self.update_check_worker.isRunning():
            return
        self.update_button.setEnabled(False)
        bind_text(self.update_button, '正在检查…')
        worker = UpdateCheckWorker(self)
        self.update_check_worker = worker
        worker.result_ready.connect(self._update_check_finished)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(self._set_update_idle)
        worker.start()

    def _update_check_failed(self, detail: str):
        message = QMessageBox(self)
        bind_text(message, '检查更新失败', property='windowTitle')
        message.setIcon(QMessageBox.Icon.Warning)
        bind_text(message, '暂时无法连接更新服务器。')
        bind_text(message, '{value0}\n\n可稍后重试，或打开发布页手动下载。', property='informativeText', value0=detail)
        open_release = message.addButton("打开发布页", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        message.exec()
        if message.clickedButton() is open_release:
            QDesktopServices.openUrl(QUrl(RELEASE_PAGE))

    def _update_check_finished(self, info):
        if not info.newer:
            QMessageBox.information(
                self,
                tr('已经是最新版'),
                tr('当前版本 {value0}，发布版 {value1}。', value0=info.current_version, value1=info.latest_version),
            )
            return
        if not info.can_self_update:
            answer = QMessageBox.question(
                self,
                tr('发现新版本'),
                tr('发现 2ByteASR {value0}。这个旧版尚不支持一键增量更新，可以下载新版安装包直接覆盖安装；模型、环境和设置都会保留。\n\n现在打开下载页吗？', value0=info.latest_version),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(info.installer_url or info.release_url))
            return
        answer = QMessageBox.question(
            self,
            tr('发现新版本'),
            tr('发现 2ByteASR {value0}（当前 {value1}）。\n\n是否下载小型更新包？下载完成后程序会退出、覆盖程序文件并自动重新打开；不会重新下载模型或 Python 环境。', value0=info.latest_version, value1=info.current_version),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._download_update(info)

    def _download_update(self, info):
        if self.update_download_worker and self.update_download_worker.isRunning():
            return
        local_data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        destination = local_data / "updates"
        self.update_button.setEnabled(False)
        bind_text(self.update_button, '下载更新 0%')
        worker = UpdateDownloadWorker(info, destination)
        self.update_download_worker = worker
        worker.progress_changed.connect(self._update_download_progress)
        worker.completed.connect(self._update_download_finished)
        worker.failed.connect(self._update_download_failed)
        worker.finished.connect(self._set_update_idle)
        worker.start()

    def _update_download_progress(self, received: int, total: int):
        if total > 0:
            percent = min(100, int(received * 100 / total))
            bind_text(self.update_button, '下载更新 {percent}%', percent=percent)
        else:
            bind_text(self.update_button, '已下载 {value0:.1f} MB', value0=received / 1048576)

    def _update_download_failed(self, detail: str):
        QMessageBox.warning(
            self,
            tr('更新下载失败'),
            tr('更新未修改任何程序文件。可稍后重试或直接覆盖安装新版。\n\n{value0}', value0=detail),
        )

    def _update_download_finished(self, package_path: str, checksum: str):
        try:
            launch_update_helper(Path(package_path), checksum, wait_pid=os.getpid())
        except Exception as exc:  # noqa: BLE001 - retain verified package for retry
            QMessageBox.critical(self, tr('无法启动更新'), str(exc))
            return
        bind_text(self.update_button, '正在重启…')
        QApplication.quit()

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
        # 素材区放在最上方：整张卡片是选择/拖放主操作。
        self.media_frame = MediaPickCard()
        self.media_frame.setProperty("dropActive", False)
        self.media_frame.setMinimumHeight(66)
        self.media_frame.activated.connect(self._choose_media)
        media_row = QHBoxLayout(self.media_frame)
        media_row.setContentsMargins(12, 8, 12, 8)
        media_icon = QLabel()
        self.media_type_icon = media_icon
        media_icon.setPixmap(themed_icon("fa5s.file-audio").pixmap(QSize(20, 20)))
        media_row.addWidget(media_icon)
        media_row.addWidget(QLabel("本地素材"))
        media_row.addSpacing(20)
        media_text = QVBoxLayout()
        media_text.setSpacing(1)
        self.media_name = QLabel("")
        self.media_name.setObjectName("mediaName")
        self.media_drop_hint = QLabel("可把视频 / 音频拖到窗口，或按回车选择")
        self.media_drop_hint.setObjectName("dropHint")
        media_text.addWidget(self.media_name)
        media_text.addWidget(self.media_drop_hint)
        self.media_origin_label = QLabel("来自兔白字幕工程")
        self.media_origin_label.setObjectName("studioOrigin")
        self.media_origin_label.hide()
        media_text.addWidget(self.media_origin_label)
        media_row.addLayout(media_text, 1)
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
        layout.addSpacing(4)
        from .home_studio_entry import StudioEntryCard
        studio_entry = StudioEntryCard()
        studio_entry.setObjectName("studioEntryCard")
        studio_entry.clicked.connect(lambda: self.open_studio_project())
        entry_layout = QVBoxLayout(studio_entry)
        entry_layout.setContentsMargins(20, 20, 20, 16)
        entry_layout.setSpacing(8)
        entry_text = QVBoxLayout()
        entry_text.setSpacing(8)
        entry_text.addStretch(1)
        entry_eyebrow = QLabel("字幕与视频编辑")
        entry_eyebrow.setObjectName("studioEntryEyebrow")
        entry_text.addWidget(entry_eyebrow, 0, Qt.AlignmentFlag.AlignLeft)
        entry_title = QLabel("字幕工作台")
        entry_title.setObjectName("studioEntryTitle")
        entry_text.addWidget(entry_title)
        entry_hint = QLabel("校对每一句，剪出好片段。\n字幕、画面与样式，在这里一起完成。")
        entry_hint.setObjectName("studioEntryHint")
        entry_hint.setWordWrap(True)
        entry_text.addWidget(entry_hint)
        self.studio_entry_recent = QLabel("最近：暂无工程")
        self.studio_entry_recent.setObjectName("studioEntryHint")
        self.studio_entry_recent.setWordWrap(True)
        entry_text.addWidget(self.studio_entry_recent)
        for label in (entry_eyebrow, entry_title, entry_hint, self.studio_entry_recent):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        entry_text.addStretch(1)
        entry_layout.addLayout(entry_text, 1)
        entry_open = AnimatedButton("进入兔白字幕 Studio  →")
        entry_open.setObjectName("studioEntryPrimary")
        install_themed_icon(entry_open, "fa5s.closed-captioning")
        entry_open.clicked.connect(lambda: self.open_studio_project())
        from .design.presentation import button_role
        button_role(entry_open, "primary", size="large")
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
        surface_layout = QHBoxLayout(surface)
        surface_layout.setContentsMargins(22, 18, 22, 18)
        surface_layout.setSpacing(22)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.settings_left_column = left
        content_profile = QFrame()
        content_profile.setObjectName("homeContentProfile")
        self.content_profile_card = content_profile
        profile_layout = QVBoxLayout(content_profile)
        profile_layout.setContentsMargins(14, 12, 14, 12)
        profile_layout.setSpacing(6)
        current_eyebrow = QLabel("内容与术语")
        current_eyebrow.setObjectName("muted")
        current_eyebrow.setParent(content_profile)
        current_eyebrow.hide()
        self.current_content_title = QLabel("通用内容")
        self.current_content_title.setObjectName("contentHeroTitle")
        profile_layout.addWidget(self.current_content_title)
        name_label = QLabel("游戏 / 内容名称")
        name_label.setStyleSheet("font-weight: 600;")
        name_label.setParent(content_profile)
        name_label.hide()
        self.game_box = EditableHistoryCombo()
        choices = []
        seen = set()
        for value in (*self.legacy.load_runtime_game_history(), *self.legacy.BUILTIN_GAME_PROFILES):
            canonical = self.legacy.canonicalize_runtime_game_name(value)
            identity = self.legacy.runtime_game_identity(canonical)
            if canonical and identity not in seen:
                choices.append(canonical)
                seen.add(identity)
        self.game_box.addItems(choices)
        self.game_box.setCurrentIndex(-1)
        bind_text(self.game_box, '选择历史记录或内置游戏，也可以直接输入；留空为通用模式', property='placeholderText')
        bind_text(self.game_box, '点击右侧箭头选择历史记录或内置游戏；输入新名称也会自动保存', property='toolTip')
        profile_layout.addWidget(self.game_box)
        self.terms = SwitchControl("游戏术语增强")
        bind_text(self.terms, '本地图鉴候选 + 联网复核；PVP 内容建议开启', property='toolTip')
        self.game_box.currentTextChanged.connect(self._auto_enable_terms)
        self.terms.toggled.connect(lambda _checked: self._resolve_glossary_binding())
        self.game_box.currentTextChanged.connect(self._refresh_asr_summary)
        self.game_box.currentTextChanged.connect(
            lambda value: bind_text(self.current_content_title, value.strip() or '通用内容')
        )
        # 术语增强开关与术语库入口同区：两者是同一件事的深浅两级。
        terms_row = QHBoxLayout()
        terms_row.setSpacing(8)
        terms_row.addWidget(self.terms, 1)
        terms_help = AnimatedButton("ⓘ")
        terms_help.setObjectName("flat")
        terms_help.setFixedSize(28, 28)
        bind_text(terms_help, '本地图鉴候选 + 联网复核，提高游戏专名识别准确度；PVP 等内容建议开启。', property='toolTip')
        terms_help.clicked.connect(
            lambda: QMessageBox.information(
                self,
                tr('术语增强说明'),
                tr('术语增强会把本批启用的词库和已确认专名作为识别参考。\n\n本地图鉴只提供弱候选，不会仅凭名字相似强制改字；联网复核时再结合上下文确认专名。\n\n游戏、PVP 或专名密集的内容建议开启；通用闲聊可关闭。'),
            )
        )
        terms_row.addWidget(terms_help)
        manage = AnimatedButton("管理术语库")
        install_themed_icon(manage, "fa5s.book-open")
        manage.clicked.connect(self._manage_terms)
        manage.setMaximumWidth(175)  # soft; EN/JA label must not truncate
        terms_row.addWidget(manage)
        self.add_glossary_button = manage
        profile_layout.addLayout(terms_row)
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
        profile_layout.addWidget(term_hint)
        term_hint.hide()
        self.term_hint = term_hint
        # The batch glossary is a compact subsection of the same content
        # profile; it is not a second competing homepage card.
        batch_glossary = QFrame()
        batch_glossary.setObjectName("homeBatchGlossary")
        self.batch_glossary_card = batch_glossary
        batch_layout = QVBoxLayout(batch_glossary)
        batch_layout.setContentsMargins(0, 10, 0, 0)
        batch_layout.setSpacing(5)
        enabled_label = QLabel("本批字幕词库")
        enabled_label.setObjectName("homeCardTitle")
        batch_layout.addWidget(enabled_label)
        self.batch_glossary_status = QLabel("术语增强 OFF")
        self.batch_glossary_status.setObjectName("homeGlossaryStatus")
        self.batch_glossary_status.setWordWrap(True)
        batch_layout.addWidget(self.batch_glossary_status)
        glossary_note = QLabel("启用后用于专名、角色名与错词修正")
        glossary_note.setObjectName("muted")
        glossary_note.setWordWrap(True)
        batch_layout.addWidget(glossary_note)
        self.glossary_chips_layout = QHBoxLayout()
        self.glossary_chips_layout.setSpacing(6)
        batch_layout.addLayout(self.glossary_chips_layout)
        profile_layout.addWidget(batch_glossary)
        left.addWidget(content_profile, 0)
        left.addWidget(studio_entry, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.settings_right_column = right
        recognition_header = QHBoxLayout()
        recognition_header.setSpacing(8)
        recognition_heading = QLabel("识别方案")
        recognition_heading.setObjectName("termGameTitle")
        recognition_header.addWidget(recognition_heading)
        recognition_header.addStretch(1)
        self.home_task_settings_button = AnimatedButton("高级设置")
        self.home_task_settings_button.setObjectName("softAction")
        install_themed_icon(self.home_task_settings_button, "fa5s.cog")
        bind_text(self.home_task_settings_button, '设置对白覆盖、说话人数、复核轨与缓存策略', property='toolTip')
        self.home_task_settings_button.clicked.connect(
            self._open_task_settings_from_workshop
        )
        recognition_header.addWidget(self.home_task_settings_button)
        right.addLayout(recognition_header)
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
        self.project_profile_manage.setFixedSize(34, 32)
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
        right.addLayout(plan_row)
        # 识别方案：三张角色模型卡（批准图核心区）
        from twobyteasr.ui_recognition import RecognitionPlanWidget

        self.recognition_plan = RecognitionPlanWidget()
        self.recognition_plan.role_requested.connect(self._open_model_picker)
        self.recognition_plan.recovery_requested.connect(self._recognition_recovery)
        right.addWidget(self.recognition_plan, 1)
        self.speaker_plan_summary = QLabel('')
        self.speaker_plan_summary.setWordWrap(True)
        self.speaker_plan_summary.setObjectName('muted')
        right.addWidget(self.speaker_plan_summary)
        # 兼容属性：旧测试/逻辑引用（内容由 _refresh_asr_summary 同步）
        self.recognition_summary = QLabel("")
        self.recognition_summary.hide()
        self.run_summary = QLabel("")
        self.run_summary.hide()
        self.run_next_action = QLabel("")
        self.run_next_action.hide()
        self.recognition_action = AnimatedButton("")
        self.recognition_action.hide()
        surface_layout.addLayout(left, 34)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {LINE};")
        surface_layout.addWidget(divider)
        surface_layout.addLayout(right, 66)
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
        api_provider = settings["models"].get("qwen_asr_api_provider", "dashscope")
        self.qwen_asr_api_provider.setCurrentIndex(
            max(0, self.qwen_asr_api_provider.findData(api_provider))
        )
        # 四十轮：模型/服务商下拉打开时当前选中项置顶（免滚动寻找）。
        self.primary_asr_backend.setProperty("selectedFirst", True)
        self.qwen_asr_api_provider.setProperty("selectedFirst", True)
        self.qwen_asr_api_model = QLineEdit(
            settings["models"].get("qwen_asr_api_model", "qwen3-asr-flash")
        )
        self.qwen_asr_api_url = QLineEdit(
            settings["models"].get("qwen_asr_api_url", "")
        )
        self.qwen_asr_api_key = QLineEdit()
        self.qwen_asr_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        from .llm_config import read_asr_api_key

        qwen_key, qwen_key_source = read_asr_api_key(
            str(self.legacy.RUNTIME_SETTINGS.get("models", {}).get("qwen_asr_api_provider", "dashscope") or "dashscope"),
            str(self.legacy.RUNTIME_SETTINGS.get("models", {}).get("qwen_asr_api_url", "") or ""),
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
            "MOSS 仍是长视频与多人内容的推荐主力；其它主力模型当前按单说话人输出，适合单人、轻量或多语种素材。"
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
        self.prefer_arabic_numbers = SwitchControl('新字幕优先使用阿拉伯数字（保留每次数字与重复）')
        self.prefer_arabic_numbers.setChecked(settings['switches'].get('prefer_arabic_numbers', True))
        bind_text(self.prefer_arabic_numbers, '只影响之后生成的字幕；不改已编辑的工程。数字只换写法，不求和或去重。', property='toolTip')
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
        from twobyteasr.ui_widgets import SettingTile, make_tile_row

        self.setting_tiles: dict[str, SettingTile] = {}
        self._tile_panels = [
            ("ai", self.ai_panel, "AI 智能断句", "fa5s.project-diagram"),
        ]
        tiles = []
        for key, _panel, title, icon_name in self._tile_panels:
            tile = SettingTile(title, "", icon_name)
            self.setting_tiles[key] = tile
            tiles.append(tile)

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
        self._refresh_ai_summary()
        layout.addLayout(make_tile_row(tiles))
        for key, panel, _t, _i in self._tile_panels:
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
        studio = getattr(self, "studio_page", None)
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
        from .home_studio_entry import latest_studio_entry
        name, cover_path = latest_studio_entry(records)
        bind_text(self.studio_entry_recent, "最近：{name}", name=name) if name else bind_text(self.studio_entry_recent, "最近：暂无工程")
        card = getattr(self, "studio_entry_card", None)
        if card is not None:
            card.set_cover_path(cover_path)

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
        bar_layout.addStretch(1)
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
        self.start_button.clicked.connect(self._start_run)
        # The dedicated Studio card owns this entrance; retain the attribute
        # for callers without a second competing footer action.
        studio_button.setParent(bar)
        studio_button.hide()
        bar_layout.addWidget(self.start_button)
        self.action_bar = bar
        return bar

    def _progress_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 14, 24, 16)
        layout.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("progressHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 15, 16, 15)
        hero_layout.setSpacing(13)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(2)
        title = QLabel("2ByteASR 正在制作字幕")
        title.setStyleSheet(f"font-family: {TITLE_FONT_STACK}; font-size: 22px; font-weight: 800;")
        hero_text.addWidget(title)
        self.progress_context = QLabel("正在准备任务…")
        self.progress_context.setObjectName("muted")
        hero_text.addWidget(self.progress_context)
        hero_layout.addLayout(hero_text, 1)
        self.progress_percent = QLabel("0%")
        self.progress_percent.setObjectName("progressPercent")
        hero_layout.addWidget(self.progress_percent)
        layout.addWidget(hero)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.recognition_live_status = QLabel('等待真实识别结果；文字将在已完成批次返回后显示')
        self.recognition_live_status.setTextFormat(Qt.TextFormat.PlainText)
        self.recognition_live_status.setWordWrap(True)
        layout.addWidget(self.recognition_live_status)
        self._recognition_live_work = {}
        self._progress_motion = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_motion.setDuration(460)
        self._progress_motion.setEasingCurve(QEasingCurve.Type.OutCubic)

        phase_row = QHBoxLayout()
        phase_row.setSpacing(8)
        self.phase_cards = [
            ProgressPhaseCard("fa5s.wave-square", "本地识别", "转写与主播", GREEN),
            ProgressPhaseCard("fa5s.magic", "字幕校对", "模型安全纠错", AMBER),
            ProgressPhaseCard("fa5s.comment-alt", "全文断句", "语义与时间轴", BLUE),
            ProgressPhaseCard("fa5s.file-export", "保存结果", "工程与报告", CORAL),
        ]
        for card in self.phase_cards:
            phase_row.addWidget(card, 1)
        layout.addLayout(phase_row)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(10)
        left_column = QVBoxLayout()
        left_column.setSpacing(10)

        current_card = QFrame()
        current_card.setObjectName("currentStageCard")
        current_layout = QVBoxLayout(current_card)
        current_layout.setContentsMargins(15, 12, 15, 13)
        current_layout.setSpacing(4)
        eyebrow_row = QHBoxLayout()
        eyebrow = QLabel("当前步骤")
        eyebrow.setObjectName("stageEyebrow")
        eyebrow_row.addWidget(eyebrow)
        self.running_indicator = RunningIndicator()
        eyebrow_row.addWidget(self.running_indicator)
        eyebrow_row.addStretch(1)
        self.stage_elapsed = QLabel("00:00")
        self.stage_elapsed.setObjectName("consoleBadge")
        eyebrow_row.addWidget(self.stage_elapsed)
        current_layout.addLayout(eyebrow_row)
        self.progress_stage = QLabel("等待启动")
        self.progress_stage.setObjectName("stageLarge")
        self.progress_stage.setWordWrap(True)
        current_layout.addWidget(self.progress_stage)
        self.progress_resource = QLabel("准备检查运行环境")
        self.progress_resource.setObjectName("muted")
        self.progress_resource.setWordWrap(True)
        current_layout.addWidget(self.progress_resource)
        self.active_tasks_label = QLabel("尚无运行中的子任务")
        self.active_tasks_label.setWordWrap(True)
        self._style_active_tasks_label()
        current_layout.addWidget(self.active_tasks_label)
        left_column.addWidget(current_card)

        feed_card = QFrame()
        feed_card.setObjectName("eventFeedCard")
        feed_layout = QVBoxLayout(feed_card)
        feed_layout.setContentsMargins(13, 10, 13, 11)
        feed_header = QHBoxLayout()
        feed_title = QLabel("任务动态")
        feed_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        feed_header.addWidget(feed_title)
        feed_header.addStretch(1)
        feed_note = QLabel("结构化进度")
        feed_note.setObjectName("consoleBadge")
        feed_header.addWidget(feed_note)
        feed_layout.addLayout(feed_header)
        self.event_log = QListWidget()
        self.event_log.setObjectName("eventFeed")
        self.event_log.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.event_log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.event_log.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        feed_layout.addWidget(self.event_log, 1)
        left_column.addWidget(feed_card, 1)
        detail_row.addLayout(left_column, 5)

        console_card = QFrame()
        console_card.setObjectName("consoleCard")
        console_layout = QVBoxLayout(console_card)
        console_layout.setContentsMargins(13, 10, 13, 11)
        console_header = QHBoxLayout()
        console_title = QLabel("完整运行日志")
        console_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        console_header.addWidget(console_title)
        console_header.addStretch(1)
        console_badge = QLabel("已接入原 CMD 输出")
        console_badge.setObjectName("consoleBadge")
        console_header.addWidget(console_badge)
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
        detail_row.addWidget(console_card, 7)
        layout.addLayout(detail_row, 1)

        row = QHBoxLayout()
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

        self._active_stages = {}
        self._completed_stages = set()
        self._skipped_stages = set()
        self._recognition_terminal = ''
        self._failed_stages = set()
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

    def _show_console_context_menu(self, position):
        menu = QMenu(self.console_log)
        menu.setObjectName("warmContextMenu")
        menu.setStyleSheet(f"""
            QMenu {{
                background: {SURFACE}; color: {INK};
                border: 1px solid {LINE}; border-radius: 8px;
                padding: 5px;
                font-family: {UI_FONT_STACK}; font-size: 13px;
            }}
            QMenu::item {{ padding: 7px 28px 7px 10px; border-radius: 5px; }}
            QMenu::item:selected {{ background: {GREEN_SOFT}; color: {INK}; }}
            QMenu::item:disabled {{ color: {MUTED_LIGHT}; }}
        """)
        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.setEnabled(self.console_log.textCursor().hasSelection())
        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        selected = menu.exec(self.console_log.mapToGlobal(position))
        if selected is copy_action:
            self.console_log.copy()
        elif selected is select_all_action:
            self.console_log.selectAll()

    def _result_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 18, 28, 20)
        layout.setSpacing(11)
        summary_card = QFrame()
        summary_card.setObjectName("resultSummaryCard")
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(22, 18, 22, 18)
        summary_layout.setSpacing(16)
        self.result_icon = QLabel()
        self.result_icon.setFixedSize(88, 88)
        self.result_icon.setStyleSheet("padding:0; margin:0; border:none;")
        self.result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.result_icon)
        summary_copy = QVBoxLayout()
        summary_copy.setSpacing(4)
        self.result_title = QLabel("任务完成")
        self.result_title.setWordWrap(True)
        self.result_title.setStyleSheet(f"font-family: {TITLE_FONT_STACK}; font-size: 22px; font-weight: 800;")
        summary_copy.addWidget(self.result_title)
        self.result_summary = QLabel("")
        self.result_summary.setWordWrap(True)
        self.result_summary.setObjectName("muted")
        summary_copy.addWidget(self.result_summary)
        self.result_review_summary = QLabel("")
        self.result_review_summary.setWordWrap(True)
        self.result_review_summary.setObjectName("resultReviewSummary")
        summary_copy.addWidget(self.result_review_summary)
        summary_layout.addLayout(summary_copy, 1)
        summary_host = QHBoxLayout()
        summary_host.addWidget(summary_card, 1)
        layout.addLayout(summary_host)
        self.result_task_selector = QComboBox()
        self.result_task_selector.setMinimumContentsLength(20)
        self.result_task_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.result_task_selector.currentIndexChanged.connect(self._select_completion_task)
        layout.addWidget(self.result_task_selector)
        self.result_task_summary = QLabel("")
        self.result_task_summary.setWordWrap(True)
        layout.addWidget(self.result_task_summary)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(11)
        files_card = QFrame()
        files_card.setObjectName("resultFilesCard")
        files_layout = QVBoxLayout(files_card)
        files_layout.setContentsMargins(13, 10, 13, 12)
        files_title = QLabel("任务与输出")
        files_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        files_layout.addWidget(files_title)
        self.result_files = QTextEdit()
        self.result_files.setObjectName("resultFiles")
        self.result_files.setReadOnly(True)
        files_layout.addWidget(self.result_files, 1)
        detail_row.addWidget(files_card, 5)

        log_card = QFrame()
        log_card.setObjectName("resultLogCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(13, 10, 13, 12)
        result_log_header = QHBoxLayout()
        result_log_title = QLabel("本次完整运行日志")
        result_log_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        result_log_header.addWidget(result_log_title)
        result_log_header.addStretch(1)
        result_log_badge = QLabel("成功与失败均保留")
        result_log_badge.setObjectName("consoleBadge")
        result_log_header.addWidget(result_log_badge)
        log_layout.addLayout(result_log_header)
        self.result_console = QTextEdit()
        self.result_console.setObjectName("resultConsole")
        self.result_console.setReadOnly(True)
        self.result_console.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        log_layout.addWidget(self.result_console, 1)
        detail_row.addWidget(log_card, 7)
        self.result_detail_row = QWidget()
        self.result_detail_row.setLayout(detail_row)
        self.result_detail_row.hide()

        details_toggle = QToolButton()
        bind_text(details_toggle, '运行详情')
        details_toggle.setCheckable(True)
        details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        details_toggle.toggled.connect(
            lambda expanded: (
                self.result_detail_row.setVisible(expanded),
                details_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow),
            )
        )
        self.result_details_toggle = details_toggle

        primary_row = QHBoxLayout()
        primary_row.setSpacing(14)
        self.export_result_button = AnimatedButton("导出字幕")
        self.export_result_button.setObjectName("primary")
        self.export_result_button.setMinimumHeight(44)
        self.export_result_button.setStyleSheet("font-size:14px; font-weight:800; padding:10px 18px;")
        self.export_result_button.clicked.connect(self._export_completion_result)
        primary_row.addWidget(self.export_result_button, 1)
        self.burn_subtitle_result_button = AnimatedButton("压制字幕视频")
        self.burn_subtitle_result_button.setObjectName("softAction")
        install_themed_icon(self.burn_subtitle_result_button, "fa5s.film")
        self.burn_subtitle_result_button.setMinimumHeight(44)
        bind_text(self.burn_subtitle_result_button, '进入工作台调整字幕与样式，确认后再导出视频', property='toolTip')
        self.burn_subtitle_result_button.setStyleSheet("font-size:14px; font-weight:800; padding:10px 18px;")
        self.burn_subtitle_result_button.clicked.connect(self._open_render_from_result)
        primary_row.addWidget(self.burn_subtitle_result_button, 1)
        close = AnimatedButton("完成并返回主菜单")
        close.setObjectName("secondaryCTA")
        close.setMinimumHeight(36)
        bind_text(close, '保存工程并返回字幕识别', property='toolTip')
        close.setStyleSheet("font-size:14px; font-weight:800; padding:10px 18px;")
        close.clicked.connect(self._return_to_main_menu)
        layout.addLayout(primary_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.open_studio_result_button = AnimatedButton("打开字幕工作台")
        self.open_studio_result_button.setObjectName("softAction")
        self.open_studio_result_button.setIcon(_icon("fa5s.closed-captioning"))
        self.open_studio_result_button.clicked.connect(
            lambda: self.open_studio_project(getattr(self, "_last_studio_project", ""), mode="edit", source="completion_edit")
        )
        open_reports = AnimatedButton("打开报告目录")
        open_reports.setObjectName("softAction")
        open_reports.setMinimumSize(150, 42)
        open_reports.setIcon(_icon("fa5s.folder-open"))
        open_reports.clicked.connect(
            lambda: (
                Path(self.legacy.task_reporting.REPORT_ROOT).mkdir(parents=True, exist_ok=True),
                os.startfile(str(self.legacy.task_reporting.REPORT_ROOT)),
            )
        )
        open_subtitles = AnimatedButton("打开字幕目录")
        open_subtitles.setObjectName("softAction")
        open_subtitles.setMinimumSize(150, 42)
        open_subtitles.setIcon(_icon("fa5s.folder-open"))
        open_subtitles.clicked.connect(self._open_subtitle_dir)
        self.retry_failed_button = AnimatedButton("重试失败项")
        self.retry_failed_button.setObjectName("softAction")
        self.retry_failed_button.setIcon(_icon("fa5s.redo"))
        self.retry_failed_button.clicked.connect(self._retry_failed_items)
        self.retry_failed_button.hide()
        row.addWidget(self.retry_failed_button)
        self.open_priority_review_button = AnimatedButton("开始优先审核")
        self.open_priority_review_button.setObjectName("softAction")
        self.open_priority_review_button.setIcon(_icon("fa5s.flag"))
        self.open_priority_review_button.clicked.connect(self._open_priority_review_from_result)
        self.open_priority_review_button.hide()
        row.addWidget(self.open_priority_review_button)
        self.open_studio_result_button.setMinimumHeight(44)
        self.open_studio_result_button.setStyleSheet("font-size:14px; font-weight:800; padding:10px 18px;")
        primary_row.insertWidget(1, self.open_studio_result_button, 1)
        self.recover_recognition_button = AnimatedButton('恢复已有识别结果…')
        self.recover_recognition_button.setObjectName('softAction')
        self.recover_recognition_button.clicked.connect(self._recover_recognition_output)
        self.open_subtitle_result_button = open_subtitles
        open_subtitles.hide()
        row.addStretch(1)
        layout.addLayout(row)
        navigation = QHBoxLayout()
        navigation.addWidget(close)
        navigation.addWidget(open_subtitles)
        navigation.addWidget(open_reports)
        navigation.addWidget(self.recover_recognition_button)
        navigation.addStretch(1)
        navigation.addWidget(details_toggle)
        layout.addLayout(navigation)
        layout.addWidget(self.result_detail_row, 1)
        layout.addStretch(0)
        return page

    def _select_completion_task(self, index):
        tasks = getattr(self, "_completion_tasks", [])
        task = tasks[index] if 0 <= index < len(tasks) else None
        self._last_studio_project = task[0].project_path if task and task[1] else ""
        self._last_recognition_report = task[0].report_json_path if task else ""
        available = bool(task and task[1])
        for button in (self.export_result_button, self.open_studio_result_button, self.burn_subtitle_result_button):
            button.setEnabled(available)
        if not task:
            self.result_task_summary.setProperty("i18nTemplate",None)
            self.result_task_summary.clear()
            return
        item, project = task
        if project:
            from .studio_edit_sequence import timeline_duration_ms, projected_cues
            template = "时间轴 {duration} 秒 · {count} 条字幕 · 耗时 {elapsed} 秒"
            arguments = dict(duration=f"{timeline_duration_ms(project)/1000:.1f}",
                count=len(projected_cues(project)),elapsed=f"{item.elapsed_seconds:.1f}")
            self.result_task_summary.setProperty("i18nTemplate",template)
            self.result_task_summary.setProperty("i18nArguments",arguments)
            self.result_task_summary.setText(
                translate(template,getattr(self,"_ui_language","zh")).format(**arguments))
        else:
            self.result_task_summary.setProperty("i18nTemplate",None)
            self.result_task_summary.setText(item.error or item.status)

    def _export_completion_result(self):
        from .completion_export import CompletionExportDialog
        tasks = getattr(self, "_completion_tasks", [])
        index = self.result_task_selector.currentIndex()
        if not 0 <= index < len(tasks) or tasks[index][1] is None:
            return
        item, project = tasks[index]
        dialog = CompletionExportDialog(project, Path(item.media_path).stem, self,
                                        getattr(self, "_ui_language", "zh"))
        if dialog.exec() and dialog.artifacts:
            self._last_srt_dir = str(dialog.artifacts[0].path.parent)
            self.open_subtitle_result_button.show()
            self.result_files.append("\n".join(str(a.path) for a in dialog.artifacts))

    def _style_active_tasks_label(self) -> None:
        theme = _active_theme_definition()
        label = getattr(self, "active_tasks_label", None)
        if label is not None:
            label.setStyleSheet(
                f"background: {theme.panel}; border-radius: 8px; padding: 7px 9px; color: {theme.text_secondary};"
            )

    def _return_to_main_menu(self):
        """Leave a completed/failed result on screen until the user is ready,
        then return to recognition without terminating the workbench process."""
        dialog = getattr(self, "_completion_dialog", None)
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
        self.open_studio_project(project, mode="review", source="completion_review")

    def _open_render_from_result(self) -> None:
        project = getattr(self, "_last_studio_project", "")
        if not project:
            return
        # 三十六轮：完成后主按钮落在工作台编辑区（用户要先调整字幕再导出），
        # 不再直达导出对话框；导出仍可从工作台内发起。
        self.open_studio_project(project, mode="edit", source="completion_studio")

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

    def _retry_failed_items(self):
        failed = getattr(self, "_last_failed_items", [])
        if not failed:
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
        self.media_paths = _merge_media_paths([], [f.media_path for f in failed])
        self._retry_cached_failed=True
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
            self.language_combo.setMinimumWidth(100)
            self.header_content.layout().invalidate()
            compact = (self.width() < 1050 or self.header_content.width()
                       < self.header_content.layout().sizeHint().width())
            self.header_mascot.setVisible(True)
            self.brand.setVisible(True)
            self.header_subtitle.setVisible(True)
            self.language_combo.setMinimumWidth(72 if compact else 100)
            self.app_header.setFixedHeight(104)
            for button, label in navigation:
                button.setAccessibleName(tr(label))
                button.setToolTip(tr(label))
                button.setText("" if compact else translate(label, current_language()))
                button.setMinimumWidth(36 if compact else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_header_density()
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.setGeometry(self.rect().adjusted(16, 16, -16, -16))
        if hasattr(self, "_modal_host") and self._modal_host.isVisible():
            self._modal_host.resize_to_parent()
        if not hasattr(self, "studio_page") or self.pages.currentWidget() is not self.studio_page:
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
        if os.name == "nt" and not self.isMaximized():
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
        if hasattr(self, "studio_page") and self.pages.currentWidget() is self.studio_page:
            return
        comfortable = self.width() >= 1600
        # Recognition cards also depend on their current height, so let that
        # lightweight cached path run on every resize.
        if hasattr(self, "recognition_plan"):
            self.recognition_plan.apply_density(comfortable)
        if self._density_comfortable is comfortable:
            return
        self._density_comfortable = comfortable
        if hasattr(self, "settings_surface"):
            # Use a minimum; allow layout-driven growth on tall windows.
            self.settings_surface.setMinimumHeight(320 if comfortable else 300)
        if hasattr(self, "setting_tiles"):
            for tile in self.setting_tiles.values():
                tile.apply_density(comfortable)
        if hasattr(self, "workshop_page"):
            self.workshop_page.apply_density(comfortable)

    def refresh_theme_palette(self) -> None:
        """Refresh MainWindow-owned inline colors after a global theme switch."""
        if hasattr(self, "media_name") and hasattr(self, "media_drop_hint"):
            self._style_media_summary()
        # The runtime-page active-tasks box is styled inline (not via the global
        # QSS), so it must be re-styled here too. A second same-name definition
        # used to shadow this call and left the box on its build-time theme.
        self._style_active_tasks_label()

    def _style_media_summary(self) -> None:
        theme = _active_theme_definition()
        if hasattr(self, "media_type_icon"):
            self.media_type_icon.setPixmap(themed_icon("fa5s.file-audio", theme=theme).pixmap(QSize(20, 20)))
        self.media_name.setStyleSheet(f"font-weight: 700; color: {theme.text};")
        self.media_drop_hint.setStyleSheet(
            f"color: {theme.text_secondary}; font-size: 13px;"
        )
        if hasattr(self, "media_origin_label"):
            self.media_origin_label.setStyleSheet(
                f"color:{theme.accent}; font-size:12px; font-weight:700;"
            )

    def _refresh_media_summary(self):
        language = getattr(self, "_ui_language", current_language())
        ready = bool(self.media_paths)
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
            bind_text(self.media_drop_hint, translate('可继续拖入另一批素材，或点击右侧重新选择', language))
            bind_text(self.header_status, f'●  {len(self.media_paths)} ' + ('media items ready' if language == 'en' else '个素材已就绪'))
        else:
            bind_text(self.media_name, translate('把视频或音频拖到这里', language))
            self.media_name.setToolTip("")
            bind_text(self.media_drop_hint, translate('支持多选；也可以点击右侧“选择素材”', language))
            bind_text(self.header_status, '● ' + translate('等待素材', language))
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
        self.project_profile_combo.addItem("自定义方案", "")
        for profile in self.profile_store.list():
            self.project_profile_combo.addItem(profile.name, profile.id)
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
        # 先落全局（configure_runtime_asr 内部深拷贝+落盘+刷新模块全局），
        # 这样后续 _apply_asr_preset_fields 读到的"已保存值"就是快照本身。
        if persist:
            self.legacy.configure_runtime_asr(models, qwen_asr_key="")
        provider = models.get("qwen_asr_api_provider", "")
        provider_index = self.qwen_asr_api_provider.findData(provider) if provider else -1
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
            provider = str(self.qwen_asr_api_provider.currentData() or "dashscope")
            base = self.qwen_asr_api_url.text().strip()
            existing, source = read_api_key(provider, base)
            if not existing:
                existing, source = resolve_api_key("qwen_asr")
            (bind_text(self.qwen_asr_api_key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.qwen_asr_api_key, '请输入 DashScope API Key', property='placeholderText'))
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
        if bind_project and self.studio_page.project:
            self.studio_page.project.studio_state["profile_id"] = profile.id
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
        if getattr(self, "_applying_recognition_plan", False):
            return
        key = str(self.recognition_mode_combo.currentData() or "custom")
        plan = recognition_plan(key)
        if key != "custom" and all(hasattr(self, name) for name in ("primary_asr_backend", "firered_asr_backend", "qwen_asr_backend")):
            self._applying_recognition_plan = True
            try:
                self._set_backend_combo(self.primary_asr_backend, plan.primary)
                self._set_backend_combo(self.firered_asr_backend, plan.timeline)
                self._set_backend_combo(self.qwen_asr_backend, plan.review)
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
        key = matching_plan(primary, timeline, review)
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
        accepted = self._supported_paths(paths)
        if accepted:
            event.acceptProposedAction()
            self.drop_overlay.set_file_count(len(accepted))
            self._set_drop_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        accepted = self._supported_paths(paths)
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
        accepted = self._supported_paths(paths)
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

    def _auto_enable_terms(self, value: str):
        if self.legacy.clean_subtitle_text(value):
            self.terms.setChecked(True)
        self._resolve_glossary_binding()

    def _resolve_glossary_binding(self) -> dict:
        name = self.legacy.canonicalize_runtime_game_name(self.game_box.currentText())
        resolver = GlossaryBindingResolver(self.legacy)
        result = resolver.resolve(name, self.legacy.runtime_game_identity(name), self.terms.isChecked())
        self._glossary_binding = result
        if self.terms.isChecked():
            settings = self.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
            settings["enabled_glossary_ids"] = list(result["active_glossaries"])
            settings["enable_domain_terms"] = bool(result["active_glossaries"])
            if hasattr(self, "batch_glossary_status"):
                labels = [item["label"] for item in result["matched_glossaries"]]
                (bind_text(self.batch_glossary_status, '术语增强 ON\n已绑定：{value0}', value0='、'.join(labels)) if labels else bind_text(self.batch_glossary_status, '未找到匹配词库'))
            self._save_glossary_settings()
        elif hasattr(self, "batch_glossary_status"):
            bind_text(self.batch_glossary_status, '术语增强 OFF')
        if hasattr(self, "_refresh_glossary_chips"):
            self._refresh_glossary_chips()
        return result

    def _asr_values(self):
        provider = str(self.qwen_asr_api_provider.currentData() or "dashscope")
        preset = ASR_API_PRESETS.get(provider, ASR_API_PRESETS["dashscope"])
        return {
            "speaker_source": self.legacy.RUNTIME_SETTINGS['models'].get('speaker_source','single'),
            "primary_asr_backend": str(self.primary_asr_backend.currentData()),
            "qwen_asr_backend": str(self.qwen_asr_backend.currentData()),
            "qwen_asr_model": self.legacy.RUNTIME_SETTINGS["models"].get(
                "qwen_asr_model", "Qwen/Qwen3-ASR-1.7B"
            ),
            "qwen_asr_api_provider": provider,
            "qwen_asr_api_protocol": preset["protocol"],
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
        provider = str(self.qwen_asr_api_provider.currentData() or "dashscope")
        label = ASR_API_PRESETS.get(provider, ASR_API_PRESETS["dashscope"])["label"]

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
        full.clicked.connect(lambda: (pop.close(), self._open_asr_api_full_tutorial_dialog(provider)))
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
        header.addWidget(bind_text(QLabel(), '<b>当前选择</b>：{value0}', value0=ASR_API_PRESETS.get(provider, ASR_API_PRESETS['dashscope'])['label']), 1)
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
        provider = str(self.qwen_asr_api_provider.currentData() or "dashscope")
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
        provider = str(self.qwen_asr_api_provider.currentData() or "dashscope")
        if provider in {'spark_asr_v2','qwen31_flash','qwen31_filetrans'}:
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
        prov = str(self.qwen_asr_api_provider.currentData() or "dashscope")
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
            prov = str(self.qwen_asr_api_provider.currentData() or "dashscope")
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
        from .speaker_strategy import execution_plan
        speaker_plan=execution_plan(self.legacy.RUNTIME_SETTINGS)
        if hasattr(self,'speaker_plan_summary'):
            active=getattr(self,'current_project_profile',None)
            bind_text(self.speaker_plan_summary, tr('说话人区分：{strategy} · 当前方案：{profile}\n{steps}', strategy=tr(speaker_plan.label), profile=active.name if active else tr('当前默认配置'), steps=' → '.join((tr(step) for step in speaker_plan.steps))))
        if not hasattr(self, "asr_panel"):
            return
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
        key_ready = bool(
            read_asr_api_key(
                str(_models_cfg.get("qwen_asr_api_provider", "dashscope") or "dashscope"),
                str(_models_cfg.get("qwen_asr_api_url", "") or ""),
            )[0]
            or self.qwen_asr_api_key.text().strip()
        )
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

        def _status(role: str, backend: str) -> tuple[str, str, str]:
            """(kind, status_text, tone)。tone: good/warn/muted。"""
            if backend == "off":
                return ("", "已关闭", "muted")
            if backend == "api":
                if key_ready:
                    return ("在线", "已配置", "good")
                return ("在线", "未配置", "warn")
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
            for role, backend in (
                ("primary", primary_backend),
                ("timeline", firered_backend),
                ("review", qwen_backend),
            ):
                _kind, status, _tone = _status(role, backend)
                if status in {"需要下载", "未配置"}:
                    problems.append(status)
            glossary_count = len(self._enabled_glossary_ids())
            if problems:
                self.action_status.setObjectName("statusWarn")
                pending = ", ".join(translate(item, language) for item in dict.fromkeys(problems))
                if language == "en":
                    text = f"⚠ Recognition plan needs attention: {pending}"
                elif language == "ja":
                    text = "⚠ " + translate("识别方案待处理：", language) + "・".join(
                        translate(item, language) for item in dict.fromkeys(problems)
                    )
                else:
                    text = f"⚠ 识别方案待处理：{'、'.join(dict.fromkeys(problems))}"
                self.action_status.setText(text)
            else:
                self.action_status.setObjectName("statusGood")
                if language == "en":
                    text = f"✔ Recognition plan and {glossary_count} term libraries are ready"
                elif language == "ja":
                    text = "✔ " + translate("识别方案与 {n} 个词库已就绪", language).replace("{n}", str(glossary_count))
                else:
                    text = f"✔ 识别方案与 {glossary_count} 个词库已就绪"
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
        if self.pages.currentWidget() is self.studio_page:
            return  # Home-only caches are irrelevant to Studio's first paint.
        import time as _t
        _t0 = _t.perf_counter()
        try:
            # 1) Model install status (used by workshop + picker cards)
            keys = installed_model_keys(APP_ROOT)
            # Optionally warm the workshop cache if present (cheap assignment, no UI rebuild)
            if hasattr(self, "workshop_page"):
                try:
                    self.workshop_page._installed = set(keys)
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
        if "安装" in action or "下载" in action:
            self._open_model_picker(role)
        elif "API" in action or "配置" in action:
            self._open_api_key_dialog()

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
        from .design.presentation import button_role
        close_header = button_role(QPushButton("×"), "ghost")
        close_header.setFixedSize(32, 32)
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
            if enabled:
                names = [self._glossary_display_name(identity) for identity in enabled[:3]]
                suffix = "…" if len(enabled) > 3 else ""
                if current_language() == "en":
                    self.batch_glossary_status.setText(
                        f"Glossary ON\nBound: {', '.join(names)}{suffix}"
                    )
                else:
                    bind_text(self.batch_glossary_status, '术语增强 ON\n已绑定：{value0}{suffix}', value0='、'.join(names), suffix=suffix)
            elif terms_on:
                bind_text(self.batch_glossary_status, translate('未找到匹配词库', current_language()))
            else:
                bind_text(self.batch_glossary_status, translate('术语增强 OFF', current_language()))
            bind_text(self.add_glossary_button, translate('管理术语库', current_language()))

    def _glossary_display_name(self, identity: str) -> str:
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
            self.legacy.RUNTIME_SETTINGS["glossary"]["enable_domain_terms"] = bool(
                self._enabled_glossary_ids()
            )
            save_runtime_settings(self.legacy.RUNTIME_SETTINGS)
        except Exception:
            pass
        self._refresh_asr_summary()

    def _remove_glossary(self, identity: str):
        enabled = [i for i in self._enabled_glossary_ids() if i != identity]
        self.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled
        self._save_glossary_settings()
        bind_text(self.term_hint, translate('已从本批词库移除', current_language()))
        self.term_hint.setVisible(bool(self.term_hint.text()))

    def _pick_glossaries(self):
        """打开可搜索的多选词库选择器。 P0: use ModalHost (no native window), skeleton first."""
        import time as _t
        self._popup_click_ts = _t.perf_counter()
        self._popup_first_paint_title = "本批字幕使用的词库"
        picker = GlossaryPickerDialog(self, self._modal_host.body)
        # Populate on next tick
        QTimer.singleShot(0, picker, picker._populate)

        def _after_close():
            chosen = picker.take_result() or []
            if chosen:
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
                    save_api_key_for(av.get("qwen_asr_api_provider", "dashscope"), av.get("qwen_asr_api_url", ""), qk)
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
        prov = av.get("qwen_asr_api_provider", "dashscope")
        burl = av.get("qwen_asr_api_url", "")
        existing, source = read_api_key(prov, burl)
        if not existing:
            existing, source = resolve_api_key("qwen_asr")
        (bind_text(self.qwen_asr_api_key, '已配置：{value0}', property='placeholderText', value0=source) if existing else bind_text(self.qwen_asr_api_key, '请输入 DashScope API Key', property='placeholderText'))
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
        self._refresh_asr_summary()
        return True

    def _refresh_ai_summary(self):
        language = getattr(self, "_ui_language", current_language())
        group = self.group_editor.model.currentText().strip()
        if hasattr(self, "ai_grouping") and not self.ai_grouping.isChecked():
            summary = translate("已关闭 · 使用本地断句规则", language)
        else:
            group_transport = str(self.group_editor.transport.currentData() or AITransport.OPENAI_COMPATIBLE.value)
            if group_transport == AITransport.ANTIGRAVITY_CLI.value:
                summary = translate("Google Antigravity · 登录态由官方 CLI 管理", language)
                self.ai_panel.set_summary(summary)
                return
            if group_transport == AITransport.GROK_CLI.value:
                summary = translate("Grok Account · OAuth 由官方 CLI 管理", language)
                self.ai_panel.set_summary(summary)
                return
            group_provider = str(self.group_editor.provider.currentData() or "custom")
            group_base = normalize_base_url(self.group_editor.base_url.text())
            configured = bool(read_api_key(group_provider, group_base)[0])
            if not configured and group_provider in {"bailian", "dashscope"}:
                configured = bool(resolve_api_key("group")[0])
            if not configured or not group:
                summary = translate("选择 API 厂商、模型并填写 API Key", language)
            else:
                base_url = self.group_editor.base_url.text().strip().casefold()
                provider = (
                    "DeepSeek"
                    if "deepseek" in base_url or group.casefold().startswith("deepseek")
                    else self.group_editor.provider.currentText().strip()
                )
                # P1: distinguish "key present" vs "verified live". We only know key presence here.
                # After a successful test in the editor this session the ConnectionTester will have shown "连接正常".
                # On first load with key we show 未验证 so user knows a live check is still useful.
                summary = f"{provider} · {group} · " + translate("已配置 · 未验证", language)
        polish_status = self.polish_editor.model.currentText().strip() if self.ai_polish.isChecked() else translate('未启用', language)
        summary = translate('校对：{polish} · 断句：{group}', language).format(polish=polish_status, group=summary)
        self.ai_panel.set_summary(summary)
        if hasattr(self, "setting_tiles"):
            self.setting_tiles["ai"].set_summary(summary)

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

    def _start_run(self):
        # P1-4 重入守卫：任意时刻最多一个 active run。必须在任何耗时准备
        # （CUDA 探测、配置保存、文件检查、token/worker 构建）之前声明占用；
        # 重复调用为 no-op（不创建 token、不覆盖 worker、不重置 UI）。
        if self._run_in_progress:
            self._run_block_reason = "已有识别任务在进行中，请等待完成或先取消。"
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
                _url = str(_models.get("qwen_asr_api_url", "") or "")
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
            enabled_glossary_ids = tuple(
                studio_context["enabled_glossary_ids"]
                if "enabled_glossary_ids" in studio_context
                else self._enabled_glossary_ids()
            )
            # Persist output extras so the same-folder artifact set stays stable
            # between runs (merged SRT is always written; txt/per-speaker opt-in).
            try:
                switches = self.legacy.RUNTIME_SETTINGS.setdefault("switches", {})
                switches["output_jianying_txt"] = self.jianying_txt.isChecked()
                switches["output_speaker_tracks"] = self.speaker_tracks.isChecked()
                save_runtime_settings(self.legacy.RUNTIME_SETTINGS)
            except Exception:
                pass
            options = RunOptions(
                settings_snapshot_json=json.dumps(self.legacy.RUNTIME_SETTINGS, ensure_ascii=False),
                content_name=game_name,
                enable_domain_terms=bool(enabled_glossary_ids),
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
            self.token = CancellationToken()
            self.worker = PipelineWorker(
                self.media_paths,
                options,
                self.token,
                self.legacy,
                self.pipeline,
                self.startup_self_test,
            )
            self.worker.event_received.connect(self._handle_event)
            self.worker.console_received.connect(self._append_console_line)
            self.worker.result_ready.connect(self._handle_result)
            self.worker.unexpected_error.connect(self._handle_unexpected_error)
            # P1-4 兜底：run() 中 try 之外的异常（如 SignalTextStream 构造
            # 失败）不会触发 result_ready/unexpected_error；finished 幂等
            # 释放保证 UI 不会永久锁在运行状态（正常路径 finished 晚于
            # 上述信号，重复释放无害）。
            self.worker.finished.connect(self._release_run_state)
            self.started_at = time.perf_counter()
            self._active_stages.clear()
            self._completed_stages.clear()
            self._skipped_stages = set()
            self._recognition_terminal = ''
            self._recognition_live_work = {}
            if hasattr(self,'recognition_live_status'):
                bind_text(self.recognition_live_status, '正在准备识别任务；临时转写将在实际批次完成后显示')
            self._failed_stages.clear()
            self.event_log.clear()
            self.console_log.clear()
            self.progress_bar.setValue(0)
            self.progress_percent.setText("0%")
            self.cancel_run_button.setEnabled(True)
            self._append_feed("准备", "配置已确认，正在建立任务队列", GREEN)
            self._progress_timer.start()
            self.workflow.set_active(0)
            if not getattr(self, "_studio_recognition_context", None):
                self._switch_page(1)
                from .ui_motion import recognition_launch_cue
                recognition_launch_cue(self.pages.currentWidget())
            started_profile = getattr(self, 'current_project_profile', None)
            started_configuration = self._profile_configuration()
            self.worker.start()
            self._retry_cached_failed=False
            launched = True
            try:
                self.profile_store.record_started(started_profile.id if started_profile else '',
                    started_configuration, self.media_paths)
            except (OSError, ValueError) as exc:
                bind_text(self.profile_recommendation, '识别已启动；上次运行配置保存失败：{exc}', exc=exc)
        finally:
            if not launched:
                # 准备阶段（worker.start 前）的任何提前返回 / 异常都必须
                # 释放占用，否则 UI 会永久锁死在运行状态。
                self._release_run_state()

    def _stage_group(self, stage_index: int) -> int:
        if stage_index <= 7:
            return 0
        if stage_index == 8:
            return 1
        if stage_index <= 10:
            return 2
        return 3

    def _append_feed(self, badge: str, message: str, color: str = MUTED):
        item = QListWidgetItem()
        card = TaskEventCard(badge, message, color)
        item.setSizeHint(QSize(0, max(50, card.sizeHint().height())))
        self.event_log.addItem(item)
        self.event_log.setItemWidget(item, card)
        while self.event_log.count() > 60:
            self.event_log.takeItem(0)
        self.event_log.scrollToBottom()
        # Only the newly created card needs a language overlay. Walking the
        # complete window here made long runs progressively more expensive.
        apply_ui_language(card, getattr(self, "_ui_language", "zh"))

    def _append_console_line(self, line: str, level: str = "stdout"):
        compact = str(line or "").rstrip()
        if not compact:
            return
        lowered = compact.lower()
        if getattr(self, "_studio_recognition_context", None):
            if "cuda" in lowered or "显存" in compact:
                self.studio_page.set_recognition_runtime_stage("初始化 CUDA", compact)
            elif "加载" in compact and ("模型" in compact or "asr" in lowered):
                self.studio_page.set_recognition_runtime_stage("加载权重", compact)
            elif "转写" in compact or "短块" in compact:
                self.studio_page.set_recognition_runtime_stage("识别中", compact)
        fatal_markers = (
            "traceback",
            "[文件失败]",
            "[阶段失败]",
            "已停止写入",
            "fatal error",
            "致命",
        )
        recoverable_markers = (
            "[警告]",
            "warning",
            "最终回退",
            "连续失败",
            "403",
            "forbidden",
        )
        if any(marker in lowered for marker in fatal_markers):
            color, background = "#ffb09d", "#47332e"
        elif any(marker in lowered for marker in recoverable_markers):
            color, background = "#f2c66d", "#3d392c"
        elif level == "stderr":
            color, background = "#c7d3c5", "#303530"
        elif "缓存命中" in compact or "缓存写入" in compact:
            color, background = "#a8d5ef", "#2f383b"
        elif "完成" in compact or "成功" in compact:
            color, background = "#a9d8a4", "#303a30"
        elif compact.startswith("[阶段") or compact.startswith("===="):
            color, background = "#f4e7bd", "#393832"
        else:
            color, background = "#edf0e9", "transparent"
        safe = html.escape(compact).replace(" ", "&nbsp;")
        append_log_html_keep_left(
            self.console_log,
            f'<div style="color:{color}; background:{background}; margin:1px 0; '
            f'padding:2px 4px; white-space:pre;">{safe}</div>',
        )

    def _refresh_progress_cards(self):
        language = getattr(self, "_ui_language", "zh")
        terminal = getattr(self, '_recognition_terminal', '')
        phase_stages = (
            set(range(1, 8)),
            {8},
            {9, 10},
            {11},
        )
        active_ids = set(self._active_stages)
        for index, (card, ids) in enumerate(zip(self.phase_cards, phase_stages)):
            if ids & self._failed_stages:
                state = "failed"
            elif ids <= self._completed_stages or terminal in {'success', 'degraded_success'}:
                state = "done"
            elif ids & active_ids:
                state = "active"
            else:
                state = "pending"
            card.set_state(state)
        if terminal:
            self.running_indicator.set_running(False)
            bind_text(self.progress_stage, {'success': '完成', 'degraded_success': '完成，有需复核项', 'failed': '任务结束，有失败项', 'cancelled': '任务已取消'}.get(terminal, '任务结束'))
            bind_text(self.progress_resource, '字幕文件与工程交付状态见结果页')
            bind_text(self.active_tasks_label, '识别子任务已退出')
        elif active_ids:
            focus_id = max(active_ids)
            focus = self._active_stages[focus_id]
            bind_text(self.progress_stage, focus["label"])
            bind_text(self.progress_resource, focus["resource"])
            rows = [
                f'{translate(item["label"], language)}  ·  {translate(item["resource"], language)}'
                for _, item in sorted(self._active_stages.items())
            ]
            prefix = translate("并行运行中" if len(rows) > 1 else "运行中", language)
            self.active_tasks_label.setText(prefix + "\n" + "\n".join(rows))
            self.running_indicator.set_running(True)
            self.workflow.set_active(self._stage_group(focus_id))
        elif self._completed_stages:
            last_id = max(self._completed_stages)
            bind_text(self.progress_stage, translate('正在衔接下一阶段', language))
            bind_text(self.progress_resource, '阶段 {stage} 已完成，正在准备后续资源', stage=last_id)
            bind_text(self.active_tasks_label, translate('当前没有并行子任务，正在进行阶段切换', language))
            self.running_indicator.set_running(False)
        else:
            self.running_indicator.set_running(False)

        total_stages = max(1, self._stage_total)
        finished = len(self._completed_stages)
        media_total = max(1, self._current_media_total)
        media_index = max(1, self._current_media_index)
        fraction = ((media_index - 1) + finished / total_stages) / media_total
        value = max(0, min(1000, int(round(fraction * 1000))))
        if terminal in {'success', 'degraded_success'}:
            value = 1000
        if self.progress_bar.value() != value:
            self._progress_motion.stop()
            self._progress_motion.setStartValue(self.progress_bar.value())
            self._progress_motion.setEndValue(value)
            self._progress_motion.start()
        self.progress_percent.setText(f"{round(value / 10):.0f}%")
        bind_text(self.progress_context, '素材 {media_index} / {media_total}  ·  已完成 {finished} / {total_stages} 个阶段', media_index=media_index, media_total=media_total, finished=finished, total_stages=total_stages)
        if terminal:
            skipped = len(getattr(self, '_skipped_stages', ()))
            bind_text(self.progress_context, '任务已结束 · {value0} 个阶段完成 · {skipped} 个阶段不适用', value0=finished - skipped, skipped=skipped)

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

    def _handle_event(self, event):
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
            self._recognition_live_work['nemotron']={'kind':event.kind,'payload':dict(payload),'at':time.monotonic()}
            self._append_feed('说话人区分',label,BLUE)
            if getattr(self,'_studio_recognition_context',None):self.studio_page.set_recognition_runtime_stage(label,'')
            self._update_progress_clock()
        elif event.kind in {'asr_progress','asr_evidence_delta','asr_worker_progress','asr_wait'}:
            payload=event.payload; backend=str(payload.get('backend','asr'))
            label=recognition_event_text(event.kind,payload)
            if not hasattr(self,'_recognition_live_work'):self._recognition_live_work={}
            prior=self._recognition_live_work.get(backend,{})
            self._recognition_live_work[backend]={'kind':event.kind,'payload':dict(payload),'at':time.monotonic() if event.kind in {'asr_progress','asr_evidence_delta'} else prior.get('at')}
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
            self._stage_total = max(1, event.stage_total)
            self._current_media_index = max(1, event.media_index)
            self._current_media_total = max(1, event.media_total)
            self._active_stages[event.stage_index] = {
                "label": event.label,
                "resource": event.resource,
                "started": time.perf_counter(),
            }
            self._append_feed("开始", join_text((tr(event.label),tr(event.resource))), self.phase_cards[self._stage_group(event.stage_index)].accent)
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
            if event.kind == 'stage_skipped':
                if not hasattr(self, '_skipped_stages'):self._skipped_stages=set()
                self._skipped_stages.add(event.stage_index)
                self._append_feed('跳过', tr('{stage} · 本次配置不适用', stage=tr(event.label)), BLUE)
            else:
                self._append_feed("完成", tr('{stage} · {seconds:.1f} 秒', stage=tr(event.label), seconds=event.elapsed_seconds), GREEN)
        elif event.kind in {"stage_failed", "media_failed"}:
            if event.stage_index:
                self._active_stages.pop(event.stage_index, None)
                self._failed_stages.add(event.stage_index)
            self._append_feed("失败", join_text((tr(event.label) if event.label else Path(event.media_path).name, tr(event.error))), CORAL)
        elif event.kind == "cache_hit":
            stage = event.payload.get("stage", "")
            self._append_feed("缓存", tr('复用 {stage}，跳过重复计算', stage=tr(stage)), BLUE)
        elif event.kind == "cloud_batches_parallel":
            self._append_feed(
                "并行",
                tr('{count} 个云端批次，最多 {workers} 路', count=event.payload.get('batches',0), workers=event.payload.get('workers',1)),
                PURPLE,
            )
        elif event.kind == "cloud_batch_completed":
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
        elif event.kind == "media_completed":
            self._append_feed("素材", tr('已完成 {name}', name=Path(event.media_path).name), GREEN)
            if getattr(self, "_studio_recognition_context", None):
                self.studio_page.finish_recognition_runtime(event.elapsed_seconds)
        self._refresh_progress_cards()

    def _cancel_run(self):
        if not self.token:
            return
        self.token.cancel()
        self.cancel_run_button.setEnabled(False)
        bind_text(self.progress_stage, '正在安全取消…')
        bind_text(self.progress_resource, '将在当前可安全停止的阶段边界退出')
        self._append_feed("取消", "已发出安全取消请求，正在等待当前阶段收尾", AMBER)
        # 四十三轮：Studio 后台识别的取消此前只写主页进度页控件——留在
        # Studio 的用户完全看不到反馈（"点了取消没反应"）。同步落到
        # 字幕列表芯片与"暂无字幕"状态卡，并禁用取消按钮防重复点击。
        if getattr(self, "_studio_recognition_context", None):
            studio_page = getattr(self, "studio_page", None)
            if studio_page is not None:
                studio_page.set_recognition_cancelling()

    def _back_to_studio_from_progress(self):
        """从主页详细进度页回到 Studio 工程（识别继续后台运行）。"""
        studio_page = getattr(self, "studio_page", None)
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
        if self.isMinimized():
            self.showNormal()
        self.show()
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
        report_path=getattr(self,'_last_recognition_report','')
        if not report_path or not Path(report_path).is_file():
            report_path,_=QFileDialog.getOpenFileName(self,tr('选择已有字幕任务报告'),'','任务报告 (*.json)')
        if not report_path:return
        try:
            from .recognition_recovery import recover_report
            path=recover_report(report_path)
            self._last_studio_project=str(path)
            self.open_studio_project(path,mode='edit',source='recognition_recovery')
        except Exception as exc:
            QMessageBox.warning(self,tr('恢复未完成'),tr('{value0}\n原工程及字幕输出保持不变。', value0=str(exc)))

    def _handle_result(self, result):
        self._release_run_state()
        self._progress_timer.stop()
        self.result_exit_code = result.exit_code
        self._recognition_terminal = ('failed' if result.failures else 'cancelled' if result.cancelled
            else 'degraded_success' if any(item.status=='degraded_success' for item in result.results) else 'success')
        self._active_stages.clear()
        if hasattr(self, '_progress_motion'):self._progress_motion.stop()
        self._refresh_progress_cards()
        self.workflow.set_active(3, finished=True)
        success_count = len(result.successes)
        failure_count = len(result.failures)
        cancel_count = len(result.cancelled)
        if failure_count:
            color, icon_name, title = CORAL, "fa5s.exclamation-circle", "部分任务失败"
        elif cancel_count:
            color, icon_name, title = AMBER, "fa5s.stop-circle", "任务已取消"
        else:
            color, icon_name, title = GREEN, "fa5s.check-circle", (
                '完成，有需复核项' if self._recognition_terminal=='degraded_success' else '字幕生成完成')
        self.result_icon.setPixmap(_icon(icon_name, color).pixmap(QSize(72, 72)))
        bind_text(self.result_title, title)
        self.result_title.setProperty("i18nText",title)
        self.result_summary.setProperty("i18nTemplate","成功 {success} 个 · 失败 {failure} 个 · 取消 {cancel} 个 · 总耗时 {elapsed} 秒")
        self.result_summary.setProperty("i18nArguments",dict(success=success_count,failure=failure_count,cancel=cancel_count,elapsed=f"{result.elapsed_seconds:.1f}"))
        bind_text(self.result_summary, '成功 {success_count} 个 · 失败 {failure_count} 个 · 取消 {cancel_count} 个 · 总耗时 {value3:.1f} 秒', success_count=success_count, failure_count=failure_count, cancel_count=cancel_count, value3=result.elapsed_seconds)
        review_total = 0
        high_risk = 0
        cue_total = 0
        polish_details={}
        retry_partial_paths=set()
        from .main_ui_helpers import polishing_completion_details
        for media_result in result.results:
            report_path = getattr(media_result, "report_json_path", "")
            if not report_path:
                continue
            try:
                report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            report_result = report.get("result", {}) if isinstance(report, dict) else {}
            lines,retry=polishing_completion_details(report if isinstance(report,dict) else {})
            polish_details[media_result.media_path]=lines
            if retry:
                retry_partial_paths.add(media_result.media_path)
            cue_total += int(report_result.get("cue_count", 0) or 0)
            counts = report.get("review_severity_counts", {}) if isinstance(report, dict) else {}
            review_total += sum(int(counts.get(key, 0) or 0) for key in ("error", "warning", "review"))
            high_risk += sum(int(counts.get(key, 0) or 0) for key in ("error", "warning"))
        if cue_total and hasattr(self, "result_review_summary"):
            suggested = min(cue_total, review_total)
            confident = max(0, cue_total - suggested)
            minutes = 0 if suggested == 0 else max(1, round(suggested * 0.15))
            bind_text(self.result_review_summary, '共 {cue_total} 条字幕 · 高置信度 {confident} 条 · 建议检查 {suggested} 条 · 高风险 {high_risk} 条 · 预计人工审核约 {minutes} 分钟', cue_total=cue_total, confident=confident, suggested=suggested, high_risk=high_risk, minutes=minutes)
            self.result_review_summary.setProperty("i18nTemplate","共 {total} 条字幕 · 建议检查 {review} 条 · 高风险 {risk} 条")
            self.result_review_summary.setProperty("i18nArguments",dict(total=cue_total,review=suggested,risk=high_risk))
        elif hasattr(self, "result_review_summary"):
            self.result_review_summary.setProperty("i18nTemplate",None)
            self.result_review_summary.setText("")
        if retry_partial_paths and not failure_count and not cancel_count:
            bind_text(self.result_title, '字幕已生成，部分校对待完成')
            self.result_title.setProperty("i18nText",'字幕已生成，部分校对待完成')
            self.result_icon.setPixmap(_icon('fa5s.exclamation-circle',AMBER).pixmap(QSize(72,72)))
        rows = []
        self._last_studio_project = ""
        self._last_recognition_report = next((item.report_json_path for item in result.results if item.report_json_path),'')
        completion_theme = _active_theme_definition()
        for item in result.results:
            status_spec = {
                "success": ("完成", completion_theme.success, completion_theme.accent_soft),
                "degraded_success": ("完成，有需复核项", completion_theme.warning, completion_theme.warning_soft),
                "failed": ("失败", completion_theme.danger, completion_theme.danger_soft),
                "cancelled": ("取消", completion_theme.warning, completion_theme.warning_soft),
                "skipped": ("跳过", completion_theme.focus, completion_theme.selected),
            }.get(item.status, (item.status, completion_theme.text_muted, completion_theme.panel))
            status_text, status_color, background = status_spec
            details = []
            details.extend(html.escape(line) for line in polish_details.get(item.media_path,[]))
            if item.srt_path:
                details.append(f"字幕：{html.escape(item.srt_path)}")
                self._last_srt_dir = str(Path(item.srt_path).parent)
            if getattr(item, "project_path", "") and Path(item.project_path).is_file():
                self._last_studio_project = item.project_path
                details.append(f'工程（可重新载入）：{html.escape(item.project_path)}')
            if item.report_text_path:
                details.append(f"报告：{html.escape(item.report_text_path)}")
            if item.error:
                details.append(f"原因：{html.escape(item.error)}")
            detail_html = "<br>".join(details) or "没有额外输出信息"
            rows.append(
                f'<div style="background:{background}; border-left:4px solid {status_color}; '
                f'margin:4px 0 10px 0; padding:9px 11px; border-radius:7px;">'
                f'<span style="color:{status_color}; font-weight:800;">{html.escape(status_text)}</span>'
                f'<span style="font-weight:700; color:{completion_theme.text};">&nbsp;&nbsp;{html.escape(Path(item.media_path).name)}</span>'
                f'<div style="color:{completion_theme.text_muted}; margin-top:5px; line-height:1.55;">{detail_html}</div>'
                "</div>"
            )
        self.result_files.setHtml("".join(rows))
        if hasattr(self, "result_task_selector"):
            from .studio_project import load_project
            self._completion_tasks = []
            self.result_task_selector.blockSignals(True)
            self.result_task_selector.clear()
            for item in result.results:
                project = None
                if item.project_path and Path(item.project_path).is_file():
                    try:
                        project = load_project(item.project_path)
                    except (OSError, ValueError, TypeError):
                        pass
                self._completion_tasks.append((item, project))
                self.result_task_selector.addItem(Path(item.media_path).name)
            self.result_task_selector.blockSignals(False)
            self._select_completion_task(0)
            self.open_subtitle_result_button.setVisible(False)
        set_log_html_keep_left(self.result_console, self.console_log.toHtml())
        apply_ui_language(self, getattr(self,"_ui_language","zh"))
        # Completion can also be exercised by guard-level tests that build a
        # deliberately minimal MainWindow shell without the full page stack.
        if hasattr(self, "history_page"):
            self.history_page.refresh()
        studio_context = getattr(self, "_studio_recognition_context", None)
        if not studio_context:
            self._switch_page(2)
        if hasattr(self, "result_details_toggle"):
            self.result_details_toggle.setChecked(bool(failure_count or cancel_count or polish_details))
        self._last_failed_items = [
            item for item in result.results if item.status == "failed" or item.media_path in retry_partial_paths
        ]
        (bind_text(self.retry_failed_button, '重试未完成校对') if retry_partial_paths else bind_text(self.retry_failed_button, '重试失败项'))
        self.retry_failed_button.setVisible(bool(self._last_failed_items))
        if hasattr(self, "open_studio_result_button"):
            self.open_studio_result_button.setVisible(bool(self._last_studio_project))
        if hasattr(self, "open_priority_review_button"):
            self.open_priority_review_button.setVisible(bool(self._last_studio_project and review_total))
        if not studio_context:
            self._show_task_notification(*_completion_notification_spec(result))
        elif failure_count or cancel_count:
            self.studio_page.fail_recognition_runtime(
                "任务已取消" if cancel_count and not failure_count else "识别失败，请检查模型与运行日志"
            )
            # 四十二轮：识别转后台后用户可能已离开 Studio 页——失败/取消也要
            # 任务通知，否则只剩藏在字幕列表里的芯片，用户无感知。
            self._show_task_notification(*_completion_notification_spec(result))
        if studio_context and result.successes:
            target = str(next((item.project_path for item in result.successes
                if os.path.normcase(os.path.abspath(item.media_path)) == os.path.normcase(os.path.abspath(studio_context.get('media_path','')))),''))
            if target and any(
                os.path.normcase(os.path.abspath(item.media_path))
                == os.path.normcase(os.path.abspath(studio_context.get("media_path", "")))
                for item in result.successes
            ):
                QTimer.singleShot(0, lambda path=target: self._finish_studio_recognition(path))
            elif not target:
                self.studio_page.fail_recognition_runtime('字幕输出已保存，工程交付未完成；请在结果页点击“恢复已有识别结果”')
                self._switch_page(2)

    def _handle_unexpected_error(self, message: str):
        self._release_run_state()
        self._progress_timer.stop()
        self.result_icon.setPixmap(_icon("fa5s.exclamation-circle", CORAL).pixmap(QSize(72, 72)))
        bind_text(self.result_title, '任务未能启动')
        self.result_title.setProperty("i18nText","任务未能启动")
        self.result_summary.setProperty("i18nTemplate",None)
        self.result_summary.setText(message)
        error_theme = _active_theme_definition()
        self.result_files.setHtml(
            f'<div style="background:{error_theme.danger_soft}; border-left:4px solid {error_theme.danger}; '
            f'padding:10px; border-radius:7px;"><b>启动失败</b><br>{html.escape(message)}</div>'
        )
        set_log_html_keep_left(self.result_console, self.console_log.toHtml())
        if getattr(self, "_studio_recognition_context", None):
            self.studio_page.fail_recognition_runtime(message)
            return
        self._switch_page(2)
        if hasattr(self, "result_details_toggle"):
            self.result_details_toggle.setChecked(True)
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
        studio = getattr(self, "studio_page", None)
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
                geometry = self.geometry()
                if geometry.width() >= 200 and geometry.height() >= 200:
                    settings.setValue(
                        "mainWindow/geometry",
                        [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    )
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

    return retheme_qss(TERM_LIBRARY_PAGE_QSS, theme or _active_theme_definition())


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

        sidebar = QFrame()
        sidebar.setObjectName("termWorkspaceSidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(260)
        sidebar.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(6)
        heading = QLabel("工作台")
        heading.setObjectName("termWorkspaceLabel")
        side.addWidget(heading)
        self.workspace_navigation = WorkspaceNavigation("terms")
        self.workspace_navigation.recognition_requested.connect(self.recognition_requested)
        self.workspace_navigation.workshop_requested.connect(self.workshop_requested)
        self.workspace_navigation.history_requested.connect(self.history_requested)
        side.addWidget(self.workspace_navigation)
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

    motion_preference = read_studio_preferences().get("reduce_motion")
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
    # 四十八轮（agy EXE 评审发现）：argv 里的 .2byteproj 工程此前被
    # _supported_paths（只认媒体后缀）丢弃 → 传工程启动回退识别首页。
    # 工程参数直接进 Studio 编辑态（与"最近工程卡片"同一条 open_studio_project 链）。
    startup_project_path = ""
    for raw_path in initial_paths or ():
        candidate = Path(str(raw_path)).expanduser()
        if candidate.is_file() and candidate.suffix.lower() in {".2byteasrproj", ".2byteproj"}:
            startup_project_path = str(candidate.resolve())
            break
    if select_media and not initial_paths and not startup_project_path:
        media_paths = _select_media_paths()
        if not media_paths:
            instance_guard.release()
            return 0
    _startup_mark("SETTINGS_LOADED")
    window = MainWindow([], legacy, pipeline, startup_self_test)
    from .desktop_intake import DesktopIntake
    window._desktop_intake = DesktopIntake(window)
    instance_guard.paths_received.connect(window._desktop_intake.receive_external)
    QTimer.singleShot(0, instance_guard.enable_receiver)
    if media_paths or (initial_paths and not startup_project_path):
        QTimer.singleShot(0, lambda: window.import_media(media_paths or initial_paths))
    if startup_project_path:
        # 首帧后再开工程：窗口刚 show 时 splitter 尺寸未定，立即打开会把
        # 时间线宿主压扁（EXE 实测 39px）。等布局稳定后走同一条编辑链。
        QTimer.singleShot(
            800,
            lambda: window.open_studio_project(startup_project_path, mode="edit", source="argv"),
        )
    _startup_mark("MAIN_WINDOW_CREATED")

    class _FirstPaintProbe(QObject):
        def eventFilter(self, watched, event):
            if watched is window and event.type() == QEvent.Type.Paint:
                _startup_mark("FIRST_PAINT")
                QTimer.singleShot(0, lambda: _startup_mark("INTERACTIVE"))
                if os.environ.get("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE") == "1":
                    QTimer.singleShot(2500, app.quit)
                window.removeEventFilter(self)
            return False

    paint_probe = _FirstPaintProbe(window)
    window._startup_paint_probe = paint_probe
    window.installEventFilter(paint_probe)
    window.show()
    _startup_mark("FIRST_SHOW")
    _run_first_run_wizard(window)
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

        QTimer.singleShot(250, _open_studio_for_audit)
    if os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR'):
        from .studio_acceptance_audit import start_acceptance
        QTimer.singleShot(1500, lambda: start_acceptance(window))
    try:
        app.exec()
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
    try:
        dialog = GuidedSetupDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        primary, timeline, review = dialog.selected_backends()
        download_keys = dialog.selected_download_keys()
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
        if dialog.open_workshop:
            def open_selected_combination():
                parent._open_model_workshop()
                parent.workshop_page.focus_primary_backend(primary)
                if dialog.auto_download and download_keys:
                    parent.workshop_page.download_combination(
                        download_keys,
                        "首次选择的字幕识别组合",
                        auto_start=True,
                    )

            QTimer.singleShot(0, open_selected_combination)
    except Exception:
        # A broken wizard must not strand a first-run user silently.
        traceback.print_exc()
        _startup_mark("FIRST_RUN_WIZARD_FAILED", traceback=traceback.format_exc())


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
        window.phase_cards[1]._paint_active(QColor("#ffe7b9"))
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
            window.workshop_page._view_model("qwen_api")
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
