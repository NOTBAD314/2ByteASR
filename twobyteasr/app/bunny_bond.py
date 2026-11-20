"""How well 兔白 and this user know each other (2026-11-18, phase 4).

User (2026-11-18): she should feel alive and give something back emotionally. Part of that is that
she is not a stranger every time: the more they have done together, the more familiar she talks.

Counted on this computer only, never sent anywhere as numbers: questions asked, recognitions she saw
finish, the days they met. From these comes a level; the chat tells the AI the level in one line
(``inner_line``), her greeting changes with it (``greeting``), and reaching a new level is said once
(``bunny_events`` 「level_up」). No tasks, points or rewards are shown to the user.

Only while 「让兔白记住我的习惯」 is on (``bunny_permissions`` ``remember``); with it off nothing is
counted and she stays at the first level. No Qt.
"""
from __future__ import annotations

import random
import time

KEY = 'bunny_bond'
WEIGHTS = {'chat': 1, 'done': 5, 'day': 3}
LEVELS = (               # (points from, name, how she talks at this level)
    (0, '刚认识', '还有点客气，会认真自我介绍；逗人只是轻轻的。'),
    (15, '熟起来了', '说话放松了，可以多一点调皮和傲娇，会主动问一句最近在做什么。'),
    (60, '老搭档', '像老朋友：会翻旧账、互相吐槽，夸人更具体，偶尔撒娇要夸奖。'),
    (150, '最好的朋友', '最亲近：最放得开、最会接梗，也最会在对方累的时候先关心人；但从不越界、不黏人。'),
)
GREETINGS = (
    (('嗨～小兔纸，我是兔白。', '有不懂的随时问我，想聊天也可以哦。'),),
    (('小兔纸来啦～', '今天做什么字幕？兔白都准备好了。'),
     ('哟，又见面了。', '有事就说，没事聊两句也行～')),
    (('老搭档上线！', '说吧，今天要兔白帮你搞定什么？'),
     ('来啦来啦～', '~~才没有在等你~~ 刚好有空而已。')),
    (('小兔纸～', '兔白今天也在这儿等你，开工还是先聊会儿？'),
     ('你来啦！', '__偷偷说，计划进度今天也是 0.01%__ 咳，先做字幕。')),
)
LEVEL_UP = (
    '',
    '感觉和小兔纸熟起来了～以后兔白说话可以随便一点了吧？',
    '不知不觉一起做了这么多字幕……哼，勉强承认你是兔白的老搭档了。',
    '^^欧耶^^，小兔纸已经是兔白最好的朋友啦。~~这句话录下来~~ 不许笑！',
)


def _allowed() -> bool:
    try:
        from . import bunny_permissions
        return bool(bunny_permissions.load().get('remember', True))
    except Exception:  # noqa: BLE001 - unreadable choices: count nothing
        return False


def load() -> dict:
    from .onboarding import load_state
    stored = load_state().get(KEY)
    values = {'chat': 0, 'done': 0, 'day': 0, 'last_day': '', 'told': 0, 'welcomed': ''}
    if isinstance(stored, dict):
        for name in ('chat', 'done', 'day', 'told'):
            try:
                values[name] = max(0, int(stored.get(name) or 0))
            except (TypeError, ValueError):
                pass
        values['last_day'] = str(stored.get('last_day') or '')
        values['welcomed'] = str(stored.get('welcomed') or '')
    return values


def _save(values: dict) -> None:
    from .onboarding import load_state, save_state
    save_state(dict(load_state(), **{KEY: values}))


def points(values: dict | None = None) -> int:
    values = load() if values is None else values
    return sum(values[name] * weight for name, weight in WEIGHTS.items())


def level(values: dict | None = None) -> int:
    score = points(values)
    return max(index for index, (start, _name, _how) in enumerate(LEVELS) if score >= start)


def note(kind: str, today: str | None = None) -> int:
    """One more ``chat`` or ``done``; a new day is counted with it. Returns the level now."""
    if kind not in ('chat', 'done') or not _allowed():
        return level()
    values = load()
    values[kind] += 1
    today = time.strftime('%Y-%m-%d') if today is None else today
    if values['last_day'] != today:
        values['last_day'] = today
        values['day'] += 1
    _save(values)
    return level(values)


def level_up_line() -> str:
    """Her words for a level reached but not yet said ('' when there is none); saying it is recorded."""
    values = load()
    now = level(values)
    if now <= values['told'] or not _allowed():
        return ''
    values['told'] = now
    _save(values)
    return LEVEL_UP[now]


def welcome_due(today: str | None = None) -> bool:
    """Once a day, from the second level on: she may greet the user back at the start. Recorded."""
    if not _allowed():
        return False
    values = load()
    today = time.strftime('%Y-%m-%d') if today is None else today
    if level(values) < 1 or values['welcomed'] == today:
        return False
    values['welcomed'] = today
    _save(values)
    return True


def greeting(rng=random) -> tuple:
    return rng.choice(GREETINGS[level()])


def inner_line() -> str:
    """One line for the AI about how familiar she is with this user."""
    index = level()
    _start, name, how = LEVELS[index]
    return f'- 和小兔纸的熟悉度：{name}（第 {index + 1} 级，共 {len(LEVELS)} 级）。{how}'


def clear() -> None:
    from .onboarding import load_state, save_state
    save_state({key: value for key, value in load_state().items() if key != KEY})


__all__ = ['LEVELS', 'clear', 'greeting', 'inner_line', 'level', 'level_up_line', 'load', 'note', 'points',
           'welcome_due']
