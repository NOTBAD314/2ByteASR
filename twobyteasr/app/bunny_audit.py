"""What 兔白 did, kept across sessions and replayable (2026-11-17, harness P4).

Agent harnesses keep an append-only log of every tool call (hooks / audit log / replay): here every
call that moves, changes or spends (``Tool.acts`` / ``edit`` / ``paid``) is one JSON line in the
user's own data folder — when, the question it answered, the tool, its arguments, what came of it.
She reads it back with ``recent_actions`` ("what did you change last time?") and ``replay_action``
hands her an old call to do again (it then goes through 「兔白权限」 like any other call).

Only on this computer, only while 「让兔白记住我的习惯」 is on; secrets are never written; the file
keeps the newest ``KEEP`` lines.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

KEEP = 600
current_question = ''        # set by the chat as each question starts, so a line says what it answered
ARG_LIMIT = 120
SECRET = re.compile(r'key|token|密钥|密码|password|secret', re.I)


def log_path() -> Path:
    from ..runtime_paths import user_data_root
    return Path(user_data_root()) / 'bunny' / 'actions.jsonl'


def _allowed() -> bool:
    try:
        from . import bunny_permissions
        return bool(bunny_permissions.load().get('remember', True))
    except Exception:  # noqa: BLE001 - unreadable permissions: keep nothing
        return False


def _clean(args) -> dict:
    out = {}
    for key, value in (args or {}).items():
        if SECRET.search(str(key)):
            out[key] = '***'
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            out[key] = text if len(text) <= ARG_LIMIT else text[:ARG_LIMIT - 1] + '…'
    return out


def outcome_of(receipt: str) -> str:
    text = str(receipt or '')
    if '还没做' in text:
        return 'pending'
    return 'ok' if '：成功' in text else 'failed'


def record(name: str, args: dict, receipt: str, *, question: str = '') -> None:
    """One line for a call that moved, changed or spent something. Never raises."""
    if not _allowed():
        return
    sensitive = [str(value) for key, value in (args or {}).items() if SECRET.search(str(key)) and value]
    def redact(text):
        for value in sorted(sensitive, key=len, reverse=True):
            text = text.replace(value, '***')
        return ' '.join(text.split())
    row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'question': redact(str(question or current_question or ''))[:80],
           'tool': name, 'args': _clean(args), 'outcome': outcome_of(receipt),
           'receipt': redact(str(receipt or ''))[:160]}
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        if path.stat().st_size > KEEP * 600:
            lines = path.read_text('utf-8').splitlines()[-KEEP:]
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError:
        pass


def read(limit: int = 20) -> list[dict]:
    try:
        lines = log_path().read_text('utf-8').splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-max(1, limit):]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def clear() -> None:
    try:
        log_path().unlink()
    except OSError:
        pass


WORDS = {'ok': '做成了', 'failed': '没做成', 'pending': '等「帮我做」'}


def _recent(_window, args) -> str:
    from .bunny_tools import ToolError, call_text
    if not _allowed():
        raise ToolError('小兔纸在「兔白权限」里关掉了“让兔白记住我的习惯”，兔白不留操作记录')
    try:
        count = max(1, min(40, int(args.get('count') or 12)))
    except (TypeError, ValueError):
        count = 12
    rows = read(count)
    if not rows:
        return '还没有操作记录（兔白还没在这台电脑上动过手）'
    total = len(read(KEEP))
    first = total - len(rows) + 1
    lines = [f'#{first + index} {row.get("at", "")[5:16]} 「{row.get("question", "")[:24]}」 '
             f'{call_text(row.get("tool", ""), row.get("args") or {})} → {WORDS.get(row.get("outcome"), "?")}'
             for index, row in enumerate(rows)]
    return '兔白最近的操作（旧的在上，replay_action 用 # 后面的编号）：\n' + '\n'.join(lines)


def _replay(_window, args) -> str:
    from .bunny_tools import TOOLS, ToolError, call_text
    if not _allowed():
        raise ToolError('小兔纸关掉了“让兔白记住我的习惯”，不能读取旧操作记录')
    rows = read(KEEP)
    try:
        number = int(str(args.get('id')).lstrip('#'))
    except (TypeError, ValueError):
        raise ToolError('id 要填 recent_actions 里 # 后面的编号') from None
    if not 1 <= number <= len(rows):
        raise ToolError(f'没有 #{number} 这条记录')
    row = rows[number - 1]
    name, call_args = row.get('tool', ''), dict(row.get('args') or {})
    if name not in TOOLS:
        raise ToolError(f'#{number} 用的工具现在没有了')
    if any(value == '***' or (isinstance(value, str) and value.endswith('…')) for value in call_args.values()):
        raise ToolError(f'#{number} 的参数没有完整记下来（太长或是隐私），没法原样重做')
    if call_args.get('ref'):
        raise ToolError(f'#{number} 是按快照编号（{call_args["ref"]}）点的，编号已经过期；先 ui_snapshot 再按名字或新编号做')
    return (f'#{number} 是 {call_text(name, call_args)}（当时：{WORDS.get(row.get("outcome"), "?")}）。'
            f'要重做就在下一轮的 tools 里原样填 {json.dumps({"name": name, "args": call_args}, ensure_ascii=False)}，'
            '照常按「兔白权限」走')


def tools():
    from .bunny_tools import Tool
    return (
        Tool('recent_actions', '{"count": 12}', '兔白在这台电脑上最近动过手的操作（跨聊天保存）：时间、当时的问题、做了什么、成没成', _recent),
        Tool('replay_action', '{"id": 7}', '把 recent_actions 里的一条操作拿出来，准备原样再做一次（下一轮照它填 tools）', _replay),
    )


__all__ = ['clear', 'log_path', 'read', 'record', 'tools']
