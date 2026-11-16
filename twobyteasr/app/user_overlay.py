"""「我的改动」: the user's own changes to 2ByteASR, kept apart from the program (2026-11-16).

User (2026-11-16): 「让这软件变成用户能自己更改和改进 … 同时也要保留用户自己改动的东西，不要被更新覆盖掉了」.
The program folder is replaced by every daily and release update (and may be read-only); the
user data folder (``%LOCALAPPDATA%\\2ByteASR``) is not. So everything the user, or 兔白 for the
user, changes lives in ``user-overlay`` there:

* ``style``  a few QSS declarations for one control, named by its objectName
  (``#bunnyChatSend`` / ``QPushButton#startButton``, optionally ``:hover``);
* ``text``   one built-in interface sentence (its Chinese source key) shown in other words;
* ``note``   a standing instruction for 兔白 (added to her prompt);
* ``script`` a Python extension (``scripts/<id>.py``) with ``API_VERSION`` and ``setup(api)``;
  runs only while 「允许运行我的扩展脚本」 is on, and only when the user enabled that script.
  A script 兔白 writes is saved switched off: the user reads it before turning it on.

Settings are not copied here: they already live in the user data folder and survive updates.
Every change first keeps a snapshot of the whole layer (``history``), so any earlier state can be
brought back; nothing is ever dropped silently: an entry that no longer fits after an update is
marked with a ``status`` and shown to the user. Applying the layer is ``user_overlay_runtime``.
No Qt here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

FORMAT_VERSION = 1
API_VERSION = 1                     # what extension scripts are written against
KINDS = ('style', 'text', 'note', 'script')
KIND_LABELS = {'style': '界面样式', 'text': '界面文字', 'note': '给兔白的说明', 'script': '扩展脚本'}
BY_LABELS = {'user': '我自己', 'bunny': '兔白'}
STATUS_LABELS = {'': '', 'paused_update': '更新后暂停', 'failed': '加载出错，已停用',
                 'paused_crash': '上次启动时可能让程序崩溃，已暂停', 'paused_api': '脚本版本和程序不符，已暂停'}
MAX_ENTRIES = 200
LIMITS = {'style': 600, 'text': 200, 'note': 300, 'script': 60_000}
HISTORY_KEEP = 40
SELECTOR = re.compile(r'^(?:[A-Za-z][A-Za-z0-9_]*)?#[A-Za-z_][A-Za-z0-9_\-]*(?::[a-z\-]+)?$')
_DECLARATION = re.compile(r'^\s*[a-z\-]+\s*:\s*[^;{}]+;?\s*$')


class OverlayError(ValueError):
    """A change that cannot be kept; the message says why in plain words."""


# ------------------------------------------------------------------ where
def root() -> Path:
    from ..runtime_paths import user_data_root
    return Path(user_data_root()) / 'user-overlay'


def store_path() -> Path:
    return root() / 'overlay.json'


def scripts_dir() -> Path:
    return root() / 'scripts'


def history_dir() -> Path:
    return root() / 'history'


def script_path(entry: dict) -> Path:
    return scripts_dir() / Path(str(entry.get('target') or '')).name


# ------------------------------------------------------------------ read / write
def _empty() -> dict:
    return {'version': FORMAT_VERSION, 'revision': 0, 'scripts_allowed': False, 'last_app_version': '',
            'next_id': 1, 'entries': []}


def load() -> dict:
    """The whole layer; an unreadable file is kept aside (never overwritten) and an empty layer used."""
    path = store_path()
    try:
        data = json.loads(path.read_text('utf-8'))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError):
        _set_aside(path)
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
        _set_aside(path)
        return _empty()
    state = dict(_empty(), **{key: data[key] for key in _empty() if key in data})
    state['entries'] = [dict(entry) for entry in data['entries'] if isinstance(entry, dict) and entry.get('kind') in KINDS]
    return state


def _set_aside(path: Path) -> None:
    try:
        path.replace(path.with_name(f'overlay.unreadable-{time.strftime("%Y%m%d-%H%M%S")}.json'))
    except OSError:
        pass


def _write(state: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), 'utf-8')
    os.replace(temp, path)


def _snapshot(state: dict, reason: str) -> str:
    """Keep the layer as it is now (with the script files) before it changes; returns the snapshot id."""
    stamp = time.strftime('%Y%m%d-%H%M%S') + f'-r{state.get("revision", 0)}'
    folder = history_dir() / stamp
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = history_dir() / f'{stamp}-{suffix}'
    folder.mkdir(parents=True)
    (folder / 'overlay.json').write_text(json.dumps(state, ensure_ascii=False, indent=1), 'utf-8')
    (folder / 'reason.txt').write_text(reason, 'utf-8')
    if scripts_dir().is_dir():
        shutil.copytree(scripts_dir(), folder / 'scripts')
    for old in sorted(history_dir().iterdir(), key=_history_key)[:-HISTORY_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return folder.name


def _history_key(folder: Path) -> tuple:
    match = re.fullmatch(r'(\d{8}-\d{6})-r(\d+)(?:-(\d+))?', folder.name)
    return (match[1], int(match[2]), int(match[3] or 1)) if match else ('', -1, 0)


def _commit(state: dict, before: dict, reason: str) -> str:
    snapshot = _snapshot(before, reason)
    state['revision'] = int(before.get('revision', 0)) + 1
    _write(state)
    return snapshot


def revision() -> int:
    return int(load().get('revision', 0))


# ------------------------------------------------------------------ checking a change
def check(kind: str, target: str, value: str) -> tuple[str, str]:
    """(target, value) cleaned, or ``OverlayError`` saying why not."""
    if kind not in KINDS:
        raise OverlayError(f'不认识的改动种类：{kind}（只能是 {"、".join(KINDS)}）')
    target = str(target or '').strip()
    value = str(value or '').strip()
    if len(value) > LIMITS[kind]:
        raise OverlayError(f'太长了：{KIND_LABELS[kind]}最多 {LIMITS[kind]} 个字')
    if kind == 'style':
        if not SELECTOR.match(target):
            raise OverlayError('样式只能按控件名改，要写成 #控件名 或 类名#控件名（可以加 :hover 这类状态）')
        rules = [part for part in value.replace('\n', ' ').split(';') if part.strip()]
        if not rules or any(not _DECLARATION.match(part + ';') for part in rules):
            raise OverlayError('样式要写成「属性: 值;」，例如 font-size: 16px; color: #333333;')
        if 'url(' in value.casefold() or '@' in value or '/*' in value:
            raise OverlayError('样式里不能引用文件、@ 规则或注释')
        value = ' '.join(rule.strip() + ';' for rule in rules)
    elif kind == 'text':
        if not target:
            raise OverlayError('要说明改哪一句界面文字')
        if not value:
            raise OverlayError('新的文字不能是空的')
    elif kind == 'note':
        if not value:
            raise OverlayError('说明不能是空的')
        target = ''
    elif kind == 'script':
        if not value:
            raise OverlayError('要写一句话说明这个脚本做什么')
    return target, value


def check_script(code: str) -> str:
    """The code of an extension script, or ``OverlayError``: it must compile and declare the API."""
    code = str(code or '')
    if not code.strip():
        raise OverlayError('脚本是空的')
    if len(code) > LIMITS['script']:
        raise OverlayError(f'脚本太长了（最多 {LIMITS["script"]} 个字）')
    try:
        compile(code, '<user script>', 'exec')
    except SyntaxError as exc:
        raise OverlayError(f'脚本有语法错误：第 {exc.lineno} 行 {exc.msg}') from None
    if not re.search(rf'^API_VERSION\s*=\s*{API_VERSION}\s*$', code, re.M):
        raise OverlayError(f'脚本要写一行 API_VERSION = {API_VERSION}')
    if not re.search(r'^def setup\(', code, re.M):
        raise OverlayError('脚本要有 def setup(api): 作为入口')
    return code


# ------------------------------------------------------------------ changing the layer
def entries(kind: str | None = None, state: dict | None = None) -> list[dict]:
    state = state or load()
    return [dict(entry) for entry in state['entries'] if kind is None or entry['kind'] == kind]


def find(entry_id: str, state: dict | None = None) -> dict | None:
    return next((dict(entry) for entry in (state or load())['entries'] if entry.get('id') == str(entry_id)), None)


def add(kind: str, target: str, value: str, *, by: str = 'user', note: str = '', code: str | None = None,
        app_version: str = '', enabled: bool | None = None) -> tuple[dict, str]:
    """A new change; (the entry, the snapshot to go back to). A script 兔白 wrote starts switched off."""
    target, value = check(kind, target, value)
    before = load()
    if len(before['entries']) >= MAX_ENTRIES:
        raise OverlayError(f'改动已经有 {MAX_ENTRIES} 条了，先删掉一些不要的')
    state = json.loads(json.dumps(before))
    entry_id = f'u{state["next_id"]}'
    state['next_id'] = int(state['next_id']) + 1
    if kind == 'script':
        code = check_script(code)
        target = f'{entry_id}.py'
    duplicate = next((item for item in state['entries'] if kind in ('style', 'text') and item['kind'] == kind
                      and item['target'] == target and item.get('enabled')), None)
    on = (by != 'bunny') if kind == 'script' and enabled is None else (True if enabled is None else bool(enabled))
    entry = {'id': entry_id, 'kind': kind, 'target': target, 'value': value, 'enabled': on, 'by': by,
             'created': time.strftime('%Y-%m-%d %H:%M'), 'app_version': app_version, 'note': str(note or '')[:200],
             'status': '', 'detail': ''}
    if duplicate is not None:            # the newer change of the same thing wins; the older one stays, switched off
        duplicate['enabled'] = False
    state['entries'].append(entry)
    snapshot = _snapshot(before, f'加入 {entry_id}：{KIND_LABELS[kind]}')
    if kind == 'script':
        scripts_dir().mkdir(parents=True, exist_ok=True)
        script_path(entry).write_text(code, 'utf-8')
    state['revision'] = int(before.get('revision', 0)) + 1
    _write(state)
    return entry, snapshot


def update(entry_id: str, **fields) -> dict:
    """Change an entry's fields (enabled, value, status, detail, note); returns it."""
    before = load()
    state = json.loads(json.dumps(before))
    entry = next((item for item in state['entries'] if item.get('id') == str(entry_id)), None)
    if entry is None:
        raise OverlayError(f'没有编号 {entry_id} 的改动')
    if 'value' in fields:
        entry['target'], entry['value'] = check(entry['kind'], entry['target'], fields.pop('value'))
    for key in ('enabled', 'status', 'detail', 'note'):
        if key in fields:
            entry[key] = bool(fields[key]) if key == 'enabled' else str(fields[key] or '')
    if fields.get('enabled') and entry.get('status'):
        entry['status'] = entry['detail'] = ''        # switching it on again means "try again"
    _commit(state, before, f'修改 {entry_id}')
    return dict(entry)


