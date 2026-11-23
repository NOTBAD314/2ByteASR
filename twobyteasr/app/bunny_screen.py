"""What 2ByteASR's own windows are saying right now, handed to 兔白 with every question (2026-11-22).

User (2026-11-22): adding one knowledge entry per reported problem does not make her smarter. The
export that "would not export" had its reason on screen the whole time (the range line said the
range was empty), yet she only had the hand-picked state fields and kept thinking. Most problems
look like that: a dialog with an error, a line in red, a grey button with its reason in the
tooltip, a progress bar that stopped. So every question now carries a short, generic reading of
the screen, without a tool call and without a picture:

* the open dialogs and windows (titles) and the page in front;
* visible lines that read like a warning, an error, a reason or a status;
* buttons that are grey, with the reason their tooltip gives;
* progress bars with their value.

Never her own card, never password fields, never list/table rows (they can hold subtitle text),
and never a line that is one of the project's subtitles. Bounded by ``LIMIT`` characters.
No setting is read or changed.
"""
from __future__ import annotations

import re

LIMIT = 700
LINE_LIMIT = 90
MAX_LINES = 10
SIGNAL = re.compile(
    r'失败|错误|出错|异常|无法|不能|不可|不支持|必须|请先|请把|请修改|请重新|超出|不足|不够|没有|找不到|缺少|未设|未安装|'
    r'未完成|中断|已停止|卡住|超时|警告|注意|灰的|不可用|已过期|冲突|占用|进度|正在|等待|剩余|'
    r'失敗|錯誤|無法|不能|請先|超出|沒有|找不到|警告|進度|正在|等待|'
    r'fail|error|cannot|can\'t|unable|must|invalid|missing|not (?:found|available|supported|installed)|'
    r'warning|timed? ?out|stalled|in progress|waiting', re.I)


def _plain(text) -> str:
    text = re.sub(r'<[^>]+>', ' ', str(text or ''))           # rich-text labels
    return ' '.join(text.split())


_PATH = re.compile(r'(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/)[^\s「」"\'，。；]*')


def _no_paths(text: str) -> str:
    """A path on screen becomes its last part: 「…\\video.mp4」 (the state never carries paths)."""
    def last(match):
        parts = [part for part in re.split(r'[\\/]', match.group(0)) if part]
        return '…\\' + parts[-1] if parts else '…'
    return _PATH.sub(last, text)


def _short(text: str, limit: int = LINE_LIMIT) -> str:
    from ..recognition.recognition_history import redact_report_payload
    text = redact_report_payload(_no_paths(text))
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _inside_rows(widget) -> bool:
    from PySide6.QtWidgets import QAbstractItemView
    node = widget.parentWidget()
    while node is not None:
        if isinstance(node, QAbstractItemView):
            return True
        node = node.parentWidget()
    return False


def _shown(widget) -> bool:
    try:
        return widget.isVisible() and widget.width() > 0 and widget.height() > 0
    except RuntimeError:
        return False


def _subtitle_lines(window) -> set:
    try:
        page = window.built_page('studio')
        project = getattr(page, 'project', None)
        return {' '.join(str(cue.text or '').split()) for cue in getattr(project, 'cues', ()) if str(cue.text or '').strip()}
    except Exception:  # noqa: BLE001 - no project, no subtitles to hide
        return set()


def _title(top) -> str:
    title = _plain(top.windowTitle())
    return title or top.metaObject().className()


def read_screen(window) -> str:
    """One short block: windows in front, warning-like lines, grey buttons with reasons, progress."""
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QProgressBar
    from .bunny_ui_control import _own, _tops
    try:
        tops = _tops(window)
    except Exception:  # noqa: BLE001 - no Qt application, nothing on screen
        return ''
    hidden = _subtitle_lines(window)
    rows, seen = [], set()
    windows = [_short(_title(top)) for top in tops if top is not window]
    if windows:
        rows.append('开着的窗口：' + '、'.join(dict.fromkeys(windows)))

    def add(text):
        text = _short(text)
        if text and text not in seen and len(rows) < MAX_LINES:
            seen.add(text)
            rows.append(text)

    for top in tops:
        prefix = '' if top is window else f'[{_title(top)}] '
        for label in top.findChildren(QLabel):
            if not _shown(label) or not _own(label) or _inside_rows(label):
                continue
            text = _plain(label.text())
            if not 4 <= len(text) <= 200 or text in hidden or not SIGNAL.search(text):
                continue
            if any(line and line in text for line in hidden if len(line) >= 6):
                continue
            add(f'{prefix}写着：{text}')
        for button in top.findChildren(QAbstractButton):
            if not _shown(button) or button.isEnabled() or not _own(button):
                continue
            name, reason = _plain(button.text()), _plain(button.toolTip())
            if name and reason and reason != name:
                add(f'{prefix}「{name}」是灰的：{reason}')
        for bar in top.findChildren(QProgressBar):
            if not _shown(bar) or not _own(bar):
                continue
            if bar.maximum() > bar.minimum():
                share = round(100 * (bar.value() - bar.minimum()) / (bar.maximum() - bar.minimum()))
                add(f'{prefix}进度条 {share}%' + (f'（{_plain(bar.format())}）' if '%' not in bar.format() and bar.format() else ''))
            else:
                add(f'{prefix}进度条在转（没有百分比）')
        for edit in top.findChildren(QLineEdit):          # an input marked invalid says so in its tooltip
            if _shown(edit) and edit.echoMode() == QLineEdit.EchoMode.Normal and _own(edit):
                tip = _plain(edit.toolTip())
                if tip and SIGNAL.search(tip) and edit.property('invalid'):
                    add(f'{prefix}输入框提示：{tip}')
    text = '；'.join(rows)
    return text if len(text) <= LIMIT else text[:LIMIT - 1] + '…'


__all__ = ['LIMIT', 'read_screen']
