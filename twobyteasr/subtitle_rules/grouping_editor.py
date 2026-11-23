"""AI subtitle-editor pass over a batch's finished Chinese lines (2026-11-22).

User (1 h 洛克王国 stream, after paid reruns reached about 93%): "99.9% should
be right without human edits". In those reruns the line breaker picked
numbered marks and, when it had to split a long line, mostly copied the local
reference cut; DeepSeek v4 flash punctuated the same sentences almost
perfectly when it wrote text. This pass gives the model the batch's current
lines as text and asks it, as a subtitle editor, to return the same text with
better line breaks. Only line breaks may change.

Every answer is checked locally: the characters of each group must be
identical (spaces and punctuation aside), protected cuts (speaker change,
long silence) stay because each group lies between them, no line may exceed
the limit unless it cannot be cut, and no cut may fall inside a confirmed
term or a number. A group whose answer fails keeps its current lines.
"""
from __future__ import annotations

import json
import time

PROMPT_VERSION = 'zh-subtitle-editor-v3-judged'
ROUNDS = 2

SCHEMA = {'type': 'object', 'properties': {'groups': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'id': {'type': 'integer'}, 'lines': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['id', 'lines']}}}, 'required': ['groups']}


def system_prompt(max_chars):
    return (
        "你是资深中文字幕编辑，负责找出并修正口语字幕里分行分错的地方。输入是若干组(group)，每组是同一个人连续说的话，"
        "lines是当前的分行，每行就是屏幕上的一条字幕。\n"
        "铁律：只能移动换行位置；每组输出拼起来必须和输入逐字相同，不得增删、替换、调换任何字、数字、字母、空格或标点。"
        f"每行最多{max_chars}个字（空格和标点不算）。组和组之间的分界不能动。\n"
        "只修正下面这些错误，没有错误的行一个字都不要动：\n"
        "1. 把词语、名字、数字拆开。\n"
        "2. 把动词和宾语拆开（或者是使用｜幸运大转盘）、介词和宾语拆开（我们是通过｜机幕方舟）、"
        "修饰语和中心语拆开（那对我们这套过山车的｜筑梦阿布队）、数量和名词拆开（他带了一个｜什么技能）、"
        "主语和谓语拆开（我们的机幕方舟｜是没有过山车的）、状语和它修饰的动词拆开（而且你其实下一秒｜就已经想到了）。\n"
        "3. 行尾停在要靠下一行才完整的词上：是、的、了、把、被、给、和、跟、因为、但是、如果、就、还、也、可能"
        "（阿布现在是｜80级、我觉得可能｜是第一把）；或下一行以的、了、吗、呢、吧、之后、出来开头。\n"
        "4. 一行里塞了两个各自完整、读起来要停顿的句子，而且合起来读着别扭（这把确实狙了我没看那个）。\n"
        "5. 没有独立意思的一两个字的碎行（应答、语气词、称呼除外）。\n"
        "修正时把这几行重新分好；一句完整的话不超过上限就保持一行，不要为了短而拆，也不要把能独立的小句硬并成接近上限的长行。"
        "字中间的空格是说话的停顿，需要换行时优先在空格处换。\n"
        '只输出JSON对象{"groups":[{"id":整数,"lines":["第一行","第二行"]}]}，每组一项（没有错误的组也原样返回）；无Markdown或解释。')


def enabled(context):
    """True when the task's settings turn the editor on (``switches.grouping_ai_editor``)."""
    settings = getattr(context, 'asr_settings_snapshot', None) or {}
    return bool((settings.get('switches') or {}).get('grouping_ai_editor'))


def lines_to_cuts(quality, start, end, lines):
    """Absolute cuts for ``lines`` covering [start, end), or None when the text differs."""
    from .text_rules import content_exact
    if content_exact(''.join(lines)) != quality.index.content[start:end]:
        return None
    cuts, cursor = [], start
    for line in lines:
        size = len(content_exact(line))
        if not size:
            continue
        cursor += size
        cuts.append(cursor)
    return cuts if cuts and cuts[-1] == end else None


