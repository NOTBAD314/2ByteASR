"""AI pause spaces inside Chinese source sentences, before line breaking (2026-11-22).

User (1 h 洛克王国 stream): "能自然的加上空格或逗号吗". The online recognizer
returns long sentences without inner punctuation, so a subtitle such as
可以可以可以不对来吧没问题的 has no visible pause, and the line breaker has no
clause edges to cut at (估计这把不能靠｜阿布了…).

Before grouping, the grouping model punctuates each corrected source sentence
without changing a character; every mark it puts inside becomes a plain
space. A stretch still longer than a line (14) is sent once more, asking for
the comma a subtitle can break at. Paid reruns of the reported stream
(DeepSeek v4 flash, 2026-11-22): picking numbered marks put a pause at almost
every word gap; punctuating gave natural ones (估计这把不能靠阿布了，得靠那个
迪莫了), and about 93% of the resulting lines needed no change. The rest
of the pipeline already treats a space between two Chinese characters as a
pause: the 添加标点 style shows it as ，, the other styles as a space, and the
line breaker counts only content characters, so text, numbers and timing are
unchanged. The same marks are free seams for the line breaker's reference cut.

Only gaps between two whole words are offered; nothing inside a word, a
number, a confirmed term, or before 的/了/吗/呢/吧/啊-style particles. A failed
or malformed answer leaves the sentence as it was.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

PROMPT_VERSION = 'zh-pause-spaces-v4-punctuate-split-long'
MAX_STRETCH = 14     # the line limit: a longer unpunctuated stretch gets a second request
MIN_CHARS = 6          # shorter sentences are read in one breath
MIN_SIDE = 1
BATCH_ROWS = 40
WORKERS = 6
_CJK = re.compile(r'[㐀-鿿]')
# A comma never goes before these (的确/得靠 start with the same characters but are
# whole words, so the word check decides those).
_PARTICLES = frozenset('的了吗呢吧啊呀嘛么啦')
_WORD_STARTS = frozenset({'的确', '了解', '了不', '吧台', '啊呀'})
PAUSE_MARKS = frozenset('，、；：。！？,;:!?…')

SCHEMA = {'type': 'object', 'properties': {'lines': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'id': {'type': 'integer'}, 'text': {'type': 'string'}}, 'required': ['id', 'text']}}}, 'required': ['lines']}

# 2026-11-22 v2: picking numbered marks, the model marked almost every word
# gap (好那 这里 我们 还地 刺去 阻止). Punctuating the sentence is a task it
# does naturally; only the marks it puts inside become pauses.
SYSTEM = (
    "给下面每行中文口语字幕加上自然的标点（逗号、顿号、问号、感叹号、句号），像正式字幕那样断句。"
    "一字不改：不得增删、替换或调换任何字、数字、字母和空格，只插入标点。"
    "一口气说完的短句不要硬加逗号；两个完整小句之间、应答或语气词之后、称呼之后加逗号。"

    '只输出JSON对象{"lines":[{"id":整数,"text":"加好标点的整行"}]}，每行一项；无Markdown或解释。')


def candidate_marks(text):
    """Content offsets where a pause space may go in ``text``."""
    from .grouping_quality import SourceIndex
    from .segmentation import boundary_word_spans, lexical_forbidden_boundary_offsets
    from .text_rules import content_exact
    index = SourceIndex.build(text)
    content = index.content
    if len(content) < MIN_CHARS:
        return []
    inside = set(lexical_forbidden_boundary_offsets(text))
    for left, right, _word in boundary_word_spans(content_exact(text)):
        inside.update(range(left+1, right))
    marks = []
    for offset in range(MIN_SIDE, len(content)-MIN_SIDE+1):
        if offset in inside or content[offset] in _PARTICLES and content[offset:offset+2] not in _WORD_STARTS:
            continue
        raw = index.raw_edges[offset]
        if raw <= 0 or raw >= len(text) or not (_CJK.match(text[raw-1]) and _CJK.match(text[raw])):
            continue  # an existing space, punctuation, digits or Latin there
        marks.append(offset)
    return marks


def apply_pauses(text, pauses, marks=None):
    """Insert one space at each accepted content offset; returns the new text."""
    from .grouping_quality import SourceIndex
    marks = set(candidate_marks(text) if marks is None else marks)
    index = SourceIndex.build(text)
    chosen, last = [], -MIN_SIDE
    for offset in sorted({int(x) for x in pauses if type(x) is int or str(x).isdigit()}):
        if offset in marks and offset - last >= MIN_SIDE and len(index.content) - offset >= MIN_SIDE:
            chosen.append(offset)
            last = offset
    out = text
    for offset in reversed(chosen):
        raw = index.raw_edges[offset]
        out = out[:raw] + ' ' + out[raw:]
    return out, chosen


SPLIT_SYSTEM = (
    "下面每段口语超过14个字，字幕一条放不下。在最自然、读起来最顺的位置插入逗号，把它分成每段不超过14个字的几段。"
    "好的位置：小句之间、句首状语或连词之后、较长的主语之后、应答或语气词之后。"
    "不能放在动词和宾语、介词和宾语、修饰语和中心语、数量和名词、主语和紧跟的单字谓语之间。"
    "一字不改：不得增删、替换或调换任何字、数字、字母和空格，只插入逗号。"
    '只输出JSON对象{"lines":[{"id":整数,"text":"插好逗号的整段"}]}，每段一项；无Markdown或解释。')


def _request(provider, snapshot, rows, cancel_check, system=SYSTEM):
    body = dict(prompt_version=PROMPT_VERSION, lines=rows)
    messages = [dict(role='system', content=system),
                dict(role='user', content=json.dumps(body, ensure_ascii=False, separators=(',', ':')))]
    response = provider.complete(messages, stage='grouped', operation_kind='group', batch_index='pauses',
                                 max_tokens=min(8192, 128+3*sum(len(r['text']) for r in rows)), temperature=0.,
                                 timeout=snapshot.timeout_policy.total, _timeout_policy=snapshot.timeout_policy,
                                 cancel_check=cancel_check, enable_thinking=False,
                                 thinking_protocol=snapshot.thinking_protocol,
                                 response_format={'type': 'json_object'}, json_schema=SCHEMA,
                                 structured_retry_system_prompt=None, structured_retry_max_tokens=())
    raw = str(response or '').strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    data = json.loads(raw)
    return {row['id']: str(row.get('text') or '') for row in data.get('lines', ())
            if isinstance(row, dict) and type(row.get('id')) is int}


def pauses_from_punctuated(original, punctuated):
    """Content offsets where ``punctuated`` put a mark between two content characters.

    None when the answer changed any counted character (the sentence stays as it was).
    """
    from .text_rules import content_exact
    if content_exact(punctuated) != content_exact(original):
        return None
    offsets, count, pending = [], 0, False
    for char in punctuated:
        if content_exact(char):
            if pending and count:
                offsets.append(count)
            pending = False
            count += 1
        elif char in PAUSE_MARKS:
            pending = True
    return offsets


def mark_pause_spaces(segments, snapshot, *, record=None, cancel_check=lambda: False, provider=None):
    """New segment list with AI pause spaces; segments that fail stay unchanged."""
    import copy
    from ..providers.ai_providers import provider_for_stage
    from ..providers.llm_adapter import post_chat_completion
    from ..recognition.service import CancelledError

    def check_cancelled():
        if cancel_check():
            raise CancelledError('字幕停顿标记已取消。')

    check_cancelled()
    record = record or (lambda *_a, **_k: None)
    provider = provider or provider_for_stage(snapshot.execution_settings(), 'group', sender=post_chat_completion)
    jobs, marks_of = [], {}
    for index, segment in enumerate(segments):
        marks = candidate_marks(segment.text)
        if marks:
            marks_of[index] = marks
            jobs.append(dict(id=index, text=segment.text))
    batches = [jobs[i:i+BATCH_ROWS] for i in range(0, len(jobs), BATCH_ROWS)]
    answers, failures = {}, 0
    started = time.perf_counter()

    def run(batch):
        check_cancelled()
        try:
            return _request(provider, snapshot, batch, cancel_check), None
        except CancelledError:
            raise
        except Exception as exc:  # the sentences of this batch stay as they were
            return {}, str(exc)[:200]

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(batches)))) as pool:
        for found, error in pool.map(run, batches):
            answers.update(found)
            failures += bool(error)
    chosen_of = {}
    for index in marks_of:
        offsets = pauses_from_punctuated(segments[index].text, answers[index]) if index in answers else None
        if offsets is not None:
            chosen_of[index] = sorted(set(offsets) & set(marks_of[index]))
    # Second round: stretches still longer than a line, asked one by one for
    # the comma a subtitle can break at (我觉得可能是第一把赢的太顺利了啊).
    from .grouping_quality import SourceIndex
    long_jobs, owners = [], {}
    for index, chosen in chosen_of.items():
        index_text = SourceIndex.build(segments[index].text)
        edges = [0, *chosen, len(index_text.content)]
        for left, right in zip(edges, edges[1:]):
            if right - left > MAX_STRETCH and any(left < m < right for m in marks_of[index]):
                job_id = len(long_jobs)
                owners[job_id] = (index, left, right)
                long_jobs.append(dict(id=job_id, text=index_text.slice(left, right).strip()))
    split_batches = [long_jobs[i:i+BATCH_ROWS] for i in range(0, len(long_jobs), BATCH_ROWS)]

    def run_split(batch):
        check_cancelled()
        try:
            return _request(provider, snapshot, batch, cancel_check, SPLIT_SYSTEM), None
        except CancelledError:
            raise
        except Exception as exc:
            return {}, str(exc)[:200]

    split_answers = {}
    if split_batches:
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(split_batches))) as pool:
            for found, error in pool.map(run_split, split_batches):
                split_answers.update(found)
                failures += bool(error)
    check_cancelled()
    split_added = 0
    for job_id, answer in split_answers.items():
        if job_id not in owners:
            continue
        index, left, right = owners[job_id]
        piece = long_jobs[job_id]['text']
        offsets = pauses_from_punctuated(piece, answer) or ()
        added = {left + x for x in offsets} & set(marks_of[index])
        split_added += len(added - set(chosen_of[index]))
        chosen_of[index] = sorted(set(chosen_of[index]) | added)
    result, inserted, lines = [], 0, 0
    for index, segment in enumerate(segments):
        if chosen_of.get(index):
            text, chosen = apply_pauses(segment.text, chosen_of[index], marks_of[index])
            if chosen:
                old = segment.text
                segment = copy.copy(segment)
                segment.text = text
                if getattr(segment, 'final_text', None) == old:
                    segment.final_text = text
                inserted += len(chosen)
                lines += 1
        result.append(segment)
    record('pause_marks_applied', prompt_version=PROMPT_VERSION, sentences=len(segments),
           offered=len(jobs), requests=len(batches), failed_requests=failures, sentences_changed=lines,
           pauses=inserted, long_stretches=len(long_jobs), split_pauses=split_added, elapsed_ms=round((time.perf_counter()-started)*1000, 1))
    return result
