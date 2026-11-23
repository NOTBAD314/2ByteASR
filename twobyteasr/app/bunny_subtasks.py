"""Subtasks: a big job split into parts, each run with a clean context (2026-11-22).

User (2026-11-22): 兔白的子任务也接着做（harness plan "subagents"）。

``run_subtask`` is a tool she asks for like any other; the chat (``BunnyChat``) runs it: the main
question waits, the subtask gets a fresh request (her fixed system prompt, the user's original words
and the subtask's goal, no chat history and none of the main question's rounds), works through its
own tool rounds under the same 「兔白权限」, and its result comes back to the main question as one
short receipt line (what was done, outcome, the subtask's own last words). Bounds: at most
``MAX_PER_QUESTION`` subtasks per question, ``ROUNDS_CAP`` rounds and ``CHAR_BUDGET`` characters sent
(the cost) per subtask; a subtask cannot start another; the chat's cancel button stops it. Progress
(which subtask, which round) shows in the chat while it runs.
"""
from __future__ import annotations

import dataclasses
import time

DEFAULT_ROUNDS = 6
ROUNDS_CAP = 10
MAX_PER_QUESTION = 4
CHAR_BUDGET = 240000             # characters sent to the AI by one subtask (≈ its cost), retries included
REQUEST_CAP = ROUNDS_CAP + 4     # requests by one subtask (format retries included)
RESULT_CHARS = 600
GOAL_CHARS = 160


@dataclasses.dataclass
class Subtask:
    goal: str
    done_when: str = ''
    max_rounds: int = DEFAULT_ROUNDS
    index: int = 1
    total: int = 1
    rounds: int = 0
    requests: int = 0
    sent_chars: int = 0
    started: float = dataclasses.field(default_factory=time.monotonic)
    final: str = ''
    stopped: str = ''            # why it ended before finishing: rounds / budget / error / cancelled
    format_retried: bool = False

    def over(self) -> str:
        """Why it may not send another request ('' when it may)."""
        if self.sent_chars >= CHAR_BUDGET:
            return f'费用上限（已发送约 {self.sent_chars // 1000} 千字）'
        if self.requests >= min(REQUEST_CAP, self.max_rounds + 4):
            return f'请求次数上限（{self.requests} 次）'
        return ''

    def status(self) -> str:
        goal = self.goal if len(self.goal) <= 14 else self.goal[:13] + '…'
        return f'子任务 {self.index}/{self.total}「{goal}」第 {min(self.rounds + 1, self.max_rounds)}/{self.max_rounds} 轮'


def from_call(args: dict, index: int, total: int) -> Subtask:
    from .bunny_tools import ToolError
    goal = ' '.join(str(args.get('goal') or '').split())[:GOAL_CHARS]
    if not goal:
        raise ToolError('goal 要写这个子任务要做成什么')
    try:
        rounds = int(args.get('max_rounds') or DEFAULT_ROUNDS)
    except (TypeError, ValueError):
        rounds = DEFAULT_ROUNDS
    return Subtask(goal=goal, done_when=' '.join(str(args.get('done_when') or '').split())[:GOAL_CHARS],
                   max_rounds=max(1, min(ROUNDS_CAP, rounds)), index=index, total=total)


def question_text(sub: Subtask, original: str) -> str:
    """The subtask's first words: a clean start that still knows what the user asked for."""
    original = ' '.join(str(original or '').split())
    return '\n'.join((
        '【子任务】这是兔白自己从大任务里分出来的一块，用干净的上下文做；做完只交回结果，不跟小兔纸聊天。',
        f'小兔纸原来的要求：{original[:300]}',
        f'这个子任务的目标：{sub.goal}',
        f'做到这样就算完成：{sub.done_when or "目标做到，结果核对过"}',
        f'最多 {sub.max_rounds} 轮工具，照常遵守「兔白权限」（要确认的改动只会排队等「帮我做」）。'
        '做完时 tools 填 []，lines 写结果：做成了什么、关键数字、没做成的原因；不要填 suggest，不要再分子任务。',
    ))


def result_line(sub: Subtask, rounds_rows) -> str:
    """The one receipt the main question gets back: outcome, steps done, the subtask's own last words."""
    from .bunny_context import _receipts
    done = [line for round_rows in rounds_rows for line in _receipts(round_rows[1:])]
    failed = sum(1 for line in done if '：没做成' in line or '：没有读取' in line)
    waiting = sum(1 for line in done if '还没做' in line)
    steps = '；'.join(' '.join(line.split())[:60] for line in done[-6:])
    end = (f'没做完（停在{sub.stopped}）' if sub.stopped else '完成')
    words = ' '.join(str(sub.final or '').split())
    line = (f'- run_subtask(goal={sub.goal})：{end}。用了 {sub.rounds} 轮、{sub.requests} 次请求。'
            f'做了 {len(done)} 步（没做成 {failed}，等「帮我做」{waiting}）'
            + (f'：{steps}' if steps else '') + (f'。子任务的结论：{words}' if words else ''))
    return line if len(line) <= RESULT_CHARS else line[:RESULT_CHARS - 1] + '…'


def _run_subtask(_window, _args):
    from .bunny_tools import ToolError
    raise ToolError('子任务只能在「问问兔白」的聊天里跑')


def tools():
    from .bunny_tools import Tool
    return (
        Tool('run_subtask', '{"goal": "检查「原神」词库有没有重复和错字", "done_when": "列出问题条目", "max_rounds": 6}',
             f'把大任务里能独立做完的一块交给子任务：它用干净的上下文自己跑工具（最多 {ROUNDS_CAP} 轮、有费用上限，照常遵守权限），'
             f'做完把结果摘要成一行交回来；一题最多 {MAX_PER_QUESTION} 个，子任务里不能再分子任务。'
             '适合互不相干的几块（分别检查几个词库、分别读几个文件）；一两步的小事直接做，不要用它', _run_subtask),
    )


__all__ = ['CHAR_BUDGET', 'MAX_PER_QUESTION', 'ROUNDS_CAP', 'Subtask', 'from_call', 'question_text', 'result_line',
           'tools']