def acceptable(quality, current, candidate, start, end):
    """'' when ``candidate`` may replace ``current`` inside [start, end), else a reason."""
    from .ai_boundary_policy import inspect, indivisible_spans
    confirmed = quality.explicit_word_interiors - quality.required
    new = [x for x in candidate if start < x < end]
    if any(x in confirmed for x in new):
        return 'term_or_number_split'
    allowed = set(getattr(quality, 'allowed', ()) or ())
    if getattr(quality, 'strict_model_boundaries', False) and any(x not in allowed for x in new):
        return 'boundary_not_allowed'
    indivisible = set(indivisible_spans(quality))
    edges = [start, *[x for x in candidate if start < x <= end]]
    for a, b in zip(edges, edges[1:]):
        if b - a > quality.max_chars and (a, b) not in indivisible:
            return 'length'
    hard = lambda cuts: [x for x in inspect(quality, cuts) if start <= x['start'] < end
                         and x['kind'] in {'protected_boundary_missing', 'semantic_boundary'}
                         and x.get('reason') in {None, 'confirmed_term_split', 'boundary_not_allowed'}]
    if len(hard(candidate)) > len(hard(current)):
        return 'hard_issue'
    return ''


def _request(provider, snapshot, quality, groups, cancel_check, batch_index):
    body = dict(prompt_version=PROMPT_VERSION, max_characters=quality.max_chars,
                groups=[dict(id=i, lines=lines) for i, (_a, _b, lines) in groups.items()])
    messages = [dict(role='system', content=system_prompt(quality.max_chars)),
                dict(role='user', content=json.dumps(body, ensure_ascii=False, separators=(',', ':')))]
    characters = sum(len(line) for _a, _b, lines in groups.values() for line in lines)
    response = provider.complete(messages, stage='grouped', operation_kind='group',
                                 batch_index=f'{batch_index}.editor', max_tokens=min(8192, 256+3*characters),
                                 temperature=0., timeout=snapshot.timeout_policy.total,
                                 _timeout_policy=snapshot.timeout_policy, cancel_check=cancel_check,
                                 enable_thinking=False, thinking_protocol=snapshot.thinking_protocol,
                                 response_format={'type': 'json_object'}, json_schema=SCHEMA,
                                 structured_retry_system_prompt=None, structured_retry_max_tokens=())
    raw = str(response or '').strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    data = json.loads(raw)
    return {row['id']: [str(x) for x in row.get('lines') or []] for row in data.get('groups', ())
            if isinstance(row, dict) and type(row.get('id')) is int}


JUDGE_SYSTEM = (
    "你是资深中文字幕编辑。每一对(pair)给出同一段口语的两种字幕分行 A 和 B，每个元素是屏幕上的一条字幕，"
    "文字完全相同，只有换行位置不同。判断哪种分行更好：每条读得顺、意思完整；不把词语、名字、数字、动词和宾语、"
    "介词和宾语、修饰语和中心语、数量和名词、主语和谓语拆开；行尾不停在要靠下一行才完整的词上；不留没意义的碎行；"
    "也不把一句完整的短话拆成两条。两者差不多就回答 same。"
    '只输出JSON对象{"answers":[{"id":整数,"better":"A"或"B"或"same"}]}。')
JUDGE_SCHEMA = {'type': 'object', 'properties': {'answers': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'id': {'type': 'integer'}, 'better': {'type': 'string'}}, 'required': ['id', 'better']}}}, 'required': ['answers']}


def _judge(provider, snapshot, pairs, cancel_check, batch_index):
    """{pair id: 'A'|'B'|'same'} for [(lines_a, lines_b), ...]."""
    body = dict(pairs=[dict(id=i, A=a, B=b) for i, (a, b) in enumerate(pairs)])
    messages = [dict(role='system', content=JUDGE_SYSTEM),
                dict(role='user', content=json.dumps(body, ensure_ascii=False, separators=(',', ':')))]
    response = provider.complete(messages, stage='grouped', operation_kind='group',
                                 batch_index=f'{batch_index}.judge', max_tokens=min(4096, 64+24*len(pairs)),
                                 temperature=0., timeout=snapshot.timeout_policy.total,
                                 _timeout_policy=snapshot.timeout_policy, cancel_check=cancel_check,
                                 enable_thinking=False, thinking_protocol=snapshot.thinking_protocol,
                                 response_format={'type': 'json_object'}, json_schema=JUDGE_SCHEMA,
                                 structured_retry_system_prompt=None, structured_retry_max_tokens=())
    raw = str(response or '').strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    return {row['id']: str(row.get('better') or '') for row in json.loads(raw).get('answers', ())
            if isinstance(row, dict) and type(row.get('id')) is int}


