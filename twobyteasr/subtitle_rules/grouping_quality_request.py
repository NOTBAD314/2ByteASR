"""Budgeted request-only source slices and bounded local quality retries."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import threading
import time
from collections import Counter

from .grouping_quality import SourceIndex


def context_text(context, side):
    value = (context or {}).get(side, "")
    if isinstance(value,list):
        value = "".join(str(row.get("text", "")) for row in value)
    return str(value)[-96:] if side=="before" else str(value)[:96]


class QualityRetryBudget:
    """Correction allowance shared by all batches/children in one grouping run.

    2026-11-18: the allowance used to be taken in batch order (a later batch
    waited for every earlier one), so the first batches spent all 16 requests
    and the second half of a long video went straight to local fallback. Each
    batch now has its own fair share of the task allowance, computed from the
    registered batch count, and every request carries all of that batch's
    failed windows. Grants depend only on the batch's own use, so the result
    does not depend on thread completion order. Totals stay capped.
    """

    # 2026-11-22 (崩铁 2-hour job, 40 batches): a 64-request ceiling gave each
    # batch one request; 31 failed ranges were never sent back and kept the ASR
    # sentence. Every batch now has one request per correction round.
    MIN_SHARE = 4       # MAX_QUALITY_ROUNDS: one request per round
    MAX_SHARE = 6       # a short task with one batch never needs more
    MAX_REQUESTS = 400  # absolute ceiling (100 batches × 4 rounds)
    RESERVE_CAP = 1024  # output tokens reserved for one multi-window request

    def __init__(self, *, requests=16, tokens=4096, seconds=600., clock=time.monotonic):
        self.base_requests = int(requests)
        self.base_tokens = int(tokens)
        self.seconds = seconds
        self.clock = clock
        self.started = None
        self.lock = threading.Lock()
        self.order = threading.Condition(self.lock)
        self.pending_batches = set()
        self.registered = set()
        self.used = Counter()
        self.requests_used = 0
        self.tokens_reserved = 0
        self.tokens_used = 0
        self.outcomes = Counter()

    # Limits are derived from the registered batches; a direct caller that
    # never registers is one batch.
    def _batches(self):
        return max(1, len(self.registered))

    @property
    def requests(self):
        base = self.base_requests
        if base <= 0:
            return 0
        if base < self.MIN_SHARE:
            return base
        return min(self.MAX_REQUESTS, max(base, self.MIN_SHARE*self._batches()))

    @property
    def tokens(self):
        return max(self.base_tokens, 256*self.requests) if self.base_tokens > 0 else 0

    def share(self):
        total = self.requests
        if total <= 0:
            return 0
        return max(1, min(self.MAX_SHARE, total//self._batches()))

    def record_outcome(self,outcome):
        with self.lock:
            self.outcomes[outcome]+=1

    def summary(self):
        with self.lock:
            result = dict(self.outcomes)
            result.update(requests_used=self.requests_used, requests_allowed=self.requests,
                          batch_share=self.share(), output_tokens_reserved=self.tokens_reserved,
                          output_tokens_used=self.tokens_used)
            return result

    def register_batches(self, indices):
        with self.order:
            indices = set(indices)
            self.pending_batches.update(indices)
            self.registered.update(indices)

    def finish_batch(self, index):
        with self.order:
            self.pending_batches.discard(index)
            self.order.notify_all()

    def take(self, max_tokens, batch_index=None, *, windows=1):
        """Reserve one request for ``batch_index``; None when nothing is left.

        Returns (output_token_reserve, timeout_seconds). The reason for a
        refusal is in ``refusal_reason(batch_index)``.
        """
        first = str(batch_index).split('.')[0]
        key = first if batch_index is not None else '_'
        with self.lock:
            now = self.clock()
            if self.started is None:
                self.started = now
            remaining = self.seconds-(now-self.started)
            wanted = max(256, 64+48*max(1, int(windows)))
            reserve = min(self.RESERVE_CAP, wanted, int(max_tokens), self.tokens-self.tokens_reserved)
            if (self.requests_used >= self.requests or self._share_exhausted(key)
                    or reserve <= 0 or remaining <= .1):
                return None
            self.used[key] += 1
            self.requests_used += 1
            self.tokens_reserved += reserve
            return reserve, min(6.+1.5*max(1, int(windows)), 24., remaining)

    def _share_exhausted(self, key):
        if self.used[key] < self.share():
            return False
        pending = {str(index).split('.')[0] for index in self.pending_batches} - {key}
        reserved = sum(max(0, self.share() - self.used[other]) for other in pending)
        return self.requests - self.requests_used <= reserved

    def settle(self, reserve, used):
        """Return the unused part of a reservation (reserve vs actual use)."""
        with self.lock:
            used = max(0, min(int(reserve), int(used or 0)))
            self.tokens_used += used
            self.tokens_reserved -= int(reserve)-used

    def refusal_reason(self, batch_index=None):
        first = str(batch_index).split('.')[0]
        key = first if batch_index is not None else '_'
        with self.lock:
            if self.requests <= 0:
                return 'retry_disabled'
            if self.requests_used >= self.requests:
                return 'task_request_limit'
            if self._share_exhausted(key):
                return 'batch_share_reserved_for_pending_batches'
            if self.started is not None and self.seconds-(self.clock()-self.started) <= .1:
                return 'task_time_limit'
            return 'task_token_limit'


def pause_space(text, raw_edge):
    """True when a space separates two Chinese characters at ``raw_edge`` (a marked pause)."""
    import re
    if not 1 < raw_edge < len(text) or text[raw_edge-1] != ' ':
        return False
    before = text[:raw_edge].rstrip(' ')
    return bool(before) and bool(re.match(r'[㐀-鿿]', before[-1])) and bool(re.match(r'[㐀-鿿]', text[raw_edge]))

# Statuses recorded for each owned window (grouping_quality_retry.status and
# the fallback receipt's reason); a window that never got a request is not
# reported as an exhausted retry.
RETRY_STATUSES = ('not_allocated', 'input_budget_conflict', 'request_failed', 'no_answer',
                  'rejected_by_gate', 'unchanged_with_violations', 'unchanged', 'improved')
# 2026-11-22: 16 (was 12) so one request per round still carries a batch's
# windows after dangling-edge checks added more of them.
MAX_WINDOWS_PER_REQUEST = 16


def owned_windows(quality, boundaries, *, advisory=True):
    """Failed neighbourhoods with immutable outer edges, as retry owns them."""
    from .ai_boundary_policy import windows
    result = []
    for left, right in windows(quality, boundaries, advisory=advisory):
        # A single pathological source/model span can itself be huge. Only
        # neighbouring legal word edges within 192 countable units are owned.
        if right-left > 192:
            choices = [x for x in quality.allowed if left < x <= left+192]
            right = choices[-1] if choices else min(right, left+192)
        if left not in {0, *boundaries} or right not in boundaries:
            # Keep the already accepted outer boundaries immutable.
            left = max((x for x in [0, *boundaries] if x <= left), default=0)
            right = min((x for x in boundaries if x >= right), default=quality.total)
        if right-left > 224 or right <= left:
            continue
        if result and left < result[-1][1]:
            result[-1] = (result[-1][0], max(right, result[-1][1]))
        else:
            result.append((left, right))
    return result


def candidate_answer(quality, result, left, right, marks):
    """One rule-scored segmentation of [left, right), offered to the AI as a reference.

    2026-11-22 (real DeepSeek run): after four rounds the model still answered
    现在终于轮到无敌的｜飞飞狐 or 幽默我的｜好学生 and never found 现在终于轮到｜
    无敌的飞飞狐登场啦. Each offered mark gets a penalty from the issues a cut
    there raises (hard 10, advisory 2) on top of a seam cost (punctuation 0,
    before a conjunction/pronoun/time word/preposition .3, inside a word or
    before a complement 3, otherwise 1); the cheapest path with every line
    within the limit wins, each line costs 1 so fewer lines are preferred.
    The AI may adopt it or answer better; its answer is gated as always.
    Returns window-relative boundaries, or None.

    2026-11-22 (user, 1 h stream): the reference joined complete clauses into
    13–14 character lines because every line cost the same and any cut could
    move. Current cuts with no issue of their own now stay fixed; a measured
    clause pause (≥ 0.3 s) is a free seam; a line longer than three quarters
    of the limit costs extra, so an over-long clause is split near its middle
    rather than filled to the limit.
    """
    from .ai_boundary_policy import (inspect, HARD_KINDS, DANGLING_PREPOSITIONS, flagged_edges,
                                     CLAUSE_PAUSE_SECONDS)
    from .grouping_syntax import DIRECTIONAL_COMPLEMENTS, RESULTATIVE_COMPLEMENTS
    RESULT_COMPLEMENTS = DIRECTIONAL_COMPLEMENTS | RESULTATIVE_COMPLEMENTS
    inner = [m for m in marks if left < m < right]
    if not inner or right - left > 192:
        return None
    flagged = flagged_edges(quality, result)
    fixed = {x for x in result if left < x < right and x not in flagged}
    inner = sorted(set(inner) | fixed)
    outside = [x for x in result if not left < x <= right]
    starts = {t['start']: t for t in getattr(quality, 'tagged_tokens', ()) or ()}
    clause = set(getattr(quality, 'clause_edges', ())) | set(getattr(quality, 'source_edges', ()))
    penalty = {}
    for mark in inner:
        issues = [x for x in inspect(quality, sorted(set(outside) | {mark, right}), advisory=True)
                  if x['start'] == x['end'] == mark]
        left_raw = quality.index.text[:quality.index.raw_edges[mark]].rstrip()
        token = starts.get(mark, {})
        # A natural seam is cheap: after punctuation, before a conjunction,
        # a subject pronoun or a time word, or at a clause/source edge.
        raw_edge = quality.index.raw_edges[mark]
        if (left_raw.endswith(('。', '！', '？', '，', '、', '；', '…', '.', '!', '?', ',', ';'))
                or quality.pauses.get(mark, 0.) >= CLAUSE_PAUSE_SECONDS
                or pause_space(quality.index.text, raw_edge)):
            base = 0.
        elif (str(token.get('pos', '')).startswith(('c', 'r', 't')) or mark in clause
              or token.get('text') in DANGLING_PREPOSITIONS):
            base = .3
        elif not token or token.get('text') in RESULT_COMPLEMENTS:
            base = 3.   # inside a tokenizer word, or verb｜complement (轮｜到)
        else:
            base = 1.
        penalty[mark] = base + sum(10 if x['kind'] in HARD_KINDS else 2 for x in issues)
    for cut in fixed:
        penalty[cut] = 0.
    points = [left, *inner, right]
    best = {left: (0., [])}
    roomy = quality.max_chars-2
    for point in points[1:]:
        options = []
        for previous in points:
            if previous >= point or previous not in best or quality.length_cost(previous, point) > quality.max_chars:
                continue
            if any(previous < cut < point for cut in fixed):
                continue  # a fixed cut is never joined over
            cost, path = best[previous]
            cost += 1. + (penalty.get(previous, 0) if previous != left else 0)
            if point - previous <= 2:
                cost += 3
            elif point - previous < 5:
                cost += .5
            if point - previous > roomy:
                cost += .15*(point - previous - roomy)
            options.append((cost, path + [point]))
        if options:
            best[point] = min(options, key=lambda option: (option[0], len(option[1])))
    if right not in best:
        return None
    return [x - left for x in best[right][1]]


def _window_body(quality, result, original, left, right, number, marks=None):
    from .ai_boundary_policy import inspect
    from .segmentation import marked_break_text
    current_issues = inspect(quality, result, advisory=True)
    window_marks = [x-left for x in (marks if marks is not None else quality.allowed) if left < x <= right]
    return dict(id=number, source_text=quality.index.slice(left,right), total_length=right-left,
        marked_text=marked_break_text(quality.index.slice(left,right), [x for x in window_marks if x < right-left]),
        body_range=[left,right],
        read_only_context=dict(before=quality.index.slice(max(0,left-32),left),
                               after=quality.index.slice(right,min(quality.total,right+32))),
        allowed_boundaries=sorted(set(window_marks) | {right-left}),
        required_boundaries=sorted(x-left for x in quality.required if left < x < right),
        preferred_boundaries=sorted(x-left for x in quality.semantic_required if left < x < right),
        illegal_positions=[x-left for x in result if left < x < right and x in quality.forbidden],
        failed_constraints=[dict(x,start=x["start"]-left,end=min(right,x["end"])-left)
                            for x in current_issues if left <= x["start"] < right],
        current_boundaries=[x-left for x in result if left < x <= right],
        current_answer=[quality.index.slice(a,b) for a,b in zip([left,*[x for x in result if left < x < right]],
                                                                [*[x for x in result if left < x < right],right])],
        original_ai_boundaries=[x-left for x in original if left < x <= right])


def _parse_windows(response, bodies):
    """{"windows":[{"id":n,"boundaries":[...]}]} → {id: cuts}; bad rows drop."""
    from .grouping_contract import parse_grouping_response
    raw = str(response or "").lstrip("﻿").strip()
    fence = chr(96)*3
    if raw.startswith(fence) and raw.endswith(fence):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1])
    data = json.loads(raw)
    rows = data.get("windows") if isinstance(data, dict) else None
    if rows is None and isinstance(data, dict) and len(bodies) == 1 and "boundaries" in data:
        rows = [dict(id=bodies[0]["id"], boundaries=data["boundaries"])]
    answers, errors = {}, {}
    by_id = {body["id"]: body for body in bodies}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("id") not in by_id or row["id"] in answers:
            continue
        body = by_id[row["id"]]
        try:
            cuts, _ = parse_grouping_response(json.dumps(dict(boundaries=row.get("boundaries"))),
                                              body["source_text"])
            answers[row["id"]] = list(cuts)
        except Exception as exc:
            errors[row["id"]] = str(exc)[:200]
    return answers, errors


WINDOW_SCHEMA = {
    'type': 'object',
    'properties': {'windows': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'id': {'type': 'integer'}, 'boundaries': {'type': 'array', 'items': {'type': 'integer'}}},
        'required': ['id', 'boundaries']}}},
    'required': ['windows'],
}


from .ai_boundary_policy import DEPENDENT_OPENERS  # noqa: E402 - shared with the advisory check


def correction_regression(quality, before, candidate, left, right):
    """Why a changed window answer is worse than the answer it replaces, or ''.

    2026-11-19 (reported job, 18 corrections all logged "improved"): the gate
    only compared issue counts, so answers that fixed one flagged edge while
    opening a line with a particle (可以翻｜了一千二, 弱兵｜的花衣蝶,
    那不对｜了没事) or turning two lines into five (但是圣剑｜一个涅河｜拖拉机…)
    replaced acceptable model lines. A correction may not open a line with
    such a particle, and may not split the window into more than one extra
    line beyond what its length requires.
    """
    old = {x for x in before if left < x < right}
    new = {x for x in candidate if left < x < right}
    added = new-set(getattr(quality, 'required', ()))-old
    if added.intersection(getattr(quality, "hard_lexical_interiors", ())):
        return 'new_immutable_word_split'
    if getattr(quality, 'strict_model_boundaries', False):
        from .ai_boundary_policy import blocked_evidence_edges
        if added - set(quality.allowed) or added & blocked_evidence_edges(quality):
            return 'new_disallowed_boundary'
    content = quality.index.content
    # Only a line opening with a particle that completes the previous words.
    # Local word/POS sets are not used here: they also flag real fixes
    # (都一直在更新｜记得在主页…, 快速移动｜到上一条…). 的确, 地刺 and 过来
    # open words of their own and stay allowed.
    if any(x < len(content) and content[x] in DEPENDENT_OPENERS and x in quality.awkward
           and x+1 not in getattr(quality, 'known_word_interiors', ())
           for x in added):
        return 'new_syntactic_damage'
    # 2026-11-20 (reported job): the spare line let a 15-character line become
    # 然后知更鸟｜也是从第一期｜开始就有 and 以卡夫卡｜和她的音擎朱退仪｜各一把.
    # A window within its limits may still separate two expressions (看一下｜
    # 风墙), and a tight one may need a spare line to cut at a clause (26
    # characters: 长枪大剑和盾牌各有分工｜而让铁的关键就是敌人｜身上的残痕). A line
    # barely over the limit uses only the lines the limit needs.
    # 2026-11-22 (user, 1 h stream): 47 corrections joined lines that were
    # already within the limit into 13–14 character lines across clause
    # edges (你们别着急｜我跟你说… → 你们别着急我跟你说｜你们别着急这时候罗隐开完古镜｜之后…),
    # each logged "improved". A cut with no issue of its own stays unless the
    # line it joins is short, and a measured clause pause always stays.
    from .ai_boundary_policy import (natural_lines, flagged_edges, length_cost, short_join_limit,
                                     CLAUSE_PAUSE_SECONDS)
    removed = old-new-set(getattr(quality, 'required', ()))
    if removed:
        flagged = flagged_edges(quality, sorted(before))
        edges = [0, *sorted(candidate)]
        for cut in removed - flagged:
            line_start = max(x for x in edges if x < cut)
            line_end = min(x for x in edges if x > cut)
            if (quality.pauses.get(cut, 0.) >= CLAUSE_PAUSE_SECONDS
                    or length_cost(quality, line_start, line_end) > short_join_limit(quality)):
                return 'merged_complete_lines'
    needed = natural_lines(quality, left, right)
    tight = length_cost(quality, left, right)/needed > .75*max(1, int(quality.max_chars))
    spare = 1 if len(old)+1 >= needed or tight else 0
    if len(new)+1 > max(len(old)+1, needed)+spare:
        return 'over_fragmented'
    return ''


def retry_quality_windows(quality, original, local, *, provider, snapshot, schema,
                          budget, record, batch_index=None, source_spans=(), cancel_check=lambda: False,
                          receipts=None, statuses=None):
    """Correct every failed neighbourhood of one batch in as few requests as possible.

    All failed windows of the batch go into one request (split only when the
    request exceeds MAX_WINDOWS_PER_REQUEST or the input budget). A second
    round, within the batch's fair share, sends the windows still failing
    back with the updated constraints. Text outside each window is read-only.
    ``statuses`` (optional dict) receives {(left, right): status}.
    """
    from ..providers.provider_input_budget import prepare_input, InputBudgetError
    from ..providers.asr_provider_snapshot import classify_request_error
    from ..recognition.service import CancelledError
    from .ai_boundary_policy import (inspect, indivisible_spans, snap_offset_errors, break_candidates,
                                     place_on_marks, answer_score, blocked_evidence_edges, HARD_KINDS)
    result = list(local)
    statuses = {} if statuses is None else statuses
    request_number = 0
    exhausted = False
    rejected = {}
    marks = break_candidates(quality)
    guarded_edges = set(quality.hard_lexical_interiors)
    if getattr(quality, 'strict_model_boundaries', False):
        guarded_edges.update(blocked_evidence_edges(quality))
    best = {}   # window -> (score, window cuts) of the best AI answer seen
    shown = set()     # issues already sent to the AI as failed_constraints
    stubborn = set()  # windows where the AI repeated a rejected answer
    for round_number in range(1, MAX_QUALITY_ROUNDS+1):
        targets = [w for w in owned_windows(quality, result)
                   if statuses.get(w) not in {'not_allocated', 'input_budget_conflict'}]
        for window in targets[:]:
            if indivisible_spans(quality, *window) == [window]:
                statuses[window] = 'indivisible_unit'
                targets.remove(window)
        if round_number > 1:
            # A later round sends back a window whose answer failed, or whose
            # current lines have an issue the AI has not been shown yet:
            # 2026-11-22 (real DeepSeek run) an answer that fixed an over-long
            # line but left 无敌的｜飞飞狐 was never sent back. An issue the AI
            # has seen and kept, or a rejected answer it repeated, is its decision.
            current = inspect(quality, result, advisory=True)
            hard_windows = {w for w in targets if any(w[0] <= x['start'] < w[1] and x['kind'] in HARD_KINDS
                                                      for x in current)}
            # A hard issue keeps going back every round (user: AI until it succeeds).
            targets = [w for w in targets if w in hard_windows or w not in stubborn and (
                any(w[0] <= x['start'] < w[1] and _issue_key(x) not in shown for x in current)
                or any(a < w[1] and w[0] < b and status in {'rejected_by_gate', 'no_answer',
                       'request_failed', 'improved_pending'} for (a, b), status in statuses.items()))]
        if not targets or exhausted:
            break
        groups = [targets[i:i+MAX_WINDOWS_PER_REQUEST]
                  for i in range(0, len(targets), MAX_WINDOWS_PER_REQUEST)]
        while groups:
            group = groups.pop(0)
            bodies = [_window_body(quality, result, original, left, right, number, marks)
                      for number, (left, right) in enumerate(group, 1)]
            shown.update(_issue_key(x) for x in inspect(quality, result, advisory=True)
                         if any(left <= x['start'] < right for left, right in group))
            for body, (left, right) in zip(bodies, group):
                body['sources'] = [dict(id=span['id'], speaker=span.get('speaker'),
                    start=span.get('start'), end=span.get('end'),
                    content_start=max(span['content_start'], left) - left,
                    content_end=min(span['content_end'], right) - left)
                    for span in source_spans if span['content_start'] < right and left < span['content_end']]
                body['previous_rejections'] = [failure for (a, b), failure in rejected.items()
                                               if a < right and left < b]
                if round_number > 1:
                    body['read_only_context'] = dict(before=quality.index.slice(max(0, left-64), left),
                        after=quality.index.slice(right, min(quality.total, right+64)))
                    body['rejected_offsets_in_window'] = sorted({failure['body_range'][0] + edge - left
                        for failure in body['previous_rejections'] for edge in failure.get('boundaries') or ()
                        if any(issue.get('start') == issue.get('end') == failure['body_range'][0]+edge
                               for issue in failure.get('issues', ()))})
                body['indivisible_length_conflicts'] = [[a-left, b-left]
                    for a, b in indivisible_spans(quality, left, right)]
                offered = candidate_answer(quality, result, left, right, marks)
                if offered and offered != body['current_boundaries']:
                    offered_full = sorted({x for x in result if not left < x <= right} | {left+x for x in offered})
                    if answer_score(quality, offered_full, left, right) < answer_score(quality, result, left, right):
                        edges = [left, *(left+x for x in offered)]
                        body['reference_answer'] = dict(boundaries=offered, texts=[
                            quality.index.slice(a, b) for a, b in zip(edges, edges[1:])])
            request = dict(index_unit="content_exact_unicode_codepoints",
                           max_characters=quality.max_chars, round=round_number, windows=bodies)
            messages = [dict(role="system", content=(
                "只纠正每个window正文范围内的字幕断点。source_text不可改写，邻文只读。"
                '只返回JSON对象{"windows":[{"id":整数,"boundaries":[整数]}]}，每个window一项。'
                "marked_text是该window的source_text，每个可以换字幕的位置插入了标记‹N›，"
                "N是该window内此位置之前的可计数字符数。boundaries直接抄写所选标记里的数字，不要自己数字数，"
                "严格递增并以total_length结束；没有标记的位置不能换字幕。"
                "保留required_boundaries，不采用illegal_positions和rejected_offsets_in_window。"
                "failed_constraints是当前断点的问题：length超长必须重分；semantic_boundary是词语或依附结构被切开；"
                "dependent_tail是依附前句的短尾巴；dependent_opener是把的、了、吗等依附词放到了下一条开头；"
                "fragmented是这一段碎片太多，只把没有独立意思的短碎片并进相邻的一条。"
                "current_answer里没有出现在failed_constraints中的断点是已经通过的完整小句边界，必须保留；"
                "只有并成的一条不超过" + str(max(1, int(.7*quality.max_chars))) + "字时才可以去掉，"
                "停顿0.3秒以上的断点一律保留。不要为了减少条数把完整小句并成接近上限的长条。"
                "length超长的一条只在这一条内部加断点：优先停顿和完整小句的边界，两段尽量均衡，不必凑满上限。"
                "dangling_edge是行末停在要靠下一条才完整的词上：修饰语的“的”（无敌的｜飞飞狐）、"
                "连词或介词（因为｜、把｜）、量词（一出｜漂亮的）、主语代词（你｜会），或下一条以方位词开头"
                "（吞下｜后）；把这个词和它所属的意群放在同一条。"
                "previous_rejections是你之前在这里被拒绝的答案和原因：over_fragmented是条数超过长度需要，"
                "merged_complete_lines是去掉了已经通过的完整小句边界，"
                "new_syntactic_damage是把依附词放到了下一条开头，semantic_or_length_quality是仍切开词语或仍超长，"
                "repeated_rejected_boundaries是重复了被拒绝的答案。不要再返回被拒绝过的boundaries，换一个完整意群的切法。"
                "reference_answer是本地按规则估算的一种切法（boundaries和对应texts），只供参考："
                "它读起来是完整意群就可以直接采用，有更自然的切法就给你的。"
                f"每条{quality.max_chars}个可计数字符以内，是上限不是目标。"
                "按完整意群选点：不拆词和固定短语，不把动词的宾语、量词后的名词、方位数量短语"
                "（上一条）或连词谓语留到下一条，也不把下一句的开头词挂在上一条末尾。"
                "逗号、连接词和短气口不单独触发切分。current_answer是当前结果，可整体重排本window内的断点。"
                "source_text里两个汉字之间的空格是已标出的句内停顿（相当于逗号），需要换行时优先选在空格处。")),
                dict(role="user", content=json.dumps(request, ensure_ascii=False, separators=(",",":")))]
            try:
                prepare_input(messages, schema=WINDOW_SCHEMA, max_tokens=QualityRetryBudget.RESERVE_CAP,
                              operation="group")
            except InputBudgetError:
                if len(group) > 1:
                    half = len(group)//2
                    groups[:0] = [group[:half], group[half:]]
                    continue
                statuses[group[0]] = 'input_budget_conflict'
                _record_window(record, budget, batch_index, f"{batch_index}.quality-input", group[0],
                               bodies[0], result, result, quality, 'input_budget_conflict',
                               dispatched=False, round_number=round_number)
                continue
            reservation = budget.take(snapshot.max_output_tokens, batch_index=batch_index, windows=len(group))
            if reservation is None:
                reason = budget.refusal_reason(batch_index)
                for window, body in zip(group, bodies):
                    if statuses.get(window) is None:
                        statuses[window] = 'not_allocated'
                    _record_window(record, budget, batch_index, None, window, body, result, result,
                                   quality, statuses[window], dispatched=False, round_number=round_number,
                                   refusal=reason)
                for later in groups:
                    for window in later:
                        statuses.setdefault(window, 'not_allocated')
                exhausted = True
                break
            max_tokens, timeout = reservation
            request_number += 1
            retry_batch_id = f"{batch_index}.quality-{request_number}"
            if cancel_check():
                raise CancelledError("断句纠错已取消。")
            started = time.perf_counter()
            diagnostics, response, answers, errors = {}, "", {}, {}
            failure = None
            record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}', label='断句：局部重试',
                   phase='grouping_quality_retry', state='running', done=0, total=1, batch_index=batch_index)
            try:
                policy = replace(snapshot.timeout_policy, connect=min(timeout,snapshot.timeout_policy.connect),
                    read_idle=min(timeout,snapshot.timeout_policy.read_idle), total=timeout,
                    queue=min(timeout,snapshot.timeout_policy.queue))
                # From the third round a little temperature lets an answer
                # that repeated itself at 0 change; every answer is still gated.
                response = provider.complete(messages, stage="grouped", operation_kind="group",
                    batch_index=retry_batch_id, max_tokens=max_tokens,
                    temperature=0. if round_number < 3 else .4,
                    timeout=timeout, _timeout_policy=policy, request_diagnostics=diagnostics,
                    cancel_check=cancel_check, enable_thinking=snapshot.enable_thinking,
                    thinking_protocol=snapshot.thinking_protocol, response_format={"type":"json_object"},
                    json_schema=WINDOW_SCHEMA, structured_retry_system_prompt=None,
                    structured_retry_max_tokens=())
                answers, errors = _parse_windows(response, bodies)
            except Exception as exc:
                from ..providers.provider_diagnostics import redact_diagnostics
                diagnostics['error'] = redact_diagnostics(str(exc))
                failure = classify_request_error(exc) if not isinstance(exc, (ValueError, TypeError)) else 'parse_failure'
                if failure == "cancelled" or isinstance(exc, CancelledError):
                    record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}',
                           label='断句：局部重试已取消', phase='grouping_quality_retry', state='cancelled',
                           done=0, total=1, batch_index=batch_index)
                    raise
            finally:
                budget.settle(max_tokens, diagnostics.get("completion_tokens") or max_tokens)
            improved_any = False
            for window, body in zip(group, bodies):
                left, right = window
                before = list(result)
                cuts = answers.get(body["id"])
                if failure is not None:
                    status, reason = 'request_failed', failure
                elif cuts is None:
                    status, reason = 'no_answer', errors.get(body["id"], 'window_missing_in_response')
                else:
                    candidate = sorted({x for x in result if not left < x <= right} | {left+x for x in cuts})
                    # A pick between marks goes to the nearest mark; a cut one or
                    # two characters off a word edge is a count miss (2026-11-22).
                    candidate, off_marks = place_on_marks(
                        candidate, marks, left=left, right=right, immutable=guarded_edges)
                    if off_marks:
                        record('grouping_boundary_snapped', batch_index=batch_index, rule='nearest_offered_mark',
                               moves=[dict(model=a, final=b) for a, b in off_marks])
                    candidate, _moves = snap_offset_errors(quality, candidate, left=left, right=right,
                                                           record=record, batch_index=batch_index)
                    # A protected cut the answer dropped is put back, as for the first answer.
                    candidate = sorted(set(candidate) | {x for x in quality.required if left < x < right})
                    window_cuts = [x for x in candidate if left < x <= right]
                    score = answer_score(quality, candidate, left, right)
                    local_issues = [x for x in inspect(quality, candidate, advisory=True)
                                    if left <= x["start"] < right]
                    hard_issues = [x for x in inspect(quality, candidate) if left <= x["start"] < right]
                    old_issues = [x for x in inspect(quality, result, advisory=True) if left <= x["start"] < right]
                    regression = correction_regression(quality, result, candidate, left, right)
                    if not regression and (window not in best or score < best[window][0]):
                        best[window] = (score, window_cuts)
                    previous = rejected.get(window, {})
                    local_candidate = [edge-left for edge in candidate if left < edge <= right]
                    if local_candidate == previous.get('boundaries'):
                        status, reason = 'rejected_by_gate', 'repeated_rejected_boundaries'
                        stubborn.add(window)
                    elif candidate == result:
                        status = 'unchanged_with_violations' if local_issues else 'unchanged'
                        reason = status
                    elif regression:
                        status, reason = 'rejected_by_gate', regression
                    elif (len(hard_issues) > 0 and len(hard_issues) >= sum(x['kind'] in HARD_KINDS for x in old_issues)
                          or len(local_issues) > len(old_issues)
                          and not any(x['kind'] in HARD_KINDS for x in old_issues)):
                        # A changed answer must pass the hard gate and may not
                        # add advisory risks (POS tags can be wrong: 更新/d).
                        status, reason = 'rejected_by_gate', 'semantic_or_length_quality'
                    else:
                        status = 'improved_pending' if hard_issues else 'improved'
                        reason = 'remaining_quality_issues' if hard_issues else 'quality_validated'
                        result = candidate
                        improved_any = True
                        if receipts is not None and not hard_issues:
                            receipts.append(dict(content_start=left, content_end=right,
                                origin='ai_targeted_correction',
                                before=[x for x in before if left < x <= right],
                                after=[x for x in candidate if left < x <= right],
                                retry_batch_id=retry_batch_id))
                if status in {'rejected_by_gate', 'unchanged_with_violations', 'no_answer', 'request_failed'}:
                    rejected[window] = dict(body_range=[left, right], boundaries=cuts, reason=reason,
                        issues=local_issues if cuts is not None and failure is None else [])
                # A previously adopted answer can remain the best answer, while
                # this individual request made no change.
                if not (status in {'unchanged', 'unchanged_with_violations'}
                        and statuses.get(window) in {'improved', 'improved_pending'}):
                    statuses[window] = status
                _record_window(record, budget, batch_index, retry_batch_id, window, body, before, result,
                               quality, status, dispatched=True, round_number=round_number, reason=reason,
                               elapsed=time.perf_counter()-started, response=response, diagnostics=diagnostics,
                               reserve=max_tokens, candidate=None if cuts is None else
                               sorted({x for x in before if not left < x <= right} | {left+x for x in cuts}))
            record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}',
                   label='断句：局部重试有改善' if improved_any else '断句：局部重试未变化',
                   phase='grouping_quality_retry', state='completed', done=1, total=1,
                   batch_index=batch_index, windows=len(group),
                   review_required=bool(inspect(quality, result)), request_dispatched=True)
    # After its rounds the AI's best answer stands wherever it beats what is
    # there; the ASR sentence is no longer the fallback (user, 2026-11-22).
    for (left, right), (score, window_cuts) in sorted(best.items()):
        if statuses.get((left, right)) == 'improved' or left not in {0, *result} or right not in result:
            continue
        candidate = sorted({x for x in result if not left < x <= right} | set(window_cuts))
        if (candidate == result or correction_regression(quality, result, candidate, left, right)
                or score >= answer_score(quality, result, left, right)):
            continue
        before = [x for x in result if left < x <= right]
        result = candidate
        statuses[(left, right)] = 'ai_best_answer'
        if receipts is not None:
            receipts.append(dict(content_start=left, content_end=right, origin='ai_targeted_correction',
                                 before=before, after=window_cuts, retry_batch_id=f'{batch_index}.best'))
        record('grouping_ai_best_answer', batch_index=batch_index, content_start=left, content_end=right,
               before=before, after=window_cuts, score=list(score))
    return result


def _issue_key(issue):
    return (issue['kind'], issue.get('reason'), issue['start'], issue['end'])


# 2026-11-22 (user: failed ranges go back to the AI until they succeed): two
# rounds left 196 ranges on the ASR sentence. Each round is one request per
# batch carrying all of its failing windows.
MAX_QUALITY_ROUNDS = 4


def _record_window(record, budget, batch_index, retry_batch_id, window, body, before, after, quality,
                   status, *, dispatched, round_number, reason=None, refusal=None, elapsed=0.,
                   response="", diagnostics=None, reserve=0, candidate=None):
    from .ai_boundary_policy import inspect
    left, right = window
    diagnostics = diagnostics or {}
    old_positions = [x for x in before if left < x <= right]
    new_positions = [x for x in after if left < x <= right]
    changed = old_positions != new_positions
    if not changed and status in {'improved', 'improved_pending'}:
        status = 'unchanged_with_violations' if reason == 'unchanged_with_violations' else 'unchanged'
    outcome = {'improved': 'improved', 'improved_pending': 'improved_pending', 'unchanged': 'unchanged',
               'unchanged_with_violations': 'unchanged_with_violations'}.get(status, 'rejected')
    if dispatched:
        budget.record_outcome(outcome)
    else:
        budget.record_outcome(status)
    candidate = before if candidate is None else candidate
    from hashlib import sha256
    from .grouping_quality import QUALITY_VERSION
    record("grouping_quality_retry", batch_index=batch_index, rule="bounded_ai_quality_correction",
        policy=QUALITY_VERSION, index_unit="content_exact_unicode_codepoints",
        source_text_sha256=sha256(quality.index.text.encode("utf-8")).hexdigest(),
        retry_batch_id=retry_batch_id, parent_batch_id=batch_index, request_dispatched=dispatched,
        round=round_number, window_id=body.get("id"), status=status, budget_refusal=refusal,
        content_start=left, content_end=right, original_boundaries=body["current_boundaries"],
        candidate_boundaries=[x-left for x in candidate if left < x <= right],
        old_positions=old_positions, new_positions=new_positions,
        before=list(body["current_answer"]),
        after=[quality.index.slice(a,b) for a,b in zip([left,*[x for x in after if left < x < right]],
               [*[x for x in after if left < x < right],right])],
        accepted=changed and status in {'improved', 'improved_pending'},
        improved=changed and status in {'improved', 'improved_pending'}, outcome=outcome,
        review_required=bool([x for x in inspect(quality, after, advisory=True) if left <= x["start"] < right]),
        reason=reason or status, output_token_reserve=reserve,
        elapsed_ms=round(elapsed*1000,3), response_length=len(response or ""),
        finish_reason=diagnostics.get("finish_reason"), error=diagnostics.get('error'),
        completion_tokens=diagnostics.get("completion_tokens"))


def split_request_source(segment, build_messages, *, schema, max_tokens, tokens=(),
                         global_start=0, context_before="", context_after=""):
    """Slice a singleton only after its actual serialized request fails budget.

    Each child retains source identity, global countable and raw spans, words,
    speaker and source-seconds. Context is outside the owned body. The caller
    reconciles the request seams against the original full source afterwards.
    """
    from .grouping_quality import quality_for_segments
    from ..providers.provider_input_budget import prepare_input, InputBudgetError
    quality = quality_for_segments([segment],tokens)
    index = quality.index
    children = []
    start = 0

    def child_at(left,right):
        child = copy.copy(segment)
        child.caption_arbitration = dict(segment.caption_arbitration)
        child.segment_id = f"{segment.segment_id}@{left}:{right}"
        child.text = index.slice(left,right)
        child.start = max(segment.start, quality.units[left].start)
        child.end = min(segment.end, max(child.start+.001,quality.units[right-1].end))
        # Preserve existing valid observations, never manufacture word evidence
        # from the display estimates used to determine the coarse envelope.
        child.words = [w for w in child.words if child.start <= w.start < w.end <= child.end+.001]
        child.caption_arbitration["grouping_request_source"] = dict(
            source_id=segment.segment_id, content_start=left,content_end=right,
            global_content_start=global_start+left, global_content_end=global_start+right,
            raw_start=index.raw_edges[left],raw_end=index.raw_edges[right],
            source_start=segment.start,source_end=segment.end,
            original_text=segment.text, time_domain="source_seconds",
            index_unit="content_exact_unicode_codepoints")
        child.caption_arbitration["grouping_read_only_context"] = dict(
            before=(context_before+index.slice(max(0,left-32),left))[-96:],
            after=(index.slice(right,min(quality.total,right+32))+context_after)[:96])
        child.caption_arbitration["grouping_request_allowed"] = sorted({right-left} | {
            x-left for x in quality.allowed if left < x < right})
        return child

    while start < quality.total:
        low, high = start+1, quality.total
        fitting = start
        while low <= high:
            middle = (low+high)//2
            child = child_at(start,middle)
            try:
                prepare_input(build_messages([child]), schema=schema,
                              max_tokens=max_tokens, operation="group")
                fitting, low = middle, middle+1
            except InputBudgetError:
                high = middle-1
        if fitting <= start:
            raise ValueError("请求固定协议和最小正文仍超过输入预算。")
        legal = [x for x in quality.allowed if start < x <= fitting]
        if fitting == quality.total:
            end = fitting
        elif legal:
            # Prefer a nearby actual pause/phrase boundary, without allowing
            # an attractive distant pause to waste most of the request budget.
            near = [x for x in legal if x >= max(start+1,fitting-64)] or legal[-1:]
            end = max(near,key=lambda x:(quality.pauses.get(x,0.)*60+
                (8 if x in quality.restarts else 0)-(5 if x in quality.awkward else 0)-.1*(fitting-x)))
        else:
            # An indivisible name may exceed the request budget itself. It is
            # still submitted in owned request pieces; the seam is not adopted
            # as a subtitle cut and the final quality gate reports its conflict.
            end = fitting
        child = child_at(start,end)
        # Check again including the exact final context and mapping overhead.
        prepare_input(build_messages([child]),schema=schema,max_tokens=max_tokens,operation="group")
        children.append(child)
        start = end
    if "".join(c.text for c in children) != segment.text:
        raise ValueError("请求切块未完整重建原始正文。")
    return children
