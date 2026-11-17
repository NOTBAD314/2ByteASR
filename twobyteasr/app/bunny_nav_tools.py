"""兔白 opens things herself: recognition results and projects (2026-11-17).

User (2026-11-17): asked to open a recognition result she could only jump to the project library;
she should handle whatever the software itself can do. These tools are what the buttons already
do — 「识别记录 → 打开识别结果」 and 「工程库 → 继续编辑」 — reached by number or name:

* ``recent_results`` / ``open_result``: the recognition records, newest first (same order as the
  ``history`` lookup), and opening one on the completion page (``_open_completion_from_history``);
* ``recent_projects`` / ``open_project``: the project library's recent projects and opening one in
  the workbench (``open_studio_project``; it asks about unsaved changes itself, so it runs after
  her answer).

Nothing here sends a path to the AI: names are file names only.
"""
from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

LIST_LIMIT = 10
SEARCH_LIMIT = 30        # how far back "the latest result" looks past failed records


def _short(text, limit: int = 40) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ------------------------------------------------------------------ recognition results
def result_records(limit: int = LIST_LIMIT, roots=None) -> list:
    """(path, record or None) of the newest recognition records, newest first."""
    from ..recognition.recognition_history import list_report_files, parse_recognition_report
    from .bunny_lookup import report_roots
    listing, _errors = list_report_files(report_roots() if roots is None else roots)
    rows = []
    for path, _stamp, *_rest in sorted(listing, key=lambda row: row[1], reverse=True)[:limit]:
        try:
            rows.append((path, parse_recognition_report(path)))
        except Exception:  # noqa: BLE001 - an unreadable report is listed, never quoted
            rows.append((path, None))
    return rows


def _project_of(record) -> str:
    payload = getattr(record, 'payload', None) or {}
    result = payload.get('result') if isinstance(payload.get('result'), dict) else {}
    outputs = result.get('outputs') if isinstance(result.get('outputs'), dict) else {}
    return str(outputs.get('project') or '')


def _openable(record) -> bool:
    project = _project_of(record)
    return bool(record is not None and project and Path(project).is_file()
                and getattr(getattr(record, 'outcome', None), 'result_usable', True))


def _recent_results(_window, _args) -> str:
    rows = result_records()
    if not rows:
        return '还没有任何识别记录'
    lines = []
    for number, (_path, record) in enumerate(rows, 1):
        if record is None:
            lines.append(f'{number}. （这条记录读不出来）')
            continue
        name = _short(PureWindowsPath(record.media_name).name)
        can = '能打开结果' if _openable(record) else '没有可打开的结果'
        lines.append(f'{number}. {record.completed_at or "时间未记录"} · {name} · {record.status_label or record.status}'
                     f' · 字幕 {record.cue_count} 条 · {can}')
    return '最近的识别（新的在上，open_result 用这里的编号）：' + '；'.join(lines)


def _pick(rows, args, name_of):
    from .bunny_tools import ToolError
    if not rows:
        raise ToolError('一条都没有')
    wanted = str(args.get('name') or '').strip().casefold()
    if wanted:
        hits = [row for row in rows if wanted in name_of(row).casefold()]
        if not hits:
            raise ToolError(f'没找到名字里有「{args.get("name")}」的')
        return hits[0], rows.index(hits[0]) + 1
    try:
        number = int(str(args.get('number', 1)).strip())
    except (TypeError, ValueError):
        raise ToolError('要给编号（数字，1 是最新的）或名字') from None
    if not 1 <= number <= len(rows):
        raise ToolError(f'没有第 {number} 个（最近一共 {len(rows)} 个）')
    return rows[number - 1], number


def _open_result(window, args) -> str:
    from .bunny_tools import ToolError
    if getattr(window, '_run_in_progress', False) or getattr(window, '_completion_retry_in_progress', False):
        raise ToolError('现在有识别正在跑，跑完才能打开别的识别结果')
    rows = result_records(SEARCH_LIMIT)          # same order as the listing; looks further back for one with a result
    newest = next(((index, row) for index, row in enumerate(rows, 1) if _openable(row[1])), None)
    if not str(args.get('number') or '').strip() and not str(args.get('name') or '').strip():
        # "the latest result": the newest record that has one (live run 2026-11-17: the newest had failed)
        if newest is None:
            raise ToolError('最近的识别里没有一次有能打开的结果（都失败或没保存工程）')
        number, (path, record) = newest
    else:
        (path, record), number = _pick(rows, args, lambda row: PureWindowsPath(row[1].media_name).name if row[1] else '')
    if record is None:
        raise ToolError(f'第 {number} 条记录读不出来，请在「识别记录」里看')
    if not _openable(record):
        hint = (f'；最新一次能打开的是第 {newest[0]} 条「{_short(PureWindowsPath(newest[1][1].media_name).name)}」'
                if newest is not None else '')
        raise ToolError(f'第 {number} 条（{_short(PureWindowsPath(record.media_name).name)}）没有能打开的结果'
                        f'（{record.status_label or record.status}），可以先看它为什么没完成{hint}')
    opener = getattr(window, '_open_completion_from_history', None)
    if not callable(opener):
        raise ToolError('这里打不开识别结果')
    opener(record)
    return (f'打开了第 {number} 条「{_short(PureWindowsPath(record.media_name).name)}」的识别结果，现在在识别完成的结果页'
            f'（字幕 {record.cue_count} 条）')


