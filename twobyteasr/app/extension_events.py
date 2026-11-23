"""Moments 「我的改动」 extension scripts can listen to (2026-11-20).

User (2026-11-20): a user wanted 识别后自动建术语库 — after he corrects the subtitles, an AI sorts his
corrections and adds them to a term library by itself. That stays out of the program everyone gets
(it would fill libraries with noise), but 兔白 should be able to write it for him as his own extension.
A script could only poll with ``api.every``; now ``api.on(event, callback)`` is called at these moments:

* ``subtitle_edited``      the user changed a line in the workbench by hand;
* ``project_saved``        the project was saved (Ctrl+S / 保存);
* ``recognition_finished`` a recognition finished with results.

Callbacks run on the GUI thread, one after another, right after the moment; a slow job belongs in
``api.in_background`` / ``api.ai``. A callback that raises is logged (「我的改动」 → 脚本记录); after
``MAX_FAILURES`` failures in a row the script is switched off and marked, never raised into the program.
Only scripts that are switched on (and 「允许运行我的扩展脚本」) are called. No Qt here.
"""
from __future__ import annotations

import traceback

EVENTS = {
    'subtitle_edited': '工作台里手动改了一句字幕。payload：before（改前整句）、after（改后整句）、'
                       'replacements（软件认出的 [(原词, 改成)] 词对）、glossary_ids（这个工程选的词库 id）、language、project',
    'project_saved': '工程保存好了。payload：path（工程文件路径）、project（工程对象：project.cues 每条有 text、start_ms、end_ms）',
    'recognition_finished': '一次识别做完了。payload：count（成功几个）、results（每个成功的视频一项 dict：'
                            'media 视频路径、srt、txt 字幕文件路径、project 工程文件路径）',
}
MAX_FAILURES = 3

_listeners: dict[str, list[tuple[str, object]]] = {}
_failures: dict[str, int] = {}


def on(script_id: str, event: str, callback) -> None:
    if event not in EVENTS:
        raise ValueError(f'没有「{event}」这个事件，可以用：{"、".join(EVENTS)}')
    if not callable(callback):
        raise TypeError('callback 要是函数')
    _listeners.setdefault(event, []).append((str(script_id), callback))


def drop(script_id: str) -> None:
    """Forget every callback of a script (it was changed, removed or unloaded)."""
    for event, rows in list(_listeners.items()):
        _listeners[event] = [row for row in rows if row[0] != str(script_id)]
    _failures.pop(str(script_id), None)


def has(event: str) -> bool:
    return bool(_listeners.get(event))


def _active_ids() -> set[str]:
    from . import user_overlay
    state = user_overlay.load()
    if not state.get('scripts_allowed'):
        return set()
    return {entry['id'] for entry in user_overlay.active('script', state)}


def _log(line: str) -> None:
    from . import user_overlay_runtime
    runtime = user_overlay_runtime.runtime()
    if runtime is not None:
        runtime.log.append(line)


def emit(event: str, **payload) -> int:
    """Call the listening, switched-on scripts; returns how many ran without an error. Never raises."""
    rows = list(_listeners.get(event) or ())
    if not rows:
        return 0
    try:
        active = _active_ids()
    except Exception:  # noqa: BLE001 - an unreadable layer runs nothing
        return 0
    done = 0
    for script_id, callback in rows:
        if script_id not in active:
            continue
        try:
            callback(dict(payload, event=event))
        except Exception as exc:  # noqa: BLE001 - the user's script must never break the program
            count = _failures.get(script_id, 0) + 1
            _failures[script_id] = count
            where = traceback.extract_tb(exc.__traceback__)[-1].lineno if exc.__traceback__ else '?'
            why = f'{type(exc).__name__}: {str(exc)[:160]}（第 {where} 行）'
            _log(f'[{script_id}] {event} 出错：{why}')
            if count >= MAX_FAILURES:
                drop(script_id)
                try:
                    from . import user_overlay
                    user_overlay.mark(script_id, 'failed', f'{event} 连续出错 {count} 次：{why}', disable=True)
                except Exception:  # noqa: BLE001
                    pass
                _log(f'[{script_id}] 连续出错 {count} 次，已停用')
            continue
        _failures.pop(script_id, None)
        done += 1
    return done


def reset() -> None:
    """Tests and a fresh runtime: nobody listens."""
    _listeners.clear()
    _failures.clear()


__all__ = ['EVENTS', 'MAX_FAILURES', 'drop', 'emit', 'has', 'on', 'reset']
