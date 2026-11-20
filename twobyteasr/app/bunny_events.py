"""When 兔白 speaks up on her own, and what she says (2026-11-18, phase 3).

User (2026-11-18): she should be there by default, so people know she exists without looking for
「问问兔白」, and help more actively; and it must be possible to turn that off.

Everything here is decided on this computer from words written in this file: a hint never calls
the text AI. Only when the user presses one of a hint's buttons does the question go to the chat
(and from there to their AI, like any question they type).

* ``HINTS``: what can happen in the software -> her words and up to two buttons;
* ``decide``: whether a hint may be shown now (the user's level, cooldowns, a cap per start, and
  silence for a week after the same kind was closed twice);
* the user's choices (``load`` / ``save``): she stays in the window or not, hints for everything /
  only when something went wrong / never, and 「今天先别出来」.

No Qt. ``bunny_resident`` shows the hints and calls ``decide`` / ``dismissed``.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

KEY = 'bunny_hints'
MODES = ('all', 'errors', 'off')
MODE_LABELS = {'all': '全部（做完、出错、小窍门都说）', 'errors': '只在出错时', 'off': '关闭（不主动说话）'}
DEFAULTS = {'resident': True, 'mode': 'all', 'quiet_day': '', 'intro': False, 'closed': {}, 'place': None}
MIN_GAP_S = 45.0             # between two hints of the everyday kind
SESSION_CAP = 8              # everyday hints per start of the software
CLOSED_TWICE_QUIET_S = 7 * 24 * 3600.0
CLOSES_BEFORE_QUIET = 2
SAID_LIMIT = 160             # of an error dialog's own words, in the question she is asked


@dataclass(frozen=True)
class Hint:
    key: str
    lines: tuple                      # variants; one is picked. ``{name}`` fields come from the event's facts
    buttons: tuple = ()               # ((label, question), …) at most two; the question goes to the chat
    urgent: bool = False              # something went wrong: shown at 「只在出错时」 too, no gap or cap
    cooldown_s: float = 600.0
    per_session: int = 2
    mood: str = 'happy'
    act: str = ''


HINTS = {hint.key: hint for hint in (
    Hint('first_run',
         ('小兔纸你好呀～我是 **兔白**，住在这个软件里陪你做字幕。不会用、找不到按钮、出了问题都可以问我；'
          '不想让我待在这里，右键点我就能让我走开。',),
         (('带我看看怎么用', '我第一次用，怎么从头做一份字幕？'), ('先不用', '')),
         cooldown_s=0, per_session=1, act='hello'),
    Hint('recognition_done',
         ('识别做完啦，辛苦了～可以直接导出，也可以进工作台再修一修。',
          '^^好耶^^，字幕出来了～要不要兔白陪你检查一遍？'),
         (('帮我检查字幕', '帮我检查一下这次的字幕'), ('接下来做什么？', '识别完成了，接下来该做什么？')),
         cooldown_s=120, per_session=4, mood='excited', act='cheer'),
    Hint('recognition_review',
         ('识别做完啦～有 {count} 处想请你确认一下，==不是出错==哦，按 **R** 进审核模式就能逐条看。',),
         (('带我去审核', '带我去审核模式，逐条确认需复核项'), ('为什么要复核？', '为什么会有需复核项？')),
         cooldown_s=120, per_session=4, mood='happy'),
    Hint('recognition_failed',
         ('呜……这次识别没成功。先别急着重装，兔白可以帮你看看是卡在哪一步。',
          '识别没做成……不是你的错啦，让兔白查查原因好不好？'),
         (('帮我看看原因', '上次识别为什么失败？帮我查一下原因和解决办法'), ('知道了', '')),
         urgent=True, cooldown_s=60, per_session=6, mood='sorry', act='startled'),
    Hint('error_dialog',
         ('兔白看到刚才跳出一个提示：「{title}」。看不懂的话可以问我。',),
         (('这是什么意思？', '刚才弹出的提示「{said}」是什么意思，该怎么办？'), ('没事', '')),
         urgent=True, cooldown_s=90, per_session=6, mood='surprised', act='startled'),
    Hint('idle_page',
         ('{tip}',),
         (), cooldown_s=900, per_session=3),
    Hint('no_text_ai',
         ('兔白现在还没有 AI 脑袋，只能帮你找功能在哪里。设置好文字 AI，就能聊天、帮你查问题和动手操作了。',),
         (('怎么设置？', '怎么设置文字 AI？'), ('以后再说', '')),
         cooldown_s=24 * 3600.0, per_session=1),
    Hint('welcome_back',
         ('欢迎回来～上次做到「{name}」，要接着做吗？',
          '小兔纸来啦。「{name}」还等着你呢，兔白帮你打开？'),
         (('打开上次的工程', '帮我打开最近编辑的那个工程'), ('今天做新的', '')),
         cooldown_s=0, per_session=1, act='hello'),
    Hint('welcome_plain',
         ('小兔纸来啦～今天也一起做字幕吧。', '哟，又见面了。有事叫兔白，兔白就在这儿。'),
         (), cooldown_s=0, per_session=1, act='hello'),
    Hint('level_up',
         ('{line}',),
         (), cooldown_s=0, per_session=2, mood='shy', act='love'),
    Hint('mutter',
         ('__……胡萝卜行动，今日进度 +0.01%__　啊，小兔纸你什么都没听到！',
          '__偷啃一口 Token……__　咳，兔白在认真待命哦。',
          '__要是全世界的视频都用兔白字幕……__　没、没什么，在想字幕的事啦。',
          '兔白刚才数了数钥匙扣大军的人数。……还是只有兔白一个。'),
         (), cooldown_s=1800, per_session=2, mood='teasing', act='smirk'),
    Hint('late_night',
         ('都这么晚了还在做字幕呀……做完这一段就去睡好不好？兔白帮你记着做到哪了。',),
         (), cooldown_s=24 * 3600.0, per_session=1, mood='comfort', act='sleepy'),
)}


PLACE_RULE = 2


def load() -> dict:
    from .onboarding import load_state
    stored = load_state().get(KEY)
    merged = dict(DEFAULTS, closed={})
    if isinstance(stored, dict):
        if isinstance(stored.get('resident'), bool):
            merged['resident'] = stored['resident']
        if stored.get('mode') in MODES:
            merged['mode'] = stored['mode']
        merged['quiet_day'] = str(stored.get('quiet_day') or '')
        merged['intro'] = stored.get('intro') is True
        closed = stored.get('closed')
        if isinstance(closed, dict):
            merged['closed'] = {str(key): [int(row[0]), float(row[1])] for key, row in closed.items()
                                if isinstance(row, (list, tuple)) and len(row) == 2 and key in HINTS}
        # 2026-11-19: a place kept before PLACE_RULE 2 may be where a wrong jump between screens
        # left her (the upper left), not where the user put her: she starts in her corner again.
        place = stored.get('place') if stored.get('place_rule') == PLACE_RULE else None
        if isinstance(place, (list, tuple)) and len(place) == 2 and all(isinstance(v, (int, float)) for v in place):
            merged['place'] = [int(place[0]), int(place[1])]
    return merged


def save(values: dict) -> None:
    from .onboarding import load_state, save_state
    kept = {name: values[name] for name in DEFAULTS if name in values}
    save_state(dict(load_state(), **{KEY: dict(load(), **kept, place_rule=PLACE_RULE)}))


def today() -> str:
    return time.strftime('%Y-%m-%d')


def resident_wanted(values: dict | None = None) -> bool:
    """She stays in the window: the switch is on and it is not a 「今天先别出来」 day."""
    values = load() if values is None else values
    return bool(values['resident']) and values['quiet_day'] != today()


@dataclass
class Session:
    """What this start of the software has already shown."""
    shown: dict = field(default_factory=dict)          # key -> [count, last time]
    last_everyday: float = -1e9
    everyday: int = 0


def decide(event: str, values: dict, session: Session, now: float | None = None) -> Hint | None:
    """The hint for ``event`` when she may say it now, else None. Nothing is recorded here."""
    hint = HINTS.get(event)
    now = time.time() if now is None else now
    if hint is None or values['mode'] == 'off' or not resident_wanted(values):
        return None
    if values['mode'] == 'errors' and not hint.urgent:
        return None
    if event == 'first_run' and values['intro']:
        return None
    closes, until = values['closed'].get(event, (0, 0.0))
    if closes >= CLOSES_BEFORE_QUIET and now < until:
        return None
    count, last = session.shown.get(event, (0, -1e9))
    if count >= hint.per_session or now - last < hint.cooldown_s:
        return None
    if not hint.urgent and event != 'first_run':
        if session.everyday >= SESSION_CAP or now - session.last_everyday < MIN_GAP_S:
            return None
    return hint


def shown(event: str, session: Session, now: float | None = None) -> None:
    hint = HINTS[event]
    now = time.time() if now is None else now
    count, _last = session.shown.get(event, (0, 0.0))
    session.shown[event] = [count + 1, now]
    if not hint.urgent:
        session.everyday += 1
        session.last_everyday = now
    if event == 'first_run':
        save({'intro': True})


def dismissed(event: str, now: float | None = None) -> None:
    """The user closed this hint with ×: the second time, that kind is quiet for a week."""
    if event not in HINTS:
        return
    now = time.time() if now is None else now
    values = load()
    closes, until = values['closed'].get(event, (0, 0.0))
    closes = 1 if (closes >= CLOSES_BEFORE_QUIET and now >= until) else closes + 1
    values['closed'][event] = [closes, now + CLOSED_TWICE_QUIET_S if closes >= CLOSES_BEFORE_QUIET else 0.0]
    save({'closed': values['closed']})


def used(event: str) -> None:
    """A button was pressed: that kind of hint is welcome, forget earlier closes."""
    values = load()
    if values['closed'].pop(event, None) is not None:
        save({'closed': values['closed']})


# ---- what just happened (2026-11-18, phase 5) ---------------------------------------------------
# A short memory of this start of the software: an error box that was closed, a recognition that
# finished or failed. The chat hands it to the AI with the next question (「最近发生的事」), so
# "what was that just now?" needs no explaining. In memory only; gone when the app closes.
RECENT_KEEP, RECENT_S, RECENT_CHARS = 6, 1800.0, 150
_recent: list = []           # [time, words]


def remember(words: str, now: float | None = None) -> None:
    words = _clean(words, RECENT_CHARS)
    if not words:
        return
    now = time.time() if now is None else now
    if _recent and _recent[-1][1] == words and now - _recent[-1][0] < 30:
        return                                       # the same box twice in a row
    _recent.append([now, words])
    del _recent[:-RECENT_KEEP]


def recent_text(now: float | None = None) -> str:
    """The last half hour's happenings, oldest first, as one line ('' when there were none)."""
    now = time.time() if now is None else now
    rows = []
    for at, words in _recent:
        age = now - at
        if 0 <= age <= RECENT_S:
            when = '刚才' if age < 90 else f'{int(age // 60)} 分钟前'
            rows.append(f'{when}{words}')
    return '；'.join(rows)