def set_enabled(entry_id: str, on: bool) -> dict:
    fields = {'enabled': bool(on)}
    if on:
        fields.update(status='', detail='')
    return update(entry_id, **fields)


def set_code(entry_id: str, code: str) -> dict:
    entry = find(entry_id)
    if entry is None or entry['kind'] != 'script':
        raise OverlayError(f'没有编号 {entry_id} 的脚本')
    code = check_script(code)
    before = load()
    _snapshot(before, f'修改脚本 {entry_id}')
    script_path(entry).write_text(code, 'utf-8')
    state = json.loads(json.dumps(before))
    state['revision'] = int(before.get('revision', 0)) + 1
    _write(state)
    return entry


def remove(entry_id: str) -> dict:
    """Delete an entry (its script file too); the snapshot keeps both, so it can come back."""
    before = load()
    state = json.loads(json.dumps(before))
    entry = next((item for item in state['entries'] if item.get('id') == str(entry_id)), None)
    if entry is None:
        raise OverlayError(f'没有编号 {entry_id} 的改动')
    state['entries'].remove(entry)
    _commit(state, before, f'删除 {entry_id}')
    if entry['kind'] == 'script':
        script_path(entry).unlink(missing_ok=True)
    return entry


def set_scripts_allowed(on: bool) -> None:
    before = load()
    state = dict(before, scripts_allowed=bool(on))
    _commit(state, before, '打开扩展脚本' if on else '关闭扩展脚本')


