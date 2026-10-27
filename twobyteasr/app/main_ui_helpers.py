"""Constants and small non-widget helpers (paths, icons, theme tokens) for the main desktop shell."""

from __future__ import annotations

import os
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog

from twobyteasr.runtime_paths import detect_install_root

from ..design.themed_icons import themed_icon
from ..design.ui_theme import theme_definition

APP_ROOT = detect_install_root()
APP_ICON_SOURCE_PATH = APP_ROOT / "assets" / "2byteasr-icon-transparent.png"
APP_ICON_FALLBACK_PATH = APP_ROOT / "assets" / "2byteasr-icon.jpg"
APP_ICON_PATH = APP_ROOT / "assets" / "app_icon.ico"  # Dedicated Taskbar/app icon (face-zoomed)
LAST_MEDIA_DIRECTORY_KEY = "paths/last_media_directory"
from ..media.media_intake import SUPPORTED_MEDIA_SUFFIXES
GUI_PROFILE_ENABLED = os.environ.get("TWOBYTEASR_GUI_PROFILE") == "1"

# 云端模型“配置类失败”特征：与本地模型损坏（模型工坊修复路径）不同，
# 这类失败重试前必须先到「AI 模型与密钥」补配置，否则只会原样再失败。
AI_CONFIG_FAILURE_MARKERS = (
    "缺少 API 密钥",
    "缺少模型名称",
    "API 地址无效",
    "尚未登录",
    "请展开 AI 模型与密钥",
    "完成登录",
    "账号登陆传输",
)


def _is_ai_config_failure(error_text) -> bool:
    text = str(error_text or "")
    return any(marker in text for marker in AI_CONFIG_FAILURE_MARKERS)


def polishing_completion_details(report):
    """Adapt the shared outcome to the established completion details API."""
    from ..recognition.recognition_outcome import normalize_recognition_outcome

    outcome = normalize_recognition_outcome(report)
    from ..i18n import current_language, translate

    language = current_language()
    lines = list(outcome.localized_detail_lines(language))
    polish = report.get('polishing_summary') or {}
    if polish:
        lines.insert(0, translate("AI文字校对：{success_batches} 批 / {success_records} 条处理记录完成；原文回退 {fallback_batches} 批 / {fallback_records} 条处理记录", language).format(
            success_batches=polish.get('success_batches', 0), success_records=outcome.success_records,
            fallback_batches=polish.get('fallback_batches', 0), fallback_records=outcome.fallback_records))
    if outcome.polish_retryable:
        categories = polish.get('failure_categories') or {}
        names = {'request_too_large': '请求超过模型预算', 'transport_length': '启动参数超限',
                 'timeout': '超时', 'rate_limited': '限流', 'authentication_required': '需要登录',
                 'permission_denied': '权限拒绝', 'request_error': '请求失败',
                 'structured_output_truncated': '输出不完整', 'parse_failure': '输出解析失败',
                 'structured_json_parse_error': '输出解析失败', 'structured_schema_error': '输出字段不符合约定',
                 'coverage_mismatch': '字幕检查回执不完整', 'semantic_validation': '字幕编号或内容不符合约定'}
        if categories:
            reasons = '、'.join(translate('{reason} {count} 条处理记录', language).format(reason=translate(names.get(key, key), language), count=count) for key, count in categories.items())
            lines.append(translate('文字校对失败原因：{reasons}', language).format(reasons=reasons))
    evidence = completion_stage_evidence(report)
    retry = bool(evidence['retry_stages'])
    if retry:
        stages = ' / '.join(translate({'polish': 'AI文字校对', 'terminology': '联网核验'}[stage], language)
                            for stage in evidence['retry_stages'])
        lines.append(translate('可重试未完成的{stages}；复用已有识别和成功文字校对缓存。', language).format(stages=stages))
    return lines, retry


def completion_stage_evidence(report):
    """Keep text retries separate from absent optional search capability."""
    from ..recognition.recognition_outcome import normalize_recognition_outcome

    outcome = normalize_recognition_outcome(report)
    polish = report.get('polishing_summary') or {}
    terms = report.get('terminology_summary') or report.get('terminology_status') or polish.get('terminology') or {}
    stages = []
    if outcome.polish_retryable:
        stages.append('polish')
    if outcome.search_retryable:
        stages.append('terminology')
    return dict(retry_stages=tuple(stages), polishing=polish, terminology=terms,
                polish_incomplete=outcome.polish_status == 'partial',
                verification_incomplete=outcome.search_status in {'not_configured', 'unsupported', 'not_run', 'partial', 'failed', 'timeout', 'insufficient_evidence'},
                search_unsupported=outcome.search_status in {'not_configured', 'unsupported'},
                outcome=outcome)


def _merge_media_paths(existing, incoming):
    """Append incoming media paths, de-duplicated by normalized absolute path."""
    merged = []
    seen = set()
    for item in (*existing, *incoming):
        key = os.path.normcase(os.path.abspath(item))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged



def _media_dialog_initial_directory(settings=None):
    settings = settings or QSettings("2ByteASR", "2ByteASR")
    remembered = str(settings.value(LAST_MEDIA_DIRECTORY_KEY, "") or "").strip()
    if remembered and Path(remembered).is_dir():
        return str(Path(remembered).resolve())
    desktop = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DesktopLocation
    )
    if desktop and Path(desktop).is_dir():
        return str(Path(desktop).resolve())
    fallback = Path.home() / "Desktop"
    return str(fallback if fallback.is_dir() else Path.home())


def _remember_media_directory(paths, settings=None):
    if not paths:
        return
    directory = Path(paths[0]).expanduser().resolve().parent
    if not directory.is_dir():
        return
    settings = settings or QSettings("2ByteASR", "2ByteASR")
    settings.setValue(LAST_MEDIA_DIRECTORY_KEY, str(directory))
    settings.sync()


def _select_media_paths(parent=None, settings=None):
    settings = settings or QSettings("2ByteASR", "2ByteASR")
    paths, _ = QFileDialog.getOpenFileNames(
        parent,
        "请选择一个或多个原视频 / 音频文件",
        _media_dialog_initial_directory(settings),
        "视频 / 音频 (" + " ".join("*" + ext for ext in sorted(SUPPORTED_MEDIA_SUFFIXES)) + ")",
    )
    _remember_media_directory(paths, settings)
    return list(paths)


def _icon(name: str, color: str | None = None) -> QIcon:
    # No explicit color means "follow the active theme's primary icon color".
    if color is None:
        return themed_icon(name, "primary")
    return qta.icon(name, color=color)


def _active_theme_definition():
    """Theme tokens for locally-styled runtime widgets (never warm literals)."""
    from twobyteasr.design.theme_manager import theme_key

    return theme_definition(theme_key())