def forget_recent() -> None:
    del _recent[:]


def _clean(text, limit: int) -> str:
    text = ' '.join(str(text or '').split()).replace('{', '（').replace('}', '）')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def wording(hint: Hint, facts: dict | None = None) -> tuple:
    """(her line, ((label, question), …)) with the event's facts filled in."""
    facts = {name: _clean(value, SAID_LIMIT) for name, value in (facts or {}).items()}
    try:
        line = random.choice(hint.lines).format(**facts)
        buttons = tuple((label, question.format(**facts)) for label, question in hint.buttons)
    except (KeyError, IndexError):
        return '', ()
    return line, buttons


def outcome_event(status: str, review_count: int = 0) -> tuple:
    """A finished recognition's report status -> (event, facts) or ('', {})."""
    status = str(status or '')
    if status in ('failed', 'interrupted', 'needs_recovery', 'empty_result'):
        return 'recognition_failed', {}
    if status in ('completed', 'partial', 'ok', 'success', 'done'):
        return ('recognition_review', {'count': int(review_count)}) if review_count else ('recognition_done', {})
    return '', {}


__all__ = ['DEFAULTS', 'HINTS', 'Hint', 'MODES', 'MODE_LABELS', 'Session', 'decide', 'dismissed', 'forget_recent',
           'load', 'outcome_event', 'recent_text', 'remember', 'resident_wanted', 'save', 'shown', 'today', 'used',
           'wording']