def mark_seen_version(app_version: str) -> None:
    """Remember the program version the layer was last checked against (no snapshot: nothing user-made changed)."""
    state = load()
    if state.get('last_app_version') != app_version:
        state['last_app_version'] = str(app_version or '')
        _write(state)


def mark(entry_id: str, status: str, detail: str = '', *, disable: bool = False) -> None:
    """The program's own verdict on an entry (after an update or a failed script); no snapshot."""
    state = load()
    for entry in state['entries']:
        if entry.get('id') == str(entry_id):
            entry['status'], entry['detail'] = status, str(detail or '')[:300]
            if disable:
                entry['enabled'] = False
    _write(state)


# ------------------------------------------------------------------ going back
def snapshots() -> list[dict]:
    """Earlier states, newest first: id, when, why, how many entries."""
    rows = []
    folder = history_dir()
    for item in sorted(folder.iterdir(), key=_history_key, reverse=True) if folder.is_dir() else ():
        try:
            data = json.loads((item / 'overlay.json').read_text('utf-8'))
            reason = (item / 'reason.txt').read_text('utf-8') if (item / 'reason.txt').is_file() else ''
        except (OSError, ValueError):
            continue
        rows.append({'id': item.name, 'reason': reason, 'count': len(data.get('entries') or []),
                     'when': f'{item.name[:4]}-{item.name[4:6]}-{item.name[6:8]} {item.name[9:11]}:{item.name[11:13]}'})
    return rows


