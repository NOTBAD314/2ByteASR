"""兔白's memory of this user, and the user's own knowledge base for her (2026-11-15).

User (2026-11-15): a memory and knowledge base of the user's own, so 兔白 fits their habits and
ways of working. Two kinds of entries, both short plain text:

* ``memory``    — what she noticed and wrote down herself (``remember`` tool): habits, preferences,
  what they make ("做原神实况，常用黄色描边", "想被叫小兔纸以外的名字…");
* ``knowledge`` — what the user teaches her in 「设置」→「兔白权限」 (rules of their channel, names,
  their own way of doing things).

Both go into her system prompt (after the fixed part, so the cached prefix stays the same) and
therefore to the user's text AI, which the settings page says. Never keys, passwords or numbers
that look like them (``looks_secret``). Kept in the user data folder; no Qt.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

LIMITS = {'memory': (60, 160), 'knowledge': (30, 600), 'recipe': (20, 20)}     # (entries, characters each)
KINDS = tuple(LIMITS)
_SECRET = re.compile(r'(sk-[A-Za-z0-9]{8,}|api[_ -]?key|密码|password|token|secret|\b\d{12,}\b|[A-Za-z0-9+/]{32,})',
                     re.IGNORECASE)


def store_path() -> Path:
    from ..runtime_paths import user_data_root
    return Path(user_data_root()) / 'bunny' / 'memory.json'


def looks_secret(text: str) -> bool:
    return bool(_SECRET.search(str(text or '')))


def load() -> list[dict]:
    try:
        data = json.loads(store_path().read_text('utf-8'))
    except (OSError, ValueError):
        return []
    rows = data.get('entries') if isinstance(data, dict) else None
    return [row for row in rows or [] if isinstance(row, dict) and row.get('kind') in KINDS and row.get('text')]


def _write(rows: list[dict]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'version': 1, 'entries': rows}, ensure_ascii=False, indent=1), 'utf-8')
    temp.replace(path)


def add(text: str, kind: str = 'memory', source: str = 'bunny', data: dict | None = None) -> dict:
    """A new entry; raises ValueError with a reason she or the page can say."""
    if kind not in KINDS:
        raise ValueError('kind 只能是 memory、knowledge 或 recipe')
    count, limit = LIMITS[kind]
    text = ' '.join(str(text or '').split()) if kind == 'memory' else str(text or '').strip()
    if not text:
        raise ValueError('没有要记的内容')
    if looks_secret(text):
        raise ValueError('看起来像密钥、密码或账号号码，兔白不记这种东西')
    text = text[:limit]
    rows = load()
    if kind == 'recipe':                        # a recipe of the same name is updated
        rows = [row for row in rows if not (row['kind'] == 'recipe' and row['text'] == text)]
    elif any(row['kind'] == kind and row['text'] == text for row in rows):
        raise ValueError('这条已经记着了')
    same = [row for row in rows if row['kind'] == kind]
    if len(same) >= count:
        oldest = same[0]                        # full: the oldest of this kind makes room
        rows = [row for row in rows if row is not oldest]
    entry = {'id': max([row.get('id', 0) for row in rows] + [0]) + 1, 'kind': kind, 'text': text,
             'source': source, 'created': time.strftime('%Y-%m-%d')}
    if data:
        entry['data'] = data
    rows.append(entry)
    _write(rows)
    return entry


def remove(entry_id) -> dict | None:
    rows = load()
    try:
        wanted = int(entry_id)
    except (TypeError, ValueError):
        return None
    gone = next((row for row in rows if row.get('id') == wanted), None)
    if gone is not None:
        _write([row for row in rows if row is not gone])
    return gone


def clear(kind: str | None = None) -> None:
    _write([row for row in load() if kind is not None and row['kind'] != kind])


def prompt_block(rows: list[dict] | None = None) -> str:
    """What she knows about this user, for the end of her system prompt ('' when nothing)."""
    rows = load() if rows is None else rows
    memory = [row for row in rows if row['kind'] == 'memory']
    knowledge = [row for row in rows if row['kind'] == 'knowledge']
    recipes = [row for row in rows if row['kind'] == 'recipe']
    parts = []
    if memory:
        parts.append('# 兔白记住的小兔纸（自己记下的习惯和喜好，编号用来 forget）\n'
                     + '\n'.join(f'- [{row["id"]}] {row["text"]}' for row in memory))
    if knowledge:
        parts.append('# 小兔纸的知识库（小兔纸亲自写给兔白的资料，优先照这个来）\n'
                     + '\n'.join(f'- [{row["id"]}] {row["text"]}' for row in knowledge))
    if recipes:
        parts.append('# 小兔纸的配方（use_recipe 填名字套用）\n' + '\n'.join(
            f'- {row["text"]}：' + '、'.join(_recipe_parts(row.get("data") or {})) for row in recipes))
    return '\n\n'.join(parts)


def _recipe_parts(data: dict) -> list:
    parts = []
    if data.get('style'):
        parts.append('样式')
    if data.get('break_rule'):
        parts.append(f'断句偏好「{str(data["break_rule"])[:24]}」')
    if data.get('speakers'):
        parts.append('说话人 ' + '、'.join(data['speakers'][:4]))
    return parts or ['（空）']


# ------------------------------------------------------------------ chats kept per project (2026-11-16)
CHAT_LIMIT = 60
CHAT_EPOCH = 0  # Invalidate live chats after the user clears saved history.


def _chat_path(key: str) -> Path:
    import hashlib
    return store_path().parent / 'chats' / (hashlib.sha1(str(key).encode('utf-8')).hexdigest()[:16] + '.json')


def load_chat(key: str) -> list:
    if not key:
        return []
    try:
        rows = json.loads(_chat_path(key).read_text('utf-8')).get('items')
    except (OSError, ValueError, AttributeError):
        return []
    if not isinstance(rows, list):
        return []
    return [(row[0], row[1]) for row in rows if isinstance(row, (list, tuple)) and len(row) == 2
            and row[0] in ('user', 'bunny') and isinstance(row[1], str) and row[1]][-CHAT_LIMIT:]


def save_chat(key: str, items) -> None:
    if not key:
        return
    path = _chat_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[who, text] for who, text in list(items)[-CHAT_LIMIT:] if not looks_secret(text)]
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'version': 1, 'items': rows}, ensure_ascii=False), 'utf-8')
    temp.replace(path)


def clear_chat(key: str) -> None:
    """One project's saved chat (「新对话」, 2026-11-16); memory, knowledge and recipes stay."""
    if not key:
        return
    try:
        _chat_path(key).unlink()
    except FileNotFoundError:
        pass


def clear_chats() -> None:
    global CHAT_EPOCH
    CHAT_EPOCH += 1
    folder = store_path().parent / 'chats'
    for path in folder.glob('*.json') if folder.is_dir() else ():
        try:
            path.unlink()
        except OSError:
            pass


__all__ = ['CHAT_LIMIT', 'KINDS', 'LIMITS', 'add', 'clear', 'clear_chat', 'clear_chats', 'load', 'load_chat', 'looks_secret', 'prompt_block',
           'remove', 'save_chat', 'store_path']
