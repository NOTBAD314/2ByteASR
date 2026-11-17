"""「新手任务」: small things worth doing once, ticked by themselves (2026-11-16).

User (2026-11-16) picked the tutorial centre with a 新手任务 tab (design C) and asked for the
tasks that matter. A task is ticked the first time the person does it in their own work:
the places that do it call ``mark(key)``; practice inside a running tutorial does not count
(``GuidedTour.live``). Two are read from state instead: a real first subtitle
(``onboarding`` ``first_task_done``) and a connected text AI.

The ticks live in the onboarding state (``tasks_done``), next to ``chapters_done``.
``mark`` never raises and does nothing once a task is ticked.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    hint: str                 # where it is done
    chapter: str = ''         # the tutorial chapter that shows it ('' = none)


TASKS = (
    Task('first_subtitle', '用自己的视频做出第一份字幕', '首页放入视频，点「开始生成字幕」', 'first'),
    Task('set_ai', '连好文字 AI', '首页「AI 智能断句」卡：填 Key、测试连接', 'first'),
    Task('export', '导出一次字幕文件', '结果页或工作台的「导出字幕」', 'first'),
    Task('proofread', '用 AI 词库校对改对一个词', '结果页「开始校对」', 'fix'),
    Task('review', '按 R 进审核模式', '字幕工作台按 R', 'studio'),
    Task('cut', '切开一条字幕', '剃刀 C，或编辑时 Shift+C', 'studio'),
    Task('shift_all', '整片字幕一起提前或推后', 'Ctrl+A 全选，再 Alt+← / →', 'editor'),
    Task('add_term', '在术语库加一个词', '术语库：正确写法 + 常被听成 → 添加', 'terms'),
    Task('try_line', '用「试一句」看词库怎么改', '术语库 →「试一句」', 'terms'),
    Task('ask_bunny', '问兔白一个问题', '顶栏「问问兔白」', 'bunny'),
    Task('speakers', '在说话人管理里改名或合并', '工作台工具栏「说话人管理」', 'speakers'),
    Task('translate', '翻译一次字幕', '工作台「翻译所选」，或首页「字幕显示」选双语', ''),
    Task('render', '压制一段带字幕的视频', '工作台「导出音视频」（Ctrl+Shift+E）', 'render'),
)
BY_KEY = {task.key: task for task in TASKS}


def _practising() -> bool:
    try:
        from .home_tour import GuidedTour
        return GuidedTour.live > 0
    except Exception:  # noqa: BLE001
        return False


def mark(key: str) -> bool:
    """The person just did ``key`` for real: tick it (once). True when newly ticked."""
    if key not in BY_KEY or _practising():
        return False
    try:
        from . import onboarding
        state = onboarding.load_state()
        done = list(state.get('tasks_done') or ())
        if key in done:
            return False
        onboarding.save_state(dict(state, tasks_done=done + [key]))
        return True
    except Exception:  # noqa: BLE001 - a tick must never break what the person was doing
        return False


def done_keys(window=None, state: dict | None = None) -> set:
    """Ticked tasks: the marked ones, plus those read from state (first subtitle, text AI)."""
    if state is None:
        try:
            from . import onboarding
            state = onboarding.load_state()
        except Exception:  # noqa: BLE001
            state = {}
    done = set(state.get('tasks_done') or ())
    if state.get('first_task_done'):
        done.add('first_subtitle')
    unlocked = getattr(window, '_ai_unlocked', None) if window is not None else None
    try:
        if callable(unlocked) and unlocked():
            done.add('set_ai')
    except Exception:  # noqa: BLE001
        pass
    return done & set(BY_KEY)