def restore(snapshot_id: str) -> dict:
    """Bring an earlier state back (the current one is kept as a snapshot first, so this is undoable too)."""
    folder = history_dir() / Path(str(snapshot_id)).name
    try:
        data = json.loads((folder / 'overlay.json').read_text('utf-8'))
    except (OSError, ValueError):
        raise OverlayError(f'找不到这一份记录：{snapshot_id}') from None
    # Keeping the current state can prune this oldest snapshot. Read all of
    # its scripts first so restoring the last retained state cannot lose code.
    script_files = {path.name: path.read_bytes() for path in (folder / 'scripts').glob('*.py')}
    before = load()
    _snapshot(before, f'回到 {snapshot_id} 之前')
    if scripts_dir().is_dir():
        shutil.rmtree(scripts_dir())
    if script_files:
        scripts_dir().mkdir(parents=True, exist_ok=True)
        for name, content in script_files.items():
            (scripts_dir() / name).write_bytes(content)
    state = dict(_empty(), **{key: data[key] for key in _empty() if key in data})
    state['revision'] = int(before.get('revision', 0)) + 1
    state['next_id'] = max(int(state.get('next_id', 1)), int(before.get('next_id', 1)))   # ids never repeat
    _write(state)
    return state


# ------------------------------------------------------------------ what is active
def active(kind: str, state: dict | None = None) -> list[dict]:
    """The switched-on entries of a kind that the program has not paused."""
    return [entry for entry in entries(kind, state) if entry.get('enabled') and not entry.get('status')]


def notes(state: dict | None = None) -> list[str]:
    return [entry['value'] for entry in active('note', state)]


def text_overrides(state: dict | None = None) -> dict[str, str]:
    return {entry['target']: entry['value'] for entry in active('text', state)}


def styles(state: dict | None = None) -> dict[str, list[tuple[str, str, str]]]:
    """objectName -> [(entry id, selector, declarations)] of the active style entries."""
    found: dict[str, list] = {}
    for entry in active('style', state):
        name = entry['target'].split('#', 1)[1].split(':', 1)[0]
        found.setdefault(name, []).append((entry['id'], entry['target'], entry['value']))
    return found


def describe(entry: dict) -> str:
    """One line for lists and for 兔白."""
    kind = entry['kind']
    if kind == 'style':
        what = f'{entry["target"]} {{ {entry["value"]} }}'
    elif kind == 'text':
        what = f'「{entry["target"]}」→「{entry["value"]}」'
    elif kind == 'script':
        what = f'{entry["target"]}：{entry["value"]}'
    else:
        what = entry['value']
    state = '开着' if entry.get('enabled') else '关着'
    status = STATUS_LABELS.get(entry.get('status') or '', entry.get('status') or '')
    return (f'[{entry["id"]}] {KIND_LABELS[kind]}（{BY_LABELS.get(entry.get("by"), entry.get("by"))}，{state}'
            + (f'，{status}' if status else '') + f'）{what}')


__all__ = ['API_VERSION', 'KINDS', 'KIND_LABELS', 'OverlayError', 'active', 'add', 'check', 'check_script',
           'describe', 'entries', 'find', 'load', 'mark', 'mark_seen_version', 'notes', 'remove', 'restore', 'revision',
           'root', 'script_path', 'set_code', 'set_enabled', 'set_scripts_allowed', 'snapshots', 'styles',
           'text_overrides', 'update']