def _hunks(result, candidate, start, end):
    """Independent changed stretches of [start, end): (low, high, new cuts inside)."""
    old = [x for x in result if start < x < end]
    new = [x for x in candidate if start < x < end]
    edges = sorted(set(old) & set(new) | {start, end})
    hunks = []
    for low, high in zip(edges, edges[1:]):
        before = [x for x in old if low < x < high]
        after = [x for x in new if low < x < high]
        if before != after:
            hunks.append((low, high, after))
    return hunks


def _lines(quality, cuts, low, high):
    edges = [low, *[x for x in cuts if low < x < high], high]
    return [quality.index.slice(a, b).strip() for a, b in zip(edges, edges[1:])]


def edit_lines(quality, boundaries, *, provider, snapshot, record=None, batch_index=None,
               cancel_check=lambda: False, rounds=ROUNDS):
    """Boundaries after the editor's rounds.

    A change is kept only when it passes ``acceptable`` and the same model,
    shown the old and new lines blind in both orders, prefers the new lines
    both times (2026-11-22 paid reruns: the editor alone also split good
    lines, and the judge leaned towards whichever answer came first).
    """
    record = record or (lambda *_a, **_k: None)
    result = sorted(set(boundaries) | {quality.total})
    started = time.perf_counter()
    from ..recognition.service import CancelledError

    stats = dict(rounds=0, groups=0, proposed=0, changed=0, rejected={}, failed=0)
    for _round in range(rounds):
        groups = {i: (a, b, [quality.index.slice(p, q) for p, q in zip([a, *[x for x in result if a < x < b]],
                                                                         [x for x in result if a < x <= b])])
                  for i, (a, b) in enumerate(zip(sorted({0, *quality.required}),
                                                 sorted({*quality.required, quality.total})))
                  if b > a}
        groups = {i: g for i, g in groups.items() if g[1] - g[0] > 4 or len(g[2]) > 1}
        if not groups:
            break
        stats['rounds'] += 1
        stats['groups'] += len(groups)
        try:
            answers = _request(provider, snapshot, quality, groups, cancel_check, batch_index)
        except CancelledError:
            raise
        except Exception as exc:
            stats['failed'] += 1
            record('grouping_editor_failed', batch_index=batch_index, error=str(exc)[:200])
            break
        proposals = []
        for i, lines in answers.items():
            if i not in groups:
                continue
            a, b, _before = groups[i]
            cuts = lines_to_cuts(quality, a, b, lines)
            if cuts is None:
                stats['rejected']['text_changed'] = stats['rejected'].get('text_changed', 0) + 1
                continue
            candidate = sorted({x for x in result if not a < x <= b} | set(cuts))
            for low, high, after in _hunks(result, candidate, a, b):
                trial = sorted({x for x in result if not low < x < high} | set(after))
                reason = acceptable(quality, result, trial, low, high)
                if reason:
                    stats['rejected'][reason] = stats['rejected'].get(reason, 0) + 1
                    continue
                # One line of context on each side.
                ctx_low = max([x for x in [0, *result] if x < low], default=0)
                ctx_high = min([x for x in result if x > high], default=quality.total)
                proposals.append((low, high, after, _lines(quality, result, ctx_low, ctx_high),
                                  _lines(quality, trial, ctx_low, ctx_high)))
        stats['proposed'] += len(proposals)
        if not proposals:
            break
        try:
            first = _judge(provider, snapshot, [(p[3], p[4]) for p in proposals], cancel_check, batch_index)
            second = _judge(provider, snapshot, [(p[4], p[3]) for p in proposals], cancel_check, batch_index)
        except CancelledError:
            raise
        except Exception as exc:
            stats['failed'] += 1
            record('grouping_editor_failed', batch_index=batch_index, error=str(exc)[:200])
            break
        changed = 0
        for k, (low, high, after, before_lines, after_lines) in enumerate(proposals):
            if not (first.get(k) == 'B' and second.get(k) == 'A'):
                stats['rejected']['judge'] = stats['rejected'].get('judge', 0) + 1
                continue
            record('grouping_editor_change', batch_index=batch_index, content_start=low, content_end=high,
                   before=before_lines, after=after_lines)
            result = sorted({x for x in result if not low < x < high} | set(after))
            changed += 1
        stats['changed'] += changed
        if not changed:
            break
    record('grouping_editor', batch_index=batch_index, prompt_version=PROMPT_VERSION,
           elapsed_ms=round((time.perf_counter()-started)*1000, 1), **stats)
    return result
