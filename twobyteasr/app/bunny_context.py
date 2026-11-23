"""Long tasks stay inside a bounded request: older rounds become a short progress note (2026-11-22).

User (2026-11-22): 兔白的长任务摘要也接着做（harness plan "context editing / compaction").

A question that takes many tool rounds (``start_task`` allows 20, a subtask runs its own) used to
send every round again with each request; ``compact_messages`` only shortened old tool results.
Now, once a question has more than ``SUMMARY_AFTER_ROUNDS`` rounds or its words pass
``SUMMARY_CHARS``, every round but the newest ``KEEP_ROUNDS`` is folded into one note appended to
the user's own question: the goal, the steps done with their outcomes, and what is still to do (her
latest step list). The question itself is never cut, so the user's original words always go whole.
The note is rebuilt from the full turn every time (no summary of a summary), it costs no AI request,
and ``bound`` then keeps the whole request under ``REQUEST_CHARS`` (oldest history first).
"""
from __future__ import annotations

import json
import re

SUMMARY_MARK = '【任务进度摘要】'
RESULT_TAG = '【兔白操作结果'
SUMMARY_AFTER_ROUNDS = 6         # a question with more rounds than this has its older rounds folded
KEEP_ROUNDS = 3                  # the newest rounds always go whole
SUMMARY_CHARS = 30000            # ... or once the question's own rounds pass this many characters
REQUEST_CHARS = 60000            # one request's words at most (pictures are not counted)
STEP_CHARS = 150
MAX_STEPS = 30
SHORT_RESULT = 400


def _words(content) -> str:
    if isinstance(content, list):
        return ''.join(str(part.get('text') or '') for part in content if isinstance(part, dict))
    return str(content or '')


def size(messages) -> int:
    return sum(len(_words(row.get('content'))) for row in messages)


def _short(text, limit: int = STEP_CHARS) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def split_rounds(rows) -> list[list[dict]]:
    """The messages after a question as rounds: each starts with her answer, then the program's turn(s)."""
    rounds = []
    for row in rows:
        if row.get('role') == 'assistant' or not rounds:
            rounds.append([row])
        else:
            rounds[-1].append(row)
    return rounds


def _reply(row) -> dict:
    try:
        data = json.loads(_words(row.get('content')))
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _receipts(rows) -> list[str]:
    lines = []
    for row in rows:
        text = _words(row.get('content'))
        if not text.startswith(RESULT_TAG):
            continue
        body = text.split('\n', 1)[1] if '\n' in text else ''
        body = body.split('\n\n【现在的软件状态】', 1)[0]
        for line in body.splitlines():
            if line.startswith('- '):
                lines.append(line[2:])
            elif lines and line.strip() and len(lines[-1]) < STEP_CHARS:
                lines[-1] += ' ' + line.strip()           # a receipt's next lines (a snapshot list)
    return lines


def summary_note(rounds, *, goal: str = '') -> str:
    """The note for ``rounds`` (already done): goal, steps done with outcomes, results, still to do."""
    done, steps, step_now, said, ok, failed = [], None, 0, '', 0, 0
    for round_rows in rounds:
        data = _reply(round_rows[0]) if round_rows and round_rows[0].get('role') == 'assistant' else {}
        calls = [item for item in data.get('tools') or () if isinstance(item, dict)]
        if isinstance(data.get('steps'), list):
            steps, step_now = [str(step) for step in data['steps']], int(data.get('step_now') or 0)
        for call in calls:
            if call.get('name') == 'start_task':
                args = call.get('args') if isinstance(call.get('args'), dict) else {}
                goal = goal or str(args.get('goal') or '')
                if steps is None and isinstance(args.get('steps'), list):
                    steps = [str(step) for step in args['steps']]
        lines = data.get('lines') or []
        if lines:
            said = str(lines[-1])
        receipts = _receipts(round_rows[1:])
        if receipts:
            for line in receipts:
                done.append(_short(line))
                if re.search(r'：(没做成|没有读取|没查到|没截|没查)', line):
                    failed += 1
                elif '还没做' not in line:
                    ok += 1
        else:
            done += [_short(f'{call.get("name")}({json.dumps(call.get("args") or {}, ensure_ascii=False)[:60]})：'
                            '没有结果记录') for call in calls]
    if len(done) > MAX_STEPS:
        skipped = len(done) - MAX_STEPS
        done = [*done[:5], f'……（中间 {skipped} 步省略）', *done[-(MAX_STEPS - 5):]]
    rows = [f'{SUMMARY_MARK}（较早的 {len(rounds)} 轮已经压缩成下面几行；上面是小兔纸的原始要求，照它做，不要改目标）']
    if goal:
        rows.append(f'目标：{_short(goal, 200)}')
    rows.append('已做的步骤和结果：' if done else '已做的步骤：（还没有）')
    rows += [f'{index}. {line}' for index, line in enumerate(done, 1)]
    rows.append(f'结果：成功 {ok} 步，没做成 {failed} 步' + ('（没做成的要换办法或照实说）' if failed else ''))
    if steps:
        left = steps[step_now:] if 0 <= step_now < len(steps) else []
        rows.append('还要做：' + ('；'.join(left) if left else '计划的步骤都做过了，确认结果后回答'))
    else:
        rows.append('还要做：看下面最新几轮，接着把原始要求做完')
    if said:
        rows.append(f'兔白上次说到：{_short(said, 100)}')
    return '\n'.join(rows)