# ------------------------------------------------------------------ projects
def project_records(limit: int = LIST_LIMIT) -> list[dict]:
    """The project library's recent projects (what 工程库 shows), newest first."""
    from ..projects.studio_project import studio_settings_path
    try:
        payload = json.loads(studio_settings_path().read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return []
    recent = payload.get('recent_projects', []) if isinstance(payload, dict) else []
    rows = []
    for index, item in enumerate(recent):
        row = dict(item) if isinstance(item, dict) else {'path': str(item)}
        path = Path(str(row.get('path') or ''))
        row.setdefault('name', path.stem)
        # The library's 「最近使用」 order (studio_hub: last_opened, then updated_at, newest first); old
        # records without a time keep their saved order, as the library does.
        row.setdefault('last_opened', str(row.get('modified') or '') or f'9999-recent-{9999 - index:04d}')
        row['exists'] = path.is_file()
        rows.append(row)
    rows.sort(key=lambda row: (str(row.get('last_opened') or ''), str(row.get('updated_at') or '')), reverse=True)
    return rows[:limit]


def _recent_projects(_window, _args) -> str:
    rows = project_records()
    if not rows:
        return '工程库里还没有工程'
    lines = []
    for number, row in enumerate(rows, 1):
        media = _short(PureWindowsPath(str(row.get('source_media') or '')).name, 30)
        parts = [f'{number}. 「{_short(row.get("name"), 30)}」', f'字幕 {int(row.get("cue_count") or 0)} 条']
        if row.get('modified'):
            parts.append(f'上次编辑 {row["modified"]}')
        if media:
            parts.append(f'素材 {media}')
        parts.append('能打开' if row['exists'] else '工程文件不见了')
        lines.append(' · '.join(parts))
    return '工程库最近的工程（open_project 用这里的编号）：' + '；'.join(lines)


def _chosen_project(args):
    from .bunny_tools import ToolError
    row, number = _pick(project_records(), args, lambda item: str(item.get('name') or ''))
    if not row['exists']:
        raise ToolError(f'第 {number} 个工程「{_short(row.get("name"), 30)}」的文件不见了（被移走或删了）')
    return row, number


def _open_project(window, args) -> str:
    from .bunny_tools import ToolError
    if not callable(getattr(window, 'open_studio_project', None)):
        raise ToolError('这里打不开工程')
    row, number = _chosen_project(args)
    return f'第 {number} 个工程「{_short(row.get("name"), 30)}」马上在字幕工作台打开（有没保存的修改时会先问小兔纸）'


def open_project_later(window, args) -> None:
    try:
        row, _number = _chosen_project(args)
    except Exception:  # noqa: BLE001 - checked a moment ago; gone now means nothing to open
        return
    window.open_studio_project(str(row['path']))


def tools():
    from .bunny_tools import Tool
    return (
        Tool('recent_results', '{}', '最近的识别记录（编号、素材、状态、字幕条数、能不能打开结果）', _recent_results),
        Tool('open_result', '{}', '打开一次识别的结果（识别完成的结果页），和「识别记录 → 打开识别结果」一样；'
             '什么都不填 = 最新一次有结果的（会跳过失败的）；要指定就填 number（recent_results 的编号）或 name（素材名里的几个字）',
             _open_result, acts=True),
        Tool('recent_projects', '{}', '工程库最近的工程（编号、名字、字幕条数、上次编辑）', _recent_projects),
        Tool('open_project', '{"number": 1}', '在字幕工作台打开工程库里的一个工程，和「继续编辑」一样；'
             'number 是 recent_projects 的编号（1 是最近的），也可以填 name', _open_project, deferred=True, acts=True,
             later=open_project_later),
    )


__all__ = ['open_project_later', 'project_records', 'result_records', 'tools']
