"""Constants and non-widget path helpers for the main desktop shell."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QFileDialog

from twobyteasr.runtime_paths import detect_install_root

APP_ROOT = detect_install_root()
APP_ICON_SOURCE_PATH = APP_ROOT / "assets" / "2byteasr-icon-transparent.png"
APP_ICON_FALLBACK_PATH = APP_ROOT / "assets" / "2byteasr-icon.jpg"
APP_ICON_PATH = APP_ROOT / "assets" / "app_icon.ico"  # Dedicated Taskbar/app icon (face-zoomed)
LAST_MEDIA_DIRECTORY_KEY = "paths/last_media_directory"
from .media_intake import SUPPORTED_MEDIA_SUFFIXES
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
    """Read persisted task evidence for the completion page and retry action."""
    polish=report.get('polishing_summary') or {}
    terms=report.get('terminology_summary') or report.get('terminology_status') or polish.get('terminology') or {}
    lines=[]
    if polish:
        lines.append(f"校对成功 {polish.get('success_batches',0)} 批 / {polish.get('success_cues',0)} 条；"
                     f"ASR 回退 {polish.get('fallback_batches',0)} 批 / {polish.get('fallback_cues',0)} 条")
        categories=polish.get('failure_categories') or {}
        names={'request_too_large':'单条请求超过模型预算','transport_length':'CLI 启动参数超限',
               'timeout':'超时','rate_limited':'限流','authentication_required':'需要登录',
               'permission_denied':'权限拒绝','request_error':'请求失败',
               'structured_output_truncated':'输出不完整','parse_failure':'输出解析失败'}
        if categories:
            lines.append('失败原因：'+'、'.join(f'{names.get(k,k)} {v} 条' for k,v in categories.items()))
    if terms:
        state=terms.get('status')
        label={'success':'已完成联网核验','partial':'联网核验部分完成','failed':'联网核验失败',
               'not_run':'未执行联网核验'}.get(state,'联网核验状态未知')
        if terms.get('cached'):
            label+='（复用已核验结果）'
        lines.append(f"{label}：已检查 {terms.get('verified_count',0)} 条，未核验 {terms.get('unverified_count',0)} 条")
    retry=bool(polish.get('fallback_cues')) or terms.get('status') in {'failed','partial'}
    if retry:
        lines.append('可重试未完成部分；复用已有识别和成功校对缓存。')
    return lines,retry


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