def _with_note(question: dict, note: str) -> dict:
    content = question.get('content')
    if isinstance(content, list):                          # pictures ride with the question
        return {**question, 'content': [*content, {'type': 'text', 'text': '\n\n' + note}]}
    return {**question, 'content': f'{content}\n\n{note}'}


def summarize(messages: list[dict], start: int, *, keep_rounds: int = KEEP_ROUNDS,
              after_rounds: int = SUMMARY_AFTER_ROUNDS, chars: int = SUMMARY_CHARS) -> tuple[list[dict], int]:
    """(messages with older rounds folded into the question, how many rounds were folded)."""
    if not 0 <= start < len(messages) or messages[start].get('role') != 'user':
        return messages, 0
    rounds = split_rounds(messages[start + 1:])
    if len(rounds) <= keep_rounds or (len(rounds) <= after_rounds and size(messages[start + 1:]) <= chars):
        return messages, 0
    old, kept = rounds[:-keep_rounds], rounds[-keep_rounds:]
    if kept and kept[0][0].get('role') != 'assistant':     # the kept part must open with her answer
        return messages, 0
    question = _with_note(messages[start], summary_note(old))
    return [*messages[:start], question, *(row for round_rows in kept for row in round_rows)], len(old)


def bound(messages: list[dict], start: int, limit: int = REQUEST_CHARS) -> list[dict]:
    """Keep one request under ``limit`` words: shorten older tool results, then drop the oldest history.
    The system prompt, the user's question and her newest round always stay whole."""
    if size(messages) <= limit:
        return messages
    rows = list(messages)
    results = [index for index, row in enumerate(rows) if index > start and row.get('role') == 'user'
               and _words(row.get('content')).startswith(RESULT_TAG)]
    for index in results[:-1]:
        content = rows[index].get('content')
        if isinstance(content, str) and len(content) > SHORT_RESULT:
            rows[index] = dict(rows[index], content=content[:SHORT_RESULT] + '\n（较早一轮的结果太长，已省略后面部分；需要的话重新查）')
        if size(rows) <= limit:
            return rows
    first = 1 if rows and rows[0].get('role') == 'system' else 0
    while size(rows) > limit and start > first:            # older questions and answers before this one
        del rows[first]
        start -= 1
    if size(rows) > limit and results:
        last = next((i for i in range(len(rows) - 1, start, -1) if rows[i].get('role') == 'user'
                     and _words(rows[i].get('content')).startswith(RESULT_TAG)), None)
        if last is not None and isinstance(rows[last].get('content'), str):
            room = max(2000, len(rows[last]['content']) - (size(rows) - limit))
            rows[last] = dict(rows[last], content=rows[last]['content'][:room] + '\n（结果太长，后面省略了）')
    return rows


def prepare(messages: list[dict], start: int) -> tuple[list[dict], int]:
    """What one request sends for a question starting at ``start``: folded, then bounded. (rows, folded)."""
    rows, folded = summarize(messages, start)          # the question keeps its index
    return bound(rows, start), folded


__all__ = ['KEEP_ROUNDS', 'REQUEST_CHARS', 'SUMMARY_MARK', 'bound', 'prepare', 'size', 'split_rounds',
           'summarize', 'summary_note']
