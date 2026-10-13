"""复制诊断信息: a problem report the user reads before copying; never uploaded (2026-10-13).

Contents: version and build, system, which recognition plan and providers are
set (ids, models, host names only), upload mode and punctuation defaults, what
this computer offers (NVIDIA tool, runtimes), MCP on/off and the newest
recognition report's summary line. Removed before display: API keys, tokens,
AccessKeys, signed-URL parameters and every query string, e-mail addresses,
and the user's home folder (shown as ~). The user can edit the text before
copying; nothing leaves the computer unless they paste it somewhere.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_QUERY = re.compile(r'(https?://[^\s?#]+)\?[^\s#]*')


def _host(url: str) -> str:
    try:
        return urlsplit(str(url or '')).hostname or ''
    except ValueError:
        return ''


def scrub(text: str) -> str:
    """Remove secrets and personal paths from free text."""
    from .provider_diagnostics import redact_diagnostics
    text = redact_diagnostics(str(text or ''))
    text = _QUERY.sub(r'\1?[已去除参数]', text)
    home = str(Path.home())
    for variant in {home, home.replace('\\', '/'), home.lower(), home.replace('\\', '/').lower()}:
        if variant:
            text = re.sub(re.escape(variant), '~', text, flags=re.IGNORECASE)
    user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
    if len(user) >= 3:
        text = re.sub(rf'(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])', '<用户名>', text)
    return text


def collect(window=None) -> str:
    lines = ['兔白字幕诊断信息（复制前请看一遍；不含密钥、令牌与签名参数）', '']
    try:
        from .build_identity import load_build_identity
        build = load_build_identity()
        lines.append(f'版本：{build.app_version}')
        lines.append(f'构建：{build.build_channel} · {build.build_time} · 源码 {str(build.source_sha256)[:12]}…')
    except Exception as exc:
        lines.append(f'版本：读取失败（{type(exc).__name__}）')
    lines.append(f'系统：{platform.system()} {platform.release()} {platform.machine()}；Python {sys.version.split()[0]}；'
                 f'{"安装版" if getattr(sys, "frozen", False) else "源码版"}')
    settings = {}
    try:
        settings = getattr(getattr(window, 'legacy', None), 'RUNTIME_SETTINGS', None) or {}
        if not settings:
            from .settings import load_runtime_settings
            settings = load_runtime_settings()[0]
    except Exception:
        settings = {}
    models = dict((settings or {}).get('models') or {})
    switches = dict((settings or {}).get('switches') or {})
    lines.append('')
    lines.append('识别方案：主力 {p} · 时间轴 {t} · 文字复核 {r}'.format(
        p=models.get('primary_asr_backend', '?'), t=models.get('firered_asr_backend', '?'),
        r=models.get('qwen_asr_backend', '?')))
    lines.append('云端识别：{provider} · {model} · {host}'.format(
        provider=models.get('qwen_asr_api_provider', ''), model=models.get('qwen_asr_api_model', ''),
        host=_host(models.get('qwen_asr_api_url', ''))))
    try:
        from .api_setup_catalog import resolve_upload_mode, upload_mode_label
        lines.append(f'录音文件识别音频交接：{upload_mode_label(resolve_upload_mode(models))}')
    except Exception:
        pass
    try:
        from .recognition_choices import cloud_asr_readiness
        ready, reason = cloud_asr_readiness(models)
        lines.append('云端识别可用：' + ('是' if ready else f'否（{reason}）'))
    except Exception:
        pass
    lines.append('文字 AI：校对 {pp} · {pm} @ {ph}；断句 {gp} · {gm} @ {gh}'.format(
        pp=models.get('polish_provider', ''), pm=models.get('polish_model', ''), ph=_host(models.get('polish_base_url', '')),
        gp=models.get('group_provider', ''), gm=models.get('group_model', ''), gh=_host(models.get('group_base_url', ''))))
    lines.append(f'新任务字幕标点：{switches.get("subtitle_punctuation", "original")}；'
                 f'字幕语言：{(settings.get("subtitle_language") or {}).get("recognition_language", "auto")}')
    try:
        from .recognition_choices import host_profile
        host = host_profile()
        lines.append(f'本机：NVIDIA 工具 {"有" if host.nvidia_tool else "无"}；主运行环境 {"有" if host.main_runtime else "无"}；'
                     f'MLX {"有" if host.mlx_runtime else "无"}')
    except Exception:
        pass
    try:
        from . import mcp_common
        mcp = mcp_common.read_settings()
        lines.append(f'外部 AI（MCP）：{"开启" if mcp.get("enabled") else "关闭"}；范围 {mcp.get("scope")}')
    except Exception:
        pass
    try:
        from .reporting import REPORT_ROOT
        reports = sorted((p for p in REPORT_ROOT.glob('*/*.json') if p.is_file()), key=lambda p: p.stat().st_mtime)
        if reports:
            payload = json.loads(reports[-1].read_text(encoding='utf-8'))
            status = payload.get('status') or payload.get('outcome') or ''
            error = payload.get('error') or ''
            lines.append(f'最近一次识别：{status} {str(error)[:300]}'.strip())
    except Exception:
        pass
    return scrub('\n'.join(lines))


def open_diagnostics_dialog(window) -> None:
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
    from .i18n import bind_text, tr
    dialog = QDialog(window)
    dialog.setObjectName('diagnosticsDialog')
    bind_text(dialog, '复制诊断信息', property='windowTitle')
    dialog.resize(640, 480)
    layout = QVBoxLayout(dialog)
    note = QLabel(tr('已去掉密钥和用户名，可以先改再复制；兔白不会自动上传'))
    note.setWordWrap(True)
    layout.addWidget(note)
    text = QPlainTextEdit(dialog)
    text.setObjectName('diagnosticsText')
    text.setPlainText(collect(window))
    layout.addWidget(text, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
    copy = buttons.addButton(tr('复制到剪贴板'), QDialogButtonBox.ButtonRole.ActionRole)
    copy.clicked.connect(lambda: (QApplication.clipboard().setText(scrub(text.toPlainText())),
                                  bind_text(note, '已复制。粘贴到问题回报时，请再看一眼内容。')))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
